/**
 * Lens — INS Data Observatory
 * A modern, dark-themed data exploration UI.
 * Reuses existing API layer + chart modules.
 */

// ---------------------------------------------------------------------------
// ECharts dark theme — override init so all chart modules use it automatically
// ---------------------------------------------------------------------------
(function registerDarkTheme() {
    const COLORS = ['#818cf8','#f472b6','#34d399','#fbbf24','#60a5fa','#a78bfa','#fb923c','#94a3b8',
                    '#e879f9','#22d3ee','#f87171','#84cc16'];
    echarts.registerTheme('lens', {
        backgroundColor: 'transparent',
        color: COLORS,
        textStyle: { color: '#a1a1aa', fontFamily: "'Inter', system-ui, sans-serif" },
        title: { textStyle: { color: '#fafafa', fontWeight: 600 }, subtextStyle: { color: '#71717a' } },
        legend: { textStyle: { color: '#a1a1aa' }, pageTextStyle: { color: '#a1a1aa' } },
        tooltip: {
            backgroundColor: 'rgba(24,24,28,0.95)',
            borderColor: 'rgba(255,255,255,0.08)',
            textStyle: { color: '#fafafa', fontSize: 12 },
            extraCssText: 'border-radius:8px; backdrop-filter:blur(8px); box-shadow:0 4px 20px rgba(0,0,0,0.5);',
        },
        categoryAxis: {
            axisLine: { lineStyle: { color: 'rgba(255,255,255,0.08)' } },
            axisTick: { lineStyle: { color: 'rgba(255,255,255,0.06)' } },
            axisLabel: { color: '#71717a', fontSize: 11 },
            splitLine: { lineStyle: { color: 'rgba(255,255,255,0.04)' } },
        },
        valueAxis: {
            axisLine: { lineStyle: { color: 'rgba(255,255,255,0.08)' } },
            axisTick: { lineStyle: { color: 'rgba(255,255,255,0.06)' } },
            axisLabel: { color: '#71717a', fontSize: 11 },
            splitLine: { lineStyle: { color: 'rgba(255,255,255,0.04)' } },
        },
        line: { smooth: true, symbolSize: 4, lineStyle: { width: 2.5 } },
        bar: { barMaxWidth: 40, itemStyle: { borderRadius: [3, 3, 0, 0] } },
        scatter: { symbolSize: 10 },
        visualMap: { textStyle: { color: '#71717a' } },
    });

    // Monkey-patch echarts.init to always use our theme
    const _origInit = echarts.init.bind(echarts);
    echarts.init = (dom, _theme, opts) => _origInit(dom, 'lens', opts);
})();


// ---------------------------------------------------------------------------
// Category color palette
// ---------------------------------------------------------------------------
const CAT_COLORS = [
    '#818cf8', '#f472b6', '#34d399', '#fbbf24', '#60a5fa',
    '#a78bfa', '#fb923c', '#22d3ee', '#e879f9', '#f87171',
    '#84cc16', '#94a3b8', '#14b8a6', '#ec4899', '#8b5cf6', '#f59e0b',
];

function catColor(index) { return CAT_COLORS[index % CAT_COLORS.length]; }


// ---------------------------------------------------------------------------
// Main application
// ---------------------------------------------------------------------------
class LensApp {
    constructor() {
        this.metadata = null;   // full dataset metadata from API
        this.profile = null;    // view profile JSON
        this.data = null;       // current chart data
        this.chartConfig = null;
        this.charts = [];       // active ECharts instances
        this.categories = null; // category tree cache
        this.searchIdx = -1;    // keyboard nav index in search results
        this.init();
    }

    // --- Init ---------------------------------------------------------------
    async init() {
        this.bindEvents();
        const code = new URLSearchParams(location.search).get('code');
        if (code) {
            this.showDashboard(code);
        } else {
            this.showBrowse();
        }
    }

