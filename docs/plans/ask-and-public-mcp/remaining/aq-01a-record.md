# AQ-01 step 01A completion record: public MCP capacity harness

**Status (2026-10-17): code-ready and validated locally on synthetic fixtures and on the read-only copied
generation. The Linux 512 MiB gate is `not_run`: Docker is not installed here.** Branch
`aq/01a-capacity-harness`, not pushed, not merged, not deployed. Only 01A was done; 01B (select a measured
profile) and 01C (optimization design) are untouched. **No application code, limit or default changed**
(`app/` has no diff).

| | |
|---|---|
| Baseline | `ce472e9` (AT-05 plus the `remaining/` specs) |
| Code | `21d569a` (`feat(mcp): capacity benchmark harness for the public MCP (AQ-01 01A)`); this record follows in a second commit |
| Spec | [01-mcp-capacity.md](01-mcp-capacity.md), section 01A |
| Corpus / tables changed | none (the copied generation was read-only; fixtures are temporary) |
| New dependencies | none (stdlib, the existing `mcp`, `httpx`, `duckdb`, `uvicorn`) |

## What was built

- **`scripts/benchmark-mcp.py`** (`run`; `serve` and `inproc` are internal child commands).
  - Launches an isolated candidate: `uvicorn` in its own process group on a port from `--ports`
    (default: an ephemeral free port), with `TEMPO_DATA_DIR` explicit, an allowlisted environment (no
    provider key, no `TEMPO_ASK_*`/`TEMPO_LLM_*`, Ask off), the MCP enabled for localhost. It never attaches
    to a server it did not start. `--out-dir` is required and may not be inside the repository.
  - Drives it with the real SDK client (`streamable_http_client` + `ClientSession`, initialize/list/call).
  - The child runs through `serve`, which wraps the real app with: a provider-call guard (the three
    provider leaf functions are replaced by a logger-and-refuse), a `BENCH_DISPATCH` line per tool dispatch,
    the app's own `MCP_METRICS` lines on stderr, and a `BENCH_CHILD` line with the child's effective
    `McpSettings`. The harness reads that log, so "refused at the gate without dispatching the handler",
    cache hits and provider calls are observed in the child, not inferred.
  - **Control profile = the application's defaults.** A candidate sets `--max-scan-rows`, `--max-seconds`,
    `--max-concurrent`, `--cache-*` or `--setting TEMPO_X=v` for the child only; they are listed in
    `profile.settings_declared` and the child's effective values in `runs[].child.mcp_settings`. Zero,
    negative, non-numeric or non-finite values are rejected before launch. Only the two per-minute rate
    limits are lifted in every child (`profile.harness_overrides`, `--keep-rate-limits` undoes it): a
    sequential sample loop would otherwise be throttled into `busy` answers.
  - **Scenarios** (`--scenarios`, all by default): `cold_chain` (startup, initialize, list, discover,
    describe, exact-year city rank; fresh process each), `cold_first_rank` (rank as the first analytical
    call), `warm` (cache hits; result-cache misses over years and county filters with metadata warm; latest
    year; top K = 1/30/100; cached describe; varied vs repeated discovery; MCP-vs-direct parity),
    `admission` (unknown dataset, the workload source against the scan cap, an optional
    `--over-limit-dataset`, simultaneous calls, a caller that hangs up mid-call and the next request),
    `timeout_probe` (a fault-injected uninterruptible worker outlives the deadline: caller answer, slot held,
    first request after) and `mixed` (MCP plus REST/search/export clients in named phases, default
    `NAME:MCP:REST:SECONDS` = AT-04 shapes `single_client` 1 and `five_clients` 5).
  - **Report** (`report.json`, schema `benchmark-mcp/1`, plus `samples.jsonl` and per-child `logs/`).
    Code identity (commit, branch, dirty flag, hash of the working-tree diff and untracked files), generation
    id and manifest hash, footer rows/size/mtime/footer hash of every source, OS/Python/package versions,
    container limit, all settings, scan estimate vs cap, per-group counts, outcomes, result/wire bytes, cache
    hits, dispatches, p50/p95 per group, wall time, child CPU (window deltas and exact lifetime), process-tree
    peak RSS (sampled) and exact lifetime peak RSS, container cgroup memory and OOM/restart fields, checks,
    gates, caveats, and the sample-count shortfalls.
- **Percentile rules.** Groups are keyed by `(case, state)` with states `cold`, `miss_warm`, `cache`, `mixed`,
  `observed`; there is no catch-all `warm` and no pooled latency anywhere. Nearest-rank (an observed value),
  over **served** answers only; refusals, tool errors, transport errors and client timeouts are counted per
  outcome with their own latency summary. A group with nothing served has `latency_s: null`. `required_n` is
  5 per cold case and 20 per warm case (1 for the one-off cases), and `sufficient` says whether it was met.
