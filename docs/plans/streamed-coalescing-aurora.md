# Plan: Write BILINGUAL.md doc + link from readme.md

## Context
The data fetching scripts (1–7) now accept `--lang ro|en`. The rest of the pipeline — DuckDB import, Parquet conversion, classification, profiling, the FastAPI app — is hardcoded to Romanian only. The goal is to make the full pipeline and app bilingual (ro/en), while keeping the architecture simple and extensible for future languages.

The app will eventually serve both languages, and future phases may add more languages.

---

## Architecture Decision: Separate vs. Merged Language Storage

**Recommendation: Separate directories for Parquet + a `lang` column in DuckDB.**

- Parquet files stay in `data/parquet-v2/{lang}/` — simple, isolated, no schema changes to data files
- DuckDB metadata tables get a `lang` column — allows bilingual metadata lookups (names, labels, dimensions) from a single DB
- App passes `?lang=ro` (default) to filter queries

**Alternative rejected:** Merging both langs into one Parquet per dataset is complex and would break the current query layer.

---

## Changes by Component

### 1. `duckdb_config.py` — Add `--lang` / env var support
**Critical blocker.** All downstream scripts import from it.

- Add `LANG` variable: read from `TEMPO_LANG` env var, with fallback to `"ro"`
- Derive all lang-specific paths from `LANG`:
  ```python
  LANG = os.environ.get("TEMPO_LANG", "ro")
  CONTEXT_CSV = DATA_DIR / "1-indexes" / LANG / "context.csv"
  MATRICES_CSV = DATA_DIR / "1-indexes" / LANG / "matrices.csv"
  METAS_DIR = DATA_DIR / "2-metas" / LANG
  ORIGINAL_CSV_DIR = DATA_DIR / "4-datasets" / LANG
  COMPACT_CSV_DIR = DATA_DIR / "5-compact-datasets" / LANG
  PARQUET_DIR = DATA_DIR / "parquet" / LANG
  PARQUET_V2_DIR = DATA_DIR / "parquet-v2" / LANG
  ```
- Usage: `TEMPO_LANG=en python 9-csv-to-parquet.py`
- No changes needed to scripts that import from `duckdb_config` — they inherit the lang automatically

### 2. `8-setup-duckdb-schema.py` — Add `lang` column to metadata tables
Schema changes needed:
- `contexts`: add `lang TEXT NOT NULL DEFAULT 'ro'` — make `(context_code, lang)` the unique key
- `matrices`: add `lang TEXT NOT NULL DEFAULT 'ro'` — make `(matrix_code, lang)` the unique key
- `dimensions`: add `lang TEXT NOT NULL DEFAULT 'ro'`
- `dimension_options`: add `lang TEXT NOT NULL DEFAULT 'ro'`
- Enrichment tables (`dataset_value_profiles`, `dataset_coverage`, `dataset_trends`, `dataset_tags`, `dataset_relationships`, `dataset_chart_recs`): these are **language-agnostic** (numeric data, relationships) — **no lang column needed**, but note they currently only cover `ro` data

**Important:** Running this will require re-importing all metadata. The schema migration approach: drop and recreate tables (they're fully regenerated from source files anyway).

### 3. `10-import-metadata.py` — Pass `lang` when inserting rows
- Read `LANG` from `duckdb_config` (already imported)
- Add `lang` value to all INSERT statements for `contexts`, `matrices`, `dimensions`, `dimension_options`
- Add `ON CONFLICT (matrix_code, lang) DO UPDATE` or skip-if-exists logic

### 4. `9-csv-to-parquet.py` — Inherit lang from `duckdb_config`
- Already uses `duckdb_config` paths — will work automatically once `duckdb_config.py` uses `TEMPO_LANG` env var
- Minor: log which lang is being processed

### 5. `utils/14-parquet-to-ids.py` — Add `--lang` support
- Currently hardcodes `parquet/ro` and `parquet-v2/ro`
- Add `--lang` argument (default `ro`), derive paths from it

### 6. `10-sdmx-export.py` — Add `--lang` support
- Hardcodes `CONFIG` dict with ro paths
- Add `--lang` argument, derive paths dynamically

### 7. `app/config.py` — Make `PARQUET_DIR` lang-aware
- Change `PARQUET_DIR` to read from env var: `TEMPO_LANG` or a new `APP_LANG` setting
- Or: make it dynamic at request time (preferred for app serving both langs)
- **Preferred:** make `PARQUET_DIR` a function or remove it from config; resolve path per request based on `?lang=` param

### 8. FastAPI app — Add `lang` query parameter
All routes that return language-dependent data need `lang: str = "ro"`:

- **`GET /categories`** → filter `WHERE lang = ?`
- **`GET /datasets`** → filter `WHERE m.lang = ?`
- **`GET /datasets/{id}`** → filter by `lang`
- **`GET /datasets/{id}/data`** → load from `parquet-v2/{lang}/{id}.parquet`
- **`GET /datasets/{id}/chart`** → load from `parquet-v2/{lang}/{id}.parquet`

Add `choices=['ro', 'en']` validation on the lang param. Default `ro`.

### 9. `11-coverage-profiler.py` and `detect_trends.py`
- These compute numeric statistics from Parquet — language-agnostic in output
- But they read from `parquet-v2/ro/` (via `duckdb_config`)
- Will work for both langs once `duckdb_config` uses `TEMPO_LANG` env var
- No schema change needed (the stats they produce are universal)

---

## What NOT to change now
- The Parquet file format — data files stay as-is, just in `{lang}/` dirs
- `10-classify-dimensions.py` — dimension archetypes are lang-agnostic (based on nom_item_id, not labels)
- Enrichment tables (`dataset_trends`, `dataset_coverage`, etc.) — these are numeric, lang-agnostic
- Frontend templates — lang switching UI is a future phase

---

## Execution Order
1. `duckdb_config.py` — env var support (unblocks everything else)
2. `8-setup-duckdb-schema.py` — add `lang` columns, update unique constraints
3. `10-import-metadata.py` — pass `lang` in INSERTs
4. `utils/14-parquet-to-ids.py` — add `--lang`
5. `10-sdmx-export.py` — add `--lang`
6. `app/config.py` + `app/routers/*.py` — add `?lang=ro` param

---

## Verification
```bash
# 1. Test duckdb_config env var
TEMPO_LANG=en python -c "import duckdb_config; print(duckdb_config.METAS_DIR)"
# Should print: .../data/2-metas/en

# 2. Run full en pipeline
TEMPO_LANG=en python 9-csv-to-parquet.py
# Should write to data/parquet-v2/en/

# 3. Check DuckDB has lang column
python -c "
import duckdb
conn = duckdb.connect('data/tempo_metadata.duckdb')
print(conn.execute('SELECT DISTINCT lang FROM matrices').fetchall())
"
# Should return [('ro',), ('en',)]

# 4. Test app endpoint
curl "http://localhost:8080/api/datasets?lang=en" | jq '.datasets[0].name'
```

---

## Notes for Future Phases
- Adding a 3rd language would only require running the pipeline with `TEMPO_LANG=<new>` + restarting the app
- Frontend lang switcher: pass `lang` in URL or session, propagate to all API calls
- Translation of dimensions/labels: could be stored as a separate `dimension_translations` table keyed on `nom_item_id`
