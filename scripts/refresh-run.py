#!/usr/bin/env python3
"""Weekly data refresh: build a candidate release, gate it, notify (HZ-5a).

One entry point for cron. It never touches the served release (`current`), the working
generation (BASE/data) or DreamHost. The owner approves a candidate with
`scripts/deploy/hetzner/promote.sh <run-id>`.

Layout (BASE defaults to /opt/tempo/pipeline):
  BASE/data/             the working generation (no 4-datasets: raw CSVs are never kept)
  BASE/runs/<run-id>/    one run: data/ (copy; corpus/parquet hard-linked), release/ (candidate:
                         code/ + data/ staged), static/, logs/, sweep/ (temporary)
  BASE/status.json       the last run (outcome, steps, timings, peak memory, counts)
  BASE/run.lock          one run at a time

Steps, in order (the first failure of a required step stops the run, keeps the run folder):
  probe -> space -> copy -> feed (update-pipeline.py --drop-csv --global-profiles) -> sweep
  (monthly) -> retired-children cleanup -> INS KPI checks of the touched codes -> compact DB ->
  generation manifest -> audit report -> stage -> release-check --local (strict) -> static build
  -> API cases -> release-check --static -> candidate -> status + notification.

Schedule: cron runs it every day at 03:00. A run is due on Sunday, or on a later day while the
previous due run is still pending (INS did not answer, or a step failed). It gives up after
--max-retry-days days with a notification. `--force` ignores the schedule.

  python scripts/refresh-run.py --base BASE [--since DD.MM.YYYY] [--matrix A,B] [--force]
         [--static-codes A,B] [--simulate-probe-failure] [--dry-run]
Environment: TEMPO_NOTIFY_URL (a webhook; POST of a short text; unset: stdout only).
"""
import argparse
import fcntl
import json
import os
import re
import resource
import shutil
import subprocess
import sys
import threading
import time
import urllib.request
from datetime import date, datetime, timedelta
from pathlib import Path

CODE = Path(__file__).resolve().parent.parent
STRICT_FLAGS = ["--require-clean-audit", "--accept-restriction", "conflicting_grain"]
# Files of the candidate release's code folder: what deploy.sh uploads.
CODE_FILES = ["requirements.txt", "llms.txt", "sdmx_labels.py", "fly.toml",
              "scripts/release-check.py", "scripts/mcp_probe.py"]
CODE_DIRS = ["app"]
# Top-level entries of the working data that a run never copies.
NOT_COPIED = {"4-datasets", "4-datasets-slim-samples", "parquet-v2", "_archive", "quarantine", "eval"}
API_CASES_CODES = "POP105A_judete_grupe,FOM106E_judete,SOM103A_judete,TUR105D_judete,ART124A,SOM101E"
SWEEP_EVERY_DAYS = 28
MIN_FREE_GB = 5


# --------------------------------------------------------------------------- small helpers
def log(msg: str) -> None:
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)


def atomic_json(path: Path, obj) -> None:
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(obj, indent=1, sort_keys=True, default=str) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def read_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def dir_bytes(path: Path) -> int:
    """Disk use, hard links counted once per call."""
    seen, total = set(), 0
    for p in path.rglob("*"):
        try:
            st = p.lstat()
        except OSError:
            continue
        if p.is_file() and not p.is_symlink() and (st.st_dev, st.st_ino) not in seen:
            seen.add((st.st_dev, st.st_ino))
            total += st.st_size
    return total


def free_gb(path: Path) -> float:
    return shutil.disk_usage(path).free / 1e9


def notify(text: str) -> None:
    """Print, and POST to TEMPO_NOTIFY_URL when set. A failure here never fails the run."""
    log("NOTIFY: " + text.replace("\n", " | "))
    url = os.environ.get("TEMPO_NOTIFY_URL")
    if not url:
        return
    try:
        req = urllib.request.Request(url, data=text.encode("utf-8"), method="POST",
                                     headers={"Content-Type": "text/plain; charset=utf-8", "Title": "TEMPO refresh"})
        urllib.request.urlopen(req, timeout=20).read()
    except Exception as e:  # noqa: BLE001
        log(f"notification failed (ignored): {type(e).__name__}: {e}")


