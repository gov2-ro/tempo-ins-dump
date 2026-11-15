# AQ-07 record — public MCP footprint

Spec: [07-mcp-footprint.md](07-mcp-footprint.md). Branch `perf/aq-07-mcp-footprint`.

## 07A — memory budget and first-call imports

Environment: macOS, generation `062bd2b0`, repo `data/` read-only, `benchmark-mcp.py run --mode local`
with `--max-scan-rows 5000000 --setting TEMPO_DB_THREADS=1`, scenarios `cold_chain,cold_first_rank,warm,worst_case`,
3 cold repeats, 20 warm samples. One run per profile (no repetition: differences under about 15 MiB are noise).

Deviation: the harness refuses an `--out-dir` inside the repository, so reports went to the session scratch
directory, not `data/logs/aq-07/`. The reports are not kept in the repository.

### Results (peak RSS of the process tree, MiB; latency in seconds)

| Profile (search / main) | cold chain | cold first rank | warm | worst case | discover cold p50/p90 | discover miss p50/p90 | describe cache p50/p90 | rank year-miss p50/p90 | refusals |
|---|---|---|---|---|---|---|---|---|---|
| default 192 / 160 | 372-376 | 277-289 | 464 | 350 | 0.747 / 0.764 | 0.102 / 0.115 | 0.026 / 0.029 | 0.096 / 0.100 | 7 `busy` |
| 64 / 160 | 367-372 | 275-278 | 456 | 362 | 0.707 / 0.717 | 0.115 / 0.149 | 0.027 / 0.032 | 0.099 / 0.112 | 7 `busy` |
| 32 / 160 | 365-377 | 282-287 | 449 | 353 | 0.710 / 0.780 | 0.102 / 0.104 | 0.025 / 0.029 | 0.095 / 0.098 | 7 `busy` |
| 192 / 128 | 368-381 | 276-286 | 457 | 351 | 0.704 / 0.714 | 0.103 / 0.107 | 0.026 / 0.031 | 0.097 / 0.104 | 7 `busy` |
| 192 / 96 | 365-367 | 276-281 | 477 | 355 | 0.733 / 0.735 | 0.110 / 0.116 | 0.026 / 0.029 | 0.097 / 0.101 | 7 `busy` |
| 64 / 128 (chosen) | 371-377 | 276-280 | 452 | 356 | 0.742 / 0.752 | 0.103 / 0.107 | 0.026 / 0.030 | 0.098 / 0.122 | 7 `busy` |
| 32 / 96 | 367-371 | 277-290 | 478 | 355 | 0.738 / 0.756 | 0.110 / 0.114 | 0.026 / 0.029 | 0.097 / 0.100 | 7 `busy` |
| 16 / 64 (extra) | 332-349 | 284-290 | 461 | 355 | 0.737 / 0.771 | 0.116 / 0.121 | n/a | n/a | 7 `busy` |

The 7 `busy` refusals are the designed one-slot gate in the `worst.concurrent` probe (8 parallel calls, 1 served).
They appear in every profile, including the default. No profile added a refusal or an error. No check failed.

First call after a fresh start: `discover_indicators` 0.75 s, `rank_entities` as first call 0.69 s (default).
Startup to ready is 0.6 s. Child RSS after import is about 101 MiB.

### Result equality

The benchmark's raw result hashes differ between any two runs, because results carry the child's
ephemeral port in source links and a `wall_s` field. After removing `127.0.0.1:PORT`, `wall_s`, `cpu_s`,
`rss_peak_bytes`, `request_id` and `elapsed_ms`, the SHA-256 of every result is identical to the default
profile for all 7 profiles: 7 parity requests and 8 worst-case requests each. The harness's own
MCP-versus-direct parity check passed in every run.

### Pandas on the MCP path

The import is not in the app code. It happens inside DuckDB: the first `conn.execute(sql, params)` with
a parameter list makes DuckDB import pandas (with numpy and pyarrow). `select 1` without parameters does
not. First hit on the MCP path: `concept_search.dataset_facts` (`app/services/concept_search.py:207`),
reached from `discover_indicators`. Every parameterised query in the app triggers it.
Cost: 0.4 s and about 71 MiB RSS (measured in a bare process).

No change made. A removal would mean rewriting every parameterised query or patching DuckDB. That is not a
small, local change, so this is reported, as the brief requires. Option for the owner: warm the import at
MCP start-up (one parameterised query in the app build). That moves the 0.4 s from the first call to
start-up. It does not save memory.

### Budgets and decision

- The workload does not fill any budget. Peak RSS barely moves with the caps (differences are within run
  noise, about 15 MiB). Only the 16 / 64 profile showed a lower cold-chain peak (about 30 MiB).
