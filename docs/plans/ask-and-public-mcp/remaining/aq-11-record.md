# AQ-11 record — generation refresh on a copy

Brief: [11-generation-refresh.md](11-generation-refresh.md). Branch `aq-11-refresh`. Not merged, not promoted, not deployed.
Run 2026-11-18/19. Owner decisions of 2026-11-19: keep the strict stage-12 rule (option a); county figures come
from the `_localitate` children.

## Generations

- Served (source): `062bd2b031733ea7d21089a40047606b943557e2dbec2434fda3ba7c0fc96e67`.
- Copy: `adc6762a4aedaeb43bde37e76a87dfca7248875453b2ae88b1d75e8e855a45c3`, at `~/devbox/gov2/tempo-gen-20261118/data`
  (copied: `corpus`, `parquet-v2`, `2-metas`, `1-indexes`, `meta`, `eval`; no CSVs).
- Staged: `~/devbox/gov2/tempo-gen-20261118/deploy-data` (991 MB, no tarball). Logs: `~/devbox/gov2/tempo-gen-20261118/logs`.

## Write isolation

Before the first write I recorded size and mtime of 18,675 files under the main `data/` (all but `4-datasets*`).
After the first command (`12-split-datasets.py --matrix AGR101B`, `TEMPO_PIPELINE_DATA_DIR` on the copy), after all
stage-12 runs and after the last step the diff is empty. The main DuckDB files were never opened.

## Commands, in order (all with `TEMPO_PIPELINE_DATA_DIR` on the copy; app/tests/evals with `TEMPO_DATA_DIR`)

1. `12-split-datasets.py --matrix <parent>` for 74 `hierarchy` parents, then for 7 `cross_product` parents that also
   had a county rule (AGR202B, LOC108B, POP107D, POP108D, PPA101A, SOM101E, SOM101F). 81 parents, all exit 0.
2. Metadata cleanup by hand (backlog: stage 12 does not do it): DELETE of the 95 removed codes from `matrix_profiles` 95,
   `dataset_trends` 95, `dataset_value_profiles` 95, `dimension_structure` 243, `dataset_coverage` 3, `kpi_total_checks` 10;
   95 `view-profiles/*_judet.json` files; 95 entries of `view-profiles/_index.json`.
3. `10-import-metadata.py --matrix <81 parents> --stats-only`; `10-classify-dimensions.py --matrix <95 children>`;
   `13-dimension-structure.py`, `generate_view_profiles.py`, `scripts/profile-values.py`, `detect_trends.py --matrix <81+95>`;
   `11-coverage-profiler.py --matrix <81 parents>`.
4. `has_time`: `10-classify-dimensions.py` then `generate_view_profiles.py --matrix <339 codes>`.
5. `scripts/build-search-index.py`; `build-generation-manifest.py` (copied into `corpus/`).
6. Checks (below), the full test suite once, `prepare-deploy-data.sh` (`TEMPO_CORPUS_SRC`, `TEMPO_DEPLOY_OUT` on the copy,
   `--no-tarball`), `release-check.py --local --stage <deploy-data> --skip-tests --require-clean-audit --accept-restriction conflicting_grain`.

## Per-parent outcomes

- 81 parents run, 0 failed, 0 kept the previous set. **0 `_judet` children regenerated; all 95 removed.**
- Cause: every `REF_AREA_2` structure in `dimension_structure` is `flat` with `additive=None` (158 geo rows). The locality
  column has no county roll-up option, so `key_drop_decision` never passes. Reasons: 73 parents "no verified additive
  structure"; PPA101A (currency), SOM101F (percentage), TUR103D and TUR103F (time unit): measure not additive; SOM101E,
  AGR101B, POP201D, POP201K: as expected by the 2026-11-08 entry. Owner accepted.
- The 7 `cross_product` parents lost only their `_judet` children. Their other 21 children keep their row counts in
  `dataset_splits`; the 6 parquets of AGR202B and LOC108B are byte-identical, the other 15 differ in bytes but a full
  `EXCEPT` both ways shows 0 differing rows. Over the whole corpus only those 15 files changed bytes; 95 files were removed.

## Repeated-key scan

No `*_judet.parquet` file is left. The manifest's `grain_findings`: `conflicting_grain` 174 to 79 and `duplicate_grain`
177 to 82. Exactly the 95 `_judet` files left both lists; none was added. The 79 left (`SCL104A_judete`, `AGR201E`, ...) are
outside the brief. Strict audit violations: `conflicting_grain` 160 to 65, all else 0.

## References and metadata

- Metadata query: for every table in `information_schema.tables` (schema main) and every VARCHAR column,
  `select count(*) from t where col in (<95 codes>)`. Before cleanup: 6 tables named them; after: **0 hits**.
- Curated configs naming a removed code: `concepts.json` (`domicile_population.also_variants.county`, now
  `POP107D_grupe_localitate`) and `dataset_notes.json` (note `TUR105EH-county-split`, retired; report rebuilt, sync test green).
  None in recipes, discovery defaults, published_totals, place KPIs, headline config, `ask_tasks.json`.
