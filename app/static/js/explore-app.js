/**
 * Lens — INS Data Observatory
 * A modern data exploration UI with dark/light theme and EN/RO language.
 * Reuses existing API layer + chart modules.
 */

// ---------------------------------------------------------------------------
// i18n — UI string translations
// ---------------------------------------------------------------------------
const UI = {
    ro: {
        heroTitle: 'Romanian Statistics<br><span class="hero-accent">Observatory</span>',
        heroSub: (n, c) => `${n} seturi de date din ${c} categorii`,
        searchPlaceholder: 'Caută seturi de date, indicatori, coduri...',
        searchTrigger: 'Caută seturi de date...',
        searchEmpty: 'Tastează pentru a căuta în toate seturile de date',
        searchNoResults: 'Niciun rezultat',
        searchError: 'Eroare la căutare',
        noDatasets: 'Niciun set de date în această categorie',
        backExplore: '← Explorare',
        backCategories: '← Categorii',
        latestValue: 'Ultima valoare',
        overallChange: 'Variație totală',
        coverage: 'Acoperire',
        periods: 'perioade',
        categories: 'categorii',
        since: 'din',
        dataPoints: 'Puncte date',
        ofTotal: 'din',
        total: 'total',
        noData: 'Fără date',
        noDataFilters: 'Nicio dată pentru filtrele curente',
        datasets: 'seturi de date',
        subcategories: 'subcategorii',
        rows: 'rânduri',
        navigate: 'navighează',
        open: 'deschide',
        categoriesRoot: 'Categorii',
        largeDatasetNotice: 'Se afișează doar o selecție — setul de date are prea multe rânduri pentru afișare completă',
        aboutDataset: 'Despre acest set de date',
        definition: 'Definiție',
        methodology: 'Metodologie',
        notes: 'Observații',
        trends: 'Tendințe',
        snapshot: 'Instantaneu',
        play: 'Redare',
        pause: 'Pauză',
        noTimePanel: 'Fără dimensiune temporală',
        noSnapshotPanel: 'Fără dimensiuni categoriale',
        sidebarTitle: 'Navigare',
        sidebarFilter: 'Filtrează seturi de date...',
        showTable: 'Arată tabelul de date',
        hideTable: 'Ascunde tabelul de date',
        tableLabel: 'Date',
        seriesLabel: 'Culoare',
        xAxisLabel: 'Axă',
        colorLabel: 'Grupare',
        noneDim: 'Niciuna',
    },
    en: {
        heroTitle: 'Romanian Statistics<br><span class="hero-accent">Observatory</span>',
        heroSub: (n, c) => `${n} datasets across ${c} categories`,
        searchPlaceholder: 'Search datasets, indicators, codes...',
        searchTrigger: 'Search datasets...',
        searchEmpty: 'Type to search across all datasets',
        searchNoResults: 'No results',
        searchError: 'Search error',
        noDatasets: 'No datasets in this category',
        backExplore: '← Explore',
        backCategories: '← Categories',
        latestValue: 'Latest Value',
        overallChange: 'Overall Change',
        coverage: 'Coverage',
        periods: 'periods',
        categories: 'categories',
        since: 'since',
        dataPoints: 'Data Points',
        ofTotal: 'of',
        total: 'total',
        noData: 'No data',
        noDataFilters: 'No data for current filters',
        datasets: 'datasets',
        subcategories: 'subcategories',
        rows: 'rows',
        navigate: 'navigate',
        open: 'open',
        categoriesRoot: 'Categories',
        largeDatasetNotice: 'Showing filtered view only — dataset too large for full display',
        aboutDataset: 'About this dataset',
        definition: 'Definition',
        methodology: 'Methodology',
        notes: 'Notes',
        trends: 'Trends',
        snapshot: 'Snapshot',
        play: 'Play',
        pause: 'Pause',
        noTimePanel: 'No time dimension',
        noSnapshotPanel: 'No categorical dimensions',
        sidebarTitle: 'Navigate',
        sidebarFilter: 'Filter datasets...',
        showTable: 'Show data table',
        hideTable: 'Hide data table',
        tableLabel: 'Data',
        seriesLabel: 'Color',
        xAxisLabel: 'Axis',
        colorLabel: 'Group',
        noneDim: 'None',
    },
};

