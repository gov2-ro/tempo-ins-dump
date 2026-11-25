/**
 * Shared site chrome for every page: the one top bar (rendered here, from this
 * file only), the search overlay, the quick-nav sidebar, theme & language toggles.
 *
 * A page holds `<nav class="topbar" id="topbar" data-active="data|places|ask|api">`.
 *   data-active  which link carries aria-current="page".
 *   data-own     space-separated controls the page controller binds itself, so
 *                this file leaves them alone: search sidebar about theme lang.
 *   [data-slot="left"|"right"] children of the nav move into the left slot
 *                (after the logo) or the right slot (before About).
 * The bar keeps the ids the controllers bind to: search-trigger, about-btn,
 * theme-toggle, lang-toggle (and the page's own sidebar-toggle).
 * Dataset links land on dashboard-v2 (the canonical dataset page). Theme changes
 * dispatch a `themechange` event on window so controllers can re-render ECharts.
 */

const BAR_UI = {
    ro: {
        nav: 'Navigare principală', data: 'Date', places: 'Locuri', ask: 'Ask', api: 'API', mcp: 'MCP',
        about: 'Despre', theme: 'Schimbă tema luminoasă/întunecată', lang: 'Schimbă limba',
        search: 'Caută seturi de date',
    },
    en: {
        nav: 'Main navigation', data: 'Data', places: 'Places', ask: 'Ask', api: 'API', mcp: 'MCP',
        about: 'About', theme: 'Toggle light/dark theme', lang: 'Switch language',
        search: 'Search datasets',
    },
};

const BAR_LINKS = [
    ['data', '/', '<ellipse cx="12" cy="5" rx="9" ry="3"/><path d="M21 12c0 1.66-4 3-9 3s-9-1.34-9-3"/><path d="M3 5v14c0 1.66 4 3 9 3s9-1.34 9-3V5"/>'],
    ['places', '/places', '<path d="M21 10c0 7-9 13-9 13s-9-6-9-13a9 9 0 0 1 18 0z"/><circle cx="12" cy="10" r="3"/>'],
    ['ask', '/ask.html', '<path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/>'],
    ['api', '/api.html', '<polyline points="16 18 22 12 16 6"/><polyline points="8 6 2 12 8 18"/>'],
    // MCP: the robot icon; the section of the API page that explains the connector
    ['mcp', '/api.html#mcp', '<path d="M12 8V4H8"/><rect width="16" height="12" x="4" y="8" rx="2"/><path d="M2 14h2"/><path d="M20 14h2"/><path d="M15 13v2"/><path d="M9 13v2"/>'],
];

function barLang() {
    const l = new URLSearchParams(window.location.search).get('lang') || localStorage.getItem('lens_lang') || 'ro';
    return l === 'en' ? 'en' : 'ro';
}

