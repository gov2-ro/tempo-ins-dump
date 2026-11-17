# HZ-3 record: measurements on Linux (Hetzner VPS)

Date: 2026-11-17 (measured 00:20-00:35 UTC). Plan: [hosting-hetzner.md](hosting-hetzner.md), section HZ-3.
Run by a Claude session (Sonnet) from the Mac. Measure and report only. Nothing on the live service changed.
No restart, no sudo, no edit in `/etc`, `/opt/tempo` or the live corpus. No commit.

## What ran

- VPS `gov2-1` (2 vCPU Intel Xeon Skylake under KVM, 3.8 GB RAM, 2 GB swap). Release `20261117-013142-062bd2b0`.
- Step 1 and 5: reads of the cgroup of `tempo-api`.
- Step 2: `benchmark-mcp.py run --mode local` from `~/g2-dev/tempo-ins-dump` (`main`, commit `4b9de30`),
  with the live venv and data, `--max-scan-rows 5000000`, `TEMPO_DB_MEMORY=128MB`, `TEMPO_SEARCH_MEMORY=64MB`.
  The harness started its own child on its own port. All scenarios ran. It lasted about 12 minutes.
  Report copy on the Mac: `/private/tmp/claude-501/-Users-pax-devbox-gov2-tempo-ins-dump/7819063e-8085-4756-a10c-0ec74c7cd1cf/scratchpad/hz3-bench/report.json`.
  Report on the VPS: `~/hz3/bench/report.json`.
- Step 3: `dd` tests, `vmstat`, and 15 new `discover_indicators` calls on loopback.
- Step 4: 10 questions with `claude -p` (Sonnet) against `https://api-ins.gov2.ro/mcp`.

Important: step 2 and step 4 ran at the same time. The live questions hit the live service while the benchmark
child used the same 2 CPUs. Latency numbers in step 2 and the live timings may be worse than on a quiet host.
See "Risks" below.

## Step 1 and 5: baseline and after (cgroup `tempo-api.service`)

| Value | Before (00:21) | After (00:32) |
|---|---|---|
| `memory.current` | 56 MiB | 267 MiB |
| `memory.peak` | 257 MiB | 283 MiB (297,123,840 bytes) |
| `memory.swap.current` | 189 MiB | 158 MiB |
| `memory.swap.peak` | not read | 192 MiB |
| `memory.max` | 1 GiB | 1 GiB |
| Anonymous memory / file cache (after) | n/a | 152 MiB / 108 MiB |
| `NRestarts` | 0 | 0 |
| Host `free -m`: used / buff-cache / swap used | 709 / 3254 / 809 MiB | 974 / 2560 / 745 MiB |
| Load average (1 min) | 0.04 | 0.67 |

- The idle service kept only 56 MiB in RAM. The kernel had moved about 189 MiB of it to swap. The first calls
  after an idle period pay a swap-in cost. This adds to the first-call latency on this host.
- `journalctl` shows nothing to user `pax` (no journal access). `MCP_METRICS` lines could not be counted.
  The file `/var/log/tempo/mcp-calls.jsonl` (readable) was used instead: 68 calls since the cutover.
- Memory outside the service (scrapers) was not measured. No scraper ran during the window (assumed from low load).

## Step 2: benchmark on Linux

Status `completed`, checks failed: none, problems: none, `oom_suspected: 0`, 15 child processes.
`linux_512mib` is still `not_run`: a local run has no container limit. This is expected.

Peak memory of the child (resident size, sum over the process tree, sampled each 0.1 s):

| Scenario | Peak RSS (MiB) | macOS (aq-07, profile 64/128) |
|---|---|---|
| cold chain (5 repeats) | 263-268 | 371-377 |
| cold first rank | 212-215 | 276-280 |
| warm | 209-217 | 452 |
| worst case, per call | 183-270 | 356 |
| mixed, single client | 266 | not run |
| mixed, five clients + 2 REST clients | **294** (highest) | not run |
| Lifetime peak (kernel `ru_maxrss`), highest run | 294 | n/a |

The Linux peak is lower than on macOS. The macOS venv has pandas, numpy and pyarrow. The VPS venv does not
(see the correction in `aq-07-record.md`). The child after import is 106 MiB (macOS: about 101 MiB).

