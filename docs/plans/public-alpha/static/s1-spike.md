# Static deployment, S1 spike results (2026-10-11)

Plan: [plan.md](plan.md) (owner decision: fully static on shared hosting, with
the query rules ported to JavaScript and proven against Python). Commit `b6d3d3d`.
Generation `a6737a26…`. **S1 checkpoint: go/no-go requested from the owner.**

## Parity (the guarantee)

| Corpus | Cases | Identical | Notes |
|---|---|---|---|
| Real: POP105A_judete_grupe, FOM106F, SOM103A_judete, TUR105D_judete, TUR105E_judet (conflicting grain), POP107D, POP107D_varste_judet, POP107D_varste_localitate, POP107D_grupe_localitate | 485 | 476 | 9 cases where DuckDB ran out of memory on the slice check (Python: `grain_unverified/slice_check_failed`); the engine names the real problem (`conflicting_grain`). Both refuse. No other difference |
| Synthetic (CI): POPX, ADDX, RATEX, INCX, DUPX, EQX | all | all | plus a forced-partition build of RATEX/POPX: identical |

Cases include every composed dashboard tile, the headline series, a seeded fuzz
(group_by subsets, single/multiple/total/unknown filter values, empty lists,
`approximate`, limit 3 truncation) and invalid inputs (unknown columns,
malformed shapes, null filters, limit 0), with messages compared verbatim.

A side effect is a fix: identical requests could return equal-key rows in a
different order, so `query_builder` now ends every ORDER BY with the value.

## Size and build (full corpus, all 3,376 served datasets)

| Part | Files | Size |
|---|---|---|
| Single-file datasets (3,336) | 3,336 | 51 MB (median 1.7 KB, p90 27 KB, max 0.6 MB) |
| 40 datasets > 200k rows, split by county and by period | 6,266 | 421 MB (median 13 KB, max 0.9 MB per file) |
| Policy contexts | 3,376 | 68 MB (median 7 KB) |
| **Total** | **13,019** | **542 MB**; build time 8 min |

Not yet included: recorded page JSON (meta/insights/related × ro/en, places,
recipe) and pre-rendered pages. Expect roughly 25k files more.

## Speed (real browser, 390 px)

| Query | Desktop | Phone (4× CPU throttle, 4G) | Downloaded |
|---|---|---|---|
| POP105A Cluj by year | 34 ms | 246 ms | 0.11 MB |
| FOM106F by year × activity | 27 ms | 146 ms | 0.05 MB |
| TUR105D 2024 by county | 20 ms | 142 ms | 0.06 MB |
| POP107D (21.6M rows) Cluj by year × age | 64 ms | 1.28 s | 1.17 MB |
| POP107D_varste_localitate Cluj by year | 83 ms | 0.84 s | 0.64 MB |
| POP107D whole country by year | 2 ms | 2 ms | 0 (refused before download: source total mismatch) |

## Open points for S2+

- Policy files can be gzipped (68 → ~10 MB).
- The browser loader keeps every table it has loaded; add an LRU before
  wiring the pages.
- Unfiltered whole-country raw queries on the largest family download
  everything (~50 MB). The same rules as the server apply, but the cost moves
  to the visitor. Consider refusing above a byte budget, which the server
  would not do (a documented divergence).
