// Render the default state of app/static/mcp-connect.html into the page itself:
// warnings, filter chips, client cards and the verification statuses from
// app/static/data/mcp-clients.csv. The page then works without JavaScript, from
// disk (file://), and search engines see the full content.
//
// Usage: node scripts/build-mcp-connect.mjs          # rewrite the page
//        node scripts/build-mcp-connect.mjs --check  # exit 1 if the page is stale
// Run it after you edit js/mcp-connect.js or data/mcp-clients.csv.
import { readFileSync, writeFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import vm from 'node:vm';

const ROOT = fileURLToPath(new URL('../app/static/', import.meta.url));
const PAGE = ROOT + 'mcp-connect.html';

const sandbox = { module: { exports: {} }, btoa: (s) => Buffer.from(s, 'binary').toString('base64'), URL };
vm.runInNewContext(readFileSync(ROOT + 'js/mcp-connect.js', 'utf8'), sandbox);
const M = sandbox.module.exports;

const status = M.parseCsv(readFileSync(ROOT + 'data/mcp-clients.csv', 'utf8'));
const missing = M.CLIENTS.map((c) => c.id).filter((id) => !status[id]);
const extra = Object.keys(status).filter((id) => !M.CLIENTS.some((c) => c.id === id));
if (missing.length || extra.length) {
    console.error(`mcp-clients.csv out of step with js/mcp-connect.js. Missing rows: ${missing.join(', ') || '-'}. Unknown ids: ${extra.join(', ') || '-'}.`);
    process.exit(1);
}

const untagged = M.CLIENTS.filter((c) => c.svc === '?').map((c) => c.id);
if (untagged.length) { console.error(`No service in SVC_OF (js/mcp-connect.js) for: ${untagged.join(', ')}`); process.exit(1); }
const uncategorised = M.CLIENTS.filter((c) => c.cat === '?').map((c) => c.id);
if (uncategorised.length) { console.error(`No type in CAT_OF (js/mcp-connect.js) for: ${uncategorised.join(', ')}`); process.exit(1); }

M.setState(M.DEFAULTS);
const parts = {
    warns: M.warningsHtml(),
    chips: M.chipsHtml(),
    cards: '\n' + M.cardsHtml(status) + '\n',
    // "<" escaped so no CSV text can close the <script> element.
    status: JSON.stringify(status).replace(/</g, '\\u003c'),
};

const before = readFileSync(PAGE, 'utf8');
let after = before;
for (const [k, v] of Object.entries(parts)) {
    const re = new RegExp(`(<!-- mcp:${k} -->)[\\s\\S]*?(<!-- /mcp:${k} -->)`);
    if (!re.test(after)) { console.error(`Marker mcp:${k} not found in ${PAGE}`); process.exit(1); }
    after = after.replace(re, (_, a, b) => a + v + b);
}

if (process.argv.includes('--check')) {
    if (after !== before) { console.error('mcp-connect.html is stale. Run: node scripts/build-mcp-connect.mjs'); process.exit(1); }
    console.log('mcp-connect.html is up to date.');
} else {
    writeFileSync(PAGE, after);
    console.log(`Rendered ${M.CLIENTS.length} cards into ${PAGE}`);
}
