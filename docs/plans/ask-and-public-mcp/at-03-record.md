# AT-03 completion record: public read-only MCP

**Status (2026-10-16): implemented and verified locally on branch `at/02-ask-runtime`
(committed after AT-02, sequentially).** Owner review pending. Not pushed, not merged, not
deployed, **disabled by default**. No live ChatGPT/Claude client, Fly load or Docker image run
was done: those are AT-04 and the release gate.

| | |
|---|---|
| Baseline | AT-02 head 2f31637 |
| Code | c9586a2 (`feat(mcp): public read-only MCP over the shared tools, off by default (AT-03)`); the record follows |
| SDK | `mcp==1.27.0`, now a pinned runtime dependency (imported only when the endpoint is enabled) |
| Corpus / tables changed | none |

## What was built

`app/services/public_mcp.py` plus the wiring in `app/main.py`.

- **Transport.** The SDK's Streamable HTTP, stateless, JSON responses, at exactly **`/mcp`**. The
  low-level `Server` is used (not `FastMCP`) so the tool schemas are the registry's own. A route at
  `/mcp` and a catch-all `/mcp/{rest}` (404) are inserted before the static catch-all: no `/mcp/mcp`,
  no redirect. The session manager runs in the parent app's lifespan. Only POST is served (GET 405,
  because there are no sessions or server-sent streams); OPTIONS answers a preflight for approved
  origins only.
- **Tools.** `tools/list` is exactly the seven AT-00 tools, in registry order, with title, description,
  inlined input and output JSON Schemas (no `$ref`, `$defs` or `discriminator`) and
  `readOnlyHint=true`, `destructiveHint=false`, `idempotentHint=true`, `openWorldHint=false`. Every call
  runs `registry.call_tool`; the envelope is `structuredContent` and, identically, the text fallback
  (compact JSON, UTF-8). `isError` is true only for `status: error`; refusals and clarifications are
  ordinary results. The server never calls a model, requests sampling or elicitation, runs SQL or code,
  reads files or logs, or dispatches to other endpoints (checked by an AST test and with every provider
  patched to fail and no key set).
- **Wire budget.** The complete JSON-RPC response (both representations) is at most 72 KiB. The
  optional preview is shortened first through the tool's own hook; if the required content cannot fit,
  `response_budget` with no data and a request hash.
- **Switch.** `TEMPO_MCP_ENABLED` (default false). Disabled: 404 for every method on `/mcp`, `/mcp/`,
  `/mcp/mcp` and any subpath, and `app.state.public_mcp` is `None`. Settings are read when the app is
  built (`McpSettings.from_env`), never at import, so a fresh app sees its own flags. The Ask switches
  are independent in both directions.
- **Trust boundaries.** Body size (declared and streamed) is checked before the SDK parses anything.
  Host (421) and Origin (403) are checked by the SDK transport before any tool runs; an absent Origin
  is allowed (server-to-server clients). The app's development CORS (`*`) is carved out for `/mcp`
  (`_CorsExceptMcp`); approved origins get their own `Access-Control-Allow-Origin`. Content type must
  be JSON. CORS is not treated as authentication.
- **Execution gate** (`Gate`): precheck (`registry.precheck`: unknown tool, non-JSON, over 16 KiB or
  schema failure answer at once, with no slot, budget or scan), cache lookup, calls-per-minute
  admission, scan estimate, a non-blocking execution slot, then the work in a pool thread on its own
  cursor with a deadline interrupt. A busy gate answers immediately with `busy` and a retry delay; there
  is no queue. *Changed 2026-10-27 (owner, after the live client test: 23 of 132 calls were `busy`
  because chat clients send calls in parallel): a call that finds the slot taken waits in a first-come
  queue of at most `TEMPO_MCP_MAX_WAITING` calls for up to `TEMPO_MCP_QUEUE_SECONDS`, and its result
  carries a `queued` warning; past that it is `busy` as before. Still one operation at a time.* The slot is released in the worker, when the work has ended: a caller that gave up at the
  deadline (or disconnected) does not free it early. Protocol metadata (initialize, list) stays
  available while busy.
- **Scan admission.** The rows an operation may read are bounded from Parquet footers
  (`parquet_file_metadata`, never a COUNT): the whole file of each source, summed across a multi-source
  recipe. Over the limit, or an unreadable footer, is `query_budget` with a `describe_dataset`
  recovery, unless a generation-bound result is cached. Metadata tools (`discover_indicators`,
  `describe_dataset`, `get_evidence_links`) are not scan-gated.
