# INS TEMPO Data Explorer — Application Specification

## Overview

A modern web interface to navigate and explore ~1,886 datasets from the Romanian National Institute of Statistics (INS TEMPO). The current official interface is not user-friendly. This application leverages rich metadata in DuckDB, pre-classified dataset archetypes, parsed dimension semantics, and data in Parquet files to auto-generate appropriate charts and contextual filters for each dataset.

**Priority**: The dataset view page — auto-adapted charts with contextual dimension filters.

## Tech Stack

| Component | Choice | Rationale |
|-----------|--------|-----------|
| Backend | Python FastAPI + DuckDB | DuckDB queries Parquet files directly with pushdown; metadata tables already exist |
| Frontend | Vanilla JS (ES6+) | No build step, matches existing codebase patterns |
| Charts | Apache ECharts | Rich interactive charts + built-in map support for Romania choropleth |
| Location | `app/` folder | Fresh start; existing `ui/` stays for reference |
| Run | `uvicorn app.main:app --reload --port 8080` | Standard FastAPI dev server |

## Data Architecture

### Existing Infrastructure

**DuckDB** (`data/tempo_metadata.duckdb`) contains:

| Table | Rows | Purpose |
|-------|------|---------|
| `contexts` | ~339 | 4-level category hierarchy (context_code, parent_code, level, context_name) |
| `matrices` | 1,888 | Dataset registry with full metadata (name, definition, methodology, update date, row_count, parquet_path, etc.) |
| `dimensions` | ~6,500 | Dimension definitions per dataset (dim_label, dim_column_name, option_count) |
| `dimension_options` | ~325K | All option values with nom_item_id, option_label, parent_id |
| `dimension_options_parsed` | ~18,200 | Classified options with parsed semantic fields |
| `matrix_profiles` | 1,888 | Per-dataset profile: archetype, has_time/geo/gender/age, time range, geo levels, unit types |

**Parquet files** (`data/parquet/ro/`) — 1,886 files, ~129MB total. Each file has dimension columns + `value` column.

### Dataset Archetypes

The classification system assigns each dataset an archetype based on its dimensional composition:

| Archetype | Count | % | Characteristics | Primary Chart |
|-----------|-------|---|-----------------|---------------|
| `time_series` | 976 | 51.7% | Time + thematic categorical dims | Line chart |
| `geo_time` | 566 | 30.0% | Time + geographic dimensions | Choropleth map + timeline |
| `demographic` | 262 | 13.9% | Time + gender/age breakdowns | Grouped bar / pyramid |
| `time_residence` | 84 | 4.4% | Time + urban/rural | Comparison lines |

### Parsed Dimension Types

Each dimension option in `dimension_options_parsed` has semantic fields based on its `dim_type`:

| dim_type | Count | Parsed fields |
|----------|-------|---------------|
| indicator | 12,675 | (domain-specific, unparsed) |
| geo | 3,815 | geo_level (national/macroregion/region/county/locality), geo_name_clean, siruta_code |
| time | 831 | year, quarter, month, semester, time_granularity |
| age | 665 | age_min, age_max |
| gender | 91 | gender (male/female/total/unknown) |
| unit | 86 | unit_type, unit_scale, currency |
| residence | 40 | geo_level=residence, geo_name_clean (urban/rural/total) |

### Multi-Unit Datasets

109 datasets have multiple incompatible units in the same UM dimension (e.g., BUF113G has Bucati, Kilograme, Litri). These must:
- Show a prominent unit selector in the UI
- Apply unit as mandatory filter before any query or aggregation
- Display separate charts per unit if showing all

### Known Issue: Parquet Text Labels

Parquet files currently store raw text labels ("Anul 1992", " Cluj" with leading spaces) despite column names ending in `_nom_id`. **Phase 0A** converts these to actual integer `nom_item_id` values for fast JOINs.

---

## Phase 0: Data Preparation

### 0A. Parquet ID Conversion

**Script**: `14-parquet-to-ids.py`

Convert parquet dimension columns from text labels to integer nom_item_ids:

1. For each matrix, read `dimensions` table for column name → dimension_id mapping
2. For each dimension, build lookup: `TRIM(option_label)` → `nom_item_id`
3. Read parquet, replace text values with integer IDs
4. Write to `data/parquet-v2/ro/`
5. Update `matrices.parquet_path` in DuckDB
6. Validate: row counts match, no NULL IDs

**Output**: ~1,886 files, ~60-80MB (integers compress better than variable-length text)

### 0B. Romania GeoJSON

- `app/static/geo/romania-counties.geojson` — 42 counties + Bucharest boundaries
- `app/static/geo/county-mapping.json` — maps `geo_name_clean` → GeoJSON feature names (handles "Municipiul Bucuresti" vs "Bucuresti", diacritics, etc.)