- **Units.** `rss_to_bytes` normalises `ps` (KiB), `/proc` (kB) and `ru_maxrss` (bytes on macOS, KiB on
  Linux). The child's exact lifetime peak is the `wait4` rusage. A process-tree RSS sum counts shared pages
  per process and is not cgroup memory (stated in `caveats`).
- **Container mode** (`--mode container --image IMAGE`): `docker run -d --memory 512m --memory-swap 512m
  --cpus 1 --restart no`, the script mounted read-only as the entrypoint, `--data-dir` mounted read-only,
  environment passed with explicit `-e` (nothing inherited), memory from the cgroup (`memory.current`,
  `memory.peak`, `memory.events`), `docker inspect` for OOMKilled/RestartCount, `docker rm -f` always. It was
  **not run against Docker**; it is exercised through an injected runner (command construction, start
  failure cleanup, measurement parsing, OOM fields). Without Docker the run is `blocked` and the gate is
  `not_run`.
- **Bounding and cleanup.** Per-call timeout, startup timeout and a total wall-clock budget
  (`--max-total-seconds`); every child is registered, stopped on any exception, on exit and on
  SIGINT/SIGTERM (SIGTERM, then SIGKILL, process group), and `stop()` is idempotent. A SIGKILL the harness
  did not send is reported as `oom_suspected`. A failed cold repetition is recorded and the others still run;
  the scenario then fails. The report is rewritten after every scenario and always written at exit.

## Acceptance for 01A

| Spec item | Where it is shown |
|---|---|
| Default profile reproduces `unavailable/query_budget` for an over-limit fixture and proves the handler was never dispatched | `test_default_profile_refuses_the_over_limit_fixture_and_never_dispatches_the_handler`: CITYBIG (footer 1,035,462 rows > 1,000,000) through the real client; the sample says `refused`, the child's `cold_first_rank-1` run has `dispatches == {}`, its log has no `BENCH_DISPATCH`; `checks.scan_admission` passes. Same on the real generation (below) |
| Winner after row 200 and a larger commune: correct ranking and exclusions through the real client | `test_candidate_profile_ranks_cities_correctly_through_the_real_client_with_parity`: on the same CITYBIG with `--max-scan-rows 2000000`: year 2025, 230 eligible, 1 outside class (the commune worth 999,999 is out), 0 excluded, values 329, 328, 327, top entity `1229 ORAS CITY229`, unit `Numar persoane`, `source_complete` |
| Parity with the direct shared tool | same test: 7 requests, MCP envelope equal to `registry.call_tool` in a fresh process (all keys, ignoring only `request_id`/timing keys), and rows/eligible/excluded/outside/unit/sources/scope/warnings reported per request |
| K = 1/30/100 never changes the eligible set | `checks.k_invariance` (eligible, excluded, outside-class, `source_complete`, shared prefix, returned row count) |
| Report schema, grouping, units, cleanup, timeout/error accounting, null/not_run | unit tests listed below |
| Report written when Docker/corpus is unavailable; Linux gate unrun | `test_a_run_without_a_corpus_writes_a_blocked_report...`, `test_container_mode_without_docker_is_blocked...`; `gates.linux_512mib` is `not_run` in every report here |
| Existing resource/ranking tests | `test_at03_resources`, `test_at03_mcp`, `test_at05_ranking` pass (below) |

## Checks run

Virtualenv `~/devbox/envs/240826`, `PYTHONDONTWRITEBYTECODE=1`, `-p no:cacheprovider`.

