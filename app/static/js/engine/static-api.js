// The static site's /api: the same paths and answers as the FastAPI app, served
// from the build (scripts/build-static.py + scripts/static_api.py) and the
// browser engine. `handle(path, params)` returns the JSON the server would, or
// throws ApiError(status, detail) where the server answers 4xx/5xx.
//
//   bounded answers      rec/…json.gz, recorded from the real app at build time
//   /datasets/{c}/data   engine/query.js (run_query port, parity-tested)
//   /datasets, /search   engine/search.js (search_datasets + concept search)
//   /datasets/{c}/options, /recipes/{id}?areas   computed here from build inputs
//
// `io.bytes(rel)` returns the decompressed bytes of a build-relative file or
// null when it does not exist (browser: fetch; Node: fs).

import { runQuery, QueryError, MISSING, pyRepr, cmp, validateFilters } from './query.js';
import { pyStr, pyFloatRepr } from './policy.js';
import { makeLoader } from './data.js';
import { fold, geoId, listDatasets, search } from './search.js';

export class ApiError extends Error {
    constructor(status, detail) {
        super(typeof detail === 'string' ? detail : (detail && detail.message) || JSON.stringify(detail));
        this.status = status;
        this.detail = detail;
    }
}

/** Gunzip when the bytes are gzip (servers may or may not decode .gz for us). */
export async function maybeGunzip(bytes) {
    if (bytes.length > 2 && bytes[0] === 0x1f && bytes[1] === 0x8b) {
        const stream = new Blob([bytes]).stream().pipeThrough(new DecompressionStream('gzip'));
        return new Uint8Array(await new Response(stream).arrayBuffer());
    }
    return bytes;
}

/** Browser io: files under `base` (default: the site root). */
export function browserIO(base = '/') {
    return {
        async bytes(rel) {
            const r = await fetch(base + rel);
            if (r.status === 404) return null;
            if (!r.ok) throw new ApiError(r.status, `static file ${rel}: HTTP ${r.status}`);
            return maybeGunzip(new Uint8Array(await r.arrayBuffer()));
        },
    };
}

const parseJsonParam = (raw, name) => {
    if (raw === undefined || raw === null || raw === '') return MISSING;
    try { return JSON.parse(raw); } catch { throw new ApiError(400, `Invalid ${name}: not valid JSON`); }
};
const intParam = (raw, dflt, lo, hi, name) => {
    if (raw === undefined || raw === null || raw === '') return dflt;
    const n = Number(raw);
    if (!Number.isInteger(n) || n < lo || (hi !== null && n > hi)) {
        throw new ApiError(422, `Invalid ${name}: must be an integer${hi !== null ? ` in ${lo}..${hi}` : ` >= ${lo}`}`);
    }
    return n;
};
const lang = p => (p.lang === 'en' ? 'en' : 'ro');

const FORMULA_START = ['=', '+', '-', '@', '\t', '\r'];
const PLAIN_NUMBER = /^[+-]?(\d+([.,]\d*)?|[.,]\d+)$/;
/** export.csv_safe */
export const csvSafe = v => (typeof v === 'string' && FORMULA_START.some(f => v.startsWith(f))
    && !PLAIN_NUMBER.test(v) ? "'" + v : v);