---

## Phase 1: Backend API

### File Structure

```
app/
  main.py                 # FastAPI app, mount routers + static files
  config.py               # Paths (DB_PATH, PARQUET_DIR), DEBUG flag
  db.py                   # DuckDB read-only connection singleton
  routers/
    __init__.py
    categories.py         # Category tree endpoint
    datasets.py           # Dataset listing, search, detail
    dataset_data.py       # Data querying for single dataset
  services/
    __init__.py
    query_builder.py      # Dynamic SQL builder for parquet queries
    chart_config.py       # Archetype → chart configuration generator
  static/                 # Frontend files (served at /)
    index.html
    dataset.html
    css/
    js/
    geo/
```

### API Endpoints

#### `GET /api/categories`

Returns the category tree (contexts table) with dataset counts per leaf node.

```json
{
  "tree": [
    {
      "code": "1",
      "name": "A. STATISTICA SOCIALA",
      "level": 0,
      "children": [
        {
          "code": "10",
          "name": "A.1 POPULATIE SI STRUCTURA DEMOGRAFICA",
          "level": 1,
          "children": [
            { "code": "1010", "name": "1. POPULATIA REZIDENTA", "level": 2, "dataset_count": 15 }
          ]
        }
      ]
    }
  ]
}
```

#### `GET /api/datasets`

Dataset listing with search, filtering, and pagination.

**Query params**: `?q=populatie&context=1010&ancestor=1&archetype=geo_time&has_geo=true&sort=updated&limit=50&offset=0`

```json
{
  "total": 566,
  "datasets": [
    {
      "matrix_code": "ACC101B",
      "matrix_name": "Accidente colective de munca...",
      "context_path": "Statistica Sociala > Forta de munca > Conditii de munca",
      "archetype": "geo_time",
      "row_count": 1155,
      "dim_count": 3,
      "time_range": "1992-2023",
      "has_geo": true,
      "ultima_actualizare": "2024-10-04",
      "primary_unit_type": "count"
    }
  ]
}
```

#### `GET /api/datasets/{matrix_code}`

Full dataset metadata, dimensions with parsed options, and auto-generated chart configuration.

```json
{
  "matrix_code": "ACC101B",
  "matrix_name": "...",
  "definitie": "...",
  "metodologie": "...",
  "ultima_actualizare": "2024-10-04",
  "row_count": 1155,
  "profile": {
    "archetype": "geo_time",
    "has_time": true,
    "time_granularity": "annual",
    "time_year_min": 1992,
    "time_year_max": 2023,
    "has_geo": true,
    "geo_levels": ["county", "macroregion", "national", "region"],
    "unit_types": ["count"],
    "primary_unit_type": "count"
  },
  "dimensions": [
    {
      "dim_code": 1,
      "dim_label": "Macroregiuni, regiuni de dezvoltare si judete",
      "dim_column_name": "macroregiuni_regiuni_de_dezvoltare_si_judet_nom_id",
      "dim_type": "geo",
      "option_count": 56,
      "options": [
        {
          "nom_item_id": 112,
          "label": "TOTAL",
          "parsed": { "dim_type": "geo", "geo_level": "national", "geo_name_clean": "Total" }
        }
      ]
    }
  ],
  "chart_config": { "..." }
}
```

#### `GET /api/datasets/{matrix_code}/data`

Query actual data from parquet with dimension filters.

**Query params**: `?filters={"col_name":[id1,id2]}&limit=5000`

Filters are JSON: dimension column name → array of nom_item_ids. The backend builds `WHERE col IN (...)` clauses with parquet pushdown.

```json
{
  "columns": ["perioade_nom_id", "macroregiuni_..._nom_id", "value"],
  "column_labels": {
    "perioade_nom_id": { "4285": "Anul 1992", "4304": "Anul 1993" },
    "macroregiuni_..._nom_id": { "112": "TOTAL", "3068": "Bihor" }
  },
  "rows": [[4285, 112, 6.0], [4304, 112, 8.0]],
  "total_rows": 1155,
  "truncated": false
}
```

**Compact format**: Rows contain integer IDs. `column_labels` provides the display names once. Keeps payload small.

**Large dataset handling**: For datasets with `row_count > 50,000`, the API requires at least one filter to prevent returning millions of rows. Returns 400 error with guidance.

### Chart Configuration Service (`services/chart_config.py`)

Server-side computation of chart settings based on archetype + dimension types:

| Archetype | `primary_chart` | `x_axis` | `series_dim` | `supports` |
|-----------|-----------------|----------|--------------|------------|
| `time_series` | `line` | time dim | first indicator dim | line, area, bar, table |
| `geo_time` | `choropleth` | geo dim | — | choropleth, line, bar, table |
| `demographic` | `grouped_bar` | age dim | gender dim | grouped_bar, pyramid, line, table |
| `time_residence` | `line` | time dim | residence dim | line, bar, table |

