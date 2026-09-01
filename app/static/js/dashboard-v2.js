/**
 * Dashboard v2 — shape-driven dataset dashboard.
 *
 * Reads chart_config.composition (built by app/services/dashboard_composer.py)
 * and renders 1-4 complementary charts at once: each tile declares its own
 * aggregated data slice; identical slices are fetched once.
 */

const UI_STRINGS = {
    ro: {
        loading: 'Se încarcă…',
        missingCode: 'Lipsește parametrul ?code=',
        notFound: code => `Setul de date „${code}" nu a fost găsit.`,
        noComposition: 'Acest set de date nu are încă o configurație de dashboard.',
        splitParent: 'Acest set de date este publicat pe sub-seturi:',
        axis: { temporal: 'Evoluție în timp', spatial: 'Distribuție teritorială',
                ranking: 'Clasament', structural: 'Structură' },
        all: 'Toate',
        brief: 'Pe scurt:',
        noDataTile: 'Fără date pentru această selecție',
        noDataGrid: 'Nicio vizualizare nu are date pentru filtrele curente',
        renderError: 'Eroare la randare',
        insightsError: 'Indicatorii nu au putut fi încărcați.',
        outliers: 'Valori atipice față de restul județelor',
        fillRate: 'date complete',
        since: 'din',
        table: 'Tabel',
        tableCount: (n, cap) => `${n} rânduri${n >= cap ? ` (primele ${cap})` : ''}`,
        tableError: 'Tabelul nu a putut fi încărcat.',
        value: 'Valoare',
        indexTooltip: 'Index: prima perioadă = 100',
        yoyTooltip: 'Schimbare % față de perioada anterioară',
        seasonal: 'Sezonier',
        seasonalTooltip: 'Suprapune anii: o linie pe an, luni/trimestre pe axa X',
        perCapita: '‰',
        perCapitaTooltip: 'La 1.000 de locuitori',
        logScale: 'log',
        logTooltip: 'Scară logaritmică (valori foarte inegale)',
        transpose: '⇄',
        transposeTooltip: 'Inversează axele',
        notableTop: 'cea mai mare valoare',
        notableBottom: 'cea mai mică valoare',
        crossFilterHint: 'Click pe hartă sau pe bare filtrează celelalte grafice',
        insTitle: 'Vezi pe INS TEMPO Online',
        v1Title: 'Pagina clasică a setului de date',
        updated: 'Actualizat',
        related: 'Seturi de date înrudite',
        compare: 'Compară →',
        compareTitle: 'Compară cele două seturi de date',
        sibling: 'sub-set al aceluiași tabel',
        similarity: 'similaritate',
        tagTitle: t => `Caută „${t}"`,
        placeProfile: 'profil',
        placeTitle: n => `Profilul locului: ${n}`,
        selected: n => `${n} selectate`,
        expand: 'Mărește',
        collapse: 'Micșorează',
        grain: 'Nivel de detaliu',
        grainTooltip: n => `${n} categorii — fără suprapuneri`,
    },
    en: {
        loading: 'Loading…',
        missingCode: 'Missing ?code= parameter',
        notFound: code => `Dataset "${code}" was not found.`,
        noComposition: 'This dataset has no dashboard configuration yet.',
        splitParent: 'This dataset is published as sub-datasets:',
        axis: { temporal: 'Evolution over time', spatial: 'Territorial distribution',
                ranking: 'Ranking', structural: 'Structure' },
        all: 'All',
        brief: 'In brief:',
        noDataTile: 'No data for this selection',
        noDataGrid: 'No visualization has data for the current filters',
        renderError: 'Render error',
        insightsError: 'Indicators could not be loaded.',
        outliers: 'Outliers vs. the other counties',
        fillRate: 'fill rate',
        since: 'since',
        table: 'Table',
        tableCount: (n, cap) => `${n} rows${n >= cap ? ` (first ${cap})` : ''}`,
        tableError: 'The table could not be loaded.',
        value: 'Value',
        indexTooltip: 'Index: first period = 100',
        yoyTooltip: '% change vs. previous period',
        seasonal: 'Seasonal',
        seasonalTooltip: 'Overlay years: one line per year, months/quarters on X',
        perCapita: '‰',
        perCapitaTooltip: 'Per 1,000 inhabitants',
        logScale: 'log',
        logTooltip: 'Logarithmic scale (highly unequal values)',
        transpose: '⇄',
        transposeTooltip: 'Swap axes',
        notableTop: 'highest value',
        notableBottom: 'lowest value',
        crossFilterHint: 'Clicking the map or bars filters the other charts',
        insTitle: 'View on INS TEMPO Online',
        v1Title: 'Classic dataset page',
        updated: 'Updated',
        related: 'Related datasets',
        compare: 'Compare →',
        compareTitle: 'Compare the two datasets',
        sibling: 'sub-dataset of the same table',
        similarity: 'similarity',
        tagTitle: t => `Search "${t}"`,
        placeProfile: 'profile',
        placeTitle: n => `Place profile: ${n}`,
        selected: n => `${n} selected`,
        expand: 'Expand',
        collapse: 'Collapse',
        grain: 'Level of detail',
        grainTooltip: n => `${n} categories — no overlap`,
    },
};

const TABLE_ROW_CAP = 1000;

// Mirror of dashboard_composer layout/slot rules — tiles whose slice comes
// back empty are dropped client-side and the survivors re-slotted. Wide
// charts (heatmap) always take a full-width row.
const GRID_LAYOUTS = { 1: 'single_full', 2: 'hero_side', 3: 'hero_2side', 4: 'hero_2side_full' };
const GRID_SLOTS = {
    1: ['full'],
    2: ['hero', 'side'],
    3: ['hero', 'side', 'side'],
    4: ['hero', 'side', 'side', 'full'],
};
const WIDE_CHARTS = new Set(['heatmap']);
const GRID_LAYOUTS_WIDE = { 2: 'hero_full', 3: 'hero_side_full', 4: 'hero_2side_full' };
const GRID_SLOTS_WIDE = {
    2: ['hero', 'full'],
    3: ['hero', 'side', 'full'],
    4: ['hero', 'side', 'side', 'full'],
};

/** Composer-mirroring slot assignment: wide charts last, in the full slot. */
function slotCharts(charts) {
    const n = Math.min(charts.length, 4);
    const wide = charts.filter(c => WIDE_CHARTS.has(c.chart_type));
    if (wide.length && n >= 2) {
        return {
            layout: GRID_LAYOUTS_WIDE[n],
            slots: GRID_SLOTS_WIDE[n],
            ordered: [...charts.filter(c => !WIDE_CHARTS.has(c.chart_type)), ...wide],
        };
    }
    return { layout: GRID_LAYOUTS[n], slots: GRID_SLOTS[n], ordered: charts };
}

