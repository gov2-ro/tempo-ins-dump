# CP — Profile pages for the large cities

Brief for a Sonnet session. Written by Opus on 2026-11-25.

## Why

The "Locuri" (Places) page lists only counties, regions and macroregions. Users expect cities.
The owner asked for city pages, at least for the cities with more than 200,000 inhabitants.

## What exists

- `app/routers/places.py` already accepts the `locality` type: `/place/locality/{slug}` and
  `/api/places/locality/{slug}` answer. For example, `municipiul-cluj-napoca` returns 159 datasets
  and peers, but no KPI cards.
- `/api/places` lists only `county`, `region` and `macroregion`. Its SQL filters the other levels out.
- `app/static/data/place_kpi_config.json` has `"locality": []`. `get_place_kpis` returns `[]` for localities.
- In static mode, `app/static/js/engine/static-api.js` and `scripts/static_api.py` answer the place
  routes. `tools/static-engine/api-parity.mjs` checks them against Python.

## Decisions (Opus)

1. **Scope:** municipalities with a resident population of at least 200,000 in the latest year.
   Expected list: Cluj-Napoca, Iași, Timișoara, Constanța, Craiova, Brașov and Galați. Confirm it from
   the data. Do not hard-code it from this brief. Bucharest is already a place (`Municipiul București`).
   Link it from the new section; do not duplicate it.
2. **List:** one curated list in `app/static/data/place_kpi_config.json` (for example
   `"featured_localities": [{"slug", "siruta", "name"}]`), with the threshold and the year written beside
   it. `/api/places` adds these entries with `type: "locality"`. Do not list every locality.
3. **KPIs:** fill `"locality"` only with indicators that exist at UAT level and pass the same gates as
   the county KPIs: `grain_guard.check_slice`, one level per dimension (`dimension_structure`), and
   `scripts/check-kpi-totals.py` where INS publishes the total. Omit an indicator that fails. Do not
   show a doubtful number. Candidates to check: population by domicile, live births, deaths,
   registered unemployed, employees, dwellings, tourist arrivals.
4. **Page:** `places.html` gets a "Orașe mari" / "Large cities" section above the counties.
   `place.html` must show the parent county for a city.
5. **Nav label:** keep "Locuri". It becomes accurate once the cities are listed.

## Out of scope

All the other localities, a city search, and new charts on the place page.

## Acceptance

- `python -m pytest tests -q` passes. Add a test on a small synthetic fixture for the
  `featured_localities` listing and for one locality KPI.
- `tests/test_static_parity.py` passes. The static engine returns the same `/api/places` list and
  locality profiles as Python.
- A browser smoke of `/places` and two city pages (console and network clean), on desktop and on a
  375 px viewport.
- Report each KPI you kept or omitted, with the reason and its value checked against INS.

## Stop and ask

Stop and ask if a KPI needs a pipeline change, a new dataset, or a change to `place_service`
rules for counties.
