# Activity History

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
