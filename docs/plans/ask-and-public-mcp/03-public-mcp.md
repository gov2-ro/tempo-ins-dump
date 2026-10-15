# AT-03: Public read-only MCP

## Problem and ownership

**AT-03: pending.** Add a public, bounded MCP interface over AT-01 so visitors can
use supported chat clients without supplying a model key to INS+. This is a data
server: the client model chooses tools and synthesizes answers. Do not proxy Ask,
invoke `run_agent` or request client-side model sampling inside a public tool.

Primary ownership: a new focused public-MCP adapter under `app/`, startup/config,
runtime requirements, Docker/release smoke and transport tests. Preserve
`tools/tempo-dev-mcp/server.py` as a separate local development server. It is
stdio-only today, includes endpoint/log/pipeline/eval introspection, and is not
copied into the image. Do not mount/import it or re-export its decorated tools.

## Transport and allowed capabilities

### Endpoint and startup

- New canonical public endpoint: **`/mcp`**, HTTPS externally through Fly. The
  application can serve it on its existing internal HTTP port. Test the exact
  externally advertised path; avoid accidental `/mcp/mcp` or mandatory redirects.
- Use official MCP Python SDK Streamable HTTP, initially stateless request/
  response operation with JSON responses where the SDK supports it. Let SDK
  negotiation determine supported protocol versions; do not hard-code a new
  protocol version without testing the actual clients.
- Default `TEMPO_MCP_ENABLED=false`. Disabled: initialization, tools/list and
  calls all get 404, including trailing-path variants. Enabled MCP does not
  enable either hosted Ask, BYOK Ask, debug mode or dev MCP.
- Mount before FastAPI's catch-all static mount. Integrate the MCP session
  manager into the parent application's lifespan and shutdown. A mounted
  sub-app's lifespan alone is insufficient. Preserve health/API/static routes.
- The alpha checkout pins `mcp==1.27.0` in dev requirements only. Make the tested
  SDK a pinned runtime dependency if MCP ships in the image, reconcile dev
  requirements, and test clean-install Docker behavior. Prefer compatible v1
  integration; a v2 migration is not required. Do not paste v2 `MCPServer`
  constructor examples into v1 `FastMCP` code.
