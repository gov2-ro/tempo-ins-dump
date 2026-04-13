# Agent live-test conclusions (deferred work)

## Context
Five iterations of live end-to-end testing of `POST /api/ask` (2026-04-09). Work deferred; conclusions and next steps captured in BACKLOG.md and here for the next session.

## What was done
- Fixed OpenAI `KeyError: 'name'` bug in `llm_client._to_openai_message`
- Wrote `docs/agent-setup.md` (full setup/usage spec)
- Iterated SYSTEM_PROMPT four times (search strategy, mandatory schema/query rules, worked example)
- Trimmed token footprint: SYSTEM_PROMPT 1,600 → 681 toks, search cards stripped, schema options 100 → 20
- Added debug logging in `ask.py`
- Added 2 eval questions to `data/eval/agent_questions.yaml`, rebuilt baseline (17 questions)
- Added provider/model recommendations to `docs/agent-setup.md`

## What didn't work (and why)
OpenAI models (gpt-4-turbo AND gpt-4o) consistently:
1. Make 2-3 searches, conclude "nothing matches", call end_turn
2. Ignore "MUST call get_dataset_schema before concluding" directives
3. Ask permission ("would you like me to fetch?") instead of fetching

Anthropic Claude was NOT tested live (no key available in session). Expected to work correctly based on the prompt structure.

## Three deferred items — all in BACKLOG.md

1. **Code-level query guardrail** — inject synthetic user turn if end_turn fires without query_dataset_data. `app/services/agent.py::run_agent()`. ~20 lines. Needed for OpenAI compat.

2. **Restore search limit 10 → 6 revert** — AMG159E (regional unemployment) is at position 7 in baseline; limit=6 hides it. Revert `_handle_search_datasets` and TOOLS default. 2-line change.

3. **FTS ranking: "județe" buries topic matches** — LOC108B tops every query containing "judete". Needs FTS tuning or query pre-processing to weight indicator terms over geo qualifiers. Also affects catalog page. Bigger job.

## Recommended next session order
1. Restore search limit (trivial, 2 lines)
2. Add code-level guardrail (~20 lines, deterministic fix)
3. Test with Anthropic key to confirm clean behavior
4. FTS ranking fix (separate session, bigger scope)
