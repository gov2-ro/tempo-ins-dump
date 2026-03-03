# INS TEMPO Data Explorer v2 — Application Specification

## 1. Design Philosophy

The v1 app is a competent search-and-drill portal: pick a category, find a dataset, view a chart. The v2 redesign exploits the enriched metadata pipeline to make the app **discovery-first**. The key insight: we now know *what the data looks like* (trends, coverage, value profiles) before the user opens it. That lets us surface signals, not just listings.

**Core principles:**

- **Show, don't list.** Every surface should preview data, not just describe it.
- **Multiple funnels.** Users can enter through topics, trends, geography, chart type, time period, or search — all first-class paths to the same datasets.
- **Metadata is navigation.** Tags, relationships, quality badges, and chart recommendations are not decorations — they are clickable, filterable, navigable.
- **Pre-compute everything navigational.** The backend serves pre-built JSON bundles for all browse/discover views. Runtime queries only happen when rendering actual data charts.
- **Progressive disclosure.** Landing page shows the forest. Each click reveals more trees. Dataset page shows every leaf.

**Non-goals:** User accounts, saved views, data export pipelines, admin interfaces. This is a read-only explorer.

---

## 2. Page Hierarchy & URL Structure

```
/                                   Landing / Discovery Hub
/explore                            Tag Cloud Explorer
/explore?tag=populatie              Filtered by tag
/explore?trend=increasing           Filtered by trend direction
/explore?geo=full                   Filtered by full county coverage
/explore?chart=choropleth           Filtered by chart type
/explore?fresh=recent               Filtered by freshness
/datasets                           Full Dataset Catalog
/datasets?context=1010              Filtered by L2 category
/datasets?ancestor=10               Filtered by L1 ancestor
/datasets?q=accidente               Text search
/datasets?archetype=geo_time        Filtered by archetype
/dataset/{matrix_code}              Dataset Detail View
/dataset/ACC101B                    Example: specific dataset
/dataset/ACC101B?chart=line         Override primary chart
/dataset/ACC101B?filters={...}      Preserved filter state (JSON-encoded)
/compare?a=ACC101B&b=ACC102B        Side-by-side comparison (future)
```

All routes are served by the same `index.html` with hash-free HTML5 History API routing (FastAPI catch-all serves `index.html` for non-API, non-static paths). Alternatively, hash-based routing (`/#/dataset/ACC101B`) avoids server config — decide at implementation time.

---

## 3. Navigation Model

### 3.1 Primary Navigation (persistent header)

```
+----------------------------------------------------------------------+
| [logo] INS TEMPO Explorer   [Discover] [Datasets] [____search____]  |
|                                                        [RO | EN]     |
+----------------------------------------------------------------------+
```

- **Logo**: Always links to `/`.
- **Discover**: Links to `/explore` — the tag/trend/facet explorer.
- **Datasets**: Links to `/datasets` — the structured catalog.
- **Search**: Global search bar, always visible. Type-ahead results grouped by: datasets (name match), tags (tag match), categories (path match). Enter navigates to `/datasets?q=...`.
- **Language toggle**: RO / EN switch. Affects dataset names, category names, tags, and UI chrome. Does NOT affect dimension option labels (those are RO-only from INS source). Persisted in `localStorage`.

### 3.2 Breadcrumbs

Context-sensitive breadcrumb below the header, visible on all pages except landing:

- **Discover page**: `Home > Discover > [active facet]`
- **Datasets page**: `Home > Datasets > [Category L0] > [Category L1]` (if category filter active)
- **Dataset detail**: `Home > Datasets > [Category L0] > [Category L1] > [Category L2] > [Dataset Name]`

Breadcrumb segments are clickable links. The context path comes from `matrices.ancestor_path` which maps to English/Romanian context names.

### 3.3 Cross-Links (the discovery web)

Every surface connects to others:

| From | To | Mechanism |
|------|----|-----------|
| Landing card | `/explore?tag=X` | Click a featured tag |
| Landing card | `/dataset/X` | Click a spotlight dataset |
| Explore tag | `/datasets?tag=X` | Click "See all N datasets" |
| Explore trend filter | `/datasets?trend=increasing` | Toggle trend facet |
| Dataset card | `/dataset/X` | Click any dataset card |
| Dataset detail tag | `/explore?tag=X` | Click a tag badge |
| Dataset detail related | `/dataset/Y` | Click a related dataset card |
| Dataset detail chart rec | Switch chart in carousel | Click chart type pill |
| Category tree node | `/datasets?context=X` | Click a category |

### 3.4 Back Navigation

HTML5 History API ensures browser back button works. Every navigation pushes state. Filter changes on dataset detail page use `replaceState` (not pushState) to avoid polluting history with every filter tweak.

---

## 4. Component Inventory

### 4.1 Global Components

| Component | File | Description |
|-----------|------|-------------|
| `AppHeader` | `components/app-header.js` | Sticky top bar with logo, nav, search, language toggle |
| `SearchBar` | `components/search-bar.js` | Type-ahead search with grouped results (datasets, tags, categories) |
| `Breadcrumb` | `components/breadcrumb.js` | Context-sensitive navigation trail |
| `LanguageToggle` | `components/language-toggle.js` | RO/EN switch, updates `localStorage` and triggers re-render |
| `Router` | `core/router.js` | History API router, maps paths to page controllers |

### 4.2 Card Components

| Component | File | Description |
|-----------|------|-------------|
| `DatasetCard` | `components/dataset-card.js` | Standard dataset preview: name, badges, sparkline, trend arrow, time range. Used in grids everywhere. |
| `DatasetCardCompact` | `components/dataset-card.js` | Narrow variant for sidebar related-datasets lists. Name + trend arrow + time range only. |
| `SpotlightCard` | `components/spotlight-card.js` | Large featured card with embedded mini-chart (sparkline or mini-map). Used on landing page. |
| `RelatedCard` | `components/related-card.js` | Shows relationship type badge + similarity score + dataset name. Used in dataset detail sidebar. |

### 4.3 Badge Components

| Component | Visual | Data Source |
|-----------|--------|-------------|
| `TrendBadge` | Arrow icon + label (Increasing / Decreasing / Volatile / Flat) | `dataset_trends.trend_direction` |
| `FreshnessBadge` | Green dot (0-2y) / Yellow (3-5y) / Gray (6-10y) / Red (10+y) | `dataset_coverage.freshness_years` |
| `QualityBadge` | Fill bar icon (%) | `dataset_coverage.fill_rate` |
| `ArchetypeBadge` | Icon + label (geo_time / demographic / time_series / time_residence) | `matrix_profiles.archetype` |
| `ChartTypePill` | Small rounded pill with chart icon | `dataset_chart_recs.chart_type` |
| `MagnitudeBadge` | Label: units / thousands / millions / billions | `dataset_value_profiles.magnitude` |
| `GeoScopeBadge` | Map pin icon + "42 counties" or "National only" | `dataset_coverage.geo_county_count` |
| `TimeRangeBadge` | Calendar icon + "1992-2024" | `dataset_coverage.time_min_year/time_max_year` |

### 4.4 Filter & Facet Components

