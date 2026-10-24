/**
 * ask.js — Chat UI for POST /api/ask (NL→Data agent)
 *
 * Manages multi-turn conversation history, renders assistant responses
 * (text + outcome + citations + data table with links + chart + warnings + tool trace).
 *
 * Follow-ups (AT-02): the server returns the canonical selections behind its answers
 * (`context`, at most four). They are kept in memory for this tab, sent back with the next
 * question and cleared by "New conversation". They are hints the server re-validates and re-runs;
 * they carry no values and certify nothing.
 */

// ---------------------------------------------------------------------------
// State
// ---------------------------------------------------------------------------

const history = [];   // [{role:'user'|'assistant', content: str}]
let askContext = [];  // follow-up selections from the server; in memory only, cleared on reset
let isLoading = false;
let MAX_HISTORY_TURNS = 20;  // overwritten from /api/ask/config
let ASK_UNAVAILABLE = false; // /api/ask/config: neither hosted nor own-key Ask
let MAX_SECONDS = 90;        // /api/ask/config limits.max_seconds
let DEBUG_AVAILABLE = false; // server runs with TEMPO_ASK_DEBUG

/** Debug mode: offered only when the server allows it; on via ?debug=1 or the settings box. */
function debugOn() {
    if (!DEBUG_AVAILABLE) return false;
    if (new URLSearchParams(location.search).get('debug') === '1') return true;
    try { return localStorage.getItem('ask_debug') === '1'; } catch { return false; }
}

/** The site's language: ?lang= first, then the switcher's lens_lang, default ro (utils.currentLang's
 *  rule, which ui-preferences.js and site-chrome.js share). It is also the language signal sent
 *  with every question; the server uses it only when the question shows none of its own. */
function siteLang() {
    let l = null;
    try { l = new URLSearchParams(location.search).get('lang'); } catch { /* no URL */ }
    if (!l) { try { l = localStorage.getItem('lens_lang'); } catch { /* storage blocked */ } }
    return l === 'en' ? 'en' : 'ro';
}

/** Language of the answer being rendered (the response's `lang`: what the server wrote its warnings,
 *  scope and table prose in). Its captions follow it; the page's own chrome and errors follow the site. */
let turnLang = null;

function isRo() { return (turnLang || siteLang()) !== 'en'; }
const tr = (ro, en) => (isRo() ? ro : en);

/** Terminal outcome of a turn (AT-02). HTTP 200 and a text answer are not enough to call it a
 *  substantive answer: partial, refused, clarification and failed are shown as such. */
const OUTCOME_LABEL = {
    clarification: ['Precizare necesară', 'Clarification needed'],
    partial: ['Răspuns parțial', 'Partial answer'],
    refused: ['Nu se poate calcula în siguranță', 'Cannot be computed safely'],
    failed: ['Răspunsul nu a putut fi generat', 'No answer could be produced'],
};
const REASON_TEXT = {
    ranking_unverified: ['clasamentul nu a putut fi verificat', 'the ranking could not be verified'],
    claim_mismatch: ['explicația contrazice unitatea sau perioada datelor', 'the explanation contradicts the data unit or period'],
    unverified_numbers: ['unele cifre nu au putut fi verificate', 'some figures could not be verified'],
    unverified_total: ['completitudinea totalului nu este verificată', 'total completeness is unverified'],
    iterations: ['s-a atins limita de pași ai modelului', 'the model-step limit was reached'],
    tools: ['s-a atins limita de apeluri către instrumente', 'the tool-call limit was reached'],
    deadline: ['s-a depășit timpul alocat', 'the time limit was reached'],
    output_budget: ['bugetul de ieșire al modelului a fost depășit', 'the model output budget was exceeded'],
    output_limit: ['modelul a întrerupt răspunsul', 'the model cut the answer off'],
    empty_output: ['modelul nu a dat niciun răspuns', 'the model gave no answer'],
    content_filter: ['filtrul de conținut al furnizorului a oprit răspunsul', "the provider's content filter stopped the answer"],
    provider: ['furnizorul modelului nu a răspuns', 'the model provider did not respond'],
    cancelled: ['cererea a fost oprită', 'the request was stopped'],
    no_valid_query: ['nicio interogare validă nu susține cifrele', 'no valid query supports the figures'],
    conflicting_grain: ['setul repetă aceeași observație cu valori diferite', 'the dataset repeats the same observation with different values'],
    duplicate_keys: ['setul repetă observații, un total ar număra dublu', 'the dataset repeats observations, a total would double-count'],
    overlapping_levels: ['nivelurile se suprapun, un total ar număra dublu', 'the levels overlap, a total would double-count'],
    incomplete_domain: ['domeniul nu este complet (ex. fără 85 de ani și peste)', 'the domain is incomplete (e.g. without 85 and over)'],
    missing_weights: ['nu există ponderi pentru o medie', 'there are no weights for an average'],
    generation_unverified: ['datele nu au o generație verificată', 'the data has no verified generation'],
    generation_changed: ['datele s-au actualizat în timpul întrebării', 'the data was updated during the request'],
};
const LINK_LABEL = {
    live_selection: ['Selecția, rulată din nou', 'The selection, re-run'],
    csv: ['Date CSV', 'CSV data'],
    evidence: ['Pachet de dovezi', 'Evidence bundle'],
    dataset: ['Pagina setului de date', 'Dataset page'],
    share: ['Link de partajare', 'Share link'],
};

/** Origin of the Ask API: js/config.js `api_origin` when the pages are served apart from it (the
 *  static site), else this page's origin. Deployment configuration only, never the URL, a chat or a
 *  tool result: the request key is sent nowhere else. null = misconfigured, and then Ask is off
 *  rather than silently sent to another host. */
const ASK_ORIGIN_SET = !!(window.TEMPO_CONFIG || {}).api_origin;
const ASK_ORIGIN = (() => {
    const o = String((window.TEMPO_CONFIG || {}).api_origin || '');
    if (!o) return window.location.origin;
    try {
        const u = new URL(o);
        if ((u.protocol === 'https:' || u.protocol === 'http:') && u.origin === o.replace(/\/$/, '')) return u.origin;
    } catch { /* not a URL */ }
    console.warn('js/config.js api_origin is not a bare http(s) origin; Ask is off');
    return null;
})();
const askUrl = path => `${ASK_ORIGIN}/api${path}`;
const ASK_HOST = ASK_ORIGIN ? new URL(ASK_ORIGIN).host : '';