/** Fill the #topbar placeholder. Runs once, as soon as this script loads. */
function renderTopbar() {
    const nav = document.getElementById('topbar');
    if (!nav || nav.dataset.rendered) return;
    const slots = { left: [], right: [] };
    for (const el of [...nav.children]) {
        if (slots[el.dataset.slot]) slots[el.dataset.slot].push(el);
    }
    const ui = BAR_UI[barLang()];
    const active = nav.dataset.active;
    const links = BAR_LINKS.map(([key, href, icon]) => `
        <a href="${href}" class="toggle-btn tb-link" data-bar="${key}"${key === active ? ' aria-current="page"' : ''}>
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${icon}</svg><span class="tb-label">${ui[key]}</span></a>`).join('');
    nav.innerHTML = `
        <div class="topbar-left">
            <a id="zelogo" href="/" class="logo"><span class="logo-dot"></span>INS<span style="margin: -1ex 0 0 -1ex;">+</span></a>
        </div>
        <button class="search-trigger" id="search-trigger" aria-label="${ui.search}">
            <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/></svg>
            <span>${CHROME_UI[barLang()].searchTrigger}</span>
            <kbd>&hairsp;/&hairsp;</kbd>
        </button>
        <div class="topbar-right">${links}
            <button class="toggle-btn about-btn" id="about-btn" title="${ui.about}" aria-label="${ui.about}">?</button>
            <button class="toggle-btn" id="theme-toggle" title="${ui.theme}" aria-label="${ui.theme}">
                <svg id="theme-icon-sun" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="5"/><line x1="12" y1="1" x2="12" y2="3"/><line x1="12" y1="21" x2="12" y2="23"/><line x1="4.22" y1="4.22" x2="5.64" y2="5.64"/><line x1="18.36" y1="18.36" x2="19.78" y2="19.78"/><line x1="1" y1="12" x2="3" y2="12"/><line x1="21" y1="12" x2="23" y2="12"/><line x1="4.22" y1="19.78" x2="5.64" y2="18.36"/><line x1="18.36" y1="5.64" x2="19.78" y2="4.22"/></svg>
                <svg id="theme-icon-moon" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"/></svg>
            </button>
            <button class="toggle-btn lang-toggle" id="lang-toggle" title="${ui.lang}" aria-label="${ui.lang}">
                <span id="lang-label">${barLang() === 'ro' ? 'EN' : 'RO'}</span>
            </button>
        </div>`;
    nav.classList.add('tb-compact');
    nav.setAttribute('aria-label', ui.nav);
    nav.querySelector('.topbar-left').append(...slots.left);
    for (const el of slots.right) nav.querySelector('.topbar-right').insertBefore(el, nav.querySelector('#about-btn'));
    nav.dataset.rendered = '1';
}

/** Relabel the bar for a language (the lang toggle changed it without a reload). */
function setBarLang(lang) {
    const nav = document.getElementById('topbar');
    if (!nav) return;
    const ui = BAR_UI[lang] || BAR_UI.ro;
    for (const a of nav.querySelectorAll('[data-bar]')) a.querySelector('.tb-label').textContent = ui[a.dataset.bar];
    for (const [id, key] of [['about-btn', 'about'], ['theme-toggle', 'theme'], ['lang-toggle', 'lang'], ['search-trigger', 'search']]) {
        const node = document.getElementById(id);
        if (!node) continue;
        node.setAttribute('aria-label', ui[key]);
        if (id !== 'search-trigger') node.title = ui[key];
    }
    nav.setAttribute('aria-label', ui.nav);
    const label = document.getElementById('lang-label');
    if (label) label.textContent = lang === 'ro' ? 'EN' : 'RO';
    const trigger = document.querySelector('#search-trigger span');
    if (trigger) trigger.textContent = CHROME_UI[lang].searchTrigger;
}

const CHROME_UI = {
    ro: {
        searchTrigger: 'Caută seturi de date...',
        searchPlaceholder: 'Caută seturi de date, indicatori, coduri...',
        searchEmpty: 'Tastează pentru a căuta în toate seturile de date',
        searchNoResults: 'Niciun rezultat',
        searchError: 'Eroare la căutare',
        searchLoading: 'Se încarcă rezultatele, poate dura câteva secunde…',
        sidebarTitle: 'Navighează',
        sidebarFilter: 'Filtrează seturile...',
    },
    en: {
        searchTrigger: 'Search datasets...',
        searchPlaceholder: 'Search datasets, indicators, codes...',
        searchEmpty: 'Type to search across all datasets',
        searchNoResults: 'No results',
        searchError: 'Search error',
        searchLoading: 'Loading results, this can take a few seconds…',
        sidebarTitle: 'Navigate',
        sidebarFilter: 'Filter datasets...',
    },
};

class SiteChrome {
    constructor() {
        const params = new URLSearchParams(window.location.search);
        this.lang = params.get('lang') || localStorage.getItem('lens_lang') || 'ro';
        if (!CHROME_UI[this.lang]) this.lang = 'ro';
        this.ui = CHROME_UI[this.lang];
        this.own = new Set((document.getElementById('topbar')?.dataset.own || '').split(/\s+/));
        this.searchIdx = -1;
        this.categories = null;
        this._sidebarLoaded = false;
    }

