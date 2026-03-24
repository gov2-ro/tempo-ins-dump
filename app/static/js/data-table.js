function isValueCol(col) { return col === 'value' || col === 'OBS_VALUE'; }

/**
 * Data table component — sortable, paginated, filterable per column (multiselect)
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
        this.colFilters = {};  // { colIndex: Set<string> }  empty set = show all
        this._openDropdown = null;
        this._closeHandler = (e) => {
            if (this._openDropdown && !this._openDropdown.contains(e.target)) {
                this._openDropdown.querySelector('.multiselect-dropdown').style.display = 'none';
                this._openDropdown = null;
            }
        };
        document.addEventListener('click', this._closeHandler);
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
        const active = Object.entries(this.colFilters).filter(([, s]) => s.size > 0);
        if (!active.length) return rows;
        return rows.filter(row => active.every(([idx, selectedSet]) => {
            const i = Number(idx);
            const col = columns[i];
            const raw = row[i];
            const text = isValueCol(col)
                ? String(raw ?? '')
                : resolveLabel(labels, col, raw);
            return selectedSet.has(text);
        }));
    }

    _buildSelectOptions(colIdx, columns, labels) {
        const col = columns[colIdx];
        const vals = [...new Set(this.data.rows.map(r => {
            const raw = r[colIdx];
            return isValueCol(col) ? String(raw ?? '') : resolveLabel(labels, col, raw);
        }))].sort((a, b) => a.localeCompare(b, undefined, { numeric: true }));
        return vals;
    }

    _createMultiselect(colIdx, columns, labels, table) {
        const opts = this._buildSelectOptions(colIdx, columns, labels);
        const selected = this.colFilters[colIdx] || new Set();

        const wrapper = document.createElement('div');
        wrapper.className = 'multiselect-wrapper';

        // Toggle button
        const btn = document.createElement('button');
        btn.className = 'multiselect-btn';
        btn.textContent = selected.size === 0 ? 'All' : `${selected.size} sel.`;
        if (selected.size > 0) btn.classList.add('has-filter');
        btn.addEventListener('click', (e) => {
            e.stopPropagation();
            const dd = wrapper.querySelector('.multiselect-dropdown');
            const isOpen = dd.style.display === 'block';
            // Close any other open dropdown
            if (this._openDropdown && this._openDropdown !== wrapper) {
                this._openDropdown.querySelector('.multiselect-dropdown').style.display = 'none';
            }
            dd.style.display = isOpen ? 'none' : 'block';
            this._openDropdown = isOpen ? null : wrapper;
        });
        wrapper.appendChild(btn);

        // Dropdown panel
        const dd = document.createElement('div');
        dd.className = 'multiselect-dropdown';
        dd.style.display = 'none';
        dd.addEventListener('click', e => e.stopPropagation());

        // "All" option
        const allLabel = document.createElement('label');
        allLabel.className = 'multiselect-option';
        const allCb = document.createElement('input');
        allCb.type = 'checkbox';
        allCb.checked = selected.size === 0;
        allCb.addEventListener('change', () => {
            this.colFilters[colIdx] = new Set();
            this.page = 0;
            this._rerenderBody(table, columns);
            // Update button text
            btn.textContent = 'All';
            btn.classList.remove('has-filter');
            // Uncheck all individual checkboxes
            dd.querySelectorAll('.multiselect-item-cb').forEach(cb => cb.checked = false);
            allCb.checked = true;
        });
        allLabel.appendChild(allCb);
        allLabel.appendChild(document.createTextNode(' All'));
        dd.appendChild(allLabel);

        // Individual options
        for (const val of opts) {
            const label = document.createElement('label');
            label.className = 'multiselect-option';
            const cb = document.createElement('input');
            cb.type = 'checkbox';
            cb.className = 'multiselect-item-cb';
            cb.checked = selected.has(val);
            cb.addEventListener('change', () => {
                if (!this.colFilters[colIdx]) this.colFilters[colIdx] = new Set();
                if (cb.checked) {
                    this.colFilters[colIdx].add(val);
                } else {
                    this.colFilters[colIdx].delete(val);
                }
                const sz = this.colFilters[colIdx].size;
                btn.textContent = sz === 0 ? 'All' : `${sz} sel.`;
                btn.classList.toggle('has-filter', sz > 0);
                allCb.checked = sz === 0;
                this.page = 0;
                this._rerenderBody(table, columns);
            });
            label.appendChild(cb);
            label.appendChild(document.createTextNode(' ' + val));
            dd.appendChild(label);
        }

        wrapper.appendChild(dd);
        return wrapper;
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
            th.textContent = isValueCol(col) ? 'Value' : (dim?.dim_label || col);
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

        // Filter row — multiselect dropdowns per column (skip value column)
        const filterRow = thead.insertRow();
        filterRow.className = 'filter-row';
        for (let i = 0; i < columns.length; i++) {
            const td = document.createElement('td');
            if (!isValueCol(columns[i])) {
                td.appendChild(this._createMultiselect(i, columns, labels, table));
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
                if (isValueCol(col)) {
                    td.className = 'value-cell';
                    td.textContent = formatNumber(row[i]);
                } else {
                    td.textContent = resolveLabel(labels, col, row[i]);
                }
            }
        }
    }

    _rerenderBody(table, columns) {
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
