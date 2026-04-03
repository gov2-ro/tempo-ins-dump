/**
 * Dataset Page V2 — Tabbed 4-view controller.
 * Consumes view profiles to drive timeline/snapshot/table views.
 */
class DatasetPageV2 {
    constructor() {
        this.matrixCode = null;
        this.parentCode = null;      // original code from URL (parent)
        this.parentProfile = null;   // parent profile (has sub_datasets list)
        this.metadata = null;
        this.profile = null;
        this.chartInstance = null;
        this.filterPanel = null;
        this.dataTable = null;
        this.controlsPanel = null;

        this.activeView = null;      // 'timeline' | 'snapshot' | 'table' | 'custom'
        this.activeChartIdx = 0;     // index into current view's charts[]
        this.viewStates = {};        // saved control states per view
        this.pageFilters = {};       // page-level filters (e.g., unit)
        this.customState = null;     // { chartType, roles: { x_axis, series } }
    }

    async init() {
        const params = new URLSearchParams(window.location.search);
        this.matrixCode = params.get('code');

        if (!this.matrixCode) {
            document.getElementById('v2-content').innerHTML =
                '<div class="empty-state" style="padding:40px;text-align:center"><h3>No dataset selected</h3><p>Add ?code=ACC101B to the URL</p></div>';
            return;
        }

        this.showLoading(true);

        try {
            // Fetch metadata + view profile in parallel
            const [metadata, profile] = await Promise.all([
                API.getDataset(this.matrixCode),
                API.getViewProfile(this.matrixCode),
            ]);

            this.metadata = metadata;
            this.profile = this.enrichProfile(profile);
            this.parentCode = this.matrixCode;
            this.parentProfile = this.profile;

            // If this is a sub-dataset, load parent's profile for sibling navigation
            if (metadata.is_split && metadata.parent_matrix_code) {
                try {
                    const parentProf = await API.getViewProfile(metadata.parent_matrix_code);
                    if (parentProf) {
                        this.parentProfile = parentProf;
                        this.parentCode = metadata.parent_matrix_code;
                    }
                } catch {}
            }

            if (!this.profile) {
                console.warn('No view profile found, falling back to v1 layout');
            }

            // Load all GeoJSON levels if geo archetype (supports county/region/macroregion)
            if (this.profile?.archetype === 'geo_time') {
                await Promise.all([
                    loadRomaniaGeoJSON('county'),
                    loadRomaniaGeoJSON('region'),
                    loadRomaniaGeoJSON('macroregion'),
                ]);
            }

            this.renderHeader();
            this.initSidebar();
            this.renderSubDatasetBar();
            this.renderPageControls();
            this.renderTabBar();

            // Init data table (reused across views)
            this.dataTable = new DataTable(
                document.getElementById('data-table'),
                document.getElementById('table-footer')
            );

            // Pick initial view
            const views = this.profile?.views || {};
            let initial = 'timeline';
            if (!views.timeline?.available) {
                initial = views.snapshot?.available ? 'snapshot' : 'table';
            }

            this.switchView(initial);
            this.renderFooter();
        } catch (err) {
            document.getElementById('v2-content').innerHTML =
                `<div class="error-msg" style="padding:40px">${err.message}</div>`;
            console.error(err);
        } finally {
            this.showLoading(false);
        }
    }

    // --- Header ---

    renderHeader() {
        const m = this.metadata;
        const breadcrumb = document.getElementById('breadcrumb');
        if (m.context_path && Array.isArray(m.context_path) && m.context_path.length > 0) {
            let html = '<a href="/">Home</a>';
            for (const seg of m.context_path) {
                html += `<span>\u203a</span><a href="/datasets.html?context=${seg.code}">${seg.name}</a>`;
            }
            breadcrumb.innerHTML = html;
        }

        const header = document.getElementById('dataset-header');
        // Always show parent dataset name in header
        const parentName = this.parentProfile?.matrix_name || m.matrix_name;
        header.querySelector('h1').textContent = parentName;

        const badges = header.querySelector('.meta-badges');
        badges.innerHTML = '';

        const p = this.profile || {};
        badges.appendChild(el('span', { className: 'badge badge-primary' }, p.archetype || 'unknown'));

        const timeDim = p.dimensions?.time;
        if (timeDim?.granularity) {
            badges.appendChild(el('span', { className: 'badge badge-muted' }, timeDim.granularity));
        }
        if (timeDim?.year_range) {
            badges.appendChild(el('span', { className: 'badge badge-muted' },
                `${timeDim.year_range[0]}–${timeDim.year_range[1]}`));
        }
        if (p.meta?.row_count) {
            badges.appendChild(el('span', { className: 'badge badge-muted' },
                `${formatNumber(p.meta.row_count, 0)} rows`));
        }
        if (m.ultima_actualizare) {
            badges.appendChild(el('span', { className: 'badge badge-accent' },
                `Updated: ${m.ultima_actualizare}`));
        }
        badges.appendChild(el('span', { className: 'badge badge-muted' }, m.matrix_code));

        // Warnings
        const warningEl = document.getElementById('warning-badges');
        warningEl.innerHTML = '';
        for (const w of (p.warnings || [])) {
            const msg = typeof w === 'string' ? w : (w.message || w.type || JSON.stringify(w));
            const severity = typeof w === 'object' ? (w.severity || 'info')
                : (w.includes('sparse') || w.includes('low_fill') ? 'warn'
                    : w.includes('error') ? 'error' : 'info');
            warningEl.appendChild(el('span', { className: `warning-badge ${severity}` }, msg));
        }
    }

    // --- Page controls (UM selector) ---