    bindEvents() {
        // Search trigger
        document.getElementById('search-trigger').addEventListener('click', () => this.openSearch());
        document.getElementById('search-backdrop').addEventListener('click', () => this.closeSearch());
        document.getElementById('search-input').addEventListener('input', e => this.onSearchInput(e.target.value));

        // Keyboard shortcuts
        document.addEventListener('keydown', e => {
            if (e.key === '/' && !e.ctrlKey && !e.metaKey &&
                document.activeElement.tagName !== 'INPUT' && document.activeElement.tagName !== 'SELECT') {
                e.preventDefault();
                this.openSearch();
            }
            if ((e.metaKey || e.ctrlKey) && e.key === 'k') {
                e.preventDefault();
                this.openSearch();
            }
            if (e.key === 'Escape') this.closeSearch();
            // Arrow nav in search
            if (!document.getElementById('search-overlay').classList.contains('hidden')) {
                if (e.key === 'ArrowDown') { e.preventDefault(); this.moveSearchIdx(1); }
                if (e.key === 'ArrowUp') { e.preventDefault(); this.moveSearchIdx(-1); }
                if (e.key === 'Enter') { e.preventDefault(); this.selectSearchItem(); }
            }
        });

        // Back button
        document.getElementById('back-btn').addEventListener('click', () => this.showBrowse());
        document.getElementById('panel-back').addEventListener('click', () => this.showCategoryGrid());

        // Resize charts
        window.addEventListener('resize', () => {
            for (const c of this.charts) {
                if (c && !c.isDisposed()) c.resize();
            }
        });
    }

    // --- Navigation ---------------------------------------------------------
    navigate(code) {
        const url = new URL(location.href);
        if (code) {
            url.searchParams.set('code', code);
        } else {
            url.searchParams.delete('code');
        }
        history.pushState({}, '', url);
    }

    // --- Browse view --------------------------------------------------------
    async showBrowse() {
        this.navigate(null);
        this.disposeCharts();

        document.getElementById('browse-view').classList.remove('hidden');
        document.getElementById('dashboard-view').classList.add('hidden');
        document.getElementById('back-btn').classList.add('hidden');

        if (!this.categories) {
            const resp = await API.getCategories();
            this.categories = resp.tree;
        }

        const totalDatasets = this.categories.reduce((s, c) => s + (c.total_datasets || 0), 0);
        document.getElementById('hero-sub').textContent =
            `${formatNumber(totalDatasets, 0)} datasets across ${this.categories.length} categories`;
        document.getElementById('dataset-count').textContent = `${formatNumber(totalDatasets, 0)} datasets`;

        this.showCategoryGrid();
    }

    showCategoryGrid() {
        document.getElementById('category-grid').classList.remove('hidden');
        document.getElementById('dataset-panel').classList.add('hidden');

        const grid = document.getElementById('category-grid');
        grid.innerHTML = '';

        this.categories.forEach((cat, i) => {
            const card = document.createElement('div');
            card.className = 'cat-card';
            card.addEventListener('click', () => this.drillCategory(cat, i));

            const color = catColor(i);
            card.innerHTML = `
                <div class="cat-accent" style="background:${color}"></div>
                <div class="cat-body">
                    <div class="cat-name">${cat.name}</div>
                    <div class="cat-meta">
                        <span class="cat-count">${cat.total_datasets || 0} datasets</span>
                        ${cat.children.length ? `<span>&middot; ${cat.children.length} subcategories</span>` : ''}
                    </div>
                    ${cat.children.length ? `<div class="cat-children">
                        ${cat.children.slice(0, 4).map(c =>
                            `<span class="cat-child-pill">${this.shortName(c.name)}</span>`
                        ).join('')}
                        ${cat.children.length > 4 ? `<span class="cat-child-pill">+${cat.children.length - 4}</span>` : ''}
                    </div>` : ''}
                </div>
            `;
            grid.appendChild(card);
        });
    }

    async drillCategory(cat, colorIdx) {
        document.getElementById('category-grid').classList.add('hidden');
        const panel = document.getElementById('dataset-panel');
        panel.classList.remove('hidden');
        document.getElementById('panel-title').textContent = cat.name;
        document.getElementById('panel-count').textContent = `${cat.total_datasets || 0} datasets`;

        const list = document.getElementById('dataset-list');
        list.innerHTML = '<div class="skeleton" style="height:200px;margin:8px 0"></div>';

        // Fetch datasets for this category (use ancestor filter)
        const resp = await API.getDatasets({ ancestor: cat.code, limit: 100, sort: 'updated' });
        list.innerHTML = '';

        if (resp.datasets.length === 0) {
            list.innerHTML = '<div class="search-empty">No datasets in this category</div>';
            return;
        }

        resp.datasets.forEach((ds, i) => {
            const row = document.createElement('div');
            row.className = 'ds-row';
            row.style.animationDelay = `${Math.min(i * 0.02, 0.5)}s`;
            row.addEventListener('click', () => this.showDashboard(ds.matrix_code));
            row.innerHTML = `
                <span class="ds-code">${ds.matrix_code}</span>
                <span class="ds-name">${ds.matrix_name}</span>
                <span class="ds-badges">
                    ${ds.time_range ? `<span class="ds-badge">${ds.time_range}</span>` : ''}
                    ${ds.archetype ? `<span class="ds-badge">${ds.archetype}</span>` : ''}
                    ${ds.row_count ? `<span class="ds-badge">${formatNumber(ds.row_count, 0)} rows</span>` : ''}
                </span>
            `;
            list.appendChild(row);
        });
    }

