# Backlog

Future tasks and intentions for the TEMPO INS data explorer.

see also [charting-ideas.md](charting-ideas.md)

## Next up — deferred 2026-09-01

Picked instead: the large-dataset correctness pass (see *Data Accuracy — Server-Side
Aggregation*). These three were the runners-up, in the order I'd take them:

1. **Headline coverage for label-hierarchies** — 22 additive hierarchies still take an
   arbitrary pin and so lose their KPI entirely (the 2026-08-23 suppression rule drops
   `latest`/`yoy`/`overall` whenever the series is a pinned slice). Extend
   `verify_partition()` in `13-dimension-structure.py` past the one-member-leftover
   shape it handles today. Small, and directly visible to visitors.
   → detail under *Chart Selection — Future Improvements*.
2. **Time-range control** — the biggest genuinely *missing* control. Time is either the
   whole x-axis or one pinned period; ECharts `dataZoom` is view-only and never narrows
   the query. Becomes more valuable once the windowing work below lands, since the
   server will already know how to restrict periods.
   → detail under *Dashboard v2*.
3. **Pipeline bookkeeping rot** — ~2,180 parquets with no `matrices` row, POP107A
   unreachable, 149 datasets with a non-time `TIME_PERIOD`. Invisible until someone hits
   a 404, but it grows with every incremental run.
   → detail under *Data pipeline*.

## Data pipeline
- [ ] **149 datasets have a non-time `TIME_PERIOD`** (found 2026-08-23): `AMG115*`/`AMG116*` carry "hours worked" bands (`11 - 20 ore`, `Nu poate fi indicata o durata obisnuita`) in the time column, and `CNF101F` carries month names (`Aprilie`, `Ianuarie`). Any chart over these is meaningless, and `13-dimension-structure.py` cannot sample periods for them. Detect with: for each parquet, share of `TIME_PERIOD` values matching `^\d{4}$|^\d{4}-Q[1-4]$|^\d{4}-\d{2}$` below 0.8. Likely a `12-split-datasets.py` bug in the `_anual`/`_trimestrial` split path.
- [ ] **536 of 2,219 `matrices` rows have no parquet** (measured 2026-09-01): `/data` and `/download` now answer these with a 404 naming the cause instead of a 500 that leaked the absolute server path (large ones were previously masked by the row-count gate). The underlying bookkeeping drift is the entry below.
- [ ] **POP107A is unreachable in the app** (found 2026-08-23): the parent has no parquet (`/data` 400s) and all six children (`POP107A_judete_varste` etc.) 404 because they have no `matrices` row. Symptom of a wider bookkeeping gap — ~2,180 of 3,863 parquets have no `matrices` row, `matrix_profiles` covers 1,986, and `dataset_splits` holds 300 rows for 101 parents. The incremental pipeline never re-runs `10-classify-dimensions.py` / `11-coverage-profiler.py` / `detect_trends.py`, which is where the drift comes from.
- [x] ~~**`parse_news()` doesn't validate matrix codes**~~: Fixed 2026-08-05. Recurred a second time (2026-08-05 run hit `113  Matrice`, same as the `86 Matrice` from 2026-07-20 — both rows are apparently persistent in the news feed history). `parse_news()` now filters `Cod matrice` values against `MATRIX_CODE_RE = ^[A-Z0-9]{4,10}$` and logs skipped rows; `fetch_meta()` now validates the response body with `json.loads()` before writing, so a bad code can no longer leave a permanent 0-byte file in `data/2-metas/`. Cleaned up the existing `113  Matrice.json` and regenerated `matrices-list.csv` (was silently truncated to 975 rows by the `4-build-meta-index.py` crash; now 1996).
- [x] ~~**Cartographic blank issue — legacy parquet column format**~~: Fixed via query-time remap. `dataset_data.py` now detects parquet schema (SDMX vs legacy v2) and reconciles dim names against the actual file via `sdmx_column_map`; `query_builder.py` accepts a `value_column` argument and aliases it to `OBS_VALUE` in the result. 67 legacy parquets (LOC103B_judet, EXP101D, LMV101B et al) — across clusters 1, 2, 3, 7, 8 — are now queryable.
- [ ] **Pipeline-level migration of legacy parquets — now 188, not 67** (re-measured 2026-09-02): the v2-format set has *grown* (37 written 2026-04, 142 in 2026-07, 9 in 2026-08). Root cause found: `12-parquet-to-sdmx.py` logged per-matrix errors and still **exited 0**, so `update-pipeline.py` recorded them as successes — the 2026-08-05 run reported `Processed: 225 | OK: 225 | Failed: 0` while FOM105I and others converted nothing in 0.1s. Fixed 2026-09-02 (exits 1 when nothing converted). The backlog now splits cleanly:
    - **94 converted 2026-09-04** — verified identical row counts and identical `SUM(value)` against a pre-repair snapshot. Backup of all 141 attempted files: `data/_obsolete/legacy-parquet-backup-20260904/`.
    - **47 reverted** — conversion replaced dimension labels with NULL for codes missing from `sdmx_codes` (up to 61% of rows in TRN113A). Blocked on the `sdmx_codes` coverage gap below.
    - **47 still need `sdmx_column_map` rows** (IAPC102, FOM10*, and split children like `POP204C_judet` whose parent has no map either). `11-build-sdmx-codes.py` populates that table.
    - Remaining legacy parquets: **94**, down from 188.
