# FIX-06 — Correct place indicators, dates and change units

Status: not started. Priority: P1. Owner: place service and UI.
Dependencies: FIX-02 policy for weighted/approximate aggregation; latest-period,
identity and unit fixes can ship first without fabricating new weights.

## Problem and files

`place_kpi_config.json` labels SOM103A as BIM unemployment, while its source
definition says registered unemployment. `_query_kpi_series()` sorts years ascending
then LIMIT 30; live Bihor's latest unemployment value is from 2020 despite source
periods through 2024. Baseline queries have the same oldest-period cap. Rates are
unweighted means of sex/residence groups with approximation notes only in config.
`place-page.js` displays relative population change as `0.1 pers.` and omits the
KPI observation period.

Read `place_service.py`, `place_kpi_config.json`, `place-page.js`, place.html,
`routers/places.py` and `tests/test_place_service.py`.

## Required behavior

1. Every KPI identifies its actual source, definition, observation period, unit and
   method. Keep SOM103A and rename it as registered unemployment in RO/EN; do not
   silently substitute BIM data with a different population/geographic scope.
2. Query latest periods before applying a display cap, then return them ascending.
   Latest value and comparison must come from the complete eligible series, not
   an oldest-30 window. Apply the same logic to national/regional baselines and
   peers. Do not treat absent observations as zero.
3. Use FIX-02's verified totals/weights. Without defensible weights, display a
   specifically named approximation or suppress that composite KPI. Config notes
   are not adequate user disclosure. Avoid claiming a county average of sexes is
   the official registered-unemployment total.
4. Add period/source/method and explicit change metadata to responses. Count
   changes use relative percent; percent rates use percentage points; per-mille
   rates use per-mille-point differences. Return unavailable changes for missing
   comparison periods/zero denominators. A zero current value is valid data.
5. Display dates and units alongside values and changes, with translated indicator
   labels. Clearly indicate stale periods and comparisons using different dates.
   Preserve selection/peer/baseline navigation and existing place URLs.

## Acceptance tests

- A 34-year fixture returns the latest eligible year, not year 30. Sparkline order
  remains ascending and baseline/current-value periods agree.
- Known count change 100→110 displays +10%; rate 2.0→2.4 displays +0.4 percentage
  points. Per-mille differences use their own labels; population never uses pers.
  as the change unit. Zero/missing cases are covered.
- Source SOM103A is never labelled BIM/ILO in either language. Renaming does not
  break the baseline label route; provide an alias for existing bookmarked labels
  or document a migration while accepting old labels unambiguously.
- Known weighted fixtures agree with FIX-02; unweighted approximations are visible
  in both response and UI and never presented as official totals.
- Browser Bihor fixture shows source/year/method, latest data, correct delta units
  and working peer comparisons at 390px and desktop.

Read-only source check: SOM103A_judete includes Bihor 2024 sex values 2.1 and 2.7
in the audited corpus. This is evidence of later data, not an instruction to assert
their mean is the true county rate. Recompute expected values from a justified
source selection when the corpus changes.

## Completion evidence

Provide old/new KPI identity/period/method lists for representative county, region
and macroregion profiles. Note omitted indicators and changed historical series;
do not preserve misleading cards solely to keep existing count-based tests green.
