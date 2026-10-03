# Bilingual support (ro / en)

Reviewed 2026-10-03. This replaces the old per-language parquet/lang-key schema
instructions, which no longer describe the app. See [CURRENT_STATE.md](CURRENT_STATE.md)
and [FIX-03](fixes/03-pipeline-and-corpus.md) before running ingestion writers.

## Current serving model

The app serves one canonical corpus at `data/corpus/`: metadata.duckdb, parquet/,
view-profiles/ and search.duckdb. Numerical observations are shared; requesting
English does not select a second parquet directory. Core metadata tables are not
keyed by `(matrix_code, lang)`.

Dataset names/definitions use bilingual metadata fields with Romanian fallback.
Dimension values use `sdmx_codes.display_label_en` where available. Detail-service
dimension labels can use source EN metadata JSON at `data/2-metas/en/`; that lookup
is currently repository-relative and not automatically redirected by TEMPO_DATA_DIR.
The deployed Docker snapshot does not include those raw EN JSON files by default.
Do not promise fully translated dimension labels in a standalone runtime image.

The FTS sidecar indexes bilingual text; production staging currently omits it
(FIX-05). The dimension-browser query uses Romanian dimension labels because the
actual dimensions table has no language column. Translation is incomplete.

## API and frontend

Catalog/detail/summary endpoints use `?lang=en` for display metadata. `/data` returns
canonical values, and has no general language-selection contract. `/download`
accepts lang for available label translations but currently silently caps rows;
see FIX-04. Examples:

```text
/api/categories?lang=en
/api/datasets?lang=en&q=unemployment
/api/datasets/AMG157G?lang=en
/api/datasets/AMG157G/download?format=csv&lang=en
```

v1/v2 include language switching and URL/localStorage language state. Some UI
labels and place indicator names still need consistency checks; FIX-06/FIX-07
cover their relevant acceptance tests. Do not treat a language toggle as proof
that every source label has an English translation.

## Fetching language sources

Fetchers accept ro/en and store separate original sources:

```bash
python 1-fetch-context.py --lang en
python 2-fetch-matrices.py --lang en
python 3-fetch-metas.py --lang en
python 6-fetch-csv.py --lang en
```

These commands fetch data; they are not a complete safe bilingual publication
recipe. Confirm target paths and source API behavior before running a full fetch.
The current canonical pipeline consumes original CSV labels; the compactor and
deprecated stage-12 converter are not required for English display support.

## Processing limitations

`duckdb_config.py` reads TEMPO_LANG for source paths but uses the same canonical
output directory for both languages. Stage 9 does not accept --lang; its inputs
depend on the process environment. `update-pipeline.py --lang en` passes language
to fetchers but not uniformly to processing subprocesses. English metadata imports
and dimension updates also require deliberate enrichment rather than overwriting
the canonical schema.

Do not run `TEMPO_LANG=en python 9-csv-to-parquet.py` against the production corpus
as a translation operation. Use a copied checkout/corpus or explicit --out-dir
where supported. FIX-03 must define and test safe enrichment-only English ingestion
or reject unsafe modes until supported. TEMPO_DATA_DIR only redirects app readers,
not all pipeline writers.

## Adding translations

Update explicit bilingual fields/code labels, test fallback and key identity,
package required translation sources for the runtime, and rebuild FTS against the
same generation. Numerical keys/grain/units must remain stable across languages.
The current code only validates ro/en in relevant configuration; arbitrary new
languages are future work, not a one-line SUPPORTED_LANGS change.
