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

        this.activeView = null;      // 'timeline' | 'snapshot' | 'table'
        this.activeChartIdx = 0;     // index into current view's charts[]
        this.viewStates = {};        // saved control states per view
        this.pageFilters = {};       // page-level filters (e.g., unit)
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
            this.profile = profile;
            this.parentCode = this.matrixCode;
            this.parentProfile = profile;

            if (!this.profile) {
                console.warn('No view profile found, falling back to v1 layout');
            }

            // Sub-dataset switching deferred — render bar but don't auto-switch
            // TODO: auto-switch to first sub-dataset once sub-dataset profiles/data are ready

            // Load GeoJSON if geo archetype
            if (this.profile?.archetype === 'geo_time') {
                await loadRomaniaGeoJSON();
            }

            this.renderHeader();
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
        if (m.context_path) {
            breadcrumb.innerHTML = `<a href="/">Home</a><span>›</span>${m.context_path}`;
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
            select.appendChild(el('option', { value: String(opt.nom_item_id) }, opt.label));
        }
        select.addEventListener('change', () => {
            this.pageFilters[unitDim.dim_column_name] = [parseInt(select.value)];
            this.fetchAndRender();
        });
        container.appendChild(select);

        // Set default
        this.pageFilters[unitDim.dim_column_name] = [parseInt(select.value)];
    }

    // --- Sub-dataset bar ---

    async renderSubDatasetBar() {
        const bar = document.getElementById('sub-dataset-bar');
        const subs = this.parentProfile?.sub_datasets;
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

            // Load GeoJSON if needed
            if (this.profile?.archetype === 'geo_time') {
                await loadRomaniaGeoJSON();
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
            const available = view === 'table' || views[view]?.available;
            tab.disabled = !available;
            tab.addEventListener('click', () => {
                if (!tab.disabled) this.switchView(view);
            });
        });
    }

    // --- View switching ---

    switchView(viewName) {
        // Save current state
        if (this.activeView && this.controlsPanel) {
            this.viewStates[this.activeView] = this.controlsPanel.saveState();
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

    // --- Chart selector ---

    renderChartSelector(charts) {
        const container = document.getElementById('chart-selector');
        container.innerHTML = '';
        if (charts.length <= 1 && !(charts[0]?.toggles?.length)) return;

        const TYPE_LABELS = {
            line: 'Line', area: 'Area', area_stacked: 'Stacked Area',
            bar: 'Bar', horizontal_bar: 'H-Bar',
            grouped_bar: 'Grouped', stacked_bar: 'Stacked',
            choropleth: 'Map', population_pyramid: 'Pyramid',
            heatmap: 'Heatmap', bubble: 'Bubble',
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

            // Variant label
            if (chart.variant) {
                const vl = document.createElement('span');
                vl.className = 'variant-label';
                vl.textContent = chart.variant.replace(/^by_/, '').replace(/_/g, ' ');
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
                    const tbtn = this.createChartBtn(
                        TYPE_LABELS[toggle] || toggle,
                        i, toggle
                    );
                    container.appendChild(tbtn);
                }
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
            // Update active states
            document.querySelectorAll('.chart-selector .chart-btn').forEach(b => {
                b.classList.toggle('active',
                    parseInt(b.dataset.chartIdx) === chartIdx && b.dataset.chartType === chartType);
            });
            this.fetchAndRender();
        });

        return btn;
    }

    getActiveChartType() {
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
            const data = await API.getDatasetData(this.matrixCode, filters, 5000);
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
            const limit = chartType === 'choropleth' ? 50000 : 5000;

            const data = await API.getDatasetData(this.matrixCode, filters, limit);

            // Dispose old chart
            if (this.chartInstance) {
                this.chartInstance.dispose();
                this.chartInstance = null;
            }

            const chartEl = document.getElementById('main-chart');
            const chartConfig = this.buildChartConfig();

            this.chartInstance = createChart(chartEl, chartConfig, data, this.metadata);
        } catch (err) {
            document.getElementById('main-chart').innerHTML =
                `<div class="error-msg" style="padding:20px">${err.message}</div>`;
            console.error(err);
        } finally {
            this.showLoading(false);
        }
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

        // Choropleth overrides: include all counties, strip non-geo/non-time
        if (chartType === 'choropleth' && this.profile.dimensions.geo) {
            const geoCol = this.profile.dimensions.geo.column;
            const timeCol = this.profile.dimensions.time?.column;

            // Get county IDs from metadata
            const geoDim = this.metadata.dimensions.find(d => d.dim_column_name === geoCol);
            if (geoDim) {
                const countyIds = geoDim.options
                    .filter(o => o.parsed && o.parsed.geo_level === 'county')
                    .map(o => o.nom_item_id);
                if (countyIds.length > 0) {
                    filters[geoCol] = countyIds;
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

        return filters;
    }

    /**
     * Bridge: translate view profile chart definition into the format
     * that chart-factory's resolveRoles() expects.
     */
    buildChartConfig() {
        const chart = this.getActiveChart();
        const chartType = this.getActiveChartType();
        const dims = this.profile.dimensions;

        return {
            primary_chart: chartType,
            ranked_charts: [{
                chart_type: chartType,
                roles: {
                    x_axis: chart.roles?.x_axis || null,
                    series: chart.roles?.series || null,
                    timeline: (this.activeView === 'timeline')
                        ? (dims.time?.column || chart.roles?.x_axis || null)
                        : null,
                    facet: chart.roles?.facet || null,
                },
            }],
            geo_dim: dims.geo?.column || null,
            time_dim: dims.time?.column || null,
            series_dim: chart.roles?.series || null,
            age_dim: dims.age || null,
            gender_dim: dims.gender || null,
            archetype: this.profile.archetype,
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
