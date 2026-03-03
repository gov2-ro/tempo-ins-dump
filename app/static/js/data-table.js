/**
 * Data table component — sortable, paginated
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
    }

    update(data, metadata) {
        this.data = data;
        this.metadata = metadata;
        this.page = 0;
        this.sortCol = -1;
        this.render();
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

        // Paginate
        const totalPages = Math.ceil(sortedRows.length / this.pageSize);
        const pageRows = sortedRows.slice(this.page * this.pageSize, (this.page + 1) * this.pageSize);

        // Build table
        const table = document.createElement('table');

        // Header
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
                this.render();
            });
            headerRow.appendChild(th);
        }

        // Body
        const tbody = table.createTBody();
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

        this.container.innerHTML = '';
        this.container.appendChild(table);

        // Footer
        if (this.footer) {
            this.footer.innerHTML = '';
            this.footer.appendChild(
                el('span', {}, `${sortedRows.length} rows` +
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
}
