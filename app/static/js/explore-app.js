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
        browseTitle: 'Date statistice România',
        browseSub: (n, obs) => `${n} seturi de date · ${obs} observații`,
        browseTagline: 'Tempo INS, da nițel mai drăgu\'',
        noticeText: 'Versiune alfa / preview. Acesta nu este un proiect oficial al Guvernului României. Date preluate de pe <a href="http://statistici.insse.ro:8077/tempo-online/" target="_blank">insse.ro</a>.',
        recentlyUpdated: 'Actualizate recent',
        categoriesLabel: 'Categorii tematice',
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
        indexMode: 'Index',
        yoyMode: 'Δ%',
        rankMode: 'Rang',
        indexTooltip: 'Perioadă de bază = 100',
        yoyTooltip: 'Variație anuală %',
        yearlyMode: 'Anual',
        yearlyTooltip: 'Grupează datele pe ani',
        zoomPresets: ['1A', '3A', '5A', 'Tot'],
        distribution: 'Distribuție',
        aboutLink: 'Despre',
        aboutTitle: 'Despre INS+',
        aboutContent: `
   
            <p><b>INS+</b> (n-am găsit încă altă rimă) este un explorator de date statistice oficiale ale României, construit pe baza datelor publice disponibile prin <a href="http://statistici.insse.ro:8077/tempo-online/" target="_blank" rel="noopener">INS TEMPO Online</a> — platforma Institutului Național de Statistică.</p>
            <p><b>Disclaimer</b>: proiectul este la nivelul alfa / prototip, încă n-a trecut printr-un control riguros al calității datelor. Cu alte cuvinte, mai avem câte una alta de făcut până la lansare.</p>
            <p>Aplauze, sugestii sau dojene: <a href="mailto:cancelarie@gov2.ro">cancelarie@gov2.ro</a> sau, și mai bine: github &rarr; <a href="https://github.com/gov2-ro/tempo-ins-dump/issues/new" target="_blank" rel="noopener">gov2-ro/tempo-ins-dump</a>.</p>
            <img src="img/tempo-ins.png" alt="Tempo online" style="max-width:100%; border-radius:8px; margin:16px 0;"><div style="font-size: 4rem; text-align: center;">🤷🏻‍♀️ 🏋🏻‍♀️ 🧚‍♂️ ✨ </div>
        `,
    },
    en: {
        browseTitle: 'Romanian Statistical Data',
        browseSub: (n, obs) => `${n} datasets · ${obs} observations`,
        browseTagline: 'Tempo INS, but nicer',
        noticeText: 'Alpha/preview. This is not an official Romanian Government project. Data sourced from <a href="https://insse.ro" target="_blank">insse.ro</a>.',
        recentlyUpdated: 'Recently updated',
        categoriesLabel: 'Thematic categories',
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
        indexMode: 'Index',
        yoyMode: 'Δ%',
        rankMode: 'Rank',
        indexTooltip: 'Base period = 100',
        yoyTooltip: 'Year-over-year %',
        yearlyMode: 'Yearly',
        yearlyTooltip: 'Group data by year',
        zoomPresets: ['1Y', '3Y', '5Y', 'All'],
        distribution: 'Distribution',
        aboutLink: 'About',
        aboutTitle: 'About INS+',
        aboutContent: `
            <h2>About INS+</h2>
            <p>INS+ is an explorer for Romania's official statistical data, built on public data from <a href="http://statistici.insse.ro:8077/tempo-online/" target="_blank" rel="noopener">INS TEMPO Online</a> — the platform of Romania's National Institute of Statistics.</p>
            <p><b>Disclaimer</b>: this is work in progress, the features and data have not undergone a proper quality check yet.</p>

         <p>Contact: <a href="mailto:cancelarie@gov2.ro">cancelarie@gov2.ro</a> or <a href="https://github.com/gov2-ro/tempo-ins-dump/" target="_blank" rel="noopener">github.com/gov2-ro/tempo-ins-dump</a>.</p>
            <img src="img/tempo-ins.png" alt="Tempo online" style="max-width:100%; border-radius:8px; margin:16px 0;">
            <div style="font-size: 4rem; text-align: center;">🤷🏻‍♀️ 🏋🏻‍♀️ 🧚‍♂️ ✨ </div>
        `,
    },
};

// ---------------------------------------------------------------------------
// Flag data URIs (Romania + UK) — same as duckdb-browser
// ---------------------------------------------------------------------------
const FLAG_DATA = {
    ro: 'data:image/svg+xml,%3Csvg xmlns%3D%22http%3A%2F%2Fwww.w3.org%2F2000%2Fsvg%22 height%3D%22512%22 width%3D%22512%22%3E%3Cg fill-rule%3D%22evenodd%22 stroke-width%3D%221pt%22%3E%3Cpath fill%3D%22%2300319c%22 d%3D%22M0 0h170.666v512H0z%22%2F%3E%3Cpath fill%3D%22%23ffde00%22 d%3D%22M170.666 0h170.666v512H170.666z%22%2F%3E%3Cpath fill%3D%22%23de2110%22 d%3D%22M341.332 0h170.665v512H341.332z%22%2F%3E%3C%2Fg%3E%3C%2Fsvg%3E',
    en: 'data:image/svg+xml,%3Csvg xmlns%3D%22http%3A%2F%2Fwww.w3.org%2F2000%2Fsvg%22 viewBox%3D%220 0 60 60%22%3E%3Crect width%3D%2260%22 height%3D%2260%22 fill%3D%22%23012169%22%2F%3E%3Cpath d%3D%22M0%200l60%2060M60%200L0%2060%22 stroke%3D%22%23fff%22 stroke-width%3D%2212%22%2F%3E%3Cpath d%3D%22M0%200l60%2060M60%200L0%2060%22 stroke%3D%22%23C8102E%22 stroke-width%3D%228%22%2F%3E%3Cpath d%3D%22M30%200v60M0%2030h60%22 stroke%3D%22%23fff%22 stroke-width%3D%2220%22%2F%3E%3Cpath d%3D%22M30%200v60M0%2030h60%22 stroke%3D%22%23C8102E%22 stroke-width%3D%2212%22%2F%3E%3C%2Fsvg%3E',
};

// ---------------------------------------------------------------------------
// Theme icons (emojis)
// ---------------------------------------------------------------------------
const THEME_ICONS = {
    'briefcase': '💼',
    'trending-up': '📈',
    'users': '👥',
    'compass': '🧭',
    'heart': '❤️',
    'book': '📚',
    'leaf': '🌿',
    'factory': '🏭',
};