| Command | Result |
|---|---|
| `python -m pytest tests/test_aq01_benchmark.py -q` | 51 passed (about 45 s, with five real children on ports 8111-8115) |
| `python -m pytest tests/test_aq01_benchmark.py tests/test_at03_resources.py tests/test_at05_ranking.py tests/test_at03_mcp.py -q` | 121 passed (51 new + the existing resource, ranking and MCP tests) |
| `python -m pytest tests -q` | **1229 passed, 73 skipped** (baseline 1175/73 plus the 51 new tests is 1226; the run shows 3 more, which AT-05's record explains as three Ask-browser cases added after its 1,175 run, not separately verified; the skips are unchanged at 73). Existing openpyxl/FastAPI warnings only |
| Docker image / Linux 512 MiB | **not run** (no `docker` executable) |

What the 51 tests assert (values, definitions, refusals, not only success): nearest-rank percentiles and
empty means null; the same case in `cache`, `miss_warm` and `cold` never merges; sufficiency counts; a
timeout is not a latency; a group with only refusals has null latency and null bytes; RSS unit conversion
for macOS and Linux and `ps`/`/proc`; process-tree sums; ps/proc/docker parsers; JSON diff paths; outcome
classification (`busy` slot vs rate limit); settings validation and the child environment (provider keys
present in the parent are absent in the child, zero/NaN rejected); log parsing with a partial line;
unknown wire size is null; the scan-admission check (over cap must be `query_budget` without dispatch,
admitted under a candidate cap); K invariance; reduced vs full scale labelling; blocked reports; the
reports-outside-the-repo rule; client-side timeout, transport error, tool error and refusal accounting
through the real `call()` path with a fake session; resource windows without a reading are null; stubs that
never listen, die at startup, ignore SIGTERM or are SIGKILLed are cleaned up or classified; a scenario that
raises after its child started leaves no child and a failed-scenario report; the container command and
cleanup through a fake Docker; four end-to-end runs through the real client.

## Numerical examples

Synthetic CITYBIG, through the real MCP client (candidate profile): year 2025, 230 eligible, 1 outside
class, ranked values 329, 328, 327 (`1229 ORAS CITY229` first), the commune with 999,999 excluded; K = 1, 30,
100 return 1, 30, 100 rows over the same 230 eligible.

Copied generation `9b3e065d2fe9bb1df9bae2131b7bdeae9be3426f3c82b9a9954f7e6dc8f45550` (read-only,
`/Users/pax/devbox/gov2/tempo-gen-20261012/data`), `rank_entities(POP107D_grupe_localitate, cities)`, latest
year 2026: 319 eligible, 2,862 outside the class, 0 excluded; 1. Municipiul Bucuresti 2,108,049, 2. Iasi
370,437, 3. Cluj-Napoca 324,860 (the same as the AT-05 direct probe); K = 1/30/100 all report 319 eligible;
seven MCP envelopes equal the direct shared tool. Footer of the file: 3,898,870 rows in 33 row groups.

## Real-generation run (reduced counts, labelled; local macOS, not a 512 MiB result)

Reports are deliberately outside the repository (not committed):
`/private/tmp/claude-501/aq01a-work/aq01a-report/control/report.json` and
`/private/tmp/claude-501/aq01a-work/aq01a-report/candidate/report.json` (the scratchpad directory named in
the assignment was reported unavailable during the session). Both ran at code `21d569a`, clean tree,
Python 3.12.15, mcp 1.27.0, duckdb 1.4.2, macOS 15.8.1 arm64, 32 GiB RAM, **unconstrained**. Mixed phases
were **30 s each instead of AT-04's 180 s and 300 s**, so `scale.label` is `reduced` in both; cold
repetitions (5) and warm samples (20) met the spec counts.

Commands:

```
python scripts/benchmark-mcp.py run --data-dir /Users/pax/devbox/gov2/tempo-gen-20261012/data \
  --out-dir .../aq01a-report/control --cold-repeats 5 --warm-samples 20 \
  --scenarios cold_chain,cold_first_rank,warm,admission --ports 8111-8115
python scripts/benchmark-mcp.py run --data-dir ... --out-dir .../aq01a-report/candidate --cold-repeats 5 \
  --warm-samples 20 --max-scan-rows 5000000 --mixed-phase single_client:1:2:30 \
  --mixed-phase five_clients:5:2:30 --export-dataset TUR105D_judete --ports 8111-8115
```

**Control (defaults, scan cap 1,000,000).** The national city rank is refused: 5 of 5 cold-chain and 5 of 5
first-rank calls, the warm and admission calls, all `unavailable/query_budget` (83 gate refusals in the
children's logs), with **zero `rank_entities` dispatches** in the first-rank children;
`checks.scan_admission` pass (3,898,870 > 1,000,000, not dispatched). Metadata calls are served: cold
discover p50 0.725 s (p95 0.797), describe p50 0.112 s. Provider calls: 0. Exit 0.

**Candidate (scan cap 5,000,000 in the child only).** 14 children, 1,946 gate calls, 1,298 cache hits, 0
provider calls, 0 OOM, 0 unexpected 5xx/4xx, all checks pass (parity 7/7, K invariance, scan admission,
deadline and slot, mixed load). Seconds, served answers only (p50 / p95, n):

| State | Case | p50 | p95 | n |
|---|---|---:|---:|---:|
| cold | startup (spawn to listening) | 0.636 | 0.718 | 5 |
| cold | discover_indicators | 0.604 | 0.686 | 5 |
| cold | describe_dataset | 0.107 | 0.190 | 5 |
| cold | exact-year city rank after describe | 0.074 | 0.094 | 5 |
| cold | exact-year city rank as the first analytical call | 0.634 | 0.697 | 5 |
| cache | same rank from the result cache | 0.021 | 0.025 | 20 |
| miss_warm | rank, different years (metadata warm) | 0.065 | 0.092 | 20 |
| miss_warm | rank, county filter x years | 0.040 | 0.048 | 20 |
| cache / miss_warm | describe (cached) / discover (varied) | 0.027 / 0.066 | 0.031 / 0.077 | 20 |

Top K = 1/30/100 (one miss each): 0.061, 0.063, 0.065 s, wire about 9.3, 15.6 and 30.6 KB.
Exact lifetime peak RSS of a child (macOS, `wait4`): 284-298 MiB for a first-rank child, 378-386 MiB for a
cold chain, 470 MiB for the warm child, **589 MiB for the mixed-load child**; the sampled process-tree peak
inside the mixed phases was 588 MiB (one MCP client plus two REST clients) and 545 MiB (five MCP plus two
REST). These are unconstrained-host figures, shared pages included; they show the workload approaches
the 512 MiB line on this host and are **neither a pass nor a fail of the 512 MiB gate**. Mixed phases (30
s, about 1,500 and 1,800 requests): MCP rank-miss p50 0.099 s (one client) and 0.159 s (five
clients), REST export p50 0.095 / 0.170 s; with five MCP clients 132 of 363 rank-miss calls were answered
`busy` as designed (the gate has one slot), cache hits bypass the slot. Simultaneous calls: 1 served, 4
`busy`. Hang-up mid-call: the next request was answered `busy`, and the slot freed 0.096 s later, so the
abandoned work kept it until it ended. Timed-out worker (fault-injected, deadline 1 s): `query_timeout`
after 3.03 s, `busy` during the work, slot free after 5.67 s, the next request served.

## Decisions to review

- Rate limits are lifted in the child (disclosed, undoable). Everything capacity-relevant stays at its default
  in the control profile.
- Percentiles are nearest-rank over served answers; failures are counted beside, never in them.
- The slot-semantics check uses a **fault-injected sleep** because a real over-deadline worker needs a slow
  query that a fast fixture cannot supply; the scan cap is raised in that probe's child only, and the report
  says so. The hang-up scenario is best effort ("observed"), not a deterministic assertion.
- Cache-intended and miss-intended samples are relabelled by what the child's log says happened (a served
  sample marked `miss_warm` that was cached is counted under `cache`).
- The 75 % container-memory threshold is **not evaluated** here: `gates.linux_512mib` can at most become
  `measured` with `evaluated: false`; the decision belongs to 01B.
- In container mode the benchmark script is mounted and used as the entrypoint (for the instrumentation), and
  MCP-vs-direct parity runs in a local fresh process on the same mounted data.
- The report's default dataset is `POP107D_grupe_localitate` (the file that was 3,898,870 rows in this
  generation); every dataset, column, year, county and REST path is an option, and the footer is read each run.

