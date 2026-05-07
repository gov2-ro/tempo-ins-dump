# Visual Smoke Test — 2026-05-07

13 exemplars across 11 clusters loaded in lens; selector pick verified against rendered ECharts series type. Console: zero errors/warnings across the sweep.

| # | Code | Cluster | Expected (taxonomy) | Selector primary | Rendered timeline | Rendered snapshot | Verdict |
|---|---|---|---|---|---|---|---|
| 1 | CON107B | 1 Simple Time Series | line | line | line × 5 | bar × 1 | ✓ |
| 2 | AGR201G | 2 Categorical Time | small_multiples / heatmap | small_multiples | small_multiples (14 panels) | bar × 1 | ✓ |
| 3 | COM109B | 3 Composition (%) | line / sm / heatmap | line | line × 3 | bar × 1 | ✓ |
| 4 | TIC113A | 4 Gender-Split | hbar / line / sm | line | line × 5 | bar × 4 | ✓ |
| 5 | AGR201E | 5 Age Cohort | sm / heatmap / grouped / hbar | **heatmap** | **line × 12 (single grid)** | bar × 1 | ⚠ FE renders line, not heatmap |
| 6 | TFA0494 | 6 Population Pyramid | population_pyramid | population_pyramid | line × 4 | bar × 2 (pyramid) | ✓ |
| 7 | LOC103B_judet | 7 Cartographic | choropleth / sm / hbar | **choropleth** | line × 1 | **line × 1 (NOT map)** | ✗ map not rendering |
| 8 | AMG158G | 8 Geo + Demographic | choropleth / line | choropleth | line × 8 | map × 1 | ✓ |
| 9 | TAV0212 | 9 Urban/Rural | hbar / line / sm | small_multiples | small_multiples (12 panels) | bar × 4 | ✓ |
| 10 | PPA103A_lunar_lei_buc | 10 Categorical Snapshot | bar_vert / grouped / hbar | bar_vertical | bar × 1 | — | ✓ |
| 11 | PNS101D_regiuni_anual | 11 Geo Snapshot | choropleth | choropleth | bar × 2 | map × 1 | ✓ |
| 12 | SAR118A | 6 Pyramid (alt) | population_pyramid | population_pyramid | line × 2 | bar × 2 | ✓ |
| 13 | TLR1111 | 4 Gender-Split (alt) | hbar / line / sm | line | line × 10 | bar × 1 | ✓ |

**11 / 13 visual passes.** 2 frontend dispatch gaps surfaced:

## Gap 1 — Cartographic falls back to line when `archetype` is null
LOC103B_judet (cluster 7): API returns `chart_config.pair = {primary: choropleth, complement: line}` and `ranked_charts[0] = choropleth (0.95)`. Frontend (`explore-app.js:1642`) only adds choropleth to the snapshot tab list when `archetype === 'geo_time' || archetype === 'geo_only'`. LOC103B_judet has `archetype: null` (split datasets don't carry over the parent archetype), so the choropleth tab is dropped and the snapshot dispatches to whatever else is in the list.

**Fix**: build snapshot/timeline tab lists from `chart_config.ranked_charts` (drop the static archetype-keyed recipe). Backstop: re-classify split datasets so archetype is set for `*_judet` / `*_regiuni` etc.

## Gap 2 — Heatmap timeline never dispatched
AGR201E (cluster 5): selector picks heatmap with high confidence, but the timeline panel only offers Line / Bar / Area / Stacked / Index / Δ%. Heatmap is offered as a *snapshot* chart type in the lens recipe, not a timeline option. The selector's primary lands on heatmap, gets dropped from both panels, and the timeline falls back to line.

**Fix**: add heatmap to timeline panel options when chart_config picks heatmap as primary. Same root cause as Gap 1 — static recipe in explore-app.js v.s. API-driven dispatch.

## Console
Zero errors or warnings across all 13 datasets. No GeoJSON load failures, no NaN axis errors, no missing-dim crashes.

## Selector vs. taxonomy
All 13 baseline matches confirmed: the selector's pick is in the cluster's expected set. Where the rendered chart diverges from the selector pick (rows 5 & 7), the gap is in the frontend dispatch, not the engine.

## Screenshots
`data/eval/smoke-screenshots/01_*.png` … `13_*.png` (full-page).