    // --- Dashboard view -----------------------------------------------------
    async showDashboard(code) {
        this.navigate(code);
        this.disposeCharts();

        document.getElementById('browse-view').classList.add('hidden');
        document.getElementById('dashboard-view').classList.remove('hidden');
        document.getElementById('back-btn').classList.remove('hidden');

        // Show loading skeletons
        document.getElementById('dash-header').innerHTML =
            '<div class="skeleton" style="height:28px;width:60%;margin-bottom:12px"></div>' +
            '<div class="skeleton" style="height:18px;width:40%"></div>';
        document.getElementById('insights-row').innerHTML =
            '<div class="insight-card skeleton" style="height:90px"></div>'.repeat(4);
        document.getElementById('primary-chart').innerHTML =
            '<div class="chart-loading">Loading data...</div>';
        document.getElementById('chart-toolbar').innerHTML = '';
        document.getElementById('filter-strip').innerHTML = '';
        document.getElementById('secondary-grid').innerHTML = '';

        try {
            // Load metadata + profile in parallel
            const [meta, profile] = await Promise.all([
                API.getDataset(code),
                API.getViewProfile(code),
            ]);
            this.metadata = meta;
            this.profile = profile;
            this.chartConfig = meta.chart_config;

            this.renderDashHeader();
            this.renderFilters();
            this.renderChartToolbar();
            await this.fetchAndRender();
        } catch (err) {
            document.getElementById('dash-header').innerHTML =
                `<div class="dash-title" style="color:var(--red)">Error loading dataset: ${err.message}</div>`;
        }
    }

    renderDashHeader() {
        const m = this.metadata;
        const cfg = m.chart_config || {};
        const profile = m.profile || {};

        const timeRange = profile.time_year_min && profile.time_year_max
            ? `${profile.time_year_min}–${profile.time_year_max}` : null;

        const header = document.getElementById('dash-header');
        header.innerHTML = `
            <div class="dash-title">${m.matrix_name}</div>
            <div class="dash-meta">
                ${cfg.archetype ? `<span class="meta-pill archetype">${cfg.archetype}</span>` : ''}
                ${profile.time_granularity ? `<span class="meta-pill time">${profile.time_granularity}</span>` : ''}
                ${timeRange ? `<span class="meta-pill time">${timeRange}</span>` : ''}
                ${m.row_count ? `<span class="meta-pill rows">${formatNumber(m.row_count, 0)} rows</span>` : ''}
                ${m.ultima_actualizare ? `<span class="meta-pill updated">Updated ${m.ultima_actualizare}</span>` : ''}
                <span class="meta-pill code">${m.matrix_code}</span>
            </div>
        `;
    }