/** Python csv.writer (excel dialect, QUOTE_MINIMAL, \r\n). */
export function toCsv(columns, rows) {
    const field = v => {
        if (v === null || v === undefined) return '';
        const s = String(v);
        return /[",\r\n]/.test(s) ? '"' + s.replace(/"/g, '""') + '"' : s;
    };
    const line = r => (r.length === 1 && r[0] === '' ? '""' : r.map(field).join(','));
    return [columns, ...rows].map(line).join('\r\n') + '\r\n';
}

export function makeStaticApi(io) {
    const memo = new Map();
    const json = rel => {
        if (!memo.has(rel)) {
            memo.set(rel, (async () => {
                const b = await io.bytes(rel);
                return b === null ? null : JSON.parse(new TextDecoder().decode(b));
            })());
        }
        return memo.get(rel);
    };
    const src = { json };
    const loader = makeLoader({ json, binary: async rel => io.bytes(rel), maxTables: 48 });

    async function recorded(rel, notFound = 'Not Found') {
        const v = await json(rel);
        if (v === null) throw new ApiError(404, notFound);
        if (v && typeof v === 'object' && '__status' in v) throw new ApiError(v.__status, v.detail);
        return v;
    }

    async function data(code, p) {
        const f = parseJsonParam(p.filters ?? '{}', 'filters');
        const g = parseJsonParam(p.group_by ?? '', 'group_by');
        const build = await loader.build();
        const limit = intParam(p.limit, build.max_data_rows, 1, build.max_data_rows, 'limit');
        const approximate = intParam(p.approximate, 0, 0, 1, 'approximate') === 1;
        try {
            return await runQuery(loader, code, f, g, limit, approximate);
        } catch (e) {
            if (e instanceof QueryError) throw new ApiError(e.status, e.message);
            throw e;
        }
    }

    /** data_query.dimension_values */
    async function options(code, p) {
        const column = p.column;
        if (!column) throw new ApiError(422, 'Missing column');
        const limit = intParam(p.limit, 50, 1, 500, 'limit');
        const offset = intParam(p.offset, 0, 0, null, 'offset');
        const q = p.q ?? null;
        const policy = await loader.policy(code);
        if (!policy) throw new ApiError(404, `Dataset ${code} not found`);
        const fileCol = policy.to_file[column] ?? column;
        if (!policy.file_columns.includes(fileCol) || fileCol === policy.value_column || fileCol === 'OBS_VALUE') {
            throw new ApiError(400, `Invalid column: unknown column ${pyRepr(column)}`);
        }
        const isTime = (policy.to_sdmx[fileCol] ?? fileCol) === 'TIME_PERIOD';
        const meta = await loader.meta(code);
        let values = [...(meta.distinct[fileCol] || [])].map(String);
        if (q) {
            const fq = fold(q);
            values = values.filter(v => fold(v).includes(fq));
        }
        if (isTime) values.sort((a, b) => cmp(b, a));
        else values.sort((a, b) => cmp(fold(a), fold(b)) || cmp(a, b));
        const page = values.slice(offset, offset + limit);
        const more = offset + limit < values.length;
        const out = { matrix_code: code, column, q, total: values.length,
                      offset, limit, values: page, next_offset: more ? offset + limit : null, truncated: more };
        if (isTime) out.period_bounds = policy.period_bounds;
        return out;
    }

    /** /recipes/{id}: the recorded full result, reduced to `areas` exactly as run() would. */
    async function recipe(id, p) {
        const lg = lang(p);
        let areas = null;
        if (p.areas) {
            let v;
            try { v = JSON.parse(p.areas); } catch {
                throw new ApiError(400, 'Invalid areas: expected a JSON array of area names');
            }
            if (!Array.isArray(v) || !v.every(a => typeof a === 'string') || v.length > 60) {
                throw new ApiError(400, 'Invalid areas: expected a JSON array of up to 60 area names');
            }
            areas = v.length ? v : null;
        }
        const latest = await json(`rec/recipe/${id}/latest.${lg}.json.gz`);
        if (latest === null) throw new ApiError(404, { reason: 'unknown_recipe', message: `no recipe ${pyRepr(id)}` });
        if ('__status' in latest) throw new ApiError(latest.__status, latest.detail);
        let full = latest;
        if (p.year) {
            if (!/^\d{4}$/.test(p.year)) throw new ApiError(422, 'Invalid year');
            if (!latest.years_available.includes(p.year)) {
                throw new ApiError(422, { reason: 'year_unavailable', message: `no common data for ${p.year}`,
                                          years_available: latest.years_available });
            }
            full = await recorded(`rec/recipe/${id}/${p.year}.${lg}.json.gz`);
        }
        const out = structuredClone(full);
        out.request = { year: p.year || null, areas, lang: lg };
        if (!areas) return out;
        const want = new Set(areas.map(geoId));
        const outside = new Set(['not_in_denominator', 'not_in_data']);
        const universe = new Set([...full.rows.map(r => r.geo_id),
            ...full.excluded.filter(e => !outside.has(e.reason)).map(e => e.geo_id)]);
        out.rows = full.rows.filter(r => want.has(r.geo_id)).map((r, i) => ({ ...r, rank: i + 1 }));
        out.excluded = full.excluded.filter(e => want.has(e.geo_id));
        const seen = new Set(out.excluded.map(e => e.geo_id));
        for (const g of [...want].sort(cmp)) {
            if (!universe.has(g) && !seen.has(g)) out.excluded.push({ geo_id: g, label: g, reason: 'not_in_data' });
        }
        out.universe = [...want].filter(g => universe.has(g)).length;
        return out;
    }

    /** Rows of `code` matching `where` ({file column: Set(str values)}), ordered
     *  by `cols` then the value (build_export_query_params). Counting happens
     *  first; `rows()` sorts on demand. Over the byte budget: 413, never cut. */
    async function select(code, policy, cols, where, _limit, countOnly = false) {
        const fileCols = new Set(policy.file_columns);
        if (Object.keys(where).some(c => !fileCols.has(c))) throw new ApiError(500, 'Query failed');
        const build = await loader.build();
        const t = await loader.table(code, Object.fromEntries(Object.entries(where).map(([c, v]) => [c, [...v]])),
                                     build.max_query_bytes);
        if (t.overBudget) {
            throw new ApiError(413, `This selection needs ${(t.bytes / 1e6).toFixed(1)} MB of data, more than the `
                + `static site loads at once (${(t.budget / 1e6).toFixed(0)} MB). Filter by county or period.`);
        }
        const table = t.table;
        const codeOf = {};
        for (const c of Object.keys(where)) {
            codeOf[c] = new Set((table.dicts[c] || []).map((v, i) => (where[c].has(String(v)) ? i : -2)).filter(i => i >= 0));
        }
        const idx = [];
        outer: for (let r = 0; r < table.rows; r++) {
            for (const c in codeOf) if (!codeOf[c].has(table.codes[c] ? table.codes[c][r] : -1)) continue outer;
            idx.push(r);
        }
        const cell = (c, r) => { const k = table.codes[c] ? table.codes[c][r] : -1; return k < 0 ? null : table.dicts[c][k]; };
        const value = r => (Number.isNaN(table.values[r]) ? null : table.values[r]);
        return {
            total: idx.length,
            rows() {
                if (cols.some(c => !fileCols.has(c))) throw new ApiError(500, 'Query failed');
                idx.sort((x, y) => {
                    for (const c of cols) { const d = cmp(cell(c, x), cell(c, y)); if (d) return d; }
                    return cmp(value(x), value(y));
                });
                return { cell, value, idx };
            },
        };
    }

    /** Effective (SDMX-named) filters -> {file column: Set(values)} as adapt_to_parquet. */
    function whereOf(policy, filters, cols) {
        const toFile = c => (c.endsWith('_nom_id') ? (policy.to_file[c] ?? c) : c);
        const valid = new Set(cols), where = {};
        for (const [c0, vals] of Object.entries(filters || {})) {
            const c = toFile(c0);
            if (!valid.has(c) || !vals || !vals.length) continue;
            const vs = vals.filter(v => v !== null && v !== undefined).map(pyStr);
            if (vs.length) where[c] = new Set(vs);
        }
        return where;
    }

    /** /datasets/{c}/download: every raw observation matching the filters
     *  (export.py / query_builder.build_export_query_params). Returns
     *  {matrix_code, format, columns, rows} for the caller to write, or the
     *  preflight JSON. The browser byte budget still applies: a selection
     *  whose files exceed it is refused (413), never cut. */
    async function exportRows(code, p) {
        const fmt = p.format || 'csv';
        if (!['csv', 'xlsx'].includes(fmt)) throw new ApiError(422, 'Invalid format');
        const lg = p.lang || 'ro';
        if (!['ro', 'en'].includes(lg)) throw new ApiError(422, 'Invalid lang');
        const safe = intParam(p.safe, 1, 0, 1, 'safe') === 1;
        const preflight = intParam(p.preflight, 0, 0, 1, 'preflight') === 1;
        const policy = await loader.policy(code);
        if (!policy) throw new ApiError(404, `Dataset ${code} not found`);
        const build = await loader.build();
        let fd;
        try {
            fd = validateFilters(parseJsonParam(p.filters ?? '{}', 'filters'), new Set(policy.allowed));
        } catch (e) {
            if (e instanceof QueryError) throw new ApiError(400, e.message);
            throw e;
        }
        const cols = policy.file_dimensions.map(d => d.dim_column_name);
        const where = whereOf(policy, fd, cols);
        const sel = await select(code, policy, cols, where, fmt === 'xlsx' ? build.xlsx_row_limit : null,
                                 preflight);
        const total = sel.total;
        if (fmt === 'xlsx' && total > build.xlsx_row_limit) {
            throw new ApiError(413, `Selection has ${total} rows, more than the XLSX limit of `
                + `${build.xlsx_row_limit} data rows. Narrow the filters or download CSV, which has no row limit.`);
        }
        if (build.export_row_limit && total > build.export_row_limit) {
            throw new ApiError(413, `Selection has ${total} rows, more than the export limit of `
                + `${build.export_row_limit}. Narrow the filters.`);
        }
        if (preflight) {
            return { matrix_code: code, format: fmt, matching_rows: total, complete: true,
                     xlsx_row_limit: build.xlsx_row_limit, export_row_limit: build.export_row_limit };
        }
        const { cell, value, idx } = sel.rows();
        const maps = lg === 'en' ? (policy.en_labels || {}) : {};
        const isFloat = /^(DOUBLE|FLOAT|REAL|DECIMAL)/i.test(policy.value_type || 'DOUBLE');
        const rows = idx.map(r => {
            const out = cols.map(c => {
                let v = cell(c, r);
                if (v === null) return null;
                const m = maps[c];
                if (m && Object.prototype.hasOwnProperty.call(m, v)) v = m[v];
                if (safe && fmt === 'csv') v = csvSafe(v);
                return v;
            });
            const v = value(r);
            out.push(v === null ? null : (isFloat ? pyFloatRepr(v) : String(v)));
            return out;
        });
        return { matrix_code: code, format: fmt, columns: [...cols, 'OBS_VALUE'], rows, total };
    }

    async function handle(path, params = {}) {
        const p = Object.fromEntries(Object.entries(params || {})
            .filter(([, v]) => v !== null && v !== undefined).map(([k, v]) => [k, String(v)]));
        const path_ = path.replace(/^\/api(?=\/)/, '').replace(/\/+$/, '');
        const seg = path_.split('/').filter(Boolean).map(decodeURIComponent);
        const lg = lang(p);
        const [a, b, c, d, e] = seg;
        if (a === 'health') {
            const build = await loader.build();
            return { status: 'ok', static: true, generation: build.generation, commit: build.commit };
        }
        if (a === 'categories' && seg.length === 1) return recorded(`rec/categories.${lg}.json.gz`);
        if (a === 'categories' && b === 'trends') return recorded('rec/categories-trends.json.gz');
        if (a === 'categories' && c === 'summary') {
            return recorded(`rec/category-summary/${b}.${lg}.json.gz`, `Category ${b} not found`);
        }
        if (a === 'corpus' && b === 'summary') return recorded(`rec/corpus-summary.${lg}.json.gz`);
        if (a === 'dimensions') {
            const limit = intParam(p.limit, 100, 1, 500, 'limit');
            return (await recorded('rec/dimensions.json.gz')).slice(0, limit);
        }
        if (a === 'reference' && b === 'population') {
            const level = p.level || 'county';
            if (!['county', 'region', 'macroregion'].includes(level)) throw new ApiError(422, 'Invalid level');
            return recorded(`rec/population.${level}.json.gz`);
        }
        if (a === 'search') {
            const q = p.q || '';
            if (q.length < 1 || q.length > 200) throw new ApiError(422, 'Invalid q: 1..200 characters');
            const build = await loader.build();
            return search(src, q, { lang: lg, limit: intParam(p.limit, 10, 1, 50, 'limit'),
                                    offset: intParam(p.offset, 0, 0, null, 'offset'),
                                    generation: build.generation });
        }
        if (a === 'datasets' && seg.length === 1) {
            try { return await listDatasets(src, p); } catch (err) {
                throw new ApiError(err.status || 500, err.message);
            }
        }
        if (a === 'datasets' && seg.length === 2) return recorded(`rec/datasets/${b}.${lg}.json.gz`, `Dataset ${b} not found`);
        if (a === 'datasets' && c === 'insights') return recorded(`rec/insights/${b}.${lg}.json.gz`, `Dataset ${b} not found`);
        if (a === 'datasets' && c === 'related') {
            const limit = intParam(p.limit, 5, 1, 12, 'limit');
            const r = await recorded(`rec/related/${b}.${lg}.json.gz`, `Dataset ${b} not found`);
            if (limit !== 5) throw new ApiError(400, 'The static site records related datasets with the default limit only');
            return r;
        }
        if (a === 'datasets' && c === 'data') return data(b, p);
        if (a === 'datasets' && c === 'options') return options(b, p);
        if (a === 'datasets' && c === 'download') {
            const out = await exportRows(b, p);
            return out.rows ? { ...out, text: toCsv(out.columns, out.rows) } : out;
        }
        if (a === 'ask' && b === 'config') {
            return { enabled: false, byok_enabled: false, available: false, chat_logging: false,
                     limits: {}, byok_models: [] };
        }
        if (a === 'places' && seg.length === 1) return recorded('rec/places.json.gz');
        if (a === 'places' && seg.length === 3) {
            return recorded(`rec/place/${b}/${c}.json.gz`, `Place not found: ${b}/${c}`);
        }
        if (a === 'places' && d === 'baselines') return recorded(`rec/place/${b}/${c}/baselines/${e}.json.gz`);
        if (a === 'recipes' && seg.length === 1) return recorded(`rec/recipes.${lg}.json.gz`);
        if (a === 'recipes' && seg.length === 2) return recipe(b, p);
        throw new ApiError(404, `Not available on the static site: ${path}`);
    }

    /** Where a recipe's recorded evidence ZIP is (areas are not applied). */
    const recipeEvidencePath = (id, year, lg) => `rec/recipe/${id}/${year}.${lg === 'en' ? 'en' : 'ro'}.zip`;

    return { handle, loader, json, exportRows, select, whereOf, recipeEvidencePath };
}