# --------------------------------------------------------------------------- schedule
def is_due(today: date, status: dict, max_retry_days: int, force: bool) -> tuple[bool, str]:
    """Sunday, or a retry day while a due run is pending (and fewer than max_retry_days old)."""
    if force:
        return True, "forced"
    pending = status.get("pending_since")
    if pending:
        age = (today - date.fromisoformat(pending)).days
        if age >= max_retry_days:
            return False, f"gave up: pending since {pending} ({age} days)"
        return True, f"retry day {age + 1} (pending since {pending})"
    if today.weekday() == 6:
        return True, "Sunday"
    return False, "not Sunday and nothing pending"


# --------------------------------------------------------------------------- run copy
def copy_working_data(src: Path, dst: Path) -> None:
    """Copy BASE/data to the run, sharing only corpus/parquet by hard link.

    Everything else is copied (DuckDB files, metas, view profiles, indexes: small), so a stage
    that writes one of them in place cannot touch the working generation. Parquet files are
    replaced by rename in stage 9 and stage 12 (audit in docs/plans/hz-5-record.md); the live-tree
    guard (snapshot/compare) proves it on every run. Logs: only the state files."""
    dst.mkdir(parents=True)
    for entry in sorted(src.iterdir()):
        name = entry.name
        if name in NOT_COPIED or name.startswith("."):
            continue
        if name == "logs":
            (dst / "logs").mkdir()
            for f in ("update-pipeline-state.json", "last-pipeline-run.txt"):
                if (entry / f).exists():
                    shutil.copy2(entry / f, dst / "logs" / f)
        elif name == "corpus":
            for sub in sorted(entry.iterdir()):
                if sub.name == "parquet":
                    (dst / "corpus" / "parquet").mkdir(parents=True)
                    for p in sub.iterdir():
                        os.link(p, dst / "corpus" / "parquet" / p.name)
                elif sub.is_dir():
                    shutil.copytree(sub, dst / "corpus" / sub.name)
                else:
                    (dst / "corpus").mkdir(exist_ok=True)
                    shutil.copy2(sub, dst / "corpus" / sub.name)
        elif entry.is_dir():
            shutil.copytree(entry, dst / name)
        else:
            shutil.copy2(entry, dst / name)


def snapshot(root: Path) -> dict:
    """{relative path: (inode, size, mtime_ns)} of every file under root except logs/."""
    out = {}
    for p in root.rglob("*"):
        rel = p.relative_to(root)
        if rel.parts and rel.parts[0] == "logs":
            continue
        try:
            st = p.lstat()
        except OSError:
            continue
        if p.is_file():
            out[str(rel)] = (st.st_ino, st.st_size, st.st_mtime_ns)
    return out


def changed_files(before: dict, after: dict) -> list[str]:
    return sorted(k for k in set(before) | set(after) if before.get(k) != after.get(k))


# --------------------------------------------------------------------------- step runner
class Runner:
    def __init__(self, run_dir: Path, status: dict, env: dict):
        self.run_dir, self.status, self.env = run_dir, status, env
        self.logs = run_dir / "logs"
        self.logs.mkdir(exist_ok=True)
        self.n = 0
        self.min_free = free_gb(run_dir)

    def _watch_disk(self, stop: threading.Event) -> None:
        """Lowest free space seen while a step runs (sampled every 2 s): the footprint peak."""
        while not stop.wait(2):
            self.min_free = min(self.min_free, free_gb(self.run_dir))

    def step(self, name: str, cmd: list, *, cwd: Path = CODE, env_extra: dict | None = None,
             required: bool = True, ok_codes=(0,)) -> int:
        """Run a command; record seconds and peak resident memory (largest process of the step)."""
        self.n += 1
        logf = self.logs / f"{self.n:02d}-{name}.log"
        env = {**self.env, **(env_extra or {})}
        log(f"step {name}: {' '.join(str(c) for c in cmd)}")
        t0 = time.time()
        stop = threading.Event()
        watcher = threading.Thread(target=self._watch_disk, args=(stop,), daemon=True)
        watcher.start()
        with open(logf, "w") as fh:
            proc = subprocess.Popen([str(c) for c in cmd], cwd=cwd, env=env, stdout=fh, stderr=subprocess.STDOUT)
            _, wstatus, ru = os.wait4(proc.pid, 0)
        stop.set()
        self.min_free = min(self.min_free, free_gb(self.run_dir))
        rc = os.waitstatus_to_exitcode(wstatus)
        proc.returncode = rc
        scale = 1 if sys.platform == "darwin" else 1024     # ru_maxrss: bytes on macOS, KiB on Linux
        rec = {"name": name, "rc": rc, "seconds": round(time.time() - t0, 1),
               "peak_rss_mb": round(ru.ru_maxrss * scale / 1e6, 1), "log": str(logf)}
        self.status["steps"].append(rec)
        log(f"  -> rc {rc} in {rec['seconds']} s, peak {rec['peak_rss_mb']} MB")
        if rc not in ok_codes and required:
            raise StepFailed(name, rc, logf)
        return rc


