/**
 * Table renderer — renders an HTML table into the container div.
 * Returns a fake chart instance with .dispose() and .resize() noops.
 */
function createTableChart(container, slots, data, metadata) {
    // Clear any previous content
    container.innerHTML = '';

    const cols     = data.columns;
    const labels   = data.column_labels;
    const rows     = data.rows;
    const valueIdx = cols.length - 1;

    // Build header labels
    const headerLabels = cols.map((col, i) => {
        if (i === valueIdx) return 'Valoare';
        const dimMeta = (metadata.dimensions || []).find(d => d.dim_column_name === col);
        return dimMeta?.dim_label || col;
    });

    // Sort rows by first dim
    const sorted = [...rows].sort((a, b) => {
        for (let i = 0; i < valueIdx; i++) {
            if (a[i] < b[i]) return -1;
            if (a[i] > b[i]) return 1;
        }
        return 0;
    });

    // Limit to 500 rows for display
    const displayRows = sorted.slice(0, 500);
    const truncated   = rows.length > 500;

    const wrapper = document.createElement('div');
    wrapper.style.cssText = 'overflow:auto;height:100%;font-size:12px;padding:8px';

    if (truncated) {
        const note = document.createElement('div');
        note.style.cssText = 'color:#9b8e82;margin-bottom:6px;font-size:11px';
        note.textContent = `Afișate primele 500 din ${formatNumber(rows.length)} rânduri`;
        wrapper.appendChild(note);
    }

    const table = document.createElement('table');
    table.style.cssText = 'border-collapse:collapse;width:100%;white-space:nowrap';

    // Header
    const thead = table.createTHead();
    const hrow  = thead.insertRow();
    for (const lbl of headerLabels) {
        const th = document.createElement('th');
        th.textContent = lbl;
        th.style.cssText = 'padding:4px 8px;border-bottom:2px solid #e8e0d8;text-align:left;background:#f5f0eb;position:sticky;top:0;font-size:11px;font-weight:600;color:#6b5e54';
        hrow.appendChild(th);
    }

    // Body
    const tbody = table.createTBody();
    for (const row of displayRows) {
        const tr = tbody.insertRow();
        row.forEach((cell, i) => {
            const td = tr.insertCell();
            if (i === valueIdx) {
                td.textContent = cell !== null ? formatNumber(cell) : '—';
                td.style.cssText = 'padding:3px 8px;border-bottom:1px solid #f0ebe5;text-align:right;font-variant-numeric:tabular-nums';
            } else {
                const dimCol = cols[i];
                const lbl    = labels[dimCol]?.[String(cell)] ?? String(cell ?? '—');
                td.textContent = lbl;
                td.style.cssText = 'padding:3px 8px;border-bottom:1px solid #f0ebe5;color:#2d2926;max-width:200px;overflow:hidden;text-overflow:ellipsis';
            }
        });
    }

    wrapper.appendChild(table);
    container.appendChild(wrapper);

    // Return fake chart instance
    return {
        dispose() { container.innerHTML = ''; },
        resize() {},
    };
}