    dsHref(code) {
        return `/dataset-v2.html?code=${code}${this.lang !== 'ro' ? `&lang=${this.lang}` : ''}`;
    }

    init() {
        this.applyLang();
        this.bindTopbar();
        if (!this.own.has('search')) {
            this.ensureSearchOverlay();
            this.bindSearch();
        }
        if (!this.own.has('sidebar')) this.initSidebar();
    }

    setLang(lang) {
        this.lang = lang;
        this.ui = CHROME_UI[lang];
        setBarLang(lang);
    }

    /** Pages without their own search overlay get this one. */
    ensureSearchOverlay() {
        if (document.getElementById('search-overlay')) return;
        document.body.insertAdjacentHTML('beforeend', `
    <div class="search-overlay hidden" id="search-overlay">
        <div class="search-backdrop" id="search-backdrop"></div>
        <div class="search-modal">
            <div class="search-input-row">
                <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/></svg>
                <input type="text" id="search-input" spellcheck="false">
                <kbd>esc</kbd>
            </div>
            <div id="search-results" class="search-results"></div>
        </div>
    </div>`);
        const input = document.getElementById('search-input');
        input.placeholder = this.ui.searchPlaceholder;
    }

    applyLang() {
        const trigger = document.querySelector('#search-trigger span');
        if (trigger) trigger.textContent = this.ui.searchTrigger;
        const input = document.getElementById('search-input');
        if (input) input.placeholder = this.ui.searchPlaceholder;
        const title = document.getElementById('sidebar-title');
        if (title) title.textContent = this.ui.sidebarTitle;
        const filter = document.getElementById('sidebar-search-input');
        if (filter) filter.placeholder = this.ui.sidebarFilter;
        const label = document.getElementById('lang-label');
        if (label) label.textContent = this.lang === 'ro' ? 'EN' : 'RO';
        if (typeof localizeChrome === 'function') localizeChrome(this.lang);
    }

    // ------------------------------------------------------------ theme/lang

    bindTopbar() {
        if (!this.own.has('theme')) document.getElementById('theme-toggle')?.addEventListener('click', () => {
            const next = (document.documentElement.dataset.theme === 'light') ? 'dark' : 'light';
            document.documentElement.dataset.theme = next;
            document.body.dataset.theme = next;
            localStorage.setItem('lens_theme', next);
            window.dispatchEvent(new CustomEvent('themechange'));
        });
        if (this.own.has('lang')) {
            // The controller switches the language in the page. Relabel the bar after it did.
            document.getElementById('lang-toggle')?.addEventListener('click', () =>
                setTimeout(() => this.setLang(document.getElementById('lang-label').textContent === 'EN' ? 'ro' : 'en')));
        } else {
            document.getElementById('lang-toggle')?.addEventListener('click', () => {
                const next = this.lang === 'ro' ? 'en' : 'ro';
                localStorage.setItem('lens_lang', next);
                const url = new URL(window.location);
                url.searchParams.set('lang', next);
                window.location.href = url.toString();
            });
        }
        if (!this.own.has('about')) document.getElementById('about-btn')?.addEventListener('click', () => {
            window.location.href = `/?page=about${this.lang === 'en' ? '&lang=en' : ''}`;
        });
    }

    // ---------------------------------------------------------------- search

