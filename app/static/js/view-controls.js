/**
 * View controls panel — renders controls from view profile definitions.
 * Each control maps to a dimension and produces filter values.
 */
class ViewControlsPanel {
    static TOTAL_RE = /^(total|toate|ambele sexe|ambele|urban\s*\+\s*rural|m\s*\+\s*f)$/i;

    constructor(container, controls, dimensions, onChange) {
        this.container = container;
        this.controls = controls || [];
        this.dimensions = dimensions || [];
        this.onChange = onChange;
        this.widgets = [];       // { control, element, getValue }
        this.periodBrowser = null;
        this.render();
    }

    /** Find dimension metadata by column name */
    findDim(column) {
        return this.dimensions.find(d => d.dim_column_name === column);
    }

    /**
     * Resolve default value for a control.
     * Parquet files do NOT contain "Total" aggregate rows — those IDs from
     * metadata won't match any data. So "total" maps to first non-total option.
     * For pill_group / multi_select with few options, empty = "All" is OK.
     */
    resolveDefault(control, options) {
        const def = control.default;
        if (Array.isArray(def)) return def;

        // "latest" — period browser needs last time point
        if (def === 'latest') {
            return options.length ? [options[options.length - 1].nom_item_id] : [];
        }

        // Everything else: select ALL non-Total options by default
        const allNonTotal = options
            .filter(o => !ViewControlsPanel.TOTAL_RE.test(o.label))
            .map(o => o.nom_item_id);
        return allNonTotal;
    }

    render() {
        this.container.innerHTML = '';
        this.widgets = [];
        this.periodBrowser = null;

        if (this.controls.length === 0) return;

        const wrap = document.createElement('div');
        wrap.className = 'view-controls-bar';

        for (const ctrl of this.controls) {
            if (ctrl.type === 'period_browser') {
                // Period browser rendered separately — store reference
                const pbContainer = document.createElement('div');
                pbContainer.className = 'control-group control-period';
                wrap.appendChild(pbContainer);
                const dim = this.findDim(ctrl.column);
                if (dim) {
                    this.periodBrowser = new PeriodBrowser(
                        pbContainer,
                        dim.options || [],
                        ctrl.granularity,
                        () => this.onChange()
                    );
                }
                continue;
            }

            if (ctrl.type === 'subgroup_selector') {
                const group = document.createElement('div');
                group.className = 'control-group';
                const label = document.createElement('label');
                label.className = 'control-label';
                label.textContent = ctrl.label || ctrl.column;
                group.appendChild(label);
                const widget = this.renderSubgroupSelector(group, ctrl);
                this.widgets.push({ control: ctrl, ...widget });
                wrap.appendChild(group);
                continue;
            }

            const dim = this.findDim(ctrl.column);
            if (!dim) continue;
            const options = dim.options || [];
            const defaults = this.resolveDefault(ctrl, options);

            const group = document.createElement('div');
            group.className = 'control-group';

            const label = document.createElement('label');
            label.className = 'control-label';
            label.textContent = ctrl.label || dim.label || ctrl.column;
            group.appendChild(label);

            let widget;
            switch (ctrl.type) {
                case 'pill_group':
                    widget = this.renderPillGroup(group, ctrl, options, defaults);
                    break;
                case 'single_select':
                    widget = this.renderSingleSelect(group, ctrl, options, defaults);
                    break;
                case 'multi_select':
                    widget = this.renderMultiSelect(group, ctrl, options, defaults);
                    break;
                case 'typeahead_select':
                    widget = this.renderTypeahead(group, ctrl, options, defaults);
                    break;
                default:
                    widget = this.renderSingleSelect(group, ctrl, options, defaults);
            }

            this.widgets.push({ control: ctrl, ...widget });
            wrap.appendChild(group);
        }

        this.container.appendChild(wrap);
    }

    // --- Widget renderers ---

