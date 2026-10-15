# AT-04: Evaluation, client onboarding and release evidence

## Problem and ownership

**AT-04: pending.** Demonstrate that supported tasks reach useful, statistically
correct results through the new tools, and prepare a reviewable MCP/plugin
candidate. Reusing a search baseline or reporting HTTP 200 does not establish
answer quality. Keep code completion, live-client validation and release approval
as separate statuses.

## Deterministic task evaluation

Add a small versioned task corpus and a deterministic runner/replay layer. Prefer
existing pytest fixtures/helpers and a machine-readable JSON result; no external
eval service or additional model is necessary. Expected answers must come from
the numerical fixtures and reviewed generation-pinned answer records, never from
today's arbitrary model output. Search drift remains a separate regression suite.

Required task set (at least these cases):

| ID | Task | Expected evidence |
|---|---|---|
| T01 | Resident population for a named county/year | Correct source definition, exact value, unit, period, scope and generation |
| T02 | Generic population/unemployment question | Consequential definition alternatives; no guessed official statistic |
| T03 | County versus same-named city | Explicit place-level clarification before claiming a value |
| T04 | Recent monthly value outside schema examples | Actual bounds and option lookup reach the requested period |
| T05 | Requested historical year absent | Explicit unavailable year with alternatives; no implicit latest fallback |
| T06 | Tourism stays per resident | Reviewed recipe, aligned year/denominator and evidence; fixture 120/60=2 |
| T07 | County earnings/unemployment total | Published source cells where available, reconstruction only as cross-check |
| T08 | Multi-interval municipal population decline | Complete eligible endpoint population, fixture changes/ranking from AT-01 |
| T09 | Duplicate locality names across counties | Full entity keys remain separate or operation is refused |
| T10 | Overlapping ages/conflicting observation keys | Correct shared refusal and safe recovery; no raw-row summation |
| T11 | Single-age 0–84 child used as all-ages | Explicit restriction/alternative, never an unqualified population total |
| T12 | Missing Total filter | Explain absence; validate the revised query/recipe rather than guessing |
| T13 | Oversized raw/context response | Compact result and exact links, complete flags and working model message pairing |
| T14 | `length`/incomplete/empty provider answer | Bounded retry or explicit partial/failure; no false success |
| T15 | Repeated refusal/tool loop | Bounded execution, clear terminal outcome and correct recovery |
| T16 | Follow-up “same for Iași”, then “now 2020” | Same definition/source, changed coordinate, revalidation and no stale result |
| T17 | Corpus generation changed between result and evidence | Explicit conflict; no new data represented as the old snapshot |
| T18 | Approximation without explicit opt-in | Refused; opted-in result remains labelled and outside official-total claims |
| T19 | Arbitrary-format fake credential in error | Absent from HTTP, NDJSON, logs, metrics, context and persisted fixtures |
| T20 | Busy/timeout/disconnect | Stable outcome, no leaked slots/workers and no cross-request cancellation |

For deterministic integration tests, replay provider tool-call sequences while
executing the actual AT-01 services. Assert meaningful behavior, not the precise
natural-language prose. Fake providers are not evidence of model tool choice;
numerical fixtures are not evidence of real corpus coverage.

Each run reports per task:

- answered/clarified/refused/partial/failed and semantic pass/fail;
- source, definition, geography key, periods, unit, coverage and generation;
- correct figures or precise refusal; evidence hash/recomputation status;
- model attempts and requested/actual token usage when known, tool dispatches
  versus executions/cache reuse, output/context bytes, and wall-clock timings;
- unexpected exceptions, data changes, unavailable prerequisites and skips.

The deterministic supported fixture set must pass 100%. Fail any invented value,
ignored filter, switched definition, unlabelled partial scope, unsafe aggregation,
unbounded work or leaked credential. Do not average those failures away using a
good overall success score. Add browser checks for terminal outcomes/tables/
citations/follow-ups at 320/390/1280 px and preserve existing page smoke coverage.

