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
