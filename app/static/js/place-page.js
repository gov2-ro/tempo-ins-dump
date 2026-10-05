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
    kpi_keys: ['resident_population', 'birth_rate', 'death_rate'],
    categories: ['Populație', 'Demografie', 'Natalitate', 'Mortalitate', 'Decese', 'Fertilitate'] },
  { id: 'munca',        label: 'Forță de muncă',  icon: '💼',
    kpi_keys: ['registered_unemployment_rate', 'net_monthly_wage'],
    categories: ['Forța de muncă', 'Muncă', 'Salarii', 'Șomaj', 'Ocupare'] },
  { id: 'economie',     label: 'Economie',        icon: '📈',
    kpi_keys: [],
    categories: ['Economie', 'Conturi naționale', 'Prețuri', 'Finanțe', 'Comerț'] },
  { id: 'educatie',     label: 'Educație',        icon: '🎓',
    kpi_keys: [],
    categories: ['Educație', 'Învățământ', 'Școli', 'Elevi'] },
  { id: 'sanatate',     label: 'Sănătate',        icon: '🏥',
    kpi_keys: [],
    categories: ['Sănătate', 'Asistență medicală', 'Spitale'] },
  { id: 'agricultura',  label: 'Agricultură',     icon: '🌾',
    kpi_keys: [],
    categories: ['Agricultură', 'Silvicultură', 'Fond funciar'] },
  { id: 'industrie',    label: 'Industrie',       icon: '🏭',
    kpi_keys: [],
    categories: ['Industrie', 'Producție industrială', 'Construcții'] },
  { id: 'turism',       label: 'Turism',          icon: '🏨',
    kpi_keys: [],
    categories: ['Turism', 'Cazare', 'Hoteluri'] },
];

