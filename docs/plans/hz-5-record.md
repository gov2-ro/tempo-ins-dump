# HZ-5a record — weekly refresh on the VPS, minimal footprint

Date: 2026-11-25. Brief: [hz-5-weekly-refresh.md](hz-5-weekly-refresh.md). Branch `hz-5-weekly-refresh`.
Status: code, tests and a Mac rehearsal are done. **Nothing ran on the VPS.** HZ-5b installs it.

## What was built

| File | Job |
|---|---|
| `update-pipeline.py` | `--drop-csv` (delete each CSV after stage 9), `--probe-only` (exit 0/1), temp + rename for its own writes |
| `scripts/cleanup-retired-children.py` | removes the leftovers of a retired split child (Work 2) |
| `app/services/dataset_meta.py`, `insights.py` | the stale INS check rule (Work 3) |
| `scripts/compact-metadata.py` | verified rewrite of `metadata.duckdb` (Work 4) |
| `scripts/refresh-run.py` | the one entry point for cron (Work 5) |
| `scripts/deploy/hetzner/promote.sh`, `lib.sh` | the owner's approval step; `deploy.sh` shares `lib.sh` (Work 6) |
| `scripts/audit-corpus.py` | `TEMPO_AUDIT_MEMORY` caps its DuckDB (see Memory) |
| `tests/test_hz5_refresh.py` | tests for all of the above |

## 1. Readers of `data/4-datasets` (raw CSV)

| Reader | Reads the CSV? | Effect of `--drop-csv` |
|---|---|---|
| `9-csv-to-parquet.py` (`CSV_SOURCE_DIR`) | yes, the only real reader | the CSV is deleted right after stage 9 succeeds |
| `10-import-metadata.py` `file_stats` | only when no parquet exists (row count from the CSV) | none: the first import runs before stage 9 and may use the CSV of a NEW matrix; the stats refresh after stage 9 uses the parquet |
| `duckdb_config.validate_config` | counts files; not called by the pipeline | none |
| `6-fetch-csv.py` | writes it (`.part` + rename); judet chunks go to `4-datasets/judet-localitate`, removed on success | none |
| `12-split-datasets.py`, 13, profilers, `generate_view_profiles.py`, search index | no: parquet only | none |
| `scripts/repair-corpus.py`, `tools/tempo-dev-mcp` (stat only), `duckdb-browser.py`, `7-data-compactor.py`, `10-sdmx-export.py`, `scripts/utils/*` | yes or stat, but none is on the weekly path | none |

`--drop-csv` (orchestrator option, default off) deletes `4-datasets/<lang>/<code>.csv` right after stage 9 succeeds
for that matrix. A matrix that fails before or in stage 9 keeps its CSV (for inspection); the run script removes
the whole `4-datasets` folder of the run at the end of a feed run. `matrices.file_size_bytes` is the **parquet** size
(`file_stats`), not the CSV size, so it stays meaningful and needs no change. Tests: stage order with the flag, CSV
kept without it and on a stage 9 failure.

## 2. `cp -al` safety audit

A run does not hard-link the whole tree. `refresh-run.py` copies every small file (DuckDB files, metas, indexes,
view profiles, published totals: about 0.5 GB) and **hard-links only `corpus/parquet/*.parquet`**
(about 0.27 GB, the part worth sharing). A stage that writes a copied file in place is therefore harmless; the
audit below matters for the parquet files and, as defence in depth, for everything else.