- [ ] **`12-parquet-to-sdmx.py` writes NULL for nomItemIds missing from `sdmx_codes` — 29% of the canonical corpus is affected** (measured 2026-09-04): 1,108 of 3,769 SDMX parquets contain NULL dimension values, 3.6M of 87.5M rows (4.1%), and **51 files where every single row has a NULL dim** (CON113A, COM104B, the CDP104* family). `query_builder` adds `"col" IS NOT NULL` to every grouped query, so those rows are silently dropped from charts, headlines and rankings — a dataset like TRN113A loses 61% of its rows without any indication. The converter already counts these as `unmapped` and reports the total, but nothing acts on it. This is the blocker for finishing the legacy migration *and* a live correctness problem for the datasets already converted. Fix `sdmx_codes` coverage first (`11-build-sdmx-codes.py`), then re-run the conversion.
- [ ] **Pipeline scripts don't signal failure**: `6-fetch-csv.py`, `12-split-datasets.py`, `13-dimension-structure.py` and `3-fetch-metas.py` contain **no `sys.exit` at all** — they always exit 0, handled errors included. `update-pipeline.py`'s `matrix_ok` gating therefore only catches unhandled tracebacks, which is why the corpus can drift (536 `matrices` rows with no parquet, POP107A unreachable) while every run reports clean. `12-parquet-to-sdmx.py` was fixed 2026-09-02; the other four need the same treatment, and flipping them will make runs start reporting failures that were previously invisible — a deliberate decision, not a drive-by.
- [ ] **Foreign-country geo classification**: `10-classify-dimensions.py` flags 410 unknown geo labels — the bulk are foreign country names (Franta, Germania, Italia, etc.) used in international comparison datasets. Add a `country` geo level (vs current county/region/macroregion) so these classify correctly.

## Deployment
- [ ] **`fly deploy` silently ships stale data**: `Dockerfile` bakes in `deploy-data/`, a manually-staged snapshot (`scripts/prepare-deploy-data.sh` copies `data/corpus/` → `deploy-data/` + rebuilds `deploy-data.tar.gz`). `fly deploy` has no hook that regenerates it, so it's easy to run a real pipeline update, confirm it locally, then deploy and ship the old snapshot unchanged — happened 2026-08-05 (`deploy-data/metadata.duckdb` was 4 months stale, from 6 Apr). Fix: wire `prepare-deploy-data.sh` into the deploy flow (`fly.toml` `release_command`, or a `deploy.sh` wrapper that runs both steps) so this can't be forgotten.

