# AQ-10 — "Din care" subsets are summed with their parent option (brief)

Priority: P1, correctness, live. Found by the AQ-09C sweep (Q17) and confirmed on 2026-11-18.

## The defect

INS marks a subset option with the label prefix "Din care:" ("of which"). The option is a part of
the option before it, not a sibling. LOC104A (dwellings completed), dimension `SURSE_DE_FINANTARE`:
- "Din fonduri publice"
- "Din fonduri private"
- "Din care: din fondurile populatiei" (a part of "Din fonduri private")

Measured on the served generation (`062bd2b0`):
- `rank_entities` on LOC104A for 2023 gives București 18,654 = 13,834 (private) + 4,820 ("Din care").
- `kpi_total_checks` for LOC104A_judete, 2025: our sum 101,617; the INS Total 59,062.
- 364 datasets have an option label that contains "din care".

Why the policy sums it:
- `aggregation_policy.label_hierarchy_cues` recognises indentation and "- total" suffixes only.
- `dimension_structure` profiles the column as `flat`, with `verified: false`. So
  `_unprofiled_partition` returns `profile_flat`, and `decide` sums the three options.
- The split child LOC104A_judete refuses only because a `kpi_total_checks` row exists for it
  (`source_total_mismatch`). The parent LOC104A has no such row, so nothing stops the sum there.
- That refusal's recovery (`tools/query.py`, `_plan_source_total` → `verified_alternatives`) offers
  the parent. The parent is offered because the policy "does not refuse it at once".

## Required behaviour

1. **The policy never sums a "Din care" option with its siblings.** Recognise the cue in
   `label_hierarchy_cues`, or in a separate rule that names its reason. Match after
   `_fold`/normalisation: "Din care:", "din care", with or without diacritics, and EN "of which".
   Check the real labels of the 364 datasets first, and report the variants you find.
   - A summing query over such a dimension is refused with a clear reason and a recovery: pin one
     option, or select the non-subset options explicitly.
   - An explicit selection of only non-subset options can still be summed, if the other rules allow
     it.
   - An explicit selection that contains a "Din care" option together with the option it is part of
     is refused.
   - **Stop and ask** before you add an automatic rule, such as "drop the subset and sum the rest".
     Owner decision.
2. **The browser engine stays identical.** `app/static/js/engine/policy.js` (and `scope.js` if it is
   involved) must make the same decision. `tools/static-engine/parity.mjs` and `api-parity.mjs` must
   pass, with a new parity case for this rule.
3. **A refused child never recommends an unchecked parent.** For `source_total_mismatch` and
   `no_source_total`, offer an alternative only if its own source-total check passes, not merely if
   the policy does not refuse it at once. A parent of a split inherits its children's
   `kpi_total_checks` verdict for the same dimension, or has its own row. Choose the simpler rule and
   record why.

## Impact report (before you change behaviour)

The same policy feeds the dataset page tiles, headlines, place KPIs, recipes, Ask, the MCP and the
static build (`rec/` answers recorded from the API). Measure on the served corpus, read only:
- how many datasets and served queries change (dataset-page compositions in `view-profiles`, headline
  KPIs, place KPIs in `app/static/data/place_kpi_config.json`, recipes in `app/data/recipes.json`);
- the chart-selector and search evals (`tempo_eval_chart_selector`, `tempo_eval_agent`, or the
  scripts). Explain every diff before you rebuild a baseline.
- `scripts/check-kpi-totals.py`: how many of the summed KPIs that disagreed with INS (about 40% on
  2026-10-05) disagree because of "Din care".

Put the numbers in the record. If a public page or a curated KPI loses a figure, list it.

## Tests

- Synthetic fixtures (small DuckDB + parquet): a dimension with "Din care" refuses a sum; an
  explicit non-subset selection sums; subset plus parent refuses; diacritic and case variants;
  EN "of which".
- The Q17 path: `rank_entities` on a synthetic parent/child pair no longer ranks the double count,
  and the child's refusal no longer offers the parent.
- A corpus test (it skips without data): LOC104A, București, 2023 is no longer 18,654.
- `tests/test_static_parity.py` with the new parity case.
- The full suite once at the end (`python -m pytest tests -q`). Never run two full suites at once.

## Stop and ask when

- A curated KPI, headline or recipe depends on summing a "Din care" option.
- The rule needs a pipeline change (`13-dimension-structure.py` or the profilers). Report it, and
  do not run pipeline scripts. A later package can fix the profiler.
- Work is needed outside `app/services/`, `app/static/js/engine/`, `tools/static-engine/`, `tests/`
  and this plan folder.

## Deliverables

Code, tests, `aq-10-record.md` (the impact numbers, the label variants found, the choices), an
activity entry, and backlog entries for anything left: the profiler, and the static rebuild and
deploy. Commit on a branch; do not deploy. Once merged, the API needs a deploy, and the static site
needs a rebuild because its recorded answers change.