/** Only http(s) URLs become links (never javascript: and the like). A relative API path (live
 *  re-run, CSV, evidence) is on the Ask API's origin; a relative page path is on this site. */
function safeHref(u) {
    try {
        const s = String(u);
        const api = /^\/(api|sdmx)\//.test(s) && ASK_ORIGIN;
        const url = new URL(s, api ? ASK_ORIGIN : window.location.origin);
        return url.protocol === 'http:' || url.protocol === 'https:' ? url.href : null;
    } catch { return null; }
}

let askConfigPromise = null;
/** /api/ask/config, fetched once (null when unreachable). A static site without an Ask API
 *  answers it from its build (always unavailable). */
function askConfig() {
    askConfigPromise = askConfigPromise || (
        !ASK_ORIGIN ? Promise.resolve({ available: false })
        : API.isStatic && !ASK_ORIGIN_SET ? API.fetch('/ask/config').catch(() => null)
        : fetch(askUrl('/ask/config'), { credentials: 'omit' })
            .then(r => (r.ok ? r.json() : null)).catch(() => null));
    return askConfigPromise;
}

/** The Ask API on another origin cannot be reached (down, or this site is not among its allowed
 *  origins): say so, and offer a retry. Nothing falls back to this site's own /api. */
function showAskUnreachable() {
    const box = document.getElementById('ask-unavailable');
    box.textContent = tr(`Serviciul de întrebări (${ASK_HOST}) nu poate fi contactat acum. `,
                         `The question service (${ASK_HOST}) cannot be reached right now. `);
    const b = document.createElement('button');
    b.type = 'button';
    b.className = 'chat-reset';
    b.textContent = tr('Încearcă din nou', 'Try again');
    b.addEventListener('click', () => location.reload());
    box.appendChild(b);
    box.classList.remove('hidden');
}

/** Show the chat-logging disclosure before any question is submitted. */
async function initServerNotices() {
    try {
        const cfg = await askConfig();
        if (!cfg) {
            if (ASK_ORIGIN !== window.location.origin) showAskUnreachable();
            return;
        }
        if (cfg.limits && cfg.limits.max_history_turns) MAX_HISTORY_TURNS = cfg.limits.max_history_turns;
        if (cfg.limits && cfg.limits.max_seconds) MAX_SECONDS = cfg.limits.max_seconds;
        DEBUG_AVAILABLE = !!cfg.debug;
        const row = document.getElementById('s-debug-row');
        if (row) row.classList.toggle('hidden', !DEBUG_AVAILABLE);
        const box = document.getElementById('s-debug');
        if (box) {
            box.checked = debugOn();
            box.addEventListener('change', () => {
                try { localStorage.setItem('ask_debug', box.checked ? '1' : '0'); } catch { /* blocked */ }
            });
        }
        const b = document.getElementById('ask-logging-banner');
        if (b) b.classList.toggle('hidden', !cfg.chat_logging);
        if (cfg.available === false) showAskUnavailable();
    } catch { /* leave the banner hidden only if the config is unreachable */ }
}

/** Ask is switched off on this server (hosted and own-key): say so, point to
 *  the manual routes, and disable input instead of leaving a dead page. */
function showAskUnavailable() {
    ASK_UNAVAILABLE = true;
    const ro = siteLang() !== 'en';
    const box = document.getElementById('ask-unavailable');
    box.innerHTML = ro
        ? 'Întrebările în limbaj natural nu sunt disponibile pe acest server. '
          + 'Găsiți aceleași date prin <a href="/">căutare</a> sau <a href="/places">locuri</a>.'
        : 'Natural-language questions are not available on this server. '
          + 'Find the same data through <a href="/">search</a> or <a href="/places">places</a>.';
    box.classList.remove('hidden');
    document.getElementById('byok-notice')?.classList.add('hidden');
    for (const el of [document.getElementById('chat-input'), document.getElementById('chat-send'),
                      ...document.querySelectorAll('.chat-example')]) {
        if (el) el.disabled = true;
    }
}

// ---------------------------------------------------------------------------
// BYOK — Bring Your Own Key settings (persisted in localStorage)
// ---------------------------------------------------------------------------

const PROVIDER_LABELS = {
    anthropic: 'Anthropic', openai: 'OpenAI', gemini: 'Google Gemini', mistral: 'Mistral',
    deepseek: 'DeepSeek', xai: 'xAI (Grok)', openrouter: 'OpenRouter', ollama: 'Ollama (local, no key)',
};
const KEY_HINTS = {
    anthropic: 'sk-ant-…', openai: 'sk-proj-…', gemini: 'AIza…', mistral: 'Mistral API key',
    deepseek: 'sk-…', xai: 'xai-…', openrouter: 'sk-or-…', ollama: 'No key needed',
};
const KEYLESS = new Set(['ollama']);   // local models: the server switches them on
let PROVIDER_MODELS = {};  // labels from /ask-models.json, limited to what the server allows

// Key storage policy (FIX-08):
//  - default: in memory + sessionStorage (this tab only, gone when the tab closes)
//  - opt-in "Remember on this device": localStorage (unencrypted)
//  - a key left in localStorage by an older version is NOT deleted silently and NOT
//    hidden: it is loaded, shown as "remembered on this device", and Clear removes it.
// The key is never written to the DOM (the input is left empty after saving).
const K = { key: 'ask_api_key', provider: 'ask_provider', model: 'ask_model' };
let memKey = '';

function store(kind) {
    try { return kind === 'local' ? window.localStorage : window.sessionStorage; } catch { return null; }
}
function sget(kind, k) { try { return store(kind)?.getItem(k) || ''; } catch { return ''; } }
function sset(kind, k, v) { try { store(kind)?.setItem(k, v); } catch { /* storage blocked */ } }
function sdel(kind, k) { try { store(kind)?.removeItem(k); } catch { /* storage blocked */ } }

