function _esc(s) {
    return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}

function alignToYears(seriesData, years) {
    const map = {};
    for (const r of seriesData) map[r.year] = r.value;
    return years.map(y => map[y] ?? null);
}

const THEMES = [
  { id: 'demografie',   label: 'Demografie',      icon: '👥',
    kpi_labels: ['Populație rezidentă', 'Rata natalității', 'Rata mortalității'],
    categories: ['Populație', 'Demografie', 'Natalitate', 'Mortalitate', 'Decese', 'Fertilitate'] },
  { id: 'munca',        label: 'Forță de muncă',  icon: '💼',
    kpi_labels: ['Rata șomajului BIM', 'Câștig salarial net mediu lunar'],
    categories: ['Forța de muncă', 'Muncă', 'Salarii', 'Șomaj', 'Ocupare'] },
  { id: 'economie',     label: 'Economie',        icon: '📈',
    kpi_labels: [],
    categories: ['Economie', 'Conturi naționale', 'Prețuri', 'Finanțe', 'Comerț'] },
  { id: 'educatie',     label: 'Educație',        icon: '🎓',
    kpi_labels: [],
    categories: ['Educație', 'Învățământ', 'Școli', 'Elevi'] },
  { id: 'sanatate',     label: 'Sănătate',        icon: '🏥',
    kpi_labels: [],
    categories: ['Sănătate', 'Asistență medicală', 'Spitale'] },
  { id: 'agricultura',  label: 'Agricultură',     icon: '🌾',
    kpi_labels: [],
    categories: ['Agricultură', 'Silvicultură', 'Fond funciar'] },
  { id: 'industrie',    label: 'Industrie',       icon: '🏭',
    kpi_labels: [],
    categories: ['Industrie', 'Producție industrială', 'Construcții'] },
  { id: 'turism',       label: 'Turism',          icon: '🏨',
    kpi_labels: [],
    categories: ['Turism', 'Cazare', 'Hoteluri'] },
];

const PLACE_UI = {
    ro: { loading: 'Se încarcă...', notFound: 'Locul nu a fost găsit.', error: 'Eroare la încărcare.',
          datasets: 'seturi de date disponibile', themes: 'Seturi de date pe teme',
          comparison: 'Comparație', national: 'Medie națională', sameRegion: 'Aceeași regiune:',
          similarSize: 'Mărime similară:', typeLabels: { county:'Județ', region:'Regiune', macroregion:'Macroregiune', locality:'Localitate' },
          searchPlaceholder: 'Caută un loc...' },
    en: { loading: 'Loading...', notFound: 'Place not found.', error: 'Loading error.',
          datasets: 'datasets available', themes: 'Datasets by theme',
          comparison: 'Comparison', national: 'National average', sameRegion: 'Same region:',
          similarSize: 'Similar size:', typeLabels: { county:'County', region:'Region', macroregion:'Macroregion', locality:'Locality' },
          searchPlaceholder: 'Search a place...' },
};

class PlaceProfileApp {
    constructor() {
        this.data = null;
        this.activeKpiIndex = 0;
        this.activePeers = new Set();
        this.comparisonChart = null;
        this.comparisonData = {};
        this.sparklines = [];
        this.allPlaces = null;
        this.lang = localStorage.getItem('lens_lang') || 'ro';
        this.theme = document.documentElement.getAttribute('data-theme') || 'dark';
    }

    get ui() { return PLACE_UI[this.lang] || PLACE_UI.ro; }

    _chartColors() {
        const isLight = this.theme === 'light';
        return {
            axisLabel: isLight ? '#6b7280' : '#64748b',
            splitLine: isLight ? '#e5e7eb' : '#1e293b',
            legendText: isLight ? '#374151' : '#94a3b8',
        };
    }

    _initNav() {
        // Theme toggle
        const applyThemeIcons = (t) => {
            document.getElementById('theme-icon-sun').style.display = t === 'light' ? 'none' : '';
            document.getElementById('theme-icon-moon').style.display = t === 'light' ? '' : 'none';
        };
        applyThemeIcons(this.theme);
        document.getElementById('lang-label').textContent = this.lang === 'ro' ? 'EN' : 'RO';

        document.getElementById('theme-toggle').addEventListener('click', () => {
            this.theme = this.theme === 'dark' ? 'light' : 'dark';
            document.documentElement.setAttribute('data-theme', this.theme);
            localStorage.setItem('lens_theme', this.theme);
            applyThemeIcons(this.theme);
            if (this.comparisonChart) this._refreshComparisonChart();
        });

        document.getElementById('lang-toggle').addEventListener('click', () => {
            this.lang = document.getElementById('lang-label').textContent.toLowerCase();
            localStorage.setItem('lens_lang', this.lang);
            document.getElementById('lang-label').textContent = this.lang === 'ro' ? 'EN' : 'RO';
            document.documentElement.setAttribute('lang', this.lang);
            this._applyLangStrings();
        });

        // Place search in topbar
        this._initPlaceSearch();
    }