## Live model and client validation

No paid provider calls are authorized by this handoff. Prepare a runner that
defaults to dry-run/replay and requires explicit live-provider selection plus
per-run request/token/spend ceilings before network calls. Never log or store
the key in the command/report. Missing pricing/usage is unknown, not $0; a hard
dollar ceiling requires a configured price schedule and pre-call upper bounds.
Stop before dispatch when a bound would be exceeded. An implementer must ask
for the missing authorization/configuration rather than silently spending.

For actual model quality after authorization, run the same reviewed prompts on
selected models, record exact provider/model/date/settings/generation, and
repeat the multi-step cases three times. Preserve redacted summaries/tool traces
with explicit content-retention consent. Explain variation and failures; do not
claim that supporting a provider means it passed the task set. Never assert
semantic correctness based only on numbers appearing somewhere in a trace.

For hosted MCP, the owner can test the candidate in their existing ChatGPT and
Claude accounts. This need not use API keys, but still consumes their normal
account usage and needs a reachable authorized test endpoint. Do not expose a
local tunnel/server publicly or install in someone else's account on your own.

Client checklist for each tested product/account:

1. Add/connect the public endpoint without an INS/model API key.
2. List/discover tools and obtain a fact with a valid source/evidence link.
3. Clarify a definition/place, run the multi-interval change case and a recipe.
4. Observe a statistical refusal and a resource refusal without a confusing
   generic server error or an unsafe workaround.
5. Follow up using the same selection and compare its values with the web API.
6. Disconnect/reconnect; verify no required hidden session state or credential.

Record product surface, plan/workspace policies, transport/SDK versions, date,
tools available and results. Account-specific absence of custom connectors is
an access limitation, not a passed compatibility check. Do not promise support
for every web chat or free account from one successful client test.

## Plugin packaging and onboarding

Prepare these reviewable artifacts without publishing:

- a ChatGPT plugin package using the **current official** package/MCP/skills
  format, with INS+ name, description, website, support/privacy/terms references,
  endpoint and anonymous-read configuration; validate against current tooling;
- an optional short skill/instructions component explaining INS definitions,
  safe tool order, clarification, evidence and refusal handling; instructions
  supplement server checks and cannot replace them;
- a Claude remote-connector guide with the exact production/test MCP URL and
  anonymous connection steps, including the applicable account-policy caveat;
- a short Romanian-first `/connect` or equivalent help page with English text,
  supported clients, examples, data-flow disclosure, limitations and links;
- a publication checklist with draft versus submitted/approved/published status.

If the final domain/contact/privacy terms are missing, use clearly marked
placeholders in the **draft**, list them as publication blockers and finish the
technical implementation/validation. Do not invent owner identity, legal terms,
source reuse permission or an approved listing. No live directory submission is
authorized. Provide manual MCP setup for a pilot before seeking a listing.

User-facing language should explain:

> Connect INS+ to your chat app to search Romanian public statistics and run
> supported calculations. Your chat app handles the conversation; INS+ receives
> tool requests and serves the data. No model API key is needed by INS+. Your
> chat provider's account limits apply. Some datasets or calculations are
> unavailable when their coverage or statistical structure is unsafe.

Public data does not mean the request itself contains no personal information.
The MCP should receive structured selections, not the complete chat by design;
clients can still send arbitrary text in a search field. Publish the actual
logging/retention policy. Do not claim "we receive no chat data" or that inputs
never leave the user's device. Do not expose debug content by default.

Verified documentation entry points as of 2026-10-15; recheck at implementation
and especially before packaging/publication:

