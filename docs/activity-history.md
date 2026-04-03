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
