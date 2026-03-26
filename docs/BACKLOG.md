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

## Data Accuracy — Server-Side Aggregation

- [ ] **CRITICAL: Raw LIMIT truncation produces misleading charts for large datasets**

  **Problem:** `query_builder.py` returns raw parquet rows with `LIMIT N` and no `GROUP BY`.
  For datasets like POP107A (485k rows), even with `LIMIT 50000`, the truncation causes
  uneven representation across dimension values — e.g., Male/Female lines appear unequal
  when the real population is roughly balanced. This is **statistically misleading**.

  **Root cause:** The query returns un-aggregated rows. The frontend sums values per
  time×series key (`chart-factory.js`), but if the LIMIT cuts off rows unevenly across
  dimension combinations, the sums are wrong. `ORDER BY TIME_PERIOD ASC` means later
  years get dropped first, and within a year, the row order is arbitrary.

  **Fix options (pick one or combine):**

  1. **Server-side GROUP BY** (recommended) — Add aggregation to `query_builder.py`:
     ```sql
     SELECT dim1, dim2, ..., TIME_PERIOD, SUM(OBS_VALUE) as OBS_VALUE
     FROM read_parquet(...)
     WHERE ...
     GROUP BY dim1, dim2, ..., TIME_PERIOD
     ORDER BY TIME_PERIOD ASC
     LIMIT N
     ```
     This produces one row per unique combination — POP107A goes from 485k raw rows
     to ~6k grouped rows (18 age groups × 2 sex × 3 residence × ~55 years).
     DuckDB handles this efficiently. The frontend aggregation in chart-factory.js
     becomes a no-op (already summing, but now each key appears once).

     **Considerations:** Some datasets have non-summable values (rates, percentages,
     indices). Need to detect `unit_of_measure` or similar metadata to choose
     `SUM` vs `AVG` vs pass-through. Could default to SUM for counts, skip
     aggregation for rates.

  2. **Pre-aggregated materialized views** — Create summary parquets at build time
     for common dimension combinations. More complex pipeline but zero query-time cost.

  3. **Truncation warning + smart sampling** — If rows > limit, show a warning badge
     and use stratified sampling (proportional rows per dimension value) instead of
     `ORDER BY TIME_PERIOD`. Simpler but still approximate.

  **Affected datasets:** Any dataset where `total_rows > limit` after filtering.
  Currently ~50 datasets have >50k rows. The worst offenders (POP107A, POP105A,
  demographic datasets with AGE×SEX×GEO) have 100k-500k rows.

  **Quick win:** Option 1 for chart/timeline queries only. Table view can keep raw
  rows (users expect individual records there). Add a `aggregate=true` parameter
  to the data endpoint.

## Data Quality

- [ ] **Remove Total/aggregate rows from parquet files** — Rows like "Total", "Ambele sexe",
  "Urban + Rural" cause double-counting when all options are selected. Verify they are actual
  sums before removing. This would simplify filter logic (no need to exclude Totals in UI).

- [ ] Review `docs/TODO_COMPACTION.md` — label normalisation issues in 7-data-compactor.py
