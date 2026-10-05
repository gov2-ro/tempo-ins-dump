/**
 * Utility functions
 */

/** Format a number with Romanian conventions (dot thousands, comma decimal) */
function formatNumber(val, decimals = null) {
    if (val === null || val === undefined) return '—';
    const n = Number(val);
    if (isNaN(n)) return String(val);
    if (decimals === null) {
        decimals = Number.isInteger(n) ? 0 : 2;
    }
    return n.toLocaleString('ro-RO', {
        minimumFractionDigits: decimals,
        maximumFractionDigits: decimals,
    });
}

/** Get the filter value for a dimension option.
 *  v3 SDMX parquets use string values; fall back to nom_item_id for v2. */
function optVal(opt) {
    return opt.sdmx_value != null ? opt.sdmx_value : opt.nom_item_id;
}

/** Resolve nom_item_id to label using column_labels dict */
function resolveLabel(columnLabels, colName, id) {
    if (id === null || id === undefined) return '—';
    const labels = columnLabels[colName];
    if (!labels) return String(id);
    return labels[String(id)] || labels[String(Math.round(id))] || String(id);
}

/** Group data rows by a dimension column index */
function groupBy(rows, colIndex) {
    const groups = {};
    for (const row of rows) {
        const key = row[colIndex];
        if (!groups[key]) groups[key] = [];
        groups[key].push(row);
    }
    return groups;
}

/** Get unique sorted values from a column */
function uniqueValues(rows, colIndex) {
    const set = new Set(rows.map(r => r[colIndex]).filter(v => v !== null));
    return [...set].sort((a, b) => {
        const na = Number(a), nb = Number(b);
        if (!isNaN(na) && !isNaN(nb)) return na - nb;
        return String(a).localeCompare(String(b));
    });
}

/** Create an element with attributes and children */
function el(tag, attrs = {}, ...children) {
    const e = document.createElement(tag);
    for (const [k, v] of Object.entries(attrs)) {
        if (k === 'className') e.className = v;
        else if (k === 'style' && typeof v === 'object') Object.assign(e.style, v);
        else if (k.startsWith('on')) e.addEventListener(k.slice(2).toLowerCase(), v);
        else e.setAttribute(k, v);
    }
    for (const child of children) {
        if (typeof child === 'string') e.appendChild(document.createTextNode(child));
        else if (child) e.appendChild(child);
    }
    return e;
}

/**
 * Time-series value transform, shared by explore-app and dashboard-v2.
 * mode: 'index' (first period = 100) | 'yoy' (% change vs previous period).
 * Returns a new data object; rows the transform can't compute are dropped.
 */