| Component | File | Description |
|-----------|------|-------------|
| `FacetPanel` | `components/facet-panel.js` | Vertical sidebar with collapsible facet groups. Used on `/explore` and `/datasets`. |
| `TagCloud` | `components/tag-cloud.js` | Weighted tag display. Tag size = number of datasets using it. Click filters to that tag. |
| `FilterPanel` | `components/filter-panel.js` | Dataset dimension filters (time range, geo hierarchy, checkboxes). Evolved from v1. |
| `ActiveFilters` | `components/active-filters.js` | Horizontal chip bar showing active filters with X remove buttons. |

### 4.5 Chart Components

| Component | File | Description |
|-----------|------|-------------|
| `ChartCarousel` | `components/chart-carousel.js` | Pill bar of recommended chart types + main chart area. Switches chart type on click. |
| `ChartFactory` | `charts/chart-factory.js` | Dispatches to chart modules by type string. |
| `LineChart` | `charts/chart-line.js` | Time series line/area. Covers `line`, `area_with_trend` recs. |
| `BarChart` | `charts/chart-bar.js` | Vertical/horizontal bar. Covers `bar`, `ranked_horizontal_bar` recs. |
| `ChoroplethChart` | `charts/chart-geo.js` | Romania county map + time slider. Covers `choropleth` rec. |
| `GroupedBarChart` | `charts/chart-demographic.js` | Age x gender grouped bars. Covers `grouped_bar`, `population_pyramid` recs. |
| `HeatmapChart` | `charts/chart-heatmap.js` | **NEW.** 2D heatmap (time x geo, time x indicator). Covers `heatmap` rec. |
| `RangeChart` | `charts/chart-range.js` | **NEW.** Line with min/max band. Covers `range_chart` rec. |
| `SparklineGrid` | `charts/chart-sparkline-grid.js` | **NEW.** Small multiples grid of mini-line charts. Covers `sparkline_grid` rec. |
| `SmallMultiples` | `charts/chart-small-multiples.js` | **NEW.** Grid of full line charts, one per entity. Covers `small_multiples_line` rec. |
| `Sparkline` | `charts/sparkline.js` | Tiny inline chart (no axes) for dataset cards. SVG-based, no ECharts overhead. |
| `DataTable` | `components/data-table.js` | Sortable, paginated data table. Evolved from v1. |

### 4.6 Layout Components

| Component | File | Description |
|-----------|------|-------------|
| `TwoColumnLayout` | `layouts/two-column.js` | Sidebar (280px) + main content. Used on datasets list and dataset detail. |
| `GridLayout` | `layouts/grid-layout.js` | Responsive card grid with configurable columns. |
| `SectionHeader` | `components/section-header.js` | Section title + optional "View all" link + optional count badge. |

---

## 5. Page-by-Page Wireframes

### 5.1 Landing Page — Discovery Hub (`/`)

The landing page is not a portal — it is an editorial surface. It answers: "What is interesting in Romanian statistics right now?"

```
+----------------------------------------------------------------------+
| [logo] INS TEMPO Explorer     [Discover] [Datasets]  [___search___] |
+----------------------------------------------------------------------+
|                                                                      |
|           Romanian Statistics Explorer                               |
|      1,886 datasets . 339 categories . 1992-2025 . Bilingual        |
|                                                                      |
|     [________________________search________________________]         |
|     | populat  -> [Populatia rezidenta...] [populatie tag] [...]  |   |
|                                                                      |
+----------------------------------------------------------------------+
|                                                                      |
|  SPOTLIGHT  (3 curated cards with mini-charts)                       |
| +--------------------+ +--------------------+ +--------------------+ |
| | [sparkline~~~~~~]  | | [mini-map of RO]   | | [bar~~~~~]         | |
| | Populatia          | | Somaj pe judete    | | Structura pe varste| |
| | rezidenta 1992-24  | | 2024, 42 counties  | | 2024 demographic   | |
| | ^^ Increasing      | | Geo variance: high | | Freshness: recent  | |
| | 22.4M -> 19.0M     | | Updated 2024-10    | | Updated 2024-08    | |
| +--------------------+ +--------------------+ +--------------------+ |
|                                                                      |
+----------------------------------------------------------------------+
|                                                                      |
|  EXPLORE BY TOPIC                                         [View all] |
|                                                                      |
|  [populatie](247) [somaj](89) [PIB](45) [educatie](112)             |
|  [sanatate](156) [agricultura](98) [constructii](67) [turism](43)   |
|  [transport](88) [comert](71) [preturi](134) [salarii](78)          |
|  [demografie](63) [mediu](45) [energie](52) [justitie](34) ...      |
|                                                                      |
+----------------------------------------------------------------------+
|                                                                      |
|  TRENDS IN DATA                                           [View all] |
|                                                                      |
|  +-----------+ +-----------+ +-----------+ +-----------+             |
|  | RISING    | | FALLING   | | VOLATILE  | | FRESH     |             |
|  | 386 ds    | | 205 ds    | | 1,190 ds  | | 948 ds    |             |
|  | [card]    | | [card]    | | [card]    | | (< 2 yr)  |             |
|  | [card]    | | [card]    | | [card]    | | [card]    |             |
|  | [card]    | | [card]    | | [card]    | | [card]    |             |
|  +-----------+ +-----------+ +-----------+ +-----------+             |
|                                                                      |
+----------------------------------------------------------------------+
|                                                                      |
|  BROWSE BY THEME                                                     |
|  (8 top-level category cards, same as v1 but with dataset counts)    |
|  +------------------+ +------------------+ +------------------+      |
|  | A. SOCIAL        | | B. ECONOMIC      | | C. ENVIRONMENT   |      |
|  | 687 datasets     | | 845 datasets     | | 124 datasets     |      |
|  +------------------+ +------------------+ +------------------+      |
|  +------------------+ +------------------+ ...                       |
|  | D. AGRICULTURE   | | E. SERVICES      |                          |
|  | 156 datasets     | | 88 datasets      |                          |
|  +------------------+ +------------------+                           |
|                                                                      |
+----------------------------------------------------------------------+
|                                                                      |
|  RECENTLY UPDATED                                         [View all] |
|  [compact card] [compact card] [compact card] [compact card] ...     |
|                                                                      |
+----------------------------------------------------------------------+
|  Footer: Data source: INS TEMPO Online | Last pipeline run: date     |
+----------------------------------------------------------------------+
```

**Data sources for landing page:**

| Section | Data | Pre-computed? |
|---------|------|---------------|
| Stats ribbon | `COUNT(*)` from matrices, contexts, min/max year from coverage | Yes, in `landing.json` |
| Spotlight | Hand-curated list of 3-5 matrix_codes + their sparkline data | Semi: codes curated, data from `dataset_trends` + one small query per spotlight |
| Topic tags | Top 30 tags by dataset count from `dataset_tags` | Yes, in `tags-summary.json` |
| Trends | Top 3 datasets per trend_direction from `dataset_trends` sorted by abs(trend_slope) | Yes, in `landing.json` |
| Theme cards | Level 0 contexts + total_datasets | Yes, from `/api/categories` |
| Recently updated | Top 12 by `ultima_actualizare` | Yes, from `/api/datasets?sort=updated&limit=12` |

### 5.2 Explore Page — Tag & Facet Explorer (`/explore`)

This page does not exist in v1. It is the primary discovery surface — browse by signal, not just structure.

