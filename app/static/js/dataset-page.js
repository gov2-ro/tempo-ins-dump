/**
 * Dataset page controller — orchestrates the full dataset view
 */
class DatasetPage {
    constructor() {
        this.matrixCode = null;
        this.metadata = null;
        this.chartInstance = null;
        this.filterPanel = null;
        this.dataTable = null;
        this.currentFilters = {};
        this.currentChartType = null;
    }

    async init() {
        // Parse matrix code from URL
        const params = new URLSearchParams(window.location.search);
        this.matrixCode = params.get('code');

        if (!this.matrixCode) {
            document.getElementById('dataset-content').innerHTML =
                '<div class="empty-state"><h3>No dataset selected</h3><p>Add ?code=ACC101B to the URL</p></div>';
            return;
        }

        this.showLoading(true);

        try {
            // Fetch metadata
            this.metadata = await API.getDataset(this.matrixCode);

            // Render UI
            this.renderHeader();

            // Load GeoJSON if this is a geo dataset
            if (this.metadata.chart_config.archetype === 'geo_time') {
                await loadRomaniaGeoJSON();
            }

            // Set initial chart type BEFORE toolbar render
            this.currentChartType = this.metadata.chart_config.primary_chart;
            // For choropleth without geo data, fall back to line
            if (this.currentChartType === 'choropleth' && !window._geoDataLoaded) {
                this.currentChartType = 'line';
            }

            this.renderToolbar();

            // Init filter panel (callbacks suppressed during construction)
            this.filterPanel = new FilterPanel(
                document.getElementById('filter-panel'),
                this.metadata.dimensions,
                this.metadata.profile,
                (filters) => this.onFiltersChanged(filters)
            );

            // Init data table
            this.dataTable = new DataTable(
                document.getElementById('data-table'),
                document.getElementById('table-footer')
            );

            // Merge filter panel defaults with any pre-set filters (e.g., unit from toolbar)
            this.currentFilters = { ...this.currentFilters, ...this.filterPanel.getFilters() };

            // Single initial fetch
            await this.fetchAndRender();

            this.renderFooter();
        } catch (err) {
            document.getElementById('dataset-content').innerHTML =
                `<div class="error-msg">Failed to load dataset: ${err.message}</div>`;
            console.error(err);
        } finally {
            this.showLoading(false);
        }
    }

    renderHeader() {
        const m = this.metadata;
        const header = document.getElementById('dataset-header');

        // Breadcrumb
        const breadcrumb = document.getElementById('breadcrumb');
        if (m.context_path) {
            breadcrumb.innerHTML = `<a href="/">Home</a><span>›</span>${m.context_path}`;
        }

        // Title
        header.querySelector('h1').textContent = m.matrix_name;

        // Badges
        const badges = header.querySelector('.meta-badges');
        badges.innerHTML = '';

        const config = m.chart_config;
        badges.appendChild(el('span', { className: 'badge badge-primary' }, config.archetype));

        if (m.profile.time_granularity) {
            badges.appendChild(el('span', { className: 'badge badge-muted' }, m.profile.time_granularity));
        }
        if (m.profile.time_year_min && m.profile.time_year_max) {
            badges.appendChild(el('span', { className: 'badge badge-muted' },
                `${m.profile.time_year_min}–${m.profile.time_year_max}`));
        }
        if (m.row_count) {
            badges.appendChild(el('span', { className: 'badge badge-muted' },
                `${formatNumber(m.row_count, 0)} rows`));
        }
        if (m.ultima_actualizare) {
            badges.appendChild(el('span', { className: 'badge badge-accent' },
                `Updated: ${m.ultima_actualizare}`));
        }

        // Matrix code
        badges.appendChild(el('span', { className: 'badge badge-muted' }, m.matrix_code));
    }

    renderToolbar() {
        const config = this.metadata.chart_config;
        const toolbar = document.getElementById('toolbar');

        // Chart type buttons
        const chartTypes = toolbar.querySelector('.chart-types');
        chartTypes.innerHTML = '';

        const typeLabels = {
            line: 'Line', area: 'Area', bar: 'Bar', choropleth: 'Map',
            grouped_bar: 'Grouped', table: 'Table',
        };

        for (const type of (config.supports || ['line', 'table'])) {
            const btn = el('button', {
                className: `btn ${type === this.currentChartType ? 'active' : ''}`,
                'data-chart-type': type,
            }, typeLabels[type] || type);
            btn.dataset.chartType = type;
            btn.addEventListener('click', () => this.switchChartType(type));
            chartTypes.appendChild(btn);
        }

        // Unit selector for multi-unit datasets
        const unitSel = toolbar.querySelector('.unit-selector');
        if (config.multi_unit && config.unit_types.length > 1) {
            const unitDim = this.metadata.dimensions.find(d => d.dim_type === 'unit');
            if (unitDim) {
                const select = el('select');
                for (const opt of unitDim.options) {
                    select.appendChild(el('option', { value: String(opt.nom_item_id) }, opt.label));
                }
                select.addEventListener('change', () => {
                    this.currentFilters[unitDim.dim_column_name] = [parseInt(select.value)];
                    this.fetchAndRender();
                });
                unitSel.innerHTML = '<label style="font-size:12px;margin-right:4px">Unit:</label>';
                unitSel.appendChild(select);

                // Apply first unit as default filter
                this.currentFilters[unitDim.dim_column_name] = [parseInt(select.value)];
            }
        }
    }

