# Hetzner VPS deployment (HZ)

Plan: [docs/plans/hosting-hetzner.md](../../../docs/plans/hosting-hetzner.md). These files serve
`api-ins.gov2.ro` (API, Ask, `/mcp`) from a Hetzner VPS: Python venv, systemd, Cloudflare Tunnel.
No Docker. Fly stays up until HZ-4 passes. Nothing here has run on the VPS yet.

| File | Install as |
|---|---|
| `tempo-api.service` | `/etc/systemd/system/tempo-api.service` |
| `api.env` | `/etc/tempo/api.env` (owner root, group tempo, mode 0640) |
| `cloudflared.yml` | `/etc/cloudflared/config.yml` (fill in the tunnel id) |
| `tempo-logrotate` | `/etc/logrotate.d/tempo` |
| `deploy.sh` | run from the Mac checkout; not installed |

## Client identity (HZ-1 finding)

The MCP per-client windows use `_client_key` in `app/services/public_mcp.py:708-719`. The order is:
`Fly-Client-IP` (line 711-713), then the first `X-Forwarded-For` entry only when
`TEMPO_MCP_TRUST_FORWARDED=true` (lines 714-717), then the peer address (718-719).

What `cloudflared` sends to the origin:
- `CF-Connecting-IP`: the visitor address. Cloudflare sets it. This is the documented header to use
  ([Cloudflare HTTP request headers](https://developers.cloudflare.com/fundamentals/reference/http-request-headers/)).
- `X-Forwarded-For`: a client-supplied value is kept and the visitor address is appended at the
  end. Reported for cloudflared 2025.2.0 with this example: client sends `a,b,c`, origin gets
  `a,b,c,203.0.113.1` ([cloudflared issue 1426](https://github.com/cloudflare/cloudflared/issues/1426),
  open when read). Without a client value, it equals `CF-Connecting-IP`.
- Not verified on a live tunnel: HZ-2 must check it (`curl -H 'X-Forwarded-For: 1.2.3.4'` and log
  the headers).

Result for the app behind the tunnel:
- With `TRUST_FORWARDED=true`, the key is the FIRST `X-Forwarded-For` entry, which the client
  writes. A client can pick any key. Do not set it.
- `Fly-Client-IP` is not stripped by Cloudflare or `cloudflared`, so a client can send it. The app
  reads it only on Fly (`FLY_APP_NAME` set), where Fly's proxy overwrites it. On the VPS it is
  ignored (decision and change, Opus review 2026-11-16; test
  `test_fly_client_ip_is_ignored_off_fly`).
- With `TRUST_FORWARDED=false` and no `Fly-Client-IP`, the key is the peer address. The service uses
  `--proxy-headers --forwarded-allow-ips 127.0.0.1`. uvicorn then takes the right-most
  `X-Forwarded-For` entry that is not loopback (the entry `cloudflared` appended), which is the real
  visitor. A client cannot forge that entry. (uvicorn 0.44 `ProxyHeadersMiddleware`,
  `get_trusted_client_host`.)

Setting in `api.env`: `TEMPO_MCP_TRUST_FORWARDED=false`. The global request window, the
one-operation gate and the scan cap do not depend on the client key and still apply.

Not chosen: a `TEMPO_MCP_CLIENT_IP_HEADER` setting. uvicorn's right-most rule already gives the real
visitor, so a new setting adds nothing while `TRUST_FORWARDED=false`. Never set `FLY_APP_NAME` on the
VPS.

## First-time setup (HZ-2, as root on the VPS, owner present)

1. Check first, read-only: `df -h / /mnt/*`, scraper peak memory, `ufw status`, the Hetzner Cloud
   Firewall in the console, `ss -tlnp`. Stop if scraper peak plus 1 GB does not fit in 4 GB.
   On gov2-1 (2026-11-16): `/` is nearly full, so `/opt/tempo` lives on the volume; 2 GB swap is on
   the volume; the Hetzner Cloud Firewall allows SSH and ICMP only. See `docs/plans/hosting-hetzner-journal.md`.
2. User and directories (replace `deployer` with the SSH user that runs `deploy.sh`; on gov2-1: `pax`).
   On gov2-1, put `/opt/tempo` on the volume with a bind mount (a real directory for systemd):
   ```
   V=/mnt/HC_Volume_105444571
   mkdir -p $V/tempo /opt/tempo
   echo "$V/tempo /opt/tempo none bind,nofail,x-systemd.requires-mounts-for=$V 0 0" >> /etc/fstab
   systemctl daemon-reload && mount /opt/tempo && findmnt /opt/tempo
   ```
   Then:
   ```
   useradd --system --home-dir /opt/tempo --shell /usr/sbin/nologin tempo
   mkdir -p /opt/tempo/releases /var/log/tempo /etc/tempo
   chown deployer: /opt/tempo /opt/tempo/releases
   chown tempo:tempo /var/log/tempo
   apt install -y python3.12-venv rsync curl
   ```
   The service user only reads `/opt/tempo`. It writes only `/var/log/tempo` and `/var/cache/tempo`
   (DuckDB spill files, `TEMPO_DUCKDB_TEMP_DIR`; systemd creates it from `CacheDirectory=`).
3. Install the config files from the table above. Then `systemctl daemon-reload`,
   `systemctl enable tempo-api`. Do not start it before the first deploy.
4. Allow the deploy user to restart the service:
   `echo 'deployer ALL=(root) NOPASSWD: /usr/bin/systemctl restart tempo-api' > /etc/sudoers.d/tempo-deploy`,
   then `chmod 0440 /etc/sudoers.d/tempo-deploy && visudo -c`. `deploy.sh` restarts over a
   non-interactive SSH session, which cannot ask for a password. Owner decision 2026-11-17: yes.
5. Firewall: allow inbound SSH only. On gov2-1 the Hetzner Cloud Firewall already does this
   (TCP 22 and ICMP inbound, outbound open), so no change. No inbound HTTP port is needed.
6. Tunnel: install `cloudflared`, run `cloudflared tunnel login` and
   `cloudflared tunnel create tempo-api` (the owner logs in), fill in `cloudflared.yml`, then
   `cloudflared service install`. DNS stays on Fly until HZ-4.

## Deploy

On the Mac, in the repository checkout:
```
bash scripts/prepare-deploy-data.sh        # stage deploy-data/ with MANIFEST.json
bash scripts/deploy/hetzner/deploy.sh <ssh-host>            # dry run
bash scripts/deploy/hetzner/deploy.sh --apply <ssh-host>    # deploy
```
`deploy.sh` refuses to run when the filesystem of `/opt/tempo` has under 5 GB free. A release is code, a venv and data in
`/opt/tempo/releases/<date>-<generation>`. Each release has its own venv and its own `home/` with the
DuckDB `fts` extension, so a rollback needs no network. Data files are hard-linked to the previous
release when unchanged. Expect about 2.5 GB in steady state and 3.7 GB during a deploy.
The venv must not hold pandas, numpy or pyarrow; the script fails the release if it does.
If the smoke fails, `current` does not move. If the health check fails after the swap, the script
swaps back and restarts the previous release. Set `SMOKE_ARGS` to change the smoke flags (default:
`--require-clean-audit --accept-restriction conflicting_grain`) only with the owner's approval.

## Rollback

```
ls -1 /opt/tempo/releases
ln -sfn /opt/tempo/releases/<previous> /opt/tempo/current.new && mv -Tf /opt/tempo/current.new /opt/tempo/current
sudo systemctl restart tempo-api
```
To leave the VPS altogether, point `api-ins.gov2.ro` back to Fly in Cloudflare (HZ-4 rollback).

## Logs

- `journalctl -u tempo-api -f`: service output, including `MCP_METRICS` and `ASK_METRICS` lines.
- `/var/log/tempo/mcp-calls.jsonl` and `ask-chats.jsonl`: full questions and results. Only users with
  access to the VPS can read them. Keep copies out of shared places.
- The app rotates `mcp-calls.jsonl` (`TEMPO_MCP_LOG_MAX_BYTES`). `tempo-logrotate` rotates
  `ask-chats.jsonl` weekly or at 100 MB, 4 copies, with `copytruncate`.
- To stop content logs, remove `TEMPO_MCP_LOG_CALLS` and `TEMPO_ASK_LOG_CHATS` from `api.env` and restart.

## Memory: scrapers and the API

The VPS has 4 GB. The scrapers and the API share it. `MemoryMax=1G` in the service file limits the API
as one cgroup; the kernel kills the API, not the scrapers, if it passes the limit. If the whole VPS
runs out of memory, `OOMScoreAdjust=-300` makes the kernel kill a scraper first; the 2 GB swap file
absorbs short peaks before that. The measured
profile is 372-464 MiB on macOS. HZ-3 measures it on Linux with the scrapers running
(`cat /sys/fs/cgroup/system.slice/tempo-api.service/memory.peak`; systemd 255 may not show
`MemoryPeak`) and sets the final `MemoryMax=` (peak plus at least 50 percent).
Check `systemctl status tempo-api` for restarts after any scraper run.

## Not tested yet

`systemd-analyze verify tempo-api.service` (Linux only), the real tunnel headers, and the whole deploy
on the VPS. `deploy.sh` was checked with `bash -n` and a dry run against fake `ssh` and `rsync`.
