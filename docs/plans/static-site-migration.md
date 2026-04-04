# Static Site Migration Plan

> **Goal**: Replace the FastAPI + DuckDB backend (`app/`, `duckdb-browser.py`) with a fully static site that uses DuckDB-WASM for client-side data querying. Zero runtime server. Hosting on any CDN.

## Architecture Overview

```
┌─────────────────────────────────────────────────────────┐
│                    BUILD PIPELINE                        │
│                                                         │
│  Existing scripts (1-12) produce:                       │
│    • data/tempo_metadata.duckdb (metadata)              │
│    • data/parquet-v3/ro/*.parquet (dataset files)        │
│                                                         │
│  New: build-static-site.py produces:                    │
│    • _site/api/categories.json                          │
│    • _site/api/datasets/index.json (all cards)          │
│    • _site/api/datasets/index-{page}.json (paginated)   │
│    • _site/api/datasets/{code}.json (per-dataset meta)  │
│    • _site/api/search-index.json (Fuse.js index)        │
│    • _site/data/*.parquet (copied/symlinked)            │
│                                                         │
│  Frontend files (static-site/):                         │
│    • index.html, css/, js/ → _site/                     │
│                                                         │
└─────────────────────────────────────────────────────────┘
                        │ deploy
                        ▼
┌─────────────────────────────────────────────────────────┐
│              CDN / STATIC HOST                          │
│  (Cloudflare Pages + R2, GitHub Pages, Dreamhost, etc.) │
│                                                         │
│  _site/                                                 │
│    index.html                 ← SPA shell               │
│    api/categories.json        ← ~50KB                   │
│    api/datasets/index.json    ← ~1.5MB (all cards)      │
│    api/datasets/{code}.json   ← ~3,900 files, 2-20KB    │
│    api/search-index.json      ← ~400KB                  │
│    data/*.parquet             ← ~3,700 files on CDN     │
│    geo/*.geojson              ← county/region polygons   │
│    js/app.js                  ← main app                │
│    js/duckdb-data-client.js   ← DuckDB-WASM wrapper     │
│    css/                       ← styles                  │
│                                                         │
└─────────────────────────────────────────────────────────┘
                        │ browser loads
                        ▼
┌─────────────────────────────────────────────────────────┐
│                     BROWSER                              │
│                                                         │
│  Phase 1: Metadata (static JSON, instant)               │
│    fetch('api/categories.json')     → render nav        │
│    fetch('api/datasets/index.json') → render cards      │
│    Fuse.js(search-index.json)       → client search     │
│                                                         │
│  Phase 2: Dataset detail (static JSON)                  │
│    fetch('api/datasets/{code}.json')                    │
│    → dimensions, chart_config, profile, coverage        │
│                                                         │
│  Phase 3: Data query (DuckDB-WASM, lazy-loaded)         │
│    duckdb-wasm init (first use only, ~10MB)             │
│    SQL: SELECT ... FROM 'data/{code}.parquet'           │
│         WHERE filters... LIMIT 50000                    │
│    → chart rendering via ECharts                        │
│                                                         │
└─────────────────────────────────────────────────────────┘
```

## What Gets Replaced

| Current (Python) | Static Replacement | Notes |
|---|---|---|
| `app/main.py` | `index.html` (SPA) | No server needed |
| `app/routers/categories.py` | `api/categories.json` | Pre-built at build time |
| `app/routers/datasets.py` (list) | `api/datasets/index.json` | Client-side filtering/sort |
| `app/routers/datasets.py` (detail) | `api/datasets/{code}.json` | One file per dataset |
| `app/routers/dataset_data.py` | `js/duckdb-data-client.js` | DuckDB-WASM queries parquet |
| `app/services/query_builder.py` | `js/duckdb-data-client.js` | SQL built in JS |
| `app/services/chart_selector.py` | Pre-computed in meta JSON | Runs at build time |
| `app/services/chart_config.py` | Pre-computed in meta JSON | Runs at build time |
| `app/db.py` | DuckDB-WASM | Browser-side DuckDB |
| `duckdb-browser.py` | Same static site | Subset of the explorer |

## File Structure

```
static-site/                    ← new directory (frontend source)
  index.html                    ← SPA shell
  css/
    app.css                     ← styles (port from app/static/css/ + explorer/)
  js/
    app.js                      ← main app controller
    duckdb-data-client.js       ← DuckDB-WASM integration
    search.js                   ← Fuse.js search
    chart-factory.js            ← chart dispatcher (port from explorer/)
    charts/                     ← individual chart modules (port)
    components/                 ← UI components (port)
    lib/
      utils.js
      i18n.js

build-static-site.py            ← build script (new)

_site/                          ← build output (gitignored)
  (everything above + generated api/ + data/)
```

## Build Script Design (`build-static-site.py`)

