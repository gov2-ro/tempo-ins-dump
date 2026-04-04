/**
 * Static StatExplorer — App Bootstrap
 *
 * Initializes the Vue 3 app with a reactive global store.
 * Data flows:
 *   1. API.getCategories()      → static JSON  → store.categories
 *   2. API.listDatasets(params)  → static JSON  → store.datasets
 *   3. API.getDataset(code)     → static JSON  → store.currentDataset
 *   4. API.getDatasetData(...)  → DuckDB-WASM  → store.chartData
 *
 * This file mirrors explorer/static/js/app.js but uses api-static.js
 * instead of server-backed API calls.
 *
 * Components are loaded from js/components/ and registered below.
 * Chart modules are loaded from js/charts/ and dispatched by chart-factory.js.
 */

// ---------------------------------------------------------------------------
// Global reactive store
// ---------------------------------------------------------------------------

const store = Vue.reactive({
    // Language
    lang: localStorage.getItem('statex_lang') || 'ro',

    // Navigation state
    view: 'picker',           // 'picker' | 'dataset'
    currentDataset: null,     // Full metadata from API.getDataset()

    // Dataset list (for picker)
    datasets: [],
    totalDatasets: 0,
    searchQuery: '',
    selectedContext: null,
    sortBy: 'updated',
    loading: false,

    // Categories
    categories: null,

    // Data & chart state
    chartData: null,          // { columns, column_labels, rows, ... }
    chartType: null,          // Current chart type string
    slots: { x_axis: null, series: null, facet: null, timeline: null, filter: [] },
    filters: {},              // { column_name: [value, ...] }

    // DuckDB-WASM state
    duckdbLoading: false,
    duckdbReady: false,

    // UI state
    dataLoading: false,
    error: null,
});

window.store = store;

// ---------------------------------------------------------------------------
// Core data loading functions
// ---------------------------------------------------------------------------

let _loadVersion = 0;  // Cancels stale requests

/**
 * Load a dataset by code. Fetches metadata (static JSON) and initial data (DuckDB-WASM).
 */
async function loadDataset(code) {
    const myVersion = ++_loadVersion;
    store.loading = true;
    store.error = null;
    store.chartData = null;

    try {
        // 1. Load metadata (static JSON — fast)
        const meta = await API.getDataset(code);
        if (myVersion !== _loadVersion) return;  // Stale

        store.currentDataset = meta;

        // 2. Apply default chart config
        const ranked = meta.chart_config?.ranked_charts || [];
        if (ranked.length > 0) {
            store.chartType = ranked[0].chart_type;
            store.slots = { ...ranked[0].roles };
        } else {
            store.chartType = 'table';
            store.slots = { x_axis: null, series: null, facet: null, timeline: null, filter: [] };
        }

        // 3. Set default filters (none initially)
        store.filters = {};

        // 4. Fetch data (DuckDB-WASM — may trigger initialization)
        await fetchData();

    } catch (e) {
        if (myVersion === _loadVersion) {
            store.error = e.message;
            console.error('Failed to load dataset:', e);
        }
    } finally {
        if (myVersion === _loadVersion) {
            store.loading = false;
        }
    }

    // Update URL hash
    window.location.hash = `#/${code}`;
}

/**
 * Fetch data for the current dataset with current filters.
 * Called after loadDataset() and whenever filters change.
 */
async function fetchData() {
    if (!store.currentDataset) return;

    const myVersion = _loadVersion;
    store.dataLoading = true;
    store.duckdbLoading = !store.duckdbReady;

    try {
        const result = await API.getDatasetData(
            store.currentDataset.matrix_code,
            store.filters
        );
        if (myVersion !== _loadVersion) return;  // Stale

        store.duckdbReady = true;
        store.duckdbLoading = false;
        store.chartData = result;

    } catch (e) {
        if (myVersion === _loadVersion) {
            store.error = e.message;
            store.duckdbLoading = false;
            console.error('Data fetch failed:', e);
        }
    } finally {
        if (myVersion === _loadVersion) {
            store.dataLoading = false;
        }
    }
}

/**
 * Go back to the dataset picker.
 */
function closeDataset() {
    store.currentDataset = null;
    store.chartData = null;
    store.chartType = null;
    store.filters = {};
    window.location.hash = '';
}

// Expose to components
window.loadDataset = loadDataset;
window.fetchData = fetchData;
window.closeDataset = closeDataset;

// ---------------------------------------------------------------------------
// URL hash routing
// ---------------------------------------------------------------------------

function handleHashChange() {
    const hash = window.location.hash;
    const match = hash.match(/^#\/(.+)$/);
    if (match) {
        const code = match[1];
        if (!store.currentDataset || store.currentDataset.matrix_code !== code) {
            loadDataset(code);
        }
    }
}

// ---------------------------------------------------------------------------
// Vue app creation
// ---------------------------------------------------------------------------

function createApp() {
    const app = Vue.createApp({
        setup() {
            return { store };
        },
    });

    // Register components (loaded from js/components/*.js as globals)
    const componentNames = [
        'TopNav', 'FilterBar', 'LeftSidebar',
        'ChartCanvas', 'DatasetPicker', 'FooterBar',
    ];

    for (const name of componentNames) {
        if (window[name]) {
            // Convert PascalCase to kebab-case for template usage
            const kebab = name.replace(/([A-Z])/g, '-$1').toLowerCase().replace(/^-/, '');
            app.component(kebab, window[name]);
        } else {
            console.warn(`Component ${name} not found — using placeholder`);
            const kebab = name.replace(/([A-Z])/g, '-$1').toLowerCase().replace(/^-/, '');
            app.component(kebab, {
                template: `<div class="placeholder">${name} (not loaded)</div>`,
            });
        }
    }

    app.mount('#app');
    console.log('StatExplorer (static) mounted');

    // Handle initial URL hash
    handleHashChange();
    window.addEventListener('hashchange', handleHashChange);
}

// ---------------------------------------------------------------------------
// Boot sequence
// ---------------------------------------------------------------------------

// Wait for API client to be ready (module import + config load)
if (window.API) {
    createApp();
} else {
    window.addEventListener('api-ready', createApp);
}
