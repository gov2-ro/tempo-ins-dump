# Backlog

Future tasks and intentions for the TEMPO INS data explorer.

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

- [ ] **Choropleth: support region-level map** (`_regiuni` sub-datasets)
  Currently only county-level choropleth is wired up. Dev regions (8) need a separate
  GeoJSON and chart path.

- [ ] **Dataset page: show split siblings**
  When viewing `POP107B_judete`, show links to `POP107B_regiuni` and `POP107B_macroregiuni`.

## Data Quality

- [ ] Review `docs/TODO_COMPACTION.md` — label normalisation issues in 7-data-compactor.py