    _applyLangStrings() {
        const t = this.ui;
        const themesTitle = document.getElementById('section-title-themes');
        if (themesTitle) themesTitle.textContent = t.themes;
        const navInput = document.getElementById('place-nav-input');
        if (navInput) navInput.placeholder = t.searchPlaceholder;
        if (this.data) {
            document.getElementById('dataset-count').textContent =
                `${this.data.dataset_count} ${t.datasets}`;
            const typeLabel = t.typeLabels[this.data.place.type] || this.data.place.type;
            document.getElementById('geo-badge').textContent = typeLabel;
        }
    }

    async _initPlaceSearch() {
        const input = document.getElementById('place-nav-input');
        const dropdown = document.getElementById('place-nav-dropdown');
        if (!input || !dropdown) return;

        // Lazy-load places list
        let places = null;
        const getPlaces = async () => {
            if (places) return places;
            try {
                const r = await fetch('/api/places');
                if (r.ok) { const d = await r.json(); places = d.places; }
            } catch (_) {}
            return places || [];
        };

        input.addEventListener('input', async () => {
            const q = input.value.trim().toLowerCase();
            if (!q) { dropdown.classList.add('hidden'); dropdown.innerHTML = ''; return; }
            const list = await getPlaces();
            const matches = list.filter(p => p.name.toLowerCase().includes(q)).slice(0, 8);
            if (!matches.length) { dropdown.classList.add('hidden'); return; }
            const typeLabels = this.ui.typeLabels;
            dropdown.innerHTML = matches.map(p => `
                <a class="topbar-place-item" href="/place/${p.type}/${p.slug}">
                    <span style="flex:1">${_esc(p.name)}</span>
                    <span class="topbar-place-item-type">${_esc(typeLabels[p.type] || p.type)}</span>
                </a>`).join('');
            dropdown.classList.remove('hidden');
        });

        document.addEventListener('click', (e) => {
            if (!document.getElementById('place-nav-wrap').contains(e.target)) {
                dropdown.classList.add('hidden');
            }
        });

        input.addEventListener('keydown', (e) => {
            if (e.key === 'Escape') { dropdown.classList.add('hidden'); input.blur(); }
        });
    }

    async init() {
        const parts = window.location.pathname.split('/').filter(Boolean);
        // /place/{type}/{slug}
        if (parts.length < 3) return;
        this.placeType = parts[1];
        this.placeSlug = parts[2];

        this._initNav();

        try {
            const resp = await fetch(`/api/places/${this.placeType}/${this.placeSlug}`);
            if (!resp.ok) {
                document.getElementById('place-loading').textContent = this.ui.notFound;
                return;
            }
            this.data = await resp.json();
        } catch (e) {
            document.getElementById('place-loading').textContent = this.ui.error;
            return;
        }

        this._renderHeader();
        this._renderKPIs();
        this._renderIndicatorGrid();
        this._renderComparison();

        document.getElementById('place-loading').style.display = 'none';
        document.getElementById('place-content').style.display = 'block';
        this._applyLangStrings();

        // Fix ECharts width: container was display:none during init, needs resize now that it's visible
        if (this.comparisonChart) {
            setTimeout(() => this.comparisonChart.resize(), 0);
        }

        document.title = `${this.data.place.name} — INS+`;
    }

    _renderHeader() {
        const { place, dataset_count } = this.data;
        const crumbs = ['<a href="/places">Locuri</a>'];
        if (place.parent) {
            crumbs.push(`<a href="/place/${place.parent.type}/${place.parent.slug}">${place.parent.name}</a>`);
        }
        crumbs.push(place.name);
        document.getElementById('breadcrumb').innerHTML = crumbs.join(' › ');
        document.getElementById('place-name').textContent = place.name;
        document.getElementById('geo-badge').textContent = this.ui.typeLabels[place.type] || place.type;
        document.getElementById('dataset-count').textContent = `${dataset_count} ${this.ui.datasets}`;
    }

