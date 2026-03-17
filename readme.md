[ins.gov2.ro](https://ins.gov2.ro/) - scrapes data from _TEMPO-Online_ ([statistici.insse.ro](http://statistici.insse.ro:8077/tempo-online))  

_INS Tempo Online but make it nice._


## Pipeline Scripts

Sequential data pipeline — run in order. All scripts accept `--lang ro|en` (default: `ro`).

| Script | Output | Description |
|---|---|---|
| `1-fetch-context.py` | `data/1-indexes/{lang}/context.csv` | Fetches category/context hierarchy from TEMPO API |
| `2-fetch-matrices.py` | `data/1-indexes/{lang}/matrices.csv` | Fetches dataset list from TEMPO API |
| `3-fetch-metas.py` | `data/2-metas/{lang}/{id}.json` | Downloads JSON metadata for each dataset |
| `4-build-meta-index.py` | `data/1-indexes/{lang}/matrices-list.csv` | Builds summary index from metadata JSONs |
| `5-varstats-db.py` | `data/3-db/{lang}/tempo-indexes.db` | Creates SQLite DB from metadata |
| `6-fetch-csv.py` | `data/4-datasets/{lang}/` | Downloads raw CSV data files from TEMPO API |
| `7-data-compactor.py` | `data/5-compact-datasets/{lang}/` | Replaces text labels with numeric IDs in CSVs |
| `8-setup-duckdb-schema.py` | `data/tempo_metadata.duckdb` | Creates DuckDB schema (contexts, matrices, dimensions) |
| `9-csv-to-parquet.py` | `data/parquet/ro/` | Converts compacted CSVs to Parquet |
| `10-import-metadata.py` | DuckDB tables | Imports all metadata into DuckDB |
| `10-classify-dimensions.py` | `dimension_options_parsed`, `matrix_profiles` | Parses/classifies dimension options, detects archetypes |
| `10-sdmx-export.py` | `data/6-sdmx-csv/ro/` | Converts compacted CSVs to SDMX-CSV 2.0 |
| `11-coverage-profiler.py` | `dataset_coverage` DuckDB table | Analyzes data completeness per dataset |
| `detect_trends.py` | `dataset_trends` DuckDB table | Detects trends, YoY growth, seasonality per dataset |

### Other root-level scripts

| Script | Description |
|---|---|
| `duckdb_config.py` | Central config: paths for all DuckDB/Parquet processing |
| `duckdb-browser.py` | Flask browser for exploring DuckDB + Parquet data |
| `build-dataset-metadata.py` | Scans CSVs, calculates stats → `ui/data/dataset-metadata.json` |
| `test_chart_selector.py` | Tests chart selection engine across all 1,886 datasets |

## utils/

| Script | Description |
|---|---|
| `14-parquet-to-ids.py` | Converts Parquet from text labels → numeric IDs → `data/parquet-v2/ro/` |
| `13-slim-samples-to-markdown.py` | Converts slim-sample CSVs to markdown for LLM analysis |
| `12-csv-headers-index.py` | Extracts headers from all CSVs → `data/2-metas/csv-headers-index.csv` |
| `11-slim-samples.py` | Samples up to 100 rows per dataset → `data/4-datasets-slim-samples/` |
| `build-dimension-index.py` | Builds searchable SQLite index from metadata JSONs |
| `build-enhanced-navigator-index.py` | Builds optimized SQLite + JSON indexes for the dataset navigator UI |
| `build-static-index.py` | Generates static JSON indexes for client-side explorer |
| `query-dimensions.py` | CLI query tool for the dimension index SQLite DB |
| `query-duckdb.py` | Query helper for DuckDB + Parquet |
| `explore-data.py` | Exploration script showing DuckDB + Parquet integration patterns |
| `export-db-to-json.py` | Exports dimension index SQLite → `ui/data/dimension_index.json` |
| `check-meta-consistency.py` | Validates consistency between metadata directories |

## profiling/

| Script | Description |
|---|---|
| `data_profiler.py` | Main profiler: validates CSV structure, classifies column types, generates reports |
| `variable_classifier.py` | Classifies variable labels using a CSV ruleset |
| `unit_classifier.py` | Classifies unit-of-measure labels semantically |
| `validation_rules.py` | Modular validation framework (column names, data content, file structure) |
| `build_indexes.py` | Builds keyword/theme indexes from datasets → `data/indexes/` |
| `tool-list-headers.py` | Extracts CSV headers → `data/2-csv-cols/ro/` |
| `tool-sample-csvs.py` | Creates sampled CSVs (first/mid/last 5 rows) → `data/datasets-samples/ro/` |
| `tool-word-frequency.py` | Romanian word frequency analysis of dataset titles |

## Data

```
data/
  1-indexes/<lang>/   matrices.csv, context.csv
  2-metas/<lang>/     {dataset-id}.json — metadata per dataset
  3-db/               tempo-indexes.db (SQLite, legacy)
  4-datasets/ro/      raw CSVs from TEMPO API
  5-compact-datasets/ CSVs with numeric IDs instead of labels
  6-sdmx-csv/         SDMX-CSV 2.0 output
  parquet/ro/         Parquet (text labels)
  parquet-v2/ro/      Parquet (numeric IDs) — used by web app
  tempo_metadata.duckdb — main metadata DB
```



## Roadmap 

### current
- [x] fetch english labels
- [ ] revise propfiling
- [ ] UI


### alpha
- [x] fetch index
- [x] download csvs
- [x] refactor csvs -> db
- [x] dashboard / charts (alpha)
- [x] compact data

### Prepare for UI
- [x] import into DuckDB / Parquet
- [ ] **split repositories** -> UI (ask 493n7 to look at initial docs, db structure and create clean specs)
    - [ ] api / FastAPI?
    - [ ] front end 


### beta
- [x] some datasets are not downloaded
    - [x] 30k cells limit alert: _Selectia dvs actuala ar solicita 30600 celule. Datorita limitarilor impuse de o aplicatie web, va rugam sa rafinati cautarea Dvs. pentru a cobori sub pragul de 30000 de celule. Va multumim!_ see comments in [6-fetch-csv.py](6-fetch-csv.py)

- [x] categorise filters
- [ ] auto charts
- [ ] dataset filtering, charting options


### UI
- [x] filter datasets by dimension
- [x] add context info
- [x] permalinks #variables in url
- [x] combine labels/dimensions
- [x] show dataset preview
- [x] collapse definition
- [ ] tree nav
- [ ] basic stats / charts - per all years, per last year - for localitati normeaza la populatie

see also: [ui/readme.md](ui/readme.md)
 
## Notes

> Atentie! Nomenclatoarele care prezinta doar optiunea "Total" se vor completa automat cu alte optiuni doar daca nomenclatorului anterior i se deselecteaza optiunea "Total" si i se alege o singura alta optiune,

> Important! Unitatile de masura sunt implicit selectate toate pentru a preveni rezultate goale atunci cand se combina cereri incompatibile (spre exemplu, s-ar putea selecta productia de porumb in litri; sau o valoare in ROL dupa denominarea din 2005, etc.).

---

## docs/ Summary

### Core Architecture
- **[DUCKDB_SPECS.md](docs/DUCKDB_SPECS.md)** — Schema design for the DuckDB + Parquet hybrid: tables, file structure, query examples. The canonical DB spec.
- **[DUCKDB_GUIDE.md](docs/DUCKDB_GUIDE.md)** — Practical query patterns and performance tips for DuckDB + Parquet usage.
- **[classify-dimensions.md](docs/classify-dimensions.md)** — Spec for dimension classification/normalization: semantic types, parsing rules, archetype detection.

### Application Specs
- **[app-spec.md](docs/app-spec.md)** — Full v1 spec: FastAPI + DuckDB backend, ECharts frontend, all phases from data prep to UI polish.
- **[app-spec-v2.md](docs/app-spec-v2.md)** — v2 redesign spec. Discovery-first approach leveraging enriched metadata (tags, trends, relationships, chart recommendations).
- **[chart-framework-spec.md](docs/chart-framework-spec.md)** — Generic chart selection engine: 15 chart types, dimension role assignment, filter system.

### Data & Profiling
- **[data analysis.md](docs/data%20analysis.md)** — Framework for systematic profiling, classification, and dashboard generation.
- **[data notes.md](docs/data%20notes.md)** — Raw notes on data quirks, dimension patterns, edge cases.
- **[TODO_COMPACTION.md](docs/TODO_COMPACTION.md)** — Known issues with CSV compaction and label normalization fixes.
- **[PROFILING_AND_EXPLORER.md](docs/PROFILING_AND_EXPLORER.md)** — Guide to the CSV profiler and Explorer UI: output paths, validation flags, API endpoints.

### UI / Legacy
- **[STATIC-CONVERSION-SUMMARY.md](docs/STATIC-CONVERSION-SUMMARY.md)** — Documents conversion from server-based to static site explorer.
- **[STATIC-VS-PYTHON-COMPARISON.md](docs/STATIC-VS-PYTHON-COMPARISON.md)** — Test results showing 100% feature parity between Python and static versions.
- **[JUDET-SPLIT-IMPLEMENTATION.md](docs/JUDET-SPLIT-IMPLEMENTATION.md)** — How large datasets are split by county (judet) to stay under the 30k-cell API limit.

### Deployment
- **[DEPLOY-DREAMHOST.md](docs/DEPLOY-DREAMHOST.md)** — Deployment guide for shared hosting via Passenger WSGI.

### Agents Pipeline (`docs/agents/`)
- **[README.md](docs/agents/README.md)** — Overview of the 6-agent enrichment pipeline (produces value_profiles, coverage, trends, tags, relationships, chart_recs).
- **[pipeline.md](docs/agents/pipeline.md)** — Orchestration: 3 phases, 7 agents, execution order and verification steps.
- **phase1-value-profiler.md** — Agent 1A: min/max/mean/percentiles/distribution per dataset.
- **phase1-coverage-profiler.md** — Agent 1B: time/geo coverage, fill rate, sparsity.
- **phase1-trend-detector.md** — Agent 1C: trend direction, YoY growth, seasonality, breakpoints.
- **phase2-topic-tagger.md** — Agent 2A: bilingual semantic tags from context + dataset names.
- **phase2-dimension-overlap.md** — Agent 2B: related-dataset discovery via dimension fingerprints.
- **phase2-chart-recommender.md** — Agent 2C: data-driven chart type recommendations.
- **phase3-ia-designer.md** — Agent 3A: generates the full information architecture spec from enriched metadata.
