/**
 * StatExplorer — Vue 3 app entry point.
 *
 * Global reactive store, URL hash routing, data fetching.
 */
const { createApp, reactive, ref, computed, provide, inject, watch, nextTick, onMounted, onUnmounted } = Vue;

// ---- Global Store ----
const store = reactive({
    lang: localStorage.getItem('statex_lang') || 'ro',
    currentDataset: null,    // metadata from /api/datasets/{code}
    chartData: null,         // data from /api/datasets/{code}/data
    dataLoading: false,
    dataError: null,
    chartType: 'line',
    slots: {
        x_axis: null,
        series: null,
        facet: null,
        filter: [],
    },
    filters: {},             // {dim_column_name: [nom_item_id, ...]}
    presets: [],             // ranked_charts from chart_config
    activePresetIndex: 0,
});

// Expose store globally so i18n helper can read lang
window._store = store;

// ---- Data Fetching ----
let _loadVersion = 0;  // increment on each load to cancel stale requests

async function loadDataset(code) {
    if (!code) return;
    const myVersion = ++_loadVersion;

    store.dataLoading = true;
    store.dataError = null;

    try {
        const meta = await API.getDataset(code, store.lang);
        if (myVersion !== _loadVersion) return;  // stale, newer load started

        // Atomically update all store state
        store.chartData = null;
        store.filters = {};
        store.presets = meta.chart_config?.ranked_charts || [];
        store.activePresetIndex = 0;

        const primary = meta.chart_config?.primary_chart || 'line';
        store.chartType = primary;

        const primaryEntry = (meta.chart_config?.ranked_charts || []).find(r => r.chart_type === primary);
        if (primaryEntry?.roles) {
            store.slots.x_axis = primaryEntry.roles.x_axis || null;
            store.slots.series = primaryEntry.roles.series || null;
            store.slots.facet = primaryEntry.roles.facet || null;
            store.slots.filter = primaryEntry.roles.filter || [];
        } else {
            const timeDim = meta.dimensions?.find(d => d.dim_type === 'time');
            const indDim = meta.dimensions?.find(d => d.dim_type === 'indicator');
            store.slots.x_axis = timeDim?.dim_column_name || null;
            store.slots.series = indDim?.dim_column_name || null;
            store.slots.filter = meta.dimensions
                ?.filter(d => d.dim_column_name !== store.slots.x_axis
                    && d.dim_column_name !== store.slots.series
                    && d.dim_type !== 'unit')
                .map(d => d.dim_column_name) || [];
        }

        // Set currentDataset LAST (triggers v-if re-renders cleanly)
        store.currentDataset = meta;

        if (myVersion !== _loadVersion) return;  // check again after await
        await fetchData();
    } catch (e) {
        if (myVersion !== _loadVersion) return;
        store.dataError = e.message;
        console.error('loadDataset error:', e);
    } finally {
        if (myVersion === _loadVersion) store.dataLoading = false;
    }
}

async function fetchData() {
    if (!store.currentDataset) return;
    const myVersion = _loadVersion;  // snapshot — guard against stale results
    const code = store.currentDataset.matrix_code;
    store.dataLoading = true;
    try {
        const data = await API.getDatasetData(code, store.filters);
        if (_loadVersion !== myVersion) return;
        store.chartData = data;
    } catch (e) {
        if (_loadVersion !== myVersion) return;
        store.dataError = e.message;
        console.error('fetchData error:', e);
    } finally {
        if (_loadVersion === myVersion) store.dataLoading = false;
    }
}

// ---- URL Hash Routing ----
function handleHash() {
    const hash = location.hash.replace('#/', '').replace('#', '').trim();
    if (hash && hash !== '/') {
        loadDataset(hash);
    } else {
        store.currentDataset = null;
        store.chartData = null;
    }
}

window.addEventListener('hashchange', handleHash);

// ---- Vue App ----
const app = createApp({
    setup() {
        provide('store', store);
        onMounted(() => {
            handleHash();
        });
    },
    template: `
        <top-nav></top-nav>
        <template v-if="store.currentDataset">
            <filter-bar></filter-bar>
            <div class="main-layout">
                <left-sidebar></left-sidebar>
                <chart-canvas></chart-canvas>
            </div>
        </template>
        <dataset-picker v-else></dataset-picker>
        <footer-bar></footer-bar>
    `,
    // Make store accessible in template
    data() { return { store }; },
});

// Register components
app.component('top-nav', TopNav);
app.component('filter-bar', FilterBar);
app.component('left-sidebar', LeftSidebar);
app.component('chart-canvas', ChartCanvas);
app.component('dataset-picker', DatasetPicker);
app.component('footer-bar', FooterBar);

// Mount
app.mount('#app');
