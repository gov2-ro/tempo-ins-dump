/**
 * TopNav — app title, breadcrumb, lang toggle, change dataset button.
 */
const TopNav = {
    template: `
        <nav class="top-nav">
            <span class="app-title">{{ ui('appTitle') }}</span>
            <span class="breadcrumb" v-if="store.currentDataset">
                <span v-if="store.currentDataset.context_path">
                    {{ contextPath }} &rsaquo;
                </span>
                {{ displayName }}
                <span style="opacity:0.5; margin-left:4px">{{ store.currentDataset.matrix_code }}</span>
            </span>
            <span class="breadcrumb" v-else>INS TEMPO</span>
            <button class="lang-toggle" @click="toggleLang">{{ store.lang === 'ro' ? 'EN' : 'RO' }}</button>
            <button class="btn-change-dataset" v-if="store.currentDataset" @click="changeDataset">
                {{ ui('changeDataset') }}
            </button>
        </nav>
    `,
    setup() {
        const store = Vue.inject('store');

        const displayName = Vue.computed(() => {
            const ds = store.currentDataset;
            if (!ds) return '';
            return datasetName(ds, store.lang);
        });

        const contextPath = Vue.computed(() => {
            const ds = store.currentDataset;
            if (!ds) return '';
            if (store.lang === 'en' && ds.context_path_en) return ds.context_path_en;
            return ds.context_path || '';
        });

        function toggleLang() {
            store.lang = store.lang === 'ro' ? 'en' : 'ro';
            localStorage.setItem('statex_lang', store.lang);
            // Reload dataset with new lang
            if (store.currentDataset) {
                loadDataset(store.currentDataset.matrix_code);
            }
        }

        function changeDataset() {
            store.currentDataset = null;
            location.hash = '#/';
        }

        return { store, displayName, contextPath, toggleLang, changeDataset, ui };
    },
};
