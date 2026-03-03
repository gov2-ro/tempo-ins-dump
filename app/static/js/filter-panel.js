/**
 * Dynamic filter panel — generates controls from dimension metadata
 */
class FilterPanel {
    constructor(container, dimensions, profile, onChange) {
        this.container = container;
        this.dimensions = dimensions;
        this.profile = profile;
        this.onChange = onChange;
        this.filters = {};
        this._suppressCallbacks = true;  // Don't fire onChange during initial render
        this.render();
        this._suppressCallbacks = false;
    }

    render() {
        this.container.innerHTML = '';

        for (const dim of this.dimensions) {
            // Skip single-option unit dimensions (auto-applied)
            if (dim.dim_type === 'unit' && dim.option_count <= 1) continue;

            const section = el('div', { className: 'filter-section' });
            const header = el('h4', {},
                dim.dim_label,
                el('span', { className: 'count' }, `(${dim.option_count})`)
            );
            section.appendChild(header);

            if (dim.dim_type === 'time') {
                this._renderTimeFilter(section, dim);
            } else if (dim.dim_type === 'gender') {
                this._renderRadioFilter(section, dim);
            } else if (dim.dim_type === 'residence') {
                this._renderRadioFilter(section, dim);
            } else if (dim.dim_type === 'geo') {
                this._renderGeoFilter(section, dim);
            } else {
                this._renderCheckboxFilter(section, dim);
            }

            this.container.appendChild(section);
        }
    }

    _renderTimeFilter(section, dim) {
        const years = dim.options
            .filter(o => o.parsed && o.parsed.year)
            .map(o => ({ id: o.nom_item_id, year: o.parsed.year }))
            .sort((a, b) => a.year - b.year);

        if (years.length === 0) {
            this._renderCheckboxFilter(section, dim);
            return;
        }

        const minYear = years[0].year;
        const maxYear = years[years.length - 1].year;

        const slider = el('div', { className: 'range-slider' });
        const labels = el('div', { className: 'range-labels' },
            el('span', {}, String(minYear)),
            el('span', {}, String(maxYear))
        );
        slider.appendChild(labels);

        const inputs = el('div', { className: 'range-inputs' });
        const inputMin = el('input', {
            type: 'number', min: minYear, max: maxYear, value: minYear,
            title: 'Start year'
        });
        const inputMax = el('input', {
            type: 'number', min: minYear, max: maxYear, value: maxYear,
            title: 'End year'
        });

        const applyTimeFilter = () => {
            const from = parseInt(inputMin.value) || minYear;
            const to = parseInt(inputMax.value) || maxYear;
            const selected = years
                .filter(y => y.year >= from && y.year <= to)
                .map(y => y.id);
            if (selected.length < years.length) {
                this.filters[dim.dim_column_name] = selected;
            } else {
                delete this.filters[dim.dim_column_name];
            }
            this.onChange(this.getFilters());
        };

        inputMin.addEventListener('change', applyTimeFilter);
        inputMax.addEventListener('change', applyTimeFilter);
        inputs.appendChild(inputMin);
        inputs.appendChild(inputMax);
        slider.appendChild(inputs);
        section.appendChild(slider);
    }

    _renderRadioFilter(section, dim) {
        const group = el('div', { className: 'filter-checkboxes' });
        const name = `radio_${dim.dim_column_name}`;

        // Add "All" option
        const allLabel = el('label', {},
            el('input', { type: 'radio', name, value: '', checked: 'true' }),
            'All'
        );
        allLabel.querySelector('input').addEventListener('change', () => {
            delete this.filters[dim.dim_column_name];
            this.onChange(this.getFilters());
        });
        group.appendChild(allLabel);

        for (const opt of dim.options) {
            const label = el('label', {},
                el('input', { type: 'radio', name, value: String(opt.nom_item_id) }),
                opt.label
            );
            label.querySelector('input').addEventListener('change', (e) => {
                this.filters[dim.dim_column_name] = [parseInt(e.target.value)];
                this.onChange(this.getFilters());
            });
            group.appendChild(label);
        }
        section.appendChild(group);
    }