/** Where the current key is persisted: 'device' | 'tab' | 'none'. */
function keyScope() {
    if (sget('local', K.key)) return 'device';
    if (memKey || sget('session', K.key)) return 'tab';
    return 'none';
}

function getBYOK() {
    const apiKey = memKey || sget('local', K.key) || sget('session', K.key);
    const provider = sget('local', K.provider) || sget('session', K.provider) || 'anthropic';
    const model = sget('local', K.model) || sget('session', K.model) || '';
    return { apiKey, provider, model };
}

function saveBYOK(provider, model, apiKey, remember) {
    const existing = getBYOK().apiKey;
    const key = apiKey || existing;           // empty field keeps the current key
    memKey = key;
    // wipe both scopes first so a key never lingers in the scope the user did not choose
    for (const kind of ['local', 'session']) for (const k of Object.values(K)) sdel(kind, k);
    const kind = remember ? 'local' : 'session';
    sset(kind, K.provider, provider);
    sset(kind, K.model, model);
    if (key) sset(kind, K.key, key);
    updateKeyBadge();
}

function clearBYOK() {
    memKey = '';
    for (const kind of ['local', 'session']) for (const k of Object.values(K)) sdel(kind, k);
    updateKeyBadge();
}

function updateKeyBadge() {
    const scope = keyScope();
    const keyless = KEYLESS.has(getBYOK().provider) && !!PROVIDER_MODELS[getBYOK().provider];
    const hasKey = scope !== 'none' || keyless;
    const status = document.getElementById('s-key-status');
    if (status) status.textContent = keyless ? 'No key needed for a local model.'
        : scope === 'device' ? 'A key is saved on this device (localStorage). Press Clear to remove it.'
        : scope === 'tab' ? 'A key is set for this tab only.' : 'No key set.';
    const remember = document.getElementById('s-remember');
    if (remember) remember.checked = scope === 'device';
    const badge = document.getElementById('settings-badge');
    if (badge) badge.classList.toggle('hidden', !hasKey);
    const notice = document.getElementById('byok-notice');
    if (notice) notice.classList.toggle('hidden', hasKey || ASK_UNAVAILABLE);
}

/** Returns extra payload fields when a user key is stored, empty object otherwise. */
function byokPayload() {
    const { apiKey, provider, model } = getBYOK();
    const keyless = KEYLESS.has(provider);
    if (!apiKey && !keyless) return {};
    const first = (PROVIDER_MODELS[provider] || [])[0];
    const out = { provider, model: model || (first && first.id) || undefined };
    if (!keyless) out.api_key = apiKey;
    return out;
}

function updateKeyHint(provider) {
    const input = document.getElementById('s-key');
    if (!input) return;
    input.placeholder = KEY_HINTS[provider] || 'API key';
    input.disabled = KEYLESS.has(provider);
}

function populateModelSelect(provider, selectedModel) {
    const sel = document.getElementById('s-model');
    if (!sel) return;
    sel.innerHTML = '';
    const models = PROVIDER_MODELS[provider] || [];
    for (const m of models) {
        const opt = document.createElement('option');
        opt.value = m.id;
        opt.textContent = m.label;
        sel.appendChild(opt);
    }
    // Select saved model, or first option
    if (selectedModel && models.some(m => m.id === selectedModel)) sel.value = selectedModel;
    else if (models.length) sel.value = models[0].id;
}

async function initSettings() {
    const toggle = document.getElementById('settings-toggle');
    const panel  = document.getElementById('ask-settings');
    if (!toggle || !panel) return;

    // Labels from the JSON; the server's allowlist decides what is offered
    // (Ollama only appears when the server has a local model configured).
    let labels = {};
    try { labels = await (await fetch('/ask-models.json')).json(); } catch { /* ids as labels */ }
    const cfg = await askConfig();
    const allowed = (cfg && cfg.byok_models) || {};
    PROVIDER_MODELS = {};
    for (const [p, ids] of Object.entries(allowed)) {
        const named = Object.fromEntries((labels[p] || []).map(m => [m.id, m.label]));
        PROVIDER_MODELS[p] = ids.map(id => ({ id, label: named[id] || id }));
    }
    const provSel = document.getElementById('s-provider');
    provSel.innerHTML = '';
    for (const p of Object.keys(PROVIDER_MODELS)) {
        const opt = document.createElement('option');
        opt.value = p;
        opt.textContent = PROVIDER_LABELS[p] || p;
        provSel.appendChild(opt);
    }

    // Populate fields from storage (a provider the server no longer allows falls back to the first)
    let { provider, model } = getBYOK();
    if (!PROVIDER_MODELS[provider]) provider = Object.keys(PROVIDER_MODELS)[0] || '';
    provSel.value = provider;
    populateModelSelect(provider, model);
    updateKeyHint(provider);
    // the stored key is deliberately NOT copied into the input (keeps it out of the DOM)
    document.getElementById('s-key').value = '';
    updateKeyBadge();

    // Rebuild model dropdown when provider changes
    document.getElementById('s-provider').addEventListener('change', e => {
        populateModelSelect(e.target.value, '');
        updateKeyHint(e.target.value);
    });

    // "Open settings" link in the no-key notice
    const noticeBtn = document.getElementById('byok-notice-btn');
    if (noticeBtn) noticeBtn.addEventListener('click', e => { e.stopPropagation(); panel.classList.remove('hidden'); });

    // Toggle panel visibility
    toggle.addEventListener('click', e => {
        e.stopPropagation();
        panel.classList.toggle('hidden');
    });
    document.addEventListener('click', e => {
        if (!panel.contains(e.target) && e.target !== toggle)
            panel.classList.add('hidden');
    });

    document.getElementById('s-save').addEventListener('click', () => {
        const p = document.getElementById('s-provider').value;
        const m = document.getElementById('s-model').value;
        const k = document.getElementById('s-key').value.trim();
        saveBYOK(p, m, k, document.getElementById('s-remember').checked);
        document.getElementById('s-key').value = '';
        panel.classList.add('hidden');
    });

    document.getElementById('s-clear').addEventListener('click', () => {
        populateModelSelect(document.getElementById('s-provider').value, '');
        document.getElementById('s-key').value = '';
        clearBYOK();
        panel.classList.add('hidden');
    });
}

// ---------------------------------------------------------------------------
// Theme
// ---------------------------------------------------------------------------