    renderPageControls() {
        const container = document.getElementById('page-controls');
        container.innerHTML = '';

        const dims = this.profile?.dimensions;
        if (!dims?.unit?.multi_unit) return;

        const unitDim = this.metadata.dimensions.find(d => d.dim_type === 'unit');
        if (!unitDim || unitDim.options.length <= 1) return;

        const label = document.createElement('label');
        label.textContent = 'Unit of measure:';
        container.appendChild(label);

        const select = document.createElement('select');
        for (const opt of unitDim.options) {
            select.appendChild(el('option', { value: String(optVal(opt)) }, opt.label));
        }
        select.addEventListener('change', () => {
            this.pageFilters[unitDim.dim_column_name] = [select.value];
            this.fetchAndRender();
        });
        container.appendChild(select);

        // Set default
        this.pageFilters[unitDim.dim_column_name] = [select.value];
    }

    // --- Sub-dataset bar ---

    async renderSubDatasetBar() {
        const bar = document.getElementById('sub-dataset-bar');
        // Try view profile first, fall back to API metadata splits
        const subs = this.parentProfile?.sub_datasets
            || (this.metadata.splits?.length > 0
                ? this.metadata.splits.map(s => ({ code: s.matrix_code, label: s.label }))
                : null);
        if (!subs || subs.length === 0) {
            bar.style.display = 'none';
            return;
        }

        // Validate first sub-dataset exists before showing pills
        try { await API.getDataset(subs[0].code); }
        catch { bar.style.display = 'none'; return; }

        bar.style.display = '';
        bar.innerHTML = '';

        const label = document.createElement('span');
        label.className = 'sub-dataset-label';
        label.textContent = 'View by:';
        bar.appendChild(label);

        const pillGroup = document.createElement('div');
        pillGroup.className = 'pill-group';

        for (const sub of subs) {
            const pill = document.createElement('button');
            pill.className = 'pill' + (sub.code === this.matrixCode ? ' active' : '');
            pill.textContent = sub.label;
            pill.addEventListener('click', () => this.switchSubDataset(sub.code));
            pillGroup.appendChild(pill);
        }

        bar.appendChild(pillGroup);
    }

    async switchSubDataset(subCode) {
        if (subCode === this.matrixCode) return;

        this.showLoading(true);
        this.matrixCode = subCode;
        this.viewStates = {};

        try {
            const [subMeta, subProfile] = await Promise.all([
                API.getDataset(subCode),
                API.getViewProfile(subCode),
            ]);
            this.metadata = subMeta;
            this.profile = subProfile;

            // Update active pill
            document.querySelectorAll('#sub-dataset-bar .pill').forEach(p => {
                p.classList.toggle('active',
                    this.parentProfile.sub_datasets.find(s => s.code === subCode)?.label === p.textContent);
            });

            // Load all GeoJSON levels if needed
            if (this.profile?.archetype === 'geo_time') {
                await Promise.all([
                    loadRomaniaGeoJSON('county'),
                    loadRomaniaGeoJSON('region'),
                    loadRomaniaGeoJSON('macroregion'),
                ]);
            }

            this.renderPageControls();
            this.renderTabBar();

            // Re-enter current view (or pick best)
            const views = this.profile?.views || {};
            let view = this.activeView;
            if (view !== 'table' && !views[view]?.available) {
                view = views.timeline?.available ? 'timeline' : 'snapshot';
            }
            this.activeView = null;
            this.switchView(view);
        } catch (err) {
            console.error('Failed to switch sub-dataset:', err);
        } finally {
            this.showLoading(false);
        }
    }

    // --- Tab bar ---

    renderTabBar() {
        const tabBar = document.getElementById('tab-bar');
        const views = this.profile?.views || {};

        tabBar.querySelectorAll('.tab').forEach(tab => {
            const view = tab.dataset.view;
            const available = view === 'table' || view === 'custom' || views[view]?.available;
            tab.disabled = !available;
            tab.addEventListener('click', () => {
                if (!tab.disabled) this.switchView(view);
            });
        });
    }

    // --- Profile enrichment ---

    enrichProfile(profile) {
        const BAR_TOGGLES = ['bar', 'stacked_bar'];
        const cats = profile.dimensions?.categories || [];
        for (const view of Object.values(profile.views || {})) {
            for (const chart of view.charts || []) {
                // Inject bar/stacked_bar toggles on all line/area charts
                if (['line', 'area', 'area_stacked'].includes(chart.chart_type)) {
                    const existing = chart.toggles || [];
                    const toAdd = BAR_TOGGLES.filter(t => !existing.includes(t));
                    if (toAdd.length) chart.toggles = [...existing, ...toAdd];
                }
                // Annotate horizontal_bar charts with stackable dimensions
                if (chart.chart_type === 'horizontal_bar' && cats.length > 0) {
                    chart._stackable_dims = cats.map(c => ({ column: c.column, label: c.label }));
                }
            }
        }
        return profile;
    }

    // --- View switching ---

