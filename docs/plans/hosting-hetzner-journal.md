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
- Open (owner, stiri project): `BACKUP_KEEP` defaults to 7 (`ops/preflight.py:39`), so about 1.25 GB of
  snapshots returns to `/` within a week. Options: `BACKUP_KEEP=1`, `BACKUP_DIR` on the volume, or leave.

## Hand-over (for a new session)

Read this journal, [hosting-hetzner.md](hosting-hetzner.md) and `scripts/deploy/hetzner/README.md`.
The VPS session is `ins-vps` (Remote Control; message it by name; repo at
`/home/pax/g2-dev/tempo-ins-dump`; it pulls `main`). SSH from the Mac: `pax@78.46.142.169`, key-based;
`pax` needs a password for sudo, so the owner runs every sudo command. Open items:
- Not yet decided by the owner: the narrow sudoers rule for `systemctl restart tempo-api`
  (without it, each deploy asks for the password).
- Then HZ-2 setup, README "First-time setup" steps 2-4 and 6 (bind mount, user and directories,
  config files, sudoers, `cloudflared` with the owner's Cloudflare login), then the first deploy from
  the Mac: `prepare-deploy-data.sh`, then `deploy.sh pax@78.46.142.169` as a dry run, then `--apply`.

## Next

1. Owner: `sudo mkdir -p $V/pax && sudo chown pax:pax $V/pax`; `systemctl disable --now nordvpnd.socket`.
2. `ins-vps` (go-ahead sent 21:2x): deletions 1-3, npm cache, the moves with symlinks; stop :8765.
4. Plan update: done (see above). Sudoers rule: owner to confirm.
5. Continue HZ-2 in a new session (see Hand-over).