```
+----------------------------------------------------------------------+
| [logo] INS TEMPO Explorer     [Discover] [Datasets]  [___search___] |
+----------------------------------------------------------------------+
| Home > Discover                                                      |
+----------------------------------------------------------------------+
|                                                                      |
| +---FACETS (LEFT)----+ +---RESULTS (MAIN)----------------------------+
| |                    | |                                             |
| | TREND              | | Showing 247 datasets                       |
| | ( ) All            | | Active: [tag: populatie x] [trend: ^ x]   |
| | (*) Increasing 386 | |                                             |
| | ( ) Decreasing 205 | | +--DATASET CARD---+ +--DATASET CARD---+   |
| | ( ) Volatile  1190 | | | Populatia rez.. | | Nasteri pe jud. |   |
| | ( ) Flat        55 | | | [~sparkline~~]  | | [~sparkline~~]  |   |
| |                    | | | ^ Increasing     | | v Decreasing     |   |
| | FRESHNESS          | | | 1992-2024 annual | | 2000-2024 annual |   |
| | [x] Recent (0-2y)  | | | ** 95% fill     | | ** 87% fill     |   |
| | [x] Medium (3-5y)  | | | geo_time 42 co. | | geo_time 42 co. |   |
| | [ ] Older  (6-10y) | | +------------------+ +------------------+   |
| | [ ] Legacy (10y+)  | |                                             |
| |                    | | +--DATASET CARD---+ +--DATASET CARD---+   |
| | GEOGRAPHIC SCOPE   | | | ...             | | ...             |   |
| | ( ) All            | | +------------------+ +------------------+   |
| | (*) Full county    | |                                             |
| | ( ) National only  | | [1] [2] [3] ... [12]     30 per page      |
| | ( ) Has localities | |                                             |
| |                    | +---------------------------------------------+
| | CHART TYPE         |
| | [x] Choropleth 566 |
| | [x] Line     1061  |
| | [ ] Heatmap   619  |
| | [x] Grouped   262  |
| | [ ] Sparklines 414 |
| | ...                 |
| |                    |
| | TIME COVERAGE      |
| | [====|--------|==] |
| | 1940       2025    |
| | Min span: [5] yrs  |
| |                    |
| | DATA QUALITY       |
| | [x] High (>90%)    |
| | [x] Good (70-90%)  |
| | [ ] Fair (50-70%)  |
| | [ ] Low  (<50%)    |
| |                    |
| | MAGNITUDE          |
| | [ ] Units          |
| | [x] Thousands      |
| | [x] Millions       |
| | [ ] Billions       |
| |                    |
| +--------------------+
```

**Tag cloud interaction:**

At the top of the main area (before the card grid), show a scrollable tag cloud. Clicking a tag adds it as a filter. Multiple tags = intersection (datasets matching ALL selected tags). The tag cloud re-weights based on current facet selection (tags not matching any result get hidden).

**Facet definitions:**

| Facet | Source Table | Options |
|-------|-------------|---------|
| Trend | `dataset_trends.trend_direction` | increasing, decreasing, volatile, flat, no_time |
| Freshness | `dataset_coverage.freshness_years` | 0-2 (recent), 3-5, 6-10, 10+ |
| Geo scope | `dataset_coverage.geo_county_count` | Full (41+), Partial (1-40), National only (0), Has localities |
| Chart type | `dataset_chart_recs.chart_type` | All 12 types |
| Time coverage | `dataset_coverage.time_min_year, time_max_year` | Range slider |
| Data quality | `dataset_coverage.fill_rate` | >90%, 70-90%, 50-70%, <50% |
| Magnitude | `dataset_value_profiles.magnitude` | units, thousands, millions, billions |
| Archetype | `matrix_profiles.archetype` | time_series, geo_time, demographic, time_residence |

**Sort options:** Relevance (when tag/search active), Freshness, Trend strength (abs slope), Data quality (fill_rate), Name A-Z.

### 5.3 Datasets Catalog (`/datasets`)

Evolved from v1. Adds: tag chips on cards, sparklines, trend arrows, better category tree.

```
+----------------------------------------------------------------------+
| [logo] INS TEMPO Explorer     [Discover] [Datasets]  [___search___] |
+----------------------------------------------------------------------+
| Home > Datasets > A.1 Population and Demographic Structure           |
+----------------------------------------------------------------------+
|                                                                      |
| +--SIDEBAR (280px)---+ +--MAIN----------------------------------+   |
| |                    | |                                         |   |
| | CATEGORIES         | | [__________search datasets__________]  |   |
| |                    | |                                         |   |
| | [-] A. Social  687 | | 47 datasets | Sort: [Updated v]       |   |
| |   [+] A.1 Pop  47 | | Active: [A.1 Population x]              |   |
| |     * 1. Rezid. 15| |                                         |   |
| |     * 2. Legal  12| | +--CARD-----+ +--CARD-----+ +--CARD--+ |   |
| |     * 3. Migrat  8| | | POP101A   | | POP102D   | | POP103B| |   |
| |   [+] A.2 Vital 34| | | Populatia | | Nascut vii| | Decese | |   |
| |   [+] A.3 Migra 22| | | rezidenta | | pe judet  | | pe cau | |   |
| | [+] B. Econ    845| | |           | |           | |        | |   |
| | [+] C. Environ 124| | | [sparkln] | | [sparkln] | | [spark]| |   |
| | ...                | | | ^Inc 0.3% | | vDec -2%  | | ~Vol   | |   |
| |                    | | | 1992-2024 | | 1990-2024 | | 95-24  | |   |
| | QUICK FILTERS      | | | annual    | | annual    | | annual | |   |
| |                    | | | geo 42co  | | geo 42co  | | noGeo  | |   |
| | Archetype:         | | | ** 95%    | | ** 87%    | | ** 72% | |   |
| | [ ] Time series   | | +-----------+ +-----------+ +--------+ |   |
| | [x] Geo + time    | |                                         |   |
| | [ ] Demographic   | | ...more cards...                        |   |
| | [ ] Residence     | |                                         |   |
| |                    | | [< Prev] Page 1 of 2 [Next >]          |   |
| | Has map data:      | |                                         |   |
| | [x] Yes [ ] No    | +------------------------------------------+  |
| +--------------------+                                               |
+----------------------------------------------------------------------+
```

**Changes from v1:**

1. Category tree now shows all 3 levels (L0/L1/L2) with expand/collapse, not just L0+L1.
2. Dataset cards are richer: include sparkline preview, trend badge, quality indicator, geo scope.
3. Quick filters in sidebar below category tree for archetype, geo, granularity.
4. Card click navigates to `/dataset/{matrix_code}`.

### 5.4 Dataset Detail View (`/dataset/{matrix_code}`)

The most complex page. Fundamentally redesigned from v1 to leverage enriched metadata.

