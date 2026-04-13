/**
 * Dimensions Explorer — sidebar layout JS
 * Left: dimension list; Right: filter bar + dataset list
 */

const TOP_N = 15;
const TOP_UM = 10;

// ── State ──────────────────────────────────────────────────────────────────

let activeDim = null;
let lang = localStorage.getItem('lens_lang') || 'ro';
let allDims = [];
let showAll = false;
let showAllUm = false;

let filters = {
    sort: 'updated',
    archetype: '',
    granularity: '',
    has_geo: false,
    has_gender: false,
    has_age: false,
};

const ARCHETYPES = [
    { value: '', label: 'All archetypes' },
    { value: 'time_series', label: 'Time series' },
    { value: 'geo_time', label: 'Geo + Time' },
    { value: 'demographic', label: 'Demographic' },
    { value: 'time_residence', label: 'Residence' },
];

const GRANULARITIES = [
    { value: '', label: 'All periods' },
    { value: 'annual', label: 'Annual' },
    { value: 'monthly', label: 'Monthly' },
    { value: 'quarterly', label: 'Quarterly' },
];

const SORTS = [
    { value: 'updated', label: 'Recently updated' },
    { value: 'name', label: 'Name A–Z' },
    { value: 'rows', label: 'Most records' },
    { value: 'dims', label: 'Most dimensions' },
    { value: 'options', label: 'Most options' },
];

function isUnitDim(label) {
    const lc = label.toLowerCase().trim();
    return lc.startsWith('um:') || lc === 'unitati de masura' || lc === 'unitate de masura';
}

// ── URL sync ───────────────────────────────────────────────────────────────

function restoreFromUrl() {
    const p = new URLSearchParams(location.search);
    activeDim = p.get('dim') || null;
    if (p.get('sort') && SORTS.some(s => s.value === p.get('sort'))) filters.sort = p.get('sort');
    if (p.get('arch')) filters.archetype = p.get('arch');
    if (p.get('gran')) filters.granularity = p.get('gran');
    if (p.get('has_geo') === 'true') filters.has_geo = true;
    if (p.get('has_gender') === 'true') filters.has_gender = true;
    if (p.get('has_age') === 'true') filters.has_age = true;
}

function syncUrl() {
    const url = new URL(location.href);
    if (activeDim) url.searchParams.set('dim', activeDim);
    else url.searchParams.delete('dim');
    if (filters.sort !== 'updated') url.searchParams.set('sort', filters.sort);
    else url.searchParams.delete('sort');
    if (filters.archetype) url.searchParams.set('arch', filters.archetype);
    else url.searchParams.delete('arch');
    if (filters.granularity) url.searchParams.set('gran', filters.granularity);
    else url.searchParams.delete('gran');
    ['has_geo', 'has_gender', 'has_age'].forEach(k => {
        if (filters[k]) url.searchParams.set(k, 'true');
        else url.searchParams.delete(k);
    });
    history.replaceState(null, '', url);
}

// ── Theme & Lang ───────────────────────────────────────────────────────────

function applyTheme(theme) {
    theme = theme || localStorage.getItem('lens_theme') || 'dark';
    document.body.dataset.theme = theme;
    document.getElementById('theme-icon-sun').classList.toggle('hidden', theme !== 'dark');
    document.getElementById('theme-icon-moon').classList.toggle('hidden', theme === 'dark');
}

function bindTheme() {
    document.getElementById('theme-toggle').addEventListener('click', () => {
        const cur = document.body.dataset.theme || 'dark';
        const next = cur === 'dark' ? 'light' : 'dark';
        localStorage.setItem('lens_theme', next);
        applyTheme(next);
    });
}

const FLAG_DATA = {
    ro: 'data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAABAAAAAKCAIAAAAHLozhAAAAGXRFWHRTb2Z0d2FyZQBBZG9iZSBJbWFnZVJlYWR5ccllPAAAALBJREFUeNpiYBgFgx0wMjIyEtIAAFBAAf8GCgQYGBiIVMDIyMjGxoaqgImJiRANTExMhGhgYmIiRAMTExMhGpiYmAjRwMTERIgGJiYmQjQwMTERooGJiYkQDUxMTIRoYGJiIkQDExMTIRqYmJgI0cDExESIBiYmJkI0MDExEaKBiYmJEA1MTEyEaGBiYiJEAxMTEyEamJiYCNHAxMREiAYmJiZCNDAAIMAA0e1ANMAAAAASUVORK5CYII=',
    en: 'data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAABAAAAAKCAIAAAAHLozhAAAAGXRFWHRTb2Z0d2FyZQBBZG9iZSBJbWFnZVJlYWR5ccllPAAAAZhJREFUeNpiYBgFgxgwMjIyEtIAACBAAf8GCgQYGBiIVMDIyMjGxoaqgImJiRANTExMhGhgYmIiRAMTExMhGpiYmAjRwMTERIgGJiYmQjQwMTERooGJiYkQDUxMTIRoYGJiIkQDExMTIRqYmJgI0cDExESIBiYmJkI0MDExEaKBiYmJEA1MTEyEaGBiYiJEAxMTEyEamJiYCNHAxMREiAYmJiZCNDAAIMAA0RNANMAAAAAElFTkSuQmCC',
};

