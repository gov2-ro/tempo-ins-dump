/**
 * Compare view — two datasets side by side (/compare.html?a=X&b=Y).
 *
 * Overlays each dataset's default temporal slice on a shared time axis
 * (dual y-axis when unit types differ) and, when both are county-level,
 * scatters county values of the latest period both datasets share.
 * Entry point: the "Compară" link on dashboard-v2 related-dataset cards.
 */

const CMP_UI = {
    ro: {
        loading: 'Se încarcă…',
        missing: 'Lipsesc parametrii ?a= și ?b=',
        notFound: c => `Setul de date „${c}" nu a fost găsit.`,
        title: 'Comparație',
        evolution: 'Evoluție în timp',
        noTemporal: 'Cel puțin unul dintre seturi nu are serie temporală — suprapunerea în timp nu este posibilă.',
        counties: 'Corespondență pe județe',
        scatterSub: (n, r, p) => `${n} județe · ${r == null ? 'corelație nedefinită' : `corelație r = ${r}`}${p ? ` · ${p}` : ''}`,
        excluded: (a, b) => `Excluse: ${[a, b].filter(Boolean).join(' · ')}`,
        onlyIn: (code, names) => `doar în ${code}: ${names.join(', ')}`,
        noCommon: (pa, pb) => `Nicio perioadă comună pe județe (${pa} / ${pb}); corelația nu se calculează între ani diferiți.`,
        duplicateArea: name => `Județul ${name} apare de mai multe ori în aceeași perioadă; corelația nu se calculează.`,
        assoc: 'asociere, nu relație cauzală',
        slice: 'felie',
        openTitle: 'Deschide dashboardul setului de date',
    },
    en: {
        loading: 'Loading…',
        missing: 'Missing ?a= and ?b= parameters',
        notFound: c => `Dataset "${c}" was not found.`,
        title: 'Comparison',
        evolution: 'Evolution over time',
        noTemporal: 'At least one dataset has no time series — the overlay is not possible.',
        counties: 'County correspondence',
        scatterSub: (n, r, p) => `${n} counties · ${r == null ? 'correlation undefined' : `correlation r = ${r}`}${p ? ` · ${p}` : ''}`,
        excluded: (a, b) => `Excluded: ${[a, b].filter(Boolean).join(' · ')}`,
        onlyIn: (code, names) => `only in ${code}: ${names.join(', ')}`,
        noCommon: (pa, pb) => `No common county period (${pa} / ${pb}); correlation is not computed across different years.`,
        duplicateArea: name => `County ${name} appears more than once in the same period; correlation is not computed.`,
        assoc: 'association, not causation',
        slice: 'slice',
        openTitle: 'Open the dataset dashboard',
    },
};

function normPeriod(p) {
    return String(p).replace(/anul\s*/i, '').trim();
}

/** Pearson r, or null when undefined: fewer than two pairs, a non-finite
 *  value or a constant axis (PA-01c, audit A06 — never a misleading 0). */
function pearson(pts) {
    const n = pts.length;
    if (n < 2 || pts.some(p => !Number.isFinite(p[0]) || !Number.isFinite(p[1]))) return null;
    const mx = pts.reduce((s, p) => s + p[0], 0) / n;
    const my = pts.reduce((s, p) => s + p[1], 0) / n;
    let num = 0, dx = 0, dy = 0;
    for (const [x, y] of pts) {
        num += (x - mx) * (y - my);
        dx += (x - mx) ** 2;
        dy += (y - my) ** 2;
    }
    return dx && dy ? num / Math.sqrt(dx * dy) : null;
}

class ComparePage {
    constructor() {
        const params = new URLSearchParams(window.location.search);
        this.a = params.get('a');
        this.b = params.get('b');
        this.lang = params.get('lang') || localStorage.getItem('lens_lang') || 'ro';
        if (!CMP_UI[this.lang]) this.lang = 'ro';
        this.ui = CMP_UI[this.lang];
        this.charts = [];
    }

    showError(msg) {
        document.getElementById('cmp-loader').classList.add('hidden');
        const el = document.getElementById('cmp-error');
        el.textContent = msg;
        el.classList.remove('hidden');
    }

