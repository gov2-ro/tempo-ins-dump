# Activity History

## 2026-04-12 — Monthly/Quarterly Yearly Aggregation Toggle

90 monthly + 27 quarterly datasets previously rendered 200–416 x-axis data points, making charts unreadable. Fixed with two changes:

**Yearly aggregation (explore-app.js)**: For monthly/quarterly datasets, `this.yearlyAgg` defaults `true`. `_aggregateByYear()` groups `TIME_PERIOD` by 4-char year prefix (`2024-01` → `2024`, `1995-Q1` → `1995`), SUM for counts/currency, AVG for percentage/rate/time_unit. A toggle button "Anual" appears in the chart type pill bar (same pattern as Index/Δ%). URL state: `?tagg=0` when user turns it off. IPC102A: 416 months → 35 yearly points.

**Raw monthly zoom (chart-factory.js)**: When user switches to raw monthly view, `dispatchAction({ type: 'dataZoom', start: X })` zooms to last ~5 years (60 periods) by default. `setOption` alone doesn't apply initial start/end — needed `dispatchAction` after render.

## 2026-04-12 — Register POP201A Split Datasets

POP201A (Nascuti vii pe sexe, medii de rezidenta) was missing from the app — the parent parquet doesn't exist in corpus/parquet/ and the splits were unregistered in DuckDB. The split parquets (POP201A_judete/regiuni/macroregiuni) had been generated but the `12-split-datasets.py` DB registration step never completed. Fixed by re-running `python 12-split-datasets.py --matrix POP201A`. Now registered: 3 children in `matrices`, 3 rows in `dataset_splits`, 15 dimension rows across children.

## 2026-04-12 — Large Dataset Handling: Time Windowing + GROUP BY Bypass

Two improvements for datasets too large to render without explicit filtering:

**GROUP BY bypass** (`dataset_data.py`): The 50k-row rejection check is skipped when `group_by` param is present. Aggregated queries (GROUP BY) collapse rows significantly, so the raw-rows rejection no longer applies.

**Server-side time windowing** (`dataset_data.py`): Datasets >500k rows auto-filter `TIME_PERIOD` to the latest N periods that fit within the 50k row budget. Period count estimated as `max(min_periods, int(50000 / rows_per_period))`. For datasets >5M rows, `min_periods=2` to avoid OOM (e.g., POP107D: 21.6M rows → 2-year window ≈ 554k rows scanned). Response includes `time_windowed: true`; frontend shows bilingual notice. Fallback path: if parquet DISTINCT scan OOMs, falls back to metadata `time_year_min/time_year_max`.

**DuckDB memory** (`db.py`): Raised from 200MB to 400MB to support larger parquet scans.

**Frontend** (`explore-app.js`): `_autoApplyTimeWindow()` estimates safe period count and pre-selects recent TIME_PERIOD values before the first fetch. `_showServerTimeWindowNotice()` displays a collapsible amber banner when the server applies windowing.

Verified: SOM101F (1.3M), EXP102J (764k), POP107D (21.6M) all load with time windowing.

## 2026-04-12 — Fix Chart Selector Gaps (Taxonomy Items 3, 4, 5)

Fixed three chart selection issues identified by the taxonomy visual audit:

**Backend (`chart_selector.py`)**:
- Population pyramid eligibility: relaxed `gender_count` threshold from ≤3 to ≤6. INS "Sexe si medii" dims mix gender+residence (Total+M+F+Urban+Rural = 5), making the old threshold too restrictive. 69 datasets now eligible.
- Region/macroregion geo_count: was 0 for non-county geo datasets (coverage profiler only tracked `geo_county_count`). Now falls back to dimension count or known geo level sizes (8 regions, 4 macroregions). Enables choropleth for ~24 region-level datasets.

**Frontend (`explore-app.js` v53)**:
- Default chart type now uses `chart_selector`'s `ranked_charts` recommendation instead of hardcoded `timeChartTypes[0]` = 'line'. Maps backend `bar_vertical` → frontend `bar` alias.
- Added `population_pyramid` to snapshot chart types when both age and gender dims exist.
- Rebuilt eval baseline (1,959 datasets).

**Verified via Playwright**: COM109B (area_stacked ✓), TFA0494 (population_pyramid ✓), PNS101D_regiuni_anual (choropleth+bar ✓), PPA103A_lunar_lei_buc (bar ✓), POP107D (no regression ✓).

## 2026-04-11 — Dataset Shape Taxonomy + Visual Audit

Created `scripts/chart-taxonomy.py` — classifies all 1,958 datasets into 12 shape clusters based on DuckDB metadata (archetype, dims, unit type). Picks 2-3 exemplars per cluster, outputs `docs/chart-taxonomy.md` and `data/eval/chart_taxonomy.json`. `--screenshot` flag takes Playwright screenshots of all 33 exemplars.

**Visual audit findings** (added to `docs/chart-taxonomy.md` Gap Analysis section):
- 71% of datasets (1,386) render suboptimally
- Top 3 issues: choropleth 50k limit (23%), cluttered high-cardinality lines (27%), wrong chart type for percentage data (15%)
- Population pyramid, categorical snapshot, and geo snapshot clusters all picking wrong chart types
- Backlog updated with 5 prioritized chart_selector fixes

## 2026-04-11 — Analytical Chart Modes (Index, YoY, Ranking, Distribution)

Added 4 pure-frontend chart transform modes to the Lens UI:
- **Index/Rebase**: divides each series by first value × 100, enables cross-scale comparison
- **YoY Δ%**: year-over-year percentage change, highlights growth vs contraction
- **Ranking/Bump**: inverted Y-axis with rank positions over time (capped 15 series)
- **Distribution strip**: box plot + jitter scatter for geographic spread in snapshot panel

Files: `explore-app.js` (v52), `chart-new-types.js` (v29), `chart-factory.js` (v31), `explore.css`.
Transform buttons (Idx/Δ%) appear in time panel toolbar. Ranking added to chart type picker when ≥3 series. Distribution strip auto-renders below choropleth snapshot.

## 2026-04-11 — View Profile Orphan Cleanup

Deleted 676 orphan view-profile JSON files from `data/corpus/view-profiles/` that had no corresponding parquet file in `data/corpus/parquet/`. These accumulated from removed/split datasets. Remaining: 3,509 VPs matching 3,706 parquets (some parquets have no VP yet — filled via `generate_view_profiles.py`).

## 2026-04-11 — BYOK (Bring Your Own Key) for ask.html

Added per-user API key support to the `/ask.html` chat UI. Users can set their own Anthropic or OpenAI key via a gear icon settings panel in the topbar. Key stored in `localStorage` only — never persisted server-side.

**Frontend** (`ask.html`, `ask.js`): gear icon in topbar opens a dropdown panel with provider select, model input, and password key input. Save/Clear buttons. `🔑` badge on gear when key active. Key included in request payload via `byokPayload()` helper only when set.