## Remaining gates (not done, not claimed)

- **Linux 512 MiB resource gate: `not_run`** (no Docker here). Needs `--mode container` on a Linux host with
  the exact candidate image and data; the container path is code-ready and fake-Docker tested only.
- Full AT-04 phase lengths (180 s, 300 s) and a longer soak: only 30 s phases were run.
- 01B: worst admitted request of every scan-gated tool (`query_data`, `compare_periods`,
  `find_dimension_values`, `run_recipe` and multi-source recipes), the candidate scan budget, the warm-p95
  and 75 % memory acceptance, `POLICY_VERSION` and operator documentation. None of that is implemented.
- 01C optimization design: not started and not needed to decide anything yet.
- Live clients, deployment, production exposure: out of scope.

## Rollback

Delete `scripts/benchmark-mcp.py`, `tests/test_aq01_benchmark.py` and this record (`git revert` of the two
commits). Nothing else depends on them; no application, configuration, limit or data was changed.

## Operating the harness

```
source ~/devbox/envs/240826/bin/activate
python scripts/benchmark-mcp.py run --data-dir <data dir with corpus/> --out-dir <dir outside the repo> \
    [--max-scan-rows N --max-seconds S ...] [--mode container --image <existing image>] [--ports 8111-8115]
```

Exit 0 completed, 1 a check or scenario failed (or a child was killed), 2 blocked. Never point it at a
data directory being written, and never at production: it only talks to children it started on 127.0.0.1.