- Concept check on the copy: `query_data POP107D_grupe_localitate`, `group_by=[REF_AREA]`, 2024: 42 rows (41 counties and
  Bucuresti), status `partial`, warning `unverified_total` (not refused), total 21,862,436. Alba 363,840 equals the SQL sum
  of its localities. The old county table POP107A_judete_grupe has Alba 363,660 (older vintage). Discovery
  ("population by domicile by county 2024") now answers from POP107D_grupe_localitate with `newer_vintage_preferred`; the
  suggested `query_data` returns the 42 rows. Test: `tests/test_aq11_county_variant.py` (3 tests).
- Stale code and test mentions updated: `scope.py`, `schemas.py`, `explore-app.js`, `alpha-workload.py`, 4 tests.
- Static links: all 95 removed codes are in the served `_static/sitemap.xml` (3,432 `<loc>`). The redirect is a backlog item.

## Audit and profile diff (served to copy)

- Files: registered splits 2,191 to 2,096; matrices 4,110 to 4,015; parquet 4,110 to 4,015; view profiles 4,014 plus index.
  Registration issues 0. `parquets_without_view_profile`: 1 (not examined).
- `matrix_profiles`: only `has_time` changed, false to true on 339 rows. Before: 350 with `TIME_PERIOD` but no `has_time`;
  after: 0. The other 11 were removed `_judet` children.
- `dimension_structure`: 3 new rows, 368 rows changed only in the `levels` text; `additive` and `aggregate_verified`
  changed nowhere. `dataset_value_profiles` 46, `dataset_trends` 40 and `dataset_coverage` 2 rows differ
  (recomputed on the touched codes); not examined value by value.

## Evals

- **Chart selector** (`evaluate_all` against `chart_selector_baseline.json`, 95 removed entries dropped first, total 4,015 both):
  4,015 compared, 3,972 equal; 7 primary, 9 top-set, 9 confidence and 18 score changes. All 43 codes are in the
  339-code `has_time` repair list. The primary changes are 7 `*_trimestrial` AMG datasets (small_multiples or heatmap to line):
  they now have a time axis. Baseline not rebuilt.
- **Agent search** (17 questions): all 17 differ from the baseline, and all 17 differ the same way on the served
  generation (checked on a scratch copy of the served DBs, since deleted): the baseline is stale (backlog P3). Served vs copy:
  14 questions identical; 2 lose `_judet` codes (`locuinte construite`, `productie agricola vegetala`); 1 swaps two
  neighbours (`preturi de consum inflatie`, search index rebuild). `populatie pe judete` also lost LOC103B_judet. Only the three
  removed `_judet` codes were dropped from the baseline.
- `chart_taxonomy.json` and `chart_taxonomy_baseline.json` (2026-05 clustering, read by no eval) still name LOC101B/103B/104B_judet
  as exemplars; left unchanged. `smoke-test-report.md` has a note.

## Public figures

No headline, place KPI, recipe or `published_totals` value can change: no config names a removed code, the `published_totals`
table has the same rows, and every other parquet is identical in content to the served one. Not recomputed one by one.

## KPI check

Not run. `check-kpi-totals.py check` asks INS for each cell, and no offline cache exists in the repo or the copy. The 10
`kpi_total_checks` rows of removed codes were deleted (they described removed pages).

## Tests

`TEMPO_DATA_DIR` on the copy, once: **2,408 passed, 63 skipped, 0 failed**, 988 s. The skips are tests pinned to generation
062bd2b0 or missing records. Spot check "regenerated county equals sum of localities and the INS total": not applicable (no
county child regenerated); the equivalent check on the locality child is in the concept check above.

## Release check

`prepare-deploy-data.sh` accepted the copy as source (it only reads `TEMPO_CORPUS_SRC` and snapshots it before and after).
`release-check.py --local` strict: PASSED. Warnings: 734 non-canonical parquets (parents, as before) and
`run_recipe registered_unemployment_county` unavailable/`query_budget` under the public profile (not compared with the served
generation; the recipe is not otherwise affected).

## Rollback

Nothing outside `~/devbox/gov2/tempo-gen-20261118` and this branch changed. To drop: delete that folder and the branch. To
promote later (owner): replace the repo `data/` generation, `deploy.sh`, rebuild static, `deploy-static.sh`. To roll back after
promotion: restore the previous `data/` generation 062bd2b0 (kept by the owner) and redeploy.

## Assumptions and open questions

- The 7 `cross_product` parents were not in the brief's "74 hierarchy parents" and were run as well.
- The 95 view-profile index entries were removed by hand; `generate_view_profiles.py --matrix` keeps stale entries.
- The `registered_unemployment_county` budget warning needs a comparison with the served generation.
- Pages for the 95 removed codes disappear; old links need the redirect (backlog).