**Backend** (`ask.py`, `agent.py`, `llm_client.py`): `AskRequest` extended with optional `provider`, `model`, `api_key` fields. Gate logic updated to allow requests with `api_key` even when `TEMPO_ASK_ENABLED=false`. `api_key` threaded through `run_agent()` → `complete_with_tools()` → SDK constructors (`anthropic.Anthropic(api_key=...)` / `openai.OpenAI(api_key=...)`). `None` key preserves existing env-var behavior.

## 2026-04-11 — URL state persistence for index.html (explore-app.js)

Implemented full URL state persistence in `explore-app.js` (the actual current UI, loaded by `index.html`). Pages are now shareable/bookmarkable with chart type, period, and filter state encoded in the URL.

**Params:** `?code=POP107D&tchart=bar&schart=grouped_bar&period=2022&filters={"COL":"val"}`  
- `tchart` — time panel chart type (omitted if default `line`)  
- `schart` — snapshot panel chart type  
- `period` — snapshot period ID (omitted if latest)  
- `filters` — JSON flat object of active filter selections  

**Writing** — `_syncURL()` calls `history.replaceState()` after every `fetchAndRender()`, chart type button clicks, manual period navigation, and when play stops. Skips `replaceState` during animation (play interval active) to avoid rapid calls.

**Restoration** — `init()` reads `tchart/schart/period/filters` into `_url*` fields. Applied in `showDashboard()` after `panelSetup` is computed (so available chart types are known). Each param is consumed (set to null) after first use. Filters are applied in `renderFilters()` via `_urlFilters` fallback, consumed at end of first `fetchAndRender()`.

Note: previous session had implemented this for `dataset-page-v2.js`/`dataset.html` which is not linked from the main app. That work is superseded by this.

## 2026-04-11 — URL state persistence for dataset page (SUPERSEDED)

`?code=`, `view=`, `chart=`, `period=`, `filters=` now all written via `replaceState` on every render and restored on page load. Pages are fully shareable/bookmarkable.

**Writing** — `_syncURL()` called after every `fetchAndRender()` and on tab switches. Builds `filters` as JSON of `controlsPanel.getValues()` (time column excluded — stored as `period`).

**Restoration** — `init()` reads all params into `_urlView/Chart/Period/Filters`. View is applied immediately in the initial `switchView()` call. Chart type is restored before `renderChartSelector()` so the active button renders correctly (bug fix: initial code restored after render, making the active button wrong). Handles both primary `chart_type` and toggle variants (`toggles[]`). Filters passed as `initialValues` to `ViewControlsPanel` constructor, overriding computed defaults in `resolveDefault()`.

**Files modified:**
- `app/static/js/dataset-page-v2.js` — `_syncURL()`, URL param reading, restoration logic
- `app/static/js/view-controls.js` — `initialValues` constructor param + `resolveDefault()` override

Verified with Playwright: direct URL load restores Snapshot tab + H-Bar chart + single age group filter correctly.

## 2026-04-11 — Chat UI for /api/ask + OpenAI query guardrail

**Chat UI (`app/static/ask.html` + `app/static/js/ask.js`)**

New page at `/ask.html` with a full multi-turn chat interface for the NL→Data agent. Features: multi-turn history (user/assistant turns passed back to `/api/ask`), markdown-lite rendering (bold, code, lists, headings), citation pills linking to dataset pages, amber warnings banner, collapsible tool trace, data table (up to 200 rows with sticky headers), and auto-chart for line/bar/area primary chart types via inline eCharts. Empty state with 5 example questions. "Ask" link added to main topbar.

**Query guardrail (`app/services/agent.py`)**

One-shot guardrail in `run_agent()`: when the model hits `end_turn` without ever calling `query_dataset_data` but search returned results, injects a synthetic `user` turn forcing schema + query. Fires once per run max (`_guardrail_fired` flag). Targets OpenAI models that ignore the system prompt directive; Anthropic models never trigger it.

**Files modified/created:**
- `app/static/ask.html` — new chat page
- `app/static/js/ask.js` — chat logic
- `app/static/index.html` — "Ask" link in topbar
- `app/services/agent.py` — query guardrail

## 2026-04-10 — FTS relevance ordering fix + agent search limit restored

**FTS ordering fix (`app/services/dataset_search.py`)**

`search_datasets()` was using FTS only as a candidate filter (`WHERE matrix_code IN (…)`) then re-sorting by `ultima_actualizare DESC`, which discarded all BM25 relevance signal. When `q` is provided and FTS succeeds, and `sort='updated'` (the default), the function now orders by `list_position(ARRAY[...ranked codes...], m.matrix_code) ASC` — preserving the BM25 relevance ranking exactly. Explicit sort overrides (`sort='name'`, `sort='rows'`) are unaffected.

Result: massive improvements across all 17 eval questions. Notable fixes:
- "populatie pe judete": LOC108B (construction permits) was #1 → now POP108D/POP107D at #1-2
- "exporturi pe tari": TUR105F (tourism) was #1 → now INT106B/EXP101I at #1-2
- "accidente de munca": AMG130M (unemployment) was #1 → now ACC102B (accidents) at #1
- "energia electrica": now IND118A (electricity production) leads, not export datasets
- "cheltuieli educatie buget": now CAV101C (education-specific) leads

Baseline rebuilt and committed: `data/eval/agent_search_baseline.json`.

**Agent search limit restored (`app/services/agent.py`)**

Tool schema default and `_handle_search_datasets` limit both reverted from 6→10. AMG159E (regional unemployment, the best geo dataset for "rata somajului") was sitting at position 7 and getting cut off. Token overhead is minimal (~200 toks/search × 3 searches).

**Files modified:**
- `app/services/dataset_search.py` — FTS ordering via `list_position()`
- `app/services/agent.py` — limit 6→10 in schema + handler
- `data/eval/agent_search_baseline.json` — rebuilt from improved search

## 2026-04-09 — Agent spec doc, OpenAI provider bugfix, search strategy hardening

First end-to-end test of `POST /api/ask` after Step 2/3b. Three fixes and one new doc.

**New doc: `docs/agent-setup.md`**

Full setup + usage spec for the NL→Data agent: prerequisites (anthropic/openai SDKs, API keys), env var table (`TEMPO_ASK_ENABLED`, `TEMPO_LLM_PROVIDER`, `TEMPO_LLM_MODEL`, `TEMPO_ASK_MAX_TOOL_CALLS`), minimal launch commands for both providers, full API reference for `POST /api/ask` (request/response shape, error codes), worked curl + Python + HTTPie examples, test-question bank (EN/RO + edge cases), tool-trace inspection snippet, and limitations. The agent was previously undocumented — config-only.

**Bugfix: `_to_openai_message` in `app/services/llm_client.py`**

