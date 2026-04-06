# Backlog

Future tasks and intentions for the TEMPO INS data explorer.

## Misc
- [x] enhance table view
- [ ] more, nice themes - mai light a bit off-white, Financial Times, or Anthropic, lighter dark theme
- [x] add dataset code to explorer
- [x] add flags to language switcher
- [x] add disclaimer, not official gov.ro site
- [x] add data download option, csv/xlsx?
  - [ ] disseminate data. Kaggle, Hugging face? Check legal?
- [ ] should we split repos, data fetching, UI? - so we make a dataset independent SDMX UI framework?
- [ ] responsive
- [ ] fetch newly updated datasets
  - [ ] continuous fetching, gh actions?
- [ ] Look for same EU stats?
- [ ] large datasets show no data: LOC108B
- [x] detect ro/intl -> language. (`?lang=en` URL param)
- [ ] translate, Hu/De

## Landing
- [x] Show latest updates
- [x] Flag interesting datasets
- [x] Some widgets per theme/subtheme/dataset

## misc
- [ ] sustainable development 2020 should be archived?

## Chart rules
- [ ] for long horizontal bar charts, prever vertical view
- [ ] bar charts, order by value
- [ ] if just 2 dimensions, don't give options to choose (axis, group), just to swap, transpose. 

## SDMX / Multi-Source

- [ ] **Phase 5: NL2SQL preparation** — Generate per-dataset JSON schema files, create
  DuckDB views for all parquet-v3 files, build corpus description for LLM context.

- [ ] **Phase 6: Multi-source adapter** — Eurostat/OECD data ingestion alongside INS data.
  Design `dataset_registry` table, build Eurostat SDMX-CSV adapter.

- [ ] **English parquet-v3 generation** — Run `12-parquet-to-sdmx.py --lang en` to
  produce English-language SDMX parquets. Requires English `sdmx_codes` entries
  (display_label_en already partially populated). *comment*: English data is the same data, we might only need to use the original Romanian ones and use the English metas.

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

## Static Site Migration

- [ ] **Phase 2: DuckDB-WASM data client** — Test `duckdb-data-client.js` against real
  parquet files, verify HTTP range requests work with CORS, compare output with
  FastAPI `/data` endpoint. Handle edge cases (missing parquet, WASM not supported).

- [ ] **Phase 3: Port frontend components** — Copy/adapt `explorer/static/js/` chart
  modules and Vue components to `static-site/js/`. Wire up to `api-static.js`.
  Main files: `DatasetPicker.js`, `ChartCanvas.js`, `FilterBar.js`, `LeftSidebar.js`.

- [ ] **Phase 4: Deploy pipeline** — GitHub Actions workflow: run `build-static-site.py`,
  upload JSON to Cloudflare Pages, upload parquet to R2. Service Worker for offline caching.

- [ ] **Phase 5: Retire FastAPI app** — Archive `app/`, `duckdb-browser.py`, update CLAUDE.md.

- [ ] **Aggregation in DuckDB-WASM** — Port the GROUP BY aggregation fix (from backlog
  "Raw LIMIT truncation" issue) into `duckdb-data-client.js`. Easier in WASM since
  the full query builder is in JS.

## UI / App

- [x] **v2 UI build (Lens)** — Two-panel dashboard shipped: Trends (line/area/stacked over time) +
  Snapshot (grouped bar/heatmap/bubble/choropleth/bar for single period) with period navigator
  and play animation. Category browse, search, theme toggle, i18n all working.
  Remaining: data table, export, responsive polish, URL state.

- [x] **Choropleth: support region-level map** (`_regiuni` sub-datasets)
  Done — region + macroregion GeoJSON files generated, multi-level choropleth in chart-geo.js.

- [x] **Dataset page: show split siblings**
  Done — sub-dataset bar with pills in dataset-page-v2.js, variant drawer in datasets-page.js.

### Lens UI Improvements