    _renderKPIs() {
        const grid = document.getElementById('kpi-grid');
        for (const c of this.sparklines) c.dispose();
        this.sparklines = [];
        grid.innerHTML = this.data.kpis.map((kpi, i) => {
            const deltaHtml = kpi.change_yoy != null
                ? `<div class="kpi-delta ${kpi.change_yoy >= 0 ? 'up' : 'down'}">
                     ${kpi.change_yoy >= 0 ? '▲' : '▼'} ${Math.abs(kpi.change_yoy)} ${_esc(kpi.unit)}
                   </div>`
                : '';
            return `
                <div class="kpi-card ${i === 0 ? 'active' : ''}"
                     data-kpi-index="${i}"
                     onclick="app._selectKpi(${i})">
                    <div class="kpi-label">${_esc(kpi.label)}</div>
                    <div>
                        <span class="kpi-value">${kpi.value != null ? kpi.value.toLocaleString('ro-RO') : '—'}</span>
                        <span class="kpi-unit">${_esc(kpi.unit)}</span>
                    </div>
                    ${deltaHtml}
                    <div class="kpi-sparkline" id="kpi-spark-${i}"></div>
                </div>`;
        }).join('');

        requestAnimationFrame(() => {
            this.data.kpis.forEach((kpi, i) => {
                this._renderSparkline(`kpi-spark-${i}`, kpi.sparkline);
            });
        });
    }

    _renderSparkline(containerId, series) {
        const el = document.getElementById(containerId);
        if (!el || !series || series.length < 2) return;
        const chart = echarts.init(el, null, { renderer: 'svg' });
        this.sparklines.push(chart);
        chart.setOption({
            animation: false,
            grid: { top: 2, right: 2, bottom: 2, left: 2 },
            xAxis: { type: 'category', show: false, data: series.map(r => r.year) },
            yAxis: { type: 'value', show: false },
            series: [{
                type: 'line',
                data: series.map(r => r.value),
                smooth: true,
                showSymbol: false,
                lineStyle: { color: '#3b82f6', width: 1.5 },
                areaStyle: { color: 'rgba(59,130,246,0.1)' },
            }],
        });
        setTimeout(() => chart.resize(), 0);
    }

    _selectKpi(index) {
        document.querySelectorAll('.kpi-card').forEach((el, i) => {
            el.classList.toggle('active', i === index);
        });
        this.activeKpiIndex = index;
        document.getElementById('comparison-kpi-label').textContent =
            this.data.kpis[index]?.label || '';
        this._refreshComparisonChart();
    }

    _renderIndicatorGrid() {
        // Legacy - replaced by _renderThemes. Keep name for now, delegate to new method.
        this._renderThemes();
    }

    _renderThemes() {
        const { datasets } = this.data;
        const grid = document.getElementById('indicator-grid');
        let html = '';

        for (const theme of THEMES) {
            const themeDatasets = datasets.filter(d =>
                theme.categories.some(cat => d.category.toLowerCase().includes(cat.toLowerCase()))
            );
            const themeKpis = theme.kpi_labels
                .map(label => this.data.kpis.find(k => k.label === label))
                .filter(Boolean);

            if (themeDatasets.length === 0 && themeKpis.length === 0) continue;

            const chartsHtml = themeKpis.slice(0, 3).map((kpi, i) => `
                <div class="mini-chart-cell">
                    <div class="mini-chart-title">${_esc(kpi.label)}</div>
                    <div class="mini-chart-canvas" id="mini-${theme.id}-${i}"></div>
                    <div class="mini-chart-stat">${kpi.value != null ? kpi.value.toLocaleString('ro-RO') : '—'} ${_esc(kpi.unit)}</div>
                </div>
            `).join('');

            const accordionItems = themeDatasets.map(d => `
                <a class="accordion-item" href="/dataset-v2.html?code=${d.code}">
                    <span class="acc-title">${_esc(d.title)}</span>
                    <span class="acc-code">${_esc(d.code)}</span>
                </a>
            `).join('');

            html += `
                <div class="theme-section" id="theme-${theme.id}">
                    <div class="theme-header" onclick="app._toggleThemeAccordion('${theme.id}')">
                        <span class="theme-icon">${theme.icon}</span>
                        <span class="theme-label">${theme.label}</span>
                        <span class="theme-count">${themeDatasets.length}</span>
                        <span class="theme-chevron">▼</span>
                    </div>
                    ${chartsHtml ? `<div class="theme-charts">${chartsHtml}</div>` : ''}
                    <div class="theme-accordion hidden" id="accordion-${theme.id}">
                        ${accordionItems}
                    </div>
                </div>
            `;
        }

        // Catch-all for datasets not in any theme
        const unmatchedDatasets = datasets.filter(d =>
            !THEMES.some(theme =>
                theme.categories.some(cat => d.category.toLowerCase().includes(cat.toLowerCase()))
            )
        );

        if (unmatchedDatasets.length > 0) {
            const items = unmatchedDatasets.map(d => `
                <a class="accordion-item" href="/dataset-v2.html?code=${d.code}">
                    <span class="acc-title">${_esc(d.title)}</span>
                    <span class="acc-code">${_esc(d.code)}</span>
                </a>
            `).join('');

            html += `
                <div class="theme-section" id="theme-altele">
                    <div class="theme-header" onclick="app._toggleThemeAccordion('altele')">
                        <span class="theme-icon">📋</span>
                        <span class="theme-label">Alte seturi de date</span>
                        <span class="theme-count">${unmatchedDatasets.length}</span>
                        <span class="theme-chevron">▼</span>
                    </div>
                    <div class="theme-accordion hidden" id="accordion-altele">
                        ${items}
                    </div>
                </div>
            `;
        }

        grid.innerHTML = html;

        // Render mini charts
        requestAnimationFrame(() => {
            for (const theme of THEMES) {
                const themeKpis = theme.kpi_labels
                    .map(label => this.data.kpis.find(k => k.label === label))
                    .filter(Boolean)
                    .slice(0, 3);
                themeKpis.forEach((kpi, i) => {
                    this._renderSparkline(`mini-${theme.id}-${i}`, kpi.sparkline);
                });
            }
        });
    }

