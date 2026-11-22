# AS-01 record (revision 2)

Branch `as-01-age-span-total`. Copied generation (5e226fc3, served data, APFS clone): `~/devbox/gov2/tempo-gen-as01/data`, used only as `TEMPO_DATA_DIR`.

## Rule as built

`aggregation_policy.spanning_age_option(dim, eff)` (Python) and `spanningAgeOption` in `app/static/js/engine/policy.js` (static engine). Metadata only.

- The dimension is `dim_type='age'`, has at least two effective options, and every effective option has parsed `age_min` and `age_max`. Any missing bound (an open-ended band) switches the rule off.
- Exactly one option S has `S.min <= o.min` and `o.max <= S.max` for all options. Two or more such options: no pin.
- `decide()` treats S like a Total option in two places only: an unfiltered request (pins S, method `aggregate_row`) and a request that selects S alone (`pinned_aggregate`).
- `_is_total_option` is unchanged. A Total-labelled option or a `dimension_structure.aggregate_value` is found first and wins. An explicit multi-band selection keeps `overlapping_levels`.
- Nothing is summed, verified or compared. Verification stays `label`. The rule is therefore safe for rates.
- No new `method`, no contract change. `scope.py` and `scope.js` need no change: domain = union of options = S, and `pinned_aggregate` is already "complete".

## Scope check (served generation 5e226fc3)

The rule pins a band in 87 canonical datasets (see the scratchpad list in the report). Families:

| Datasets | Column | Band pinned | Measure |
|---|---|---|---|
| AMG111A/B, AMG131A/B (+ `_anual`, `_trimestrial`), AMG130M/N/O | AGE | `15 - 74 ani` | additive |
| AMG155C-F, AMG156C-F, AMG157C-F (+ variants) | AGE | `15 ani si peste` | rate |
| AMG157G/H/I | AGE | `15 - 74 ani` | rate |
| AMG158A/B, AMG159A/B (+ variants) | AGE | `15-74 ani` | rate |
| SAR119C | AGE | `0-64 ani` | rate |
| TFA0494, TLH1019 | AGE | `15-34 ani` | rate |
| TFX0531, TIS0824 (+ `_regiuni`, `_macroregiuni`) | AGE | `15-64 ani` | rate |

The 9 matches of the first run:

- AMG130M/N/O: AGE pinned; the dataset decision changes from `overlapping_levels` to a valid total with SEX summed.
- AMG157G/H/I, SAR119C: AGE pinned; the verdict changes to `missing_weights` (SEX summed on a rate).
- TFA0494, TLH1019: AGE pinned; another dimension still gives `overlapping_levels`.

## AMG130M numbers

Latest period 2026-09. There is no `Total` option in SEX (data: Feminin, Masculin).

- `15 - 74 ani`: Masculin 290,554 and Feminin 225,210; both sexes 515,764 (query_data with an explicit `SEX` set and the span pinned).
- The unfiltered request now pins the AGE span (`effective_filters {'AGE': ['15 - 74 ani']}`) and no longer reports `overlapping_levels`.
- It is still withheld, now with reason `source_total_unchecked` ("totalul nu a fost verificat cu INS"). SEX is summed over Feminin and Masculin with `metadata` verification, and the INS cross-check has no row for this dataset because there is no Total sex option. This is the existing SEX gate, not part of AS-01.
- `/api/datasets/AMG130M/insights` therefore still has no `latest` KPI (suppressed `source_total_unchecked`).

## Fix 2

`dashboard-v2.js renderInsights`: with a selection, the refusal card for `latest` is not rendered. Without a selection it stays. v1 (`explore-app.js`) has no such card: its insight row reflects the current selection's data, so it is unchanged.

## Verification

See the final report: unit tests `tests/test_as01_age_span.py` (12), static parity, chart-selector A/B (no diff), offline Ask tasks, browser smoke.

## Assumptions and open points

- The span rule also fires on the synthetic POPX fixture (single years plus one `0-4 ani` band that equals their sum). The offline Ask tasks T10 and T15 expected a refusal there and now see a pinned `0-4 ani`.
- Several pinned spans are the dataset's own domain, not the whole population (SAR119C `0-64`, 15-34 youth series, 15-64 working age).