function initTheme() {
    const saved = localStorage.getItem('lens_theme');
    const prefersDark = window.matchMedia('(prefers-color-scheme: dark)').matches;
    const theme = saved || (prefersDark ? 'dark' : 'light');
    applyTheme(theme);
}

function applyTheme(theme) {
    document.documentElement.setAttribute('data-theme', theme);
    localStorage.setItem('lens_theme', theme);
    const sun = document.getElementById('theme-icon-sun');
    const moon = document.getElementById('theme-icon-moon');
    if (sun) sun.classList.toggle('hidden', theme === 'dark');
    if (moon) moon.classList.toggle('hidden', theme === 'light');
}

// ---------------------------------------------------------------------------
// Markdown-lite renderer
// ---------------------------------------------------------------------------

function escapeHtml(s) {
    return s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}

function renderMarkdown(text) {
    // Escape first, then apply formatting
    let s = escapeHtml(text);
    // Bold
    s = s.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>');
    // Code spans
    s = s.replace(/`([^`]+)`/g, '<code>$1</code>');
    // Bullet lists (lines starting with - or *)
    s = s.replace(/^[ \t]*[-*] (.+)$/gm, '<li>$1</li>');
    s = s.replace(/(<li>.*<\/li>)/s, (m) => `<ul>${m}</ul>`);
    // Numbered lists
    s = s.replace(/^[ \t]*\d+\. (.+)$/gm, '<li>$1</li>');
    // Headings
    s = s.replace(/^### (.+)$/gm, '<h3>$1</h3>');
    s = s.replace(/^## (.+)$/gm, '<h2>$1</h2>');
    // Double newline → paragraph break
    s = s.replace(/\n\n/g, '</p><p>');
    // Single newline → <br>
    s = s.replace(/\n/g, '<br>');
    return `<p>${s}</p>`;
}

// ---------------------------------------------------------------------------
// Data table
// ---------------------------------------------------------------------------

function renderDataTable(data) {
    if (!data || !data.columns || !data.rows || data.rows.length === 0) return null;

    const wrap = document.createElement('div');
    wrap.className = 'chat-data-table-wrap';

    const meta = document.createElement('div');
    meta.className = 'chat-data-meta';
    // A ranking was computed over every eligible entity before its top K was cut; only an unranked
    // result (a query preview) is captioned as a preview.
    meta.textContent = data.ranked
        ? `${data.rows.length} ${tr('din', 'of')} ${data.eligible_count} ${(data.interval_count || 1) > 1
            ? tr('perechi entitate–interval eligibile, clasate pe interval', 'eligible entity–interval pairs, ranked within each interval')
            : tr('entități eligibile, în ordine', 'eligible entities, ranked')}`
        : data.truncated || data.preview
            ? `${tr('Previzualizare: primele', 'Preview: first')} ${data.rows.length} ${tr('rânduri; nu este un clasament', 'rows; not a ranking')}`
            : `${data.row_count ?? data.rows.length} ${tr('rânduri', 'rows')}`;
    if (data.unit) meta.textContent += ` · ${data.unit}`;
    if (data.ranked && data.excluded_count) {
        meta.textContent += ` · ${data.excluded_count} ${tr('excluse', 'excluded')}`;
    }
    if (data.ranked && data.outside_class_count) {
        meta.textContent += ` · ${data.outside_class_count} ${tr('din afara clasei (comune, totaluri), neclasate', 'outside the class (communes, totals), not ranked')}`;
    }
    if (data.matrix_code) {
        const link = document.createElement('a');
        link.href = datasetHref(data.matrix_code);
        link.target = '_blank';
        link.textContent = data.matrix_code;
        link.className = 'chat-data-code';
        meta.appendChild(document.createTextNode(' · '));
        meta.appendChild(link);
    }
    if (data.status === 'partial') {
        const b = document.createElement('span');
        b.className = 'agg-badge agg-badge-slice';
        b.textContent = tr('parțial', 'partial');
        meta.appendChild(document.createTextNode(' '));
        meta.appendChild(b);
    }
    wrap.appendChild(meta);

    // What part of the domain these values cover, when it is not the whole of it
    const sc = data.scope;
    if (sc && sc.description && sc.domain_complete !== true) {
        const note = document.createElement('div');
        note.className = 'chat-data-scope';
        note.textContent = sc.description;
        wrap.appendChild(note);
    }

    const tableWrap = document.createElement('div');
    tableWrap.className = 'chat-table-scroll';

    const table = document.createElement('table');
    table.className = 'chat-table';

    const thead = table.createTHead();
    const hrow = thead.insertRow();
    data.columns.forEach(col => {
        const th = document.createElement('th');
        const headings = {REF_AREA: tr('Județ / zonă', 'County / area'), REF_AREA_2: tr('Localitate', 'Locality'),
            TIME_PERIOD: tr('Perioadă', 'Period'), OBS_VALUE: tr('Valoare', 'Value'),
            RANK: tr('Poziție', 'Rank'), INTERVAL: tr('Interval', 'Interval'),
            FROM_VALUE: tr('Valoare inițială', 'Starting value'), TO_VALUE: tr('Valoare finală', 'Ending value'),
            ABSOLUTE: tr('Schimbare', 'Change'), PERCENT: tr('Schimbare (%)', 'Change (%)'),
            LABEL: tr('Zonă', 'Area'), VALUE: tr('Valoare', 'Value'), AGE: tr('Vârstă', 'Age'), SEX: tr('Sex', 'Sex')};
        th.textContent = headings[col] || col;
        th.title = col;
        hrow.appendChild(th);
    });

    const tbody = table.createTBody();
    const displayRows = data.rows.slice(0, 200);
    displayRows.forEach(row => {
        const tr = tbody.insertRow();
        row.forEach(cell => {
            const td = tr.insertCell();
            td.textContent = cell ?? '';
        });
    });

    if (data.rows.length > 200 || data.truncated) {
        const footerRow = tbody.insertRow();
        const td = footerRow.insertCell();
        td.colSpan = data.columns.length;
        td.className = 'chat-table-truncated';
        td.textContent = data.ranked
            ? tr('Lista este limitată; clasamentul complet și excluderile sunt în linkurile sursă.',
                 'This list is limited; the complete ranking and exclusions are in the source links.')
            : tr('Previzualizare limitată. Consultați selecția completă din linkurile sursă.',
                 'Limited preview. Open the complete selection using the source links.');
    }

    tableWrap.appendChild(table);
    wrap.appendChild(tableWrap);

    // The complete data and its evidence, one click away (the table above is a bounded preview)
    const links = (data.links || []).map(l => ({ ...l, href: safeHref(l.url) })).filter(l => l.href);
    if (links.length) {
        const box = document.createElement('div');
        box.className = 'chat-links';
        links.forEach(l => {
            const a = document.createElement('a');
            a.href = l.href;
            a.target = '_blank';
            a.rel = 'noopener';
            a.dataset.kind = l.kind || '';
            const label = LINK_LABEL[l.kind];
            a.textContent = label ? tr(label[0], label[1]) : (l.description || l.kind || l.href);
            if (l.description) a.title = l.description;
            box.appendChild(a);
        });
        wrap.appendChild(box);
    }
    return wrap;
}

// ---------------------------------------------------------------------------
// Chart rendering (simple eCharts for line / bar)
// ---------------------------------------------------------------------------

/** The dataset page a citation or table opens (the canonical v2 route). */
function datasetHref(code) {
    return `/dataset-v2.html?code=${encodeURIComponent(code)}${siteLang() === 'en' ? '&lang=en' : ''}`;
}

/** Chart series from a query result (PA-01c, audit A03). Every column other
 *  than time and value that varies across rows is part of a series' identity
 *  (geography included), so no observation is merged into another. A repeated
 *  (series, period) pair returns {error} instead of keeping one of them; the
 *  table still shows every row. */
function chartSeries(columns, rows) {
    const timeIdx = columns.indexOf('TIME_PERIOD');
    const valueIdx = columns.indexOf('OBS_VALUE');
    if (timeIdx === -1 || valueIdx === -1) return { error: 'no_time_or_value' };
    const keyIdx = columns.map((_, i) => i).filter(i => i !== timeIdx && i !== valueIdx
        && new Set(rows.map(r => r[i])).size > 1);
    const seriesMap = new Map();
    const allX = new Set();
    for (const row of rows) {
        const name = keyIdx.map(i => String(row[i] ?? '').trim()).join(' · ') || 'Value';
        const x = row[timeIdx];
        const y = row[valueIdx] == null ? null : parseFloat(row[valueIdx]);
        if (!seriesMap.has(name)) seriesMap.set(name, new Map());
        const pts = seriesMap.get(name);
        if (pts.has(x)) return { error: 'duplicate_key', series: name, period: x };
        pts.set(x, Number.isNaN(y) ? null : y);
        allX.add(x);
    }
    const xData = Array.from(allX).sort();
    return {
        xData,
        series: [...seriesMap].map(([name, pts]) => ({ name, data: xData.map(x => pts.get(x) ?? null) })),
    };
}

function renderChart(data, chartSpec) {
    if (!data || !data.columns || !data.rows || data.rows.length === 0) return null;
    if (!chartSpec || !chartSpec.primary_chart) return null;

    const primary = chartSpec.primary_chart;
    if (!['line', 'bar', 'grouped_bar', 'stacked_bar', 'area'].includes(primary)) return null;

    const built = chartSeries(data.columns, data.rows);
    if (built.error) return null;    // the table below still lists every row

    const container = document.createElement('div');
    container.className = 'chat-chart';
    const xData = built.xData;
    const chartType = ['area', 'line'].includes(primary) ? 'line' : 'bar';
    const series = built.series.map(({ name, data: pts }) => ({
        name,
        type: chartType,
        areaStyle: primary === 'area' ? {} : undefined,
        data: pts,
        smooth: primary === 'line' || primary === 'area',
    }));

    // Limit to 8 series to avoid clutter
    const visibleSeries = series.slice(0, 8);
    const hiddenCount = series.length - visibleSeries.length;

    const isDark = document.documentElement.getAttribute('data-theme') !== 'light';

    const option = {
        backgroundColor: 'transparent',
        textStyle: { color: isDark ? '#c8ccd4' : '#374151' },
        tooltip: { trigger: 'axis' },
        legend: series.length > 1 ? { top: 4, textStyle: { color: isDark ? '#c8ccd4' : '#374151' } } : undefined,
        grid: { left: 48, right: 16, top: series.length > 1 ? 36 : 12, bottom: 40, containLabel: false },
        xAxis: {
            type: 'category',
            data: xData,
            axisLabel: {
                color: isDark ? '#9ca3af' : '#6b7280',
                rotate: xData.length > 12 ? 45 : 0,
                fontSize: 11,
            },
            axisLine: { lineStyle: { color: isDark ? '#374151' : '#e5e7eb' } },
        },
        yAxis: {
            type: 'value',
            axisLabel: { color: isDark ? '#9ca3af' : '#6b7280', fontSize: 11 },
            splitLine: { lineStyle: { color: isDark ? '#1f2937' : '#f3f4f6' } },
        },
        series: visibleSeries,
        color: ['#818cf8', '#34d399', '#fb923c', '#f472b6', '#60a5fa', '#a78bfa', '#fbbf24', '#4ade80'],
    };

    // Defer init so container is in DOM
    requestAnimationFrame(() => {
        try {
            const chart = echarts.init(container);
            chart.setOption(option);
            if (hiddenCount > 0) {
                const note = document.createElement('div');
                note.className = 'chat-chart-note';
                note.textContent = `+${hiddenCount} series hidden`;
                container.after(note);
            }
        } catch (e) {
            console.warn('Chart render failed:', e);
        }
    });

    return container;
}

// ---------------------------------------------------------------------------
// Message rendering
// ---------------------------------------------------------------------------

function appendMessage(role, text) {
    const list = document.getElementById('chat-messages');
    const div = document.createElement('div');
    div.className = `chat-msg chat-msg--${role}`;
    div.innerHTML = role === 'user'
        ? `<div class="chat-bubble">${escapeHtml(text)}</div>`
        : `<div class="chat-bubble">${renderMarkdown(text)}</div>`;
    list.appendChild(div);
    scrollToBottom();
    return div;
}

function appendAssistantResponse(result) {
    turnLang = result.lang === 'en' || result.lang === 'ro' ? result.lang : null;
    try { buildAssistantResponse(result); } finally { turnLang = null; }
}

function buildAssistantResponse(result) {
    const list = document.getElementById('chat-messages');
    const div = document.createElement('div');
    div.className = 'chat-msg chat-msg--assistant';
    div.dataset.outcome = result.outcome || 'answered';

    // Outcome first: a partial, refused, failed or clarifying turn must not read as an answer
    const outcome = result.outcome;
    if (outcome && outcome !== 'answered' && OUTCOME_LABEL[outcome]) {
        const banner = document.createElement('div');
        banner.className = `chat-outcome chat-outcome--${outcome}`;
        banner.setAttribute('role', 'status');
        const lab = OUTCOME_LABEL[outcome];
        const why = REASON_TEXT[result.reason];
        banner.textContent = tr(lab[0], lab[1])
            + (result.reason && outcome !== 'clarification' ? ' — ' + (why ? tr(why[0], why[1]) : result.reason) : '');
        div.appendChild(banner);
    }

    // Answer text
    const bubble = document.createElement('div');
    bubble.className = 'chat-bubble';
    bubble.innerHTML = renderMarkdown(result.answer || tr('(fără răspuns)', '(no answer)'));
    div.appendChild(bubble);

    // Citations
    if (result.citations && result.citations.length > 0) {
        const cites = document.createElement('div');
        cites.className = 'chat-citations';
        result.citations.forEach(c => {
            const code = typeof c === 'string' ? c : c.matrix_code;
            const name = typeof c === 'string' ? '' : (c.matrix_name || '');
            const a = document.createElement('a');
            a.href = datasetHref(code);
            a.target = '_blank';
            a.className = 'chat-citation';
            a.textContent = `↗ ${code}${name ? ' — ' + name : ''}`;
            cites.appendChild(a);
            // FIX-02/08: what the cited query was allowed to claim
            const q = (c.queries || []);
            const tag = q.some(x => x.approximation) ? 'approx'
                : q.length && q.every(x => x.status === 'unavailable') ? 'unavail'
                : q.some(x => x.outcome === 'valid_slice' || x.status === 'partial') ? 'slice' : null;
            if (tag) {
                const ro = isRo();
                const label = { approx: ro ? 'aproximare' : 'approximation',
                                unavail: ro ? 'indisponibil' : 'unavailable',
                                slice: ro ? 'selecție parțială' : 'partial selection' }[tag];
                const b = document.createElement('span');
                b.className = 'agg-badge agg-badge-' + tag;
                b.textContent = label;
                cites.appendChild(b);
            }
        });
        div.appendChild(cites);
    }

    // Warnings (filter out internal diagnostics)
    const userWarnings = (result.warnings || []).filter(w => !w.startsWith('Guardrail:'));
    if (userWarnings.length > 0) {
        const warn = document.createElement('div');
        warn.className = 'chat-warnings';
        userWarnings.forEach(w => {
            const item = document.createElement('div');
            item.className = 'chat-warning-item';
            item.textContent = w;
            warn.appendChild(item);
        });
        div.appendChild(warn);
    }

    // Numbers the deterministic check could not find in any query result
    const unc = (result.verification && result.verification.uncited_numbers) || [];
    if (unc.length && result.verification.status === 'unverified_numbers') {
        const note = document.createElement('div');
        note.className = 'chat-unverified';
        note.textContent = tr('Cifre negăsite în rezultatele interogărilor: ',
                              'Numbers not found in the query results: ') + unc.slice(0, 8).join(', ');
        div.appendChild(note);
    }
    // Figures found in a result but not tied to a row the answer names
    const cs = result.verification && result.verification.claim_summary;
    if (cs && cs.unverified > 0 && result.verification.status === 'verified') {
        const note = document.createElement('div');
        note.className = 'chat-unverified';
        note.textContent = tr('Unele cifre nu au putut fi legate de un anumit rând din rezultate.',
                              'Some figures could not be tied to a specific result row.');
        div.appendChild(note);
    }

    // Data table
    const tableEl = renderDataTable(result.data);
    if (tableEl) div.appendChild(tableEl);

    // Chart
    const chartEl = renderChart(result.data, result.chart_spec);
    if (chartEl) div.appendChild(chartEl);

    // Tool trace (collapsible)
    if (result.tool_trace && result.tool_trace.length > 0) {
        const details = document.createElement('details');
        details.className = 'chat-trace';
        const summary = document.createElement('summary');
        summary.textContent = `${result.tool_trace.length} tool call${result.tool_trace.length > 1 ? 's' : ''}`;
        details.appendChild(summary);
        result.tool_trace.forEach(t => {
            const row = document.createElement('div');
            row.className = 'chat-trace-item';
            row.innerHTML = `<span class="chat-trace-tool">${escapeHtml(t.tool)}</span>`
                + `<code class="chat-trace-input">${escapeHtml(JSON.stringify(t.input))}</code>`;
            details.appendChild(row);
        });
        div.appendChild(details);
    }

    if (result.debug) {
        const { debug, ...raw } = result;
        appendDebugPanel(div, debug.events || [], raw);
    }

    list.appendChild(div);
    scrollToBottom();
}

function appendLoadingIndicator() {
    const list = document.getElementById('chat-messages');
    const div = document.createElement('div');
    div.className = 'chat-msg chat-msg--assistant chat-msg--loading';
    div.id = 'chat-loading';
    div.innerHTML = '<div class="chat-bubble"><span class="chat-dots"><span></span><span></span><span></span></span>'
        + '<span class="chat-wait"></span><div class="chat-debug-log hidden"></div></div>';
    list.appendChild(div);
    // Elapsed time against the server's budget, so a slow answer is not a silent one.
    const wait = div.querySelector('.chat-wait');
    const t0 = Date.now();
    const timer = setInterval(() => {
        const s = Math.round((Date.now() - t0) / 1000);
        wait.textContent = `${s}s / ${MAX_SECONDS}s`;
    }, 1000);
    const remove = div.remove.bind(div);
    div.remove = () => { clearInterval(timer); remove(); };
    scrollToBottom();
    return div;
}

/** One agent step (debug mode) as a short line. */
function fmtEvent(ev) {
    const t = `${(ev.ms / 1000).toFixed(1)}s`.padStart(6);
    const secs = ms => `${(ms / 1000).toFixed(1)}s`;
    switch (ev.event) {
        case 'start': return `${t}  start · ${ev.provider} / ${ev.model} · ${ev.history_turns} earlier turns`
            + (ev.context_entries ? ` · ${ev.context_entries} earlier selections` : '')
            + (ev.lang ? ` · ${ev.lang} (${ev.lang_source})` : '');
        case 'model_call': return `${t}  → model call #${ev.iteration} (${ev.messages} messages`
            + `${ev.max_tokens ? `, ≤${ev.max_tokens} tokens` : ''})${ev.final ? ' · final answer, tools off' : ''}`;
        case 'model_done': return `${t}  ← model #${ev.iteration} in ${secs(ev.took_ms)}: ${ev.finish || ev.stop_reason}`
            + ((ev.tool_calls || []).length ? ` · tools: ${ev.tool_calls.join(', ')}` : '') + ` · text ${ev.text_chars} chars`
            + (ev.usage ? ` · ${ev.usage.input_tokens ?? '?'} in / ${ev.usage.output_tokens ?? '?'} out tokens` : '');
        case 'model_error': return `${t}  ✗ model #${ev.iteration} after ${secs(ev.took_ms)}: ${ev.code} · ${ev.detail}`;
        case 'retry': return `${t}  ↻ one retry (${ev.code})`;
        case 'compact': return `${t}  ⇣ ${ev.results} earlier result(s) shortened to fit the context budget`;
        case 'tool': return `${t}  ⚙ ${ev.name} ${JSON.stringify(ev.input).slice(0, 160)}`;
        case 'tool_done': return `${t}  ✓ ${ev.name} in ${secs(ev.took_ms)}`
            + (ev.status ? ` · ${ev.status}` : '') + (ev.reason ? ` (${ev.reason})` : '')
            + (ev.cached ? ' · from this turn\'s cache' : '') + (ev.rows != null ? ` · ${ev.rows} rows` : '')
            + ` · ${ev.result_bytes ?? ev.result_chars} bytes`;
        case 'guardrail': return `${t}  ! guardrail: ${ev.note}`;
        case 'answer': return `${t}  ✔ answer (${ev.text_chars} chars)${ev.outcome ? ` · ${ev.outcome}` : ''}${ev.reason ? ` (${ev.reason})` : ''}`;
        case 'stopped': return `${t}  ■ stopped: ${ev.reason}`;
        case 'server_error': return `      ✗ server error: ${ev.detail}`;
        default: return `${t}  ${JSON.stringify(ev)}`;
    }
}

