# Hosting split and cutover runbook

**Status: runbook only, written 2026-10-16. Nothing here has been run. Ship when
AT-02/AT-03 (and the Ask key-redaction fix) are accepted.** Deploying, DNS changes and
uploads each need the owner's explicit go-ahead.

## Target topology

| Hostname | Served by | Purpose |
|---|---|---|
| `ins.gov2.ro` | DreamHost shared hosting (static build) | the site people use |
| `api-ins.gov2.ro` | Fly app `tempo-ins-explorer` | Ask API (`/api/ask*`), public MCP (`/mcp`), REST/SDMX |
| other `*.gov2.ro` | DreamHost shared hosting | unrelated sites, unchanged |

- DNS for `gov2.ro` is at **Cloudflare** (since 2026-10-16), not DreamHost. Every
  site record is **DNS only (grey cloud)**. `mail` and `ftp` must never be proxied.
  Cloudflare's import missed all subdomains; they were re-added from the old DreamHost
  zone.
- `api-ins` is one level deep, not `api.ins`, because Cloudflare's Universal SSL covers
  only `*.gov2.ro`. Fly serves its own certificate for it (keep it grey-cloud first;
  a proxied hop may buffer the NDJSON stream and cuts requests at about 100 s).
- Each DreamHost site has its own IP. The server hostname's IP
  (`iad1-shared-b7-17.dreamhost.com`) does not serve HTTP. Take the site IP from the
  DreamHost panel, not from the server name. DreamHost no longer updates these IPs for
  you now that DNS is external.
- Check state with `dig +short <name>.gov2.ro @igor.ns.cloudflare.com`; resolvers cache
  the old delegation for a while.

## Decisions before shipping

1. **Code and data.** Fly image and static build come from the **same commit and the same
   generation** (`9b3e065d…`, `../tempo-gen-20261012/data`). The earlier static build
   (`47ac900`) predates the Ask and UI work: rebuild it.
2. **Ask exposure.** Bring-your-own-key (`TEMPO_ASK_BYOK_ENABLED`) costs the operator
   nothing. Server-funded Ask needs `fly secrets set <PROVIDER>_API_KEY=…` and a budget.
   Neither goes public before the key-redaction P1 in `docs/BACKLOG.md` is fixed.
3. **Order.** Fly serves `ins.gov2.ro` today, so `fly deploy` replaces the live site
   immediately. To avoid that, do C and D before B.

## A. Code (small, before any build)

- `askApiBase` in the generated `config.js`; `ask.js` uses it instead of relative
  `/api/ask` and `/api/ask/stream`.
- CORS restricted to `https://ins.gov2.ro` through an env var (`app/main.py` has
  `allow_origins=["*"]`).
- Request keys are redacted before Ask events are logged.
- `TEMPO_MCP_ENABLED` / `TEMPO_PUBLIC_BASE_URL=https://api-ins.gov2.ro` set only when the
  MCP ships.

## B. Fly (`api-ins.gov2.ro`)

```bash
source ~/devbox/envs/240826/bin/activate
export TEMPO_CORPUS_SRC=~/devbox/gov2/tempo-gen-20261012/data/corpus
bash scripts/prepare-deploy-data.sh
python scripts/release-check.py --source "$TEMPO_CORPUS_SRC"   # validates stage, runs tests
fly auth login
# fly.toml [env]: Ask/MCP switches, CORS origin, TEMPO_PUBLIC_BASE_URL
fly deploy                                  # or: release-check.py --docker --deploy
```

- Verify: `curl -sI https://api-ins.gov2.ro/api/ask/config` (404 on the old code),
  `fly logs`, `fly status`.
- The 512 MB machine is unproven (a local run reached about 1.2 GiB RSS). Watch for
  restarts; do not enlarge it silently.
- MCP clients can time out on a cold start: consider `min_machines_running = 1` once
  `/mcp` is live.
- Rollback: `fly releases`, redeploy the previous image.

## C. Static site on DreamHost

```bash
TEMPO_DATA_DIR=~/devbox/gov2/tempo-gen-20261012/data \
  python scripts/build-static.py --out ../tempo-gen-20261012/static --base-url https://ins.gov2.ro
python scripts/release-check.py --static ../tempo-gen-20261012/static
scripts/deploy-static.sh ../tempo-gen-20261012/static USER@iad1-shared-b7-17.dreamhost.com ins.gov2.ro        # dry run
scripts/deploy-static.sh ../tempo-gen-20261012/static USER@iad1-shared-b7-17.dreamhost.com ins.gov2.ro --go
```

1. The upload creates `~/ins.gov2.ro/releases/<gen>-<commit>/` and a `current` symlink.
   Shell access must be enabled for `USER`.
2. DreamHost panel: **Manage Domains → ins.gov2.ro → Edit**, web directory
   `ins.gov2.ro/current` (keeps `releases/` out of public view).
3. Take the site IP from the panel. Test before the DNS change:
   `curl -sI --resolve ins.gov2.ro:80:<IP> http://ins.gov2.ro/`.

## D. Cutover (DNS, not an HTTP redirect)

1. Cloudflare: change the `ins` **A** record to the DreamHost IP, DNS only.
2. **Delete the `ins` AAAA record**, otherwise IPv6 visitors keep reaching Fly.
3. DreamHost: enable HTTPS (Let's Encrypt) for `ins.gov2.ro`. It probably needs the name
   to resolve to DreamHost first, so expect a short certificate warning (unverified).
4. Verify: `curl -sI https://ins.gov2.ro/` shows no `server: Fly`;
   `https://ins.gov2.ro/build.json` shows the expected commit and generation;
   `/api/` returns 404 from the static `.htaccess`.
5. After 24–48 h: `fly certs remove ins.gov2.ro -a tempo-ins-explorer`. **Keep the
   `api-ins` certificate.**

Rollback: restore `ins` A `66.241.124.71` and AAAA `2a09:8280:1::f3:e56d:0`, or repoint
`current` at the previous release directory.

## Later: ETL on a VPS

- Cron `update-pipeline.py` nightly under `flock -n /var/lock/tempo.lock` (DuckDB has one
  writer); `--global-profiles` weekly. It exits 1 on a required failure; ping
  healthchecks.io or mail on failure.
- The VPS builds a candidate generation; release stays manual: `release-check.py`,
  `deploy-static.sh --go`, `fly deploy --remote-only`. Automate later with
  `fly tokens create deploy` and a restricted rsync key.
- Make the VPS the only corpus writer. rsync `data/` once and compare generation ids
  with `scripts/audit-corpus.py`. Size the disk for `data/4-datasets` (6.6 GB) and
  `data/corpus` (about 0.9 GB) with headroom.
- Before migrating, fetch a few matrices from the VPS: INS may throttle datacenter IPs.
