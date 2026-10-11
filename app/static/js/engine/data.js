// Static data access for the browser engine: build.json, per-dataset policy and
// TCOL1 binary tables (scripts/build-static.py `tcol`), whole or the partitions
// a query needs. The same code runs in Node for the parity harness; only the
// two fetch functions differ.

const MAGIC = 'TCOL1\n';
const INT_NULL = -2147483648;

/** Decode an (already decompressed) TCOL1 buffer into a columnar table. */
export function decodeTcol(buf) {
    const bytes = buf instanceof Uint8Array ? buf : new Uint8Array(buf);
    const ab = bytes.buffer.slice(bytes.byteOffset, bytes.byteOffset + bytes.byteLength);
    const magic = new TextDecoder().decode(bytes.subarray(0, 6));
    if (magic !== MAGIC) throw new Error('not a TCOL1 table');
    const hlen = new DataView(ab).getUint32(6, true);
    const header = JSON.parse(new TextDecoder().decode(bytes.subarray(10, 10 + hlen)));
    let off = 10 + hlen;
    off += (8 - (off % 8)) % 8;
    const n = header.rows;
    const codes = {};
    for (const c of header.columns) {
        if (c === 'OBS_VALUE') continue;
        const t = header.code_types[c];
        const arr = t === 'i16' ? new Int16Array(ab, off, n) : new Int32Array(ab, off, n);
        codes[c] = arr;
        off += arr.byteLength;
        off += (8 - (off % 8)) % 8;
    }
    let values;
    if (header.value_type === 'i32') {
        const raw = new Int32Array(ab, off, n);
        values = new Float64Array(n);
        for (let i = 0; i < n; i++) values[i] = raw[i] === INT_NULL ? NaN : raw[i];
    } else {
        values = new Float64Array(ab, off, n);
    }
    return { columns: header.columns, dicts: header.dicts, codes, values, rows: n };
}

/** Concatenate tables that may use different dictionaries. */
export function mergeTables(tables) {
    if (tables.length === 1) return tables[0];
    const columns = tables[0].columns;
    const dims = columns.filter(c => c !== 'OBS_VALUE');
    const rows = tables.reduce((s, t) => s + t.rows, 0);
    const dicts = {}, codes = {};
    for (const c of dims) {
        dicts[c] = [];
        const index = new Map();
        const dst = new Int32Array(rows);
        let o = 0;
        for (const t of tables) {
            const remap = (t.dicts[c] || []).map(v => {
                let k = index.get(v);
                if (k === undefined) { k = dicts[c].length; dicts[c].push(v); index.set(v, k); }
                return k;
            });
            const src = t.codes[c];
            for (let r = 0; r < t.rows; r++) dst[o++] = src ? (src[r] === -1 ? -1 : remap[src[r]]) : -1;
        }
        codes[c] = dst;
    }
    const values = new Float64Array(rows);
    let o = 0;
    for (const t of tables) { values.set(t.values, o); o += t.rows; }
    return { columns, dicts, codes, values, rows };
}

const emptyTable = columns => ({ columns: [...columns, 'OBS_VALUE'], dicts: {}, codes: {},
                                 values: new Float64Array(0), rows: 0 });

/**
 * makeLoader({json, binary}) -> loader for runQuery. json(path) resolves to the
 * parsed JSON of a build-relative path (.json or .json.gz) or null when absent;
 * binary(path) to the decompressed bytes (Uint8Array/ArrayBuffer) of a .bin.gz file.
 */
export function makeLoader({ json, binary, maxTables = 48 }) {
    const cache = new Map();
    const memo = (key, fn) => { if (!cache.has(key)) cache.set(key, fn()); return cache.get(key); };
    // decoded tables are the memory cost: keep the most recently used ones
    const tables = new Map();
    const lru = (key, fn) => {
        if (tables.has(key)) { const v = tables.get(key); tables.delete(key); tables.set(key, v); return v; }
        const v = fn();
        tables.set(key, v);
        while (tables.size > maxTables) tables.delete(tables.keys().next().value);
        return v;
    };
    const getJSON = p => memo('j:' + p, () => json(p));
    // only partitioned datasets have an index file (build.json lists them)
    const indexOf = async code => {
        const b = await getJSON('build.json');
        const parts = b && b.partitioned;
        return !parts || parts.includes(code) ? getJSON(`data/${code}.index.json`) : null;
    };
    const getTable = p => lru('t:' + p, async () => decodeTcol(await binary(p)));

    async function whole(code) {
        return lru('w:' + code, async () => {
            const table = await getTable(`data/${code}.bin.gz`);
            const distinct = {};
            for (const c of table.columns) if (c !== 'OBS_VALUE') distinct[c] = [...table.dicts[c]];
            const tc = table.codes.TIME_PERIOD;
            return { table, distinct, hasNullTime: !!(tc && tc.includes(-1)) };
        });
    }

    return {
        build: () => getJSON('build.json'),
        policy: code => getJSON(`policy/${code}.json.gz`),
        /** Distinct values (whole file) without loading partitions. */
        async meta(code) {
            const index = await indexOf(code);
            if (!index) { const w = await whole(code); return { distinct: w.distinct, hasNullTime: w.hasNullTime }; }
            const t = (index.partitions || {}).time;
            return { distinct: index.distinct, hasNullTime: !!(t && t.null) };
        },
        /** The rows a query with these (file-column) filters can touch. */
        async table(code, filters, budget = 0) {
            const index = await indexOf(code);
            if (!index) return whole(code);
            const parts = index.partitions || {};
            // the partition set that reads fewer rows for these filters
            const pick = p => {
                const want = (filters[p.column] || []).filter(v => v !== null && v !== undefined).map(String);
                if (!want.length) return null;
                const files = want.filter(v => p.files[v]);
                return { files: files.map(v => p.files[v]),
                         rows: files.reduce((s, v) => s + ((p.rows || {})[v] || 0), 0) };
            };
            const cands = [parts.area && pick(parts.area), parts.time && pick(parts.time)].filter(Boolean);
            cands.sort((a, b) => a.rows - b.rows);
            let files = cands.length ? cands[0].files : null;
            if (!files) {
                const p = parts.area || parts.time;
                files = [...Object.values(p.files), ...(p.null ? [p.null] : [])];
            }
            // bytes this query would download; the caller enforces the budget
            const sizeOf = {};
            for (const p of Object.values(parts)) {
                for (const [v, f] of Object.entries(p.files)) sizeOf[f] = (p.bytes || {})[v] || 0;
            }
            const bytes = files.reduce((s, f) => s + (sizeOf[f] || 0), 0);
            if (budget && bytes > budget) return { overBudget: true, bytes, budget };
            const tables = await Promise.all(files.map(f => getTable(`data/${f}`)));
            const t = (parts.time || {});
            return { table: tables.length ? mergeTables(tables) : emptyTable(index.columns),
                     distinct: index.distinct, hasNullTime: !!t.null };
        },
    };
}
