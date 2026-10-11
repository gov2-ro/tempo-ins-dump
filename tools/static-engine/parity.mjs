#!/usr/bin/env node
// Parity: replay recorded run_query answers (scripts/gen-parity-cases.py)
// through the browser engine (app/static/js/engine) on a static build.
//
//   node tools/static-engine/parity.mjs --build _static --cases cases.jsonl [--verbose N]
//
// Exit 1 on any mismatch. Rows whose full dimension key ties (duplicate keys in
// conflicting-grain files) may come back in a different order in DuckDB itself;
// those are reported as `tie_order`, not failures, when the multisets agree.
import fs from 'node:fs';
import path from 'node:path';
import readline from 'node:readline';
import zlib from 'node:zlib';
import { runQuery, QueryError } from '../../app/static/js/engine/query.js';
import { makeLoader } from '../../app/static/js/engine/data.js';

const args = Object.fromEntries(process.argv.slice(2).reduce((a, x, i, arr) =>
    (x.startsWith('--') ? [...a, [x.slice(2), arr[i + 1]]] : a), []));
const build = args.build, casesPath = args.cases, verbose = +(args.verbose || 5);

const loader = makeLoader({
    async json(rel) {
        try { return JSON.parse(await fs.promises.readFile(path.join(build, rel), 'utf8')); } catch (e) {
            if (e.code === 'ENOENT') return null;
            throw e;
        }
    },
    async binary(rel) { return zlib.gunzipSync(await fs.promises.readFile(path.join(build, rel))); },
});

const close = (a, b) => {
    if (typeof a === 'number' && typeof b === 'number') {
        return a === b || Math.abs(a - b) <= 1e-9 * Math.max(1, Math.abs(a), Math.abs(b));
    }
    return a === b;
};
function deepEq(a, b) {
    if (close(a, b)) return true;
    if (a === null || b === null || typeof a !== 'object' || typeof b !== 'object') return false;
    if (Array.isArray(a) !== Array.isArray(b)) return false;
    if (Array.isArray(a)) return a.length === b.length && a.every((x, i) => deepEq(x, b[i]));
    const ka = Object.keys(a), kb = Object.keys(b);
    return ka.length === kb.length && ka.every(k => k in b && deepEq(a[k], b[k]));
}
const rowKey = r => JSON.stringify(r);
const sortRows = rows => [...rows].sort((x, y) => (rowKey(x) < rowKey(y) ? -1 : rowKey(x) > rowKey(y) ? 1 : 0));

function compare(want, got) {
    const diffs = [];
    const keys = new Set([...Object.keys(want), ...Object.keys(got)]);
    keys.delete('rows');
    for (const k of keys) {
        const a = want[k], b = got[k];
        if (k === 'unavailable' && !a && !b) continue;
        if (!deepEq(a ?? null, b ?? null)) diffs.push(k);
    }
    let tie = false;
    if (!deepEq(want.rows, got.rows)) {
        if ((want.rows || []).length === (got.rows || []).length
            && deepEq(sortRows(want.rows.map(r => r.map(v => (typeof v === 'number' ? +v.toPrecision(12) : v)))),
                      sortRows(got.rows.map(r => r.map(v => (typeof v === 'number' ? +v.toPrecision(12) : v)))))) {
            tie = true;
        } else diffs.push('rows');
    }
    return { diffs, tie };
}

const rl = readline.createInterface({ input: fs.createReadStream(casesPath), crlfDelay: Infinity });
let n = 0, ok = 0, ties = 0, fail = 0, shown = 0, resourceSkips = 0;
const byField = {};
const t0 = Date.now();
for await (const line of rl) {
    if (!line.trim()) continue;
    const c = JSON.parse(line);
    n++;
    const req = c.request;
    const val = v => (v === '__MISSING__' ? undefined : v);
    let got, err;
    try {
        got = await runQuery(loader, c.code, val(req.filters), val(req.group_by), req.limit, req.approximate);
    } catch (e) {
        if (!(e instanceof QueryError)) { err = { status: 'exception', message: String(e.stack || e) }; }
        else err = { status: e.status, message: e.message };
    }
    let diffs = [], tie = false;
    if (c.error) {
        if (!err || err.status !== c.error.status || err.message !== c.error.message) diffs = ['error'];
    } else if (err) {
        diffs = ['unexpected_error'];
    } else {
        ({ diffs, tie } = compare(c.response, got));
        // DuckDB ran out of memory on the slice check (Python reports
        // grain_unverified / slice_check_failed). Both sides must refuse; the
        // engine is allowed to name the actual grain problem.
        const ps = c.response.quality?.slice;
        if (diffs.length && ps && ps.evidence === 'slice_check_failed' && got.unavailable
            && diffs.every(d => d === 'aggregation' || d === 'quality')) {
            resourceSkips++;
            continue;
        }
    }
    if (!diffs.length) { ok++; if (tie) ties++; continue; }
    fail++;
    for (const d of diffs) byField[d] = (byField[d] || 0) + 1;
    if (shown++ < verbose) {
        console.log(`MISMATCH ${c.code} ${JSON.stringify(req)} fields=${diffs.join(',')}`);
        if (err) console.log('  engine error:', err);
        if (c.error) console.log('  python error:', c.error);
        for (const d of diffs) {
            if (d === 'rows') {
                console.log('  python rows:', JSON.stringify((c.response.rows || []).slice(0, 4)), (c.response.rows || []).length);
                console.log('  engine rows:', JSON.stringify((got.rows || []).slice(0, 4)), (got.rows || []).length);
            } else if (c.response && got) {
                console.log(`  ${d}: python=${JSON.stringify(c.response[d])?.slice(0, 400)}`);
                console.log(`  ${d}: engine=${JSON.stringify(got[d])?.slice(0, 400)}`);
            }
        }
    }
}
console.log(JSON.stringify({ cases: n, ok, tie_order: ties, python_resource_refusals: resourceSkips, fail, by_field: byField,
                             seconds: (Date.now() - t0) / 1000 }));
process.exit(fail ? 1 : 0);