function appendDebugLine(loadingEl, ev) {
    const log = loadingEl.querySelector('.chat-debug-log');
    log.classList.remove('hidden');
    const line = document.createElement('div');
    if (/error/.test(ev.event)) line.className = 'err';
    line.textContent = fmtEvent(ev);
    log.appendChild(line);
    log.scrollTop = log.scrollHeight;
    scrollToBottom();
}

/** Debug panel under an answer or an error: the steps and the raw JSON. */
function appendDebugPanel(parent, events, raw) {
    const details = document.createElement('details');
    details.className = 'chat-debug';
    const summary = document.createElement('summary');
    summary.textContent = `Debug · ${events.length} steps`;
    details.appendChild(summary);
    const steps = document.createElement('pre');
    steps.textContent = events.map(fmtEvent).join('\n');
    details.appendChild(steps);
    if (raw !== undefined) {
        const json = document.createElement('pre');
        json.textContent = JSON.stringify(raw, null, 2);
        details.appendChild(json);
    }
    parent.appendChild(details);
}

/** Debug mode: POST /api/ask/stream, show each step live, resolve with the result. */
async function askStreaming(body, loadingEl, signal) {
    const resp = await fetch(askUrl('/ask/stream'), {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body), signal,
        credentials: 'omit',
    });
    if (!resp.ok || !resp.body) return { error: { status: resp.status, detail: resp.statusText }, events: [] };
    const reader = resp.body.getReader();
    const dec = new TextDecoder();
    const events = [];
    let buf = '', last = null;
    for (;;) {
        const { value, done } = await reader.read();
        if (done) break;
        buf += dec.decode(value, { stream: true });
        let nl;
        while ((nl = buf.indexOf('\n')) >= 0) {
            const line = buf.slice(0, nl).trim();
            buf = buf.slice(nl + 1);
            if (!line) continue;
            const ev = JSON.parse(line);
            if (ev.event === 'result' || ev.event === 'error') { last = ev; continue; }
            events.push(ev);
            appendDebugLine(loadingEl, ev);
        }
    }
    if (!last) return { error: { status: 0, detail: 'The stream ended without a result' }, events };
    return last.event === 'result' ? { result: last.result, events } : { error: last, events };
}

