# HZ — Move the API and public MCP from Fly to the owner's Hetzner VPS

**Status: brief (2026-11-15, revised the same day after the owner's answers).**
Written by Opus. HZ-1 is for a Sonnet session on the Mac. HZ-2 and HZ-3 run in a Claude session
that the owner starts on the VPS. HZ-4 is the owner's. Each of HZ-2 to HZ-4 needs the owner's
explicit go-ahead.

## Why

The public MCP was not promoted because it timed out on Fly. AQ-07A
([record](ask-and-public-mcp/remaining/aq-07-record.md)) measured the process at 372-376 MiB on a
cold start and 464 MiB warm (macOS), on a 512 MB machine. Smaller DuckDB caps did not lower it.
Only `api-ins.gov2.ro` (API, Ask, `/mcp`) moves. The UI stays on DreamHost (`ins.gov2.ro`).

## The VPS (owner, 2026-11-15)

Hetzner CX (x86), 2 vCPU, 4 GB RAM, 40 GB local disk, Ubuntu 24.04.4 LTS. **Corrected 2026-11-16:**
the local disk `/` was nearly full (4 GB free) and the 15 GB volume was empty. Scrapers run from cron;
nothing serves the web; no Docker. The Hetzner Cloud Firewall allows inbound SSH and ICMP only.
Details and the clean-up: [journal](hosting-hetzner-journal.md).

## Decisions (Opus, 2026-11-15)

- **No Docker.** A Python 3.12 venv (Ubuntu 24.04's own Python) and a systemd service. Reasons:
  the disk is tight (an image plus layers holds a second copy of the 1 GB data), and systemd
  gives the two things Docker would: `MemoryMax=` (cgroup limit, protects the scrapers) and a
  separate user. The release gate is `release-check.py --local`, run on the VPS.
- **One uvicorn worker.** The MCP gate, caches and measured profile are per worker.
- **Cloudflare Tunnel (`cloudflared`), not a public web server.** The VPS dials out to Cloudflare.
  No inbound HTTP port, no certificate, no Cloudflare IP list. uvicorn listens on `127.0.0.1` only.
  The firewall allows inbound SSH only.
- **Client identity behind the tunnel.** The MCP's per-client windows read `Fly-Client-IP`, or the
  first `X-Forwarded-For` entry when `TEMPO_MCP_TRUST_FORWARDED=true`. HZ-1 must establish which
  header `cloudflared` sends (`CF-Connecting-IP` for certain; `X-Forwarded-For` to verify) and
  whether a client can forge the value the app reads. If the app needs to read `CF-Connecting-IP`,
  that is a small app change: stop and report it for an Opus decision; do not make it.
- **Disk (revised 2026-11-16):** releases live on the volume, bind-mounted at `/opt/tempo`, so the
  service paths stay the same: `/opt/tempo/releases/<id>` (code + data, about 1.5 GB each), a
  `current` symlink, keep two releases. `deploy.sh` checks free space on that filesystem. Logs stay in
  `/var/log/tempo` on `/` (small, rotated). 2 GB swap is on the volume; the service has
  `OOMScoreAdjust=-300`, so a scraper is killed before the API if the VPS runs out of memory.
- **Production installs no pandas, numpy or pyarrow** (not in `requirements.txt` or its 50
  dependencies). DuckDB imports pandas only when it is installed, so the venv must not add it:
  AQ-07A's 0.4 s first-call import and about 71 MiB came from the development venv.
- **Fly stays up, unchanged, until HZ-4 passes.** Rollback is a DNS switch back to Fly.

## HZ-1 — Deployment files (Sonnet, on the Mac)

Add `scripts/deploy/hetzner/`, modelled on `scripts/deploy/oracle/` (older; do not edit it):
1. `tempo-api.service`: user `tempo`; `WorkingDirectory` and `TEMPO_DATA_DIR` under
   `/opt/tempo/current`; `EnvironmentFile=/etc/tempo/api.env`; one worker on `127.0.0.1:8080`;
   `MemoryMax=` from the profile (start at 1G; HZ-3 sets the final value); `Restart=always`.
2. `api.env`: the production profile, from `scripts/deploy/fly/mcp-public.env`. Change only:
   `TEMPO_ASK_LOG_DIR`, `TEMPO_MCP_ALLOWED_HOSTS` (drop the Fly hostname; audit MCP-08), and
   `TEMPO_MCP_TRUST_FORWARDED` per the decision above. Keep its measurement comments.
3. `cloudflared.yml` example: one ingress rule, `api-ins.gov2.ro` → `http://127.0.0.1:8080`.
4. `deploy.sh <ssh-host>`: rsync code and the staged `deploy-data/` (with `MANIFEST.json`) to a
   new release directory; create or refresh the venv; install the DuckDB `fts` extension offline
   (as the `Dockerfile` does); run the smoke against the new release on another port; then swap
   `current`, restart, re-smoke, and swap back if the smoke fails. Dry run by default; `--apply`.
   Use `rsync --link-dest` against the previous release so unchanged data files are hard links.
   Keep two releases; delete the oldest only after the new one passes. Refuse to start when the
   filesystem of `/opt/tempo` has less than 5 GB free.
5. `logrotate` config for the log directory.
6. `README.md`: first-time setup (user, directories, venv, firewall, tunnel), deploy, rollback,
   reading logs, and how the scrapers and the API share memory.

Rules: no change to `app/`, the `Dockerfile` or the Fly files. Test locally what can be tested:
`bash -n`, `systemd-analyze verify` if available (else `not_run`), and a test that `api.env`
keeps every key of the Fly profile except those named above.

## HZ-2 — Provision and deploy (VPS session, owner present)

Inventory first, read-only: free disk on `/` (5 GB needed: about 2.5 GB in steady state, 3.7 GB
during a deploy) and the volume, memory used by the scrapers (peak, not
only now), firewall state (`ufw status`, Hetzner Cloud Firewall in the console), open ports. Stop
and report before installing anything if the scrapers' peak memory plus 1 GB does not fit in 4 GB.
Then: create the user and directories, set the firewall to SSH only, install `cloudflared` and
create the tunnel (the owner logs in to Cloudflare), deploy with `--apply`, and run
`release-check.py --local --stage <release>/data` and `scripts/mcp_probe.py` on the VPS.

Data transfer: the VPS session cannot pull from the Mac. The owner (or the Mac session) runs
`deploy.sh` from the Mac, which rsyncs the staged release over SSH.

## HZ-3 — Measure on Linux

On the VPS, run `scripts/benchmark-mcp.py run --mode local` against the service settings, with
the scrapers running. Record peak RSS and cgroup memory (`systemctl show -p MemoryPeak`). This
closes the Linux gate that AQ-07A left `not_run`. Set `MemoryMax=` to the peak plus at least 50%.
Then run the 10 live questions of 2026-11-15 through a test hostname on the tunnel.

## HZ-4 — Cutover (owner)

Point `api-ins.gov2.ro` at the tunnel in Cloudflare. Probe `/mcp` with a non-browser User-Agent and
check that Browser Integrity Check (error 1010) does not block MCP clients; add a rule for `/mcp`
if it does. Watch memory, restarts and `MCP_METRICS` for one week before promoting the MCP.
Rollback: point DNS back to Fly.

## HZ-6 — Cloudflare rules for the public API launch (owner, dashboard)

Written by Opus on 2026-11-25. The API page (`/api.html`) promotes `api-ins.gov2.ro` to anyone.
Cloudflare does not cache the API (`cf-cache-status: DYNAMIC`), so every request reaches the VPS
(2 vCPU). The REST API has no rate limit of its own; `/mcp` has its own per-worker gate. The page
promises "a per-IP limit; a `429` means wait and retry", so these rules make that true.

All rules go in the `gov2.ro` zone and match only `http.host eq "api-ins.gov2.ro"`.

1. **Rate limiting rule** (Security → WAF → Rate limiting rules). The Free plan allows one rule,
   a 10-second period and a 10-second block.
   - Name: `api-ins per-IP limit`.
   - Expression: `(http.host eq "api-ins.gov2.ro")`.
   - Characteristic: IP. Limit: 60 requests per 10 seconds. Action: Block for 10 seconds.
     Cloudflare answers `429`.
   - On a paid plan, add a second, stricter rule: 10 requests per minute for
     `/api/datasets/*/download` and `/api/ask*`, because those are the expensive routes.
2. **Configuration rule** (Rules → Configuration rules) for the same expression: Browser Integrity
   Check **off**, Security Level **essentially off**. API clients send plain User-Agents; the 2026-10
   Fly setup returned error 1010 to `python-urllib`. Today `Python-urllib` and `python-requests`
   both get 200, so this rule only keeps it that way.
3. **Check zone-wide settings:** Bot Fight Mode must stay **off** (it challenges `curl`, Python and
   MCP clients, and the Free plan cannot scope it to one host). Do not turn on "Under Attack" for the
   zone without a skip rule for `api-ins`.
4. **No cache rule.** Responses depend on the served generation. Keep them DYNAMIC.

Verify from the Mac after you save:

```bash
for i in $(seq 1 80); do curl -s -o /dev/null -w "%{http_code}\n" https://api-ins.gov2.ro/api/health; done | sort | uniq -c
# expect mostly 200, then some 429; after 10 s, 200 again
curl -s -o /dev/null -w "%{http_code}\n" -A "Python-urllib/3.12" https://api-ins.gov2.ro/api/datasets?limit=1   # 200
python scripts/mcp_probe.py https://api-ins.gov2.ro/mcp   # check its --help for the exact flags first
```

The app keys nothing on the client IP for REST, so no app change is needed. Record the rule values
in `hz-3-record.md` once applied.
