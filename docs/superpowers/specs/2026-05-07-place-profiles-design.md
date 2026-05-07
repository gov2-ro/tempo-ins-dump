# Place Profiles — Design Spec

**Date:** 2026-05-07  
**Status:** Approved for implementation

---

## Context

The INS TEMPO explorer surfaces ~3,700 datasets but has no cross-cutting view of a *place*. Users who care about a specific county or region must hunt across datasets individually. Place profiles give every county, region, macroregion, and locality a dedicated page showing key trends and comparisons — shareable by URL, consistent in structure, discoverable via a "Places" nav link.

---

## Scope

**Geographic levels covered:**
- 42 counties (județe)
- 8 development regions (NUTS-2)
- 4 macroregions (NUTS-1)
- Localities — included with graceful degradation (show whatever data exists; no hard failure for sparse places)

**Not in v1:** population-normalisation toggle on absolute-count charts (added to backlog).

---

## URL Structure

```
/places                         → directory listing
/place/county/bihor             → county profile
/place/region/nord-vest         → region profile
/place/macroregion/nord         → macroregion profile
/place/locality/oradea          → locality profile (graceful degradation)
```

Slugs: lowercase, diacritics stripped, spaces → hyphens. Same normalisation already present in `dimension_options_parsed.cleaned_name`.

---

## Page Structure

Three stacked sections, in order:

### A — KPI Heroes
Breadcrumb (`Romania › Nord-Vest › Bihor County`) + place name + geo-level badge + dataset count.

Below: 6–8 curated KPI cards (curated per geo level, see config below). Each card shows:
- Latest value + unit
- YoY delta (▲/▼ with colour)
- 10-year ECharts sparkline (mini line chart, reuses `chart-factory.js`)

Localities show whichever KPIs have data; missing ones are omitted entirely.

### B — Indicator Grid
Category filter chips (All / Population / Economy / Health / Education / …). Below: a grid of small trend cards, one per dataset that has data for this place. Each card: dataset title + sparkline. Cards with no data are shown faded with "no data" label.

Clicking any card navigates to `/dataset/{code}?place={slug}` — the existing dataset page, pre-filtered.

### C — Comparison
Always-on baseline chips: **National average** + **{parent region} average** (cannot be removed).

Below those, two peer suggestion groups:
- **Same region:** sibling counties/places at the same geo level, sorted by population
- **Similar size:** 3 closest matches by population nationally

Clicking a peer chip fetches its API data and overlays its series on the comparison chart. 2 always-on baselines + up to 3 optional peer overlays = 5 series maximum (keeps the chart readable).

Comparison chart: ECharts multi-line chart for the **currently selected indicator** (defaults to first KPI; clicking any KPI card or grid item switches focus). Y-axis label shows unit.

---

## New Files

| File | Purpose |
|------|---------|
| `app/routers/places.py` | Two routes: HTML page + JSON API |
| `app/services/place_service.py` | All aggregation logic |
| `app/static/data/place_kpi_config.json` | Curated KPI sets per geo level |
| `app/static/places.html` | Directory listing page |
| `app/static/place.html` | Profile page shell |
| `app/static/js/places-page.js` | Directory page controller |
| `app/static/js/place-page.js` | Profile page controller |

**Existing files modified:**
- `app/main.py` — include new `places` router
- `app/static/datasets.html` — add "Places" nav link

---

## Backend Design

### Routes (`app/routers/places.py`)

```
GET /places                      → serves places.html
GET /place/{type}/{slug}         → serves place.html
GET /api/places                  → list all places {type, slug, name, parent}
GET /api/places/{type}/{slug}    → full profile JSON (see shape below)
```

### API Response Shape

```json
{
  "place": {
    "name": "Bihor", "type": "county", "slug": "bihor",
    "parent": { "type": "region", "slug": "nord-vest", "name": "Nord-Vest" }
  },
  "kpis": [
    {
      "label": "Population", "dataset_code": "POP101A",
      "value": 576000, "unit": "persons",
      "change_yoy": -1.2, "sparkline": [...]
    }
  ],
  "datasets": [
    {
      "code": "POP101A", "title": "...", "category": "Population",
      "has_data": true
    }
  ],
  "peers": {
    "same_region": [
      {"slug": "cluj", "name": "Cluj", "type": "county"}
    ],
    "similar_size": [
      {"slug": "timis", "name": "Timiș", "type": "county"}
    ]
  }
}
```

### `place_service.py` Logic