    async init() {
        document.getElementById('cmp-loader').textContent = this.ui.loading;
        if (!this.a || !this.b) {
            this.showError(this.ui.missing);
            return;
        }
        try {
            [this.metaA, this.metaB] = await Promise.all([
                API.getDataset(this.a, { lang: this.lang }),
                API.getDataset(this.b, { lang: this.lang }),
            ]);
        } catch (e) {
            this.showError(`${this.ui.notFound(`${this.a} / ${this.b}`)} (${e.message})`);
            return;
        }
        this.renderHeader();
        const [sa, sb] = await Promise.all([
            this.temporalSeries(this.metaA),
            this.temporalSeries(this.metaB),
        ]);
        document.getElementById('cmp-loader').classList.add('hidden');
        if (sa && sb) {
            this.renderLines(sa, sb);
        } else {
            const el = document.getElementById('cmp-notice');
            el.textContent = this.ui.noTemporal;
            el.classList.remove('hidden');
        }
        await this.renderScatter();
        window.addEventListener('resize', () => {
            this.charts.forEach(c => c && c.resize && c.resize());
        });
    }

    renderHeader() {
        const langQ = this.lang !== 'ro' ? `&lang=${this.lang}` : '';
        const card = m => `
            <a class="cmp-ds" href="/dataset-v2.html?code=${m.matrix_code}${langQ}"
               title="${this.ui.openTitle}">
                <span class="dash-code">${m.matrix_code}</span>
                ${m.matrix_name}
            </a>`;
        document.getElementById('cmp-header').innerHTML = `
            <div class="dash-breadcrumbs">${this.ui.title}</div>
            <div class="cmp-title-row">
                ${card(this.metaA)}
                <span class="cmp-vs">vs</span>
                ${card(this.metaB)}
            </div>`;
        document.title = `${this.a} vs ${this.b} — INS+`;
    }

    /** Default temporal slice of one dataset, reduced to a single series:
     *  the composer tile's query, then the Total series when one exists,
     *  otherwise the most complete series (disclosed as a slice label). */
    async temporalSeries(meta) {
        const comp = meta.chart_config?.composition;
        const timeCol = meta.chart_config?.time_dim;
        if (!comp || !timeCol) return null;
        const tile = (comp.charts || []).find(c =>
            c.axis === 'temporal' && c.data.group_by.includes(timeCol));
        if (!tile) return null;
        let data;
        try {
            data = await API.getDatasetData(meta.matrix_code, tile.data.filters,
                                            50000, { groupBy: tile.data.group_by });
        } catch (e) {
            console.warn(`Temporal slice for ${meta.matrix_code} failed:`, e);
            return null;
        }
        if (!data?.rows?.length) return null;
        const cols = data.columns;
        const ti = cols.indexOf(timeCol);
        const vi = cols.length - 1;
        if (ti === -1) return null;

        const seriesCol = tile.data.group_by.find(c => c !== timeCol && cols.includes(c));
        let rows = data.rows;
        let sliceLabel = null;
        if (seriesCol) {
            const si = cols.indexOf(seriesCol);
            const bySeries = new Map();
            for (const r of rows) {
                const k = String(r[si]).trim();
                if (!bySeries.has(k)) bySeries.set(k, []);
                bySeries.get(k).push(r);
            }
            const totalRe = /^(total|toate|ambele)/i;
            let chosen = [...bySeries.keys()].find(k => totalRe.test(k));
            if (!chosen) {
                chosen = [...bySeries.entries()]
                    .sort((x, y) => y[1].length - x[1].length)[0][0];
                sliceLabel = chosen;
            }
            rows = bySeries.get(chosen);
        }
        const points = new Map();
        for (const r of rows) {
            if (r[vi] != null) points.set(normPeriod(r[ti]), r[vi]);
        }
        return points.size
            ? { points, sliceLabel,
                unitType: meta.chart_config?.primary_unit_type || '' }
            : null;
    }