```
+----------------------------------------------------------------------+
| [logo] INS TEMPO Explorer     [Discover] [Datasets]  [___search___] |
+----------------------------------------------------------------------+
| Home > Social > Population > 1. Resident Population > POP101A        |
+----------------------------------------------------------------------+
|                                                                      |
| Populatia rezidenta la 1 ianuarie pe grupe de varsta, sexe,          |
| macroregiuni, regiuni de dezvoltare si judete                        |
|                                                                      |
| [geo_time] [annual] [1992-2024] [42 counties] [21.5M rows]          |
| [^Increasing +0.3%/yr] [** 95% fill] [Updated: 2024-10-04] POP101A |
|                                                                      |
| Tags: [populatie] [rezidenta] [judete] [varsta] [sexe] [+7 more]   |
+----------------------------------------------------------------------+
|                                                                      |
| CHART RECOMMENDATIONS (pill bar — click to switch)                   |
| [*Choropleth*] [Line] [Heatmap] [Sparkline Grid] [Range] [Table]   |
|                                                                      |
| Unit: [Numar persoane v]                                             |
+----------------------------------------------------------------------+
|                                                                      |
| +--FILTERS (280px)--+ +--CHART AREA (main)----+--INSIGHTS (240px)-+ |
| |                   | |                        |                   | |
| | PERIOADE          | |  +------------------+  | TREND             | |
| | [1992]----[2024]  | |  |                  |  | ^ Increasing      | |
| |                   | |  |  [CHOROPLETH MAP |  | Slope: +0.3%/yr   | |
| | JUDETE            | |  |   OF ROMANIA     |  | Peak: 2002 (22.4M)| |
| | * TOTAL           | |  |   with county    |  | Trough: 2024      | |
| | * Macroregiuni    | |  |   fill colors]   |  | Breakpoints: 2009 | |
| |   > Reg. NV       | |  |                  |  | Seasonality: No   | |
| |     [ ] Bihor     | |  +--[2024]--slider--+  |                   | |
| |     [x] Cluj      | |                        | COVERAGE           | |
| |     ...           | |                        | Fill rate: 95%     | |
| |                   | |                        | 32 years of data   | |
| | SEXE              | |                        | 42/42 counties     | |
| | (*) All           | |                        | National: Yes      | |
| | ( ) Masculin      | |                        |                   | |
| | ( ) Feminin       | |                        | RELATED DATASETS   | |
| |                   | |                        | +--Compact Card--+ | |
| | GRUPE VARSTA      | |                        | | POP102D        | | |
| | [x] Total         | |                        | | Nasteri vii    | | |
| | [ ] 0-4 ani       | |                        | | same_topic 0.9 | | |
| | [ ] 5-9 ani       | |                        | +----------------+ | |
| | ...               | |                        | +--Compact Card--+ | |
| |                   | |                        | | POP103B        | | |
| |                   | |                        | | Decese pe cauze | | |
| |                   | |                        | | same_topic 0.87| | |
| |                   | |                        | +----------------+ | |
| |                   | |                        | [See all 10 rel.]  | |
| +-------------------+ +------------------------+-------------------+ |
|                                                                      |
+----------------------------------------------------------------------+
| DATA TABLE (collapsible)                                             |
| [Expand/Collapse] Showing 1-50 of 4,832 filtered rows               |
| +------------------------------------------------------------------+ |
| | Perioada | Judet      | Sex    | Grupa varsta | Value             | |
| | 2024     | Cluj       | Total  | Total        | 725,438           | |
| | 2024     | Cluj       | Masc.  | Total        | 351,221           | |
| | ...                                                               | |
| +------------------------------------------------------------------+ |
| [< Prev] [1] [2] [3] ... [97] [Next >]                             |
+----------------------------------------------------------------------+
| METADATA                                                             |
| [v Definition] [v Methodology] [v Notes] [v Source: INS TEMPO]       |
+----------------------------------------------------------------------+
```

**Key differences from v1:**

1. **Chart Carousel**: Pills across the top show ALL recommended chart types from `dataset_chart_recs`, sorted by relevance. Primary chart is pre-selected. User clicks to switch. No more hardcoded `supports` list — recommendations are data-driven.

2. **Right Insights Sidebar**: New panel showing pre-computed analytics:
   - Trend summary (direction, slope, peak/trough years, breakpoints)
   - Coverage summary (fill rate, time span, geo scope)
   - Related datasets (top 5 from `dataset_relationships`, sorted by similarity_score)
   - Each related dataset is clickable, navigating to its detail page

3. **Tags as navigation**: Tags from `dataset_tags` shown below the title. Each is clickable, navigating to `/explore?tag=X`.

4. **Quality badges inline**: Trend arrow, fill rate indicator, freshness dot — all visible without hovering.

5. **Sparkline in header area (optional)**: Small sparkline showing the overall national trend next to the title, giving instant visual context before the main chart loads.

### 5.5 Comparison View (`/compare?a=X&b=Y`) — Future Phase

Side-by-side view of two datasets sharing dimensions. Not in initial implementation but the data model (`dataset_relationships` with `shared_dim_types`) supports it. Placeholder in the navigation: "Compare" link on related dataset cards.

---

## 6. Data Flow & API Design

### 6.1 Pre-computed JSON Bundles

For navigation/discovery views, the backend pre-computes JSON files at pipeline time (or on first request with caching). These are served as static files — no runtime DuckDB queries for browsing.

| Bundle | File | Contents | Size Est. |
|--------|------|----------|-----------|
| `landing.json` | `/api/static/landing.json` | Stats, spotlight datasets (with trend data), top tags, trend leaders | ~50KB |
| `tags-summary.json` | `/api/static/tags-summary.json` | All unique tags with dataset counts, bilingual | ~200KB |
| `explore-index.json` | `/api/static/explore-index.json` | Per-dataset: matrix_code, tags[], trend_direction, freshness_years, fill_rate, magnitude, archetype, chart_recs[], geo_county_count, time_min/max, name_ro, name_en | ~800KB |
| `categories.json` | `/api/static/categories.json` | Full category tree with bilingual names and dataset counts | ~30KB |
| `relationships-index.json` | `/api/static/relationships-index.json` | Map: matrix_code -> [{related_code, type, score, name}] | ~400KB |

The `explore-index.json` is the key file: it contains all facetable metadata for all 1,886 datasets. The frontend loads it once, then filters/sorts entirely client-side. At ~800KB gzipped to ~150KB, this is a single fast load.

### 6.2 API Endpoints

**Existing (keep from v1, enhance):**

| Endpoint | Changes |
|----------|---------|
| `GET /api/categories` | Add `name_en` field from English contexts CSV |
| `GET /api/datasets` | Add tag, trend, freshness, fill_rate, magnitude, chart_type filters. Add name_en field. |
| `GET /api/datasets/{code}` | Add: tags, chart_recs, trend, coverage, value_profile, relationships. Add name_en. |
| `GET /api/datasets/{code}/data` | No changes — this is the data query engine |

**New endpoints:**

| Endpoint | Purpose | Response |
|----------|---------|----------|
| `GET /api/explore` | Faceted dataset search with all enriched filters | `{total, datasets: [{code, name, name_en, tags, trend, freshness, fill_rate, magnitude, archetype, chart_recs, geo_count, time_range}]}` |
| `GET /api/tags` | Tag listing with counts | `{tags: [{tag_ro, tag_en, source, count}]}` |
| `GET /api/tags/{tag}` | Datasets for a specific tag | `{tag_ro, tag_en, datasets: [...]}` |
| `GET /api/datasets/{code}/sparkline` | Pre-computed sparkline data (national total over time) | `{years: [1992...2024], values: [22.4M...19.0M]}` |
| `GET /api/static/{bundle}.json` | Serve pre-computed JSON bundles | Static file |

**Sparkline endpoint design:**

For each dataset with a time dimension, pre-compute the simplest possible time series: national total (or first indicator option if no geo) over all years. Store as a compact array. This powers the sparkline on dataset cards without loading full parquet data.

```json
{
  "matrix_code": "POP101A",
  "years": [1992, 1993, ..., 2024],
  "values": [22810035, 22755260, ..., 19027520]
}
```

Pre-compute all ~1,800 sparklines into `sparklines.json` (~200KB). Load client-side. Render as inline SVG (no ECharts overhead for these tiny charts).

