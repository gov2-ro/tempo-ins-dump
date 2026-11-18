# AQ-08 record — chart hints and chart links

Brief: [08-chart-hints.md](08-chart-hints.md). Branch `aq-08-chart-hints`. No contract bump
(`tempo-tools/2`): `data.chart` is a new optional key in `data`, and the `data` models were already open.

## What was built

- `app/services/tools/chart.py`: builds `data.chart`. `registry.call_tool` calls `chart.apply` after the
  handler, before the vintage warning, for `query_data`, `rank_entities`, `compare_periods` and `run_recipe`,
  and only when `status` is `ok` or `partial`.
- `contract.dataset_page(..., levels=)` adds the page's `g=`. `links.recipe_page_url` is the one builder of
  the recipe page link (`get_evidence_links` uses it too).
- `ask_present.display_table` adds `table["chart"]` for rankings, change rankings and recipes (`chart_of`).
  `ask.js` `renderHintChart` draws it; `query_data` keeps the dataset chart spec (`renderChart`).
- Prose (titles, link notes) is in `tools/messages.py` (`chart.*`, RO and EN).

## Hint shape

```json
{"type": "bar", "rows": "data.rows", "row_format": "object", "x": "entity.REF_AREA_2", "y": "value",
 "series": null, "sort": "desc", "unit": "Numar persoane", "title": "...", "url": "...", "url_note": "..."}
```

- `rows` is a dotted path to the list of rows (`data.intervals[0].rows` for `compare_periods`).
- `row_format: "object"`: `x`/`y` are dotted paths inside one row (`entity.REF_AREA_2`, `value`, `percent`).
  `row_format: "array"` (`query_data`): `x`/`y`/`series` are names in `columns` (`"data.columns"`).
- `sort` is the order the rows already have, by `y`. The hint never copies a row.
- `url_note` (not `url_description`): the masking rule of the language tests treats `*_note` as prose.

## Rules chosen

- `rank_entities`: bar; `y` = `value`; `sort` = requested order. `compare_periods`: bar; `y` = the metric.
  **Several intervals: null.** Each interval ranks the entities differently, so one chart would mix rankings.
- One bar label per row: a single entity column, or county plus locality (label = `REF_AREA_2`, which carries
  the SIRUTA code). Any other key (for example county by sex) has no single label: null.
- Fewer than 2 bars: null. A ranking cut to one row (`top_k` 1) has no chart.
- `query_data`: line when `TIME_PERIOD` varies and at most one other column varies (that column is the
  series, at most 12); bar when one period and one column varies. Null for: a cut preview or an incomplete
  source, an unweighted approximation, `conflicting_grain`/`duplicate_keys`, a repeated (x, series) key, a
  varying `UNIT_MEASURE`, two varying non-time columns ("two geographic series are never merged").
- `run_recipe`: bar per area when every row has a label and a numeric value and no row has `year`; null for
  the national series and for one row.
- No hint on `unavailable`, `error` or `needs_clarification` results.

## Chart link (`data.chart.url`)

`dataset-v2.html?code=…&f=…[&g=…][&lang=en]`. Filters are the query's effective filters (what the
aggregation policy pinned), the period is added (`rank_entities`: its year; `compare_periods`: the `to` year,
matched with `recipes._year`), levels come from `effective_selection.levels`. A recipe links to
`compare.html?recipe=…&year=…[&areas=…]`. The link is on the trusted origin, never shortened. Over 4096 bytes
it is `null` (and `url_note` is `null`); the chart hint stays.

**No stable bar preset:** `dataset-v2.html` builds tile ids at run time (`t=` keys them), so the link carries
filters, period and levels only. Checked in a browser: the page opens with "Selecția ta: 2026" for a
`TIME_PERIOD` filter, but it chooses its own tiles. `url_note` says it shows the values for the year, and
for `compare_periods` "not the computed change".

## Measured

Real corpus (generation `062bd2b0`, repo `data/` read-only), public MCP on :8090:

| Call | Result bytes | Hint bytes |
|---|---|---|
| `rank_entities` POP107D_grupe_localitate cities, top_k 10 | 5,956 | about 620 |
| `rank_entities` same, top_k 100, `en` | 16,214 | about 600 |
| `compare_periods` same dataset, cities, 2016→2026, percent, top_k 100 (the 2026-11-18 call) | 24,994 | about 640 |
| `run_recipe` tourism_intensity | 13,545 | about 640 |
| `query_data` POP112A_grupe, one series over time | 3,521 | about 700 |

The cap is 32,768 bytes; the largest case adds under 1 KiB. The hint URL is at most 4 KiB by rule; if a result
ever overflows, `_fit` halves rows as before and the hint still names fields of the rows that remain.

## Assumptions and open points

- A `partial` result keeps its hint (for example `unverified_total` on the POP107D city ranking). The warnings
  travel in the same envelope and the Ask table shows them, as for the table. If the owner wants no chart for
  `unverified_total`/`incomplete_domain`, it is one condition in `chart.apply`.
- `title` is the dataset's metric name, which is long for some datasets (POP107D). It is the same text the
  sources carry; a shorter label needs curated titles.
- The page `f=` uses the same list-valued filters as the existing evidence links. The page honours a
  `TIME_PERIOD` filter (browser check), but does not show it as a filter chip.
- The Ask chart is horizontal bars sorted as the hint says; echarts comes from the CDN as before.
- Not covered: line charts in Ask from a hint (`query_data` keeps the dataset chart spec); MCP Apps.
