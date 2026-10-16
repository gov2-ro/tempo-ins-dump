# AT-02: Robust Ask orchestration

## Problem and ownership

**AT-02: implemented 2026-10-16** (see [at-02-record.md](at-02-record.md); owner review pending). Make the existing Ask loop a bounded adapter over AT-01.
Primary files: `agent.py`, `llm_client.py`, `ask_guard.py`, Ask router/config,
`ask.js` and focused tests. Preserve disabled-by-default hosted/BYOK switches,
history validation, allowlists, concurrency limits and existing data/chart UI.
Do not broaden model/provider availability or expose Ask in production here.

## Context, state and budgets

### Shared tools and bounded model context

Use AT-01 tool schemas/handlers, not a second implementation of their rules.
Keep aliases for old names only where necessary for existing internal callers;
do not advertise duplicate old/new tools to the model. Adapt old test/UI traces
deliberately. Recipe/change tools must count as valid data retrieval in answer
checking and citations; they are no longer limited to `query_dataset_data`.

The model receives the compact `tempo-tools/1` envelope. Full tables/bundles go
to the user through existing data/download/evidence facilities; do not silently
cut the page's export while reducing model context. The response's legacy
`data`/`chart_spec` fields can remain adapters for supported table/series shapes.
For a new change/recipe result, render an appropriate bounded table and links;
never invent a chart role or collapse two geographic series into one.

Initial configurable model-context budget: **96 KiB of serialized tool output
retained across a turn**, in addition to existing bounded user/assistant history.
This is a deterministic byte limit, not an exact token estimator. Track tokens
when the provider returns them. Retain current request, definitions, effective
selections, warnings, result ids and necessary values. Replace old bulky tool
results with compact factual summaries and canonical selections. Preserve the
provider's valid tool-call/result pairing; never leave orphan call ids or make
the model believe deleted rows were checked.

### Follow-up selections

The current browser retains only question/answer prose. Add bounded structured
context for the last four validated selections, so "same for Iași" or "now 2020"
can reuse a source/definition and change only the requested coordinate.

Use an additive typed `context` field on Ask requests/responses. It contains
canonical selection specs, tool type, generation id, definition/unit identifiers
and small provenance summaries, **no model credentials or bulk observations**.
Maximum four entries and 8 KiB UTF-8 serialized context. The browser keeps it in
memory for the tab, clears it with chat reset, and sends it within the existing
request bounds. It is untrusted input: validate every identifier/filter again,
ignore client-supplied verification/value claims, and reject a stale generation
with a refresh action. It grants neither authorization nor approximation consent.
No persistent conversation DB or OAuth system is required.

### Execution budgets and loop recovery

Keep default limits at 8 model calls, 12 tool dispatches and 90 seconds. Make
every attempt, including retries and final synthesis, count. Higher limits are
an operator choice after measurements, not the acceptance criterion.

- Reserve the last available model call for final synthesis with tool use
  disabled using provider-supported controls. Pass only usable results and
  explicit gaps. If there is no usable result, return a clear bounded refusal or
  clarification, not fabricated data. Do not ask for tools on the final call and
  then discard them as the current loop does. Reserve its configured output
  allowance inside the aggregate requested-token budget as well.
- At most one retry per identical normalized tool request per turn. A repeated
  refusal gets a compact previous outcome plus its recovery candidates, not
  another expensive scan. Exact duplicate calls can reuse their result within
  the same generation, but every model-requested tool dispatch still counts
  toward the tool budget. Expose cache reuse separately from actual executions.
- Follow-up recovery must either narrow/change the request, pick a supported
  candidate or ask a consequential clarification. Raw-row fallback does not
  bypass a grain/domain/overlap refusal. If no justified next action remains,
  stop early with the known reason and sources.
- Compute remaining time before every provider/tool operation. Include SDK
  retries/backoff in the total budget; per-attempt timeouts must not multiply
  a supposed 90-second deadline. Disable hidden SDK retries when the explicit
  retry policy owns the budget, or prove their bounded aggregate behavior.
- On HTTP disconnect/browser abort, propagate cancellation to the operation
  where possible. A stopped response does not mean a synchronous query/thread
  stopped. Keep concurrency slots occupied until underlying work is terminated
  or finishes; use an owned cursor for interruption. Do not interrupt another
  user's cursor or the shared parent DB connection.

## Provider completion and recovery

Extend `LLMResponse` with optional normalized completion state and provider usage:
input/output/reasoning/cached tokens when provided; missing fields remain null.
Keep raw provider usage out of browser payloads unless sanitized/needed. Preserve
tool-call ids and existing Anthropic/OpenAI/compatible message conversions.

Normalize provider terminal states (`length`, `max_tokens`, incomplete Responses,
content filtering, unavailable/error) before the agent decides it has an answer.
An empty string/whitespace final answer is never a completed success.

Initial provider policies:

| Case | Required behavior |
|---|---|
| Valid tool call | Dispatch only under remaining tool/time limits |
| Complete nonempty answer | Finalize/cite/check; distinguish answer/clarification/refusal |
| Output limit with no usable answer | One bounded retry if time/calls/tokens permit, using a suitable output allowance and compact context; otherwise explicit `output_limit` partial/failure |
| Output limit with partial text | Mark partial; do not declare `completed`; preserve useful verified data separately |
| Auth/model/invalid-request error | Stable actionable error; no automatic switch to another provider or key |
| Retryable timeout/rate/unavailability | At most one retry under remaining budget, then explicit partial/provider failure |
| Empty nominal success | At most one bounded repair attempt; then `empty_output`, never `(no answer)` as successful completion |