### 6.3 Enhanced Dataset Detail Response

The `/api/datasets/{code}` response gains these new sections:

```json
{
  "matrix_code": "POP101A",
  "matrix_name": "Populatia rezidenta...",
  "matrix_name_en": "Resident population...",
  "context_path": "Social > Population > Resident Population",
  "context_path_en": "Social > Population > Resident Population",

  "tags": [
    {"tag_ro": "populatie", "tag_en": "population", "source": "context"},
    {"tag_ro": "rezidenta", "tag_en": "resident", "source": "matrix_name"},
    {"tag_ro": "judete", "tag_en": "counties", "source": "matrix_name"}
  ],

  "chart_recommendations": [
    {"chart_type": "choropleth", "relevance": 1.0, "reason": "Geographic data with time dimension", "config": {...}},
    {"chart_type": "sparkline_grid", "relevance": 0.6, "reason": "Multiple geographic units over time", "config": {...}},
    {"chart_type": "heatmap", "relevance": 0.5, "reason": "Sparse multi-dimensional data", "config": {...}}
  ],

  "trend": {
    "direction": "increasing",
    "slope": 0.003,
    "yoy_growth_latest": 0.3,
    "max_value_year": 2002,
    "min_value_year": 2024,
    "breakpoint_years": [2009],
    "has_seasonality": false,
    "geo_variance": 0.3175,
    "geo_outlier_counties": ["Alba", "Galati"]
  },

  "coverage": {
    "time_min_year": 1992,
    "time_max_year": 2024,
    "time_year_count": 32,
    "time_granularity": "annual",
    "geo_county_count": 42,
    "geo_has_national": true,
    "fill_rate": 0.95,
    "freshness_years": 2
  },

  "value_profile": {
    "min": 0,
    "max": 22810035,
    "mean": 487231,
    "magnitude": "millions",
    "distribution_shape": "right_skewed",
    "coeff_variation": 2.44
  },

  "related_datasets": [
    {"matrix_code": "POP102D", "matrix_name": "Nasteri vii...", "matrix_name_en": "Live births...",
     "relationship_type": "same_topic", "similarity_score": 0.92,
     "shared_dim_types": ["geo", "time"]},
    {"matrix_code": "POP103B", "relationship_type": "same_topic", "similarity_score": 0.87, "...": "..."}
  ],

  "profile": { "...existing v1 fields..." },
  "dimensions": [ "...existing v1 fields..." ],
  "chart_config": { "...existing v1 chart config for backward compat..." }
}
```

---

## 7. Interaction Patterns

### 7.1 Search

**Global search bar** (always in header):

1. User types 2+ characters.
2. After 200ms debounce, query both the pre-loaded `explore-index.json` (client-side) and show grouped results:
   - **Datasets** (name match, top 5): `POP101A — Populatia rezidenta...`
   - **Tags** (tag match, top 3): `populatie (247 datasets)`
   - **Categories** (path match, top 3): `A.1 Population > 1. Resident Pop.`
3. Click a dataset -> navigate to `/dataset/{code}`.
4. Click a tag -> navigate to `/explore?tag={tag}`.
5. Click a category -> navigate to `/datasets?context={code}`.
6. Press Enter -> navigate to `/datasets?q={query}` for full-text search.

### 7.2 Filtering (Explore page)

Client-side filtering against `explore-index.json`:

1. User toggles a facet checkbox (e.g., "Trend: Increasing").
2. JS filters the in-memory dataset array: `datasets.filter(d => d.trend_direction === 'increasing')`.
3. Re-render card grid + update facet counts (show only remaining options with non-zero counts).
4. Update URL query params via `replaceState`.
5. Active filters shown as chips above the grid. Click X on chip to remove.

Facets are **additive within a group** (OR) and **intersective across groups** (AND). Example: selecting both "Increasing" and "Decreasing" under Trend shows both, but combining that with "Full county" under Geo Scope narrows to the intersection.

### 7.3 Chart Switching (Dataset detail)

1. `dataset_chart_recs` provides an ordered list of recommended charts.
2. The carousel pill bar renders all recommendations, sorted by `relevance` descending.
3. Primary chart (highest relevance) is pre-selected and loaded.
4. User clicks a different pill:
   a. New chart type is set.
   b. If the chart type requires different filter logic (e.g., choropleth needs all counties, heatmap needs no filters), adjust filters automatically.
   c. Re-fetch data with appropriate limit and filters.
   d. Render new chart via `ChartFactory`.
   e. Update URL with `?chart=heatmap` via `replaceState`.
5. "Table" is always the last pill, even if not in recommendations.

**Chart-specific filter behavior:**

| Chart Type | Filter Behavior |
|------------|-----------------|
| `choropleth` | Force geo filter to all counties. Remove non-geo/non-time/non-unit filters. Limit 50,000. |
| `sparkline_grid` | Similar to choropleth: need all geo units + all time. Limit 50,000. |
| `heatmap` | Need two dimensions fully expanded. Auto-select time x first-indicator. Limit 50,000. |
| `line`, `bar`, `area_with_trend` | Use user-selected filters. Limit 5,000. |
| `grouped_bar`, `population_pyramid` | Force single time point (latest). Expand age and gender. |
| `range_chart` | Like line, but overlay min/max band from value_profile percentiles. |
| `ranked_horizontal_bar` | Single time point, all options of first indicator dim, sort by value. |
| `small_multiples_line` | Like sparkline_grid but fewer entities (top 9 by variance). |

### 7.4 Dimension Filters (Dataset detail)

Enhanced from v1:

1. **Smart defaults per chart type**: When switching charts, filters reset to chart-appropriate defaults.
2. **Immediate apply**: No "Apply" button. Each filter change triggers a debounced (200ms) re-fetch.
3. **Dependent options**: When geo filter changes to "counties only", the chart can switch from national-level line to county-level choropleth automatically.
4. **Filter presets**: For geo_time datasets, offer preset buttons: "National", "Counties", "Regions" that set the geo filter in one click.
5. **Time range slider**: Enhanced with a mini sparkline overlay showing the national trend, so users can see where interesting years are before selecting a range.

### 7.5 Related Dataset Navigation

On the dataset detail page, the right sidebar shows related datasets:

1. Sorted by `similarity_score` descending.
2. Each card shows: name, relationship type badge (`same_topic` / `same_structure` / `complementary`), similarity score as bar.
3. Click navigates to that dataset's detail page.
4. "Compare" link (grayed out / future) for `same_structure` relationships.

### 7.6 Bilingual Support

Language state stored in `localStorage('lang')`, defaulting to `'ro'`.

| Content | RO source | EN source |
|---------|-----------|-----------|
| Dataset name | `matrices.matrix_name` | `data/1-indexes/en/matrices.csv` |
| Category path | `contexts.context_name` | `data/1-indexes/en/context.csv` |
| Tags | `dataset_tags.tag_ro` | `dataset_tags.tag_en` (58% null for indicator tags) |
| Dimension labels | `dimensions.dim_label` | No translation available — always RO |
| Option labels | `dimension_options.option_label` | No translation — always RO |
| UI chrome | Hardcoded RO strings | Hardcoded EN strings in `i18n.js` |

For untranslated tags (`tag_en IS NULL`), display the Romanian tag in both modes. Dimension labels and options remain in Romanian regardless of language — this is a known limitation of the source data.

