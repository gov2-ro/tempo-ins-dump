/**
 * DuckDB-WASM Data Client
 *
 * Replaces the server-side /api/datasets/{code}/data endpoint.
 * Queries parquet files directly in the browser using DuckDB-WASM
 * with HTTP range requests (no full file download needed).
 *
 * Usage:
 *   import { queryDataset, getRowCount } from './duckdb-data-client.js';
 *
 *   // metadata = the pre-built JSON from api/datasets/{code}.json
 *   const result = await queryDataset('ACC101B', metadata.dimensions, filters, 5000);
 *   // result = { columns, column_labels, rows, total_rows, returned_rows, truncated }
 *
 * DuckDB-WASM is lazy-loaded on first use (~10MB download).
 * Subsequent queries reuse the initialized instance.
 *
 * See docs/plans/static-site-migration.md for architecture details.
 */

// ---------------------------------------------------------------------------
// Configuration — loaded from site-config.json at init
// ---------------------------------------------------------------------------

let CONFIG = {
    base_data_url: './data',
    duckdb_wasm_cdn: 'https://cdn.jsdelivr.net/npm/@duckdb/duckdb-wasm/dist/',
    max_data_rows: 50000,
    large_dataset_threshold: 50000,
};

// ---------------------------------------------------------------------------
// DuckDB-WASM singleton
// ---------------------------------------------------------------------------

let _db = null;
let _conn = null;
let _initPromise = null;  // Prevents concurrent initialization

/**
 * Load site-config.json and merge into CONFIG.
 */
export async function loadConfig() {
    try {
        const resp = await fetch('./site-config.json');
        if (resp.ok) {
            const cfg = await resp.json();
            Object.assign(CONFIG, cfg);
        }
    } catch (e) {
        console.warn('Could not load site-config.json, using defaults:', e);
    }
}

/**
 * Get current config (for reading base_data_url etc.)
 */
export function getConfig() {
    return CONFIG;
}

/**
 * Initialize DuckDB-WASM. Lazy — only called on first data query.
 * Returns the connection. Safe to call multiple times (idempotent).
 */
export async function initDuckDB() {
    if (_conn) return _conn;

    // Prevent concurrent initialization
    if (_initPromise) return _initPromise;

    _initPromise = _doInit();
    try {
        const conn = await _initPromise;
        return conn;
    } finally {
        _initPromise = null;
    }
}

async function _doInit() {
    console.time('duckdb-wasm:init');

    // Dynamic import from CDN
    const duckdb = await import(
        /* webpackIgnore: true */
        'https://cdn.jsdelivr.net/npm/@duckdb/duckdb-wasm/+esm'
    );

    // Select the best available bundle (EH > MVP)
    const JSDELIVR_BUNDLES = {
        mvp: {
            mainModule: CONFIG.duckdb_wasm_cdn + 'duckdb-mvp.wasm',
            mainWorker: CONFIG.duckdb_wasm_cdn + 'duckdb-browser-mvp.worker.js',
        },
        eh: {
            mainModule: CONFIG.duckdb_wasm_cdn + 'duckdb-eh.wasm',
            mainWorker: CONFIG.duckdb_wasm_cdn + 'duckdb-browser-eh.worker.js',
        },
    };

    const bundle = await duckdb.selectBundle(JSDELIVR_BUNDLES);
    const worker = new Worker(bundle.mainWorker);
    const logger = new duckdb.ConsoleLogger();

    _db = new duckdb.AsyncDuckDB(logger, worker);
    await _db.instantiate(bundle.mainModule);

    _conn = await _db.connect();

    // Enable httpfs for remote parquet access
    await _conn.query("INSTALL httpfs; LOAD httpfs;");

    console.timeEnd('duckdb-wasm:init');
    console.log('DuckDB-WASM initialized');
    return _conn;
}


// ---------------------------------------------------------------------------
// Data Query API
// ---------------------------------------------------------------------------

/**
 * Query a dataset's parquet file with optional filters.
 *
 * This is the static-site equivalent of:
 *   GET /api/datasets/{code}/data?filters={}&limit=N
 *
 * @param {string} matrixCode - Dataset code (e.g. 'ACC101B')
 * @param {Array} dimensions - From meta.json: [{dim_column_name, dim_type, options}]
 * @param {Object} filters - {column_name: [value, ...]} — values are SDMX strings (v3)
 * @param {number} limit - Max rows (default: CONFIG.max_data_rows)
 * @returns {Object} {columns, column_labels, rows, total_rows, returned_rows, truncated}
 */
