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
    return [...set].sort((a, b) => a - b);
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