Implementation: a simple `i18n.js` module with:
```javascript
const STRINGS = {
  en: { discover: 'Discover', datasets: 'Datasets', search: 'Search datasets...', ... },
  ro: { discover: 'Descoperire', datasets: 'Seturi de date', search: 'Cauta seturi de date...', ... }
};
function t(key) { return STRINGS[currentLang][key] || key; }
```

### 7.7 URL Sharing & Bookmarks

Every navigable state is reflected in the URL:

- `/explore?tag=populatie&trend=increasing` — shareable faceted view
- `/dataset/POP101A?chart=heatmap&filters=%7B%22perioade_nom_id%22%3A%5B4285%5D%7D` — exact chart + filter state
- `/datasets?context=1010&q=nasteri` — category + search

On load, the page reads URL params and restores state. This means any view can be bookmarked or shared.

---

## 8. Badge & Indicator System

### 8.1 Trend Indicators

| Direction | Icon | Color | Label |
|-----------|------|-------|-------|
| increasing | Arrow up | `#10b981` (green) | `^ Increasing (+X%/yr)` |
| decreasing | Arrow down | `#ef4444` (red) | `v Decreasing (X%/yr)` |
| volatile | Zigzag | `#f59e0b` (amber) | `~ Volatile` |
| flat | Horizontal line | `#6b7280` (gray) | `- Flat` |
| no_time | Dash | `#9ca3af` (muted) | `No time dimension` |

The `yoy_growth_latest` value is shown in parentheses when available. On the dataset detail page, the insights sidebar expands this with slope, peak/trough years, and breakpoint years.

### 8.2 Freshness Indicators

| Freshness | Visual | Color |
|-----------|--------|-------|
| 0-2 years | Filled green circle | `#10b981` |
| 3-5 years | Filled yellow circle | `#f59e0b` |
| 6-10 years | Filled gray circle | `#9ca3af` |
| 10+ years | Empty red circle (outline) | `#ef4444` |

### 8.3 Quality Indicators (Fill Rate)

A small horizontal bar showing data completeness:

```
[==========-] 95%    (green bar, 95% width)
[======-----] 63%    (yellow bar, 63% width)
[===--------] 30%    (red bar, 30% width)
```

Colors: >80% green, 50-80% yellow, <50% red.

### 8.4 Archetype Icons

| Archetype | Icon suggestion | Description |
|-----------|----------------|-------------|
| time_series | Line chart icon | Time-based data |
| geo_time | Map pin icon | Geographic + time |
| demographic | People icon | Age/gender structure |
| time_residence | House+tree icon | Urban/rural split |

### 8.5 Geographic Scope

| Scope | Visual |
|-------|--------|
| 41-43 counties | Map icon + "42 counties" (full coverage) |
| 1-40 counties | Map icon + "N counties" (partial) |
| 0 counties, has national | Globe icon + "National" |
| No geo | No icon |

### 8.6 Badge Placement Summary

| Surface | Badges Shown |
|---------|-------------|
| Dataset card (grid) | Archetype, trend arrow, time range, sparkline, quality bar |
| Dataset card (compact/sidebar) | Trend arrow, time range |
| Dataset detail header | All badges: archetype, granularity, time range, geo scope, row count, freshness, quality, trend, magnitude, matrix code |
| Dataset detail insights sidebar | Full trend details, full coverage details |
| Explore page card | Same as grid card + tag chips |

---

## 9. Chart System Design

### 9.1 Chart Recommendation Pipeline

The `dataset_chart_recs` table was computed by the profiling pipeline. Each dataset has 1-5 recommended chart types with relevance scores (0-1) and pre-computed config JSON.

**Rendering pipeline:**

```
dataset_chart_recs (from DB)
    |
    v
Chart Carousel UI (pill bar sorted by relevance)
    |
    v (user clicks or default = highest relevance)
    |
ChartFactory.create(chartType, config, data, metadata)
    |
    +---> LineChart           (type: line, area_with_trend)
    +---> BarChart            (type: bar, ranked_horizontal_bar)
    +---> ChoroplethChart     (type: choropleth)
    +---> GroupedBarChart      (type: grouped_bar, population_pyramid)
    +---> HeatmapChart        (type: heatmap)           ** NEW **
    +---> RangeChart          (type: range_chart)        ** NEW **
    +---> SparklineGridChart  (type: sparkline_grid)     ** NEW **
    +---> SmallMultiplesChart (type: small_multiples_line) ** NEW **
    +---> SeasonalChart       (type: seasonal_pattern)   ** NEW (low priority, 8 datasets) **
    +---> DataTable           (type: table)
```

### 9.2 Chart Carousel Component

```
+----------------------------------------------------------------------+
| [*Choropleth*] [Line] [Heatmap] [Sparkline Grid] [Range] [Table]   |
+----------------------------------------------------------------------+
|                                                                      |
|            [ Main chart renders here — ECharts instance ]            |
|                                                                      |
+----------------------------------------------------------------------+
```

- Pills are rendered from `chart_recommendations`, sorted by `relevance` descending.
- Active pill has filled background (primary color).
- Hover on pill shows tooltip with `reason` text from the recommendation.
- "Table" is always appended as the last option.
- When switching chart types:
  1. The carousel emits a `chart-switch` event.
  2. The page controller adjusts filters for the new chart type.
  3. Data is re-fetched if filter changes require it.
  4. The old ECharts instance is disposed.
  5. A new chart is created via `ChartFactory`.

### 9.3 New Chart Module Specs

#### HeatmapChart (`charts/chart-heatmap.js`)

For datasets with 2+ non-time dimensions, show a 2D color matrix.

- **X-axis**: Time (years/quarters).
- **Y-axis**: Second dimension (geo counties, indicators, etc.).
- **Cell color**: Value magnitude, using ECharts `visualMap` with sequential blue palette.
- **Tooltip**: Shows exact value + dimension labels.
- **Config source**: `config_json` from `dataset_chart_recs` specifies `time_dim` and second dimension.
- **Data needs**: All time points x all Y-axis values. May need limit=50,000.
- **ECharts type**: `heatmap` series on cartesian2d.

#### RangeChart (`charts/chart-range.js`)

Line chart with a confidence/range band.

- **Primary line**: Mean/median value over time.
- **Band area**: P25-P75 (or min-max across geo units) shown as a semi-transparent area behind the line.
- **Use case**: Volatile data (1,190 datasets). The band shows the spread.
- **Implementation**: ECharts `line` series (main) + `line` series with `areaStyle` for the band (stack two series representing upper and lower bounds).
- **Data computation**: Client-side. Group data by time. For each time point, compute min/max across all series values. The main line is the median or a selected series.

#### SparklineGridChart (`charts/chart-sparkline-grid.js`)

A grid of mini-line charts — one per geographic unit or indicator.

- **Layout**: CSS grid of small ECharts instances (or single ECharts with custom graphic elements).
- **Each cell**: Title label + tiny line chart (no axes, no legend, just the line).
- **Sort**: By latest value, or by trend slope.
- **Max cells**: 42 (counties) or configurable. Paginate if > 42.
- **Implementation**: For performance, use a single ECharts instance with `grid` array (up to 42 grids in one chart) rather than 42 separate instances.

#### SmallMultiplesChart (`charts/chart-small-multiples.js`)

Like SparklineGridChart but with full axes — for fewer entities (6-12).