    renderPillGroup(group, ctrl, options, defaults) {
        const pillWrap = document.createElement('div');
        pillWrap.className = 'pill-group';

        const filtered = options.filter(o => !ViewControlsPanel.TOTAL_RE.test(o.label));
        const selected = new Set(defaults);
        const allSelected = () => filtered.every(o => selected.has(o.nom_item_id));

        const updatePillStates = () => {
            allPill.classList.toggle('active', allSelected());
            pillWrap.querySelectorAll('.pill:not([data-id="_all"])').forEach(p => {
                p.classList.toggle('active', selected.has(parseInt(p.dataset.id)));
            });
        };

        // "All" pill — toggles all on/off
        const allPill = document.createElement('button');
        allPill.className = 'pill' + (allSelected() ? ' active' : '');
        allPill.textContent = 'All';
        allPill.dataset.id = '_all';
        allPill.addEventListener('click', () => {
            if (allSelected()) {
                // Deselect all — keep just first
                selected.clear();
                if (filtered.length > 0) selected.add(filtered[0].nom_item_id);
            } else {
                // Select all
                for (const o of filtered) selected.add(o.nom_item_id);
            }
            updatePillStates();
            this.onChange();
        });
        pillWrap.appendChild(allPill);

        for (const opt of filtered) {
            const pill = document.createElement('button');
            pill.className = 'pill' + (selected.has(opt.nom_item_id) ? ' active' : '');
            pill.textContent = opt.label;
            pill.dataset.id = opt.nom_item_id;
            pill.addEventListener('click', () => {
                if (selected.has(opt.nom_item_id)) {
                    // Don't allow deselecting the last one
                    if (selected.size > 1) selected.delete(opt.nom_item_id);
                } else {
                    selected.add(opt.nom_item_id);
                }
                updatePillStates();
                this.onChange();
            });
            pillWrap.appendChild(pill);
        }
        group.appendChild(pillWrap);

        return {
            element: pillWrap,
            getValue: () => {
                // All selected = no filter needed (efficient)
                if (allSelected()) return [];
                return Array.from(selected);
            },
        };
    }

    renderSingleSelect(group, ctrl, options, defaults) {
        const select = document.createElement('select');
        select.className = 'control-select';

        // "All" option when default is empty (no filter)
        const allOpt = document.createElement('option');
        allOpt.value = '_all';
        allOpt.textContent = '— All —';
        if (defaults.length === 0) allOpt.selected = true;
        select.appendChild(allOpt);

        for (const opt of options) {
            // Skip Total-like options (not in parquet)
            if (ViewControlsPanel.TOTAL_RE.test(opt.label)) continue;

            const option = document.createElement('option');
            option.value = opt.nom_item_id;
            option.textContent = opt.label;
            if (defaults.includes(opt.nom_item_id)) option.selected = true;
            select.appendChild(option);
        }
        select.addEventListener('change', () => this.onChange());
        group.appendChild(select);

        return {
            element: select,
            getValue: () => {
                if (select.value === '_all') return [];
                return [parseInt(select.value)];
            },
        };
    }

    renderMultiSelect(group, ctrl, options, defaults) {
        const wrapper = document.createElement('div');
        wrapper.className = 'multi-select-wrap';

        // Filter out Total-like options
        const filtered = options.filter(o => !ViewControlsPanel.TOTAL_RE.test(o.label));

        const btn = document.createElement('button');
        btn.className = 'multi-select-btn';
        const allMode = defaults.length === 0 || defaults.length === filtered.length;
        btn.textContent = allMode ? 'All' : `Select (${defaults.length})`;

        const dropdown = document.createElement('div');
        dropdown.className = 'multi-select-dropdown hidden';

        const selected = new Set(defaults);

        for (const opt of filtered) {
            const row = document.createElement('label');
            row.className = 'multi-opt';
            const cb = document.createElement('input');
            cb.type = 'checkbox';
            cb.value = opt.nom_item_id;
            cb.checked = allMode || selected.has(opt.nom_item_id);
            cb.addEventListener('change', () => {
                const total = dropdown.querySelectorAll('input').length;
                const count = dropdown.querySelectorAll('input:checked').length;
                btn.textContent = count === total ? 'All' : `Select (${count})`;
                this.onChange();
            });
            row.appendChild(cb);
            row.appendChild(document.createTextNode(' ' + opt.label));
            dropdown.appendChild(row);
        }

        btn.addEventListener('click', (e) => {
            e.stopPropagation();
            dropdown.classList.toggle('hidden');
        });

        // Close on outside click
        document.addEventListener('click', () => dropdown.classList.add('hidden'));
        wrapper.addEventListener('click', (e) => e.stopPropagation());

        wrapper.appendChild(btn);
        wrapper.appendChild(dropdown);
        group.appendChild(wrapper);

        return {
            element: wrapper,
            getValue: () => {
                const checked = dropdown.querySelectorAll('input:checked');
                return Array.from(checked).map(cb => parseInt(cb.value));
            },
        };
    }

