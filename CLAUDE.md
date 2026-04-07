# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview
Romanian National Institute of Statistics (INS) data scraper and explorer. Fetches, processes, and visualizes ~3,600 canonical statistical datasets from TEMPO Online. Three main components: a data pipeline (numbered Python scripts), a FastAPI + DuckDB web application (`app/`), and static HTML explorers (`ui/`).

## Architecture

### Data Pipeline (Numbered Scripts)
Sequential scripts process data through stages. All accept `--lang ro|en` (default: `ro`).

| # | Script | Output | Description |
|---|---|---|---|
| 1 | `1-fetch-context.py` | `data/1-indexes/{lang}/context.csv` | Fetches category hierarchy from TEMPO API |
| 2 | `2-fetch-matrices.py` | `data/1-indexes/{lang}/matrices.csv` | Fetches dataset list |
| 3 | `3-fetch-metas.py` | `data/2-metas/{lang}/{id}.json` | Downloads metadata per dataset |
| 4 | `4-build-meta-index.py` | `data/1-indexes/{lang}/matrices-list.csv` | Builds summary index from metadata |
| 5 | `5-varstats-db.py` | `data/3-db/{lang}/tempo-indexes.db` | Creates SQLite DB from metadata (legacy) |
| 6 | `6-fetch-csv.py` | `data/4-datasets/{lang}/` | Downloads raw CSV data from TEMPO API |
| 7 | `7-data-compactor.py` | `data/5-compact-datasets/{lang}/` | Replaces text labels with numeric IDs |
| 8 | `8-setup-duckdb-schema.py` | `data/corpus/metadata.duckdb` | Creates DuckDB schema (contexts, matrices, dimensions) |
| 9 | `9-csv-to-parquet.py` | `data/parquet-v2/ro/` | Converts compacted CSVs to Parquet (intermediate) |
| 10 | `10-import-metadata.py` | DuckDB tables | Imports all metadata into DuckDB |
| 10 | `10-classify-dimensions.py` | `dimension_options_parsed`, `matrix_profiles` | Parses/classifies dimensions, detects archetypes |
| 10 | `10-sdmx-export.py` | `data/6-sdmx-csv/ro/` | Converts to SDMX-CSV 2.0 |
| 11 | `11-build-sdmx-codes.py` | DuckDB code mapping tables | Builds SDMX code mappings |
| 11 | `11-coverage-profiler.py` | `dataset_coverage` DuckDB table | Analyzes data completeness |
| 12 | `12-parquet-to-sdmx.py` | `data/corpus/parquet/` | Transforms parquet-v2 to SDMX-native canonical parquet |
| 12 | `12-split-datasets.py` | `data/corpus/parquet/` | Splits inconsistent datasets into clean sub-datasets |

Note: `{lang}` is `ro` or `en`.

### Other Root Scripts

| Script | Description |
|---|---|
| `generate_view_profiles.py` | Generates per-dataset JSON view profiles → `data/corpus/view-profiles/` |
| `build-geo-regions.py` | Dissolves county GeoJSON into regions/macroregions |
| `split_rules.py` | Split rules engine — detects datasets needing structural splits |
| `detect_trends.py` | Detects trends, YoY growth, seasonality per dataset |
| `duckdb_config.py` | Central config: paths for all DuckDB/Parquet processing |
| `duckdb-browser.py` | Flask browser for exploring DuckDB + Parquet data |
| `build-dataset-metadata.py` | Scans CSVs, calculates stats → `ui/data/dataset-metadata.json` |
| `get-news.py` | Scrapes INS news/press releases |
| `test_chart_selector.py` | Tests chart selection engine across all datasets |

### FastAPI Application (`app/`)
Primary web application — FastAPI + DuckDB + Parquet backend, Vanilla JS + ECharts frontend.