- **Layout**: 2x3 or 3x3 grid of complete line charts with shared Y-axis scale.
- **Each chart**: Has X-axis (years) + Y-axis + line + title.
- **Entity selection**: Top 9 by variance from `dataset_trends.geo_variance`, or user-selectable.
- **Implementation**: Single ECharts instance with multiple `grid`/`xAxis`/`yAxis`/`series` configs.

### 9.4 Sparkline for Dataset Cards

Inline sparklines on dataset cards are rendered as **pure SVG** (not ECharts) for performance. With 30 cards per page, we cannot instantiate 30 ECharts instances.

```javascript
function renderSparkline(container, values, trend) {
  const w = 120, h = 32;
  const min = Math.min(...values), max = Math.max(...values);
  const range = max - min || 1;
  const points = values.map((v, i) =>
    `${(i / (values.length - 1)) * w},${h - ((v - min) / range) * h}`
  ).join(' ');

  const color = trend === 'increasing' ? '#10b981' :
                trend === 'decreasing' ? '#ef4444' : '#6b7280';

  container.innerHTML = `<svg width="${w}" height="${h}" viewBox="0 0 ${w} ${h}">
    <polyline points="${points}" fill="none" stroke="${color}" stroke-width="1.5"/>
  </svg>`;
}
```

Data source: pre-computed `sparklines.json` loaded once on page init (~200KB for all 1,886 datasets).

### 9.5 Chart Interaction Patterns

All ECharts instances share these behaviors:

- **Tooltip**: Cross-axis pointer for time-series charts, item pointer for maps/heatmaps.
- **Legend**: Scrollable, clickable to toggle series. Hidden when only 1 series.
- **Zoom**: DataZoom slider on X-axis for time-series charts with >20 time points.
- **Resize**: Window resize triggers `chart.resize()`.
- **Theme**: Custom ECharts theme matching the app color palette (blues, with accent colors for series).
- **Animation**: 300ms duration for initial render, 200ms for updates.

---

## 10. Frontend File Structure

```
app/static/
  index.html                          # Single HTML shell (all pages)
  css/
    variables.css                     # CSS custom properties (colors, spacing, fonts)
    reset.css                         # Minimal reset
    layout.css                        # App shell, grid systems, two-column layout
    components.css                    # Badges, cards, buttons, pills, chips
    pages/
      landing.css                     # Landing page specifics
      explore.css                     # Explore page facets + tag cloud
      datasets.css                    # Dataset catalog
      dataset.css                     # Dataset detail page
  js/
    core/
      router.js                       # History API router
      api.js                          # Fetch wrapper + error handling
      i18n.js                         # Bilingual string management
      state.js                        # Simple app state (lang, loaded bundles)
    components/
      app-header.js                   # Header with nav + search
      search-bar.js                   # Type-ahead search
      breadcrumb.js                   # Breadcrumb trail
      dataset-card.js                 # Standard + compact card variants
      spotlight-card.js               # Landing page featured card
      related-card.js                 # Related dataset card
      badge-factory.js                # Creates all badge types from data
      tag-cloud.js                    # Weighted tag display
      facet-panel.js                  # Explore page sidebar facets
      filter-panel.js                 # Dataset dimension filters (evolved from v1)
      active-filters.js               # Chip bar for active filters
      chart-carousel.js               # Chart type pill bar + dispatch
      data-table.js                   # Sortable paginated table (evolved from v1)
      sparkline.js                    # Inline SVG sparkline renderer
    charts/
      chart-factory.js                # Dispatch to chart modules by type
      chart-line.js                   # Line / area / area_with_trend
      chart-bar.js                    # Vertical bar / ranked horizontal bar
      chart-geo.js                    # Choropleth map (evolved from v1)
      chart-demographic.js            # Grouped bar / population pyramid (evolved from v1)
      chart-heatmap.js                # NEW: 2D heatmap
      chart-range.js                  # NEW: Line with range band
      chart-sparkline-grid.js         # NEW: Mini-chart grid
      chart-small-multiples.js        # NEW: Full chart grid
      echarts-theme.js                # Custom ECharts theme registration
    pages/
      landing-page.js                 # Landing page controller
      explore-page.js                 # Explore page controller
      datasets-page.js                # Catalog page controller (evolved from v1)
      dataset-page.js                 # Detail page controller (evolved from v1)
    utils/
      format.js                       # Number formatting, date helpers
      dom.js                          # DOM helper (el() function from v1)
      url.js                          # URL param read/write helpers
  geo/
    romania-counties.geojson          # County boundaries (existing)
    county-mapping.json               # Name normalization mapping (existing)
```

### Single HTML Shell

v2 uses a single `index.html` that loads all JS and CSS, with the router swapping page content:

```html
<!DOCTYPE html>
<html lang="ro">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>INS TEMPO Explorer</title>
  <link rel="stylesheet" href="/css/variables.css">
  <link rel="stylesheet" href="/css/reset.css">
  <link rel="stylesheet" href="/css/layout.css">
  <link rel="stylesheet" href="/css/components.css">
  <!-- Page-specific CSS loaded by router or bundled -->
  <script src="https://cdn.jsdelivr.net/npm/echarts@5/dist/echarts.min.js"></script>
</head>
<body>
  <div id="app-header"></div>
  <div id="breadcrumb-bar"></div>
  <main id="page-content"></main>
  <footer id="app-footer"></footer>

  <!-- Core -->
  <script src="/js/core/router.js"></script>
  <script src="/js/core/api.js"></script>
  <script src="/js/core/i18n.js"></script>
  <script src="/js/core/state.js"></script>
  <!-- Utils -->
  <script src="/js/utils/format.js"></script>
  <script src="/js/utils/dom.js"></script>
  <script src="/js/utils/url.js"></script>
  <!-- Components -->
  <script src="/js/components/app-header.js"></script>
  <script src="/js/components/search-bar.js"></script>
  <!-- ... all component scripts ... -->
  <!-- Charts -->
  <script src="/js/charts/echarts-theme.js"></script>
  <script src="/js/charts/chart-factory.js"></script>
  <script src="/js/charts/chart-line.js"></script>
  <!-- ... all chart scripts ... -->
  <!-- Pages -->
  <script src="/js/pages/landing-page.js"></script>
  <script src="/js/pages/explore-page.js"></script>
  <script src="/js/pages/datasets-page.js"></script>
  <script src="/js/pages/dataset-page.js"></script>
</body>
</html>
```

Alternatively, use ES modules with `type="module"` for cleaner dependency management. Decision at implementation time.

---

## 11. Pre-computation Pipeline

A new script `15-build-ui-bundles.py` runs after the profiling pipeline to generate all JSON bundles:

```python
# 15-build-ui-bundles.py
# Generates pre-computed JSON files for the v2 frontend

def build_landing_json(conn):
    """Stats, spotlight datasets, top tags, trend leaders."""

def build_tags_summary(conn):
    """All unique tags with dataset counts, bilingual."""

def build_explore_index(conn):
    """Per-dataset facetable metadata for client-side filtering."""

def build_sparklines(conn, parquet_dir):
    """National-level sparkline data for all datasets."""

def build_relationships_index(conn):
    """Map: matrix_code -> related datasets."""

def build_categories_bilingual(conn):
    """Category tree with RO + EN names."""
```

Output files go to `app/static/data/` and are served as static files by FastAPI.

**English name integration:**