    renderTypeahead(group, ctrl, options, defaults) {
        const wrapper = document.createElement('div');
        wrapper.className = 'typeahead-wrap';

        const input = document.createElement('input');
        input.type = 'text';
        input.className = 'typeahead-input';
        input.placeholder = 'Type to search...';

        const list = document.createElement('div');
        list.className = 'typeahead-list hidden';

        const tags = document.createElement('div');
        tags.className = 'typeahead-tags';

        const selected = new Set(defaults);

        const renderTags = () => {
            tags.innerHTML = '';
            for (const id of selected) {
                const opt = options.find(o => o.nom_item_id === id);
                if (!opt) continue;
                const tag = document.createElement('span');
                tag.className = 'typeahead-tag';
                tag.innerHTML = `${opt.label} <span class="tag-remove" data-id="${id}">&times;</span>`;
                tag.querySelector('.tag-remove').addEventListener('click', () => {
                    selected.delete(id);
                    renderTags();
                    this.onChange();
                });
                tags.appendChild(tag);
            }
        };

        const showResults = (query) => {
            list.innerHTML = '';
            const q = query.toLowerCase();
            const matches = options
                .filter(o => !selected.has(o.nom_item_id) && o.label.toLowerCase().includes(q))
                .slice(0, 20);

            if (matches.length === 0) {
                list.classList.add('hidden');
                return;
            }

            for (const opt of matches) {
                const item = document.createElement('div');
                item.className = 'typeahead-item';
                item.textContent = opt.label;
                item.addEventListener('click', () => {
                    if (selected.size < 8) {
                        selected.add(opt.nom_item_id);
                        renderTags();
                        input.value = '';
                        list.classList.add('hidden');
                        this.onChange();
                    }
                });
                list.appendChild(item);
            }
            list.classList.remove('hidden');
        };

        input.addEventListener('input', () => showResults(input.value));
        input.addEventListener('focus', () => { if (input.value) showResults(input.value); });
        document.addEventListener('click', () => list.classList.add('hidden'));
        wrapper.addEventListener('click', (e) => e.stopPropagation());

        renderTags();

        wrapper.appendChild(tags);
        wrapper.appendChild(input);
        wrapper.appendChild(list);
        group.appendChild(wrapper);

        return {
            element: wrapper,
            getValue: () => Array.from(selected),
        };
    }

    renderSubgroupSelector(group, ctrl) {
        const subgroups = ctrl.subgroups || [];
        const pillWrap = document.createElement('div');
        pillWrap.className = 'pill-group subgroup-selector';

        let activeIds = subgroups.length > 0 ? subgroups[0].ids : [];
        const pills = [];

        for (const sg of subgroups) {
            const pill = document.createElement('button');
            pill.className = 'pill';
            pill.textContent = sg.label;
            pill.addEventListener('click', () => {
                pills.forEach(p => p.classList.remove('active'));
                pill.classList.add('active');
                activeIds = sg.ids;
                this.onChange();
            });
            pills.push(pill);
            pillWrap.appendChild(pill);
        }

        // Default: activate first sub-group
        if (pills.length > 0) pills[0].classList.add('active');

        group.appendChild(pillWrap);
        return {
            element: pillWrap,
            getValue: () => activeIds,
        };
    }

    // --- Public API ---

    /** Get all control values as { column: [ids] } */
    getValues() {
        const values = {};
        for (const w of this.widgets) {
            const ids = w.getValue();
            if (ids.length > 0) {
                values[w.control.column] = ids;
            }
        }
        return values;
    }

    /** Get period browser reference (if snapshot view) */
    getPeriodBrowser() {
        return this.periodBrowser;
    }

    /** Save current state for tab restoration */
    saveState() {
        const state = {};
        for (const w of this.widgets) {
            state[w.control.column] = w.getValue();
        }
        if (this.periodBrowser) {
            state._periodId = this.periodBrowser.getCurrentPeriodId();
        }
        return state;
    }

    /** Restore saved state */
    restoreState(state) {
        if (!state) return;
        // Restoring widget state requires re-render with saved defaults
        // For simplicity, we just trigger onChange after re-applying
        if (state._periodId && this.periodBrowser) {
            this.periodBrowser.setPeriod(state._periodId);
        }
    }

    destroy() {
        this.container.innerHTML = '';
        this.widgets = [];
        this.periodBrowser = null;
    }
}
