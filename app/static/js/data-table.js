/**
 * Data table component — sortable, paginated, filterable per column
 */
class DataTable {
    constructor(container, footerContainer) {
        this.container = container;
        this.footer = footerContainer;
        this.data = null;
        this.metadata = null;
        this.sortCol = -1;
        this.sortAsc = true;
        this.page = 0;
        this.pageSize = 50;
        this.colFilters = {};  // { colIndex: string }
    }

    update(data, metadata) {
        this.data = data;
        this.metadata = metadata;
        this.page = 0;
        this.sortCol = -1;
        this.colFilters = {};
        this.render();
    }

    _getFilteredRows(rows, columns, labels) {
        const active = Object.entries(this.colFilters).filter(([, v]) => v.trim());
        if (!active.length) return rows;
        return rows.filter(row => active.every(([idx, term]) => {
            const i = Number(idx);
            const col = columns[i];
            const raw = row[i];
            const text = col === 'value'
                ? String(raw ?? '')
                : resolveLabel(labels, col, raw).toLowerCase();
            return text.includes(term.trim().toLowerCase());
        }));
    }

    render() {
        if (!this.data || !this.data.rows.length) {
            this.container.innerHTML = '<div class="empty-state"><h3>No data</h3></div>';
            if (this.footer) this.footer.innerHTML = '';
            return;
        }

        const { columns, column_labels: labels, rows } = this.data;
        const dims = this.metadata?.dimensions || [];

        // Sort rows if needed
        let sortedRows = [...rows];
        if (this.sortCol >= 0) {
            sortedRows.sort((a, b) => {
                let va = a[this.sortCol], vb = b[this.sortCol];
                if (va === null) return 1;
                if (vb === null) return -1;
                if (typeof va === 'number') return this.sortAsc ? va - vb : vb - va;
                va = String(va); vb = String(vb);
                return this.sortAsc ? va.localeCompare(vb) : vb.localeCompare(va);
            });
        }

        // Apply column filters
        const filteredRows = this._getFilteredRows(sortedRows, columns, labels);

        // Paginate
        const totalPages = Math.ceil(filteredRows.length / this.pageSize);
        const pageRows = filteredRows.slice(this.page * this.pageSize, (this.page + 1) * this.pageSize);

        // Build table
        const table = document.createElement('table');

        // Header row
        const thead = table.createTHead();
        const headerRow = thead.insertRow();
        for (let i = 0; i < columns.length; i++) {
            const th = document.createElement('th');
            const col = columns[i];
            const dim = dims.find(d => d.dim_column_name === col);
            th.textContent = col === 'value' ? 'Value' : (dim?.dim_label || col);
            if (this.sortCol === i) {
                th.innerHTML += `<span class="sort-arrow">${this.sortAsc ? '▲' : '▼'}</span>`;
            }
            th.addEventListener('click', () => {
                if (this.sortCol === i) {
                    this.sortAsc = !this.sortAsc;
                } else {
                    this.sortCol = i;
                    this.sortAsc = true;
                }
                this.page = 0;
                this.render();
            });
            headerRow.appendChild(th);
        }

        // Filter row (skip value column)
        const filterRow = thead.insertRow();
        filterRow.className = 'filter-row';
        for (let i = 0; i < columns.length; i++) {
            const td = document.createElement('td');
            if (columns[i] !== 'value') {
                const input = document.createElement('input');
                input.type = 'text';
                input.placeholder = '🔍';
                input.className = 'col-filter-input';
                input.value = this.colFilters[i] || '';
                input.addEventListener('input', (e) => {
                    this.colFilters[i] = e.target.value;
                    this.page = 0;
                    this._rerenderBody(table, columns);
                });
                // Prevent sort when clicking filter input
                input.addEventListener('click', e => e.stopPropagation());
                td.appendChild(input);
            }
            filterRow.appendChild(td);
        }

        // Body
        const tbody = table.createTBody();
        this._fillBody(tbody, pageRows, columns, labels);

        this.container.innerHTML = '';
        this.container.appendChild(table);

        // Footer
        this._renderFooter(filteredRows.length, totalPages);
    }

    _fillBody(tbody, pageRows, columns, labels) {
        tbody.innerHTML = '';
        for (const row of pageRows) {
            const tr = tbody.insertRow();
            for (let i = 0; i < columns.length; i++) {
                const td = tr.insertCell();
                const col = columns[i];
                if (col === 'value') {
                    td.className = 'value-cell';
                    td.textContent = formatNumber(row[i]);
                } else {
                    td.textContent = resolveLabel(labels, col, row[i]);
                }
            }
        }
    }

    _rerenderBody(table, columns) {
        // Re-filter with current state (colFilters may have changed)
        const { column_labels: lbls, rows } = this.data;
        let sortedRows = [...rows];
        if (this.sortCol >= 0) {
            sortedRows.sort((a, b) => {
                let va = a[this.sortCol], vb = b[this.sortCol];
                if (va === null) return 1;
                if (vb === null) return -1;
                if (typeof va === 'number') return this.sortAsc ? va - vb : vb - va;
                va = String(va); vb = String(vb);
                return this.sortAsc ? va.localeCompare(vb) : vb.localeCompare(va);
            });
        }
        const newFiltered = this._getFilteredRows(sortedRows, columns, lbls);
        const totalPages = Math.ceil(newFiltered.length / this.pageSize);
        if (this.page >= totalPages) this.page = Math.max(0, totalPages - 1);
        const pageRows = newFiltered.slice(this.page * this.pageSize, (this.page + 1) * this.pageSize);
        this._fillBody(table.tBodies[0], pageRows, columns, lbls);
        this._renderFooter(newFiltered.length, totalPages);
    }

    _renderFooter(total, totalPages) {
        if (!this.footer) return;
        this.footer.innerHTML = '';
        this.footer.appendChild(
            el('span', {}, `${total} rows` +
                (this.data.truncated ? ' (truncated)' : ''))
        );

        if (totalPages > 1) {
            const pag = el('div', { className: 'pagination' });
            const prevBtn = el('button', { className: 'btn btn-sm' }, '←');
            prevBtn.disabled = this.page === 0;
            prevBtn.addEventListener('click', () => { this.page--; this.render(); });

            const nextBtn = el('button', { className: 'btn btn-sm' }, '→');
            nextBtn.disabled = this.page >= totalPages - 1;
            nextBtn.addEventListener('click', () => { this.page++; this.render(); });

            pag.appendChild(prevBtn);
            pag.appendChild(el('span', {}, ` ${this.page + 1} / ${totalPages} `));
            pag.appendChild(nextBtn);
            this.footer.appendChild(pag);
        }
    }

}