class DashboardV2 {
    constructor() {
        const params = new URLSearchParams(window.location.search);
        this.code = params.get('code');
        this.lang = params.get('lang') || localStorage.getItem('lens_lang') || 'ro';
        if (!UI_STRINGS[this.lang]) this.lang = 'ro';
        this.ui = UI_STRINGS[this.lang];
        this.metadata = null;
        this.composition = null;
        this.charts = [];       // live ECharts instances
        this.userFilters = {};  // column → label, from the compact filter row
        this.tileFilters = {};  // chart.id → {column → value}, per-tile controls
        this.userLevels = {};   // column → level_id, from the global filter row
        this._refreshTimer = null;
        this.tableOpen = false;
        this.tableData = null;  // cached raw rows for the table view
        this.tableSort = null;  // {col: idx, dir: 1|-1}
        this.tileTransforms = {};  // chart.id → 'index' | 'yoy' | 'seasonal' | null
        this.tileSwaps = {};       // chart.id → bool (x/series transposed)
        this.tileNorms = {};       // chart.id → bool (per-1000-capita)
        this.tileLogs = {};        // chart.id → bool (log scale)
        this._popRef = null;       // /reference/population cache
        try {
            this.userFilters = JSON.parse(params.get('f') || '{}');
        } catch { /* malformed ?f= — ignore */ }
        try {
            this.userLevels = JSON.parse(params.get('g') || '{}');
        } catch { /* malformed ?g= — ignore */ }
        try {
            const t = JSON.parse(params.get('t') || '{}');
            for (const [id, st] of Object.entries(t)) {
                if (st.f) this.tileFilters[id] = st.f;
                if (st.x) this.tileTransforms[id] = st.x;
                if (st.s) this.tileSwaps[id] = true;
                if (st.n) this.tileNorms[id] = true;
                if (st.l) this.tileLogs[id] = true;
            }
        } catch { /* malformed ?t= — ignore */ }
    }

    async init() {
        document.getElementById('dbv2-loader').textContent = this.ui.loading;
        if (!this.code) {
            this.showError(this.ui.missingCode);
            return;
        }
        try {
            this.metadata = await API.getDataset(this.code, { lang: this.lang });
        } catch (e) {
            this.showError(`${this.ui.notFound(this.code)} (${e.message})`);
            return;
        }
        this.composition = this.metadata.chart_config?.composition;
        this.renderHeader();
        // Correspondences load in the background — never block the dashboard
        this.loadRelated();
        if (!this.composition || !this.composition.charts?.length) {
            // Split parents have no parquet of their own — route to the
            // sub-datasets instead of dead-ending on an error.
            if (this.metadata.splits?.length) {
                this.renderSplits();
            } else {
                this.showError(this.ui.noComposition);
            }
            return;
        }
        this.renderFilterRow();

        // KPIs/sentences and chart slices load in parallel
        const insightsPromise = API.fetch(`/datasets/${this.code}/insights`, { lang: this.lang })
            .then(ins => this.renderInsights(ins))
            .catch(e => {
                console.warn('Insights unavailable:', e);
                this.showNotice(this.ui.insightsError);
            });
        await this.refresh();
        document.getElementById('dbv2-loader').classList.add('hidden');
        await insightsPromise;

        window.addEventListener('resize', () => {
            this.charts.forEach(c => c && c.resize && c.resize());
        });
    }

    showError(msg) {
        document.getElementById('dbv2-loader').classList.add('hidden');
        const el = document.getElementById('dbv2-error');
        el.textContent = msg;
        el.classList.remove('hidden');
    }

    /** Non-fatal notice (e.g. insights failed) — dismissible, page stays usable. */
    showNotice(msg) {
        const el = document.getElementById('dbv2-notice');
        if (!el) return;
        el.textContent = msg;
        el.classList.remove('hidden');
        el.onclick = () => el.classList.add('hidden');
    }

    /** Sub-dataset pills for split parents (no parquet of their own). */
    renderSplits() {
        document.getElementById('dbv2-loader').classList.add('hidden');
        const grid = document.getElementById('dbv2-grid');
        const pills = this.metadata.splits.map(s =>
            `<a class="dbv2-split-pill" href="/dataset-v2.html?code=${s.matrix_code}${this.lang !== 'ro' ? `&lang=${this.lang}` : ''}">
                ${s.label || s.matrix_code}
                <span class="dbv2-split-code">${s.matrix_code}</span>
            </a>`).join('');
        grid.className = 'dbv2-grid layout-single_full';
        grid.innerHTML = `<div class="dbv2-splits">
            <div class="dbv2-splits-label">${this.ui.splitParent}</div>
            <div class="dbv2-splits-row">${pills}</div>
        </div>`;
        grid.classList.remove('hidden');
    }

    // ------------------------------------------------------------------ data

    /** Any filter the user actively set (global row or tile control)? */
    hasUserFilters() {
        return Object.keys(this.userFilters).length > 0
            || Object.values(this.tileFilters).some(tf => Object.keys(tf).length);
    }

    /** Resolve a displayed name (map county, bar category) to the exact
     *  data value used in filters — via composer options, then metadata. */
    matchOptionValue(column, name) {
        const norm = s => String(s ?? '').trim();
        const pools = [];
        const fd = (this.composition.filter_dims || []).find(f => f.column === column);
        if (fd) pools.push(fd.options || []);
        for (const ch of this.composition.charts) {
            const c = (ch.controls || []).find(x => x.column === column);
            if (c) pools.push(c.options || []);
        }
        for (const pool of pools) {
            const hit = pool.find(o => norm(o.label) === name || norm(o.value) === name);
            if (hit) return hit.value;
        }
        const dim = (this.metadata.dimensions || []).find(d => d.dim_column_name === column);
        const opt = (dim?.options || []).find(o =>
            norm(o.label) === name || norm(o.sdmx_value) === name
            || norm(o.parsed?.geo_name_clean) === name);
        return opt ? (opt.sdmx_value || opt.label) : null;
    }

    /** Cross-filter: pin `column` to `value` everywhere it's a control —
     *  the global row when it lives there, otherwise on every tile that
     *  doesn't chart the column. Same value again clears the pin. */
    setCrossFilter(column, value) {
        // Remember geo clicks even when nothing filterable listens — the
        // spatial tile turns the pick into a place-profile link
        const isGeo = (this.metadata.dimensions || []).some(d =>
            d.dim_type === 'geo' && d.dim_column_name === column);
        if (isGeo) {
            this._geoPick = (this._geoPick?.value === value)
                ? null : { column, value };
        }
        const fd = (this.composition.filter_dims || []).find(f => f.column === column);
        if (fd) {
            if (this.userFilters[column] === value) delete this.userFilters[column];
            else this.userFilters[column] = value;
            this.renderFilterRow();
            this.refresh();
            return;
        }
        const targets = this.composition.charts.filter(ch =>
            !ch.data.group_by.includes(column)
            && (ch.controls || []).some(c => c.column === column));
        if (!targets.length) {
            if (isGeo) this.refresh();  // re-render tile bars → place chip
            return;
        }
        const allSet = targets.every(ch => this.tileFilters[ch.id]?.[column] === value);
        for (const ch of targets) {
            const tf = this.tileFilters[ch.id] ||= {};
            if (allSet) delete tf[column];
            else tf[column] = value;
        }
        this.refresh();
    }