class StepFailed(Exception):
    def __init__(self, name, rc, logf):
        super().__init__(f"step {name} failed (rc {rc}), log {logf}")
        self.step, self.rc, self.logf = name, rc, logf


# --------------------------------------------------------------------------- pieces
def touched_codes(run_data: Path, since_started: str) -> list[str]:
    """Parents refreshed in this run (state) plus their registered children."""
    import duckdb
    state = read_json(run_data / "logs" / "update-pipeline-state.json", {})
    parents = sorted(c for c, m in state.get("matrices", {}).items()
                     if m.get("outcome") in ("ok", "ok_degraded") and (m.get("updated_at") or "") >= since_started)
    if not parents:
        return []
    con = duckdb.connect(str(run_data / "corpus" / "metadata.duckdb"), read_only=True)
    try:
        marks = ",".join("?" for _ in parents)
        kids = [r[0] for r in con.execute(
            f"SELECT sub_matrix_code FROM dataset_splits WHERE parent_matrix_code IN ({marks})", parents).fetchall()]
    finally:
        con.close()
    return sorted(set(parents) | set(kids))


def sweep_codes(sweep_dir: Path) -> tuple[list[str], list[str]]:
    """(codes INS updated or added, codes the DB has and INS no longer lists) from changes.csv."""
    import csv
    path = sweep_dir / "changes.csv"
    if not path.exists():
        return [], []
    todo, gone = [], []
    for r in csv.DictReader(open(path, encoding="utf-8")):
        (gone if r["kind"] == "not_listed_by_ins" else todo).append(r["code"])
    return sorted(todo), sorted(gone)


def clear_stale_dim_checks(db: Path, codes: list[str]) -> None:
    """kpi_dimension_checks rows of a re-checked code describe the old check: drop them, `dims` rebuilds
    the ones that still disagree."""
    import duckdb
    con = duckdb.connect(str(db))
    try:
        if con.execute("SELECT COUNT(*) FROM information_schema.tables WHERE table_name = 'kpi_dimension_checks'"
                       ).fetchone()[0]:
            for i in range(0, len(codes), 500):
                chunk = codes[i:i + 500]
                con.execute(f"DELETE FROM kpi_dimension_checks WHERE matrix_code IN ({','.join('?' * len(chunk))})", chunk)
    finally:
        con.close()