The script reads `data/1-indexes/en/matrices.csv` and `data/1-indexes/en/context.csv` to build a lookup map: `matrix_code -> english_name` and `context_code -> english_name`. These are merged into the JSON bundles.

---

## 12. Implementation Plan

### Phase 1: Foundation (infrastructure + bundles)

| Step | Task | Effort |
|------|------|--------|
| 1.1 | Write `15-build-ui-bundles.py` to generate all JSON bundles | 1 day |
| 1.2 | Enhance `/api/datasets/{code}` with tags, chart_recs, trend, coverage, relationships | 0.5 day |
| 1.3 | Add bilingual name fields to existing endpoints | 0.5 day |
| 1.4 | Set up single-page app shell with router | 0.5 day |
| 1.5 | Port v1 CSS to new variable/component structure | 0.5 day |

### Phase 2: Discovery surfaces

| Step | Task | Effort |
|------|------|--------|
| 2.1 | Landing page with spotlight, tag cloud, trend cards, categories | 1 day |
| 2.2 | Explore page with facet panel + client-side filtering | 1 day |
| 2.3 | Enhanced dataset cards with sparklines + badges | 0.5 day |
| 2.4 | Global search with type-ahead | 0.5 day |
| 2.5 | Bilingual toggle | 0.5 day |

### Phase 3: Enhanced dataset detail

| Step | Task | Effort |
|------|------|--------|
| 3.1 | Chart carousel from recommendations | 0.5 day |
| 3.2 | Insights sidebar (trend, coverage, related) | 0.5 day |
| 3.3 | Tag navigation from detail page | 0.25 day |
| 3.4 | Heatmap chart module | 0.5 day |
| 3.5 | Range chart module | 0.5 day |
| 3.6 | Sparkline grid module | 0.75 day |
| 3.7 | Small multiples module | 0.5 day |

### Phase 4: Polish

| Step | Task | Effort |
|------|------|--------|
| 4.1 | URL state management (share/bookmark all views) | 0.5 day |
| 4.2 | Loading skeletons, error states, empty states | 0.5 day |
| 4.3 | Responsive breakpoints (tablet, mobile) | 0.5 day |
| 4.4 | Performance: lazy-load chart modules, defer non-visible bundles | 0.5 day |
| 4.5 | Accessibility: ARIA labels, keyboard navigation, screen reader support | 0.5 day |

**Total estimated effort: ~12 developer-days.**

### Migration from v1

v1 files remain in place. v2 is built alongside them. The router dispatches to v2 page controllers. Once v2 is stable, v1 HTML files (`dataset.html`, `datasets.html`) can be removed. API endpoints are additive — v1 endpoints keep working, v2 adds new ones and enhances existing ones.

---

## 13. Performance Considerations

### 13.1 Bundle Sizes

| Resource | Raw | Gzipped | Load Strategy |
|----------|-----|---------|---------------|
| `explore-index.json` | ~800KB | ~150KB | Load on first visit to `/explore`. Cache in memory. |
| `sparklines.json` | ~200KB | ~40KB | Load on first page with dataset cards. Cache in memory. |
| `tags-summary.json` | ~200KB | ~40KB | Load on first visit to `/` or `/explore`. Cache. |
| `landing.json` | ~50KB | ~10KB | Load on `/`. Cache. |
| `categories.json` | ~30KB | ~8KB | Load on app init. Cache. |
| `relationships-index.json` | ~400KB | ~80KB | Load on first dataset detail page. Cache. |
| ECharts core | ~800KB | ~280KB | CDN, cached by browser. |
| App JS (all) | ~100KB | ~25KB | Single load. |
| App CSS (all) | ~30KB | ~8KB | Single load. |

**Total first-paint budget**: ~350KB gzipped (ECharts + app + landing.json + categories.json). Subsequent pages add bundles as needed.

### 13.2 Runtime Performance

- **No DuckDB queries for navigation.** Browse, filter, search all use pre-computed JSON.
- **DuckDB queries only for data charts.** Parquet pushdown keeps these fast (<100ms for most datasets).
- **Sparklines are SVG, not ECharts.** 30 SVG sparklines render in <10ms. 30 ECharts instances would take 500ms+.
- **Client-side facet filtering** on 1,886 items is instantaneous (<5ms).
- **Lazy chart module loading**: Heatmap, range, sparkline-grid modules are only loaded when their pill is clicked. Basic line/bar/choropleth are always loaded.

### 13.3 Caching Strategy

- Pre-computed JSON bundles have long `Cache-Control` headers (1 hour). Invalidated by pipeline re-run (could add hash to filename).
- API responses for dataset metadata are cached in-memory (FastAPI + `functools.lru_cache` or similar) for the session.
- ECharts loaded from CDN with immutable cache headers.

---

## 14. Key Design Decisions & Rationale

| Decision | Rationale |
|----------|-----------|
| **Pre-compute everything navigational** | The 1,886-dataset corpus is small enough to fit in client memory. Client-side filtering is instant, avoids round-trips, and simplifies the backend. |
| **Single-page app** | Avoids full-page reloads when switching between explore/datasets/detail. Shared header and search state. |
| **No framework** | Matches v1 codebase. ECharts is the only dependency. Vanilla JS + CSS is sufficient for this scale. Avoids build tooling overhead. |
| **Chart recommendations drive the carousel** | Instead of hardcoding 4 chart types per archetype (v1), we use the pre-computed recommendations (avg 2.8 per dataset, 12 types total). This means every dataset gets the chart types that actually suit its data. |
| **SVG sparklines, not ECharts** | Dataset cards show 30 sparklines per page. ECharts per sparkline is too heavy. SVG polyline is <1ms per sparkline. |
| **Bilingual with RO fallback** | English translations exist for names and categories (60%+ coverage). Dimension labels stay RO. This is pragmatic — full translation would require INS cooperation. |
| **Explore page as client-side faceted search** | With only 1,886 datasets and ~6 facets, client-side filtering is cleaner and faster than a server-side faceted search engine. |
| **Right sidebar for insights** | The dataset detail page's left sidebar is for filters (user input). The right sidebar is for computed insights (system output). This left=input, right=output pattern is intuitive. |
| **Hash-free URLs preferred** | Cleaner URLs for sharing. Requires FastAPI catch-all route. Fall back to hash-based if deployment constraints require it. |

---

## 15. What Makes This Different

Most national statistics portals (including INS TEMPO Online) are structured as: pick a category, pick a dataset, configure dimensions, download a table. The user must already know what they are looking for.

This v2 explorer is different because the enriched metadata pipeline gives us information that typical portals do not have:

1. **Trend signals**: We can show users that Romanian population is declining, unemployment is volatile, GDP is increasing — without them having to open each dataset and chart it manually.

2. **Quality signals**: Fill rate, freshness, geo coverage — users can immediately see which datasets are trustworthy and complete, and which are sparse or stale.

3. **Chart intelligence**: Instead of showing a generic line chart for everything, we recommend the specific chart types that suit each dataset's structure and characteristics.

4. **Relationship web**: "If you're looking at population, you might also want births, deaths, migration" — these connections are computed, not hand-curated.

5. **Tag-based discovery**: The bilingual tag system lets users find datasets about "education" or "agriculture" without navigating a rigid category tree.

6. **Preview before commitment**: Sparklines on cards, trend arrows, quality badges — users can scan 30 datasets at a glance and pick the most promising one, rather than clicking into each one blindly.

This is the difference between a data catalog and a data discovery tool.