    renderLines(sa, sb) {
        const periods = [...new Set([...sa.points.keys(), ...sb.points.keys()])].sort();
        const dual = sa.unitType !== sb.unitType;
        const name = (code, s) =>
            `${code}${s.sliceLabel ? ` · ${s.sliceLabel}` : ''}`;
        const nameA = name(this.a, sa);
        const nameB = name(this.b, sb);
        const section = document.getElementById('cmp-line');
        document.getElementById('cmp-line-title').textContent = this.ui.evolution;
        section.classList.remove('hidden');
        const chart = echarts.init(document.getElementById('cmp-line-chart'));
        chart.setOption({
            tooltip: { trigger: 'axis' },
            legend: { data: [nameA, nameB], bottom: 0, type: 'scroll' },
            grid: { left: 16, right: dual ? 16 : 24, top: 36, bottom: 52, containLabel: true },
            xAxis: {
                type: 'category', data: periods,
                axisLabel: { rotate: periods.length > 18 ? 45 : 0 },
            },
            yAxis: dual
                ? [{ type: 'value', name: sa.unitType, scale: true },
                   { type: 'value', name: sb.unitType, scale: true,
                     splitLine: { show: false } }]
                : [{ type: 'value', name: sa.unitType, scale: true }],
            series: [
                { name: nameA, type: 'line', yAxisIndex: 0, connectNulls: false,
                  showSymbol: periods.length < 40,
                  data: periods.map(p => sa.points.get(p) ?? null) },
                { name: nameB, type: 'line', yAxisIndex: dual ? 1 : 0, connectNulls: false,
                  showSymbol: periods.length < 40,
                  data: periods.map(p => sb.points.get(p) ?? null) },
            ],
        });
        this.charts.push(chart);
    }

    /** County values of one dataset for every available period:
     *  {byPeriod: Map(period -> Map(county -> value)), duplicate: Map(period -> county)}. Uses the
     *  geo tile's slice with time released, so the two datasets can be
     *  aligned on a period they share instead of each one's own latest. */
    async geoSlice(meta) {
        const comp = meta.chart_config?.composition;
        const geoCol = meta.chart_config?.geo_dim;
        const timeCol = meta.chart_config?.time_dim;
        if (!comp || !geoCol) return null;
        const tiles = (comp.charts || []).filter(c => c.roles?.x_axis === geoCol);
        const tile = tiles.find(c => !timeCol || !c.data.group_by.includes(timeCol))
            || tiles[0];
        if (!tile) return null;
        const filters = { ...tile.data.filters };
        const groupBy = [...tile.data.group_by];
        if (timeCol) {
            delete filters[timeCol];
            if (!groupBy.includes(timeCol)) groupBy.push(timeCol);
        }
        let data;
        try {
            data = await API.getDatasetData(meta.matrix_code, filters, 50000, { groupBy });
        } catch (e) {
            console.warn(`Geo slice for ${meta.matrix_code} failed:`, e);
            return null;
        }
        if (!data?.rows?.length || data.truncated) return null;   // never correlate a capped result
        const cols = data.columns;
        const gi = cols.indexOf(geoCol);
        const ti = timeCol ? cols.indexOf(timeCol) : -1;
        const vi = cols.length - 1;
        if (gi === -1) return null;

        const dim = (meta.dimensions || []).find(d => d.dim_column_name === geoCol);
        const toClean = {};
        for (const o of dim?.options || []) {
            const c = o.parsed?.geo_name_clean;
            if (!c) continue;
            if (o.label) toClean[o.label.trim()] = c;
            if (o.sdmx_value) toClean[String(o.sdmx_value).trim()] = c;
        }
        // Aggregate areas would sit far off the county cloud — drop them
        const aggRe = /^(total|macroregiunea|regiunea)/i;
        const byPeriod = new Map();
        const duplicate = new Map();   // period -> a county seen twice
        for (const r of data.rows) {
            const raw = String(r[gi]).trim();
            const clean = toClean[raw] || raw;
            if (aggRe.test(clean)) continue;
            const period = ti === -1 ? '' : normPeriod(r[ti]);
            if (!byPeriod.has(period)) byPeriod.set(period, new Map());
            const m = byPeriod.get(period);
            if (m.has(clean) && !duplicate.has(period)) duplicate.set(period, clean);
            m.set(clean, r[vi]);
        }
        return byPeriod.size ? { byPeriod, duplicate } : null;
    }