OpenAI provider crashed on the second tool-calling iteration with `KeyError: 'name'`. Root cause: `_assistant_turn` produces an assistant message where `tool_calls` are *already* in OpenAI's `{id, type, function: {name, arguments}}` shape, but `_to_openai_message` tried to re-format them using our internal `{id, name, input}` shape — so it accessed `tc["name"]` on a dict that only has `tc["function"]["name"]`. Also fixed a related bug: `msg.get("text")` → `msg.get("content")` (the assistant message stores text under `"content"`). Fix: just pass `msg["tool_calls"]` through as-is.

Only affected OpenAI provider (default is Anthropic), so it slipped through the initial Step 2 testing.

**Agent search strategy hardening**

First curl test ("unemployment rate in Romania by county for 2023") exposed that the agent:
- Called `search_datasets` exactly once with the full verbose query + `has_geo=true`
- `has_geo=true` excluded AMG157G (national, best match — `has_geo=false`)
- Got fertility (POP203C) and tourism (TUR109C) as top hits
- Gave up without retrying, without `get_dataset_schema`, without querying data

Baseline investigation confirmed the FTS ranker is actually fine: "What is the unemployment rate by county in 2023?" ranks AMG157G at #1 *without* the `has_geo` filter. The entire failure was caused by the agent's over-eager use of the geo filter.

Rewrote the `SYSTEM_PROMPT` search-strategy section in `app/services/agent.py`:
- Explicit stopword-stripping rule (strip "rate", "by", "in", year numbers)
- "Prefer Romanian keywords on the first search" (dataset names are Romanian)
- **"Do NOT set `has_geo=true` on the first search"** — this was the load-bearing rule
- "Read the entire result list, not just the top hit" — a match at position 7 beats a non-match at position 1
- "Retry at least once if results look unrelated"
- "When user asks for a granularity that doesn't exist, use the closest one and explain" — INS publishes most labor-market indicators at `regiuni de dezvoltare` (8 NUTS-2), not `județe` (42 counties)
- Added a worked example walking through the unemployment query end-to-end

**Eval harness expansion**

Added two regression questions to `data/eval/agent_questions.yaml`:
- "What is the unemployment rate by county in 2023?" (verbose EN w/ stopwords)
- "Care este rata șomajului pe județe în 2023?" (same intent in RO)

Rebuilt `data/eval/agent_search_baseline.json` via `scripts/build_agent_search_baseline.py` → 17 questions total, 3,017 bytes.

**Minor: debug logging in `app/routers/ask.py`**

Added `log.exception("Agent failed")` in the except block so unhandled agent errors now print their full traceback to the uvicorn terminal. Previously the only visible artifact was the short `"Agent error: {e}"` in the 500 response body.

**Files modified:**
- `app/services/llm_client.py` — bugfix in `_to_openai_message`
- `app/services/agent.py` — rewrote search strategy section of SYSTEM_PROMPT + worked example
- `app/routers/ask.py` — traceback logging
- `data/eval/agent_questions.yaml` — 2 new questions
- `data/eval/agent_search_baseline.json` — regenerated
- `docs/agent-setup.md` — new file

**Not done (deferred):**
- Search-side stopword filter in `dataset_search.py` (Layer 3 in plan) — skipped, since the baseline showed FTS ranking is already fine once the agent stops adding `has_geo=true`. Revisit only if the prompt fix alone doesn't close the gap.
- End-to-end re-test of the curl question with updated prompt — requires a live API key; deferred to the user.

---

## 2026-04-08 — Dev MCP: agent search eval + view-profile audit (Step 3b part 2)

Shipped the remaining two eval tools for Step 3b, plus a critical FTS bug
fix uncovered by the first one.

**New tools:**

- `tempo_eval_agent` — search-quality regression detection. Runs
  `search_datasets()` for every question in `data/eval/agent_questions.yaml`
  (15 seed questions covering population, unemployment, inflation, GDP,
  etc.) and diffs the top-K hits against `data/eval/agent_search_baseline.json`.
  Same baseline-diff pattern as `tempo_eval_chart_selector`.
- `tempo_check_view_profiles` — diagnostic audit of `corpus/view-profiles/`.
  Cross-checks against the parquet corpus and DB `matrix_profiles` table to
  surface missing VPs, orphan VPs, schema version drift, archetype
  mismatches, parse errors, and top warning categories.

**New files:**