    switchView(viewName) {
        // Save current state
        if (this.activeView && this.controlsPanel) {
            if (this.activeView === 'custom') {
                this.viewStates['custom'] = {
                    customState: this.customState ? { ...this.customState, roles: { ...this.customState.roles } } : null,
                    controlState: this.controlsPanel.saveState(),
                };
            } else {
                this.viewStates[this.activeView] = this.controlsPanel.saveState();
            }
        }

        this.activeView = viewName;

        // Update tab bar
        document.querySelectorAll('.tab-bar .tab').forEach(tab => {
            tab.classList.toggle('active', tab.dataset.view === viewName);
        });

        // Show/hide chart vs table areas
        const chartView = document.getElementById('chart-view');
        const tableView = document.getElementById('table-view');

        const viewControls = document.getElementById('view-controls');
        const chartSelector = document.getElementById('chart-selector');

        if (viewName === 'table') {
            chartView.style.display = 'none';
            tableView.style.display = 'flex';
            viewControls.style.display = 'none';
            chartSelector.style.display = 'none';
            this.renderTableView();
            return;
        }

        chartView.style.display = '';
        tableView.style.display = 'none';
        viewControls.style.display = '';
        chartSelector.style.display = '';

        // Custom view — user-driven chart building
        if (viewName === 'custom') {
            // Restore saved custom state
            if (this.viewStates['custom']?.customState) {
                this.customState = { ...this.viewStates['custom'].customState, roles: { ...this.viewStates['custom'].customState.roles } };
            }
            this.renderCustomControls();
            // Restore filter state after controls are rendered
            if (this.viewStates['custom']?.controlState && this.controlsPanel) {
                this.controlsPanel.restoreState(this.viewStates['custom'].controlState);
            }
            this.fetchAndRender();
            return;
        }

        // Render view controls
        this.renderViewControls(viewName);

        // Pick primary chart
        const view = this.profile?.views?.[viewName];
        const charts = view?.charts || [];
        const primaryIdx = charts.findIndex(c => c.is_primary);
        this.activeChartIdx = primaryIdx >= 0 ? primaryIdx : 0;

        // Render chart selector
        this.renderChartSelector(charts);

        // Restore saved state
        if (this.viewStates[viewName] && this.controlsPanel) {
            this.controlsPanel.restoreState(this.viewStates[viewName]);
        }

        if (charts.length === 0) {
            document.getElementById('main-chart').innerHTML =
                '<div class="error-msg" style="padding:20px;color:var(--text-light)">No chart available for this view.</div>';
            return;
        }

        this.fetchAndRender();
    }

    // --- View controls ---

    renderViewControls(viewName) {
        const container = document.getElementById('view-controls');
        if (this.controlsPanel) this.controlsPanel.destroy();

        const view = this.profile?.views?.[viewName];
        const controls = view?.controls || [];

        this.controlsPanel = new ViewControlsPanel(
            container,
            controls,
            this.metadata.dimensions,
            () => this.fetchAndRender()
        );
    }

    // --- Custom view ---

    static CUSTOM_CHART_TYPES = [
        { type: 'line',           label: 'Line',    needsSeries: false },
        { type: 'area_stacked',   label: 'Area',    needsSeries: true  },
        { type: 'bar_vertical',   label: 'Bar',     needsSeries: false },
        { type: 'horizontal_bar', label: 'H-Bar',   needsSeries: false },
        { type: 'grouped_bar',    label: 'Grouped', needsSeries: true  },
        { type: 'stacked_bar',    label: 'Stacked', needsSeries: true  },
        { type: 'choropleth',     label: 'Map',     needsSeries: false, requiresGeo: true },
        { type: 'heatmap',        label: 'Heatmap', needsSeries: true,  minOptions: 5 },
        { type: 'bubble',         label: 'Bubble',  needsSeries: true  },
    ];

    getCustomDims() {
        const singletons = this.profile?.dimensions?.singleton_dims || [];
        return this.metadata.dimensions.filter(d => {
            if (singletons.includes(d.dim_column_name)) return false;
            if (d.dim_type === 'unit') return false;
            return d.option_count > 1;
        });
    }

    isChartTypeEligible(chartDef, dims) {
        if (chartDef.requiresGeo && !dims.find(d => d.dim_type === 'geo')) return false;
        if (chartDef.needsSeries && dims.length < 2) return false;
        if (chartDef.minOptions) {
            const qualifying = dims.filter(d => d.option_count >= chartDef.minOptions);
            if (qualifying.length < 2) return false;
        }
        return true;
    }

    initCustomDefaults(dims) {
        const timeDim = dims.find(d => d.dim_type === 'time' && d.option_count >= 3);
        const geoDim = dims.find(d => d.dim_type === 'geo');
        const analysisDims = dims.filter(d => d.dim_type !== 'time' && d.dim_type !== 'geo');

        // Pick best series dim
        const pickSeries = (exclude) => {
            const candidates = dims.filter(d => d.dim_column_name !== exclude);
            const gender = candidates.find(d => d.dim_type === 'gender');
            if (gender) return gender.dim_column_name;
            const residence = candidates.find(d => d.dim_type === 'residence');
            if (residence) return residence.dim_column_name;
            const small = candidates.filter(d => d.option_count <= 8 && d.dim_type !== 'time' && d.dim_type !== 'geo')
                .sort((a, b) => a.option_count - b.option_count);
            if (small.length) return small[0].dim_column_name;
            return null;
        };

        if (timeDim) {
            const series = pickSeries(timeDim.dim_column_name);
            this.customState = { chartType: 'line', roles: { x_axis: timeDim.dim_column_name, series } };
        } else if (geoDim) {
            this.customState = { chartType: 'horizontal_bar', roles: { x_axis: geoDim.dim_column_name, series: null } };
        } else {
            const largest = [...dims].sort((a, b) => b.option_count - a.option_count)[0];
            this.customState = { chartType: 'bar_vertical', roles: { x_axis: largest?.dim_column_name || null, series: null } };
        }
    }