// Category images (mapped by top-level code) — PNGs in /img/themes/
// Note: '3' (Finances) and '4' (Justice) have no matching icon yet
const CATEGORY_IMGS = {
    '1': '1 society.png',                      // A. STATISTICA SOCIALA
    '2': '2 economy.png',                      // B. STATISTICA ECONOMICA
    '5': '4 environment.png',                  // E. MEDIU INCONJURATOR
    '6': '6 transport.png',                    // F. UTILITATI PUBLICE
    '7': '7 sustainable development.png',      // G. DEZVOLTARE DURABILA 2020
    '8': '7 sustainable development.png',      // H. DEZVOLTARE DURABILA 2030
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

function _exportPng(chart, filename) {
    const url = chart.getDataURL({ type: 'png', pixelRatio: 2, backgroundColor: 'transparent' });
    const a = document.createElement('a');
    a.href = url; a.download = `${filename}.png`; a.click();
}


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
        this.timeTransform = null;         // null | 'index' | 'yoy'

        // Drill filter/sort state
        this.drillSort = 'updated';
        this.drillFilters = {};  // { granularity, has_geo, has_gender, has_age }

        // Sidebar state
        this._sidebarLoaded = false;

        // Theme, language & view mode from localStorage
        const savedTheme = localStorage.getItem('lens_theme');
        const osPrefersDark = window.matchMedia('(prefers-color-scheme: dark)').matches;
        this.theme = savedTheme || (osPrefersDark ? 'dark' : 'light');
        const urlLang = new URLSearchParams(window.location.search).get('lang');
        this.lang = (urlLang === 'en' || urlLang === 'ro') ? urlLang : (localStorage.getItem('lens_lang') || 'ro');
        this.dsViewMode = localStorage.getItem('lens_ds_view') || 'grid';

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
        // Footer notice is always shown, independent of notice bar state
        const footerNotice = document.getElementById('footer-notice');
        if (footerNotice) footerNotice.innerHTML = this.ui.noticeText;
        const params = new URLSearchParams(location.search);
        const code = params.get('code');
        const page = params.get('page');
        // URL-restored dashboard state (consumed on first showDashboard call)
        this._urlTChart  = params.get('tchart') || null;
        this._urlSChart  = params.get('schart') || null;
        this._urlPeriod  = params.get('period') || null;
        this._urlTAgg    = params.get('tagg');   // '0' = yearly-agg explicitly off
        this._urlTZoom   = params.get('tzoom') || null;  // '1y'|'3y'|'5y'|'all'
        const tmode = params.get('tmode');
        if (tmode === 'index' || tmode === 'yoy') this.timeTransform = tmode;
        this._urlFilters = {};
        try { const f = params.get('filters'); if (f) this._urlFilters = JSON.parse(f); } catch {}
        this._urlCat = params.get('cat') || null;
        // Restore drill sort/filters from URL
        const urlSort = params.get('sort');
        if (urlSort && ['updated','name','rows','dims','options'].includes(urlSort)) this.drillSort = urlSort;
        const urlGran = params.get('gran');
        if (urlGran) this.drillFilters.granularity = urlGran;
        if (params.get('has_geo') === 'true') this.drillFilters.has_geo = true;
        if (params.get('has_gender') === 'true') this.drillFilters.has_gender = true;
        if (params.get('has_age') === 'true') this.drillFilters.has_age = true;
        const lnk = document.getElementById('about-link');
        if (lnk) lnk.textContent = this.ui.aboutLink;
        if (page === 'about') {
            this.showAbout();
        } else if (code) {
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

        // About link + button (SPA — prevent full reload)
        document.getElementById('about-link').addEventListener('click', e => {
            e.preventDefault();
            this.showAbout();
        });
        document.getElementById('about-btn').addEventListener('click', () => this.showAbout());
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

        // Dataset view toggle (grid/list)
        const viewToggle = document.getElementById('view-toggle');
        if (viewToggle) {
            this._syncViewToggleIcon();
            viewToggle.addEventListener('click', () => {
                this.dsViewMode = this.dsViewMode === 'grid' ? 'list' : 'grid';
                localStorage.setItem('lens_ds_view', this.dsViewMode);
                this._syncViewToggleIcon();
                // Re-render current dataset list if visible
                const list = document.getElementById('dataset-list');
                if (list && this._lastDrillDatasets) {
                    this._renderDatasetEntries(list, this._lastDrillDatasets);
                }
            });
        }

        this.initSidebar();
        this.initTableToggle();
    }

    _syncViewToggleIcon() {
        const gridIcon = document.querySelector('.view-icon-grid');
        const listIcon = document.querySelector('.view-icon-list');
        if (!gridIcon || !listIcon) return;
        // Show the icon of the mode you'd switch TO
        if (this.dsViewMode === 'grid') {
            gridIcon.classList.add('hidden');
            listIcon.classList.remove('hidden');
        } else {
            gridIcon.classList.remove('hidden');
            listIcon.classList.add('hidden');
        }
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
        const nextLang = this.lang === 'ro' ? 'en' : 'ro';
        document.getElementById('lang-label').textContent = nextLang.toUpperCase();
        const flagEl = document.getElementById('lang-flag');
        if (flagEl) flagEl.src = FLAG_DATA[nextLang] || '';
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
        const footerNotice = document.getElementById('footer-notice');
        if (footerNotice) footerNotice.innerHTML = this.ui.noticeText;
        const aboutLink = document.getElementById('about-link');
        if (aboutLink) aboutLink.textContent = this.ui.aboutLink;
        // Re-render about page if currently shown
        if (!document.getElementById('about-view').classList.contains('hidden')) {
            document.getElementById('about-content').innerHTML = `<div class="about-page">${this.ui.aboutContent}</div>`;
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
    navigate(code, page) {
        const url = new URL(location.href);
        url.searchParams.delete('code');
        url.searchParams.delete('page');
        url.searchParams.delete('cat');
        if (code) url.searchParams.set('code', code);
        if (page) url.searchParams.set('page', page);
        history.pushState({}, '', url);
    }

    // --- About view ---------------------------------------------------------
    showAbout() {
        document.getElementById('page-loader')?.classList.add('hidden');
        this.navigate(null, 'about');
        this.disposeCharts();
        document.getElementById('browse-view').classList.add('hidden');
        document.getElementById('dashboard-view').classList.add('hidden');
        document.getElementById('about-view').classList.remove('hidden');
        document.getElementById('back-btn').classList.remove('hidden');
        document.getElementById('back-btn').textContent = this.ui.backExplore;

        const el = document.getElementById('about-content');
        el.innerHTML = `<div class="about-page">${this.ui.aboutContent}</div>`;
        this._updatePageMeta(null);
        document.title = `${this.ui.aboutTitle} — INS+`;

        // Update footer link label
        const lnk = document.getElementById('about-link');
        if (lnk) lnk.textContent = this.ui.aboutLink;
    }

    // --- Browse view --------------------------------------------------------
    async showBrowse() {
        this.navigate(null);
        this.disposeCharts();
        this.hideTableToggleRow();
        this._updatePageMeta(null);

        document.getElementById('browse-view').classList.remove('hidden');
        document.getElementById('dashboard-view').classList.add('hidden');
        document.getElementById('about-view').classList.add('hidden');
        document.getElementById('back-btn').classList.add('hidden');

        const [catResp, trendsResp, summary] = await Promise.all([
            this.categories ? Promise.resolve(null) : API.getCategories({ lang: this.lang }),
            this.categoryTrends ? Promise.resolve(null) : API.getCategoryTrends(),
            API.getCorpusSummary({ lang: this.lang }),
        ]);
        if (catResp) this.categories = catResp.tree;
        if (trendsResp) this.categoryTrends = trendsResp.trends;


        this.headlines = summary.headlines || [];
        this.renderNoticeBar();
        this.renderBrowseHeader(summary.corpus);
        this.renderHeadlines(this.headlines);
        this.renderRecentlyUpdated(summary.recently_updated);
        const catLabel = document.getElementById('categories-label');
        if (catLabel) catLabel.textContent = this.ui.categoriesLabel;

        document.getElementById('page-loader')?.classList.add('hidden');
        this.showCategoryGrid();
        if (this._urlCat) {
            const target = this._urlCat;
            this._urlCat = null;
            await this._restoreDrillFromUrl(target);
        }
    }

    showCategoryGrid() {
        document.getElementById('category-grid').classList.remove('hidden');
        document.getElementById('dataset-panel').classList.add('hidden');
        document.getElementById('facet-bar')?.classList.add('hidden');
        // Show landing sections (recent-section only if it has content)
        document.getElementById('headlines-section')?.classList.remove('hidden');
        const recentGrid = document.getElementById('recent-grid');
        if (recentGrid && recentGrid.children.length) {
            document.getElementById('recent-section')?.classList.remove('hidden');
        }
        document.getElementById('categories-label')?.classList.remove('hidden');
        this.drillStack = [];

        const grid = document.getElementById('category-grid');
        grid.innerHTML = '';

        this.categories.forEach((cat, i) => {
            const section = document.createElement('div');
            section.className = 'cat-section';

            const imgFile = CATEGORY_IMGS[cat.code];
            const imgTag = imgFile ? `<img class="cat-section-img" src="/img/themes/${encodeURIComponent(imgFile)}" alt="" aria-hidden="true">` : '';
            const header = document.createElement('div');
            header.className = 'cat-section-header';
            header.innerHTML = `
                <div class="cat-section-title">
                    <span class="cat-section-name">${this.shortName(cat.name)}</span>
                    <span class="cat-section-meta"><strong>${cat.total_datasets || 0}</strong> ${this.ui.datasets} · <strong>${cat.children.length}</strong> ${this.ui.subcategories}</span>
                </div>
                ${imgTag}
            `;
            header.addEventListener('click', () => this.drillCategory(cat, i));
            section.appendChild(header);

            if (cat.children.length > 1) {
                const subcats = document.createElement('div');
                subcats.className = 'cat-subcats';

                cat.children.forEach((child, ci) => {
                    const sub = document.createElement('span');
                    sub.className = 'cat-subcat';
                    sub.addEventListener('click', (e) => {
                        e.stopPropagation();
                        this.drillCategory(cat, i);
                        this.drillCategory(child, 0);
                    });
                    sub.innerHTML = `<span class="cat-subcat-name">${this.shortName(child.name)}</span> <span class="cat-subcat-count">(${child.total_datasets})</span>`;
                    subcats.appendChild(sub);
                    if (ci < cat.children.length - 1) {
                        const sep = document.createElement('span');
                        sep.className = 'cat-subcat-sep';
                        sep.textContent = '·';
                        subcats.appendChild(sep);
                    }
                });
                section.appendChild(subcats);
            }

            grid.appendChild(section);
        });
    }

    // --- Landing page sections ------------------------------------------------
    renderNoticeBar() {
        const bar = document.getElementById('notice-bar');
        if (!bar) return;
        if (localStorage.getItem('notice-dismissed')) { bar.classList.add('hidden'); return; }
        document.getElementById('notice-text').innerHTML = this.ui.noticeText;
        bar.classList.remove('hidden');
        document.getElementById('notice-close').onclick = () => {
            bar.classList.add('hidden');
            localStorage.setItem('notice-dismissed', '1');
        };
    }

    renderBrowseHeader(corpus) {
        const title = document.getElementById('browse-title');
        const sub = document.getElementById('browse-subtitle');
        const tagline = document.getElementById('browse-tagline');
        if (title) title.textContent = this.ui.browseTitle;
        if (sub && corpus) {
            sub.innerHTML = this.ui.browseSub(
                formatNumber(corpus.datasets, 0),
                formatNumber(corpus.observations, 0)
            ) + ` · <a href="/dimensions-explorer.html" class="browse-dims-link">${this.lang === 'ro' ? 'Explorează după dimensiuni' : 'Explore by dimension'} →</a>`;
        }
        if (tagline) tagline.textContent = this.ui.browseTagline;
    }

    renderHeadlines(headlines) {
        const container = document.getElementById('headlines-section');
        if (!container || !headlines || !headlines.length) return;
        container.innerHTML = '';

        const grid = document.createElement('div');
        grid.className = 'headlines-grid';

        for (const theme of headlines) {
            const section = document.createElement('div');
            section.className = 'headline-theme';
            section.dataset.cols = String(theme.indicators.length);

            // Theme header with icon + label + arrow → drills into category
            const header = document.createElement('div');
            header.className = 'headline-theme-header';
            header.innerHTML = `
                <span class="headline-theme-icon">${THEME_ICONS[theme.icon] || '📊'}</span>
                <span class="headline-theme-label">${theme.theme_label}</span>
                <span class="headline-theme-arrow">›</span>
            `;
            if (theme.context_code) {
                header.addEventListener('click', () => this._drillToContext(theme.context_code));
            }
            section.appendChild(header);

            const cards = document.createElement('div');
            cards.className = 'headline-cards';

            for (const ind of theme.indicators) {
                const card = document.createElement('div');
                card.className = 'headline-card';
                card.addEventListener('click', () => this.showDashboard(ind.code));

                const changeHtml = ind.change_pct != null
                    ? `<span class="headline-change ${ind.change_pct >= 0 ? 'up' : 'down'}">${ind.change_pct >= 0 ? '↑' : '↓'} ${Math.abs(ind.change_pct).toFixed(1)}%</span>`
                    : '';

                const sparkHtml = this._renderSparkline(ind.sparkline, ind.change_pct);

                card.innerHTML = `
                    ${sparkHtml}
                    <div class="headline-card-info">
                        <div class="headline-label">${ind.label}</div>
                        <div class="headline-value-row">
                            <span class="headline-value">${this._formatHeadlineValue(ind.value, ind.format)}</span>
                            <span class="headline-unit">${ind.unit}</span>
                        </div>
                    </div>
                    <div class="headline-footer">
                        <span class="headline-period">${ind.period}</span>
                        ${changeHtml}
                    </div>
                `;
                cards.appendChild(card);
            }
            section.appendChild(cards);
            grid.appendChild(section);
        }
        container.appendChild(grid);
    }

    _drillToContext(contextCode) {
        // Find the category node matching this context_code and drill into it
        if (!this.categories) return;
        const findCat = (nodes) => {
            for (let i = 0; i < nodes.length; i++) {
                if (nodes[i].code === contextCode) return { cat: nodes[i], idx: i };
                if (nodes[i].children) {
                    const found = findCat(nodes[i].children);
                    if (found) return found;
                }
            }
            return null;
        };
        const result = findCat(this.categories);
        if (result) this.drillCategory(result.cat, result.idx);
    }

    _renderSparkline(data, changePct) {
        if (!data || data.length < 3) return '';
        const fill = changePct != null ? (changePct >= 0 ? 'var(--green)' : 'var(--red)') : 'var(--text-3)';
        const min = Math.min(...data);
        const max = Math.max(...data);
        const range = max - min || 1;
        const w = 100, h = 30, pad = 1;
        const points = data.map((v, i) => {
            const x = pad + (i / (data.length - 1)) * (w - 2 * pad);
            const y = h - pad - ((v - min) / range) * (h - 2 * pad);
            return `${x.toFixed(1)},${y.toFixed(1)}`;
        });
        const polyline = points.join(' ');
        const fillPoly = `${points[0].split(',')[0]},${h} ${polyline} ${points[points.length-1].split(',')[0]},${h}`;
        return `<svg class="headline-sparkline" viewBox="0 0 ${w} ${h}" preserveAspectRatio="none">
            <polygon points="${fillPoly}" fill="${fill}" />
            <polyline points="${polyline}" />
        </svg>`;
    }

    _formatHeadlineValue(value, format) {
        if (value == null) return '—';
        switch (format) {
            case 'currency':
                return formatNumber(value, value >= 10 ? 0 : 1);
            case 'percent':
                return value.toFixed(1) + '%';
            case 'index':
                return value.toFixed(1);
            case 'number':
            default:
                if (Math.abs(value) >= 1_000_000) return (value / 1_000_000).toFixed(1) + ' mil.';
                if (Math.abs(value) >= 10_000) return formatNumber(Math.round(value), 0);
                return formatNumber(value, value % 1 === 0 ? 0 : 1);
        }
    }

    renderRecentlyUpdated(datasets) {
        const section = document.getElementById('recent-section');
        const label = document.getElementById('recent-label');
        const grid = document.getElementById('recent-grid');
        if (!section || !grid || !datasets || !datasets.length) return;

        label.textContent = this.ui.recentlyUpdated;
        grid.innerHTML = '';

        for (const ds of datasets) {
            const card = document.createElement('div');
            card.className = 'recent-card';
            card.addEventListener('click', () => this.showDashboard(ds.matrix_code));

            let trendHtml = '';
            if (ds.trend_direction === 'increasing' || (ds.yoy_growth_latest != null && ds.yoy_growth_latest > 0)) {
                trendHtml = `<span class="recent-trend up">↑${ds.yoy_growth_latest != null ? ' ' + Math.abs(ds.yoy_growth_latest).toFixed(1) + '%' : ''}</span>`;
            } else if (ds.trend_direction === 'decreasing' || (ds.yoy_growth_latest != null && ds.yoy_growth_latest < 0)) {
                trendHtml = `<span class="recent-trend down">↓${ds.yoy_growth_latest != null ? ' ' + Math.abs(ds.yoy_growth_latest).toFixed(1) + '%' : ''}</span>`;
            } else {
                trendHtml = `<span class="recent-trend flat">→</span>`;
            }

            const excerptHtml = ds.excerpt
                ? `<div class="recent-excerpt">${ds.excerpt}</div>`
                : '';

            card.innerHTML = `
                <div class="recent-card-top">
                    <div class="recent-info">
                        <div class="recent-name">${ds.matrix_name}</div>
                        <div class="recent-meta">${ds.matrix_code} · ${ds.ultima_actualizare || ''}</div>
                    </div>
                    ${trendHtml}
                </div>
                ${excerptHtml}
            `;
            grid.appendChild(card);
        }
        section.classList.remove('hidden');
    }

    async renderThemeStats(code) {
        const container = document.getElementById('theme-stats');
        if (!container) return;
        container.classList.add('hidden');
        try {
            const data = await API.getCategorySummary(code, { lang: this.lang });
            if (!data || !data.datasets) { container.classList.add('hidden'); return; }

            const timeSpan = data.time_span ? `${data.time_span.min}–${data.time_span.max}` : '—';
            const trends = data.trends || {};
            const trendTotal = (trends.up || 0) + (trends.down || 0) + (trends.flat || 0) + (trends.volatile || 0);
            const trendLabel = trendTotal ? `↑${trends.up || 0} ↓${trends.down || 0}` : '—';

            container.innerHTML = `
                <div class="theme-stat-card">
                    <div class="theme-stat-value">${formatNumber(data.datasets, 0)}</div>
                    <div class="theme-stat-label">${this.ui.datasets}</div>
                </div>
                <div class="theme-stat-card">
                    <div class="theme-stat-value">${data.observations ? formatNumber(data.observations, 0) : '—'}</div>
                    <div class="theme-stat-label">${this.lang === 'ro' ? 'observații' : 'observations'}</div>
                </div>
                <div class="theme-stat-card">
                    <div class="theme-stat-value">${timeSpan}</div>
                    <div class="theme-stat-label">${this.lang === 'ro' ? 'interval' : 'time span'}</div>
                </div>
                <div class="theme-stat-card">
                    <div class="theme-stat-value">${trendLabel}</div>
                    <div class="theme-stat-label">${this.lang === 'ro' ? 'tendințe' : 'trends'}</div>
                </div>
            `;
            container.classList.remove('hidden');
        } catch (e) {
            container.classList.add('hidden');
        }
    }

    renderThemeHeadlines(contextCode) {
        const container = document.getElementById('theme-headlines');
        if (!container) return;
        // Find matching theme by context_code
        const theme = (this.headlines || []).find(t => t.context_code === contextCode);
        if (!theme || !theme.indicators || !theme.indicators.length) {
            container.classList.add('hidden');
            return;
        }
        const cards = document.createElement('div');
        cards.className = 'headline-cards';
        for (const ind of theme.indicators) {
            const card = document.createElement('div');
            card.className = 'headline-card';
            card.addEventListener('click', (e) => { e.stopPropagation(); this.showDashboard(ind.code); });
            const changeHtml = ind.change_pct != null
                ? `<span class="headline-change ${ind.change_pct >= 0 ? 'up' : 'down'}">${ind.change_pct >= 0 ? '↑' : '↓'} ${Math.abs(ind.change_pct).toFixed(1)}%</span>`
                : '';
            const sparkHtml = this._renderSparkline(ind.sparkline, ind.change_pct);
            card.innerHTML = `
                ${sparkHtml}
                <div class="headline-card-info">
                    <div class="headline-label">${ind.label}</div>
                    <div class="headline-value-row">
                        <span class="headline-value">${this._formatHeadlineValue(ind.value, ind.format)}</span>
                        <span class="headline-unit">${ind.unit}</span>
                    </div>
                </div>
                <div class="headline-footer">
                    <span class="headline-period">${ind.period}</span>
                    ${changeHtml}
                </div>
            `;
            cards.appendChild(card);
        }
        container.innerHTML = '';
        container.appendChild(cards);
        container.classList.remove('hidden');
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

    /** Recursive search for a category by code in the loaded categories tree. */
    _findCategoryByCode(code, tree = null) {
        const cats = tree || this.categories || [];
        for (const cat of cats) {
            if (cat.code === code) return cat;
            if (cat.children?.length) {
                const found = this._findCategoryByCode(code, cat.children);
                if (found) return found;
            }
        }
        return null;
    }

    /** Restore drill stack from a colon-separated cat URL param (e.g. "E:E1"). */
    async _restoreDrillFromUrl(catPath) {
        const codes = catPath.split(':').filter(Boolean);
        if (!codes.length) return;
        this.drillStack = [];
        for (let i = 0; i < codes.length - 1; i++) {
            const cat = this._findCategoryByCode(codes[i]);
            if (cat) this.drillStack.push({ cat, colorIdx: 0 });
        }
        const lastCat = this._findCategoryByCode(codes[codes.length - 1]);
        if (lastCat) await this.drillCategory(lastCat, 0, false);
    }

    async drillCategory(cat, colorIdx, pushToStack = true) {
        if (pushToStack) this.drillStack.push({ cat, colorIdx });

        // Sync drill path to URL (replaceState — no history spam)
        const catPath = this.drillStack.map(e => e.cat.code).join(':');
        const _url = new URL(location.href);
        _url.searchParams.delete('code');
        _url.searchParams.delete('page');
        _url.searchParams.set('cat', catPath);
        history.replaceState(null, '', _url);

        // Update page title + meta tags for category
        this._updatePageMeta({ type: 'category', cat, catPath });

        // Hide landing-page-only sections
        document.getElementById('headlines-section')?.classList.add('hidden');
        document.getElementById('recent-section')?.classList.add('hidden');
        document.getElementById('categories-label')?.classList.add('hidden');

        document.getElementById('category-grid').classList.add('hidden');
        const panel = document.getElementById('dataset-panel');
        panel.classList.remove('hidden');
        document.getElementById('panel-back').textContent =
            this.drillStack.length > 1 ? '← ' + this.drillStack[this.drillStack.length - 2].cat.name : this.ui.backCategories;
        document.getElementById('panel-title').textContent = cat.name;
        document.getElementById('panel-count').textContent = `${cat.total_datasets || 0} ${this.ui.datasets}`;

        this.renderBreadcrumbs();
        this.renderFacetBar();
        this.renderThemeStats(cat.code);
        this.renderThemeHeadlines(cat.code);

        const list = document.getElementById('dataset-list');
        list.innerHTML = '<div class="skeleton" style="height:200px;margin:8px 0"></div>';

        // Fetch datasets for this category (use ancestor filter, respecting current sort/filters)
        const resp = await API.getDatasets({
            ancestor: cat.code, limit: 100,
            sort: this.drillSort, lang: this.lang,
            ...this.drillFilters,
        });
        list.innerHTML = '';

        // Show subcategory cards first (if any)
        if (cat.children && cat.children.length > 0) {
            const subcatGrid = document.createElement('div');
            subcatGrid.className = 'subcat-grid';
            for (const child of cat.children) {
                const trend = this.categoryTrends?.[child.code];
                let trendHtml = '';
                if (trend && trend.total) {
                    const yoy = trend.avg_yoy;
                    if (yoy != null) {
                        const cls = yoy >= 0 ? 'up' : 'down';
                        trendHtml = `<span class="subcat-trend ${cls}">${yoy >= 0 ? '↑' : '↓'} ${Math.abs(yoy).toFixed(1)}%</span>`;
                    }
                }
                const card = document.createElement('div');
                card.className = 'subcat-card';
                card.addEventListener('click', () => this.drillCategory(child, colorIdx));
                card.innerHTML = `
                    <span class="subcat-name">${child.name}</span>
                    <span class="subcat-meta">
                        <span class="subcat-count">${child.total_datasets || 0} ${this.ui.datasets}</span>
                        ${trendHtml}
                    </span>
                `;
                subcatGrid.appendChild(card);
            }
            list.appendChild(subcatGrid);
        }

        if (resp.datasets.length === 0 && (!cat.children || cat.children.length === 0)) {
            list.innerHTML = `<div class="search-empty">${this.ui.noDatasets}</div>`;
            return;
        }

        this._lastDrillDatasets = resp.datasets;
        this._renderDatasetEntries(list, resp.datasets);
    }

    _renderDatasetEntries(list, datasets) {
        // Remove existing dataset entries (keep subcat-grid if present)
        list.querySelectorAll('.ds-row, .ds-grid-card, .ds-grid').forEach(el => el.remove());

        if (this.dsViewMode === 'grid') {
            const grid = document.createElement('div');
            grid.className = 'ds-grid';
            datasets.forEach((ds, i) => {
                const card = document.createElement('div');
                card.className = 'ds-grid-card';
                card.style.animationDelay = `${Math.min(i * 0.02, 0.5)}s`;
                card.addEventListener('click', () => this.showDashboard(ds.matrix_code));
                card.innerHTML = `
                    <span class="ds-grid-code">${ds.matrix_code}</span>
                    <span class="ds-grid-name">${ds.matrix_name}</span>
                    <div class="ds-grid-meta">
                        ${ds.time_range ? `<span class="ds-badge">${ds.time_range}</span>` : ''}
                        ${ds.archetype ? `<span class="ds-badge">${ds.archetype}</span>` : ''}
                        ${ds.row_count ? `<span class="ds-badge">${formatNumber(ds.row_count, 0)} ${this.ui.rows}</span>` : ''}
                    </div>
                `;
                grid.appendChild(card);
            });
            list.appendChild(grid);
        } else {
            datasets.forEach((ds, i) => {
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

    renderFacetBar() {
        const bar = document.getElementById('facet-bar');
        if (!bar) return;
        bar.classList.remove('hidden');
        bar.innerHTML = '';

        const sortOptions = [
            { key: 'updated', label: 'Updated' },
            { key: 'name',    label: 'Name' },
            { key: 'rows',    label: 'Records' },
            { key: 'dims',    label: 'Dims' },
            { key: 'options', label: 'Options' },
        ];

        // Sort pills group
        const sortGroup = document.createElement('div');
        sortGroup.className = 'facet-group';
        const sortLabel = document.createElement('span');
        sortLabel.className = 'facet-label';
        sortLabel.textContent = 'Sort:';
        sortGroup.appendChild(sortLabel);
        sortOptions.forEach(({ key, label }) => {
            const pill = document.createElement('button');
            pill.className = 'sort-pill' + (this.drillSort === key ? ' active' : '');
            pill.textContent = label;
            pill.addEventListener('click', () => {
                this.drillSort = key;
                this._syncDrillUrl();
                const top = this.drillStack[this.drillStack.length - 1];
                if (top) this.drillCategory(top.cat, top.colorIdx, false);
            });
            sortGroup.appendChild(pill);
        });
        bar.appendChild(sortGroup);

        // Separator
        const sep1 = document.createElement('div');
        sep1.className = 'facet-sep';
        bar.appendChild(sep1);

        // Granularity group
        const granGroup = document.createElement('div');
        granGroup.className = 'facet-group';
        const granLabel = document.createElement('span');
        granLabel.className = 'facet-label';
        granLabel.textContent = 'Period:';
        granGroup.appendChild(granLabel);
        [['', 'All'], ['annual', 'Annual'], ['monthly', 'Monthly'], ['quarterly', 'Quarterly']].forEach(([val, label]) => {
            const chip = document.createElement('button');
            const active = (val === '' && !this.drillFilters.granularity) || (val && this.drillFilters.granularity === val);
            chip.className = 'facet-chip' + (active ? ' active' : '');
            chip.textContent = label;
            chip.addEventListener('click', () => {
                if (val) this.drillFilters.granularity = val;
                else delete this.drillFilters.granularity;
                this._syncDrillUrl();
                const top = this.drillStack[this.drillStack.length - 1];
                if (top) this.drillCategory(top.cat, top.colorIdx, false);
            });
            granGroup.appendChild(chip);
        });
        bar.appendChild(granGroup);

        // Separator
        const sep2 = document.createElement('div');
        sep2.className = 'facet-sep';
        bar.appendChild(sep2);

        // Has: toggles group
        const hasGroup = document.createElement('div');
        hasGroup.className = 'facet-group';
        const hasLabel = document.createElement('span');
        hasLabel.className = 'facet-label';
        hasLabel.textContent = 'Has:';
        hasGroup.appendChild(hasLabel);
        [['has_geo', 'Geo'], ['has_gender', 'Gender'], ['has_age', 'Age']].forEach(([key, label]) => {
            const chip = document.createElement('button');
            chip.className = 'facet-chip' + (this.drillFilters[key] ? ' active' : '');
            chip.textContent = label;
            chip.addEventListener('click', () => {
                if (this.drillFilters[key]) delete this.drillFilters[key];
                else this.drillFilters[key] = true;
                this._syncDrillUrl();
                const top = this.drillStack[this.drillStack.length - 1];
                if (top) this.drillCategory(top.cat, top.colorIdx, false);
            });
            hasGroup.appendChild(chip);
        });
        bar.appendChild(hasGroup);

        // Clear all (if any filter active)
        const hasActiveFilters = Object.keys(this.drillFilters).length > 0 || this.drillSort !== 'updated';
        if (hasActiveFilters) {
            const sep3 = document.createElement('div');
            sep3.className = 'facet-sep';
            bar.appendChild(sep3);
            const clear = document.createElement('span');
            clear.className = 'facet-clear';
            clear.textContent = '× Clear';
            clear.addEventListener('click', () => {
                this.drillSort = 'updated';
                this.drillFilters = {};
                this._syncDrillUrl();
                const top = this.drillStack[this.drillStack.length - 1];
                if (top) this.drillCategory(top.cat, top.colorIdx, false);
            });
            bar.appendChild(clear);
        }
    }

    _syncDrillUrl() {
        const url = new URL(location.href);
        if (this.drillSort === 'updated') url.searchParams.delete('sort');
        else url.searchParams.set('sort', this.drillSort);
        if (this.drillFilters.granularity) url.searchParams.set('gran', this.drillFilters.granularity);
        else url.searchParams.delete('gran');
        ['has_geo', 'has_gender', 'has_age'].forEach(k => {
            if (this.drillFilters[k]) url.searchParams.set(k, 'true');
            else url.searchParams.delete(k);
        });
        history.replaceState(null, '', url);
    }

    // --- Dashboard view -----------------------------------------------------
    async showDashboard(code) {
        document.getElementById('page-loader')?.classList.add('hidden');
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
            // Use chart_selector's recommendation for defaults (instead of always 'line')
            // Normalize backend names → frontend names (bar_vertical → bar)
            const _chartAlias = { 'bar_vertical': 'bar' };
            const _ranked = this.chartConfig?.ranked_charts || [];
            const _bestTime = _ranked.find(r => {
                const name = _chartAlias[r.chart_type] || r.chart_type;
                return this.panelSetup.timeChartTypes.includes(name);
            });
            this.timeChartType = _bestTime
                ? (_chartAlias[_bestTime.chart_type] || _bestTime.chart_type)
                : (this.panelSetup.timeChartTypes[0] || 'line');
            const _bestSnap = _ranked.find(r => this.panelSetup.snapshotChartTypes.includes(r.chart_type));
            this.snapshotChartType = _bestSnap ? _bestSnap.chart_type : (this.panelSetup.snapshotChartTypes[0] || null);
            this.selectedPeriodIdx = -1; // latest

            // Yearly aggregation default for monthly/quarterly datasets
            // time_granularity lives in meta.profile (matrix_profiles), not the view profile
            const _gran = this.metadata?.profile?.time_granularity;
            this.timeGranularity = _gran || null;
            this.yearlyAgg = (_gran === 'monthly' || _gran === 'quarterly');
            this.timeZoomPreset = '5y';  // default raw-monthly zoom window

            // Restore URL state (first load only — consumed below)
            const setup = this.panelSetup;
            if (this._urlTChart && setup.timeChartTypes.includes(this._urlTChart))
                this.timeChartType = this._urlTChart;
            if (this._urlSChart && setup.snapshotChartTypes.includes(this._urlSChart))
                this.snapshotChartType = this._urlSChart;
            if (this._urlPeriod) {
                const pidx = setup.periods.findIndex(p => p.id === this._urlPeriod);
                if (pidx >= 0) this.selectedPeriodIdx = pidx;
            }
            if (this._urlTAgg !== null) this.yearlyAgg = this._urlTAgg !== '0';
            if (this._urlTZoom) this.timeZoomPreset = this._urlTZoom;
            this._urlTChart = null;
            this._urlSChart = null;
            this._urlPeriod = null;
            this._urlTAgg = null;
            this._urlTZoom = null;

            this.renderDashHeader();
            this._updatePageMeta(this.metadata);
            this.renderInfoPanel();
            this.renderFilters();
            this.renderTimePanel();
            this.renderSnapshotPanel();
            this.highlightSidebarDataset(code);
            await this.fetchAndRender();
            this._urlFilters = {}; // consume after first render
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
            const crumbs = m.context_path.map((p) => {
                const label = this.shortName(p.name);
                return `<span class="dash-crumb-link" data-code="${p.code}">${label}</span>`;
            });
            pathHtml = `<div class="dash-breadcrumbs">${crumbs.join('<span class="dash-crumb-sep">›</span>')}</div>`;
        }

        const header = document.getElementById('dash-header');
        header.innerHTML = `
            ${pathHtml}
            <div class="dash-title-row">
                <div class="dash-title">
                    ${m.matrix_name}
                    <span class="dash-code">${m.matrix_code}</span>
                </div>
                <div class="dash-download">
                    <a class="dl-btn" href="http://statistici.insse.ro/tempoins/index.jsp?page=tempo3&lang=${this.lang === 'en' ? 'en' : 'ro'}&ind=${m.parent_matrix_code || m.matrix_code}" target="_blank" rel="noopener" title="${this.lang === 'en' ? 'View on INS TEMPO Online' : 'Vezi pe INS TEMPO Online'}">INS ↗</a>
                    <a class="dl-btn" href="/sdmx/2.1/data/INS,${m.matrix_code}/" target="_blank" rel="noopener" title="SDMX-ML 2.1 data feed">SDMX ↗</a>
                    <button class="dl-btn" id="dl-csv-btn">↓ CSV</button>
                    <button class="dl-btn" id="dl-xlsx-btn">↓ XLSX</button>
                </div>
            </div>
            <div class="dash-meta">
                ${cfg.archetype ? `<span class="meta-pill archetype">${cfg.archetype}</span>` : ''}
                ${profile.time_granularity ? `<span class="meta-pill time">${profile.time_granularity}</span>` : ''}
                ${timeRange ? `<span class="meta-pill time">${timeRange}</span>` : ''}
                ${m.row_count ? `<span class="meta-pill rows">${formatNumber(m.row_count, 0)} rows</span>` : ''}
                ${m.ultima_actualizare ? `<span class="meta-pill updated">Updated ${m.ultima_actualizare}</span>` : ''}
            </div>
        `;

        // Download buttons — build URL with current filters and language at click time
        const buildDownloadUrl = (fmt) => {
            const f = JSON.stringify(this.getFilters());
            return `/api/datasets/${m.matrix_code}/download?format=${fmt}&lang=${this.lang}&filters=${encodeURIComponent(f)}`;
        };
        header.querySelector('#dl-csv-btn').addEventListener('click', () => {
            window.location.href = buildDownloadUrl('csv');
        });
        header.querySelector('#dl-xlsx-btn').addEventListener('click', () => {
            window.location.href = buildDownloadUrl('xlsx');
        });

        // Bind breadcrumb clicks → navigate to category drill
        header.querySelectorAll('.dash-crumb-link').forEach(el => {
            el.addEventListener('click', async () => {
                const targetCode = el.dataset.code;
                const pathCodes = [];
                for (const p of m.context_path) {
                    pathCodes.push(p.code);
                    if (p.code === targetCode) break;
                }
                this._urlCat = pathCodes.join(':');
                await this.showBrowse();
            });
        });
    }

    /**
     * Update document.title and meta/OG tags.
     * Pass null to reset to landing-page defaults.
     * Pass { type: 'category', cat, catPath } for category/theme pages.
     * Pass a dataset metadata object for dataset pages.
     */
    _updatePageMeta(m) {
        const setMeta = (sel, val) => {
            const el = document.querySelector(sel);
            if (el) el.setAttribute('content', val);
        };
        const en = this.lang === 'en';
        if (!m) {
            document.title = en ? 'INS+ — Romanian Statistical Data' : 'INS+ — Date statistice România';
            const defDesc = en
                ? 'Explore over 1,900 official Romanian statistical datasets. Labor, economy, demographics, tourism and more — from INS TEMPO Online.'
                : 'Explorați peste 1900 de seturi de date statistice oficiale din România. Cifre pentru forța de muncă, economie, demografie, turism și multe altele — date de la INS Tempo Online, prezentate mai accesibil.';
            const defTitle = en ? 'INS+ Statistical Data' : 'INS+ Date statistice';
            const defShort = en
                ? 'Explore over 1,900 official Romanian statistical datasets.'
                : 'Explorați peste 1900 de seturi de date statistice oficiale din România — cifre pentru forța de muncă, economie, demografie, turism și multe altele.';
            setMeta('meta[name="description"]', defDesc);
            setMeta('meta[property="og:title"]', defTitle);
            setMeta('meta[property="og:description"]', defShort);
            setMeta('meta[property="og:url"]', 'https://ins.gov2.ro/');
            setMeta('meta[name="twitter:title"]', defTitle);
            setMeta('meta[name="twitter:description"]', defShort);
            return;
        }
        if (m.type === 'category') {
            const { cat, catPath } = m;
            const count = cat.total_datasets || 0;
            const pageTitle = en ? `${cat.name} — INS+ Statistics` : `${cat.name} — INS+ Statistici`;
            const description = en
                ? `${count} statistical datasets in category ${cat.name}. Official Romanian data, INS TEMPO Online.`
                : `${count} seturi de date statistice în categoria ${cat.name}. Date oficiale INS România, TEMPO Online.`;
            const pageUrl = `https://ins.gov2.ro/?cat=${encodeURIComponent(catPath)}`;
            document.title = pageTitle;
            setMeta('meta[name="description"]', description);
            setMeta('meta[property="og:title"]', pageTitle);
            setMeta('meta[property="og:description"]', description);
            setMeta('meta[property="og:url"]', pageUrl);
            setMeta('meta[name="twitter:title"]', pageTitle);
            setMeta('meta[name="twitter:description"]', description);
            return;
        }
        const profile = m.profile || {};
        const timeRange = profile.time_year_min && profile.time_year_max
            ? ` (${profile.time_year_min}–${profile.time_year_max})` : '';
        const updatedPart = m.ultima_actualizare
            ? (en ? `. Updated ${m.ultima_actualizare}` : `. Actualizat ${m.ultima_actualizare}`)
            : '';
        const description = en
            ? `INS+ ${m.matrix_code}: ${m.matrix_name}${timeRange}. Official Romanian statistics, INS TEMPO Online${updatedPart}.`
            : `INS+ ${m.matrix_code}: ${m.matrix_name}${timeRange}. Date statistice oficiale România, INS TEMPO Online${updatedPart}.`;
        const pageTitle = `${m.matrix_name} — INS+ ${m.matrix_code}`;
        const pageUrl = `https://ins.gov2.ro/?code=${m.matrix_code}`;

        document.title = pageTitle;
        setMeta('meta[name="description"]', description);
        setMeta('meta[property="og:title"]', pageTitle);
        setMeta('meta[property="og:description"]', description);
        setMeta('meta[property="og:url"]', pageUrl);
        setMeta('meta[name="twitter:title"]', pageTitle);
        setMeta('meta[name="twitter:description"]', description);
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
                ${this.ui.aboutDataset || 'About this dataset'}${this.lang === 'en' ? ' <span class="info-lang-note">RO</span>' : ''}
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
        const seriesDimMeta = timeSeriesDim ? dims.find(d => d.dim_column_name === timeSeriesDim) : null;
        const seriesCount = seriesDimMeta ? (seriesDimMeta.option_count || 0) : 0;
        const timeChartTypes = hasTimePanel ? ['line', 'bar', 'area_stacked', 'stacked_bar', ...(seriesCount >= 3 ? ['ranking'] : [])] : [];

        // Snapshot chart types
        let snapshotChartTypes = [];
        if (hasSnapshotPanel) {
            if (categoryDims.length >= 2) {
                snapshotChartTypes = ['grouped_bar', 'stacked_bar', 'heatmap', 'bubble'];
            } else {
                snapshotChartTypes = ['bar_vertical', 'horizontal_bar'];
            }
            // For geo datasets, prepend choropleth
            if ((archetype === 'geo_time' || archetype === 'geo_only') && geoDimObj) {
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
            // For age+gender datasets, add population pyramid
            const hasAgeDim = dims.some(d => d.dim_type === 'age' && d.option_count > 1);
            const hasGenderDim = dims.some(d => d.dim_type === 'gender' && d.option_count > 1);
            if (hasAgeDim && hasGenderDim && !snapshotChartTypes.includes('population_pyramid')) {
                snapshotChartTypes.push('population_pyramid');
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
            line: 'Line', bar: 'Bar', area_stacked: 'Area', stacked_bar: 'Stacked', ranking: this.ui.rankMode,
        };

        for (const type of setup.timeChartTypes) {
            const btn = document.createElement('button');
            btn.className = 'ct-btn' + (type === this.timeChartType ? ' active' : '');
            btn.textContent = LABELS[type] || type;
            btn.addEventListener('click', () => {
                this.timeChartType = type;
                pills.querySelectorAll('.ct-btn:not(.transform-btn)').forEach(b => b.classList.remove('active'));
                btn.classList.add('active');
                const el = document.getElementById('time-chart');
                el.style.opacity = '0.4';
                el.style.transition = 'opacity 0.15s';
                this.renderTimeChart();
                el.style.opacity = '';
                el.style.transition = '';
                this._syncURL();
            });
            pills.appendChild(btn);
        }

        // Transform mode toggles (Index, YoY) — separator + two toggle buttons
        const sep = document.createElement('span');
        sep.className = 'ct-sep';
        sep.textContent = '·';
        pills.appendChild(sep);

        for (const [mode, label, tooltip] of [['index', this.ui.indexMode, this.ui.indexTooltip], ['yoy', this.ui.yoyMode, this.ui.yoyTooltip]]) {
            const btn = document.createElement('button');
            btn.className = 'ct-btn transform-btn' + (this.timeTransform === mode ? ' active' : '');
            btn.textContent = label;
            btn.title = tooltip;
            btn.addEventListener('click', () => {
                this.timeTransform = this.timeTransform === mode ? null : mode;
                pills.querySelectorAll('.transform-btn').forEach(b => b.classList.remove('active'));
                if (this.timeTransform) btn.classList.add('active');
                this.renderTimeChart();
                this._syncURL();
            });
            pills.appendChild(btn);
        }

        // Yearly aggregation toggle + zoom presets — only for monthly/quarterly datasets
        if (this.timeGranularity === 'monthly' || this.timeGranularity === 'quarterly') {
            const sep2 = document.createElement('span');
            sep2.className = 'ct-sep';
            sep2.textContent = '·';
            pills.appendChild(sep2);

            const yearlyBtn = document.createElement('button');
            yearlyBtn.className = 'ct-btn transform-btn' + (this.yearlyAgg ? ' active' : '');
            yearlyBtn.textContent = this.ui.yearlyMode;
            yearlyBtn.title = this.ui.yearlyTooltip;

            // Zoom preset buttons (1Y/3Y/5Y/All) — visible only in raw monthly mode
            const presetWrap = document.createElement('span');
            presetWrap.className = 'zoom-preset-wrap' + (this.yearlyAgg ? ' hidden' : '');
            const presetKeys = ['1y', '3y', '5y', 'all'];
            const presetLabels = this.ui.zoomPresets;  // ['1A','3A','5A','Tot'] or ['1Y','3Y','5Y','All']
            presetKeys.forEach((key, i) => {
                const pbtn = document.createElement('button');
                pbtn.className = 'ct-btn zoom-preset-btn' + (this.timeZoomPreset === key ? ' active' : '');
                pbtn.textContent = presetLabels[i];
                pbtn.dataset.zoomKey = key;
                pbtn.addEventListener('click', () => {
                    this.timeZoomPreset = key;
                    presetWrap.querySelectorAll('.zoom-preset-btn').forEach(b => b.classList.remove('active'));
                    pbtn.classList.add('active');
                    this._applyZoomPreset(key);
                    this._syncURL();
                });
                presetWrap.appendChild(pbtn);
            });

            yearlyBtn.addEventListener('click', () => {
                this.yearlyAgg = !this.yearlyAgg;
                yearlyBtn.classList.toggle('active', this.yearlyAgg);
                presetWrap.classList.toggle('hidden', this.yearlyAgg);
                this.renderTimeChart();
                this._syncURL();
            });

            pills.appendChild(yearlyBtn);
            pills.appendChild(presetWrap);
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
                this._syncURL();
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
        // Sync URL on manual nav (skip during animation to avoid rapid replaceState calls)
        if (!this.playInterval) this._syncURL();
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
            this._syncURL();
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
            } else if (this._urlFilters?.[dim.dim_column_name]) {
                select.value = this._urlFilters[dim.dim_column_name];
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
        const groupBy = this.computeGroupBy();

        // Large dataset handling: GROUP BY bypasses the server limit,
        // so only auto-filter when no GROUP BY (e.g. table view)
        const rowCount = this.metadata.row_count || 0;
        const hasActiveFilters = Object.keys(filters).length > 0;
        let autoFilterApplied = false;

        if (rowCount > 50000 && !hasActiveFilters && !groupBy) {
            autoFilterApplied = this._autoApplyTimeWindow(filters);
            if (!autoFilterApplied) autoFilterApplied = this._autoApplyFilter(filters);
        }

        try {
            this.data = await API.getDatasetData(code, filters, 50000, { groupBy });
            // Server may have auto-applied time window for very large datasets
            if (this.data.time_windowed) {
                this._showServerTimeWindowNotice();
            } else if (autoFilterApplied) {
                this._showLargeDatasetNotice();
            } else {
                this._hideLargeDatasetNotice();
            }
            this.renderInsights();
            await this.renderTimeChart();
            await this.renderSnapshotChart();
            if (!document.getElementById('table-panel').classList.contains('hidden')) this.renderTable();
            this._syncURL();
        } catch (err) {
            const msg = err.message || 'Failed to load data';
            const isLarge = msg.includes('filter');
            // Retry with time window or auto-filter on large dataset error
            if (isLarge && !autoFilterApplied) {
                autoFilterApplied = this._autoApplyTimeWindow(filters)
                    || this._autoApplyFilter(filters);
                if (autoFilterApplied) {
                    try {
                        this.data = await API.getDatasetData(code, filters, 50000, { groupBy: this.computeGroupBy() });
                        this._showLargeDatasetNotice();
                        this.renderInsights();
                        await this.renderTimeChart();
                        await this.renderSnapshotChart();
                        if (!document.getElementById('table-panel').classList.contains('hidden')) this.renderTable();
                        this._syncURL();
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

    /** Sync current dashboard state to URL (replaceState — no history pollution). */
    _syncURL() {
        const code = this.metadata?.matrix_code;
        if (!code) return;
        const url = new URL(location.href);
        url.searchParams.set('code', code);
        url.searchParams.delete('page');

        // Time chart type (omit default 'line' to keep URLs clean)
        if (this.timeChartType && this.timeChartType !== 'line')
            url.searchParams.set('tchart', this.timeChartType);
        else
            url.searchParams.delete('tchart');

        // Time transform mode
        if (this.timeTransform)
            url.searchParams.set('tmode', this.timeTransform);
        else
            url.searchParams.delete('tmode');

        // Yearly aggregation — only store when user explicitly turned it OFF (default is ON for monthly/quarterly)
        if (this.yearlyAgg === false && (this.timeGranularity === 'monthly' || this.timeGranularity === 'quarterly'))
            url.searchParams.set('tagg', '0');
        else
            url.searchParams.delete('tagg');

        // Zoom preset — only store when not default (5y)
        if (!this.yearlyAgg && this.timeZoomPreset && this.timeZoomPreset !== '5y')
            url.searchParams.set('tzoom', this.timeZoomPreset);
        else
            url.searchParams.delete('tzoom');

        // Snapshot chart type
        if (this.snapshotChartType)
            url.searchParams.set('schart', this.snapshotChartType);
        else
            url.searchParams.delete('schart');

        // Period — only persist if not latest
        const periods = this.panelSetup?.periods || [];
        const pidx = this.selectedPeriodIdx < 0 ? periods.length - 1 : this.selectedPeriodIdx;
        if (pidx >= 0 && pidx !== periods.length - 1 && periods[pidx])
            url.searchParams.set('period', periods[pidx].id);
        else
            url.searchParams.delete('period');

        // Filters (flatten single-value arrays to strings for compactness)
        const filters = this.getFilters();
        const flat = {};
        for (const [k, v] of Object.entries(filters))
            flat[k] = Array.isArray(v) ? v[0] : v;
        if (Object.keys(flat).length > 0)
            url.searchParams.set('filters', JSON.stringify(flat));
        else
            url.searchParams.delete('filters');

        history.replaceState(null, '', url);
    }

    /**
     * Auto-restrict to latest N time periods for large datasets.
     * Estimates how many periods fit within the 50k row budget.
     */
    _autoApplyTimeWindow(filters) {
        const setup = this.panelSetup;
        if (!setup || !setup.timeDim || !setup.periods.length) return false;

        const totalRows = this.metadata.row_count || 0;
        const totalPeriods = setup.periods.length;
        if (totalPeriods <= 1) return false;

        // Estimate rows per period, then how many periods fit in budget
        const rowsPerPeriod = Math.ceil(totalRows / totalPeriods);
        let windowSize = Math.max(5, Math.floor(50000 / rowsPerPeriod));
        windowSize = Math.min(windowSize, totalPeriods);

        if (windowSize >= totalPeriods) return false; // all periods fit

        // Take the latest N periods (periods are chronological, oldest first)
        const latestPeriods = setup.periods.slice(-windowSize);
        const periodValues = latestPeriods.map(p => p.id);
        filters[setup.timeDim] = periodValues;
        this._timeWindowInfo = { shown: windowSize, total: totalPeriods };
        return true;
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
        const tw = this._timeWindowInfo;
        const msg = tw
            ? (this.lang === 'ro'
                ? `Se afișează ultimele ${tw.shown} perioade (din ${tw.total} disponibile)`
                : `Showing last ${tw.shown} periods (of ${tw.total} available)`)
            : this.ui.largeDatasetNotice;
        notice.innerHTML = `<span class="notice-icon">⚠</span> ${msg}`;
        notice.classList.remove('hidden');
        this._timeWindowInfo = null;
    }

    _showServerTimeWindowNotice() {
        // Server auto-applied time window — detect period count from returned data
        const periods = this.panelSetup?.periods || [];
        const data = this.data;
        const timeDim = this.panelSetup?.timeDim;
        let shownPeriods = 0;
        if (timeDim && data?.rows) {
            const timeIdx = data.columns.indexOf(timeDim);
            if (timeIdx >= 0) {
                const seen = new Set();
                for (const r of data.rows) seen.add(r[timeIdx]);
                shownPeriods = seen.size;
            }
        }
        const msg = this.lang === 'ro'
            ? `Se afișează ultimele ${shownPeriods || '?'} perioade (din ${periods.length} disponibile) — set de date mare`
            : `Showing last ${shownPeriods || '?'} periods (of ${periods.length} available) — large dataset`;
        let notice = document.getElementById('large-dataset-notice');
        if (!notice) {
            notice = document.createElement('div');
            notice.id = 'large-dataset-notice';
            notice.className = 'large-dataset-notice';
            const filterStrip = document.getElementById('filter-strip');
            filterStrip.insertAdjacentElement('beforebegin', notice);
        }
        notice.innerHTML = `<span class="notice-icon">⚠</span> ${msg}`;
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

    /**
     * Apply index/rebase or YoY transform to data rows.
     * Returns a new data object with transformed OBS_VALUE column.
     */
    _applyTimeTransform(data, timeDim, seriesDim) {
        if (!this.timeTransform || !data || !data.rows.length) return data;
        const cols = data.columns;
        const timeIdx = cols.indexOf(timeDim);
        if (timeIdx === -1) return data;
        const seriesIdx = seriesDim ? cols.indexOf(seriesDim) : -1;
        const valIdx = cols.length - 1;

        // Group rows by series key
        const groups = new Map();
        for (const row of data.rows) {
            const key = seriesIdx >= 0 ? String(row[seriesIdx]) : '__all__';
            if (!groups.has(key)) groups.set(key, []);
            groups.get(key).push(row);
        }

        const newRows = [];
        for (const rows of groups.values()) {
            const sorted = [...rows].sort((a, b) => String(a[timeIdx]).localeCompare(String(b[timeIdx])));
            if (this.timeTransform === 'index') {
                const base = sorted[0]?.[valIdx];
                if (base == null || base === 0) continue;
                for (const row of sorted) {
                    const nr = [...row];
                    nr[valIdx] = row[valIdx] != null ? (row[valIdx] / base) * 100 : null;
                    newRows.push(nr);
                }
            } else if (this.timeTransform === 'yoy') {
                for (let i = 1; i < sorted.length; i++) {
                    const prev = sorted[i - 1][valIdx];
                    const curr = sorted[i][valIdx];
                    if (prev == null || prev === 0 || curr == null) continue;
                    const nr = [...sorted[i]];
                    nr[valIdx] = ((curr - prev) / Math.abs(prev)) * 100;
                    newRows.push(nr);
                }
            }
        }
        return { ...data, rows: newRows };
    }

    /**
     * Aggregate monthly/quarterly rows to yearly resolution (client-side).
     * Groups TIME_PERIOD by year prefix: "2024-01" → "2024", "1995-Q1" → "1995".
     * AVG for percentage/rate/time_unit; SUM for counts/currency.
     */
    _aggregateByYear(data, timeDim, seriesDim) {
        if (!data || !data.rows.length) return data;
        const cols = data.columns;
        const timeIdx = cols.indexOf(timeDim);
        if (timeIdx === -1) return data;
        const seriesIdx = seriesDim ? cols.indexOf(seriesDim) : -1;
        const valIdx = cols.length - 1;

        const unitType = this.chartConfig?.primary_unit_type;
        const useAvg = unitType === 'percentage' || unitType === 'time_unit' || unitType === 'rate';

        // key = seriesValue + '|' + year
        const sums = new Map();
        const counts = new Map();
        const firstRow = new Map();

        for (const row of data.rows) {
            const period = String(row[timeIdx] || '');
            const year = period.slice(0, 4);  // "2024-01" → "2024"
            const seriesVal = seriesIdx >= 0 ? row[seriesIdx] : '__';
            const key = `${seriesVal}|${year}`;
            const v = row[valIdx];
            if (v == null) continue;
            sums.set(key, (sums.get(key) || 0) + v);
            counts.set(key, (counts.get(key) || 0) + 1);
            if (!firstRow.has(key)) firstRow.set(key, row);
        }

        const newRows = [];
        for (const [key, sum] of sums) {
            const cnt = counts.get(key);
            const template = [...firstRow.get(key)];
            const year = key.slice(key.lastIndexOf('|') + 1);
            template[timeIdx] = year;
            template[valIdx] = useAvg ? sum / cnt : sum;
            newRows.push(template);
        }

        newRows.sort((a, b) => {
            if (seriesIdx >= 0 && a[seriesIdx] !== b[seriesIdx])
                return String(a[seriesIdx]).localeCompare(String(b[seriesIdx]));
            return String(a[timeIdx]).localeCompare(String(b[timeIdx]));
        });

        const newLabels = { ...data.column_labels };
        newLabels[timeDim] = Object.fromEntries(newRows.map(r => [r[timeIdx], r[timeIdx]]));

        return { ...data, rows: newRows, column_labels: newLabels };
    }

    /**
     * Apply a named zoom preset to the time chart.
     * preset: '1y' (12 periods), '3y' (36), '5y' (60), 'all' (reset)
     */
    _applyZoomPreset(preset) {
        const chart = this.charts.find(c => c && !c.isDisposed() && c._timePanel);
        if (!chart) return;
        const totalPeriods = this.panelSetup?.periods?.length || 1;
        const windowMap = { '1y': 12, '3y': 36, '5y': 60, 'all': Infinity };
        const w = windowMap[preset] ?? 60;
        const start = w >= totalPeriods ? 0 : Math.max(0, Math.round((1 - w / totalPeriods) * 100));
        // setOption merge is more reliable than dispatchAction for initial zoom
        chart.setOption({
            dataZoom: [
                { type: 'inside', start, end: 100 },
                { type: 'slider', start, end: 100 },
            ]
        });
    }

    /**
     * Render distribution strip chart (box + scatter) below choropleth.
     * Extracts geo values for the selected period.
     */
    _renderDistribution(data, setup) {
        const strip = document.getElementById('distribution-strip');
        if (!strip) return;

        const isChoropleth = this.snapshotChartType === 'choropleth';
        if (!isChoropleth || !setup?.geoDim || !data?.rows.length) {
            strip.classList.add('hidden');
            return;
        }

        const cols = data.columns;
        const timeIdx = setup.timeDim ? cols.indexOf(setup.timeDim) : -1;
        const valIdx = cols.length - 1;

        // Use selected period if it has data, otherwise fall back to latest period present in data
        let targetPeriod = null;
        if (timeIdx !== -1) {
            const periods = setup.periods;
            const pidx = this.selectedPeriodIdx < 0 ? periods.length - 1 : this.selectedPeriodIdx;
            const selectedPeriod = periods[pidx];
            // Check if selected period has data
            const inData = new Set(data.rows.map(r => String(r[timeIdx])));
            if (selectedPeriod && inData.has(String(selectedPeriod.id))) {
                targetPeriod = String(selectedPeriod.id);
            } else {
                // Find latest period actually in data
                const dataPeriods = [...inData].sort();
                targetPeriod = dataPeriods[dataPeriods.length - 1] || null;
            }
        }

        let rows = data.rows;
        if (targetPeriod && timeIdx !== -1) {
            rows = rows.filter(r => String(r[timeIdx]) === targetPeriod);
        }

        const values = rows.map(r => r[valIdx]).filter(v => v != null && !isNaN(v));
        if (values.length < 3) {
            strip.classList.add('hidden');
            return;
        }

        strip.classList.remove('hidden');
        const container = document.getElementById('distribution-chart');
        if (!container) return;

        // Dispose old chart
        if (this._distChart && !this._distChart.isDisposed()) this._distChart.dispose();

        this._distChart = createDistributionChart(container, values, targetPeriod || '');
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
                _valueFormat: this.timeTransform === 'index' ? 'index' :
                              this.timeTransform === 'yoy'   ? 'pct_change' : null,
                _yearlyAgg: this.yearlyAgg,
                _timeGranularity: this.timeGranularity,
            };
            const translated = this._translateData(this.data);
            // Yearly aggregation (default ON for monthly/quarterly; user can toggle)
            const aggregated = this.yearlyAgg
                ? this._aggregateByYear(translated, setup.timeDim, setup.timeSeriesDim)
                : translated;
            const transformed = this._applyTimeTransform(aggregated, setup.timeDim, setup.timeSeriesDim);
            const chart = await createChart(container, cfg, transformed, this.metadata);
            if (chart) {
                chart._timePanel = true;
                this.charts.push(chart);
                const btn = document.getElementById('time-png-btn');
                if (btn) { btn.classList.remove('hidden'); btn.onclick = () => _exportPng(chart, `${this.metadata.matrix_code}-trends`); }
                // Apply zoom preset for raw monthly/quarterly view
                if (!this.yearlyAgg && (this.timeGranularity === 'monthly' || this.timeGranularity === 'quarterly')) {
                    this._applyZoomPreset(this.timeZoomPreset || '5y');
                }
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
            document.getElementById('distribution-strip')?.classList.add('hidden');
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

        const isChoropleth = this.snapshotChartType === 'choropleth';

        // For non-choropleth charts, bail early if the selected period has no data
        // Choropleth uses all time periods internally, so skip this check for it
        if (!isChoropleth && filteredData.rows.length === 0) {
            container.innerHTML = `<div class="chart-loading">${this.ui.noDataFilters}</div>`;
            document.getElementById('distribution-strip')?.classList.add('hidden');
            return;
        }

        // Dispose existing snapshot chart
        const existing = this.charts.filter(c => c && !c.isDisposed() && c._snapshotPanel);
        existing.forEach(c => { c.dispose(); });
        this.charts = this.charts.filter(c => c && !c.isDisposed());

        container.innerHTML = '';

        try {
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
                const btn = document.getElementById('snapshot-png-btn');
                if (btn) { btn.classList.remove('hidden'); btn.onclick = () => _exportPng(chart, `${this.metadata.matrix_code}-snapshot`); }
            }
            // Distribution strip: auto-shown below choropleth
            this._renderDistribution(this.data, setup);
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

            // Dimensions Explorer shortcut at top of sidebar
            const dimsLink = document.createElement('a');
            dimsLink.href = '/dimensions-explorer.html';
            dimsLink.className = 'sb-dims-link';
            dimsLink.innerHTML = `<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="3" width="7" height="7" rx="1"/><rect x="14" y="3" width="7" height="7" rx="1"/><rect x="3" y="14" width="7" height="7" rx="1"/><rect x="14" y="14" width="7" height="7" rx="1"/></svg> Dimension Browser`;
            tree.appendChild(dimsLink);

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
        this._tableColFilters = {};
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
        this._tableSortCol = null;
        this._tableSortAsc = true;
        this._tableColFilters = {};
    }

    renderTable() {
        if (!this.data) return;
        const display = this._translateData(this.data);
        const { columns, rows, truncated, returned_rows, total_rows } = display;
        const scroll = document.getElementById('table-scroll');
        const countEl = document.getElementById('table-row-count');

        if (!rows || !rows.length) {
            scroll.innerHTML = `<div class="table-truncated">${this.ui.noDataFilters}</div>`;
            if (countEl) countEl.textContent = '';
            return;
        }

        // Column headers
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

        const obsIdx = columns.indexOf('OBS_VALUE');
        const valueCol = obsIdx !== -1 ? obsIdx : columns.length - 1;

        // Build unique values per dimension column (for filters)
        const uniques = columns.map((col, i) => {
            if (i === valueCol) return null; // skip value column
            const set = new Set();
            for (const r of rows) if (r[i] != null) set.add(r[i]);
            return [...set].sort((a, b) => String(a).localeCompare(String(b)));
        });

        // Apply column filters
        const filters = this._tableColFilters;
        let filteredRows = rows;
        const hasFilters = Object.values(filters).some(v => v);
        if (hasFilters) {
            filteredRows = rows.filter(row =>
                Object.entries(filters).every(([idx, val]) => {
                    if (!val) return true;
                    return String(row[+idx] ?? '') === val;
                })
            );
        }

        // Sort
        let sortedRows = [...filteredRows];
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

        // Header row
        const th = colHeaders.map((lbl, i) => {
            const arrow = this._tableSortCol === i
                ? `<span class="sort-arrow">${this._tableSortAsc ? '↑' : '↓'}</span>` : '';
            return `<th data-col="${i}">${lbl}${arrow}</th>`;
        }).join('');

        // Filter row
        const filterCells = columns.map((col, i) => {
            if (i === valueCol || !uniques[i]) return '<td></td>';
            if (uniques[i].length > 500) return '<td></td>'; // too many options
            const current = filters[i] || '';
            const active = current ? ' active' : '';
            const opts = uniques[i].map(v => {
                const escaped = String(v).replace(/"/g, '&quot;');
                const sel = String(v) === current ? ' selected' : '';
                return `<option value="${escaped}"${sel}>${v}</option>`;
            }).join('');
            const allLabel = this.lang === 'en' ? '— all —' : '— toate —';
            return `<td><select class="col-filter${active}" data-col="${i}"><option value="">${allLabel}</option>${opts}</select></td>`;
        }).join('');

        // Body rows
        const trs = sortedRows.map(row => {
            const tds = row.map((val, i) => {
                if (i === valueCol) {
                    const fmt = val == null ? '–' : formatNumber(val, val % 1 === 0 ? 0 : 2);
                    return `<td class="num">${fmt}</td>`;
                }
                return `<td>${val ?? '–'}</td>`;
            }).join('');
            return `<tr>${tds}</tr>`;
        }).join('');

        scroll.innerHTML = `
            <table class="data-table">
                <thead>
                    <tr>${th}</tr>
                    <tr class="filter-row">${filterCells}</tr>
                </thead>
                <tbody>${trs}</tbody>
            </table>
            ${truncated ? `<div class="table-truncated">Showing ${formatNumber(returned_rows || rows.length, 0)} of ${formatNumber(total_rows || rows.length, 0)} rows</div>` : ''}
        `;

        // Row count
        if (countEl) {
            countEl.textContent = hasFilters
                ? `${formatNumber(sortedRows.length, 0)} / ${formatNumber(rows.length, 0)} rows`
                : `${formatNumber(rows.length, 0)} rows`;
        }

        // Sort handlers
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

        // Filter handlers
        scroll.querySelectorAll('.col-filter').forEach(sel => {
            sel.addEventListener('click', e => e.stopPropagation());
            sel.addEventListener('change', e => {
                const idx = e.target.dataset.col;
                this._tableColFilters[idx] = e.target.value;
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
        // Remove numbering prefix like "1. " or "A.01 ", then title-case
        const stripped = name.replace(/^[A-Z]?\.\d*\s*/, '').replace(/^\d+\.\s*/, '');
        // Title-case: first letter upper, rest lower (handles all-caps from API)
        return stripped.charAt(0).toUpperCase() + stripped.slice(1).toLowerCase();
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
    const params = new URLSearchParams(location.search);
    const code = params.get('code');
    const page = params.get('page');
    const cat  = params.get('cat');
    if (page === 'about') {
        window.app.showAbout();
    } else if (code) {
        window.app.showDashboard(code);
    } else if (cat) {
        window.app._urlCat = cat;
        window.app.showBrowse();
    } else {
        window.app.showBrowse();
    }
});