- Current v1/v2 differences and lifespan requirements are documented in the
  [official Python SDK](https://github.com/modelcontextprotocol/python-sdk).
  Confirm the selected installed version's API in source/tests, not only the
  changing default branch examples.

### Public tool surface

`tools/list` exposes **exactly** the seven AT-00 names with typed input schemas,
output schemas, readable descriptions and read-only annotations. Prefer canonical
objects over legacy JSON strings. Set `readOnlyHint=true`,
`destructiveHint=false`, `idempotentHint=true`; the idempotence means the call has
no user-data mutation, not that live data will never change. Tools read the
closed corpus and return links; no arbitrary external URL fetch is available.

Return the identical `tempo-tools/1` envelope in `structuredContent` and a
serialized text fallback for clients needing it. Keep the logical 32 KiB budget;
the complete MCP wire response, including both representations, must be at most
**72 KiB**. Do not put bulk tables in a separate content block to evade the cap.
Measure the encoded wire response: escaping the text fallback can expand it
beyond twice the logical JSON size. Reduce optional previews further or return
`response_budget` if the required content cannot fit.
Use SDK-supported error mapping as defined by AT-00.

No public tools for: general endpoint dispatch, SQL, code execution, file/log
reads, environment/process details, pipeline mutation, eval/baseline rebuild,
provider calls, MCP sampling/elicitation of model keys, or arbitrary downloads.
Protocol lifecycle requests (initialize/ping/list/call) use the SDK, not a new
handwritten JSON-RPC implementation. Unsupported protocol capabilities stay off.

### Anonymous access and links

V1 serves public statistics anonymously. Advertise anonymous/no-auth tool access
where required by clients; do not require a model API key, a shared secret in a
setup URL, or a fabricated OAuth flow. This does not make traffic authenticated
or per-person quotas reliable. Optional accounts/personal features are a later
design, not an accidental promise of this endpoint.

Configure `TEMPO_PUBLIC_BASE_URL` to the trusted HTTPS origin used for citations,
downloads and evidence. For an enabled public deployment, missing/invalid base
URL fails startup clearly. Allow a localhost origin only for explicit local test
configuration. Never derive security-sensitive links from arbitrary Host or
forwarded headers. Do not fetch a provided callback URL.

MCP clients may connect from their provider's cloud; a user's browser IP is not
the authenticated end-user identity. Make no per-user entitlement claims from
IP, user-agent, session id or arbitrary client metadata.

## Resource and access controls

### Initial configuration

Names below are part of the proposed configuration contract; document any
necessary rename consistently in tests/setup/release records.

| Setting | Initial default | Meaning |
|---|---:|---|
| `TEMPO_MCP_ENABLED` | false | Public endpoint exposure switch |
| `TEMPO_PUBLIC_BASE_URL` | unset | Required trusted origin for enabled public deployment |
| `TEMPO_MCP_MAX_BODY_BYTES` | 65,536 | Entire HTTP request body, enforced before parsing/DB access |
| `TEMPO_MCP_MAX_CONCURRENT` | 1 | Actual analytical tool operations in flight per worker |
| `TEMPO_MCP_MAX_SECONDS` | 10 | Deadline for one complete tool operation |
| `TEMPO_MCP_MAX_CALLS_PER_MINUTE` | 120 | Aggregate tools/call admission budget, not per-user quota |
| `TEMPO_MCP_MAX_SCAN_ROWS` | 1,000,000 | Estimated selected input rows per analytical operation |
| `TEMPO_MCP_CACHE_BYTES` | 4,194,304 | Maximum bounded serialized-result cache memory |
| `TEMPO_MCP_ALLOWED_HOSTS` | explicit deployment/local hosts | Host validation |
| `TEMPO_MCP_ALLOWED_ORIGINS` | explicit approved origins | Origin validation when the header is present |

Validate numeric settings and fail on impossible/negative production values;
do not silently interpret zero as unlimited. Initialization/list metadata also
need bounded body/work and inexpensive request throttling; they cannot create
unbounded sessions/threads or monopolize the worker while calls are busy.

One million scan rows is an initial conservative admission threshold, not a
claim all useful population queries fit it. Estimate the selected scope from
Parquet metadata, actual partition statistics and filters where feasible. A
full-file metadata upper bound is acceptable; an unbounded preliminary COUNT
to decide whether a query is too expensive is not. Unknown/unbounded estimates
are refused unless a precomputed, generation-bound result is available. Raising
the threshold requires the resource/load evidence in AT-04.

### Execution, cancellation and caches

- Acquire the analytical slot before DB work, with no unbounded wait queue. A
  busy response contains a retry delay (HTTP 429/503 or the documented tool
  envelope according to the stage reached). Protocol metadata remains available.
- Give each operation its own cursor; close it and release the slot in `finally`.
  Recipes/change tools may perform several reads inside that one admitted
  operation; nested acquisition must not deadlock or silently bypass the budget.
- Count cumulative source estimates for multi-source recipes and endpoint reads.
  A result row cap does not cap input scan cost. Large cached/precomputed
  answers can be served only with the same generation, semantic verdict and
  provenance; do not cache an unchecked sum just because it is fast.
- Enforce a wall-clock query deadline by cancellation/interruption of the owned
  work. Cancelling a Python Future/HTTP response alone does not stop DuckDB.
  Keep admission occupied until the underlying execution actually stops. Test
  isolation from another cursor and prevent background-thread accumulation.
- Bound cache entries as well as bytes, e.g. 128 entries and 5-minute TTL. Keys
  include contract, generation, normalized selection, language and relevant
  policy/config version. Cache only envelopes/compact metadata, not unbounded
  observations; don't cache failures across generations or retain credentials.
  Missing/stale generation disables certification/cached analytical success.
- This per-worker gate does not bound the entire deployment. Document one worker
  for the first release and account for concurrent REST, exports, Ask and search
  in mixed-load measurement. Do not claim a globally bounded quota across
  multiple workers/Machines without shared coordination.

### HTTP trust boundaries

Validate Host and Origin using SDK transport security and deployment settings.
An absent Origin may be legitimate for server-to-server clients; an unapproved
present Origin is rejected before tool execution. CORS is not authentication.
Do not let the app's broad development CORS configuration override the MCP
policy. Reject oversized bodies, invalid content types/protocol payloads and
unexpected paths without exposing internals. Never trust client-supplied hints
as permission to run a privileged tool.

## Deployment and rollback

Keep the existing Fly web app/data snapshot architecture for v1; a second Machine
or service is not required just to add MCP. Use the same deployed generation.
The static artifact cannot host this dynamic endpoint and should link to the
configured Fly origin if onboarding is added there.

Add a small health capability summary: MCP enabled, contract version and
generation status, without secrets, internal paths, request contents or client
identifiers. Keep existing health meanings compatible. Include MCP initialization
and one fixture/read-only tool call in image smoke tests. Environment flags must
be tested in fresh application instances; module-import state must not leak
between tests.

The existing 512 MiB Fly setup has not passed its Linux resource gate. AT-03 code
completion does not clear that gate. Do not provision more RAM, enable production
MCP, add keys or deploy as part of implementation. Produce a container/local
candidate and AT-04 measurements/recommendation first.

Rollback: disable `TEMPO_MCP_ENABLED` and confirm `/mcp` is unavailable while the
web/API remain healthy. A previous image/config rollback is secondary; never
restore a query path that bypasses aggregation or grain policy. No corpus
migration or regeneration is needed for this adapter package.

## Acceptance checks

1. Real SDK client initializes, lists exactly seven tools, validates schemas and
   calls each on a synthetic generation over Streamable HTTP. Test application
   startup/shutdown/lifespan and the advertised `/mcp` path, not only handlers.
2. Disabled endpoint is 404 for initialize/list/call; both Ask switches remain
   independent. Clean runtime dependency install works without dev packages.
3. Service/Ask/MCP numerical, refusal, scope, completeness and generation parity
   pass. `structuredContent` equals the parsed fallback; both validate and fit
   their byte budgets, including Romanian non-ASCII text.
4. Bad Host/Origin, oversized body/arguments, unknown tools/columns and adversarial
   literal values cannot reach privileged behavior. Existing SQL-binding and
   query-validation tests still pass; responses reveal no paths/SQL/secrets.
5. Slow operation, overload, client disconnect and failed query release resources
   only after actual execution ends. Test cache byte/entry/TTL/generation
   invalidation and scan refusal without an expensive pre-count.
6. Patch `run_agent`/LLM client/provider network calls to fail if invoked; all
   seven tools still work with every model API key unset. No `sampling/createMessage`
   request is sent to the client. This establishes the no-server-model-call
   property underlying the operator's model-cost expectation.
7. Image smoke, representative web/API pages and static parity remain passing.
   Live ChatGPT/Claude interoperability and Fly load are recorded under AT-04,
   not claimed from local SDK mocks.

