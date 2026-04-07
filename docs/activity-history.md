# Activity History

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
