# Agent 2C: Chart Recommender

**Type:** `Bash`
**Phase:** 2 (needs Phase 1: `dataset_value_profiles`, `dataset_coverage`, `dataset_trends`)
**Output table:** `dataset_chart_recs`
**Runtime:** ~2 minutes for 1,886 datasets (5,365 recommendations)

## What it does

Applies a rules engine over Phase 1 profiling data to generate dataset-specific chart recommendations. Goes beyond the 4-archetype default chart selection to suggest the best 2-5 chart types per dataset with relevance scores and config hints. Enables:
- "Chart carousel" on dataset detail page — user can switch between recommended views
- Smarter defaults (e.g., population pyramid instead of grouped bar for age × gender data)
- Config hints that reduce chart setup work (which column is time, which is geo, etc.)

## Output Schema

```sql
CREATE TABLE dataset_chart_recs (
    matrix_code  VARCHAR,   -- composite PK
    chart_type   VARCHAR,   -- composite PK
    relevance    DOUBLE,    -- 0-1 fit score (1.0 = primary recommendation)
    reason       VARCHAR,   -- human-readable explanation
    config_json  VARCHAR    -- JSON: {time_dim, geo_dim, animate, ...}
)
```

**Chart types produced (INS TEMPO distribution):**

| Chart type | Count | When recommended |
|---|---|---|
| `line` | 1,061 | All time-series datasets |
| `range_chart` | 911 | Volatile trend |
| `bar` | 738 | Short time range (< 5 years) or categorical |
| `heatmap` | 619 | High sparsity across 2 dims |
| `choropleth` | 566 | geo_time archetype (≥30 counties + time) |
| `area_with_trend` | 430 | Single time series + long time range |
| `sparkline_grid` | 414 | Multiple geo units over time |
| `small_multiples_line` | 283 | 2-3 series + long time |
| `grouped_bar` | 262 | age × gender (demographic) |
| `population_pyramid` | 67 | age + gender dims present |
| `seasonal_pattern` | 8 | has_seasonality = TRUE |
| `ranked_horizontal_bar` | 6 | Few geo units, 1 time point |

## Rules Engine

Reads from three Phase 1 tables + `matrix_profiles` + `dimensions`/`dimension_options_parsed`.

```
Input per dataset:
  - archetype (from matrix_profiles)
  - has_time, has_geo, has_gender, has_age (from matrix_profiles)
  - time_col, geo_col (from dataset_coverage: time_dim_column, geo_dim_column)
  - geo_county_count (from dataset_coverage)
  - time_year_count (from dataset_coverage)
  - time_granularity (from dataset_coverage)
  - fill_rate (from dataset_coverage)
  - trend_direction (from dataset_trends)
  - has_seasonality (from dataset_trends)
  - distribution_shape (from dataset_value_profiles)
  - negative_pct (from dataset_value_profiles)

Rules (emit chart_type + relevance + reason + config_json):

1. choropleth (rel=1.0 if geo_county_count >= 30 AND has_time)
   reason: "Geographic data with time dimension"
   config: {time_dim, geo_dim, primary: true}

2. sparkline_grid (rel=0.6 if geo_county_count >= 5 AND has_time)
   reason: "Multiple geographic units over time suit sparkline grid"
   config: {time_dim, geo_dim, animate: false, compact: true}

3. population_pyramid (rel=1.0 if has_age AND has_gender)
   reason: "Age and gender dimensions indicate population pyramid"
   config: {age_dim, gender_dim}

4. grouped_bar (rel=0.85 if has_age AND has_gender, fallback if no pyramid support)
   reason: "Age × gender breakdown"

5. line (rel=0.9 if has_time AND time_year_count >= 3)
   reason: "Time series with sufficient data points"
   config: {time_dim}

6. area_with_trend (rel=0.8 if has_time AND time_year_count >= 10 AND NOT has_geo)
   reason: "Long single time series benefits from area + trend line"
   config: {time_dim, show_trend: true}

7. small_multiples_line (rel=0.75 if has_time AND 2 <= series_count <= 6)
   reason: "Multiple series over long time suit small multiples"
   config: {time_dim, facet_dim}

8. heatmap (rel=0.7 if fill_rate < 0.5 AND dim_count >= 2)
   reason: "Sparse data across multiple dimensions suits heatmap"
   config: {x_dim, y_dim}

9. range_chart (rel=0.5 if trend_direction = 'volatile')
   reason: "Volatile data benefits from range/band visualization"
   config: {time_dim, show_bands: true}

10. bar (rel=0.7 if has_time AND time_year_count < 5)
    reason: "Short time range suits bar chart"
    config: {time_dim}

11. seasonal_pattern (rel=0.9 if has_seasonality = TRUE)
    reason: "Seasonal pattern detected in quarterly/monthly data"
    config: {time_dim, period: 'quarter'/'month'}

12. ranked_horizontal_bar (rel=0.6 if has_geo AND NOT has_time)
    reason: "Geographic snapshot without time suits ranked bar"
    config: {geo_dim, sort: 'desc'}
```