// ---------------------------------------------------------------------------
// ECharts themes — dark and light variants
// ---------------------------------------------------------------------------
(function registerThemes() {
    const COLORS = ['#818cf8','#f472b6','#34d399','#fbbf24','#60a5fa','#a78bfa','#fb923c','#94a3b8',
                    '#e879f9','#22d3ee','#f87171','#84cc16'];

    const sharedStyle = {
        color: COLORS,
        line: { smooth: true, symbolSize: 4, lineStyle: { width: 2.5 } },
        bar: { barMaxWidth: 40, itemStyle: { borderRadius: [3, 3, 0, 0] } },
        scatter: { symbolSize: 10 },
    };

    echarts.registerTheme('lens-dark', {
        ...sharedStyle,
        backgroundColor: 'transparent',
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
        visualMap: { textStyle: { color: '#71717a' } },
    });

    echarts.registerTheme('lens-light', {
        ...sharedStyle,
        backgroundColor: 'transparent',
        textStyle: { color: '#4a4a55', fontFamily: "'Inter', system-ui, sans-serif" },
        title: { textStyle: { color: '#111118', fontWeight: 600 }, subtextStyle: { color: '#8a8a99' } },
        legend: { textStyle: { color: '#4a4a55' }, pageTextStyle: { color: '#4a4a55' } },
        tooltip: {
            backgroundColor: 'rgba(255,255,255,0.96)',
            borderColor: 'rgba(0,0,0,0.08)',
            textStyle: { color: '#111118', fontSize: 12 },
            extraCssText: 'border-radius:8px; backdrop-filter:blur(8px); box-shadow:0 4px 20px rgba(0,0,0,0.12);',
        },
        categoryAxis: {
            axisLine: { lineStyle: { color: 'rgba(0,0,0,0.1)' } },
            axisTick: { lineStyle: { color: 'rgba(0,0,0,0.06)' } },
            axisLabel: { color: '#8a8a99', fontSize: 11 },
            splitLine: { lineStyle: { color: 'rgba(0,0,0,0.05)' } },
        },
        valueAxis: {
            axisLine: { lineStyle: { color: 'rgba(0,0,0,0.1)' } },
            axisTick: { lineStyle: { color: 'rgba(0,0,0,0.06)' } },
            axisLabel: { color: '#8a8a99', fontSize: 11 },
            splitLine: { lineStyle: { color: 'rgba(0,0,0,0.05)' } },
        },
        visualMap: { textStyle: { color: '#8a8a99' } },
    });

    // Monkey-patch echarts.init to use the current theme
    const _origInit = echarts.init.bind(echarts);
    echarts.init = (dom, _theme, opts) => {
        const themeName = document.body.dataset.theme === 'light' ? 'lens-light' : 'lens-dark';
        return _origInit(dom, themeName, opts);
    };
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
        this.categoryTrends = null; // trend aggregates per context code
        this.drillStack = [];   // breadcrumb navigation stack
        this.searchIdx = -1;    // keyboard nav index in search results

        // Two-panel chart state
        this.timeChartType = 'line';      // current type in time panel
        this.snapshotChartType = null;     // current type in snapshot panel (auto-determined)
        this.selectedPeriodIdx = -1;       // -1 = latest period
        this.playInterval = null;          // auto-advance timer
        this.panelSetup = null;            // result of determinePanelSetup()

        // Sidebar state
        this._sidebarLoaded = false;

        // Theme & language from localStorage
        this.theme = localStorage.getItem('lens_theme') || 'dark';
        this.lang = localStorage.getItem('lens_lang') || 'ro';

        this.init();
    }

    /** Shortcut to get current UI strings */
    get ui() { return UI[this.lang] || UI.ro; }

    // --- Init ---------------------------------------------------------------
    async init() {
        this.applyTheme();
        this.applyLang();
        this.bindEvents();
        this.bindThemeAndLang();
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
        document.getElementById('panel-back').addEventListener('click', () => {
            if (this.drillStack.length > 1) {
                this.drillStack.pop();
                const parent = this.drillStack[this.drillStack.length - 1];
                this.drillCategory(parent.cat, parent.colorIdx, false);
            } else {
                this.drillStack = [];
                this.showCategoryGrid();
            }
        });

        // Resize charts
        window.addEventListener('resize', () => {
            for (const c of this.charts) {
                if (c && !c.isDisposed()) c.resize();
            }
        });

        this.initSidebar();
        this.initTableToggle();
    }

    // --- Theme & Language ----------------------------------------------------
    bindThemeAndLang() {
        document.getElementById('theme-toggle').addEventListener('click', () => {
            this.theme = this.theme === 'dark' ? 'light' : 'dark';
            localStorage.setItem('lens_theme', this.theme);
            this.applyTheme();
            this.reRenderCharts();
        });

        document.getElementById('lang-toggle').addEventListener('click', () => {
            this.lang = this.lang === 'ro' ? 'en' : 'ro';
            localStorage.setItem('lens_lang', this.lang);
            this.applyLang();
            // Clear caches (names depend on lang)
            this.categories = null;
            this.categoryTrends = null;
            this._sidebarLoaded = false;
            // Re-render sidebar tree if open
            const sidebar = document.getElementById('lens-sidebar');
            if (sidebar && !sidebar.classList.contains('hidden')) {
                document.getElementById('sidebar-tree').innerHTML = '';
                this.renderSidebar();
            }
            // Re-render current view
            const code = new URLSearchParams(location.search).get('code');
            if (code) {
                this.showDashboard(code);
            } else {
                this.showBrowse();
            }
        });
    }

    applyTheme() {
        document.body.dataset.theme = this.theme;
        const sunIcon = document.getElementById('theme-icon-sun');
        const moonIcon = document.getElementById('theme-icon-moon');
        if (this.theme === 'light') {
            sunIcon.classList.add('hidden');
            moonIcon.classList.remove('hidden');
        } else {
            sunIcon.classList.remove('hidden');
            moonIcon.classList.add('hidden');
        }
    }

    applyLang() {
        document.getElementById('lang-label').textContent = this.lang === 'ro' ? 'EN' : 'RO';
        document.getElementById('search-trigger').querySelector('span').textContent = this.ui.searchTrigger;
        document.getElementById('search-input').placeholder = this.ui.searchPlaceholder;
        const sidebarTitle = document.getElementById('sidebar-title');
        if (sidebarTitle) sidebarTitle.textContent = this.ui.sidebarTitle;
        const sidebarFilter = document.getElementById('sidebar-search-input');
        if (sidebarFilter) sidebarFilter.placeholder = this.ui.sidebarFilter;
        const tablePanelLabel = document.getElementById('table-panel-label');
        if (tablePanelLabel) tablePanelLabel.textContent = this.ui.tableLabel;
        const tableToggleLabel = document.getElementById('table-toggle-label');
        if (tableToggleLabel) {
            const panelHidden = document.getElementById('table-panel')?.classList.contains('hidden');
            tableToggleLabel.textContent = panelHidden ? this.ui.showTable : this.ui.hideTable;
        }
    }

    /** Dispose and re-create all charts (needed after theme change) */
    reRenderCharts() {
        if (this.data && this.chartConfig && this.panelSetup) {
            this.disposeCharts();
            this.renderTimeChart();
            this.renderSnapshotChart();
        }
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
        this.hideTableToggleRow();

        document.getElementById('browse-view').classList.remove('hidden');
        document.getElementById('dashboard-view').classList.add('hidden');
        document.getElementById('back-btn').classList.add('hidden');

        if (!this.categories) {
            const [catResp, trendsResp] = await Promise.all([
                API.getCategories({ lang: this.lang }),
                this.categoryTrends ? Promise.resolve(null) : API.getCategoryTrends(),
            ]);
            this.categories = catResp.tree;
            if (trendsResp) this.categoryTrends = trendsResp.trends;
        }

        const totalDatasets = this.categories.reduce((s, c) => s + (c.total_datasets || 0), 0);
        document.getElementById('hero-sub').innerHTML = this.ui.heroSub(formatNumber(totalDatasets, 0), this.categories.length);
        document.getElementById('dataset-count').textContent = `${formatNumber(totalDatasets, 0)} ${this.ui.datasets}`;

        this.showCategoryGrid();
    }

    showCategoryGrid() {
        document.getElementById('category-grid').classList.remove('hidden');
        document.getElementById('dataset-panel').classList.add('hidden');
        this.drillStack = [];

        const grid = document.getElementById('category-grid');
        grid.innerHTML = '';

        this.categories.forEach((cat, i) => {
            const card = document.createElement('div');
            card.className = 'cat-card';
            card.addEventListener('click', () => this.drillCategory(cat, i));

            const color = catColor(i);
            const trendHtml = this._renderTrendIndicator(cat.code);
            card.innerHTML = `
                <div class="cat-accent" style="background:${color}"></div>
                <div class="cat-body">
                    <div class="cat-name">${cat.name}</div>
                    <div class="cat-meta">
                        <span class="cat-count">${cat.total_datasets || 0} ${this.ui.datasets}</span>
                        ${cat.children.length ? `<span>&middot; ${cat.children.length} ${this.ui.subcategories}</span>` : ''}
                    </div>
                    ${trendHtml}
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

    _renderTrendIndicator(contextCode) {
        const trend = this.categoryTrends?.[contextCode];
        if (!trend || !trend.total) return '';
        const total = trend.total;
        const upPct = (trend.up / total * 100).toFixed(0);
        const dnPct = (trend.down / total * 100).toFixed(0);
        const yoy = trend.avg_yoy;
        const yoyStr = yoy != null ? `${yoy >= 0 ? '+' : ''}${yoy.toFixed(1)}%` : '';
        const yoyCls = yoy >= 0 ? 'up' : 'down';
        return `
            <div class="cat-trend">
                <div class="cat-trend-bar">
                    <div class="cat-trend-up" style="width:${upPct}%"></div>
                    <div class="cat-trend-down" style="width:${dnPct}%"></div>
                </div>
                ${yoyStr ? `<span class="cat-trend-yoy ${yoyCls}">${yoyStr}</span>` : ''}
            </div>
        `;
    }

    async drillCategory(cat, colorIdx, pushToStack = true) {
        if (pushToStack) this.drillStack.push({ cat, colorIdx });

        document.getElementById('category-grid').classList.add('hidden');
        const panel = document.getElementById('dataset-panel');
        panel.classList.remove('hidden');
        document.getElementById('panel-back').textContent =
            this.drillStack.length > 1 ? '← ' + this.drillStack[this.drillStack.length - 2].cat.name : this.ui.backCategories;
        document.getElementById('panel-title').textContent = cat.name;
        document.getElementById('panel-count').textContent = `${cat.total_datasets || 0} ${this.ui.datasets}`;

        this.renderBreadcrumbs();

        const list = document.getElementById('dataset-list');
        list.innerHTML = '<div class="skeleton" style="height:200px;margin:8px 0"></div>';

        // Fetch datasets for this category (use ancestor filter)
        const resp = await API.getDatasets({ ancestor: cat.code, limit: 100, sort: 'updated', lang: this.lang });
        list.innerHTML = '';

        // Show subcategory rows first (if any)
        if (cat.children && cat.children.length > 0) {
            for (const child of cat.children) {
                const trendHtml = this._renderTrendIndicator(child.code);
                const row = document.createElement('div');
                row.className = 'ds-row ds-row-subcat';
                row.addEventListener('click', () => this.drillCategory(child, colorIdx));
                row.innerHTML = `
                    <span class="ds-code" style="color:var(--text-2)">▸</span>
                    <span class="ds-name" style="font-weight:600">${child.name}</span>
                    <span class="ds-badges">
                        <span class="ds-badge">${child.total_datasets || 0} ${this.ui.datasets}</span>
                    </span>
                `;
                list.appendChild(row);
            }
        }

        if (resp.datasets.length === 0 && (!cat.children || cat.children.length === 0)) {
            list.innerHTML = `<div class="search-empty">${this.ui.noDatasets}</div>`;
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
                    ${ds.row_count ? `<span class="ds-badge">${formatNumber(ds.row_count, 0)} ${this.ui.rows}</span>` : ''}
                </span>
            `;
            list.appendChild(row);
        });
    }

    renderBreadcrumbs() {
        let bc = document.getElementById('breadcrumb-trail');
        if (!bc) {
            bc = document.createElement('div');
            bc.id = 'breadcrumb-trail';
            bc.className = 'breadcrumb-trail';
            const panelHeader = document.querySelector('#dataset-panel .panel-header');
            panelHeader.insertAdjacentElement('afterend', bc);
        }
        bc.innerHTML = '';

        // Root link
        const root = document.createElement('span');
        root.className = 'breadcrumb-item breadcrumb-link';
        root.textContent = this.ui.categoriesRoot;
        root.addEventListener('click', () => { this.drillStack = []; this.showCategoryGrid(); });
        bc.appendChild(root);

        this.drillStack.forEach((entry, i) => {
            const sep = document.createElement('span');
            sep.className = 'breadcrumb-sep';
            sep.textContent = '›';
            bc.appendChild(sep);

            const crumb = document.createElement('span');
            crumb.textContent = this.shortName(entry.cat.name);
            if (i < this.drillStack.length - 1) {
                crumb.className = 'breadcrumb-item breadcrumb-link';
                crumb.addEventListener('click', () => {
                    this.drillStack = this.drillStack.slice(0, i + 1);
                    this.drillCategory(entry.cat, entry.colorIdx, false);
                });
            } else {
                crumb.className = 'breadcrumb-item breadcrumb-current';
            }
            bc.appendChild(crumb);
        });
    }

    // --- Dashboard view -----------------------------------------------------
    async showDashboard(code) {
        this.navigate(code);
        this.disposeCharts();
        this.stopPlay();

        document.getElementById('browse-view').classList.add('hidden');
        document.getElementById('dashboard-view').classList.remove('hidden');
        document.getElementById('back-btn').classList.remove('hidden');
        document.getElementById('back-btn').textContent = this.ui.backExplore;
        this.hideTable();
        this.showTableToggleRow();

        // Show loading skeletons
        document.getElementById('dash-header').innerHTML =
            '<div class="skeleton" style="height:28px;width:60%;margin-bottom:12px"></div>' +
            '<div class="skeleton" style="height:18px;width:40%"></div>';
        document.getElementById('insights-row').innerHTML =
            '<div class="insight-card skeleton" style="height:90px"></div>'.repeat(4);
        document.getElementById('time-chart').innerHTML =
            '<div class="chart-loading">Loading data...</div>';
        document.getElementById('snapshot-chart').innerHTML = '';
        document.getElementById('time-pills').innerHTML = '';
        document.getElementById('snapshot-pills').innerHTML = '';
        document.getElementById('period-nav').innerHTML = '';
        document.getElementById('filter-strip').innerHTML = '';

        try {
            // Load metadata + profile in parallel
            const [meta, profile] = await Promise.all([
                API.getDataset(code, { lang: this.lang }),
                API.getViewProfile(code),
            ]);
            this.metadata = meta;
            this.profile = profile;
            this.chartConfig = meta.chart_config;
            this.buildValueMap();

            this.panelSetup = this.determinePanelSetup();
            this.timeChartType = this.panelSetup.timeChartTypes[0] || 'line';
            this.snapshotChartType = this.panelSetup.snapshotChartTypes[0] || null;
            this.selectedPeriodIdx = -1; // latest

            this.renderDashHeader();
            this.renderInfoPanel();
            this.renderFilters();
            this.renderTimePanel();
            this.renderSnapshotPanel();
            this.highlightSidebarDataset(code);
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

        // Build category breadcrumb path
        let pathHtml = '';
        if (m.context_path && m.context_path.length > 0) {
            const crumbs = m.context_path.map((p, i) => {
                const label = this.shortName(p.name);
                if (i < m.context_path.length - 1) {
                    return `<span class="dash-crumb-link" data-code="${p.code}">${label}</span>`;
                }
                return `<span class="dash-crumb-current">${label}</span>`;
            });
            pathHtml = `<div class="dash-breadcrumbs">${crumbs.join('<span class="dash-crumb-sep">›</span>')}</div>`;
        }

        const header = document.getElementById('dash-header');
        header.innerHTML = `
            ${pathHtml}
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

        // Bind breadcrumb clicks → navigate to category drill
        header.querySelectorAll('.dash-crumb-link').forEach(el => {
            el.addEventListener('click', () => {
                const code = el.dataset.code;
                const cat = m.context_path.find(p => p.code === code);
                if (cat) {
                    this.drillStack = [];
                    // Build stack up to clicked level
                    const idx = m.context_path.indexOf(cat);
                    for (let i = 0; i <= idx; i++) {
                        this.drillStack.push({ cat: m.context_path[i], colorIdx: 0 });
                    }
                    this.showBrowse();
                    this.drillCategory(cat, 0, false);
                }
            });
        });
    }

    renderInfoPanel() {
        const m = this.metadata;
        const panel = document.getElementById('info-panel');
        const definitie = m.definitie?.trim();
        const metodologie = m.metodologie?.trim();
        const observatii = m.observatii?.trim();

        if (!definitie && !metodologie && !observatii) {
            panel.classList.add('hidden');
            return;
        }

        panel.classList.remove('hidden');
        panel.innerHTML = `
            <button class="info-toggle" id="info-toggle" aria-expanded="false">
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/></svg>
                ${this.ui.aboutDataset || 'About this dataset'}
                <svg class="info-chevron" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><polyline points="6 9 12 15 18 9"/></svg>
            </button>
            <div class="info-body hidden" id="info-body">
                ${definitie ? `<div class="info-section"><strong>${this.ui.definition || 'Definition'}</strong><p>${definitie}</p></div>` : ''}
                ${metodologie ? `<div class="info-section"><strong>${this.ui.methodology || 'Methodology'}</strong><p>${metodologie}</p></div>` : ''}
                ${observatii ? `<div class="info-section"><strong>${this.ui.notes || 'Notes'}</strong><p>${observatii}</p></div>` : ''}
            </div>
        `;

        document.getElementById('info-toggle').addEventListener('click', () => {
            const body = document.getElementById('info-body');
            const btn = document.getElementById('info-toggle');
            const expanded = !body.classList.contains('hidden');
            body.classList.toggle('hidden', expanded);
            btn.setAttribute('aria-expanded', String(!expanded));
            btn.querySelector('.info-chevron').style.transform = expanded ? '' : 'rotate(180deg)';
        });
    }

    // --- Two-panel setup -----------------------------------------------------

    /**
     * Analyze dataset dimensions to determine what each panel shows.
     * Returns: { hasTimePanel, hasSnapshotPanel, timeDim, timeSeriesDim,
     *   snapXDim, snapSeriesDim, timeChartTypes, snapshotChartTypes, filterDims, periods }
     */
    determinePanelSetup() {
        const dims = this.metadata?.dimensions || [];
        const profile = this.profile;
        const singletons = profile?.dimensions?.singleton_dims || [];
        const cfg = this.chartConfig || {};
        const archetype = cfg.archetype;

        // Classify dimensions
        const timeDimObj = dims.find(d => d.dim_type === 'time');
        const geoDimObj = dims.find(d => d.dim_type === 'geo');
        const unitDims = dims.filter(d => d.dim_type === 'unit').map(d => d.dim_column_name);
        const singletonSet = new Set(singletons);

        // Non-time, non-unit, non-singleton dims with more than 1 option
        const categoryDims = dims.filter(d =>
            d.dim_type !== 'time' && d.dim_type !== 'unit' &&
            !singletonSet.has(d.dim_column_name) && d.option_count > 1
        );

        // Time panel
        const hasTimePanel = !!timeDimObj;
        const timeDim = timeDimObj?.dim_column_name || null;

        // Pick best series dim for time panel: prefer 2-6 values, then lowest cardinality
        let timeSeriesDim = null;
        if (hasTimePanel && categoryDims.length > 0) {
            const candidates = categoryDims.filter(d => d.option_count >= 2 && d.option_count <= 6);
            if (candidates.length > 0) {
                // Prefer residence/gender dims, then small cardinality
                const preferred = candidates.find(d => ['residence', 'gender'].includes(d.dim_type))
                    || candidates.find(d => d.option_count <= 4);
                timeSeriesDim = (preferred || candidates[0]).dim_column_name;
            } else {
                // Pick lowest cardinality
                const sorted = [...categoryDims].sort((a, b) => a.option_count - b.option_count);
                timeSeriesDim = sorted[0].dim_column_name;
            }
        }

        // Snapshot panel
        const hasSnapshotPanel = categoryDims.length > 0;
        let snapXDim = null, snapSeriesDim = null;

        if (hasSnapshotPanel) {
            // Sort by cardinality descending → highest cardinality = x-axis
            const sorted = [...categoryDims].sort((a, b) => b.option_count - a.option_count);
            snapXDim = sorted[0].dim_column_name;
            if (sorted.length > 1) {
                // Prefer gender/residence for series (color), then 2nd highest cardinality
                const remaining = sorted.slice(1);
                const preferred = remaining.find(d => ['residence', 'gender'].includes(d.dim_type));
                snapSeriesDim = (preferred || remaining[0]).dim_column_name;
            }
        }

        // Time chart types
        const timeChartTypes = hasTimePanel ? ['line', 'bar', 'area_stacked', 'stacked_bar'] : [];

        // Snapshot chart types
        let snapshotChartTypes = [];
        if (hasSnapshotPanel) {
            if (categoryDims.length >= 2) {
                snapshotChartTypes = ['grouped_bar', 'stacked_bar', 'heatmap', 'bubble'];
            } else {
                snapshotChartTypes = ['bar_vertical', 'horizontal_bar'];
            }
            // For geo_time, prepend choropleth
            if (archetype === 'geo_time' && geoDimObj) {
                snapshotChartTypes.unshift('choropleth');
                // Detect geo level from dimension options to load correct GeoJSON
                let geoLevel = 'county';
                if (geoDimObj.options) {
                    const lvlCounts = {};
                    for (const opt of geoDimObj.options) {
                        const lvl = opt.parsed?.geo_level;
                        if (lvl) lvlCounts[lvl] = (lvlCounts[lvl] || 0) + 1;
                    }
                    if (lvlCounts['macroregion'] > 0 && !lvlCounts['county']) geoLevel = 'macroregion';
                    else if (lvlCounts['region'] > 0 && !lvlCounts['county']) geoLevel = 'region';
                }
                if (typeof loadRomaniaGeoJSON === 'function') loadRomaniaGeoJSON(geoLevel);
            }
        }

        // Periods from time dimension options
        let periods = [];
        if (timeDimObj) {
            periods = (timeDimObj.options || []).map(o => ({
                id: o.sdmx_value || o.nom_item_id,
                label: (o.label || '').replace(/^Anul\s+/, ''),
            }));
            // Options are in chronological order (oldest first) from API
        }

        // Filter dims: dims not assigned to any chart axis
        const axisDims = new Set([timeDim, timeSeriesDim, snapXDim, snapSeriesDim].filter(Boolean));
        const filterDims = dims.filter(d =>
            !axisDims.has(d.dim_column_name) &&
            d.dim_type !== 'unit' &&
            !singletonSet.has(d.dim_column_name) &&
            d.option_count > 1
        );

        return {
            hasTimePanel, hasSnapshotPanel,
            timeDim, timeSeriesDim,
            snapXDim, snapSeriesDim,
            timeChartTypes, snapshotChartTypes,
            filterDims, periods,
            geoDim: geoDimObj?.dim_column_name || cfg.geo_dim || null,
            categoryDims,
        };
    }

    renderTimePanel() {
        const panel = document.getElementById('time-panel');
        const setup = this.panelSetup;

        document.getElementById('time-panel-label').textContent = this.ui.trends;

        if (!setup.hasTimePanel) {
            panel.classList.add('hidden');
            return;
        }
        panel.classList.remove('hidden');

        const pills = document.getElementById('time-pills');
        pills.innerHTML = '';

        const LABELS = {
            line: 'Line', bar: 'Bar', area_stacked: 'Area', stacked_bar: 'Stacked',
        };

        for (const type of setup.timeChartTypes) {
            const btn = document.createElement('button');
            btn.className = 'ct-btn' + (type === this.timeChartType ? ' active' : '');
            btn.textContent = LABELS[type] || type;
            btn.addEventListener('click', () => {
                this.timeChartType = type;
                pills.querySelectorAll('.ct-btn').forEach(b => b.classList.remove('active'));
                btn.classList.add('active');
                const el = document.getElementById('time-chart');
                el.style.opacity = '0.4';
                el.style.transition = 'opacity 0.15s';
                this.renderTimeChart();
                el.style.opacity = '';
                el.style.transition = '';
            });
            pills.appendChild(btn);
        }

        // Dimension picker for time series (which dim colors the lines)
        if (setup.categoryDims.length >= 2) {
            const picker = document.createElement('div');
            picker.className = 'dim-picker';
            picker.innerHTML = `<span class="dim-picker-label">${this.ui.seriesLabel}:</span>`;
            const sel = document.createElement('select');
            sel.className = 'dim-picker-select';
            // "None" option — single aggregate line
            const noneOpt = document.createElement('option');
            noneOpt.value = '';
            noneOpt.textContent = this.ui.noneDim;
            sel.appendChild(noneOpt);
            for (const d of setup.categoryDims) {
                const opt = document.createElement('option');
                opt.value = d.dim_column_name;
                opt.textContent = d.dim_label;
                if (d.dim_column_name === setup.timeSeriesDim) opt.selected = true;
                sel.appendChild(opt);
            }
            sel.addEventListener('change', () => {
                this.panelSetup.timeSeriesDim = sel.value || null;
                this.renderFilters();
                this.renderTimeChart();
            });
            picker.appendChild(sel);
            pills.appendChild(picker);
        }
    }

    renderSnapshotPanel() {
        const panel = document.getElementById('snapshot-panel');
        const setup = this.panelSetup;

        document.getElementById('snapshot-panel-label').textContent = this.ui.snapshot;

        if (!setup.hasSnapshotPanel) {
            panel.classList.add('hidden');
            return;
        }
        panel.classList.remove('hidden');

        const pills = document.getElementById('snapshot-pills');
        pills.innerHTML = '';

        const LABELS = {
            grouped_bar: 'Grouped', stacked_bar: 'Stacked', heatmap: 'Heatmap', bubble: 'Bubble',
            bar_vertical: 'Bar', horizontal_bar: 'H-Bar', choropleth: 'Map',
        };

        for (const type of setup.snapshotChartTypes) {
            const btn = document.createElement('button');
            btn.className = 'ct-btn' + (type === this.snapshotChartType ? ' active' : '');
            btn.textContent = LABELS[type] || type;
            btn.addEventListener('click', () => {
                this.snapshotChartType = type;
                pills.querySelectorAll('.ct-btn').forEach(b => b.classList.remove('active'));
                btn.classList.add('active');
                const el = document.getElementById('snapshot-chart');
                el.style.opacity = '0.4';
                el.style.transition = 'opacity 0.15s';
                this.renderSnapshotChart();
                el.style.opacity = '';
                el.style.transition = '';
            });
            pills.appendChild(btn);
        }

        // Dimension pickers for snapshot (X-axis and Color/Series)
        if (setup.categoryDims.length >= 2) {
            const pickerRow = document.createElement('div');
            pickerRow.className = 'dim-picker-row';

            // X-axis picker
            const xPicker = document.createElement('div');
            xPicker.className = 'dim-picker';
            xPicker.innerHTML = `<span class="dim-picker-label">${this.ui.xAxisLabel}:</span>`;
            const xSel = document.createElement('select');
            xSel.className = 'dim-picker-select';
            for (const d of setup.categoryDims) {
                const opt = document.createElement('option');
                opt.value = d.dim_column_name;
                opt.textContent = d.dim_label;
                if (d.dim_column_name === setup.snapXDim) opt.selected = true;
                xSel.appendChild(opt);
            }
            xPicker.appendChild(xSel);
            pickerRow.appendChild(xPicker);

            // Series/Color picker
            const sPicker = document.createElement('div');
            sPicker.className = 'dim-picker';
            sPicker.innerHTML = `<span class="dim-picker-label">${this.ui.colorLabel}:</span>`;
            const sSel = document.createElement('select');
            sSel.className = 'dim-picker-select';
            const noneOpt = document.createElement('option');
            noneOpt.value = '';
            noneOpt.textContent = this.ui.noneDim;
            sSel.appendChild(noneOpt);
            for (const d of setup.categoryDims) {
                const opt = document.createElement('option');
                opt.value = d.dim_column_name;
                opt.textContent = d.dim_label;
                if (d.dim_column_name === setup.snapSeriesDim) opt.selected = true;
                sSel.appendChild(opt);
            }
            sPicker.appendChild(sSel);
            pickerRow.appendChild(sPicker);

            const onDimChange = () => {
                const newX = xSel.value;
                let newS = sSel.value;
                // Avoid same dim on both axes
                if (newS && newS === newX) newS = '';
                this.panelSetup.snapXDim = newX;
                this.panelSetup.snapSeriesDim = newS || null;
                this.renderFilters();
                this.renderSnapshotChart();
            };
            xSel.addEventListener('change', onDimChange);
            sSel.addEventListener('change', onDimChange);

            // Remove any previous picker row before inserting
            const oldPicker = pills.parentNode.querySelector('.dim-picker-row');
            if (oldPicker) oldPicker.remove();
            pills.parentNode.insertBefore(pickerRow, pills.nextSibling);
        }

        this.renderPeriodNav();
    }

    renderPeriodNav() {
        const nav = document.getElementById('period-nav');
        nav.innerHTML = '';

        const setup = this.panelSetup;
        if (!setup.hasTimePanel || setup.periods.length === 0) return;

        const periods = setup.periods;
        const currentIdx = this.selectedPeriodIdx < 0 ? periods.length - 1 : this.selectedPeriodIdx;

        const prevBtn = document.createElement('button');
        prevBtn.className = 'period-btn';
        prevBtn.innerHTML = '&#9664;';
        prevBtn.disabled = currentIdx <= 0;
        prevBtn.title = 'Previous period';
        prevBtn.addEventListener('click', () => this.advancePeriod(-1));

        const label = document.createElement('span');
        label.className = 'period-label';
        label.textContent = periods[currentIdx]?.label || '';

        const nextBtn = document.createElement('button');
        nextBtn.className = 'period-btn';
        nextBtn.innerHTML = '&#9654;';
        nextBtn.disabled = currentIdx >= periods.length - 1;
        nextBtn.title = 'Next period';
        nextBtn.addEventListener('click', () => this.advancePeriod(1));

        const playBtn = document.createElement('button');
        playBtn.className = 'period-play' + (this.playInterval ? ' playing' : '');
        playBtn.innerHTML = this.playInterval ? '&#9646;&#9646;' : '&#9654;';
        playBtn.title = this.playInterval ? this.ui.pause : this.ui.play;
        playBtn.addEventListener('click', () => this.togglePlay());

        nav.appendChild(prevBtn);
        nav.appendChild(label);
        nav.appendChild(nextBtn);
        nav.appendChild(playBtn);
    }

    advancePeriod(delta) {
        const periods = this.panelSetup?.periods || [];
        if (periods.length === 0) return;

        let idx = this.selectedPeriodIdx < 0 ? periods.length - 1 : this.selectedPeriodIdx;
        idx += delta;

        if (idx < 0) idx = 0;
        if (idx >= periods.length) {
            idx = periods.length - 1;
            this.stopPlay();
        }

        this.selectedPeriodIdx = idx;
        this.renderPeriodNav();
        this.renderSnapshotChart();
    }

    togglePlay() {
        if (this.playInterval) {
            this.stopPlay();
        } else {
            // Start from beginning if at the end
            const periods = this.panelSetup?.periods || [];
            let idx = this.selectedPeriodIdx < 0 ? periods.length - 1 : this.selectedPeriodIdx;
            if (idx >= periods.length - 1) {
                this.selectedPeriodIdx = 0;
                this.renderPeriodNav();
                this.renderSnapshotChart();
            }
            this.playInterval = setInterval(() => this.advancePeriod(1), 1500);
            this.renderPeriodNav();
        }
    }

    stopPlay() {
        if (this.playInterval) {
            clearInterval(this.playInterval);
            this.playInterval = null;
            this.renderPeriodNav();
        }
    }

    getActiveFilterDims() {
        if (!this.metadata || !this.panelSetup) return [];
        const setup = this.panelSetup;
        // Dims currently assigned to chart axes (not available for filtering)
        const chartedDims = new Set([
            setup.timeDim,
            setup.timeSeriesDim,
            setup.snapXDim,
            setup.snapSeriesDim,
        ].filter(Boolean));
        // Filter dims = category dims not on any chart axis
        const dims = this.metadata.dimensions || [];
        const profile = this.profile;
        const singletons = new Set(profile?.dimensions?.singleton_dims || []);
        return dims.filter(d =>
            !chartedDims.has(d.dim_column_name) &&
            d.dim_type !== 'time' && d.dim_type !== 'unit' &&
            !singletons.has(d.dim_column_name) &&
            d.option_count > 1
        );
    }

    renderFilters() {
        const strip = document.getElementById('filter-strip');
        // Preserve existing filter selections before rebuilding
        const prevSelections = {};
        strip.querySelectorAll('.filter-select').forEach(sel => {
            if (sel.value) prevSelections[sel.dataset.col] = sel.value;
        });
        strip.innerHTML = '';
        if (!this.metadata || !this.panelSetup) return;

        const filterDims = this.getActiveFilterDims();

        for (const dim of filterDims) {
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

            let options = [...dim.options];
            // Don't auto-filter time dims anymore — time is on the chart axis
            for (const opt of options.slice(0, 100)) {
                const o = document.createElement('option');
                o.value = opt.sdmx_value || opt.nom_item_id;
                o.textContent = opt.label;
                select.appendChild(o);
            }

            // Restore previous selection if this dim was a filter before
            if (prevSelections[dim.dim_column_name]) {
                select.value = prevSelections[dim.dim_column_name];
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
        if (!this.metadata) return null;
        const dims = this.metadata.dimensions || [];
        const profile = this.profile;
        const singletons = new Set(profile?.dimensions?.singleton_dims || []);

        // Include ALL non-singleton, non-unit dimension columns
        // Both panels share data, so we need the most granular breakdown
        const cols = new Set();
        for (const dim of dims) {
            if (singletons.has(dim.dim_column_name)) continue;
            if (dim.dim_type === 'unit' && dim.option_count <= 1) continue;
            if (dim.option_count <= 1) continue;
            cols.add(dim.dim_column_name);
        }
        // Always include filter dims that are set
        document.querySelectorAll('#filter-strip .filter-select').forEach(sel => {
            if (sel.value) cols.add(sel.dataset.col);
        });
        return cols.size > 0 ? [...cols] : null;
    }

    async fetchAndRender() {
        const code = this.metadata.matrix_code;
        const filters = this.getFilters();

        // Smarter large dataset handling: auto-apply filter if needed
        const rowCount = this.metadata.row_count || 0;
        const hasActiveFilters = Object.keys(filters).length > 0;
        let autoFilterApplied = false;

        if (rowCount > 50000 && !hasActiveFilters) {
            autoFilterApplied = this._autoApplyFilter(filters);
        }

        const groupBy = this.computeGroupBy();

        try {
            this.data = await API.getDatasetData(code, filters, 50000, { groupBy });
            if (autoFilterApplied) this._showLargeDatasetNotice(); else this._hideLargeDatasetNotice();
            this.renderInsights();
            await this.renderTimeChart();
            await this.renderSnapshotChart();
            if (!document.getElementById('table-panel').classList.contains('hidden')) this.renderTable();
        } catch (err) {
            const msg = err.message || 'Failed to load data';
            const isLarge = msg.includes('filter');
            // Retry with auto-filter on large dataset error
            if (isLarge && !autoFilterApplied) {
                autoFilterApplied = this._autoApplyFilter(filters);
                if (autoFilterApplied) {
                    try {
                        this.data = await API.getDatasetData(code, filters, 50000, { groupBy: this.computeGroupBy() });
                        this._showLargeDatasetNotice();
                        this.renderInsights();
                        await this.renderTimeChart();
                        await this.renderSnapshotChart();
                        if (!document.getElementById('table-panel').classList.contains('hidden')) this.renderTable();
                        return;
                    } catch (_) { /* fall through */ }
                }
            }
            this._hideLargeDatasetNotice();
            document.getElementById('time-chart').innerHTML = `
                <div class="chart-loading" style="color:${isLarge ? 'var(--amber)' : 'var(--red)'}">
                    ${isLarge ? '⚠ ' : ''}${msg}
                </div>`;
        }
    }

    /** Auto-pick first available filter value for large datasets (skip "TOTAL" aggregates) */
    _autoApplyFilter(filters) {
        const selects = document.querySelectorAll('#filter-strip .filter-select');
        for (const sel of selects) {
            if (sel.value) continue;
            // Find first non-empty, non-TOTAL option
            const opts = [...sel.querySelectorAll('option:not([value=""])')];
            const pick = opts.find(o => !/^TOTAL$/i.test(o.value)) || opts[0];
            if (pick) {
                sel.value = pick.value;
                filters[sel.dataset.col] = [pick.value];
                return true;
            }
        }
        return false;
    }

    _showLargeDatasetNotice() {
        let notice = document.getElementById('large-dataset-notice');
        if (!notice) {
            notice = document.createElement('div');
            notice.id = 'large-dataset-notice';
            notice.className = 'large-dataset-notice';
            const filterStrip = document.getElementById('filter-strip');
            filterStrip.insertAdjacentElement('beforebegin', notice);
        }
        notice.innerHTML = `<span class="notice-icon">⚠</span> ${this.ui.largeDatasetNotice}`;
        notice.classList.remove('hidden');
    }

    _hideLargeDatasetNotice() {
        const notice = document.getElementById('large-dataset-notice');
        if (notice) notice.classList.add('hidden');
    }

    // --- Insights -----------------------------------------------------------
    renderInsights() {
        const row = document.getElementById('insights-row');
        row.innerHTML = '';
        if (!this.data || !this.data.rows.length) {
            row.innerHTML = `<div class="insight-card"><div class="insight-label">Status</div><div class="insight-value" style="font-size:16px;color:var(--text-2)">${this.ui.noDataFilters}</div></div>`;
            return;
        }

        const rows = this.data.rows;
        const cols = this.data.columns;
        const valueIdx = cols.length - 1;
        const values = rows.map(r => r[valueIdx]).filter(v => v != null);
        const setup = this.panelSetup;

        // Aggregate by time period if time dimension exists
        // Use AVG for rate/percentage data, SUM for counts
        const unitType = this.chartConfig?.primary_unit_type;
        const useAvg = unitType === 'percentage' || unitType === 'time_unit' || unitType === 'rate';
        const timeDim = setup?.timeDim;
        const timeIdx = timeDim ? cols.indexOf(timeDim) : -1;
        let periodTotals = null; // [{period, total}] sorted chronologically

        if (timeIdx !== -1) {
            const byPeriod = {};
            const byCounts = {};
            for (const r of rows) {
                const t = r[timeIdx];
                const v = r[valueIdx];
                if (t != null && v != null) {
                    byPeriod[t] = (byPeriod[t] || 0) + v;
                    byCounts[t] = (byCounts[t] || 0) + 1;
                }
            }
            periodTotals = Object.entries(byPeriod)
                .map(([p, t]) => ({
                    period: p,
                    total: useAvg ? t / (byCounts[p] || 1) : t,
                }))
                .sort((a, b) => String(a.period).localeCompare(String(b.period)));
        }

        // Card 1: Latest period aggregate with YoY trend
        if (periodTotals && periodTotals.length > 0) {
            const latest = periodTotals[periodTotals.length - 1];
            const prev = periodTotals.length > 1 ? periodTotals[periodTotals.length - 2] : null;
            let trendHtml = '';
            if (prev && prev.total !== 0) {
                const pctChange = ((latest.total - prev.total) / Math.abs(prev.total)) * 100;
                const arrow = pctChange >= 0 ? '↑' : '↓';
                const cls = pctChange >= 0 ? 'insight-up' : 'insight-down';
                trendHtml = `<span class="${cls}">${arrow} ${Math.abs(pctChange).toFixed(1)}%</span>`;
            }
            const periodLabel = String(latest.period).replace(/^Anul\s+/, '');
            this.addInsight(row, this.ui.latestValue, this.formatBigNumber(latest.total),
                (trendHtml ? trendHtml + ' ' : '') + (periodLabel ? `<span class="insight-period">${periodLabel}</span>` : ''));
        } else {
            // No time dimension — show sum or avg of all values
            const agg = useAvg
                ? values.reduce((a, b) => a + b, 0) / values.length
                : values.reduce((a, b) => a + b, 0);
            this.addInsight(row, this.ui.latestValue, this.formatBigNumber(agg));
        }

        // Card 2: Overall Change (first→last period %)
        if (periodTotals && periodTotals.length >= 2) {
            const first = periodTotals[0];
            const latest = periodTotals[periodTotals.length - 1];
            if (first.total && first.total !== 0) {
                const change = ((latest.total - first.total) / Math.abs(first.total)) * 100;
                const sign = change >= 0 ? '+' : '';
                const cls = change >= 0 ? 'insight-up' : 'insight-down';
                const firstLabel = String(first.period).replace(/^Anul\s+/, '');
                this.addInsight(row, this.ui.overallChange,
                    `<span class="${cls}">${sign}${change.toFixed(1)}%</span>`,
                    `${this.ui.since} ${firstLabel}`);
            } else {
                this.addInsight(row, this.ui.coverage, String(periodTotals.length),
                    this.ui.periods);
            }
        } else {
            this.addInsight(row, this.ui.dataPoints, formatNumber(rows.length, 0));
        }

        // Card 3: Data Coverage (periods × categories)
        if (periodTotals && periodTotals.length > 0) {
            // Count unique values in the largest non-time dimension
            const nonTimeDims = cols.filter((c, i) => i !== valueIdx && c !== timeDim);
            let catCount = 0;
            if (nonTimeDims.length > 0) {
                // Find dimension with most unique values
                for (const dim of nonTimeDims) {
                    const idx = cols.indexOf(dim);
                    const uniq = new Set(rows.map(r => r[idx]).filter(v => v != null)).size;
                    if (uniq > catCount) catCount = uniq;
                }
            }
            const sub = catCount > 1
                ? `${this.ui.periods} · ${catCount} ${this.ui.categories}`
                : this.ui.periods;
            this.addInsight(row, this.ui.coverage, String(periodTotals.length), sub);
        } else {
            this.addInsight(row, this.ui.coverage, formatNumber(rows.length, 0), this.ui.dataPoints);
        }

        // Card 4: Sparkline (per-period totals) or Data Points
        if (periodTotals && periodTotals.length >= 3) {
            this.addSparklineInsight(row, periodTotals);
        } else {
            this.addInsight(row, this.ui.dataPoints, formatNumber(rows.length, 0),
                `${this.ui.ofTotal} ${formatNumber(this.metadata.row_count, 0)} ${this.ui.total}`);
        }
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

    addSparklineInsight(container, periodTotals) {
        const card = document.createElement('div');
        card.className = 'insight-card';
        const totals = periodTotals.map(p => p.total);
        const minVal = Math.min(...totals);
        const maxVal = Math.max(...totals);
        const range = maxVal - minVal;
        const W = 100, H = 36, pad = 2;

        const points = totals.map((v, i) => {
            const x = totals.length > 1 ? (i / (totals.length - 1)) * W : W / 2;
            const y = range > 0 ? H - pad - ((v - minVal) / range) * (H - 2 * pad) : H / 2;
            return `${x.toFixed(1)},${y.toFixed(1)}`;
        }).join(' ');

        const areaPoints = `${points} ${W},${H} 0,${H}`;
        const firstLabel = String(periodTotals[0].period).replace(/^Anul\s+/, '');
        const lastLabel = String(periodTotals[periodTotals.length - 1].period).replace(/^Anul\s+/, '');

        card.innerHTML = `
            <div class="insight-label">${this.ui.trends}</div>
            <svg viewBox="0 0 ${W} ${H}" preserveAspectRatio="none"
                 style="width:100%;height:${H}px;margin:6px 0 2px;display:block">
                <defs>
                    <linearGradient id="spark-fill" x1="0" y1="0" x2="0" y2="1">
                        <stop offset="0%" stop-color="var(--accent)" stop-opacity="0.25"/>
                        <stop offset="100%" stop-color="var(--accent)" stop-opacity="0.02"/>
                    </linearGradient>
                </defs>
                <polygon points="${areaPoints}" fill="url(#spark-fill)"/>
                <polyline points="${points}" fill="none"
                          stroke="var(--accent)" stroke-width="1.5"
                          stroke-linejoin="round" stroke-linecap="round"
                          vector-effect="non-scaling-stroke"/>
            </svg>
            <div class="insight-sub">${firstLabel} – ${lastLabel}</div>
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

    // --- Charts (two-panel) --------------------------------------------------

    async renderTimeChart() {
        const container = document.getElementById('time-chart');
        const setup = this.panelSetup;

        // Dispose only time-panel chart instances
        this.charts.filter(c => c && !c.isDisposed() && c._timePanel).forEach(c => c.dispose());
        this.charts = this.charts.filter(c => c && !c.isDisposed());

        if (!setup?.hasTimePanel) return;

        if (!this.data || !this.data.rows.length) {
            container.innerHTML = `<div class="chart-loading">${this.ui.noData}</div>`;
            return;
        }
        container.innerHTML = '';

        try {
            // Build config for time panel — omit ranked_charts so resolveRoles()
            // doesn't override our explicit dim assignments
            const cfg = {
                ...this.chartConfig,
                ranked_charts: [],
                primary_chart: this.timeChartType,
                time_dim: setup.timeDim,
                series_dim: setup.timeSeriesDim,
                x_axis_dim: setup.timeDim,  // time is always on x-axis for this panel
            };
            const chart = await createChart(container, cfg, this._translateData(this.data), this.metadata);
            if (chart) {
                chart._timePanel = true;
                this.charts.push(chart);
            }
        } catch (err) {
            container.innerHTML = `<div class="chart-loading" style="color:var(--red)">Chart error: ${err.message}</div>`;
        }
    }

    async renderSnapshotChart() {
        const container = document.getElementById('snapshot-chart');
        const setup = this.panelSetup;

        if (!setup?.hasSnapshotPanel || !this.snapshotChartType) {
            container.innerHTML = '';
            return;
        }

        if (!this.data || !this.data.rows.length) {
            container.innerHTML = `<div class="chart-loading">${this.ui.noData}</div>`;
            return;
        }

        // Filter data to selected period
        const periods = setup.periods;
        const periodIdx = this.selectedPeriodIdx < 0 ? periods.length - 1 : this.selectedPeriodIdx;
        const selectedPeriod = periods[periodIdx];

        let filteredData = this.data;
        if (selectedPeriod && setup.timeDim) {
            const timeCol = this.data.columns.indexOf(setup.timeDim);
            if (timeCol !== -1) {
                const periodId = selectedPeriod.id;
                const filteredRows = this.data.rows.filter(r =>
                    String(r[timeCol]) === String(periodId)
                );
                filteredData = {
                    ...this.data,
                    rows: filteredRows,
                };
            }
        }

        if (filteredData.rows.length === 0) {
            container.innerHTML = `<div class="chart-loading">${this.ui.noDataFilters}</div>`;
            return;
        }

        // Dispose existing snapshot chart
        const existing = this.charts.filter(c => c && !c.isDisposed() && c._snapshotPanel);
        existing.forEach(c => { c.dispose(); });
        this.charts = this.charts.filter(c => c && !c.isDisposed());

        container.innerHTML = '';

        try {
            const isChoropleth = this.snapshotChartType === 'choropleth';
            const cfg = {
                ...this.chartConfig,
                ranked_charts: [],
                primary_chart: this.snapshotChartType,
                // Choropleth builds its own timeline from all data; other charts use single period
                time_dim: isChoropleth ? setup.timeDim : null,
                x_axis_dim: setup.snapXDim,
                series_dim: isChoropleth ? null : setup.snapSeriesDim,
                geo_dim: isChoropleth ? setup.geoDim : null,
            };
            // Choropleth needs all time periods for its internal timeline
            // Also: choropleth must use untranslated data — geo names must match GeoJSON features
            const chartData = isChoropleth ? this.data : filteredData;

            const chart = await createChart(container, cfg, isChoropleth ? chartData : this._translateData(chartData), this.metadata);
            if (chart) {
                chart._snapshotPanel = true;
                this.charts.push(chart);
            }
        } catch (err) {
            container.innerHTML = `<div class="chart-loading" style="color:var(--red)">Chart error: ${err.message}</div>`;
        }
    }

    disposeCharts() {
        this.stopPlay();
        for (const c of this.charts) {
            if (c && !c.isDisposed()) c.dispose();
        }
        this.charts = [];
    }

    // --- Sidebar ------------------------------------------------------------
    initSidebar() {
        const toggle = document.getElementById('sidebar-toggle');
        const sidebar = document.getElementById('lens-sidebar');
        const close = document.getElementById('sidebar-close');
        const filterInput = document.getElementById('sidebar-search-input');

        toggle?.addEventListener('click', () => this.toggleSidebar());
        close?.addEventListener('click', () => this.closeSidebar());

        filterInput?.addEventListener('input', e => this.filterSidebar(e.target.value.toLowerCase()));

        // Restore from session
        if (sessionStorage.getItem('lensNavOpen') === '1') {
            this.openSidebar(true);
        }

        // Update i18n text
        document.getElementById('sidebar-title').textContent = this.ui.sidebarTitle;
        filterInput.placeholder = this.ui.sidebarFilter;
    }

    openSidebar(load = true) {
        const sidebar = document.getElementById('lens-sidebar');
        const toggle = document.getElementById('sidebar-toggle');
        sidebar.classList.remove('hidden');
        toggle.classList.add('active');
        document.body.classList.add('sidebar-open');
        sessionStorage.setItem('lensNavOpen', '1');

        // Lazy-load tree
        if (load && !this._sidebarLoaded) {
            this.renderSidebar();
        }

        // Resize charts to account for narrower main
        requestAnimationFrame(() => {
            for (const c of this.charts) {
                if (c && !c.isDisposed()) c.resize();
            }
        });
    }

    closeSidebar() {
        const sidebar = document.getElementById('lens-sidebar');
        const toggle = document.getElementById('sidebar-toggle');
        sidebar.classList.add('hidden');
        toggle.classList.remove('active');
        document.body.classList.remove('sidebar-open');
        sessionStorage.setItem('lensNavOpen', '');

        requestAnimationFrame(() => {
            for (const c of this.charts) {
                if (c && !c.isDisposed()) c.resize();
            }
        });
    }

    toggleSidebar() {
        const sidebar = document.getElementById('lens-sidebar');
        if (sidebar.classList.contains('hidden')) {
            this.openSidebar(true);
        } else {
            this.closeSidebar();
        }
    }

    async renderSidebar() {
        this._sidebarLoaded = true;
        const tree = document.getElementById('sidebar-tree');
        tree.innerHTML = '<div class="sb-loading">Loading...</div>';

        try {
            if (!this.categories) {
                const resp = await API.getCategories({ lang: this.lang });
                this.categories = resp.tree;
            }

            tree.innerHTML = '';
            for (const cat of this.categories) {
                this._buildSidebarSection(cat, tree);
            }

            // Highlight current dataset if dashboard is open
            const code = new URLSearchParams(location.search).get('code');
            if (code) this.highlightSidebarDataset(code);

        } catch (err) {
            tree.innerHTML = `<div class="sb-loading">Error: ${err.message}</div>`;
        }
    }

    _buildSidebarSection(cat, container) {
        // L1 section header
        const section = document.createElement('div');
        section.className = 'sb-section';
        section.textContent = this.shortName(cat.name, 40);
        container.appendChild(section);

        // L2 children
        if (cat.children?.length) {
            for (const sub of cat.children) {
                this._buildSidebarItem(sub, container, 2);
            }
        }
    }

    _buildSidebarItem(cat, container, level) {
        const hasChildren = cat.children?.length > 0 || cat.dataset_count > 0 || cat.total_datasets > 0;

        const item = document.createElement('div');
        item.className = 'sb-item';
        item.dataset.level = level;
        item.dataset.code = cat.code;

        if (hasChildren) {
            const arrow = document.createElement('span');
            arrow.className = 'sb-arrow';
            arrow.textContent = '▶';
            item.appendChild(arrow);
        }

        const label = document.createElement('span');
        label.textContent = this.shortName(cat.name, 38 - level * 4);
        item.appendChild(label);

        const count = document.createElement('span');
        count.className = 'sb-count';
        count.textContent = cat.total_datasets || cat.dataset_count || '';
        item.appendChild(count);

        container.appendChild(item);

        // Children container (collapsed by default)
        const childWrap = document.createElement('div');
        childWrap.className = 'sb-children';
        container.appendChild(childWrap);

        if (!hasChildren) return;

        item.addEventListener('click', async () => {
            const isOpen = childWrap.classList.contains('open');
            if (isOpen) {
                childWrap.classList.remove('open');
                item.querySelector('.sb-arrow')?.classList.remove('open');
            } else {
                childWrap.classList.add('open');
                item.querySelector('.sb-arrow')?.classList.add('open');

                // Populate if not already done
                if (childWrap.children.length === 0) {
                    if (cat.children?.length) {
                        for (const sub of cat.children) {
                            this._buildSidebarItem(sub, childWrap, level + 1);
                        }
                    } else {
                        // Leaf category — load datasets
                        await this._loadSidebarDatasets(cat.code, childWrap);
                    }
                    // Re-highlight after loading
                    const code = new URLSearchParams(location.search).get('code');
                    if (code) this.highlightSidebarDataset(code);
                }
            }
        });
    }

    async _loadSidebarDatasets(contextCode, container) {
        container.innerHTML = '<div class="sb-loading">Loading...</div>';
        try {
            const result = await API.getDatasets({ context: contextCode, limit: 200, lang: this.lang });
            container.innerHTML = '';
            const datasets = result.datasets || result.items || [];
            for (const ds of datasets) {
                const dsItem = document.createElement('div');
                dsItem.className = 'sb-item';
                dsItem.dataset.level = '4';
                dsItem.dataset.dsCode = ds.matrix_code;

                const label = document.createElement('span');
                label.textContent = ds.matrix_name || ds.matrix_code;
                label.title = label.textContent;
                dsItem.appendChild(label);

                const code = document.createElement('span');
                code.className = 'sb-code';
                code.textContent = ds.matrix_code;
                dsItem.appendChild(code);

                dsItem.addEventListener('click', e => {
                    e.stopPropagation();
                    this.showDashboard(ds.matrix_code);
                });
                container.appendChild(dsItem);
            }
        } catch (err) {
            container.innerHTML = `<div class="sb-loading">Error</div>`;
        }
    }

    highlightSidebarDataset(code) {
        // Remove previous active state
        for (const el of document.querySelectorAll('#sidebar-tree .sb-item.active')) {
            el.classList.remove('active');
        }
        if (!code) return;

        // Find dataset item and mark active + auto-open parents
        const dsItem = document.querySelector(`#sidebar-tree .sb-item[data-ds-code="${code}"]`);
        if (dsItem) {
            dsItem.classList.add('active');
            // Expand parent sb-children containers
            let parent = dsItem.parentElement;
            while (parent && parent.id !== 'sidebar-tree') {
                if (parent.classList.contains('sb-children')) {
                    parent.classList.add('open');
                    const prevSibling = parent.previousElementSibling;
                    prevSibling?.querySelector('.sb-arrow')?.classList.add('open');
                }
                parent = parent.parentElement;
            }
            requestAnimationFrame(() => dsItem.scrollIntoView({ block: 'nearest', behavior: 'smooth' }));
        }
    }

    filterSidebar(query) {
        const items = document.querySelectorAll('#sidebar-tree .sb-item[data-level="4"]');
        for (const item of items) {
            const text = (item.textContent || '').toLowerCase();
            const match = !query || text.includes(query);
            item.style.display = match ? '' : 'none';
        }
        // If query, open all children so results are visible
        if (query) {
            for (const el of document.querySelectorAll('#sidebar-tree .sb-children')) {
                el.classList.add('open');
            }
            for (const el of document.querySelectorAll('#sidebar-tree .sb-arrow')) {
                el.classList.add('open');
            }
        }
    }

    // --- Value translation (EN mode) ----------------------------------------
    /**
     * Build a per-column lookup: { col_name → { sdmx_value → en_label } }
     * Used to translate parquet row values for display (table + charts).
     * Only populated when lang=en. Time dimensions are skipped (years are universal).
     */
    buildValueMap() {
        this.valueMap = {};
        if (this.lang !== 'en' || !this.metadata) return;
        for (const dim of this.metadata.dimensions) {
            if (dim.dim_type === 'time') continue;  // "1990" is clearer than "Year 1990" on axes
            const map = {};
            for (const opt of dim.options) {
                if (opt.sdmx_value != null && opt.label) {
                    map[String(opt.sdmx_value)] = opt.label;
                }
            }
            if (Object.keys(map).length) this.valueMap[dim.dim_column_name] = map;
        }
    }

    /**
     * Return a display copy of `data` with row values translated to the current language.
     * Column names (SDMX codes) are unchanged so internal logic that indexes by column
     * name continues to work. Only the values visible to the user are translated.
     */
    _translateData(data) {
        if (!data || this.lang !== 'en' || !this.valueMap || !Object.keys(this.valueMap).length) {
            return data;
        }
        const colMaps = data.columns.map(col => this.valueMap[col] || null);
        if (!colMaps.some(Boolean)) return data;
        return {
            ...data,
            rows: data.rows.map(row =>
                row.map((val, i) => {
                    const m = colMaps[i];
                    return m ? (m[String(val)] ?? val) : val;
                })
            ),
        };
    }

    // --- Data Table ---------------------------------------------------------
    initTableToggle() {
        const btn = document.getElementById('table-toggle-btn');
        const closeBtn = document.getElementById('table-close-btn');
        btn?.addEventListener('click', () => this.toggleTable());
        closeBtn?.addEventListener('click', () => this.hideTable());
        this._tableSortCol = null;
        this._tableSortAsc = true;
    }

    showTableToggleRow() {
        document.getElementById('table-toggle-row')?.classList.add('visible');
    }

    hideTableToggleRow() {
        document.getElementById('table-toggle-row')?.classList.remove('visible');
        this.hideTable();
    }

    toggleTable() {
        const panel = document.getElementById('table-panel');
        if (panel.classList.contains('hidden')) {
            this.showTable();
        } else {
            this.hideTable();
        }
    }

    showTable() {
        const panel = document.getElementById('table-panel');
        const btn = document.getElementById('table-toggle-btn');
        const label = document.getElementById('table-toggle-label');
        panel.classList.remove('hidden');
        btn.classList.add('active');
        if (label) label.textContent = this.ui.hideTable || 'Hide data table';
        this.renderTable();
    }

    hideTable() {
        const panel = document.getElementById('table-panel');
        const btn = document.getElementById('table-toggle-btn');
        const label = document.getElementById('table-toggle-label');
        panel.classList.add('hidden');
        btn?.classList.remove('active');
        if (label) label.textContent = this.ui.showTable || 'Show data table';
    }

    renderTable() {
        if (!this.data) return;
        const display = this._translateData(this.data);
        const { columns, rows, truncated, returned_rows, total_rows } = display;
        const scroll = document.getElementById('table-scroll');
        const countEl = document.getElementById('table-row-count');

        if (!rows || !rows.length) {
            scroll.innerHTML = `<div class="table-truncated">${this.ui.noDataFilters}</div>`;
            return;
        }

        // Build human-readable column headers (use dim_label when available)
        const dimLabelMap = {};
        if (this.metadata?.dimensions) {
            for (const d of this.metadata.dimensions) {
                dimLabelMap[d.dim_column_name] = d.dim_label;
            }
        }
        const colHeaders = columns.map(col => {
            if (col === 'OBS_VALUE') return this.lang === 'en' ? 'Value' : 'Valoare';
            return dimLabelMap[col] || col;
        });

        // Sort
        let sortedRows = [...rows];
        if (this._tableSortCol !== null) {
            const idx = this._tableSortCol;
            const asc = this._tableSortAsc;
            sortedRows.sort((a, b) => {
                const va = a[idx], vb = b[idx];
                if (va == null) return 1;
                if (vb == null) return -1;
                return asc ? (va > vb ? 1 : va < vb ? -1 : 0) : (va < vb ? 1 : va > vb ? -1 : 0);
            });
        }

        const obsIdx = columns.indexOf('OBS_VALUE');

        const th = colHeaders.map((lbl, i) => {
            const arrow = this._tableSortCol === i
                ? `<span class="sort-arrow">${this._tableSortAsc ? '↑' : '↓'}</span>` : '';
            return `<th data-col="${i}">${lbl}${arrow}</th>`;
        }).join('');

        const trs = sortedRows.map(row => {
            const tds = row.map((val, i) => {
                if (i === obsIdx) {
                    const fmt = val == null ? '–' : formatNumber(val, val % 1 === 0 ? 0 : 2);
                    return `<td class="num">${fmt}</td>`;
                }
                return `<td>${val ?? '–'}</td>`;
            }).join('');
            return `<tr>${tds}</tr>`;
        }).join('');

        scroll.innerHTML = `
            <table class="data-table">
                <thead><tr>${th}</tr></thead>
                <tbody>${trs}</tbody>
            </table>
            ${truncated ? `<div class="table-truncated">Showing ${formatNumber(returned_rows || rows.length, 0)} of ${formatNumber(total_rows || rows.length, 0)} rows</div>` : ''}
        `;

        if (countEl) countEl.textContent = `${formatNumber(rows.length, 0)} rows`;

        // Column sort click handlers
        scroll.querySelectorAll('th[data-col]').forEach(th => {
            th.addEventListener('click', () => {
                const col = +th.dataset.col;
                if (this._tableSortCol === col) {
                    this._tableSortAsc = !this._tableSortAsc;
                } else {
                    this._tableSortCol = col;
                    this._tableSortAsc = true;
                }
                this.renderTable();
            });
        });
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
            `<div class="search-empty">${this.ui.searchEmpty}</div>`;
    }

    closeSearch() {
        document.getElementById('search-overlay').classList.add('hidden');
    }

    async onSearchInput(query) {
        const results = document.getElementById('search-results');
        if (!query || query.length < 2) {
            results.innerHTML = `<div class="search-empty">${this.ui.searchEmpty}</div>`;
            this.searchIdx = -1;
            return;
        }

        try {
            const resp = await API.getDatasets({ q: query, limit: 12, lang: this.lang });
            results.innerHTML = '';
            this.searchIdx = -1;

            if (resp.datasets.length === 0) {
                results.innerHTML = `<div class="search-empty">${this.ui.searchNoResults}</div>`;
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
            results.innerHTML = `<div class="search-empty">${this.ui.searchError}</div>`;
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