- [ ] **URL state persistence** — persist filters, chart type, and selected period in URL. Also, language.
  so dashboard views are shareable/bookmarkable (e.g. `?code=POP301A&period=2020&snap=heatmap`).
  Currently only `?code=` is saved; filter/chart/period selections reset on reload.

- [x] **Data table toggle** — Done. Collapsible data table with dropdown column filters,
  zebra striping, sticky headers, filtered/total row count. Client-side filtering via
  exact match on dimension columns.

- [ ] **Visual polish pass** — x-axis label truncation on rotated labels, responsive
  breakpoints for mobile (category grid, insight cards, chart panels), smooth transitions
  between chart type switches.

- [x] **Export** — CSV/XLSX download of filtered data with language support.
- [ ] **Export** — PNG export of charts.

- [ ] **Add `lang` to `get_dataset()` endpoint** — dataset names in the dashboard header still
  show in Romanian when EN is selected. Add `lang` param, use `COALESCE(matrix_name_en, matrix_name)`.

- [ ] **Responsive mobile layout** — 3-column category grid and 4-column insight cards don't
  adapt well to phones. Add `@media (max-width: 768px)` breakpoints for stacking.

- [ ] **Monthly → yearly aggregation toggle** — For datasets with monthly data,
  add an option to aggregate values by year (SUM for counts, AVG for rates/indices).
  Useful for long time series (20+ years of monthly data = 240+ points) where
  yearly trends are easier to read.

- [ ] **Keyboard shortcuts legend** — Lens supports `/`, `Cmd+K`, arrow keys but there's no
  discoverable way to learn about them beyond the search footer hints.

- [x] **Loading states for chart switching** — Done. Chart containers show loading state with
  opacity transitions during re-render.

- [x] **Dataset definition/methodology panel** — Done. Collapsible info panel below header
  shows definition, methodology, and notes from metadata.

- [x] **Category breadcrumbs** — Done. Clickable breadcrumb trail with nested subcategory
  drill-down (▸ rows), back button shows parent name. Stack-based navigation.

- [x] **Smarter large dataset handling** — Done. Auto-applies first non-TOTAL filter for
  datasets >50k rows. Shows amber warning banner. Retries on filter-required errors.

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

## Chart Selection — Future Improvements

- [ ] **Treemap chart type** — For hierarchical categorical data (CAEN economic sectors),
  treemap would show proportions better than horizontal bar. Requires frontend implementation.

- [ ] **Sparkline/KPI view** — Datasets with 1 dimension (pure time series, no categories)
  are perfect for a large KPI number + sparkline, not a full chart.

- [ ] **Ratio/change chart mode** — Year-over-year change, growth rates, indexed values.
  The trend data already detects these patterns; expose as an alternative view.

- [ ] **Radar chart** — For comparing a small number of categories across multiple
  metrics (e.g., county profiles across health/education/economy indicators).

- [ ] **Unify `generate_view_profiles.py` with `chart_selector.py`** — Both contain
  independent chart selection logic. The view profile generator has its own snapshot chart
  rules that partially overlap. Long-term, view profiles should call `select_charts()`.

- [ ] **Delete `app/services/chart_config.py`** — Dead code, no imports found. Kept for
  reference during the transition period but should be removed.

## Data Quality

- [x] **Phase 8: Strip aggregate/total rows from parquet files** — Done.
  49 parquet files stripped of 28,280 aggregate rows (Total in SEX, AGE, RESIDENCE, REF_AREA).
  Scripts: `scripts/detect-totals.py` (detection + decisions), `scripts/strip-totals-from-parquet.py`
  (apply to existing parquets), `12-parquet-to-sdmx.py --strip-totals` (integrated pipeline).
  Handles mutually exclusive breakdowns via intersection mode (only strips grand-total row).
  Decisions stored in `data/logs/total-decisions.json`.

- [ ] Review `docs/TODO_COMPACTION.md` — label normalisation issues in 7-data-compactor.py
