# Journal — MCP readiness and the move to the Hetzner VPS

Running log of the work that started on 2026-11-15. Plan: [hosting-hetzner.md](hosting-hetzner.md).
Times are UTC. Sessions: `ins-local` (Mac, this repo, Opus), Sonnet agents started by it, and
`ins-vps` (Claude on the VPS `gov2-1`, over Remote Control).

## 2026-11-15 — local MCP tests

- **Release smoke** (`release-check.py --local --stage deploy-data --source data/corpus --skip-tests`):
  passed. Warnings: 734 non-canonical staged parquets; 160 `conflicting_grain` datasets;
  `registered_unemployment_county` refused at the 1M scan cap (known P1; production uses 5M).
- **Live session:** 10 questions (RO/EN) from the audit findings, run with Sonnet through headless
  `claude -p` against `scripts/serve-mcp-test.sh` (:8090). 36 tool calls, no errors, slowest 1.25 s.
  Correct: births ask for a definition; national unemployment 3.3% (INS cell); Cluj 1.2%; vintage
  warning used for domicile population; overlapping teacher levels not summed; series breaks
  reported. Weak: "doctors per county" took 12 turns (SAN104A read as women only; SAN104B_judet
  refused for conflicting grain). The concept note's "differs by up to ~10%" for births is unverified.
- **Owner:** the MCP was not promoted because it timed out on Fly (infra), not for answer quality.
- **Diagnosis:** locally `discover_indicators` has a median of 47 ms; on Fly it passed the 10 s
  deadline. `min_machines_running = 1` has been live since 2026-10-28, so a cold start is unlikely.
  Hypothesis: memory starvation on the 512 MB machine.

## 2026-11-15 — AQ-07 (MCP footprint)

- **07A** (Sonnet): peak RSS 372-376 MiB cold, 464 MiB warm (macOS). Smaller DuckDB caps changed
  nothing measurable; the Fly profile now sets search 64 MB and main 128 MB (ceiling 480 → 352 MB).
- **Correction (Opus):** production installs no pandas/numpy/pyarrow. The 0.4 s first-call import
  and about 71 MiB came from the development venv. Realistic production peak: 300-390 MiB.
- **07B** (Sonnet): period bounds come from the distinct-period read when the parquet footer proves
  no NULL value. Identical output on all 4,110 datasets; 0.1-0.2 s saved per call on the Mac.
- Owner decisions recorded in the backlog: deterministic dataset cards (LLM only for search
  phrasings), after the answer-quality eval; split the repo into pipeline and serving, MCP with
  serving, after the Hetzner move.

## 2026-11-15/16 — Hetzner plan and HZ-1

- **Plan:** only `api-ins.gov2.ro` moves to the owner's VPS; the UI stays on DreamHost. Owner asked
  why Docker; decision: venv + systemd (`MemoryMax`), Cloudflare Tunnel, no inbound HTTP port.
- **HZ-1** (Sonnet): `scripts/deploy/hetzner/` (service, `api.env`, tunnel example, `deploy.sh`,
  logrotate, README) and a test. **Review fixes (Opus):** `Fly-Client-IP` is read only on Fly
  (`FLY_APP_NAME`), so a client cannot pick its own window behind the tunnel; the service may write
  the releases, because DuckDB spills next to each database file.
- Full suite before merging: 2,365 passed. Merged to `main` and pushed. **CI on `main` has collected
  no tests since 2026-10-28** (`requests`/`tqdm` missing in `requirements-dev.txt`; backlog P1).

## 2026-11-16 — VPS inventory (`ins-vps`, read-only)

- `gov2-1`: Hetzner CX, x86_64, 2 vCPU, 3.8 GB RAM, **no swap**, Ubuntu 24.04, systemd 255.
- Disk: `/` 38 GB, **4.0 GB free**. The 15 GB volume `/mnt/HC_Volume_105444571` was **empty**.
  The plan had said "volume nearly full"; that was wrong.
- Memory: peak about 3.36 GiB used (sysstat, 5-minute samples, includes interactive sessions).
  Spikes around 17:00-17:10 UTC. Postgres about 334 MB RSS.
- Both HZ-2 stop rules tripped (free disk, memory). Nothing was installed.
- **Firewall:** Hetzner Cloud Firewall `firewall-1` on `gov2-1`: inbound TCP 22 and ICMP only,
  outbound open. Probe from the Mac: 22 open; 80, 5432 and 8765 filtered. The `http.server` on
  :8765 (monitorulpreturilor site) is not reachable from outside.