    bindSearch() {
        document.getElementById('search-trigger')?.addEventListener('click', () => this.openSearch());
        document.getElementById('search-backdrop')?.addEventListener('click', () => this.closeSearch());
        document.getElementById('search-input')?.addEventListener('input',
            e => this.onSearchInput(e.target.value));
        document.addEventListener('keydown', e => {
            const typing = ['INPUT', 'SELECT', 'TEXTAREA'].includes(document.activeElement.tagName);
            if (e.key === '/' && !e.ctrlKey && !e.metaKey && !typing) {
                e.preventDefault();
                this.openSearch();
            }
            if ((e.metaKey || e.ctrlKey) && e.key === 'k') {
                e.preventDefault();
                this.openSearch();
            }
            if (e.key === 'Escape') this.closeSearch();
            if (!document.getElementById('search-overlay').classList.contains('hidden')) {
                if (e.key === 'ArrowDown') { e.preventDefault(); this.moveSearchIdx(1); }
                if (e.key === 'ArrowUp') { e.preventDefault(); this.moveSearchIdx(-1); }
                if (e.key === 'Enter') { e.preventDefault(); this.selectSearchItem(); }
            }
        });
    }

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
        const seq = this._searchSeq = (this._searchSeq || 0) + 1;
        const slow = setTimeout(() => {          // the first search can take seconds (index load)
            if (seq === this._searchSeq) results.innerHTML =
                `<div class="search-empty search-loading"><span class="search-spinner"></span>${this.ui.searchLoading}</div>`;
        }, 300);
        try {
            const resp = await API.search(query, { limit: 10, lang: this.lang });
            if (seq !== this._searchSeq) return;         // a newer keystroke owns the list
            this.searchIdx = -1;
            if (!renderSearchResults(results, resp, {
                lang: this.lang, onOpenCode: code => { window.location.href = this.dsHref(code); } })) {
                results.innerHTML = `<div class="search-empty">${this.ui.searchNoResults}</div>`;
            }
        } catch (_) {
            if (seq === this._searchSeq) results.innerHTML = `<div class="search-empty">${this.ui.searchError}</div>`;
        } finally {
            clearTimeout(slow);
        }
    }

    moveSearchIdx(delta) {
        const items = document.querySelectorAll('#search-results .search-item');
        if (!items.length) return;
        this.searchIdx = Math.max(0, Math.min(items.length - 1, this.searchIdx + delta));
        items.forEach((el, i) => el.classList.toggle('selected', i === this.searchIdx));
        items[this.searchIdx].scrollIntoView({ block: 'nearest' });
    }

    selectSearchItem() {
        const items = document.querySelectorAll('#search-results .search-item');
        if (this.searchIdx >= 0 && items[this.searchIdx]) items[this.searchIdx].click();
        else if (items.length) items[0].click();
    }

    // --------------------------------------------------------------- sidebar

    initSidebar() {
        if (!document.getElementById('lens-sidebar')) return;
        document.getElementById('sidebar-toggle')?.addEventListener('click', () => this.toggleSidebar());
        document.getElementById('sidebar-close')?.addEventListener('click', () => this.closeSidebar());
        document.getElementById('sidebar-search-input')?.addEventListener('input',
            e => this.filterSidebar(e.target.value.toLowerCase()));
        if (sessionStorage.getItem('lensNavOpen') === '1') this.openSidebar();
    }

    toggleSidebar() {
        const sidebar = document.getElementById('lens-sidebar');
        if (sidebar.classList.contains('hidden')) this.openSidebar();
        else this.closeSidebar();
    }

    openSidebar() {
        document.getElementById('lens-sidebar').classList.remove('hidden');
        document.getElementById('sidebar-toggle').classList.add('active');
        document.getElementById('sidebar-toggle').setAttribute('aria-expanded', 'true');
        document.body.classList.add('sidebar-open');
        sessionStorage.setItem('lensNavOpen', '1');
        if (!this._sidebarLoaded) this.renderSidebar();
        requestAnimationFrame(() => window.dispatchEvent(new Event('resize')));
    }

    closeSidebar() {
        document.getElementById('lens-sidebar').classList.add('hidden');
        document.getElementById('sidebar-toggle').classList.remove('active');
        document.getElementById('sidebar-toggle').setAttribute('aria-expanded', 'false');
        document.body.classList.remove('sidebar-open');
        sessionStorage.setItem('lensNavOpen', '');
        requestAnimationFrame(() => window.dispatchEvent(new Event('resize')));
    }

    shortName(name) {
        const stripped = String(name).replace(/^[A-Z]?\.\d*\s*/, '').replace(/^\d+\.\s*/, '');
        return stripped.charAt(0).toUpperCase() + stripped.slice(1).toLowerCase();
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
                const section = document.createElement('div');
                section.className = 'sb-section';
                section.textContent = this.shortName(cat.name);
                tree.appendChild(section);
                for (const sub of cat.children || []) {
                    this.buildSidebarItem(sub, tree, 2);
                }
            }
            const code = new URLSearchParams(window.location.search).get('code');
            if (code) this.highlightSidebarDataset(code);
        } catch (err) {
            tree.innerHTML = `<div class="sb-loading">Error: ${err.message}</div>`;
        }
    }

    buildSidebarItem(cat, container, level) {
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
        label.textContent = this.shortName(cat.name);
        item.appendChild(label);
        const count = document.createElement('span');
        count.className = 'sb-count';
        count.textContent = cat.total_datasets || cat.dataset_count || '';
        item.appendChild(count);
        container.appendChild(item);

        const childWrap = document.createElement('div');
        childWrap.className = 'sb-children';
        container.appendChild(childWrap);
        if (!hasChildren) return;

        item.addEventListener('click', async () => {
            const isOpen = childWrap.classList.contains('open');
            childWrap.classList.toggle('open', !isOpen);
            item.querySelector('.sb-arrow')?.classList.toggle('open', !isOpen);
            if (!isOpen && childWrap.children.length === 0) {
                if (cat.children?.length) {
                    for (const sub of cat.children) {
                        this.buildSidebarItem(sub, childWrap, level + 1);
                    }
                } else {
                    await this.loadSidebarDatasets(cat.code, childWrap);
                }
                const code = new URLSearchParams(window.location.search).get('code');
                if (code) this.highlightSidebarDataset(code);
            }
        });
    }

    async loadSidebarDatasets(contextCode, container) {
        container.innerHTML = '<div class="sb-loading">Loading...</div>';
        try {
            const result = await API.getDatasets({ context: contextCode, limit: 200, lang: this.lang });
            container.innerHTML = '';
            for (const ds of result.datasets || []) {
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
                    window.location.href = this.dsHref(ds.matrix_code);
                });
                container.appendChild(dsItem);
            }
        } catch (_) {
            container.innerHTML = '<div class="sb-loading">Error</div>';
        }
    }

    highlightSidebarDataset(code) {
        for (const el of document.querySelectorAll('#sidebar-tree .sb-item.active')) {
            el.classList.remove('active');
        }
        const dsItem = document.querySelector(`#sidebar-tree .sb-item[data-ds-code="${code}"]`);
        if (!dsItem) return;
        dsItem.classList.add('active');
        let parent = dsItem.parentElement;
        while (parent && parent.id !== 'sidebar-tree') {
            if (parent.classList.contains('sb-children')) {
                parent.classList.add('open');
                parent.previousElementSibling?.querySelector('.sb-arrow')?.classList.add('open');
            }
            parent = parent.parentElement;
        }
        requestAnimationFrame(() => dsItem.scrollIntoView({ block: 'nearest', behavior: 'smooth' }));
    }

    filterSidebar(query) {
        for (const item of document.querySelectorAll('#sidebar-tree .sb-item[data-level="4"]')) {
            const match = !query || (item.textContent || '').toLowerCase().includes(query);
            item.style.display = match ? '' : 'none';
        }
        if (query) {
            for (const el of document.querySelectorAll('#sidebar-tree .sb-children')) {
                el.classList.add('open');
            }
            for (const el of document.querySelectorAll('#sidebar-tree .sb-arrow')) {
                el.classList.add('open');
            }
        }
    }
}

// Render now when the placeholder is already parsed (scripts sit at the end of body),
// so the page controllers find the bar's ids when they bind.
renderTopbar();
document.addEventListener('DOMContentLoaded', () => {
    renderTopbar();
    window.siteChrome = new SiteChrome();
    window.siteChrome.init();
});