function scrollToBottom() {
    const list = document.getElementById('chat-messages');
    list.scrollTop = list.scrollHeight;
}

// ---------------------------------------------------------------------------
// Send message
// ---------------------------------------------------------------------------

/** Start over: history, follow-up selections and the thread are dropped (nothing was stored server-side). */
function resetChat() {
    history.length = 0;
    askContext = [];
    document.querySelectorAll('#chat-messages .chat-msg').forEach(el => el.remove());
    const empty = document.getElementById('chat-empty');
    if (empty) empty.style.display = '';
    document.getElementById('chat-reset')?.classList.add('hidden');
    document.getElementById('chat-input')?.focus();
}

/** A failed turn: say why, keep the question for editing, and suggest what to do next. */
function appendFailure(text, question, opts = {}) {
    const el = appendMessage('assistant', text);
    el.classList.add('chat-msg--error');
    el.dataset.outcome = 'error';
    const input = document.getElementById('chat-input');
    if (question && input && !input.value) { input.value = question; autoResize(input); }
    const next = document.createElement('div');
    next.className = 'chat-next';
    const search = document.createElement('a');
    search.href = '/';
    search.textContent = tr('Caută direct în date', 'Search the data directly');
    next.appendChild(search);
    if (opts.reset) {
        const b = document.createElement('button');
        b.type = 'button';
        b.textContent = tr('Conversație nouă', 'New conversation');
        b.addEventListener('click', resetChat);
        next.appendChild(b);
    }
    el.appendChild(next);
    return el;
}

