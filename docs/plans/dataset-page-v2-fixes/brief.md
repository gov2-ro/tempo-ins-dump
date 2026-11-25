# DP-01 — Dataset page v2: a total inside the label, index notes, option pills, table filters (brief)

Owner decisions, 2026-11-26: do parts 1–4 below. No stacked bars for this case. The index keeps a
fixed base (option A). Example page:
`ins.gov2.ro/dataset-v2.html?code=CLV104A_litri_alcool_pur_100`.

The split `CLV104A_litri_alcool_pur_100` has one dimension `PRINCIPALELE_PRODUSE_ALIMENTARE_SI_BAUTU`
with two options. "Consum total de alcool (alcool 100%)" is INS's total. "Bauturi alcoolice distilate
(alcool 100%)" is one part of it (beer and wine are the other parts, in other units). In 2024: 8.7 and 2.0.

Work in a worktree. Commit only your own files. Do not deploy, and do not change the live corpus.

## Part 1 — recognise "Consum total de …" as the total (data rule)

### The problem

The KPI row shows "Total indisponibil: INS nu publică un total pentru această dimensiune". Verified:

- `dimension_structure` for the split: `confidence='flat'`, `aggregate_value=None`, `additive=None`.
- `kpi_total_checks`: `ours=10.7` (2.0 + 8.7, a double count), `status='unresolved'`,
  `reason='no_total_option:PRINCIPALELE_…'`.
- `dataset_meta.source_total_gate` therefore withholds the sum with `no_source_total`. The refusal is
  correct; the message is wrong, and the correct value (8.7) is not shown.

Cause: total detection matches only a label that *starts* with a total word.
`TOTAL_RE = ^(total|toate|ambele sexe|…)\b` lives in `app/services/chart_selector.py`, and a copy
lives in `13-dimension-structure.py:93`. `aggregation_policy._is_total_option` uses it, and so does
`scripts/check-kpi-totals.py` (`no_total_option`). The static engine mirrors the policy in
`app/static/js/engine/policy.js`.

### Step 1 — scan first, change nothing

Scan every canonical dataset dimension in the generation (read-only). List each option whose label
contains the word `total` (`\btotal\b`, case-insensitive, not `totale`) anywhere other than at the start,
and is not already matched by `TOTAL_RE` or `TOTAL_SUFFIX_RE`. For each candidate, report:

- code, column, label, unit, number of options in the dimension;
- the number of candidates in the same dimension;
- whether its value is ≥ every other option's value in every period and every slice of the other
  dimensions (the "dominates" check). Report the number of cells that fail.

Stop and report the scan to Opus before Step 2. The rule below may change after the scan.

### Step 2 — the rule (proposed)

In `13-dimension-structure.py`: a dimension's option is the aggregate when all of these are true:

1. Its label contains the word `total` (rule above).
2. It is the only such option in the dimension.
3. It dominates every other option in all checked cells (non-negative values).

Then store it as `aggregate_value`, with `additive=False`. Never sum the other options and never compare
their sum with it. The query-time policy then pins it like a "Total" label (method `aggregate_row`), so
the KPI shows INS's own value.

Keep one rule. If the scan shows a query-time rule is safer (no data check needed), say so and propose
it instead; do not build both. `check-kpi-totals.py` must see the same aggregate (use `aggregate_value`).
Any change to `aggregation_policy` must keep `policy.js` in step (static parity tests).

Acceptance:

- A synthetic fixture with "Consum total de X" + one part: the structure stores the aggregate, and the
  insights KPI returns the total's latest value, not a sum and not a refusal.
- A fixture with two "… total …" options, and one where the candidate does not dominate: no aggregate.
- For the real split, run stage 13 with `--matrix` on a **copied** generation only. Report the KPI
  value from `/api/datasets/CLV104A_litri_alcool_pur_100/insights` (expected 8.7, 2024).
- List every dataset where the rule now sets an aggregate.

## Part 2 — say what Index and Δ% show

Today the chips only carry a hover tooltip ("Index: prima perioadă = 100"). In index mode the chart
tooltip says "<dataset title> [Litri alcool pur (100%)]: 121.1". Readers take 121.1 as litres.

Change, in `app/static/js/dashboard-v2.js` (`applyTimeTransform`, `valueFormat`) and the chart code:

1. While Index or Δ% is on, show a one-line note under the chart, RO and EN, with the real base:
   - Index: "Indice: 1990 = 100. Peste 100 = mai mult decât în 1990." Name the first period in the data.
   - Δ%: "Schimbare procentuală față de anul anterior." Use the time grain (an, lună, trimestru).
2. The y-axis label and the tooltip carry the transformed unit ("indice, 1990 = 100" or "%"), never
   the dataset unit.
3. A single-series chart names the series by the selected option, not by the dataset title.
4. The base stays the first period in the data. Zooming does not rebase. The note always names the
   base year, so a zoom that hides it is still explained.

## Part 3 — pills instead of the option dropdown

The series selector next to the chips is a native `<select>`, which hides the options. When a
dimension has at most 6 options, show them as pills (single select, same state and URL as today).
Above 6, keep the dropdown. Long labels may wrap. Check the selector in the v2 page and any shared
helper it uses; do not change v1.

## Part 4 — filters for the data table

The table under the charts ("70 rânduri") has no filters. Add, per dimension column, a multi-select of
its options, and a year (period) range. The filters act on the rows already loaded; they make no new
request. Show "N din M rânduri" when a filter is active. Keep CSV/XLSX downloads unchanged (they export
the selection, not the table filter) and say so in a tooltip.

## Verification

- `python -m pytest tests -q`, and the static parity tests if Part 1 touches the policy.
- Chart-selector eval (dev MCP `tempo_eval_chart_selector`); explain any diff.
- Browser smoke of the example page and of one dataset with more than 6 options (dropdown stays) and
  one with a time series in months (Δ% note says "lună"). Check the console and network tabs.
- Report what you measured and what you assumed. Stop and ask if a step would change a spec, an ADR,
  an invariant or a file outside `app/`, `13-dimension-structure.py`, `scripts/check-kpi-totals.py` and
  tests.

## Order

Parts 2–4 are frontend only and independent of Part 1. Part 1 Step 1 (the scan) can run in parallel.
Part 1 Step 2 waits for Opus's review of the scan. Part 1 reaches production only with the next data
generation.