Additional config includes: `default_series_limit` (5 for time_series), `default_time` (latest year for geo_time), `default_geo_level` (county).

---

## Phase 2: Frontend — Dataset View (Priority)

### Page Layout

```
+------------------------------------------------------------------+
| HEADER: breadcrumb (cat > subcat > dataset), metadata badges     |
+------------------------------------------------------------------+
| TOOLBAR: [Line|Map|Bar|Table] [Unit: ▼] [⬇ Download] [🔗 Share] |
+--------+---------------------------------------------------------+
|        |                                                         |
| FILTER |              CHART AREA (ECharts)                       |
| PANEL  |              Auto-selected by archetype                 |
| ~280px |                                                         |
|        |                                                         |
| [time] +---------------------------------------------------------+
| [geo]  |                                                         |
| [cats] |  DATA TABLE (collapsible, sortable, paginated)         |
|        |                                                         |
+--------+---------------------------------------------------------+
| FOOTER: Definition, methodology, source, last update             |
+------------------------------------------------------------------+
```

### Frontend File Structure

```
app/static/
  index.html              # Landing page / category browser
  dataset.html            # Dataset view page
  css/
    main.css              # Shared: reset, typography, layout, colors
    dataset.css           # Dataset page layout, chart container
    filters.css           # Filter panel controls, chips
  js/
    api.js                # Fetch wrapper, error handling
    router.js             # Hash-based routing
    dataset-page.js       # Dataset page controller (orchestrator)
    chart-factory.js      # Dispatches to correct chart builder
    chart-time-series.js  # ECharts line/area chart configuration
    chart-geo.js          # ECharts choropleth + time slider
    chart-demographic.js  # Grouped bar + population pyramid
    chart-comparison.js   # Urban/rural comparison lines
    filter-panel.js       # Dynamic filter UI generation
    data-table.js         # Tabular data display
    utils.js              # Number formatting, date helpers
  geo/
    romania-counties.geojson
    county-mapping.json
```

### Filter Panel (`js/filter-panel.js`)

Dynamically generated from `/api/datasets/{code}` response. Each dimension gets a control based on its parsed `dim_type`:

| Dimension Type | Control | Behavior |
|---------------|---------|----------|
| **time** | Year range slider (min–max) | Draggable endpoints; default: full range |
| **geo** | Hierarchical checkboxes | National > Macroregion > Region > County; collapsible levels |
| **gender** | Radio buttons | Masculin / Feminin / Total |
| **age** | Checkbox list + select-all | Grouped by ranges |
| **residence** | Radio buttons | Urban / Rural / Total |
| **unit** | Dropdown (only shown if multi-unit) | Mandatory for 109 multi-unit datasets |
| **indicator** | Checkbox list + search | Can have 100+ options; type-to-filter |

- Single-option UM dimensions (1,542 datasets) are auto-applied, not shown in panel
- Active filters shown as removable chips above chart
- "Apply" button triggers re-query + chart update
- Smart defaults: latest year, national total, first few indicators

### Chart Modules

**`chart-factory.js`** — Entry point:
```javascript
function createChart(container, chartConfig, data, metadata) {
    switch (chartConfig.primary_chart) {
        case 'line':       return createTimeSeriesChart(...);
        case 'choropleth': return createChoroplethMap(...);
        case 'grouped_bar': return createGroupedBarChart(...);
    }
}
```

**`chart-time-series.js`** (covers 52% + 4% of datasets):
- X-axis: years (or quarters/months per `time_granularity`)
- Series: one line per selected indicator/category
- Tooltip: crosshair showing all series at hovered time
- Legend: clickable toggle for each series
- Toolbar toggle to: area chart, stacked area, bar chart

**`chart-geo.js`** (covers 30% of datasets):
- Primary: Romania county choropleth via `echarts.registerMap('romania', geoJSON)`
- Time slider below map to scrub through years
- Click county → show line chart for that county over time
- Color scale: sequential (light→dark) based on value range
- VisualMap component for legend/scale control

**`chart-demographic.js`** (covers 14% of datasets):
- Grouped bar chart: x=age groups, series=gender
- Population pyramid option: horizontal diverging bars (male negative, female positive)
- Year selector to pick time slice

**`chart-comparison.js`** (covers 4% of datasets):
- 2–3 line series: Urban, Rural, Total
- Distinct colors (green=urban, brown=rural, gray=total)

### Data Table (`js/data-table.js`)

- Columns: dimension labels + Value (labels from `column_labels`)
- Client-side sort on each column
- Pagination: 50 rows per page
- Romanian number formatting (dot thousands, comma decimal)
- "Download CSV" exports current filtered view

