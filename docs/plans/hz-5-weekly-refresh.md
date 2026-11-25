# HZ-5 — Weekly data refresh on the VPS, minimal footprint (brief)

Written by Opus, 2026-11-25. Builds on [hosting-hetzner.md](hosting-hetzner.md) (HZ-1…HZ-4) and the
2026-11-20…25 refresh (activity log; memory "data refresh"). **HZ-5a is for a Sonnet session on the Mac.
HZ-5b (install on the VPS) is a later session with the owner present.**

## Why

- INS's news feed lists only about the last month. The corpus silently fell about a year behind because
  no feed run happened for months. A weekly run keeps every update inside the feed window.
- The Mac run needed about 13 GB, mostly raw CSVs (9.7 GB) that no later stage reads, and a
  `metadata.duckdb` that grew from 120 MB to 2.7 GB through rewrites. The VPS has about 10 GB free on
  `/opt/tempo` and also runs scrapers.
- Five manual steps of the last refresh must become automatic: probe and backoff, cleanup of retired
  split children, DB compaction, manifest and gates, and the INS KPI check for touched matrices.

## Decisions (Opus, 2026-11-25; the owner may overrule at review)

1. **Schedule:** weekly, Sunday 03:00 Europe/Bucharest. A monthly full metadata sweep
   (`scripts/utils/meta-sweep.py`) catches anything the feed missed. Stage 12 must not miss runs: if INS is
   down, the run retries daily until it succeeds, and stops after 7 days with a notification.
2. **Deploy policy, first phase: build, gate, notify.** The run builds a complete candidate release and its
   static site, runs every gate, and notifies the owner. It never swaps `current` and never uploads the
   static site. The owner approves with one command (`promote.sh <release-id>`), which does the swap,
   health check and swap-back, and the static upload. Automatic promotion is a later decision.
3. **No raw CSV kept.** Each CSV is fetched into a temporary folder, converted, and deleted after stage 9
   succeeds. If a stage other than 9 reads the CSV, find it and say so (see Work 1). The CSV mirror on the
   owner's backup drive covers a global reconversion.
4. **Notification:** a generic webhook (`TEMPO_NOTIFY_URL`, POST of a short text; works with ntfy.sh, a
   Slack webhook or similar) plus a status JSON. No email setup.
5. **The pipeline runs as the deploy user (`pax`), never as the service user `tempo`.** It has its own venv
   (`requirements-pipeline.txt`: pandas, numpy, pyarrow) outside the release folders. The API release venv
   must stay free of those (`deploy.sh` checks it).

## Layout on the VPS (proposal; adjust if a fact below is wrong)

```
/opt/tempo/
  releases/<id>/        API releases (unchanged; deploy.sh / promote.sh)
  current -> releases/<id>
  pipeline/
    venv/               pipeline venv (pandas, pyarrow, …)
    code/               git checkout of main, read-only during a run (or code from the current release)
    data/               the working generation: 2-metas, 1-indexes, corpus/ (parquet, DB, view profiles,
                        search), logs/, published-totals/; NO 4-datasets
    runs/<date>/        a run's scratch: hard-linked copy of data/ (cp -al) + a real copy of the DB,
                        temp CSVs, logs, the candidate deploy-data and static build
    status.json         last run: outcome, generation, counts, failures, retry set, timings
```

Copy-on-write is not available on ext4, so a run works on `cp -al` of `data/`. That is only safe if every
stage *replaces* a file (write temp + rename) instead of writing into it. **Verify this for each stage**;
the DuckDB files are always copied, never linked.

Steady state: corpus about 0.5–1 GB + DB 120 MB + metas 70 MB + two API releases (hard-linked) + one
candidate during a run. Budget: under 4 GB, and fail early when `/opt/tempo` has less than 5 GB free.

## Work — HZ-5a (Sonnet, on the Mac, on clones only)

1. **CSV readers.** List every script and stage that reads `data/4-datasets` (stage 9, `10-import-metadata`
   file stats, profilers, slim samples, `duckdb_config`). Make the run delete each CSV after stage 9
   succeeds (an orchestrator option such as `--drop-csv`, default off on the Mac). Make sure nothing later
   in the same run needs it, and that `file_size_bytes` stays meaningful or is documented as the CSV size
   at fetch time.
2. **Retired split children (backlog P3).** When stage 12 replaces a child set and a child code disappears,
   delete that code's rows in every profile table (`matrix_profiles`, `dimension_structure`,
   `dataset_trends`, `dataset_value_profiles`, `dataset_coverage`, `kpi_total_checks`, `sdmx_column_map`,
   and any other table keyed by `matrix_code`), its view profile and its `_index.json` entry. Find the
   tables from `information_schema`, not from this list. Add a test.
