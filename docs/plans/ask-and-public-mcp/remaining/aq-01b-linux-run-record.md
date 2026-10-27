# AQ-01B partial record: first Linux 512 MiB runs, and the image gate

**Status (2026-10-27): measurements only. 01B is not complete, and no limit, default or
production setting was changed.** These runs replace `not_run` for the image gate and give
the first cgroup-limited numbers. They do not cover the worst admitted request of every
scan-gated tool, which 01B requires. Branch `aq/01b-container-run`; not pushed, not merged,
not deployed.

## Result in one paragraph

The candidate image builds, starts and passes the full `release-check.py --docker` smoke,
after one release-blocking fix (the image was missing `sdmx_labels.py`). Under the AT-04
mixed load (180 s with one MCP client, then 300 s with five, two REST clients throughout),
a 512 MiB / 1 CPU container never ran out of memory or restarted. It returned no unexpected
4xx or 5xx, and the MCP slot freed itself after each phase. Peak container memory was
**73 % of the limit on arm64 and 76–77 % on amd64**, which is Fly's architecture. The proposed
75 % headroom threshold is therefore **not met on amd64**. Moving the scan cap from the default 1M
rows to 5M rows (which lets `POP107D` city rankings through) did not change the peak
beyond run-to-run noise. Neither did smaller DuckDB budgets. The memory comes from the REST and
search load and the Python heap, not from the MCP scan cap.

## Host and identity