| Stage / script | What it writes | Replace or in place | Action |
|---|---|---|---|
| `9-csv-to-parquet.py` | `corpus/parquet/<code>.parquet` | temp `.parquet.tmp` + `os.replace` | none needed |
| `12-split-datasets.py` | child parquets | staged in a dir, then `os.replace`; old files `unlink` (removes a link, not the inode) | none needed |
| `10-import-metadata`, `10-classify-dimensions`, `11-build-sdmx-codes`, `13-dimension-structure`, `11-coverage-profiler`, `detect_trends`, `profile-values`, `load-published-totals`, `check-kpi-totals --write-db` | DuckDB tables | DB file (always copied) | none |
| `build-search-index.py` | `search.duckdb` | `unlink` then create | none (copied anyway) |
| `6-fetch-csv.py` | CSV, logs | CSV: `.part` + rename. Logs: **append in place** | logs are not linked: a run copies only the two state files of `logs/` |
| `update-pipeline.py` | `2-metas/<code>.json`, `insse_news.csv`, `last-pipeline-run.txt` | **in place** (`write_text`, `to_csv`) | fixed: temp + rename |
| `4-build-meta-index.py` | `1-indexes/<lang>/matrices-list.csv` | **in place** | fixed: temp + rename |
| `generate_view_profiles.py` | `view-profiles/<code>.json`, `_index.json` | **in place** | fixed: temp + rename |
| `scripts/fetch-ins-reference-cells.py` | `published-totals/*.csv`, `manifest.json` | **in place** | fixed: temp + rename |
| `1-fetch-context.py`, `2-fetch-matrices.py` | `1-indexes/<lang>/context.*`, `matrices.csv` | in place | not on the weekly path (`--fetch-context` only); copied, not linked, so safe; not changed |
| `scripts/cleanup-retired-children.py` | DB, deletes view profiles, `_index.json` | DB copied; `unlink`; `_index.json` temp + rename | none |
| `scripts/build-generation-manifest.py` | writes `--out` | the run script writes outside `corpus/` and `os.replace`s it in | none |
| `prepare-deploy-data.sh` | `cp` into a new folder | new files | none |

Proof on every run: before the run `refresh-run.py` records inode, size and mtime of every file of the working
`data/` (without `logs/`); after the run it compares. A change fails the run (`live_tree_changed` in `status.json`).
Tests: a replace by rename leaves the working file untouched; an append through a link is caught; `fetch_meta` keeps
a hard-linked copy's old content.

Stage 12 reads `parquet-v2/` only when the v3 parent file is missing (`12-split-datasets.py` line 421-424). A
refreshed matrix always has its parent in `corpus/parquet` (stage 9 just wrote it), so the VPS needs no `parquet-v2/`.
The rehearsal ran without it.

## 3. Retired split children

Stage 12 deletes a retired child's rows in `dataset_splits`, `dimension_options`, `dimensions` and `matrices` and its
parquet. It leaves the rows in every profile table, the view profile and the `_index.json` entry.

`scripts/cleanup-retired-children.py --data-dir RUN/data` removes them. Rule: a code is live when `matrices` has it.
It finds the tables in `information_schema` (every base table with `matrix_code`, `sub_matrix_code`,
`parent_matrix_code` (in `dataset_splits`), `matrix_a` or `matrix_b`) and deletes the rows that name a non-live code.
It also deletes the view profile files and `_index.json` entries of non-live codes, and **reports** (does not delete)
parquet files of non-live codes. It refuses the repository's own `data/`.

Tables found on the served generation `9c3e8eaa`: `dataset_coverage`, `dataset_relationships`, `dataset_splits`,
`dataset_tags`, `dataset_trends`, `dataset_value_profiles`, `dimension_structure`, `kpi_dimension_checks`,
`kpi_total_checks`, `matrix_profiles`, `published_totals`, `sdmx_column_map`, `unmapped_labels`.
**The served generation still has 18 retired codes with 90 rows in `sdmx_column_map`** (BUF110I, BUF110J, BUF112I,
BUF112J, BUF113I, BUF113J children). The rehearsal's cleanup removed them; the next promoted run fixes the served
data. Tests: every table, files, index, live children and live relationships stay, dry run writes nothing, orphan
parquet is only reported.

## 4. Stale INS checks