Latency in seconds (Linux values from this run; macOS from aq-07, same profile family):

| Case | State | n | p50 | p95 | max | macOS p50 |
|---|---|---|---|---|---|---|
| startup (child ready) | cold | 5 | 2.49 | 3.98 | 3.98 | 0.6 |
| `initialize` | cold | 5 | 0.011 | 0.022 | 0.022 | n/a |
| `tools/list` | cold | 5 | 0.037 | 0.043 | 0.043 | n/a |
| `discover_indicators` (first call of a fresh process) | cold | 5 | 1.55 | 2.96 | 2.96 | 0.74 |
| `describe_dataset` | cold | 5 | 0.66 | 0.68 | 0.68 | n/a |
| `rank_entities` after the chain | cold | 5 | 0.48 | 0.63 | 0.63 | n/a |
| `rank_entities` as first call | cold | 5 | 1.44 | 1.72 | 1.72 | 0.69 |
| `rank_entities`, exact year (cache) | cache | 20 | 0.098 | 0.111 | 0.114 | 0.026 (describe) |
| `rank_entities`, year miss | warm | 20 | 0.321 | 0.438 | 0.452 | 0.098 |
| `rank_entities`, county miss | warm | 20 | 0.205 | 0.243 | 0.273 | n/a |
| `describe_dataset` | cache | 20 | 0.129 | 0.152 | 0.155 | 0.026 |
| `discover_indicators` | miss, warm | 20 | 0.285 | 0.367 | 0.451 | 0.103 |
| `discover_indicators` | cache | 20 | 0.131 | 0.156 | 0.157 | n/a |

Worst-case calls (one call each, seconds): `query_data` by year 0.85; `query_data` one year 0.26;
`find_dimension_values` 0.20; `rank_entities` top 100 0.38; `compare_periods` four intervals 0.83;
recipe `tourism_intensity` 0.72; `net_earnings_county` 1.33; `registered_unemployment_county` 1.48.
Scan estimate 3,898,870 rows against the cap of 5,000,000. All were served. None was refused for the scan cap.

Admission and timeout outcomes:

| Probe | Result |
|---|---|
| unknown dataset | `tool_error` (expected) |
| 5 concurrent `rank_entities` | 1 served, 4 `busy` (expected, one slot) |
| 8 concurrent worst-case calls | 1 served, 7 `busy` (expected; macOS also 7) |
| after cancel / timeout probe (`max_seconds=1`) | refused as designed; the first call after was served in 0.87 s |
| mixed, single client, 10 s | 0 unexpected 4xx or 5xx; slot free after 0.15 s |
| mixed, five MCP clients + 2 REST clients, 10 s | 0 unexpected 4xx or 5xx; slot free after 0.36 s; 10 of 22 `rank` misses `busy` (expected under the one-slot gate) |

Totals: 310 gate calls, 134 cache hits, 39 `busy`, 1 `query_timeout` (the designed 1 s probe). Both parity checks passed.
Mixed five-client latency (p50 / p95, s): `rank` miss 1.00 / 2.02; `describe` 0.59 / 1.32; REST `/health` 0.20 / 0.58;
REST county query 0.38 / 1.05; REST detail 0.97 / 1.44; REST search 0.47 / 0.57.

## Step 3: latency gap (new `discover_indicators`: 0.6-3.8 s on the VPS, 47 ms on the Mac)

Evidence:

1. A cache hit is also slow. A cache hit does no disk read. It took 0.098-0.131 s on the VPS (p50) and 0.026 s on macOS.
   That is a 4-5 times gap with no I/O involved.
2. A plain Python loop (`sum of i*i`, 10 million steps) took 3.46 s on the VPS and 1.23 s on the Mac. The VPS is 2.8 times slower per core.
3. The 15 new queries on loopback (server times, seconds): 1.90, 0.43, 0.26, 0.87, 1.27, 0.48, 0.37, 0.20, 0.78, 0.77,
   0.24, 0.40, 0.13, 1.40, 0.34. Median 0.43, range 0.13-1.90. Query text changes the time a lot (the work depends on how many
   concepts match). The 36 uncached calls in `mcp-calls.jsonl` have p50 0.76 s and one value of 10.6 s (see Risks).
