// Evidence bundles in the browser (tempo-evidence/1), a port of
// app/services/evidence.dataset_bundle: the /data selection's unrounded result,
// the raw observations behind an aggregation, the decision, definition, source,
// and a manifest with the sha256 of every file. Written as a store-only ZIP.
// Recipe bundles are recorded at build time (rec/recipe/{id}/{year}.{lang}.zip).

import { pyFloatRepr } from './policy.js';

const SCHEMA = 'tempo-evidence/1';
const INS_URL = 'http://statistici.insse.ro:8077/tempo-online/';
export const MAX_INPUT_ROWS = 200_000;
const README_LIVE =
    'A live link re-runs this selection on the data the site serves at the time;\n'
    + 'if the source is revised, the live answer changes. This bundle keeps the\n'
    + 'answer as it was computed, with the generation id in manifest.json.\n';

// ------------------------------------------------------------------ zip (stored)

const CRC_TABLE = (() => {
    const t = new Uint32Array(256);
    for (let n = 0; n < 256; n++) {
        let c = n;
        for (let k = 0; k < 8; k++) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1;
        t[n] = c >>> 0;
    }
    return t;
})();
function crc32(bytes) {
    let c = 0xffffffff;
    for (let i = 0; i < bytes.length; i++) c = CRC_TABLE[(c ^ bytes[i]) & 0xff] ^ (c >>> 8);
    return (c ^ 0xffffffff) >>> 0;
}

/** files: [[name, Uint8Array], ...] -> ZIP bytes (no compression, fixed date 2026-01-01). */
export function zipStore(files) {
    const enc = new TextEncoder();
    const DOS_TIME = 0, DOS_DATE = ((2026 - 1980) << 9) | (1 << 5) | 1;
    const parts = [], central = [];
    let offset = 0;
    for (const [name, data] of files) {
        const nb = enc.encode(name), crc = crc32(data);
        const h = new DataView(new ArrayBuffer(30));
        h.setUint32(0, 0x04034b50, true); h.setUint16(4, 20, true); h.setUint16(6, 0x0800, true);
        h.setUint16(8, 0, true); h.setUint16(10, DOS_TIME, true); h.setUint16(12, DOS_DATE, true);
        h.setUint32(14, crc, true); h.setUint32(18, data.length, true); h.setUint32(22, data.length, true);
        h.setUint16(26, nb.length, true); h.setUint16(28, 0, true);
        parts.push(new Uint8Array(h.buffer), nb, data);
        const c = new DataView(new ArrayBuffer(46));
        c.setUint32(0, 0x02014b50, true); c.setUint16(4, 20, true); c.setUint16(6, 20, true);
        c.setUint16(8, 0x0800, true); c.setUint16(10, 0, true); c.setUint16(12, DOS_TIME, true);
        c.setUint16(14, DOS_DATE, true); c.setUint32(16, crc, true); c.setUint32(20, data.length, true);
        c.setUint32(24, data.length, true); c.setUint16(28, nb.length, true);
        c.setUint32(42, offset, true);
        central.push(new Uint8Array(c.buffer), nb);
        offset += 30 + nb.length + data.length;
    }
    const csize = central.reduce((s, x) => s + x.length, 0);
    const e = new DataView(new ArrayBuffer(22));
    e.setUint32(0, 0x06054b50, true); e.setUint16(8, files.length, true); e.setUint16(10, files.length, true);
    e.setUint32(12, csize, true); e.setUint32(16, offset, true);
    const all = [...parts, ...central, new Uint8Array(e.buffer)];
    const out = new Uint8Array(all.reduce((s, x) => s + x.length, 0));
    let o = 0;
    for (const x of all) { out.set(x, o); o += x.length; }
    return out;
}

async function sha256Hex(bytes) {
    const h = new Uint8Array(await crypto.subtle.digest('SHA-256', bytes));
    return [...h].map(b => b.toString(16).padStart(2, '0')).join('');
}

// ------------------------------------------------------------------ formats

