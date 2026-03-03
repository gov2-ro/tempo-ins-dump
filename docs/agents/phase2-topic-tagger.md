# Agent 2A: Topic Tagger

**Type:** `Bash`
**Phase:** 2 (needs Phase 1 complete — but in practice only needs existing `matrices` + context/matrix EN CSVs)
**Output table:** `dataset_tags`
**Runtime:** ~2 minutes for 1,886 datasets (92,612 tags)

## What it does

Generates bilingual semantic tags for every dataset from three sources:
1. **Context hierarchy** (EN labels from CSV) — high-weight topic labels
2. **Matrix names** (EN keywords from CSV) — medium-weight descriptors
3. **Indicator dimension options** (RO labels from DuckDB) — granular sub-tags

Enables tag-based discovery, faceted search, and "Related by topic" grouping. Tags from EN sources are bilingual; indicator tags are RO-only (no EN translations available from the source NSI).

## Output Schema

```sql
CREATE TABLE dataset_tags (
    matrix_code  VARCHAR,
    tag_ro       VARCHAR,   -- Romanian tag (all sources)
    tag_en       VARCHAR,   -- English tag (context + matrix_name sources only; NULL for indicator)
    source       VARCHAR,   -- 'context' | 'matrix_name' | 'indicator'
    weight       DOUBLE     -- 1.0=high, 0.5=medium
)
```

**Tag source breakdown (INS TEMPO example):**
| Source | Rows | Weight | Notes |
|--------|------|--------|-------|
| `indicator` | 36,199 | 0.5 | RO indicator option labels per dataset |
| `matrix_name` | 34,759 | 1.0 | Keywords from EN matrix name |
| `context` | 21,654 | 1.0 | EN context path labels (deduplicated) |

## Input Files

| File | Content | Used for |
|------|---------|---------|
| `{{EN_MATRICES_CSV}}` | `matrix_code, matrix_name_en` | EN keyword extraction per dataset |
| `{{EN_CONTEXT_CSV}}` | `context_code, context_name_en, parent_code` | Context path → topic tags |
| DuckDB `matrices` | `matrix_code, matrix_name (RO), context_code` | RO name + context link |
| DuckDB `dimensions` | `matrix_code, dimension_id, dim_column_name` | Find indicator dim |
| DuckDB `dimension_options` | `dimension_id, option_label` | Indicator labels (RO) |
| DuckDB `dimension_options_parsed` | `nom_item_id, dim_type` | Filter to indicator type |

## Prompt Template

```
You are Agent 2A: Topic Tagger.

**Environment:**
- Activate: `source {{VENV_PATH}}/bin/activate`
- Working dir: `{{PROJECT_DIR}}`
- DuckDB: `{{DB_PATH}}`
- English matrices CSV: `{{EN_MATRICES_CSV}}`   (columns: matrix_code, matrix_name_en or similar)
- English context CSV: `{{EN_CONTEXT_CSV}}`     (columns: context_code, context_name_en, parent_code or similar)

**DB Schema:**
- `matrices` — matrix_code, matrix_name (RO), context_code
- `dimensions` — matrix_code, dimension_id, dim_column_name
- `dimension_options` — dimension_id, nom_item_id, option_label
- `dimension_options_parsed` — nom_item_id, dim_type

**Task:**
Write a Python script (heredoc) and run it. Steps:

1. Connect to {{DB_PATH}} read-write.
   Try main DB; if locked, write to fallback `{{PROJECT_DIR}}/data/dataset_tags.duckdb`.

2. DROP TABLE IF EXISTS dataset_tags; CREATE:
   matrix_code VARCHAR, tag_ro VARCHAR, tag_en VARCHAR, source VARCHAR, weight DOUBLE

3. Load EN translations from CSVs:
   a. Read {{EN_MATRICES_CSV}} → dict {matrix_code → name_en}
      Inspect actual column names first (use csv.DictReader + print headers).
   b. Read {{EN_CONTEXT_CSV}} → dict {context_code → name_en}
      Build full path dict: {context_code → [ancestor_names + own_name]} by traversing parent_code.

4. Load from DuckDB:
   a. matrices: [(matrix_code, matrix_name_ro, context_code)]
   b. indicator dimensions per matrix: get dimension_id for each matrix's 'indicator' dim_type
      SELECT d.matrix_code, dopt.option_label
      FROM dimensions d
      JOIN dimension_options dopt ON dopt.dimension_id = d.dimension_id
      JOIN dimension_options_parsed dop ON dop.nom_item_id = dopt.nom_item_id
      WHERE dop.dim_type = 'indicator'
      (Never alias dimension_options as "do" — reserved SQL word. Use "dopt".)
      → dict: {matrix_code → [option_label, ...]}

5. For each dataset, generate tags:

   a. Context tags (source='context', weight=1.0):
      Walk the context path from context_code up to root.
      For each context node in the path: emit one tag.
      tag_ro = RO context name (from DB), tag_en = EN context name (from CSV).
      Deduplicate by (matrix_code, tag_en or tag_ro).

   b. Matrix name tags (source='matrix_name', weight=1.0):
      EN name: split on spaces + punctuation, lowercase, remove stopwords
        (EN stopwords: the, a, an, of, in, for, by, and, or, with, to, from, on, at, per, by, total, data)
      Keep tokens of length >= 3.
      RO name: same process with RO stopwords
        (RO stopwords: si, in, pe, la, de, a, cu, din, pentru, ale, al, sau, prin, privind, dupa, total, date)
      Each kept token → one tag row. tag_ro = RO token, tag_en = EN token (or NULL if no match).
      Deduplicate within dataset.

   c. Indicator tags (source='indicator', weight=0.5):
      Take indicator option_labels for this matrix (RO only, no EN translation).
      Each label → one tag row with tag_ro=label, tag_en=NULL.
      Deduplicate within dataset.

6. Batch insert all tags. Print progress every 500 datasets.

7. Print summary:
   - Total tag rows
   - Rows per source (context / matrix_name / indicator)
   - Top 20 most common EN tags (context + matrix_name source)
   - Top 10 most common RO indicator tags
   - Sample: all tags for matrix_code='{{SAMPLE_MATRIX_CODE}}'
```

## Adaptation Notes

- **EN CSV format**: Inspect actual column names before hardcoding. The matrices CSV for INS TEMPO has columns `matrix_code` + `matrix_name_en`; context CSV has `context_code`, `context_name_en`, `parent_code`. Your NSI may use different names.
- **Stopword lists**: Extend as needed for your language. Common statistical noise words to add: "rate", "index", "total", "annual", "average", "percent", "number", "gross", "net".
- **Context depth**: Romanian INS has 3 levels (L0 → L1 → L2 → dataset). Eurostat may have 5+. Walk `parent_code` until NULL for full path.
- **Indicator vs other dim types**: INS TEMPO has an `indicator` dim type in `dimension_options_parsed`. Other NSIs may not — adapt by using the dimension with the most options, or the one that isn't time/geo/unit.
- **No EN translations for indicator labels**: This is typical for NSI data. Only tag_ro is populated for the `indicator` source. The UI should display RO tags with a fallback to romanized/original text.
- **Tag cardinality**: 92K tags for 1,886 datasets = ~49 tags/dataset avg. This is fine — the UI should paginate/collapse long tag lists.
