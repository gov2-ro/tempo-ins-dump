# AQ-11 — Generation refresh: re-split county children, repair `has_time` (brief)

Owner request, 2026-11-18: repair the served data on a copy, then ship it together with AQ-08 (chart
hints) and AQ-10 ("Din care" rule) in one VPS deploy and one static rebuild. **This is a data repair.**
Nothing touches `data/` of the main checkout, the VPS or DreamHost. The owner approves the
promotion of the new generation separately, after reviewing the record.

## Defects

1. **Every county child has repeated keys.** All 95 `*_judet` files of generation `062bd2b0` (74
   hierarchy parents in `dataset_splits`) keep one row per locality after dropping `REF_AREA_2`.
   Example: AGR101B_judet has 2,416 repeated key groups, about 114 rows per county and year. The
   grain guard refuses every tile, so 95 dataset pages are empty. The stage-12 fix (`94be06f`,
   2026-11-08, `split_rules.key_drop_decision`) sums to the county key only for an additive measure
   with a verified roll-up, and otherwise skips the child. The served generation was built on
   2026-10-14, before that fix.
2. **`has_time` is wrong for about 350 split children.** The classifier fix is in code (activity
   entry 2026-11-08, "PKG-PIPELINE"). The stored profiles were never recomputed. Codes:
   `dimensions.dim_column_name='TIME_PERIOD' AND option_count>1 AND NOT matrix_profiles.has_time`.

## Procedure (on a copy)

Read first: `AGENTS.md` (pipeline, gotchas, DuckDB write lock), the 2026-11-08 and 2026-10-12
activity entries, `12-split-datasets.py` (`_county_view_policy`, `_split_hierarchy`, the staging
and rollback), `split_rules.py` (`detect_hierarchy`, `key_drop_decision`),
`scripts/build-generation-manifest.py`, `scripts/audit-corpus.py`,
`scripts/prepare-deploy-data.sh`.

1. **Copy.** Copy the served generation to a new folder outside the repo, for example
   `~/devbox/gov2/tempo-gen-20261118/data`. Copy only what the steps need; a full `data/` copy holds
   9.7 GB of CSVs. The Mac has about 19 GB free, so check the space before and after. Record the
   source manifest id. Every later command runs with `TEMPO_PIPELINE_DATA_DIR` (pipeline) and
   `TEMPO_DATA_DIR` (app, tests, evals) pointing at the copy. Before any write, prove that a command
   writes only into the copy (AGENTS.md: stored `parquet_path` values are absolute and stale).
2. **Re-split.** Run stage 12 per hierarchy parent (`12-split-datasets.py --matrix <code>`). Read its
   argparse block first; do not probe scripts with `--help`. Record per parent: `_judet` regenerated
   (with summed rows), or skipped and why. Expect skips: AGR101B, POP201D, POP201K and SOM101E are
   named in the 2026-11-08 entry.
3. **Downstream of the split.** For each touched parent and its children, run the steps the
   orchestrator runs after stage 12: `10-import-metadata --stats-only` and the re-classification of
   the split children. Then rerun stage 13, the view profiles, and the scoped value profiles, trends
   and coverage, always with `--matrix`. Never run a profiler without `--matrix`: it rebuilds every
   row.
4. **`has_time`.** `10-classify-dimensions.py --matrix <codes>`, then
   `generate_view_profiles.py --matrix <codes>`, for the 350 codes (plus any the re-split adds).
5. **Global steps.** Rebuild the search index (`scripts/build-search-index.py`): touched children
   change, and removed `_judet` children must leave it. Then build the generation manifest. Its grain
   findings must no longer list repeated keys for any `_judet` child.
6. **Checks on the copy:**
   - `scripts/audit-corpus.py --data-dir <copy>`: compare with the served generation and list every
     change;
   - a scan of all `*_judet` files for repeated keys: expect 0;
   - spot checks: a regenerated county value equals the sum of its localities, and equals the INS
     Total where `kpi_total_checks` has one;
   - the chart-selector and search evals: explain every diff before you rebuild a baseline;
   - `scripts/check-kpi-totals.py`: before and after;
   - the full `python -m pytest tests -q` with `TEMPO_DATA_DIR` on the copy, once.
7. **Stage, do not deploy.** Run `scripts/prepare-deploy-data.sh` with the copy as its source, if the
   script allows that safely; otherwise stop and report. Run `release-check.py --local --stage <dir>`
   with the strict arguments from AGENTS.md. Run no `--deploy` and no upload.

## Stop and ask when

- A command could write outside the copy, or the disk drops below 8 GB free.
- More than 10 parents fail, or a parent that should keep its `_judet` child is skipped.
- A public figure changes in a headline, a place KPI, a recipe or `published_totals`. List each one
  with its old and new value.
- A step needs a fetch from INS (stages 1-6), or a schema change.

## Deliverables

- `aq-11-record.md`: the copy path and manifest ids; the commands in order; per-parent outcomes;
  the audit diff; the eval diffs with explanations; the KPI check; the test counts; the staged
  `deploy-data` path; the rollback.
- An activity entry and the backlog updates (the two P1 pipeline items).
- Code fixes found on the way, with tests, on a branch `aq-11-refresh`. Do not push, merge or
  deploy.

Promotion, after the owner approves:
1. Replace the repo's `data/` generation.
2. `deploy.sh` to the VPS.
3. Rebuild the static site, then `deploy-static.sh`.

AQ-10 must be merged before step 3, so that the static site records answers under the new rule.