| What | Value |
|---|---|
| Container runtime | Colima 0.10.3 (`--vm-type vz --vz-rosetta`, 4 CPU / 6 GiB VM), Docker 29.5.2, Ubuntu 24.04 kernel 6.8.0, cgroup v2 |
| Limit per container | `--memory 512m --memory-swap 512m --cpus 1 --restart no` (harness `--mode container`) |
| Images | arm64 `sha256:98e830537626…` (native) and amd64 `sha256:01db1332d12b…` (Rosetta); both built from `f88924c` with the 06B stage baked in (`--container-data image`) |
| Generation | `9b3e065d2fe9bb1df9bae2131b7bdeae9be3426f3c82b9a9954f7e6dc8f45550` (the 06B stage, cloned into the worktree's `deploy-data/`) |
| Harness | `scripts/benchmark-mcp.py` at `4f5c138` (the first `candidate`/`control` runs) and `64d75da` (the `mixed-*` runs), clean tree |
| Reports | `/Users/pax/devbox/gov2/tempo-rc-06b/aq01b/<run>/report.json` (outside the repository) |

The amd64 runs are emulated, so **their latencies are not valid**. Only their memory figures count.
`--cpus 1` is a full core. Fly's `shared-cpu-1x` is a shared, throttled CPU, so under sustained
load real latencies will be worse than every figure below.

## Image gate

`release-check.py --source …/corpus --require-clean-audit --accept-restriction conflicting_grain --docker`:

- **First run: blocked.** "container did not become healthy". The image exited at import with
  `ModuleNotFoundError: No module named 'sdmx_labels'`. Since FIX-01 phase 2,
  `app/services/sdmx_registry.py` has imported that root-level module, but the Dockerfile copies
  only `app/`. `main` does not have the import, so the live site is not affected. `--local`
  runs from the checkout and could not see the problem. Fixed in `f88924c`: `COPY sdmx_labels.py .`,
  plus a test that every root-level module the app imports is copied and not dockerignored.
  The test fails on the old Dockerfile.
- **Second run: `RELEASE CHECK PASSED`** (stage checks plus the Docker smoke; `--skip-tests`).
  The first run had already passed pytest on the same code: 2079 passed, 89 skipped. The fix
  adds only the Dockerfile line and tests.
  - The image passes `LOAD fts` offline, serves the staged generation, and answers 404 on `/mcp`
    while it is disabled. Ask is off.
  - With the MCP on: 8 tools through the official SDK client, and the tourism and net-earnings
    recipes are served. `registered_unemployment_county` is refused with `query_budget` (P1, a
    warning).
  - Evidence links point the page at the site and the API at the API origin. The evidence
    bundle returns 200 at the cited generation and 409 at another, with `generation_changed`.
  - CORS allows the listed origin, refuses any other, and never applies to `/mcp`.

## Memory under the mixed load

Peak = cgroup `memory.peak` over the container's life. Heap = the highest sampled `anon` from
`memory.stat` (every 0.1 s, page cache excluded). Limit 536,870,912 bytes; 75 % = 402,653,184.

| Run | Arch | Profile | Peak | % of limit | Heap (sampled) | Checks |
|---|---|---|---:|---:|---:|---|
| mixed-candidate | arm64 | scan cap 5M | 393.3 MB | 73.3 % | 387.2 MB | all pass |
| mixed-control | arm64 | defaults (1M) | 394.2 MB | 73.4 % | 388.4 MB | all pass |
| control (full run, first) | arm64 | defaults | 401.9 MB | 74.9 % | not sampled | `mixed_load` failed: harness probe bug, fixed |
| mixed-candidate-amd64 | amd64 | scan cap 5M | **413.2 MB** | **77.0 %** | 407.0 MB | all pass |
| mixed-control-amd64 | amd64 | defaults | **406.7 MB** | **75.8 %** | 399.6 MB | all pass |
| mixed-candidate-amd64-db200 | amd64 | 5M, `TEMPO_DB_MEMORY=200MB`, `TEMPO_SEARCH_MEMORY=96MB` | **405.2 MB** | **75.5 %** | 398.8 MB | all pass |

- Nearly all of the peak is heap: page cache is only 5–7 MB. The 75 % line is not an artefact
  of reclaimable cache.
- The peak rises from the one-client phase to the five-client phase on every run, by 26–36 MB
  (for example 378 → 404 MB on db200, 386 → 405 MB on amd64 control). These runs cannot tell
  growth that would level off from growth that would continue. That needs a longer soak.
- Each configuration ran once. On arm64 the two control runs differ by 8 MB, so differences
  smaller than about 10 MB are noise.

## Latency (arm64, native; `--cpus 1`)

Candidate profile (scan cap 5M), served answers, nearest-rank, from `candidate/report.json`
and `mixed-candidate/report.json`. AT-04 targets: warm p95 under 2 s for metadata and under
5 s for analytical calls. Both are met.

| State | Case | p50 s | p95 s | n |
|---|---|---:|---:|---:|
| cold | container start to `/api/health` 200 | 0.758 | 0.910 | 5 |
| cold | `discover_indicators` | 0.703 | 0.797 | 5 |
| cold | rank as the first analytical call | 0.443 | 0.559 | 5 |
| cache | same rank | 0.020 | 0.025 | 20 |
| miss_warm | rank, other years / county filter | 0.106 / 0.072 | 0.125 / 0.117 | 20 / 20 |
| miss_warm | `discover_indicators` | 0.261 | 0.342 | 20 |
| mixed, 1 MCP client | rank miss / REST detail / REST search | 0.351 / 0.589 / 0.295 | 0.577 / 0.798 / 0.460 | 384 / 298 / 348 |
| mixed, 5 MCP clients | rank miss (1,317 served, 1,732 `busy`) / REST detail | 0.251 / 0.598 | 0.567 / 0.869 | |

`busy` refusals under five clients are the designed one-slot gate. Cache hits bypass the gate.
The other checks pass: K invariance, parity with the direct tool (7/7), scan admission
(3,898,870 rows > 1M refused without dispatch under the defaults), the deadline and the slot,
zero provider calls, and no lost child.

## Harness fixes found by the first real container runs

| Commit | Problem |
|---|---|
| `47e8129` | The gate required `platform.system() == "Linux"` on the host. Colima and Docker Desktop run a Linux VM, so it now checks the Docker daemon's `OSType` and records the kernel, the cgroup version and the image id and architecture. An OOM-killed container now counts as a measured failure, although its peak can no longer be read |
| `4f5c138` | A published Docker port accepts TCP before the app listens, so readiness by TCP connect sent the first MCP call to an app that had not started. Every scenario failed with a TaskGroup error. Container children now wait for `/api/health` 200 |
| `ce4760b` | The post-phase slot probe took a new fresh rank request on every `busy` poll, and the 300 s phase had already used up the variant pool. The probe now reuses the variant, since a busy answer is neither dispatched nor cached, and one variant is set aside per phase |
| `64d75da` | Memory is now split into heap (`anon`) and page cache (`file`) |


## What 01B still needs (not done)

- The worst admitted request of every scan-gated tool: `query_data`, `compare_periods`,
  `find_dimension_values`, `run_recipe` and the multi-source recipes. The harness drives only
  `rank_entities` and its REST mix.
- A longer soak (≥ 30 min), to see whether the heap levels off.
- A decision on the threshold. On amd64 the **current defaults** are already above 75 % under
  this load, with or without the MCP, so the line is crossed by the REST and search mix. Following
  the spec, the failure is published, no larger Fly machine is assumed, and the threshold is not
  weakened. The options are in "Decisions for the owner".
- The MCP limits stay as they are. `POLICY_VERSION`, the operator configuration and rollback
  notes follow only from a profile that passes.

## Decisions for the owner

1. **The threshold on amd64:** keep 75 % and reduce the work (01C: smaller caches or fewer
   concurrent REST paths), or accept a measured 77–78 % with no OOM as the operating profile.
   Raising the Fly memory is out of scope without your approval.
2. **The P1 scan estimate:** the cap is not what drives memory (5M vs 1M is within noise), so a
   filter-aware estimate is safe to add. Raising the cap alone is the cheaper fix, but it
   still needs the per-tool runs above.

## Follow-up: where the memory goes (2026-10-27, after the owner kept the 75 % line)

These are diagnostic runs, not gate runs. They used the same images and limits (512 MiB, 1 CPU), arm64
unless noted. The scratch probes are in `/Users/pax/devbox/gov2/tempo-rc-06b/aq01b/`
(`heap_probe.py`, `run_alpha.sh`, `serve_sampled.py`, `place_mem.py`).

**Main DuckDB budget.** The main metadata connection caches the table pages it scans, up to its
`memory_limit` (default `400MB`, 381 MiB effective). This is in addition to the FTS sidecar (192MB budget),
every scratch instance (128MB each) and the MCP footer reads (32MB). The budgets sum to more than the
machine. Under the AT-04 mixed load (harness, scan cap 5M):

| `TEMPO_DB_MEMORY` | arm64 peak | amd64 peak | Latency vs default (arm64) |
|---|---:|---:|---|
| default (400MB) | 73.3 % | 76.0–77.0 % | baseline |
| 200MB | | 75.5 % | |
| 160MB | 69.2 % | not run | about 5–10 % slower p50, all well under target |
| 128MB | 69.6 % | 69.6 % | the same as 160MB |
| 96MB | | 72.6 % | (an emulated run with lower throughput, so this row is noise) |

**The PA-04 site workload is heavier than the AT-04 mix, and it reaches the limit.**
`scripts/alpha-workload.py` (5 clients, 300 s; the MCP off) in the same container:

- **Default budgets:** `memory.peak` = 100 % of the limit, 168 `memory.max` events, sampled heap up to 513 MB.
  There was no OOM kill, no 5xx and no inconsistency, but the kernel was reclaiming at the limit.
- **`TEMPO_DB_MEMORY=160MB`:** heap up to 470 MB, 2 `max` events.
- **Plus `TEMPO_SCRATCH_MEMORY=64MB`:** 91.9 % peak.

Per request kind (5 clients, 120 s, default budgets):

| Kind | Peak |
|---|---:|
| place profile `/api/places/county/cluj` | **76.9 %** |
| concept search `/api/search` | 60.6 % |
| export | 40.0 % |
| query | 36.7 % |
| recipe | 31.2 % |
| page | 27.2 % |
| evidence | 26.1 % |
| health (AT-04 probe) | about 12 % |

**One place profile, in-process:**

- The first call adds 273 MB of heap in 3.9 s and opens **57 separate in-memory DuckDB instances**
  (`scratch_conn()`, one per KPI step). Later calls take 0.55 s, open 52 instances each and add nothing.
- Afterwards the main DuckDB holds 133 MB of cached table pages and the glibc heap holds about 70 MB.
- Smaller jemalloc flush thresholds and background threads, `MALLOC_ARENA_MAX=2` and `malloc_trim` change
  nothing. One shared scratch instance instead of 57 made it worse: 95.6 % with 5 clients.

**At the peak of the PA-04 workload** (160MB main budget), anon was 489 MB:

| Part | Size |
|---|---:|
| main DuckDB | 124 MB (93 table pages, 20 hash tables, 10 indexes) |
| FTS | 4 MB |
| glibc heap (Python objects, 1.69M blocks) | 120 MB |
| outside DuckDB's and glibc's accounting (scratch instances in flight, pymalloc arenas, allocator overhead) | about 240 MB |

`main` (the live site) has the same design: a 400MB main budget and place KPIs on separate DuckDB
connections. These runs are of `fix/ask-answer-quality`, so whether the live machine reaches its
limit under this load is not measured. Its Fly logs were not read.

## Changes made after the owner's decisions (2026-10-27): 1, 2 and 4 approved

Branch `aq/01bc-capacity`, final image built from `b53d050` (tests: 2,097 passed and 89 skipped before the
fixture budget fix in `83647d7`; that fix makes the harness tests pass, 59/59).

| Change | Commit | Measured effect |
|---|---|---|
| `TEMPO_DB_MEMORY` default 400MB → 160MB | `0eb60de` | Removes the 400MB ceiling on the main DuckDB cache. At 96MB the PA-04 queries fail (5 DuckDB OOM errors); 128MB measured no better than 160MB; 256MB raised the PA-04 heap to 85 % |
| Place profiles: built one at a time, cached per generation (`TEMPO_PLACE_*`) | `0eb60de` | Place-only PA-04 load: 77 % → 60 % heap; p50 6.06 s → 0.015 s, p95 22.6 s → 2.1 s |
| The place recipe cache keeps only the fields KPIs read, for one generation | `e193fc5` | About 70 MB of retained source tables gone. KPI reports and baselines for six places are byte-identical |
| The main connection uses at most 2 DuckDB threads by default | `b53d050` | At 160MB, the heaviest admitted MCP query failed 5/5 with 8 threads and passed 16/16 with 1–2. Fly has one vCPU, so it already ran with one thread |
| MCP operator profile `scripts/deploy/fly/mcp-public.env` (scan cap 5M; app defaults unchanged) | `0eb60de` | See the worst-case table below |

The P1 filter-aware estimate was dropped. Every row group of the large files spans all counties and all
years (POP107D_grupe_localitate: 33 groups, each Alba..Caras-Severin and 1992..2026), so footer statistics
cannot prune anything. A filter-aware count would need a new per-value count in the generation.

## Final runs (arm64 native, 512 MiB, 1 CPU, image `b53d050`)

"Heap" is the sampled cgroup `anon`: what an OOM kill is made of. "Peak" is `memory.peak`, which also
counts page cache. The kernel reclaims page cache at the limit, so peak can read 100 % with a heap of 71 %
(PA-04 run below, 172 reclaim events, no OOM).

| Run | Peak | Heap | Result |
|---|---:|---:|---|
| AT-04 harness: cold, warm, admission, timeout, worst case, mixed 180 s + 300 s | 72.8 % | **71.8 %** | every check passes, incl. worst-case parity 8/8 |
| PA-04 site workload, 5 clients, 300 s (MCP off) | 100 % (page cache) / 76.9 % in a repeat | **70.6–70.8 %** (was 95.6 %) | 0 problems, no OOM |
| AT-04 mixed soak, 5 MCP + 2 REST clients, **1,800 s** | 88.9 % | **78.1 %** | 0 unexpected 4xx/5xx, slot frees, no OOM |
| Heap curve, `mixed_load.py` 5 MCP + 2 REST clients, 1,800 s | 74.9 % | ~300 MB at 1 min → ~370 MB at 30 min, slope falling (+35, +20, +15 MB per 10 min) | `MALLOC_ARENA_MAX=2`: the same curve |

Worst admitted request per scan-gated tool, scan cap 5M, each on a warm child (arm64; amd64 identical
outcomes):

| Request | Result | Wall s | Heap in its window |
|---|---|---:|---:|
| `query_data` POP107D_grupe_localitate by county, locality, year | partial (preview) | 0.14 | 130 MB |
| `query_data` by locality, one year | partial | 0.05 | 130 MB |
| `find_dimension_values` locality | ok | 0.04 | 128 MB |
| `rank_entities` all localities, top 100 | partial | 0.10 | 127 MB |
| `compare_periods` 4 intervals, all localities | partial | 0.23 | 140 MB |
| `run_recipe` tourism_intensity / net_earnings_county / registered_unemployment_county | ok | 0.14 / 0.24 / 0.28 | 149 / 199 / 212 MB |
| All 8 at once from separate sessions | 1 served, 7 `busy` | | 231 MB |

Latency, arm64 native (AT-04 targets: warm p95 < 2 s metadata, < 5 s analytical; all met):
- **Cold:** discover p50 0.56 s; the first rank 0.41 s.
- **Warm misses:** rank p95 0.11 s; discover p95 0.30 s.
- **Mixed, five clients:** rank-miss p95 0.46 s; REST detail p95 0.72 s.

### Still open

- **The 75 % line over long runs.** Short runs are at 71–72 % heap. A 30-minute soak reached 78 %, still
  rising but more slowly each time. The main DuckDB cache filling up to its 152 MiB cap fits that shape, but
  it is not proven. A longer soak (≥ 2 h) would show where the heap levels off.
- **Group-bys over every dimension of a 3.9M-row file** (`query_data` with 4–5 dimensions) need more than the
  160MB budget. DuckDB does not spill them, even with a `temp_directory`. Such a request returns
  `execution_failed`, not a crash. With 4 dimensions it needs ≥ 256MB; with 5, more. The REST `/data` path
  time-windows these, and its 18 heaviest requests pass at 160MB.
  *Resolved 2026-10-27 (owner: refuse before execution):* the tools estimate the groups and answer
  `query_budget` above 250,000 with the column to filter (570k groups fit at 160MB, 860k failed). See the
  activity log.
- **amd64 is emulated (Rosetta),** which adds about 50 MB of heap at idle (108 vs 58 MB) and after light load
  (288 vs 232 MB). So amd64 figures here overstate the real x86 heap, and arm64 may understate it slightly. A
  real x86 Linux run (a Fly test machine or a Linux host) is the only exact one.