    renderChartToolbar() {
        const ranked = this.chartConfig?.ranked_charts || [];
        const primary = this.chartConfig?.primary_chart || 'line';
        const toolbar = document.getElementById('chart-toolbar');
        toolbar.innerHTML = '';

        const LABELS = {
            line: 'Line', bar_vertical: 'Bar', area_stacked: 'Area', horizontal_bar: 'H-Bar',
            grouped_bar: 'Grouped', stacked_bar: 'Stacked', choropleth: 'Map',
            heatmap: 'Heatmap', bubble: 'Bubble', scatter: 'Scatter',
            population_pyramid: 'Pyramid', small_multiples: 'Multiples',
            table: 'Table',
        };

        // For geo_time archetype, inject choropleth if not already present
        const archetype = this.chartConfig?.archetype;
        if (archetype === 'geo_time' && !ranked.some(r => r.chart_type === 'choropleth')) {
            const geoDim = this.chartConfig.geo_dim;
            const timeDim = this.chartConfig.time_dim;
            ranked.unshift({
                chart_type: 'choropleth',
                roles: { entity: geoDim, timeline: timeDim },
            });
            // Pre-load GeoJSON
            if (typeof loadRomaniaGeoJSON === 'function') loadRomaniaGeoJSON();
        }

        const types = [...new Set(ranked.map(r => r.chart_type))].filter(t => t !== 'table');
        for (const type of types) {
            const btn = document.createElement('button');
            btn.className = 'ct-btn' + (type === primary ? ' active' : '');
            btn.textContent = LABELS[type] || type;
            btn.addEventListener('click', () => {
                this.chartConfig.primary_chart = type;
                // Update roles from ranked_charts
                const entry = ranked.find(r => r.chart_type === type);
                if (entry && entry.roles) {
                    this.chartConfig.geo_dim = entry.roles.entity || this.chartConfig.geo_dim;
                }
                toolbar.querySelectorAll('.ct-btn').forEach(b => b.classList.remove('active'));
                btn.classList.add('active');
                this.fetchAndRender();
            });
            toolbar.appendChild(btn);
        }
    }

    renderFilters() {
        const strip = document.getElementById('filter-strip');
        strip.innerHTML = '';
        if (!this.metadata) return;

        const dims = this.metadata.dimensions;
        const profile = this.profile;
        const singletons = profile?.dimensions?.singleton_dims || [];

        // Determine which dims are chart roles (not filterable)
        const cfg = this.chartConfig;
        const ranked = cfg?.ranked_charts || [];
        const entry = ranked.find(r => r.chart_type === cfg.primary_chart);
        const roles = entry?.roles || {};
        const roleCols = new Set([roles.x_axis, roles.series, roles.timeline, roles.entity].filter(Boolean));

        for (const dim of dims) {
            if (singletons.includes(dim.dim_column_name)) continue;
            if (dim.option_count <= 1) continue;
            if (roleCols.has(dim.dim_column_name)) continue;

            const group = document.createElement('div');
            group.className = 'filter-group';

            const label = document.createElement('span');
            label.className = 'filter-label';
            label.textContent = dim.dim_label;
            group.appendChild(label);

            const select = document.createElement('select');
            select.className = 'filter-select';
            select.dataset.col = dim.dim_column_name;

            // "All" option
            const allOpt = document.createElement('option');
            allOpt.value = '';
            allOpt.textContent = 'All';
            select.appendChild(allOpt);

            // Sort options: for time dims, show newest first
            let options = [...dim.options];
            if (dim.dim_type === 'time') options.reverse();

            for (const opt of options.slice(0, 100)) {
                const o = document.createElement('option');
                o.value = opt.sdmx_value || opt.nom_item_id;
                o.textContent = opt.label;
                select.appendChild(o);
            }

            // Default: for time dims, pick latest
            if (dim.dim_type === 'time' && options.length > 0) {
                select.value = options[0].sdmx_value || options[0].nom_item_id;
            }

            select.addEventListener('change', () => this.fetchAndRender());
            group.appendChild(select);
            strip.appendChild(group);
        }
    }

    getFilters() {
        const filters = {};
        document.querySelectorAll('#filter-strip .filter-select').forEach(sel => {
            if (sel.value) {
                filters[sel.dataset.col] = [sel.value];
            }
        });
        return filters;
    }

    computeGroupBy() {
        if (!this.chartConfig) return null;
        const entry = (this.chartConfig.ranked_charts || [])
            .find(r => r.chart_type === this.chartConfig.primary_chart);
        const roles = entry?.roles || {};
        const cols = new Set();
        for (const key of ['x_axis', 'series', 'timeline', 'entity', 'pivot', 'facet']) {
            if (roles[key]) cols.add(roles[key]);
        }
        // Always include filter dims that are set
        document.querySelectorAll('#filter-strip .filter-select').forEach(sel => {
            if (sel.value) cols.add(sel.dataset.col);
        });
        return cols.size > 0 ? [...cols] : null;
    }