### Inputs
- `data/tempo_metadata.duckdb` (read-only)
- `data/parquet-v3/ro/*.parquet` (copy/symlink)
- `data/view-profiles/*.json` (optional enrichment)
- `app/static/geo/*.geojson` (copy)
- `static-site/` (frontend source)

### Outputs → `_site/`

#### 1. `api/categories.json`
Same shape as `GET /api/categories` response:
```json
{
  "tree": [
    {
      "code": "A",
      "name": "Agriculture",
      "level": 1,
      "dataset_count": 12,
      "total_datasets": 45,
      "children": [...]
    }
  ]
}
```
Built from: `contexts` + `matrices` tables.

#### 2. `api/datasets/index.json`
Full dataset list (all ~1,900 cards). Client does filtering/sorting/pagination.
```json
{
  "total": 1886,
  "datasets": [
    {
      "matrix_code": "ACC101B",
      "matrix_name": "...",
      "context_code": "...",
      "ultima_actualizare": "2024-01-15",
      "row_count": 12345,
      "dim_count": 4,
      "archetype": "time_series",
      "has_time": true,
      "has_geo": false,
      "time_range": "2000-2023",
      "primary_unit_type": "number",
      "time_granularity": "annual",
      "is_split": false,
      "parent_matrix_code": null,
      "split_count": 0
    }
  ]
}
```
Size estimate: ~1.5MB uncompressed, ~300KB gzipped.

#### 3. `api/datasets/{code}.json` (×3,900 files)
Same shape as `GET /api/datasets/{code}` response — full metadata with dimensions, options, chart_config, coverage, value_profile, trend.

Chart config is **pre-computed** at build time using the existing `chart_selector.py` and `chart_config.py` — no need to port that logic to JS.

#### 4. `api/search-index.json`
Lightweight index for Fuse.js:
```json
[
  {"c": "ACC101B", "n": "Dataset name", "k": "agriculture gdp national"},
  ...
]
```
~400KB, enables instant client-side fuzzy search.

#### 5. `data/*.parquet`
Symlinks or copies of `data/parquet-v3/ro/` files. In production, these live on object storage (R2/S3) with CORS + Range request support.

#### 6. `geo/*.geojson`
Copied from `app/static/geo/`.

### Build Command
```bash
source ~/devbox/envs/240826/bin/activate
python build-static-site.py [--data-dir data/] [--output-dir _site/] [--symlink-parquet]
```

Options:
- `--symlink-parquet`: Symlink instead of copy parquet files (for dev)
- `--skip-parquet`: Don't copy/link parquet (when hosted separately)
- `--base-url`: Base URL for parquet files if on different host
- `--lang ro|en`: Language (default: ro)

## DuckDB-WASM Integration (`duckdb-data-client.js`)

This replaces `app/routers/dataset_data.py` + `app/services/query_builder.py`.

### Design

```javascript
// duckdb-data-client.js

import * as duckdb from '@duckdb/duckdb-wasm';

let db = null;
let conn = null;

/**
 * Lazy-initialize DuckDB-WASM. Called on first data request only.
 * Downloads ~10MB WASM bundle. Shows loading indicator.
 */
export async function initDuckDB() { ... }

/**
 * Query a dataset's parquet file with optional filters.
 * Equivalent to GET /api/datasets/{code}/data?filters={}&limit=N
 *
 * @param {string} matrixCode - Dataset code
 * @param {Object} dimensions - From meta.json: [{dim_column_name, options}]
 * @param {Object} filters - {column_name: [value, ...]}
 * @param {number} limit - Max rows (default 50000)
 * @returns {Object} {columns, column_labels, rows, total_rows, returned_rows, truncated}
 */
export async function queryDataset(matrixCode, dimensions, filters = {}, limit = 50000) {
    if (!db) await initDuckDB();

    const parquetUrl = `${BASE_URL}/data/${matrixCode}.parquet`;

    // Build SELECT clause
    const dimCols = dimensions.map(d => `"${d.dim_column_name}"`);
    const valueName = 'OBS_VALUE';  // v3 parquet format
    const selectCols = [...dimCols, valueName].join(', ');

    // Build WHERE clause from filters
    const whereClauses = [];
    for (const [col, values] of Object.entries(filters)) {
        if (values && values.length > 0) {
            const escaped = values.map(v => typeof v === 'string' ? `'${v}'` : v);
            whereClauses.push(`"${col}" IN (${escaped.join(',')})`);
        }
    }
    const whereSQL = whereClauses.length > 0
        ? 'WHERE ' + whereClauses.join(' AND ')
        : '';

    // Build ORDER BY (time dimension first if present)
    const timeDim = dimensions.find(d => d.dim_type === 'time');
    const orderSQL = timeDim ? `ORDER BY "${timeDim.dim_column_name}" ASC` : '';

    const sql = `SELECT ${selectCols} FROM '${parquetUrl}' ${whereSQL} ${orderSQL} LIMIT ${limit}`;
    const result = await conn.query(sql);

    // Build column_labels from dimension options (already in metadata)
    const columnLabels = {};
    for (const dim of dimensions) {
        columnLabels[dim.dim_column_name] = {};
        for (const opt of dim.options) {
            columnLabels[dim.dim_column_name][String(opt.nom_item_id)] = opt.label;
        }
    }

    // Convert Arrow result to rows array
    const rows = result.toArray().map(row => [...Object.values(row)]);

    return {
        columns: [...dimensions.map(d => d.dim_column_name), valueName],
        column_labels: columnLabels,
        rows: rows,
        total_rows: rows.length,  // Approximate; exact count needs separate query
        returned_rows: rows.length,
        truncated: rows.length >= limit
    };
}
```