4. During those 15 calls (`vmstat 1`, 33 s): user CPU 24.7 % average (peaks 43-60 % on a 2-core host, so one core near full),
   iowait 1.2 % average (2-6 % peaks), 28 MB read from disk in total, no swap-in worth noting. The data was almost all in the page cache.
5. Disk tests (`dd`, direct I/O, so page cache is bypassed):

   | File | Network volume (`/opt/tempo`) | Local disk copy |
   |---|---|---|
   | `search.duckdb` 48 MiB, sequential 1 MiB | 156 MB/s (0.32 s) | 906 MB/s (0.06 s) |
   | `metadata.duckdb` 589 MiB, sequential 1 MiB | 183 MB/s (3.4 s) | 802 MB/s (0.77 s) |
   | `metadata.duckdb`, 20,000 random reads of 4 KiB | 4.1 MB/s (20.0 s, about 1.0 ms each) | 16.8 MB/s (4.9 s, about 0.24 ms each) |
   | `metadata.duckdb`, buffered read (cached) | 980 MB/s | n/a |

Conclusion: the main cause is CPU. The VPS core is about 3 times slower than the Mac core, and
the call path (SQL, FTS, Python) is CPU bound. This explains the warm numbers (miss 0.29 s against 0.10 s, cache 0.13 s against 0.026 s)
and most of the new-query range. I am fairly sure (about 80 %).

The network volume adds a second, smaller cost for cold reads. Its sequential read is 4-6 times slower than the local disk,
and a random 4 KiB read is 4 times slower (1 ms against 0.24 ms). This hits the first call after a start or after the
page cache drops. It does not explain warm latency, because the files are cached (buff/cache is 2.5-3.2 GB) and iowait stays low.
The cold chain (1.5 s for the first `discover_indicators`) mixes both causes, and I could not split them without dropping the cache (needs root).
Swap-in of the idle service (189 MiB in swap) is a third cause for first calls after idle. I did not measure it separately.

Suggestions (not applied):
- Test `search.duckdb` (48 MiB) on the local disk (for example under `/var/cache/tempo`). It is small. This only helps cold reads. Expect no gain on warm calls.
- Keep the page cache warm: a read of both `.duckdb` files at service start (`cat file > /dev/null` in `ExecStartPost`) costs 1 s and avoids the first random reads.
- For warm latency only more CPU helps (a larger plan type), or less work per call. Check this gap against the real traffic before paying for it. 0.3-1.9 s is acceptable for an MCP tool.
- Consider `MemorySwapMax=0` or a lower `vm.swappiness` for `tempo-api`, so an idle service stays in RAM. The service has a small RSS, so this is cheap.

## Step 4: ten live questions through `api-ins.gov2.ro/mcp`

Compared with `baseline-2026-11-15/` (same questions, local server on the Mac). Each of the 10 runs ended without an error flag.
No permission denial. No `403`, `421`, `busy` or timeout reached the client as a transport error. The `.err` files are empty.

| Q | Question (short) | Baseline: answer, turns, s | Live: answer, turns, s | Verdict |
|---|---|---|---|---|
| 01 | births in 2024 | asked which definition; 3; 9 | gave both: 142,613 (`POP201H_judete`) and 148,916 (`POP201A_judete`); 6; 31 | Better (answers). One `query_timeout` on the first search, the model shortened the query and went on |
| 02 | registered unemployment 2025 | 3.3 % (`SOM103A`); 4; 11 | 3.3 %; 4; 14 | Same |
| 03 | Cluj 2023 | 1.2 % (`SOM103A_judete`), 4,182 persons; 4; 9 | 1.2 %, 4,182; 4; 17 | Same |
| 04 | top 5 population growth | Hănești +126.1 %, Vârfu Câmpului +97.0 %, Prisăcani, Moșnița Nouă, Oancea (`POP107D_grupe_localitate`); 6; 19 | same five, same values; 7; 27 | Same |
| 05 | 5 counties, fewest births | asked which definition; 3; 7 | asked which definition; 3; 8 | Same |
| 06 | latest monthly inflation | no total; May 2026 by 3 groups (`IPC102A`); 5; 12 | same; 5; 15 | Same |
| 07 | tourism intensity 2018-2019 | Vâlcea +0.43 (3.92 to 4.35), `tourism_intensity`; 5; 16 | same figures; 6; 14 | Same |
| 08 | population 2025 | about 21.75 M (`POP107D_grupe_localitate` 21,751,865; `POP107A_judete_grupe` 21,739,373); 7; 19 | same 21,751,865; second set named `POP107A_macroregiuni_grupe` (21,739,373); 8; 25 | Same numbers. Second dataset code differs, same value |
| 09 | teachers, Bucharest | no safe total; levels from `SCL104D_judet`; 7; 18 | no total; levels from `SCL104D_judet` and `SCL104E_judete`; 10; 27 | Same outcome. Slightly more turns |
| 10 | doctors per county 2023 | table, `SAN104B`, Bucharest 18,027; 12; 27 | table, `SAN104B`, Bucharest 18,027; 10; 29 | Same |