    renderCustomControls() {
        const chartSelectorEl = document.getElementById('chart-selector');
        const viewControlsEl = document.getElementById('view-controls');
        chartSelectorEl.innerHTML = '';
        if (this.controlsPanel) this.controlsPanel.destroy();

        const dims = this.getCustomDims();

        // Initialize defaults on first open
        if (!this.customState) {
            this.initCustomDefaults(dims);
        }

        // Chart type picker
        const typeBar = document.createElement('div');
        typeBar.className = 'custom-chart-type-bar';
        for (const def of DatasetPageV2.CUSTOM_CHART_TYPES) {
            const btn = document.createElement('button');
            btn.className = 'chart-type-btn';
            btn.textContent = def.label;
            const eligible = this.isChartTypeEligible(def, dims);
            btn.disabled = !eligible;
            if (!eligible) btn.title = def.requiresGeo ? 'No geographic dimension' :
                def.minOptions ? 'Needs 2+ dimensions with 5+ options' : 'Needs 2+ dimensions';
            if (def.type === this.customState.chartType) btn.classList.add('active');
            btn.addEventListener('click', () => {
                if (!eligible) return;
                this.customState.chartType = def.type;
                // If chart now requires series and we don't have one, pick one
                if (def.needsSeries && !this.customState.roles.series) {
                    const avail = dims.filter(d => d.dim_column_name !== this.customState.roles.x_axis);
                    if (avail.length) this.customState.roles.series = avail[0].dim_column_name;
                }
                // If choropleth, force x_axis to geo
                if (def.requiresGeo) {
                    const geo = dims.find(d => d.dim_type === 'geo');
                    if (geo) this.customState.roles.x_axis = geo.dim_column_name;
                }
                this.renderCustomControls();
                this.fetchAndRender();
            });
            typeBar.appendChild(btn);
        }
        chartSelectorEl.appendChild(typeBar);

        // Role assignment
        const roleBar = document.createElement('div');
        roleBar.className = 'custom-role-bar';

        const activeDef = DatasetPageV2.CUSTOM_CHART_TYPES.find(d => d.type === this.customState.chartType);
        const showSeries = activeDef ? (activeDef.needsSeries || dims.length > 1) : dims.length > 1;

        // X-Axis dropdown
        const xGroup = document.createElement('div');
        xGroup.className = 'custom-role-group';
        const xLabel = document.createElement('span');
        xLabel.className = 'custom-role-label';
        xLabel.textContent = 'X-Axis';
        const xSelect = document.createElement('select');
        xSelect.className = 'custom-role-select';
        for (const d of dims) {
            const opt = document.createElement('option');
            opt.value = d.dim_column_name;
            opt.textContent = `${d.dim_label} (${d.option_count})`;
            if (d.dim_column_name === this.customState.roles.x_axis) opt.selected = true;
            xSelect.appendChild(opt);
        }
        xSelect.addEventListener('change', () => {
            this.customState.roles.x_axis = xSelect.value;
            // If series is now same as x, clear it
            if (this.customState.roles.series === xSelect.value) {
                this.customState.roles.series = null;
            }
            this.renderCustomControls();
            this.fetchAndRender();
        });
        xGroup.appendChild(xLabel);
        xGroup.appendChild(xSelect);
        roleBar.appendChild(xGroup);

        // Series dropdown
        if (showSeries) {
            const sGroup = document.createElement('div');
            sGroup.className = 'custom-role-group';
            const sLabel = document.createElement('span');
            sLabel.className = 'custom-role-label';
            sLabel.textContent = 'Series';
            const sSelect = document.createElement('select');
            sSelect.className = 'custom-role-select';
            if (!activeDef?.needsSeries) {
                const noneOpt = document.createElement('option');
                noneOpt.value = '';
                noneOpt.textContent = '(none)';
                if (!this.customState.roles.series) noneOpt.selected = true;
                sSelect.appendChild(noneOpt);
            }
            for (const d of dims) {
                if (d.dim_column_name === this.customState.roles.x_axis) continue;
                const opt = document.createElement('option');
                opt.value = d.dim_column_name;
                opt.textContent = `${d.dim_label} (${d.option_count})`;
                if (d.dim_column_name === this.customState.roles.series) opt.selected = true;
                sSelect.appendChild(opt);
            }
            sSelect.addEventListener('change', () => {
                this.customState.roles.series = sSelect.value || null;
                this.renderCustomControls();
                this.fetchAndRender();
            });
            sGroup.appendChild(sLabel);
            sGroup.appendChild(sSelect);
            roleBar.appendChild(sGroup);
        }

        // Warnings
        const seriesDim = dims.find(d => d.dim_column_name === this.customState.roles.series);
        if (seriesDim && seriesDim.option_count > 12) {
            const warn = document.createElement('span');
            warn.className = 'custom-warning';
            warn.textContent = `Series has ${seriesDim.option_count} values (top 12 shown)`;
            roleBar.appendChild(warn);
        }

        chartSelectorEl.appendChild(roleBar);

        // Auto-generate filters for unassigned dims
        this.renderCustomFilters(viewControlsEl, dims);
    }

    renderCustomFilters(container, dims) {
        const assigned = new Set(
            Object.values(this.customState.roles).filter(Boolean)
        );
        const filterDims = dims.filter(d => !assigned.has(d.dim_column_name));

        const controls = filterDims.map(dim => {
            const oc = dim.option_count;
            let type = 'pill_group';
            if (oc > 100) type = 'typeahead_select';
            else if (oc > 25) type = 'single_select';
            else if (oc > 5) type = 'multi_select';
            return {
                type,
                column: dim.dim_column_name,
                label: dim.dim_label,
                scope: 'view',
                default: 'total',
            };
        });

        this.controlsPanel = new ViewControlsPanel(
            container,
            controls,
            this.metadata.dimensions,
            () => this.fetchAndRender()
        );
    }

    buildCustomChartConfig() {
        const ct = this.customState.chartType;
        const roles = this.customState.roles;
        const dims = this.profile?.dimensions || {};
        const timeDim = dims.time?.column || null;
        const xIsTime = roles.x_axis === timeDim;

        return {
            primary_chart: ct,
            ranked_charts: [{
                chart_type: ct,
                roles: {
                    x_axis: roles.x_axis || null,
                    series: roles.series || null,
                    timeline: xIsTime ? roles.x_axis : null,
                    pivot: null,
                    entity: null,
                    facet: null,
                },
            }],
            geo_dim: dims.geo?.column || null,
            time_dim: timeDim,
            series_dim: roles.series || null,
            pivot_dim: null,
            entity_dim: null,
            age_dim: dims.age || null,
            gender_dim: dims.gender || null,
            archetype: this.profile?.archetype,
            max_series: 12,
            multi_unit: dims.unit?.multi_unit || false,
        };
    }

