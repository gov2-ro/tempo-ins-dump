/**
 * DatasetPicker — search + grid of dataset cards.
 */
const DatasetPicker = {
    template: `
        <div class="dataset-picker">
            <h2>{{ ui('appTitle') }} — INS TEMPO</h2>
            <input class="picker-search" type="text" :placeholder="ui('search')"
                v-model="query" @input="debouncedSearch" ref="searchInput">
            <div style="margin-bottom:12px;font-size:12px;color:var(--text-muted)">
                {{ total }} {{ ui('datasets') }}
            </div>
            <div class="picker-grid">
                <div class="picker-card" v-for="ds in datasets" :key="ds.matrix_code"
                    @click="selectDataset(ds.matrix_code)">
                    <div class="card-code">{{ ds.matrix_code }}</div>
                    <div class="card-name">{{ dsName(ds) }}</div>
                    <div class="card-meta">
                        <span class="tag" v-if="ds.time_range">{{ ds.time_range }}</span>
                        <span class="tag" v-if="ds.archetype">{{ ds.archetype }}</span>
                        <span v-if="ds.row_count">{{ formatNumber(ds.row_count, 0) }} {{ ui('rows') }}</span>
                    </div>
                </div>
            </div>
            <div v-if="datasets.length < total" style="text-align:center;margin-top:20px">
                <button @click="loadMore" style="padding:8px 20px;border:1px solid var(--border);border-radius:var(--radius);background:var(--bg-card);cursor:pointer">
                    Load more...
                </button>
            </div>
        </div>
    `,
    setup() {
        const store = Vue.inject('store');
        const query = Vue.ref('');
        const datasets = Vue.ref([]);
        const total = Vue.ref(0);
        const offset = Vue.ref(0);
        const searchInput = Vue.ref(null);

        let debounceTimer = null;
        function debouncedSearch() {
            clearTimeout(debounceTimer);
            debounceTimer = setTimeout(() => {
                offset.value = 0;
                search();
            }, 300);
        }

        async function search() {
            try {
                const res = await API.listDatasets({
                    q: query.value || undefined,
                    lang: store.lang,
                    limit: 50,
                    offset: offset.value,
                });
                if (offset.value === 0) {
                    datasets.value = res.datasets;
                } else {
                    datasets.value.push(...res.datasets);
                }
                total.value = res.total;
            } catch (e) {
                console.error('Search error:', e);
            }
        }

        function loadMore() {
            offset.value = datasets.value.length;
            search();
        }

        function dsName(ds) {
            if (store.lang === 'en' && ds.matrix_name_en) return ds.matrix_name_en;
            return ds.matrix_name;
        }

        function selectDataset(code) {
            location.hash = `#/${code}`;
        }

        Vue.onMounted(() => {
            search();
            Vue.nextTick(() => searchInput.value?.focus());
        });

        return { store, query, datasets, total, debouncedSearch, loadMore, dsName, selectDataset, searchInput, ui, formatNumber };
    },
};