## Lens (canonical dataset page)
- [ ] **API-driven chart dispatch instead of archetype recipe** — `explore-app.js` builds the snapshot/timeline tab list from `archetype` (e.g. `archetype === 'geo_time'` adds choropleth). Two failures surfaced in the 2026-05-07 visual smoke test (`data/eval/smoke-test-report.md`): (1) LOC103B_judet has `archetype: null` so its choropleth pick is dropped from the snapshot tab list and the snapshot falls back to line; (2) AGR201E selector picks heatmap as primary but the timeline panel only offers line/bar/area/stacked, so heatmap never dispatches and timeline falls back to line. Fix: build tab lists from `chart_config.ranked_charts` (with archetype as a tiebreak / fallback only). This makes the lens honor whatever the selector recommends.
- [ ] **Backfill archetype for split datasets** — split children (`*_judet`, `*_regiuni_anual`, etc.) inherit no archetype from the parent matrix in `matrix_profiles`. Even after API-driven dispatch lands, archetype is still surfaced as a UI badge and used by other code paths. Re-run `10-classify-dimensions.py` on split children, or have `12-split-datasets.py` propagate the parent's archetype.

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

## Geographic profiles
- [ ] **Place profiles: norm by population toggle** — On any absolute-count KPI/indicator chart in place profiles, add a "per 1,000 population" toggle. Requires population lookup for place + year from `POP105A_judete_grupe.parquet` (or equivalent). Affects `place-page.js` KPI cards and indicator grid sparklines. Spec: `docs/superpowers/specs/2026-05-07-place-profiles-design.md`.
- [ ] **Place profiles: choropleth click-through** — Clicking a county on any choropleth map should open `/place/county/{slug}` in addition to (or instead of) the current filter behaviour. Add click handler in `app/static/js/chart-geo.js`.
- [ ] **Place profiles: dataset page cross-link** — When a dataset is filtered to a single county via `?place={slug}`, show a "Profil {name}" link in the dataset page header. Modify `app/static/js/dataset-page.js`.

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
- [x] ~~**`ORDER BY "TIME_PERIOD" ASC` + `LIMIT` drops the NEWEST periods**~~: Fixed 2026-09-01. `build_data_query` now takes the newest rows in a subquery (`ORDER BY <time> DESC LIMIT n`) and restores ascending order outside it, and `time_column` is a parameter so the 67 legacy parquets get the same treatment via their `*_nom_id` time column. Measured on ART101C grouped by (TIME_PERIOD, REF_AREA) at limit=500: the window moved from 1990–1999 to 2016–2024.
- [x] ~~**`truncated` / `time_windowed` are computed and thrown away**~~: Fixed 2026-09-01. `coverageNote()` renders a `.dbv2-coverage` pill in the tile bar showing the span actually plotted (e.g. `2011–2025`), with a tooltip naming the reason. Note it does not fire on any composition today — the full-corpus sweep found 0 of 4,131 composed tiles truncating — so it is insurance for future composer picks and for direct API use; verified by injecting the flags into a live response.
- [x] ~~**Mixed units in one headline**~~: Added 2026-09-02. `insights._mixes_units()` suppresses the headline when the slice spans more than one unit of measure — AGR202B was adding hectolitres, kilograms, thousand pieces and tonnes live weight. 74 datasets have such a slice; all but 3 were already suppressed for another reason, so the cost is 3 headlines, every one of them previously wrong.
- [ ] **`_parquet_dim_values` keeps its own column resolution**: deliberately not folded into the shared adapter on 2026-09-02 — it probes for column existence rather than translating a query, and its per-column try/except fallback works even where `sdmx_column_map` has no rows. It does spend one failing query per column on every legacy dataset.
- [ ] **A truncated `/download` is still silent**: `download_dataset` gets the newest-first ordering for free but not the partial-period drop, and the CSV carries no marker saying it was cut at `MAX_DATA_ROWS`. POP107D downloads 50k of 21.6M rows with nothing to say so.
- [x] ~~**`group_by` bypasses the 50k gate**~~: Fixed 2026-09-01. Auto-windowing now runs for grouped queries too, sizing the window from Π(cardinality of the grouped dims) via `_rows_per_period()` — `dimensions.option_count` rather than `dimension_structure.n_effective`, since the former covers the whole corpus and over-estimating is the safe direction. POP107D by locality went from 50,000 truncated rows spanning 1992–2008 to 47,685 complete rows spanning 2011–2025; SOM101E from 2010–Feb 2011 to Jun 2024–Aug 2025.
- [x] ~~**No point-level cost control**~~: Closed 2026-09-01 as mostly not a problem. Measured first: the corpus tops out at 463 periods (PPA101A) against a 12-series cap, so the worst case is ~5.5k points — well inside ECharts' comfort zone, and no per-tile point budget is warranted. Added `sampling: 'lttb'` to line series as insurance (ECharts only downsamples once points outnumber pixels, so it costs nothing until something does). Deliberately did *not* set `large: true` on the scatter/bubble charts: large mode ignores per-point `symbolSize`, which is the encoding those charts depend on.
- [x] ~~**`insights.py` does not remap legacy parquet columns**~~: Fixed 2026-09-02. The translation now lives once in `query_builder.resolve_parquet_schema()` / `adapt_to_parquet()`; `dataset_data.py`, `agent.py` and `insights.py` all use it, replacing three divergent copies and one omission. Corpus-wide: headlines 633 → 713, sentences 1,229 → 1,366, and **zero datasets had an existing headline value change**. `agent.py` also silently queried a legacy parquet's `value` column as `OBS_VALUE` and now reports SDMX column names back to the model.
- [ ] **107 datasets sum an un-totalled multi-option `indicator` dim into the headline** (measured 2026-09-02): 100 already-canonical parquets plus the 7 legacy ones the fix above unmasked. `_build_slice` pins a dim to one option only when the unit type is non-additive, so an additive dataset whose indicator dim has no Total gets every option summed. A narrow guard now covers the unambiguous sub-case (see below); the general case is open, and is the same family as the 22 label-hierarchies.
- [ ] **Dims typed `unit` that are really categorical breakdowns**: ASS101A's `UNIT_MEASURE` holds `Total / Centre de recuperare / …` — facility types, not units — while its actual unit dim is `UNIT_MEASURE_2` (`Numar persoane`). The composer skips `unit`-typed dims when pinning, so such a dim is summed whole, Total included. Suppressed for now by the mixed-unit guard; the classification itself is wrong and belongs in `10-classify-dimensions.py`.
- [ ] **High-cardinality filters render as a bare input**: POP201D's 3,182-option `Localitati` filter is an `<input>` + `<datalist>` typeahead with no placeholder, so it reads as an empty broken box. Add placeholder text naming the dimension.
- [ ] **TUR106D cannot be time-ordered**: the one legacy large dataset whose period labels are month names (`luni_nom_id`), which sort alphabetically rather than chronologically. `_resolve_time_column()` deliberately returns None for it, so it keeps the old unordered behaviour and still refuses an unfiltered table view. Fixed for free by the legacy-parquet pipeline migration already filed above.
- [ ] **Every interaction rebuilds all four charts**: `renderGrid()` disposes and re-creates every ECharts instance on each refresh, so one chip click costs 4 requests + 4 scans + 4 `echarts.init()`. The 2026-08-23 multi-select added a 250ms debounce (`refreshSoon`); incremental `setOption` is still the real fix.

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
- [ ] **22 additive label-hierarchies still get an arbitrary pin** (2026-08-23): `verify_partition` catches the ART101C shape (leftovers tile exactly one member of the shallow level) but misses cases like TAV0212 `GRADE_DE_SEVERITATE_ALE_MALNUTRITIEI` and POP206L `CLASIFICAREA_INTERNATIONALA_A_MALADIILOR`. Each one costs that dataset its headline KPI, since the pin now suppresses `latest`/`yoy`/`overall`.
- [ ] **Locality drill-down**: `dimension_structure.nests_in` records `REF_AREA_2 -> REF_AREA` for 43 datasets, and the child is now simply dropped from the global filter row (it used to collapse a 41-county ranking to one bar). The real answer is a drill-down: clicking a county re-groups the ranking by that county's localities. No GeoJSON below county, so the map stays at county level.
- [ ] **Richer informativeness signals** (deferred 2026-08-23): `dimension_structure` now carries `discrimination` (CV across a level's options) and `dominance` (top option's share), because both fall out of the additivity probe for free, and `_best_temporal_series` uses `discrimination` to reject splits that do not separate. Not yet computed: *temporal divergence* (do the series actually diverge over time, or move in lockstep?) and *joint slice coverage* (CDP104H pins CATEGORY + latest year onto a combination that has no rows — per-dim distincts cannot see joint holes). Both are cheap on the same probe pass.
- [ ] **Heatmap is the structural default too often**: it appeared in 135 of 247 sampled dashboards (2026-08-23) — it wins the structural slot whenever two categorical dims exist. Worth deciding whether a dense cross-tab is the right filler for a lay visitor before adding new chart types.
- [ ] **Extend levels to the remaining proposers**: the corpus run verifies 41 multi-level dims (34 geo, 5 indentation, 2 age). `parent_id` and CAEN-depth proposers are implemented but currently never survive verification — worth checking whether that is correct (the levels genuinely do not tile) or whether the 2% tolerance / 3-period sample is too strict for sparse CAEN data.

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
- [ ] large datasets: `LOC108B`
  - [ ] SOM101E map not showing: 'Se afișează doar o selecție — setul de date are prea multe rânduri pentru afișare completă'
