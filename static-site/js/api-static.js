/**
 * Static API Client
 *
 * Drop-in replacement for the FastAPI-backed API client.
 * Fetches pre-built JSON for metadata, delegates data queries to DuckDB-WASM.
 *
 * API compatibility: same return shapes as the FastAPI endpoints.
 *
 * Metadata endpoints (static JSON):
 *   API.getCategories()           → fetch('api/categories.json')
 *   API.listDatasets(params)      → fetch('api/datasets/index.json') + client filter
 *   API.getDataset(code)          → fetch('api/datasets/{code}.json')
 *
 * Data endpoint (DuckDB-WASM):
 *   API.getDatasetData(code, ...) → duckdb-data-client.queryDataset()
 */

import { queryDataset, getRowCount, loadConfig, getConfig } from './duckdb-data-client.js';

// ---------------------------------------------------------------------------
// Cache for loaded JSON
// ---------------------------------------------------------------------------

const _cache = {
    categories: null,
    datasetIndex: null,     // full dataset list
    searchIndex: null,      // Fuse.js index
    datasets: new Map(),    // per-dataset metadata: code → json
};

let _fuseInstance = null;

// ---------------------------------------------------------------------------
// Initialization
// ---------------------------------------------------------------------------

/**
 * Initialize the API client. Call once at app startup.
 * Loads site-config.json and optionally pre-fetches the dataset index.
 */
export async function init() {
    await loadConfig();
}

// ---------------------------------------------------------------------------
// Categories
// ---------------------------------------------------------------------------

/**
 * Get the category tree with dataset counts.
 * Equivalent to: GET /api/categories
 *
 * @returns {Object} { tree: [...] }
 */
export async function getCategories() {
    if (_cache.categories) return _cache.categories;

    const config = getConfig();
    const resp = await fetch(`${config.base_api_url}/categories.json`);
    if (!resp.ok) throw new Error(`Failed to load categories: ${resp.status}`);

    _cache.categories = await resp.json();
    return _cache.categories;
}


// ---------------------------------------------------------------------------
// Dataset List
// ---------------------------------------------------------------------------

/**
 * Load the full dataset index (once).
 */
async function _ensureDatasetIndex() {
    if (_cache.datasetIndex) return _cache.datasetIndex;

    const config = getConfig();
    const resp = await fetch(`${config.base_api_url}/datasets/index.json`);
    if (!resp.ok) throw new Error(`Failed to load dataset index: ${resp.status}`);

    _cache.datasetIndex = await resp.json();
    return _cache.datasetIndex;
}

/**
 * List datasets with search, filters, sort, and pagination.
 * Equivalent to: GET /api/datasets?q=...&context=...&sort=...&limit=...&offset=...
 *
 * All filtering happens client-side against the pre-loaded index.
 *
 * @param {Object} params - { q, context, ancestor, archetype, has_geo, sort, limit, offset }
 * @returns {Object} { total: N, datasets: [...] }
 */
export async function listDatasets(params = {}) {
    const index = await _ensureDatasetIndex();
    let datasets = [...index.datasets];

    // --- Filtering ---
    if (params.q) {
        const q = params.q.toLowerCase();
        datasets = datasets.filter(d =>
            d.matrix_name?.toLowerCase().includes(q) ||
            d.matrix_code?.toLowerCase().includes(q)
        );
    }

    if (params.context) {
        datasets = datasets.filter(d => d.context_code === params.context);
    }

    if (params.ancestor) {
        // Ancestor filtering requires context_path, which is only in per-dataset JSON.
        // For the index, we approximate: context_code starts with ancestor pattern.
        // Full ancestor filtering needs the per-dataset meta — skip for index.
        // TODO: add ancestor_codes to index if needed
        datasets = datasets.filter(d => d.context_code === params.ancestor);
    }

    if (params.archetype) {
        datasets = datasets.filter(d => d.archetype === params.archetype);
    }

    if (params.has_geo !== undefined && params.has_geo !== null) {
        datasets = datasets.filter(d => d.has_geo === params.has_geo);
    }

    // --- Sorting ---
    const sort = params.sort || 'updated';
    if (sort === 'updated') {
        datasets.sort((a, b) => (b.ultima_actualizare || '').localeCompare(a.ultima_actualizare || ''));
    } else if (sort === 'name') {
        datasets.sort((a, b) => (a.matrix_name || '').localeCompare(b.matrix_name || ''));
    } else if (sort === 'rows') {
        datasets.sort((a, b) => (b.row_count || 0) - (a.row_count || 0));
    }

    // --- Pagination ---
    const total = datasets.length;
    const limit = params.limit || 50;
    const offset = params.offset || 0;
    const page = datasets.slice(offset, offset + limit);

    return { total, datasets: page };
}