function bindLang() {
    const btn = document.getElementById('lang-toggle');
    updateLangBtn();
    btn.addEventListener('click', () => {
        lang = lang === 'ro' ? 'en' : 'ro';
        localStorage.setItem('lens_lang', lang);
        updateLangBtn();
        loadDatasets();
    });
}

function updateLangBtn() {
    const nextLang = lang === 'ro' ? 'en' : 'ro';
    document.getElementById('lang-label').textContent = nextLang.toUpperCase();
    const flagEl = document.getElementById('lang-flag');
    if (flagEl) flagEl.src = FLAG_DATA[nextLang] || '';
}

// ── Filter bar ─────────────────────────────────────────────────────────────

function renderFilterBar() {
    const bar = document.getElementById('dims-filter-bar');
    bar.innerHTML = '';

    bar.appendChild(makeSelect('arch-select', ARCHETYPES, filters.archetype, v => {
        filters.archetype = v; syncUrl(); loadDatasets();
    }));

    bar.appendChild(makeSelect('gran-select', GRANULARITIES, filters.granularity, v => {
        filters.granularity = v; syncUrl(); loadDatasets();
    }));

    const sep = document.createElement('div');
    sep.className = 'facet-sep';
    bar.appendChild(sep);

    const hasLabel = document.createElement('span');
    hasLabel.className = 'facet-label';
    hasLabel.textContent = 'Has:';
    bar.appendChild(hasLabel);

    [
        { key: 'has_geo', label: 'Geo' },
        { key: 'has_gender', label: 'Gender' },
        { key: 'has_age', label: 'Age' },
    ].forEach(({ key, label }) => {
        const chip = document.createElement('button');
        chip.className = 'facet-chip' + (filters[key] ? ' active' : '');
        chip.textContent = label;
        chip.addEventListener('click', () => {
            filters[key] = !filters[key];
            chip.classList.toggle('active', filters[key]);
            syncUrl(); loadDatasets();
        });
        bar.appendChild(chip);
    });

    const sep2 = document.createElement('div');
    sep2.className = 'facet-sep';
    bar.appendChild(sep2);

    bar.appendChild(makeSelect('sort-select', SORTS, filters.sort, v => {
        filters.sort = v; syncUrl(); loadDatasets();
    }));
}

function makeSelect(id, options, currentVal, onChange) {
    const wrap = document.createElement('div');
    wrap.className = 'facet-select-wrap';
    const sel = document.createElement('select');
    sel.id = id;
    sel.className = 'facet-select';
    options.forEach(opt => {
        const o = document.createElement('option');
        o.value = opt.value;
        o.textContent = opt.label;
        if (opt.value === currentVal) o.selected = true;
        sel.appendChild(o);
    });
    sel.addEventListener('change', () => onChange(sel.value));
    wrap.appendChild(sel);
    return wrap;
}

// ── Dimension sidebar ──────────────────────────────────────────────────────

async function loadDimensions() {
    try {
        allDims = await API.getDimensions({ limit: 300 });
        renderDimList();
    } catch (e) {
        document.getElementById('dims-dim-list').innerHTML =
            `<div class="dims-loading" style="padding:8px 14px;">Error: ${escHtml(e.message)}</div>`;
    }
}

