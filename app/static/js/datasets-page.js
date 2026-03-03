/**
 * Datasets list page — category sidebar + searchable card grid
 */
class DatasetsPage {
    constructor() {
        this.currentContext = null;
        this.currentSearch = '';
        this.currentSort = 'updated';
        this.currentPage = 0;
        this.pageSize = 30;
        this.totalDatasets = 0;
        this._searchTimer = null;
    }

    async init() {
        // Load category tree
        this.loadCategories();

        // Check URL params
        const params = new URLSearchParams(window.location.search);
        this.currentContext = params.get('context');
        this.currentSearch = params.get('q') || '';

        if (this.currentSearch) {
            document.getElementById('search-input').value = this.currentSearch;
        }

        // Wire up search
        document.getElementById('search-input').addEventListener('input', (e) => {
            clearTimeout(this._searchTimer);
            this._searchTimer = setTimeout(() => {
                this.currentSearch = e.target.value.trim();
                this.currentPage = 0;
                this.loadDatasets();
                this.updateURL();
            }, 250);
        });

        // Wire up sort
        document.getElementById('sort-select').addEventListener('change', (e) => {
            this.currentSort = e.target.value;
            this.currentPage = 0;
            this.loadDatasets();
        });

        // Load datasets
        this.loadDatasets();
    }

    async loadCategories() {
        try {
            const data = await API.getCategories();
            const tree = document.getElementById('category-tree');
            tree.innerHTML = '';

            // "All" option
            const allItem = el('a', {
                className: `cat-item ${!this.currentContext ? 'active' : ''}`,
                'data-level': '2',
            }, 'All Datasets', el('span', { className: 'cat-count' }, ''));
            allItem.addEventListener('click', () => this.selectCategory(null));
            tree.appendChild(allItem);

            for (const root of data.tree) {
                // Root level = section header
                const rootEl = el('div', {
                    className: 'cat-item',
                    'data-level': '1',
                }, root.name);
                tree.appendChild(rootEl);

                // Children = clickable
                for (const child of root.children) {
                    const active = this.currentContext === child.code;
                    const item = el('a', {
                        className: `cat-item ${active ? 'active' : ''}`,
                        'data-level': '2',
                        'data-code': child.code,
                    },
                        child.name,
                        el('span', { className: 'cat-count' }, String(child.total_datasets))
                    );
                    item.addEventListener('click', () => this.selectCategory(child.code));
                    tree.appendChild(item);
                }
            }
        } catch (err) {
            console.error('Failed to load categories', err);
        }
    }

    selectCategory(code) {
        this.currentContext = code;
        this.currentPage = 0;

        // Update sidebar active state
        document.querySelectorAll('.cat-item').forEach(el => {
            el.classList.toggle('active',
                code ? el.dataset.code === code : !el.dataset.code && el.dataset.level === '2');
        });

        this.updateActiveFilters();
        this.loadDatasets();
        this.updateURL();
    }

    updateActiveFilters() {
        const container = document.getElementById('active-filters');
        container.innerHTML = '';

        if (this.currentContext) {
            const catItem = document.querySelector(`.cat-item[data-code="${this.currentContext}"]`);
            const name = catItem ? catItem.textContent.replace(/\d+$/, '').trim() : this.currentContext;
            const tag = el('span', { className: 'filter-tag' },
                `Category: ${name}`,
                el('span', { className: 'remove' }, '\u00d7')
            );
            tag.querySelector('.remove').addEventListener('click', () => this.selectCategory(null));
            container.appendChild(tag);
        }
    }

    async loadDatasets() {
        const grid = document.getElementById('datasets-grid');
        grid.innerHTML = '<div class="loading">Loading...</div>';

        try {
            const params = {
                limit: this.pageSize,
                offset: this.currentPage * this.pageSize,
                sort: this.currentSort,
            };
            if (this.currentSearch) params.q = this.currentSearch;
            if (this.currentContext) params.ancestor = this.currentContext;

            const qs = new URLSearchParams(params).toString();
            const resp = await fetch(`/api/datasets?${qs}`);
            const data = await resp.json();

            this.totalDatasets = data.total;
            document.getElementById('result-count').textContent = `${formatNumber(data.total, 0)} datasets`;

            grid.innerHTML = '';
            if (data.datasets.length === 0) {
                grid.innerHTML = '<div class="empty-state"><h3>No datasets found</h3><p>Try a different search or category.</p></div>';
                document.getElementById('pagination').innerHTML = '';
                return;
            }

            for (const ds of data.datasets) {
                grid.appendChild(this.renderCard(ds));
            }

            this.renderPagination();
            this.updateActiveFilters();

        } catch (err) {
            grid.innerHTML = `<div class="error-msg">Failed to load datasets: ${err.message}</div>`;
            console.error(err);
        }
    }

    renderCard(ds) {
        const card = el('a', {
            className: 'dataset-card',
            href: `/dataset.html?code=${ds.matrix_code}`,
        });

        card.appendChild(el('h4', {}, ds.matrix_name));

        const meta = el('div', { className: 'card-meta' });
        meta.appendChild(el('span', { className: 'badge badge-primary badge-sm' }, ds.archetype));
        if (ds.time_granularity) {
            meta.appendChild(el('span', { className: 'badge badge-muted badge-sm' }, ds.time_granularity));
        }
        if (ds.time_range) {
            meta.appendChild(el('span', { className: 'badge badge-muted badge-sm' }, ds.time_range));
        }
        if (ds.has_geo) {
            meta.appendChild(el('span', { className: 'badge badge-muted badge-sm' }, 'geo'));
        }
        card.appendChild(meta);

        const footer = el('div', { className: 'card-footer' });
        footer.appendChild(el('span', {}, `${formatNumber(ds.row_count, 0)} rows \u00b7 ${ds.dim_count} dims`));
        footer.appendChild(el('span', { className: 'card-code' }, ds.matrix_code));
        card.appendChild(footer);

        if (ds.ultima_actualizare) {
            footer.insertBefore(
                el('span', {}, `Updated ${ds.ultima_actualizare}`),
                footer.lastChild
            );
        }

        return card;
    }

    renderPagination() {
        const container = document.getElementById('pagination');
        const totalPages = Math.ceil(this.totalDatasets / this.pageSize);
        if (totalPages <= 1) {
            container.innerHTML = '';
            return;
        }

        container.innerHTML = '';

        const prev = el('button', { ...(this.currentPage === 0 ? { disabled: true } : {}) }, '\u2190 Previous');
        prev.addEventListener('click', () => {
            this.currentPage--;
            this.loadDatasets();
            window.scrollTo(0, 0);
        });
        container.appendChild(prev);

        container.appendChild(el('span', { className: 'page-info' },
            `Page ${this.currentPage + 1} of ${totalPages}`));

        const next = el('button', { ...(this.currentPage >= totalPages - 1 ? { disabled: true } : {}) }, 'Next \u2192');
        next.addEventListener('click', () => {
            this.currentPage++;
            this.loadDatasets();
            window.scrollTo(0, 0);
        });
        container.appendChild(next);
    }

    updateURL() {
        const params = new URLSearchParams();
        if (this.currentContext) params.set('context', this.currentContext);
        if (this.currentSearch) params.set('q', this.currentSearch);
        const qs = params.toString();
        history.replaceState(null, '', qs ? `?${qs}` : '/datasets.html');
    }
}

document.addEventListener('DOMContentLoaded', () => {
    new DatasetsPage().init();
});