- `app/services/agent_eval.py` — shared `run_search_eval(questions, top_k)`
  + `diff_against_baseline()` + lightweight YAML loader (falls back to a
  minimal parser if PyYAML isn't installed).
- `scripts/build_agent_search_baseline.py` — baseline generator, same
  compact one-line-per-question format used for `chart_selector_baseline`.
- `data/eval/agent_questions.yaml` — 15 seed questions.
- `data/eval/agent_search_baseline.json` — committed baseline (2.6 KB).

**Search bugs found and fixed while calibrating the eval:**

1. **FTS sort direction was inverted.** `_fts_search()` in
   `dataset_search.py` had `ORDER BY score` (DuckDB default ASC) with
   `LIMIT 200`. BM25 returns *higher* scores for *more* relevant docs, so
   the candidate pool contained the 200 *worst* matches. POP107D/POP108D
   scored 4.93 for `"populatie pe judete"` but were never seen — the top
   200 were scores 0.066-0.086. Fixed to `ORDER BY score DESC`. This is a
   serious production bug: search quality jumps immediately on every query.
2. **Outer `ORDER BY` was non-deterministic.** Many canonical datasets
   share `ultima_actualizare` values (or both are NULL), and there was no
   tie-breaker. Result: same query returned different orderings across
   runs, and the baseline/eval diff was perpetually flaky. Added
   `m.matrix_code ASC` as the secondary sort on every branch of
   `sort_map`. First eval run now reports `ok=15, drift=0` stably across
   repeated runs.

**View-profile audit findings (initial run):**

- 197 parquets in `corpus/parquet/` lack view-profile JSONs — the generator
  needs a re-run to catch up.
- 675 orphan VPs — files for datasets no longer in the corpus.
- 49 archetype mismatches on `PNS101D_*` splits (VP says `geo_time`, DB
  says `geo_only`) — schema drift between the VP generator and the
  classifier.
- 933 VPs carry warnings — top categories: `multi_unit` (490),
  `very_sparse` (230), `sparse_data` (205), `high_cardinality` (78),
  `short_series` (40).

All follow-ups logged in `docs/BACKLOG.md` under dedicated "Search quality"
and "View profiles" sections.

**Step 3 status:** Eval sub-steps complete. Remaining: Playwright frontend
probing and gated mutation tools.

## 2026-04-08 — Dev MCP: chart_selector eval harness (Step 3b)

Added regression-detection for the chart-selection engine. Every dataset is
scored on-demand and diffed against a committed baseline so that changes to
`chart_selector.py` surface concrete drift instead of silent ranking shifts.

**New files:**

- `app/services/chart_selector_eval.py` — shared `_load_inputs()`,
  `evaluate_all(top_n=3)`, and `diff_against_baseline(baseline, current,
  score_threshold)`. Bulk-loads every dim/profile/coverage/trend in one go
  (~1s for the whole corpus) instead of calling `get_dataset_meta` per
  dataset (would be ~20s).
- `scripts/build_chart_selector_baseline.py` — run-once builder that writes
  `data/eval/chart_selector_baseline.json` (1959 datasets, 290 KB, custom
  compact format with one dataset per line so git diffs stay tight).
- `tools/tempo-dev-mcp/server.py` :: `tempo_eval_chart_selector` — MCP tool
  that loads the baseline, re-runs `evaluate_all()`, and returns a compact
  report: `primary_changes` (full), `top_set_changes` (cap 50),
  `confidence_changes` (cap 30), `score_drifts` (cap 50), `missing`/`added`
  (cap 30). Uses the same `evaluate_all()` as the build script so baseline
  generation and diffing are guaranteed in lock-step.

**Non-determinism bug fixed:** the first baseline showed `ACC102C`'s top-3
chart set flipping between `[…, horizontal_bar]` and `[…, stacked_bar]` on
re-runs. Root cause: `_load_inputs`'s per-dimension `dim_type` majority-vote
query had no tie-breaker on `COUNT(*) DESC`, so DuckDB returned tied rows in
arbitrary order. `ACC102C`'s `UNIT_MEASURE` dim has exactly one option parsed
as `unit` and one as `indicator` — a perfect tie.

Fix: add `MIN(dopt.option_offset) ASC` as the secondary sort. This matches
the runtime `dataset_meta.py:172` behavior, where `max(type_counts,
key=type_counts.get)` implicitly picks the first-inserted key on ties, and
insertion order there is `ORDER BY option_offset`. Verified ACC102C now
agrees between runtime and eval (`UNIT_MEASURE` dim_type = `unit`, third
chart = `horizontal_bar`).

Five consecutive eval runs after the fix report `ok=1959, drift=0`.

**To refresh the baseline after an intentional `chart_selector.py` change:**

    python scripts/build_chart_selector_baseline.py
    # then inspect `git diff data/eval/chart_selector_baseline.json`

## 2026-04-08 — Agent: fix double-counting via marginal Total rows

`POST /api/ask`'s `query_dataset_data` tool was double-counting whenever it
aggregated (`group_by`) over a dataset that publishes a marginal `Total` row
alongside its breakdown rows. Phase 8 had only stripped totals from ~49 of
3,600 parquets, so the bug was latent on the rest.

**Fix** (in `app/services/agent.py`):

- New helper `_detect_total_locks(matrix_code, dimensions, filters, group_by, conn)`
  scans the parquet directly. For each dim that is neither in `group_by` nor in
  `filters`, it issues a `SELECT DISTINCT col WHERE LOWER(TRIM(col))='total'`. If
  any rows come back, that dim is eligible to be auto-locked to its Total value.
  `TIME_PERIOD` is never locked. Datasets without a parquet (parents of split
  datasets like `AMG1010`) return `{}` cleanly.
- `_handle_query_dataset_data` now runs the locked query first when `group_by`
  is set:
  - **Locked query non-empty** → use it, emit
    `Auto-applied Total filters to prevent double-counting: COL=val, …`.
  - **Locked query empty** (non-cross-product marginals — `TFP0512`,
    `AMG1010_*`) → fall back to the unfiltered query and emit a loud
    `POSSIBLE DOUBLE-COUNTING: …` warning with a concrete re-query suggestion
    (e.g. `filters={'SEX': ['Total']}`). The LLM can then self-correct.
- System-prompt section *"Total" rows and double-counting* rewritten to teach
  the LLM the two warning shapes and how to react.

**Verification:**

| Dataset | Query | Before | After |
|---|---|---|---|
| `POP107D` | group_by `[TIME_PERIOD]` | 41.78M (1992) | 41.78M, no warning (parquet pre-stripped, fix is no-op) |
| `FOM104G` | group_by `[TIME_PERIOD]` | **28.25M** (2023, ~5.3× too high) | **5.36M**, warning lists the 3 auto-locked dims |
| `FOM104G` | group_by `[TIME_PERIOD,SEX]` | broken | 2.79M Masculin + 2.57M Feminin = 5.36M ✓ |
| `FOM104G` | filter `SEX=Masculin`, group_by `[TIME_PERIOD]` | broken | 2.79M (auto-lock respects user filter) |
| `TFP0512` | group_by `[TIME_PERIOD]` | inflated SUM | inflated SUM **+ POSSIBLE DOUBLE-COUNTING warning** with re-query hint |

**Design choices / non-obvious bits:**

- Detection runs against the parquet, not metadata. Reason: `dimension_options.option_label`
  has trailing-whitespace artefacts (`'Total '`) and `sdmx_codes.sdmx_value` may
  not match the parquet's literal value. Querying the parquet is authoritative
  and avoids the metadata→parquet normalization mismatch.
- Detection cost is one `DISTINCT … WHERE` per candidate dim. For typical
  4-dim datasets that's 2-3 extra queries (~50ms each on the corpus parquets).
  Skipped entirely when `group_by` is empty or no candidate dims exist.
- Only TRIM/LOWER='total' is treated as a marginal-total marker. Variants like
  `'Total persoane'` or `'Industrie - total'` are intentionally NOT matched —
  those are standalone categories, not aggregates of other rows.
- `TIME_PERIOD` is excluded from candidates: time can never be a "Total".

**Known follow-up** (added to `docs/BACKLOG.md`): the pre-existing
0-rows-strip-Total fallback can still hide an explicit Total filter when the
parquet really has no `(Total, Total, …)` cross-product cell (TFP0512 case).
Fix is to only strip a dim's Total filter when the parquet has no Total for
that dim.

**Files modified:**

- `app/services/agent.py` — added `_detect_total_locks`, rewrote the
  aggregation-time guard in `_handle_query_dataset_data`, updated SYSTEM_PROMPT.
- `docs/BACKLOG.md` — checked off the double-counting item under Step 2,
  added the fallback follow-up.

---

## 2026-04-08 — Dev MCP Step 3a: introspection bundle (5 new tools)

Extended `tools/tempo-dev-mcp/server.py` with the introspection half of Step 3
(read-only, no new dependencies). Tools 7–11:

- **`tempo_routes`** — lists every FastAPI route on `app.main:app` with
  methods/path/name/endpoint/tags. API routes sorted before static mounts. Useful
  to verify new routers mounted (e.g. confirms `/api/ask` is present).
- **`tempo_call_endpoint(method, path, params_json?, body_json?)`** — hits any
  route in-process via `starlette.testclient.TestClient`. No live server needed.
  Returns `{status_code, content_type, body, json?}`, body capped to 8000 chars.
  `raise_server_exceptions=False` so 500s come back as a status code rather than
  raising.
- **`tempo_outdated(days=180, limit=50)`** — datasets sorted by `ultima_actualizare`
  age. Returns counts (`fresh / stale / unknown_null`) plus oldest and null
  samples. Bundles a caveat about the underlying column being unreliable
  (already tracked under "Data Pipeline" in BACKLOG). Confirmed real numbers:
  1959 total, 453 fresh, 1505 stale (>180d), 1 null.
- **`tempo_pipeline_status(recent_log_count=10)`** — reads
  `data/logs/last-pipeline-run.txt`, parses `data/logs/corpus-audit.json`, lists
  the most recently-modified `*.log` files with mtime/size and ERROR/WARNING
  counts. Logs ≥2 MB skipped to keep response fast.
- **`tempo_dataset_lineage(matrix_code)`** — for one matrix, walks 5 pipeline
  stages (`metadata_json`, `raw_csv`, `parquet_v2`, `corpus_parquet`,
  `view_profile`) reporting presence/size/mtime, plus DuckDB row presence in
  `matrices`/`matrix_profiles`/`dataset_coverage`/`dataset_trends`/
  `dataset_value_profiles`, plus split children and parent.

**Notes / gotchas hit:**
- DuckDB won't bind a parameter into `INTERVAL ? DAY`. Inlined the int (already
  validated) instead of using a placeholder.
