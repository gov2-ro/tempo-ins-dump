# FIX-03 — Retryable pipeline and validated corpus generations

Status: not started. Priority: P1. Owner: ingestion and corpus tooling.
Dependencies: agree on FIX-02's verified grain/additivity contract. Deliver control
flow, refresh ordering, and corpus repair in independently reviewable steps.

## Problem and baseline

`update-pipeline.py` continues after metadata failure, ignores rebuild failures,
and advances a date checkpoint when matrices failed. Some child scripts log handled
errors and exit zero. Metadata import only enriches missing records, so refreshed
dimension options are not reliably imported for existing datasets. Conversion and
splitting happen before the final import; mapping/classification/coverage/trend
refreshes are missing from the incremental orchestrator.

Audit counts and samples are in the spec index. In particular, AMG115A parent and
splits put hours-worked labels in TIME_PERIOD and years in TIME_PERIOD_2. This
affects parents too; do not assume the split path alone caused it. AGR101B_judet
has 2,416 repeated dimension keys with differing values after locality labels
were removed. DISTINCT is not county aggregation.

Read `update-pipeline.py`, stages 3/6/9/10/11/12/13, `split_rules.py`,
`generate_view_profiles.py`, `detect_trends.py`, `duckdb_config.py` and
`scripts/audit-corpus.py`. Do not run the deprecated stage-12 SDMX converter.

## Pipeline success and ordering

1. Record per-matrix/per-stage state, source update timestamp, outcome and reason.
   Required errors produce a nonzero process exit. Metadata-fetch/import, CSV,
   conversion and registered split output are required. Decide which profiles are
   required for publishing; optional failures must be visible and restrict derived
   features rather than claiming verified coverage.
2. Persist a retry set. A failed matrix cannot disappear when a global watermark
   advances. Minimal first patch: keep the watermark unchanged on any required
   failure. Durable retries may subsequently allow successful work to advance.
3. Derive the watermark from successfully handled feed updates, not wall-clock
   today. Merge retries with news results, handle multiple updates on one date,
   and define manual --matrix/--since/--all/--skip-existing behavior explicitly.
4. Fetch/validate metadata and CSV; import changed metadata/options; classify and
   refresh code maps; convert canonical parquet; split/register children; profile
   parent and children; rebuild coverage/trends/view profiles/search as needed;
   validate artifacts; then publish/checkpoint. Check prerequisite return values.
5. Add targeted refresh paths for scripts that currently only support global runs.
   Preserve foreign-key relationships and unrelated matrices. Do not drop all
   classification rows to refresh one matrix or let an existing-record guard
   suppress newly fetched dimension changes.
6. Normalize language configuration explicitly at subprocess boundaries. --lang en
   currently does not propagate to stage 9's TEMPO_LANG-based paths; canonical
   corpus output is shared. English label ingestion must not overwrite Romanian
   canonical data. Define and test an explicit enrichment-only English mode, or
   reject the unsafe mode until supported; remove misleading CLI promises.

## Artifact and repair policy

Write replacements to temporary outputs, validate, then publish them. Regenerate
split children as a set; a failure must preserve the last usable generation. A
manifest must tie DB metadata, parquets, profiles and index to the same generation.
Use staging/copies for cross-file consistency rather than assuming a DB transaction
makes filesystem writes atomic. Stop readers that would conflict with DB writes.

Produce a deterministic read-only audit with explicit categories: served canonical,
noncanonical parent, registered split, intentional unavailable, leftover and invalid.
Correct the view-profile audit path to `data/corpus/view-profiles`. Report schema,
NULL dimensions, time validity, grain uniqueness, mapping/profile coverage and
registration. Include file hashes, row counts and source/update provenance.

Classify the 179 unmatched files before repair; quarantine confirmed leftovers with
a manifest instead of deleting them. Explain the 7 metadata-only cases rather than
counting every unavailable parent as a failure. View-profile absence must be judged
against the serving contract; do not invent profiles for unsupported leftovers.

Repair real time classification based on dimension meaning and sampled values;
rename hours-worked to a descriptive concept and map actual time to TIME_PERIOD.
Update dependent metadata/code maps and regenerate affected children. Do not swap
columns blindly or reinterpret free text as dates.

County split policy: if child grain drops locality, values may collapse only when
additivity and disjoint locality membership are verified under FIX-02. SUM verified
additive localities grouped by remaining dimensions; for rates/indices lacking
valid weights, preserve locality grain or mark the county aggregate unavailable.
Do not deduplicate differing values or choose the first. Child metadata must
describe the actual grain. Fix counts only after comparing to source totals.

## Acceptance tests and migration gates

- Inject metadata, fetch, import, conversion, split and profile failures. Verify
  exits, retry state, unchanged watermark and preservation of usable artifacts.
- Re-run and resume a synthetic feed; no updates lost, no recursively split
  children or duplicate registrations, and dry-run changes no corpus/checkpoint.
- Refresh an existing matrix with a new option and a new period; maps, parquet,
  parent/child metadata, derived profiles and search all reflect the refresh.
- Explicitly test language-mode safety and source paths without a network fetch.
- A synthetic hours-worked dimension stays categorical; real periods validate.
- Additive locality fixture produces one correct county row; non-additive fixture
  is rejected/preserved with its grain; overlapping localities never double count.
- A shadow audit has zero unexplained served violations. Exceptions carry a reason,
  affected IDs and serving restriction, not a blanket numeric allowlist.
- Real repair report shows source/target hashes, changed grain, per-file counts,
  NULL/time changes and source-reconciled totals. Stop on unexplained loss.

Deliver a dry-run repair command, explicit opt-in publish step and rollback to a
previous complete generation. No global destructive repair is part of simply
implementing or testing this package. Integrate the manifest gate with FIX-05.