    onChartClick(chart, params) {
        if (!params || params.componentType !== 'series') return;
        const column = chart.roles?.x_axis;
        if (!column || column === 'TIME_PERIOD') return;
        const name = String(params.name || '').trim();
        if (!name) return;
        const value = this.matchOptionValue(column, name);
        if (value != null) this.setCrossFilter(column, value);
    }

    async refresh() {
        this.syncURL();
        const slices = await this.fetchSlices();
        // Composer-time data holes answer no question — drop those tiles and
        // re-layout around the survivors. But once the USER has filtered
        // (globally or per-tile), every tile stays visible with an explicit
        // empty message: silent disappearance reads as a bug, and the user
        // needs the tile's controls to undo the selection.
        const keepAll = this.hasUserFilters();
        const alive = this.composition.charts.filter(c => {
            const d = slices.get(c.id);
            return keepAll || (d && d.rows?.length);
        });
        this.renderGrid(alive);
        if (alive.length) await this.renderTiles(alive, slices);
        if (this.tableOpen) this.renderTable();
    }

    /** Effective filters for one tile: composed pins ⊕ tile controls ⊕ global row. */
    tileEffectiveFilters(chart) {
        const f = { ...chart.data.filters };
        for (const [col, v] of Object.entries(this.tileFilters[chart.id] || {})) {
            f[col] = [v];
        }
        for (const [col, vals] of Object.entries(this.expandedUserFilters())) {
            f[col] = vals;
        }
        return f;
    }

    /** User-selected filter values, with trimmed/untrimmed variants like the
     *  composer emits (metadata labels may carry indentation whitespace). */
    expandedUserFilters() {
        const out = {};
        for (const [col, lvl] of Object.entries(this.userLevels)) {
            const members = this.levelMembers(col, lvl);
            if (members) out[col] = members;
        }
        for (const [col, val] of Object.entries(this.userFilters)) {
            if (!val) continue;
            const picks = Array.isArray(val) ? val : [val];
            if (!picks.length) continue;
            out[col] = picks.flatMap(v => this._labelVariants(v));
        }
        return out;
    }

    /** A label and its trimmed form — metadata carries indentation the
     *  parquet may not, and the composer sends both spellings too. */
    _labelVariants(label) {
        const t = String(label).trim();
        return t !== String(label) ? [String(label), t] : [String(label)];
    }

    /** Data values of one grain of a dimension, from composition.dim_levels
     *  (sent once per dataset, not per tile). */
    levelMembers(column, levelId) {
        const entries = this.composition?.dim_levels?.[column];
        if (!entries) return null;
        return entries.find(l => l.level_id === levelId)?.members || null;
    }

    /** Coalesce bursts of control changes into one round of fetches —
     *  ticking five checkboxes should not fire five times four requests. */
    refreshSoon() {
        clearTimeout(this._refreshTimer);
        this._refreshTimer = setTimeout(() => this.refresh(), 250);
    }

    /** Fetch the slice of every tile (identical requests deduped), keyed by
     *  chart.id. Slices are data-grounded server-side (built from values
     *  that exist in the parquet), so an empty result is genuine. */
    async fetchSlices() {
        const inflight = new Map();
        const jobs = this.composition.charts.map(async chart => {
            const filters = this.tileEffectiveFilters(chart);
            const key = JSON.stringify([chart.data.group_by, filters]);
            if (!inflight.has(key)) {
                inflight.set(key,
                    API.getDatasetData(this.code, filters, 50000,
                                       { groupBy: chart.data.group_by })
                        .catch(e => {
                            console.error(`Slice for ${chart.id} failed:`, e);
                            return null;
                        }));
            }
            return [chart.id, await inflight.get(key)];
        });
        return new Map(await Promise.all(jobs));
    }

    // -------------------------------------------------------------------- ui

    renderHeader() {
        const m = this.metadata;
        const cfg = m.chart_config || {};
        const profile = m.profile || {};
        const timeRange = profile.time_year_min && profile.time_year_max
            ? `${profile.time_year_min}–${profile.time_year_max}` : null;

        let pathHtml = '';
        if (m.context_path?.length) {
            const codes = [];
            const crumbs = m.context_path.map(p => {
                codes.push(p.code);
                return `<a class="dash-crumb-link" href="/?cat=${codes.join(':')}">${p.name}</a>`;
            });
            pathHtml = `<div class="dash-breadcrumbs">${crumbs.join('<span class="dash-crumb-sep">›</span>')}</div>`;
        }

        const insCode = m.parent_matrix_code || m.matrix_code;
        document.getElementById('dbv2-header').innerHTML = `
            ${pathHtml}
            <div class="dash-title-row">
                <div class="dash-title">
                    ${m.matrix_name}
                    <span class="dash-code">${m.matrix_code}</span>
                </div>
                <div class="dash-download">
                    <a class="dl-btn v1-badge" href="/?code=${m.matrix_code}" title="${this.ui.v1Title}">← v1</a>
                    <a class="dl-btn" href="http://statistici.insse.ro/tempoins/index.jsp?page=tempo3&lang=${this.lang === 'en' ? 'en' : 'ro'}&ind=${insCode}" target="_blank" rel="noopener" title="${this.ui.insTitle}">INS ↗</a>
                    <a class="dl-btn" href="/sdmx/2.1/data/INS,${m.matrix_code}/" target="_blank" rel="noopener" title="SDMX-ML 2.1 data feed">SDMX ↗</a>
                    <button class="dl-btn" id="dbv2-csv-btn">↓ CSV</button>
                    <button class="dl-btn" id="dbv2-xlsx-btn">↓ XLSX</button>
                    <button class="dl-btn" id="dbv2-table-btn">☰ ${this.ui.table}</button>
                </div>
            </div>
            <div class="dash-meta">
                ${cfg.archetype ? `<span class="meta-pill archetype">${cfg.archetype}</span>` : ''}
                ${timeRange ? `<span class="meta-pill time">${timeRange}</span>` : ''}
                ${m.ultima_actualizare ? `<span class="meta-pill updated">${this.ui.updated} ${m.ultima_actualizare}</span>` : ''}
                <span class="meta-pill v2">dashboard v2</span>
            </div>
        `;
        document.title = `${m.matrix_name} — INS+ v2`;

        const dlUrl = fmt => `/api/datasets/${m.matrix_code}/download?format=${fmt}`
            + `&lang=${this.lang}&filters=${encodeURIComponent(JSON.stringify(this.expandedUserFilters()))}`;
        document.getElementById('dbv2-csv-btn').addEventListener('click',
            () => { window.location.href = dlUrl('csv'); });
        document.getElementById('dbv2-xlsx-btn').addEventListener('click',
            () => { window.location.href = dlUrl('xlsx'); });
        document.getElementById('dbv2-table-btn').addEventListener('click',
            () => this.toggleTable());
        // Theme & language toggles live in the site chrome topbar —
        // recreate the charts when the chrome flips the ECharts theme
        window.addEventListener('themechange', () => this.refresh());
    }

    // -------------------------------------------------------------- insights

