# Backlog

Future tasks and intentions for the TEMPO INS data explorer.

see also [charting-ideas.md](charting-ideas.md)

## Data pipeline
- [ ] **Cartographic blank issue — legacy parquet column format**: ~452 cluster-7 (cartographic) datasets are flagged in `docs/chart-taxonomy.md` as rendering blank. Investigation: split sub-datasets like `LOC103B_judet` keep the v2-style parquet schema (`judete_nom_id`, `perioade_nom_id`, `value`) instead of SDMX-canonical (`REF_AREA`, `TIME_PERIOD`, `OBS_VALUE`). `dataset_data.py:77-88` rewrites `dim_column_name` in the dimensions list but `query_builder.py` still hardcodes `"OBS_VALUE"` in the SELECT — so SQL fails for these. Either rebuild affected parquets via `12-parquet-to-sdmx.py` for split children, or teach `query_builder` to consult `sdmx_column_map` and rewrite both dim names and the value column.
- [ ] **Foreign-country geo classification**: `10-classify-dimensions.py` flags 410 unknown geo labels — the bulk are foreign country names (Franta, Germania, Italia, etc.) used in international comparison datasets. Add a `country` geo level (vs current county/region/macroregion) so these classify correctly.

## UI / Navigation
- [ ] **Dimension Browser — language support** — dimension labels in the `dimensions` table are Romanian-only (no `lang` column in the actual DB). For EN lang, either: (a) add an `en` row per dim by translating labels during pipeline, or (b) fall back to Romanian labels with a note. The `dims-explorer.js` already passes `lang` to `getDatasets` for dataset names but dimension labels stay in Romanian regardless.
- [x] add static pages - how do we treat translations?
- [x] add proper title: 'INS+' + {code} + {title - first 15 words}
- [ ] add 'last updated' page 
  - [ ] investigate current situation, aren't the metadatas read right?
- [x] Dataset page breadcrumbs: links click through but navigate to home instead of the correct category — fixed: breadcrumb clicks now use `_findCategoryByCode` + `_restoreDrillFromUrl`
- [ ] **Pretty permalink URLs for category/theme pages** — currently `?cat=E:E1` (code-based). Should use slugs like `/?cat=economie/preturi` for SEO and shareability. Requires slug mapping (code → slug) built from category names, a slug→code reverse map on load, and updating `_syncURL`/`_restoreDrillFromUrl` accordingly. The `?cat=CODE:CODE` format can stay as a fallback alias.
- [ ] create a release log. how? backwards? 
- [ ] cleanup, refactor folders, move most scripts in a folder (`scripts`?) - and current scripts into `utils`?

## Misc
- [x] research data dissemination, where could we expose the data. Kaggle, Hugging Face, torrent, Jupyter notebooks or similar? Could we set an automatic pipeline to update data when it updates?
- [ ] check if all the datasets are in Tempo Online or also other sources from INS
- [x] enhance table view
- [ ] more, nice themes - mai light a bit off-white, Financial Times, or Anthropic, lighter dark theme
- [x] add dataset code to explorer
- [x] add flags to language switcher
- [x] add disclaimer, not official gov.ro site
- [x] add data download option, csv/xlsx?
  - [ ] disseminate data. Kaggle, Hugging face? Check legal?
- [ ] should we split repos, data fetching, UI? - so we make a dataset independent SDMX UI framework?
- [ ] responsive
- [x] fetch newly updated datasets
  - [ ] continuous fetching, gh actions?
- [ ] Look for same EU stats?
- [ ] large datasets show no data: LOC108B — root cause: 0.4% fill rate (locality dimension has 3172 options × 43 counties × 7 categories × 23 years = theoretical 43M rows, actual 188k). Choropleth eligibility fixed (geo fallback). Remaining issue: needs REF_AREA_2 (locality) filtered before chart renders. Consider splitting into county-level vs locality-level sub-datasets.
- [x] detect ro/intl -> language. (`?lang=en` URL param)
- [ ] translate, Hu/De
- [ ] clean up obsolete subts, refactor scripts - utils, scripts?
- [ ] static site? - see `docs/misc-ideas/static-site/`
- [x] add llms.txt
- [x] Dynamic page title + meta/og:description per dataset — set from matrix_name, time range, updated date on dashboard load; reset to defaults on browse/about
- [x] description, title, og:info should follow language — all three cases (home, category, dataset) now language-aware in `_updatePageMeta()`
- [ ] **OG images per dataset** — pre-generate a chart screenshot or branded card per dataset code, cache in `app/static/og/` (e.g. `IPC102A.png`). Set `og:image` dynamically to `https://ins.gov2.ro/og/{code}.png` when available, fall back to default `landing.png`. Could be generated headlessly via Playwright during pipeline runs.
- [ ] **Clean dataset URLs** — serve datasets at `/{dataset-id}/` (e.g. `/IPC102A/`) instead of `?code={dataset}` for better SEO and shareability. Requires either a catch-all route in FastAPI returning `index.html` + JS routing via `location.pathname`, or static pre-rendering. Current `?code=` param can stay as alias for backwards-compat.
- [ ] how to deal with parent columns, like judete and localitati - SOM101E
- [ ] older datasets like sustainable development 2020 should be archived?


