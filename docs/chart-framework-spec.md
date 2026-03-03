# Generic Statistical Data Visualization Framework

## Context

The current INS TEMPO Explorer has 4 hardcoded archetypes (`time_series`, `geo_time`, `demographic`, `time_residence`) mapped to specific chart types in `app/services/chart_config.py`. This works for Romanian INS data but cannot handle Eurostat, OECD, or arbitrary SDMX-like statistical datasets without adding more archetypes — a pattern that doesn't scale.

**Goal**: Define a generic, rules-based framework that examines any statistical dataset's dimension profile and data characteristics, then produces a ranked list of applicable chart types with dimension-to-role mappings. The current 4 archetypes should emerge naturally from the rules, not be hardcoded inputs.

**Scope**: This document is a **design spec** — defining the problem, the chart catalog, the selection engine, and the role assignment system. It is source-agnostic: works for INS TEMPO, Eurostat, OECD, any SDMX-conformant data.

**Non-goals**: Data ingestion adapters, ETL pipelines, user accounts, data export. Assumes tidy/long-format data with typed dimensions is already available.

---

## 1. The Universal Statistical Data Shape

All SDMX-like statistical data shares the same shape:

```
┌─────────────────────────────────────────────────────────┐
│  1 VALUE column (numeric measure)                       │
│  1 TIME dimension (year/quarter/month) — almost always  │
│  0-1 GEO dimension (country/region/county/NUTS)         │
│  0-1 FREQUENCY dimension (annual/quarterly/monthly)     │
│  1-4 CATEGORICAL dimensions (sex, age, industry, etc.)  │
│  0-1 UNIT dimension (count, %, EUR, etc.)               │
│  Long-format / tidy data                                │
└─────────────────────────────────────────────────────────┘
```

Every dataset is a slice of a **multidimensional cube**. The framework's job is to map cube dimensions to visual encodings.

---

## 2. Dimension Classification System

### 2.1 Semantic Types

| dim_type | Detection signals | Example labels |
|----------|-------------------|---------------|
| `time` | "year","period","quarter","month"; numeric 1900-2100 | 2020, Q3 2019, 2021-M06 |
| `geo` | "region","county","country","NUTS","area"; geo codes | Bucuresti, RO321, DE |
| `gender` | "sex","gen"; exactly 2-3 options (M/F/Total) | Masculin, Feminin |
| `age` | "age","varst"; ordered numeric ranges | 0-4, 15-19, 65+ |
| `residence` | "urban","rural"; exactly 2-3 options | Urban, Rural |
| `unit` | "unit","measure","UM"; non-data-shaping | Number, %, thousands EUR |
| `frequency` | "freq"; A/Q/M | Annual, Quarterly |
| `indicator` | Default fallback — everything else | GDP, Exports, Unemployment |

### 2.2 Classifier Chain

1. Match column name against SDMX concept IDs: `TIME_PERIOD`, `REF_AREA`, `SEX`, `AGE`, `UNIT_MEASURE`, `FREQ`
2. Match option labels against regex patterns per type (multilingual)
3. Check cardinality + value patterns (all 4-digit numeric → year)
4. Fallback: `indicator`

**Key output per dimension**: `{ dim_type, option_count, has_total, has_hierarchy, is_ordered }`

Already implemented for Romanian data in `dimension_options_parsed`. For other sources, the classifier needs English/multilingual label matchers.

---

## 3. Chart Type Catalog (15 types)