### Key Differences from Server Version

| Aspect | Server (`query_builder.py`) | Client (`duckdb-data-client.js`) |
|---|---|---|
| Parquet access | Local filesystem | HTTP range requests via `httpfs` |
| nomItemId → SDMX translation | SQL lookup in `sdmx_codes` table | Not needed — meta.json has labels |
| v2/v3 detection | Runtime DESCRIBE query | All v3 (build script validates) |
| Label resolution | SQL join on dimension_options | Pre-loaded from meta.json |
| Connection management | Cursor-per-request | Single persistent connection |

## Migration Path (Phases)

### Phase 1: Build Script + Static JSON ✱ START HERE
- Create `build-static-site.py`
- Export all metadata endpoints to JSON
- Test: compare JSON output with live API responses

### Phase 2: DuckDB-WASM Data Client
- Create `duckdb-data-client.js`
- Test: query parquet files in browser, compare with API `/data` endpoint
- Handle: CORS, range requests, error states, loading UX

### Phase 3: Port Frontend
- Copy/adapt `explorer/static/js/` to `static-site/js/`
- Replace `API.getDataset()` → `fetch('api/datasets/{code}.json')`
- Replace `API.getDatasetData()` → `queryDataset()` from DuckDB-WASM client
- Replace `API.listDatasets()` → `fetch('api/datasets/index.json')` + client filter
- Replace `API.getCategories()` → `fetch('api/categories.json')`
- Add Fuse.js search

### Phase 4: Polish + Deploy
- Service Worker for offline metadata caching
- Loading states for DuckDB-WASM initialization
- Error boundaries (parquet not found, WASM not supported)
- Deploy pipeline (GitHub Actions → Cloudflare Pages + R2)

### Phase 5: Retire Python App
- Archive `app/` and `duckdb-browser.py`
- Update CLAUDE.md
- Redirect old URLs

## Hosting Options

| Host | Static Files | Parquet Storage | Cost | Complexity |
|---|---|---|---|---|
| **Cloudflare Pages + R2** | Pages (free) | R2 (free tier: 10GB) | $0 | Low |
| **GitHub Pages + R2** | GH Pages (free) | R2 ($0.015/GB/mo) | ~$0 | Low |
| **Dreamhost** | Static hosting | Same server | Existing plan | Lowest |
| **Vercel + R2** | Vercel (free) | R2 | $0 | Low |
| **Netlify + S3** | Netlify (free) | S3 ($0.023/GB/mo) | ~$1/mo | Medium |

**Recommendation**: Cloudflare Pages + R2. Free tier covers this project easily. R2 has no egress fees and supports range requests natively.

For development: `python -m http.server 8000` in `_site/` — same as current `ui/` workflow.

## Trade-offs Acknowledged

| Concern | Mitigation |
|---|---|
| DuckDB-WASM ~10MB bundle | Lazy-load only when user opens a dataset |
| Mobile memory pressure | 50k row limit; most datasets are much smaller |
| Parquet files publicly accessible | INS data is public domain |
| CORS for range requests | R2/S3 support this natively; dev: `--cors` flag |
| Build time on data refresh | ~5 min for metadata JSON; parquet already exists |
| No server-side search | Fuse.js index (~400KB) handles 1,900 datasets well |
| Offline chart_selector changes | Pre-computed at build time — rebuild to update |
| Two languages doubles metadata | ~3MB total gzipped — acceptable |

## Estimated Sizes

| Asset | Raw Size | Gzipped |
|---|---|---|
| `api/categories.json` | ~50KB | ~10KB |
| `api/datasets/index.json` | ~1.5MB | ~300KB |
| `api/datasets/*.json` (×3,900) | ~2-20KB each | ~1-5KB each |
| `api/search-index.json` | ~400KB | ~100KB |
| `duckdb-wasm` bundle | ~10MB | ~4MB |
| `geo/*.geojson` | ~2MB | ~500KB |
| Parquet files (total) | varies | N/A (binary) |
| **Initial page load** | **~2MB** | **~500KB** |