3. **Stale INS checks.** `dataset_meta.source_total_gate` accepts a `kpi_total_checks` row even when its
   `period` is older than the KPI's latest period. Treat such a row as unchecked (the KPI is then withheld
   as `source_total_unchecked`, never shown with an old check). Then the refresh re-runs
   `check-kpi-totals.py collect/check --codes-file <touched codes>` (`--write-db` now replaces only the
   checked codes' rows) so that touched matrices are re-verified. Tests for both.
4. **DB compaction.** `scripts/compact-metadata.py SRC DST`: schema copy (`COPY FROM DATABASE … (SCHEMA)`),
   inserts in foreign-key order (contexts, matrices, dimensions, dimension_options, then the rest),
   verification (same tables, row counts, a content hash per table, constraints, indexes, sequence
   values). It refuses to write the repository's `data/`. Test on a synthetic DB with the same FK shape.
   A plain `COPY FROM DATABASE` fails: the alphabetical order breaks the FK from `dimensions` to `matrices`.
5. **The run script** `scripts/refresh-run.sh` (or `.py`), one entry point:
   probe INS (`update-pipeline` probe; on failure, write status, notify only on the 1st and 7th day, exit) →
   check free space → make the run copy → `update-pipeline.py --refetch-news --global-profiles` (+ the
   monthly sweep codes when due) → retired-children cleanup → INS KPI check for touched codes → compact DB
   → manifest → audit (`--strict` rules as `release-check`) → stage `deploy-data` (`prepare-deploy-data.sh`
   with `TEMPO_CORPUS_SRC` / `TEMPO_DEPLOY_OUT`) → `release-check.py --local` (strict flags, its own port)
   → `build-static.py` → `release-check.py --static` with parity cases → write the candidate release folder
   → status + notification with: touched codes, new matrices, failures and retry set, gates, sizes.
   Nothing touches `current`, the live `data/`, or DreamHost. A failed step leaves the live state untouched
   and keeps the run folder for inspection; old run folders are pruned (keep the last 2).
   If a test or gate fails because a curated note names an old period (`concepts.json`, as in batches 1 and
   2), report it in the status; do not edit curated files automatically.
6. **`promote.sh <release-id>`**: the owner's approval step on the VPS. It reuses `deploy.sh`'s swap,
   health check, swap-back and "keep two releases" logic for a release that is already on the VPS, then
   uploads the static site with `deploy-static.sh` (credentials from the owner's environment), then promotes
   the run's `data/` to `pipeline/data/`. Factor shared code out of `deploy.sh` instead of copying it.
7. **Rehearsal on the Mac.** Run the whole script on an APFS clone of the served data, with a small feed
   window (`--since` a recent date) and `--matrix` for a handful of codes, plus one run where the probe
   fails (simulate). Measure peak disk and peak memory of each step. **The static build and the full test
   suite must not run at the same time** (memory).

## Facts to verify, not assume

- Whether Node is installed on the VPS (the static parity gate runs `tools/static-engine/*.mjs`). If not,
  say so: the owner decides between installing Node and running the static gate elsewhere.
- Peak memory of `build-static.py` and of the pipeline next to the running API (`MemoryMax` of the service,
  4 GB total, scrapers). If the static build cannot fit at 03:00, propose a lower-memory mode or a split.
- Whether DreamHost can be reached from the VPS with a key (HZ-5b sets this up; HZ-5a only documents it).

## Stop and ask when

- A stage writes into a file in place, so `cp -al` would corrupt the live tree, and the fix is more than
  "write temp + rename" in that stage.
- The footprint cannot stay under the 4 GB budget, or the static build does not fit in the VPS's memory.
- A change is needed in `aggregation_policy`, in the tool contract, or in what the app serves (other than
  the stale-check rule in Work 3).
- Work is needed outside the root pipeline scripts, `scripts/`, `scripts/deploy/hetzner/`,
  `app/services/dataset_meta.py` (Work 3 only), `tests/` and this plan file.

## Deliverables (HZ-5a)

Code and tests on branch `hz-5-weekly-refresh` from `main` (do not merge, push or deploy). A record
`docs/plans/hz-5-record.md`: what each stage reads and writes, the `cp -al` safety audit, the rehearsal
(commands, sizes, timings, peak memory), the install steps for HZ-5b (cron entry, venv, folders, webhook,
DreamHost key), and open questions. Full `python -m pytest tests -q` once at the end. Do not edit
`docs/BACKLOG.md`, `docs/activity-history.md`, `AGENTS.md` or `docs/CURRENT_STATE.md`: return proposed text.
