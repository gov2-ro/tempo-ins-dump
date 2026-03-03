# Agent 1B: Coverage & Sparsity Profiler

**Type:** `Bash`
**Phase:** 1 (independent — no dependencies)
**Output table:** `dataset_coverage`
**Runtime:** ~7 seconds for 1,886 datasets

## What it does

For each dataset, measures how much of the *theoretical* data space is actually populated, and characterises the time and geographic coverage. This enables:
- "Coverage completeness" quality badges (fill_rate)
- Filters like "show only datasets covering 2020 onwards" or "show full county coverage"
- Detecting datasets where filtering is essential (sparse data → must pre-filter)
- Freshness indicators ("data last updated 3 years ago")

## Output Schema

```sql
CREATE TABLE dataset_coverage (
    matrix_code      VARCHAR PRIMARY KEY,
    -- Time dimension
    time_dim_column  VARCHAR,        -- column name of the time dim in parquet
    time_min_year    INTEGER,
    time_max_year    INTEGER,
    time_year_count  INTEGER,        -- distinct years (not max-min, actual count)
    time_gap_years   VARCHAR,        -- JSON: [2005, 2006] — missing years in range
    time_granularity VARCHAR,        -- 'annual' | 'quarterly' | 'monthly' | 'other'
    -- Geographic dimension
    geo_dim_column   VARCHAR,        -- column name of the geo dim in parquet
    geo_county_count INTEGER,        -- number of distinct sub-national units present
    geo_has_national BOOLEAN,        -- true if national-level aggregate present
    geo_has_locality BOOLEAN,        -- true if locality-level data present
    geo_level_counts VARCHAR,        -- JSON: {"county": 41, "national": 1}
    -- Sparsity
    theoretical_max  BIGINT,         -- product of all dimension option_counts
    actual_rows      BIGINT,         -- actual row count from parquet
    fill_rate        DOUBLE,         -- actual_rows / theoretical_max (0-1+)
    freshness_years  INTEGER,        -- CURRENT_YEAR - time_max_year
    sparse_dims      VARCHAR,        -- JSON: [{dim, actual, expected, ratio}] for dims with ratio < 0.5
    dim_count        INTEGER
)
```

**Fill rate interpretation:**
- `>= 1.0` — fully dense (every combination present, possibly with aggregates)
- `0.75-1.0` — mostly complete
- `0.5-0.75` — moderate sparsity
- `0.25-0.5` — significant sparsity (multiple filter presets needed)
- `< 0.25` — highly sparse (warn user, always show filters)

## Key Schema Dependency

This agent must navigate the chain:

```
dimensions (matrix_code → dimension_id, dim_column_name)
  → dimension_options (dimension_id → nom_item_id)
    → dimension_options_parsed (nom_item_id → dim_type, year, geo_level, …)
```

The `dim_type` for a dimension is determined by majority vote of its options' types in `dimension_options_parsed`.

## Prompt Template

```
You are Agent 1B: Coverage & Sparsity Profiler.

**Environment:**
- Activate: `source {{VENV_PATH}}/bin/activate`
- Working dir: `{{PROJECT_DIR}}`
- DuckDB: `{{DB_PATH}}`
- Parquet dir: `{{PARQUET_DIR}}`
- Current year: {{CURRENT_YEAR}}
- Number of geo sub-units in this country: {{GEO_UNIT_COUNT}} (e.g., 42 for Romania)

**DB Schema:**
- `matrices` — matrix_code, row_count, parquet_path
- `dimensions` — matrix_code, dimension_id, dim_column_name, option_count
- `dimension_options` — dimension_id, nom_item_id, option_label
- `dimension_options_parsed` — nom_item_id, dim_type, year, time_granularity, geo_level, geo_name_clean

**Task:**
Write a Python script (heredoc) and run it. Steps:

1. Open a read-only connection to {{DB_PATH}} for metadata queries.
   Open a write connection (try {{DB_PATH}}, fallback to `data/dataset_coverage.duckdb` if locked).
   Open a separate in-memory DuckDB connection for parquet queries (avoids lock conflicts).

2. Pre-load into Python dicts (fast lookup during the loop):
   a. dim_type_map: {dimension_id → dim_type} — majority vote from:
      SELECT dopt.dimension_id, dop.dim_type, COUNT(*) as cnt
      FROM dimension_options dopt
      JOIN dimension_options_parsed dop ON dopt.nom_item_id = dop.nom_item_id
      GROUP BY dopt.dimension_id, dop.dim_type
      ORDER BY dopt.dimension_id, cnt DESC
      (take first dim_type per dimension_id — highest count wins)
      NOTE: never alias dimension_options as "do" — it's a reserved SQL word.

   b. dims_by_matrix: {matrix_code → [{dimension_id, column, option_count, dim_type}]}

   c. time_years: {nom_item_id → (year, time_granularity)} — from dimension_options_parsed where dim_type='time'

   d. geo_levels: {nom_item_id → geo_level} — from dimension_options_parsed where dim_type='geo'

   e. matrices: [(matrix_code, row_count, parquet_path)] — all datasets

3. DROP TABLE IF EXISTS dataset_coverage; CREATE TABLE with the schema above.

4. For each dataset:

   a. Find time dimension: first dim in dims_by_matrix[mc] where dim_type == 'time'.
      If found and parquet exists: query DISTINCT {time_col} from parquet, resolve to years via time_years dict.
      Compute: time_min_year, time_max_year, time_year_count.
      time_gap_years = sorted(set(range(min,max+1)) - set of present years) as JSON.
      time_granularity = majority vote from time_granularity field of resolved options.
      freshness_years = {{CURRENT_YEAR}} - time_max_year.

   b. Find geo dimension: first dim where dim_type == 'geo'.
      If found and parquet exists: query DISTINCT {geo_col} from parquet, resolve geo_level via geo_levels dict.
      Compute: geo_county_count (options where geo_level == '{{GEO_SUB_LEVEL}}' e.g. 'county').
      geo_has_national, geo_has_locality from respective geo_level keys.
      geo_level_counts = Counter as JSON.

   c. Fill rate: theoretical_max = product of all option_counts.
      fill_rate = row_count / theoretical_max.

   d. Sparse dims: for each non-unit dim, query COUNT(DISTINCT {col}) from parquet.
      If actual / option_count < 0.5, add to sparse list.

5. Insert all records. Handle errors gracefully (store NULLs, log first 5 errors).

6. Print summary: dataset count, avg fill rate, freshness distribution, top 5 sparse datasets.

Print progress every 200 datasets.
```

## Adaptation Notes

- `{{GEO_SUB_LEVEL}}` is the `geo_level` value that corresponds to your target administrative unit (e.g., `'county'` for Romania, `'nuts2'` for Eurostat, `'state'` for US Census)
- `{{GEO_UNIT_COUNT}}` is used only for display/validation — e.g., "41 out of 42 counties"
- If your parsed options don't have a `time_granularity` field, infer it from the label format: labels like "2020Q1" → quarterly, "2020-01" → monthly, "2020" → annual
- The fill_rate can exceed 1.0 if the dataset contains aggregate rows (e.g., "Total" across all values of a dimension). This is fine — it just means the data is denser than the pure cross-product.
