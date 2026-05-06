# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview
Romanian National Institute of Statistics (INS) data scraper and explorer. Fetches, processes, and visualizes ~3,700 canonical statistical datasets from TEMPO Online. Two main components: a data pipeline (numbered Python scripts) and a FastAPI + DuckDB web application (`app/`).

## Architecture

### Data Pipeline (Numbered Scripts)
Sequential. All accept `--lang ro|en` (default: `ro`). Output paths + full details in [readme.md](readme.md).

| # | Script | Purpose |
|---|---|---|
| 1 | `1-fetch-context.py` | Fetch category hierarchy from TEMPO API |
| 2 | `2-fetch-matrices.py` | Fetch dataset list |
| 3 | `3-fetch-metas.py` | Download metadata per dataset |
| 4 | `4-build-meta-index.py` | Build summary index from metadata |
| 5 | `5-varstats-db.py` | Create SQLite DB from metadata (legacy) |
| 6 | `6-fetch-csv.py` | Download raw CSV data |
| 7 | `7-data-compactor.py` | Replace text labels with numeric IDs |
| 8 | `8-setup-duckdb-schema.py` | Create DuckDB schema (`corpus/metadata.duckdb`) |
| 9 | `9-csv-to-parquet.py` | Convert compacted CSVs to intermediate Parquet (`parquet-v2/`) |
| 10 | `10-import-metadata.py` | Import metadata into DuckDB |
| 10 | `10-classify-dimensions.py` | Parse/classify dimensions, detect archetypes |
| 10 | `10-sdmx-export.py` | Convert to SDMX-CSV 2.0 |
| 11 | `11-build-sdmx-codes.py` | Build SDMX code mappings |
| 11 | `11-coverage-profiler.py` | Analyze data completeness → `dataset_coverage` |
| 12 | `12-parquet-to-sdmx.py` | Transform parquet-v2 → canonical SDMX parquet (`corpus/parquet/`) |
| 12 | `12-split-datasets.py` | Split inconsistent datasets into clean sub-datasets |

**Orchestrator**: `update-pipeline.py` — incremental runs from INS news feed (per-matrix: meta → CSV → parquet → SDMX → split → view profile).

### Other Root Scripts
`generate_view_profiles.py` (per-dataset JSON view profiles), `generate_sdmx_yaml.py`, `build-geo-regions.py` (county GeoJSON → regions/macroregions), `build-static-site.py`, `split_rules.py`, `detect_trends.py`, `duckdb_config.py` (path config), `duckdb-browser.py`, `get-news.py`, `test_chart_selector.py`. See readme.md for descriptions. Helper scripts (audit, baselines, search index, canonicalize, normalize) are in `scripts/`.

### FastAPI Application (`app/`)
Primary web application — FastAPI + DuckDB + Parquet backend, Vanilla JS + ECharts frontend.

```
app/
  main.py              — FastAPI entry point, mounts routers + static files
  config.py            — DB_PATH (corpus/metadata.duckdb), PARQUET_DIR (corpus/parquet), MAX_DATA_ROWS=50000
  db.py                — DuckDB cursor-per-request (critical for concurrency)
  routers/
    ask.py             — /api/ask LLM-backed Q&A
    categories.py      — /api/categories endpoints
    datasets.py        — /api/datasets list + search
    dataset_data.py    — /api/datasets/{id}/data + metadata
    sdmx.py            — SDMX 2.1 REST endpoints (/sdmx/2.1/data, /datastructure, /dataflow)
  services/
    agent.py                — LLM agent wiring (search + answer)
    dataset_search.py       — search/list datasets (shared by route, MCP, agent)
    dataset_meta.py         — full dataset metadata + chart config (shared by route, MCP, agent)
    chart_selector.py       — chart type selection engine
    chart_selector_eval.py  — bulk re-score + diff-against-baseline (MCP eval harness)
    agent_eval.py           — search-quality regression harness (MCP eval harness)
    headlines.py            — KPI/headline extraction (driven by headline_config.json)
    llm_client.py           — shared LLM client wrapper
    query_builder.py        — DuckDB query construction
  static/
    js/
      dataset-page.js  — main dataset view controller
      chart-factory.js — dispatches to chart modules
      chart-geo.js     — choropleth map (geo_time archetype)
      chart-demographic.js — grouped bar (demographic archetype)
      filter-panel.js  — dynamic filter UI
      api.js, utils.js, data-table.js, view-controls.js, period-browser.js
    css/               — dataset.css, datasets.css, main.css, dataset-v2.css
    geo/               — romania-counties.geojson, romania-regions.geojson, romania-macroregions.geojson
```


