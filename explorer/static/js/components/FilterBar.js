/**
 * FilterBar — page-level dimension filter chips.
 * Shows a dropdown chip for each dimension in the "filter" role.
 */
const FilterBar = {
    template: `
        <div class="filter-bar" v-if="filterDims.length">
            <div class="filter-chip" v-for="dim in filterDims" :key="dim.dim_column_name">
                <span class="dim-name">{{ dim.dim_label }}</span>
                <span class="filter-value">{{ filterDisplay(dim) }}</span>
                <select @change="onFilterChange(dim, $event)" :value="currentValue(dim)">
                    <option value="">{{ ui('allValues') }}</option>
                    <option v-for="opt in dim.options" :key="opt.nom_item_id" :value="opt.nom_item_id">
                        {{ opt.label }}
                    </option>
                </select>
            </div>
        </div>
    `,
    setup() {
        const store = Vue.inject('store');

        const filterDims = Vue.computed(() => {
            if (!store.currentDataset) return [];
            const filterCols = store.slots.filter || [];
            return store.currentDataset.dimensions.filter(d =>
                filterCols.includes(d.dim_column_name)
            );
        });

        function currentValue(dim) {
            const f = store.filters[dim.dim_column_name];
            return f && f.length === 1 ? f[0] : '';
        }

        function filterDisplay(dim) {
            const f = store.filters[dim.dim_column_name];
            if (!f || f.length === 0) return ui('allValues');
            if (f.length === 1) {
                const opt = dim.options.find(o => o.nom_item_id === f[0]);
                return opt ? opt.label : String(f[0]);
            }
            return `${f.length} selected`;
        }

        function onFilterChange(dim, event) {
            const val = event.target.value;
            if (val) {
                store.filters[dim.dim_column_name] = [Number(val)];
            } else {
                delete store.filters[dim.dim_column_name];
            }
            fetchData();
        }

        return { store, filterDims, currentValue, filterDisplay, onFilterChange, ui };
    },
};
