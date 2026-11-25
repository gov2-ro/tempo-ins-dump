/**
 * MCP connection cheatsheet (mcp-connect.html).
 * One file for the browser and for scripts/build-mcp-connect.mjs, which renders the
 * default state into the page (SEO, no-JS, file://). Statuses come from
 * data/mcp-clients.csv and are baked into the page by the same script.
 * Rendering returns HTML strings; every dynamic value passes through esc().
 */
(function (global) {
    'use strict';
    var DEFAULT_URL = 'https://api-ins.gov2.ro/mcp';
    var DEFAULT_NAME = 'ins-tempo';
    var DEFAULTS = { url: DEFAULT_URL, name: DEFAULT_NAME, t: 'http', auth: 'none', hdr: 'X-API-Key', env: 'MCP_TOKEN', svc: 'all' };
    var S = Object.assign({}, DEFAULTS);

    // ---------- helpers ----------
    function J(o) { return JSON.stringify(o, null, 2); }
    function hasHdr() { return S.auth === 'bearer' || S.auth === 'header'; }
    function hName() { return S.auth === 'bearer' ? 'Authorization' : (S.hdr || 'X-API-Key'); }
    function hVal(tok) { return S.auth === 'bearer' ? 'Bearer ' + tok : tok; }
    function headers(tok) { if (!hasHdr()) return undefined; var o = {}; o[hName()] = hVal(tok); return o; }
    function env() { return (S.env || 'MCP_TOKEN').replace(/[^A-Za-z0-9_]/g, '_'); }
    function nm() { return (S.name || DEFAULT_NAME).replace(/[^A-Za-z0-9_-]/g, '-'); }
    function obj(base, extra) { Object.keys(extra || {}).forEach(function (k) { if (extra[k] !== undefined) base[k] = extra[k]; }); return base; }
    function wrap(key, inner) { var o = {}; o[key] = {}; o[key][nm()] = inner; return o; }
    var TOK = '<YOUR_TOKEN>';
    function L(ro, en) { return { ro: ro, en: en || ro }; }

    function question() {
        return S.url === DEFAULT_URL
            ? 'Care a fost populația rezidentă a județului Cluj în 2024?'
            : 'Which tools do you have? Use one of them.';
    }

    // Notes shared by many cards.
    var N = {
        oauthUi: L('La prima folosire, aplicația deschide pagina de login a serverului.', 'On first use, the app opens the server\'s sign-in page.'),
        cloud: L('Conexiunea pleacă din cloud-ul furnizorului: adresa trebuie să fie publică, HTTPS.', 'The connection starts from the vendor\'s cloud: the URL must be public HTTPS.'),
        hdrUi: L('Antete fixe: căutați „Advanced settings” în formular. Dacă lipsesc, serverul are nevoie de OAuth.', 'Fixed headers: look for “Advanced settings” in the form. If there are none, the server needs OAuth.'),
        noHdr: L('Nu acceptă antete fixe documentate: serverul are nevoie de OAuth sau de acces fără cheie.', 'No documented fixed headers: the server needs OAuth or no auth.'),
        noSse: L('Doar Streamable HTTP. SSE nu este acceptat.', 'Streamable HTTP only. SSE is not supported.'),
        envSet: function () { return L('Setați tokenul în shell: export ' + env() + '=…', 'Set the token in your shell: export ' + env() + '=…'); },
        lit: L('Înlocuiți ' + TOK + ' cu tokenul. Nu publicați fișierul.', 'Replace ' + TOK + ' with the token. Do not commit the file.')
    };

    // ---------- clients ----------
    // Each: id, name, where, docs, cloud (connects from vendor cloud), sse:false when unsupported, nosupport,
    // build() -> { steps:[], snips:[{lbl, code}], notes:[L], buttons:[{href,label}] }. Service: SVC_OF below.

    function urlSnip() { return { lbl: 'URL', code: S.url }; }
    function authNotes(opts) {
        var n = [];
        if (S.auth === 'oauth') n.push(N.oauthUi);
        if (hasHdr()) n.push(opts && opts.hdr === false ? N.noHdr : N.hdrUi);
        return n;
    }

    var CLIENTS = [
        // ---------------- chat apps ----------------
        { id: 'claude', name: 'Claude', where: 'web · desktop · mobile', cloud: true,
          docs: 'https://support.claude.com/en/articles/11175166-get-started-with-custom-connectors-using-remote-mcp',
          build: function () { return {
            steps: ['claude.ai → Customize → Connectors → Add custom connector', 'Name: ' + nm() + ' · URL: paste', 'Chat: + → Connectors → enable ' + nm()],
            snips: [urlSnip()],
            notes: [L('Adăugat o dată, merge pe web, desktop, mobil și în Claude Code. Planul Free: un singur conector propriu. Doar portul 443.', 'Added once, it works on web, desktop, mobile and in Claude Code. Free plan: one custom connector. Port 443 only.'),
                    L('Team/Enterprise: un administrator îl adaugă din Organization settings → Connectors.', 'Team/Enterprise: an admin adds it in Organization settings → Connectors.')].concat(authNotes()) }; } },
        { id: 'chatgpt', name: 'ChatGPT', where: 'web', cloud: true,
          docs: 'https://help.openai.com/en/articles/12584461-connecting-custom-mcp-servers-in-chatgpt',
          build: function () { return {
            steps: ['Settings → Apps / Plugins → Advanced → enable Developer mode', '+ Add custom MCP server → name, URL, authentication', 'Chat: @' + nm() + ' or pick it from + → More'],
            snips: [urlSnip()],
            notes: [L('Complet pe Business/Enterprise/Edu (administratorul decide); Pro: doar citire. Doar pe web, nu din aplicația mobilă.', 'Full support on Business/Enterprise/Edu (admin-controlled); Pro: read-only tools. Web only, not from the mobile app.')].concat(authNotes({ hdr: false })) }; } },
        { id: 'chatgpt-desktop', name: 'ChatGPT', where: 'desktop (macOS)',
          docs: 'https://help.openai.com/en/articles/12584461-connecting-custom-mcp-servers-in-chatgpt',
          build: function () { return {
            steps: ['Settings → Integrations → Plugins → MCPs → Add', 'URL: paste' + (S.auth === 'bearer' ? ' · Bearer token env var: ' + env() : '') + (S.auth === 'header' ? ' · Headers from environment variables: ' + hName() + ' = ' + env() : '')],
            snips: [urlSnip()],
            notes: [L('Conexiunea pleacă de pe calculatorul dvs.: merge și cu adrese locale.', 'The connection starts from your computer: local URLs work too.')].concat(S.auth === 'oauth' ? [N.oauthUi] : []) }; } },
        { id: 'gemini', name: 'Gemini', where: 'web · mobile', cloud: true,
          docs: 'https://support.google.com/gemini/answer/17209137',
          build: function () { return {
            steps: ['gemini.google.com → Settings → Connected Apps', 'Custom apps → Add a custom app → URL → Next', 'Chat: @' + nm(), 'Check: gemini.google.com/devmode → Tool schemas'],
            snips: [urlSnip()],
            notes: [L('Restricționat: cont personal Google, 18+, SUA, engleză, istoric activat.', 'Restricted: personal Google account, 18+, US, English, history on.')].concat(
                    S.auth === 'oauth' ? [L('Fără înregistrare dinamică (DCR): Advanced features → client ID/secret.', 'Without dynamic registration (DCR): Advanced features → client ID/secret.')] : [],
                    hasHdr() ? [N.noHdr] : []) }; } },
        { id: 'grok', name: 'Grok', where: 'web · Grok desktop', cloud: true,
          docs: 'https://docs.x.ai/grok/connectors',
          build: function () { return {
            steps: ['Web: grok.com/connectors → New Connector → Custom → URL → authenticate', 'Desktop: Connect apps → Add a custom connector → Type: Remote HTTPS → Server URL' + (hasHdr() ? ' → HTTP headers' : '')],
            snips: [urlSnip()],
            notes: [L('Business/Enterprise: un administrator aprobă conectorul în console.x.ai.', 'Business/Enterprise: an admin approves the connector in console.x.ai.')].concat(
                    hasHdr() ? [L('Antete fixe: doar în aplicația desktop. Pe web: OAuth.', 'Fixed headers: desktop app only. On the web: OAuth.')] : [],
                    S.auth === 'oauth' ? [N.oauthUi] : []) }; } },
        { id: 'perplexity', name: 'Perplexity', where: 'web', cloud: true,
          docs: 'https://www.perplexity.ai/help-center/en/',
          build: function () { return {
            steps: ['Settings → Connectors → + Custom connector → Remote', 'URL; auth: ' + ({ none: 'None', oauth: 'OAuth', bearer: 'API key', header: 'API key' })[S.auth]],
            snips: [urlSnip()],
            notes: S.auth === 'header' ? [L('Verificați dacă formularul acceptă alt antet decât Authorization.', 'Check whether the form accepts a header other than Authorization.')] : [] }; } },
        { id: 'mistral', name: 'Le Chat (Mistral)', where: 'web', cloud: true,
          docs: 'https://help.mistral.ai/',
          build: function () { return {
            steps: ['chat.mistral.ai → Intelligence → Connectors → Add Connector', 'Custom MCP Connector → URL → authentication'],
            snips: [urlSnip()], notes: authNotes() }; } },
        { id: 'copilot-studio', name: 'Copilot Studio', where: 'Microsoft 365 agents', cloud: true,
          docs: 'https://learn.microsoft.com/en-us/microsoft-copilot-studio/mcp-add-existing-server-to-agent',
          build: function () { return {
            steps: ['Agent → Tools → Add a tool → New tool → Model Context Protocol', 'Server name, URL; auth: ' + ({ none: 'None', oauth: 'OAuth 2.0', bearer: 'API key (header)', header: 'API key → header ' + hName() })[S.auth]],
            snips: [urlSnip()], notes: [] }; } },
        { id: 'deepseek', name: 'DeepSeek', where: 'chat · API', cloud: true, nosupport: true,
          docs: 'https://api-docs.deepseek.com/',
          build: function () { return {
            steps: [],
            snips: [],
            notes: [L('Chat-ul și API-ul DeepSeek nu conectează servere MCP. Folosiți modelul DeepSeek într-un client MCP (OpenCode, Cline, Roo, Continue, LibreChat).', 'DeepSeek chat and API do not connect to MCP servers. Use the DeepSeek model inside an MCP client (OpenCode, Cline, Roo, Continue, LibreChat).')] }; } },

        // ---------------- CLI agents ----------------
        { id: 'claude-code', name: 'Claude Code', where: 'CLI · IDE',
          docs: 'https://code.claude.com/docs/en/mcp',
          build: function () {
            var cmd = 'claude mcp add --transport ' + S.t + ' --scope user ' + nm() + ' ' + S.url;
            if (hasHdr()) cmd += ' \\\n  --header "' + hName() + ': ' + hVal('$' + env()) + '"';
            var cfg = wrap('mcpServers', obj({ type: S.t, url: S.url }, { headers: headers('${' + env() + '}') }));
            var s = [{ lbl: 'Terminal', code: cmd }];
            if (S.auth === 'oauth') s.push({ lbl: L('Apoi, în Claude Code', 'Then, inside Claude Code'), code: '/mcp' });
            s.push({ lbl: L('Sau în proiect: .mcp.json', 'Or per project: .mcp.json'), code: J(cfg) });
            return { steps: [], snips: s, notes: [L('Conectorul adăugat pe claude.ai apare și aici, fără comandă.', 'A connector added on claude.ai shows up here too, with no command.')].concat(hasHdr() ? [N.envSet()] : []) }; } },
        { id: 'codex', name: 'Codex', where: 'CLI · IDE extension', sse: false,
          docs: 'https://developers.openai.com/codex/mcp',
          build: function () {
            var cmd = 'codex mcp add ' + nm() + ' --url ' + S.url;
            if (S.auth === 'bearer') cmd += ' \\\n  --bearer-token-env-var ' + env();
            var toml = '[mcp_servers.' + nm() + ']\nurl = "' + S.url + '"';
            if (S.auth === 'bearer') toml += '\nbearer_token_env_var = "' + env() + '"';
            if (S.auth === 'header') toml += '\nenv_http_headers = { "' + hName() + '" = "' + env() + '" }';
            var s = [];
            if (S.auth !== 'header') s.push({ lbl: 'Terminal', code: cmd });
            if (S.auth === 'oauth') s.push({ lbl: 'OAuth', code: 'codex mcp login ' + nm() });
            s.push({ lbl: '~/.codex/config.toml', code: toml });
            return { steps: [], snips: s, notes: [L('CLI-ul și extensia IDE folosesc același config.toml.', 'The CLI and the IDE extension share config.toml.')].concat(hasHdr() ? [N.envSet()] : []) }; } },
        { id: 'gemini-cli', name: 'Gemini CLI', where: 'CLI',
          docs: 'https://github.com/google-gemini/gemini-cli/blob/main/docs/tools/mcp-server.md',
          build: function () {
            var cmd = 'gemini mcp add --scope user --transport ' + S.t + ' ' + nm() + ' ' + S.url;
            if (hasHdr()) cmd += ' \\\n  -H "' + hName() + ': ' + hVal('$' + env()) + '"';
            var inner = {}; inner[S.t === 'http' ? 'httpUrl' : 'url'] = S.url;
            var cfg = wrap('mcpServers', obj(inner, { headers: headers('$' + env()) }));
            var s = [{ lbl: 'Terminal', code: cmd }];
            if (S.auth === 'oauth') s.push({ lbl: L('Apoi, în Gemini CLI', 'Then, inside Gemini CLI'), code: '/mcp auth ' + nm() });
            s.push({ lbl: '~/.gemini/settings.json', code: J(cfg) });
            return { steps: [], snips: s, notes: hasHdr() ? [N.envSet()] : [] }; } },
        { id: 'grok-cli', name: 'Grok CLI', where: 'CLI', sse: false,
          docs: 'https://docs.x.ai/build/features/mcp-servers',
          build: function () {
            var cmd = 'grok mcp add --transport http ' + nm() + ' ' + S.url;
            if (hasHdr()) cmd += ' \\\n  --header "' + hName() + ': ' + hVal('${' + env() + '}') + '"';
            return { steps: [], snips: [{ lbl: 'Terminal', code: cmd + '\ngrok mcp doctor ' + nm() }],
                     notes: (S.auth === 'oauth' ? [L('OAuth pornește automat la prima conectare.', 'OAuth starts automatically on first connection.')] : []).concat(hasHdr() ? [N.envSet()] : []) }; } },
        { id: 'copilot-cli', name: 'GitHub Copilot CLI', where: 'CLI',
          docs: 'https://docs.github.com/en/copilot/how-tos/use-copilot-agents/use-copilot-cli',
          build: function () {
            var cfg = wrap('mcpServers', obj({ type: S.t, url: S.url }, { headers: headers(TOK), tools: ['*'] }));
            return { steps: ['copilot → /mcp add → HTTP → URL'], snips: [{ lbl: '~/.copilot/mcp-config.json', code: J(cfg) }], notes: hasHdr() ? [N.lit] : [] }; } },
        { id: 'opencode', name: 'OpenCode', where: 'CLI · any model',
          docs: 'https://opencode.ai/docs/mcp-servers/',
          build: function () {
            var inner = obj({ type: 'remote', url: S.url, enabled: true }, { headers: headers('{env:' + env() + '}') });
            var cfg = { '$schema': 'https://opencode.ai/config.json', mcp: {} }; cfg.mcp[nm()] = inner;
            var s = [{ lbl: 'opencode.json', code: J(cfg) }];
            if (S.auth === 'oauth') s.push({ lbl: 'OAuth', code: 'opencode mcp auth ' + nm() });
            return { steps: [], snips: s, notes: [L('Funcționează cu orice model: DeepSeek, Qwen, modele locale.', 'Works with any model: DeepSeek, Qwen, local models.')].concat(hasHdr() ? [N.envSet()] : []) }; } },
        { id: 'qwen', name: 'Qwen Code', where: 'CLI',
          docs: 'https://qwenlm.github.io/qwen-code-docs/en/users/features/mcp/',
          build: function () {
            var cmd = 'qwen mcp add --transport ' + S.t + ' ' + nm() + ' ' + S.url;
            if (hasHdr()) cmd += ' \\\n  -H "' + hName() + ': ' + hVal('$' + env()) + '"';
            return { steps: [], snips: [{ lbl: 'Terminal', code: cmd }], notes: [L('Aceeași sintaxă ca Gemini CLI (~/.qwen/settings.json).', 'Same syntax as Gemini CLI (~/.qwen/settings.json).')] }; } },
        { id: 'kiro', name: 'Kiro', where: 'IDE · CLI',
          docs: 'https://kiro.dev/docs/mcp/',
          build: function () {
            var cfg = wrap('mcpServers', obj({ url: S.url }, { headers: headers(TOK) }));
            return { steps: [], snips: [{ lbl: '~/.kiro/settings/mcp.json', code: J(cfg) }], notes: hasHdr() ? [N.lit] : [] }; } },

        // ---------------- IDEs ----------------
        { id: 'vscode', name: 'VS Code (Copilot)', where: 'IDE',
          docs: 'https://code.visualstudio.com/docs/copilot/customization/mcp-servers',
          build: function () {
            var srv = obj({ type: S.t, url: S.url }, { headers: headers('${input:' + env().toLowerCase() + '}') });
            var cfg = { servers: {} }; cfg.servers[nm()] = srv;
            if (hasHdr()) cfg.inputs = [{ type: 'promptString', id: env().toLowerCase(), description: nm() + ' token', password: true }];
            var b = [];
            if (!hasHdr()) {
                var link = J(obj({ name: nm() }, { type: S.t, url: S.url })).replace(/\s+/g, '');
                b.push({ href: 'vscode:mcp/install?' + encodeURIComponent(link), label: L('Instalează în VS Code', 'Install in VS Code') });
                b.push({ href: 'vscode-insiders:mcp/install?' + encodeURIComponent(link), label: 'VS Code Insiders' });
            }
            return { steps: ['Command Palette → MCP: Add Server → HTTP → URL'], buttons: b,
                     snips: [{ lbl: '.vscode/mcp.json', code: J(cfg) }],
                     notes: hasHdr() ? [L('VS Code cere tokenul la pornire și îl păstrează criptat.', 'VS Code asks for the token on start and stores it encrypted.')] : [] }; } },
        { id: 'cursor', name: 'Cursor', where: 'IDE',
          docs: 'https://cursor.com/docs/context/mcp',
          build: function () {
            var srv = obj({ url: S.url }, { headers: headers('${env:' + env() + '}') });
            var b = [];
            if (!hasHdr()) b.push({ href: 'cursor://anysphere.cursor-deeplink/mcp/install?name=' + encodeURIComponent(nm()) + '&config=' + encodeURIComponent(btoa(JSON.stringify({ url: S.url }))), label: L('Adaugă în Cursor', 'Add to Cursor') });
            return { steps: [], buttons: b, snips: [{ lbl: L('~/.cursor/mcp.json (global) sau .cursor/mcp.json', '~/.cursor/mcp.json (global) or .cursor/mcp.json'), code: J(wrap('mcpServers', srv)) }],
                     notes: (S.auth === 'oauth' ? [L('Settings → MCP → Login.', 'Settings → MCP → Login.')] : []).concat(hasHdr() ? [N.envSet()] : []) }; } },
        { id: 'windsurf', name: 'Windsurf', where: 'IDE',
          docs: 'https://docs.windsurf.com/windsurf/cascade/mcp',
          build: function () {
            var srv = obj({ serverUrl: S.url }, { headers: headers('${env:' + env() + '}') });
            return { steps: ['Cascade → MCP servers → Configure (or edit the file)'], snips: [{ lbl: '~/.codeium/windsurf/mcp_config.json', code: J(wrap('mcpServers', srv)) }], notes: hasHdr() ? [N.envSet()] : [] }; } },
        { id: 'zed', name: 'Zed', where: 'editor',
          docs: 'https://zed.dev/docs/ai/mcp',
          build: function () {
            var srv = obj({ url: S.url }, { headers: headers(TOK) });
            return { steps: [], snips: [{ lbl: 'settings.json', code: J(wrap('context_servers', srv)) }],
                     notes: (S.auth === 'oauth' ? [L('Fără antet Authorization, Zed pornește OAuth.', 'Without an Authorization header, Zed starts OAuth.')] : []).concat(hasHdr() ? [N.lit] : []) }; } },
        { id: 'cline', name: 'Cline', where: 'VS Code extension',
          docs: 'https://docs.cline.bot/mcp/connecting-to-a-remote-server',
          build: function () {
            var srv = obj({ type: S.t === 'http' ? 'streamableHttp' : 'sse', url: S.url }, { headers: headers(TOK) });
            return { steps: ['MCP Servers → Remote Servers → Streamable HTTP → URL'], snips: [{ lbl: 'cline_mcp_settings.json', code: J(wrap('mcpServers', srv)) }],
                     notes: [L('Fără "type", Cline presupune SSE.', 'Without "type", Cline assumes SSE.')].concat(hasHdr() ? [N.lit] : []) }; } },
        { id: 'roo', name: 'Roo Code', where: 'VS Code extension',
          docs: 'https://docs.roocode.com/features/mcp/using-mcp-in-roo',
          build: function () {
            var srv = obj({ type: S.t === 'http' ? 'streamable-http' : 'sse', url: S.url }, { headers: headers('${env:' + env() + '}') });
            return { steps: [], snips: [{ lbl: '.roo/mcp.json', code: J(wrap('mcpServers', srv)) }], notes: hasHdr() ? [N.envSet()] : [] }; } },
        { id: 'continue', name: 'Continue', where: 'VS Code · JetBrains',
          docs: 'https://docs.continue.dev/customize/deep-dives/mcp',
          build: function () {
            var y = 'mcpServers:\n  - name: ' + nm() + '\n    type: ' + (S.t === 'http' ? 'streamable-http' : 'sse') + '\n    url: ' + S.url;
            if (hasHdr()) y += '\n    requestOptions:\n      headers:\n        ' + hName() + ': "' + hVal('${{ secrets.' + env() + ' }}') + '"';
            return { steps: [], snips: [{ lbl: 'config.yaml', code: y }], notes: [L('Uneltele MCP merg doar în modul Agent.', 'MCP tools work in Agent mode only.')] }; } },

        // ---------------- desktop / self-hosted ----------------
        { id: 'lmstudio', name: 'LM Studio', where: 'desktop · local models',
          docs: 'https://lmstudio.ai/docs/app/mcp',
          build: function () {
            var srv = obj({ url: S.url }, { headers: headers(TOK) });
            return { steps: ['Program → Install → Edit mcp.json'], snips: [{ lbl: 'mcp.json', code: J(wrap('mcpServers', srv)) }], notes: hasHdr() ? [N.lit] : [] }; } },
        { id: 'openwebui', name: 'Open WebUI', where: 'self-hosted',
          docs: 'https://docs.openwebui.com/features/mcp',
          build: function () { return {
            steps: ['Admin Settings → External Tools → + Add Server', 'Type: MCP (Streamable HTTP) → URL' + (hasHdr() ? ' → Auth: Bearer / headers' : '')],
            snips: [urlSnip()], notes: S.t === 'sse' ? [N.noSse] : [] }; } },
        { id: 'librechat', name: 'LibreChat', where: 'self-hosted',
          docs: 'https://www.librechat.ai/docs/configuration/librechat_yaml/object_structure/mcp_servers',
          build: function () {
            var y = 'mcpServers:\n  ' + nm() + ':\n    type: ' + (S.t === 'http' ? 'streamable-http' : 'sse') + '\n    url: ' + S.url;
            if (hasHdr()) y += '\n    headers:\n      ' + hName() + ': "' + hVal('${' + env() + '}') + '"';
            return { steps: ['UI: MCP Settings → Add MCP → URL'], snips: [{ lbl: 'librechat.yaml', code: y }],
                     notes: [L('Fără "type", LibreChat presupune SSE.', 'Without "type", LibreChat assumes SSE.')].concat(hasHdr() ? [N.envSet()] : []) }; } },
        { id: 'claude-desktop-local', name: L('Clienți doar stdio (punte mcp-remote)', 'stdio-only clients (mcp-remote bridge)'), where: 'Claude Desktop config · others',
          docs: 'https://www.npmjs.com/package/mcp-remote',
          build: function () {
            var args = ['-y', 'mcp-remote', S.url];
            var srv = { command: 'npx', args: args };
            if (S.t === 'sse') args.push('--transport', 'sse-only');
            if (hasHdr()) { args.push('--header', hName() + ':${AUTH_HEADER}'); srv.env = { AUTH_HEADER: hVal(TOK) }; }
            return { steps: [], snips: [{ lbl: 'claude_desktop_config.json / mcp.json', code: J(wrap('mcpServers', srv)) }],
                     notes: [L('Doar pentru clienți fără suport HTTP. În Claude Desktop folosiți Connectors. Necesită Node.js.', 'Only for clients without HTTP support. In Claude Desktop, use Connectors. Needs Node.js.')] }; } },

        // ---------------- APIs ----------------
        { id: 'anthropic-api', name: 'Claude API', where: 'Messages API (beta)', cloud: true,
          docs: 'https://platform.claude.com/docs/en/agents-and-tools/mcp-connector',
          build: function () {
            var srv = { type: 'url', url: S.url, name: nm() };
            if (S.auth === 'bearer' || S.auth === 'oauth') srv.authorization_token = TOK;
            var body = { model: 'claude-sonnet-5-5', max_tokens: 1024, messages: [{ role: 'user', content: question() }], mcp_servers: [srv], tools: [{ type: 'mcp_toolset', mcp_server_name: nm() }] };
            var c = 'curl https://api.anthropic.com/v1/messages \\\n  -H "x-api-key: $ANTHROPIC_API_KEY" \\\n  -H "anthropic-version: 2023-06-01" \\\n  -H "anthropic-beta: mcp-client-2025-11-20" \\\n  -H "content-type: application/json" \\\n  -d \'' + J(body) + '\'';
            return { steps: [], snips: [{ lbl: 'curl', code: c }],
                     notes: [N.cloud].concat(S.auth === 'header' ? [L('Acceptă doar un token Bearer (authorization_token), nu antete proprii.', 'Accepts a Bearer token only (authorization_token), not custom headers.')] : [], S.auth === 'oauth' ? [L('OAuth: obțineți tokenul în aplicația dvs. și trimiteți-l la fiecare cerere.', 'OAuth: get the token in your app and send it with every request.')] : []) }; } },
        { id: 'openai-api', name: 'OpenAI API', where: 'Responses API', cloud: true,
          docs: 'https://platform.openai.com/docs/guides/tools-connectors-mcp',
          build: function () {
            var tool = { type: 'mcp', server_label: nm(), server_url: S.url, require_approval: 'never' };
            if (S.auth === 'bearer' || S.auth === 'oauth') tool.authorization = TOK;
            if (S.auth === 'header') tool.headers = headers(TOK);
            var body = { model: 'gpt-5', tools: [tool], input: question() };
            var c = 'curl https://api.openai.com/v1/responses \\\n  -H "Authorization: Bearer $OPENAI_API_KEY" \\\n  -H "Content-Type: application/json" \\\n  -d \'' + J(body) + '\'';
            return { steps: [], snips: [{ lbl: 'curl', code: c }], notes: [N.cloud] }; } },
        { id: 'xai-api', name: 'xAI API', where: 'Responses API', cloud: true,
          docs: 'https://docs.x.ai/developers/tools/remote-mcp',
          build: function () {
            var tool = { type: 'mcp', server_label: nm(), server_url: S.url };
            if (S.auth === 'bearer' || S.auth === 'oauth') tool.authorization = TOK;
            if (S.auth === 'header') tool.headers = headers(TOK);
            var body = { model: 'grok-4', tools: [tool], input: question() };
            var c = 'curl https://api.x.ai/v1/responses \\\n  -H "Authorization: Bearer $XAI_API_KEY" \\\n  -H "Content-Type: application/json" \\\n  -d \'' + J(body) + '\'';
            return { steps: [], snips: [{ lbl: 'curl', code: c }], notes: [N.cloud] }; } },

        // ---------------- test / code ----------------
        { id: 'curl', name: L('Test rapid (curl)', 'Quick test (curl)'), where: 'initialize',
          docs: 'https://modelcontextprotocol.io/specification/latest/basic/transports',
          build: function () {
            var init = { jsonrpc: '2.0', id: 1, method: 'initialize', params: { protocolVersion: '2025-06-18', capabilities: {}, clientInfo: { name: 'curl', version: '0' } } };
            var c = 'curl -sS -X POST ' + S.url + ' \\\n  -H "Content-Type: application/json" \\\n  -H "Accept: application/json, text/event-stream" \\\n';
            if (hasHdr()) c += '  -H "' + hName() + ': ' + hVal('$' + env()) + '" \\\n';
            c += "  -d '" + JSON.stringify(init) + "'";
            return { steps: [], snips: [{ lbl: 'Terminal', code: c }],
                     notes: [L('Răspunsul corect conține serverInfo. 401 = lipsește autentificarea.', 'A good response contains serverInfo. 401 = authentication missing.')].concat(S.t === 'sse' ? [L('Testul este pentru Streamable HTTP.', 'This test is for Streamable HTTP.')] : []) }; } },
        { id: 'inspector', name: 'MCP Inspector', where: 'browser UI',
          docs: 'https://modelcontextprotocol.io/docs/tools/inspector',
          build: function () { return {
            steps: ['Transport: ' + (S.t === 'http' ? 'Streamable HTTP' : 'SSE') + ' → URL' + (hasHdr() ? ' → Authentication: header ' + hName() : '') + ' → Connect → Tools → List'],
            snips: [{ lbl: 'Terminal', code: 'npx @modelcontextprotocol/inspector' }], notes: [] }; } },
        { id: 'python', name: 'Python (SDK mcp)', where: 'pip install mcp',
          docs: 'https://github.com/modelcontextprotocol/python-sdk',
          build: function () {
            var imp = S.t === 'http' ? 'from mcp.client.streamable_http import streamablehttp_client as connect' : 'from mcp.client.sse import sse_client as connect';
            var h = hasHdr() ? '\nHEADERS = {"' + hName() + '": ' + (S.auth === 'bearer' ? '"Bearer " + ' : '') + 'os.environ["' + env() + '"]}' : '\nHEADERS = None';
            var unpack = S.t === 'http' ? '(read, write, _)' : '(read, write)';
            var c = 'import asyncio, os\nfrom mcp import ClientSession\n' + imp + '\n' + h +
                '\n\nasync def main():\n    async with connect("' + S.url + '", headers=HEADERS) as ' + unpack + ':\n' +
                '        async with ClientSession(read, write) as s:\n            await s.initialize()\n' +
                '            tools = await s.list_tools()\n            print([t.name for t in tools.tools])\n\nasyncio.run(main())';
            return { steps: [], snips: [{ lbl: 'client.py', code: c }], notes: S.auth === 'oauth' ? [L('OAuth: vezi OAuthClientProvider în SDK.', 'OAuth: see OAuthClientProvider in the SDK.')] : [] }; } },
        { id: 'typescript', name: 'TypeScript (SDK)', where: 'npm i @modelcontextprotocol/sdk',
          docs: 'https://github.com/modelcontextprotocol/typescript-sdk',
          build: function () {
            var http = S.t === 'http';
            var cls = http ? 'StreamableHTTPClientTransport' : 'SSEClientTransport';
            var mod = http ? 'streamableHttp.js' : 'sse.js';
            var opts = hasHdr() ? ', {\n  requestInit: { headers: { "' + hName() + '": ' + (S.auth === 'bearer' ? '`Bearer ${process.env.' + env() + '}`' : 'process.env.' + env()) + ' } },\n}' : '';
            var c = 'import { Client } from "@modelcontextprotocol/sdk/client/index.js";\nimport { ' + cls + ' } from "@modelcontextprotocol/sdk/client/' + mod + '";\n\n' +
                'const client = new Client({ name: "demo", version: "1.0.0" });\nawait client.connect(new ' + cls + '(new URL("' + S.url + '")' + opts + '));\n' +
                'console.log((await client.listTools()).tools.map(t => t.name));\nawait client.close();';
            return { steps: [], snips: [{ lbl: 'client.mjs', code: c }], notes: [] }; } }
    ];

    // ---------- service filter: popular services as pills, the rest in one "Others" dropdown ----------
    var SERVICES = [  // [key, label, pill?]
        ['claude', 'Claude', true], ['openai', 'ChatGPT / Codex', true], ['google', 'Gemini', true], ['xai', 'Grok', true],
        ['microsoft', 'VS Code / Copilot', true], ['cursor', 'Cursor', true],
        ['perplexity', 'Perplexity'], ['mistral', 'Mistral (Le Chat)'], ['deepseek', 'DeepSeek'], ['opencode', 'OpenCode'],
        ['qwen', 'Qwen Code'], ['kiro', 'Kiro'], ['windsurf', 'Windsurf'], ['zed', 'Zed'], ['cline', 'Cline'], ['roo', 'Roo Code'],
        ['continue', 'Continue'], ['lmstudio', 'LM Studio'], ['openwebui', 'Open WebUI'], ['librechat', 'LibreChat'],
        ['mcp-remote', 'mcp-remote (stdio)'], ['sdk', L('Test / SDK (curl, Python, TS)', 'Test / SDK (curl, Python, TS)')]
    ];
    var SVC_OF = {
        'claude': 'claude', 'claude-code': 'claude', 'anthropic-api': 'claude',
        'chatgpt': 'openai', 'chatgpt-desktop': 'openai', 'codex': 'openai', 'openai-api': 'openai',
        'gemini': 'google', 'gemini-cli': 'google', 'grok': 'xai', 'grok-cli': 'xai', 'xai-api': 'xai',
        'copilot-studio': 'microsoft', 'copilot-cli': 'microsoft', 'vscode': 'microsoft', 'cursor': 'cursor',
        'perplexity': 'perplexity', 'mistral': 'mistral', 'deepseek': 'deepseek', 'opencode': 'opencode', 'qwen': 'qwen', 'kiro': 'kiro',
        'windsurf': 'windsurf', 'zed': 'zed', 'cline': 'cline', 'roo': 'roo', 'continue': 'continue',
        'lmstudio': 'lmstudio', 'openwebui': 'openwebui', 'librechat': 'librechat', 'claude-desktop-local': 'mcp-remote',
        'curl': 'sdk', 'inspector': 'sdk', 'python': 'sdk', 'typescript': 'sdk'
    };
    CLIENTS.forEach(function (c) { c.svc = SVC_OF[c.id] || '?'; });
    function matches(cl) { return S.svc === 'all' || cl.svc === S.svc; }

    // ---------- verification status (CSV → {id: row}) ----------
    var ST = {
        'tested': ['ok', L('testat', 'tested')],
        'ui-confirmed': ['ok', L('confirmat în UI', 'UI confirmed')],
        'syntax-checked': ['mid', L('sintaxă verificată', 'syntax checked')],
        'docs': ['', L('doar din docs', 'docs only')],
        'unsure': ['bad', L('neverificat', 'unverified')]
    };
    function parseCsv(txt) {
        var rows = [], row = [], f = '', q = false;
        for (var i = 0; i < txt.length; i++) {
            var c = txt[i];
            if (q) { if (c === '"') { if (txt[i + 1] === '"') { f += '"'; i++; } else q = false; } else f += c; }
            else if (c === '"') q = true;
            else if (c === ',') { row.push(f); f = ''; }
            else if (c === '\n') { row.push(f); rows.push(row); row = []; f = ''; }
            else if (c !== '\r') f += c;
        }
        if (f || row.length) { row.push(f); rows.push(row); }
        var h = rows.shift() || [];
        var out = {};
        rows.forEach(function (r) { var o = {}; h.forEach(function (k, j) { o[k] = r[j] || ''; }); if (o.id) out[o.id] = o; });
        return out;
    }

    // ---------- HTML rendering ----------
    function esc(s) { return String(s).replace(/[&<>"']/g, function (c) { return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]; }); }
    function attrs(a) { return Object.keys(a || {}).map(function (k) { return a[k] == null ? '' : ' ' + k + '="' + esc(a[k]) + '"'; }).join(''); }
    function bi(tag, cls, v, a) {
        var inner = typeof v === 'string' ? esc(v)
            : '<span data-l="ro">' + esc(v.ro) + '</span><span data-l="en">' + esc(v.en) + '</span>';
        return '<' + tag + attrs(Object.assign({ class: cls || null }, a)) + '>' + inner + '</' + tag + '>';
    }
    function urlInfo() { try { return new URL(S.url); } catch (_) { return null; } }
    function isPublicHttps(u) {
        if (!u || u.protocol !== 'https:') return false;
        return !/^(localhost|127\.|10\.|192\.168\.|172\.(1[6-9]|2\d|3[01])\.|\[?::1\]?$|0\.0\.0\.0)/.test(u.hostname) && !/\.local$/.test(u.hostname);
    }

    function warningsHtml() {
        var out = [], u = urlInfo();
        var add = function (v, info) { out.push(bi('li', info ? 'info' : null, v)); };
        if (!u) { add(L('Adresa nu este un URL valid.', 'The address is not a valid URL.')); return out.join(''); }
        if (S.url === DEFAULT_URL) add(L('Serverul INS+: Streamable HTTP, fără cheie, doar citire. Lăsați „Fără” la autentificare.', 'INS+ server: Streamable HTTP, no key, read-only. Keep authentication on “None”.'), true);
        if (!isPublicHttps(u)) add(L('Adresa nu este HTTPS public: aplicațiile chat și API-urile din cloud nu o pot accesa. Folosiți un tunel (cloudflared, ngrok). Clienții locali (CLI, IDE) merg.', 'The URL is not public HTTPS: cloud chat apps and APIs cannot reach it. Use a tunnel (cloudflared, ngrok). Local clients (CLI, IDE) work.'));
        if (u.port && u.port !== '443') add(L('Port ' + u.port + ': conectorii Claude acceptă doar 443.', 'Port ' + u.port + ': Claude connectors accept 443 only.'));
        if (/\/sse\/?$/.test(u.pathname) && S.t === 'http') add(L('Adresa se termină cu /sse: probabil transportul este SSE.', 'The URL ends with /sse: the transport is probably SSE.'));
        if (S.t === 'sse') add(L('SSE este învechit. Unii clienți nu îl mai acceptă (marcați mai jos).', 'SSE is deprecated. Some clients no longer accept it (marked below).'));
        return out.join('');
    }

    // <option> cannot hold the per-language spans: it carries both labels and the page swaps the text.
    function opt(v, label, sel) {
        var l = typeof label === 'string' ? { ro: label, en: label } : label;
        var cur = typeof document !== 'undefined' && document.documentElement.lang === 'en' ? 'en' : 'ro';
        return '<option' + attrs({ value: v, selected: sel ? 'selected' : null, 'data-ro': l.ro, 'data-en': l.en }) + '>' + esc(l[cur]) + '</option>';
    }
    function chipsHtml() {
        var pill = function (key, label) { return bi('button', 'chip', label, { type: 'button', 'data-svc': key, 'aria-pressed': String(S.svc === key) }); };
        var others = SERVICES.filter(function (x) { return !x[2]; });
        var inOthers = others.some(function (x) { return x[0] === S.svc; });
        return pill('all', L('Toate', 'All')) +
            SERVICES.filter(function (x) { return x[2]; }).map(function (x) { return pill(x[0], x[1]); }).join('') +
            '<select class="chip" data-svc-other aria-label="' + esc('Altele / Others') + '"' + (inOthers ? ' aria-pressed="true"' : '') + '>' +
            opt('', L('Altele…', 'Others…'), !inOthers) +
            others.map(function (x) { return opt(x[0], x[1], S.svc === x[0]); }).join('') + '</select>';
    }

    function cardHtml(cl, status, pub) {
        var r = cl.build(), st = status[cl.id], sm = st && ST[st.status], h = [];
        h.push('<header>', bi('h2', null, cl.name), bi('span', 'where', cl.where));
        if (sm) h.push(bi('span', 'badge ' + sm[0], sm[1], { title: st.how_checked + (st.checked_on ? ' (' + st.checked_on + ')' : '') }));
        if (cl.nosupport) h.push(bi('span', 'badge bad', L('fără MCP', 'no MCP')));
        if (cl.sse === false && S.t === 'sse') h.push(bi('span', 'badge bad', L('fără SSE', 'no SSE')));
        if (cl.cloud && !pub && !cl.nosupport) h.push(bi('span', 'badge bad', L('cere HTTPS public', 'needs public HTTPS')));
        h.push('<a class="doclink" href="' + esc(cl.docs) + '" target="_blank" rel="noopener">docs ↗</a></header>');
        if (r.steps && r.steps.length) h.push('<ol>' + r.steps.map(function (s) { return bi('li', null, s); }).join('') + '</ol>');
        if (r.buttons && r.buttons.length) h.push('<div class="btnrow">' + r.buttons.map(function (b) { return bi('a', 'btn', b.label, { href: b.href }); }).join('') + '</div>');
        (r.snips || []).forEach(function (s) {
            h.push('<div class="snip">', bi('p', 'lbl', s.lbl), '<pre><code>' + esc(s.code) + '</code></pre><button type="button" class="copy">copy</button></div>');
        });
        if (cl.sse === false && S.t === 'sse') h.push(bi('p', 'note warn', N.noSse));
        (r.notes || []).forEach(function (n) { h.push(bi('p', 'note', n)); });
        if (st && st.uncertain) h.push('<p class="note unsure">' + bi('b', null, L('Neverificat: ', 'Unverified: ')) + esc(st.uncertain) + '</p>');
        return '<article class="cc" id="c-' + esc(cl.id) + '">' + h.join('') + '</article>';
    }

    function cardsHtml(status) {
        var pub = isPublicHttps(urlInfo());
        var html = CLIENTS.filter(matches).map(function (cl) { return cardHtml(cl, status || {}, pub); }).join('\n');
        return html || bi('p', 'empty', L('Niciun client pentru acest filtru.', 'No client matches this filter.'));
    }

    function setState(st) { S = Object.assign({}, DEFAULTS, st || {}); }

    var api = { DEFAULTS: DEFAULTS, setState: setState, parseCsv: parseCsv, cardsHtml: cardsHtml, chipsHtml: chipsHtml, warningsHtml: warningsHtml, CLIENTS: CLIENTS };
    if (typeof module === 'object' && module.exports) { module.exports = api; return; }
    global.McpConnect = api;
    if (typeof document === 'undefined') return;

    // ---------- browser ----------
    var $ = function (id) { return document.getElementById(id); };
    var STATUS = {};
    // The build script writes the JSON between comment markers; drop them before parsing.
    try { STATUS = JSON.parse((($('mcp-status') || {}).textContent || '').replace(/<!--[\s\S]*?-->/g, '') || '{}'); } catch (_) {}

    var qs = new URLSearchParams(location.search), init = {};
    Object.keys(DEFAULTS).forEach(function (k) { if (qs.get(k)) init[k] = qs.get(k); });
    if (init.t && init.t !== 'sse') delete init.t;
    if (init.auth && ['oauth', 'bearer', 'header'].indexOf(init.auth) < 0) delete init.auth;
    setState(init);

    function saveState() {
        var p = new URLSearchParams(location.search);
        Object.keys(DEFAULTS).forEach(function (k) { if (S[k] && S[k] !== DEFAULTS[k]) p.set(k, S[k]); else p.delete(k); });
        var q = p.toString();
        try { history.replaceState(null, '', location.pathname + (q ? '?' + q : '') + location.hash); } catch (_) {}
    }
    function render() {
        $('w-hdr').hidden = S.auth !== 'header';
        $('w-env').hidden = !(S.auth === 'bearer' || S.auth === 'header');
        $('warns').innerHTML = warningsHtml();
        $('chips').innerHTML = chipsHtml();
        $('cards').innerHTML = cardsHtml(STATUS);
    }
    function copyText(txt, btn) {
        var done = function () { var o = btn.textContent; btn.textContent = '✓'; setTimeout(function () { btn.textContent = o; }, 1200); };
        function fallback() { var ta = document.createElement('textarea'); ta.value = txt; ta.style.position = 'fixed'; ta.style.opacity = '0'; document.body.appendChild(ta); ta.select(); try { document.execCommand('copy'); done(); } catch (_) {} ta.remove(); }
        if (navigator.clipboard && window.isSecureContext) navigator.clipboard.writeText(txt).then(done, fallback); else fallback();
    }

    var F = { url: 'f-url', name: 'f-name', t: 'f-t', auth: 'f-auth', hdr: 'f-hdr', env: 'f-env' };
    Object.keys(F).forEach(function (k) {
        var inp = $(F[k]); inp.value = S[k];
        inp.addEventListener('input', function () { S[k] = inp.value.trim(); saveState(); render(); });
    });
    $('f-reset').addEventListener('click', function () {
        ['url', 'name', 't', 'auth'].forEach(function (k) { S[k] = DEFAULTS[k]; $(F[k]).value = S[k]; });
        saveState(); render();
    });
    $('chips').addEventListener('click', function (e) {
        var b = e.target.closest('button[data-svc]'); if (!b) return;
        S.svc = b.getAttribute('data-svc'); saveState(); render();
    });
    $('chips').addEventListener('change', function (e) {
        if (!e.target.hasAttribute('data-svc-other')) return;
        S.svc = e.target.value || 'all'; saveState(); render();
    });
    $('cards').addEventListener('click', function (e) {
        var b = e.target.closest('.copy'); if (!b) return;
        copyText(b.previousElementSibling.textContent, b);
    });
    render();
})(this);