function applyTimeTransform(data, timeDim, seriesDim, mode) {
    if (!mode || !data || !data.rows.length) return data;
    const cols = data.columns;
    const timeIdx = cols.indexOf(timeDim);
    if (timeIdx === -1) return data;
    const seriesIdx = seriesDim ? cols.indexOf(seriesDim) : -1;
    const valIdx = cols.length - 1;

    const groups = new Map();
    for (const row of data.rows) {
        const key = seriesIdx >= 0 ? String(row[seriesIdx]) : '__all__';
        if (!groups.has(key)) groups.set(key, []);
        groups.get(key).push(row);
    }

    const newRows = [];
    for (const rows of groups.values()) {
        const sorted = [...rows].sort((a, b) => String(a[timeIdx]).localeCompare(String(b[timeIdx])));
        if (mode === 'index') {
            const base = sorted[0]?.[valIdx];
            if (base == null || base === 0) continue;
            for (const row of sorted) {
                const nr = [...row];
                nr[valIdx] = row[valIdx] != null ? (row[valIdx] / base) * 100 : null;
                newRows.push(nr);
            }
        } else if (mode === 'yoy') {
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
 * Seasonal overlay transform: sub-annual series → one line per year over a
 * month/quarter x-axis. Only rows with "YYYY-<sub>" periods participate.
 * Only a time-only slice is folded: any other dim would be summed/averaged
 * across its options here (FIX-02 — a total the server's aggregation policy
 * never approved), so the overlay returns null instead. `useAvg` averages
 * repeated sub-periods of a non-additive measure.
 * Returns null when the data has no sub-annual structure.
 */
function seasonalOverlay(data, timeDim, useAvg) {
    if (!data || !data.rows.length) return null;
    const cols = data.columns;
    const ti = cols.indexOf(timeDim);
    const vi = cols.length - 1;
    if (ti === -1) return null;
    if (cols.length > 2) return null;   // time + value only; see above

    const agg = new Map();  // "year sub" → {sum, n}
    for (const r of data.rows) {
        const m = /^(\d{4})-(.+)$/.exec(String(r[ti]).trim());
        if (!m || r[vi] == null) continue;
        const key = m[1] + ' ' + m[2];
        const cur = agg.get(key) || { sum: 0, n: 0 };
        cur.sum += r[vi];
        cur.n++;
        agg.set(key, cur);
    }
    if (!agg.size) return null;
    const rows = [];
    for (const [key, entry] of agg) {
        const parts = key.split(' ');
        rows.push([parts[1], parts[0], useAvg ? entry.sum / entry.n : entry.sum]);
    }
    return { columns: ['__SUB__', '__YEAR__', 'OBS_VALUE'], column_labels: {}, rows };
}

// ---------------------------------------------------------------- FIX-07 --

/** Localized accessible names/tooltips for the shared topbar (v1 + v2). */
const CHROME_A11Y = {
    ro: { 'sidebar-toggle': 'Navigare rapidă', 'search-trigger': 'Caută seturi de date',
          'about-btn': 'Despre', 'theme-toggle': 'Schimbă tema luminoasă/întunecată',
          'lang-toggle': 'Schimbă limba', 'sidebar-close': 'Închide', 'back-btn': 'Înapoi la explorare' },
    en: { 'sidebar-toggle': 'Quick navigate', 'search-trigger': 'Search datasets',
          'about-btn': 'About', 'theme-toggle': 'Toggle light/dark theme',
          'lang-toggle': 'Switch language', 'sidebar-close': 'Close', 'back-btn': 'Back to explore' },
};
function localizeChrome(lang) {
    const names = CHROME_A11Y[lang] || CHROME_A11Y.ro;
    for (const [id, name] of Object.entries(names)) {
        const node = document.getElementById(id);
        if (!node) continue;
        node.setAttribute('aria-label', name);
        if (id !== 'search-trigger' && id !== 'back-btn') node.title = name;
    }
    const places = document.querySelector('.topbar-right a[href="/places"]');
    if (places) {
        const t = lang === 'en' ? 'Places' : 'Locuri';
        places.setAttribute('aria-label', t);
        places.title = t;
        const lab = places.querySelector('.tb-label');
        if (lab) lab.textContent = t;
    }
    const ask = document.querySelector('.topbar-right a[href="/ask.html"]');
    if (ask) ask.setAttribute('aria-label', lang === 'en' ? 'Ask AI' : 'Întreabă AI');
}

/** Compact axis number: 1234567 -> "1,2 mil." / "1.2M". Ticks only; tooltips keep full values. */
function formatCompact(val, lang = 'ro') {
    const n = Number(val);
    if (val === null || val === undefined || !isFinite(n)) return '';
    const a = Math.abs(n);
    const units = lang === 'en'
        ? [[1e12, 'T'], [1e9, 'B'], [1e6, 'M'], [1e3, 'K']]
        : [[1e12, ' tril.'], [1e9, ' mld.'], [1e6, ' mil.'], [1e3, ' K']];
    for (const [div, suf] of units) {
        if (a >= div) {
            const v = n / div;
            const d = Math.abs(v) >= 100 ? 0 : (Math.abs(v) >= 10 ? 1 : 2);
            let s = v.toFixed(d);
            if (s.includes('.')) s = s.replace(/0+$/, '').replace(/\.$/, '');
            if (lang !== 'en') s = s.replace('.', ',');
            return s + suf;
        }
    }
    if (Number.isInteger(n)) return String(n);
    return String(Number(n.toPrecision(3))).replace('.', lang === 'en' ? '.' : ',');
}

/** User-facing chart type names (internal identifiers stay in diagnostics). */
const CHART_TYPE_LABELS = {
    ro: { line: 'Linie', bar: 'Bare', bar_vertical: 'Bare', horizontal_bar: 'Bare orizontale',
          grouped_bar: 'Bare grupate', stacked_bar: 'Bare stivuite', area_stacked: 'Arii stivuite',
          stacked_area: 'Arii stivuite', area: 'Arie', pie: 'Plăcintă', donut: 'Inel', treemap: 'Treemap',
          heatmap: 'Hartă termică', choropleth: 'Hartă', population_pyramid: 'Piramida vârstelor',
          scatter: 'Dispersie', radar: 'Radar', bubble: 'Bule', small_multiples: 'Grafice multiple',
          table: 'Tabel', sunburst: 'Sunburst', slope: 'Pantă', bump: 'Clasament' },
    en: { line: 'Line', bar: 'Bars', bar_vertical: 'Bars', horizontal_bar: 'Horizontal bars',
          grouped_bar: 'Grouped bars', stacked_bar: 'Stacked bars', area_stacked: 'Stacked area',
          stacked_area: 'Stacked area', area: 'Area', pie: 'Pie', donut: 'Donut', treemap: 'Treemap',
          heatmap: 'Heatmap', choropleth: 'Map', population_pyramid: 'Population pyramid',
          scatter: 'Scatter', radar: 'Radar', bubble: 'Bubbles', small_multiples: 'Small multiples',
          table: 'Table', sunburst: 'Sunburst', slope: 'Slope', bump: 'Rank' },
};
function chartTypeLabel(type, lang = 'ro') {
    const t = (CHART_TYPE_LABELS[lang] || CHART_TYPE_LABELS.ro)[type];
    if (t) return t;
    const s = String(type || '').replace(/_/g, ' ');
    return s.charAt(0).toUpperCase() + s.slice(1);
}

/** Active UI language for chart helpers (same precedence as the page controllers). */
function currentLang() {
    try {
        const l = new URLSearchParams(location.search).get('lang') || localStorage.getItem('lens_lang');
        return l === 'en' ? 'en' : 'ro';
    } catch (e) { return 'ro'; }
}
/** Value-axis tick label: compact, locale-aware. Tooltips keep formatNumber's full value. */
function axisNumber(v) { return formatCompact(v, currentLang()); }


// ------------------------------------------------------------- FIX-02 --
// Aggregation disclosure shared by v1, v2 and Ask. The server's shared policy
// (app/services/aggregation_policy.py) decides whether a total exists; the
// client only *shows* its verdict and never re-derives a suppressed total.

const AGG_I18N = {
    ro: {
        prefix: { total: 'Total indisponibil', change: 'Variație indisponibilă',
                  tile: 'Date indisponibile' },
        reasons: {
            overlapping_levels: dt => `niveluri ${dt === 'age' ? 'de vârstă ' : dt === 'geo' ? 'geografice ' : ''}suprapuse`,
            unverified_structure: () => 'structură neverificată',
            contains_aggregate: () => 'totalul este amestecat cu componentele',
            label_hierarchy: () => 'ierarhie codificată în etichete',
            non_additive_measure: () => 'rată/indice fără ponderi',
            missing_weights: () => 'rată/indice fără ponderi',
            mixed_units: () => 'unități de măsură diferite',
            slice_value_missing: () => 'valoare de filtrare inexistentă',
            declared_partition_invalid: () => 'partiție nevalidă',
            arbitrary_pin: () => 'doar o selecție parțială, nu totalul',
            comparator_missing: () => 'fără perioadă de comparație',
            comparator_zero: () => 'baza de comparație este zero',
            ambiguous_slice: () => 'selecție ambiguă',
            no_data: () => 'fără date',
        },
        fallback: 'verificare statistică eșuată',
        badges: { approximation: 'aproximare', weighted: 'medie ponderată', slice: 'selecție parțială',
                  approximationTip: 'Medie neponderată — nu este o rată oficială',
                  methods: { aggregate_row: 'rând total din sursă', sum_partition: 'sumă pe o partiție verificată',
                             single_row: 'selecție explicită', weighted_mean: 'medie ponderată',
                             unweighted_mean: 'medie neponderată', none: '' } },
    },
    en: {
        prefix: { total: 'Total unavailable', change: 'Change unavailable',
                  tile: 'Data unavailable' },
        reasons: {
            overlapping_levels: dt => `overlapping ${dt === 'age' ? 'age ' : dt === 'geo' ? 'geographic ' : ''}levels`,
            unverified_structure: () => 'unverified structure',
            contains_aggregate: () => 'total mixed with its components',
            label_hierarchy: () => 'hierarchy encoded in labels',
            non_additive_measure: () => 'rate/index without weights',
            missing_weights: () => 'rate/index without weights',
            mixed_units: () => 'mixed units',
            slice_value_missing: () => 'filter value not in the data',
            declared_partition_invalid: () => 'invalid partition',
            arbitrary_pin: () => 'only a partial selection, not the total',
            comparator_missing: () => 'no comparison period',
            comparator_zero: () => 'comparison base is zero',
            ambiguous_slice: () => 'ambiguous selection',
            no_data: () => 'no data',
        },
        fallback: 'statistical check failed',
        badges: { approximation: 'approximation', weighted: 'weighted mean', slice: 'partial selection',
                  approximationTip: 'Unweighted mean — not an official rate',
                  methods: { aggregate_row: 'source total row', sum_partition: 'sum over a verified partition',
                             single_row: 'explicit selection', weighted_mean: 'weighted mean',
                             unweighted_mean: 'unweighted mean', none: '' } },
    },
};

function _escHtml(s) {
    return String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
}

/** Short translated reason for an unavailable aggregate, e.g.
 *  "Total indisponibil: niveluri de vârstă suprapuse".
 *  `src` is a decision/suppressed entry ({reason, ...}); `kind` picks the
 *  prefix (total | change | tile); `dimType` ('age' | 'geo' | ...) refines
 *  overlapping_levels. */
function aggReasonText(src, lang = 'ro', { kind = 'total', dimType = null } = {}) {
    const t = AGG_I18N[lang] || AGG_I18N.ro;
    const fn = t.reasons[src && src.reason];
    const why = fn ? fn(dimType) : t.fallback;
    return `${t.prefix[kind] || t.prefix.total}: ${why}`;
}

/** Badge descriptor from a decision / provenance object: approximation,
 *  weighted mean or partial selection; null for a plain verified total. */
function aggBadge(src, lang = 'ro') {
    if (!src) return null;
    const b = (AGG_I18N[lang] || AGG_I18N.ro).badges;
    const tip = aggMethodTitle(src, lang);
    if (src.approximation || src.outcome === 'approximation') {
        return { cls: 'approx', label: b.approximation, title: b.approximationTip };
    }
    if (src.method === 'weighted_mean') return { cls: 'weighted', label: b.weighted, title: tip };
    if (src.outcome === 'valid_slice') return { cls: 'slice', label: b.slice, title: tip };
    return null;
}

function aggBadgeHTML(src, lang = 'ro') {
    const b = aggBadge(src, lang);
    return b ? `<span class="agg-badge agg-badge-${b.cls}" title="${_escHtml(b.title)}">${_escHtml(b.label)}</span>` : '';
}

/** Method + verification as a tooltip, for plain totals too. */
function aggMethodTitle(src, lang = 'ro') {
    if (!src) return '';
    const b = (AGG_I18N[lang] || AGG_I18N.ro).badges;
    return [b.methods[src.method], src.verification].filter(Boolean).join(' · ');
}