/** The request never reached the Ask API or its answer was cut off. The browser does not say
 *  which (a refused cross-origin request looks like a network error), and its message is not
 *  shown: the question stays in the box, with a retry. */
function appendInterrupted(question) {
    const el = appendFailure(tr(`Serviciul de întrebări (${ASK_HOST}) nu a putut fi contactat sau răspunsul s-a întrerupt. Întrebarea a rămas în câmp.`,
                                `The question service (${ASK_HOST}) could not be reached or its answer was cut off. Your question is still in the box.`),
                             question);
    el.dataset.outcome = 'interrupted';
    const b = document.createElement('button');
    b.type = 'button';
    b.textContent = tr('Încearcă din nou', 'Try again');
    b.addEventListener('click', () => { if (!isLoading) sendMessage(); });
    el.querySelector('.chat-next').prepend(b);
}

async function sendMessage() {
    if (ASK_UNAVAILABLE || !ASK_ORIGIN) return;
    const input = document.getElementById('chat-input');
    const question = input.value.trim();
    if (!question || isLoading) return;

    isLoading = true;
    input.value = '';
    autoResize(input);
    setInputDisabled(true);

    appendMessage('user', question);
    const loadingEl = appendLoadingIndicator();

    // server caps history; send only the most recent turns (see /api/ask/config limits)
    // `lang` is the site's language, on every turn: the server uses it for a question that shows none.
    const body = { question, lang: siteLang(), history: history.slice(-MAX_HISTORY_TURNS),
                   ...(askContext.length ? { context: askContext } : {}), ...byokPayload() };
    // Never wait forever: the server stops at MAX_SECONDS; allow a margin for the last call.
    // Aborting also tells the server to stop the work (it sees the disconnect).
    const ctl = new AbortController();
    const abortTimer = setTimeout(() => ctl.abort(), (MAX_SECONDS + 30) * 1000);
    try {
        let result;
        if (debugOn()) {
            const out = await askStreaming(body, loadingEl, ctl.signal);
            loadingEl.remove();
            if (out.error && out.error.status === 0) {
                appendInterrupted(question);
                return;
            }
            if (out.error) {
                const d = out.error.detail;
                if (out.error.status === 409 && d && d.action === 'refresh') askContext = [];
                const el = appendFailure(`Error ${out.error.status}: ${typeof d === 'string' ? d : (d && d.message) || JSON.stringify(d)}`,
                                         question, { reset: out.error.status === 409 });
                appendDebugPanel(el, out.events, out.error);
                return;
            }
            result = { ...out.result, debug: { events: out.events } };
        } else {
            const resp = await fetch(askUrl('/ask'), {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(body),
                signal: ctl.signal,
                credentials: 'omit',
            });

            loadingEl.remove();

            if (!resp.ok) {
                const err = await resp.json().catch(() => ({ detail: resp.statusText }));
                const detail = typeof err.detail === 'string' ? err.detail
                    : (err.detail && typeof err.detail.message === 'string') ? err.detail.message : 'Request rejected';
                const retry = resp.headers.get('Retry-After');
                const stale = resp.status === 409 && err.detail && err.detail.action === 'refresh';
                if (stale) askContext = [];            // the earlier selections belong to older data
                appendFailure(`Error ${resp.status}: ${detail}` + (retry ? ` (retry in ~${retry}s)` : ''),
                              question, { reset: stale });
                return;
            }
            try { result = await resp.json(); } catch { appendInterrupted(question); return; }
        }
        appendAssistantResponse(result);
        if (Array.isArray(result.context)) askContext = result.context;
        document.getElementById('chat-reset')?.classList.remove('hidden');

        // Update history for next turn
        history.push({ role: 'user', content: question });
        history.push({ role: 'assistant', content: result.answer || '' });

    } catch (e) {
        loadingEl.remove();
        if (e.name === 'AbortError') {
            appendFailure(tr(`Niciun răspuns după ${MAX_SECONDS + 30}s; cererea a fost oprită. Încercați o întrebare mai restrânsă (un singur indicator, un an, un județ).`,
                             `No answer after ${MAX_SECONDS + 30}s; the request was stopped. Try a narrower question (one indicator, one year, one county).`), question);
        } else {
            appendInterrupted(question);   // network, refused cross-origin request or a cut stream
        }
    } finally {
        clearTimeout(abortTimer);
        isLoading = false;
        setInputDisabled(false);
        input.focus();
    }
}