/** evidence._csv: csv.writer(lineterminator="\n"), floats as repr, None empty. */
export function evidenceCsv(header, rows) {
    const field = v => {
        if (v === null || v === undefined) return '';
        const s = typeof v === 'number' ? pyFloatRepr(v) : String(v);
        return /[",\r\n]/.test(s) ? '"' + s.replace(/"/g, '""') + '"' : s;
    };
    return [header, ...rows].map(r => r.map(field).join(',')).join('\n') + '\n';
}
const pyJson = obj => JSON.stringify(obj, null, 1) + '\n';

function attribution(sources) {
    const today = new Date().toISOString().slice(0, 10);
    return {
        sources: sources.map(s => ({ dataset: s.dataset, title: s.title ?? null,
            publisher: 'Institutul Național de Statistică (INS), TEMPO Online', url: INS_URL,
            source_updated: s.source_updated ?? null })),
        reuse_terms: null,
        reuse_terms_note: 'Not verified for this bundle; consult INS terms before republishing.',
        citation: sources.map(s => `INS, TEMPO Online, ${s.dataset} — ${s.title || ''}`
            + (s.source_updated ? ` (actualizat ${s.source_updated})` : '')).join('; ')
            + `. Accesat ${today} prin INS+.`,
    };
}

/** evidence.dataset_bundle on the static API -> {zip, files, manifest}.
 *  Throws ApiError(413/4xx) like the server. */
export async function datasetEvidence(api, ApiError, code, { filters, groupBy, approximate = false,
                                                              lang = 'ro', link, build }) {
    const params = { filters: JSON.stringify(filters ?? {}), lang };
    if (groupBy) params.group_by = JSON.stringify(groupBy);
    if (approximate) params.approximate = 1;
    const res = await api.handle(`/datasets/${code}/data`, params);
    if (res.aggregation && res.aggregation.reason === 'browser_budget') {
        // The browser could not load the rows: refuse, never bundle an empty answer.
        throw new ApiError(413, `This selection needs ${(res.budget.bytes / 1e6).toFixed(1)} MB of data, more than the `
            + `static site loads at once (${(res.budget.max_bytes / 1e6).toFixed(0)} MB). Filter by county or period.`);
    }
    if (res.truncated || res.time_windowed || res.partial_period_dropped) {
        throw new ApiError(413, 'The selection is larger than an evidence bundle can hold '
            + 'completely. Narrow it (period or area) and try again.');
    }
    const policy = await api.loader.policy(code);
    const facts = (policy.facts && policy.facts[lang]) || { title: code };
    const agg = res.aggregation || null;
    const ti = res.columns.indexOf('TIME_PERIOD');
    const files = {
        'selection.json': pyJson({
            dataset: code, link, lang,
            requested: { filters: filters ?? null, group_by: groupBy ?? null, approximate },
            effective: { filters: agg ? agg.filters ?? null : null, levels: agg ? agg.levels ?? null : null },
            periods_in_result: ti >= 0 ? [...new Set(res.rows.map(r => String(r[ti])))].sort() : null,
        }),
        'method.json': pyJson({
            kind: agg ? 'aggregation' : 'raw_observations', decision: agg, quality: res.quality ?? null,
            definition: facts.definition ?? null, unit: facts.unit ?? null,
            rounding: 'values are unrounded; the site rounds only for display',
            unavailable: !!res.unavailable,
        }),
        'attribution.json': pyJson(attribution([{ dataset: code, ...facts }])),
        'result.csv': evidenceCsv(res.columns, res.rows),
    };
    if (agg && !res.unavailable) {
        const cols = policy.evidence_dims.map(c => (c.endsWith('_nom_id') ? (policy.to_file[c] ?? c) : c));
        const where = api.whereOf(policy, agg.filters || {}, cols);
        const sel = await api.select(code, policy, cols, where);
        if (sel.total > MAX_INPUT_ROWS) {
            throw new ApiError(413, `The aggregation reads ${sel.total} observations, more than an `
                + `evidence bundle carries (${MAX_INPUT_ROWS}). Narrow the selection.`);
        }
        const { cell, value, idx } = sel.rows();
        const header = [...cols.map(c => policy.to_sdmx[c] ?? c), 'OBS_VALUE'];
        const isFloat = /^(DOUBLE|FLOAT|REAL|DECIMAL)/i.test(policy.value_type || 'DOUBLE');
        const val = r => { const v = value(r); return v === null || isFloat ? v : String(v); };
        files['inputs/observations.csv'] = evidenceCsv(header, idx.map(r => [...cols.map(c => cell(c, r)), val(r)]));
    }
    files['README.txt'] = `Evidence for ${code}: ${facts.title ?? null}\n\n`
        + 'result.csv           the answer, unrounded\n'
        + (agg ? 'inputs/observations.csv  every source observation the aggregation used\n' : '')
        + 'selection.json       what was asked and the filters actually applied\n'
        + 'method.json          aggregation decision, data quality, definition, unit\n'
        + 'attribution.json     source, update date and a citation\n'
        + 'manifest.json        versions, generation id and sha256 of each file\n\n' + README_LIVE;
    const enc = new TextEncoder();
    const names = Object.keys(files).sort();
    const hashes = {};
    for (const n of names) hashes[n] = await sha256Hex(enc.encode(files[n]));
    const manifest = { schema: SCHEMA, kind: 'dataset',
        created_at: new Date().toISOString().replace(/\.\d{3}Z$/, '+00:00'),
        app_version: build?.commit ? `static-${build.commit.slice(0, 12)}` : 'static',
        query_contract: res.contract ?? null, generation: res.generation ?? null, dataset: code, files: hashes };
    const zip = zipStore([['manifest.json', enc.encode(pyJson(manifest))],
                          ...names.map(n => [n, enc.encode(files[n])])]);
    return { zip, files, manifest };
}