    /** Pairs for the latest period both datasets cover (no implicit lag).
     *  Pure, so it can be checked on fixtures. */
    static alignCounties(ga, gb) {
        const common = [...ga.byPeriod.keys()].filter(p => gb.byPeriod.has(p)).sort();
        const latest = m => [...m.keys()].sort().pop();
        if (!common.length) {
            return { error: 'no_common_period', periods: [latest(ga.byPeriod), latest(gb.byPeriod)] };
        }
        const period = common[common.length - 1];
        const dup = ga.duplicate?.get(period) || gb.duplicate?.get(period);
        if (dup) return { error: 'duplicate_area', name: dup };
        const a = ga.byPeriod.get(period), b = gb.byPeriod.get(period);
        const ok = v => v != null && Number.isFinite(+v);
        const pts = [];
        for (const [name, v] of a) if (ok(v) && ok(b.get(name))) pts.push([+v, +b.get(name), name]);
        const onlyA = [...a].filter(([n, v]) => ok(v) && !ok(b.get(n))).map(([n]) => n).sort();
        const onlyB = [...b].filter(([n, w]) => ok(w) && !ok(a.get(n))).map(([n]) => n).sort();
        return { period, pts, onlyA, onlyB,
                 r: pearson(pts) };
    }

    async renderScatter() {
        const county = m => (m.chart_config?.dataset_signature?.geo_levels || [])
            .includes('county');
        if (!county(this.metaA) || !county(this.metaB)) return;
        const [ga, gb] = await Promise.all([
            this.geoSlice(this.metaA), this.geoSlice(this.metaB)]);
        if (!ga || !gb) return;
        const al = ComparePage.alignCounties(ga, gb);
        document.getElementById('cmp-scatter-title').textContent = this.ui.counties;
        const section = document.getElementById('cmp-scatter');
        const sub = document.getElementById('cmp-scatter-sub');
        if (al.error) {
            sub.textContent = al.error === 'no_common_period'
                ? this.ui.noCommon(...al.periods) : this.ui.duplicateArea(al.name);
            document.getElementById('cmp-scatter-chart').classList.add('hidden');
            section.classList.remove('hidden');
            return;
        }
        const pts = al.pts;
        if (pts.length < 2) return;
        sub.textContent = this.ui.scatterSub(pts.length, al.r == null ? null : al.r.toFixed(2),
                                             `${al.period} · ${this.ui.assoc}`);
        const excluded = [al.onlyA.length ? this.ui.onlyIn(this.a, al.onlyA) : '',
                          al.onlyB.length ? this.ui.onlyIn(this.b, al.onlyB) : ''];
        if (excluded.some(Boolean)) {
            const note = document.createElement('div');
            note.className = 'dbv2-notice cmp-excluded';
            note.textContent = this.ui.excluded(...excluded);
            section.appendChild(note);
        }
        section.classList.remove('hidden');
        const chart = echarts.init(document.getElementById('cmp-scatter-chart'));
        chart.setOption({
            tooltip: {
                formatter: p => `<b>${p.data[2]}</b><br>` +
                    `${this.a}: ${formatNumber(p.data[0])}<br>` +
                    `${this.b}: ${formatNumber(p.data[1])}`,
            },
            grid: { left: 16, right: 24, top: 36, bottom: 40, containLabel: true },
            xAxis: { type: 'value', name: this.a, scale: true,
                     nameLocation: 'middle', nameGap: 28 },
            yAxis: { type: 'value', name: this.b, scale: true },
            series: [{ type: 'scatter', symbolSize: 11, data: pts }],
        });
        this.charts.push(chart);
    }
}

document.addEventListener('DOMContentLoaded', () => {
    const t = document.documentElement.dataset.theme || localStorage.getItem('lens_theme') || 'dark';
    document.body.dataset.theme = t;
    new ComparePage().init();
    // Chrome theme toggle — charts are stateless, a reload re-themes them
    window.addEventListener('themechange', () => window.location.reload());
});
