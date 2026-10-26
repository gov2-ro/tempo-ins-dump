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