- `@mcp.tool()` does not wrap the function — it just registers it on the
  FastMCP instance and returns the original. Direct Python imports can call the
  tools verbatim, no `.fn`/`.__wrapped__` needed.

**Verification:** all 5 tools smoke-tested via direct Python import (the MCP
server itself needs a Claude Code restart to surface them as
`mcp__tempo-dev__tempo_*`). Verified happy paths (real route list,
`/api/categories` 200, `/api/datasets/POP107D` 200, real outdated counts,
real lineage for `POP107D` and split-child `ACC102B_judete_numar_persoane`)
plus error path (`tempo_dataset_lineage("NONEXISTENT")` → clean error).

**Files modified:**
- `tools/tempo-dev-mcp/server.py` — +330 lines (5 new `@mcp.tool()` functions).
- `tools/tempo-dev-mcp/README.md` — added sections 7–11, bumped tool count to 11.
- `CLAUDE.md` — extended Dev MCP table with the 5 new tools.
- `docs/BACKLOG.md` — checked off the introspection rows under Step 3.

**Deferred (still under Step 3):** chart_selector / agent eval harness, Playwright
frontend probing, gated mutation tools.

---

## 2026-04-07 — LLM Agent Step 2: v1 user-facing NL→Data agent

Built `POST /api/ask` tool-calling agent on top of the existing service layer.
Gated by `TEMPO_ASK_ENABLED` (disabled by default). LLM never generates SQL —
all data access goes through `query_builder.build_data_query()`.

**New files:**
- `app/services/llm_client.py` (~190 lines) — provider-agnostic `complete_with_tools()`
  returning a normalised `LLMResponse{stop_reason, text, tool_calls}`. Supports
  Anthropic (primary, SDK 0.89.0) and OpenAI backends with shared message/tool
  format translation helpers.
- `app/services/agent.py` (~390 lines) — 4 tools (`search_datasets`,
  `get_dataset_schema`, `query_dataset_data`, `list_categories`), ~2.3k-char
  system prompt (bilingual workflow, Romanian vocabulary cheatsheet, "Total"
  gotcha), `run_agent()` loop (max 8 iterations, dispatches tool calls,
  accumulates `tool_trace`, attaches `chart_spec` from `chart_selector` for the
  last queried matrix).
- `app/routers/ask.py` (~35 lines) — POST `/api/ask` endpoint, returns 404 when
  disabled, 500 on agent error.

**Modified files:**
- `app/config.py` — added `ASK_ENABLED`, `LLM_PROVIDER`, `LLM_MODEL`,
  `ASK_MAX_TOOL_CALLS` environment flags.
- `app/main.py` — mounted `ask.router` under `/api`.

**Key design decisions:**
- Agent reuses the existing shared service layer (`dataset_search.py`,
  `dataset_meta.py`, `query_builder.py`) — same code paths as the FastAPI
  routes and the dev MCP server.
- `query_dataset_data` handler mirrors `routers/dataset_data.py`: legacy
  `_nom_id` column resolution, `primary_unit_type`-based agg_func
  (SUM/AVG), 5k row cap with `limit+1` truncation detection, and auto-retry
  after stripping `Total`/`TOTAL` filter values when a query returns 0 rows.
- Anthropic provider packs all tool results in a single `user` turn; OpenAI
  uses individual `tool` messages — `run_agent()` branches on
  `config.LLM_PROVIDER` to produce the right shape.
- `chart_spec` is not built per-query during the loop — only attached once
  after `end_turn` for the last queried matrix (avoids repeated work).

**Verified offline (no API key required):**
- `TOOLS` schema validation, `SYSTEM_PROMPT` contains required vocabulary
- `search_datasets("somaj pe judete")` → 200 hits; `search_datasets("unemployment")` → 9 hits
- `get_dataset_schema("POP107D")` → 6 dims, values capped correctly
- `query_dataset_data("POP107D", group_by=["TIME_PERIOD"])` → 34 rows, SUM agg
- Auto-retry: `POP107D` with `SEX=Total` filter → 0 rows → retry without filter → 34 rows + warning
- `list_categories()` → 339 entries (levels 0–2 only, filtered from ~200k)
- Disabled endpoint returns 404 with `{"detail": "Ask endpoint is disabled"}`
- App mounts cleanly with `/api/ask` in the route list

**Bug fixed during implementation:**
- `_handle_list_categories` used the wrong column names (`code`, `name`,
  `parent_code`) — actual schema is `context_code`, `context_name`,
  `parent_code`, `level`. Fixed + filtered to levels ≤ 2 to avoid dumping
  the entire category tree into the prompt.

**Still pending:**
- Live end-to-end test with a real `ANTHROPIC_API_KEY` (offline plumbing
  verified; LLM loop itself not exercised yet).
- Dependency pinning: `anthropic>=0.40` should be added to `requirements.txt`.
- Optional: a tiny chat UI for `/api/ask` — currently only curl-testable.

**How to run live test:**
```bash
source ~/devbox/envs/240826/bin/activate
TEMPO_ASK_ENABLED=true ANTHROPIC_API_KEY=... \
  uvicorn app.main:app --reload --port 8080

curl -s -X POST localhost:8080/api/ask \
  -H 'Content-Type: application/json' \
  -d '{"question": "Care este populația Clujului în 2023?"}' | jq
```

## 2026-04-07 — MCP corpus quality fixes: geo fallback, unit classifier, chart selector

