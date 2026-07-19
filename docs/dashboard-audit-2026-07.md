# Dashboard Audit — Charts, Filters, Views & Slices (2026-07)

Audit of how each dataset presents charts + filters, and the roadmap that came
out of it: evolve the dataset page from "a chart with dropdowns" into a
**perspectives surface** — for every dataset shape, the viewer is offered the
set of questions the data can answer. Target surface: **dashboard-v2**
(`dataset-v2.html` + `dashboard-v2.js` + `dashboard_composer.py`); v1
(`explore-app.js`) stays until parity.

## Corpus shape
1,986 baseline datasets: time_series 50%, geo_time 30%, demographic 13%.
Units: percentage 35%, count, currency, 171 unknown. Primary picks before the
fixes: choropleth 572, line 550, small_multiples 485, heatmap 250, pyramid 73.
315 low + 437 medium confidence defaults.

## Correctness bugs found (Phase 0 — FIXED 2026-07-19)

| # | Bug | Fix |
|---|---|---|
| B1 | `time_points` fallback returned the literal max year (e.g. 2024) → every `tp >= N` rule silently true, corpus-wide | fallback = `year_max − year_min + 1` only (`chart_selector.build_signature`) |
| B2 | Index/rate datasets got SUMmed in grouped queries; base-100 indices also stacked | shared `AVG_UNIT_TYPES` in `query_builder.py` (used by dataset_data, insights, agent); `index`/`ratio` added to composer `NON_ADDITIVE_UNIT_TYPES`; area/stacked ineligible for `index` unit |
| B3 | Blanket `exclude_total=True` could empty charts whose only real values are Totals | `_non_totals_survive()` grounds the default in parquet values |
| B4 | `geo>=4` choropleth eligibility + −0.15 geo-primary penalties force-routed 4-macroregion datasets to a 4-shape map | eligibility & penalties now `geo>=8`; 30 datasets moved to bars/lines |
| B5 | Pyramid allowed gender_count≤6 → Urban/Rural could become mirrored pyramid sides | new `gender_mf_count` signal (parsed male/female options); eval harness supplies it in lock-step |
| B6 | Dataset-level confidence stamped on every ranked chart | primary = gap to runner-up; alternatives = distance from primary |
| B7 | Insights YoY compared last two periods regardless of granularity (MoM labelled as YoY) | seasonal compare vs same sub-period last year (`2025-08` vs `2024-08`); MoM kept as secondary `prev` card |
| B8 | Selector line-series default (gender-first) diverged from composer's substantive-split retune | `retune_ranked_series()` aligns `ranked_charts` roles with composer tiles |
| B9 | Non-additive dims without Total pinned to the *first* option — arbitrary headline slices | `_widest_pin()` prefers the option with the most parquet rows (`_parquet_dim_values` now returns per-value counts) |
| — | area_stacked vestigial (no parts-of-whole detector) despite 444 percentage datasets | data-grounded `is_composition` probe in `dataset_meta` (non-Total options sum ≈ Total ±2%, or ≈100 for pct); ±0.30/−0.15 score adjustment |

Eval impact (reviewed before re-baseline): 64/1,986 primary changes — 30
choropleth demotions (geo 4–7), 17 short-series small_multiples/heatmap →
ranked bars (real `tp` exposed), pyramid fixes (SOM101C mf=1 → line; SAR115A
gained a valid pyramid). Baseline rebuilt.

Known deliberate divergence: the `is_composition` probe needs parquet access,
so the eval harness scores it as None (documented in `chart_selector_eval.py`).

## Frontend gaps (Phases 1–3)

| # | Gap |
|---|---|
| F1 | ~735 datasets have primaries (small_multiples/heatmap) the panels can't always dispatch → silent line fallback. Tab lists must come from `ranked_charts`, not archetype |
| F2 | Orphaned dead code (`dataset-page.js`, `dataset-page-v2.js`, `filter-panel.js`, `view-controls.js`, `period-browser.js`, `data-table.js`) holds the richest filter widgets — salvage then delete |
| F3 | Live filtering regressed to bare single-selects (v1 strip, v2 global row) |
| F4 | Choropleth computes per-year frames but renders only the latest — no time slider (demographic charts have a play-timeline) |
| F5 | Silent series truncation (top-12 by sum) with no "showing N of M" affordance |
| F6 | No pivot/transpose/role-swap anywhere — chart pills change style, never the question |
| F7 | v2 missing vs v1: data table, CSV/XLSX, Index/YoY transforms, zoom presets, period nav, i18n, theme toggle |
| F8 | Inconsistent v2 empty states (message vs silent tile drop) |
| F9 | Insights fetch failure silently swallowed |

## Unused riches
Signals computed but invisible: `has_seasonality`, `distribution`,
`coeff_variation`, `has_negatives`, `has_geo_outliers` (partial), option
`parent_id` hierarchies. `dataset_relationships` (18,880 rows) and
`dataset_tags` (92k) never surfaced. No distribution/slope/treemap charts.

## The reframe: from "which chart?" to "which question?"

| Perspective | Question | Views | Available when |
|---|---|---|---|
| Trend | Ce s-a schimbat? | line/area + Index/YoY + breakpoint annotations; seasonal overlay when `has_seasonality` | has_time, tp≥3 |
| Place | Unde? | choropleth with time slider + ranking bar + outlier chips | has_geo≥8 |
| Composition | Din ce e format? | 100% stacked, treemap for hierarchies | `is_composition` |
| Comparison | Cum se compară? | grouped bars, small multiples, slope chart, series multi-select | ≥2 non-singleton dims |
| Distribution | Cât de împrăștiat? | strip/histogram, log-scale when right-skewed | cv/distribution signals |
| Correspondence | Cu ce se leagă? | related-datasets rail, split siblings, tags, 2-dataset compare, county scatter | dataset_relationships |

Full phased implementation plan: see `docs/BACKLOG.md` → "Perspectives roadmap"
and the activity log entry of 2026-07-19.