    async fetchAndRender() {
        const code = this.metadata.matrix_code;
        const isChoropleth = this.chartConfig?.primary_chart === 'choropleth';
        const filters = this.getFilters();
        // For choropleth, remove the geo filter so all counties are included
        if (isChoropleth && this.chartConfig?.geo_dim) {
            delete filters[this.chartConfig.geo_dim];
        }
        const groupBy = this.computeGroupBy();

        try {
            this.data = await API.getDatasetData(code, filters, 50000, { groupBy });
            this.renderInsights();
            this.renderPrimaryChart();
            this.renderSecondaryCharts();
        } catch (err) {
            const msg = err.message || 'Failed to load data';
            const isLarge = msg.includes('filter');
            document.getElementById('primary-chart').innerHTML = `
                <div class="chart-loading" style="color:${isLarge ? 'var(--amber)' : 'var(--red)'}">
                    ${isLarge ? '⚠ ' : ''}${msg}
                </div>`;
        }
    }

    // --- Insights -----------------------------------------------------------
    renderInsights() {
        const row = document.getElementById('insights-row');
        row.innerHTML = '';
        if (!this.data || !this.data.rows.length) {
            row.innerHTML = '<div class="insight-card"><div class="insight-label">Status</div><div class="insight-value" style="font-size:16px;color:var(--text-2)">No data for current filters</div></div>';
            return;
        }

        const rows = this.data.rows;
        const cols = this.data.columns;
        const valueIdx = cols.length - 1;
        const values = rows.map(r => r[valueIdx]).filter(v => v != null);

        // Latest value with trend
        const latest = values[values.length - 1];
        const prev = values.length > 1 ? values[values.length - 2] : null;
        let trendHtml = '';
        if (prev != null && prev !== 0) {
            const pctChange = ((latest - prev) / Math.abs(prev)) * 100;
            const arrow = pctChange >= 0 ? '↑' : '↓';
            const cls = pctChange >= 0 ? 'insight-up' : 'insight-down';
            trendHtml = `<span class="${cls}">${arrow} ${Math.abs(pctChange).toFixed(1)}%</span>`;
        }
        this.addInsight(row, 'Latest Value', this.formatBigNumber(latest), trendHtml);

        // Average
        const avg = values.reduce((a, b) => a + b, 0) / values.length;
        this.addInsight(row, 'Average', this.formatBigNumber(avg));

        // Min / Max
        const min = Math.min(...values);
        const max = Math.max(...values);
        this.addInsight(row, 'Range', `${this.formatBigNumber(min)} – ${this.formatBigNumber(max)}`);

        // Data points
        this.addInsight(row, 'Data Points', formatNumber(rows.length, 0), `of ${formatNumber(this.metadata.row_count, 0)} total`);
    }

    addInsight(container, label, value, sub = '') {
        const card = document.createElement('div');
        card.className = 'insight-card';
        card.innerHTML = `
            <div class="insight-label">${label}</div>
            <div class="insight-value">${value}</div>
            ${sub ? `<div class="insight-sub">${sub}</div>` : ''}
        `;
        container.appendChild(card);
    }

    formatBigNumber(n) {
        if (n == null) return '—';
        const abs = Math.abs(n);
        if (abs >= 1e9) return (n / 1e9).toFixed(1) + 'B';
        if (abs >= 1e6) return (n / 1e6).toFixed(1) + 'M';
        if (abs >= 1e4) return (n / 1e3).toFixed(1) + 'K';
        return formatNumber(n);
    }

    // --- Charts -------------------------------------------------------------
    renderPrimaryChart() {
        const container = document.getElementById('primary-chart');
        this.disposeCharts();

        if (!this.data || !this.data.rows.length) {
            container.innerHTML = '<div class="chart-loading">No data</div>';
            return;
        }
        container.innerHTML = '';

        try {
            const chart = createChart(container, this.chartConfig, this.data, this.metadata);
            if (chart) this.charts.push(chart);
        } catch (err) {
            container.innerHTML = `<div class="chart-loading" style="color:var(--red)">Chart error: ${err.message}</div>`;
        }
    }

