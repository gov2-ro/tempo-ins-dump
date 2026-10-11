// Browser port of app/services/data_query.run_query over a static build.
// Same validation messages, aggregation decision (policy.js), time window,
// grain gate, filtering/grouping/ordering, truncation and response envelope.
// Python is the specification; tools/static-engine/parity.mjs replays recorded
// answers against this file.

import { decideGrouped, sourceTotalGate, pyStr } from './policy.js';

export const MISSING = undefined;          // an absent JSON parameter

export class QueryError extends Error {
    constructor(status, message) { super(message); this.status = status; }
}

const MAX_FILTER_VALUES = 10000;

/** Python repr() of a str (for validation messages). */
function pyRepr(s) {
    s = String(s);
    const q = (s.includes("'") && !s.includes('"')) ? '"' : "'";
    let out = '';
    for (const ch of s) {
        const c = ch.codePointAt(0);
        if (ch === '\\') out += '\\\\';
        else if (ch === q) out += '\\' + q;
        else if (ch === '\n') out += '\\n';
        else if (ch === '\r') out += '\\r';
        else if (ch === '\t') out += '\\t';
        else if (c < 0x20 || c === 0x7f) out += '\\x' + c.toString(16).padStart(2, '0');
        else out += ch;
    }
    return q + out + q;
}

const isScalar = v => typeof v === 'string' || (typeof v === 'number' && Number.isFinite(v));
const isObject = v => v !== null && typeof v === 'object' && !Array.isArray(v);
const fmtInt = n => Math.trunc(n).toLocaleString('en-US');

function validateFilters(data, allowed) {
    if (data === MISSING) return {};
    if (!isObject(data)) throw new QueryError(400, 'Invalid filters: expected a JSON object {column: [values]}');
    let total = 0;
    const out = {};
    for (const [col, vals] of Object.entries(data)) {
        if (!allowed.has(col)) throw new QueryError(400, `Invalid filters: unknown column ${pyRepr(col)}`);
        if (!Array.isArray(vals)) throw new QueryError(400, `Invalid filters: values for ${pyRepr(col)} must be an array`);
        if (!vals.every(isScalar)) throw new QueryError(400, `Invalid filters: values for ${pyRepr(col)} must be strings or numbers`);
        total += vals.length;
        if (total > MAX_FILTER_VALUES) throw new QueryError(400, 'Invalid filters: too many values');
        out[col] = vals;
    }
    return out;
}

function validateGroupBy(data, allowed) {
    if (data === MISSING) return null;
    if (!Array.isArray(data) || !data.every(c => typeof c === 'string')) {
        throw new QueryError(400, 'Invalid group_by: expected a JSON array of column names');
    }
    for (const c of data) if (!allowed.has(c)) throw new QueryError(400, `Invalid group_by: unknown column ${pyRepr(c)}`);
    return data.length ? data : null;
}

// DuckDB VARCHAR order is byte order; for BMP strings that equals UTF-16 code
// unit order, which is what < compares. NULLs sort last (ASC and DESC).
function cmp(a, b) {
    if (a === b) return 0;
    if (a === null) return 1;
    if (b === null) return -1;
    return a < b ? -1 : 1;
}

// Numbers or strings, NULLs last (used for the value tie-break)
function cmpAny(a, b) {
    if (a === b) return 0;
    if (a === null) return 1;
    if (b === null) return -1;
    return a < b ? -1 : 1;
}

// DESC with NULLs still last (DuckDB default_null_order = nulls_last)
function cmpDesc(a, b) {
    if (a === b) return 0;
    if (a === null) return 1;
    if (b === null) return -1;
    return a < b ? 1 : -1;
}

function rowsPerPeriod(dimensions, groupBy, filters, timeDim, rowCount, nPeriods) {
    if (!groupBy || !groupBy.length) return rowCount / Math.max(nPeriods, 1);
    const declared = {};
    for (const d of dimensions) declared[d.dim_column_name] = Math.max(declared[d.dim_column_name] || 1, d.option_count || 1);
    let cells = 1;
    for (const col of groupBy) {
        if (col === timeDim) continue;
        const picked = filters[col];
        const n = (picked && picked.length) ? picked.length : (declared[col] || 1);
        cells *= Math.max(n, 1);
    }
    return cells;
}