function setInputDisabled(disabled) {
    document.getElementById('chat-input').disabled = disabled;
    document.getElementById('chat-send').disabled = disabled;
    document.getElementById('chat-send').classList.toggle('loading', disabled);
}

// ---------------------------------------------------------------------------
// Auto-resize textarea
// ---------------------------------------------------------------------------

function autoResize(el) {
    el.style.height = 'auto';
    el.style.height = Math.min(el.scrollHeight, 160) + 'px';
}

// ---------------------------------------------------------------------------
// Init
// ---------------------------------------------------------------------------

document.addEventListener('DOMContentLoaded', () => {
    initTheme();
    initSettings();
    initServerNotices();

    // Theme toggle
    document.getElementById('theme-toggle').addEventListener('click', () => {
        const current = document.documentElement.getAttribute('data-theme');
        applyTheme(current === 'dark' ? 'light' : 'dark');
    });

    // Send button
    document.getElementById('chat-send').addEventListener('click', sendMessage);
    document.getElementById('chat-reset')?.addEventListener('click', resetChat);

    // Enter to send (Shift+Enter = newline)
    const input = document.getElementById('chat-input');
    input.addEventListener('keydown', e => {
        if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault();
            sendMessage();
        }
    });
    input.addEventListener('input', () => autoResize(input));

    // Example questions
    document.querySelectorAll('.chat-example').forEach(btn => {
        btn.addEventListener('click', () => {
            input.value = btn.dataset.q;
            autoResize(input);
            input.focus();
        });
    });

    input.focus();
});
