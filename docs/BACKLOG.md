# Backlog

Future tasks and intentions for the TEMPO INS data explorer.

## SDMX / Multi-Source

- [ ] **Phase 5: NL2SQL preparation** — Generate per-dataset JSON schema files, create
  DuckDB views for all parquet-v3 files, build corpus description for LLM context.

- [ ] **Phase 6: Multi-source adapter** — Eurostat/OECD data ingestion alongside INS data.
  Design `dataset_registry` table, build Eurostat SDMX-CSV adapter.

- [ ] **English parquet-v3 generation** — Run `12-parquet-to-sdmx.py --lang en` to
  produce English-language SDMX parquets. Requires English `sdmx_codes` entries
  (display_label_en already partially populated).

- [x] **Clean up stale split profile files** — Done.
  Moved 1,150 stale profiles to `_stale/`: 736 parent profiles (parquets replaced by children),
  414 with `_nom_id` column refs. Fixed `dim_column_name` in DuckDB for 414 v2 splits
  (old `_nom_id` → SDMX names like `TIME_PERIOD`, `REF_AREA`). Regenerated 414 view profiles.
  Script: `scripts/cleanup-view-profiles.py`.

## Data Pipeline

- [ ] **Replicate geo_hierarchy split for English (`eng`) parquet files**
  Pattern F splits are done on `ro` only. Since `nom_item_id` values are shared across
  languages, the same ID sets detected from `ro` can be reused. Low effort once the ro
  run is stable.

- [ ] **Handle `Municipii si orase` (4 datasets) — Pattern G**
  321 values mixing municipalities and towns in a single dimension. Potential split:
  `_municipii` and `_orase`. Affects: AGR*, TLC* and others.

- [ ] **`Macroregiuni si regiuni de dezvoltare` (60 datasets)**
  2-level variant of geo_hierarchy (no counties). Already handled by Pattern F
  (emits `_regiuni` + `_macroregiuni`), but worth verifying output quality separately.

## UI / App

- [ ] **v2 UI build** — see `docs/app-spec-v2.md` for full spec

- [x] **Choropleth: support region-level map** (`_regiuni` sub-datasets)
  Done — region + macroregion GeoJSON files generated, multi-level choropleth in chart-geo.js.

- [x] **Dataset page: show split siblings**
  Done — sub-dataset bar with pills in dataset-page-v2.js, variant drawer in datasets-page.js.

### Lens UI Improvements

- [ ] **Add `lang` to `get_dataset()` endpoint** — dashboard dataset names are stuck in Romanian
  when EN is selected. Add `lang` param, use `COALESCE(matrix_name_en, matrix_name)`.

- [ ] **Responsive mobile layout** — 3-column category grid and 4-column insight cards don't
  adapt well to phones. Add `@media (max-width: 768px)` breakpoints for stacking.

- [ ] **Filter persistence across navigation** — navigating away and back to the same dataset
  resets filters. Could persist filter state to URL params for shareability.

- [ ] **Loading states for chart switching** — clicking a chart type pill shows no transition.
  A brief loading indicator while new data arrives would feel snappier.

- [ ] **Dataset definition/methodology panel** — metadata has `definitie` and `metodologie`
  fields not shown in Lens. Expandable info panel below the header would add context.

- [ ] **Keyboard shortcuts legend** — Lens supports `/`, `Cmd+K`, arrow keys but there's no
  discoverable way to learn about them beyond the search footer hints.

- [x] **Category breadcrumbs** — Done. Clickable breadcrumb trail with nested subcategory
  drill-down (▸ rows), back button shows parent name. Stack-based navigation.

- [x] **Smarter large dataset handling** — Done. Auto-applies first non-TOTAL filter for
  datasets >50k rows. Shows amber warning banner. Retries on filter-required errors.

- [ ] **URL deep-linking for filters** — encode filter state in URL so dashboard views
  can be shared with specific filters pre-applied.

- [ ] **Secondary chart lazy loading** — render secondary charts only when they scroll
  into view to improve initial load performance.

- [x] **Trend indicators on category cards** — Done. Green/red bar showing proportion of
  increasing vs decreasing datasets, plus avg YoY% growth. New `/api/categories/trends` endpoint
  aggregates `dataset_trends` via `UNNEST(ancestor_codes)`. Works for all context levels.

## Data Accuracy — Server-Side Aggregation

- [x] **Server-side GROUP BY for chart queries** — Done.
  Frontend sends `group_by` param with chart-relevant dimension columns. Backend
  `query_builder.py` generates `SELECT dims, SUM(OBS_VALUE) ... GROUP BY dims`.
  Table view sends raw queries (no GROUP BY). Typical reduction: 99%+ for large datasets
  (e.g., EXP102J: 18,225 → 168 rows). Files: `query_builder.py`, `dataset_data.py`,
  `api.js`, `dataset-page-v2.js`.

- [x] **Non-summable values** — Done.
  `query_builder.py` accepts `agg_func` param (SUM or AVG). `dataset_data.py` looks up
  `matrix_profiles.primary_unit_type` — uses AVG for `percentage` (694 datasets) and
  `time_unit` (12 datasets), SUM for everything else.

## Data Quality

- [x] **Phase 8: Strip aggregate/total rows from parquet files** — Done.
  49 parquet files stripped of 28,280 aggregate rows (Total in SEX, AGE, RESIDENCE, REF_AREA).
  Scripts: `scripts/detect-totals.py` (detection + decisions), `scripts/strip-totals-from-parquet.py`
  (apply to existing parquets), `12-parquet-to-sdmx.py --strip-totals` (integrated pipeline).
  Handles mutually exclusive breakdowns via intersection mode (only strips grand-total row).
  Decisions stored in `data/logs/total-decisions.json`.

- [ ] Review `docs/TODO_COMPACTION.md` — label normalisation issues in 7-data-compactor.py