    // --- Chart selector ---

    renderChartSelector(charts) {
        const container = document.getElementById('chart-selector');
        container.innerHTML = '';
        if (charts.length <= 1 && !(charts[0]?.toggles?.length)) return;

        const TYPE_LABELS = {
            line: 'Line', area: 'Area', area_stacked: 'Stacked Area',
            bar: 'Grouped', horizontal_bar: 'H-Bar',
            grouped_bar: 'Grouped', stacked_bar: 'Stacked',
            choropleth: 'Map', population_pyramid: 'Pyramid',
            heatmap: 'Heatmap', bubble: 'Bubble', scatter: 'Scatter',
            small_multiples: 'Small ×',
        };

        for (let i = 0; i < charts.length; i++) {
            const chart = charts[i];
            if (i > 0) {
                // Separator between chart groups
                const sep = document.createElement('span');
                sep.className = 'sep';
                container.appendChild(sep);
            }

            // Variant label — resolve column names to dimension labels
            if (chart.variant) {
                const vl = document.createElement('span');
                vl.className = 'variant-label';
                const dimLabel = (col) => {
                    const cats = this.profile?.dimensions?.categories || [];
                    const d = cats.find(c => c.column === col);
                    return d ? d.label.trim() : col.replace(/_/g, ' ');
                };
                const m = chart.variant.match(/^(.+?)_by_(.+)$/);
                if (m) {
                    vl.textContent = `${dimLabel(m[1])} × ${dimLabel(m[2])}`;
                } else {
                    vl.textContent = chart.variant.replace(/^by_/, '').replace(/_/g, ' ');
                }
                container.appendChild(vl);
            }

            // Main chart button
            const btn = this.createChartBtn(
                TYPE_LABELS[chart.chart_type] || chart.chart_type,
                i, chart.chart_type
            );
            container.appendChild(btn);

            // Toggle variants (e.g., line → area_stacked)
            if (chart.toggles) {
                for (const toggle of chart.toggles) {
                    if (toggle === chart.chart_type) continue; // Skip self-toggle
                    const tbtn = this.createChartBtn(
                        TYPE_LABELS[toggle] || toggle,
                        i, toggle
                    );
                    container.appendChild(tbtn);
                }
            }
        }

        // "Stack by" dropdown for horizontal_bar charts with stackable dims
        const activeChart = charts[this.activeChartIdx];
        if (activeChart?._stackable_dims?.length > 0 &&
            this.getActiveChartType() === 'horizontal_bar') {
            const defaultDim = this._stackByDim !== undefined
                ? this._stackByDim
                : (activeChart.roles?.series || null);

            const sep = document.createElement('span');
            sep.className = 'sep';
            container.appendChild(sep);

            const lbl = document.createElement('span');
            lbl.className = 'variant-label';
            lbl.textContent = 'STACK BY';
            container.appendChild(lbl);

            const sel = document.createElement('select');
            sel.className = 'stack-by-select';
            const noneOpt = document.createElement('option');
            noneOpt.value = '';
            noneOpt.textContent = '(none)';
            if (!defaultDim) noneOpt.selected = true;
            sel.appendChild(noneOpt);

            for (const dim of activeChart._stackable_dims) {
                const opt = document.createElement('option');
                opt.value = dim.column;
                opt.textContent = dim.label;
                if (dim.column === defaultDim) opt.selected = true;
                sel.appendChild(opt);
            }
            sel.addEventListener('change', () => {
                this._stackByDim = sel.value || null;
                this.fetchAndRender();
            });
            container.appendChild(sel);
        }

        // Scatter axis selectors — two dropdowns to pick pivot categories for X and Y
        if (this.getActiveChartType() === 'scatter') {
            const pivotCol = activeChart?.roles?.pivot;
            const pivotMeta = pivotCol
                ? this.metadata.dimensions.find(d => d.dim_column_name === pivotCol)
                : null;
            if (pivotMeta && pivotMeta.options && pivotMeta.options.length >= 2) {
                const opts = pivotMeta.options;
                const currentX = this._scatterAxes?.x ?? optVal(opts[0]);
                const currentY = this._scatterAxes?.y ?? optVal(opts[Math.min(1, opts.length - 1)]);
                // Initialize defaults if not set
                if (!this._scatterAxes) {
                    this._scatterAxes = { x: currentX, y: currentY };
                }

                const sep = document.createElement('span');
                sep.className = 'sep';
                container.appendChild(sep);

                const makeSelect = (label, current, onChange) => {
                    const wrap = document.createElement('span');
                    wrap.style.cssText = 'display:inline-flex;align-items:center;gap:4px;margin-right:8px;';
                    const lbl = document.createElement('span');
                    lbl.textContent = label;
                    lbl.style.cssText = 'font-size:12px;color:#666;';
                    const sel = document.createElement('select');
                    sel.className = 'chart-btn';
                    for (const o of opts) {
                        const option = document.createElement('option');
                        option.value = optVal(o);
                        option.textContent = o.label;
                        if (String(optVal(o)) === String(current)) option.selected = true;
                        sel.appendChild(option);
                    }
                    sel.addEventListener('change', () => onChange(sel.value));
                    wrap.appendChild(lbl);
                    wrap.appendChild(sel);
                    return wrap;
                };

                container.appendChild(makeSelect('X:', currentX, v => {
                    this._scatterAxes = { ...this._scatterAxes, x: v };
                    this.fetchAndRender();
                }));
                container.appendChild(makeSelect('Y:', currentY, v => {
                    this._scatterAxes = { ...this._scatterAxes, y: v };
                    this.fetchAndRender();
                }));
            }
        }

        // Dimension pair toggle for bubble chart
        if (activeChart?.dimension_pair_toggle && this.getActiveChartType() === 'bubble') {
            const cats = (this.profile.dimensions.categories || [])
                .filter(d => d.option_count >= 3);
            if (cats.length > 2) {
                const sep = document.createElement('span');
                sep.className = 'sep';
                container.appendChild(sep);

                const sel = document.createElement('select');
                sel.className = 'chart-btn';
                const currentX = this._bubbleRoles?.x_axis || activeChart.roles?.x_axis;
                const currentS = this._bubbleRoles?.series || activeChart.roles?.series;
                for (let a = 0; a < cats.length; a++) {
                    for (let b = a + 1; b < cats.length; b++) {
                        const opt = document.createElement('option');
                        opt.value = `${cats[a].column}|${cats[b].column}`;
                        opt.textContent = `${cats[a].label.trim()} × ${cats[b].label.trim()}`;
                        if (cats[a].column === currentX && cats[b].column === currentS) opt.selected = true;
                        if (cats[b].column === currentX && cats[a].column === currentS) opt.selected = true;
                        sel.appendChild(opt);
                    }
                }
                sel.addEventListener('change', () => {
                    const [x, s] = sel.value.split('|');
                    this._bubbleRoles = { x_axis: x, series: s };
                    this.fetchAndRender();
                });
                container.appendChild(sel);
            }
        }
    }