- SSH from the Mac to `pax@78.46.142.169` works with keys. `pax` needs a password for sudo.

## 2026-11-16 — disk inspection, backup and clean-up

- **Inspection** (`ins-vps`): `/home/pax` 25 GB, of which `g2-dev` 21 GB. Largest: `prices.db`
  9.9 GB (live), `posturi.gov.ro/data/downloads` 2.8 GB, stiri snapshots 1.3 GB, monitorulpreturilor
  dumps 1.25 GB, `audit-export-2026-10-12` 1.2 GB. Postgres holds one database, `posturi` (973 MB).
  Nothing was copied off the server before today.
- **Owner (sudo):** `/var/lib/postgresql` 2.0 GB, `/var/log` 1.8 GB. `pg_dumpall` to the volume:
  `backup/pg_dumpall-2026-11-16.sql.gz`, 223 MB. `journalctl --vacuum-size=200M` freed 1.4 GB.
- **Backup** (`ins-local`, from 19:35): to `/Volumes/geana/NAS-devbox/gov2-1/2026-11-16/` (HFS+).
  `sqlite-dumps/`: consistent `.dump` of prices.db, news.db, avize.db, posturi.sqlite and
  alerts.sqlite (the three large ones use WAL, so the dump does not block the scrapers).
  `home-pax/`: rsync of `/home/pax` without the live databases, venvs, caches, `node_modules` and
  the Claude binaries. `volume-backup/`: the Postgres dump (gzip test passed). Cron stayed active.
  Script: `backup-gov2-1.sh` in the session scratchpad. **Result (21:25): complete.** Dumps
  19:35-20:12, all gzip-tested (prices.db 885 MB compressed, 33 min). rsync 20:13-21:25: 75,923 files,
  11.5 GB, about 2.7 MB/s. Dry-run check: 9 changed entries, all logs, a lock file and the VPS Claude
  session's own files.
- **Owner (sudo):** 2 GB swap file on the volume (`sw,nofail` in fstab), `vm.swappiness=10`; after:
  3.8 GB RAM, 2.2 GB available, swap unused. `nordvpnd` disabled; its socket was still active, so
  `nordvpnd.socket` must be disabled as well.
- **Owner decisions:**
  1. Delete the two older Claude versions (673 MB): yes.
  2. stiri snapshots (backups on the same disk): do not keep. Note: stiri's pipeline creates one
     each day; its retention is in that project.
  3. Delete `stiri/data/annotations.db.corrupt-20261028`: yes.
  4. `posturi.gov.ro/data/downloads`: leave for now.
  5. `nordvpnd`: not needed for now; disable it (reinstall later if needed).
  6. Stop the `http.server` on :8765.
  7. Journal vacuum: done.
  Moves to the volume (from the proposal, not objected to): `audit-export-2026-10-12`,
  `posturi-2026-11-15.sql.gz`, monitorulpreturilor `data/backups` (symlink back), `prices_ci.db`,
  `posturi.pre-v4.sqlite`, `schema-pre-v4*.csv`.

## 2026-11-16 — plan revised for the volume

- `deploy.sh` checks free space on `/opt/tempo`, not `/`. The README sets up `/opt/tempo` as a bind
  mount of `$V/tempo` on the volume. The service has `OOMScoreAdjust=-300`. The Hetzner Cloud Firewall
  already allows SSH only, so the README's `ufw` step is not needed on gov2-1.
- Owner: `$V/pax` created; `nordvpnd` and `nordvpnd.socket` inactive. Free on `/`: 5.4 GB before the
  `ins-vps` clean-up (expected about 10.6 GB after).

## 2026-11-16 — clean-up done (`ins-vps`)

- Free on `/`: 4.0 GB → **11 GB**. Volume: 5.0 GB used (swap 2.1 GB, Postgres dump 0.2 GB, moved files
  2.8 GB), 9.0 GB free.
- Deleted: Claude 2.1.322 and 2.1.323 (673 MB; 2.1.325 runs); the 7 stiri snapshots (1.3 GB; folder
  kept); `annotations.db.corrupt-20261028`; `~/.npm/_cacache` (344 MB); stale crontab backups.
- Moved to `$V/pax` with a symlink at each old path: `audit-export-2026-10-12`, `posturi-2026-11-15.sql.gz`,
  monitorulpreturilor `data/backups` (its Sunday script writes through the link; it aborts if the volume
  is not mounted), `prices_ci.db`, `posturi.pre-v4.sqlite`, `schema-pre-v4*.csv`.