    _toggleThemeAccordion(id) {
        const accordion = document.getElementById(`accordion-${id}`);
        const chevron = document.querySelector(`#theme-${id} .theme-chevron`);
        if (!accordion) return;
        const isOpen = !accordion.classList.contains('hidden');
        accordion.classList.toggle('hidden', isOpen);
        chevron.textContent = isOpen ? '▼' : '▲';
    }

    _renderComparison() {
        const { place, peers, kpis } = this.data;

        const alwaysChips = document.getElementById('always-chips');
        const baselines = [];
        if (place.parent) {
            baselines.push(`<span class="baseline-chip">🇷🇴 Medie națională</span>`);
            baselines.push(`<span class="baseline-chip">${_esc(place.parent.name)} (regiune)</span>`);
        } else {
            baselines.push(`<span class="baseline-chip">🇷🇴 Medie națională</span>`);
        }
        alwaysChips.innerHTML = baselines.join('');

        const peerGroupsEl = document.getElementById('peer-groups');
        const groups = [];
        if (peers.same_region?.length) {
            const chips = peers.same_region.map(p =>
                `<div class="peer-chip" data-slug="${p.slug}" data-type="${p.type}" data-name="${_esc(p.name)}"
                      onclick="app._togglePeer(this)">${_esc(p.name)}</div>`
            ).join('');
            groups.push(`<div class="peer-group">
                <span class="peer-group-label">${this.ui.sameRegion}</span>${chips}
            </div>`);
        }
        if (peers.similar_size?.length) {
            const chips = peers.similar_size.map(p =>
                `<div class="peer-chip" data-slug="${p.slug}" data-type="${p.type}" data-name="${_esc(p.name)}"
                      onclick="app._togglePeer(this)">${_esc(p.name)}</div>`
            ).join('');
            groups.push(`<div class="peer-group">
                <span class="peer-group-label">${this.ui.similarSize}</span>${chips}
            </div>`);
        }
        peerGroupsEl.innerHTML = groups.join('');

        document.getElementById('comparison-kpi-label').textContent = kpis[0]?.label || '';

        const chartEl = document.getElementById('comparison-chart');
        this.comparisonChart = echarts.init(chartEl, null, { renderer: 'svg' });

        this._loadBaselines().then(() => this._refreshComparisonChart());
    }

    async _loadBaselines() {
        const kpi = this.data.kpis[this.activeKpiIndex];
        if (!kpi) return;
        const label = encodeURIComponent(kpi.label);
        try {
            const resp = await fetch(
                `/api/places/${this.placeType}/${this.placeSlug}/baselines/${label}`
            );
            if (!resp.ok) return;
            const { national, region } = await resp.json();
            this.comparisonData['__national__'] = national;
            this.comparisonData['__region__'] = region;
        } catch (_) {}
    }

    async _togglePeer(el) {
        const slug = el.dataset.slug;
        const type = el.dataset.type;
        const name = el.dataset.name;

        if (this.activePeers.has(slug)) {
            this.activePeers.delete(slug);
            el.classList.remove('active');
            delete this.comparisonData[slug];
        } else {
            if (this.activePeers.size >= 3) return;
            this.activePeers.add(slug);
            el.classList.add('active');
            try {
                const resp = await fetch(`/api/places/${type}/${slug}`);
                if (resp.ok) {
                    const peer = await resp.json();
                    const kpiLabel = this.data.kpis[this.activeKpiIndex]?.label;
                    const kpi = peer.kpis.find(k => k.label === kpiLabel);
                    this.comparisonData[slug] = kpi ? kpi.sparkline : [];
                }
            } catch (_) {}
        }
        this._refreshComparisonChart();
    }