    _renderGeoFilter(section, dim) {
        const group = el('div', { className: 'filter-checkboxes' });

        // Group by geo_level
        const levels = { national: [], macroregion: [], region: [], county: [], other: [] };
        for (const opt of dim.options) {
            const level = (opt.parsed && opt.parsed.geo_level) || 'other';
            (levels[level] || levels.other).push(opt);
        }

        // For line chart fallback of geo_time, default to macroregion level to avoid 56 lines
        const hasCounties = levels.county.length > 10;
        const defaultLevels = hasCounties
            ? new Set(['national', 'macroregion'])
            : null;  // null = check all

        // Add select controls
        const controls = el('div', { className: 'select-controls' });
        const selAll = el('a', {}, 'All');
        selAll.addEventListener('click', () => {
            group.querySelectorAll('input[type="checkbox"]').forEach(cb => cb.checked = true);
            delete this.filters[dim.dim_column_name];
            this.onChange(this.getFilters());
        });
        const selNone = el('a', {}, 'None');
        selNone.addEventListener('click', () => {
            group.querySelectorAll('input[type="checkbox"]').forEach(cb => cb.checked = false);
            this._applyCheckboxFilter(dim, group);
        });
        controls.appendChild(selAll);
        controls.appendChild(selNone);
        section.appendChild(controls);

        // Render by level
        for (const [level, opts] of Object.entries(levels)) {
            for (const opt of opts) {
                const cssClass = `geo-${level}`;
                const checked = defaultLevels ? defaultLevels.has(level) : true;
                const label = el('label', { className: cssClass },
                    el('input', {
                        type: 'checkbox',
                        value: String(opt.nom_item_id),
                        ...(checked ? { checked: 'true' } : {}),
                    }),
                    opt.label
                );
                label.querySelector('input').addEventListener('change', () => {
                    this._applyCheckboxFilter(dim, group);
                });
                group.appendChild(label);
            }
        }
        section.appendChild(group);

        // Apply initial filter if we limited the default geo selection
        if (defaultLevels) {
            this._applyCheckboxFilter(dim, group);
        }
    }

    _renderCheckboxFilter(section, dim) {
        // Search box for large option sets
        if (dim.option_count > 15) {
            const search = el('input', {
                className: 'filter-search',
                type: 'text',
                placeholder: `Search ${dim.dim_label}...`,
            });
            search.addEventListener('input', (e) => {
                const q = e.target.value.toLowerCase();
                section.querySelectorAll('.filter-checkboxes label').forEach(lbl => {
                    lbl.style.display = lbl.textContent.toLowerCase().includes(q) ? '' : 'none';
                });
            });
            section.appendChild(search);
        }

        const controls = el('div', { className: 'select-controls' });
        const group = el('div', { className: 'filter-checkboxes' });

        const selAll = el('a', {}, 'All');
        selAll.addEventListener('click', () => {
            group.querySelectorAll('input[type="checkbox"]').forEach(cb => cb.checked = true);
            delete this.filters[dim.dim_column_name];
            this.onChange(this.getFilters());
        });
        const selNone = el('a', {}, 'None');
        selNone.addEventListener('click', () => {
            group.querySelectorAll('input[type="checkbox"]').forEach(cb => cb.checked = false);
            this._applyCheckboxFilter(dim, group);
        });
        controls.appendChild(selAll);
        controls.appendChild(selNone);
        section.appendChild(controls);

        // Default: select first 5 for indicator dims with many options
        const defaultLimit = (dim.dim_type === 'indicator' && dim.option_count > 10) ? 5 : dim.option_count;

        for (let i = 0; i < dim.options.length; i++) {
            const opt = dim.options[i];
            const checked = i < defaultLimit;
            const label = el('label', {},
                el('input', {
                    type: 'checkbox',
                    value: String(opt.nom_item_id),
                    ...(checked ? { checked: 'true' } : {}),
                }),
                opt.label
            );
            label.querySelector('input').addEventListener('change', () => {
                this._applyCheckboxFilter(dim, group);
            });
            group.appendChild(label);
        }

        section.appendChild(group);

        // Apply initial filter if we limited defaults
        if (defaultLimit < dim.option_count) {
            this._applyCheckboxFilter(dim, group);
        }
    }

    _applyCheckboxFilter(dim, group) {
        const checked = [...group.querySelectorAll('input:checked')].map(cb => parseInt(cb.value));
        if (checked.length === 0 || checked.length === dim.option_count) {
            delete this.filters[dim.dim_column_name];
        } else {
            this.filters[dim.dim_column_name] = checked;
        }
        if (!this._suppressCallbacks) this.onChange(this.getFilters());
    }

    getFilters() {
        return { ...this.filters };
    }
}
