/**
 * FooterBar — status info.
 */
const FooterBar = {
    template: `
        <footer class="footer-bar">
            <span v-if="store.currentDataset">{{ store.currentDataset.matrix_code }}</span>
            <span v-if="store.chartData">
                {{ store.chartData.returned_rows }} {{ ui('observations') }}
                <template v-if="store.chartData.truncated"> (truncated)</template>
            </span>
            <span v-if="store.currentDataset">
                {{ store.currentDataset.dim_count }} {{ ui('dimensions') }}
            </span>
            <span style="flex:1"></span>
            <span>INS TEMPO StatExplorer</span>
        </footer>
    `,
    setup() {
        const store = Vue.inject('store');
        return { store, ui };
    },
};