    sparklineSVG(values, w = 84, h = 26) {
        if (!values || values.length < 2) return '';
        const min = Math.min(...values), max = Math.max(...values);
        const span = max - min || 1;
        const pts = values.map((v, i) =>
            `${(i / (values.length - 1) * w).toFixed(1)},${(h - 2 - (v - min) / span * (h - 4)).toFixed(1)}`
        ).join(' ');
        return `<svg class="dbv2-spark" width="${w}" height="${h}" viewBox="0 0 ${w} ${h}">
            <polyline points="${pts}" fill="none" stroke="currentColor" stroke-width="1.5"/>
        </svg>`;
    }

    renderInsights(ins) {
        if (!ins) return;
        const kpiEl = document.getElementById('dbv2-kpis');
        const cards = (ins.kpis || []).map(k => {
            let value = '', sub = '';
            if (k.key === 'latest') {
                value = `${formatNumber(k.value)}${this.sparklineSVG(k.sparkline)}`;
                // context = non-total pins ("Masculin") — without them the
                // number reads as the dataset-wide value, which it isn't
                sub = [k.unit, k.period, ...(k.context || [])].filter(Boolean).join(' · ');
            } else if (k.format === 'pct') {
                const up = k.direction === 'up';
                value = `<span class="${up ? 'dbv2-up' : 'dbv2-down'}">${up ? '▲' : '▼'} ${Math.abs(k.value).toFixed(1)}%</span>`;
                sub = k.since ? `${this.ui.since} ${k.since}` : '';
            } else if (k.badge) {
                value = `<span class="dbv2-badge dbv2-badge-${k.badge}">${k.badge_label}</span>`;
            } else {
                value = k.value ?? '—';
                // fill_rate > 1 means coverage was computed against a different
                // dataset shape (e.g. split parent) — hide it rather than show 5156%
                if (k.fill_rate != null && k.fill_rate <= 1) sub = `${this.ui.fillRate}: ${Math.round(k.fill_rate * 100)}%`;
            }
            return `<div class="dbv2-kpi">
                <div class="dbv2-kpi-label">${k.label}</div>
                <div class="dbv2-kpi-value">${value}</div>
                ${sub ? `<div class="dbv2-kpi-sub">${sub}</div>` : ''}
            </div>`;
        });
        if (cards.length) {
            kpiEl.innerHTML = cards.join('');
            kpiEl.classList.remove('hidden');
        }

        if (ins.sentences?.length) {
            const sEl = document.getElementById('dbv2-sentences');
            sEl.innerHTML = `<span class="dbv2-sentences-label">${this.ui.brief}</span> ` +
                ins.sentences.map(s => `<span class="dbv2-sentence">${s}</span>`).join(' ');
            sEl.classList.remove('hidden');
            this.renderNotables(ins.notables || [], sEl);
        }
    }

    /** Actionable notable-slice chips (top/bottom entity) appended to the
     *  sentence strip — clicking pins that entity across the dashboard. */
    renderNotables(notables, host) {
        for (const n of notables) {
            if (!n.column || n.value == null) continue;
            const btn = document.createElement('button');
            btn.className = 'dbv2-notable';
            const arrow = n.type === 'bottom' ? '▼' : '▲';
            btn.innerHTML = `${arrow} ${n.label}${n.amount ? ` <span class="dbv2-notable-amt">${n.amount}</span>` : ''}`;
            btn.title = (n.type === 'bottom' ? this.ui.notableBottom : this.ui.notableTop)
                + ' · ' + this.ui.crossFilterHint;
            btn.addEventListener('click', () => this.setCrossFilter(n.column, n.value));
            host.appendChild(btn);
        }
    }

    dimLabel(col) {
        const d = (this.metadata.dimensions || []).find(x => x.dim_column_name === col);
        return d ? d.dim_label : col;
    }

    tileTitle(chart) {
        const base = this.ui.axis[chart.axis] || chart.axis;
        if (chart.axis === 'structural' || chart.axis === 'ranking') {
            const x = chart.roles?.x_axis;
            if (x && x !== 'TIME_PERIOD') return `${base}: ${this.dimLabel(x)}`;
        }
        return base;
    }

    /** Inline selects for the tile's pinned dims (composer `controls`) —
     *  every pin the composer made is a default the user can change. */
    tileControls(chart) {
        const frag = document.createDocumentFragment();
        for (const ctrl of chart.controls || []) {
            const sel = document.createElement('select');
            sel.className = 'dbv2-chip-select';
            sel.title = ctrl.label || ctrl.column;
            for (const opt of ctrl.options) {
                const o = document.createElement('option');
                o.value = opt.value;
                o.textContent = opt.label;
                sel.appendChild(o);
            }
            sel.value = this.tileFilters[chart.id]?.[ctrl.column] ?? ctrl.default;
            sel.addEventListener('change', () => {
                const tf = this.tileFilters[chart.id] ||= {};
                if (sel.value === ctrl.default) delete tf[ctrl.column];
                else tf[ctrl.column] = sel.value;
                this.refresh();
            });
            frag.appendChild(sel);
        }
        this.tileTransformChips(chart, frag);
        this.tilePerspectiveChips(chart, frag);
        return frag;
    }

    /** Blow one tile up to full width and height. A 103-bar pyramid or a
     *  40-series heatmap is unreadable in a 200px side slot, and the grain
     *  switcher makes that easy to hit on purpose. */
    expandBtn(chart, tile) {
        const btn = document.createElement('button');
        btn.className = 'dbv2-expand';
        btn.type = 'button';
        const sync = () => {
            const on = tile.classList.contains('expanded');
            btn.textContent = on ? '\u2715' : '\u2922';
            btn.title = on ? this.ui.collapse : this.ui.expand;
        };
        btn.addEventListener('click', () => {
            const on = tile.classList.toggle('expanded');
            this.expanded = on ? chart.id : null;
            sync();
            // The container changed size under ECharts; it cannot know.
            const inst = this.charts.find(c => c.getDom() === tile.querySelector('.dbv2-tile-chart'));
            requestAnimationFrame(() => inst?.resize());
        });
        sync();
        return btn;
    }

    _chipBtn(frag, label, tip, active, onClick) {
        const btn = document.createElement('button');
        btn.className = 'dbv2-chip-btn' + (active ? ' active' : '');
        btn.textContent = label;
        btn.title = tip;
        btn.addEventListener('click', onClick);
        frag.appendChild(btn);
    }

    /** Index / Δ% / Sezonier toggle chips — temporal line/area tiles only. */
    tileTransformChips(chart, frag) {
        const timeOnX = chart.axis === 'temporal'
            && chart.data.group_by.includes(chart.roles?.x_axis)
            && (this.metadata.dimensions || []).some(d =>
                d.dim_type === 'time' && d.dim_column_name === chart.roles.x_axis);
        if (!timeOnX || !['line', 'area_stacked', 'bar_vertical'].includes(chart.chart_type)) return;
        const modes = [['index', 'Index', this.ui.indexTooltip],
                       ['yoy', 'Δ%', this.ui.yoyTooltip]];
        // Seasonal overlay only makes sense for sub-annual series
        const gran = this.metadata.profile?.time_granularity;
        if (gran === 'monthly' || gran === 'quarterly') {
            modes.push(['seasonal', this.ui.seasonal, this.ui.seasonalTooltip]);
        }
        for (const [mode, label, tip] of modes) {
            this._chipBtn(frag, label, tip, this.tileTransforms[chart.id] === mode, () => {
                this.tileTransforms[chart.id] =
                    this.tileTransforms[chart.id] === mode ? null : mode;
                this.refresh();
            });
        }
    }

