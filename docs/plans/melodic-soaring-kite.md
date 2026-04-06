# SDMX Dataflow Link — Decision

## Recommendation: Skip it

Header already has: INS ↗ · SDMX ↗ · ↓ CSV · ↓ XLSX

The dataflow endpoint (`/sdmx/2.1/dataflow/INS/{code}/1.0`) is structural metadata for SDMX developers — they can derive it from the data URL. Adding a dedicated button clutters the header for minimal gain.

**If user wants it anyway**: add a dropdown under "SDMX ↗" in `renderDashHeader()` in `app/static/js/explore-app.js` with two items (Data / Dataflow).
