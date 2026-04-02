# Activity History

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