## Data Pipeline — API improvements (from TEMPO R pkg analysis)

- [ ] **`lastUpdate` in `/pivot` payload** — The R package optionally includes `lastUpdate` (from `details.lastUpdate` in matrix metadata) in the POST payload to `/pivot`. We never send this field. If the server honours it as a conditional-fetch, it could return only rows newer than that timestamp — enabling incremental re-downloads without full re-fetch. Worth testing on a dataset with a known `ultimaActualizare` date.

- [x] **Generic dimension chunking for oversized datasets** — Implemented `generate_chunks()` + `fetch_by_generic_chunks()` in `6-fetch-csv.py`. Recursively splits the largest dimension until each chunk fits under 25k cells (just below API limit). Tried after judet-split fails; aborts if >5,000 chunks needed (SAN101B, INT109C). Recovers ~14 previously-skipped datasets. Logs to `data/logs/generic-chunk-datasets.log`. Verified on INT101T: 37 chunks → 414,363 rows.

- [ ] **`ultimaActualizare`-based skip in incremental re-runs** — R package compares local file mtime against `ultimaActualizare` before downloading and skips if local is newer. `6-fetch-csv.py` currently skips only if file exists (regardless of age). Adding mtime-vs-`ultimaActualizare` comparison would make pipeline re-runs fast and safe for picking up INS updates without `--force`.


## Data intelligence
- [ ] correlations? 
- [ ] county profiles, demographics?


## Landing
- [x] Show latest updates
- [x] Flag interesting datasets
- [x] Some widgets per theme/subtheme/dataset


## Chart rules
- [ ] for long horizontal bar charts, prever vertical view
- [ ] bar charts, order by value
- [ ] if just 2 dimensions, don't give options to choose (axis, group), just to swap, transpose. 
- [ ] Max 3 dimensions no bubble but overlayed bars? Or up to 4? Matrix of bars?


## LLM Tooling — see plan `~/.claude/plans/peppy-fluttering-bubble.md`

Hybrid roadmap: minimal dev MCP → v1 user-facing agent → expand MCP → v2.
Architectural decision: tool-calling agent over existing safe services, **not** literal NL2SQL.
Shared substrate: extract `app/services/dataset_search.py` + `dataset_meta.py` once, reuse from MCP, agent, and existing routes.