```
app/
  main.py              — FastAPI entry point, mounts routers + static files
  config.py            — DB_PATH (corpus/metadata.duckdb), PARQUET_DIR (corpus/parquet), MAX_DATA_ROWS=50000
  db.py                — DuckDB cursor-per-request (critical for concurrency)
  routers/
    categories.py      — /api/categories endpoints
    datasets.py        — /api/datasets list + search
    dataset_data.py    — /api/datasets/{id}/data + metadata
  services/
    dataset_search.py  — search/list datasets (shared by route, MCP, agent)
    dataset_meta.py    — full dataset metadata + chart config (shared by route, MCP, agent)
    chart_config.py    — archetype → chart config mapping
    chart_selector.py  — chart type selection engine
    query_builder.py   — DuckDB query construction
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

### StatExplorer (`explorer/`)
Alternative Tableau-inspired explorer with i18n support and component-based JS.

```
explorer/
  main.py              — FastAPI entry ("StatExplorer")
  config.py, db.py
  routers/             — categories, datasets, dataset_data
  services/            — chart_selector, query_builder, translations
  static/
    js/charts/         — chart-bar, chart-geo, chart-line, chart-heatmap, chart-pyramid, etc.
    js/components/     — ChartCanvas, DatasetPicker, FilterBar, LeftSidebar, TopNav, FooterBar
    js/lib/            — api, i18n, utils
    css/explorer.css
```

### Static UI Explorers (`ui/`)
Standalone HTML pages served via `python -m http.server 8000`:

| Page | Description |
|---|---|
| `dataset-navigator.html` | Primary unified dataset browser (category tree + cards + filters) |
| `dataset-profile.html` | Individual dataset profile view |
| `profile-preview.html` | Quick profile preview |
| `index.html` + `app.js` | Dimension browser with tag-based interface |
| `category-browser.html` | Grid layout of all categories with counts |
| `tree-browser.html` | Hierarchical 3-level category navigation |

Legacy/archived UIs are in `ui/prev/` and `ui/v1/`.

### Dev MCP Server (`tools/tempo-dev-mcp/`)
Claude Code introspection tools for this repo. Registered in `.mcp.json` (repo-local), auto-loaded every session.

| Tool | Description |
|---|---|
| `tempo_dataset_info(matrix_code)` | Full metadata + dims + chart scores + sample rows + coverage/trends in one call |
| `tempo_search_datasets(query, has_geo, archetype, limit)` | Catalog search (LIKE-based, FTS upgrade planned) |
| `tempo_chart_signature(matrix_code)` | `build_signature()` + `select_charts()` scores per chart type |
| `tempo_sample(matrix_code, n, filters)` | Labelled rows from parquet |

All tools import from the shared service layer: `app/services/dataset_search.py` and `app/services/dataset_meta.py`.

## Development Commands

### Python Environment
Always activate: `source ~/devbox/envs/240826/bin/activate`

### Main App (FastAPI)
```bash
uvicorn app.main:app --reload --port 8080
# http://localhost:8080
```

### Static UI Pages
```bash
python -m http.server 8000
# http://localhost:8000/ui/dataset-navigator.html
# http://localhost:8000/ui/category-browser.html
# http://localhost:8000/ui/tree-browser.html
```

### StatExplorer (alternative)
```bash
uvicorn explorer.main:app --reload --port 8081
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
    parquet/                 SDMX-native canonical parquets — 3,632 files
    view-profiles/           Per-dataset JSON view profiles — ~3,800 files

  # Archived (not needed for app or pipeline)
  _obsolete/                 Legacy intermediates: parquet-v1, 5-compact-datasets, 6-sdmx-csv, etc.