const PLACE_UI = {
    ro: { loading: 'Se încarcă...', notFound: 'Locul nu a fost găsit.', error: 'Eroare la încărcare.',
          datasets: 'seturi de date disponibile', themes: 'Seturi de date pe teme',
          comparison: 'Comparație', national: 'Medie națională', sameRegion: 'Aceeași regiune:',
          similarSize: 'Mărime similară:', typeLabels: { county:'Județ', region:'Regiune', macroregion:'Macroregiune', locality:'Localitate' },
          searchPlaceholder: 'Caută un loc...',
          approx: 'aproximare', approxTitle: 'Aproximare: medie simplă, nu rata oficială pentru total',
          weighted: 'medie ponderată', source: 'Sursă', period: 'perioadă', method: 'Metodă',
          stale: 'date mai vechi', staleTitle: 'Sursa are date până în', changeNA: 'schimbare indisponibilă',
          diffDates: 'perioade diferite', vs: 'față de', since: 'din',
          units: { percent: '%', percentage_points: 'p.p.', per_mille_points: 'puncte ‰' },
          noteDiff: 'Atenție: perioade diferite în grafic —', nationalApprox: 'Medie națională (aproximare)',
          regionWord: '(regiune)', omitted: 'Indicatori indisponibili:',
          omittedReasons: { no_all_activities_total: 'nu există rând de total pe activități', no_data: 'fără date', missing_weights: 'fără ponderi' }, },
    en: { loading: 'Loading...', notFound: 'Place not found.', error: 'Loading error.',
          datasets: 'datasets available', themes: 'Datasets by theme',
          comparison: 'Comparison', national: 'National average', sameRegion: 'Same region:',
          similarSize: 'Similar size:', typeLabels: { county:'County', region:'Region', macroregion:'Macroregion', locality:'Locality' },
          searchPlaceholder: 'Search a place...',
          approx: 'approximation', approxTitle: 'Approximation: simple mean, not the official rate for the total',
          weighted: 'weighted mean', source: 'Source', period: 'period', method: 'Method',
          stale: 'older data', staleTitle: 'Source has data through', changeNA: 'change unavailable',
          diffDates: 'different periods', vs: 'vs', since: 'since',
          units: { percent: '%', percentage_points: 'pp', per_mille_points: '‰ points' },
          noteDiff: 'Note: different periods in the chart —', nationalApprox: 'National mean (approximation)',
          regionWord: '(region)', omitted: 'Unavailable indicators:',
          omittedReasons: { no_all_activities_total: 'no all-activities total row in the source', no_data: 'no data', missing_weights: 'no weights' }, },
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
            this._rerenderForLang();
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

    // KPI labels, methods and units are language-dependent
    _rerenderForLang() {
        if (!this.data) return;
        this._renderKPIs();
        this._renderThemes();
        this._renderComparisonHeader();
        this._renderBaselineChips();
        this._refreshComparisonChart();
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

    // ---- KPI helpers (language-aware labels, dates, units, change) ----
    _kl(kpi) { return this.lang === 'en' ? (kpi.label_en || kpi.label) : kpi.label; }
    _ku(kpi) { return this.lang === 'en' ? (kpi.unit_en || kpi.unit) : kpi.unit; }
    _locale() { return this.lang === 'en' ? 'en-GB' : 'ro-RO'; }

    _fmtValue(kpi, v) {
        if (v == null) return '—';
        const kind = kpi.unit_kind;
        const max = (kind === 'percent_rate' || kind === 'per_mille_rate') ? 1 : 0;
        return v.toLocaleString(this._locale(), { maximumFractionDigits: max });
    }

    // {text, cls, title}: delta with its own unit (relative % for counts,
    // percentage points for % rates, per-mille points for ‰ rates) and dates.
    _changeParts(kpi) {
        const t = this.ui, ch = kpi.change;
        if (!ch || ch.status !== 'ok' || ch.value == null) {
            return { text: t.changeNA, cls: 'na', title: ch && ch.reason ? ch.reason : '' };
        }
        const v = ch.value;
        const arrow = v > 0 ? '▲' : v < 0 ? '▼' : '■';
        const cls = v > 0 ? 'up' : v < 0 ? 'down' : 'flat';
        const sign = v > 0 ? '+' : v < 0 ? '−' : '';
        const unit = t.units[ch.display_unit] || ch.display_unit;
        const num = Math.abs(v).toLocaleString(this._locale(), { maximumFractionDigits: 2 });
        const sep = ch.display_unit === 'percent' ? '' : ' ';
        const gap = ch.basis !== 'yoy';
        const range = ch.from_period && ch.to_period
            ? `${t.vs} ${ch.from_period}${gap ? ` (${t.diffDates})` : ''}` : '';
        return { text: `${arrow} ${sign}${num}${sep}${unit}`, range, cls, gap,
                 title: `${ch.from_period || '?'} → ${ch.to_period || '?'}` };
    }

    _methodBadge(kpi) {
        const t = this.ui, m = kpi.method || {};
        if (m.approximation) return `<span class="kpi-badge approx" title="${_esc(t.approxTitle)}">${_esc(t.approx)}</span>`;
        if (m.code === 'weighted_mean') return `<span class="kpi-badge weighted">${_esc(t.weighted)}</span>`;
        return '';
    }

    _methodNote(kpi) {
        const m = kpi.method || {};
        return (this.lang === 'en' ? m.note_en : m.note) || '';
    }

    _renderKPIs() {
        const grid = document.getElementById('kpi-grid');
        for (const c of this.sparklines) c.dispose();
        this.sparklines = [];
        const t = this.ui;
        grid.innerHTML = this.data.kpis.map((kpi, i) => {
            const ch = this._changeParts(kpi);
            const deltaHtml = `<div class="kpi-delta ${ch.cls}" title="${_esc(ch.title || '')}">
                     ${_esc(ch.text)}${ch.range ? ` <span class="kpi-delta-range${ch.gap ? ' warn' : ''}">${_esc(ch.range)}</span>` : ''}
                   </div>`;
            const staleHtml = kpi.stale
                ? `<span class="kpi-badge stale" title="${_esc(t.staleTitle)} ${_esc(kpi.source_latest_period)}">${_esc(t.stale)}</span>` : '';
            const note = this._methodNote(kpi);
            const src = kpi.source || {};
            const srcTitle = (this.lang === 'en' ? src.title_en : src.title) || '';
            const def = (this.lang === 'en' ? kpi.definition_en : kpi.definition) || '';
            return `
                <div class="kpi-card ${i === this.activeKpiIndex ? 'active' : ''}"
                     data-kpi-index="${i}" data-kpi-key="${_esc(kpi.key)}"
                     title="${_esc(def)}"
                     onclick="app._selectKpi(${i})">
                    <div class="kpi-label">${_esc(this._kl(kpi))}</div>
                    <div>
                        <span class="kpi-value">${this._fmtValue(kpi, kpi.value)}</span>
                        <span class="kpi-unit">${_esc(this._ku(kpi))}</span>
                        <span class="kpi-period">${_esc(kpi.period || '')}</span>
                    </div>
                    ${deltaHtml}
                    <div class="kpi-badges">${this._methodBadge(kpi)}${staleHtml}</div>
                    <div class="kpi-sparkline" id="kpi-spark-${i}"></div>
                    <div class="kpi-source" title="${_esc(srcTitle)}">${_esc(t.source)}: ${_esc(src.code || '')}${note ? ` · ${_esc(note)}` : ''}</div>
                </div>`;
        }).join('');

        const om = this.data.omitted_kpis || [];
        const omEl = document.getElementById('kpi-omitted');
        if (omEl) {
            omEl.innerHTML = om.length
                ? `${_esc(t.omitted)} ` + om.map(o => `${_esc(this.lang === 'en' ? (o.label_en || o.label) : o.label)}`
                    + ` (${_esc(t.omittedReasons[o.reason] || o.reason)})`).join('; ')
                : '';
        }

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

    async _selectKpi(index) {
        document.querySelectorAll('.kpi-card').forEach((el, i) => {
            el.classList.toggle('active', i === index);
        });
        this.activeKpiIndex = index;
        this._renderComparisonHeader();
        // Baselines and peer series are per KPI: reload them for the new selection.
        this.comparisonData = {};
        this._applyPeerSeries();
        await this._loadBaselines();
        this._refreshComparisonChart();
    }

    _renderComparisonHeader() {
        const kpi = this.data.kpis[this.activeKpiIndex];
        document.getElementById('comparison-kpi-label').textContent = kpi ? this._kl(kpi) : '';
        const meta = document.getElementById('comparison-kpi-meta');
        if (meta && kpi) {
            const note = this._methodNote(kpi);
            meta.textContent = `${this.ui.source}: ${(kpi.source || {}).code || ''} · ${kpi.period || ''} · ${this._ku(kpi)}`
                + (note ? ` · ${note}` : '');
        }
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
            const themeKpis = theme.kpi_keys
                .map(key => this.data.kpis.find(k => k.key === key))
                .filter(Boolean);

            if (themeDatasets.length === 0 && themeKpis.length === 0) continue;

            const chartsHtml = themeKpis.slice(0, 3).map((kpi, i) => `
                <div class="mini-chart-cell">
                    <div class="mini-chart-title">${_esc(this._kl(kpi))}</div>
                    <div class="mini-chart-canvas" id="mini-${theme.id}-${i}"></div>
                    <div class="mini-chart-stat">${this._fmtValue(kpi, kpi.value)} ${_esc(this._ku(kpi))} · ${_esc(kpi.period || '')}${kpi.method && kpi.method.approximation ? ` · ${_esc(this.ui.approx)}` : ''}</div>
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
                const themeKpis = theme.kpi_keys
                    .map(key => this.data.kpis.find(k => k.key === key))
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

        const peerGroupsEl = document.getElementById('peer-groups');
        const groups = [];
        const chip = p => `<div class="peer-chip ${this.activePeers.has(p.slug) ? 'active' : ''}" data-slug="${p.slug}" data-type="${p.type}" data-name="${_esc(p.name)}"
                      onclick="app._togglePeer(this)">${_esc(p.name)}</div>`;
        if (peers.same_region?.length) {
            groups.push(`<div class="peer-group">
                <span class="peer-group-label">${this.ui.sameRegion}</span>${peers.same_region.map(chip).join('')}
            </div>`);
        }
        if (peers.similar_size?.length) {
            groups.push(`<div class="peer-group">
                <span class="peer-group-label">${this.ui.similarSize}</span>${peers.similar_size.map(chip).join('')}
            </div>`);
        }
        peerGroupsEl.innerHTML = groups.join('');
        this._renderBaselineChips();
        this._renderComparisonHeader();

        if (!this.comparisonChart) {
            const chartEl = document.getElementById('comparison-chart');
            this.comparisonChart = echarts.init(chartEl, null, { renderer: 'svg' });
        }
        this._loadBaselines().then(() => this._refreshComparisonChart());
    }

    _renderBaselineChips() {
        const { place } = this.data;
        const alwaysChips = document.getElementById('always-chips');
        const nat = this.comparisonData['__national__meta'];
        const natLabel = nat && nat.approximation ? this.ui.nationalApprox : this.ui.national;
        const chips = [`<span class="baseline-chip">🇷🇴 ${_esc(natLabel)}</span>`];
        if (place.parent) chips.push(`<span class="baseline-chip">${_esc(place.parent.name)} ${_esc(this.ui.regionWord)}</span>`);
        alwaysChips.innerHTML = chips.join('');
    }

    async _loadBaselines() {
        const kpi = this.data.kpis[this.activeKpiIndex];
        if (!kpi) return;
        const key = encodeURIComponent(kpi.key);
        try {
            const resp = await fetch(
                `/api/places/${this.placeType}/${this.placeSlug}/baselines/${key}`
            );
            if (!resp.ok) return;
            const b = await resp.json();
            // ignore a stale response if the selection changed meanwhile
            if (this.data.kpis[this.activeKpiIndex] !== kpi) return;
            this.comparisonData['__national__'] = b.national || [];
            this.comparisonData['__region__'] = b.region || [];
            this.comparisonData['__national__meta'] = b.national_meta;
            this.comparisonData['__region__meta'] = b.region_meta;
            this._renderBaselineChips();
        } catch (_) {}
    }

    // Peer profile cache: slug -> /api/places response (one fetch per peer)
    async _peerProfile(type, slug) {
        this.peerProfiles = this.peerProfiles || {};
        if (!this.peerProfiles[slug]) {
            const resp = await fetch(`/api/places/${type}/${slug}`);
            if (!resp.ok) return null;
            this.peerProfiles[slug] = await resp.json();
        }
        return this.peerProfiles[slug];
    }

    _applyPeerSeries() {
        const key = this.data.kpis[this.activeKpiIndex]?.key;
        for (const slug of this.activePeers) {
            const peer = (this.peerProfiles || {})[slug];
            const kpi = peer && peer.kpis.find(k => k.key === key);
            this.comparisonData[slug] = kpi ? kpi.sparkline : [];
        }
    }

    async _togglePeer(el) {
        const slug = el.dataset.slug;
        const type = el.dataset.type;

        if (this.activePeers.has(slug)) {
            this.activePeers.delete(slug);
            el.classList.remove('active');
            delete this.comparisonData[slug];
        } else {
            if (this.activePeers.size >= 3) return;
            this.activePeers.add(slug);
            el.classList.add('active');
            try {
                await this._peerProfile(type, slug);
            } catch (_) {}
            this._applyPeerSeries();
        }
        this._refreshComparisonChart();
    }

    _refreshComparisonChart() {
        if (!this.comparisonChart) return;
        const kpi = this.data.kpis[this.activeKpiIndex];
        if (!kpi) return;

        // x axis = union of every plotted series' periods, ascending, so a
        // baseline or peer that is newer/older than the place is not cut off.
        const yearSet = new Set(kpi.sparkline.map(r => r.year));
        for (const k of ['__national__', '__region__', ...this.activePeers]) {
            for (const r of (this.comparisonData[k] || [])) yearSet.add(r.year);
        }
        const xYears = [...yearSet].sort();
        const series = [];
        const primaryValues = []; // place + peers only — used for y-axis range
        const colors = ['#3b82f6', '#94a3b8', '#64748b', '#f59e0b', '#a78bfa', '#4ade80'];
        let colorIdx = 0;
        const lastYear = arr => (arr && arr.length ? arr[arr.length - 1].year : null);
        const periods = [[this.data.place.name, lastYear(kpi.sparkline)]];

        const placeData = alignToYears(kpi.sparkline, xYears);
        primaryValues.push(...placeData.filter(v => v != null));
        series.push({
            name: this.data.place.name,
            type: 'line',
            data: placeData,
            lineStyle: { width: 2.5, color: colors[colorIdx++] },
            showSymbol: false, smooth: false, connectNulls: false,
        });

        const natMeta = this.comparisonData['__national__meta'];
        if (this.comparisonData['__national__']?.length) {
            const nn = natMeta && natMeta.approximation ? this.ui.nationalApprox : this.ui.national;
            series.push({
                name: nn,
                type: 'line',
                data: alignToYears(this.comparisonData['__national__'], xYears),
                lineStyle: { width: 1.5, color: colors[colorIdx++], type: 'dashed' },
                showSymbol: false, smooth: false,
            });
            periods.push([nn, lastYear(this.comparisonData['__national__'])]);
        }

        if (this.comparisonData['__region__']?.length) {
            const rn = this.data.place.parent?.name || 'Regiune';
            series.push({
                name: rn,
                type: 'line',
                data: alignToYears(this.comparisonData['__region__'], xYears),
                lineStyle: { width: 1.5, color: colors[colorIdx++], type: 'dashed' },
                showSymbol: false, smooth: false,
            });
            periods.push([rn, lastYear(this.comparisonData['__region__'])]);
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
                    showSymbol: false, smooth: false,
                });
                periods.push([peerName, lastYear(this.comparisonData[slug])]);
            }
        }

        // Different-date warning: every plotted line should end on the same period.
        const noteEl = document.getElementById('comparison-note');
        if (noteEl) {
            const ends = new Set(periods.map(p => p[1]).filter(Boolean));
            noteEl.textContent = ends.size > 1
                ? `${this.ui.noteDiff} ` + periods.map(p => `${p[0]} ${p[1] || '—'}`).join(', ')
                : '';
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