### Dataset Page Controller (`js/dataset-page.js`)

Orchestrates the full page lifecycle:

1. Parse matrix_code from URL hash
2. Fetch metadata (`/api/datasets/{code}`)
3. Render header (breadcrumb, title, badges for archetype/period/update date)
4. Build filter panel from dimensions
5. Compute smart defaults (latest year, national, first indicators)
6. Fetch data (`/api/datasets/{code}/data?filters=...`)
7. Create chart via `chart-factory.js`
8. Render data table
9. On filter change → re-fetch data → update chart + table

---

## Phase 3: Navigation & Discovery

### Landing Page (`index.html`)

- **Search bar** at top: searches dataset names, autocomplete dropdown
- **Category grid**: 8 level-0 categories as large cards (with thematic icons)
- Click card → expand to level-1 subcategories → show dataset list
- **Stats ribbon**: "1,886 datasets | 339 categories | 1992–2024"
- **Recently updated** sidebar: 10 most recently updated datasets

### Dataset List View

- **Category tree sidebar**: Collapsible 3-level tree with dataset count badges
- **Dataset cards**: Name, matrix_code badge, archetype icon, row count, time range, last updated
- **Search**: Full-text on dataset names
- **Filter bar**: Archetype, periodicity, has_geo, time range

---

## Phase 4: Polish

### URL Routing (`js/router.js`)

Hash-based routing for shareable links:
```
#/                              → Landing page
#/datasets                      → Dataset listing
#/datasets?context=1010         → Filtered by category
#/dataset/ACC101B               → Dataset view
#/dataset/ACC101B?filters=...   → Dataset view with preserved filter state
```

### UX Polish

- **Loading**: Skeleton loaders for chart area during API calls
- **Errors**: Inline alerts (not modals), retry buttons, "No data matches filters" with suggestion to broaden
- **Responsive**: Desktop=full layout, tablet=filter panel collapses to overlay, mobile=stacked layout
- **Metadata footer**: Definition, methodology, data source, last update below chart

---

## Implementation Order

| Step | What | Covers |
|------|------|--------|
| 0A | Parquet ID conversion script, run it | Data foundation |
| 1A | FastAPI skeleton + config + DB connection | Backend foundation |
| 1B | Dataset detail endpoint + chart_config service | Metadata API |
| 1C | Dataset data query endpoint | Data API |
| 2A | HTML layout + CSS (dataset.html) | UI shell |
| 2B | Time series chart module | **52% of datasets** |
| 2C | Filter panel | Interactivity |
| 2D | Data table | Tabular fallback |
| 0B | GeoJSON + county mapping | Map data |
| 2E | Choropleth map module | **+30% coverage** |
| 2F | Demographic chart module | **+14% coverage** |
| 2G | Multi-unit handling | 109 edge-case datasets |
| 1D | Categories + dataset list endpoints | Navigation API |
| 3A | Landing page | Discovery |
| 3B | Category tree + dataset cards | Browsing |
| 4 | URL routing, loading states, responsive | Polish |

**Milestone 1** (steps 0A–2D): End-to-end working for time_series datasets with filters + table.
**Milestone 2** (steps 0B–2G): All 4 archetypes charted, multi-unit handled.
**Milestone 3** (steps 1D–4): Full navigation, discovery, and polish.

---

## Key Reference Files

| File | What it provides |
|------|-----------------|
| `data/tempo_metadata.duckdb` | All metadata tables (contexts, matrices, dimensions, dimension_options, dimension_options_parsed, matrix_profiles) |
| `9-csv-to-parquet.py` | How parquets were built (text labels, leading spaces, column naming) |
| `10-classify-dimensions.py` | Classification logic, county name normalization, archetype assignment rules |
| `utils/duckdb_config.py` | Existing DB path config, `sanitize_column_name()` |
| `docs/classify-dimensions.md` | Full documentation of parsed fields, normalization recipes |
| `docs/data analysis.md` | Analysis framework, multi-unit handling, visualization mapping strategy |

## Potential Challenges

1. **POP107D (21.5M rows)**: Mandatory filters for large datasets. DuckDB parquet pushdown helps but cannot send millions of rows to the browser.
2. **GeoJSON name matching**: `geo_name_clean` values have variations (Bucuresti, Municipiul Bucuresti). County mapping JSON must handle all variants.
3. **Time granularity mixing**: Some datasets have annual + quarterly + monthly in the same time dimension. Chart needs granularity selector or auto-detection.
4. **Diverse schemas**: 1,886 datasets have different column names and counts (2–6 dimensions). Query builder and filter panel must be fully dynamic — never hardcode dimension names.
5. **Unknown dimension options**: ~69 unknown unit labels and ~410 unknown geo labels (mostly foreign country names). These fall through to "indicator" type and work as generic categorical filters.