    renderFooter() {
        const m = this.metadata;
        const footer = document.getElementById('dataset-footer');
        if (!footer) return;

        let html = '';
        if (m.definitie) {
            html += `<details><summary>Definition</summary><p>${m.definitie}</p></details>`;
        }
        if (m.metodologie) {
            html += `<details><summary>Methodology</summary><p>${m.metodologie}</p></details>`;
        }
        if (m.observatii) {
            html += `<details><summary>Notes</summary><p>${m.observatii}</p></details>`;
        }
        footer.innerHTML = html;
    }

    async fetchAndRender() {
        this.showLoading(true);

        try {
            let filters = { ...this.currentFilters };

            // For choropleth, override filters for clean map data
            if (this.currentChartType === 'choropleth' && this.metadata.chart_config.geo_dim) {
                const geoDim = this.metadata.chart_config.geo_dim;
                const timeDim = this.metadata.chart_config.time_dim;

                // Include all county-level geo IDs
                const geoDimMeta = this.metadata.dimensions.find(d => d.dim_column_name === geoDim);
                if (geoDimMeta) {
                    const countyIds = geoDimMeta.options
                        .filter(o => o.parsed && o.parsed.geo_level === 'county')
                        .map(o => o.nom_item_id);
                    if (countyIds.length > 0) {
                        filters[geoDim] = countyIds;
                    }
                }

                // Remove non-geo, non-time dimension filters for choropleth.
                // The chart deduplicates by taking last value per county per time.
                // This avoids filtering to IDs that may not exist in the parquet.
                for (const dim of this.metadata.dimensions) {
                    const col = dim.dim_column_name;
                    if (col === geoDim || col === timeDim) continue;
                    if (dim.dim_type === 'unit') continue; // unit already handled
                    delete filters[col];
                }
            }

            // Choropleth needs all years × all counties — raise limit accordingly
            const limit = this.currentChartType === 'choropleth' ? 50000 : 5000;
            const data = await API.getDatasetData(
                this.matrixCode,
                filters,
                limit
            );

            // Render chart
            if (this.chartInstance) {
                this.chartInstance.dispose();
            }

            const chartEl = document.getElementById('main-chart');
            if (this.currentChartType === 'table') {
                chartEl.style.display = 'none';
            } else {
                chartEl.style.display = '';
                this.chartInstance = createChart(
                    chartEl,
                    { ...this.metadata.chart_config, primary_chart: this.currentChartType },
                    data,
                    this.metadata
                );
            }

            // Render table
            this.dataTable.update(data, this.metadata);

        } catch (err) {
            document.getElementById('main-chart').innerHTML =
                `<div class="error-msg">${err.message}</div>`;
            console.error(err);
        } finally {
            this.showLoading(false);
        }
    }

    onFiltersChanged(filters) {
        this.currentFilters = { ...this.currentFilters, ...filters };
        // Remove empty filters
        for (const [k, v] of Object.entries(this.currentFilters)) {
            if (!v || (Array.isArray(v) && v.length === 0)) {
                delete this.currentFilters[k];
            }
        }
        // Debounce to avoid rapid-fire fetches
        clearTimeout(this._fetchTimer);
        this._fetchTimer = setTimeout(() => this.fetchAndRender(), 150);
    }

    switchChartType(type) {
        this.currentChartType = type;

        // Update toolbar buttons
        document.querySelectorAll('.chart-types .btn').forEach(btn => {
            btn.classList.toggle('active', btn.dataset.chartType === type);
        });

        this.fetchAndRender();
    }

    showLoading(show) {
        const overlay = document.getElementById('loading-overlay');
        if (overlay) overlay.style.display = show ? 'flex' : 'none';
    }
}

// Resize chart on window resize
window.addEventListener('resize', () => {
    if (window._datasetPage?.chartInstance) {
        window._datasetPage.chartInstance.resize();
    }
});

// Init on DOM ready
document.addEventListener('DOMContentLoaded', () => {
    window._datasetPage = new DatasetPage();
    window._datasetPage.init();
});
