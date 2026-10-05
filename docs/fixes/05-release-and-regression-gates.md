# FIX-05 — Reproducible releases, FTS and regression gates

Status: phase 1 implemented on fix/05-release-gates and merged to audit-fixes (not yet on main) (FTS staging, release-check wrapper, FTS-in-image, per-request FTS cursors, split requirements, tracked CI, corpus test markers); not deployed, docker smoke not yet run (no docker locally). Phase 2 (FIX-03 generation manifest, correctness fixtures from other packages, image smoke evidence, eval baselines) open. Priority: P1. Owner: deployment and validation tooling.
Dependencies: FIX-03 generation manifest; meaningful tests from the other packages.
FTS staging and an initial validation wrapper may ship before corpus repair.

## Problem

Docker copies a manually staged deploy-data directory. Preparation does not copy
search.duckdb. The local source index exists but the staged index does not; live
search falls back to name matching. The local Fly workflow is ignored/untracked,
and no tracked CI proves a clean checkout can validate or build the release.
The 38 passing tests and unchanged chart picks do not test numerical correctness;
2,116 new chart-eval datasets lack baseline comparisons.

Read Dockerfile, fly.toml, requirements.txt, .dockerignore, .gitignore,
`scripts/prepare-deploy-data.sh`, `scripts/build-search-index.py`,
`dataset_search.py`, eval services/baselines and `tests/`.

## Required release flow

Provide one documented entry point: validate source generation, build/rebuild its
FTS index, stage required artifacts, verify manifest/hashes and index availability,
run tests/image smoke checks, then invoke deployment only when explicitly requested.
Preparation must precede image build; Fly release_command cannot repair stale data
already copied into that image.

Stage metadata, canonical/required parquet files, profiles, search index and the
generation manifest together. Build staging in a temporary directory and replace
only on success. Copy from a quiescent generation; reject mid-copy changes or hash
mismatches. Separate an old-but-consistent source observation date from a stale
generation/staging mismatch. Show both dates rather than guessing freshness from
file mtime. Preserve the previous staged/generation artifact for rollback.

Make the FTS extension available for the pinned DuckDB version/platform in the
runtime image; test LOAD fts without a surprise runtime download. Fail the release
check on missing/incompatible index or required extension. Development fallback
may remain, but production fallback must be observable. Use per-request cursors
for the FTS sidecar too; the current cached connection is shared across threads.
Index coverage and generation must match the serving catalog. Define whether query
totals/pagination refer to the whole match set or a ranked cutoff; do not imply a
200-candidate cutoff is the full catalog count.

## CI and dependencies

Commit a tracked workflow for synthetic tests and artifact validation. Remove the
broad .github ignore only as needed; do not accidentally include local credentials
or deploy-data. Data-dependent checks are a separate job supplied a validated
artifact, not a required 320MB checkout. Define runtime, pipeline and development
dependency sets, including currently implicit pandas/requests/tqdm/pytest/httpx
requirements; use supported Python and reproducible version constraints/locks.

Exercise correctness fixtures from FIX-01/02/03/04/06/08 and browser checks from
FIX-07. Keep production-source smoke checks bounded and read-only. Do not silently
replace chart/search baselines. Review numerical changes and additions, and keep
selection-regression baselines distinct from gold numerical expectations.

## Acceptance tests

- Clean checkout can install documented dependencies and run synthetic tests
  without a maintainer home path, corpus or secrets. Existing real-corpus tests
  are marked/separated or given fixtures; a CI skip is not a passing numerical test.
- Failed preparation leaves previous staging usable; old staging, missing search,
  changed source hashes and schema/index generation mismatches block image release.
- Built image can serve a fixture catalog, query its FTS index and export a known
  selection. Test multiword Romanian/English queries whose matches depend on
  tags/definitions rather than literal names, and stable tie ordering.
- Concurrent FTS fixture searches remain isolated without duplicate/mixed results.
- A package's failed correctness test blocks the release flow. Validating an image
  does not automatically deploy it or require access to Fly secrets.
- Demonstrate rollback to a previous complete artifact and report generation ID,
  pipeline outcome, index mode and latest source observation/update dates.

## Completion evidence

Provide exact clean-checkout commands, tracked workflow, staged manifest and image
smoke results. Document deployment and rollback in CURRENT_STATE.md/readme.md.
Do not split repositories or migrate hosting as part of this repair.