`dataset_meta.source_total_gate(conn, code, decision, latest_period=None)`: a `kpi_total_checks` row with status
`match` whose `period` is older than `latest_period` is treated as if INS had not been asked. The KPI is then
withheld as `source_total_unchecked` when a summed dimension has weak verification (`profile_flat`, `metadata`,
`label`, `unverified`), and stands when all are `verified`/`curated` (the existing "no check" behaviour).
`insights.compute_insights` passes the period of the KPI it computed (`period_totals[-1]`), so a check of 2023
cannot vouch for a 2025 number. The other statuses are unchanged: a stale `mismatch` still withholds (never
published on an older check's authority), `unresolved`/`ins_blank` keep their reasons.

**Deviation from the brief's file list (owner to confirm):** the rule needs the KPI's period, which only `insights.py`
knows, so `insights.py` changes by one argument. The callers that pass no period (`/data` headline in
`data_query.py`, `dashboard_composer.py`, `tools/query.py`) behave as before. I did not extend the rule to them: it
needs the static engine's `policy.js` (`sourceTotalGate`) and `build-static.py`'s policy to carry the latest period,
which the brief puts out of scope, and a guess from the parquet maximum would withhold forever a dataset whose pinned
slice never reaches the newest period. The cost: the dataset page's KPI is withheld, the `/data` headline series is
not. Open question 1.

Tests: older/equal/`Anul`-prefixed periods, verified sums, no period passed, stale mismatch and `no_source_total`
unchanged, and the real `/insights` endpoint on a fixture corpus (check period 2025 publishes, 2024 withholds).
Effect on the served corpus: see "Rehearsal results".

## 5. DB compaction

`scripts/compact-metadata.py SRC DST [--json-out F]`:
1. `COPY FROM DATABASE src TO dst (SCHEMA)`: tables, constraints, indexes, views, sequences.
2. Rows with `INSERT INTO dst SELECT * FROM src`, tables in foreign-key order (derived from `duckdb_constraints()`:
   `contexts`, `matrices`, `dimensions`, `dimension_options`, then the rest). A plain `COPY FROM DATABASE` fails on the
   alphabetical order.
3. Verification, reading both files again: the same tables, views, constraints, indexes, sequence values, columns and
   types; per table the same row count and the same order-independent content hash
   (`SUM(hash(row)::HUGEINT)`). A difference deletes DST and exits 1.
4. It refuses an existing DST, SRC = DST, and a DST inside the repository's `data/`. It never writes SRC.

DuckDB 1.4.2 has no `setval`; the sequences came across unchanged (`seq_dimension_id`, `seq_option_id`; nothing calls
`nextval`, `10-import-metadata.py` allocates MAX+1), and the check compares them. A test caught a real bug while I
wrote it: a table alias `x` in the hash query hid a column called `x`; the alias is now `__row`.
Tests: synthetic bloated DB with the same FK shape, indexes, a view, a sequence and non-ASCII text (smaller output,
FK still enforced, order), a forced difference (DST removed), the hash catches a changed value, refusals.

## 6. The run script and `promote.sh`

### `scripts/refresh-run.py` (cron, as `pax`)

Every step logs to `runs/<id>/logs/NN-<step>.log`; `status.json` records rc, seconds and peak resident memory per step.

| # | Step | Required | What it does | Touches |
|---|---|---|---|---|
| 0 | schedule, lock | | due on Sunday, or on a later day while a due run is pending; gives up after 7 days. `run.lock` allows one run | `status.json` |
| 1 | `probe` | stops the run (not a failure) | `update-pipeline.py --probe-only` (POP107A, one cell). Failure: `pending_since`, notify on day 1 and day 7 only | `status.json` |
| 2 | `space`, `copy` | yes | at least 5 GB free; copy of `pipeline/data` (parquet hard-linked); snapshot of the working data | `runs/<id>/data` |
| 3 | `feed` | exit 0 or 1 | `update-pipeline.py --refetch-news --global-profiles --drop-csv [--since D \| --matrix A,B]` | run data only |
| 4 | `sweep`, `sweep-refresh` | yes, when due | every 28 days: `meta-sweep.py`, then `update-pipeline.py --matrix <updated or new codes>` | run data |
| 5 | `cleanup-retired` | yes | retired-children cleanup | run DB, view profiles |
| 6 | `kpi-collect`, `kpi-check`, `kpi-dims` | collect: yes; check, dims: no | INS check of the touched parents and their children; `kpi_dimension_checks` rows of touched codes are dropped first, `dims` rebuilds those that still disagree | run DB |
| 7 | `compact` | yes | compaction and verification; the compact file replaces the run's DB | run DB |
| 8 | `manifest` | yes | `build-generation-manifest.py` (written outside `corpus/`, then renamed into it) | run corpus |
| 9 | `audit` | no | `audit-corpus.py` report | `audit.json` |
| 10 | `stage` | yes | `prepare-deploy-data.sh` with `TEMPO_CORPUS_SRC`/`TEMPO_DEPLOY_OUT`, plus the code folder | `runs/<id>/release/` |
| 11 | `release-check-local` | yes | strict: `--require-clean-audit --accept-restriction conflicting_grain`, own port 8095/8096, default and MCP smoke | none |
| 12 | `static-build`, `api-cases`, `release-check-static` | yes | full static build, API parity cases, the static gate (node parity) | `runs/<id>/static/` |
| 13 | live-tree guard | yes | the working data must be unchanged | none |
| 14 | status, notification | | outcome `candidate` or `candidate_with_failures`; prune to the last 2 runs | `status.json` |

Failure handling: a failed required step (or an unreadable gate) stops the run, sets `pending_since` (daily retry),
keeps the run folder (the 2 newest are kept), writes `status.json` (`failed_step`, `failed_tail`) and notifies. The
served release, `pipeline/data` and DreamHost are never touched by any step. Matrices that fail inside the feed stay in
the retry set of the run's state file and the run still produces a candidate (`candidate_with_failures`, listed in the
notification): the owner decides. A gate failure that mentions `concepts` adds a note to the status and nothing is
edited. `TEMPO_NOTIFY_URL` receives a plain-text POST (header `Title: TEMPO refresh`); a failed POST is ignored.
`--dry-run` stops before any copy.

