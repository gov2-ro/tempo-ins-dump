# PA-03 implementation record

Branch `pa/00-baseline`, generation `a6737a26…`. Recorded 2026-10-11. Not deployed.
Commit `ada6e1e` (plus deterministic ordering and feedback links in the PA-04
commit).

## What exists

- **Recipe** `app/data/recipes.json` → `tourism_intensity` v1:
  `stays(county, Y) / resident_population(county, 1 January Y)`. Sources are
  TUR105D_judete and POP105A_judete_grupe, each built by the shared query
  (aggregation policy + grain gate). It refuses unavailable, capped,
  time-windowed or approximated sources. Each source is reduced to one row per
  (exact-label county id, year), with duplicates refused before the join.
  Declared unit multipliers are applied. The year is the latest year both
  sources have, or the requested one if both have it. Exclusions carry
  reasons: `numerator_missing`, `denominator_missing`,
  `denominator_not_positive`, `nonfinite`, `not_in_denominator`, `not_in_data`.
- **API**: `/api/recipes`, `/api/recipes/{id}?year&areas&lang`, and
  `/api/recipes/{id}/evidence`.
- **Page**: `compare.html?recipe=tourism_intensity[&year=][&areas=]`. It shows
  the definition, the review status, a latest/fixed year choice, a chart with
  title/unit/source and PNG export, and a table with stays, population and
  intensity (3 decimals, display only). It also lists exclusions, links each
  source to its exact year slice, and offers the generation id, a copy-link
  button, evidence download and a report link.
- **Evidence bundles** (`tempo-evidence/1`), for a recipe or any `/data`
  selection. Contents: `manifest.json` (schema, created_at, app version,
  query contract, generation, sha256 of every file), `selection.json`,
  `result.csv` (unrounded), `method.json`, `attribution.json` (sources,
  update dates, citation; reuse terms marked unverified), `README.txt`.
  Recipes add `inputs/stays.csv`, `inputs/population.csv` and
  `recompute.py`. Aggregated single-source answers add
  `inputs/observations.csv`. Selections too large are refused with 413,
  never cut.
- **Search/home**: the reviewed concept `tourism_intensity` (e.g. "înnoptări
  pe locuitor", "stays per resident") leads to the recipe with the parsed
  counties/year. The guided Q4 question now asks per resident.
- **Per-capita tiles** use the same-year population only. Rows without one are
  dropped and counted on the tile; the old fallback that showed raw counts
  under a per-1,000 label is gone.

## Checks

| Check | Result |
|---|---|
| Spec synthetic table (ratio/ranking, multiplier, zero, missing/invalid reasons, duplicates, different latest years, exact-name join, refused/capped sources, unknown unit) | `tests/test_pa03_recipe_evidence.py`: all pass |
| Real 2024 result vs PA-00 Q4 record | All 42 counties equal at 3 decimals (corpus-marked test) |
| Offline recomputation | `recompute.py` from a downloaded bundle: "recomputed 42 rows; 0 differ" (real), 2/2 (fixture); hashes verified |
| Single-source bundle | Cluj resident population: 14 result rows, 1,008 input observations; each result equals the sum of its inputs (fixture assertion) |
| Old vs new generation | Bundle manifest keeps its generation; a live link reports the current one |
| Browser | Search → recipe → evidence download → year change → three-county subset at 1280 and 390 px; no page errors, no overflow |

## Remaining restrictions

- **Not yet verified:** the Q4 county denominators against INS cells (the
  fetch is pending; INS offline). The recipe page shows this status.
- **Comparison:** no compatibility preview for arbitrary pairs; the recipe is
  the one reviewed join.
- **Evidence for the dataset page:** it follows the selection headline's
  query (time series of the selection), not every tile's view.
- **Reuse terms:** INS's terms are not asserted in bundles until verified.