1. **Resolve place** — look up slug in `dimension_options_parsed` (normalised name match) to get the dimension option ID and parent chain.
2. **KPI data** — for each entry in `place_kpi_config.json`: call `query_builder` with `filters={REF_AREA: [option_id], TIME_PERIOD: last_10_years}`, extract latest value + sparkline. Missing data → `null` (card omitted on frontend for localities, shown faded for fixed levels).
3. **Dataset list** — query `dimension_options` joined to `dimensions` joined to `matrix_profiles` to find all datasets that include this place's option ID. Return with category from `matrix_profiles.category`.
4. **Peers** — from `dimension_options_parsed`: siblings = same `geo_level` + same parent region; similar size = all places at the same level sorted by |population - this_population|, top 3 excluding self. Population sourced from the Population KPI query result (cached within the request). For localities where the Population KPI returns no data, fall back to sibling-only peer group (omit the "similar size" group rather than error).

Reuses existing: `app/services/query_builder.py`, `app/db.py` cursor pattern.

### `place_kpi_config.json` Structure

```json
{
  "county": [
    { "label": "Population", "dataset_code": "POP101A", "dim_filter": {}, "unit": "persons" },
    { "label": "Unemployment", "dataset_code": "SOM101A", "dim_filter": {}, "unit": "%" },
    { "label": "Avg. net wage", "dataset_code": "FOM101B", "dim_filter": {}, "unit": "lei" },
    { "label": "Birth rate", "dataset_code": "DEM101A", "dim_filter": {}, "unit": "‰" },
    { "label": "Death rate", "dataset_code": "DEM102A", "dim_filter": {}, "unit": "‰" },
    { "label": "Net migration", "dataset_code": "MIG101A", "dim_filter": {}, "unit": "persons" }
  ],
  "region": [
    { "label": "Population", "dataset_code": "POP101A", "dim_filter": {}, "unit": "persons" },
    { "label": "GDP/capita", "dataset_code": "REG101A", "dim_filter": {}, "unit": "lei" },
    { "label": "Employment rate", "dataset_code": "FOM102A", "dim_filter": {}, "unit": "%" },
    { "label": "Avg. net wage", "dataset_code": "FOM101B", "dim_filter": {}, "unit": "lei" }
  ],
  "macroregion": [
    { "label": "Population", "dataset_code": "POP101A", "dim_filter": {}, "unit": "persons" },
    { "label": "GDP/capita", "dataset_code": "REG101A", "dim_filter": {}, "unit": "lei" },
    { "label": "Employment rate", "dataset_code": "FOM102A", "dim_filter": {}, "unit": "%" }
  ],
  "locality": []
}
```

Dataset codes are placeholders — actual codes confirmed during implementation by querying the catalog.

---

## Frontend Design

`place-page.js`: single class `PlaceProfileApp`, initialised on `DOMContentLoaded`. One `fetch('/api/places/{type}/{slug}')` call, then renders all three sections. No framework.

`places-page.js`: fetches `/api/places` and renders a grouped directory (counties alphabetically, then regions, then macroregions). Static enough that it could also be pre-rendered, but dynamic fetch keeps it consistent.

Chart strategy:
- KPI sparklines: ECharts line, `height: 40px`, no axes, no tooltip — pure shape
- Comparison chart: ECharts multi-line, full axes, tooltip with all series, legend
- Grid cards: same mini sparkline as KPIs

Reuses: `chart-factory.js` (line chart builder), existing CSS variables/dark theme.

---

## Navigation Integration

- `app/static/datasets.html` nav bar: add "Places" link → `/places`
- No changes to choropleth or dataset pages in v1

---

## Backlog Items (deferred from this spec)

- **Norm by population toggle**: on any chart showing absolute counts (births, deaths, crimes, etc.), add a "per 1,000 population" toggle. Requires population lookup for the place + year.
- **Choropleth click-through**: clicking a county on a map navigates to its place profile
- **Dataset page "View {place} profile" link**: when filtered to a county

---

## Verification

1. Start dev server: `uvicorn app.main:app --reload --port 8080`
2. Navigate to `http://localhost:8080/places` — directory shows all counties, regions, macroregions
3. Click a county → `/place/county/bihor` — three sections render; KPI cards show values with sparklines
4. Click a KPI card → comparison chart switches focus indicator
5. Click a peer chip (e.g., "Cluj") → series overlaid on comparison chart
6. Navigate to a small locality → graceful degradation: missing KPI cards omitted, grid shows "no data" for unavailable datasets
7. Check `GET /api/places/county/bihor` directly — JSON shape matches spec
8. Run `tempo_eval_chart_selector` MCP tool — no regressions in existing chart scoring