### `scripts/deploy/hetzner/promote.sh [--apply] [--base DIR] [--no-static | --static-only] <run-id>`

Dry run by default. Steps with `--apply`: check the run (outcome `candidate*`, staged candidate present, built on the
generation that `pipeline/data` has now, no run holding `run.lock`); build `releases/<run-id>-<gen8>` with
`rsync --link-dest` against `current` (code and data); `lib.sh`: venv, requirements, fts, refuse pandas/numpy/pyarrow,
smoke on 8095/8096 (`current` unchanged until it passes); swap `current`, restart, health check, swap back on
failure; promote the run's data (`pipeline/data` -> `data.prev`, `runs/<id>/data` -> `pipeline/data`, remove
`runs/<id>/release`); keep two releases; `deploy-static.sh --go` (credentials from the owner's environment:
`.env` in the code folder with `STATIC_SSH`, `STATIC_ROOT`). **Order differs from the brief:** the data promotion comes
before the static upload. After the API swap the API already serves the new generation; a failed upload then must not
leave `pipeline/data` behind it. A failed upload exits 1 and prints the retry command (`--static-only`).
`deploy.sh` now sources the same `lib.sh` (a refactor of its steps 4-7; its dry-run path is unchanged).

## 7. Install on the VPS (HZ-5b, owner present)

**Check first (read-only), and write the answers here before installing:**
```
node --version                                   # the static parity gate needs Node (api-parity.mjs runs with --max-old-space-size=6000)
python3 --version; python3 -m venv --help >/dev/null && echo venv-ok; rsync --version | head -1
free -m; swapon --show; df -h /opt/tempo /tmp
systemctl show tempo-api -p MemoryMax -p MemoryHigh
cat /sys/fs/cgroup/system.slice/tempo-api.service/memory.peak     # the API's own peak
ps -eo rss,comm --sort=-rss | head                                # what the scrapers hold at 03:00
ssh -o BatchMode=yes "$STATIC_SSH" 'echo reachable'               # DreamHost key (below)
```
If Node is missing, the static gate cannot run the API parity cases: `refresh-run.py` then marks the status
`api_parity: SKIPPED` and never reports a full pass. The owner decides between installing Node and running that gate
on the Mac before `promote.sh`.