Three fixes targeting classification/profiling gaps that cascaded into wrong chart selection:

**Fix 1: chart_selector.py — geo_count NULL fallback** (`app/services/chart_selector.py:67-76`)
- When `geo_county_count` is NULL in coverage data but `has_geo=True` and `geo_levels` contains 'county', now falls back to dimension option_count (or 42, Romania's county count)
- Fixes choropleth eligibility for parent/sparse datasets like LOC108B

**Fix 2: 11-coverage-profiler.py — geo stats when no parquet** (`11-coverage-profiler.py:172-185`)
- Added `else` branch: when no parquet exists, geo stats (county count, national/locality flags) are estimated from `dimension_options_parsed` metadata using `dim_nids` lookup
- LOC108B: `geo_county_count` now correctly shows 42 (was NULL)

**Fix 3: 10-classify-dimensions.py — expanded unit recognition** (`10-classify-dimensions.py:82-200`)
- Expanded `UNIT_MAP` with ~30 new entries: physical units (litri, kilograme, grame, mp, m2, m3, mii litri, mii m3), count variants (perechi, capete, mii capete, familii, gospodarii), energy (kwh, mwh, gwh, gigacalorii), distance, etc.
- Added `UNIT_KEYWORDS` regex fallback after exact-match fails — 10 patterns covering lei/euro/currency, procent, weight, volume, area, distance, energy, time, index, count
- Remaining 172 unknowns are genuinely composite/unusual strings (e.g. "lei preturile anului curent", "echivalent norma intreaga")

**Verification:**
- Re-ran `10-classify-dimensions.py` and `11-coverage-profiler.py` on full corpus
- `tempo_dataset_info("LOC108B")`: `coverage.geo_county_count = 42`, `chart_selector.primary_chart = choropleth (score 0.85)`
- `tempo_catalog_stats(group_by="unit_type")`: unknown=172 (stable; remaining unknowns are truly composite)

## 2026-04-07 — MCP v2: query tool, catalog stats, FTS search

**MCP v1 documentation:**
- Created `tools/tempo-dev-mcp/README.md` — full documentation for all tools with parameters, return shapes, examples, architecture, and limitations
- Expanded CLAUDE.md MCP section with parameter signatures for all tools

**New MCP tools (v2):**
- `tempo_query(matrix_code, filters?, group_by?, limit?)` — aggregated data queries wrapping `query_builder.build_data_query()`. Auto-picks agg function (AVG for percentage/time_unit, SUM otherwise). Returns columns, rows, row_count, and the generated SQL.
- `tempo_catalog_stats(group_by?)` — corpus-level breakdowns by archetype/category/unit_type/geo/time_granularity. Shows 1,225 canonical datasets across 5 archetypes.

**FTS search upgrade:**
- Created `scripts/build-search-index.py` — builds a sidecar `data/corpus/search.duckdb` (14 MB, ~2s) with DuckDB FTS over matrix names (RO+EN), 92k bilingual tags, definitions, and category paths.
- Updated `app/services/dataset_search.py` — FTS-first strategy with LIKE fallback. Sidecar connection cached as lazy singleton.
- Before: "unemployment rate" → 0 results. After: → 130 results matching through English tags and definitions.
- Before: "somaj" → 9 results (name match only). After: → 61 results (matches tags and definitions too).
- FTS uses `stemmer='none'` — Romanian morphology not handled; "populatia" won't match "populatie". Planned for v3 with embeddings.

**Key decisions:**
- Sidecar DB (`search.duckdb`) avoids write-lock conflicts with `metadata.duckdb`. Read-only at runtime.
- `tempo_query` never generates SQL from LLM input — wraps the existing safe `build_data_query()`.
- Category stats show 71 datasets without ancestor_codes (split sub-datasets) — acceptable for v2.

## 2026-04-07 — Step 1: Service layer extraction + tempo-dev MCP server

**Service layer refactor:**
- Extracted `search_datasets()` → `app/services/dataset_search.py` (from `app/routers/datasets.py:list_datasets`)
- Extracted `get_dataset_meta()` → `app/services/dataset_meta.py` (from `app/routers/datasets.py:get_dataset`)
- Route handlers now thin wrappers — same API behavior, verified via curl
- Both services accept optional `conn=` param for DuckDB cursor injection (defaults to `get_conn()`)

**MCP server (`tools/tempo-dev-mcp/server.py`):**
- 4 tools: `tempo_dataset_info`, `tempo_search_datasets`, `tempo_chart_signature`, `tempo_sample`
- Uses official `mcp` Python SDK (FastMCP), stdio transport
- Registered in `.mcp.json` at repo root (repo-local, auto-loaded by Claude Code)
- All tools import from the shared service layer — no duplicated logic

## 2026-04-07 — LLM Tooling Plan (dev MCP + NL→Data agent)

Designed a 4-step hybrid roadmap for adding LLM capabilities to the project. Plan stored at `~/.claude/plans/peppy-fluttering-bubble.md`.

**Architectural decisions:**
- **Not literal NL2SQL.** With 3,632 different parquet schemas, the hard problem is "which parquet + which columns," not "what SQL." A tool-calling agent over the existing safe `query_builder.build_data_query()` is the right shape — SQL is never LLM-generated.
- **Dev MCP first.** A separate `tempo-dev` MCP server compounds across every future Claude Code session. Refactoring to extract `dataset_search.py` + `dataset_meta.py` is the shared substrate for both the MCP and the user-facing agent — one refactor, three reuses (MCP, agent, existing UI route).
- **Hybrid build order:** minimal MCP (4 tools) → v1 user agent → expand MCP (informed by v1's friction) → v2 features.
- **Provider abstraction** via `app/services/llm_client.py` (Anthropic + OpenAI), swappable through `TEMPO_LLM_PROVIDER` env var.
- **DuckDB FTS in sidecar** `data/corpus/search.duckdb` to avoid the metadata.duckdb write-lock.
- **Chart selection stays rule-based** — agent never picks chart types; `chart_selector.select_charts()` is called after the agent settles on data.

Backlog updated with the full task breakdown for Steps 1–4. Implementation starts with Step 1 (extract services + minimal MCP server).

## 2026-04-07 — Split Dataset Metadata Propagation

**Fixed split sub-datasets missing from "Actualizate recent" and lacking "Despre" panel:**
- Root cause: split children (e.g. `LOC108C_numar`) have `is_canonical=TRUE` but `ultima_actualizare=NULL` and `definitie=NULL` — they never inherited metadata from their parent
- Added `propagate_split_metadata()` in `update-pipeline.py`: copies `ultima_actualizare`, `definitie`, `metodologie`, `observatii` from parent matrix to all split children via `dataset_splits` JOIN
- Runs automatically after `sync_ultima_actualizare()`; also available standalone via `python update-pipeline.py --propagate-splits`
- Applied one-time fix to existing DuckDB: canonical 2026 dataset count went from 8 → 38
- English `definitie` was already handled correctly — `_load_en_meta()` in `datasets.py` falls back to parent code for splits

**Fixed TEMPO Online link for split datasets:**
- `explore-app.js`: INS link now uses `m.parent_matrix_code || m.matrix_code`, so split variants like `LOC108C_numar` link to `ind=LOC108C` on statistici.insse.ro instead of a broken URL

## 2026-04-06 — Update Pipeline Improvements

**Fixed stale "Actualizate recent" on landing page:**
- Root cause: `10-import-metadata.py` fails with `lang` column schema mismatch (tracked in backlog), so `matrices.ultima_actualizare` in DuckDB was never refreshed after pipeline runs
- Added `sync_ultima_actualizare(codes, lang)` in `update-pipeline.py` — reads `ultimaActualizare` from freshly fetched metadata JSONs and directly updates DuckDB; runs after every pipeline execution regardless of `10-import-metadata.py` success

**Incremental run tracking:**
- Added `data/logs/last-pipeline-run.txt` marker — written after each successful run
- `update-pipeline.py` now auto-applies `--since {last_run_date}` when no explicit `--since` given, so re-running the script daily only processes genuinely new matrices
- New flags: `--force-meta` (re-fetch metadata JSONs without re-downloading CSVs/parquets), `--all` (ignore last run date)

**Quieted verbose pipeline output:**
- `12-split-datasets.py`: per-matrix progress lines moved to DEBUG (only visible with `--debug`); summary totals remain at INFO
- `generate_view_profiles.py`: JSON profile dump now only prints with `--debug` flag

## 2026-04-06 — Theme Icons, INS Link, UI Polish

**Category section theme icons:**
- Replaced category emojis with transparent PNGs from `app/static/img/themes/`
- Icons bottom-aligned with section header text, naturally rising above via flex layout
- Mapping: society (A), economy (B), environment (E), transport (F), sustainable development (G+H)
- Subcategory left indent removed for cleaner alignment

**Dataset header:**
- Added "INS ↗" link to official TEMPO Online page (`statistici.insse.ro/tempoins/...?ind={code}`) next to download buttons
- Link respects current UI language (ro/en)

## 2026-04-06 — Landing Redesign, Downloads, UI Polish

**Landing page redesign:**
- Replaced hero section with compact header + themed KPI cards (Czech CSO style)
- KPI cards: real values from parquet (salary, GDP, tourism arrivals, etc.) with sparklines + YoY change
- Category grid switched to CSS columns layout with emoji icons, inline subcategories, bold stats
- Notice bar (dismissable, "not official gov.ro"), permanent footer with GitHub link
- OS `prefers-color-scheme` theme detection (defaults to light)
- OG/SEO meta tags: description, og:image, twitter:card — domain `ins.gov2.ro`

**Data download (CSV / XLSX):**
- New `GET /api/datasets/{code}/download?format=csv|xlsx&filters=...&lang=ro|en` endpoint
- On-the-fly generation from parquet via DuckDB + stdlib csv / openpyxl (no pandas)
- Language-aware: when `lang=en`, translates dimension values via `sdmx_codes` table
- Download buttons (↓ CSV / ↓ XLSX) in dataset header; pass active filters + current lang at click time

**SDMX endpoints** (already existed, confirmed working):
- `GET /sdmx/2.1/data/INS,{flow}/{key}` — SDMX-ML 2.1 GenericData XML
- `GET /sdmx/2.1/datastructure/INS/{flow}/1.0` — DSD with codelists
- `GET /sdmx/2.1/dataflow/INS/{flow}/1.0` — Dataflow definition

**Other UI improvements:**
- Dataset code badge in title (accent-colored, replaces meta-pill)
- `?lang=en` URL parameter — opens app in English (useful for sharing with international users)

## 2026-04-04 — Alpha Preview & UI Polish

Prepared alpha preview with multiple UI/UX improvements across the Lens dashboard.

**Insight cards redesign:**
- Replaced meaningless Average card with **Overall Change** (first→last period % change, colored +/-)
- Replaced meaningless Range card with **Coverage** (period count + category count)
- Replaced div-bar sparkline with **SVG polyline** sparkline (`viewBox` + `preserveAspectRatio="none"` + gradient fill polygon)
- Fixed `--text-3` CSS variable (undefined, causing transparent backgrounds in 8+ places)

**Tooltip totals:**
- All multi-series charts (line, area, stacked bar) now show ∑ total on top of tooltip before series breakdown
- Updated formatters in both `chart-factory.js` and `chart-new-types.js`

**Data table enhancements:**
- Added dropdown column filters (like duckdb-browser) with active state styling
- Zebra striping, sticky filter row, filtered/total row count display
- Client-side filtering via exact string match, all filters AND-combined

**Landing page:**
- Redesigned `index.html` as a public-facing landing page (old version preserved as `index-old.html`)
- Added language flag icons (EN/RO SVGs)

**Deployment:**
- Merged `claude/deploy-flyio-uvicorn-7MxCw` branch — updated paths for `corpus/` data layout
- Added deploy scripts: Oracle Cloud (`deploy.sh`, nginx config, systemd service), HF Spaces (`Dockerfile`)
- Updated `fly.toml` with corpus-aware `TEMPO_DATA_DIR`

## 2026-04-03 — Chart Selection Engine v2

Comprehensive overhaul of `app/services/chart_selector.py` scoring engine.

**Unit-type awareness:**
- Signature now includes `primary_unit_type` and `unit_types` from matrix_profiles
- Percentage data strongly prefers `area_stacked` (parts-of-whole visualization)
- Index/rate data boosts `line` chart (continuous trends are meaningful)
- Currency/count data gives small bonus to comparison bars and bubble charts
- Index data penalizes `bar_vertical` (bar heights misleading for base-100 values)

**Scoring rebalancing:**
- `bar_vertical` base lowered from 0.5 to 0.45, penalized for long time series (>=10 pts: -0.15)
- `area_stacked` base raised from 0.3 to 0.4, big boost for percentage+small-series data
- Seasonal data: line gets +0.15 (was +0.05), bar_vertical gets -0.10
- Sparse data penalties added to area_stacked (-0.15), stacked_bar (-0.10), small_multiples (-0.10)

**Confidence scoring:**
- Each recommendation now includes `confidence` (high/medium/low) based on score gap to runner-up
- Complementary chart pairs annotated (e.g., choropleth ↔ line, pyramid ↔ line)

**Deterministic tie-breaking:**
- When scores tie, specific/informative charts win (choropleth > line > bar_vertical > table)

**Smarter role assignment:**
- `assign_roles()` now returns `filter_hints` (single_select/multi_select/pill_group per dim)
- `defaults` dict with recommended initial filter state (e.g., time='latest', exclude_total=True)
- Line series selection prefers 2-6 option dims over raw minimum cardinality
- Stacked charts prefer stackable (2-6 option) dims for series role

**Eliminated recursive scoring bug** — horizontal_bar and bubble no longer call `_score('choropleth', ...)` to cap themselves; use explicit score ceilings instead.

**Synced** explorer/services/chart_selector.py. Updated test_chart_selector.py with unit-type distribution and confidence reporting.

## 2026-04-02 — Static Site Migration Plan

Designed and scaffolded a static website architecture to replace the FastAPI backend.

**Approach:** DuckDB-WASM for client-side parquet queries + pre-built static JSON for metadata. Zero server at runtime.

**Created:**
- `docs/plans/static-site-migration.md` — Full architecture plan with phased migration path
- `build-static-site.py` — Build script that exports DuckDB metadata → static JSON (categories, dataset index, per-dataset metadata with chart configs)
- `static-site/` — Frontend scaffold:
  - `index.html` — SPA shell (Vue 3 + ECharts + Fuse.js)
  - `js/duckdb-data-client.js` — DuckDB-WASM integration (replaces `query_builder.py`)
  - `js/api-static.js` — Static API client (replaces `app/routers/` endpoints)
  - `js/app.js` — App bootstrap with reactive store
  - Stub files for charts and components (to be ported from `explorer/` in Phase 3)

**Key decisions:**
- DuckDB-WASM queries parquet via HTTP range requests (no full file download)
- Chart selector runs at build time (pre-computed in meta JSON, not ported to JS)
- Fuse.js for client-side fuzzy search (~400KB index)
- Target hosting: Cloudflare Pages + R2 (free tier)

## 2026-03-28–29 — Lens Observatory UI

Built the Lens dark-themed data observatory (`app/static/explore.html`):
- Category grid with trend indicators (green/red bars + avg YoY%)
- Nested subcategory drill-down with breadcrumb navigation
- Full-text dataset search with keyboard navigation (`/`, arrow keys, Enter)
- Light/dark theme toggle (persisted in localStorage)
- EN/RO language switcher with full i18n (40+ strings)
- Collapsible info panel (definition, methodology, notes)
- Smart large dataset handling (auto-filter for >50k rows)

**Two-panel chart dashboard:**
- **Trends panel**: time-axis charts (Line / Area / Stacked Bar) with best-fit series dimension
- **Snapshot panel**: category breakdown for a single period (Grouped Bar / Heatmap / Bubble / Choropleth / Bar / H-Bar) with period navigator (prev/next/play auto-advance)
- `determinePanelSetup()` analyzes dimensions to assign roles per panel
- Both panels share a single data fetch; snapshot filters client-side to selected period
- Independent pill switching per panel
- Fixed `resolveRoles()` x_axis_dim fallback bug in chart-factory.js
- Fixed heatmap dedup bug (xDim === yDim) in chart-new-types.js

**Verified across archetypes:** demographic (POP301A), geo_time (ACC101B_judete), time_series multi-dim (TUR105F), time_series single-dim (COM1071).

## 2026-03-25–27 — Data Quality & Chart Improvements

- Stripped aggregate/total rows from 49 parquet files (28,280 rows removed)
- Added scatter/correlation chart type to view profiles
- Fixed AVG aggregation for percentage-type datasets
- Fixed heatmap dimension role assignment
- Cleaned 1,150 stale view profile files
- Added chart selection rules reference (`docs/chart-rules.md`)

## 2026-03-24 — Corpus Normalization (Phases 1-7)

Full normalization of the data corpus into a canonical, consumption-ready format:
- **Phase 1**: Corpus audit — inventory of all parquet files, orphan detection
- **Phase 2**: Canonicalize corpus — convert splits, adopt orphans, archive parent datasets
- **Phase 3**: Build i18n dictionary from English metadata
- **Phase 4**: Profile all sub-datasets — dimensions, coverage, values, trends
- **Phase 5**: Simplify app to v3-only, add canonical filter and i18n support
- **Phase 6**: Reorganize data directory into `corpus/` for clean consumption
- **Phase 7**: Normalize dimension labels across all datasets

Result: 3,632 canonical parquet files in `data/corpus/parquet/`, metadata in `data/corpus/metadata.duckdb`, view profiles in `data/corpus/view-profiles/`.

## 2026-03-24 — SDMX-Native Data Format (Phases 0-4)

Transformed the entire data layer from opaque integer IDs to SDMX-compatible, human-readable format.

**Scripts created:**
- `11-build-sdmx-codes.py` — builds `sdmx_codes` (18,203 rows) and `sdmx_column_map` (10,683 rows) in DuckDB
- `12-parquet-to-sdmx.py` — transforms 1,886 parquet files from v2 (integer nomItemIds) to v3 (SDMX strings)

**Backend updated:**
- `app/config.py` — PARQUET_DIR → `parquet-v3/ro`
- `app/services/query_builder.py` — transparent nomItemId → sdmx_value filter translation
- `app/routers/dataset_data.py` — v3-aware label resolution (identity mapping for string values)
- `app/static/js/data-table.js` — `isValueCol()` handles both `value` and `OBS_VALUE`

**Metadata updated:**
- DuckDB `dimensions.dim_column_name` → SDMX concept IDs (REF_AREA, TIME_PERIOD, etc.)
- View profiles regenerated with new column names

**Result:** Data is now self-documenting (`WHERE REF_AREA = 'Bihor'` instead of `WHERE macroregiuni_nom_id = 3068`). Ready for NL2SQL, Jupyter notebooks, and multi-source (Eurostat/OECD) integration.

## 2025-12 — 2026-03 — FastAPI + DuckDB App

Built the web application with:
- FastAPI backend serving DuckDB metadata + Parquet data
- ECharts-based charting: choropleth, demographic grouped bar, time series, horizontal bar, heatmap, bubble, small multiples, population pyramid
- Filter panel with dynamic dimension controls
- Data table with sort, pagination, column filters
- Dataset list page with search
- v2 data enrichment pipeline (6 profiling agents): value profiles, coverage, trends, tags, relationships, chart recommendations

## 2025-08 — 2025-12 — Data Pipeline + Enrichment

- DuckDB + Parquet hybrid architecture
- CSV → Parquet conversion (1,886 datasets)
- Dimension classification (time, geo, gender, age, unit, residence, indicator)
- Dataset splitting by geo hierarchy (county/region/macroregion)
- SDMX-CSV export prototype
- Dimension index and search tools

## 2024-12 — 2025-08 — Initial Setup

- Project forked from `gov2-ro/scrapers`
- Data scraping pipeline (scripts 1-7): contexts, matrices, metadata, CSV data, compaction
- UI prototypes: dataset navigator, dimension browser, category browser, tree browser
- SQLite dimension index
- PHP API for dimension search
- Flask data profiler