Summary: no regression in answer or number. Q01 improved. The run took 14-31 s per question, 10-30 % longer than the baseline on most
questions. Part of that is the benchmark running at the same time and part is the 3 times slower CPU. Tool calls on the server
(from `mcp-calls.jsonl`, all 68 calls since the cutover, so it includes earlier owner checks): `ok` 53, `partial` 6 (`unverified_total`), `needs_clarification` 4,
`unavailable` 5 (`query_timeout` 1, `conflicting_grain` 2, `query_budget` 1, `level_unavailable` 1). All of those are designed answers except the timeout.

## Risks and one finding to check

- At 00:24:15 UTC, `discover_indicators` for "număr nașteri vii în România în 2024" took 10.6 s and returned `query_timeout`
  (limit 10 s). A repeat query 6 s later took 4.1 s. A recipe call took 5.8 s and a `query_data` call 3.7 s. These calls ran while
  my benchmark child was starting on the same two cores. I could not run the live questions alone, so I cannot prove that the
  benchmark caused the timeout. An alone-run of the 15 new queries (step 3) had a maximum of 1.9 s.
  A real user with a cold cache and a busy host can get the same timeout. Suggest watching `query_timeout` in `mcp-calls.jsonl` during the observation week.
- The benchmark peak (294 MiB) comes from a 10-second mixed phase. A long scraper run plus Ask traffic is not covered.

## Step 5: proposed `MemoryMax`

- Observed cgroup peak of the live service: 283 MiB (`memory.peak` 297,123,840 bytes), after the benchmark, 10 live questions and 15 queries.
- Observed benchmark peak RSS: 294 MiB (highest lifetime value, five clients plus REST). I use this number because it is the higher one
  and it comes from a defined workload.
- 294 MiB plus 50 % is 441 MiB. Rounded up: **`MemoryMax=512M`**.
- Basis: benchmark peak RSS, not the cgroup peak. The cgroup counts 108 MiB of file cache that the kernel can drop. The RSS sum counts
  shared pages once for each process, so it is a safe upper bound.
- Optional: set `MemoryHigh=448M` to make the kernel reclaim early before the hard limit.
- Keep `1G` until Ask traffic is measured (see below). The limit kills the API, not the scrapers.
  A lower limit gives the scrapers more room on the 4 GB host; the host had 2.8 GB available during the test, so there is no pressure now.
- Not applied. The owner decides.

## What I assumed

- The 15 new queries were new to the cache. The log shows `cached: false` for them.
- The scrapers did not run during the window (load average 0.04-0.7).
- macOS numbers in the tables come from `aq-07-record.md` (profile 64/128, one thread). They are one run each.
- The Python loop is a rough proxy for CPU speed. It is not the same as DuckDB speed.
- The latency conclusion treats the page cache as warm because `buff/cache` was 2.5-3.2 GB and `bi` was low.

## What I could not measure

- A cold page cache on the VPS (needs `drop_caches`, root). The split between volume cost and CPU cost on the cold path is unknown.
- The exact effect of swap-in on first calls.
- `MCP_METRICS` and `ASK_METRICS` counts (no journal access for `pax`).
- Scraper memory peaks and the combined host peak. The Ask path (hosted or BYOK) under load.
- The 512 MiB container gate (`linux_512mib` is `not_run`; it is not needed for the VPS).
- A clean live-question run with no other load on the VPS.
- Client IP behind the tunnel (not in scope).

Cleanup: the two test copies under `~/hz3/` were deleted. `~/hz3/` keeps `bench/`, `bench.log`, `vmstat.log` and `disc.sh`.
