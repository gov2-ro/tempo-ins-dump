# Static S2 — full-corpus build and parity (2026-10-11)

Built from the copied generation `a6737a263a34`. Read-only on the corpus.

## Parity

`gen-parity-cases.py --per-dataset 8` recorded the Python answers for every
served dataset: tile queries, the headline series, seeded fuzz, and invalid
inputs. `parity.mjs` replayed them through the browser engine.

| | Cases |
|---|---|
| Total (3,376 datasets) | 70,708 |
| Identical (errors, decision, columns, rows, order, flags; values to 1e-9) | 70,663 |
| Python refused on resources (`slice_check_failed`), engine answered | 4 |
| Engine refused over the 12 MB browser budget (`browser_budget`) | 34 |
| Mismatch | 7, all ART124A (fixed below) |

The 7 mismatches were a **server bug**, not a port bug. ART124A's parquet
carries canonical columns (`FILME`, `TIPURI_DE_FILME`). Its `dimensions` rows
still say `filme_nom_id`/`tipuri_de_filme_nom_id`, and `sdmx_column_map` has no
pair for them. So the SQL binder failed and the API answered a 500 "Query
failed". `run_query` now refuses such a file with `unavailable`, reason
`schema_mismatch`, naming the column. The engine reads the same flag from the
policy file, and a synthetic stale dataset covers it in `test_static_parity.py`.
On this generation, ART124A is the only dataset affected. Re-checked: 43/43
cases pass on ART124A plus a control.

## Browser budget

A query is refused, never cut, when the files it needs exceed
`build.max_query_bytes` (12 MB, set with `--max-query-bytes`):
- the response is `unavailable` with reason `browser_budget` and
  `budget: {bytes, max_bytes}`;
- the check runs before any download;
- the loader picks whichever partition set (by county or by period) needs fewer
  rows.

This is a documented divergence from the server, which would answer. All 34
refusals are unfiltered or whole-country reads of the partitioned families
(POP107D/108D, SOM101E/F, PPA101A, TUR10x localities). The loaded-table cache is
an LRU of 48 tables.

Follow-ups (owner suggestions, not built):
- default the big families' pages to the latest N years;
- precompute the county × year aggregates those pages ask for.

Both would turn most of these refusals into answers.

## Size (unchanged from S1's full build)

13,019 files, 542 MB:
- data 473 MB;
- policies 68 MB, about 10 MB once gzipped (not yet done).

The largest file is 0.9 MB, and none exceed 2 MB. 40 datasets are partitioned.
Build 9 min, case recording 6.5 min, Node replay 76 s.
