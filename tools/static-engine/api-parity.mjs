#!/usr/bin/env node
// API parity: replay the server answers recorded by scripts/gen-api-cases.py
// through the static site's /api (app/static/js/engine/static-api.js) on a
// static build. 200s must be deep-equal (numbers to 1e-9); errors must carry
// the same status and, except FastAPI's own 422 validation lists, the same detail.
//
//   node tools/static-engine/api-parity.mjs --build _static --cases api-cases.jsonl [--verbose N]
import crypto from 'node:crypto';
import fs from 'node:fs';
import path from 'node:path';
import readline from 'node:readline';
import zlib from 'node:zlib';
import { makeStaticApi, ApiError } from '../../app/static/js/engine/static-api.js';
import { datasetEvidence } from '../../app/static/js/engine/evidence.js';

const args = Object.fromEntries(process.argv.slice(2).reduce((a, x, i, arr) =>
    (x.startsWith('--') ? [...a, [x.slice(2), arr[i + 1]]] : a), []));
const build = args.build, verbose = +(args.verbose || 5);

const api = makeStaticApi({
    async bytes(rel) {
        try {
            const raw = await fs.promises.readFile(path.join(build, rel));
            return rel.endsWith('.gz') ? zlib.gunzipSync(raw) : raw;
        } catch (e) {
            if (e.code === 'ENOENT') return null;
            throw e;
        }
    },
});

const close = (a, b) => (typeof a === 'number' && typeof b === 'number')
    ? a === b || Math.abs(a - b) <= 1e-9 * Math.max(1, Math.abs(a), Math.abs(b)) : a === b;
function diff(a, b, at = '') {
    if (close(a, b)) return null;
    if (a === null || b === null || typeof a !== 'object' || typeof b !== 'object') return at || '.';
    if (Array.isArray(a) !== Array.isArray(b)) return at || '.';
    if (Array.isArray(a)) {
        if (a.length !== b.length) return `${at}.length`;
        for (let i = 0; i < a.length; i++) { const d = diff(a[i], b[i], `${at}[${i}]`); if (d) return d; }
        return null;
    }
    for (const k of new Set([...Object.keys(a), ...Object.keys(b)])) {
        const d = diff(a[k] ?? null, b[k] ?? null, `${at}.${k}`);
        if (d) return d;
    }
    return null;
}

const t0 = Date.now();
const stats = { cases: 0, ok: 0, fail: 0, by_path: {} };
const rl = readline.createInterface({ input: fs.createReadStream(args.cases) });
for await (const line of rl) {
    if (!line.trim()) continue;
    const c = JSON.parse(line);
    stats.cases++;
    let got, err = null;
    try {
        if (c.path.endsWith('/evidence')) {
            const code = c.path.split('/')[3];
            const ev = await datasetEvidence(api, ApiError, code, {
                filters: JSON.parse(c.params.filters || '{}'),
                groupBy: c.params.group_by ? JSON.parse(c.params.group_by) : null,
                lang: c.params.lang || 'ro', link: 'x', build: null });
            for (const [n, txt] of Object.entries(ev.files)) {
                const h = crypto.createHash('sha256').update(txt, 'utf8').digest('hex');
                if (ev.manifest.files[n] !== h) throw new Error(`manifest hash wrong for ${n}`);
            }
            got = { __zip: Object.fromEntries(Object.keys(c.body?.__zip || {}).map(n => [n, ev.files[n]])) };
        } else {
            got = await api.handle(c.path, c.params);
        }
    } catch (e) { err = e; }
    let why = null;
    const budget = err instanceof ApiError && err.status === 413 && /static site loads at once/.test(err.message);
    if ((c.status === 200 || c.status === 413) && budget) {
        stats.browser_budget_refusals = (stats.browser_budget_refusals || 0) + 1;   // documented divergence
    } else if (c.status === 200 && c.body && c.body.__csv_sha256) {
        if (err) why = `error ${err.status}: ${err.message}`;
        else if (crypto.createHash('sha256').update(got.text, 'utf8').digest('hex') !== c.body.__csv_sha256) {
            why = `csv sha256 differs (${c.body.__csv_bytes} vs ${Buffer.byteLength(got.text)} bytes)`;
        }
    } else if (c.status === 200 && typeof c.body === 'string') {      // CSV download
        if (err) why = `error ${err.status}: ${err.message}`;
        else if (got.text !== c.body) {
            const a = c.body.split('\r\n'), b = (got.text || '').split('\r\n');
            const i = a.findIndex((l, k) => l !== b[k]);
            why = `csv line ${i}: server ${JSON.stringify(a[i])} static ${JSON.stringify(b[i])} (${a.length}/${b.length} lines)`;
        }
    } else if (c.status === 200) {
        if (err) why = `error ${err.status}: ${err.message}`;
        else why = diff(c.body, got) && `field ${diff(c.body, got)}`;
    } else if (!err) {
        why = `expected ${c.status}, got 200`;
    } else if (!(err instanceof ApiError) || err.status !== c.status) {
        why = `status ${err.status ?? err} != ${c.status}`;
    } else if (c.status !== 422 || !Array.isArray(c.body?.detail)) {
        const d = diff(c.body?.detail ?? null, err.detail ?? null);
        if (d) why = `detail ${d}`;
    }
    const key = c.path.split('/').slice(0, 3).join('/') + (c.path.split('/').length > 3 ? '/…/' + c.path.split('/').pop() : '');
    if (why) {
        stats.fail++;
        stats.by_path[key] = (stats.by_path[key] || 0) + 1;
        if (stats.fail <= verbose) {
            console.log(`MISMATCH ${c.path} ${JSON.stringify(c.params)} ${why}`);
            if (c.status === 200 && got) {
                const d = diff(c.body, got);
                const pick = (o, p) => p.split(/\.|\[|\]/).filter(Boolean).reduce((x, k) => (x == null ? x : x[k]), o);
                console.log('  server:', JSON.stringify(pick(c.body, d))?.slice(0, 300));
                console.log('  static:', JSON.stringify(pick(got, d))?.slice(0, 300));
            }
        }
    } else stats.ok++;
}
stats.seconds = (Date.now() - t0) / 1000;
console.log(JSON.stringify(stats));
process.exit(stats.fail ? 1 : 0);