- Stopped the `http.server` on :8765 (started by hand; nothing restarts it).
- stiri: owner chose `BACKUP_KEEP=1`. `ins-vps` appended it to `~/g2-dev/stiri/.env` (untracked);
  `config()` reads 1. Its comment says "backup also kept off-box": true only for the one-time backup of
  2026-11-16. No recurring off-box backup exists (backlog).
- `ins-vps` pulled `main` (fast-forward to 771f06f).

## 2026-11-17 — HZ-2 setup prepared (`ins-local`)

- VPS state (read-only, over SSH): no `tempo` user, no `/opt/tempo`, `/etc/tempo` or service.
  `python3.12-venv`, `rsync` and `curl` already installed. Free: `/` 11 GB, volume 9 GB.
- **Owner:** narrow sudoers rule, yes: `pax` may run only `/usr/bin/systemctl restart tempo-api`
  without a password. `deploy.sh` restarts over a non-interactive SSH session, so it needs the rule.
- **Finding (Opus):** the service user cannot write the releases (`pax`, mode `a+rX`), and
  `ReadWritePaths` does not grant Unix permissions. A DuckDB spill next to a database file then
  fails (`Failed to create directory "<db>.tmp": Permission denied`, reproduced). **Owner:** new
  app setting `TEMPO_DUCKDB_TEMP_DIR` (`app/db.py:duckdb_config`) on the main, scratch and search
  connections. The service sets it to `/var/cache/tempo/duckdb` (`CacheDirectory=tempo`) and no
  longer lists `/opt/tempo/releases` as writable. Tests in `tests/test_hz1_hetzner_deploy.py`.

- **Owner** ran `hz2-root-setup.sh` (README steps 2-4): `/opt/tempo` bind-mounted from the volume
  (`/dev/sdb[/tempo]`), `tempo` user (uid 996), service installed and enabled (not started), sudoers
  rule parsed. Checked: `sudo -n` runs only `systemctl restart tempo-api`; all else asks for a password.
- `deploy-data/` is current (generation `062bd2b0`, the one Fly serves); no restaging.
- **Dry run found two first-deploy bugs in `deploy.sh`** (fixed): `readlink -f` printed
  `/opt/tempo/current` when it did not exist, so `--apply` would fail on `--link-dest` and a failed
  health check would "swap back" to itself (now `readlink -e`); empty `--link-dest` arrays were
  unbound under `set -u` in macOS bash 3.2. Dry run now clean.

- **First deploy** (`--apply`, owner go-ahead, 01:31 local): release `20261117-013142-062bd2b0`. Smoke
  passed (strict). Warnings as on 2026-11-15; the `registered_unemployment_county` refusal comes from
  the smoke's 1M cap; under `api.env` (5M) the recipe answers (42 counties, 2025). Service active,
  `/api/health` ok, MCP on with call logging, spill dir `/var/cache/tempo` owned by `tempo`.
  Volume after: 6.2 GB used, 7.9 GB free.
- **Live checks on the VPS** (loopback, `Host: api-ins.gov2.ro`): `initialize` 5 ms, 8 tools listed.
  `/mcp` with `Host: 127.0.0.1` answers 421 (host guard; `mcp_probe.py` cannot set the Host, so use
  curl or the tunnel). `discover_indicators`: new queries 0.6-3.8 s (Mac median 47 ms), repeats 8 ms
  (cache). For HZ-3: measure warm latency; suspect first reads from the network volume.
  cgroup memory peak 257 MiB after these calls (limit 1 GiB).

- **Tunnel** (owner): `cloudflared` 2026.11.0 from Cloudflare's apt repo; tunnel `tempo-api`
  `3881fb85-6ad9-4848-af0f-a86d3c065049`; `hz2-tunnel-setup.sh` installed the credentials and
  `/etc/cloudflared/config.yml` (same as `scripts/deploy/hetzner/cloudflared.yml`) and the service;
  4 connections registered (fra08/16/10/17, QUIC).
- **Cutover (HZ-4) done by the owner, about 23:50 UTC on 2026-11-16**, without a test hostname
  (owner: nobody uses the MCP yet). Owner deleted A `66.241.124.71` (DNS only) and AAAA
  `2a09:8280:1::f3:e56d:0` (proxied) and added a proxied Tunnel record to `tempo-api`. Rollback:
  restore those two records. The `_acme-challenge` CNAME for Fly stays.
