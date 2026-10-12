# Methodology: how our numbers relate to INS's

How the explorer turns INS TEMPO Online exports into the values it shows, and when
those values can differ from what INS publishes. For pipeline mechanics see
[CURRENT_STATE.md](CURRENT_STATE.md); for the evidence behind the examples, the
[PA-00 answer records](plans/public-alpha/pa-00/answer-records.md).

## 1. What we download

- Each INS matrix is fetched as a CSV from the TEMPO pivot API, with its metadata
  (definition, methodology, options, INS's "last updated" date).
- **Options labelled "Total" are dropped at fetch.** The download keeps the
  breakdowns (counties, sexes, CAEN sections, age groups…) but not the totals INS
  publishes across them. Every total the app shows is therefore either computed by us
  or, where computing it would be wrong, not shown.
- A set of downloads, plus everything derived from it, is a **generation**,
  identified by `generation_id`. INS revises data. A generation shows INS's data as it
  was on the fetch date, not INS's current values. Example: POP105A revised 2024–2025
  on 10-09-2026, after an earlier download.

## 2. Counts: summing gives INS's total exactly

Counts of people, stays and units, and money totals (not averages), are additive.
INS publishes them exactly, so summing a **complete, non-overlapping** breakdown
reproduces INS's total exactly, not approximately. Checked on POP105A
(645 county-years) and TUR105D (602 county-years).

The condition matters more than the arithmetic. We sum a dimension only when its
structure is verified as one disjoint level (`dimension_structure`). We never sum:
- dimensions whose options repeat the same domain at several levels (single years of
  age **and** five-year bands; counties **and** regions);
- label-encoded trees (indented options, "- total", "din care" rows);
- several units of measure together.

In those cases the API answers `unavailable` with a reason (`overlapping_levels`,
`label_hierarchy`, `mixed_units`, …).

## 3. Averages, rates, percentages, indices: never summed

A mean or a rate is not the sum of its parts, and not their plain average either.
The county's average wage is the employee-weighted average of the sections' wages.
The both-sexes unemployment rate is total unemployed / total active population. Without
the weights:
- the API refuses (`non_additive_measure` / `missing_weights`);
- with `approximate=1` it returns an **unweighted mean**, labelled as an
  approximation and never called a total.

**Reconstructions.** Where INS publishes the weights in another matrix, a reviewed
recipe rebuilds the total (`/api/recipes/{id}`, labelled "reconstituit"):
- `net_earnings_county`: CAEN-section × sex earnings (FOM106E), weighted by average
  employees (FOM104F).
- `registered_unemployment_county`: rates by sex (SOM103A) and year-end registered
  unemployed (SOM101E). The active population by sex is recovered as unemployed / rate.

## 4. Why a reconstructed total can differ from INS's

INS computes its total from unrounded survey data. We only have its **published**
parts, and each one is rounded (earnings to whole lei, rates to 0.1 percentage
points). So:

1. each part is off by at most half a unit (0.5 lei, 0.05 pp);
2. a weighted average of parts that are each off by ≤ 0.5 is itself off by ≤ 0.5;
3. INS then rounds its own total, by up to another 0.5.

So our value and INS's can be up to **one unit apart** (1 lei, 0.1 pp). When the true
value lies near a rounding boundary, the last digit differs. Example: Iași 2024 net
earnings reconstruct to 5,097.4 → 5,097; INS publishes 5,098.

Observed against INS's own total cells (2026-10-12):

| Recipe | Cells | Same after rounding | Largest gap |
|---|---|---|---|
| net earnings, 2008–2024 | 714 | 649 (91 %) | 1.14 lei (2 cells above 1 lei, where FOM104F's employee counts are not exactly INS's weights) |
| registered unemployment, 2010–2025 | 656 | 548 (84 %) | 0.09 pp |

Counts have none of this: they are published exactly and add up exactly (section 2).

**What it means for use.** A reconstruction is good for levels and trends. It is
fragile for rankings and thresholds: a 0.1 pp difference can reorder close
counties. Where INS publishes the total, prefer INS's cell. Keeping INS's "Total"
rows at fetch is an open decision (see BACKLOG, "Serve INS's own Total cells").

## 5. How values are checked

- **Headline KPIs:** every summed KPI is compared with the cell INS publishes
  (`scripts/check-kpi-totals.py`, stored as `kpi_total_checks`). A KPI is shown as a
  total only when INS confirms it, or when its structure is verified and INS does not
  contradict it.
- **Answer records:** reviewed questions are checked against independently fetched INS
  cells, kept with fetch time and sha256 (`scripts/fetch-ins-reference-cells.py`).
- **Tolerance:** counts must match exactly. For means and rates, a reconstruction may
  differ by up to one published unit (section 4), and the difference is disclosed.

## 6. Labels you will see

| Label | Meaning |
|---|---|
| total | INS's own cell, or an exact sum of a verified disjoint breakdown |
| reconstituit / reconstructed | weighted rebuild of a mean or rate from INS-published weights; may differ from INS's total by one unit in the last digit |
| aproximativ / approximation | unweighted mean; not the statistic, shown only on request |
| interval / range | the value is unknown, but must lie between the shown bounds (e.g. between the two sexes' rates) |
| unavailable + reason | no honest single number exists for this selection |

Per-dataset caveats, series breaks and the decisions behind them are kept in
`app/data/dataset_notes.json` and listed in [reports/ins-notes.md](reports/ins-notes.md).