- **Cache.** Serialized envelopes only, keyed by contract, base URL, generation id, tool, language,
  canonical arguments and a policy version; at most 128 entries, 4 MiB, 5 minutes; entries of another
  generation are purged; nothing is cached without a present generation. `ok`, `partial`,
  `needs_clarification` and statistical refusals are cached; `busy`, `query_timeout`, `query_budget`,
  `response_budget`, `generation_*`, `execution_failed` and all `error` results are not.
- **Health and smoke.** `/api/health` gains `mcp: {enabled, contract, generation}`.
  `scripts/mcp_probe.py` (standard library only) initializes, lists and makes one read-only call;
  `release-check.py --docker` now checks the image ships with MCP disabled (`/mcp` 404) and then runs
  the image with the endpoint enabled and probes it.

## Configuration

| Setting | Default | |
|---|---:|---|
| `TEMPO_MCP_ENABLED` | false | exposure switch |
| `TEMPO_PUBLIC_BASE_URL` | unset | required when enabled; a bare `https://` origin (plain `http://localhost` only with `TEMPO_MCP_LOCAL_TEST=true`) |
| `TEMPO_MCP_ALLOWED_HOSTS` | the base URL's host | extra Host values (add the `*.fly.dev` host if it is used) |
| `TEMPO_MCP_ALLOWED_ORIGINS` | the base URL's origin | extra Origin values |
| `TEMPO_MCP_MAX_BODY_BYTES` | 65,536 | whole request body |
| `TEMPO_MCP_MAX_CONCURRENT` | 1 | analytical operations in flight per worker |
| `TEMPO_MCP_MAX_SECONDS` | 10 | deadline of one operation |
| `TEMPO_MCP_QUEUE_SECONDS` | 15 | how long a call waits for a busy slot (0 = answer `busy` at once; added 2026-10-27) |
| `TEMPO_MCP_MAX_WAITING` | 4 | calls that may wait at once; more are `busy` (added 2026-10-27) |
| `TEMPO_MCP_LOG_CALLS` | false | development servers: every call's arguments and full result to `mcp-calls.jsonl` in `TEMPO_ASK_LOG_DIR`, nothing about the caller; the server instructions then say calls are recorded and may be published (added 2026-10-27) |
| `TEMPO_MCP_MAX_CALLS_PER_MINUTE` | 120 | `tools/call` admissions (aggregate, not per user) |
| `TEMPO_MCP_MAX_REQUESTS_PER_MINUTE` | 600 | every HTTP request, initialize/list included (429 + Retry-After) |
| `TEMPO_MCP_MAX_SCAN_ROWS` | 1,000,000 | estimated rows an operation may read. The measured operator profile for enabling the MCP on Fly, `scripts/deploy/fly/mcp-public.env`, raises it to 5,000,000 (AQ-01B) |
| `TEMPO_MCP_CACHE_BYTES` / `_ENTRIES` / `_TTL_SECONDS` | 4 MiB / 128 / 300 | result cache |

Zero, negative, non-numeric or non-finite values, a wildcard host or origin, a missing or non-https
base URL and an unparseable flag fail startup with a clear message; zero is never "unlimited".
`TEMPO_MCP_MAX_REQUESTS_PER_MINUTE`, `_CACHE_ENTRIES`, `_CACHE_TTL_SECONDS` and `_LOCAL_TEST` are
additions to the proposed table.

## Checks run

| Check | Result |
|---|---|
| `python -m pytest tests -q` (synthetic) | **1139 passed, 73 skipped** |
| `TEMPO_DATA_DIR=…/tempo-gen-20261012/data python -m pytest tests -q` (read-only, copied generation 9b3e065d) | **1212 passed, 0 skipped** (1020 on `integ/at01-ui-rhythm`) |
| New AT-03 tests | `test_at03_mcp` 37, `test_at03_resources` 21 |
| Clean runtime install | a new venv with only `requirements.txt` (no pytest) runs the real app on the copied generation with the endpoint on; `scripts/mcp_probe.py` against it returns 7 tools, `describe_dataset(POP105A)` ok, structured == text; `POST /mcp/` 404, `GET /mcp` 405, a wrong Host 421 |
| Docker image smoke | **not run** (no Docker here); the code path is in `release-check.py` |
| Live ChatGPT/Claude, Fly load | **not run** |