- Chosen for `scripts/deploy/fly/mcp-public.env`: `TEMPO_SEARCH_MEMORY=64MB`, `TEMPO_DB_MEMORY=128MB`.
  They cut the ceiling (sum of caps 352 MB against 480 MB with scratch) with identical answers and no
  latency change. They are a margin for heavier queries, not a measured saving.
- Not chosen: 32 / 96 and 16 / 64. They passed too, but the workload has no heavier case, and AQ-01C
  found the main budget matters for the heaviest admitted query (3.9M rows) at higher thread counts.
- Scratch (`TEMPO_SCRATCH_MEMORY`) is opened only by `place_service`. The MCP workload does not open it.
- App defaults in `app/db.py` and `dataset_search.py` are unchanged.

### Not run, assumptions

- Linux 512 MB cgroup check: `not_run`. macOS RSS is not cgroup memory.
- The benchmark scenarios `admission`, `timeout_probe` and `mixed` were not run (not needed for the budget question).
- Each profile was run once. Latency differences under about 15% are noise.
- The hypothesis that the 512 MB machine starves the process is not confirmed or rejected here.
  Local RSS (375 MiB cold chain, 464 MiB warm run) is close to the limit, and the DuckDB caps are not the cause.
  Python and native library memory dominate. See the brief's out-of-scope list.

## 07B — period bounds without a second full scan

Branch `perf/aq-07b-period-bounds`. Code: `app/services/data_query.py` (`_value_column_has_no_nulls`, `dimension_values`).
Tests: `tests/test_aq07b_period_bounds.py`.

### Change

`dimension_values` already reads the distinct non-NULL periods. When the parquet footer proves the value column
has no NULL, it now takes `min`, `max` and the count from that list. The second full-file query runs only
when the footer shows a NULL, lacks null_count statistics, or cannot be read.

Why the result is the same: with no NULL value, the old filter `value IS NOT NULL` keeps every row. Old `min`, `max`
and `count(DISTINCT)` ignore NULL time values, and the first query also drops them. Both sides compare VARCHAR
text (Python compares code points, DuckDB compares UTF-8 bytes; the order is the same). The count comes from the
list before the `q` filter, so `q` does not change the bounds.

### Checks

- Fixture tests (8): no NULL (fast path), NULL values (current query), legacy `*_nom_id`/`value` file,
  text order unlike numeric order (VARCHAR and numeric time column), NULL time values, empty file, all-NULL value
  column, `q` filter. Each compares with the old SQL on the same file and asserts which path ran.
- Real corpus, read-only, generation `062bd2b0`: 4110 matrices with a parquet file and a time column.
  Old and new `dimension_values` output were identical for all 4110. Fast path: 4066 files. Fallback: 44 files.
  (Old behaviour was run by forcing the fallback.)

### Latency (macOS, `TEMPO_DB_THREADS` default, seconds)

`describe_dataset` through `registry.call_tool`, fresh process per run, 2 runs each:

| Dataset | before cold | before warm | after cold | after warm |
|---|---|---|---|---|
| POP107D_grupe_localitate | 0.65-0.80 | 0.14-0.16 | 0.64-0.65 | 0.12-0.16 |
| POP107D | 1.26-1.32 | 0.64-0.75 | 1.14-1.19 | 0.53-0.64 |

`dimension_values` alone (one fresh process, 1 thread):

| Dataset | before cold / warm | after cold / warm |
|---|---|---|
| POP107D_grupe_localitate | 0.46 / 0.045 | 0.36 / 0.009 |
| POP107D | 0.67 / 0.25 | 0.40 / 0.043 |

The saving is 0.1-0.2 s cold per call and about 0.2 s warm on POP107D. It is smaller than the 1.8-2.4 s in
the audit finding. On this Mac the file is in the page cache. `describe_dataset` has other costs.

### Assumptions

- `TIME_PERIOD` is the time column name used for the corpus comparison (every matrix had it).
- "Served" means every matrix in `matrices` with a file in `corpus/parquet`.
- `tools/static-engine` parity: synthetic cases pass; 2 real-corpus parity tests are `not_run` (no `data/` in the worktree).

## Correction (Opus review, 2026-11-15)

07A measured in the development venv, which has pandas, numpy and pyarrow. Production does not:
they are not in `requirements.txt`, and none of its 50 resolved dependencies pulls them in. DuckDB
imports pandas on the first parameterised query only when pandas is installed. So the 0.4 s
first-call import and about 71 MiB of the measured RSS do not occur in the production image or the
Hetzner venv. A realistic production peak is about 300-390 MiB, still too tight for 512 MB.
Do not add a start-up warm-up for pandas. Measure the real peak on Linux in HZ-3.
07B real-corpus parity (`tests/test_static_parity.py` with `data/`) passed in the main checkout
after the merge: 18 passed together with `test_aq07b_period_bounds.py`.