    /** Perspective chips: transpose (structural), ‰ per-capita (geo counts),
     *  log scale (right-skewed distributions). */
    tilePerspectiveChips(chart, frag) {
        const sig = this.metadata.chart_config?.dataset_signature || {};
        const roles = chart.roles || {};

        // Transpose: both axes categorical → swapping asks the mirror question
        if (['grouped_bar', 'stacked_bar', 'heatmap', 'bubble'].includes(chart.chart_type)
                && roles.x_axis && roles.series) {
            this._chipBtn(frag, this.ui.transpose, this.ui.transposeTooltip,
                !!this.tileSwaps[chart.id], () => {
                    this.tileSwaps[chart.id] = !this.tileSwaps[chart.id];
                    this.refresh();
                });
        }

        // Per-capita: absolute counts over geo areas
        const geoOnX = (this.metadata.dimensions || []).some(d =>
            d.dim_type === 'geo' && d.dim_column_name === roles.x_axis);
        if (geoOnX && this.metadata.chart_config?.primary_unit_type === 'count') {
            this._chipBtn(frag, this.ui.perCapita, this.ui.perCapitaTooltip,
                !!this.tileNorms[chart.id], () => {
                    this.tileNorms[chart.id] = !this.tileNorms[chart.id];
                    this.refresh();
                });
        }

        // Log scale: dominant categories flatten everything else
        if (sig.distribution === 'right_skewed'
                && ['line', 'horizontal_bar', 'bar_vertical'].includes(chart.chart_type)) {
            this._chipBtn(frag, this.ui.logScale, this.ui.logTooltip,
                !!this.tileLogs[chart.id], () => {
                    this.tileLogs[chart.id] = !this.tileLogs[chart.id];
                    this.refresh();
                });
        }
    }

    /** (Re)build the tile grid for the given charts. Called on every
     *  refresh — filter changes can empty or revive individual slices. */
    renderGrid(activeCharts) {
        this.charts.forEach(c => { try { c.dispose(); } catch { /* gone */ } });
        this.charts = [];
        const grid = document.getElementById('dbv2-grid');
        grid.innerHTML = '';
        if (!activeCharts.length) {
            grid.className = 'dbv2-grid layout-single_full';
            grid.innerHTML = `<div class="dbv2-empty">${this.ui.noDataGrid}</div>`;
            grid.classList.remove('hidden');
            return;
        }
        const { layout, slots, ordered } = slotCharts(activeCharts);
        grid.className = `dbv2-grid layout-${layout}`;
        let sideIdx = 0;
        ordered.forEach((chart, i) => {
            const slot = slots[i];
            const area = slot === 'side' ? `side${++sideIdx}` : slot;
            const tile = document.createElement('div');
            tile.className = `dbv2-tile dbv2-slot-${slot}`;
            tile.style.gridArea = area;
            tile.innerHTML = `
                <div class="dbv2-tile-bar">
                    <span class="dbv2-tile-title">${this.tileTitle(chart)}</span>
                    <span class="dbv2-tile-type">${chart.chart_type}</span>
                </div>
                <div class="dbv2-tile-chart" id="dbv2-chart-${chart.id}"></div>
            `;
            const bar = tile.querySelector('.dbv2-tile-bar');
            bar.insertBefore(this.tileControls(chart), bar.querySelector('.dbv2-tile-type'));
            this.placeChip(chart, bar);
            bar.appendChild(this.expandBtn(chart, tile));
            grid.appendChild(tile);
        });
        grid.classList.remove('hidden');
    }

    async renderTiles(activeCharts, slices) {
        for (const chart of activeCharts) {
            const container = document.getElementById(`dbv2-chart-${chart.id}`);
            container.innerHTML = '';
            const data = slices.get(chart.id);
            if (!data || !data.rows?.length) {
                // Empty under the current (user-set) filters — same message
                // regardless of which control caused it
                container.innerHTML = `<div class="dbv2-empty">${this.ui.noDataTile}</div>`;
                continue;
            }
            // Per-tile config in the exact shape resolveRoles()/createChart() expect.
            // Compat fields (time_dim/geo_dim) must point at columns present in
            // THIS tile's slice — the dataset-level ones may reference dims the
            // slice pinned away (e.g. a base-year time dim), which would route
            // chart-factory to the wrong renderer.
            const dims = this.metadata.dimensions || [];
            const inSlice = col => chart.data.group_by.includes(col);
            const sliceDim = type => dims.find(d =>
                d.dim_type === type && inSlice(d.dim_column_name))?.dim_column_name || null;
            const transform = this.tileTransforms[chart.id] || null;
            // Transposed structural tiles ask the mirror question of the
            // same slice — swap the visual roles, data stays identical.
            const roles = this.tileSwaps[chart.id] && chart.roles?.series
                ? { ...chart.roles, x_axis: chart.roles.series, series: chart.roles.x_axis }
                : chart.roles;
            const timeDim = sliceDim('time');

            let tileData = data;
            let valueFormat = null;
            let seasonalMode = false;
            if (transform === 'seasonal') {
                const useAvg = ['percentage', 'time_unit', 'index', 'rate', 'ratio']
                    .includes(this.metadata.chart_config?.primary_unit_type);
                const s = seasonalOverlay(data, timeDim, useAvg);
                if (s) { tileData = s; seasonalMode = true; }
            } else if (transform) {
                tileData = applyTimeTransform(data, timeDim, roles?.series, transform);
                valueFormat = transform === 'index' ? 'index' : 'pct_change';
            }
            if (this.tileNorms[chart.id] && !seasonalMode) {
                tileData = await this.normalizePerCapita(tileData, roles, chart) || tileData;
            }

            const tileRoles = seasonalMode
                ? { x_axis: '__SUB__', series: '__YEAR__' } : roles;
            const tileConfig = {
                ...this.metadata.chart_config,
                primary_chart: chart.chart_type,
                ranked_charts: [{ chart_type: chart.chart_type, roles: tileRoles }],
                time_dim: seasonalMode ? '__SUB__' : timeDim,
                geo_dim: sliceDim('geo'),
                _valueFormat: valueFormat,
                _logScale: !!this.tileLogs[chart.id],
            };
            delete tileConfig.composition;
            try {
                const instance = await createChart(container, tileConfig, tileData, this.metadata);
                if (instance) {
                    this.charts.push(instance);
                    // Peak/trough pins describe the RAW series — skip them
                    // when the tile shows a transformed/normalized view
                    if (typeof applyAnnotations === 'function' && !transform
                            && !this.tileNorms[chart.id]) {
                        applyAnnotations(instance, chart.annotations);
                    }
                    instance.on('click', p => this.onChartClick({ ...chart, roles }, p));
                }
                this.renderOutlierChip(chart);
            } catch (e) {
                console.error(`Tile ${chart.id} render failed:`, e);
                container.innerHTML = `<div class="dbv2-empty">${this.ui.renderError}</div>`;
            }
        }
    }