    _refreshComparisonChart() {
        if (!this.comparisonChart) return;
        const kpi = this.data.kpis[this.activeKpiIndex];
        if (!kpi) return;

        const xYears = kpi.sparkline.map(r => r.year);
        const series = [];
        const primaryValues = []; // place + peers only — used for y-axis range
        const colors = ['#3b82f6', '#94a3b8', '#64748b', '#f59e0b', '#a78bfa', '#4ade80'];
        let colorIdx = 0;

        const placeData = alignToYears(kpi.sparkline, xYears);
        primaryValues.push(...placeData.filter(v => v != null));
        series.push({
            name: this.data.place.name,
            type: 'line',
            data: placeData,
            lineStyle: { width: 2.5, color: colors[colorIdx++] },
            showSymbol: false, smooth: true,
        });

        if (this.comparisonData['__national__']?.length) {
            series.push({
                name: this.ui.national,
                type: 'line',
                data: alignToYears(this.comparisonData['__national__'], xYears),
                lineStyle: { width: 1.5, color: colors[colorIdx++], type: 'dashed' },
                showSymbol: false, smooth: true,
            });
        }

        if (this.comparisonData['__region__']?.length) {
            series.push({
                name: this.data.place.parent?.name || 'Regiune',
                type: 'line',
                data: alignToYears(this.comparisonData['__region__'], xYears),
                lineStyle: { width: 1.5, color: colors[colorIdx++], type: 'dashed' },
                showSymbol: false, smooth: true,
            });
        }

        for (const slug of this.activePeers) {
            if (this.comparisonData[slug]?.length) {
                const peerName = [...document.querySelectorAll('.peer-chip')]
                    .find(el => el.dataset.slug === slug)?.dataset.name || slug;
                const peerData = alignToYears(this.comparisonData[slug], xYears);
                primaryValues.push(...peerData.filter(v => v != null));
                series.push({
                    name: peerName,
                    type: 'line',
                    data: peerData,
                    lineStyle: { width: 1.5, color: colors[colorIdx++ % colors.length] },
                    showSymbol: false, smooth: true,
                });
            }
        }

        // Compute y-axis range from place + peer data only.
        // Baselines (national, region) can have incomparable scales (e.g. national SUM vs county),
        // so we don't let them dictate the axis range.
        let yMin, yMax;
        if (primaryValues.length > 0) {
            const lo = Math.min(...primaryValues);
            const hi = Math.max(...primaryValues);
            const pad = (hi - lo) * 0.12 || hi * 0.1 || 1;
            yMin = Math.max(0, lo - pad);
            yMax = hi + pad;
        }

        // Filter out baseline series whose values are all outside the primary range —
        // they'd only distort the legend without adding visible information.
        const visibleSeries = series.filter(s => {
            if (yMin == null || yMax == null) return true;
            const vals = (s.data || []).filter(v => v != null);
            if (!vals.length) return false;
            const sMax = Math.max(...vals);
            const sMin = Math.min(...vals);
            // Keep if values actually overlap the visible y range (with 20% headroom)
            return sMax >= yMin * 0.8 && sMin <= yMax * 1.2;
        });

        const cc = this._chartColors();
        this.comparisonChart.setOption({
            animation: false,
            tooltip: { trigger: 'axis', confine: true },
            legend: { bottom: 0, textStyle: { color: cc.legendText, fontSize: 10 }, orient: 'horizontal' },
            grid: { top: 8, right: 12, bottom: 40, left: 52 },
            xAxis: { type: 'category', data: xYears, axisLabel: { color: cc.axisLabel, fontSize: 9, rotate: 45 } },
            yAxis: {
                type: 'value',
                min: yMin,
                max: yMax,
                axisLabel: { color: cc.axisLabel, fontSize: 8,
                    formatter: v => {
                        if (Math.abs(v) >= 1e6) return (v/1e6).toFixed(1) + 'M';
                        if (Math.abs(v) >= 1e3) return (v/1e3).toFixed(0) + 'K';
                        return v;
                    }
                },
                splitLine: { lineStyle: { color: cc.splitLine } },
            },
            series: visibleSeries,
        }, true);
    }
}

window.app = new PlaceProfileApp();
document.addEventListener('DOMContentLoaded', () => window.app.init());
