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
