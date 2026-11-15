# AQ-07 — Public MCP footprint: memory, first-call cost and period bounds

**Status: ready (2026-11-15). 07A first, then 07B.** Written by Opus for a Sonnet session.
No deployment, production setting or generation change is authorized here.

## Why this package exists

The public MCP was not promoted because it failed on Fly: `discover_indicators` ran past the
10 s deadline (`INTERRUPT Error: Interrupted!`). On a Mac the same tool has a median of 47 ms.
The code is not slow. The 512 MB Fly machine probably starves the process. These measurements
support that hypothesis (2026-11-15, generation `062bd2b0`, macOS, `TEMPO_DB_THREADS=1`):

| Observation | Value |
|---|---|
| RSS after imports and opening `metadata.duckdb` | 61 MB |
| RSS after the first `discover_indicators` call | 283 MB |
| RSS after five tool calls, no web server | 375 MB |
| Python heap (tracemalloc) after the first call | 35 MB |
| DuckDB `memory_limit` sum: metadata 160 MB + search 192 MB + scratch 128 MB | 480 MB |
| Import time of pandas (with numpy, pyarrow) inside the first `discover_indicators` call | 0.39 s |
| `describe_dataset` local latency: median / p90 / max | 0.62 / 1.75 / 2.42 s |

Most of the memory is native (DuckDB buffers, library code), not Python objects. The DuckDB
caps alone almost fill the machine. `metadata.duckdb` is 617 MB and `search.duckdb` is 50 MB.

Required outcome: the MCP server process stays well inside 512 MB under the benchmark workload,
the first call after start does not pay avoidable import cost, and `describe_dataset` does not
scan a whole parquet file twice to find its period bounds. Answers must stay identical.

## Read these files

- `app/db.py` (`get_conn`, `scratch_conn`, budgets), `app/services/dataset_search.py:70-95`
  (the search connection and its 192 MB default).
- `app/services/data_query.py` `dimension_values` (about lines 555-595): `period_bounds`.
- `app/services/tools/discovery.py` (describe path, `period_bounds` use near line 1286 and
  1452), `app/services/tools/query.py:619` (`period_bounds`).
- `scripts/benchmark-mcp.py` (`run --mode local`; it reports process-tree peak RSS),
  `scripts/serve-mcp-test.sh`, `scripts/deploy/fly/mcp-public.env`.
- [AQ-01](01-mcp-capacity.md) for the measurement rules. Do not repeat its work.

## 07A — Memory budget and first-call imports

1. **Baseline.** Run `scripts/benchmark-mcp.py run --mode local` on the repo's `data/` with
   the operator profile (`TEMPO_MCP_MAX_SCAN_ROWS=5000000`, `TEMPO_DB_THREADS=1`). Record peak
   RSS per scenario, latency per tool and the first-call latency after a fresh start.
2. **First-call imports.** Find which code imports pandas (and so numpy and pyarrow) on the MCP
   path. Use `python -X importtime`. If the import comes from a convenience call (for example
   `.df()` or `.fetchdf()` where tuples suffice), replace it on the MCP path. Do not remove
   pandas from code paths that need it (exports, insights). If removal is not small and local,
   stop and report the call site instead.
3. **DuckDB budgets.** Measure peak RSS and latency with smaller budgets. Try at least:
   `TEMPO_SEARCH_MEMORY` 64 MB and 32 MB; `TEMPO_DB_MEMORY` 128 MB and 96 MB. Scratch is used
   only by place profiles; record whether the MCP workload opens it. Keep every answer identical:
   compare the benchmark's result hashes with the baseline run.
4. **Profile.** Write the chosen budgets into `scripts/deploy/fly/mcp-public.env` with the
   measured numbers in a comment. Do not change the app defaults in `app/db.py` or
   `dataset_search.py`; developer machines keep them.

Acceptance:
- A before/after table: peak RSS, first-call latency, p50/p90 per tool, refusals, result hashes.
- Identical results for every benchmark case. A refusal that appears only under the smaller
  budget (for example a DuckDB out-of-memory error) rejects that budget.
- macOS RSS is not Linux cgroup memory. Report the Linux 512 MB check as `not_run`.

## 07B — Period bounds without a second full scan

`dimension_values` runs `SELECT DISTINCT` on the time column, then a second query over the whole
file for `min`, `max` and `count(DISTINCT)` where the value is not NULL. On POP107D (22.3M rows)
this costs 1.8-2.4 s cold (audit finding MCP-04).

Preferred approach: compute the bounds from the first query's result when the value column
holds no NULL. Stage 9 never writes NULL, and the parquet footer's `null_count` for the value
column proves it per file without a scan. When the footer shows NULL values, or the file has a
legacy shape, keep the current query. The sort must match the current SQL comparison: both
compare `VARCHAR` values.

Do not add a new generation artifact, pipeline step or manifest field. If the preferred approach
cannot reproduce the current bounds exactly, stop and report the cases that differ.

Acceptance:
- Tests on temporary parquet fixtures: no NULL values (fast path), NULL values (current query),
  a legacy-shaped file, and a time column whose values sort differently as numbers and as text.
- `period_bounds` is identical to the current output for every served dataset with a time
  column. Compare all of them read-only, and record the count and the generation.
- `describe_dataset` latency on POP107D before and after, cold and warm.
- `tools/static-engine/parity.mjs` and `api-parity.mjs` still pass (`tests/test_static_parity.py`).
  `data_query` is in the static-site parity scope.

## Out of scope

Hosting (Fly size, the Hetzner VPS), the scan cap, the deadline, discovery quality, the
answer-quality eval, deployment. Report findings about them; do not change them.

## Done

Targeted tests, then `python -m pytest tests -q` once (never two full suites in parallel).
Write `aq-07-record.md` in this folder with the measurements, the assumptions and the commit.
Add an activity-history entry. Stop for Opus review before merging.
