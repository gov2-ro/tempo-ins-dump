# INS TEMPO Data Explorer — Project Memory

## Project
Romanian INS TEMPO dataset explorer. FastAPI + DuckDB backend, Vanilla JS + ECharts frontend.
Working directory: `/Users/pax/devbox/gov2/tempo-ins-dump`
**Live URL**: https://ins.gov2.ro (Fly.io, app: `tempo-ins-explorer`)

## Dev Server
```bash
source ~/devbox/envs/240826/bin/activate && uvicorn app.main:app --reload --port 8080
```
Visit: http://localhost:8080

## Key Files
- `app/main.py` — FastAPI app entry point
- `app/config.py` — DB_PATH, PARQUET_DIR, MAX_DATA_ROWS=50000
- `app/db.py` — DuckDB cursor per request (critical for concurrency)
- `app/services/chart_config.py` — archetype → chart config mapping
- `app/static/js/dataset-page.js` — main dataset view controller
- `app/static/js/chart-factory.js` — dispatches to chart modules
- `app/static/js/chart-geo.js` — choropleth map (geo_time archetype)
- `app/static/js/chart-demographic.js` — grouped bar (demographic archetype)
- `app/static/js/filter-panel.js` — dynamic filter UI
- `app/static/geo/romania-counties.geojson` — 42 counties, source: expertforum.ro

## Archetypes & Charts
| Archetype | Primary Chart | Notes |
|---|---|---|
| geo_time | choropleth | Romania county map + timeline |
| demographic | grouped_bar | Age × gender bars + timeline |
| time_residence | line | Urban/rural lines |
| time_series | line | Default |

## Critical Fixes
- **DuckDB concurrency**: `get_conn()` returns `_conn.cursor()` not `_conn` — parallel requests need separate cursors
- **Choropleth data**: For map mode, remove non-geo/non-time filters (parquet may lack "Total" IDs that metadata lists). Chart deduplicates per county via last-write-wins dict.
- **Choropleth limit**: Use `limit=50000` for choropleth queries (need all years × counties)

## Data
- 1,886 parquet files in `data/parquet-v2/ro/`
- DuckDB metadata: `data/tempo_metadata.duckdb`
- GeoJSON county name format: ASCII (e.g., "Bistrita-Nasaud", "Municipiul Bucuresti")

## Enriched Metadata (v2 Pipeline)
DuckDB now has 12 tables (6 original + 6 enriched):
- `dataset_value_profiles` — 1,886 rows: statistical profiles (min/max/mean/percentiles/magnitude/distribution_shape)
- `dataset_coverage` — 1,889 rows: time/geo coverage, fill_rate, freshness, sparse_dims
- `dataset_trends` — 1,886 rows: trend_direction, slope, YoY growth, breakpoints, seasonality, geo outliers
- `dataset_tags` — 92,612 bilingual tags (context/matrix_name/indicator sources)
- `dataset_relationships` — 18,880 relationships (top 10 per dataset, similarity 0.47-1.0)
- `dataset_chart_recs` — 5,365 recs across 12 chart types (avg 2.8/dataset)

English translations: `data/1-indexes/en/matrices.csv`, `data/1-indexes/en/context.csv`

## Sub-Agent Gotchas
- DuckDB write lock: only ONE process can write at a time. Stop dev server before running profilers.
- Agents that need write access should use fallback DB pattern (write to separate .duckdb, merge later)
- `dimension_options` alias `do` is reserved in DuckDB SQL — use `dopt` instead
- value_profiles originally used `matrix_id` column name — renamed to `matrix_code` for consistency

## Status
- [x] Parquet ID conversion
- [x] FastAPI backend (v1)
- [x] Dataset view (filters, chart, table)
- [x] Datasets list + landing page
- [x] Choropleth map module
- [x] Demographic grouped bar module
- [x] v2 data enrichment pipeline (6 agents)
- [x] v2 IA spec (`docs/app-spec-v2.md`)
- [ ] v2 UI build