const val = (table, r) => { const v = table.values[r]; return Number.isNaN(v) ? null : v; };

/** Row indices passing CAST(col AS VARCHAR) IN (...) on non-NULL values;
 *  empty value lists and columns outside `fileCols` are ignored. */
function sliceRows(table, filters, fileCols) {
    const conds = [];
    for (const [col, values] of Object.entries(filters)) {
        if (!fileCols.has(col) || !values || !values.length) continue;
        const safe = new Set(values.filter(v => v !== null && v !== undefined).map(pyStr));
        if (!safe.size) continue;
        const codes = table.codes[col];
        if (!codes) return new Uint32Array(0);      // column absent -> NULL -> no match
        const ok = new Uint8Array((table.dicts[col] || []).length + 1);
        table.dicts[col].forEach((v, i) => { if (safe.has(v)) ok[i] = 1; });
        conds.push([codes, ok]);
    }
    const out = new Uint32Array(table.rows);
    let n = 0;
    outer: for (let r = 0; r < table.rows; r++) {
        for (let j = 0; j < conds.length; j++) {
            const k = conds[j][0][r];
            if (k === -1 || !conds[j][1][k]) continue outer;
        }
        out[n++] = r;
    }
    return out.subarray(0, n);
}

/** Map key for a tuple of dictionary codes: numeric when it fits, else string. */
function keyer(table, cols) {
    const sizes = cols.map(c => (table.dicts[c] || []).length + 1);
    const total = sizes.reduce((a, b) => a * b, 1);
    const codes = cols.map(c => table.codes[c]);
    if (total < Number.MAX_SAFE_INTEGER) {
        return r => {
            let k = 0;
            for (let j = 0; j < codes.length; j++) k = k * sizes[j] + (codes[j] ? codes[j][r] + 1 : 0);
            return k;
        };
    }
    return r => codes.map(cs => (cs ? cs[r] : -1)).join(',');
}

function grainCheck(policy, table, filters, rowCount, precheckOnly = false) {
    const fs = policy.grain_file_status;
    const out = { generation: fs.generation, file_status: fs.status };
    if (fs.status === 'unique') return { ...out, ok: true, reason: null, evidence: 'generation_audit' };
    const active = {};
    for (const [c, vs] of Object.entries(filters)) if (vs && vs.length) active[c] = vs;
    if (!Object.keys(active).length && (rowCount || 0) > policy.grain_check_max_rows) {
        return { ...out, ok: false, reason: 'grain_unverified', evidence: 'slice_too_large_to_check' };
    }
    if (precheckOnly) return null;
    const dims = table.columns.filter(c => c !== 'OBS_VALUE');
    const keep = sliceRows(table, active, new Set(dims));
    const key = keyer(table, dims);
    const groups = new Map();
    for (const r of keep) {
        const k = key(r);
        let g = groups.get(k);
        if (!g) groups.set(k, g = { n: 0, v: null, multi: false });
        g.n++;
        const v = val(table, r);
        if (v !== null) {
            if (g.v === null) g.v = v; else if (g.v !== v) g.multi = true;
        }
    }
    let dup = 0, conf = 0;
    for (const g of groups.values()) if (g.n > 1) { dup++; if (g.multi) conf++; }
    const res = conf ? { ...out, ok: false, reason: 'conflicting_grain' }
        : dup ? { ...out, ok: false, reason: 'duplicate_keys' } : { ...out, ok: true, reason: null };
    return { ...res, evidence: 'slice_check', duplicate_keys: dup, conflicting_keys: conf };
}