- [ ] [OpenRouter](https://openrouter.ai/) version

### Step 1 — Minimal `tempo-dev` MCP (~2h) ✅
- [x] Refactor: extract `search_datasets()` and `get_dataset_meta()` from `app/routers/datasets.py` into `app/services/dataset_search.py` and `app/services/dataset_meta.py`. Keep route behaviour identical.
- [x] Write `tools/tempo-dev-mcp/server.py` (~150 lines, official `mcp` Python SDK) with 4 introspection tools: `tempo_dataset_info`, `tempo_search_datasets`, `tempo_chart_signature`, `tempo_sample`.
- [x] Add `.mcp.json` at repo root for repo-local registration.
- [x] Document in CLAUDE.md.

### Step 1.5 — MCP v2: query, catalog stats, FTS ✅
- [x] `tempo_query(matrix_code, filters?, group_by?, limit?)` — aggregated data queries via `build_data_query()`.
- [x] `tempo_catalog_stats(group_by?)` — corpus-level breakdowns by archetype/category/unit_type/geo/time_granularity.
- [x] `scripts/build-search-index.py` — FTS sidecar `data/corpus/search.duckdb` (14 MB, ~2s build). Bilingual search over names, 92k tags, definitions, categories.
- [x] `dataset_search.py` FTS-first strategy with LIKE fallback. "unemployment rate" → 130 results (was 0).
- [x] Full documentation in `tools/tempo-dev-mcp/README.md`.

### Step 2 — v1 user-facing NL→Data agent (~2.5h) ✅
- [x] `app/services/llm_client.py` — provider abstraction (Anthropic + OpenAI), normalised `LLMResponse`.
- [x] `app/services/agent.py` — tool registry, system prompt, `run_agent()` loop.
- [x] `app/routers/ask.py` — `POST /api/ask` behind `TEMPO_ASK_ENABLED` flag.
- [x] 4 agent tools: `search_datasets`, `get_dataset_schema`, `query_dataset_data`, `list_categories`. SQL never LLM-generated — calls `query_builder.build_data_query()` directly.
- [x] Live end-to-end test — done (2026-04-09). See `docs/misc/nl2br-output/` for 5 iteration outputs.
- [x] Minimal chat UI for `/api/ask` — `app/static/ask.html` + `app/static/js/ask.js`. Multi-turn history, text answer with markdown-lite rendering, citations, data table (up to 200 rows), auto chart (line/bar), warnings banner, collapsible tool trace. "Ask" link in main topbar.
- [x] **Agent: code-level query guardrail** — implemented in `run_agent()`. When model hits `end_turn` without calling `query_dataset_data` but search returned results, injects one synthetic user turn forcing schema+query. One-shot per run (`_guardrail_fired` flag). Fires for OpenAI models; Anthropic models never trigger the condition.
- [ ] **Agent: search ranking "județe" buries topic matches** — queries containing "județe" (or "judete") consistently rank LOC108B (construction permits with "judete si localitati" in name) at #1, pushing labor-market datasets like AMG157G/AMG159E to positions 3-7 or off the top-6. Root cause: FTS treats "judete" as a strong content match for datasets whose names contain the phrase literally, while thematic terms like "somaj" are treated as equal weight. Fix options: (a) boost datasets where query terms match the *indicator* part of the name vs the *geo qualifier* part, (b) strip known geo filler terms ("pe judete", "pe regiuni", "pe localitati") from search queries before FTS, (c) penalize LOC* context_code when query contains labor/employment vocabulary. Tracked separately from the agent — this also affects the catalog `/datasets` page.
- [x] **Agent: restore `search_datasets` default limit to 10** — reverted from 6→10. AMG159E (regional unemployment) at position 7 now visible.
- [x] **Agent: double-counting via unfiltered Total rows** — fixed via per-query parquet inspection. When the agent's `query_dataset_data` is called with `group_by`, `_detect_total_locks` scans each non-grouped, non-filtered dim for a `Total` value (`LOWER(TRIM(col))='total'`). If found, the handler locks those dims to Total and warns `Auto-applied Total filters: …`. If locking returns 0 rows (non-cross-product marginals like `TFP0512`), it falls back to the unfiltered SUM and warns `POSSIBLE DOUBLE-COUNTING: …` with an explicit re-query suggestion. Verified on `FOM104G`: buggy 28.25M → correct 5.36M for 2023. POP107D unchanged (parquet was pre-stripped). System prompt updated to teach the LLM how to read both warnings.
  - [ ] Follow-up: tighten the `query_dataset_data` 0-rows-strip-Total fallback so it doesn't undermine an explicit Total filter when the parquet truly has no cross-product cell (TFP0512 case). Currently the fallback strips Total filters even when Total exists in the parquet, returning the buggy unfiltered SUM. Fix: only strip a dim's Total filter if the parquet has no Total value for that dim.
- [ ] Pin `anthropic>=0.40` in `requirements.txt` (SDK 0.89.0 installed in dev venv but not pinned).

### Step 3 — Expand the dev MCP (~3–4h, after Step 2 surfaces real friction)
- [x] Pipeline state introspection: `tempo_pipeline_status`, `tempo_dataset_lineage`, `tempo_outdated`.
- [x] Code introspection: `tempo_routes`, `tempo_call_endpoint` (FastAPI TestClient).
- [x] Eval: `tempo_eval_chart_selector` (diff vs baseline). Shared `app/services/chart_selector_eval.py` + committed baseline `data/eval/chart_selector_baseline.json` (1959 datasets). Rebuild via `python scripts/build_chart_selector_baseline.py`. Fixed a latent non-determinism in `_load_inputs` dim_type majority vote: added `MIN(option_offset)` tie-breaker to match runtime `dataset_meta.py` "first-inserted wins" behavior (ACC102C UNIT_MEASURE was flipping between `unit`/`indicator` on ties).
- [x] Eval: `tempo_eval_agent` (search-quality diff vs baseline). Shared `app/services/agent_eval.py` + committed baseline `data/eval/agent_search_baseline.json` + seed `data/eval/agent_questions.yaml` (15 questions). Rebuild via `python scripts/build_agent_search_baseline.py`. **Uncovered two search bugs in the process:** (1) `_fts_search` used `ORDER BY score` (ASC) with `LIMIT 200`, so the FTS candidate pool contained the 200 *least* relevant datasets — POP107D was invisible to `"populatie pe judete"`. Fixed to `ORDER BY score DESC`. (2) Outer `ORDER BY ultima_actualizare DESC NULLS LAST` had no tie-breaker; fixed with secondary `m.matrix_code ASC`.
- [x] Eval: `tempo_check_view_profiles` — audits `corpus/view-profiles/` against parquet corpus + DB. Surfaced 197 missing VPs, 675 orphans, 49 archetype mismatches (mostly `geo_time`/`geo_only` schema drift on PNS101D splits), and 933 profiles carrying non-empty `warnings[]`.

### Search quality — follow-ups surfaced by `tempo_eval_agent`
- [x] **Preserve FTS relevance ordering through the outer query.** Fixed via `list_position(ARRAY[...], m.matrix_code)` ORDER BY when FTS is active and `sort='updated'`. Major improvements: "populatie pe judete" → POP108D/POP107D #1-2 (was LOC108B); "exporturi pe tari" → INT106B/EXP101I (was TUR105F); "accidente de munca" → ACC102B (was AMG130M). Baseline updated.
- [x] **Agent: restore `search_datasets` default limit to 10** — reverted from 6→10 in schema default and `_handle_search_datasets`. AMG159E (regional unemployment) at position 7 is now visible.
- [ ] **ask.html: Save/bookmark queries** — Allow users to save question+answer pairs from the chat UI.  Options to consider: localStorage-based history list (sidebar or modal), shareable URLs encoding the question. Related: conversation history is already tracked in-memory per session (`history[]` in ask.js) — persisting it to localStorage across sessions would be the simplest first step.


### View profiles — follow-ups surfaced by `tempo_check_view_profiles`
- [ ] 197 parquets without view profiles — **root cause: all are `_localitate_judet`/`_localitate_localitate` splits that exist as parquets but are NOT registered in `matrix_profiles` DB table.** `generate_view_profiles.py` only processes DB-registered datasets so re-running it has no effect. Fix requires either: (a) register locality splits in DB (complex, high-cardinality ~3,172 localities), or (b) exclude them from audit as intentionally unregistered. Likely (b) — these datasets are too large for the UI anyway.
- [x] 675 orphan VPs — deleted (2026-04-14). Parent dataset VPs left behind after splits.
- [ ] 49 archetype mismatches on `PNS101D_*` splits (VP says `geo_time`, DB says `geo_only`). Investigate whether the VP generator or the classifier is authoritative.
- [ ] Frontend probing (Playwright): `tempo_render_dataset`, `tempo_console_errors`, `tempo_validate_echarts_spec`.
- [ ] Gated mutations (`TEMPO_DEV_MUTATIONS=true`): `tempo_run_pipeline_script`, `tempo_regen_view_profile`, `tempo_clear_search_index`.
- [ ] Eval baselines: `data/eval/chart_selector_baseline.json`, `data/eval/agent_questions.yaml`.

### Step 4 — v2+ user features (varies)
- [ ] Cross-dataset reasoning: `compute_ratio` / `query_two_datasets` tool (joins on shared SDMX dims).
- [ ] Derived metrics tool: expose `dataset_trends` table as `get_trend_summary(matrix_code)`.
- [ ] Multi-turn drill-down with session memory.
- [ ] Hybrid retrieval: lexical FTS + multilingual embeddings (BGE-M3 / multilingual-e5-large).
- [ ] Streaming + chat panel UI.
- [ ] Methodology Q&A (RAG over `matrices.definitie` + `matrices.metodologie`).
- [ ] Statistical narrative generation (auto-explanatory journalism over INS data).
- [ ] LLM-driven chart customisation (override `chart_selector` defaults).
- [ ] Auto-generated periodic reports (Markdown/PDF/HTML).
- [ ] (See plan file Tier 2-4 for ambitious / research-grade ideas.)

## SDMX / Multi-Source

- [ ] **Phase 5: NL2SQL preparation** — Generate per-dataset JSON schema files, create DuckDB views for all parquet-v3 files, build corpus description for LLM context. *(Superseded by the LLM Tooling plan above — tool-calling agent reuses existing services rather than per-dataset views.)*

- [ ] **Phase 6: Multi-source adapter** — Eurostat/OECD data ingestion alongside INS data.
  Design `dataset_registry` table, build Eurostat SDMX-CSV adapter.

- [ ] **English parquet-v3 generation** — Run `12-parquet-to-sdmx.py --lang en` to
  produce English-language SDMX parquets. Requires English `sdmx_codes` entries
  (display_label_en already partially populated). *comment*: English data is the same data, we might only need to use the original Romanian ones and use the English metas.

- [x] **Clean up stale split profile files** — Done.
  Moved 1,150 stale profiles to `_stale/`: 736 parent profiles (parquets replaced by children),
  414 with `_nom_id` column refs. Fixed `dim_column_name` in DuckDB for 414 v2 splits
  (old `_nom_id` → SDMX names like `TIME_PERIOD`, `REF_AREA`). Regenerated 414 view profiles.
  Script: `scripts/cleanup-view-profiles.py`.

## Data Pipeline

- [x] **"Actualizate recent" shows only ~8 of 220 2026-updated datasets** — investigated 2026-04-13,
  not a bug. `2-metas` dates are correct (stored as DD-MM-YYYY, parsed correctly by pipeline).
  DB dates match `2-metas`; original symptom was from a stale pipeline run. Now 201 canonical
  datasets have 2026 `ultima_actualizare`. News vs DB date difference (1–5 days) is expected:
  news = INS press release date, DB = actual data file update date.
- [x] **13 datasets in `insse_news.csv` not in corpus** — ingested 2026-04-14.
  `FOM105I, FOM106G, FOM107G, FOM108C, FOM108D, FOM109C, FOM109D, PMI115C, PMI117B,
  SAR102G, SAR107B, IAPC102, IPPR101`. All have parquet + DB registration + view profiles.
- [x] **Fix `10-import-metadata.py` — schema mismatch on `lang` column** — fixed 2026-04-14.
  Removed `lang` from INSERTs/conflicts, added `matrices-list.csv` as supplementary source
  for new codes not yet in `matrices.csv`, added dimension-skip guard for duplicate IDs,
  enrichment now targets only matrices with missing `context_code` or zero dimensions.
  Also fixed `10-classify-dimensions.py`: `--matrix` mode now preserves existing table data
  (CREATE TABLE IF NOT EXISTS, INSERT OR REPLACE instead of DROP+INSERT).


- [ ] **Replicate geo_hierarchy split for English (`eng`) parquet files**
  Pattern F splits are done on `ro` only. Since `nom_item_id` values are shared across
  languages, the same ID sets detected from `ro` can be reused. Low effort once the ro
  run is stable.

- [ ] **Handle `Municipii si orase` (4 datasets) — Pattern G**
  321 values mixing municipalities and towns in a single dimension. Potential split:
  `_municipii` and `_orase`. Affects: AGR*, TLC* and others.

- [ ] **`Macroregiuni si regiuni de dezvoltare` (60 datasets)**
  2-level variant of geo_hierarchy (no counties). Already handled by Pattern F
  (emits `_regiuni` + `_macroregiuni`), but worth verifying output quality separately.

## Static Site Migration

- [ ] **Phase 2: DuckDB-WASM data client** — Test `duckdb-data-client.js` against real
  parquet files, verify HTTP range requests work with CORS, compare output with
  FastAPI `/data` endpoint. Handle edge cases (missing parquet, WASM not supported).

- [ ] **Phase 3: Port frontend components** — Copy/adapt `explorer/static/js/` chart
  modules and Vue components to `static-site/js/`. Wire up to `api-static.js`.
  Main files: `DatasetPicker.js`, `ChartCanvas.js`, `FilterBar.js`, `LeftSidebar.js`.

- [ ] **Phase 4: Deploy pipeline** — GitHub Actions workflow: run `build-static-site.py`,
  upload JSON to Cloudflare Pages, upload parquet to R2. Service Worker for offline caching.

- [ ] **Phase 5: Retire FastAPI app** — Archive `app/`, `duckdb-browser.py`, update CLAUDE.md.

- [ ] **Aggregation in DuckDB-WASM** — Port the GROUP BY aggregation fix (from backlog
  "Raw LIMIT truncation" issue) into `duckdb-data-client.js`. Easier in WASM since
  the full query builder is in JS.

## UI / App

- [x] **v2 UI build (Lens)** — Two-panel dashboard shipped: Trends (line/area/stacked over time) +
  Snapshot (grouped bar/heatmap/bubble/choropleth/bar for single period) with period navigator
  and play animation. Category browse, search, theme toggle, i18n all working.
  Remaining: data table, export, responsive polish, URL state.

- [x] **Choropleth: support region-level map** (`_regiuni` sub-datasets)
  Done — region + macroregion GeoJSON files generated, multi-level choropleth in chart-geo.js.

- [x] **Dataset page: show split siblings**
  Done — sub-dataset bar with pills in dataset-page-v2.js, variant drawer in datasets-page.js.

### Lens UI Improvements

- [x] **URL state persistence** — `?code=`, `view=`, `chart=`, `period=`, `filters=` all persisted via `replaceState`. Shareable/bookmarkable. Filter defaults restored via `ViewControlsPanel` `initialValues` param. Language not yet included.

- [x] **Data table toggle** — Done. Collapsible data table with dropdown column filters,
  zebra striping, sticky headers, filtered/total row count. Client-side filtering via
  exact match on dimension columns.

- [x] **Monthly/quarterly yearly aggregation toggle** — Done. For monthly (90 datasets) and
  quarterly (27 datasets) data, Trends chart defaults to yearly-aggregated values. "Anual"
  toggle button in chart type pill bar (same pattern as Index/Δ% transforms). Client-side:
  group TIME_PERIOD by year prefix, SUM for counts/currency, AVG for percentage/rate/time_unit.
  Raw monthly view defaults zoom to last ~5 years (60 periods) via ECharts dispatchAction.
  URL state: `?tagg=0` persists when user explicitly turns off yearly mode.

- [ ] **Visual polish pass** — x-axis label truncation on rotated labels, responsive
  breakpoints for mobile (category grid, insight cards, chart panels), smooth transitions
  between chart type switches.

- [x] **Export** — CSV/XLSX download of filtered data with language support.
- [x] **Export** — PNG export of charts — already implemented via `_exportPng()` + `time-png-btn`/`snapshot-png-btn` in index.html.

- [x] **Add `lang` to `get_dataset()` endpoint** — already implemented: router accepts `lang` param, `dataset_meta.py` returns `COALESCE(matrix_name_en, matrix_name)`, frontend passes `lang` in `API.getDataset()`.

- [ ] **Responsive mobile layout** — 3-column category grid and 4-column insight cards don't
  adapt well to phones. Add `@media (max-width: 768px)` breakpoints for stacking.

- [ ] **Monthly → yearly aggregation toggle** — For datasets with monthly data,
  add an option to aggregate values by year (SUM for counts, AVG for rates/indices).
  Useful for long time series (20+ years of monthly data = 240+ points) where
  yearly trends are easier to read.

- [ ] **Keyboard shortcuts legend** — Lens supports `/`, `Cmd+K`, arrow keys but there's no
  discoverable way to learn about them beyond the search footer hints.

- [x] **Loading states for chart switching** — Done. Chart containers show loading state with
  opacity transitions during re-render.

- [x] **Dataset definition/methodology panel** — Done. Collapsible info panel below header
  shows definition, methodology, and notes from metadata.

- [x] **Category breadcrumbs** — Done. Clickable breadcrumb trail with nested subcategory
  drill-down (▸ rows), back button shows parent name. Stack-based navigation.

- [x] **Smarter large dataset handling** — Done. Auto-applies first non-TOTAL filter for
  datasets >50k rows. Shows amber warning banner. Retries on filter-required errors.

- [x] **Trend indicators on category cards** — Done. Green/red bar showing proportion of
  increasing vs decreasing datasets, plus avg YoY% growth. New `/api/categories/trends` endpoint
  aggregates `dataset_trends` via `UNNEST(ancestor_codes)`. Works for all context levels.

## Data Accuracy — Server-Side Aggregation

- [x] **Server-side GROUP BY for chart queries** — Done.
  Frontend sends `group_by` param with chart-relevant dimension columns. Backend
  `query_builder.py` generates `SELECT dims, SUM(OBS_VALUE) ... GROUP BY dims`.
  Table view sends raw queries (no GROUP BY). Typical reduction: 99%+ for large datasets
  (e.g., EXP102J: 18,225 → 168 rows). Files: `query_builder.py`, `dataset_data.py`,
  `api.js`, `dataset-page-v2.js`.

- [x] **Non-summable values** — Done.
  `query_builder.py` accepts `agg_func` param (SUM or AVG). `dataset_data.py` looks up
  `matrix_profiles.primary_unit_type` — uses AVG for `percentage` (694 datasets) and
  `time_unit` (12 datasets), SUM for everything else.

## Chart Selection — Future Improvements

See also: `docs/chart-taxonomy.md` for full gap analysis per cluster (33 exemplar screenshots).

- [x] **Fix 50k limit for choropleth / large datasets** (HIGH, 452 datasets / 23%) — Done (partial).
  Two fixes applied: (1) GROUP BY bypass: large-dataset rejection skipped when `group_by` param present,
  allowing aggregated views of datasets >50k rows. (2) Server-side time windowing: datasets >500k rows
  auto-filter `TIME_PERIOD` to the latest N periods that fit within 50k budget (min 2 for >5M row datasets).
  Response includes `time_windowed: true` flag; frontend shows bilingual notice.
  Remaining gap: datasets with legacy `_nom_id` columns (e.g. LOC103B_judet) still have column-resolution issues.
- [x] **Boost area_stacked for percentage data** (HIGH, 295 datasets / 15%) — Done.
  Frontend now uses chart_selector's recommendation for default chart type.
  Selector already scored area_stacked correctly; frontend was ignoring it.
- [ ] **Small multiples / heatmap for high-cardinality time** (MED, 520 datasets / 27%) —
  Categorical Time cluster (6-50 options) renders cluttered lines. Default to heatmap/small_multiples for >8 series.
- [x] **Fix population_pyramid selection** (MED, 69 datasets / 4%) — Done.
  Relaxed gender_count threshold from ≤3 to ≤6 (INS mixes gender+residence in one dim).
  Added population_pyramid to frontend snapshot chart types when age+gender dims present.
- [x] **Fix snapshot chart type for non-time datasets** (MED, 49 datasets / 2.5%) — Done.
  Frontend now uses selector's ranked_charts to pick default time/snapshot chart type.
  Fixed geo_count for region/macroregion datasets (was 0, now uses actual count).

- [ ] **Treemap chart type** — For hierarchical categorical data (CAEN economic sectors),
  treemap would show proportions better than horizontal bar. Requires frontend implementation.

- [ ] **Sparkline/KPI view** — Datasets with 1 dimension (pure time series, no categories)
  are perfect for a large KPI number + sparkline, not a full chart.

- [x] **Ratio/change chart mode** — Year-over-year change, growth rates, indexed values.
  Done: Index/Rebase, YoY Δ%, Ranking/Bump, Distribution strip — all as frontend transforms.

- [ ] **Radar chart** — For comparing a small number of categories across multiple
  metrics (e.g., county profiles across health/education/economy indicators).

- [ ] **Unify `generate_view_profiles.py` with `chart_selector.py`** — Both contain
  independent chart selection logic. The view profile generator has its own snapshot chart
  rules that partially overlap. Long-term, view profiles should call `select_charts()`.

- [ ] **Delete `app/services/chart_config.py`** — Dead code, no imports found. Kept for
  reference during the transition period but should be removed.

## Data Quality

- [x] **Phase 8: Strip aggregate/total rows from parquet files** — Done.
  49 parquet files stripped of 28,280 aggregate rows (Total in SEX, AGE, RESIDENCE, REF_AREA).
  Scripts: `scripts/detect-totals.py` (detection + decisions), `scripts/strip-totals-from-parquet.py`
  (apply to existing parquets), `12-parquet-to-sdmx.py --strip-totals` (integrated pipeline).
  Handles mutually exclusive breakdowns via intersection mode (only strips grand-total row).
  Decisions stored in `data/logs/total-decisions.json`.

- [ ] Review `docs/TODO_COMPACTION.md` — label normalisation issues in 7-data-compactor.py


## Bugs
- [ ] large datasets: LOC108B
  - [ ] SOM101E map not showing: 'Se afișează doar o selecție — setul de date are prea multe rânduri pentru afișare completă'
