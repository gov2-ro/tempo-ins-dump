# Activity History

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