- **Checks from the Mac:** `/api/health` 200 via Cloudflare (no Fly headers), generation `062bd2b0`.
  CORS preflight from `https://ins.gov2.ro` 200 with the right origin; `/api/ask/config` BYOK
  available. MCP: the official Python SDK (httpx) lists 8 tools, `discover_indicators` 0.7-0.9 s;
  curl and node user agents pass. **`Python-urllib` gets 403, Cloudflare error 1010** (Browser
  Integrity Check), so `scripts/mcp_probe.py` fails from outside. Fix is in Cloudflare (owner).
- **Owner:** Cloudflare Page Rule `api-ins.gov2.ro/*` → Browser Integrity Check: Off (legacy Page
  Rule; a Configuration Rule is the modern equivalent). The Page Rules screen warned the host may not
  be proxied: false alarm, it does not recognise the Tunnel record type. After it, `mcp_probe.py
  https://api-ins.gov2.ro POP112A_grupe` passes from the Mac (8 tools, `describe_dataset` ok,
  structured == text).
- **Client IP behind the tunnel: verified** (owner ran `tcpdump -i lo` while the Mac sent requests with
  forged `X-Forwarded-For: 1.2.3.4` and `Fly-Client-IP: 5.6.7.8`). uvicorn received
  `X-Forwarded-For: 1.2.3.4,<real IP>` and `Cf-Connecting-Ip: <real IP>`. With
  `--forwarded-allow-ips 127.0.0.1`, uvicorn takes the right-most entry, the real visitor; the app
  ignores `Fly-Client-IP` off Fly. The MCP per-client key cannot be forged.

## 2026-11-17 — HZ-3 measurements (Sonnet agent, reviewed by Opus)

Record: [hz-3-record.md](hz-3-record.md). Nothing on the live service changed.
- Benchmark on Linux with the `api.env` settings: all checks passed; peak RSS 294 MiB; live cgroup peak
  283 MiB, 0 restarts. First `discover_indicators` in a fresh process p50 1.55 s (Mac 0.74 s); warm miss
  p50 0.29 s (Mac 0.10 s).
- Latency gap: mainly CPU (a Python loop is 2.8 times slower than on the Mac; iowait 1.2% during new
  queries). The network volume adds cold-read cost; the idle service had 189 MiB in swap.
- 10 live questions through the tunnel: no regression, no transport errors; Q01 now answers.
- **Watch:** one `query_timeout` (10.6 s) while the benchmark started on the same two vCPUs. The 10 s
  deadline has less headroom here than on the Mac.
- **Opus review:** accepted. `MemoryMax` stays 1G until the end of the observation week (Ask load not
  measured; 2.8 GB available on the host). Proposed next step for the owner: `MemorySwapMax=0` for
  `tempo-api`, so the idle service stays in RAM.

- **Owner applied `MemorySwapMax=0`** (08:45 UTC): installed the service file from `bf91fbf`, restarted.
  Check: `memory.swap.max` 0, `memory.swap.current` 0 (223 MiB before), `memory.current` 123 MiB,
  `MemoryMax` 1G, public `/api/health` 200.

## 2026-11-17 — Static site on DreamHost (`ins-local`)

The site was rebuilt from `183a36f` and switched to a releases layout: `~/ins.gov2.ro/current`,
the October build kept as `releases/20261028-8d95a7c`. Details: `docs/activity-history.md`,
`docs/DEPLOY-STATIC.md`. Ask on `ins.gov2.ro` now calls the VPS through the tunnel.

## Hand-over (for a new session)

Read this journal, [hosting-hetzner.md](hosting-hetzner.md) and `scripts/deploy/hetzner/README.md`.
HZ-2, the HZ-4 cutover and HZ-3 are done; `api-ins.gov2.ro` runs on gov2-1. SSH from the Mac:
`pax@78.46.142.169`, key-based; deploys restart the service through the narrow sudoers rule; any
other sudo command is the owner's. Open items are in `docs/BACKLOG.md` ("NEXT — HZ-3"):
- Observation week until about 2026-11-24: `memory.peak`, restarts, `query_timeout` in
  `/var/log/tempo/mcp-calls.jsonl`; then set the final `MemoryMax`.
- Retire Fly (copy its `/logs` first); Page Rule → Configuration Rule.
- Not yet tested: a second `deploy.sh` run (hard links) and the swap-back.
