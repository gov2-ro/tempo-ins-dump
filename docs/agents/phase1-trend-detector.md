# Agent 1C: Trend & Pattern Detector

**Type:** `Bash`
**Phase:** 1 (independent — no dependencies)
**Output table:** `dataset_trends`
**Runtime:** ~5 seconds for 1,886 datasets

## What it does

Detects temporal patterns by aggregating `value` across all non-time dimensions per year, then applying linear regression and YoY delta analysis. Also detects geo outlier counties for geo-enabled datasets. This enables:
- "Trending up/down" badges and filters
- Growth rate sorting ("show fastest-growing datasets")
- Auto chart annotations ("breakpoint: 2020")
- Related dataset discovery by similar trend pattern

## Output Schema

```sql
CREATE TABLE dataset_trends (
    matrix_code          VARCHAR PRIMARY KEY,
    trend_direction      VARCHAR,  -- 'increasing' | 'decreasing' | 'flat' | 'volatile' | 'no_time'
    trend_slope          DOUBLE,   -- normalized slope (slope / |mean_value|)
    yoy_growth_latest    DOUBLE,   -- % YoY change for the most recent year pair
    max_value_year       INTEGER,  -- year with highest summed value
    min_value_year       INTEGER,  -- year with lowest summed value
    has_seasonality      BOOLEAN,  -- detected from quarterly/monthly granularity
    breakpoint_years     VARCHAR,  -- JSON: years where YoY delta > 2σ
    geo_variance         DOUBLE,   -- cross-county variance (latest year, geo datasets)
    geo_outlier_counties VARCHAR   -- JSON: county names with value > mean + 2σ
)
```

**Trend direction rules:**
- Compute YoY % changes. Normalize slope = raw_slope / |mean_value|.
- `volatile` if CV of YoY changes > 0.5 AND |slope_norm| < 0.05
- `increasing` if slope_norm > 0.02
- `decreasing` if slope_norm < -0.02
- `volatile` if CV of YoY changes > 0.5
- else `flat`
- `no_time` if dataset has no time dimension or fewer than 2 data years

**Seasonality detection:** Only for quarterly/monthly granularity. Aggregate by period (quarter 1-4 or month 1-12) across all years. If CV of period totals > 0.3, mark as seasonal.

**Breakpoints:** YoY deltas that are > 2σ from the mean delta. Common causes: policy changes, data revisions, COVID-19 (2020).

## Key Query Pattern

The core query joins parquet data directly with `dimension_options_parsed` using DuckDB's ability to read parquet from within a query context that also has access to the DuckDB database tables:

```sql
SELECT dop.year, SUM(p.value) as total
FROM read_parquet(?) p
JOIN dimension_options_parsed dop
  ON p.{time_col} = dop.nom_item_id AND dop.dim_type = 'time'
WHERE dop.year IS NOT NULL AND p.value IS NOT NULL
GROUP BY dop.year
ORDER BY dop.year
```

This works because both the parquet file and the DuckDB tables are accessed through the **same DuckDB connection** — not the in-memory parquet connection pattern used in Agent 1B.

## Prompt Template