| # | Chart Type | Required Dims | Cardinality Limits | Best When | Avoid When |
|---|-----------|--------------|-------------------|-----------|-----------|
| 1 | **line** | time (x) | series ≤ 15 | Trends over time | >15 series (use small_multiples) |
| 2 | **area_stacked** | time + 1 cat | series ≤ 8 | Composition over time | Negative values |
| 3 | **bar_vertical** | 1 cat or short time | x ≤ 20 | Few categories, ranking | >20 categories |
| 4 | **grouped_bar** | 2 categoricals | x ≤ 20, series ≤ 6 | Cross-tabulation (age × gender) | Either dim > 20 |
| 5 | **stacked_bar** | 2 categoricals | x ≤ 20, series ≤ 8 | Composition comparison | Negative values |
| 6 | **horizontal_bar** | 1 cat (high-card) | 5-50 categories | Rankings, long labels | Time series |
| 7 | **choropleth** | geo + value (+time) | geo ≥ 5 units | Spatial patterns | <5 geo units |
| 8 | **population_pyramid** | age + gender | age ordered, gender = 2 | Demographic structure | Missing age or gender |
| 9 | **heatmap** | 2 categoricals | 5 ≤ each ≤ 50 | Dense cross-tabulation | Very sparse data |
| 10 | **small_multiples** | any + 1 facet dim | facet 4-25 | Compare many units | <4 facet values |
| 11 | **scatter** | 2 measures or continuous dims | 10-5000 points | Correlation, outliers | Single measure (rare in SDMX) |
| 12 | **treemap** | 1+ hierarchical cat | 5-200 leaves | Part-of-whole, hierarchy | Flat structure |
| 13 | **range_chart** | time + value | time ≥ 5 | Volatile data, uncertainty | Stable trends |
| 14 | **radar** | 3+ indicators, 1-5 entities | indicators 3-12 | Multivariate comparison | Many entities |
| 15 | **table** | any | unlimited | Always available fallback | — |

**v1 scope** (core 10): line, bar_vertical, grouped_bar, stacked_bar, horizontal_bar, choropleth, heatmap, small_multiples, population_pyramid, table. Deferred: treemap, radar, scatter, range_chart, area_stacked.

---

## 4. Chart Selection Engine

### 4.1 Dataset Signature

Computed from dimension metadata + enriched profiling tables:

```python
signature = {
    # Dimension presence
    'has_time': bool, 'time_points': int,
    'has_geo': bool, 'geo_count': int, 'geo_levels': list,
    'has_gender': bool, 'gender_count': int,
    'has_age': bool, 'age_count': int,
    'has_residence': bool,
    'categorical_dims': [{'name': str, 'count': int, 'has_total': bool, 'is_ordered': bool}],
    'total_dims': int,
    # Value characteristics (from dataset_value_profiles)
    'has_negatives': bool,      # negative_pct > 0
    'is_sparse': bool,          # fill_rate < 0.3
    'distribution': str,        # normal/skewed/uniform
    'coeff_variation': float,
    # Trend characteristics (from dataset_trends)
    'trend_direction': str,     # increasing/decreasing/flat/volatile
    'has_seasonality': bool,
}
```

### 4.2 Eligibility Rules (Hard Requirements)

Each chart type defines a boolean eligibility check:

```python
ELIGIBILITY = {
    'line':              has_time AND time_points >= 3,
    'area_stacked':      has_time AND time_points >= 3 AND NOT has_negatives AND has_categoricals,
    'bar_vertical':      always eligible,
    'grouped_bar':       total_dims >= 2 AND any dim with count <= 20,
    'stacked_bar':       NOT has_negatives AND total_dims >= 2,
    'horizontal_bar':    any categorical dim with count >= 5,
    'choropleth':        has_geo AND geo_count >= 5,
    'population_pyramid': has_age AND has_gender AND gender_count == 2,
    'heatmap':           total_dims >= 2 AND NOT is_sparse,
    'small_multiples':   has_time AND any dim with 6 < count <= 25,
    'scatter':           rare — needs 2 measures (skip for most SDMX),
    'treemap':           any categorical with has_total (hierarchical),
    'range_chart':       has_time AND coeff_variation > 0.3,
    'radar':             any categorical with 3 <= count <= 12,
    'table':             always eligible,
}
```

### 4.3 Relevance Scoring (Soft Preferences)

Each eligible chart gets a score 0.0–1.0. Scoring factors per type:

