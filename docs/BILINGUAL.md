# Bilingual Support (ro / en)

The pipeline and app support both Romanian (`ro`) and English (`en`) data. All scripts default to `ro`. This document covers the architecture, how to run the pipeline for each language, and how the app serves both.

---

## Architecture

Two storage layers, each with its own language strategy:

**Parquet files** — separate directories per language:
```
data/parquet-v2/ro/   ← Romanian data files
data/parquet-v2/en/   ← English data files
```

**DuckDB metadata** (`data/tempo_metadata.duckdb`) — single database with a `lang` column in all metadata tables (`contexts`, `matrices`, `dimensions`). Both languages coexist in one DB, filtered at query time.

Enrichment tables (`dataset_value_profiles`, `dataset_coverage`, `dataset_trends`, `dataset_tags`, `dataset_relationships`, `dataset_chart_recs`) are **language-agnostic** — they contain numeric statistics and relationships that apply across languages.

---

## Running the Pipeline

### Fetching scripts (1–7)

All accept `--lang ro|en` (default `ro`):

```bash
python 1-fetch-context.py --lang en
python 2-fetch-matrices.py --lang en
python 3-fetch-metas.py --lang en
python 4-build-meta-index.py --lang en
python 5-varstats-db.py --lang en
python 6-fetch-csv.py --lang en
python 7-data-compactor.py --lang en
```

### Processing scripts (8–14)

These import from `duckdb_config.py`, which reads the `TEMPO_LANG` environment variable (default `ro`). Set it before running:

```bash
# Romanian (default)
python 9-csv-to-parquet.py
python 10-import-metadata.py

# English
TEMPO_LANG=en python 9-csv-to-parquet.py
TEMPO_LANG=en python 10-import-metadata.py
TEMPO_LANG=en python utils/14-parquet-to-ids.py
```

Scripts that inherit from `duckdb_config` automatically use the correct paths:

| Script | Input | Output |
|---|---|---|
| `9-csv-to-parquet.py` | `data/4-datasets/{lang}/` | `data/parquet/{lang}/` |
| `10-import-metadata.py` | `data/2-metas/{lang}/`, `data/1-indexes/{lang}/` | DuckDB `lang` rows |
| `utils/14-parquet-to-ids.py` | `data/parquet/{lang}/` | `data/parquet-v2/{lang}/` |

### Running both languages end-to-end

```bash
# Fetch
python 1-fetch-context.py --lang ro && python 1-fetch-context.py --lang en
python 2-fetch-matrices.py --lang ro && python 2-fetch-matrices.py --lang en
python 3-fetch-metas.py --lang ro && python 3-fetch-metas.py --lang en
python 6-fetch-csv.py --lang ro && python 6-fetch-csv.py --lang en
python 7-data-compactor.py --lang ro && python 7-data-compactor.py --lang en

# Process (run schema setup once)
python 8-setup-duckdb-schema.py --force

# Import both languages into DuckDB
python 10-import-metadata.py
TEMPO_LANG=en python 10-import-metadata.py

# Convert to Parquet v2 for both
python utils/14-parquet-to-ids.py
TEMPO_LANG=en python utils/14-parquet-to-ids.py
```

---

## DuckDB Schema

The four core metadata tables all have a `lang` column:

```sql
-- Composite primary keys include lang
contexts        PRIMARY KEY (context_code, lang)
matrices        PRIMARY KEY (matrix_code, lang)
dimensions      UNIQUE (matrix_code, lang, dim_code)
dimension_options  -- no lang column; keyed by dimension_id which is lang-specific
```

Importing is idempotent — re-running `10-import-metadata.py` for the same lang uses `ON CONFLICT DO UPDATE`.

---

## FastAPI App

All API endpoints accept an optional `?lang=ro` query parameter (default `ro`):

```
GET /api/categories?lang=en
GET /api/datasets?lang=en&q=populatie
GET /api/datasets/{matrix_code}?lang=en
GET /api/datasets/{matrix_code}/data?lang=en
```

The app:
- Filters all DuckDB queries by `lang`
- Resolves parquet files from `data/parquet-v2/{lang}/`
- Returns dimension labels in the requested language

Key files:
- `app/config.py` — `get_parquet_dir(lang)`, `SUPPORTED_LANGS`, `DEFAULT_LANG`
- `app/routers/categories.py`, `datasets.py`, `dataset_data.py` — all accept `lang` param
- `app/services/query_builder.py` — passes `lang` to `_resolve_parquet_path`

---

## Adding a New Language

1. Run fetching scripts with `--lang <new>`
2. Run processing scripts with `TEMPO_LANG=<new>`
3. Add `<new>` to `SUPPORTED_LANGS` in `app/config.py` and `duckdb_config.py`

---

## What's Language-Agnostic

These are computed from numeric data and apply across languages — no lang column, no re-run needed:

- `dataset_value_profiles` — min/max/mean/percentiles
- `dataset_coverage` — time/geo coverage, fill rate
- `dataset_trends` — trend direction, YoY growth, seasonality
- `dataset_tags` — bilingual semantic tags (contain both langs by design)
- `dataset_relationships` — similarity scores between datasets
- `dataset_chart_recs` — chart type recommendations
- `10-classify-dimensions.py` — archetypes based on `nom_item_id`, not labels

---

## Future: More Languages

The current design supports N languages with no structural changes — just add to `SUPPORTED_LANGS` and run the pipeline. A future phase may add a frontend language switcher that propagates `?lang=` to all API calls.

Dimension label translation (e.g. storing Romanian labels alongside English) could be added as a `dimension_translations` table keyed on `nom_item_id`.