export async function queryDataset(matrixCode, dimensions, filters = {}, limit = null) {
    limit = limit || CONFIG.max_data_rows;
    const conn = await initDuckDB();

    const parquetUrl = _resolveParquetUrl(matrixCode);

    // Build SELECT: dimension columns + OBS_VALUE
    const dimCols = dimensions.map(d => `"${_escapeIdent(d.dim_column_name)}"`);
    const selectCols = [...dimCols, '"OBS_VALUE"'].join(', ');

    // Build WHERE from filters
    const whereParts = [];
    const validCols = new Set(dimensions.map(d => d.dim_column_name));

    for (const [colName, values] of Object.entries(filters)) {
        if (!validCols.has(colName) || !values || values.length === 0) continue;

        const escaped = values.map(v =>
            typeof v === 'string'
                ? `'${_escapeSQL(v)}'`
                : String(v)
        );
        whereParts.push(`CAST("${_escapeIdent(colName)}" AS VARCHAR) IN (${escaped.join(', ')})`);
    }

    const whereSQL = whereParts.length > 0 ? 'WHERE ' + whereParts.join(' AND ') : '';

    // ORDER BY time dimension if present
    const timeDim = dimensions.find(d => d.dim_type === 'time');
    const orderSQL = timeDim ? `ORDER BY "${_escapeIdent(timeDim.dim_column_name)}" ASC` : '';

    // Query with limit + 1 to detect truncation
    const sql = `SELECT ${selectCols} FROM '${parquetUrl}' ${whereSQL} ${orderSQL} LIMIT ${limit + 1}`;

    console.time(`query:${matrixCode}`);
    let result;
    try {
        result = await conn.query(sql);
    } catch (e) {
        console.error(`Query failed for ${matrixCode}:`, e);
        throw new Error(`Failed to query dataset ${matrixCode}: ${e.message}`);
    }
    console.timeEnd(`query:${matrixCode}`);

    // Convert Arrow table to plain arrays
    const allRows = _arrowToArrays(result);
    const truncated = allRows.length > limit;
    const rows = truncated ? allRows.slice(0, limit) : allRows;

    // Build column_labels from dimension metadata (pre-loaded from meta.json)
    const columnLabels = _buildColumnLabels(dimensions, rows);

    const columns = [...dimensions.map(d => d.dim_column_name), 'OBS_VALUE'];

    return {
        columns,
        column_labels: columnLabels,
        rows,
        total_rows: rows.length,  // Approximate; see getRowCount for exact
        returned_rows: rows.length,
        truncated,
    };
}


/**
 * Get exact row count for a dataset (separate query, faster than full scan).
 *
 * @param {string} matrixCode - Dataset code
 * @returns {number} Total row count
 */
export async function getRowCount(matrixCode) {
    const conn = await initDuckDB();
    const parquetUrl = _resolveParquetUrl(matrixCode);
    const result = await conn.query(`SELECT COUNT(*) as cnt FROM '${parquetUrl}'`);
    const rows = _arrowToArrays(result);
    return rows[0]?.[0] ?? 0;
}


/**
 * Get distinct values for a column (useful for building filter dropdowns).
 *
 * @param {string} matrixCode - Dataset code
 * @param {string} columnName - Column to get distinct values for
 * @returns {Array} Sorted array of distinct values
 */
export async function getDistinctValues(matrixCode, columnName) {
    const conn = await initDuckDB();
    const parquetUrl = _resolveParquetUrl(matrixCode);
    const sql = `SELECT DISTINCT "${_escapeIdent(columnName)}" as val FROM '${parquetUrl}' ORDER BY 1`;
    const result = await conn.query(sql);
    return _arrowToArrays(result).map(r => r[0]);
}


// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function _resolveParquetUrl(matrixCode) {
    const base = CONFIG.base_data_url.replace(/\/$/, '');
    return `${base}/${matrixCode}.parquet`;
}

function _escapeSQL(s) {
    return String(s).replace(/'/g, "''");
}

function _escapeIdent(s) {
    // DuckDB quoted identifiers: double-quote escaping
    return String(s).replace(/"/g, '""');
}

/**
 * Convert an Arrow table result to array of arrays.
 */
function _arrowToArrays(arrowResult) {
    const rows = [];
    const numCols = arrowResult.numCols;
    const numRows = arrowResult.numRows;

    // Access columns by index for performance
    const columns = [];
    for (let c = 0; c < numCols; c++) {
        columns.push(arrowResult.getChildAt(c));
    }

    for (let r = 0; r < numRows; r++) {
        const row = new Array(numCols);
        for (let c = 0; c < numCols; c++) {
            row[c] = columns[c].get(r);
        }
        rows.push(row);
    }
    return rows;
}

/**
 * Build column_labels mapping from dimension metadata.
 *
 * For v3 SDMX parquets, values are already human-readable strings,
 * so column_labels maps value → value (identity). This preserves
 * compatibility with the frontend's label resolution logic.
 *
 * For dimensions with pre-parsed options (from meta.json), we provide
 * the richer nom_item_id → label mapping.
 */
function _buildColumnLabels(dimensions, rows) {
    const columnLabels = {};

    for (let i = 0; i < dimensions.length; i++) {
        const dim = dimensions[i];
        const col = dim.dim_column_name;

        // Collect unique values from query results
        const uniqueVals = new Set();
        for (const row of rows) {
            if (row[i] != null) uniqueVals.add(row[i]);
        }

        // Check if values are strings (v3 SDMX) or integers (v2 legacy)
        const hasStringValues = [...uniqueVals].some(v => typeof v === 'string');

        if (hasStringValues) {
            // v3: identity mapping (values are already labels)
            columnLabels[col] = {};
            for (const v of uniqueVals) {
                columnLabels[col][String(v)] = String(v);
            }
        } else if (dim.options && dim.options.length > 0) {
            // v2: use pre-loaded options from meta.json
            columnLabels[col] = {};
            const optMap = new Map(dim.options.map(o => [o.nom_item_id, o.label]));
            for (const v of uniqueVals) {
                columnLabels[col][String(v)] = optMap.get(v) || String(v);
            }
        }
    }

    return columnLabels;
}