The spec's acceptance checks map to tests: 1 → the real SDK client lists and calls all seven over
Streamable HTTP through the app's lifespan, and a uvicorn test covers startup/shutdown and the `/mcp`
path; 2 → `test_disabled_endpoint_is_404…`, `test_the_ask_and_mcp_switches_are_independent`, the
clean venv; 3 → `test_service_and_mcp_return_the_same_envelope` (values, refusals, partial, errors,
generation), the wire-size and non-ASCII tests; 4 → host/origin/body/argument/adversarial-literal tests;
5 → deadline, hang-up, overload, failure, cache and scan tests; 6 → `test_all_seven_tools_work_with_no_model…`;
7 → the suite (static parity included), the image smoke is code only.

### Seven calls on the copied generation through MCP (read-only)

In-process, real SDK client; `parity` is the MCP envelope equal to a direct `registry.call_tool`.

| Tool | Request | Status | Wire | Time |
|---|---|---|---:|---:|
| `describe_dataset` | POP105A | ok | 20,240 B | 624 ms (cold) |
| `query_data` | POP105A, 2024, by county | ok | 11,098 B | 29 ms |
| `compare_periods` | POP105A counties 2012→2021, top 3 | ok | 13,008 B | 34 ms |
| `run_recipe` | tourism_intensity 2025 | ok | 28,214 B | 102 ms |
| `query_data` | POP107A by time | unavailable `overlapping_levels` | 6,736 B | 102 ms |
| `query_data` | POP107D_varste_localitate by time | unavailable `query_budget` (scan limit) | 2,596 B | 23 ms |
| `discover_indicators` | "innoptari pe locuitor Cluj" | ok | 20,664 B | 159 ms |

All parity true. POP107D's single-age child, which AT-01 returned as `partial`/`incomplete_domain`, is
now refused earlier by the public scan limit (the file is far over 1,000,000 rows); a narrower
sub-dataset or a recipe is the way in. This is the intended, conservative first-release behaviour.

## Contract decisions

- Low-level `Server`, `validate_input=False`: the service validates strictly and answers with its own
  envelope and a corrective message; the SDK's schema check would answer with its own text. The
  published input schemas are still strict (`additionalProperties: false`).
- Stateless and POST-only: no session ids to track, no server-sent streams, nothing to leak across
  clients. If a client needs sessions, that is a later change.
- `isError` mapping: `status: error` → true; `unavailable`, `partial`, `needs_clarification` → false.
- The text fallback is compact JSON, the same bytes the cache stores; both representations are in the
  wire budget.

## Remaining limitations

- **One worker.** Every limit is per worker, not a deployment-wide quota. A second machine needs shared
  coordination before any global claim.
- **The 512 MiB Fly machine has not passed its Linux resource gate**; completing AT-03 does not clear it.
  A cold first `describe_dataset` takes about 0.6 s on the real copy; no load or memory measurement was
  made (AT-04). `min_machines_running = 0` means a cold start that may time out a connector.
- **The scan estimate is the whole file**, so a large split family is refused even when a filter would
  read little. Partition statistics could admit those; raising the limit or refining the estimate needs
  AT-04 evidence.
- **The image grows** by the SDK's dependencies (`mcp` is now in `requirements.txt`; it is imported only
  when the endpoint is enabled, so a disabled deployment pays disk, not memory). Not measured: no Docker here.
- **No live client interoperability.** ChatGPT and Claude connector behaviour (schema acceptance, anonymous
  access, timeouts) is untested; the SDK client is the only client used.
- **A caller that disconnects** is detected where the transport reports it; otherwise the deadline bounds
  the work. Either way the slot is released only when the work ends.
- **Every tool call shares the one analytical slot**, metadata tools included: while a slow analysis runs,
  even `describe_dataset` answers `busy`. Only initialize and `tools/list` stay available.

## Rollback

Set `TEMPO_MCP_ENABLED` to false (or unset it) and restart: `/mcp` answers 404 and the web app and API
are untouched. Reverting the package removes the dependency on `mcp` at runtime. No corpus migration or
regeneration is involved. Never restore a query path that bypasses the aggregation or grain policy.