| Chart | High score when | Low score when |
|-------|----------------|---------------|
| **line** | long time span (≥10), stable trend, 1-3 series | <5 time points, many series |
| **choropleth** | geo_count ≥ 20, has county level, has time (animate) | sparse geo, no time |
| **grouped_bar** | has_age + has_gender (demographic), few categories | high cardinality |
| **population_pyramid** | age is ordered, exactly M/F | includes Total gender |
| **heatmap** | 2 dims with 10-30 options each, dense fill | sparse, tiny dims |
| **small_multiples** | facet dim 6-16, line per facet | facet > 25 |
| **range_chart** | volatile trend | stable data |
| **area_stacked** | parts-of-whole, 3-6 series | >8 series |
| **horizontal_bar** | 10-50 categories, single time point | has time series |

### 4.4 Output

```python
select_charts(signature) -> [
    {'chart_type': 'choropleth', 'score': 0.95, 'roles': {...}},
    {'chart_type': 'line',       'score': 0.72, 'roles': {...}},
    {'chart_type': 'heatmap',    'score': 0.55, 'roles': {...}},
    ...
]
```

Primary chart = highest score. The `supports` list = all eligible types.

### 4.5 Backward Compatibility

Current archetypes emerge naturally:
- `geo_time` → choropleth scores highest (has_geo + has_time)
- `demographic` → grouped_bar or population_pyramid scores highest (has_age + has_gender)
- `time_residence` → line scores highest (residence as series dim)
- `time_series` → line scores highest (default)

The `archetype` field becomes informational metadata, not a control-flow input.

---

## 5. Dimension Role Assignment

### 5.1 Visual Roles

| Role | What it controls | Cardinality | Examples |
|------|-----------------|-------------|---------|
| **x_axis** | Primary position | 3-100 | Time points, age groups |
| **series** | Color/legend | 2-15 | Gender, residence, region |
| **facet** | Small multiples grid | 4-25 | Counties, industries |
| **filter** | User selection (dropdown) | unlimited | Everything not above |
| **color** | Intensity/hue (heatmap, choropleth) | continuous | Value, geo |
| **timeline** | Animation control (choropleth) | time dim | Years |

### 5.2 Default Assignment per Chart Type

| Chart Type | x_axis | series | facet | special |
|-----------|--------|--------|-------|---------|
| **line** | time | first categorical (≤15) | optional (if another dim 4-25) | — |
| **choropleth** | geo (map position) | — | — | time → timeline control |
| **grouped_bar** | age (or largest cat) | gender (or 2nd cat) | — | time → timeline |
| **population_pyramid** | age | gender | — | time → timeline |
| **heatmap** | largest cat dim | 2nd largest cat dim | — | value → color intensity |
| **small_multiples** | time | — | high-card dim (6-25) | each facet = mini chart |
| **horizontal_bar** | highest-card dim | — | — | value → bar length |

### 5.3 User Override

Frontend exposes role assignment as dropdowns. When user swaps roles:
1. Re-check which charts remain eligible
2. Re-score and re-rank
3. If current chart ineligible, switch to highest-scoring alternative

---

## 6. Filter System

### 6.1 Control Type by dim_type

| dim_type | Control | Default |
|----------|---------|---------|
| `time` | Range slider (min year ↔ max year) | Full range |
| `geo` | Hierarchical checkboxes grouped by geo_level | All at highest level |
| `gender` | Radio buttons + "All" | All |
| `residence` | Radio buttons + "All" | All |
| `age` | Ordered checkboxes or range | All |
| `unit` | Single-select dropdown | First option |
| `indicator` (≤10) | Checkboxes | First 5 |
| `indicator` (>10) | Searchable multi-select | First 5 |

### 6.2 Smart Defaults per Chart Type

- **Choropleth active**: geo filter locked to county level, all counties selected
- **Population pyramid**: gender filter hidden (both needed), all age groups shown
- **Small multiples**: facet dim shows top-N selector (grid: 4/9/16/25)

### 6.3 "Total" Row Handling

- Detect "Total" by label: "Total", "TOTAL", "Ambele sexe", etc.
- Dim in **series** role → auto-exclude "Total" (prevents double-counting)
- Dim in **filter** role with "Total" selected → returns aggregate
- Toggle: "Include totals" (default: off for series dims)

