# HZ — Move the API and public MCP from Fly to the owner's Hetzner VPS

**Status: draft brief (2026-11-15), waiting for the owner's answers in "Open questions".**
Written by Opus. HZ-1 is for a Sonnet session. HZ-2 to HZ-4 change a server and DNS, so each one
needs the owner's explicit go-ahead.

## Why

The public MCP was not promoted because it timed out on Fly. AQ-07A
([record](ask-and-public-mcp/remaining/aq-07-record.md)) measured the process at 372-376 MiB on a
cold start and 464 MiB warm (macOS), on a 512 MB machine. Smaller DuckDB caps did not lower it.
The owner's VPS has 2 vCPU, 4 GB RAM, 40 GB local disk and a 15 GB volume. The UI stays on DreamHost
(`ins.gov2.ro`, static). Only `api-ins.gov2.ro` (API, Ask, `/mcp`) moves.

## Decisions (Opus, 2026-11-15)

- **Docker, built on the VPS.** The image is the one `release-check.py --docker` smokes. Building
  on the VPS gives native amd64 and needs no Docker on the Mac. No venv or systemd unit for the app.
- **One uvicorn worker.** The MCP gate, caches and measured profile are per worker. Two workers is
  a later, measured decision.
- **Cloudflare stays in front.** The firewall accepts 80/443 only from Cloudflare's published IP
  ranges, plus SSH. TLS between Cloudflare and the VPS uses a Cloudflare Origin Certificate
  ("Full (strict)"), so no ACME challenge goes through the proxy.
- **Client identity:** set `TEMPO_MCP_TRUST_FORWARDED=true`. The reverse proxy must set
  `X-Forwarded-For` to `CF-Connecting-IP` (overwrite, do not append). This is safe only with the
  firewall rule above. Drop the Fly hostname from `TEMPO_MCP_ALLOWED_HOSTS` (audit MCP-08).
- **Data and logs on the 15 GB volume:** `deploy-data/` (about 1 GB) as the current and previous
  release, and `/logs` for content logs.
- **Fly stays up, unchanged, until HZ-4 passes.** Then the owner decides whether to delete it.

## HZ-1 — Deployment files (local; Sonnet)

Add `scripts/deploy/hetzner/` with:
1. `compose.yaml`: the app image built from the repo `Dockerfile`; `mem_limit` from the profile;
   `restart: unless-stopped`; port 8080 bound to `127.0.0.1` only; volumes for `/app/data`
   (read-only) and `/logs`; `env_file: api.env`.
2. `api.env`: the production profile. Start from `scripts/deploy/fly/mcp-public.env`; change only
   what this brief names. Keep its measurement comments.
3. A reverse-proxy snippet for whichever proxy the VPS already runs (see open questions), with the
   origin certificate, `CF-Connecting-IP` → `X-Forwarded-For`, and the request body limit.
4. `deploy.sh <ssh-host>`: rsync the code and the staged `deploy-data/` (with `MANIFEST.json`) to
   a new release directory, build, swap a symlink, `compose up -d`, run the smoke, and switch back
   to the previous release when the smoke fails. Dry run by default; `--apply` to act.
5. `README.md`: first-time setup (Docker, firewall, certificate, volume), deploy, rollback, reading
   the logs, and updating Cloudflare's IP list.

Rules: no change to `app/`, the `Dockerfile` or the Fly files. If the `Dockerfile` must change,
stop and report. Test what can be tested locally: shell syntax, `docker compose config` if Docker
exists (else `not_run`), and a test that `api.env` keeps the Fly profile's keys except those named.

## HZ-2 — Provision and deploy (owner present)

Inventory first, read-only: OS, CPU architecture, free disk, the volume mount, open ports, running
services and existing proxies. Stop and report a conflict before installing anything. Then install
Docker, set the firewall, place the certificate, deploy with `--apply`, and smoke on the VPS:
`release-check.py --local` equivalents and `scripts/mcp_probe.py` against `127.0.0.1:8080`.

## HZ-3 — Measure on Linux

On the VPS, run `scripts/benchmark-mcp.py run --mode container --container-memory 512m`, then 1g.
This closes the Linux gate that AQ-07A left `not_run`. Choose `mem_limit` from the measured peak
with at least 50% headroom. Run the 10 live questions of 2026-11-15 through a test hostname.

## HZ-4 — Cutover (owner)

Point `api-ins.gov2.ro` at the VPS in Cloudflare. Probe `/mcp` with a non-browser User-Agent and
check that Cloudflare's Browser Integrity Check (error 1010) does not block MCP clients; add a
rule for `/mcp` if it does. Watch memory, restarts and `MCP_METRICS` for one week before promoting
the MCP. Rollback: point DNS back to Fly.

## Open questions for the owner

1. Which OS runs on the VPS, and is it x86 (CX line) or ARM (CAX line)?
2. What else runs there? Is there a reverse proxy (nginx, Caddy, Traefik) that holds 80/443?
3. Is Docker already installed? Is the 15 GB volume mounted, and where?
4. Do you manage the firewall with Hetzner Cloud Firewall, `ufw`, or something else?
5. How do I reach it: an SSH alias from this Mac, and a user with sudo?