    createChartBtn(label, chartIdx, chartType) {
        const btn = document.createElement('button');
        btn.className = 'chart-btn';
        btn.textContent = label;
        btn.dataset.chartIdx = chartIdx;
        btn.dataset.chartType = chartType;

        // Active state
        if (chartIdx === this.activeChartIdx && chartType === this.getActiveChartType()) {
            btn.classList.add('active');
        }

        btn.addEventListener('click', () => {
            this.activeChartIdx = chartIdx;
            this._toggleType = chartType;
            // Re-render chart selector to show/hide stack-by dropdown
            const view = this.profile?.views?.[this.activeView];
            this.renderChartSelector(view?.charts || []);
            this.fetchAndRender();
        });

        return btn;
    }

    getActiveChartType() {
        if (this.activeView === 'custom' && this.customState) {
            return this.customState.chartType;
        }
        const view = this.profile?.views?.[this.activeView];
        const charts = view?.charts || [];
        const chart = charts[this.activeChartIdx];
        // If a toggle variant was selected, use that
        if (this._toggleType) return this._toggleType;
        return chart?.chart_type || 'line';
    }

    getActiveChart() {
        const view = this.profile?.views?.[this.activeView];
        const charts = view?.charts || [];
        return charts[this.activeChartIdx] || charts[0];
    }

    // --- Table view ---

    renderTableView() {
        this.fetchTableData();
    }

    async fetchTableData() {
        this.showLoading(true);
        try {
            const filters = this.buildFilters();
            const data = await API.getDatasetData(this.matrixCode, filters, 50000);
            this.dataTable.update(data, this.metadata);
        } catch (err) {
            document.getElementById('data-table').innerHTML =
                `<div class="error-msg" style="padding:20px">${err.message}</div>`;
            console.error('Table fetch error:', err);
        } finally {
            this.showLoading(false);
        }
    }

    // --- Data fetch & render ---

    async fetchAndRender() {
        if (this.activeView === 'table') return;

        this.showLoading(true);

        try {
            const filters = this.buildFilters();
            const chartType = this.getActiveChartType();
            const limit = 50000;

            const groupBy = this.computeGroupBy();
            const data = await API.getDatasetData(this.matrixCode, filters, limit, { groupBy });

            // Dispose old chart
            if (this.chartInstance) {
                this.chartInstance.dispose();
                this.chartInstance = null;
            }

            const chartEl = document.getElementById('main-chart');
            const chartConfig = this.buildChartConfig();

            this.chartInstance = await createChart(chartEl, chartConfig, data, this.metadata);
        } catch (err) {
            document.getElementById('main-chart').innerHTML =
                `<div class="error-msg" style="padding:20px">${err.message}</div>`;
            console.error(err);
        } finally {
            this.showLoading(false);
        }
    }

    computeGroupBy() {
        if (this.activeView === 'table') return null;

        const chartConfig = this.buildChartConfig();
        const roles = resolveRoles(chartConfig);

        const keepDims = new Set();
        if (roles.time_dim)   keepDims.add(roles.time_dim);
        if (roles.series_dim) keepDims.add(roles.series_dim);
        if (roles.geo_dim)    keepDims.add(roles.geo_dim);
        if (roles.x_axis_dim) keepDims.add(roles.x_axis_dim);
        if (roles.age_dim)    keepDims.add(roles.age_dim);
        if (roles.gender_dim) keepDims.add(roles.gender_dim);
        if (roles.facet_dim)  keepDims.add(roles.facet_dim);
        if (roles.pivot_dim)  keepDims.add(roles.pivot_dim);
        if (roles.entity_dim) keepDims.add(roles.entity_dim);

        // Always keep UNIT_MEASURE if present (avoid summing across units)
        const allCols = this.metadata.dimensions.map(d => d.dim_column_name);
        if (allCols.includes('UNIT_MEASURE')) keepDims.add('UNIT_MEASURE');

        return keepDims.size > 0 ? [...keepDims] : null;
    }

