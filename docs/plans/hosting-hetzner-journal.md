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

## Next

1. Owner: `sudo mkdir -p $V/pax && sudo chown pax:pax $V/pax`; `systemctl disable --now nordvpnd.socket`.
2. `ins-vps` (go-ahead sent 21:2x): deletions 1-3, npm cache, the moves with symlinks; stop :8765.
4. Update the plan: releases, logs and swap on the volume; `deploy.sh` checks free space on the
   release filesystem; `OOMScoreAdjust` so scrapers are killed before the API; narrow sudoers rule
   for `systemctl restart tempo-api` (owner to confirm).
5. Continue HZ-2: user, directories, `cloudflared`, first deploy (dry run first).