## Prompt Template

```
You are Agent 2C: Chart Recommender.

**Environment:**
- Activate: `source {{VENV_PATH}}/bin/activate`
- Working dir: `{{PROJECT_DIR}}`
- DuckDB: `{{DB_PATH}}`

**Phase 1 tables available:** dataset_value_profiles, dataset_coverage, dataset_trends
**Other tables:** matrix_profiles, dimensions, dimension_options, dimension_options_parsed

**Task:**
Write a Python script (heredoc) and run it. Steps:

1. Connect to {{DB_PATH}} read-write.
   Try main DB; if locked, write to fallback `{{PROJECT_DIR}}/data/dataset_chart_recs.duckdb`.

2. DROP TABLE IF EXISTS dataset_chart_recs; CREATE:
   matrix_code VARCHAR, chart_type VARCHAR, relevance DOUBLE,
   reason VARCHAR, config_json VARCHAR
   PRIMARY KEY (matrix_code, chart_type)

3. Load a merged profile per dataset:
   SELECT
     m.matrix_code,
     mp.archetype, mp.has_time, mp.has_geo, mp.has_gender, mp.has_age,
     dc.time_dim_column, dc.geo_dim_column, dc.geo_county_count,
     dc.time_year_count, dc.time_granularity, dc.fill_rate, dc.dim_count,
     dt.trend_direction, dt.has_seasonality,
     dvp.distribution_shape, dvp.negative_pct
   FROM matrices m
   LEFT JOIN matrix_profiles mp ON mp.matrix_code = m.matrix_code
   LEFT JOIN dataset_coverage dc ON dc.matrix_code = m.matrix_code
   LEFT JOIN dataset_trends dt ON dt.matrix_code = m.matrix_code
   LEFT JOIN dataset_value_profiles dvp ON dvp.matrix_code = m.matrix_code
   WHERE m.parquet_path IS NOT NULL

4. For dimension counts, pre-load:
   SELECT matrix_code, COUNT(DISTINCT dim_column_name) as dim_count FROM dimensions GROUP BY 1
   And the names of age/gender dimension columns where dim_type in ('age', 'gender').

5. Apply the rules engine (see "Rules Engine" section of the agent spec) to generate recs.
   For each dataset, apply ALL applicable rules and collect (chart_type, relevance, reason, config_json).
   Sort by relevance DESC. Keep top {{MAX_RECS_PER_DATASET}} (default: 6).
   Mark the highest-relevance rec as primary in its config_json: {"primary": true}.

6. Insert all records.

7. Print summary:
   - Total recommendations, avg per dataset
   - Distribution by chart_type (sorted by count)
   - Datasets with highest number of recs
   - Sample: all recs for matrix_code='{{SAMPLE_MATRIX_CODE}}'

Print progress every 500 datasets.
```

## Adaptation Notes

- `{{MAX_RECS_PER_DATASET}}` — default 6. Increase if your UI shows a longer carousel; decrease if you want tighter curation.
- **Geo threshold** (`geo_county_count >= 30`): Romania has 42 counties so 30 is ~70%. Adjust to 60-70% of your total geo unit count.
- **Series count for small_multiples**: Replace with actual distinct-values count on the non-time, non-geo, non-unit dimension. Requires a parquet query — can be skipped if too slow (use dim `option_count` from `dimensions` table as a proxy).
- **Population pyramid**: Only useful if your data has both `age` and `gender` dim types. If `dimension_options_parsed` doesn't classify these, use label heuristics (columns containing "varsta"/"age"/"grupe" and "sex"/"gender"/"masculin"/"feminin").
- **Config JSON**: The `config_json` field stores chart-specific parameters. At minimum include the relevant column names so the UI doesn't need to re-derive them. The exact keys depend on your chart component API.
- **Archetype override**: The archetype from `matrix_profiles` is the baseline; this agent may recommend a different primary chart. The UI should use this agent's top recommendation, not the archetype default.
