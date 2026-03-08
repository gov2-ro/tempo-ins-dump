/**
 * ChartCanvas — ECharts container, reacts to store changes.
 *
 * ECharts is initialized on a programmatically-created div (not Vue-managed)
 * so that echarts.dispose() never touches Vue's vdom nodes.
 */
const ChartCanvas = {
    template: `
        <div class="chart-canvas">
            <div ref="containerEl" class="chart-container">
                <!-- Vue-managed overlays only — ECharts div injected programmatically -->
                <div class="loading-overlay" v-if="store.dataLoading">{{ ui('loading') }}</div>
                <div class="loading-overlay" v-else-if="store.dataError">
                    <span style="font-size:24px">⚠️</span>
                    <span>{{ store.dataError }}</span>
                    <span style="font-size:12px;color:var(--text-light)">Aplicați un filtru din bara de sus</span>
                </div>
                <div class="loading-overlay" v-else-if="!store.chartData" style="color:var(--text-light)">
                    Selectați un set de date pentru a vedea graficul
                </div>
            </div>
        </div>
    `,
    setup() {
        const store = Vue.inject('store');
        const containerEl = Vue.ref(null);
        let echartsEl = null;   // programmatically created, NOT in Vue's vdom
        let chartInstance = null;
        let ro = null;
        let _renderVersion = 0;  // cancel stale async renders

        function disposeChart() {
            if (chartInstance) {
                chartInstance.dispose();
                chartInstance = null;
            }
        }

        async function renderIfReady() {
            if (!store.chartData || !echartsEl) return;
            if (!document.contains(echartsEl)) return;
            const myVersion = ++_renderVersion;
            disposeChart();
            const result = renderChart(
                echartsEl,
                store.chartType,
                store.slots,
                store.chartData,
                store.currentDataset
            );
            // renderChart may return a Promise (e.g. choropleth loads GeoJSON async)
            const instance = (result instanceof Promise) ? await result : result;
            if (myVersion !== _renderVersion) {
                // A newer render started while we were awaiting — discard this result
                if (instance && typeof instance.dispose === 'function') instance.dispose();
                return;
            }
            chartInstance = instance;
        }

        // Watch for data/slot changes and re-render
        Vue.watch(
            () => [store.chartData, store.chartType, store.slots.x_axis, store.slots.series],
            () => {
                if (!store.chartData) {
                    disposeChart();
                    return;
                }
                renderIfReady();
            },
            { deep: true }
        );

        Vue.onMounted(() => {
            // Inject ECharts div as first child, before Vue's overlay divs
            echartsEl = document.createElement('div');
            echartsEl.style.cssText = 'position:absolute;inset:0;border-radius:inherit;z-index:1';
            containerEl.value.insertBefore(echartsEl, containerEl.value.firstChild);

            ro = new ResizeObserver(() => {
                if (chartInstance) chartInstance.resize();
            });
            ro.observe(echartsEl);

            // Render immediately if data already loaded (e.g. hot-reload)
            if (store.chartData) renderIfReady();
        });

        Vue.onUnmounted(() => {
            ro?.disconnect();
            disposeChart();
            // Remove echartsEl from DOM cleanly
            if (echartsEl && echartsEl.parentNode) {
                echartsEl.parentNode.removeChild(echartsEl);
            }
            echartsEl = null;
        });

        return { store, containerEl, ui };
    },
};