- [ ] `POP108D` not loading? just `1992` - data is allright. For these large datasets, let's maybe load just the last few years? There are just 2 huge ones, larger than 1gb `POP108D` and `POP107D` – the next one is `INT109C` - 167Mb, the others being less than 100Mb – as csv. Should we use xlsx instead, generally, when fetching data?

## Dashboard v2
- [ ] **Time range control**: there is still no time control at all — time is either the whole x-axis or pinned to a single period. ECharts `dataZoom` is view-only and never narrows the query.
- [ ] **"Compare by ▾" pivot**: the `⇄` chip only swaps two already-assigned roles on four chart types. Generalise it to a picker over the ranked series candidates (audit item F6; BACKLOG "if just 2 dimensions, don't give options to choose (axis, group), just to swap, transpose").
- [ ] **Nested geo as drill-down**: `dimension_structure.nests_in` now records `REF_AREA_2 → REF_AREA` for 43 datasets, but the UI still renders `REF_AREA_2` as a 3,179-entry `single_select` in the filter row (SOM101E, POP107D, LOC104B). Use the nesting to offer a drill-down from the selected county instead.
- [ ] **Delete the obsolete widget files**: `filter-panel.js`, `view-controls.js`, `period-browser.js`, `data-table.js` (1,142 lines) are referenced only from `app/static/_obsolete/`. The multi-select implemented on 2026-08-23 was the last thing worth salvaging from them (audit item F2).
- [ ] Split-parent datasets (e.g. AMG101A, AGR209A) have no parquet — v2 dashboard tiles show 500s/empty. Port the sub-dataset bar from `dataset-page-v2.js` (plan Phase 5) or redirect to the first sub-dataset.
- [ ] Delete dormant `app/static/js/dataset-page-v2.js` (tabbed controller, never wired) once dashboard-v2 covers its useful bits (header, sub-dataset bar).
- [ ] `small_multiples` hero with no facet dim (AMG101E) degrades to a single line — composer could swap chart_type to plain `line` when roles.facet is null.
- [x] ~~`chart_selector.build_signature` time_points fallback bug~~ — fixed 2026-07-19 (Phase 0 of the perspectives roadmap, see `docs/dashboard-audit-2026-07.md`). Fallback is now `time_year_max - time_year_min + 1`; eval re-baselined (64 intentional primary changes).
- [ ] **NULL dim values in SDMX parquets** (mapping gap): e.g. FOM106F has 18 rows with `ECON_ACTIVITY = NULL` (the "–" rows in the data table) — options that never got an `sdmx_codes` mapping. `query_builder` now excludes NULL group columns from aggregations (they produced a bogus 100k "null" bar), but the pipeline should backfill the missing mappings in `11-build-sdmx-codes.py` / `12-parquet-to-sdmx.py`.
- [ ] **Overlapping AGE options double-count sums**: POP107D's AGE dim mixes single years ("53 ani") with bands ("50-54 ani") and has no Total in data → unfiltered SUM gives 38.8M (2× population) in insights "Ultima valoare" and any slice that leaves AGE unpinned. Composer/insights need an age-band canonicalization (pick one non-overlapping granularity via parsed age_min/age_max). Pre-existing in v1 too.
- [ ] **Cross-dim coverage holes can still empty a slice** (rare, 1/121 in sampling): CDP104H pins CATEGORY="Cheltuieli de personal" + latest year, but that combo has no rows. Per-dim distincts can't see joint coverage; frontend drops the tile gracefully. If it shows up more, validate slices with one COUNT(*) probe at compose time.
- [ ] **v2 parity with v1, remaining gaps**: (a) multi-select series compare on the evolution tile (v1 typeahead, up to 8 CAEN lines — v2 tile control is single-select, series stays the composer's pick); (b) per-tile chart-type toggles (line↔area↔stacked); (c) cross-filtering — clicking a ranking bar / map county should set that value on the other tiles' controls; (d) tile-control state not synced to URL (global `?f=` is).
- [x] ~~**LOC103B_judet Map tab renders a line chart, not a choropleth**~~ — fixed 2026-07-19 (Perspectives Phase 1). Three stacked causes: (1) v1 snapshot gate was archetype-driven (null for split children) — now ranked_charts-driven; (2) legacy parquets ignored `group_by`/filters sent with SDMX names — `/data` now remaps both directions and answers with canonical column names; (3) `chart-geo.js` couldn't match legacy label geo values (leading spaces/diacritics) — now normalizes every known spelling to `geo_name_clean`. v2 renders county choropleth + time slider; v1 Map tab works.
- [ ] **AMG158G choropleth may have a color-scale binding bug**: `data/eval/smoke-screenshots/08_AMG158G_geo_demographic.png` shows a legend spanning 28 (Low) to 91 (High) but every region renders the same color for 2024 — either a genuinely uniform distribution that year or the map's color scale isn't binding per-county values correctly. Worth a quick manual check in the v2 dashboard.

## Perspectives roadmap (2026-07 audit — `docs/dashboard-audit-2026-07.md`)
- [x] **Phase 0 — truthful signals** (2026-07-19): B1 time_points fallback, B2 index/rate AVG + no index stacking (`query_builder.AVG_UNIT_TYPES` shared by dataset_data/insights/agent), B3 data-grounded exclude_total, B4 choropleth geo≥8, B5 pyramid gender_mf guard, B6 per-chart confidence, B7 seasonal YoY in insights, B8 ranked/composer series alignment (`retune_ranked_series`), B9 widest-coverage forced pins, parts-of-whole `is_composition` probe. Baseline rebuilt.
- [x] **Phase 1 — guaranteed dispatch + v2 parity** (2026-07-19): ranked_charts-driven v1 gates (choropleth for null-archetype splits, heatmap time-panel pill, selector-validated pyramid), choropleth time slider + play, composer degradations (small_multiples→line without facet, heatmap gains a time axis when series-less, no-parquet parents → split pills incl. corpus-derived children), v2 parity (sortable table, CSV/XLSX/INS, RO/EN, theme toggle, shared `echarts-theme.js`, Index/Δ% tile chips), unified empty states + insights-error notice, "top N / M" series-truncation disclosure, legacy-parquet group_by/filter remap with SDMX-canonical responses (fixes the silent unaggregated fallback), `_effective` whitespace-tolerant grounding (collision-guarded), hierarchical-dim root pinning (AGR201E KPI 10.3M→1.85M honest), `dataset-page.js`/`dataset-page-v2.js` → `_obsolete/js/`. Remaining for Phase 2: typeahead series multi-select, widget salvage from `view-controls.js`/`filter-panel.js`, ranking-tile total/part dedup (age-band canonicalization).
- [x] **Phase 2 — slices & controls** (2026-07-20): structured `notables` from insights (top/bottom slice chips in the sentence strip, click → cross-filter), chart-click cross-filtering (map county / ranking bar / series point → sets that value on tiles not charting the column, highlight chip on tiles that do; toggle to clear), transpose ⇄ chip (grouped/stacked/heatmap/bubble with x+series), per-capita ‰ toggle (count×geo via new `/api/reference/population?level=county|region|macroregion` from POP105A parquets, nearest-year fallback), log-scale chip when `right_skewed`, seasonal overlay chip (monthly/quarterly → one line per year via `seasonalOverlay()` in utils.js), upgraded global filter widgets (pill_group ≤6 / select / typeahead >25), tile-transform state in `?t=` URL param (restored on load), B7 seasonal YoY as its own KPI. Fill-rate KPI hidden when >100% (split datasets inherit parent coverage).
- [ ] **Seasonal overlay year pick** — series truncation is top-12-by-sum; for the seasonal view it should prefer the *most recent* 12 years instead (COM109B shows 12/16 with an arbitrary-looking mix).
- [ ] **Line-chart y-axis label clipping** — 8-digit values (LOC101B_judet evolution tile, ~8.000.000) get clipped at the left grid edge; chart-factory grid needs `containLabel` or wider left margin for large magnitudes.
- [x] **Phase 3 — correspondences** (2026-07-20): related-datasets rail on dashboard-v2 (new `/api/datasets/{code}/related` + `get_related()` in dataset_search.py — union of both `dataset_relationships` directions, split children fall back to parent rows with sibling splits prepended, similarity/shared-dim/time-range badges), topic tag chips in the header (from `dataset_tags` context+matrix_name sources, stoplist + subsumed-token dedup) → `/?q=tag` opens explore search prefilled, `compare.html` view (temporal overlay of each dataset's composer slice — Total series or widest disclosed slice, dual y-axis on differing unit types — plus county scatter with Pearson r at latest period when both are county-level), geo-click → "↗ profil" chip on spatial tiles linking `/place/{level}/{slug}` (client-side slugify mirroring place_service).
- [ ] **Compare view polish** — mixed time granularities interleave on the category axis (annual '2010' vs monthly '2010-01'); scatter could color counties by region (needs a county→region lookup exposed to the client); no URL state for slice choice.
- [ ] **Recompute dataset_relationships post-split** — the table predates 12-split-datasets, so split children borrow parent rows and non-canonical parents appear as related; a canonical-only rebuild would sharpen the rail.
- [ ] **Extract explore-app chrome into site-chrome.js** — `js/site-chrome.js` (used by dataset-v2/compare since the 2026-07-20 switchover) duplicates ~250 lines of topbar/search/sidebar behavior from the explore-app monolith; explore-app should delegate to the shared module so the two can't drift.
- [ ] **v1 retirement checklist** — v1 dataset view is now reachable only via `/?code=` (the v2 toolbar's "← v1"); once v2 has proven parity in real use, strip the v1 dashboard-view code from explore-app (~1,500 lines) and turn `/?code=` into a redirect.
- [ ] **query_builder follow-ups** (audit B10, unscheduled): ORDER BY only fires when TIME_PERIOD is an output column (legacy parquets return unordered); `group_by` fallback silently switches to all-dims unaggregated when no requested column exists — should error instead; currency treated globally non-additive (wrong for total-lei datasets like wage bill/exports — needs a per-dataset additive flag).
- [ ] **Precompute `is_composition` corpus-wide** in the pipeline (e.g. coverage profiler) so the eval harness regains full runtime parity and the probe cost leaves the request path.