**Install:**
1. Folders, owner `pax`: `/opt/tempo/pipeline/{venv,code,data,runs}`.
2. Venv: `python3 -m venv /opt/tempo/pipeline/venv && /opt/tempo/pipeline/venv/bin/pip install -r requirements-pipeline.txt`
   (it includes `requirements.txt`; fastapi, duckdb and the app are needed by the release smoke and by `check-kpi-totals.py`).
   The API release venvs stay separate and free of pandas, numpy and pyarrow (`deploy.sh` and `promote.sh` check).
3. Code: a checkout of `main` in `/opt/tempo/pipeline/code`, at the commit to release (the candidate release's `app/`
   is copied from it; `git pull` between runs, never during one). Put `.env` there with `STATIC_SSH` and `STATIC_ROOT`
   (see `.env.example`; gitignored).
4. Seed `/opt/tempo/pipeline/data` from the served generation (Mac -> VPS, rsync): `corpus/` (`metadata.duckdb`,
   `search.duckdb`, `generation-manifest.json`, `parquet/`, `view-profiles/`), `2-metas/ro/`, `1-indexes/ro/`,
   `published-totals/`, `insse_news.csv`, `logs/update-pipeline-state.json`, `logs/last-pipeline-run.txt`, and `meta/`
   (small; I did not prove it is unneeded). Not needed: `4-datasets*`, `parquet-v2`, `eval`, `quarantine`, `_archive`.
   Check the seed once: `python scripts/refresh-run.py --base /opt/tempo/pipeline --dry-run`, then a rehearsal with
   `--force --matrix <3 small codes> --static-codes <their codes>` and `promote.sh` WITHOUT `--apply`.
5. The webhook: `export TEMPO_NOTIFY_URL=https://ntfy.sh/<private-topic>` (or a Slack webhook) in the cron environment.
6. DreamHost key: a key pair for `pax` on the VPS, its public key in DreamHost's authorized keys for the static
   user; test `ssh -o BatchMode=yes "$STATIC_SSH" true`. `deploy-static.sh` needs `rsync` and `ssh` there.
7. Cron (`crontab -e` as `pax`; daily 03:00, the script decides whether a run is due):
   ```
   0 3 * * * cd /opt/tempo/pipeline/code && TEMPO_NOTIFY_URL=... /opt/tempo/pipeline/venv/bin/python scripts/refresh-run.py --base /opt/tempo/pipeline --python /opt/tempo/pipeline/venv/bin/python >> /var/log/tempo/refresh-run.log 2>&1
   ```
   Make `/var/log/tempo/refresh-run.log` writable by `pax` and add it to `tempo-logrotate`.
8. Sudo: `promote.sh` already needs the `systemctl restart tempo-api` rule from `deploy.sh`'s setup.
9. Memory: if the static build or the parity gate does not fit next to the API and the scrapers, run the cron entry
   after the scrapers or stop `tempo-api`'s neighbours; see "Memory" below for the numbers.

## 8. Rehearsal results (Mac, APFS clone of generation `9c3e8eaa`)

Setup: the served `data/` cloned with `cp -c -R` (without `_archive`, `4-datasets*`) into `~/devbox/gov2/tempo-gen-hz5/data`;
`refresh-run.py --base ~/devbox/gov2/tempo-gen-hz5`. The clone had no `4-datasets` and the run copy left out
`parquet-v2`, `eval` and `quarantine`, as on the VPS. INS answered every time. Nothing in the main checkout was written.
Promotion ran in a sandbox (`--base` a temp folder with a fake restart command, port 18080); the working data of the
clone was promoted there, never the served one.