    geoLevelForDim() {
        const lv = this.metadata.chart_config?.dataset_signature?.geo_levels || [];
        return lv.includes('county') ? 'county'
             : lv.includes('region') ? 'region' : 'macroregion';
    }

    /** Divide count values by population/1000 of the row's area+year.
     *  Population comes from /api/reference/population (POP105A), matched
     *  by clean geo name with nearest-year fallback (population moves
     *  slowly; dropping pre-coverage years would break map timelines). */
    async normalizePerCapita(data, roles, chart) {
        if (!data?.rows?.length) return null;
        if (!this._popRef) {
            try {
                this._popRef = await API.fetch('/reference/population',
                    { level: this.geoLevelForDim() });
            } catch (e) {
                console.warn('Population reference unavailable:', e);
                return null;
            }
        }
        const popByArea = this._popRef.population || {};
        const cols = data.columns;
        const gi = cols.indexOf(roles.x_axis);
        const vi = cols.length - 1;
        if (gi === -1) return null;

        const clean = s => String(s ?? '').trim();
        const timeDims = (this.metadata.dimensions || []).filter(d => d.dim_type === 'time');
        const ti = timeDims.map(d => cols.indexOf(d.dim_column_name)).find(i => i !== -1) ?? -1;
        let pinnedYear = null;
        for (const d of timeDims) {
            const f = chart.data.filters[d.dim_column_name];
            const m = f && /(\d{4})/.exec(String(f[0]));
            if (m) { pinnedYear = m[1]; break; }
        }
        const geoDim = (this.metadata.dimensions || []).find(d => d.dim_column_name === roles.x_axis);
        const toClean = {};
        for (const o of geoDim?.options || []) {
            const c = o.parsed?.geo_name_clean;
            if (!c) continue;
            toClean[clean(o.label)] = c;
            if (o.sdmx_value) toClean[clean(o.sdmx_value)] = c;
            toClean[c] = c;
        }
        const popFor = (area, year) => {
            const series = popByArea[toClean[clean(area)] || clean(area)];
            if (!series) return null;
            if (year && series[year] != null) return series[year];
            const years = Object.keys(series);
            if (!years.length) return null;
            if (!year) return series[years.sort()[years.length - 1]];
            let best = years[0];
            for (const y of years) {
                if (Math.abs(+y - +year) < Math.abs(+best - +year)) best = y;
            }
            return series[best];
        };
        const rows = [];
        for (const r of data.rows) {
            const year = ti !== -1
                ? ((/(\d{4})/.exec(String(r[ti])) || [])[1] || pinnedYear)
                : pinnedYear;
            const p = popFor(r[gi], year);
            if (!p) continue;
            const nr = [...r];
            nr[vi] = r[vi] != null ? r[vi] / (p / 1000) : null;
            rows.push(nr);
        }
        return rows.length ? { ...data, rows } : null;
    }

    /** Caption chip on spatial tiles listing outlier counties from trends.
     *  Each county is clickable — pins it across the dashboard. */
    renderOutlierChip(chart) {
        const outliers = (chart.annotations || [])
            .find(a => a.type === 'outlier_regions')?.values;
        if (!outliers?.length) return;
        const bar = document.querySelector(`#dbv2-chart-${chart.id}`)
            ?.closest('.dbv2-tile')?.querySelector('.dbv2-tile-bar');
        if (!bar || bar.querySelector('.dbv2-chip-outliers')) return;
        const chip = document.createElement('span');
        chip.className = 'dbv2-chip dbv2-chip-outliers';
        chip.title = `${this.ui.outliers} · ${this.ui.crossFilterHint}`;
        chip.append('⚠ ');
        outliers.slice(0, 3).forEach((name, i) => {
            if (i) chip.append(', ');
            const a = document.createElement('span');
            a.className = 'dbv2-chip-link';
            a.textContent = name;
            a.addEventListener('click', () => {
                const col = chart.roles?.x_axis;
                const v = col ? this.matchOptionValue(col, String(name).trim()) : null;
                if (v != null) this.setCrossFilter(col, v);
            });
            chip.appendChild(a);
        });
        bar.insertBefore(chip, bar.querySelector('.dbv2-tile-type'));
    }

    // ------------------------------------------------------- correspondences

    /** Tags under the title + related-datasets rail at the bottom.
     *  Both come from /related — one background fetch, failures silent. */
    async loadRelated() {
        let rel;
        try {
            rel = await API.fetch(`/datasets/${this.code}/related`, { lang: this.lang });
        } catch (e) {
            console.warn('Related datasets unavailable:', e);
            return;
        }
        this.renderTags(rel.tags || []);
        this.renderRelated(rel.related || []);
    }

    /** Topic tag chips appended to the header meta row → catalog search. */
    renderTags(tags) {
        const meta = document.querySelector('#dbv2-header .dash-meta');
        if (!meta || !tags.length) return;
        for (const tag of tags.slice(0, 6)) {
            const a = document.createElement('a');
            a.className = 'dbv2-tag';
            a.textContent = `#${tag}`;
            a.title = this.ui.tagTitle(tag);
            a.href = `/?q=${encodeURIComponent(tag)}${this.lang !== 'ro' ? `&lang=${this.lang}` : ''}`;
            meta.appendChild(a);
        }
    }

    renderRelated(related) {
        const host = document.getElementById('dbv2-related');
        if (!host || !related.length) return;
        const langQ = this.lang !== 'ro' ? `&lang=${this.lang}` : '';
        const cards = related.map(r => {
            const href = `/dataset-v2.html?code=${r.matrix_code}${langQ}`;
            const simPct = r.similarity != null ? Math.round(r.similarity * 100) : null;
            const badge = r.relationship_type === 'sibling'
                ? `<span class="dbv2-rel-sim sibling" title="${this.ui.sibling}">＝</span>`
                : simPct != null
                    ? `<span class="dbv2-rel-sim" title="${this.ui.similarity}">${simPct}%</span>`
                    : '';
            const dims = (r.shared_dims || [])
                .map(d => `<span class="dbv2-rel-dim">${d}</span>`).join('');
            const compare = r.can_compare
                ? `<a class="dbv2-rel-compare" title="${this.ui.compareTitle}"
                     href="/compare.html?a=${this.code}&b=${r.matrix_code}${langQ}">${this.ui.compare}</a>`
                : '';
            // div + click handler, not <a>: the compare link inside would nest
            // anchors, which the HTML parser splits into duplicate cards
            return `<div class="dbv2-rel-card" data-href="${href}">
                <div class="dbv2-rel-top">${badge}<span class="dbv2-rel-code">${r.matrix_code}</span>
                    ${r.time_range ? `<span class="dbv2-rel-time">${r.time_range}</span>` : ''}</div>
                <div class="dbv2-rel-name">${r.name}</div>
                <div class="dbv2-rel-foot">${dims}${compare}</div>
            </div>`;
        }).join('');
        host.innerHTML = `<div class="dbv2-related-label">${this.ui.related}</div>
            <div class="dbv2-related-row">${cards}</div>`;
        host.querySelectorAll('.dbv2-rel-card').forEach(card =>
            card.addEventListener('click', e => {
                if (e.target.closest('.dbv2-rel-compare')) return;
                window.location.href = card.dataset.href;
            }));
        host.classList.remove('hidden');
    }

