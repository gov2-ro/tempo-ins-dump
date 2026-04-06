/**
 * LeftSidebar — Configure + Smart Presets tabs.
 */
const LeftSidebar = {
    template: `
        <aside class="left-sidebar">
            <div class="sidebar-tabs">
                <button class="sidebar-tab" :class="{ active: tab === 'configure' }"
                    @click="tab = 'configure'">{{ ui('configure') }}</button>
                <button class="sidebar-tab" :class="{ active: tab === 'presets' }"
                    @click="tab = 'presets'">{{ ui('presets') }}</button>
            </div>
            <div class="sidebar-content">
                <!-- Configure tab -->
                <template v-if="tab === 'configure'">
                    <h4 style="font-size:11px;text-transform:uppercase;letter-spacing:0.5px;color:var(--text-light);margin-bottom:8px">
                        {{ ui('chartType') }}
                    </h4>
                    <div class="chart-type-grid">
                        <button v-for="ct in supportedCharts" :key="ct"
                            class="chart-type-btn" :class="{ active: store.chartType === ct }"
                            @click="setChartType(ct)">
                            <span class="icon">{{ chartMeta(ct).icon }}</span>
                            {{ chartMeta(ct).label[store.lang] || chartMeta(ct).label.ro }}
                        </button>
                    </div>

                    <!-- Dimension slots -->
                    <div class="slot-section">
                        <h4>{{ ui('xAxis') }}</h4>
                        <div class="slot-zone slot-x">
                            <span v-if="slotDim('x_axis')" class="dim-pill"
                                :class="'type-' + slotDimType('x_axis')">
                                {{ slotDimLabel('x_axis') }}
                            </span>
                            <span v-else style="font-size:11px;color:var(--text-light);padding:4px">—</span>
                        </div>
                    </div>
                    <div class="slot-section">
                        <h4>{{ ui('series') }}</h4>
                        <div class="slot-zone slot-series">
                            <span v-if="slotDim('series')" class="dim-pill"
                                :class="'type-' + slotDimType('series')">
                                {{ slotDimLabel('series') }}
                            </span>
                            <span v-else style="font-size:11px;color:var(--text-light);padding:4px">—</span>
                        </div>
                    </div>

                    <!-- All dimensions -->
                    <div class="slot-section" style="margin-top:16px">
                        <h4>{{ ui('dimensions') }}</h4>
                        <div style="display:flex;flex-wrap:wrap;gap:4px">
                            <span v-for="dim in allDims" :key="dim.dim_column_name"
                                class="dim-pill" :class="'type-' + dim.dim_type"
                                @click="cycleDimSlot(dim)"
                                :title="dim.dim_column_name + ' (' + dim.option_count + ')'">
                                {{ dim.dim_label }}
                                <span style="font-size:10px;opacity:0.6">{{ dimRole(dim) }}</span>
                            </span>
                        </div>
                    </div>
                </template>

                <!-- Presets tab -->
                <template v-else>
                    <div v-for="(preset, i) in store.presets" :key="i"
                        class="preset-card" :class="{ active: store.activePresetIndex === i }"
                        @click="applyPreset(i)">
                        <div class="preset-name">
                            {{ chartMeta(preset.chart_type).icon }}
                            {{ chartMeta(preset.chart_type).label[store.lang] || preset.chart_type }}
                        </div>
                        <div class="preset-score">Score: {{ preset.score }}</div>
                    </div>
                </template>
            </div>
        </aside>
    `,
    setup() {
        const store = Vue.inject('store');
        const tab = Vue.ref('configure');

        const supportedCharts = Vue.computed(() =>
            store.currentDataset?.chart_config?.supports || ['line']
        );

        const allDims = Vue.computed(() =>
            store.currentDataset?.dimensions?.filter(d => d.dim_type !== 'unit') || []
        );

        function chartMeta(ct) {
            return CHART_TYPE_META[ct] || { icon: '📊', label: { ro: ct, en: ct } };
        }

        function setChartType(ct) {
            store.chartType = ct;
            // Get roles for this chart type
            const ranked = store.currentDataset?.chart_config?.ranked_charts || [];
            const entry = ranked.find(r => r.chart_type === ct);
            if (entry && entry.roles) {
                store.slots.x_axis = entry.roles.x_axis;
                store.slots.series = entry.roles.series;
                store.slots.facet = entry.roles.facet;
                store.slots.filter = entry.roles.filter || [];
            }
            fetchData();
        }

        function slotDim(slotName) {
            return store.slots[slotName];
        }

        function slotDimType(slotName) {
            const col = store.slots[slotName];
            if (!col) return 'indicator';
            const dim = store.currentDataset?.dimensions?.find(d => d.dim_column_name === col);
            return dim?.dim_type || 'indicator';
        }

        function slotDimLabel(slotName) {
            const col = store.slots[slotName];
            if (!col) return '';
            const dim = store.currentDataset?.dimensions?.find(d => d.dim_column_name === col);
            return dim?.dim_label || col;
        }

        function dimRole(dim) {
            const col = dim.dim_column_name;
            if (store.slots.x_axis === col) return '(X)';
            if (store.slots.series === col) return '(S)';
            if (store.slots.facet === col) return '(F)';
            return '';
        }

        function cycleDimSlot(dim) {
            const col = dim.dim_column_name;
            const currentRole = store.slots.x_axis === col ? 'x_axis'
                : store.slots.series === col ? 'series'
                : store.slots.facet === col ? 'facet'
                : 'filter';

            // Cycle: filter → x_axis → series → facet → filter
            const cycle = ['filter', 'x_axis', 'series', 'facet'];
            const nextIdx = (cycle.indexOf(currentRole) + 1) % cycle.length;
            const nextRole = cycle[nextIdx];

            // Remove from current slot
            if (currentRole !== 'filter') {
                store.slots[currentRole] = null;
            }

            // Assign to new slot (swap if occupied)
            if (nextRole !== 'filter') {
                const displaced = store.slots[nextRole];
                store.slots[nextRole] = col;
                if (displaced) {
                    store.slots.filter = [...(store.slots.filter || []), displaced];
                }
            }

            // Rebuild filter list
            const assigned = new Set([store.slots.x_axis, store.slots.series, store.slots.facet].filter(Boolean));
            store.slots.filter = (store.currentDataset?.dimensions || [])
                .filter(d => !assigned.has(d.dim_column_name) && d.dim_type !== 'unit')
                .map(d => d.dim_column_name);

            fetchData();
        }

        function applyPreset(i) {
            const preset = store.presets[i];
            if (!preset) return;
            store.activePresetIndex = i;
            store.chartType = preset.chart_type;
            if (preset.roles) {
                store.slots.x_axis = preset.roles.x_axis;
                store.slots.series = preset.roles.series;
                store.slots.facet = preset.roles.facet;
                store.slots.filter = preset.roles.filter || [];
            }
            fetchData();
        }

        return {
            store, tab, supportedCharts, allDims,
            chartMeta, setChartType, slotDim, slotDimType, slotDimLabel,
            dimRole, cycleDimSlot, applyPreset, ui,
        };
    },
};
