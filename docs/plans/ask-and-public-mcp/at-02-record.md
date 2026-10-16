# AT-02 completion record: bounded, recoverable Ask over the shared tools

**Status (2026-10-16): implemented and verified locally on branch `at/02-ask-runtime`.
Owner review/acceptance pending.** Not pushed, not merged, not deployed. No live provider
call was made (none is part of AT-02 acceptance; live quality is AT-04). Ask stays off unless
`TEMPO_ASK_ENABLED` / `TEMPO_ASK_BYOK_ENABLED` is set, exactly as before.

| | |
|---|---|
| Baseline | `integ/at01-ui-rhythm` 81030f5 (= `pa/00-baseline` 8a9689d + `ui/rhythm` + AT-01 + the combined landing) |
| Code | `at/02-ask-runtime`: dcf9cc7 (AT-02a), 6195e2c (b), 17b702e (c/d/e), 2f31637 (f); the record follows |
| Worktree | `../tempo-at23` |
| Corpus / tables changed | none |

## What was built

| Part | Where | What |
|---|---|---|
| Provider completion | `llm_client.py` | `LLMResponse.finish` (`complete`, `tool_use`, `output_limit`, `content_filter`, `incomplete`, `other`), `usage` (input/output/reasoning/cached tokens, null when the provider is silent) and `requested_tokens`. `complete_with_tools(..., tool_choice="none")` for the final answer, `max_retries` (the loop passes 0). A truncated tool-call argument string is flagged, not raised. A failed Responses turn is a stable `provider_error`. Output allowances are configured per provider/model. |
| The loop | `agent.py` | Calls the seven `tempo-tools/1` tools through `registry.call_tool` (schemas inlined from the registry). Counted together: model calls (8), tool dispatches (12), wall clock (90 s), requested output tokens (64,000). The last model call is reserved for a final answer with tools disabled and the known gaps stated. |
| Duplicate and refused requests | `agent.py` | An identical request in the same generation is served from the turn cache (counted as a dispatch and a cache hit, not an execution). A repeated refusal returns its previous outcome and recovery candidates, not another scan. A request refused as `busy`/`query_timeout`/`execution_failed` may run once more. Three consecutive failures stop the exploring and go to the final answer. |
| Model context | `ask_context.py` | At most 96 KiB of tool output stays in the conversation. Older results become compact summaries under the same call id: definition, canonical selection, effective selection, scope, warnings, recovery and at most five rows, with `rows_omitted` and a note that removed rows were not re-checked. |
| Follow-ups | `ask_context.py`, `routers/ask.py` | The response carries `context`: at most four canonical selections (8 KiB). The request echoes them back as untrusted input: only tool, generation id and the schema-validated selection survive, any claim the client attaches is dropped, a stale generation is a 409 with `action: refresh`. They reach the model as hints and are re-run. |
| Terminal state | `agent.py` | `outcome` (`answered`, `clarification`, `refused`, `partial`, `failed`) and a stable `reason` next to `stop_reason`: `iterations`, `tools`, `deadline`, `output_budget`, `output_limit`, `empty_output`, `content_filter`, `provider`, `cancelled`, `no_valid_query`, or the tool's own refusal code. |
| Verification | `answer_check.py` | Recipes and period changes count as data retrieval. `verification.claims`: each numeric claim bound by the server to a result cell (`tool_call_id`, JSON Pointer `path`, `entity`, `period`, `unit`, `check`). A claim is `matched` only if a cell holds the number and, when the cell belongs to a named entity, the sentence names it. A sign is not compared ("fell by 50" matches -50). |
| Display | `ask_present.py` | The page keeps its shapes. A query becomes the `data` table; a change ranking and a recipe become plain bounded tables with no chart; links to the complete data and evidence come from `get_evidence_links` for the displayed selection. |
| Logging | `ask_guard.py`, `agent.py`, `routers/ask.py` | The request's own key is removed from every log record while the request runs (a context variable), from provider error text where it is made, and from debug events and NDJSON lines before delivery. Debug fields are bounded as values; at most 200 events are kept and the drop count is reported. Ordinary metrics are a whitelist of ids, counts, sizes, durations and stable codes. |
| Cancellation | `ask_guard.py`, `routers/ask.py` | `/api/ask` and `/api/ask/stream` are async. A browser abort or disconnect cancels a `CancelToken`, which interrupts only the cursor the request owns. A deadline watchdog interrupts a running query at the 90 s limit. The concurrency slot is released when the work has really ended. |
| Page | `ask.js`, `ask.html` | Outcome banners with reasons, partial/scope notes, safe data links, an unbound-figures note, follow-up context kept in memory and cleared by "New conversation", failures that keep the question and suggest a next step. |