    renderSecondaryCharts() {
        const grid = document.getElementById('secondary-grid');
        grid.innerHTML = '';
        if (!this.data || !this.data.rows.length) return;

        const ranked = this.chartConfig?.ranked_charts || [];
        const primary = this.chartConfig?.primary_chart;

        // Show up to 2 secondary chart types
        const secondary = ranked
            .filter(r => r.chart_type !== primary)
            .slice(0, 2);

        for (const entry of secondary) {
            const card = document.createElement('div');
            card.className = 'sec-chart-card';

            const LABELS = {
                line: 'Line', bar_vertical: 'Bar', area_stacked: 'Area', horizontal_bar: 'H-Bar',
                grouped_bar: 'Grouped Bar', stacked_bar: 'Stacked Bar', choropleth: 'Map',
                heatmap: 'Heatmap', bubble: 'Bubble', scatter: 'Scatter',
            };

            const title = document.createElement('div');
            title.className = 'sec-chart-title';
            title.textContent = LABELS[entry.chart_type] || entry.chart_type;
            card.appendChild(title);

            const container = document.createElement('div');
            container.className = 'sec-chart-container';
            card.appendChild(container);
            grid.appendChild(card);

            // Build a temporary config with this chart type
            try {
                const tempConfig = {
                    ...this.chartConfig,
                    primary_chart: entry.chart_type,
                };
                const chart = createChart(container, tempConfig, this.data, this.metadata);
                if (chart) this.charts.push(chart);
            } catch (_) {
                container.innerHTML = '<div class="chart-loading">Unavailable</div>';
            }
        }
    }

    disposeCharts() {
        for (const c of this.charts) {
            if (c && !c.isDisposed()) c.dispose();
        }
        this.charts = [];
    }

    // --- Search -------------------------------------------------------------
    openSearch() {
        const overlay = document.getElementById('search-overlay');
        overlay.classList.remove('hidden');
        const input = document.getElementById('search-input');
        input.value = '';
        input.focus();
        this.searchIdx = -1;
        document.getElementById('search-results').innerHTML =
            '<div class="search-empty">Type to search across all datasets</div>';
    }

    closeSearch() {
        document.getElementById('search-overlay').classList.add('hidden');
    }

    async onSearchInput(query) {
        const results = document.getElementById('search-results');
        if (!query || query.length < 2) {
            results.innerHTML = '<div class="search-empty">Type to search across all datasets</div>';
            this.searchIdx = -1;
            return;
        }

        try {
            const resp = await API.getDatasets({ q: query, limit: 12 });
            results.innerHTML = '';
            this.searchIdx = -1;

            if (resp.datasets.length === 0) {
                results.innerHTML = '<div class="search-empty">No results</div>';
                return;
            }

            for (const ds of resp.datasets) {
                const item = document.createElement('div');
                item.className = 'search-item';
                item.addEventListener('click', () => {
                    this.closeSearch();
                    this.showDashboard(ds.matrix_code);
                });
                item.innerHTML = `
                    <span class="search-item-code">${ds.matrix_code}</span>
                    <span class="search-item-name">${ds.matrix_name}</span>
                    <span class="search-item-meta">${ds.time_range || ''}</span>
                `;
                results.appendChild(item);
            }
        } catch (_) {
            results.innerHTML = '<div class="search-empty">Search error</div>';
        }
    }

    moveSearchIdx(delta) {
        const items = document.querySelectorAll('#search-results .search-item');
        if (!items.length) return;
        items.forEach(i => i.classList.remove('active'));
        this.searchIdx = Math.max(-1, Math.min(items.length - 1, this.searchIdx + delta));
        if (this.searchIdx >= 0) {
            items[this.searchIdx].classList.add('active');
            items[this.searchIdx].scrollIntoView({ block: 'nearest' });
        }
    }

    selectSearchItem() {
        const items = document.querySelectorAll('#search-results .search-item');
        if (this.searchIdx >= 0 && this.searchIdx < items.length) {
            items[this.searchIdx].click();
        }
    }

    // --- Utilities ----------------------------------------------------------
    shortName(name) {
        // Remove numbering prefix like "1. " or "A.01 "
        return name.replace(/^[A-Z]?\.\d*\s*/, '').replace(/^\d+\.\s*/, '');
    }
}


// ---------------------------------------------------------------------------
// Bootstrap
// ---------------------------------------------------------------------------
document.addEventListener('DOMContentLoaded', () => {
    window.app = new LensApp();
});

// Handle browser back/forward
window.addEventListener('popstate', () => {
    const code = new URLSearchParams(location.search).get('code');
    if (code) {
        window.app.showDashboard(code);
    } else {
        window.app.showBrowse();
    }
});