```
You are Agent 1C: Trend & Pattern Detector.

**Environment:**
- Activate: `source {{VENV_PATH}}/bin/activate`
- Working dir: `{{PROJECT_DIR}}`
- DuckDB: `{{DB_PATH}}`
- Parquet dir: `{{PARQUET_DIR}}`

**DB Schema:**
- `matrices` — matrix_code, parquet_path
- `dimensions` — matrix_code, dim_column_name, dimension_id
- `dimension_options` — dimension_id, nom_item_id
- `dimension_options_parsed` — nom_item_id, dim_type, year, time_granularity, geo_level, geo_name_clean
- `matrix_profiles` — matrix_code, time_granularity (may be NULL)

**Task:**
Write a Python script (heredoc) and run it. Steps:

1. Connect to {{DB_PATH}} read-write.

2. DROP TABLE IF EXISTS dataset_trends; CREATE with schema:
   matrix_code VARCHAR PRIMARY KEY, trend_direction VARCHAR, trend_slope DOUBLE,
   yoy_growth_latest DOUBLE, max_value_year INTEGER, min_value_year INTEGER,
   has_seasonality BOOLEAN, breakpoint_years VARCHAR, geo_variance DOUBLE,
   geo_outlier_counties VARCHAR

3. Pre-load into dicts:
   a. dim_map: {matrix_code → {dim_type → dim_column_name}}
      Get first (majority) dim_type per (matrix_code, column) from:
        SELECT d.matrix_code, d.dim_column_name, dop.dim_type
        FROM dimensions d
        JOIN dimension_options dopt ON dopt.dimension_id = d.dimension_id
        JOIN dimension_options_parsed dop ON dop.nom_item_id = dopt.nom_item_id
        GROUP BY d.matrix_code, d.dim_column_name, dop.dim_type
      (Never alias dimension_options as "do" — reserved SQL word. Use "dopt".)

   b. gran_map: {matrix_code → time_granularity} from matrix_profiles (nullable)

   c. matrices: [(matrix_code, parquet_path)] from matrices where parquet_path IS NOT NULL

4. For each dataset, using the SAME connection (not in-memory):
   a. Look up time_col = dim_map[mc].get('time'), geo_col = dim_map[mc].get('geo')
   b. If no time_col: set trend_direction = 'no_time', insert, continue

   c. Run aggregate query over parquet + dimension_options_parsed JOIN:
      SELECT dop.year, SUM(p.value) as total
      FROM read_parquet('{parquet_path}') p
      JOIN dimension_options_parsed dop
        ON p.{time_col} = dop.nom_item_id AND dop.dim_type = 'time'
      WHERE dop.year IS NOT NULL AND p.value IS NOT NULL
      GROUP BY dop.year ORDER BY dop.year

   d. If < 2 time points: trend_direction = 'flat' or 'no_time'; continue

   e. Compute:
      - Linear regression slope: slope = Σ((x-x̄)(y-ȳ)) / Σ((x-x̄)²)
      - slope_norm = slope / |mean_value|
      - YoY % changes: (total[i] - total[i-1]) / |total[i-1]| * 100
      - trend_direction: volatile if CV(yoy) > 0.5 AND |slope_norm| < 0.05;
        increasing if slope_norm > 0.02; decreasing if slope_norm < -0.02;
        volatile if CV(yoy) > 0.5; else flat
      - yoy_growth_latest = last yoy change
      - max_value_year, min_value_year
      - breakpoint_years: years where |z-score of yoy| > 2 (JSON list)

   f. Seasonality (only if time_granularity in ('quarterly', 'monthly')):
      SELECT dop.quarter/month, SUM(p.value)
      FROM read_parquet('{parquet_path}') p
      JOIN dimension_options_parsed dop
        ON p.{time_col} = dop.nom_item_id AND dop.dim_type = 'time'
      WHERE dop.quarter/month IS NOT NULL GROUP BY 1
      has_seasonality = True if CV of period totals > 0.3

   g. Geo outliers (only if geo_col and latest_year known):
      SELECT dop_g.geo_name_clean, SUM(p.value)
      FROM read_parquet('{parquet_path}') p
      JOIN dimension_options_parsed dop_t ON p.{time_col} = dop_t.nom_item_id AND dop_t.dim_type = 'time'
      JOIN dimension_options_parsed dop_g ON p.{geo_col} = dop_g.nom_item_id AND dop_g.dim_type = 'geo'
      WHERE dop_t.year = {latest_year} AND dop_g.geo_level = '{{GEO_SUB_LEVEL}}' GROUP BY 1
      geo_variance = variance of county values
      geo_outlier_counties = county names with value > mean + 2σ (JSON list)

5. Batch insert every 100 records. Handle errors gracefully (insert trend_direction='no_time', log first 5).

6. Print summary: trend direction distribution, seasonality count, geo outlier count, sample rows for known datasets.

Print progress every 200 datasets.
```

## Adaptation Notes

- `{{GEO_SUB_LEVEL}}` matches the `geo_level` value for your target admin unit (e.g., `'county'` for Romania, `'nuts2'` for Eurostat)
- If `matrix_profiles` doesn't have a `time_granularity` column, infer it from `dimension_options_parsed.time_granularity` via the majority vote pattern used in Agent 1B
- The DuckDB JOIN between parquet data and DB tables works because both are accessed through the same connection — don't open a separate in-memory connection for parquet queries in this agent
- If `dimension_options_parsed` doesn't have `quarter`/`month` columns, skip seasonality detection entirely (set `has_seasonality = NULL`)
