[ins.gov2.ro](https://ins.gov2.ro/) - scrapes data from _TEMPO-Online_ ([statistici.insse.ro](http://statistici.insse.ro:8077/tempo-online))  

_INS Tempo Online but make it nice._


## Pipeline Scripts

Sequential data pipeline — run in order:

| Script | Output | Description |
|---|---|---|
| `1-fetch-context.py` | `data/1-indexes/ro/context.csv` | Fetches category/context hierarchy from TEMPO API |
| `2-fetch-matrices.py` | `data/1-indexes/ro/matrices.csv` | Fetches dataset list from TEMPO API |
| `3-fetch-metas.py` | `data/2-metas/ro/{id}.json` | Downloads JSON metadata for each dataset |
| `4-build-meta-index.py` | `data/1-indexes/ro/matrices-list.csv` | Builds summary index from metadata JSONs |
| `5-varstats-db.py` | `data/3-db/ro/tempo-indexes.db` | Creates SQLite DB from metadata |
| `6-fetch-csv.py` | `data/4-datasets/ro/` | Downloads raw CSV data files from TEMPO API |
| `7-data-compactor.py` | `data/5-compact-datasets/ro/` | Replaces text labels with numeric IDs in CSVs |
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
### alpha
- [x] fetch index
- [x] download csvs
- [x] refactor csvs -> db
- [x] dashboard / charts (alpha)
- [x] compact data

### Prepare for UI
- [ ] import into DuckDB / Parquet
- [ ] **split repositories** -> UI (ask 493n7 to look at initial docs, db structure and create clean specs)
    - [ ] api / FastAPI?
    - [ ] front end 


### beta
- [ ] some datasets are not downloaded
    - [x] 30k cells limit alert: _Selectia dvs actuala ar solicita 30600 celule. Datorita limitarilor impuse de o aplicatie web, va rugam sa rafinati cautarea Dvs. pentru a cobori sub pragul de 30000 de celule. Va multumim!_ see comments in [6-fetch-csv.py](6-fetch-csv.py)

### beta
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