| Run | Command (after `--base ... --python ... --force --sweep no`) | Result |
|---|---|---|
| 1 | `--matrix EXP101A,FOM114A,AGR210A --static-codes <5 codes>` | stopped at the static gate: the API parity cases name datasets that are not in a subset build. Fixed: with `--static-codes` the cases are skipped and the status says so |
| 2 | same, full static build | stopped at `release-check-local`: the memory cap below made the audit mark 4 big files `invalid` (out of memory). The gate worked as meant. Fixed by the bucketed grain check |
| 3 | `--matrix EXP101A,FOM114A,AGR210A` (**full static build, full API parity**) | **candidate**, 27 min |
| 4 | `--matrix EXP103A,ZZZ9999 --static-codes <3>` (`ZZZ9999` does not exist: a failed matrix) | **candidate_with_failures**; exposed the `--write-db` bug (fixed) |
| 5 | `--matrix EXP103B,FOM103H --static-codes <2>` after all fixes | **candidate**, about 6 min |
| probe | `--simulate-probe-failure`, twice | `probe_failed`, notified on day 1 only, run folder removed, working data untouched |

### Run 3, per step (the full run)

| Step | Seconds | Peak resident memory (largest process of the step) |
|---|---|---|
| probe | 0.7 | 135 MB |
| copy | 3.7 | |
| feed (3 matrices, global profiles, search index) | 62 | 691 MB |
| cleanup-retired | 0.6 | 178 MB |
| kpi-collect / kpi-check | 0.6 / 1.4 | 218 / 181 MB |
| compact | 2.7 | 418 MB |
| manifest (audit with grain check, hashes) | 99 | 1,439 MB (**8,105 MB** before the cap and the buckets) |
| audit report | 95 | 1,501 MB (8,284 MB before) |
| stage (`prepare-deploy-data.sh`) | 6.4 | 198 MB |
| release-check-local (default + MCP smoke) | 5.5 | 308 MB |
| **static-build (full, 3,333 datasets)** | **1,069** | **1,511 MB** |
| api-cases (`gen-api-cases.py`) | 253 | **4,379 MB** with POP107D; **930 MB** without it (measured apart; now the default) |
| release-check-static (node parity, 537 cases) | 18 | 2,203 MB |
| total | 1,620 | |

Run 5 (small, after the fixes): feed 64 s / 702 MB, manifest 102 s / 1,265 MB, audit 102 s / 1,435 MB.

### Footprint

- Files of a full run folder: data copy 545 MB + staged release 461 MB + static site 609 MB = 1.55 GB.
- Steady state on the sandbox after three promotions: working `data/` 545 MB, `data.prev` 273 MB unique (parquet is shared),
  two releases about 0.6 GB each (the second shares files with the first once the staged mtimes are preserved, see below).
  Estimate on the VPS: 2.0 GB at rest, 3.6 GB during a run. **Under the 4 GB budget.**
- `peak_used_gb` in `status.json` is the lowest free space seen (sampled every 2 s) minus the start: 0.7 GB for the small runs.
  Run 3 shows 7.2 GB because the 4.4 GB `api-cases` process made macOS swap; it is not file footprint.
- Raw CSVs: never more than one matrix's CSV at a time; the rehearsal runs left no `4-datasets` behind.

### Status and notification samples

Success (`status.json`, run 3, trimmed; the steps are in the table above):

    {"outcome": "candidate", "run_id": "rehearsal3", "generation": "c45dc4df...", "seconds": 1620,
     "feed": {"exit_code": 0, "processed": 3, "failed": [], "empty": [], "optional_failed": [], "retry_set": [],
              "watermark": "20.11.2026", "stale": {}},
     "touched": {"count": 6, "codes": ["AGR210A", "EXP101A", "..."]}, "cleanup": {"codes": 18, "tables": 1},
     "kpi_checks": {"match": 1}, "db_bytes_before": 140783616, "db_bytes_after": 120074240,
     "live_tree_changed": [], "api_parity": "run", "notes": [],
     "disk": {"free_before_gb": 38.66, "peak_used_gb": 7.23, "run_dir_bytes": 1548587826},
     "pending_since": null, "last_success": "2026-11-25",
     "promote": "bash scripts/deploy/hetzner/promote.sh --apply rehearsal3"}

