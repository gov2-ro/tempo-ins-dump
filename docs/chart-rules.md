# Chart Selection Rules

Rules used by `generate_view_profiles.py` to decide which charts each dataset gets. Each dataset gets a **Timeline** view, a **Snapshot** view, and a **Table** view.

## Dimension Classification

Every dimension is classified before chart selection:

| Property | How it's determined |
|---|---|
| **dim_type** | Majority type from parsed options: `time`, `geo`, `gender`, `age`, `residence`, `unit`, or `indicator` (default) |
| **cardinality** | low (2-5), medium (6-25), high (26-100), very_high (>100) |
| **is_singleton** | 1 option, or 2 options where one is "Total" — effectively a single value, excluded from charts |
| **has_total** | Has a "Total"/"Ambele sexe" option |
| **is_caen** | Label matches CAEN economic activity patterns |
| **has_hierarchy** | >50% of options have a parent_id |

**Special dimensions** (handled separately from analysis dims):
- **time** → drives Timeline x-axis and Snapshot period browser
- **geo** → drives choropleth maps and bar rankings
- **unit** → drives unit selector when multi-unit

**Analysis dims** = everything that isn't time/geo/unit. These become series, filters, or chart axes.

## Series Dimension Selection

When a chart needs a "series" dimension (colored lines/bars), priority order:

1. **gender** (always good — low cardinality, universal)
2. **residence** (urban/rural — 2-3 values)
3. **smallest indicator ≤ 8 options**
4. **age ≤ 8 options**
5. **any dim ≤ 15 options**
6. **fallback**: smallest available dim (may need typeahead)

## Timeline View

**Required:** has_time = true AND ≥ 3 time points. Otherwise skipped.

### Charts

| # | Chart | Condition | Notes |
|---|---|---|---|
| 1 | **Line** (primary) | Always | x = time, series = best series dim, filters = remaining dims. Toggle → bar_vertical if <5 time points; toggle → area_stacked if series has 2-6 options and no negative values |
| 2 | **Variant lines** | ≥ 2 non-singleton dims | One line chart per alternative series dim. Each swaps the series role to a different dimension |

### Controls

- Geo → filter (if present)
- Remaining analysis dims → filters (max_selected=8 if >25 options)

## Snapshot View

Single time period view. Gets a period browser if ≥ 2 time points.

### Charts (generated in order)

| # | Chart | Condition | Roles |
|---|---|---|---|
| 1 | **Choropleth** | has_geo AND ≥ 5 counties AND no localities | x_axis = geo. Always primary when present |
| 2 | **Horizontal bar** | has_geo AND ≥ 5 geo values | x_axis = geo, series = first dim ≤ 6 options. Toggle → stacked_bar, line |
| 2alt | **Bar** (no geo) | non-singleton dims exist | x_axis = highest-cardinality dim. If >20 options → horizontal_bar; if has series → grouped_bar; else → bar_vertical |
| 3 | **Population pyramid** | has_age AND has_gender AND gender has 2-3 options | x_axis = age, series = gender. Becomes primary (demotes bars) |
| 3b | **Variant bars** | ≥ 2 non-singleton dims | All dim pairs (x × series) where series ≤ 8 options. horizontal_bar if x > 20, else grouped_bar. Toggle → stacked_bar if series 2-4 |
| 4 | **Bubble matrix** | ≥ 2 dims with ≥ 3 options each | x_axis = smallest dim, series = 2nd smallest. If 3+ qualifying → dimension_pair_toggle = true |
| 4b | **Scatter** | pivot dim 2-20 options AND entity dim ≥ 4 options | pivot = smallest qualifying, entity = largest other. Numeric axes, bubbles = entities |
| 5 | **Heatmap** | ≥ 2 dims with ≥ 5 options AND at least one ≥ 10 AND fill_rate > 30% | x_axis = largest dim, series = 2nd largest |

### Controls

- **Period browser**: always if ≥ 2 time points (default: latest)
- **Choropleth filters**: each analysis dim gets its own filter scoped to choropleth
- **Remaining dims**: filters for dims not assigned to primary chart axes

## Control Type Selection

| Condition | Control |
|---|---|
| CAEN or very_high cardinality | typeahead_select (search box) |
| Has hierarchy | tree_select |
| Series role + high/very_high | typeahead_select |
| Series role + medium | multi_select |
| Series role + low | pill_group |
| Geo | multi_select |
| Filter + low (2-5) | pill_group |
| Filter + medium (6-25) | multi_select |
| Filter + high (26-100) | single_select |
| Filter + very_high (>100) | typeahead_select |

## Default Values

| Condition | Default |
|---|---|
| Geo dimension | all |
| Has "Total" option | total |
| Otherwise | first option |

## Warnings

| Warning | Condition |
|---|---|
| very_sparse | fill_rate < 10% |
| sparse_data | fill_rate 10-25% |
| short_series | 1-2 time periods |
| high_cardinality | non-geo/time/unit dim with >100 options |
| multi_unit | >1 measurement unit type |

## Archetypes

Detected by `10-classify-dimensions.py`, stored in `matrix_profiles.archetype`:

| Archetype | Detection |
|---|---|
| geo_time | has_geo + has_time |
| demographic | has_age + has_gender + has_time |
| time_residence | has_residence + has_time |
| time_series | has_time (default) |

The archetype influences the primary chart choice (geo_time → choropleth, demographic → pyramid) but the view profile rules above take precedence.