function envelope(policy, grain) {
    const quality = { grain: policy.grain_file_status };
    if (grain) {
        quality.slice = {};
        for (const k of ['ok', 'reason', 'evidence', 'duplicate_keys', 'conflicting_keys']) {
            quality.slice[k] = grain[k] === undefined ? null : grain[k];
        }
    }
    return { contract: policy.contract, generation: policy.generation, quality };
}

function unavailable(policy, columns, rowCount, aggregation, grain = null) {
    return { columns: [...columns, 'OBS_VALUE'], column_labels: {}, rows: [], total_rows: rowCount,
             returned_rows: 0, truncated: false, unavailable: true, aggregation,
             ...envelope(policy, grain) };
}

/**
 * run_query(code, filters, group_by, limit, approximate).
 * `loader` provides: build() -> build.json, policy(code) -> policy JSON|null,
 * table(code, filters) -> {table, distinct} (whole file or the partitions the
 * filters need; `distinct` = {col: [values]} over the whole file).
 */
export async function runQuery(loader, code, filters = MISSING, groupBy = MISSING,
                               limit, approximate = false) {
    const build = await loader.build();
    const MAX = build.max_data_rows, LARGE = build.large_dataset_threshold;
    if (limit === undefined) limit = MAX;
    if (typeof limit !== 'number' || !Number.isInteger(limit) || limit < 1 || limit > MAX) {
        throw new QueryError(400, `Invalid limit: must be an integer in 1..${MAX}`);
    }
    const policy = await loader.policy(code);
    if (!policy) throw new QueryError(404, `Dataset ${code} not found`);
    const rowCount = policy.row_count;
    const allowed = new Set(policy.allowed);
    const rename = c => policy.rename[c] ?? c;

    let filterDict = validateFilters(filters, allowed);
    let groupCols = validateGroupBy(groupBy, allowed);
    const requested = new Set(Object.entries(filterDict).filter(([, v]) => v && v.length).map(([c]) => rename(c)));

    let aggregation = null;
    let aggFunc = 'SUM';
    if (groupCols) {
        const ctx = policy.context;
        if (ctx) {
            const sdGroup = groupCols.map(rename);
            const sdFilters = {};
            for (const [k, v] of Object.entries(filterDict)) sdFilters[rename(k)] = v;
            const dec = decideGrouped(ctx, sdGroup, sdFilters, approximate);
            aggregation = dec;
            const timeCols = new Set(ctx.dimensions.filter(d => d.dim_type === 'time').map(d => d.dim_column_name));
            const available = dec.outcome !== 'unavailable';
            if (available && !Object.keys(sdFilters).length && sdGroup.length === 1 && timeCols.has(sdGroup[0])) {
                const reason = sourceTotalGate(policy, dec);
                if (reason) {
                    aggregation = { ...dec, outcome: 'unavailable', reason };
                    return unavailable(policy, sdGroup, rowCount, aggregation);
                }
            }
            if (!available) return unavailable(policy, sdGroup, rowCount, aggregation);
            groupCols = sdGroup;
            filterDict = {};
            for (const [k, v] of Object.entries(dec.filters)) filterDict[k] = [...v];
            aggFunc = dec.agg_func || 'SUM';
        } else {
            aggregation = { outcome: 'unavailable', reason: 'no_aggregation_context',
                            blocking_dimension: null, method: 'none' };
            return unavailable(policy, groupCols.map(rename), rowCount, aggregation);
        }
    }
    // adapt_to_parquet (canonical files: only *_nom_id names are renamed)
    const dimensions = policy.file_dimensions;
    if (groupCols) groupCols = groupCols.map(rename);
    { const f = {}; for (const [k, v] of Object.entries(filterDict)) f[rename(k)] = v; filterDict = f; }

    const timeCol = policy.time_col;
    let timeWindowed = false;
    if (rowCount > MAX && timeCol && !(timeCol in filterDict)) {
        const meta = await loader.meta(code);
        const timeVals = [...(meta.distinct[timeCol] || [])].sort((a, b) => cmp(b, a));
        if (meta.hasNullTime) timeVals.push(null);
        if (timeVals.length) {
            const n = timeVals.length;
            const rpp = rowsPerPeriod(dimensions, groupCols, filterDict, timeCol, rowCount, n);
            const minPeriods = rowCount > 5_000_000 ? 2 : 5;
            let safe = Math.max(minPeriods, Math.trunc(MAX / Math.max(rpp, 1)));
            safe = Math.min(safe, n);
            if (safe < n) {
                filterDict[timeCol] = timeVals.slice(0, safe);
                timeWindowed = true;
            }
        }
    }
    if (rowCount > LARGE && !Object.keys(filterDict).length && !groupCols && !timeWindowed) {
        throw new QueryError(400, `Dataset has ${fmtInt(rowCount)} rows. Please apply at least one filter `
            + `to narrow results (max ${fmtInt(MAX)} rows returned).`);
    }
    // A refusal that needs no rows is decided before anything is downloaded.
    let grain = null;
    if (groupCols) {
        const empty = { columns: [], dicts: {}, codes: {}, values: new Float64Array(0), rows: 0 };
        const pre = grainCheck(policy, empty, filterDict, rowCount, true);
        if (pre && !pre.ok) {
            aggregation = { ...(aggregation || {}), outcome: 'unavailable', reason: pre.reason,
                            blocking_dimension: null, method: 'none' };
            return unavailable(policy, groupCols, rowCount, aggregation, pre);
        }
    }
    const data = await loader.table(code, filterDict);
    const table = data.table;

    if (groupCols) {
        grain = grainCheck(policy, table, filterDict, rowCount);
        if (!grain.ok) {
            aggregation = { ...(aggregation || {}), outcome: 'unavailable', reason: grain.reason,
                            blocking_dimension: null, method: 'none' };
            return unavailable(policy, groupCols, rowCount, aggregation, grain);
        }
    }

    // ---- execute (query_builder._build_sql) ----
    const allDimCols = dimensions.map(d => d.dim_column_name);
    const validCols = new Set(allDimCols);
    const keep = sliceRows(table, filterDict, validCols);
    let outputCols, rows;
    // per-column rank of each dictionary value (DuckDB VARCHAR order)
    const rankOf = c => {
        const d = table.dicts[c] || [];
        const order = d.map((_, i) => i).sort((i, j) => cmp(d[i], d[j]));
        const rank = new Int32Array(d.length);
        order.forEach((i, pos) => { rank[i] = pos; });
        return rank;
    };
    if (groupCols) {
        let keepCols = groupCols.filter(c => validCols.has(c));
        if (!keepCols.length) keepCols = allDimCols;
        outputCols = keepCols;
        const codeCols = keepCols.map(c => table.codes[c]);
        const key = keyer(table, keepCols);
        const groups = new Map();
        for (const r of keep) {
            let isNull = false;
            for (const cs of codeCols) if (!cs || cs[r] === -1) { isNull = true; break; }
            if (isNull) continue;                 // grouped: WHERE col IS NOT NULL
            const k = key(r);
            let g = groups.get(k);
            if (!g) groups.set(k, g = { r, sum: 0, n: 0 });
            const v = val(table, r);
            if (v !== null) { g.sum += v; g.n++; }
        }
        rows = [];
        for (const g of groups.values()) {
            const row = codeCols.map((cs, j) => table.dicts[keepCols[j]][cs[g.r]]);
            row.push(g.n ? (aggFunc === 'AVG' ? g.sum / g.n : g.sum) : null);
            rows.push(row);
        }
        const n = outputCols.length;
        const lim = limit + 1;
        const ti = timeCol ? outputCols.indexOf(timeCol) : -1;
        const rest = [...Array(n + 1).keys()].filter(j => j !== ti);   // + value tie-break
        const byRest = (a, b) => { for (const j of rest) { const c = cmpAny(a[j], b[j]); if (c) return c; } return 0; };
        if (ti === -1) {
            rows.sort(byRest);
            rows = rows.slice(0, lim);
        } else {
            rows.sort((a, b) => cmpDesc(a[ti], b[ti]) || byRest(a, b));
            rows = rows.slice(0, lim);
            rows.sort((a, b) => cmp(a[ti], b[ti]) || byRest(a, b));
        }
    } else {
        outputCols = allDimCols;
        const ranks = outputCols.map(c => (table.codes[c] ? rankOf(c) : null));
        const codeCols = outputCols.map(c => table.codes[c]);
        const r2k = (j, r) => { const cs = codeCols[j]; const k = cs ? cs[r] : -1; return k === -1 ? Infinity : ranks[j][k]; };
        const ti = timeCol ? outputCols.indexOf(timeCol) : -1;
        const rest = [...outputCols.keys()].filter(j => j !== ti);
        const byRest = (a, b) => {
            for (const j of rest) { const d = r2k(j, a) - r2k(j, b); if (d) return d > 0 ? 1 : -1; }
            return cmpAny(val(table, a), val(table, b));
        };
        const idx = Array.from(keep);
        const lim = limit + 1;
        let sel;
        if (ti === -1) {
            idx.sort(byRest);
            sel = idx.slice(0, lim);
        } else {
            const tdesc = (a, b) => { const x = r2k(ti, a), y = r2k(ti, b);
                if (x === y) return 0; if (x === Infinity) return 1; if (y === Infinity) return -1; return y - x; };
            idx.sort((a, b) => tdesc(a, b) || byRest(a, b));
            sel = idx.slice(0, lim);
            sel.sort((a, b) => { const d = r2k(ti, a) - r2k(ti, b); return (d ? (d > 0 ? 1 : -1) : 0) || byRest(a, b); });
        }
        rows = sel.map(r => [...codeCols.map((cs, j) => (cs && cs[r] !== -1 ? table.dicts[outputCols[j]][cs[r]] : null)), val(table, r)]);
    }
    const truncated = rows.length > limit;
    rows = rows.slice(0, limit);

    let resultDims;
    if (groupCols) {
        const byCol = {};
        for (const d of dimensions) byCol[d.dim_column_name] = d;
        resultDims = groupCols.filter(c => byCol[c]).map(c => byCol[c]);
        if (!resultDims.length) resultDims = dimensions;
    } else {
        resultDims = dimensions;
    }

    let partialPeriod = null;
    if (truncated && timeCol) {
        const tidx = resultDims.findIndex(d => d.dim_column_name === timeCol);
        if (tidx !== -1) {
            const periods = new Set(rows.map(r => r[tidx]).filter(v => v !== null));
            if (periods.size > 1) {
                partialPeriod = [...periods].sort(cmp)[0];
                rows = rows.filter(r => r[tidx] !== partialPeriod);
            }
        }
    }

    const columnLabels = {};
    resultDims.forEach((dim, i) => {
        const values = new Set(rows.map(r => r[i]).filter(v => v !== null));
        if (!values.size) return;
        const m = {};
        for (const v of values) m[String(v)] = String(v);
        columnLabels[dim.dim_column_name] = m;
    });
    const columns = [...resultDims.map(d => d.dim_column_name), 'OBS_VALUE'];
    const resp = { columns, column_labels: columnLabels, rows, total_rows: rowCount,
                   returned_rows: rows.length, truncated, aggregation, ...envelope(policy, grain) };
    if (timeWindowed) resp.time_windowed = true;
    if (partialPeriod !== null) resp.partial_period_dropped = String(partialPeriod);
    if (!rows.length && requested.size && !resp.unavailable) {
        const missing = {};
        for (const [col, vals] of Object.entries(filterDict)) {
            if (!requested.has(col) || !vals || !vals.length) continue;
            const present = new Set(data.distinct[col] || []);
            const miss = vals.map(pyStr).filter(v => !present.has(v));
            if (miss.length) missing[col] = miss;
        }
        resp.selection = { empty: true, missing_values: missing };
    }
    return resp;
}
