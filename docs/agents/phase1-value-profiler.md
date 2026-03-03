# Agent 1A: Value Profiler

**Type:** `Bash`
**Phase:** 1 (independent — no dependencies)
**Output table:** `dataset_value_profiles`
**Runtime:** ~7 seconds for 1,886 datasets

## What it does

Runs a single aggregate DuckDB query per parquet file to compute statistical properties of the `value` column. This enables:
- Smart axis scaling in charts
- Number formatting (1,234 vs 1.2M vs 1.2B)
- "Interesting dataset" ranking by variance
- Outlier detection
- Distribution hints for chart type selection

## Output Schema

```sql
CREATE TABLE dataset_value_profiles (
    matrix_code      VARCHAR PRIMARY KEY,
    row_count        BIGINT,
    val_min          DOUBLE,
    val_max          DOUBLE,
    val_mean         DOUBLE,
    val_median       DOUBLE,   -- approx_quantile(0.5)
    val_stddev       DOUBLE,
    val_p25          DOUBLE,   -- approx_quantile(0.25)
    val_p75          DOUBLE,   -- approx_quantile(0.75)
    null_pct         DOUBLE,   -- % null values
    zero_pct         DOUBLE,   -- % zero values
    negative_pct     DOUBLE,   -- % negative values
    coeff_variation  DOUBLE,   -- stddev / mean
    magnitude        VARCHAR,  -- 'units' | 'thousands' | 'millions' | 'billions'
    distribution_shape VARCHAR  -- 'normal' | 'right_skewed' | 'left_skewed' | 'uniform' | 'sparse'
)
```

**Magnitude rules:** based on `max(abs(value))`:
- `< 1,000` → units
- `< 1,000,000` → thousands
- `< 1,000,000,000` → millions
- else → billions

**Distribution shape rules** (heuristic):
- `null_pct > 50` → sparse
- `abs((mean - median) / stddev) < 0.5` → normal
- `(mean - median) / stddev > 0.5` → right_skewed
- `(mean - median) / stddev < -0.5` → left_skewed
- `coeff_variation < 0.1` → uniform

## Prompt Template

```
You are Agent 1A: Value Profiler.

**Environment:**
- Activate: `source {{VENV_PATH}}/bin/activate`
- Working dir: `{{PROJECT_DIR}}`
- DuckDB: `{{DB_PATH}}`
- Parquet dir: `{{PARQUET_DIR}}`

**Task:**
Write and run a Python script (use heredoc). The script should:

1. Connect to DuckDB. Try writing to {{DB_PATH}}; if locked (duckdb.IOException),
   write to fallback `{{PROJECT_DIR}}/data/value_profiles.duckdb` instead.

2. Create table `dataset_value_profiles` (DROP IF EXISTS first) with schema:
   matrix_code VARCHAR PRIMARY KEY, row_count BIGINT,
   val_min DOUBLE, val_max DOUBLE, val_mean DOUBLE, val_median DOUBLE,
   val_stddev DOUBLE, val_p25 DOUBLE, val_p75 DOUBLE,
   null_pct DOUBLE, zero_pct DOUBLE, negative_pct DOUBLE,
   coeff_variation DOUBLE, magnitude VARCHAR, distribution_shape VARCHAR

3. Get all datasets from `matrices` table where parquet_path IS NOT NULL.

4. For each dataset, run ONE aggregate DuckDB query:
   ```sql
   SELECT
     COUNT(*) as row_count,
     MIN(value) as val_min, MAX(value) as val_max,
     AVG(value) as val_mean,
     APPROX_QUANTILE(value, 0.5) as val_median,
     STDDEV(value) as val_stddev,
     APPROX_QUANTILE(value, 0.25) as val_p25,
     APPROX_QUANTILE(value, 0.75) as val_p75,
     COUNT(*) FILTER (WHERE value IS NULL) * 100.0 / COUNT(*) as null_pct,
     COUNT(*) FILTER (WHERE value = 0) * 100.0 / COUNT(*) as zero_pct,
     COUNT(*) FILTER (WHERE value < 0) * 100.0 / COUNT(*) as negative_pct
   FROM read_parquet('{path}')
   ```

   Then compute in Python:
   - coeff_variation = stddev / mean (handle div-by-zero → NULL)
   - magnitude: based on max(abs(val_min), abs(val_max))
   - distribution_shape: sparse if null_pct > 50; else use (mean - median) / stddev heuristic

5. Insert all results.

6. Print summary: total datasets, distribution of shapes and magnitudes.
   Print sample row for matrix_code='{{SAMPLE_MATRIX_CODE}}'.

Print progress every 200 datasets.
```

## Adaptation Notes

- Replace `{{SAMPLE_MATRIX_CODE}}` with any known matrix code in your dataset (e.g., the first alphabetically)
- If your parquet files don't have a column named exactly `value`, update the SQL query column name
- The `approx_quantile` function is DuckDB-specific — works on any DuckDB version ≥ 0.7