Notifications (a local webhook that logged the POST):

    candidate:               TEMPO refresh rehearsal3: candidate. Generation c45dc4df, 6 datasets touched, 0 failed (), retry set 0. DB 141 -> 120 MB. Gates passed. Approve: bash scripts/deploy/hetzner/promote.sh --apply rehearsal3
    candidate with failures: TEMPO refresh rehearsal4: candidate_with_failures. Generation 17955ee6, 3 datasets touched, 1 failed (ZZZ9999), retry set 1. DB 140 -> 120 MB. Gates passed. Approve: bash scripts/deploy/hetzner/promote.sh --apply rehearsal4
    gate failed:             TEMPO refresh rehearsal1 FAILED: step release-check-static failed (rc 1), log .../13-release-check-static.log. Run folder kept: .../runs/rehearsal1. The served release is untouched.
    INS down (day 1):        TEMPO refresh: INS does not answer a data query (day 1 of 7). Retrying daily.

### What the rehearsal showed

1. **The corpus the VPS would start from has 18 retired split children** (BUF110I ... BUF113J_*, 90 `sdmx_column_map`
   rows); the first cleanup removed them. The cleanup count of run 3 is that.
2. **`--write-db` of `check-kpi-totals.py` crashed on an empty result** and left the old rows of datasets that no
   longer sum a dimension. Fixed, tested.
3. **The audit used 8 GB** (one 22M-row dataset, POP107D, grouped in one pass). A memory cap alone made it fail (OOM,
   reported as `invalid`, which the strict gate caught). The grain check now runs in hash buckets
   (`TEMPO_AUDIT_GRAIN_BUCKET_ROWS`, same sums, tested): 1.4-1.5 GB with `TEMPO_AUDIT_MEMORY=512MB`, one thread.
4. **`gen-api-cases.py` needed 4.9 GB** because its default list includes an unfiltered CSV download of POP107D held in the
   test client. The run script passes `--codes` without it (0.9 GB). The static parity then covers `/options` and
   `/download` for six datasets, not seven.
5. **`rsync --link-dest` linked nothing**: `prepare-deploy-data.sh` used `cp`, so every staged file had a new mtime.
   It uses `cp -p` now. The sandbox's first two releases pre-date the fix; proven with `cp -pR` + `rsync --link-dest`
   (same inode). Not re-proven end to end: the third promotion compared against a release made before the fix.
6. A `promote.sh` that fails before the swap leaves its release folder; a retry now reuses it. The service inherited the
   `run.lock` file descriptor in the sandbox; `lib.sh` closes it for the restart command.
7. Swap-back: with a release that does not start, `promote.sh` swapped back to the previous release, the health check
   passed, the exit code was 1, and the run's data stayed unpromoted. A second promote on the same candidate succeeded.

### Effect of the stale-check rule on the served generation

