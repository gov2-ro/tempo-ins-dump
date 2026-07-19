/**
 * Shared site chrome for standalone pages (dataset-v2, compare): topbar,
 * search overlay, quick-nav sidebar, theme & language toggles.
 *
 * Mirrors the explore-app chrome — same element ids and explore.css classes,
 * so the two look identical. Dataset links land on dashboard-v2 (the
 * canonical dataset page). Theme changes dispatch a `themechange` event on
 * window so page controllers can re-render their ECharts instances.
 */

const CHROME_UI = {
    ro: {
        searchTrigger: 'Caută seturi de date...',
        searchPlaceholder: 'Caută seturi de date, indicatori, coduri...',
        searchEmpty: 'Tastează pentru a căuta în toate seturile de date',
        searchNoResults: 'Niciun rezultat',
        searchError: 'Eroare la căutare',
        sidebarTitle: 'Navighează',
        sidebarFilter: 'Filtrează seturile...',
    },
    en: {
        searchTrigger: 'Search datasets...',
        searchPlaceholder: 'Search datasets, indicators, codes...',
        searchEmpty: 'Type to search across all datasets',
        searchNoResults: 'No results',
        searchError: 'Search error',
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
        this.searchIdx = -1;
        this.categories = null;
        this._sidebarLoaded = false;
    }

    dsHref(code) {
        return `/dataset-v2.html?code=${code}${this.lang !== 'ro' ? `&lang=${this.lang}` : ''}`;
    }

    init() {
        this.applyLang();
        this.syncThemeIcons();
        this.bindTopbar();
        this.bindSearch();
        this.initSidebar();
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
        const flag = document.getElementById('lang-flag');
        if (flag) flag.remove();  // standalone pages skip the flag asset
    }

    // ------------------------------------------------------------ theme/lang

    syncThemeIcons() {
        const theme = document.body.dataset.theme || 'dark';
        document.getElementById('theme-icon-sun')?.classList.toggle('hidden', theme !== 'dark');
        document.getElementById('theme-icon-moon')?.classList.toggle('hidden', theme === 'dark');
    }

    bindTopbar() {
        document.getElementById('theme-toggle')?.addEventListener('click', () => {
            const next = (document.body.dataset.theme === 'light') ? 'dark' : 'light';
            document.documentElement.dataset.theme = next;
            document.body.dataset.theme = next;
            localStorage.setItem('lens_theme', next);
            this.syncThemeIcons();
            window.dispatchEvent(new CustomEvent('themechange'));
        });
        document.getElementById('lang-toggle')?.addEventListener('click', () => {
            const next = this.lang === 'ro' ? 'en' : 'ro';
            localStorage.setItem('lens_lang', next);
            const url = new URL(window.location);
            url.searchParams.set('lang', next);
            window.location.href = url.toString();
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
        try {
            const resp = await API.getDatasets({ q: query, limit: 12, lang: this.lang });
            results.innerHTML = '';
            this.searchIdx = -1;
            if (!resp.datasets.length) {
                results.innerHTML = `<div class="search-empty">${this.ui.searchNoResults}</div>`;
                return;
            }
            for (const ds of resp.datasets) {
                const item = document.createElement('div');
                item.className = 'search-item';
                item.addEventListener('click', () => {
                    window.location.href = this.dsHref(ds.matrix_code);
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
        document.body.classList.add('sidebar-open');
        sessionStorage.setItem('lensNavOpen', '1');
        if (!this._sidebarLoaded) this.renderSidebar();
        requestAnimationFrame(() => window.dispatchEvent(new Event('resize')));
    }

    closeSidebar() {
        document.getElementById('lens-sidebar').classList.add('hidden');
        document.getElementById('sidebar-toggle').classList.remove('active');
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

document.addEventListener('DOMContentLoaded', () => {
    window.siteChrome = new SiteChrome();
    window.siteChrome.init();
});