---

## 7. Data Query Strategy

| Chart Type | Row Limit | Special Handling |
|-----------|----------|-----------------|
| line/area | 5,000 | Standard filters |
| bar/grouped_bar | 5,000 | Standard filters |
| choropleth | 50,000 | Force all geo units; remove non-geo/time/unit filters |
| population_pyramid | 5,000 | Force both genders; all age groups |
| heatmap | 10,000 | Full cross-tab of 2 dims |
| small_multiples | 20,000 | All facet values |
| horizontal_bar | 2,000 | Single time point (latest) |
| table | 5,000 | Paginated |

Optional server-side aggregation endpoint:
```
GET /api/datasets/{code}/data?agg=sum&group_by=dim1,dim2&exclude={col:[ids]}
```

---

## 8. Implementation Architecture

### 8.1 File Changes

```
app/services/
  chart_config.py     → REPLACE with chart_selector.py (scoring engine)
  role_assigner.py    → NEW (dimension → role mapping)
  query_builder.py    → EXTEND (add agg/group_by/exclude params)

app/static/js/
  chart-registry.js   → NEW (chart catalog + metadata)
  chart-selector.js   → NEW (client-side re-scoring for user overrides)
  role-assigner.js    → NEW (role reassignment UI logic)
  filter-panel.js     → EXTEND (smart defaults per chart type)
  chart-factory.js    → EXTEND (registry-driven dispatch instead of switch)
  dataset-page.js     → REFACTOR (use ranked_charts, role assignment)
  chart-heatmap.js    → NEW
  chart-pyramid.js    → NEW
  chart-small-mult.js → NEW
  chart-horizontal.js → NEW
  chart-treemap.js    → NEW (deferred)
  chart-radar.js      → NEW (deferred)
```

### 8.2 API Response Shape

```json
{
  "chart_config": {
    "ranked_charts": [
      {"chart_type": "choropleth", "score": 0.95, "roles": {"x_axis": "geo_col", "timeline": "time_col"}},
      {"chart_type": "line", "score": 0.72, "roles": {"x_axis": "time_col", "series": "geo_col"}}
    ],
    "primary_chart": "choropleth",
    "supports": ["choropleth", "line", "heatmap", "bar", "table"],
    "dataset_signature": { ... }
  }
}
```

---

## 9. Migration Path

1. **Backend scoring engine** — Create `chart_selector.py`. Verify primary chart matches old archetype output for all 1,886 datasets.
2. **Frontend chart registry** — Create `chart-registry.js`. Render toolbar from `ranked_charts`. Keep existing renderers working.
3. **New chart renderers** — Implement one at a time: heatmap, pyramid, horizontal_bar, small_multiples.
4. **Role assignment UI** — Dropdown/drag to swap dimension roles. Connect to client-side re-scoring.
5. **Remove archetype dependency** — Drop `archetype` from control flow. Keep as cached label.

---

## 10. Decisions Made

1. **UX pattern**: Sidebar filters with smart defaults. No sentence builder for now.
2. **Chart scope**: Core 10 types for v1 (line, bar_vertical, grouped_bar, stacked_bar, horizontal_bar, choropleth, heatmap, small_multiples, population_pyramid, table). Treemap, radar, scatter, range_chart, area_stacked deferred.
3. **Multi-measure**: Treat as single-measure with unit selector. Dual-axis deferred.
4. **Scoring engine**: Purely algorithmic, no per-source overrides.
5. **Deliverable**: This spec as a standalone design document. Implementation in a separate session.

---

## Verification

- For all 1,886 INS TEMPO datasets, the scoring engine's primary chart should match or improve on the current archetype assignment
- Spot-check: ACC101B (geo_time), AMG101A (demographic), BUF104G (time_residence), SOM101B (time_series)
- Test with synthetic Eurostat-like dimension profiles (e.g., NUTS2 geo, quarterly time, 3 indicators)
- Verify role assignment produces sensible filter panels for each chart type