def build_candidate(run_dir: Path, code_dir: Path) -> Path:
    """release/code/: what deploy.sh uploads, from the checkout this script runs from."""
    out = run_dir / "release" / "code"
    for d in CODE_DIRS:
        shutil.copytree(code_dir / d, out / d, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    for f in CODE_FILES:
        (out / f).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(code_dir / f, out / f)
    return out


def generation_id(stage: Path) -> str:
    return read_json(stage / "MANIFEST.json", {}).get("generation", {}).get("id", "")


# --------------------------------------------------------------------------- main run
def run(args) -> int:
    base = Path(args.base).resolve()
    data = base / "data"
    today = date.today()
    base.mkdir(parents=True, exist_ok=True)
    status_path = base / "status.json"
    prev = read_json(status_path, {})

    lock = open(base / "run.lock", "w")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        log("another run holds the lock; exiting")
        return 0

    due, why = is_due(today, prev, args.max_retry_days, args.force)
    if not due:
        log(f"not due: {why}")
        if prev.get("pending_since") and "gave up" in why:
            prev["pending_since"] = None
            prev["outcome"] = "gave_up"
            atomic_json(status_path, prev)
            notify(f"TEMPO refresh gave up after {args.max_retry_days} days ({why}). Check INS and the last run.")
        return 0
    log(f"due: {why}")

    run_id = args.run_id or datetime.now().strftime("%Y%m%d-%H%M")
    run_dir = base / "runs" / run_id
    status = {"run_id": run_id, "started": datetime.now().isoformat(timespec="seconds"), "reason": why,
              "outcome": "running", "steps": [], "notes": [], "pending_since": prev.get("pending_since"),
              "last_sweep": prev.get("last_sweep"), "last_success": prev.get("last_success"),
              "last_candidate_run_id": prev.get("last_candidate_run_id"), "args": vars(args).copy()}
    peak_disk = {"free_before_gb": round(free_gb(base), 2)}
    started_iso = status["started"]

    def finish(outcome: str, msg: str | None = None) -> int:
        status["outcome"] = outcome
        status["finished"] = datetime.now().isoformat(timespec="seconds")
        status["seconds"] = round((datetime.fromisoformat(status["finished"]) -
                                   datetime.fromisoformat(status["started"])).total_seconds())
        if run_dir.exists():
            status["run_dir_bytes"] = dir_bytes(run_dir)
        status["disk"] = {**peak_disk, "free_after_gb": round(free_gb(base), 2),
                          "peak_used_gb": round(peak_disk["free_before_gb"] - runner.min_free, 2),
                          "base_data_bytes": dir_bytes(data) if data.exists() else 0}
        if msg:
            status["message"] = msg
        atomic_json(status_path, status)
        if run_dir.exists():
            atomic_json(run_dir / "status.json", status)
        return 0 if outcome.startswith("candidate") or outcome in ("probe_failed",) else 1

    # ---- probe (before any copy)
    probe_cmd = [args.python, str(CODE / "update-pipeline.py"), "--probe-only"]
    env = {**os.environ, "TEMPO_PIPELINE_DATA_DIR": str(data), "TEMPO_LANG": "ro",
           "TEMPO_AUDIT_MEMORY": args.duckdb_memory, "TEMPO_AUDIT_THREADS": "1",
           "TEMPO_AUDIT_GRAIN_BUCKET_ROWS": str(args.grain_bucket_rows), "TEMPO_AUDIT_TMP": str(run_dir / "tmp")}
    if args.simulate_probe_failure:
        probe_cmd = [args.python, "-c", "import sys; print('simulated probe failure'); sys.exit(1)"]
    run_dir.mkdir(parents=True, exist_ok=True)
    runner = Runner(run_dir, status, env)
    if args.dry_run:
        log("dry run: stopping before any copy")
        shutil.rmtree(run_dir, ignore_errors=True)
        return 0
    if runner.step("probe", probe_cmd, required=False) != 0:
        first = prev.get("pending_since") is None
        status["pending_since"] = status["pending_since"] or today.isoformat()
        day = (today - date.fromisoformat(status["pending_since"])).days + 1
        status["probe_failures"] = day
        shutil.rmtree(run_dir, ignore_errors=True)
        status["steps"] = status["steps"]        # kept in status.json
        if first or day >= args.max_retry_days:
            notify(f"TEMPO refresh: INS does not answer a data query (day {day} of {args.max_retry_days}). "
                   + ("Retrying daily." if day < args.max_retry_days else "Giving up until next Sunday."))
        return finish("probe_failed", f"INS probe failed, day {day}")

    before = None
    status["base_generation"] = (read_json(data / "corpus" / "generation-manifest.json", {}) or {}).get("generation_id")
    try:
        # ---- space, copy
        if free_gb(base) < args.min_free_gb:
            raise RuntimeError(f"only {free_gb(base):.1f} GB free under {base}; need {args.min_free_gb}")
        before = snapshot(data)
        t0 = time.time()
        copy_working_data(data, run_dir / "data")
        status["steps"].append({"name": "copy", "rc": 0, "seconds": round(time.time() - t0, 1)})
        rdata = run_dir / "data"
        penv = {"TEMPO_PIPELINE_DATA_DIR": str(rdata), "TEMPO_DATA_DIR": str(rdata)}
        py = args.python

        # ---- feed
        feed = [py, CODE / "update-pipeline.py", "--refetch-news", "--global-profiles", "--drop-csv"]
        if args.matrix:
            feed += ["--matrix", args.matrix]
        elif args.since:
            feed += ["--since", args.since]
        rc = runner.step("feed", feed, env_extra=penv, ok_codes=(0, 1))
        state = read_json(rdata / "logs" / "update-pipeline-state.json", {})
        lr = state.get("last_run", {})
        status["feed"] = {"exit_code": rc, "processed": lr.get("processed"), "failed": lr.get("failed", []),
                          "empty": lr.get("empty", []), "optional_failed": lr.get("optional_failed", []),
                          "retry_set": sorted(state.get("retry", {})), "watermark": state.get("watermark"),
                          "stale": {k: len(v) for k, v in state.get("stale", {}).items() if v}}

        # ---- monthly sweep: codes the feed window missed
        sweep_due = args.sweep == "yes" or (args.sweep == "auto" and (
            not prev.get("last_sweep") or (today - date.fromisoformat(prev["last_sweep"])).days >= SWEEP_EVERY_DAYS))
        if sweep_due:
            sdir = run_dir / "sweep"
            runner.step("sweep", [py, CODE / "scripts/utils/meta-sweep.py", sdir, rdata / "corpus/metadata.duckdb"], env_extra=penv)
            todo, gone = sweep_codes(sdir)
            done = set(state.get("matrices", {}))
            todo = [c for c in todo if c not in done]
            status["sweep"] = {"to_refresh": len(todo), "not_listed_by_ins": gone[:20], "not_listed_count": len(gone)}
            if todo:
                runner.step("sweep-refresh", [py, CODE / "update-pipeline.py", "--matrix", ",".join(todo),
                                              "--global-profiles", "--drop-csv"], env_extra=penv, ok_codes=(0, 1))
                state = read_json(rdata / "logs" / "update-pipeline-state.json", {})
                status["feed"]["failed"] = sorted(set(status["feed"]["failed"]) | set(state.get("last_run", {}).get("failed", [])))
                status["feed"]["retry_set"] = sorted(state.get("retry", {}))
            shutil.rmtree(sdir, ignore_errors=True)
            status["last_sweep"] = today.isoformat()
        shutil.rmtree(rdata / "4-datasets", ignore_errors=True)   # nothing may stay behind

        touched = touched_codes(rdata, started_iso)
        status["touched"] = {"count": len(touched), "codes": touched[:200]}

        # ---- retired children
        runner.step("cleanup-retired", [py, CODE / "scripts/cleanup-retired-children.py", "--data-dir", rdata,
                                        "--json-out", run_dir / "cleanup.json"], env_extra=penv)
        status["cleanup"] = {k: (len(v) if isinstance(v, (list, dict)) else v)
                             for k, v in read_json(run_dir / "cleanup.json", {}).items()}

        # ---- INS checks of the touched codes
        if touched:
            codes_file = run_dir / "touched.txt"
            codes_file.write_text("\n".join(touched) + "\n")
            kc = [py, CODE / "scripts/check-kpi-totals.py"]
            cache = run_dir / "kpi-cache"
            runner.step("kpi-collect", kc + ["collect", "--data-dir", rdata, "--out", run_dir / "kpis.json",
                                             "--codes-file", codes_file], env_extra=penv)
            runner.step("kpi-check", kc + ["check", "--data-dir", rdata, "--kpis", run_dir / "kpis.json",
                                           "--cache", cache, "--out", run_dir / "kpi-report.json",
                                           "--codes-file", codes_file, "--write-db",
                                           rdata / "corpus/metadata.duckdb"], env_extra=penv, required=False)
            rep = read_json(run_dir / "kpi-report.json", {})
            status["kpi_checks"] = rep.get("summary", {}).get("status", {})
            clear_stale_dim_checks(rdata / "corpus/metadata.duckdb", touched)
            bad = sorted(c for c, r in rep.get("results", {}).items() if r.get("status") == "mismatch")
            if bad:
                (run_dir / "mismatch.txt").write_text("\n".join(bad) + "\n")
                runner.step("kpi-dims", kc + ["dims", "--data-dir", rdata, "--kpis", run_dir / "kpis.json",
                                              "--cache", cache, "--out", run_dir / "kpi-dims.json",
                                              "--codes-file", run_dir / "mismatch.txt", "--write-db",
                                              rdata / "corpus/metadata.duckdb"], env_extra=penv, required=False)
            shutil.rmtree(cache, ignore_errors=True)
        else:
            status["kpi_checks"] = "no touched codes"

        # ---- compact the DB
        db = rdata / "corpus/metadata.duckdb"
        compact = run_dir / "metadata.compact.duckdb"
        status["db_bytes_before"] = db.stat().st_size
        runner.step("compact", [py, CODE / "scripts/compact-metadata.py", db, compact,
                                "--json-out", run_dir / "compact.json"], env_extra=penv)
        for suffix in ("", ".wal"):
            Path(str(db) + suffix).unlink(missing_ok=True)
        os.replace(compact, db)
        status["db_bytes_after"] = db.stat().st_size

        # ---- manifest, audit report
        runner.step("manifest", [py, CODE / "scripts/build-generation-manifest.py", "--data-dir", rdata,
                                 "--out", run_dir / "generation-manifest.json"], env_extra=penv)
        os.replace(run_dir / "generation-manifest.json", rdata / "corpus" / "generation-manifest.json")
        runner.step("audit", [py, CODE / "scripts/audit-corpus.py", "--data-dir", rdata, "--json-out",
                              run_dir / "audit.json", "--quiet"], env_extra=penv, required=False)

        # ---- stage + local smoke (strict)
        stage = run_dir / "release" / "data"
        runner.step("stage", ["bash", CODE / "scripts/prepare-deploy-data.sh", "--no-tarball"],
                    env_extra={"TEMPO_CORPUS_SRC": str(rdata / "corpus"), "TEMPO_DEPLOY_OUT": str(stage),
                               "PYTHON": py})
        shutil.rmtree(str(stage) + ".prev", ignore_errors=True)
        status["generation"] = generation_id(stage)
        build_candidate(run_dir, CODE)
        runner.step("release-check-local", [py, CODE / "scripts/release-check.py", "--local", "--stage", stage,
                                            "--skip-tests", "--port", args.port, *STRICT_FLAGS])

        # ---- static build + gate
        static = run_dir / "static"
        build = [py, CODE / "scripts/build-static.py", "--out", static, "--base-url", args.static_base_url]
        if args.static_codes:
            build += ["--codes", args.static_codes]
            status["notes"].append(f"static build limited to --codes {args.static_codes} (rehearsal subset)")
        runner.step("static-build", build, env_extra=penv)
        cases = run_dir / "api-cases.jsonl"
        gate = [py, CODE / "scripts/release-check.py", "--static", static, "--source", rdata / "corpus",
                "--skip-tests"]
        if args.static_codes:
            status["api_parity"] = "SKIPPED (subset build: the cases name datasets that are not in it)"
            status["notes"].append(status["api_parity"])
        elif shutil.which("node") and not args.no_api_parity:
            gen = [py, CODE / "scripts/gen-api-cases.py", "--out", cases, "--n", args.api_cases_n,
                   "--codes", args.api_cases_codes]
            runner.step("api-cases", gen, env_extra=penv)
            gate += ["--api-cases", cases]
            status["api_parity"] = "run"
        else:
            status["api_parity"] = "SKIPPED (node missing or --no-api-parity): the static gate is not complete"
            status["notes"].append(status["api_parity"])
        runner.step("release-check-static", gate, env_extra=penv)

        # ---- the live tree must not have changed
        changed = changed_files(before, snapshot(data))
        status["live_tree_changed"] = changed[:20]
        if changed:
            raise RuntimeError(f"the working generation changed during the run ({len(changed)} files, e.g. {changed[:3]})")

        peak_disk["run_dir_bytes"] = dir_bytes(run_dir)
        failed = status["feed"]["failed"]
        outcome = "candidate_with_failures" if failed or status["feed"]["optional_failed"] else "candidate"
        status["last_success"] = today.isoformat()
        status["last_candidate_run_id"] = run_id
        status["pending_since"] = None
        status["promote"] = f"bash scripts/deploy/hetzner/promote.sh --apply {run_id}"
        _prune(base, keep=args.keep_runs, protect=run_id)
        msg = (f"TEMPO refresh {run_id}: {outcome}. Generation {status['generation'][:8]}, "
               f"{status['touched']['count']} datasets touched, {len(failed)} failed "
               f"({', '.join(failed[:5])}), retry set {len(status['feed']['retry_set'])}. "
               f"DB {status['db_bytes_before'] / 1e6:.0f} -> {status['db_bytes_after'] / 1e6:.0f} MB. "
               f"Gates passed. Approve: {status['promote']}")
        rc = finish(outcome)
        notify(msg)
        return rc
    except (StepFailed, RuntimeError, OSError) as e:
        status["pending_since"] = status["pending_since"] or today.isoformat()
        if isinstance(e, StepFailed):
            status["failed_step"] = e.step
            tail = Path(e.logf).read_text(errors="replace")[-1500:]
            status["failed_tail"] = tail
            if re.search(r"concepts(\.json)?|curated note", tail, re.I):
                status["notes"].append("a gate failure mentions concepts/curated notes: a note may name an old "
                                       "period; fix the note by hand (not edited automatically)")
        status["error"] = str(e)
        if before is not None:
            status["live_tree_changed"] = changed_files(before, snapshot(data))[:20]
        _prune(base, keep=args.keep_runs, protect=run_id)
        rc = finish("failed", str(e))
        notify(f"TEMPO refresh {run_id} FAILED: {e}. Run folder kept: {run_dir}. The served release is untouched.")
        return rc


def _prune(base: Path, keep: int, protect: str) -> None:
    runs = sorted(p for p in (base / "runs").iterdir() if p.is_dir())
    for p in runs[:-keep] if keep else runs:
        if p.name != protect:
            shutil.rmtree(p, ignore_errors=True)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--base", default="/opt/tempo/pipeline")
    ap.add_argument("--python", default=sys.executable)
    ap.add_argument("--since", help="DD.MM.YYYY: feed entries on or after this date (default: the stored watermark)")
    ap.add_argument("--matrix", help="CODE[,CODE]: process exactly these (rehearsals); no watermark change")
    ap.add_argument("--sweep", choices=("auto", "yes", "no"), default="auto")
    ap.add_argument("--force", action="store_true", help="run even when the schedule says not due")
    ap.add_argument("--max-retry-days", type=int, default=7)
    ap.add_argument("--keep-runs", type=int, default=2)
    ap.add_argument("--min-free-gb", type=float, default=MIN_FREE_GB)
    ap.add_argument("--port", default="8095")
    ap.add_argument("--duckdb-memory", default="512MB",
                    help="memory_limit of the audit's DuckDB (the grain check used 8 GB uncapped on the Mac)")
    ap.add_argument("--grain-bucket-rows", type=int, default=1_000_000,
                    help="the audit's grain check groups a big file in buckets of about this many rows")
    ap.add_argument("--static-codes", help="build the static site for these codes only (rehearsal)")
    ap.add_argument("--static-base-url", default="https://ins.gov2.ro")
    ap.add_argument("--api-cases-n", default="60")
    ap.add_argument("--api-cases-codes", default=API_CASES_CODES,
                    help="datasets for the /options and /download parity cases. The default leaves out POP107D "
                         "(22M rows): its unfiltered CSV download held 3.6 GB in the test client; the whole "
                         "step peaked at 4.9 GB with it and 0.9 GB without")
    ap.add_argument("--no-api-parity", action="store_true")
    ap.add_argument("--run-id")
    ap.add_argument("--simulate-probe-failure", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    return run(ap.parse_args(argv))


if __name__ == "__main__":
    sys.exit(main())