function renderDimList() {
    const container = document.getElementById('dims-dim-list');
    container.innerHTML = '';

    const mainDims = allDims.filter(d => !isUnitDim(d.label));
    const unitDims = allDims.filter(d => isUnitDim(d.label));

    const visible = showAll ? mainDims : mainDims.slice(0, TOP_N);
    const remaining = mainDims.length - TOP_N;

    const cloud = document.createElement('div');
    cloud.className = 'dims-pill-cloud';
    visible.forEach(d => cloud.appendChild(makeDimPill(d)));
    container.appendChild(cloud);

    if (!showAll && remaining > 0) {
        const btn = document.createElement('button');
        btn.className = 'dim-show-more';
        btn.textContent = `+ ${remaining} more`;
        btn.addEventListener('click', () => { showAll = true; renderDimList(); });
        container.appendChild(btn);
    }

    if (unitDims.length > 0) {
        const sep = document.createElement('div');
        sep.className = 'dims-sidebar-sep';
        container.appendChild(sep);

        const groupLabel = document.createElement('div');
        groupLabel.className = 'dims-sidebar-group-label';
        groupLabel.textContent = `Units of Measure (${unitDims.length})`;
        container.appendChild(groupLabel);

        const visibleUm = showAllUm ? unitDims : unitDims.slice(0, TOP_UM);
        const remainingUm = unitDims.length - TOP_UM;

        const unitCloud = document.createElement('div');
        unitCloud.className = 'dims-pill-cloud';
        visibleUm.forEach(d => unitCloud.appendChild(makeDimPill(d)));
        container.appendChild(unitCloud);

        if (!showAllUm && remainingUm > 0) {
            const btn = document.createElement('button');
            btn.className = 'dim-show-more';
            btn.textContent = `+ ${remainingUm} more`;
            btn.addEventListener('click', () => { showAllUm = true; renderDimList(); });
            container.appendChild(btn);
        }
    }

    if (activeDim) highlightDimPill(activeDim);
}

function makeDimPill(d) {
    const btn = document.createElement('button');
    btn.className = 'dim-pill' + (activeDim === d.label ? ' active' : '');
    btn.dataset.label = d.label;
    btn.title = d.label;
    btn.innerHTML = `${escHtml(d.label)}<span class="dim-pill-count">${d.dataset_count}</span>`;
    btn.addEventListener('click', () => setActiveDim(activeDim === d.label ? null : d.label));
    return btn;
}

function highlightDimPill(label) {
    document.querySelectorAll('.dim-pill').forEach(el => {
        el.classList.toggle('active', el.dataset.label === label);
    });
}

function setActiveDim(label) {
    activeDim = label;
    highlightDimPill(label);
    syncUrl();
    loadDatasets();
}

// ── Dataset list ───────────────────────────────────────────────────────────

async function loadDatasets() {
    const list = document.getElementById('dims-dataset-list');
    const header = document.getElementById('dims-dataset-header');
    list.innerHTML = '<div class="dims-loading">Loading datasets…</div>';

    const params = { limit: 30, lang, sort: filters.sort };
    if (activeDim) params.dim = activeDim;
    if (filters.archetype) params.archetype = filters.archetype;
    if (filters.granularity) params.granularity = filters.granularity;
    if (filters.has_geo) params.has_geo = true;
    if (filters.has_gender) params.has_gender = true;
    if (filters.has_age) params.has_age = true;

    try {
        const data = await API.getDatasets(params);
        const total = data.total;
        const label = activeDim
            ? `Datasets with "${activeDim}" (${total})`
            : `Recent Datasets (${total > 30 ? '30 of ' + total : total})`;
        header.textContent = label;
        renderDatasetList(list, data.datasets);
    } catch (e) {
        list.innerHTML = `<div class="dims-loading">Error: ${escHtml(e.message)}</div>`;
    }
}

function renderDatasetList(list, datasets) {
    list.innerHTML = '';
    if (!datasets.length) {
        list.innerHTML = '<div class="dims-loading">No datasets match the current filters.</div>';
        return;
    }
    datasets.forEach(ds => {
        const row = document.createElement('div');
        row.className = 'ds-row';
        row.style.cursor = 'pointer';
        row.addEventListener('click', () => { window.location.href = `/?code=${ds.matrix_code}`; });
        row.innerHTML = `
            <span class="ds-code">${escHtml(ds.matrix_code)}</span>
            <span class="ds-name">${escHtml(ds.matrix_name)}</span>
            <span class="ds-badges">
                ${ds.time_range ? `<span class="ds-badge">${ds.time_range}</span>` : ''}
                ${ds.archetype ? `<span class="ds-badge">${ds.archetype}</span>` : ''}
                ${ds.row_count ? `<span class="ds-badge">${ds.row_count.toLocaleString()} rows</span>` : ''}
            </span>
        `;
        list.appendChild(row);
    });
}

// ── Utils ──────────────────────────────────────────────────────────────────

function escHtml(str) {
    return String(str || '').replace(/[&<>"']/g, c =>
        ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c])
    );
}

// ── Boot ───────────────────────────────────────────────────────────────────

document.addEventListener('DOMContentLoaded', () => {
    applyTheme();
    bindTheme();
    bindLang();
    restoreFromUrl();
    renderFilterBar();
    loadDimensions();
    loadDatasets();
});