### Dev MCP Server (`tools/tempo-dev-mcp/`)
Claude Code introspection tools for this repo. Registered in `.mcp.json` (repo-local), auto-loaded every session. Full docs: `tools/tempo-dev-mcp/README.md`.

| Tool | Parameters | Returns |
|---|---|---|
| `tempo_dataset_info` | `matrix_code: str` | Full metadata + dims (options capped 50/dim) + chart scores + coverage/trends + 10 sample rows |
| `tempo_search_datasets` | `query: str, has_geo?: bool, archetype?: str, limit?: int(10)` | `{total, datasets[]}` — catalog cards with archetype, time_range, unit_type |
| `tempo_chart_signature` | `matrix_code: str` | `{archetype, signature, ranked_charts[]}` — chart scores + roles per type |
| `tempo_sample` | `matrix_code: str, n?: int(10), filters?: json_str` | `{rows[]}` — labelled SDMX rows from parquet |
| `tempo_query` | `matrix_code: str, filters?: json_str, group_by?: json_str, limit?: int(1000)` | `{columns, rows, row_count}` — aggregated data via query_builder |
| `tempo_catalog_stats` | `group_by?: str("archetype")` | Corpus-level breakdowns by archetype/category/unit_type/geo |
| `tempo_routes` | — | All FastAPI routes: `{total, routes[{methods, path, name, endpoint, tags}]}` |
| `tempo_call_endpoint` | `method: str, path: str, params_json?: str, body_json?: str` | In-process TestClient call: `{status_code, content_type, body, json?}` (body capped 8k) |
| `tempo_outdated` | `days?: int(180), limit?: int(50)` | Stale/null `ultima_actualizare` lists with reliability caveat |
| `tempo_pipeline_status` | `recent_log_count?: int(10)` | `last-pipeline-run.txt` + corpus audit summary + recent logs with err/warn counts |
| `tempo_dataset_lineage` | `matrix_code: str` | Per-stage artifact presence (5 stages) + DuckDB row presence + splits/parent |
| `tempo_check_view_profiles` | — | Audits `corpus/view-profiles/` vs parquets + DB: `{summary, missing_vps, orphan_vps, version_drift, archetype_mismatches, top_warnings, …}` |
| `tempo_eval_chart_selector` | `score_threshold?: float(0.05)` | Diffs `chart_selector` vs `data/eval/chart_selector_baseline.json`: `{summary, primary_changes, top_set_changes, confidence_changes, score_drifts, missing, added}` |
| `tempo_eval_agent` | — | Diffs `search_datasets` quality vs `data/eval/agent_search_baseline.json` for questions in `agent_questions.yaml`: `{summary, top_set_changes, order_changes, total_hit_drifts, missing, added}` |

All tools import from the shared service layer: `app/services/dataset_search.py`, `app/services/dataset_meta.py`, `app/services/chart_selector_eval.py`, and `app/services/agent_eval.py`.

## Development Commands

### Python Environment
Always activate: `source ~/devbox/envs/240826/bin/activate`

### Main App (FastAPI)
```bash
uvicorn app.main:app --reload --port 8080
# http://localhost:8080
```


### DuckDB Browser
```bash
python duckdb-browser.py
# Flask-based DuckDB + Parquet explorer
```

### Data Pipeline Examples
```bash
python 7-data-compactor.py --matrix ZDP1321     # Single matrix debug
python 12-split-datasets.py --matrix ACC101B    # Split single dataset
python generate_view_profiles.py                 # Regenerate view profiles
```