    buildFilters() {
        let filters = { ...this.pageFilters };

        // Add view control values
        if (this.controlsPanel) {
            const vals = this.controlsPanel.getValues();
            Object.assign(filters, vals);
        }

        // Snapshot: add period filter
        if (this.activeView === 'snapshot') {
            const pb = this.controlsPanel?.getPeriodBrowser();
            if (pb) {
                const timeCol = this.profile.dimensions.time?.column;
                if (timeCol) {
                    filters[timeCol] = [pb.getCurrentPeriodId()];
                }
            }
        }

        const chartType = this.getActiveChartType();

        // Choropleth overrides: include all geo features for the detected level
        if (chartType === 'choropleth' && this.profile.dimensions.geo) {
            const geoCol = this.profile.dimensions.geo.column;
            const timeCol = this.profile.dimensions.time?.column;

            // Detect actual geo level from options, then include all IDs for that level
            const geoDim = this.metadata.dimensions.find(d => d.dim_column_name === geoCol);
            if (geoDim) {
                const levelCounts = {};
                for (const o of geoDim.options) {
                    const lvl = o.parsed?.geo_level;
                    if (lvl) levelCounts[lvl] = (levelCounts[lvl] || 0) + 1;
                }
                const targetLevel = levelCounts['county'] > 0 ? 'county'
                    : levelCounts['region'] > 0 ? 'region'
                    : levelCounts['macroregion'] > 0 ? 'macroregion'
                    : 'county';
                const geoIds = geoDim.options
                    .filter(o => o.parsed?.geo_level === targetLevel)
                    .map(o => optVal(o));
                if (geoIds.length > 0) {
                    filters[geoCol] = geoIds;
                }
            }

            // Remove non-geo, non-time, non-unit dimension filters
            const unitCol = this.profile.dimensions.unit?.column;
            for (const dim of this.metadata.dimensions) {
                const col = dim.dim_column_name;
                if (col === geoCol || col === timeCol) continue;
                if (col === unitCol) continue;
                delete filters[col];
            }
        }

        // Population pyramid needs ALL ages and ALL genders
        if (chartType === 'population_pyramid') {
            const ageDim = this.profile.dimensions.age;
            const genderDim = this.profile.dimensions.gender;
            if (ageDim) delete filters[ageDim];
            if (genderDim) delete filters[genderDim];
        }

        // When stacking by a dimension, remove it from filters (need all values)
        const stackDim = (chartType === 'horizontal_bar' && this._stackByDim !== undefined)
            ? this._stackByDim : null;
        if (stackDim && filters[stackDim]) {
            delete filters[stackDim];
        }

        return filters;
    }

    /**
     * Bridge: translate view profile chart definition into the format
     * that chart-factory's resolveRoles() expects.
     */
    buildChartConfig() {
        if (this.activeView === 'custom' && this.customState) {
            return this.buildCustomChartConfig();
        }

        const chart = this.getActiveChart();
        const chartType = this.getActiveChartType();
        const dims = this.profile.dimensions;

        // Stack-by override for h-bar: replaces both roles.series and series_dim
        const effectiveSeries = (chartType === 'horizontal_bar' && this._stackByDim !== undefined)
            ? this._stackByDim
            : (chart?.roles?.series || null);

        // Bubble dim-pair override
        const bubbleX = (chartType === 'bubble' && this._bubbleRoles)
            ? this._bubbleRoles.x_axis : null;
        const bubbleS = (chartType === 'bubble' && this._bubbleRoles)
            ? this._bubbleRoles.series : null;

        return {
            primary_chart: chartType,
            ranked_charts: [{
                chart_type: chartType,
                roles: {
                    x_axis: bubbleX || chart?.roles?.x_axis || null,
                    series: bubbleS || effectiveSeries,
                    pivot: chart?.roles?.pivot || null,
                    entity: chart?.roles?.entity || null,
                    timeline: (this.activeView === 'timeline')
                        ? (dims.time?.column || chart?.roles?.x_axis || null)
                        : null,
                    facet: chart?.roles?.facet || null,
                },
            }],
            geo_dim: dims.geo?.column || null,
            time_dim: dims.time?.column || null,
            series_dim: bubbleS || effectiveSeries,
            pivot_dim: chart?.roles?.pivot || null,
            entity_dim: chart?.roles?.entity || null,
            x_category: (chartType === 'scatter' && this._scatterAxes) ? this._scatterAxes.x : null,
            y_category: (chartType === 'scatter' && this._scatterAxes) ? this._scatterAxes.y : null,
            age_dim: dims.age || null,
            gender_dim: dims.gender || null,
            archetype: this.profile.archetype,
            max_series: chart?.max_series || null,
            // Legacy compat fields
            multi_unit: dims.unit?.multi_unit || false,
        };
    }

    // --- Footer ---

    renderFooter() {
        const m = this.metadata;
        const footer = document.getElementById('dataset-footer');
        if (!footer) return;

        let html = '';
        if (m.definitie) html += `<details><summary>Definition</summary><p>${m.definitie}</p></details>`;
        if (m.metodologie) html += `<details><summary>Methodology</summary><p>${m.metodologie}</p></details>`;
        if (m.observatii) html += `<details><summary>Notes</summary><p>${m.observatii}</p></details>`;
        footer.innerHTML = html;
    }

    // --- Sidebar ---

    initSidebar() {
        const toggle = document.getElementById('sidebar-toggle');
        const sidebar = document.getElementById('dataset-sidebar');
        const close = document.getElementById('sidebar-close');

        toggle?.addEventListener('click', () => {
            const opening = sidebar.classList.contains('hidden');
            sidebar.classList.toggle('hidden');
            toggle.classList.toggle('sidebar-open');
            if (opening && !this._sidebarLoaded) {
                this.renderSidebar();
                this._sidebarLoaded = true;
            }
            sessionStorage.setItem('sidebarOpen', opening ? '1' : '');
        });
        close?.addEventListener('click', () => {
            sidebar.classList.add('hidden');
            toggle.classList.remove('sidebar-open');
            sessionStorage.setItem('sidebarOpen', '');
        });

        // Auto-open if was open on previous page
        if (sessionStorage.getItem('sidebarOpen') === '1') {
            sidebar.classList.remove('hidden');
            toggle.classList.add('sidebar-open');
            this.renderSidebar();
            this._sidebarLoaded = true;
        }
    }