Keep provider-specific output allowances configurable. The current 8,000 minimum
on Responses and 2,048 compatible default are observed defaults, not universal
requirements for all models. For configured reasoning-capable compatible models,
start with a tested 8,000-token allowance and a **64,000 aggregate requested
output-token allowance per Ask turn** (all calls/retries included). Charge each
call's requested `max_tokens`/`max_output_tokens` against that safety allowance;
return explicit `output_budget` when insufficient, never silently truncate the
conversation. Configure per provider/model; cached server-side tool results do
not authorize more model calls. Revisit these engineering defaults after AT-04
cost/quality measurements, with evidence.

Do not infer that a generic timeout means the user's key was wrong. Never send
a provider's server key to another compatible API. Preserve the existing keyless
Ollama opt-in and server/BYOK allowlists.

### Terminal response semantics

Retain `answer`, `citations`, `tool_trace`, `data`, `chart_spec`, `warnings`,
`verification`, `stop_reason`, `budget` and optional debug fields. Add a terminal
`outcome`: `answered|clarification|refused|partial|failed`, with stable `reason`.
HTTP 200 partial/refusal remains possible for compatibility; metrics/UI must not
equate HTTP 200 or `end_turn` with a successful substantive answer.

Surface `output_limit`, `empty_output`, `output_budget`, `iterations`, `tools`,
`deadline`, `provider` and `cancelled` distinctly. Partial results have explicit
labels and exact query/evidence links. Follow-ups can reuse validated selections.

### Answer verification

Preserve deterministic numerical checks, extend them to recipe/change outputs,
and attach claim references to tool result/field/entity/period/unit where the
answer exposes a number. Deterministic tool-derived result tables and citations
are authoritative. Number occurrence in any result is not semantic verification.
If prose cannot be bound to a fact, flag it; do not claim the whole narrative is
verified. Valid derived changes come from `compare_periods`/recipes rather than
unverified model arithmetic. Never bypass an unavailable tool outcome.

Use additive `verification.claims` entries with `text`, `tool_call_id`, `path`
(JSON Pointer into that result), `entity`, `period`, `unit` and
`check=matched|unverified`. The server validates referenced facts; model-supplied
references do not certify themselves. If the prose format does not provide
bindable references, keep the existing unverified-claim warnings and verified
result table, rather than treating occurrence-based number matching as semantic
proof. This is not a mandate to add a second verifier-model call.

## Logging and credentials

Fix redaction **before** JSON serialization/logging/debug-sink delivery. Pass the
actual request key into redaction, plus provider-specific server credentials if
they can appear in an exception. Keep credentials out of event objects, state,
normal metrics, caches, trace persistence and error text. Test arbitrary-format
keys as well as `sk-`, Google and xAI patterns. Never print real logs in tests.

Ordinary content-free metrics remain allowed when `ASK_LOG_CHATS=false`:
request id, provider/model, terminal outcome/reason, model attempts, tool
dispatches/executions/cache hits, durations, request/result byte counts, usage
token totals when known, refusal-code counts and cancellation/timeout status.
No question/history/answer, tool filter values, credentials or exception bodies.

Detailed debug remains local-only and off by default. Sensitive content may
appear only under its explicitly enabled content policy, with credentials always
redacted first. Bound individual fields/arrays before logging; do not slice the
serialized JSON into invalid records. Report dropped-debug-event counts.

UI timeout stops the spinner and offers a useful next action. Retain the NDJSON
step display. Ensure errors after stream start still produce a terminal error
event, free resources and show a stable reason. A disconnected stream must not
leave unbounded worker threads.

## Acceptance checks

Use fake provider responses and real AT-01 services on synthetic corpora:

1. Reproduce `length` + zero text, Responses incomplete, whitespace success,
   partial text, auth 401, rate limit and provider timeout. Assert normalized
   outcomes, retry counts, deadlines and usable final user messages.
2. Simulate repeated search/query refusals and a provider requesting tools on
   its last call. Verify no unsafe raw aggregation, no duplicate executions,
   budgets counted and reserved final synthesis behavior.
3. Model responses with 2,732 rows/category trees cannot exceed the logical
   output/context budgets; warnings, facts and provider tool-pairing survive
   compaction. Page/download completeness is independently asserted.
4. Follow-up "same for Iași" reuses the declared source/definition, changes only
   the place, and re-runs validation. Stale-generation or tampered context cannot
   certify a number or enable an approximation.
5. Capture HTTP, NDJSON, logger records and persisted metrics with an
   arbitrary-format fake key echoed by a provider error. The key appears nowhere;
   chat logging disabled means no content fields in ordinary metrics.
6. Cancel one streaming request while another query runs. The cancelled work is
   interrupted or remains counted until it actually stops; the second request
   succeeds and all slots are eventually released. Fake clocks cover deadlines;
   a real DuckDB cursor fixture covers query interruption/isolation.
7. Browser tests at 320/390/1280 px cover answered/clarification/partial/error,
   recipe/change tables, citations, context reset and debug-off behavior. Existing
   v1/v2/compare/place pages and chart-series identity keep passing.
8. Full required tests and relevant static parity pass. No live model calls are
   required for AT-02 acceptance; record live quality separately in AT-04.

Completion record must include old→new terminal behavior for the logged empty
answer, maximum retained context/usage allowances, log-redaction evidence and
configuration/rollback. Disable Ask rather than reverting statistical guards if
a production issue is discovered later.