```

### Data Flow
1. Scrape contexts and dataset lists from INS TEMPO API
2. Download metadata for each dataset
3. Build searchable dimension index + SQLite DB
4. Download CSV data files (handles 30k-cell API limit)
5. Compact data (replace labels with IDs)
6. Create DuckDB schema + import metadata
7. Convert to Parquet → classify dimensions → detect archetypes
8. SDMX code mapping → transform to v3 parquet → split datasets
9. Generate view profiles → serve via FastAPI app

## Technology Stack
- **Backend**: FastAPI + DuckDB + Parquet
- **Frontend**: Vanilla HTML5/CSS3/JS (ES6+), ECharts for visualization
- **Database**: DuckDB (16 tables in `corpus/metadata.duckdb`)
- **Data**: Parquet files (SDMX-native, 3,632 canonical files in `corpus/parquet/`)
- **GeoJSON**: County/region/macroregion polygons for choropleth maps
- **Deployment**: Docker + Fly.io (also Oracle Cloud, HF Spaces)

## Profiling & Validation
- `profiling/data_profiler.py` - Main data profiling tool
- `profiling/validation_rules.py` - Validation rule definitions
- `profiling/variable_classifier.py` - Variable type classification
- `profiling/unit_classifier.py` - Unit of measurement classification

## Development Best Practices
- Always test locally before committing
- Use browser dev tools for frontend debugging
- Check console for JavaScript errors
- Validate API responses with browser network tab
- Test with actual INS data samples
- **DuckDB concurrency**: `get_conn()` returns `_conn.cursor()` not `_conn` — parallel requests need separate cursors
- **DuckDB write lock**: Only ONE process can write at a time. Stop dev server before running pipeline scripts

## Persona
- Act as a senior full-stack developer with deep knowledge.
- When possible run the code in your terminal to verify it works as expected. When possible make the tests short (timewise) - for example, limit the number of events or sources processed while testing. 
- provide relevant output messages and logging.
- generally create a debug mode with verbose logging for complex changes. Debug mode should be a flag in the configuration file.
- use `npx playwright` (Playwright already installed) when needed to test or debug the final results.

## General Coding Principles
- Focus on simplicity, readability, performance, maintainability, testability, and reusability.
- Less code is better; lines of code = debt.
- Make minimal code changes and only modify relevant sections.
- Suggest solutions proactively and treat the user as an expert.
- Write correct, up-to-date, bug-free, secure, performant, and efficient code.
- If unsure, say so instead of guessing


Please keep your answers concise and to the point.
Don’t just agree with me — feel free to challenge my assumptions or offer a different perspective.
Act as a senior full-stack developer with deep knowledge. Suggest improvements, optimizations, or best practices where applicable.
If a question or request is ambiguous or would benefit from clarification, ask follow-up questions before answering or getting to work.

When working with large files (>300 lines) or complex changes always start by creating a detailed plan BEFORE making any edits.
When refactoring large files break work into logical, independently functional chunks, ensure each intermediate state maintains functionality.

## Bug Handling
- If you encounter a bug or suboptimal code, add a TODO comment outlining the problem.

## RATE LIMIT AVOIDANCE
- For very large files, suggest splitting changes across multiple sessions
- Prioritize changes that are logically complete units
- Always provide clear stopping points

# important-instruction-reminders
Generally do what has been asked; nothing more, nothing less, but provide suggestions when you think it would be useful/smart – when it would support the intention of this project. 
Avoid creating files unless they're absolutely necessary for achieving your goal.
Prefer editing an existing file to creating a new one.


# Other notes

When detecting things that need to be addressed later, add to `docs/BACKLOG.md`. Use a checkbox `- [ ]` entry with a clear title and enough context to act on it later.

After completing any meaningful work, add an entry to `docs/activity-history.md` under a `## YYYY-MM-DD — Short Title` heading. Include what was done, why, and any non-obvious decisions.

When running Python commands, always first activate the following venv `~/devbox/envs/240826/` (/Users/pax/devbox/envs/240826/bin/activate)

See `data/4-datasets-slim-samples/50` and `data/4-datasets-slim-samples/100` first - when samplinga datasets, it contains a smaller number of sample records (50 or 100) for analysis with using less context. 

The git repository is at https://github.com/gov2-ro/tempo-ins-dump/ 