## Old → new terminal behaviour for the logged empty answer

The 2026-10-15 DeepSeek Flash run ended its last call with `finish_reason: length` and 0 text
chars after 14 s.

| | Old | New |
|---|---|---|
| Result | HTTP 200, `stop_reason: end_turn`, answer `(no answer)` | One bounded retry: the allowance at least doubles (never below 8,000 for a reasoning model, never beyond what the turn has left), older results are compacted and the model is told to answer briefly. If that call answers, the answer is real and `outcome: answered`. |
| If it fails again | the same | `outcome: failed`, `reason: output_limit`, a notice in the question's language, HTTP 200 |
| Partial text | shown as a normal answer | `outcome: partial`, `reason: output_limit`, the text plus a cut-off note |
| Whitespace success | `(no answer)` | One repair call with tools off, then `empty_output` |

Tested with scripted providers: `test_at02_loop.py::TestProviderOutcomes`.

## Allowances and bounds in force

| Limit | Default | Setting |
|---|---:|---|
| Model calls per turn (retries and the final answer included) | 8 | `TEMPO_ASK_MAX_ITERATIONS` |
| Tool dispatches per turn | 12 | `TEMPO_ASK_MAX_TOOL_CALLS` |
| Wall clock | 90 s | `TEMPO_ASK_MAX_SECONDS` |
| Output tokens requested per call | 2,048 (8,000 for `deepseek:*`; OpenAI Responses at least 8,000) | `TEMPO_ASK_OUTPUT_TOKENS`, `TEMPO_ASK_REASONING_OUTPUT_TOKENS`, `TEMPO_ASK_REASONING_MODELS`, `TEMPO_ASK_RESPONSES_MIN_OUTPUT_TOKENS` |
| Output tokens requested per turn | 64,000 | `TEMPO_ASK_TURN_OUTPUT_TOKENS` |
| Tool output kept in the model's context | 96 KiB | `TEMPO_ASK_CONTEXT_BYTES` |
| One tool result | 32 KiB, 200 rows | AT-00 |
| Follow-up context | 4 entries, 8 KiB | constants in `ask_context.py` |
| Debug events kept | 200 | `TEMPO_ASK_DEBUG_MAX_EVENTS` |
| Provider calls started | not within 2 s of the deadline | `MIN_CALL_SECONDS` in `agent.py` |

The reasoning-model list is a starting point (`deepseek:*`, the observed failure), not a measured
one. Revisit all allowances with the AT-04 cost/quality evidence.

## Checks run

| Check | Result |
|---|---|
| `python -m pytest tests -q` (synthetic, no corpus) | **1139 passed, 73 skipped** (948 / 73 at the baseline) |
| `TEMPO_DATA_DIR=…/tempo-gen-20261012/data python -m pytest tests -q` (read-only, copied generation 9b3e065d) | **1212 passed, 0 skipped**, run at the AT-03 head (the AT-02 head alone: 1154 passed) |
| New AT-02 tests | `test_at02_llm_client` 25, `_guard` 12, `_loop` 31, `_context` 24, `_cancel` 5, `_privacy` 4, `_browser` 27 (9 states × 320/390/1280 px, Chromium) |
| Mutation check | with the exact-key scrub disabled, `test_at02_privacy.py::test_the_key_is_nowhere_in_http_ndjson_logs_or_metrics` fails (the key reached the `ASK_DEBUG` log line) |
| Browser | outcome banners, tables, links, reset, 409, busy, network error and client timeout: no console errors, no horizontal scroll at 320/390/1280 px; screenshots read at 320 and 1280 |
| Static parity | passes (it is part of the suite) |
| Live provider, live ChatGPT/Claude, Fly | **not run** |