    /** Mirror of place_service.slugify — county/region name → /place slug. */
    placeSlug(name) {
        return String(name).replace(/^regiunea\s+/i, '').trim()
            .normalize('NFKD').replace(/[\u0300-\u036f]/g, '')
            .toLowerCase().replace(/[\s_]+/g, '-').replace(/[^a-z0-9-]/g, '')
            .replace(/-+/g, '-').replace(/^-+|-+$/g, '');
    }

    /** When a cross-filter pins a geo value, the spatial tile (which charts
     *  the geo dim, so the pin doesn't apply to it) links to that place's
     *  profile page instead. */
    placeChip(chart, bar) {
        const col = chart.roles?.x_axis;
        const geoDim = (this.metadata.dimensions || []).find(d =>
            d.dim_type === 'geo' && d.dim_column_name === col);
        if (!geoDim) return;
        let value = this.userFilters[col];
        if (!value) {
            for (const tf of Object.values(this.tileFilters)) {
                if (tf[col]) { value = tf[col]; break; }
            }
        }
        if (!value && this._geoPick?.column === col) value = this._geoPick.value;
        if (!value) return;
        const opt = (geoDim.options || []).find(o =>
            o.label === value || o.label?.trim() === String(value).trim()
            || o.sdmx_value === value);
        const cleanName = opt?.parsed?.geo_name_clean || String(value).trim();
        const level = this.geoLevelForDim();
        if (level === 'macroregion') return;  // no macroregion profiles
        const a = document.createElement('a');
        a.className = 'dbv2-chip dbv2-chip-place';
        a.textContent = `↗ ${this.ui.placeProfile}: ${cleanName}`;
        a.title = this.ui.placeTitle(cleanName);
        a.href = `/place/${level}/${this.placeSlug(cleanName)}`;
        bar.insertBefore(a, bar.querySelector('.dbv2-tile-type'));
    }

    // ------------------------------------------------------------ data table

    toggleTable() {
        this.tableOpen = !this.tableOpen;
        const el = document.getElementById('dbv2-table');
        document.getElementById('dbv2-table-btn')?.classList.toggle('active', this.tableOpen);
        if (!this.tableOpen) {
            el.classList.add('hidden');
            return;
        }
        el.classList.remove('hidden');
        this.renderTable();
    }

    /** Raw-rows table (respects the global filter row), sortable by column. */
    async renderTable() {
        const wrap = document.getElementById('dbv2-table-wrap');
        const countEl = document.getElementById('dbv2-table-count');
        const filterKey = JSON.stringify(this.expandedUserFilters());
        if (!this.tableData || this.tableData.key !== filterKey) {
            wrap.innerHTML = `<div class="dbv2-empty">${this.ui.loading}</div>`;
            try {
                const data = await API.getDatasetData(
                    this.code, this.expandedUserFilters(), TABLE_ROW_CAP);
                this.tableData = { key: filterKey, data };
                this.tableSort = null;
            } catch (e) {
                console.error('Table fetch failed:', e);
                wrap.innerHTML = `<div class="dbv2-empty">${this.ui.tableError}</div>`;
                return;
            }
        }
        const { columns, rows, column_labels } = this.tableData.data;
        const headers = columns.map(c => c === 'OBS_VALUE' ? this.ui.value : this.dimLabel(c));

        let sorted = rows;
        if (this.tableSort) {
            const { col, dir } = this.tableSort;
            sorted = [...rows].sort((a, b) => {
                const va = a[col], vb = b[col];
                if (va == null) return 1;
                if (vb == null) return -1;
                if (typeof va === 'number' && typeof vb === 'number') return (va - vb) * dir;
                return String(va).localeCompare(String(vb)) * dir;
            });
        }

        const label = (ci, v) => {
            if (v == null) return '—';
            const map = column_labels?.[columns[ci]];
            const s = map?.[String(v)] ?? v;
            return typeof s === 'number' ? formatNumber(s) : String(s).trim();
        };
        const head = headers.map((h, i) => {
            const arrow = this.tableSort?.col === i
                ? (this.tableSort.dir > 0 ? ' ▲' : ' ▼') : '';
            return `<th data-col="${i}">${h}${arrow}</th>`;
        }).join('');
        const body = sorted.map(r =>
            `<tr>${r.map((v, ci) => `<td>${label(ci, v)}</td>`).join('')}</tr>`
        ).join('');
        wrap.innerHTML = `<table><thead><tr>${head}</tr></thead><tbody>${body}</tbody></table>`;
        countEl.textContent = this.ui.tableCount(rows.length, TABLE_ROW_CAP);

        wrap.querySelectorAll('th').forEach(th => {
            th.addEventListener('click', () => {
                const col = Number(th.dataset.col);
                const dir = (this.tableSort?.col === col && this.tableSort.dir > 0) ? -1 : 1;
                this.tableSort = { col, dir };
                this.renderTable();
            });
        });
    }

    // ----------------------------------------------------------- filter row

    /** Current effective value of a filter dim ('' = Toate). */
    _filterValue(fd, options) {
        const current = this.userFilters[fd.column];
        if (current) return current;
        if (fd.default != null) return fd.default;
        return fd.allow_all ? '' : options[0].value;
    }

    _setFilter(column, value, rerender = true) {
        const empty = value == null || value === ''
            || (Array.isArray(value) && value.length === 0);
        if (empty) delete this.userFilters[column];
        else this.userFilters[column] = value;
        if (rerender) { this.renderFilterRow(); this.refresh(); }
        else this.refreshSoon();
    }

    _setLevel(column, levelId, fallback) {
        if (!levelId || levelId === fallback) delete this.userLevels[column];
        else this.userLevels[column] = levelId;
        this.renderFilterRow();
        this.refresh();
    }

