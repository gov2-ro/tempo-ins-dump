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

- [ ] **Clean up stale split profile files** — `data/view-profiles/` has ~1,600 old
  split profiles with `_nom_id` column names. Remove orphaned files not in `dataset_splits` table.

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

## Data Quality

- [ ] **Remove Total/aggregate rows from parquet files** — Rows like "Total", "Ambele sexe",
  "Urban + Rural" cause double-counting when all options are selected. Verify they are actual
  sums before removing. This would simplify filter logic (no need to exclude Totals in UI).

- [ ] Review `docs/TODO_COMPACTION.md` — label normalisation issues in 7-data-compactor.py