### Deployment
```bash
bash scripts/prepare-deploy-data.sh   # Stage data for deployment
# Dockerfile + fly.toml for Fly.io (shared-cpu-1x, 512MB, Amsterdam)
# deploy/oracle/ for Oracle Cloud, deploy/hf-spaces/ for HF Spaces
```

**Live URL**: https://ins.gov2.ro (Fly.io, app: `tempo-ins-explorer`)

## Data Structure

```
data/
  # Pipeline stages (scripts write here)
  1-indexes/{lang}/          context.csv, matrices.csv
  2-metas/{lang}/            {dataset-id}.json — metadata per dataset
  4-datasets/{lang}/         raw CSVs from TEMPO API
  4-datasets-slim-samples/   50/ and 100/ row samples for LLM analysis
  parquet-v2/ro/             Parquet (numeric IDs) — pipeline intermediate, read by scripts 12-*
  meta/                      Reference data (judet CSVs, SIRUTA)
  logs/                      Pipeline execution logs
  sdmx-dashboards/           SDMX dashboard YAML configs (generate_sdmx_yaml.py)

  # Final output — app reads from here
  corpus/
    metadata.duckdb          Main DuckDB metadata (16 tables)
    search.duckdb            Search index DB
    parquet/                 SDMX-native canonical parquets — 3,706 files
    view-profiles/           Per-dataset JSON view profiles — 3,523 files
  eval/                      Eval baselines (chart_selector, agent_search)

  # Archived (not needed for app or pipeline)
  _obsolete/                 Legacy intermediates: parquet-v3, 5-compact-datasets, 6-sdmx-csv, 3-db, etc.
```

### Data Flow
1. Scrape contexts + dataset lists from INS TEMPO API → download metadata per dataset
2. Build summary index + (legacy) SQLite DB
3. Download CSV data (handles 30k-cell API limit) → compact (labels → numeric IDs)
4. Create DuckDB schema → import metadata → classify dimensions / detect archetypes
5. Convert intermediates to Parquet → SDMX code mapping → canonical SDMX parquet → split inconsistent datasets
6. Generate view profiles → serve via FastAPI app

## Technology Stack
- **Backend**: FastAPI + DuckDB + Parquet
- **Frontend**: Vanilla HTML5/CSS3/JS (ES6+), ECharts for visualization
- **Database**: DuckDB (16 tables in `corpus/metadata.duckdb`)
- **Data**: Parquet files (SDMX-native, 3,706 canonical files in `corpus/parquet/`)
- **GeoJSON**: County/region/macroregion polygons for choropleth maps
- **Deployment**: Docker + Fly.io (also Oracle Cloud, HF Spaces)

## Development Best Practices
- **DuckDB concurrency**: `get_conn()` returns `_conn.cursor()` not `_conn` — parallel requests need separate cursors
- **DuckDB write lock**: Only ONE process can write at a time. Stop dev server before running pipeline scripts
- Test locally before committing; verify via browser dev tools (console + network tab) for frontend changes
- Use `npx playwright` (already installed) to test/debug final UI results
- For complex changes, add a debug-mode flag with verbose logging

## Working Style
- Act as a senior full-stack developer; suggest improvements/optimizations proactively
- Keep answers concise; challenge assumptions rather than just agreeing
- If a request is ambiguous, ask follow-up questions before working
- For large files (>300 lines) or complex changes, plan BEFORE editing; break refactors into independently functional chunks
- Less code = less debt — make minimal, targeted changes; do not add files unless necessary
- If unsure, say so instead of guessing

# Notes

- **Backlog**: When detecting things to address later, add a `- [ ]` entry with title + enough context to `docs/BACKLOG.md`
- **Activity log**: After meaningful work, add an entry to `docs/activity-history.md` under `## YYYY-MM-DD — Short Title` (what + why + non-obvious decisions)
- **Slim samples**: When sampling datasets, prefer `data/4-datasets-slim-samples/50` (or `/100`) for smaller records and lower context use
- **Repo**: https://github.com/gov2-ro/tempo-ins-dump/