    /** Checkbox dropdown for 7-25 options. The composer has emitted
     *  widget:'multi_select' since the beginning; nothing rendered it, so
     *  every filter on this page used to be single-value. */
    _multiSelect(wrap, fd, options, value) {
        const picked = new Set(
            (Array.isArray(value) ? value : (value ? [value] : [])).map(String));
        const det = document.createElement('details');
        det.className = 'dbv2-multi';
        const sum = document.createElement('summary');
        const caption = () => picked.size === 0 ? this.ui.all
            : picked.size === 1
                ? (options.find(o => picked.has(String(o.value)))?.label || '1')
                : this.ui.selected(picked.size);
        sum.textContent = caption();
        det.appendChild(sum);
        const list = document.createElement('div');
        list.className = 'dbv2-multi-list';
        for (const opt of options) {
            const row = document.createElement('label');
            const cb = document.createElement('input');
            cb.type = 'checkbox';
            cb.checked = picked.has(String(opt.value));
            cb.addEventListener('change', () => {
                if (cb.checked) picked.add(String(opt.value));
                else picked.delete(String(opt.value));
                sum.textContent = caption();
                this._setFilter(fd.column, [...picked], false);
            });
            row.appendChild(cb);
            row.append(' ' + opt.label);
            list.appendChild(row);
        }
        det.appendChild(list);
        wrap.appendChild(det);
    }

    /** Grain switcher: pick which level of a multi-level dimension is shown.
     *  Not a value picker — every level covers the whole dimension once. */
    _levelSwitch(wrap, column, levels, current, onPick) {
        const pills = document.createElement('span');
        pills.className = 'dbv2-pills dbv2-levels';
        for (const lv of levels) {
            const b = document.createElement('button');
            b.className = 'dbv2-pill' + (lv.level_id === current ? ' active' : '');
            b.textContent = lv.name;
            b.title = this.ui.grainTooltip(lv.n);
            b.addEventListener('click', () => onPick(lv.level_id));
            pills.appendChild(b);
        }
        wrap.appendChild(pills);
    }

    /** (Re)build the global filter row. Widget per composer hint:
     *  pill_group (few options), select (medium), typeahead (many). */
    renderFilterRow() {
        document.querySelector('.dbv2-filter-row')?.remove();
        const dims = this.composition.filter_dims || [];
        const grains = this.composition.grain_dims || [];
        if (!dims.length && !grains.length) return;
        const grid = document.getElementById('dbv2-grid');
        const row = document.createElement('div');
        row.className = 'dbv2-filter-row';

        // Grain first: it changes what every tile is counting, so it reads
        // ahead of the filters that only narrow the selection.
        for (const g of grains) {
            const wrap = document.createElement('label');
            wrap.className = 'dbv2-filter dbv2-grain';
            wrap.textContent = g.label || g.column;
            this._levelSwitch(wrap, g.column, g.levels,
                this.userLevels[g.column] || g.default,
                id => this._setLevel(g.column, id, g.default));
            row.appendChild(wrap);
        }

        for (const fd of dims) {
            // Composer emits data-grounded options (only values present in
            // the parquet) with the default pin; older payloads fall back
            // to metadata options.
            const options = fd.options?.length ? fd.options
                : ((this.metadata.dimensions || [])
                    .find(d => d.dim_column_name === fd.column)?.options || [])
                    .map(o => ({ label: o.label.trim(), value: o.label }));
            if (options.length < 2) continue;

            const wrap = document.createElement('label');
            wrap.className = 'dbv2-filter';
            wrap.textContent = fd.label || fd.column;
            const value = this._filterValue(fd, options);

            if (fd.widget === 'level_switch' && fd.levels?.length > 1) {
                this._levelSwitch(wrap, fd.column, fd.levels,
                    this.userLevels[fd.column] || fd.level,
                    id => this._setLevel(fd.column, id, fd.level));
            } else if (fd.widget === 'multi_select') {
                this._multiSelect(wrap, fd, options, value);
            } else if (fd.widget === 'pill_group') {
                const pills = document.createElement('span');
                pills.className = 'dbv2-pills';
                const entries = fd.allow_all
                    ? [{ label: this.ui.all, value: '' }, ...options] : options;
                for (const opt of entries) {
                    const b = document.createElement('button');
                    b.className = 'dbv2-pill' + (String(opt.value) === String(value) ? ' active' : '');
                    b.textContent = opt.label;
                    b.addEventListener('click', () => this._setFilter(fd.column, opt.value));
                    pills.appendChild(b);
                }
                wrap.appendChild(pills);
            } else if (fd.widget === 'single_select' && options.length > 25) {
                // Typeahead over many options (CAEN-style dims)
                const input = document.createElement('input');
                const listId = `dbv2-dl-${fd.column}`;
                input.setAttribute('list', listId);
                input.className = 'dbv2-typeahead';
                const byLabel = new Map(options.map(o => [o.label, o.value]));
                input.value = options.find(o => String(o.value) === String(value))?.label || '';
                const dl = document.createElement('datalist');
                dl.id = listId;
                for (const opt of options) {
                    const o = document.createElement('option');
                    o.value = opt.label;
                    dl.appendChild(o);
                }
                input.addEventListener('change', () => {
                    const v = byLabel.get(input.value);
                    if (v != null) this._setFilter(fd.column, v);
                });
                wrap.appendChild(input);
                wrap.appendChild(dl);
            } else {
                const sel = document.createElement('select');
                sel.dataset.col = fd.column;
                if (fd.allow_all) {
                    const o = document.createElement('option');
                    o.value = '';
                    o.textContent = this.ui.all;
                    sel.appendChild(o);
                }
                for (const opt of options) {
                    const o = document.createElement('option');
                    o.value = opt.value;
                    o.textContent = opt.label;
                    sel.appendChild(o);
                }
                sel.value = value;
                sel.addEventListener('change', () => this._setFilter(fd.column, sel.value));
                wrap.appendChild(sel);
            }
            row.appendChild(wrap);
        }
        // Above the grid: these controls change what every tile is counting,
        // so they have to be visible before the charts, not after them.
        if (row.children.length) grid.parentNode.insertBefore(row, grid);
    }

    syncURL() {
        const url = new URL(window.location);
        const active = Object.fromEntries(
            Object.entries(this.userFilters).filter(([, v]) => v));
        if (Object.keys(active).length) {
            url.searchParams.set('f', JSON.stringify(active));
        } else {
            url.searchParams.delete('f');
        }
        if (Object.keys(this.userLevels).length) {
            url.searchParams.set('g', JSON.stringify(this.userLevels));
        } else {
            url.searchParams.delete('g');
        }
        // Per-tile state (filters/transform/transpose/norm/log), compacted
        const t = {};
        for (const ch of this.composition?.charts || []) {
            const st = {};
            const tf = this.tileFilters[ch.id];
            if (tf && Object.keys(tf).length) st.f = tf;
            if (this.tileTransforms[ch.id]) st.x = this.tileTransforms[ch.id];
            if (this.tileSwaps[ch.id]) st.s = 1;
            if (this.tileNorms[ch.id]) st.n = 1;
            if (this.tileLogs[ch.id]) st.l = 1;
            if (Object.keys(st).length) t[ch.id] = st;
        }
        if (Object.keys(t).length) url.searchParams.set('t', JSON.stringify(t));
        else url.searchParams.delete('t');
        window.history.replaceState({}, '', url);
    }
}

document.addEventListener('DOMContentLoaded', () => {
    // Mirror theme to body so ECharts theme detection (body.dataset.theme) works
    const t = document.documentElement.dataset.theme || localStorage.getItem('lens_theme') || 'dark';
    document.body.dataset.theme = t;
    new DashboardV2().init();
});