// ---------------------------------------------------------------------------
// Dataset Detail
// ---------------------------------------------------------------------------

/**
 * Get full dataset metadata (dimensions, chart config, profile, etc.)
 * Equivalent to: GET /api/datasets/{code}
 *
 * @param {string} matrixCode - Dataset code
 * @returns {Object} Full dataset metadata
 */
export async function getDataset(matrixCode) {
    if (_cache.datasets.has(matrixCode)) {
        return _cache.datasets.get(matrixCode);
    }

    const config = getConfig();
    const resp = await fetch(`${config.base_api_url}/datasets/${matrixCode}.json`);
    if (!resp.ok) {
        if (resp.status === 404) throw new Error(`Dataset ${matrixCode} not found`);
        throw new Error(`Failed to load dataset ${matrixCode}: ${resp.status}`);
    }

    const data = await resp.json();
    _cache.datasets.set(matrixCode, data);
    return data;
}


// ---------------------------------------------------------------------------
// Dataset Data (DuckDB-WASM)
// ---------------------------------------------------------------------------

/**
 * Query dataset parquet with dimension filters.
 * Equivalent to: GET /api/datasets/{code}/data?filters={}&limit=N
 *
 * First call triggers DuckDB-WASM initialization (~10MB download).
 * Subsequent calls are fast.
 *
 * @param {string} matrixCode - Dataset code
 * @param {Object} filters - { column_name: [value, ...] }
 * @param {number} limit - Max rows (default: 50000)
 * @returns {Object} { columns, column_labels, rows, total_rows, returned_rows, truncated }
 */
export async function getDatasetData(matrixCode, filters = {}, limit = null) {
    // Load metadata to get dimensions
    const meta = await getDataset(matrixCode);

    const config = getConfig();
    limit = limit || config.max_data_rows;

    // Check if large dataset needs filters
    if (meta.row_count > config.large_dataset_threshold && Object.keys(filters).length === 0) {
        throw new Error(
            `Dataset has ${meta.row_count.toLocaleString()} rows. ` +
            `Please apply at least one filter (max ${config.max_data_rows.toLocaleString()} rows).`
        );
    }

    return queryDataset(matrixCode, meta.dimensions, filters, limit);
}


// ---------------------------------------------------------------------------
// Search (Fuse.js integration)
// ---------------------------------------------------------------------------

/**
 * Search datasets using Fuse.js fuzzy search.
 * Falls back to simple substring match if Fuse.js is not loaded.
 *
 * @param {string} query - Search term
 * @param {number} limit - Max results (default: 20)
 * @returns {Array} Array of { matrix_code, matrix_name, ... }
 */
export async function searchDatasets(query, limit = 20) {
    if (!query || query.trim().length === 0) {
        return (await listDatasets({ limit })).datasets;
    }

    // Try Fuse.js first
    if (typeof Fuse !== 'undefined') {
        if (!_fuseInstance) {
            const config = getConfig();
            const resp = await fetch(`${config.base_api_url}/search-index.json`);
            if (resp.ok) {
                const searchData = await resp.json();
                _fuseInstance = new Fuse(searchData, {
                    keys: ['n', 'c'],  // name, code
                    threshold: 0.3,
                    distance: 100,
                });
            }
        }

        if (_fuseInstance) {
            const results = _fuseInstance.search(query, { limit });
            const codes = new Set(results.map(r => r.item.c));

            // Return full dataset cards for matched codes
            const index = await _ensureDatasetIndex();
            return index.datasets.filter(d => codes.has(d.matrix_code));
        }
    }

    // Fallback: simple substring search
    return (await listDatasets({ q: query, limit })).datasets;
}


// ---------------------------------------------------------------------------
// Export as namespace
// ---------------------------------------------------------------------------

const API = {
    init,
    getCategories,
    listDatasets,
    getDataset,
    getDatasetData,
    searchDatasets,
};

export default API;