    async renderSidebar() {
        const tree = document.getElementById('sidebar-tree');
        if (!tree) return;

        tree.innerHTML = '<div style="padding:12px;font-size:12px;color:#999">Loading...</div>';

        try {
            const data = await API.getCategories();
            tree.innerHTML = '';

            const currentContext = this.metadata.context_code;
            const ancestors = new Set(
                (this.metadata.context_path || []).map(s => s.code)
            );

            for (const root of data.tree) {
                // L1: section header
                const rootEl = document.createElement('div');
                rootEl.className = 'cat-item cat-section';
                rootEl.dataset.level = '1';
                rootEl.textContent = root.name;
                tree.appendChild(rootEl);

                for (const child of root.children) {
                    const isAncestor = ancestors.has(child.code);
                    const hasChildren = child.children && child.children.length > 0;

                    // L2: category row
                    const item = document.createElement('a');
                    item.className = 'cat-item' + (isAncestor ? ' expanded' : '');
                    item.dataset.level = '2';
                    item.dataset.code = child.code;
                    item.href = `/datasets.html?context=${child.code}`;

                    // L3 children container (created before arrow handler needs it)
                    let childWrap = null;
                    if (hasChildren) {
                        childWrap = document.createElement('div');
                        childWrap.className = 'cat-children' + (isAncestor ? '' : ' collapsed');

                        const arrow = document.createElement('span');
                        arrow.className = 'cat-arrow';
                        arrow.textContent = isAncestor ? '\u25be' : '\u25b8';
                        arrow.addEventListener('click', (e) => {
                            e.preventDefault();
                            e.stopPropagation();
                            const expanded = childWrap.classList.toggle('collapsed');
                            arrow.textContent = expanded ? '\u25b8' : '\u25be';
                        });
                        item.appendChild(arrow);
                    }

                    const nameSpan = document.createElement('span');
                    nameSpan.textContent = child.name;
                    item.appendChild(nameSpan);

                    const count = document.createElement('span');
                    count.className = 'cat-count';
                    count.textContent = child.total_datasets;
                    item.appendChild(count);

                    tree.appendChild(item);

                    // Append L3 children
                    if (hasChildren && childWrap) {
                        for (const gc of child.children) {
                            const isActiveL3 = String(gc.code) === String(currentContext);
                            const gcItem = document.createElement('a');
                            gcItem.className = 'cat-item' + (isActiveL3 ? ' active' : '');
                            gcItem.dataset.level = '3';

                            const gcName = document.createElement('span');
                            gcName.textContent = gc.name;
                            gcItem.appendChild(gcName);

                            const gcCount = document.createElement('span');
                            gcCount.className = 'cat-count';
                            gcCount.textContent = gc.dataset_count;
                            gcItem.appendChild(gcCount);

                            childWrap.appendChild(gcItem);

                            if (isActiveL3) {
                                // Active L3: don't link away, expand inline with datasets
                                gcItem.href = 'javascript:void(0)';

                                const datasetWrap = document.createElement('div');
                                datasetWrap.className = 'cat-children cat-datasets';
                                datasetWrap.innerHTML = '<div class="cat-loading">Loading datasets...</div>';
                                childWrap.appendChild(datasetWrap);

                                API.getDatasets({ context: gc.code, limit: 200, sort: 'name' }).then(result => {
                                    datasetWrap.innerHTML = '';
                                    const datasets = result.datasets || [];
                                    for (const ds of datasets) {
                                        if (ds.is_split) continue;
                                        const isCurrent = ds.matrix_code === this.matrixCode
                                            || ds.matrix_code === (this.metadata.parent_matrix_code || '');
                                        const dsItem = document.createElement('a');
                                        dsItem.className = 'cat-item cat-dataset-item' + (isCurrent ? ' active' : '');
                                        dsItem.dataset.level = '4';
                                        dsItem.href = `/dataset.html?code=${ds.matrix_code}`;
                                        dsItem.textContent = ds.matrix_name;
                                        dsItem.addEventListener('click', () => {
                                            sessionStorage.setItem('sidebarOpen', '1');
                                        });
                                        datasetWrap.appendChild(dsItem);
                                    }
                                    const activeDsItem = datasetWrap.querySelector('.cat-dataset-item.active');
                                    if (activeDsItem) activeDsItem.scrollIntoView({ block: 'center', behavior: 'smooth' });
                                }).catch(err => {
                                    datasetWrap.innerHTML = '<div class="cat-loading" style="color:#c00">Failed to load</div>';
                                    console.error('Failed to load sidebar datasets', err);
                                });
                            } else {
                                gcItem.href = `/datasets.html?context=${gc.code}`;
                            }
                        }
                        tree.appendChild(childWrap);
                    }
                }
            }

            // Scroll active item into view
            const active = tree.querySelector('.cat-item.active');
            if (active) active.scrollIntoView({ block: 'center', behavior: 'smooth' });

        } catch (err) {
            tree.innerHTML = '<div style="padding:12px;font-size:12px;color:#c00">Failed to load categories</div>';
            console.error('Sidebar load failed', err);
        }
    }

    showLoading(show) {
        const overlay = document.getElementById('loading-overlay');
        if (overlay) overlay.style.display = show ? 'flex' : 'none';
    }
}

// Resize chart on window resize
window.addEventListener('resize', () => {
    if (window._datasetPageV2?.chartInstance) {
        window._datasetPageV2.chartInstance.resize();
    }
});

// Init on DOM ready
document.addEventListener('DOMContentLoaded', () => {
    window._datasetPageV2 = new DatasetPageV2();
    window._datasetPageV2.init();
});