The spec's acceptance checks map to tests: 1 → `TestProviderOutcomes`; 2 → `TestRefusalLoopsAndDuplicates`;
3 → `TestBudgets` (context compaction keeps call/result pairing, warnings and selections; a real
2,732-row result stays within 32 KiB while the page keeps its links); 4 → `test_at02_context`;
5 → `test_at02_privacy`; 6 → `test_at02_cancel` (a real DuckDB cursor is interrupted, another
cursor answers, the slot is freed); 7 → `test_at02_browser`; 8 → the full suite.

## Intentional behaviour changes (existing surfaces)

- **Tools:** the model sees the seven shared tools. `search_datasets`, `get_dataset_schema`,
  `query_dataset_data` and `list_categories` are gone with no alias; topic browsing goes through
  `discover_indicators`. `agent._handle_*` and `TOOL_HANDLERS` no longer exist.
- **Tests:** the parity tests that compared REST and the dev MCP with the old Ask adapter now use
  the shared tool (`tests/ask_adapter.py`). Differences: an empty selection is `unavailable` with a
  message and a `find_dimension_values` recovery instead of a `warnings` entry; `query_data` needs a
  present generation for grouped results (the fixtures write a manifest); `fix08_helpers.install`
  fakes `agent.call_tool` instead of `TOOL_HANDLERS`.
- **Response:** additive `outcome`, `reason`, `context`; `budget` gains executions, cache hits,
  requested tokens and context bytes; `verification` gains `claims` and `claim_summary`;
  `tool_trace` entries gain `id`, `executed`, `cached`; the old `tool_trace[].output` is the envelope.
  `data` gains `tool`, `scope`, `links`; its `status` can be `partial`.
- **Router:** `/api/ask` and `/api/ask/stream` are `async def` (work in the default executor); a 409
  can occur for a stale context; `/api/ask/config` lists the follow-up limits.
- **Redaction:** keys of dict entries are no longer redacted when the value is a number or flag
  (`max_tokens: 2048` was being hidden by the `token` pattern).
- **Limits:** a provider call is not started with under 2 s left; SDK retries are off in the loop.

## Remaining limitations

- **No live evidence.** Quality, cost and the allowance defaults need AT-04 runs with real models.
- **Provider calls in flight cannot be interrupted.** After an abort the call ends at its own
  deadline-bounded timeout; the slot stays taken until then.
- **`tool_choice: none` is untested against live providers.** Both SDKs type it (Anthropic
  `{"type": "none"}`, OpenAI `"none"`), but an OpenAI-compatible provider could reject it, which would fail
  the final call as `provider_error`. A provider that ignores it has its tool requests ignored; with no
  text the turn ends as a budget stop with what was gathered.
- **Claim binding is sentence-level.** It needs the entity named in the same sentence; period and unit
  are reported, not required. A one-letter entity code must stand alone with the same case.
- **`clarification` is inferred** from the last tool result or a trailing question mark.
- **Tool messages are English** (AT-01); the Ask page's own text is Romanian/English.
- **One table, one chart.** The page shows the last data-bearing result; a chart only for a query.
- **Links:** built from `TEMPO_PUBLIC_BASE_URL`, relative when unset. A static page on another
  origin needs an API base in `ask.js` and CORS on the API (the hosting runbook, step A).
- **The browser tests mock `/api/ask`.** They prove rendering, not the full stack; the full stack is
  covered by the Python tests.

## Configuration and rollback

- New settings are listed above; none changes a default that was on. Ask exposure switches are
  unchanged and independent of AT-03.
- **Rollback:** disable Ask (`TEMPO_ASK_ENABLED` / `TEMPO_ASK_BYOK_ENABLED` unset) rather than
  reverting statistical guards. Reverting the branch restores the old four-tool loop; the REST and
  static surfaces do not depend on it.