Measured with `insights.compute_insights` on the clone of `9c3e8eaa`, old gate against new gate, for all 906
datasets with a `match` row in `kpi_total_checks`:
**541 datasets would lose their headline KPI** (withheld as `source_total_unchecked`), 361 keep it, 4 had none already.
Examples: `ACC101B_judete`, `AGR206A_judete_mii_lei_ron`, `AGR210A`, `AGR301A_judete`. Their checks name an older
period than the KPI shows. A weekly run re-checks only the datasets it touched. **Do not deploy the rule before a
full re-check** (one-off, about 900 INS cells, throttled 0.7 s each; the cache is reusable): run
`check-kpi-totals.py collect` and `check ... --write-db` on a copy of the DB (commands in the script's docstring), then
compact, manifest and stage as in the run.

## 9. Memory on the VPS (4 GB shared with the API at `MemoryMax=1G` and the scrapers)

| Step | Peak on the Mac | Fits next to the API (1 GB) and a scraper? |
|---|---|---|
| feed | 0.7 GB (about 1.5 GB for a large matrix, not measured) | yes |
| manifest, audit | 1.4-1.5 GB | yes if the scrapers are not at their peak: **check on the VPS** |
| static-build | 1.5 GB | tight; run it after the scrapers |
| api-cases | 0.9 GB (4.4 GB with POP107D) | yes without POP107D |
| node parity gate | 2.2 GB | **no with API + scraper: verify**; options below |

These are macOS resident sizes; nothing was measured on Linux. If the node gate does not fit: (a) run only that step
on the Mac (`release-check.py --static <copied static dir> --api-cases ...`) before `promote.sh`; (b) lower
`--max-old-space-size` in `release-check.py` (6000 now) after measuring; (c) add 2 GB swap during the run.
The cron time can also move after the scrapers. `refresh-run.py` runs the steps one after another, never in parallel.

## 10. Not done, not verified, assumed

- **Nothing ran on the VPS.** Linux, Node, DreamHost, the real `systemctl restart`, the Python 3.12 venv build and memory
  next to the API are unverified (commands in section 7).
- **The monthly sweep** (`--sweep yes`, `sweep-refresh`) was not run (it fetches all 4,100 metas: about 90 minutes).
  Its parts are tested (`sweep_codes`). A code that INS added (`new_in_ins`) goes through `update-pipeline.py --matrix`
  without `--fetch-context`: untested whether a new matrix gets its context row. Run one sweep run on the Mac before
  enabling it on the VPS.
- `deploy-static.sh --go` was not run (no DreamHost access); its dry run was. The `--static-only` retry was not run.
- The full static build ran once (run 3, before the `--codes` change for api-cases). Later runs used `--static-codes`.
- `meta/`, `misc/` and `sdmx-dashboards/` were in the run copies; I did not prove the run needs them.
- `deploy.sh` was refactored onto `lib.sh` and checked with `bash -n` and a read-through; it was not run against a host.

## 11. Tests

`python -m pytest tests -q` on the branch, once, with nothing else running: **2582 passed, 146 skipped** (15 min).
`tests/test_hz5_refresh.py`: 33 test functions (stale rule, cleanup, compaction, the orchestrator flags, atomic writes, schedule,
run copy, live-tree guard, notification, probe failure, bucketed audit, `--write-db`, sweep and touched-code helpers).

## 12. Open questions for the owner

1. **Stale rule scope.** The rule needs one line in `insights.py` (outside the brief's file list) and covers the dataset
   page KPI only. `/data` headline, composer tiles and `tools/query` still accept an old `match`. Covering them needs the
   static engine (`policy.js`, `build-static.py`) to carry the latest period. Decide: leave as is, or open a package.
2. **541 KPIs.** The rule withholds the headline KPI of 541 served datasets today (section 8). Run a full re-check
   before deploying it, or accept the gap until the weekly runs cover them.
3. **Candidate with failures.** A run with failed matrices still makes a candidate (listed in the notification). Should
   `promote.sh` refuse those without `--accept-failures`?
4. **Order in `promote.sh`.** Data promotion before the static upload (section 6). Confirm.
5. **Node on the VPS and the 2.2 GB parity gate** (section 9): install Node there, or run that gate on the Mac?
6. **`parquet` in `data.prev`.** The previous working data stays after each promotion (273 MB unique). Keep, or delete
   after the next successful run?
7. **Curated notes.** A gate that fails on a note naming an old period is reported only (status note), as the brief says.
   Nothing yet detects it before the gate; a pre-check of `concepts.json` periods could.
8. The chart-selector baseline `data/eval/chart_selector_baseline.json` still names retired children (backlog P3);
   the cleanup does not touch it.
