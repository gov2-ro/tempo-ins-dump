# Activity History

## 2026-08-05 — fix recurring bogus news-feed matrix code (root cause, not just cleanup)

The `86 Matrice` issue from 2026-07-20 recurred as `113  Matrice` in today's `update-pipeline.py --refetch-news` run — same failure mode, same root cause, previously only patched by deleting the cached file. Fixed properly this time:

- `parse_news()` (`update-pipeline.py`) now filters `Cod matrice` values through `MATRIX_CODE_RE = ^[A-Z0-9]{4,10}$`, logging and dropping non-conforming rows before they ever reach `fetch_meta()`. Confirmed via `--dry-run` that it catches both `113  Matrice` and `86  Matrice` (both apparently persist in the news feed's row history).
- `fetch_meta()` now runs `json.loads()` on the response body before writing it to `data/2-metas/{lang}/{code}.json` — a bad/garbage code that still 200s with an empty body can no longer leave a permanent corrupt file (the `output_path.exists()` skip-guard was why the old `86 Matrice.json` never self-healed).
- Deleted the stray `data/2-metas/ro/113  Matrice.json` and reran `4-build-meta-index.py --lang ro`: `data/1-indexes/ro/matrices-list.csv` had been silently truncated to 975 rows (crashed mid-`os.listdir` on the corrupt file) — now regenerated at 1996 rows.
- Also clarified for future reference: running `update-pipeline.py` without `--refetch-news` right after a `--refetch-news` run correctly reports "No matrices to process" — it re-reads the same news snapshot filtered to `--since` (auto-set to today after any run), and INS news entries are rarely dated same-day.

## 2026-07-20 — update-pipeline.py run: stale dev-server lock + bogus news-feed matrix code

`update-pipeline.py` was failing at the DuckDB rebuild step with `Could not set lock on file ".../metadata.duckdb"`. Root cause: a `uvicorn` dev server (PID 92672, port 8088) had been running for ~49 min with the DB file open — DuckDB only allows one writer. Killed the stale process and reran; pipeline completed (358 matrices processed, 357 OK).

- The one failure was legitimate but not a real dataset: the INS news feed had a row where "Cod matrice" was literally `86 Matrice` (a bulk-update summary, not an individual code) instead of an actual matrix ID. `6-fetch-csv.py` failed on it as expected, but `fetch_meta()`'s skip-if-exists guard had left behind a permanent 0-byte `data/2-metas/ro/86 Matrice.json`, which also crashed `4-build-meta-index.py` (non-fatal — its result is unchecked in `update-pipeline.py`, and `10-import-metadata.py` ran fine afterward). Deleted the bad cached file; root-cause fix (validate codes in `parse_news()`) noted in BACKLOG under Data pipeline.

## 2026-07-20 — dashboard-v2 becomes the main dataset page

Switchover after the perspectives roadmap landed. Verified via Playwright (browse card → v2, search → v2, sidebar tree, theme toggle, ← v1 round-trip, compare chrome) — zero console errors.

- **All dataset navigation lands on `/dataset-v2.html`**: `explore-app.showDashboard()` is now a redirect (single choke point — covers browse cards, recent/headline cards, drill lists, sidebar, search); the old renderer lives on as `showDashboardV1()`, reachable only via `/?code=` deep links (init/popstate/lang-toggle) — which is exactly what the v2 toolbar's "← v1" button targets for comparison. `place-page.js` accordion links updated too.
- **v2 (and compare) adopted the site chrome**: new `js/site-chrome.js` renders the explore topbar (logo, search overlay with keyboard nav, Locuri/Ask, theme, lang) and the quick-nav sidebar (lazy category tree → datasets, filter, active-dataset highlight, `lensNavOpen` continuity) against the same markup ids/CSS as index.html, so the two look identical. Chrome dataset links go to v2. Theme flips dispatch a `themechange` window event; dashboard-v2 re-renders its charts on it (its own toolbar lang/theme buttons removed as now redundant), compare reloads.
- Deliberate duplication: site-chrome reimplements ~250 lines of explore-app chrome behavior rather than refactoring the 3,300-line SPA monolith; extraction noted in BACKLOG.

## 2026-07-20 — Perspectives Phase 3: correspondences

The "what does this connect to?" layer — last phase of the 2026-07 dashboard audit roadmap. Verified via Playwright (AMG158G rail/tags, LOC101B_judet place chip, both compare modes, ?q= deep link) — zero console errors.

- **Related-datasets rail** (`/api/datasets/{code}/related`, `get_related()` in dataset_search.py): top-5 from `dataset_relationships` (union of both directions, `arg_max` dedup) joined with names + year ranges. The table predates splits, so split children fall back to their parent's rows and get their sibling splits prepended as the strongest links. Cards show similarity %, shared-dim badges, and a "Compară" link when time is shared. Gotcha fixed: the compare link inside a card `<a>` nested anchors — the HTML parser's adoption-agency step cloned every card (10 rendered from 5); cards are now `<div>`s with a click handler.
- **Topic tags** under the title (same endpoint, `dataset_tags` context+matrix_name sources): the tag soup is tokenized words, so display goes through a structural-word stoplist, punctuation strip, and subsumed-token dedup ("munca" ⊂ "forta de munca"). Chips link to `/?q=tag` — explore-app now opens its search overlay prefilled from `?q=`.
- **Compare view** (`compare.html` + `js/compare.js`): overlays each dataset's composer temporal slice on a shared period axis (Total series when one exists, otherwise the most complete series, disclosed in the legend), dual y-axis when unit types differ; when both datasets are county-level it adds a per-county scatter at the latest period with Pearson r (LOC101B vs LOC103B: r = 0.95 across 41 counties). Aggregate areas (Total/regiuni/macroregiuni) are excluded from the scatter join.
- **Place cross-link**: clicking a county/region on the map or ranking bars now also remembers the pick (`_geoPick`) even when no other tile can be filtered by it, and spatial tiles grow a "↗ profil: {name}" chip → `/place/{level}/{slug}` (client-side slugify mirroring `place_service.slugify`; slugs verified against `/api/places`).
- Deferred to backlog: mixed-granularity compare axes, region-colored scatter, post-split relationships recompute.

## 2026-07-20 — Perspectives Phase 2: slices & controls

Interactivity layer on dashboard-v2. Verified via Playwright (AMG158G cross-filter, COM109B seasonal, LOC101B_judet per-capita) — zero console errors, all state URL-restorable.

- **Notables as slices** (`insights.py` + `dashboard-v2.js`): insights now returns structured `notables` (top/bottom entity with exact data-string value); rendered as ▲/▼ chips in the sentence strip — clicking one cross-filters the whole dashboard to that slice.
- **Chart-click cross-filtering**: clicking a map county / ranking bar / series point sets that value on every tile *not* charting the column (via pin selects or tile filters) and puts a highlight chip on tiles that do; second click clears (toggle). If the column has a global filter widget, it drives that instead.
- **Tile transform/perspective chips**: transpose ⇄ (swaps x↔series on grouped/stacked/heatmap/bubble), per-capita ‰ (count-unit × geo; population from new `/api/reference/population` endpoint reading POP105A county/region/macroregion parquets, nearest-year fallback, clean-name matching), log-scale (when `distribution == right_skewed`, only if all values > 0), seasonal overlay (monthly/quarterly → sub-period on x, one line per year via `seasonalOverlay()` in utils.js).
- **Filter widgets upgraded**: global row now renders pill groups (≤6 options), selects, or datalist typeaheads (>25) instead of bare selects; row is rebuildable so cross-filters reflect into it.
- **URL state**: tile transforms/swaps/norms/logs persist as compact `?t=` JSON alongside `?f=` filters; restored on load.
- **B7 fixed** (`insights.py`): monthly/quarterly datasets get a true seasonal YoY KPI (same sub-period, previous year) labeled "Față de anul anterior", with MoM kept as the separate "previous period" card.
- Fill-rate KPI suppressed when > 100% (splits inherit parent coverage — LOC101B_judet showed "5156%").
- Deferred to backlog: seasonal overlay should prefer most-recent years over top-by-sum; line-chart y-axis clipping on 8-digit values.

## 2026-07-19 — Perspectives Phase 1: guaranteed dispatch + v2 parity

Frontend follow-through of the audit (same day as Phase 0). Verified per-dataset via Playwright screenshots (`scripts/dbv2-screenshot.mjs`), zero console errors across CON107B/AGR201E/AMG158G/LOC103B_judet/COM109B/TFA0494/PPA103A.

- **Dispatch is now selector-driven, not archetype-driven.** v1 (`explore-app.js`): choropleth snapshot gate, new Heatmap time-panel pill, and population_pyramid all keyed off `ranked_charts` (archetype kept as fallback badge). Kills the silent line-fallback for ~735 datasets whose primary the panels couldn't render; AGR201E now opens on its cat×time heatmap, LOC103B_judet (archetype null) gets its Map tab.
- **Choropleth time slider**: `chart-geo.js` already computed per-year frames but rendered only the latest — wired them to an ECharts timeline with play control (same pattern as chart-demographic). Both surfaces.
- **Composer honesty upgrades** (`dashboard_composer.py`): small_multiples without a facet renders as line (AMG101E); a heatmap without a second categorical gets time as its x axis (or is skipped); split parents with no parquet get NO composition — v2 shows sub-dataset pills instead of 500-ing tiles, with children derived from the parquet corpus when `dataset_splits` has no rows (AMG101A_anual/_trimestrial).
- **Hierarchical-dim double-counting fixed** (`_hierarchy_root_pin`): dims that encode a tree in label indentation + "- total" suffixes (no parent_id data) were summed whole — AGR201E's headline read 10.3M "bovines" (2011 collapse = artifact) vs the real 1.85M. Slices/insights/global-filter defaults now pin the top-level aggregate and disclose it.
- **Legacy parquet path unbroken** (`dataset_data.py`): requests arrive with SDMX names but 67 legacy files have `*_nom_id` columns — `group_by` silently fell back to *unaggregated all-dims* (the audit's B10) and filters never matched. Both are now remapped to the file's names, and responses translate back to SDMX-canonical columns. Plus `_parquet_dim_values` resolves legacy columns via `sdmx_column_map` and `_effective` gained a collision-guarded whitespace-tolerant match (legacy values carry indentation metadata lacks — but hierarchy dims use indentation to distinguish options, hence the guard). Net: LOC103B_judet v2 = choropleth + slider + ranking + evolution, all data-grounded.
- **v2 parity** (`dashboard-v2.js` +~250 lines): sortable raw-data table (cap 1000), CSV/XLSX/INS links, RO/EN strings + lang toggle, theme toggle, Index/Δ% transform chips on temporal tiles (shared `applyTimeTransform` extracted to utils.js; annotations skipped under transforms — peak/trough pins describe raw values), unified empty-tile behavior (composer-time holes drop the tile; user-caused emptiness keeps it with a message), visible notice when insights fail.
- **Shared ECharts themes**: v2 charts rendered in default ECharts theme (registration lived only in explore-app) — extracted to `js/echarts-theme.js`, loaded by both pages; added timeline styling.
- **Truncation disclosure**: series-capped time charts show "top 12 / 42" instead of silently dropping series (`chart-factory.js`).
- Moved dead controllers `dataset-page.js`, `dataset-page-v2.js` to `app/static/_obsolete/js/`.

## 2026-07-19 — Dashboard audit + Phase 0: truthful chart-selection signals

Full audit of chart/filter selection (rules, data shape, frontend dispatch) — report in `docs/dashboard-audit-2026-07.md`, phased roadmap in BACKLOG ("Perspectives roadmap"). Phase 0 (backend correctness) implemented and verified:

- **B1 time_points**: the `time_year_max` fallback returned the literal year (2024) corpus-wide, not just ECC109A — every `tp >= N` rule was silently true. Now `max − min + 1`. This alone moved 17 short-series datasets off small_multiples/heatmap onto ranked bars in the eval.
- **B2 aggregation**: new shared `query_builder.AVG_UNIT_TYPES` (`percentage/time_unit/index/rate/ratio`) replaces three divergent copies in dataset_data/insights/agent — index datasets were being SUMmed (base-100 indices summed across dims). `index`/`ratio` added to composer `NON_ADDITIVE_UNIT_TYPES`; area_stacked/stacked_bar ineligible for `index` unit.
- **B4 choropleth**: eligibility geo≥4 → geo≥8 and the five copy-pasted "geo-primary" −0.15 penalties follow — 4-macroregion datasets (30 in eval) no longer get a four-shape map burying the time story.
- **B5 pyramid**: new `gender_mf_count` signature signal (parsed male/female options); mixed "Sexe si medii" dims can no longer mirror Urban/Rural as pyramid sides (SOM101C had mf=1). Eval harness supplies the same count from DB for lock-step parity.
- **B6 confidence**: was dataset-level stamped on all ranked entries; now primary = gap to runner-up, alternatives = distance from primary.
- **B7 insights YoY**: monthly/quarterly data now compares the same sub-period last year ("2025-08 vs 2024-08"), with MoM/QoQ as a secondary `prev` card — previously MoM was labelled as the headline change.
- **B8 series alignment**: `retune_ranked_series()` (composer) applies `_best_temporal_series` to `ranked_charts` roles so v1 (raw roles) and v2 (composer tiles) present the same default split.
- **B9 forced pins**: `_parquet_dim_values` now returns per-value row counts; arbitrary non-additive pins prefer the densest option (`_widest_pin`) instead of first-listed.
- **B3 exclude_total**: only defaulted True when the charted dims keep non-Total values in the parquet (`_non_totals_survive`).
- **Parts-of-whole probe**: `dataset_meta._detect_composition` verifies on the latest period whether non-Total options sum to Total (±2%) or to ~100 for percentages → `sig.is_composition` drives area_stacked/stacked_bar (±0.30/−0.15). Runtime-only by design; eval scores it as None (documented divergence in `chart_selector_eval.py`).
- Consolidated three copies of the Total-detection regex into `chart_selector.TOTAL_RE`.

Eval reviewed before re-baselining: 64/1,986 primary changes, all in intended directions (choropleth demotions geo 4–7 + one mixed-level LMV101A; short-series facet charts → bars; pyramid corrections both ways). Baseline rebuilt via `scripts/build_chart_selector_baseline.py`.

## 2026-07-15 — Knowledge graph of the repo via `/graphify`

Built a graphify knowledge graph over the whole repo (289 files, ~573K words): AST-extracted 1,682 nodes/3,495 edges from 179 code files structurally (free, no LLM), then dispatched 21 parallel subagents for semantic extraction of 93 docs + 17 images (no `GEMINI_API_KEY` set, so the host session did the semantic pass via subagents instead of the Gemini backend).

The 4 doc-chunk subagents (each reading 21-24 markdown/HTML files) ran far longer than the 17 image chunks — one finished in ~8 min after being written off as stalled, the other three never finished in-session. Per user decision, the final graph (`graphify-out/graph.json`, 1,722 nodes/2,980 edges/143 communities) was built from AST + the 17 completed image chunks only; the 93 document-category files were deliberately excluded from `manifest.json`'s semantic_hash stamping (rather than the skill's default kind='both' write) so a future `/graphify --update` retries them instead of silently skipping already-"seen" files that were never actually extracted.

Two real UI issues surfaced incidentally from vision analysis of eval smoke-screenshots (added to `docs/BACKLOG.md` under Dashboard v2): LOC103B_judet's Map tab rendering a line chart instead of a choropleth, and AMG158G's v2 choropleth legend (28-91) rendering every county the same color for 2024 — both worth a manual look.

## 2026-06-12 — Dashboard v2: data-grounded slices (no more empty tiles / ghost filters)

FOM106F exposed three composer failures: an empty heatmap hero ("Fără date"), only 2 tiles for a 4-dim dataset, and a "Categorii de salariati" filter whose selectable option (Muncitori) doesn't exist in the data. Root cause for all: the composer trusted *metadata* options, but parquets routinely lack rows metadata promises (FOM106F has no `SEX='Total'` and no `CATEGORY='Muncitori'` rows at all).

**Composer grounded in parquet reality** (`dashboard_composer.py`, `dataset_meta.py`): `get_dataset_meta` now reads distinct values per dim column from the parquet (`_parquet_dim_values`, ms-cheap) and passes them in. Slices only pin values that exist; dims that are singletons *in the data* are skipped entirely (no pin, no filter control). The `fallback_filters` retry machinery is gone — it papered over the mismatch and produced wrong sums (it would SUM salaries across all CAEN activities).

**Non-additive pinning**: when a dim has no Total in the data, additive units still go unfiltered (SUM = total), but non-additive ones (`currency`/`percentage`/`rate`/`time_unit` — means can't be summed) pin the first real option; the tile chip discloses it (FOM106F heatmap shows "Masculin"). The data router only AVGs percentage/time_unit, so summed currency means were silently wrong before.

**More tiles for rich data**: structural/temporal heroes now also request a ranking companion, and ranking synthesis generalizes beyond geo to the widest categorical dim (≥6 real options) — FOM106F gets heatmap + line + top-30 CAEN bar (3 tiles); 40-dataset sampling: 2–4 tiles, mostly 3, exactly 1 empty slice (CDP104H cross-dim coverage hole).

**NULL group buckets** (`query_builder.py`): parquets carry NULL dim values where SDMX mapping is missing; GROUP BY lumped them into one bogus summed bar (100k "salary" on FOM106F ranking). Aggregations now exclude rows whose group column is NULL.

**Frontend** (`dashboard-v2.js?v=4`): tiles whose slice comes back empty are *dropped* and survivors re-slotted client-side (GRID_LAYOUTS/SLOTS mirror the composer) instead of rendering a "Fără date" placeholder; zero-alive shows one message (split parents like AGR101A now degrade cleanly). Filter row renders composer-provided data-grounded options (`options`/`default`/`allow_all`) instead of raw metadata options; "Toate" only offered when values are additive and total-less.

`insights.py` updated to the new slice API (same grounding). Backlog: NULL-mapping pipeline backfill, overlapping AGE bands double-count (POP107D 38.8M), compose-time joint-coverage probe if empty slices recur.

**Follow-up 2 (same day): per-tile controls — pins become defaults, not verdicts.** User feedback: v2 had *fewer* choices than v1 (for FOM106F: zero controls — you couldn't view a CAEN sector's evolution), "Ultima valoare" was men-only salary presented as the dataset headline, and the tendință badge duplicated schimbare totală. Changes:
- Composer emits `controls` per tile (`_tile_controls`): one select per pinned dim with ≥2 real options, data-grounded (FOM106F's CAEN select has the 50 values that exist, not metadata's 68), default = the pin. Dims covered by the global filter row are excluded (no duplicates).
- `dashboard-v2.js?v=6`: selects render in the tile bar (chip-styled, replacing the static chips), per-tile state in `tileFilters`, fetch keyed per chart.id with identical-request dedupe. A tile emptied by its *own* control shows "Fără date pentru această selecție" (not dropped — user must be able to switch back).
- `insights.py`: "Ultima valoare" carries `context` labels for non-total pins (renders "Lei RON · 2024 · Masculin"); tendință badge only shown when it adds signal (volatile/flat or contradicting the overall %) — increasing+up is suppressed as noise.
- Still not ported from v1 (deliberate, follow-ups): multi-select series compare (up to 8 CAEN lines), chart-type toggles per tile, view-profile snapshot variants.

**Follow-up (same day): heatmaps demoted from hero + smarter timeline series.** User feedback: heatmaps are hard to read as the lead chart, and FOM106F's evolution line only showed M/F. Two global rules in the composer:
- `NON_HERO_CHARTS`/`WIDE_CHARTS = {'heatmap'}`: hero = first non-heatmap candidate; a picked heatmap is ordered last and gets a full-width row via new layouts `hero_full` ("hero"/"full") and `hero_side_full` ("hero side1"/"full full") — mirrored in `dashboard-v2.js slotCharts()` for client re-slotting and added to `dashboard-v2.css`. FOM106F: line hero, CAEN ranking side, heatmap full bottom; 40-dataset sample has zero heatmap heroes.
- `_best_temporal_series()`: evolution charts (line/area/stacked/bar) swap the selector's gender-first series for the most informative real split — ranked by **fewest forced arbitrary pins** (a candidate that forces other no-total non-additive dims onto a pinned single option loses), then substantive-over-demographic (gender/residence/age), then series count (2–8 band). Composer-only (roles copied) so `ranked_charts`/v1/eval stay untouched. FOM106F deliberately *keeps* M/F: INS published no SEX totals there, so any other split would pin the whole chart to one sex — honesty beats richness. TIV0827/AGR205A/TRN102B (3/40 sampled) switch to substantive splits (occupational status, agri branches) with pins disclosed as chips.

## 2026-06-11 — Dashboard v2 Phase 1: shape-driven composition engine + page skeleton

New side-by-side dataset page (`/dataset-v2.html?code=X`) that composes 1-4 complementary charts at once instead of the fixed two-panel layout, so most datasets are understandable with zero clicks.

**Composer** (`app/services/dashboard_composer.py`, new): consumes `select_charts()` ranked output + roles and picks charts by *information-axis diversity* (temporal/spatial/ranking/structural, max 1 per axis, max 4 charts), synthesizing a trend line or top-N geo ranking when the hero's natural companion didn't rank. Emitted as `chart_config.composition` (3-line hook in `dataset_meta.py`). Each chart carries a declarative data-slice spec (`group_by` from its roles + filters) and zero-cost annotations from `dataset_trends` (breakpoints/peak/trough/geo outliers — rendering deferred to Phase 3).

**Non-obvious slice rules** (each found by a real failing dataset):
- Dims not on an axis are pinned to their Total option to avoid double-count SUMs; a `fallback_filters` variant with totals *excluded* ships alongside because some parquets lack the Total rows metadata lists (AMG1103).
- Filter values include trimmed variants — metadata labels carry hierarchy-indentation whitespace ("   Din total : salariati") that parquet values don't. Trimmed variant skipped if it collides with another option of the same dim.
- Time pins must use the option's `sdmx_value` ("2023"), not the RO label ("Anul 2023") — SDMX parquets store normalized TIME_PERIOD.
- Secondary time dims (index base years, CNS106A) are left unpinned when a time dim is already on an axis — pinning the latest base truncates the series to one point; coverage windows don't overlap so aggregation is safe.
- `horizontal_bar` is not timeline-capable (its renderer sums all rows per category), so its `timeline` role is dropped from the slice and time pinned latest instead.

**Selector fix** (`chart_selector.py assign_roles`): with two time dims, the time axis is now the one with the most periods (base-year dims are small). Eval clean — roles aren't scored.

**Frontend** (`dataset-v2.html`, `js/dashboard-v2.js`, `css/dashboard-v2.css`, new): slices deduped by `slice_id` and fetched in parallel as small aggregated `group_by` queries (sidesteps the 50k cap); CSS `grid-template-areas` per layout (`single_full`/`hero_side`/`hero_2side`/`hero_2side_full`); tiles reuse `createChart()` unchanged. Gotcha: per-tile compat fields `time_dim`/`geo_dim` must be re-derived from the tile's own slice columns — inheriting the dataset-level ones routes chart-factory to the wrong renderer when the slice pinned that dim away.

**Eval baseline refreshed**: `chart_selector_baseline.json` was stale (predates the 05-07 selector rework, 476 phantom primary changes); regenerated, now 0-drift. Verified via Playwright screenshots (`scripts/dbv2-screenshot.mjs`, new dev helper) on all four layouts; no console errors.

Next: Phase 2 (KPI strip + insight sentences), Phase 3 (annotations + compact filters), Phase 4 (selector signal tuning).

## 2026-06-11 — Dashboard v2 Phases 2-4: insights, annotations, filters, selector signal tuning

**Phase 2 — insights** (`app/services/insights.py`, new + `GET /api/datasets/{id}/insights`): KPI cards (latest value + SVG sparkline, YoY, overall change, trend badge, coverage) and ≤3 template sentences (RO/EN), computed from the same composer slice rules as the tiles (totals pinning, whitespace variants, sdmx_value time pins) so numbers always match the charts. Sentence priority: YoY → top/bottom geo (or top category) → breakpoints; overall change stays KPI-only to not waste a slot. Geo rankings drop coarser levels (counties never mix with their region aggregates). TTL cache (1h) like headlines.py.

**Phase 3 — annotations + filters**: `js/chart-annotations.js` merges markLine (breakpoint years, dashed) + markPoint (peak/trough pins, single-series only) onto rendered tiles via series-index merge; spatial outliers render as a ⚠ chip in the tile bar. Compact filter row from `composition.filter_dims` — one select per unconsumed dim, defaults mirror the composer's Total pin, synthetic "Toate" (= sum) for dims without a Total option (suppressed for unit dims), state in `?f=` URL param, charts disposed + refetched on change.

**Phase 4 — selector tuning** (eval-gated, 3 iterations): final nudges are (1) line +0.05 on |trend_slope| ≥ 0.05 *gated on the small-series readability condition* — ungated it poached 37 deliberate small_multiples/heatmap wins from the May cluster tuning; (2) choropleth +0.05 when `geo_outlier_counties` non-empty (scale-free; raw `geo_variance` spans 1e6–1e14 and is unusable as a threshold); (3) horizontal_bar +0.05 on right_skewed distribution. The heatmap −0.05 skew penalty from the plan was dropped — it created 3-way ties resolved to line-spaghetti (ECC109A, 28 series × 3 periods). Net result: exactly 7 primary changes, all geo datasets upgrading to choropleth (e.g. CON103G regional GDP), reviewed and re-baselined.

**Latent bug exposed + fixed** (`chart-factory.js`): geo-level detection was macroregion-first while `createChoroplethChart` is region-first — region+macroregion datasets loaded the wrong GeoJSON and crashed ECharts on the unregistered map. Never seen before because those datasets only now rank choropleth as primary. Aligned to county > region > macroregion.

Verified: Playwright on 8 datasets (all layouts + both new choropleth flips) + v1 spot-check, zero console errors; selector eval 0-drift after re-baseline.

## 2026-05-07 — Place Profiles feature (counties, regions, macroregions)

Full place profile pages at `/place/{type}/{slug}` showing KPI heroes, indicator grid with category filtering, and cross-place comparison chart. Directory listing at `/places`.

**Backend** (`app/services/place_service.py`, `app/routers/places.py`): `slugify()` strips "Regiunea" prefix before normalizing so the 24 DB variants for 8 regions all resolve to clean slugs. County→region mapping is a hardcoded dict (no DB table). `_query_kpi_series` opens a fresh DuckDB connection per call and closes it in `finally`. Baselines route registered before profile route in FastAPI to avoid path capture conflict.

**KPI config** (`app/static/data/place_kpi_config.json`): 7 KPIs per geo level, parquet filenames verified against actual corpus files. County uses POP202A for birth/death rates (1990–2024); region/macroregion use POP202B (2012–2024). FOM106E (not FOM106A) used for wages — FOM106A only covers 1993–2007.

**Frontend** (`place-page.js`): `PlaceProfileApp` class; XSS escaping via `_esc()` throughout innerHTML; ECharts sparklines tracked for disposal on re-render; comparison chart uses `type:'category'` xAxis with `alignToYears()` to handle series with different year ranges.

**Deferred to backlog**: norm-by-population toggle, choropleth click-through, dataset page cross-link.

## 2026-05-07 — Cluster 4 + cluster 2 deep-dives (selector → 96.8%)

Two more passes on the cluster-correctness baseline pushed overall match rate from 92.1% → 96.8%.

**Cluster 4 (Gender-Split): 87% → 100%.** Reclassifier fix in `scripts/chart-taxonomy.py` — datasets with gender + a CAEN/ISCO/Activitati cat dim ≥30 options were landing in cluster 4 (expects line/sm/hbar) but the selector correctly picks heatmap (cat × time matrix is the only readable view at that cardinality). Threshold 30 reroutes them to cluster 2, whose expected set already includes heatmap. Same pattern applied later for cluster 9.

**Cluster 2 (Categorical Time): 82% → 95%.** Mix of selector and classifier fixes:
- Heatmap eligibility: allow on sparse data when a cat dim >20 options is present (was: blanket `not is_sparse` exclusion). Line/sm both fail at that cardinality and a partly-empty heatmap still reveals where the data clusters.
- Heatmap defer: -0.15 when has_geo (cluster 7) or has_residence (cluster 9) without demographic overlay, so the very_long-cat bonus doesn't poach choropleth/line wins. Mirror of the line/bubble/sm defer added during cluster 7 work.
- Line small-series bonus: gate on *total* cat₁×cat₂×… ≤ 6 (was: any single dim ≤4). A small dim alongside a 5-25 dim still yields hundreds of series. Also suppress when has_geo so cluster-7 datasets defer to choropleth.
- Horizontal_bar: -0.10 when has_time≥5 and any cat dim ≥10. Snapshot ranking shouldn't beat heatmap/line for time-rich, long-cat datasets.
- Residence + max_opts ≥30 → cluster 2 (mirrors cluster 4 reclass). SCL/TLC datasets with 50+ education categories belong in Categorical Time, not Urban/Rural.

Cluster 3 went 98% → 100% as a side-effect; cluster 9 went 94% → 100%. Cluster 7 stayed at 95%. Final state: cluster 1 100%, 2 95%, 3 100%, 4 100%, 5 97%, 6 93%, 7 95%, 8 96%, 9 100%, 10 100%, 11 88%. Diminishing returns past this point — clusters 6/11 each have <5 misses.

## 2026-05-07 — Visual smoke test (Phase 5)

Loaded 13 cluster exemplars in lens via Chrome DevTools MCP, captured full-page screenshots, inspected ECharts series types, checked console. Report at `data/eval/smoke-test-report.md`. Console: zero errors/warnings across the sweep.

**11/13 visual passes.** 2 frontend dispatch gaps surfaced — both routed to BACKLOG:

1. **Cartographic falls back to line when archetype is null** (LOC103B_judet, cluster 7). API returns choropleth as primary + curated pair, but `explore-app.js:1642` only adds choropleth to the snapshot tab list when `archetype === 'geo_time' || archetype === 'geo_only'`. Split datasets carry `archetype: null` so the choropleth tab is dropped.
2. **Heatmap timeline never dispatched** (AGR201E, cluster 5). Selector picks heatmap with high confidence; the lens timeline panel only offers Line/Bar/Area/Stacked/Index/Δ%. Heatmap is a snapshot-only chart type in the current static recipe.

Both gaps point at the same fix: drop the static archetype-keyed dispatch in lens and read from the selector's `chart_config.ranked_charts` instead.

## 2026-05-07 — Docs refresh (CLAUDE.md + readme.md)

Cleaned up CLAUDE.md and readme.md to match current repo state. Removed stale references — `ui/`, `explorer/`, `profiling/` directories no longer exist; `chart_config.py` moved to `app/services/_obsolete/`. Corrected pipeline script tables (paths now point to `corpus/parquet` and `corpus/metadata.duckdb`). Added current `app/services/` entries (`agent.py`, `headlines.py`, `llm_client.py`) and routers (`ask.py`, `sdmx.py`). Consolidated CLAUDE.md's redundant Persona/Coding Principles sections. Pipeline script tables now live primarily in readme.md with a compact summary in CLAUDE.md so Claude can answer "what does script N do" without a Read call.

## 2026-05-07 — Chart paradigm redesign (Phase 0 + Phase 1)

Major rework of the chart-selection engine after diagnosing why ~71% of datasets were rendering suboptimal charts. Guided by the plan at `~/.claude/plans/i-want-to-have-quirky-haven.md` — hybrid pair-when-needed paradigm, full-redesign scope.

**Root cause (Phase 0):** `matrix_profiles` had only 13 rows out of 1,986 expected. A previous full run of `10-classify-dimensions.py` had executed `DROP TABLE` then died before INSERT; the surviving 13 rows were just the datasets ingested 2026-04-14 via single-matrix mode. The chart selector had no signature to score against for 99% of datasets and was falling back to defaults. Re-ran the classifier → matrix_profiles now has 1,986 rows with proper archetype distribution (time_series 50%, geo_time 30%, demographic 13.5%, time_residence 4%, categorical 1.3%, geo_only 1.2%).

Adjacent fix: recreated `v_canonical_datasets` view (schema-stale because the bilingual work on 2026-04-13 added `matrix_name_en`/`definitie_en` columns to `matrices` but didn't drop+recreate the view).

**Selector tweaks** (`app/services/chart_selector.py`):
- `area_stacked` demoted from 216 primary picks to 0. Audit found ~92% of "percentage" datasets are rates/indices/shares (NOT parts-of-whole), so the +0.2 percentage boost was wrong for the vast majority. Lowered base from 0.4 → 0.35; replaced broad boost with a tiny +0.05 only for 2-4-series percentage shape. Stays as a swappable alternate in `ranked_charts[]`.
- `line`: added `percentage` to the rate/ratio/index unit-affinity bonus; -0.15 penalty for too-many overlapping series (>8); -0.10 penalty for age-cohort shape (`has_age && has_time && !has_gender`).
- `small_multiples`: bumped facet bonus and time bonus so it wins for cluster 2 (categorical-time, 534 datasets / 27% of corpus). Primary picks went from 8 → 413 corpus-wide.
- `heatmap`: +0.30 bonus for age × time when no gender/geo (cluster 5).
- `population_pyramid`: handle `gender_count=3` (M+F+Total) with +0.15 (vs +0.20 for pure 2-option).
- `choropleth`: lower eligibility from `geo>=5` to `geo>=4` (covers macroregion datasets); +0.15 when geo + demographic both present.
- `bar_vertical`: -0.15 when geo present without demographics (defer to choropleth).
- `horizontal_bar`: -0.15 for "no time, no geo, 2+ small cat dims" (defer to grouped_bar).
- `grouped_bar`: +0.4 for that same snapshot shape.

**Ranking chart retired** — `createRankingChart` was never auto-selected (not in `CHART_TYPES`, no eligibility/score rule), reachable only via the deprecated v1 toolbar. Deleted 122 lines of dead code from `chart-new-types.js`, dropped the `'ranking'` case from `chart-factory.js`, removed `rankMode` i18n labels and the pill list entry from `explore-app.js`.

**Cluster-correctness baseline** (`scripts/chart-taxonomy.py`): added `data/eval/chart_taxonomy_baseline.json` recording each dataset's cluster + expected primary chart + selector's actual primary + match. Cluster 3 expectation revised from `area_stacked` to `line` (matching the data analysis). Clusters 4, 9, 10 broadened to accept multiple primary picks since they absorb diverse dim shapes (gender/residence + high-cardinality category → small_multiples is genuinely better than line; single-cat snapshots can sensibly be horizontal_bar OR grouped_bar OR bar_vertical depending on cardinality).

**Outcome:** spot-check accuracy on cluster exemplars **42% → 96%**. Corpus-wide cluster-correctness **~29% → 72.7%**. Per-cluster: simple TS 99%, gender-split 100%, urban/rural 95%, cat snapshot 100%, geo+demographic 96%, pop pyramid 93%, geo snapshot 88%, cartographic 75%, composition % 72%, age cohort 56%, categorical time 46% (the remaining lever).

## 2026-05-07 — Pair API + lens panel defaults

Wired the chart-selector's complementary-pair recommendation into the dashboard layout — Phase 2 backend + minimal-lens-frontend.

**Backend** (`chart_selector.py` + `dataset_meta.py`): added `decide_pair()` helper that processes the ranked results and emits `chart_config.pair = {primary, complement, reason}` when (a) primary belongs to a curated complementary pair (`COMPLEMENTARY_PAIRS`) AND (b) its partner is in the top-4 results AND (c) the complement scores ≥ 0.5. Returns null for single-chart layouts.

**Lens** (`app/static/js/explore-app.js`):
- Pair-aware default selection: when `chart_config.pair` is set, place `pair.primary` in its natural panel and `pair.complement` in the other. Falls back to per-panel best-score from `ranked_charts[]` when pair is null.
- Added `small_multiples` to `timeChartTypes` when there's a facet candidate (6-25 options) OR when the selector recommends it. Otherwise the selector's small_multiples picks (cluster 2's 534 datasets) had no render path in lens.
- `renderTimeChart` now picks a separate facet dim (6-25 options) for small_multiples — `setup.timeSeriesDim` is selected for line series (2-6 options) and is too narrow for faceting.
- LABELS: `small_multiples → "Multiples"` for the pill button.

**Bug fix** (`chart-factory.js`): `resolveRoles` was returning `facet_dim: roles.facet || null` and then spreading over `chartConfig.facet_dim`, wiping out caller-supplied values. Changed to `roles.facet || chartConfig.facet_dim || null`, matching the pattern used for `time_dim`/`series_dim`.

**Verified visually** via Chrome DevTools MCP:
- `AGR201G` (cluster 2): renders as a 4×3 small_multiples grid, 12 mini line charts per pig weight category — the headline UX fix.
- `CON107B` (simple TS): single line, no Multiples pill, no second panel.
- `TFA0494` (pop pyramid): line trend + population pyramid as snapshot default.
- `TAN0131` (geo+demographic): line trend + choropleth map as snapshot default.

## 2026-05-07 — Data router resilience (time-window + legacy parquet remap)

Two distinct fixes to `/api/datasets/{code}/data`.

**Auto time-window threshold lowered.** `TIME_WINDOW_THRESHOLD` was 500_000 — datasets in the 50k–500k range silently truncated their result without windowing time, so charts saw partial data with no indicator. Lowered to `MAX_DATA_ROWS` (50_000) so windowing fires *before* truncation. Skip when `group_by_cols` is set since group_by already aggregates row count down.

**Legacy-format parquet support.** 67 of 3,706 parquets (1.8%) still use the v2 column convention (`*_nom_id` dim names + `value` value column) instead of SDMX (`REF_AREA`, `TIME_PERIOD`, `OBS_VALUE`). The `/data` endpoint failed with "Binder Error: Referenced column REF_AREA not found" for these, leaving them blank in the UI.

Two patterns underlie the mismatch:
- *Canonical* legacy datasets (EXP101D, LMV101B, CON108C, ...) — `dimensions` table records SDMX names but the parquet is legacy.
- *Split* legacy datasets (LOC103B_judet) — `dimensions` has `_nom_id` and the parquet matches.

Fix:
- New `_detect_parquet_schema()` helper in `dataset_data.py` peeks at the parquet's columns and returns `{is_legacy, value_column}`.
- Reconcile `dim_column_name` with the actual parquet via `sdmx_column_map`: forward map (legacy→SDMX) for SDMX parquets with legacy dim records; reverse map (SDMX→legacy) for legacy parquets with SDMX dim records.
- `query_builder.build_data_query` accepts a `value_column` argument and aliases it back to `OBS_VALUE` in the SELECT so downstream code keeps a uniform response shape.
- Skip the auto-time-windowing block for legacy parquets (no `TIME_PERIOD` column).

Affects clusters 1, 2, 3, 7, 8 — wider than just cluster 7's 28 datasets. Closes the cartographic-blank BACKLOG entry; opens a follow-up to do a pipeline-level migration of these matrices via `12-parquet-to-sdmx.py` so the special-case code path can eventually be removed.

## 2026-04-22 — Generic dimension chunking for oversized pipeline datasets

Added `generate_chunks()` (recursive generator) and `fetch_by_generic_chunks()` to `6-fetch-csv.py`. The algorithm finds the dimension with the most options and splits it into sub-sets such that each chunk stays ≤25,000 cells (just under the TEMPO API limit). Chunks are pre-counted before fetching; if >5,000 chunks would be needed (SAN101B: 432M cells, INT109C: 520B cells) the dataset is still skipped. The new fallback is wired in after judet-split fails in the oversized handling block. Logs recoveries to `data/logs/generic-chunk-datasets.log`. Verified on INT101T (891k cells → 37 chunks → 414,363 rows). Should recover ~14 datasets that were permanently logged in `oversized-datasets.log`.

## 2026-04-20 — TEMPO R package API analysis

Compared MarianNecula/TEMPO (R package) against our Python pipeline. Confirmed our endpoint coverage is complete (context, matrices, matrix/{code}, pivot, excel). Identified three gaps worth addressing: (1) `lastUpdate` payload field in `/pivot` — potentially enables conditional/incremental fetches; (2) generic dimension chunking instead of judet-specific splitting — would recover currently-skipped oversized datasets; (3) `ultimaActualizare`-based skip logic for incremental pipeline re-runs. Added all three to BACKLOG.

## 2026-04-14 — VP cleanup + 13 new datasets ingested + pipeline fixes

**View profile cleanup:**
- Deleted 675 orphan VP JSON files (parent datasets replaced by splits) + cleared 1,150-file `_stale/` directory
- Diagnosed 197 "missing" VPs: all are `_localitate_judet`/`_localitate_localitate` splits that exist as parquets but aren't registered in `matrix_profiles` (too high-cardinality for the UI). Not a simple re-run issue — documented in backlog.

**13 new datasets ingested** (new on TEMPO Online since last full scrape):
`FOM105I, FOM106G, FOM107G, FOM108C, FOM108D, FOM109C, FOM109D` (CAEN Rev.3 labor stats),
`PMI115C, PMI117B` (environmental goods/services), `SAR102G, SAR107B` (poverty/Gini),
`IAPC102` (harmonized price indices), `IPPR101` (residential property price indices).
All have: parquet → DB registration → dimensions → matrix_profiles → view profiles.

**Pipeline fixes (new datasets not in `matrices.csv`):**
- `10-import-metadata.py`: removed `lang` column from all INSERTs/conflicts; added `matrices-list.csv` as supplementary source for codes not yet in full API scrape; added dimension-skip guard; enrichment now targets only matrices with missing `context_code` or zero dimensions.
- `10-classify-dimensions.py`: `--matrix` mode now uses `CREATE TABLE IF NOT EXISTS` + `INSERT OR REPLACE` instead of DROP+recreate, so single-matrix runs don't wipe existing data.
- Sequence drift fix: after partial failed run, `seq_dimension_id` and `seq_option_id` were reset via DROP+recreate at correct starting values.

## 2026-04-13 — Enhanced sort + faceted filter bar

Added sort options and filter chips to the dataset list panel shown when drilling into a category.

**Backend** (`dataset_search.py`, `datasets.py`):
- New sort options: `dims` (by dimension count) and `options` (by total option count, via subquery on `dimensions` table)
- New filter params: `granularity` (annual/monthly/quarterly), `has_gender`, `has_age`, `has_residence`
- `option_count` added to returned dataset cards

**Frontend** (`explore-app.js`):
- `this.drillSort` and `this.drillFilters` state in constructor
- `renderFacetBar()` renders sort pills (Updated/Name/Records/Dims/Options) and filter chips (Period: All/Annual/Monthly/Quarterly; Has: Geo/Gender/Age)
- `_syncDrillUrl()` writes `?sort=`, `?gran=`, `?has_geo=` etc. via `history.replaceState`
- URL params restored on page load; "× Clear" button resets to defaults
- `drillCategory()` spreads `this.drillFilters` into the API call

**CSS** (`explore.css`): `.facet-bar`, `.sort-pill`, `.facet-chip`, `.facet-label`, `.facet-sep`, `.facet-clear` styles added.

## 2026-04-13 — Language-aware meta/OG tags

`_updatePageMeta()` now respects `this.lang` in all three cases:
- **Home page**: title, og:title, description all switch to English when `lang=en`
- **Category page**: title and description follow lang (category names already come from API with lang)
- **Dataset page**: description suffix ("Updated" vs "Actualizat") follows lang; `matrix_name` is already localized by the backend

Also marked two already-done items in backlog: PNG export and `lang` on `get_dataset()` were both already implemented.

## 2026-04-13 — Category URL State + Breadcrumb Fixes + Category Meta Tags

Three related improvements to `app/static/js/explore-app.js`:

**Category URL state**: Category drill-down navigation now syncs to the URL as `?cat=CODE1:CODE2` (e.g. `?cat=E:E1`). Uses `replaceState` within a drill session (no history spam) and `pushState` on major navigations. Refreshing the page while browsing a category restores the full drill state. Back button in the browser works correctly.

**Breadcrumb fix (dashboard → browse)**: Previously, clicking a breadcrumb on a dataset page silently failed because `context_path` objects only contain `{code, name}` — not the full category objects (with `children`, `total_datasets`) that `drillCategory()` requires. Fixed by adding `_findCategoryByCode(code, tree)` (recursive search through `this.categories`) and `_restoreDrillFromUrl(catPath)` helpers. Breadcrumb click now sets `_urlCat` and calls `showBrowse()`, which restores the drill stack.

**Category page meta tags**: `_updatePageMeta()` extended to handle `{ type: 'category', cat, catPath }`. When drilling into any category/theme, `document.title`, `meta[description]`, `og:title`, `og:description`, and `og:url` are updated to reflect the category name and dataset count. `showBrowse()` resets meta to landing-page defaults; drilling overrides it again.

## 2026-04-12 — Monthly/Quarterly Yearly Aggregation Toggle

90 monthly + 27 quarterly datasets previously rendered 200–416 x-axis data points, making charts unreadable. Fixed with two changes:

**Yearly aggregation (explore-app.js)**: For monthly/quarterly datasets, `this.yearlyAgg` defaults `true`. `_aggregateByYear()` groups `TIME_PERIOD` by 4-char year prefix (`2024-01` → `2024`, `1995-Q1` → `1995`), SUM for counts/currency, AVG for percentage/rate/time_unit. A toggle button "Anual" appears in the chart type pill bar (same pattern as Index/Δ%). URL state: `?tagg=0` when user turns it off. IPC102A: 416 months → 35 yearly points.

**Raw monthly zoom (chart-factory.js)**: When user switches to raw monthly view, `dispatchAction({ type: 'dataZoom', start: X })` zooms to last ~5 years (60 periods) by default. `setOption` alone doesn't apply initial start/end — needed `dispatchAction` after render.

## 2026-04-12 — Register POP201A Split Datasets

POP201A (Nascuti vii pe sexe, medii de rezidenta) was missing from the app — the parent parquet doesn't exist in corpus/parquet/ and the splits were unregistered in DuckDB. The split parquets (POP201A_judete/regiuni/macroregiuni) had been generated but the `12-split-datasets.py` DB registration step never completed. Fixed by re-running `python 12-split-datasets.py --matrix POP201A`. Now registered: 3 children in `matrices`, 3 rows in `dataset_splits`, 15 dimension rows across children.

## 2026-04-12 — Large Dataset Handling: Time Windowing + GROUP BY Bypass

Two improvements for datasets too large to render without explicit filtering:

**GROUP BY bypass** (`dataset_data.py`): The 50k-row rejection check is skipped when `group_by` param is present. Aggregated queries (GROUP BY) collapse rows significantly, so the raw-rows rejection no longer applies.

**Server-side time windowing** (`dataset_data.py`): Datasets >500k rows auto-filter `TIME_PERIOD` to the latest N periods that fit within the 50k row budget. Period count estimated as `max(min_periods, int(50000 / rows_per_period))`. For datasets >5M rows, `min_periods=2` to avoid OOM (e.g., POP107D: 21.6M rows → 2-year window ≈ 554k rows scanned). Response includes `time_windowed: true`; frontend shows bilingual notice. Fallback path: if parquet DISTINCT scan OOMs, falls back to metadata `time_year_min/time_year_max`.

**DuckDB memory** (`db.py`): Raised from 200MB to 400MB to support larger parquet scans.

**Frontend** (`explore-app.js`): `_autoApplyTimeWindow()` estimates safe period count and pre-selects recent TIME_PERIOD values before the first fetch. `_showServerTimeWindowNotice()` displays a collapsible amber banner when the server applies windowing.

Verified: SOM101F (1.3M), EXP102J (764k), POP107D (21.6M) all load with time windowing.

## 2026-04-12 — Fix Chart Selector Gaps (Taxonomy Items 3, 4, 5)

Fixed three chart selection issues identified by the taxonomy visual audit:

**Backend (`chart_selector.py`)**:
- Population pyramid eligibility: relaxed `gender_count` threshold from ≤3 to ≤6. INS "Sexe si medii" dims mix gender+residence (Total+M+F+Urban+Rural = 5), making the old threshold too restrictive. 69 datasets now eligible.
- Region/macroregion geo_count: was 0 for non-county geo datasets (coverage profiler only tracked `geo_county_count`). Now falls back to dimension count or known geo level sizes (8 regions, 4 macroregions). Enables choropleth for ~24 region-level datasets.

**Frontend (`explore-app.js` v53)**:
- Default chart type now uses `chart_selector`'s `ranked_charts` recommendation instead of hardcoded `timeChartTypes[0]` = 'line'. Maps backend `bar_vertical` → frontend `bar` alias.
- Added `population_pyramid` to snapshot chart types when both age and gender dims exist.
- Rebuilt eval baseline (1,959 datasets).

**Verified via Playwright**: COM109B (area_stacked ✓), TFA0494 (population_pyramid ✓), PNS101D_regiuni_anual (choropleth+bar ✓), PPA103A_lunar_lei_buc (bar ✓), POP107D (no regression ✓).

## 2026-04-11 — Dataset Shape Taxonomy + Visual Audit

Created `scripts/chart-taxonomy.py` — classifies all 1,958 datasets into 12 shape clusters based on DuckDB metadata (archetype, dims, unit type). Picks 2-3 exemplars per cluster, outputs `docs/chart-taxonomy.md` and `data/eval/chart_taxonomy.json`. `--screenshot` flag takes Playwright screenshots of all 33 exemplars.

**Visual audit findings** (added to `docs/chart-taxonomy.md` Gap Analysis section):
- 71% of datasets (1,386) render suboptimally
- Top 3 issues: choropleth 50k limit (23%), cluttered high-cardinality lines (27%), wrong chart type for percentage data (15%)
- Population pyramid, categorical snapshot, and geo snapshot clusters all picking wrong chart types
- Backlog updated with 5 prioritized chart_selector fixes

## 2026-04-11 — Analytical Chart Modes (Index, YoY, Ranking, Distribution)

Added 4 pure-frontend chart transform modes to the Lens UI:
- **Index/Rebase**: divides each series by first value × 100, enables cross-scale comparison
- **YoY Δ%**: year-over-year percentage change, highlights growth vs contraction
- **Ranking/Bump**: inverted Y-axis with rank positions over time (capped 15 series)
- **Distribution strip**: box plot + jitter scatter for geographic spread in snapshot panel

Files: `explore-app.js` (v52), `chart-new-types.js` (v29), `chart-factory.js` (v31), `explore.css`.
Transform buttons (Idx/Δ%) appear in time panel toolbar. Ranking added to chart type picker when ≥3 series. Distribution strip auto-renders below choropleth snapshot.

## 2026-04-11 — View Profile Orphan Cleanup

Deleted 676 orphan view-profile JSON files from `data/corpus/view-profiles/` that had no corresponding parquet file in `data/corpus/parquet/`. These accumulated from removed/split datasets. Remaining: 3,509 VPs matching 3,706 parquets (some parquets have no VP yet — filled via `generate_view_profiles.py`).

## 2026-04-11 — BYOK (Bring Your Own Key) for ask.html

Added per-user API key support to the `/ask.html` chat UI. Users can set their own Anthropic or OpenAI key via a gear icon settings panel in the topbar. Key stored in `localStorage` only — never persisted server-side.

**Frontend** (`ask.html`, `ask.js`): gear icon in topbar opens a dropdown panel with provider select, model input, and password key input. Save/Clear buttons. `🔑` badge on gear when key active. Key included in request payload via `byokPayload()` helper only when set.

**Backend** (`ask.py`, `agent.py`, `llm_client.py`): `AskRequest` extended with optional `provider`, `model`, `api_key` fields. Gate logic updated to allow requests with `api_key` even when `TEMPO_ASK_ENABLED=false`. `api_key` threaded through `run_agent()` → `complete_with_tools()` → SDK constructors (`anthropic.Anthropic(api_key=...)` / `openai.OpenAI(api_key=...)`). `None` key preserves existing env-var behavior.

## 2026-04-11 — URL state persistence for index.html (explore-app.js)

Implemented full URL state persistence in `explore-app.js` (the actual current UI, loaded by `index.html`). Pages are now shareable/bookmarkable with chart type, period, and filter state encoded in the URL.

**Params:** `?code=POP107D&tchart=bar&schart=grouped_bar&period=2022&filters={"COL":"val"}`  
- `tchart` — time panel chart type (omitted if default `line`)  
- `schart` — snapshot panel chart type  
- `period` — snapshot period ID (omitted if latest)  
- `filters` — JSON flat object of active filter selections  

**Writing** — `_syncURL()` calls `history.replaceState()` after every `fetchAndRender()`, chart type button clicks, manual period navigation, and when play stops. Skips `replaceState` during animation (play interval active) to avoid rapid calls.

**Restoration** — `init()` reads `tchart/schart/period/filters` into `_url*` fields. Applied in `showDashboard()` after `panelSetup` is computed (so available chart types are known). Each param is consumed (set to null) after first use. Filters are applied in `renderFilters()` via `_urlFilters` fallback, consumed at end of first `fetchAndRender()`.

Note: previous session had implemented this for `dataset-page-v2.js`/`dataset.html` which is not linked from the main app. That work is superseded by this.

## 2026-04-11 — URL state persistence for dataset page (SUPERSEDED)

`?code=`, `view=`, `chart=`, `period=`, `filters=` now all written via `replaceState` on every render and restored on page load. Pages are fully shareable/bookmarkable.

**Writing** — `_syncURL()` called after every `fetchAndRender()` and on tab switches. Builds `filters` as JSON of `controlsPanel.getValues()` (time column excluded — stored as `period`).

**Restoration** — `init()` reads all params into `_urlView/Chart/Period/Filters`. View is applied immediately in the initial `switchView()` call. Chart type is restored before `renderChartSelector()` so the active button renders correctly (bug fix: initial code restored after render, making the active button wrong). Handles both primary `chart_type` and toggle variants (`toggles[]`). Filters passed as `initialValues` to `ViewControlsPanel` constructor, overriding computed defaults in `resolveDefault()`.

**Files modified:**
- `app/static/js/dataset-page-v2.js` — `_syncURL()`, URL param reading, restoration logic
- `app/static/js/view-controls.js` — `initialValues` constructor param + `resolveDefault()` override

Verified with Playwright: direct URL load restores Snapshot tab + H-Bar chart + single age group filter correctly.

## 2026-04-11 — Chat UI for /api/ask + OpenAI query guardrail

**Chat UI (`app/static/ask.html` + `app/static/js/ask.js`)**

New page at `/ask.html` with a full multi-turn chat interface for the NL→Data agent. Features: multi-turn history (user/assistant turns passed back to `/api/ask`), markdown-lite rendering (bold, code, lists, headings), citation pills linking to dataset pages, amber warnings banner, collapsible tool trace, data table (up to 200 rows with sticky headers), and auto-chart for line/bar/area primary chart types via inline eCharts. Empty state with 5 example questions. "Ask" link added to main topbar.

**Query guardrail (`app/services/agent.py`)**

One-shot guardrail in `run_agent()`: when the model hits `end_turn` without ever calling `query_dataset_data` but search returned results, injects a synthetic `user` turn forcing schema + query. Fires once per run max (`_guardrail_fired` flag). Targets OpenAI models that ignore the system prompt directive; Anthropic models never trigger it.

**Files modified/created:**
- `app/static/ask.html` — new chat page
- `app/static/js/ask.js` — chat logic
- `app/static/index.html` — "Ask" link in topbar
- `app/services/agent.py` — query guardrail

## 2026-04-10 — FTS relevance ordering fix + agent search limit restored

**FTS ordering fix (`app/services/dataset_search.py`)**

`search_datasets()` was using FTS only as a candidate filter (`WHERE matrix_code IN (…)`) then re-sorting by `ultima_actualizare DESC`, which discarded all BM25 relevance signal. When `q` is provided and FTS succeeds, and `sort='updated'` (the default), the function now orders by `list_position(ARRAY[...ranked codes...], m.matrix_code) ASC` — preserving the BM25 relevance ranking exactly. Explicit sort overrides (`sort='name'`, `sort='rows'`) are unaffected.

Result: massive improvements across all 17 eval questions. Notable fixes:
- "populatie pe judete": LOC108B (construction permits) was #1 → now POP108D/POP107D at #1-2
- "exporturi pe tari": TUR105F (tourism) was #1 → now INT106B/EXP101I at #1-2
- "accidente de munca": AMG130M (unemployment) was #1 → now ACC102B (accidents) at #1
- "energia electrica": now IND118A (electricity production) leads, not export datasets
- "cheltuieli educatie buget": now CAV101C (education-specific) leads

Baseline rebuilt and committed: `data/eval/agent_search_baseline.json`.

**Agent search limit restored (`app/services/agent.py`)**

Tool schema default and `_handle_search_datasets` limit both reverted from 6→10. AMG159E (regional unemployment, the best geo dataset for "rata somajului") was sitting at position 7 and getting cut off. Token overhead is minimal (~200 toks/search × 3 searches).

**Files modified:**
- `app/services/dataset_search.py` — FTS ordering via `list_position()`
- `app/services/agent.py` — limit 6→10 in schema + handler
- `data/eval/agent_search_baseline.json` — rebuilt from improved search

## 2026-04-09 — Agent spec doc, OpenAI provider bugfix, search strategy hardening

First end-to-end test of `POST /api/ask` after Step 2/3b. Three fixes and one new doc.

**New doc: `docs/agent-setup.md`**

Full setup + usage spec for the NL→Data agent: prerequisites (anthropic/openai SDKs, API keys), env var table (`TEMPO_ASK_ENABLED`, `TEMPO_LLM_PROVIDER`, `TEMPO_LLM_MODEL`, `TEMPO_ASK_MAX_TOOL_CALLS`), minimal launch commands for both providers, full API reference for `POST /api/ask` (request/response shape, error codes), worked curl + Python + HTTPie examples, test-question bank (EN/RO + edge cases), tool-trace inspection snippet, and limitations. The agent was previously undocumented — config-only.

**Bugfix: `_to_openai_message` in `app/services/llm_client.py`**

OpenAI provider crashed on the second tool-calling iteration with `KeyError: 'name'`. Root cause: `_assistant_turn` produces an assistant message where `tool_calls` are *already* in OpenAI's `{id, type, function: {name, arguments}}` shape, but `_to_openai_message` tried to re-format them using our internal `{id, name, input}` shape — so it accessed `tc["name"]` on a dict that only has `tc["function"]["name"]`. Also fixed a related bug: `msg.get("text")` → `msg.get("content")` (the assistant message stores text under `"content"`). Fix: just pass `msg["tool_calls"]` through as-is.

Only affected OpenAI provider (default is Anthropic), so it slipped through the initial Step 2 testing.

**Agent search strategy hardening**

First curl test ("unemployment rate in Romania by county for 2023") exposed that the agent:
- Called `search_datasets` exactly once with the full verbose query + `has_geo=true`
- `has_geo=true` excluded AMG157G (national, best match — `has_geo=false`)
- Got fertility (POP203C) and tourism (TUR109C) as top hits
- Gave up without retrying, without `get_dataset_schema`, without querying data

Baseline investigation confirmed the FTS ranker is actually fine: "What is the unemployment rate by county in 2023?" ranks AMG157G at #1 *without* the `has_geo` filter. The entire failure was caused by the agent's over-eager use of the geo filter.

Rewrote the `SYSTEM_PROMPT` search-strategy section in `app/services/agent.py`:
- Explicit stopword-stripping rule (strip "rate", "by", "in", year numbers)
- "Prefer Romanian keywords on the first search" (dataset names are Romanian)
- **"Do NOT set `has_geo=true` on the first search"** — this was the load-bearing rule
- "Read the entire result list, not just the top hit" — a match at position 7 beats a non-match at position 1
- "Retry at least once if results look unrelated"
- "When user asks for a granularity that doesn't exist, use the closest one and explain" — INS publishes most labor-market indicators at `regiuni de dezvoltare` (8 NUTS-2), not `județe` (42 counties)
- Added a worked example walking through the unemployment query end-to-end

**Eval harness expansion**

Added two regression questions to `data/eval/agent_questions.yaml`:
- "What is the unemployment rate by county in 2023?" (verbose EN w/ stopwords)
- "Care este rata șomajului pe județe în 2023?" (same intent in RO)

Rebuilt `data/eval/agent_search_baseline.json` via `scripts/build_agent_search_baseline.py` → 17 questions total, 3,017 bytes.

**Minor: debug logging in `app/routers/ask.py`**

Added `log.exception("Agent failed")` in the except block so unhandled agent errors now print their full traceback to the uvicorn terminal. Previously the only visible artifact was the short `"Agent error: {e}"` in the 500 response body.

**Files modified:**
- `app/services/llm_client.py` — bugfix in `_to_openai_message`
- `app/services/agent.py` — rewrote search strategy section of SYSTEM_PROMPT + worked example
- `app/routers/ask.py` — traceback logging
- `data/eval/agent_questions.yaml` — 2 new questions
- `data/eval/agent_search_baseline.json` — regenerated
- `docs/agent-setup.md` — new file

**Not done (deferred):**
- Search-side stopword filter in `dataset_search.py` (Layer 3 in plan) — skipped, since the baseline showed FTS ranking is already fine once the agent stops adding `has_geo=true`. Revisit only if the prompt fix alone doesn't close the gap.
- End-to-end re-test of the curl question with updated prompt — requires a live API key; deferred to the user.

---

## 2026-04-08 — Dev MCP: agent search eval + view-profile audit (Step 3b part 2)

Shipped the remaining two eval tools for Step 3b, plus a critical FTS bug
fix uncovered by the first one.

**New tools:**

- `tempo_eval_agent` — search-quality regression detection. Runs
  `search_datasets()` for every question in `data/eval/agent_questions.yaml`
  (15 seed questions covering population, unemployment, inflation, GDP,
  etc.) and diffs the top-K hits against `data/eval/agent_search_baseline.json`.
  Same baseline-diff pattern as `tempo_eval_chart_selector`.
- `tempo_check_view_profiles` — diagnostic audit of `corpus/view-profiles/`.
  Cross-checks against the parquet corpus and DB `matrix_profiles` table to
  surface missing VPs, orphan VPs, schema version drift, archetype
  mismatches, parse errors, and top warning categories.

**New files:**

- `app/services/agent_eval.py` — shared `run_search_eval(questions, top_k)`
  + `diff_against_baseline()` + lightweight YAML loader (falls back to a
  minimal parser if PyYAML isn't installed).
- `scripts/build_agent_search_baseline.py` — baseline generator, same
  compact one-line-per-question format used for `chart_selector_baseline`.
- `data/eval/agent_questions.yaml` — 15 seed questions.
- `data/eval/agent_search_baseline.json` — committed baseline (2.6 KB).

**Search bugs found and fixed while calibrating the eval:**

1. **FTS sort direction was inverted.** `_fts_search()` in
   `dataset_search.py` had `ORDER BY score` (DuckDB default ASC) with
   `LIMIT 200`. BM25 returns *higher* scores for *more* relevant docs, so
   the candidate pool contained the 200 *worst* matches. POP107D/POP108D
   scored 4.93 for `"populatie pe judete"` but were never seen — the top
   200 were scores 0.066-0.086. Fixed to `ORDER BY score DESC`. This is a
   serious production bug: search quality jumps immediately on every query.
2. **Outer `ORDER BY` was non-deterministic.** Many canonical datasets
   share `ultima_actualizare` values (or both are NULL), and there was no
   tie-breaker. Result: same query returned different orderings across
   runs, and the baseline/eval diff was perpetually flaky. Added
   `m.matrix_code ASC` as the secondary sort on every branch of
   `sort_map`. First eval run now reports `ok=15, drift=0` stably across
   repeated runs.

**View-profile audit findings (initial run):**

- 197 parquets in `corpus/parquet/` lack view-profile JSONs — the generator
  needs a re-run to catch up.
- 675 orphan VPs — files for datasets no longer in the corpus.
- 49 archetype mismatches on `PNS101D_*` splits (VP says `geo_time`, DB
  says `geo_only`) — schema drift between the VP generator and the
  classifier.
- 933 VPs carry warnings — top categories: `multi_unit` (490),
  `very_sparse` (230), `sparse_data` (205), `high_cardinality` (78),
  `short_series` (40).

All follow-ups logged in `docs/BACKLOG.md` under dedicated "Search quality"
and "View profiles" sections.

**Step 3 status:** Eval sub-steps complete. Remaining: Playwright frontend
probing and gated mutation tools.

## 2026-04-08 — Dev MCP: chart_selector eval harness (Step 3b)

Added regression-detection for the chart-selection engine. Every dataset is
scored on-demand and diffed against a committed baseline so that changes to
`chart_selector.py` surface concrete drift instead of silent ranking shifts.

**New files:**

- `app/services/chart_selector_eval.py` — shared `_load_inputs()`,
  `evaluate_all(top_n=3)`, and `diff_against_baseline(baseline, current,
  score_threshold)`. Bulk-loads every dim/profile/coverage/trend in one go
  (~1s for the whole corpus) instead of calling `get_dataset_meta` per
  dataset (would be ~20s).
- `scripts/build_chart_selector_baseline.py` — run-once builder that writes
  `data/eval/chart_selector_baseline.json` (1959 datasets, 290 KB, custom
  compact format with one dataset per line so git diffs stay tight).
- `tools/tempo-dev-mcp/server.py` :: `tempo_eval_chart_selector` — MCP tool
  that loads the baseline, re-runs `evaluate_all()`, and returns a compact
  report: `primary_changes` (full), `top_set_changes` (cap 50),
  `confidence_changes` (cap 30), `score_drifts` (cap 50), `missing`/`added`
  (cap 30). Uses the same `evaluate_all()` as the build script so baseline
  generation and diffing are guaranteed in lock-step.

**Non-determinism bug fixed:** the first baseline showed `ACC102C`'s top-3
chart set flipping between `[…, horizontal_bar]` and `[…, stacked_bar]` on
re-runs. Root cause: `_load_inputs`'s per-dimension `dim_type` majority-vote
query had no tie-breaker on `COUNT(*) DESC`, so DuckDB returned tied rows in
arbitrary order. `ACC102C`'s `UNIT_MEASURE` dim has exactly one option parsed
as `unit` and one as `indicator` — a perfect tie.

Fix: add `MIN(dopt.option_offset) ASC` as the secondary sort. This matches
the runtime `dataset_meta.py:172` behavior, where `max(type_counts,
key=type_counts.get)` implicitly picks the first-inserted key on ties, and
insertion order there is `ORDER BY option_offset`. Verified ACC102C now
agrees between runtime and eval (`UNIT_MEASURE` dim_type = `unit`, third
chart = `horizontal_bar`).

Five consecutive eval runs after the fix report `ok=1959, drift=0`.

**To refresh the baseline after an intentional `chart_selector.py` change:**

    python scripts/build_chart_selector_baseline.py
    # then inspect `git diff data/eval/chart_selector_baseline.json`

## 2026-04-08 — Agent: fix double-counting via marginal Total rows

`POST /api/ask`'s `query_dataset_data` tool was double-counting whenever it
aggregated (`group_by`) over a dataset that publishes a marginal `Total` row
alongside its breakdown rows. Phase 8 had only stripped totals from ~49 of
3,600 parquets, so the bug was latent on the rest.

**Fix** (in `app/services/agent.py`):

- New helper `_detect_total_locks(matrix_code, dimensions, filters, group_by, conn)`
  scans the parquet directly. For each dim that is neither in `group_by` nor in
  `filters`, it issues a `SELECT DISTINCT col WHERE LOWER(TRIM(col))='total'`. If
  any rows come back, that dim is eligible to be auto-locked to its Total value.
  `TIME_PERIOD` is never locked. Datasets without a parquet (parents of split
  datasets like `AMG1010`) return `{}` cleanly.
- `_handle_query_dataset_data` now runs the locked query first when `group_by`
  is set:
  - **Locked query non-empty** → use it, emit
    `Auto-applied Total filters to prevent double-counting: COL=val, …`.
  - **Locked query empty** (non-cross-product marginals — `TFP0512`,
    `AMG1010_*`) → fall back to the unfiltered query and emit a loud
    `POSSIBLE DOUBLE-COUNTING: …` warning with a concrete re-query suggestion
    (e.g. `filters={'SEX': ['Total']}`). The LLM can then self-correct.
- System-prompt section *"Total" rows and double-counting* rewritten to teach
  the LLM the two warning shapes and how to react.

**Verification:**

| Dataset | Query | Before | After |
|---|---|---|---|
| `POP107D` | group_by `[TIME_PERIOD]` | 41.78M (1992) | 41.78M, no warning (parquet pre-stripped, fix is no-op) |
| `FOM104G` | group_by `[TIME_PERIOD]` | **28.25M** (2023, ~5.3× too high) | **5.36M**, warning lists the 3 auto-locked dims |
| `FOM104G` | group_by `[TIME_PERIOD,SEX]` | broken | 2.79M Masculin + 2.57M Feminin = 5.36M ✓ |
| `FOM104G` | filter `SEX=Masculin`, group_by `[TIME_PERIOD]` | broken | 2.79M (auto-lock respects user filter) |
| `TFP0512` | group_by `[TIME_PERIOD]` | inflated SUM | inflated SUM **+ POSSIBLE DOUBLE-COUNTING warning** with re-query hint |

**Design choices / non-obvious bits:**

- Detection runs against the parquet, not metadata. Reason: `dimension_options.option_label`
  has trailing-whitespace artefacts (`'Total '`) and `sdmx_codes.sdmx_value` may
  not match the parquet's literal value. Querying the parquet is authoritative
  and avoids the metadata→parquet normalization mismatch.
- Detection cost is one `DISTINCT … WHERE` per candidate dim. For typical
  4-dim datasets that's 2-3 extra queries (~50ms each on the corpus parquets).
  Skipped entirely when `group_by` is empty or no candidate dims exist.
- Only TRIM/LOWER='total' is treated as a marginal-total marker. Variants like
  `'Total persoane'` or `'Industrie - total'` are intentionally NOT matched —
  those are standalone categories, not aggregates of other rows.
- `TIME_PERIOD` is excluded from candidates: time can never be a "Total".

**Known follow-up** (added to `docs/BACKLOG.md`): the pre-existing
0-rows-strip-Total fallback can still hide an explicit Total filter when the
parquet really has no `(Total, Total, …)` cross-product cell (TFP0512 case).
Fix is to only strip a dim's Total filter when the parquet has no Total for
that dim.

**Files modified:**

- `app/services/agent.py` — added `_detect_total_locks`, rewrote the
  aggregation-time guard in `_handle_query_dataset_data`, updated SYSTEM_PROMPT.
- `docs/BACKLOG.md` — checked off the double-counting item under Step 2,
  added the fallback follow-up.

---

## 2026-04-08 — Dev MCP Step 3a: introspection bundle (5 new tools)

Extended `tools/tempo-dev-mcp/server.py` with the introspection half of Step 3
(read-only, no new dependencies). Tools 7–11:

- **`tempo_routes`** — lists every FastAPI route on `app.main:app` with
  methods/path/name/endpoint/tags. API routes sorted before static mounts. Useful
  to verify new routers mounted (e.g. confirms `/api/ask` is present).
- **`tempo_call_endpoint(method, path, params_json?, body_json?)`** — hits any
  route in-process via `starlette.testclient.TestClient`. No live server needed.
  Returns `{status_code, content_type, body, json?}`, body capped to 8000 chars.
  `raise_server_exceptions=False` so 500s come back as a status code rather than
  raising.
- **`tempo_outdated(days=180, limit=50)`** — datasets sorted by `ultima_actualizare`
  age. Returns counts (`fresh / stale / unknown_null`) plus oldest and null
  samples. Bundles a caveat about the underlying column being unreliable
  (already tracked under "Data Pipeline" in BACKLOG). Confirmed real numbers:
  1959 total, 453 fresh, 1505 stale (>180d), 1 null.
- **`tempo_pipeline_status(recent_log_count=10)`** — reads
  `data/logs/last-pipeline-run.txt`, parses `data/logs/corpus-audit.json`, lists
  the most recently-modified `*.log` files with mtime/size and ERROR/WARNING
  counts. Logs ≥2 MB skipped to keep response fast.
- **`tempo_dataset_lineage(matrix_code)`** — for one matrix, walks 5 pipeline
  stages (`metadata_json`, `raw_csv`, `parquet_v2`, `corpus_parquet`,
  `view_profile`) reporting presence/size/mtime, plus DuckDB row presence in
  `matrices`/`matrix_profiles`/`dataset_coverage`/`dataset_trends`/
  `dataset_value_profiles`, plus split children and parent.

**Notes / gotchas hit:**
- DuckDB won't bind a parameter into `INTERVAL ? DAY`. Inlined the int (already
  validated) instead of using a placeholder.
- `@mcp.tool()` does not wrap the function — it just registers it on the
  FastMCP instance and returns the original. Direct Python imports can call the
  tools verbatim, no `.fn`/`.__wrapped__` needed.

**Verification:** all 5 tools smoke-tested via direct Python import (the MCP
server itself needs a Claude Code restart to surface them as
`mcp__tempo-dev__tempo_*`). Verified happy paths (real route list,
`/api/categories` 200, `/api/datasets/POP107D` 200, real outdated counts,
real lineage for `POP107D` and split-child `ACC102B_judete_numar_persoane`)
plus error path (`tempo_dataset_lineage("NONEXISTENT")` → clean error).

**Files modified:**
- `tools/tempo-dev-mcp/server.py` — +330 lines (5 new `@mcp.tool()` functions).
- `tools/tempo-dev-mcp/README.md` — added sections 7–11, bumped tool count to 11.
- `CLAUDE.md` — extended Dev MCP table with the 5 new tools.
- `docs/BACKLOG.md` — checked off the introspection rows under Step 3.

**Deferred (still under Step 3):** chart_selector / agent eval harness, Playwright
frontend probing, gated mutation tools.

---

## 2026-04-07 — LLM Agent Step 2: v1 user-facing NL→Data agent

Built `POST /api/ask` tool-calling agent on top of the existing service layer.
Gated by `TEMPO_ASK_ENABLED` (disabled by default). LLM never generates SQL —
all data access goes through `query_builder.build_data_query()`.

**New files:**
- `app/services/llm_client.py` (~190 lines) — provider-agnostic `complete_with_tools()`
  returning a normalised `LLMResponse{stop_reason, text, tool_calls}`. Supports
  Anthropic (primary, SDK 0.89.0) and OpenAI backends with shared message/tool
  format translation helpers.
- `app/services/agent.py` (~390 lines) — 4 tools (`search_datasets`,
  `get_dataset_schema`, `query_dataset_data`, `list_categories`), ~2.3k-char
  system prompt (bilingual workflow, Romanian vocabulary cheatsheet, "Total"
  gotcha), `run_agent()` loop (max 8 iterations, dispatches tool calls,
  accumulates `tool_trace`, attaches `chart_spec` from `chart_selector` for the
  last queried matrix).
- `app/routers/ask.py` (~35 lines) — POST `/api/ask` endpoint, returns 404 when
  disabled, 500 on agent error.

**Modified files:**
- `app/config.py` — added `ASK_ENABLED`, `LLM_PROVIDER`, `LLM_MODEL`,
  `ASK_MAX_TOOL_CALLS` environment flags.
- `app/main.py` — mounted `ask.router` under `/api`.

**Key design decisions:**
- Agent reuses the existing shared service layer (`dataset_search.py`,
  `dataset_meta.py`, `query_builder.py`) — same code paths as the FastAPI
  routes and the dev MCP server.
- `query_dataset_data` handler mirrors `routers/dataset_data.py`: legacy
  `_nom_id` column resolution, `primary_unit_type`-based agg_func
  (SUM/AVG), 5k row cap with `limit+1` truncation detection, and auto-retry
  after stripping `Total`/`TOTAL` filter values when a query returns 0 rows.
- Anthropic provider packs all tool results in a single `user` turn; OpenAI
  uses individual `tool` messages — `run_agent()` branches on
  `config.LLM_PROVIDER` to produce the right shape.
- `chart_spec` is not built per-query during the loop — only attached once
  after `end_turn` for the last queried matrix (avoids repeated work).

**Verified offline (no API key required):**
- `TOOLS` schema validation, `SYSTEM_PROMPT` contains required vocabulary
- `search_datasets("somaj pe judete")` → 200 hits; `search_datasets("unemployment")` → 9 hits
- `get_dataset_schema("POP107D")` → 6 dims, values capped correctly
- `query_dataset_data("POP107D", group_by=["TIME_PERIOD"])` → 34 rows, SUM agg
- Auto-retry: `POP107D` with `SEX=Total` filter → 0 rows → retry without filter → 34 rows + warning
- `list_categories()` → 339 entries (levels 0–2 only, filtered from ~200k)
- Disabled endpoint returns 404 with `{"detail": "Ask endpoint is disabled"}`
- App mounts cleanly with `/api/ask` in the route list

**Bug fixed during implementation:**
- `_handle_list_categories` used the wrong column names (`code`, `name`,
  `parent_code`) — actual schema is `context_code`, `context_name`,
  `parent_code`, `level`. Fixed + filtered to levels ≤ 2 to avoid dumping
  the entire category tree into the prompt.

**Still pending:**
- Live end-to-end test with a real `ANTHROPIC_API_KEY` (offline plumbing
  verified; LLM loop itself not exercised yet).
- Dependency pinning: `anthropic>=0.40` should be added to `requirements.txt`.
- Optional: a tiny chat UI for `/api/ask` — currently only curl-testable.

**How to run live test:**
```bash
source ~/devbox/envs/240826/bin/activate
TEMPO_ASK_ENABLED=true ANTHROPIC_API_KEY=... \
  uvicorn app.main:app --reload --port 8080

curl -s -X POST localhost:8080/api/ask \
  -H 'Content-Type: application/json' \
  -d '{"question": "Care este populația Clujului în 2023?"}' | jq
```

## 2026-04-07 — MCP corpus quality fixes: geo fallback, unit classifier, chart selector

Three fixes targeting classification/profiling gaps that cascaded into wrong chart selection:

**Fix 1: chart_selector.py — geo_count NULL fallback** (`app/services/chart_selector.py:67-76`)
- When `geo_county_count` is NULL in coverage data but `has_geo=True` and `geo_levels` contains 'county', now falls back to dimension option_count (or 42, Romania's county count)
- Fixes choropleth eligibility for parent/sparse datasets like LOC108B

**Fix 2: 11-coverage-profiler.py — geo stats when no parquet** (`11-coverage-profiler.py:172-185`)
- Added `else` branch: when no parquet exists, geo stats (county count, national/locality flags) are estimated from `dimension_options_parsed` metadata using `dim_nids` lookup
- LOC108B: `geo_county_count` now correctly shows 42 (was NULL)

**Fix 3: 10-classify-dimensions.py — expanded unit recognition** (`10-classify-dimensions.py:82-200`)
- Expanded `UNIT_MAP` with ~30 new entries: physical units (litri, kilograme, grame, mp, m2, m3, mii litri, mii m3), count variants (perechi, capete, mii capete, familii, gospodarii), energy (kwh, mwh, gwh, gigacalorii), distance, etc.
- Added `UNIT_KEYWORDS` regex fallback after exact-match fails — 10 patterns covering lei/euro/currency, procent, weight, volume, area, distance, energy, time, index, count
- Remaining 172 unknowns are genuinely composite/unusual strings (e.g. "lei preturile anului curent", "echivalent norma intreaga")

**Verification:**
- Re-ran `10-classify-dimensions.py` and `11-coverage-profiler.py` on full corpus
- `tempo_dataset_info("LOC108B")`: `coverage.geo_county_count = 42`, `chart_selector.primary_chart = choropleth (score 0.85)`
- `tempo_catalog_stats(group_by="unit_type")`: unknown=172 (stable; remaining unknowns are truly composite)

## 2026-04-07 — MCP v2: query tool, catalog stats, FTS search

**MCP v1 documentation:**
- Created `tools/tempo-dev-mcp/README.md` — full documentation for all tools with parameters, return shapes, examples, architecture, and limitations
- Expanded CLAUDE.md MCP section with parameter signatures for all tools

**New MCP tools (v2):**
- `tempo_query(matrix_code, filters?, group_by?, limit?)` — aggregated data queries wrapping `query_builder.build_data_query()`. Auto-picks agg function (AVG for percentage/time_unit, SUM otherwise). Returns columns, rows, row_count, and the generated SQL.
- `tempo_catalog_stats(group_by?)` — corpus-level breakdowns by archetype/category/unit_type/geo/time_granularity. Shows 1,225 canonical datasets across 5 archetypes.

**FTS search upgrade:**
- Created `scripts/build-search-index.py` — builds a sidecar `data/corpus/search.duckdb` (14 MB, ~2s) with DuckDB FTS over matrix names (RO+EN), 92k bilingual tags, definitions, and category paths.
- Updated `app/services/dataset_search.py` — FTS-first strategy with LIKE fallback. Sidecar connection cached as lazy singleton.
- Before: "unemployment rate" → 0 results. After: → 130 results matching through English tags and definitions.
- Before: "somaj" → 9 results (name match only). After: → 61 results (matches tags and definitions too).
- FTS uses `stemmer='none'` — Romanian morphology not handled; "populatia" won't match "populatie". Planned for v3 with embeddings.

**Key decisions:**
- Sidecar DB (`search.duckdb`) avoids write-lock conflicts with `metadata.duckdb`. Read-only at runtime.
- `tempo_query` never generates SQL from LLM input — wraps the existing safe `build_data_query()`.
- Category stats show 71 datasets without ancestor_codes (split sub-datasets) — acceptable for v2.

## 2026-04-07 — Step 1: Service layer extraction + tempo-dev MCP server

**Service layer refactor:**
- Extracted `search_datasets()` → `app/services/dataset_search.py` (from `app/routers/datasets.py:list_datasets`)
- Extracted `get_dataset_meta()` → `app/services/dataset_meta.py` (from `app/routers/datasets.py:get_dataset`)
- Route handlers now thin wrappers — same API behavior, verified via curl
- Both services accept optional `conn=` param for DuckDB cursor injection (defaults to `get_conn()`)

**MCP server (`tools/tempo-dev-mcp/server.py`):**
- 4 tools: `tempo_dataset_info`, `tempo_search_datasets`, `tempo_chart_signature`, `tempo_sample`
- Uses official `mcp` Python SDK (FastMCP), stdio transport
- Registered in `.mcp.json` at repo root (repo-local, auto-loaded by Claude Code)
- All tools import from the shared service layer — no duplicated logic

## 2026-04-07 — LLM Tooling Plan (dev MCP + NL→Data agent)

Designed a 4-step hybrid roadmap for adding LLM capabilities to the project. Plan stored at `~/.claude/plans/peppy-fluttering-bubble.md`.

**Architectural decisions:**
- **Not literal NL2SQL.** With 3,632 different parquet schemas, the hard problem is "which parquet + which columns," not "what SQL." A tool-calling agent over the existing safe `query_builder.build_data_query()` is the right shape — SQL is never LLM-generated.
- **Dev MCP first.** A separate `tempo-dev` MCP server compounds across every future Claude Code session. Refactoring to extract `dataset_search.py` + `dataset_meta.py` is the shared substrate for both the MCP and the user-facing agent — one refactor, three reuses (MCP, agent, existing UI route).
- **Hybrid build order:** minimal MCP (4 tools) → v1 user agent → expand MCP (informed by v1's friction) → v2 features.
- **Provider abstraction** via `app/services/llm_client.py` (Anthropic + OpenAI), swappable through `TEMPO_LLM_PROVIDER` env var.
- **DuckDB FTS in sidecar** `data/corpus/search.duckdb` to avoid the metadata.duckdb write-lock.
- **Chart selection stays rule-based** — agent never picks chart types; `chart_selector.select_charts()` is called after the agent settles on data.

Backlog updated with the full task breakdown for Steps 1–4. Implementation starts with Step 1 (extract services + minimal MCP server).

## 2026-04-07 — Split Dataset Metadata Propagation

**Fixed split sub-datasets missing from "Actualizate recent" and lacking "Despre" panel:**
- Root cause: split children (e.g. `LOC108C_numar`) have `is_canonical=TRUE` but `ultima_actualizare=NULL` and `definitie=NULL` — they never inherited metadata from their parent
- Added `propagate_split_metadata()` in `update-pipeline.py`: copies `ultima_actualizare`, `definitie`, `metodologie`, `observatii` from parent matrix to all split children via `dataset_splits` JOIN
- Runs automatically after `sync_ultima_actualizare()`; also available standalone via `python update-pipeline.py --propagate-splits`
- Applied one-time fix to existing DuckDB: canonical 2026 dataset count went from 8 → 38
- English `definitie` was already handled correctly — `_load_en_meta()` in `datasets.py` falls back to parent code for splits

**Fixed TEMPO Online link for split datasets:**
- `explore-app.js`: INS link now uses `m.parent_matrix_code || m.matrix_code`, so split variants like `LOC108C_numar` link to `ind=LOC108C` on statistici.insse.ro instead of a broken URL

## 2026-04-06 — Update Pipeline Improvements

**Fixed stale "Actualizate recent" on landing page:**
- Root cause: `10-import-metadata.py` fails with `lang` column schema mismatch (tracked in backlog), so `matrices.ultima_actualizare` in DuckDB was never refreshed after pipeline runs
- Added `sync_ultima_actualizare(codes, lang)` in `update-pipeline.py` — reads `ultimaActualizare` from freshly fetched metadata JSONs and directly updates DuckDB; runs after every pipeline execution regardless of `10-import-metadata.py` success

**Incremental run tracking:**
- Added `data/logs/last-pipeline-run.txt` marker — written after each successful run
- `update-pipeline.py` now auto-applies `--since {last_run_date}` when no explicit `--since` given, so re-running the script daily only processes genuinely new matrices
- New flags: `--force-meta` (re-fetch metadata JSONs without re-downloading CSVs/parquets), `--all` (ignore last run date)

**Quieted verbose pipeline output:**
- `12-split-datasets.py`: per-matrix progress lines moved to DEBUG (only visible with `--debug`); summary totals remain at INFO
- `generate_view_profiles.py`: JSON profile dump now only prints with `--debug` flag

## 2026-04-06 — Theme Icons, INS Link, UI Polish

**Category section theme icons:**
- Replaced category emojis with transparent PNGs from `app/static/img/themes/`
- Icons bottom-aligned with section header text, naturally rising above via flex layout
- Mapping: society (A), economy (B), environment (E), transport (F), sustainable development (G+H)
- Subcategory left indent removed for cleaner alignment

**Dataset header:**
- Added "INS ↗" link to official TEMPO Online page (`statistici.insse.ro/tempoins/...?ind={code}`) next to download buttons
- Link respects current UI language (ro/en)

## 2026-04-06 — Landing Redesign, Downloads, UI Polish

**Landing page redesign:**
- Replaced hero section with compact header + themed KPI cards (Czech CSO style)
- KPI cards: real values from parquet (salary, GDP, tourism arrivals, etc.) with sparklines + YoY change
- Category grid switched to CSS columns layout with emoji icons, inline subcategories, bold stats
- Notice bar (dismissable, "not official gov.ro"), permanent footer with GitHub link
- OS `prefers-color-scheme` theme detection (defaults to light)
- OG/SEO meta tags: description, og:image, twitter:card — domain `ins.gov2.ro`

**Data download (CSV / XLSX):**
- New `GET /api/datasets/{code}/download?format=csv|xlsx&filters=...&lang=ro|en` endpoint
- On-the-fly generation from parquet via DuckDB + stdlib csv / openpyxl (no pandas)
- Language-aware: when `lang=en`, translates dimension values via `sdmx_codes` table
- Download buttons (↓ CSV / ↓ XLSX) in dataset header; pass active filters + current lang at click time

**SDMX endpoints** (already existed, confirmed working):
- `GET /sdmx/2.1/data/INS,{flow}/{key}` — SDMX-ML 2.1 GenericData XML
- `GET /sdmx/2.1/datastructure/INS/{flow}/1.0` — DSD with codelists
- `GET /sdmx/2.1/dataflow/INS/{flow}/1.0` — Dataflow definition

**Other UI improvements:**
- Dataset code badge in title (accent-colored, replaces meta-pill)
- `?lang=en` URL parameter — opens app in English (useful for sharing with international users)

## 2026-04-04 — Alpha Preview & UI Polish

Prepared alpha preview with multiple UI/UX improvements across the Lens dashboard.

**Insight cards redesign:**
- Replaced meaningless Average card with **Overall Change** (first→last period % change, colored +/-)
- Replaced meaningless Range card with **Coverage** (period count + category count)
- Replaced div-bar sparkline with **SVG polyline** sparkline (`viewBox` + `preserveAspectRatio="none"` + gradient fill polygon)
- Fixed `--text-3` CSS variable (undefined, causing transparent backgrounds in 8+ places)

**Tooltip totals:**
- All multi-series charts (line, area, stacked bar) now show ∑ total on top of tooltip before series breakdown
- Updated formatters in both `chart-factory.js` and `chart-new-types.js`

**Data table enhancements:**
- Added dropdown column filters (like duckdb-browser) with active state styling
- Zebra striping, sticky filter row, filtered/total row count display
- Client-side filtering via exact string match, all filters AND-combined

**Landing page:**
- Redesigned `index.html` as a public-facing landing page (old version preserved as `index-old.html`)
- Added language flag icons (EN/RO SVGs)

**Deployment:**
- Merged `claude/deploy-flyio-uvicorn-7MxCw` branch — updated paths for `corpus/` data layout
- Added deploy scripts: Oracle Cloud (`deploy.sh`, nginx config, systemd service), HF Spaces (`Dockerfile`)
- Updated `fly.toml` with corpus-aware `TEMPO_DATA_DIR`

## 2026-04-03 — Chart Selection Engine v2

Comprehensive overhaul of `app/services/chart_selector.py` scoring engine.

**Unit-type awareness:**
- Signature now includes `primary_unit_type` and `unit_types` from matrix_profiles
- Percentage data strongly prefers `area_stacked` (parts-of-whole visualization)
- Index/rate data boosts `line` chart (continuous trends are meaningful)
- Currency/count data gives small bonus to comparison bars and bubble charts
- Index data penalizes `bar_vertical` (bar heights misleading for base-100 values)

**Scoring rebalancing:**
- `bar_vertical` base lowered from 0.5 to 0.45, penalized for long time series (>=10 pts: -0.15)
- `area_stacked` base raised from 0.3 to 0.4, big boost for percentage+small-series data
- Seasonal data: line gets +0.15 (was +0.05), bar_vertical gets -0.10
- Sparse data penalties added to area_stacked (-0.15), stacked_bar (-0.10), small_multiples (-0.10)

**Confidence scoring:**
- Each recommendation now includes `confidence` (high/medium/low) based on score gap to runner-up
- Complementary chart pairs annotated (e.g., choropleth ↔ line, pyramid ↔ line)

**Deterministic tie-breaking:**
- When scores tie, specific/informative charts win (choropleth > line > bar_vertical > table)

**Smarter role assignment:**
- `assign_roles()` now returns `filter_hints` (single_select/multi_select/pill_group per dim)
- `defaults` dict with recommended initial filter state (e.g., time='latest', exclude_total=True)
- Line series selection prefers 2-6 option dims over raw minimum cardinality
- Stacked charts prefer stackable (2-6 option) dims for series role

**Eliminated recursive scoring bug** — horizontal_bar and bubble no longer call `_score('choropleth', ...)` to cap themselves; use explicit score ceilings instead.

**Synced** explorer/services/chart_selector.py. Updated test_chart_selector.py with unit-type distribution and confidence reporting.

## 2026-04-02 — Static Site Migration Plan

Designed and scaffolded a static website architecture to replace the FastAPI backend.

**Approach:** DuckDB-WASM for client-side parquet queries + pre-built static JSON for metadata. Zero server at runtime.

**Created:**
- `docs/plans/static-site-migration.md` — Full architecture plan with phased migration path
- `build-static-site.py` — Build script that exports DuckDB metadata → static JSON (categories, dataset index, per-dataset metadata with chart configs)
- `static-site/` — Frontend scaffold:
  - `index.html` — SPA shell (Vue 3 + ECharts + Fuse.js)
  - `js/duckdb-data-client.js` — DuckDB-WASM integration (replaces `query_builder.py`)
  - `js/api-static.js` — Static API client (replaces `app/routers/` endpoints)
  - `js/app.js` — App bootstrap with reactive store
  - Stub files for charts and components (to be ported from `explorer/` in Phase 3)

**Key decisions:**
- DuckDB-WASM queries parquet via HTTP range requests (no full file download)
- Chart selector runs at build time (pre-computed in meta JSON, not ported to JS)
- Fuse.js for client-side fuzzy search (~400KB index)
- Target hosting: Cloudflare Pages + R2 (free tier)

## 2026-03-28–29 — Lens Observatory UI

Built the Lens dark-themed data observatory (`app/static/explore.html`):
- Category grid with trend indicators (green/red bars + avg YoY%)
- Nested subcategory drill-down with breadcrumb navigation
- Full-text dataset search with keyboard navigation (`/`, arrow keys, Enter)
- Light/dark theme toggle (persisted in localStorage)
- EN/RO language switcher with full i18n (40+ strings)
- Collapsible info panel (definition, methodology, notes)
- Smart large dataset handling (auto-filter for >50k rows)

**Two-panel chart dashboard:**
- **Trends panel**: time-axis charts (Line / Area / Stacked Bar) with best-fit series dimension
- **Snapshot panel**: category breakdown for a single period (Grouped Bar / Heatmap / Bubble / Choropleth / Bar / H-Bar) with period navigator (prev/next/play auto-advance)
- `determinePanelSetup()` analyzes dimensions to assign roles per panel
- Both panels share a single data fetch; snapshot filters client-side to selected period
- Independent pill switching per panel
- Fixed `resolveRoles()` x_axis_dim fallback bug in chart-factory.js
- Fixed heatmap dedup bug (xDim === yDim) in chart-new-types.js

**Verified across archetypes:** demographic (POP301A), geo_time (ACC101B_judete), time_series multi-dim (TUR105F), time_series single-dim (COM1071).

## 2026-03-25–27 — Data Quality & Chart Improvements

- Stripped aggregate/total rows from 49 parquet files (28,280 rows removed)
- Added scatter/correlation chart type to view profiles
- Fixed AVG aggregation for percentage-type datasets
- Fixed heatmap dimension role assignment
- Cleaned 1,150 stale view profile files
- Added chart selection rules reference (`docs/chart-rules.md`)

## 2026-03-24 — Corpus Normalization (Phases 1-7)

Full normalization of the data corpus into a canonical, consumption-ready format:
- **Phase 1**: Corpus audit — inventory of all parquet files, orphan detection
- **Phase 2**: Canonicalize corpus — convert splits, adopt orphans, archive parent datasets
- **Phase 3**: Build i18n dictionary from English metadata
- **Phase 4**: Profile all sub-datasets — dimensions, coverage, values, trends
- **Phase 5**: Simplify app to v3-only, add canonical filter and i18n support
- **Phase 6**: Reorganize data directory into `corpus/` for clean consumption
- **Phase 7**: Normalize dimension labels across all datasets

Result: 3,632 canonical parquet files in `data/corpus/parquet/`, metadata in `data/corpus/metadata.duckdb`, view profiles in `data/corpus/view-profiles/`.

## 2026-03-24 — SDMX-Native Data Format (Phases 0-4)

Transformed the entire data layer from opaque integer IDs to SDMX-compatible, human-readable format.

**Scripts created:**
- `11-build-sdmx-codes.py` — builds `sdmx_codes` (18,203 rows) and `sdmx_column_map` (10,683 rows) in DuckDB
- `12-parquet-to-sdmx.py` — transforms 1,886 parquet files from v2 (integer nomItemIds) to v3 (SDMX strings)

**Backend updated:**
- `app/config.py` — PARQUET_DIR → `parquet-v3/ro`
- `app/services/query_builder.py` — transparent nomItemId → sdmx_value filter translation
- `app/routers/dataset_data.py` — v3-aware label resolution (identity mapping for string values)
- `app/static/js/data-table.js` — `isValueCol()` handles both `value` and `OBS_VALUE`

**Metadata updated:**
- DuckDB `dimensions.dim_column_name` → SDMX concept IDs (REF_AREA, TIME_PERIOD, etc.)
- View profiles regenerated with new column names

**Result:** Data is now self-documenting (`WHERE REF_AREA = 'Bihor'` instead of `WHERE macroregiuni_nom_id = 3068`). Ready for NL2SQL, Jupyter notebooks, and multi-source (Eurostat/OECD) integration.

## 2025-12 — 2026-03 — FastAPI + DuckDB App

Built the web application with:
- FastAPI backend serving DuckDB metadata + Parquet data
- ECharts-based charting: choropleth, demographic grouped bar, time series, horizontal bar, heatmap, bubble, small multiples, population pyramid
- Filter panel with dynamic dimension controls
- Data table with sort, pagination, column filters
- Dataset list page with search
- v2 data enrichment pipeline (6 profiling agents): value profiles, coverage, trends, tags, relationships, chart recommendations

## 2025-08 — 2025-12 — Data Pipeline + Enrichment

- DuckDB + Parquet hybrid architecture
- CSV → Parquet conversion (1,886 datasets)
- Dimension classification (time, geo, gender, age, unit, residence, indicator)
- Dataset splitting by geo hierarchy (county/region/macroregion)
- SDMX-CSV export prototype
- Dimension index and search tools

## 2024-12 — 2025-08 — Initial Setup

- Project forked from `gov2-ro/scrapers`
- Data scraping pipeline (scripts 1-7): contexts, matrices, metadata, CSV data, compaction
- UI prototypes: dataset navigator, dimension browser, category browser, tree browser
- SQLite dimension index
- PHP API for dimension search
- Flask data profiler