- [Official Python SDK](https://github.com/modelcontextprotocol/python-sdk): use
  the installed/pinned version's transport/lifespan APIs.
- [ChatGPT MCP connection](https://developers.openai.com/plugins/deploy/connect-chatgpt),
  [tool authentication](https://developers.openai.com/plugins/build/auth), and
  [plugin submission](https://developers.openai.com/plugins/deploy/submission).
- [Claude remote connectors](https://support.claude.com/en/articles/11175166-get-started-with-custom-connectors-using-remote-mcp).
- [Fly resource pricing](https://docs.fly.io/about/pricing) and the repo's actual
  `fly.toml`/release gates, not a hard-coded monthly estimate.
- [ChatGPT plan usage](https://developers.openai.com/siwc/token-sharing-open-source):
  current open-source/local-app docs direct remotely hosted applications to an
  interest form. Embedding subscription-funded Ask on INS's website is a
  separate integration, not a promised side effect of MCP or ordinary login.

## Release and cost gates

Before public exposure, run the existing release gate against the exact staged
generation/image, plus MCP smoke and a **Linux container resource test**. The
earlier local web workload reached about 1.2 GiB RSS; the configured 512 MiB Fly
Machine therefore remains unproven. Do not call an unconstrained macOS run the
512 MiB gate, silently enlarge production RAM, or re-use an old candidate's pass.

Suggested bounded measurement: one worker; three minutes at one active MCP
client, then five minutes with five MCP clients, plus a mixed REST/search/export
phase and deliberate over-budget queries. Use synthetic stress fixtures first;
the real copied generation is read-only. Never load-test production. Include
cold-start behavior, request timeouts and shutdown/cancellation.

Acceptance:

- zero unexpected 5xx, OOMs, corrupted exports, credential leaks or differing
  analytical results for identical generation/selection;
- expected busy/over-budget refusals are counted separately from successful
  requests; the admission limit prevents work continuing in the background;
- at the selected operating concurrency, target warm p95 <2 s for discovery/
  schema/options and <5 s for admitted analytical calls; hard tool deadline
  remains enforced. Report misses rather than relaxing thresholds silently;
- document peak RSS, CPU time, DB/scratch budgets, queue behavior, response
  bytes and cache effectiveness under the actual container memory limit;
- operator model requests from public MCP: **zero**, proven by instrumentation
  or a provider-client fail-on-call assertion, with server API keys unset;
- recommend a tested Fly size/concurrency/scan budget with the measured
  limitations. Choosing/provisioning that size remains an owner action.

Cost report separates current fixed hosting, incremental CPU/RAM, outbound bytes,
storage/observability and any separately authorized built-in Ask model calls.
For MCP, the chat client supplies inference; unknown future provider/platform
fees are not a guarantee of free service. Use current regional Fly pricing and
observed bytes/query; extrapolate with stated assumptions (e.g. questions ×
tools/question × average response bytes). Input/results caps alone do not bound
scan cost or aggregate usage. Do not advertise unlimited anonymous capacity.

Release sequence after implementation and authorization: stage exact candidate;
pass synthetic/corpus/static/MCP/image gates; validate clients and resource
profile; approve exposure/domain/privacy; enable public MCP; pilot; consider
directory submission. Hosted/BYOK Ask stays off until its separate live-quality
gate is accepted. No deployment is implied by completing these steps on paper.

## Completion record

Add an implementation record in this directory (only after real implementation)
with this table and supporting report paths:

| Gate | Status: pass/fail/not run/blocked | Code/generation/date | Command/client | Evidence/limitations |
|---|---|---|---|---|
| AT-01 tool contract + numerical fixtures | | | | |
| AT-02 Ask replay/UI/privacy | | | | |
| AT-03 SDK transport/resource-bound tests | | | | |
| Existing full pytest + static parity | | | | |
| Pinned copied-generation task checks | | | | |
| Separately authorized live-provider tasks | | | | |
| ChatGPT / Claude interoperability | | | | |
| Linux image/memory/mixed-load gate | | | | |
| Plugin package validation and real help links | | | | |
| Owner exposure/publication approval | | | | |

Include config/disable rollback instructions and remaining source restrictions.
Unperformed operational gates must not leave engineering work falsely marked
unfinished, and completed engineering must not imply production readiness.

