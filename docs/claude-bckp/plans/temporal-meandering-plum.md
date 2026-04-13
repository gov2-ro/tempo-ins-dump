# Commit LLM Agent Step 2

## Context

Step 2 of the LLM Tooling roadmap is implemented in the working tree but uncommitted.
Offline plumbing has been verified (all 4 tool handlers, disabled-mode 404, app mounts cleanly).
Before taking the next task (chat UI / double-counting fix / MCP Step 3), we want a clean
commit that captures exactly Step 2 — nothing more — so the live end-to-end test runs
against a stable baseline and any follow-up work has a clear diff boundary.

## Scope

Stage and commit **only** these 7 paths:

**New files:**
- `app/services/llm_client.py` — provider abstraction (Anthropic + OpenAI)
- `app/services/agent.py` — tool registry, system prompt, `run_agent()` loop
- `app/routers/ask.py` — `POST /api/ask`, 404 when `ASK_ENABLED` is false

**Modified:**
- `app/config.py` — adds `ASK_ENABLED`, `LLM_PROVIDER`, `LLM_MODEL`, `ASK_MAX_TOOL_CALLS`
- `app/main.py` — mounts `ask.router` under `/api`
- `docs/BACKLOG.md` — marks Step 2 checklist complete, adds follow-ups (double-counting, chat UI, live test, anthropic pinning)
- `docs/activity-history.md` — adds the 2026-04-07 Step 2 entry

**Explicitly excluded:**
- `app/static/js/explore-app.js` — pre-existing unrelated one-word tweak (not ours). Leave in working tree.

## Commit message

```
feat(agent): add user-facing NL→Data agent (Step 2)

- llm_client.py: provider-agnostic complete_with_tools() with Anthropic
  (primary) and OpenAI backends, normalised LLMResponse
- agent.py: 4 tools (search_datasets, get_dataset_schema,
  query_dataset_data, list_categories), bilingual system prompt,
  run_agent() loop with tool_trace, citations, and chart_spec
  attachment for the last queried matrix
- routers/ask.py: POST /api/ask, gated by TEMPO_ASK_ENABLED

Reuses the existing service layer — SQL is never LLM-generated.
query_dataset_data handler mirrors routers/dataset_data.py: legacy
_nom_id column resolution, primary_unit_type-based agg_func, 5k row
cap with truncation detection, auto-retry on 0 rows after stripping
Total filter values.

Disabled by default (TEMPO_ASK_ENABLED=false); endpoint returns 404
until explicitly enabled.
```

## Execution steps

1. `git status` — confirm the 7 paths above are the only ones to commit.
2. `git add` the 7 paths explicitly (do NOT use `git add -A` or `.`, so the
   unrelated `explore-app.js` tweak stays out).
3. `git commit -m "<message above>"` with Claude co-author trailer.
4. `git status` — verify the commit succeeded and the tree is clean
   except for `explore-app.js`.
5. `git log -1 --stat` — sanity-check the commit touched exactly 7 files.

## Verification (post-commit)

- `git log -1 --oneline` → single line summary
- `git show --stat HEAD` → 7 files, no explore-app.js
- App still imports cleanly:
  ```bash
  source ~/devbox/envs/240826/bin/activate
  python -c "from app.main import app; print('OK')"
  ```

## After the commit

Return to the user with the four next-task options from earlier and let them pick:
A. Minimal chat UI for `/api/ask`
B. Double-counting defense in `query_dataset_data`
C. Step 3 — expand dev MCP
D. Something else from backlog
