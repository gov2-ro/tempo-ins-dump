#!/usr/bin/env python3
"""Capacity harness for the public MCP (AQ-01 step 01A): measures, changes nothing in the app.

It launches an isolated local candidate process (or a Docker container) on an explicit data
directory with provider keys unset, drives it with the real MCP SDK client over Streamable HTTP,
and writes a machine-readable report to an explicit output directory. Never point it at
production or at a server it did not start.

  # control profile (the application's defaults), local, reduced counts
  python scripts/benchmark-mcp.py run --data-dir DIR --out-dir OUT --cold-repeats 2 --warm-samples 20
  # candidate: a larger scan cap in the child only, AT-04 mixed-load lengths, a CSV export in the REST mix
  python scripts/benchmark-mcp.py run --data-dir DIR --out-dir OUT --max-scan-rows 5000000 \\
      --mixed-phase single_client:1:2:180 --mixed-phase five_clients:5:2:300 --export-dataset TUR105D_judete
  # container: an existing image, DIR mounted read-only, 512 MiB with no swap (needs a Docker daemon on a Linux kernel:
  # a Linux host, or a Linux VM such as Colima on macOS)
  python scripts/benchmark-mcp.py run --mode container --image IMAGE --data-dir DIR --out-dir OUT

DIR is a data directory (it holds corpus/); the child opens it read-only. OUT must be outside the repository.

The defaults of the app form the control profile. A larger scan cap (or other TEMPO_MCP_*
setting) is applied only to the child it launches and is recorded in the report; the app's own
defaults are untouched. Measured states are never combined: cold (fresh process), cache (same
request served from the result cache), miss_warm (result-cache miss, metadata warm), mixed (REST
plus MCP load) and observed (single-shot admission/concurrency/cancellation facts). A measurement
that was not taken is null or `not_run`, never 0.

Internal sub-commands run inside the child: `serve` (the app under uvicorn, with a provider-call
guard, a tool-dispatch log and MCP metrics on stderr) and `inproc` (the shared tools called
directly, for numerical parity with what the MCP returned).

Exit status: 0 completed, 1 a check or scenario failed, 2 blocked (arguments/corpus).
"""
from __future__ import annotations

import argparse
import asyncio
import atexit
import contextlib
import dataclasses
import datetime as dt
import hashlib
import json
import math
import os
import platform
import re
import resource
import shutil
import signal
import socket
import subprocess
import sys
import threading
import time
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = Path(__file__).resolve()
SCHEMA = "benchmark-mcp/1"
CONTAINER_PORT = 8080

# sample states: percentiles are computed per (case, state) and never across states
STATES = ("cold", "miss_warm", "cache", "mixed", "observed")
REQUIRED_N = {"cold": 5, "miss_warm": 20, "cache": 20, "mixed": 1, "observed": 1}
SINGLE_CASES = ("rank_latest_year", "rank_topk_", "warm.first_rank")   # one observation each, not a latency population
SERVED = frozenset({"ok", "partial", "needs_clarification"})
SCENARIOS = ("cold_chain", "cold_first_rank", "warm", "admission", "timeout_probe", "mixed")
AT04_PHASES = (("single_client", 1, 180.0), ("five_clients", 5, 300.0))      # 04-evaluation-and-release.md
IGNORED_IN_PARITY = frozenset({"request_id", "elapsed_ms", "duration_ms", "timing"})

PROFILE_FLAGS = {"max_scan_rows": "TEMPO_MCP_MAX_SCAN_ROWS", "max_seconds": "TEMPO_MCP_MAX_SECONDS",
                 "max_concurrent": "TEMPO_MCP_MAX_CONCURRENT", "cache_bytes": "TEMPO_MCP_CACHE_BYTES",
                 "cache_entries": "TEMPO_MCP_CACHE_ENTRIES", "cache_ttl_seconds": "TEMPO_MCP_CACHE_TTL_SECONDS"}
# Per-minute rate limits are admission policy, not capacity: lifted so a sequential sample loop is not
# throttled into `busy` answers. Recorded in the report under profile.harness_overrides.
HARNESS_OVERRIDES = {"TEMPO_MCP_MAX_CALLS_PER_MINUTE": "1000000", "TEMPO_MCP_MAX_REQUESTS_PER_MINUTE": "1000000"}
ENV_ALLOW = ("PATH", "HOME", "LANG", "LC_ALL", "LC_CTYPE", "TMPDIR", "VIRTUAL_ENV", "SYSTEMROOT")
SECRET_NAME = re.compile(r"(API_KEY|_TOKEN|SECRET|PASSWORD)$|^(ANTHROPIC|OPENAI|GEMINI|MISTRAL|DEEPSEEK|XAI|OPENROUTER)_")
FORBIDDEN_SETTING = re.compile(r"^TEMPO_(ASK|LLM|OLLAMA)")
LOG_EVENT = re.compile(r"^(MCP_METRICS|BENCH_DISPATCH|BENCH_PROVIDER_CALL|BENCH_CHILD) (\{.*\})\s*$")


class HarnessError(RuntimeError):
    """A condition the harness itself cannot continue past (bad arguments, a child that will not start)."""


# ====================================================================== pure helpers

def nearest_rank(sorted_values: list, p: float):
    """Nearest-rank percentile: always an observed value (no interpolation)."""
    k = max(1, math.ceil(p / 100.0 * len(sorted_values)))
    return sorted_values[min(k, len(sorted_values)) - 1]


def latency_summary(values) -> dict | None:
    """Seconds -> {n,min,p50,p95,max,mean}; None when there is nothing to summarise (never zeros)."""
    xs = sorted(float(v) for v in values if v is not None and math.isfinite(float(v)))
    if not xs:
        return None
    r = lambda v: round(v, 4)
    return {"n": len(xs), "min": r(xs[0]), "p50": r(nearest_rank(xs, 50)), "p95": r(nearest_rank(xs, 95)),
            "max": r(xs[-1]), "mean": r(sum(xs) / len(xs)), "method": "nearest_rank"}


def rss_to_bytes(value, source: str, system: str | None = None) -> int | None:
    """Normalise a resident-size reading to bytes. `ps_kib` (ps -o rss, KiB on macOS and Linux) and
    `proc_kb` (/proc VmRSS/VmHWM, kB = KiB) are KiB; `ru_maxrss` is bytes on macOS but KiB on Linux."""
    if value is None:
        return None
    if source in ("ps_kib", "proc_kb"):
        return int(value) * 1024
    if source == "ru_maxrss":
        return int(value) if (system or platform.system()) == "Darwin" else int(value) * 1024
    raise ValueError(f"unknown RSS source {source!r}")


def parse_ps_table(text: str) -> list[tuple[int, int, int]]:
    """`ps -A -o pid=,ppid=,rss=` -> [(pid, ppid, rss_kib)]; malformed lines are skipped."""
    rows = []
    for line in text.splitlines():
        parts = line.split()
        if len(parts) == 3 and all(p.isdigit() for p in parts):
            rows.append((int(parts[0]), int(parts[1]), int(parts[2])))
    return rows


def tree_rss_bytes(table: list[tuple[int, int, int]], root: int) -> int | None:
    """Summed RSS of `root` and all its descendants, bytes; None when the root is not in the table.
    A sum of RSS double counts shared pages and is not cgroup memory."""
    by_parent: dict = {}
    rss = {}
    for pid, ppid, kib in table:
        rss[pid] = kib
        by_parent.setdefault(ppid, []).append(pid)
    if root not in rss:
        return None
    total, stack, seen = 0, [root], set()
    while stack:
        pid = stack.pop()
        if pid in seen:
            continue
        seen.add(pid)
        total += rss_to_bytes(rss[pid], "ps_kib")
        stack.extend(by_parent.get(pid, ()))
    return total


def parse_ps_time(text: str) -> float | None:
    """ps cputime: `M:SS.cc`, `H:MM:SS` or `D-HH:MM:SS` -> seconds."""
    text = text.strip()
    m = re.fullmatch(r"(?:(\d+)-)?(?:(\d+):)?(\d+):(\d+(?:\.\d+)?)", text)
    if not m:
        return None
    days, hours, minutes, seconds = m.groups()
    if hours is None:
        return int(minutes) * 60 + float(seconds) + int(days or 0) * 86400
    return int(days or 0) * 86400 + int(hours) * 3600 + int(minutes) * 60 + float(seconds)


def parse_proc_stat_cpu(text: str, clk_tck: int) -> float | None:
    """utime + stime of /proc/<pid>/stat in seconds (fields 14, 15; the comm field may hold spaces)."""
    try:
        rest = text[text.rindex(")") + 2:].split()
        return (int(rest[11]) + int(rest[12])) / clk_tck
    except (ValueError, IndexError):
        return None


def parse_docker_size(text: str) -> int | None:
    """`123.4MiB` / `1.2GB` / `512kB` -> bytes (binary prefixes with i, decimal without)."""
    m = re.fullmatch(r"\s*([\d.]+)\s*([kKMGT]?i?B)\s*", text or "")
    if not m:
        return None
    unit = m.group(2).lower()
    scale = {"b": 1, "kb": 1000, "mb": 1000 ** 2, "gb": 1000 ** 3, "tb": 1000 ** 4,
             "kib": 1024, "mib": 1024 ** 2, "gib": 1024 ** 3, "tib": 1024 ** 4}[unit]
    return int(float(m.group(1)) * scale)


def parse_memory_flag(text: str) -> int | None:
    """Docker `--memory` value (`512m`, `1g`, `536870912`) -> bytes."""
    m = re.fullmatch(r"(\d+)([bkmg]?)", str(text).strip().lower())
    if not m:
        return None
    return int(m.group(1)) * {"": 1, "b": 1, "k": 1024, "m": 1024 ** 2, "g": 1024 ** 3}[m.group(2)]


def diff_json(a, b, ignore=IGNORED_IN_PARITY, path: str = "$", out: list | None = None, limit: int = 20) -> list:
    """Paths at which two JSON values differ (keys in `ignore` skipped at every depth)."""
    out = [] if out is None else out
    if len(out) >= limit:
        return out
    if isinstance(a, dict) and isinstance(b, dict):
        for k in sorted(set(a) | set(b)):
            if k in ignore:
                continue
            if k not in a or k not in b:
                out.append(f"{path}.{k}: present in only one side")
            else:
                diff_json(a[k], b[k], ignore, f"{path}.{k}", out, limit)
    elif isinstance(a, list) and isinstance(b, list):
        if len(a) != len(b):
            out.append(f"{path}: length {len(a)} != {len(b)}")
        for i, (x, y) in enumerate(zip(a, b)):
            diff_json(x, y, ignore, f"{path}[{i}]", out, limit)
    elif a != b:
        out.append(f"{path}: {str(a)[:60]!r} != {str(b)[:60]!r}")
    return out[:limit]


def sha256_json(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
                          .encode("utf-8")).hexdigest()


def classify(env, is_error: bool = False) -> tuple[str, str | None, str | None, str | None]:
    """(outcome, status, reason, detail) of a tool envelope. Refusals are not failures."""
    if not isinstance(env, dict) or "status" not in env:
        return "protocol_error", None, None, None
    status, reason = env["status"], env.get("reason")
    if status in SERVED:
        return "served", status, reason, None
    if status == "unavailable":
        detail = None
        if reason == "busy":
            detail = "rate_limit" if "many requests" in str(env.get("message")) else "slot"
        return "refused", status, reason, detail
    if status == "error" or is_error:
        return "tool_error", status, reason, None
    return "protocol_error", status, reason, None


def is_secret_name(name: str) -> bool:
    return bool(SECRET_NAME.search(name))


def profile_env(cfg_values: dict, extra_settings: list[str], keep_rate_limits: bool) -> tuple[dict, dict]:
    """(declared, harness_overrides): the TEMPO_* variables for the child. `cfg_values` maps the PROFILE_FLAGS
    keys to values or None; every value must be a positive finite number (zero is never 'unlimited')."""
    declared: dict = {}
    for key, var in PROFILE_FLAGS.items():
        v = cfg_values.get(key)
        if v is not None:
            declared[var] = _positive(var, v)
    for item in extra_settings:
        name, sep, value = item.partition("=")
        if not sep or not name.startswith("TEMPO_") or FORBIDDEN_SETTING.match(name) or is_secret_name(name):
            raise HarnessError(f"--setting must be TEMPO_NAME=value (not Ask/LLM/credentials): {item!r}")
        declared[name] = value
    overrides = {} if keep_rate_limits else {k: v for k, v in HARNESS_OVERRIDES.items() if k not in declared}
    return declared, overrides


def _positive(name: str, value) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise HarnessError(f"{name} must be a number, not {value!r}") from None
    if not (number > 0 and math.isfinite(number)):
        raise HarnessError(f"{name} must be positive (zero is not 'unlimited'), not {value!r}")
    return str(value)


def build_child_env(parent: dict, *, data_dir: str, port: int, declared: dict, overrides: dict) -> dict:
    """A minimal environment for the child: an allowlist of the parent's, never its provider keys."""
    env = {k: parent[k] for k in ENV_ALLOW if k in parent}
    env.update({"TEMPO_DATA_DIR": str(data_dir), "TEMPO_MCP_ENABLED": "true", "TEMPO_MCP_LOCAL_TEST": "true",
                "TEMPO_PUBLIC_BASE_URL": f"http://127.0.0.1:{port}", "TEMPO_ASK_ENABLED": "false",
                "TEMPO_ASK_BYOK_ENABLED": "false", "TEMPO_DEBUG": "false",
                "PYTHONDONTWRITEBYTECODE": "1", "PYTHONUNBUFFERED": "1"})
    env.update(overrides)
    env.update(declared)
    leaked = sorted(k for k in env if is_secret_name(k))
    if leaked:
        raise HarnessError(f"credential-looking variables in the child environment: {leaked}")
    return env


def parse_log_events(text: str) -> list[dict]:
    """Structured lines the child writes to its log: MCP_METRICS (the app's), BENCH_* (the launcher's)."""
    events = []
    for line in text.splitlines():
        m = LOG_EVENT.match(line)
        if not m:
            continue
        try:
            events.append({"kind": m.group(1), **json.loads(m.group(2))})
        except ValueError:
            continue
    return events


def parse_ports(spec: str | None) -> list[int] | None:
    if not spec:
        return None
    lo, _, hi = spec.partition("-")
    ports = list(range(int(lo), int(hi or lo) + 1))
    if not ports or any(not 1024 <= p <= 65535 for p in ports):
        raise HarnessError(f"--ports must be like 8111-8115 (unprivileged ports), not {spec!r}")
    return ports


def code_identity(root: Path = ROOT) -> dict:
    """Commit plus a hash of the working-tree diff (tracked changes and untracked file contents)."""
    def git(*a):
        try:
            out = subprocess.run(["git", "-C", str(root), *a], capture_output=True, timeout=60)
        except (OSError, subprocess.TimeoutExpired):
            return None
        return out.stdout if out.returncode == 0 else None
    head = git("rev-parse", "HEAD")
    if head is None:
        return {"commit": None, "branch": None, "dirty": None, "diff_sha256": None}
    status = git("status", "--porcelain") or b""
    diff = git("diff", "HEAD") or b""
    h = hashlib.sha256(diff)
    for name in sorted((git("ls-files", "--others", "--exclude-standard") or b"").decode().splitlines()):
        h.update(b"\0" + name.encode())
        with contextlib.suppress(OSError):
            h.update((root / name).read_bytes()[: 1 << 20])
    branch = (git("rev-parse", "--abbrev-ref", "HEAD") or b"").decode().strip() or None
    dirty = bool(status.strip())
    return {"commit": head.decode().strip(), "branch": branch, "dirty": dirty,
            "diff_sha256": h.hexdigest() if dirty else None}


def parquet_fingerprint(path: Path) -> dict:
    """Size, mtime, footer row count and a hash of the footer bytes of one Parquet file (no data read)."""
    out = {"file": path.name, "bytes": None, "mtime_ns": None, "rows": None, "row_groups": None,
           "footer_sha256": None}
    try:
        st = path.stat()
    except OSError:
        return out
    out.update(bytes=st.st_size, mtime_ns=st.st_mtime_ns)
    try:
        with path.open("rb") as f:
            f.seek(-8, os.SEEK_END)
            tail = f.read(8)
            if tail[4:] == b"PAR1":
                n = int.from_bytes(tail[:4], "little")
                f.seek(-8 - n, os.SEEK_END)
                out["footer_sha256"] = hashlib.sha256(f.read(n)).hexdigest()
    except OSError:
        pass
    try:
        import duckdb
        con = duckdb.connect(config={"memory_limit": "32MB", "threads": 1})
        try:
            out["rows"] = int(con.execute("SELECT num_rows FROM parquet_file_metadata(?)", [str(path)]).fetchone()[0])
            out["row_groups"] = int(con.execute("SELECT count(DISTINCT row_group_id) FROM parquet_metadata(?)",
                                                [str(path)]).fetchone()[0])
        finally:
            con.close()
    except Exception:  # noqa: BLE001 — an unreadable footer is reported as null, not as zero rows
        pass
    return out


def data_fingerprint(data_dir: Path, datasets: list[str]) -> dict:
    corpus = data_dir / "corpus"
    manifest = corpus / "generation-manifest.json"
    db = corpus / "metadata.duckdb"
    out = {"data_dir": str(data_dir), "available": db.exists(), "generation": None, "metadata_db": None,
           "datasets": []}
    if db.exists():
        st = db.stat()
        out["metadata_db"] = {"bytes": st.st_size, "mtime_ns": st.st_mtime_ns}
    if manifest.exists():
        try:
            raw = manifest.read_bytes()
            m = json.loads(raw)
            out["generation"] = {"id": m.get("generation_id"), "built_at": m.get("built_at"),
                                 "manifest_sha256": hashlib.sha256(raw).hexdigest()}
        except (OSError, ValueError):
            out["generation"] = {"id": None, "built_at": None, "manifest_sha256": None, "unreadable": True}
    for code in datasets:
        out["datasets"].append({"dataset": code, **parquet_fingerprint(corpus / "parquet" / f"{code}.parquet")})
    return out


def environment_info() -> dict:
    from importlib import metadata

    def ver(name):
        try:
            return metadata.version(name)
        except metadata.PackageNotFoundError:
            return None
    ram = None
    try:
        if platform.system() == "Darwin":
            ram = int(subprocess.run(["sysctl", "-n", "hw.memsize"], capture_output=True, text=True).stdout)
        else:
            ram = int(re.search(r"MemTotal:\s+(\d+) kB", Path("/proc/meminfo").read_text()).group(1)) * 1024
    except Exception:  # noqa: BLE001
        ram = None
    return {"os": platform.platform(), "system": platform.system(), "machine": platform.machine(),
            "python": platform.python_version(), "cpu_count": os.cpu_count(), "ram_total_bytes": ram,
            "packages": {p: ver(p) for p in ("mcp", "duckdb", "uvicorn", "fastapi", "starlette", "httpx")}}


# ====================================================================== recorder

def required_n(case: str, state: str) -> int:
    """Samples the spec asks for: 5 fresh-process repetitions per cold case, 20 per warm case; one-off
    observations (first call after describe, latest year, each top K) need one."""
    if case.startswith(SINGLE_CASES) or (state == "cold" and not case.startswith(("cold_chain.", "cold_first_rank."))):
        return 1
    return REQUIRED_N[state]


class Recorder:
    """Samples keyed by (case, state). Summaries are per group and never merge states; latency percentiles
    cover served answers only, other outcomes (refusals, errors, client timeouts) are counted beside them."""

    def __init__(self):
        self.samples: list[dict] = []
        self.notes: dict = {}
        self._lock = threading.Lock()

    def add(self, case: str, state: str, *, wall_s, outcome: str, status=None, reason=None, detail=None,
            cached=None, dispatched=None, result_bytes=None, wire_bytes=None, run=None, variant=None,
            error=None) -> dict:
        if state not in STATES:
            raise ValueError(f"unknown state {state!r}")
        s = {"case": case, "state": state, "wall_s": None if wall_s is None else round(float(wall_s), 4),
             "outcome": outcome, "status": status, "reason": reason, "detail": detail, "cached": cached,
             "dispatched": dispatched, "result_bytes": result_bytes, "wire_bytes": wire_bytes, "run": run,
             "variant": variant, "error": None if error is None else str(error)[:200]}
        with self._lock:
            self.samples.append(s)
        return s

    def annotate(self, case: str, state: str, **extra) -> None:
        with self._lock:
            self.notes.setdefault((case, state), {}).update(extra)

    def groups(self) -> dict:
        out: dict = {}
        for s in self.samples:
            out.setdefault((s["case"], s["state"]), []).append(s)
        return out

    def summary(self) -> list[dict]:
        rows = []
        for (case, state), items in self.groups().items():
            by_outcome = Counter(s["outcome"] for s in items)
            lat_by = {o: latency_summary([s["wall_s"] for s in items if s["outcome"] == o]) for o in by_outcome}
            need = required_n(case, state)
            sized = lambda key: ({"min": min(v), "max": max(v), "mean": round(sum(v) / len(v), 1)}
                                 if (v := [s[key] for s in items if s[key] is not None]) else None)
            cached = [s["cached"] for s in items if s["cached"] is not None]
            disp = [s["dispatched"] for s in items if s["dispatched"] is not None]
            rows.append({
                "case": case, "state": state, "n": len(items), "required_n": need,
                "sufficient": len(items) >= need,
                "outcomes": dict(by_outcome),
                "results": dict(Counter(f"{s['status']}/{s['reason']}" for s in items if s["status"])),
                "latency_basis": "served",
                "latency_s": lat_by.get("served"),
                "latency_by_outcome": lat_by,
                "result_bytes": sized("result_bytes"), "wire_bytes": sized("wire_bytes"),
                "cache_hits": sum(1 for c in cached if c) if cached else None,
                "dispatched": sum(1 for d in disp if d) if disp else None,
                **self.notes.get((case, state), {})})
        return rows


# ====================================================================== children

class ChildRegistry:
    """Every started child, so an exception, a signal or interpreter exit always stops them."""

    def __init__(self):
        self.children: list = []
        self._lock = threading.Lock()
        self._installed = False

    def add(self, child) -> None:
        with self._lock:
            self.children.append(child)

    def discard(self, child) -> None:
        with self._lock:
            if child in self.children:
                self.children.remove(child)

    def kill_all(self) -> int:
        with self._lock:
            pending = list(self.children)
        for c in pending:
            with contextlib.suppress(Exception):
                c.stop()
        return len(pending)

    def install(self) -> None:
        if self._installed:
            return
        self._installed = True
        atexit.register(self.kill_all)
        if threading.current_thread() is threading.main_thread():
            for sig in (signal.SIGINT, signal.SIGTERM):
                signal.signal(sig, self._on_signal)

    def _on_signal(self, signum, _frame):
        self.kill_all()
        raise SystemExit(128 + signum)


CHILDREN = ChildRegistry()


def pick_port(candidates: list[int] | None, avoid=()) -> int:
    """A free local port from `candidates` (round robin by the caller), or an ephemeral one."""
    for p in (candidates or [0]):
        if p in avoid:
            continue
        with socket.socket() as s:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)     # as uvicorn binds: TIME_WAIT is not "busy"
            try:
                s.bind(("127.0.0.1", p))
            except OSError:
                continue
            return s.getsockname()[1]
    raise HarnessError(f"no free port in {candidates}")


def wait_listening(port: int, timeout: float, alive=lambda: True) -> float:
    """Seconds until something accepts connections on 127.0.0.1:port; raises when `alive()` goes false
    or the timeout passes (uvicorn listens only after the app's lifespan has started)."""
    t0 = time.perf_counter()
    while time.perf_counter() - t0 < timeout:
        if not alive():
            raise HarnessError("the child exited before it started listening")
        with socket.socket() as s:
            s.settimeout(0.2)
            try:
                s.connect(("127.0.0.1", port))
                return time.perf_counter() - t0
            except OSError:
                pass
        time.sleep(0.02)
    raise HarnessError(f"the child did not listen on port {port} within {timeout:g}s")


def tail_text(path: Path, n: int = 600) -> str:
    try:
        return path.read_bytes()[-n:].decode("utf-8", "replace")
    except OSError:
        return ""


class LogTail:
    """Incremental reader of a child's log: `take()` returns the events written since the last call."""

    def __init__(self, path: Path):
        self.path, self.pos = path, 0
        self.all: list[dict] = []

    def take(self) -> list[dict]:
        try:
            with self.path.open("rb") as f:
                f.seek(self.pos)
                data = f.read()
        except OSError:
            return []
        cut = data.rfind(b"\n") + 1                    # leave a partial last line for the next call
        self.pos += cut
        events = parse_log_events(data[:cut].decode("utf-8", "replace"))
        self.all.extend(events)
        return events


class LocalChild:
    """The app under uvicorn (via this script's `serve`), in its own process group on a local port."""
    kind = "local"

    def __init__(self, *, name: str, port: int, env: dict, log_path: Path, startup_timeout: float,
                 cmd: list[str] | None = None, cwd: Path = ROOT, fault: dict | None = None):
        self.name, self.port, self.env, self.log_path = name, port, env, log_path
        self.startup_timeout, self.cwd = startup_timeout, cwd
        fault_args = [a for k, v in (fault or {}).items() for a in ("--fault-delay", f"{k}={v}")]
        self.cmd = cmd or [sys.executable, str(SCRIPT), "serve", "--host", "127.0.0.1", "--port", str(port),
                           "--app-root", str(ROOT), *fault_args]
        self.proc: subprocess.Popen | None = None
        self.pid: int | None = None
        self.startup_s: float | None = None
        self._exit: tuple | None = None                # (status, rusage) once reaped
        self._we_stopped = False
        self._lock = threading.Lock()
        self.base_url = f"http://127.0.0.1:{port}"
        self._stats: dict | None = None
        self.term_grace, self.kill_grace = 8.0, 5.0

    # -- lifecycle
    def start(self) -> None:
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        with self.log_path.open("ab") as log:
            self.proc = subprocess.Popen(self.cmd, env=self.env, cwd=str(self.cwd), stdin=subprocess.DEVNULL,
                                         stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
        self.pid = self.proc.pid
        CHILDREN.add(self)
        try:
            self.startup_s = wait_listening(self.port, self.startup_timeout, alive=self.alive)
        except HarnessError as e:
            detail = tail_text(self.log_path)
            self.stop()
            raise HarnessError(f"{self.name}: {e}; log tail: {detail!r}") from None

    def _reap(self, block: bool) -> bool:
        with self._lock:
            if self._exit is not None or self.pid is None:
                return True
            try:
                pid, status, usage = os.wait4(self.pid, 0 if block else os.WNOHANG)
            except ChildProcessError:
                self._exit = (None, None)
                return True
            if pid == 0:
                return False
            self._exit = (status, usage)
            if self.proc is not None:
                self.proc.returncode = os.waitstatus_to_exitcode(status)
            return True

    def alive(self) -> bool:
        return self.pid is not None and not self._reap(False)

    def stop(self) -> dict:
        """Idempotent: SIGTERM the process group, SIGKILL after a grace period, reap, return the stats."""
        if self._stats is not None:
            return self._stats
        CHILDREN.discard(self)
        if self.pid is not None and self.alive():
            self._we_stopped = True
            for sig, grace in ((signal.SIGTERM, self.term_grace), (signal.SIGKILL, self.kill_grace)):
                with contextlib.suppress(ProcessLookupError, PermissionError):
                    os.killpg(self.pid, sig)
                end = time.monotonic() + grace
                while time.monotonic() < end and not self._reap(False):
                    time.sleep(0.02)
                if self._exit is not None:
                    break
            self._reap(False)
        else:
            self._reap(False)
        status, usage = self._exit or (None, None)
        signum = os.WTERMSIG(status) if status is not None and os.WIFSIGNALED(status) else None
        code = os.WEXITSTATUS(status) if status is not None and os.WIFEXITED(status) else None
        self._stats = {
            "exit_code": code, "signal": signum, "stopped_by_harness": self._we_stopped,
            "oom_suspected": bool(signum == signal.SIGKILL and not self._we_stopped),
            "cpu_s_total": None if usage is None else round(usage.ru_utime + usage.ru_stime, 3),
            "rss_peak_kernel_bytes": None if usage is None else rss_to_bytes(usage.ru_maxrss, "ru_maxrss"),
            "restarts": None}                           # a local child has no supervisor to restart it
        return self._stats

    # -- measurements
    def sample(self) -> dict:
        try:
            out = subprocess.run(["ps", "-A", "-o", "pid=,ppid=,rss="], capture_output=True, text=True, timeout=5)
            rss = tree_rss_bytes(parse_ps_table(out.stdout), self.pid) if out.returncode == 0 else None
        except (OSError, subprocess.TimeoutExpired):
            rss = None
        return {"rss_tree_bytes": rss, "container_memory_bytes": None}

    def cpu_seconds(self) -> float | None:
        if self.pid is None or not self.alive():
            return None
        try:
            if platform.system() == "Linux":
                return parse_proc_stat_cpu(Path(f"/proc/{self.pid}/stat").read_text(), os.sysconf("SC_CLK_TCK"))
            out = subprocess.run(["ps", "-o", "time=", "-p", str(self.pid)], capture_output=True, text=True, timeout=5)
            return parse_ps_time(out.stdout) if out.returncode == 0 else None
        except (OSError, subprocess.TimeoutExpired):
            return None

    def describe(self) -> dict:
        return {"kind": "local", "pid": self.pid, "port": self.port, "cmd": self.cmd[1:], "memory_limit_bytes": None}


class ContainerChild:
    """The same launcher inside a Docker container with a hard memory limit (`--memory`, no swap). This path
    is written to the Docker CLI's documented behaviour; its tests use an injected runner, and the Linux gate is
    filled only by a run against a daemon on a Linux kernel (`ContainerChild.daemon`)."""
    kind = "container"

    def __init__(self, *, name: str, port: int, image: str, env: dict, log_path: Path, startup_timeout: float,
                 data_dir: Path | None, memory: str = "512m", cpus: str = "1", fault: dict | None = None,
                 runner=subprocess.run, popen=subprocess.Popen):
        self.name, self.port, self.image, self.env = name, port, image, env
        self.log_path, self.startup_timeout, self.data_dir = log_path, startup_timeout, data_dir
        self.memory, self.cpus, self.fault, self.run, self.popen = memory, cpus, fault or {}, runner, popen
        self.container = f"aq01a-{os.getpid()}-{name}".replace("_", "-")
        self.pid: int | None = None
        self.startup_s: float | None = None
        self.base_url = f"http://127.0.0.1:{port}"
        self._cgroup: str | None = None
        self._logger: subprocess.Popen | None = None
        self._stats: dict | None = None
        self._started = False

    @staticmethod
    def available(which=None, runner=None) -> tuple[bool, str | None]:
        which, runner = which or shutil.which, runner or subprocess.run
        if not which("docker"):
            return False, "docker executable not found"
        try:
            if runner(["docker", "info"], capture_output=True, timeout=30).returncode != 0:
                return False, "docker daemon not reachable"
        except (OSError, subprocess.TimeoutExpired) as e:
            return False, f"docker not usable: {type(e).__name__}"
        return True, None

    @staticmethod
    def daemon(image: str | None = None, runner=None) -> dict | None:
        """The Docker daemon's kernel and cgroup facts (and the image's id/arch): the gate needs a Linux kernel
        enforcing the limit, which is the daemon's OS, not the host's (Colima/Docker Desktop run a Linux VM)."""
        runner = runner or subprocess.run
        try:
            out = runner(["docker", "info", "--format", "{{json .}}"], capture_output=True, text=True, timeout=30)
            info = json.loads(out.stdout) if out.returncode == 0 else None
        except (OSError, subprocess.TimeoutExpired, ValueError):
            info = None
        if not isinstance(info, dict):
            return None
        d = {"os_type": info.get("OSType"), "kernel": info.get("KernelVersion"),
             "operating_system": info.get("OperatingSystem"), "architecture": info.get("Architecture"),
             "cgroup_version": info.get("CgroupVersion"), "mem_total_bytes": info.get("MemTotal"),
             "ncpu": info.get("NCPU"), "server_version": info.get("ServerVersion"),
             "image_id": None, "image_architecture": None}
        if image:
            try:
                out = runner(["docker", "image", "inspect", "--format", "{{.Id}} {{.Architecture}}", image],
                             capture_output=True, text=True, timeout=30)
                parts = out.stdout.split() if out.returncode == 0 else []
                if len(parts) == 2:
                    d["image_id"], d["image_architecture"] = parts
            except (OSError, subprocess.TimeoutExpired):
                pass
        return d

    def command(self) -> list[str]:
        cmd = ["docker", "run", "-d", "--name", self.container, "--memory", self.memory,
               "--memory-swap", self.memory, "--cpus", self.cpus, "--restart", "no",
               "-p", f"127.0.0.1:{self.port}:{CONTAINER_PORT}", "-v", f"{SCRIPT}:/bench/benchmark-mcp.py:ro"]
        if self.data_dir is not None:
            cmd += ["-v", f"{self.data_dir}:/bench-data:ro"]
        for k, v in sorted(self.env.items()):
            cmd += ["-e", f"{k}={v}"]
        fault_args = [a for k, v in self.fault.items() for a in ("--fault-delay", f"{k}={v}")]
        return cmd + [self.image, "python", "/bench/benchmark-mcp.py", "serve", "--host", "0.0.0.0",
                      "--port", str(CONTAINER_PORT), "--app-root", "/app", *fault_args]

    def _docker(self, *args, timeout=30):
        try:
            return self.run(["docker", *args], capture_output=True, text=True, timeout=timeout)
        except (OSError, subprocess.TimeoutExpired):
            return None

    def start(self) -> None:
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        out = self.run(self.command(), capture_output=True, text=True, timeout=120)
        if out.returncode != 0:
            raise HarnessError(f"{self.name}: docker run failed: {(out.stderr or '')[-300:]}")
        self._started = True
        CHILDREN.add(self)
        with self.log_path.open("ab") as log:
            self._logger = self.popen(["docker", "logs", "-f", self.container], stdout=log,
                                      stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL)
        try:
            self.startup_s = wait_listening(self.port, self.startup_timeout, alive=self.alive)
        except HarnessError as e:
            detail = tail_text(self.log_path)
            self.stop()
            raise HarnessError(f"{self.name}: {e}; log tail: {detail!r}") from None

    def alive(self) -> bool:
        out = self._docker("inspect", "-f", "{{.State.Running}}", self.container)
        return bool(out and out.returncode == 0 and out.stdout.strip() == "true")

    def _read(self, *paths) -> str | None:
        for p in paths:
            out = self._docker("exec", self.container, "cat", p, timeout=10)
            if out is not None and out.returncode == 0 and out.stdout.strip():
                return out.stdout
        return None

    def sample(self) -> dict:
        text = self._read("/sys/fs/cgroup/memory.current", "/sys/fs/cgroup/memory/memory.usage_in_bytes")
        return {"rss_tree_bytes": None,
                "container_memory_bytes": int(text.strip()) if text and text.strip().isdigit() else None}

    def cpu_seconds(self) -> float | None:
        text = self._read("/sys/fs/cgroup/cpu.stat")
        m = re.search(r"usage_usec (\d+)", text or "")
        return int(m.group(1)) / 1e6 if m else None

    def stop(self) -> dict:
        if self._stats is not None:
            return self._stats
        CHILDREN.discard(self)
        peak = oom_events = None
        if self._started and self.alive():
            text = self._read("/sys/fs/cgroup/memory.peak", "/sys/fs/cgroup/memory/memory.max_usage_in_bytes")
            peak = int(text.strip()) if text and text.strip().isdigit() else None
            ev = self._read("/sys/fs/cgroup/memory.events")
            m = re.search(r"oom_kill (\d+)", ev or "")
            oom_events = int(m.group(1)) if m else None
        cpu = self.cpu_seconds() if self._started and self.alive() else None
        state = {"oom": None, "restarts": None, "code": None}
        if self._started:
            out = self._docker("inspect", "-f", "{{.State.OOMKilled}} {{.RestartCount}} {{.State.ExitCode}}",
                               self.container)
            if out is not None and out.returncode == 0:
                parts = out.stdout.split()
                if len(parts) == 3:
                    state = {"oom": parts[0] == "true", "restarts": int(parts[1]), "code": int(parts[2])}
            self._docker("stop", "-t", "8", self.container, timeout=40)
            self._docker("rm", "-f", self.container)
        if self._logger is not None:
            with contextlib.suppress(Exception):
                self._logger.terminate()
        self._stats = {"exit_code": state["code"], "signal": None, "stopped_by_harness": True,
                       "oom_suspected": state["oom"] or bool(oom_events), "oom_killed": state["oom"],
                       "oom_kill_events": oom_events, "restarts": state["restarts"],
                       "cpu_s_total": None if cpu is None else round(cpu, 3),
                       "rss_peak_kernel_bytes": None, "container_memory_peak_bytes": peak}
        return self._stats

    def describe(self) -> dict:
        return {"kind": "container", "container": self.container, "image": self.image, "port": self.port,
                "memory_limit": self.memory, "memory_swap": self.memory, "cpus": self.cpus,
                "memory_limit_bytes": parse_memory_flag(self.memory)}


class ResourceMonitor:
    """Samples a child's memory in a thread; named windows get their own peaks and CPU deltas."""

    def __init__(self, child, interval: float = 0.1):
        self.child, self.interval = child, interval
        self._open: dict = {}
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(5)

    def _loop(self) -> None:
        while not self._stop.is_set():
            self._take()
            self._stop.wait(self.interval)

    def _take(self) -> None:
        try:
            s = self.child.sample()
        except Exception:  # noqa: BLE001
            s = {}
        with self._lock:
            for w in self._open.values():
                w["samples"] += 1
                for key, field in (("rss_tree_bytes", "rss_peak_bytes"),
                                   ("container_memory_bytes", "container_memory_peak_bytes")):
                    v = s.get(key)
                    if v is not None and (w[field] is None or v > w[field]):
                        w[field] = v

    @contextlib.contextmanager
    def window(self, name: str):
        w = {"name": name, "wall_s": None, "samples": 0, "rss_peak_bytes": None,
             "container_memory_peak_bytes": None, "cpu_s": None}
        t0, cpu0 = time.perf_counter(), None
        with contextlib.suppress(Exception):
            cpu0 = self.child.cpu_seconds()
        with self._lock:
            self._open[id(w)] = w
        self._take()
        try:
            yield w
        finally:
            self._take()
            with self._lock:
                self._open.pop(id(w), None)
            w["wall_s"] = round(time.perf_counter() - t0, 3)
            cpu1 = None
            with contextlib.suppress(Exception):
                cpu1 = self.child.cpu_seconds()
            if cpu0 is not None and cpu1 is not None:
                w["cpu_s"] = round(cpu1 - cpu0, 3)


# ====================================================================== child-side sub-commands

def _emit(tag: str, obj: dict) -> None:
    sys.stderr.write(f"{tag} {json.dumps(obj, separators=(',', ':'), default=str)}\n")
    sys.stderr.flush()


def install_guards(fault_delays: dict | None = None) -> None:
    """In the child: any provider call is recorded and refused; every tool dispatch is logged (so a
    refusal at the gate can be shown not to have dispatched). `fault_delays` (harness self-test only)
    maps a tool to (seconds, count): its first `count` dispatches sleep in plain Python, which no cursor
    interrupt can reach, standing in for uninterruptible slow work."""
    from app.services import llm_client
    from app.services.tools import registry

    def blocked(fn):
        def refuse(*_a, **_k):
            _emit("BENCH_PROVIDER_CALL", {"fn": fn})
            raise RuntimeError("provider calls are disabled in the benchmark child")
        return refuse
    for fn in ("_anthropic", "_openai_responses", "_openai"):
        if hasattr(llm_client, fn):
            setattr(llm_client, fn, blocked(fn))
    real = registry.call_tool
    delays = {k: list(v) for k, v in (fault_delays or {}).items()}
    lock = threading.Lock()

    def traced(name, arguments, **kw):
        _emit("BENCH_DISPATCH", {"tool": str(name)[:40]})
        with lock:
            d = delays.get(name)
            hold = d[0] if d and d[1] > 0 else 0.0
            if hold:
                d[1] -= 1
        if hold:
            time.sleep(hold)
        return real(name, arguments, **kw)
    registry.call_tool = traced


def serve(args) -> int:
    """Child entry point: the real application under uvicorn, one worker."""
    app_root = Path(args.app_root).resolve()
    sys.path.insert(0, str(app_root))
    os.chdir(app_root)
    import logging
    import uvicorn
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(logging.Formatter("%(message)s"))
    mcp_log = logging.getLogger("app.mcp")
    mcp_log.setLevel(logging.INFO)
    mcp_log.addHandler(handler)
    mcp_log.propagate = False
    faults = {}
    for item in args.fault_delay or []:
        name, _, spec = item.partition("=")
        secs, _, count = spec.partition(":")
        faults[name] = (float(secs), int(count or 1))
    from app import config
    from app.main import app
    from app.services import generation, public_mcp
    install_guards(faults)
    mcp = getattr(app.state, "public_mcp", None)
    settings = None if mcp is None else {k: (list(v) if isinstance(v, tuple) else v)
                                         for k, v in dataclasses.asdict(mcp.settings).items()}
    _emit("BENCH_CHILD", {
        "pid": os.getpid(), "python": platform.python_version(), "system": platform.system(),
        "data_dir": str(config.DATA_DIR), "mcp_settings": settings, "policy_version": public_mcp.POLICY_VERSION,
        "max_data_rows": config.MAX_DATA_ROWS, "generation": generation.summary(),
        "fault_delays": faults or None, "env_ask_enabled": config.ASK_ENABLED,
        "db_memory": os.environ.get("TEMPO_DB_MEMORY"), "db_threads": os.environ.get("TEMPO_DB_THREADS"),
        "imported_rss_bytes": rss_to_bytes(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss, "ru_maxrss")})
    uvicorn.run(app, host=args.host, port=args.port, workers=1, log_level="warning", access_log=False)
    return 0


def inproc(args) -> int:
    """Call the shared tools directly (no gate) for numerical parity with what the MCP returned."""
    app_root = Path(args.app_root).resolve()
    sys.path.insert(0, str(app_root))
    os.chdir(app_root)
    install_guards({})
    from app.services.tools import registry
    requests = json.loads(Path(args.requests).read_text())
    results, t_all, c_all = [], time.perf_counter(), time.process_time()
    for r in requests:
        t0 = time.perf_counter()
        env = registry.call_tool(r["tool"], r["arguments"])
        results.append({"id": r["id"], "wall_s": round(time.perf_counter() - t0, 4), "envelope": env})
    out = {"results": results, "wall_s": round(time.perf_counter() - t_all, 4),
           "cpu_s": round(time.process_time() - c_all, 3),
           "rss_peak_bytes": rss_to_bytes(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss, "ru_maxrss")}
    Path(args.out).write_text(json.dumps(out))
    return 0


# ====================================================================== run configuration

@dataclasses.dataclass
class Workload:
    """The request family measured: a one-year city ranking of the national locality population."""
    dataset: str = "POP107D_grupe_localitate"
    entity_columns: list = dataclasses.field(default_factory=lambda: ["REF_AREA", "REF_AREA_2"])
    entity_class: str = "cities"
    county_column: str = "REF_AREA"
    discover_query: str = "populatia orase"
    top_k: int = 30
    year: str | None = None
    years: list | None = None
    counties: list | None = None
    over_limit_dataset: str | None = None
    export_dataset: str | None = None

    def rank_args(self, year=None, top_k=None, county=None, dataset=None) -> dict:
        a = {"dataset": dataset or self.dataset, "entity_columns": list(self.entity_columns),
             "entity_class": self.entity_class, "top_k": top_k or self.top_k}
        if year:
            a["year"] = str(year)
        if county:
            a["filters"] = {self.county_column: [county]}
        return a


@dataclasses.dataclass
class Cfg:
    data_dir: Path
    out_dir: Path
    mode: str = "local"
    image: str | None = None
    container_memory: str = "512m"
    container_cpus: str = "1"
    container_data: str = "mount"
    cold_repeats: int = 5
    warm_samples: int = 20
    concurrency: int = 5
    declared: dict = dataclasses.field(default_factory=dict)
    overrides: dict = dataclasses.field(default_factory=dict)
    workload: Workload = dataclasses.field(default_factory=Workload)
    scenarios: tuple = SCENARIOS
    mixed_phases: tuple = (("single_client", 1, 0, 10.0), ("five_clients", 5, 2, 10.0))
    rest_requests: list | None = None
    ports: list | None = None
    call_timeout: float = 30.0
    startup_timeout: float = 90.0
    max_total_seconds: float = 3600.0
    cancel_after: float = 0.01
    timeout_probe_seconds: float = 1.0
    label: str = ""

    @property
    def profile_name(self) -> str:
        capacity = {k for k in self.declared if k != "TEMPO_DB_THREADS"}
        return "candidate" if capacity else "control"


def scale_report(cfg: Cfg) -> dict:
    """Whether the run met the sample counts the spec asks for; a reduced run says so."""
    short = []
    if cfg.cold_repeats < REQUIRED_N["cold"]:
        short.append(f"cold repetitions {cfg.cold_repeats} < {REQUIRED_N['cold']}")
    if cfg.warm_samples < REQUIRED_N["cache"]:
        short.append(f"warm samples {cfg.warm_samples} < {REQUIRED_N['cache']}")
    phases = {p[0]: p for p in cfg.mixed_phases}
    for name, clients, seconds in AT04_PHASES:
        got = phases.get(name)
        if not got or got[1] < clients or got[3] < seconds:
            short.append(f"mixed phase {name} ({clients} MCP client(s), {seconds:g}s) not run at AT-04 length")
    return {"meets_spec_counts": not short, "shortfalls": short, "cold_repeats": cfg.cold_repeats,
            "warm_samples": cfg.warm_samples,
            "label": "full" if not short else "reduced"}


def parse_phase(text: str) -> tuple:
    name, *rest = text.split(":")
    try:
        mcp, rest_clients, seconds = int(rest[0]), int(rest[1]), float(rest[2])
    except (IndexError, ValueError):
        raise HarnessError(f"--mixed-phase must be NAME:MCP_CLIENTS:REST_CLIENTS:SECONDS, not {text!r}") from None
    if not name or mcp < 0 or rest_clients < 0 or mcp + rest_clients < 1 or seconds <= 0:
        raise HarnessError(f"--mixed-phase needs at least one client and positive seconds: {text!r}")
    return name, mcp, rest_clients, seconds


class Budget:
    """The harness bounds itself: a total wall-clock budget checked between and inside scenarios."""

    def __init__(self, seconds: float, clock=time.monotonic):
        self.clock, self.end = clock, clock() + seconds

    def remaining(self) -> float:
        return max(0.0, self.end - self.clock())

    def check(self, what: str) -> None:
        if self.remaining() <= 0:
            raise HarnessError(f"harness time budget exhausted before {what}")


class Ctx:
    def __init__(self, cfg: Cfg, report: dict):
        self.cfg, self.report, self.wl = cfg, report, cfg.workload
        self.recorder = Recorder()
        self.budget = Budget(cfg.max_total_seconds)
        self.parity: dict = {}
        self.checks: dict = report["checks"]
        self._port_i = 0
        self.problems: list = []

    def next_port(self) -> int:
        ports = self.cfg.ports
        if not ports:
            return pick_port(None)
        i = self._port_i % len(ports)
        port = pick_port(ports[i:] + ports[:i])                      # round robin over the assigned range
        self._port_i = ports.index(port) + 1
        return port

    def flush(self) -> None:
        write_report(self.cfg, self.report, self.recorder)

    def cap(self) -> int | None:
        """The scan cap the children actually run with: the child's own report, else the declaration."""
        for r in self.report["runs"]:
            v = ((r.get("child") or {}).get("mcp_settings") or {}).get("max_scan_rows")
            if v:
                return int(v)
        v = self.cfg.declared.get("TEMPO_MCP_MAX_SCAN_ROWS")
        return int(float(v)) if v else None


# ====================================================================== running a child

class Run:
    def __init__(self, name, child, tail, monitor, record):
        self.name, self.child, self.tail, self.monitor, self.record = name, child, tail, monitor, record
        self.log_ok = False


def summarize_events(events: list[dict]) -> dict:
    m = [e for e in events if e["kind"] == "MCP_METRICS"]
    return {"gate_calls": len(m), "cache_hits": sum(1 for e in m if e.get("cached")),
            "results": dict(Counter(f"{e.get('status')}/{e.get('reason')}" for e in m)),
            "dispatches": dict(Counter(e["tool"] for e in events if e["kind"] == "BENCH_DISPATCH")),
            "provider_calls": sum(1 for e in events if e["kind"] == "BENCH_PROVIDER_CALL")}


@contextlib.asynccontextmanager
async def running_child(ctx: Ctx, name: str, scenario: str, *, fault: dict | None = None, overrides: dict | None = None):
    cfg = ctx.cfg
    port = ctx.next_port()
    log_path = cfg.out_dir / "logs" / f"{name}.log"
    merged = {**cfg.overrides, **(overrides or {})}
    if cfg.mode == "container":
        data_in = "/bench-data" if cfg.container_data == "mount" else "/app/data"
        env = build_child_env({}, data_dir=data_in, port=port, declared=cfg.declared, overrides=merged)
        child = ContainerChild(name=name, port=port, image=cfg.image, env={k: v for k, v in env.items() if k.startswith(("TEMPO_", "PYTHON"))},
                               log_path=log_path, startup_timeout=cfg.startup_timeout,
                               data_dir=cfg.data_dir if cfg.container_data == "mount" else None,
                               memory=cfg.container_memory, cpus=cfg.container_cpus, fault=fault)
    else:
        env = build_child_env(os.environ, data_dir=str(cfg.data_dir), port=port, declared=cfg.declared, overrides=merged)
        child = LocalChild(name=name, port=port, env=env, log_path=log_path, startup_timeout=cfg.startup_timeout,
                           fault=fault)
    record = {"name": name, "scenario": scenario, "port": port, "profile_overrides": overrides or None,
              "env_names": sorted(env),
              "fault_delays": fault or None, "log": str(log_path.relative_to(cfg.out_dir)), "child": None,
              "target": child.describe()}
    ctx.report["runs"].append(record)
    run = Run(name, child, LogTail(log_path), None, record)
    monitor = None
    try:
        child.start()
        record.update(pid=child.pid, startup_s=round(child.startup_s, 4), target=child.describe())
        run.tail.take()
        info = next((e for e in run.tail.all if e["kind"] == "BENCH_CHILD"), None)
        if info:
            run.log_ok = True
            record["child"] = {k: v for k, v in info.items() if k != "kind"}
        monitor = run.monitor = ResourceMonitor(child)
        monitor.start()
        yield run
    except BaseException as e:
        record["error"] = f"{type(e).__name__}: {str(e)[:300]}"
        raise
    finally:
        if monitor is not None:
            monitor.stop()
        stats = child.stop()
        run.tail.take()
        record["stats"] = stats
        record["events"] = summarize_events(run.tail.all)
        if stats.get("oom_suspected"):
            ctx.problems.append(f"{name}: child killed (OOM suspected)")
        if stats.get("restarts"):
            ctx.problems.append(f"{name}: container restarted {stats['restarts']}x")
        ctx.flush()


# ====================================================================== the MCP driver

class WireCounter:
    """HTTP response bytes (Content-Length) seen by one client; a response without the header makes the
    interval unknown (None), never zero."""

    def __init__(self):
        self.total, self.unknown, self._lock = 0, 0, threading.Lock()

    def add(self, header) -> None:
        with self._lock:
            if header is not None and str(header).isdigit():
                self.total += int(header)
            else:
                self.unknown += 1

    def mark(self) -> tuple:
        with self._lock:
            return self.total, self.unknown

    def since(self, mark: tuple) -> int | None:
        with self._lock:
            return self.total - mark[0] if self.unknown == mark[1] else None


class Sess:
    def __init__(self, session, wire, initialize_s):
        self.session, self.wire, self.initialize_s = session, wire, initialize_s


@contextlib.asynccontextmanager
async def open_session(ctx: Ctx, run: Run):
    """An initialized SDK ClientSession over Streamable HTTP to the child (the real client and transport)."""
    import httpx
    from mcp import ClientSession
    from mcp.client.streamable_http import streamable_http_client
    wire = WireCounter()

    async def on_response(resp):
        wire.add(resp.headers.get("content-length"))
    async with httpx.AsyncClient(timeout=ctx.cfg.call_timeout + 10, event_hooks={"response": [on_response]}) as client:
        async with streamable_http_client(f"{run.child.base_url}/mcp", http_client=client) as (r, w, _):
            async with ClientSession(r, w) as s:
                t0 = time.perf_counter()
                await asyncio.wait_for(s.initialize(), ctx.cfg.call_timeout)
                yield Sess(s, wire, time.perf_counter() - t0)


def _envelope(res) -> dict | None:
    if isinstance(res.structuredContent, dict):
        return res.structuredContent
    try:
        return json.loads(res.content[0].text)
    except (IndexError, ValueError, AttributeError):
        return None


class Result:
    def __init__(self, sample, env):
        self.sample, self.env = sample, env

    @property
    def served(self) -> bool:
        return self.sample["outcome"] == "served"


async def call(ctx: Ctx, run: Run, sess: Sess, case: str, state: str, tool: str, args: dict, *,
               variant=None, record: bool = True, attribute: bool = True, expect_error: bool = False) -> Result:
    """One timed tools/call. `attribute` reads the child's log after the call to say whether the result
    cache answered and whether the tool was dispatched (only sound for one call in flight)."""
    if attribute:
        run.tail.take()
    mark = sess.wire.mark()
    t0 = time.perf_counter()
    env, error, rbytes = None, None, None
    try:
        res = await asyncio.wait_for(sess.session.call_tool(tool, args), ctx.cfg.call_timeout)
        wall = time.perf_counter() - t0
        env = _envelope(res)
        outcome, status, reason, detail = classify(env, bool(res.isError))
        if env is not None:
            rbytes = len(json.dumps(env, separators=(",", ":"), ensure_ascii=False).encode("utf-8"))
    except asyncio.TimeoutError:
        wall, outcome, status, reason, detail = time.perf_counter() - t0, "timeout", None, None, None
        error = f"no answer within {ctx.cfg.call_timeout:g}s"
    except asyncio.CancelledError:
        raise
    except Exception as e:  # noqa: BLE001 — a transport failure is a counted outcome, not a crash
        wall, outcome, status, reason, detail = time.perf_counter() - t0, "transport_error", None, None, None
        error = f"{type(e).__name__}: {e}"
    wire = sess.wire.since(mark)
    cached = dispatched = None
    if attribute and run.log_ok:
        events = run.tail.take()
        metrics = [e for e in events if e["kind"] == "MCP_METRICS"]
        if metrics:
            cached = any(bool(e.get("cached")) for e in metrics)
        dispatched = any(e["kind"] == "BENCH_DISPATCH" and e.get("tool") == tool for e in events)
    if outcome == "served" and cached is not None and state in ("miss_warm", "cache"):
        state = "cache" if cached else "miss_warm"          # label by what happened, not by what was intended
    sample = {"case": case, "state": state, "wall_s": wall, "outcome": outcome, "status": status, "reason": reason,
              "detail": detail, "cached": cached, "dispatched": dispatched, "result_bytes": rbytes,
              "wire_bytes": wire, "run": run.name, "variant": variant, "error": error}
    if record:
        ctx.recorder.add(**sample)
    if outcome in ("transport_error", "protocol_error", "timeout") or (outcome == "tool_error" and not expect_error):
        ctx.problems.append(f"{case}: {outcome} {reason or error or ''}"[:200])
    return Result(sample, env)


async def timed(ctx: Ctx, run: Run, case: str, state: str, fn) -> object:
    """Time any awaitable-producing callable (initialize, list_tools); failure is recorded, then raised."""
    t0 = time.perf_counter()
    try:
        out = await asyncio.wait_for(fn(), ctx.cfg.call_timeout)
    except Exception as e:  # noqa: BLE001
        ctx.recorder.add(case, state, wall_s=time.perf_counter() - t0,
                         outcome="timeout" if isinstance(e, asyncio.TimeoutError) else "transport_error",
                         run=run.name, error=f"{type(e).__name__}: {e}")
        raise
    ctx.recorder.add(case, state, wall_s=time.perf_counter() - t0, outcome="served", run=run.name)
    return out


def resolve_workload(ctx: Ctx, env) -> None:
    """Fill the years and county sample from a describe_dataset envelope (metadata only: scan-gated tools
    such as find_dimension_values are refused under the control profile)."""
    wl = ctx.wl
    if not isinstance(env, dict) or env.get("status") not in SERVED:
        return
    d = env.get("data") or {}
    t = d.get("time") or {}
    try:
        last, first = int(t["last"]), int(t["first"])
    except (KeyError, TypeError, ValueError):
        last = first = None
    if last is not None:
        wl.year = wl.year or str(last)
        wl.years = wl.years or [str(y) for y in range(last, max(first, last - 11) - 1, -1)]
    if not wl.counties:
        for dim in d.get("dimensions") or []:
            if dim.get("column") == wl.county_column and isinstance(dim.get("examples"), list):
                wl.counties = [str(x) for x in dim["examples"][:3]]


class VariantPool:
    """Distinct rank requests that cannot hit the result cache: (year, county, K) combinations never used."""

    def __init__(self, wl: Workload):
        self.wl, self.used = wl, set()

    @staticmethod
    def key(args: dict) -> str:
        return json.dumps(args, sort_keys=True)

    def take(self, args: dict) -> dict:
        self.used.add(self.key(args))
        return args

    def fresh(self, n: int, *, counties: bool) -> list[tuple[dict, dict]]:
        """Up to n unused (variant, args): years x (counties) at K=30 first, then other K values."""
        wl, out = self.wl, []
        years = wl.years or ([wl.year] if wl.year else [None])
        counts = (wl.counties or []) if counties else [None]
        if counties and not counts:
            return []
        ks = [wl.top_k] + [k for k in range(wl.top_k - 1, 1, -1)] + list(range(wl.top_k + 1, 100))
        for k in ks:
            for y in years:
                for c in counts:
                    a = wl.rank_args(year=y, top_k=k, county=c)
                    if self.key(a) in self.used:
                        continue
                    self.used.add(self.key(a))
                    out.append(({"year": y, "county": c, "top_k": k}, a))
                    if len(out) >= n:
                        return out
        return out


async def await_slot_free(ctx: Ctx, run: Run, sess: Sess, pool: VariantPool, timeout: float):
    """Poll with fresh rank requests (a cached answer never touches the slot) until one is not answered
    `busy`. That call is also the first request after the work. Returns (seconds, Result) or (None, None)."""
    t0 = time.perf_counter()
    while time.perf_counter() - t0 < timeout:
        fresh = pool.fresh(1, counties=False)
        if not fresh:
            break
        r = await call(ctx, run, sess, "slot_poll", "observed", "rank_entities", fresh[0][1], attribute=False,
                       record=False)
        if r.sample["reason"] != "busy":
            return time.perf_counter() - t0, r
        await asyncio.sleep(0.05)
    return None, None


def ranking_view(env: dict | None) -> dict | None:
    """The numerical content of a rank envelope that parity and the k-invariance check compare."""
    if not isinstance(env, dict) or env.get("status") not in SERVED:
        return None
    d = env.get("data") or {}
    rows = d.get("rows") or []
    return {"year": d.get("year"), "unit": d.get("unit"), "eligible_count": d.get("eligible_count"),
            "excluded_count": d.get("excluded_count"), "outside_class_count": d.get("outside_class_count"),
            "n_rows": len(rows), "values": [r.get("value") for r in rows],
            "top": [{"rank": r.get("rank"), "entity": r.get("entity"), "value": r.get("value")} for r in rows[:3]],
            "source_complete": (env.get("limits") or {}).get("source_complete")}


def k_invariance(views: dict) -> dict:
    """Top K limits presentation only: eligible/excluded/outside counts and the shared prefix must agree."""
    got = {k: v for k, v in views.items() if v}
    if len(got) < 2:
        return {"status": "not_run", "reason": "fewer than two K values were served", "served": sorted(got)}
    base_k = sorted(got)[0]
    base = got[base_k]
    problems = []
    for k, v in got.items():
        for f in ("year", "unit", "eligible_count", "excluded_count", "outside_class_count", "source_complete"):
            if v[f] != base[f]:
                problems.append(f"K={k}: {f} {v[f]!r} != {base[f]!r}")
        n = min(len(v["values"]), len(base["values"]))
        if v["values"][:n] != base["values"][:n]:
            problems.append(f"K={k}: ranked values differ from K={base_k}")
        if v["n_rows"] != min(k, v["eligible_count"] or 0):
            problems.append(f"K={k}: returned {v['n_rows']} rows for {v['eligible_count']} eligible")
    return {"status": "fail" if problems else "pass", "k_values": sorted(got), "problems": problems[:10],
            "eligible_count": base["eligible_count"]}


def scan_admission_check(est, cap, sample) -> dict:
    """The gate must refuse (query_budget, never dispatched) exactly when the footer estimate exceeds the cap."""
    base = {"estimated_rows": est, "scan_cap": cap}
    if est is None or cap is None:
        return {"status": "not_run", "reason": "estimate or cap unknown", **base}
    refused_budget = sample["outcome"] == "refused" and sample["reason"] == "query_budget"
    if est > cap:
        if sample["dispatched"] is None:
            return {"status": "not_run", "reason": "dispatch log unavailable", "observed": sample["reason"], **base}
        ok = refused_budget and sample["dispatched"] is False
        return {"status": "pass" if ok else "fail", "expected": "unavailable/query_budget, handler not dispatched",
                "observed": f"{sample['status']}/{sample['reason']}", "dispatched": sample["dispatched"], **base}
    ok = not refused_budget
    return {"status": "pass" if ok else "fail", "expected": "admitted (estimate within cap)",
            "observed": f"{sample['status']}/{sample['reason']}", **base}


# ====================================================================== scenarios

async def _cold_repetition(ctx: Ctx, i: int, scenario: str, chain: bool) -> None:
    wl, name = ctx.wl, f"{scenario}-{i + 1}"
    async with running_child(ctx, name, scenario) as run:
        with run.monitor.window(name) as win:
            ctx.recorder.add(f"{scenario}.startup", "cold", wall_s=run.child.startup_s, outcome="served", run=name)
            async with open_session(ctx, run) as sess:
                ctx.recorder.add(f"{scenario}.initialize", "cold", wall_s=sess.initialize_s, outcome="served", run=name)
                if chain:
                    tools = await timed(ctx, run, f"{scenario}.list_tools", "cold", sess.session.list_tools)
                    run.record["tools"] = [t.name for t in tools.tools]
                    await call(ctx, run, sess, f"{scenario}.discover_indicators", "cold", "discover_indicators",
                               {"query": wl.discover_query})
                    d = await call(ctx, run, sess, f"{scenario}.describe_dataset", "cold", "describe_dataset",
                                   {"dataset": wl.dataset})
                    resolve_workload(ctx, d.env)
                await call(ctx, run, sess, f"{scenario}.rank_entities", "cold", "rank_entities",
                           wl.rank_args(year=wl.year))
        run.record["window"] = win


async def _cold_repetitions(ctx: Ctx, scenario: str, chain: bool) -> None:
    """Fresh-process repetitions; one that fails is recorded and the others still run, then the scenario fails."""
    failures = []
    for i in range(ctx.cfg.cold_repeats):
        ctx.budget.check(scenario)
        try:
            await _cold_repetition(ctx, i, scenario, chain)
        except Exception as e:  # noqa: BLE001
            failures.append(f"{scenario}-{i + 1}: {type(e).__name__}: {str(e)[:160]}")
    if failures:
        raise HarnessError(f"{len(failures)} of {ctx.cfg.cold_repeats} repetitions failed: {'; '.join(failures)}")


async def scenario_cold_chain(ctx: Ctx) -> None:
    await _cold_repetitions(ctx, "cold_chain", True)


async def scenario_cold_first_rank(ctx: Ctx) -> None:
    await _cold_repetitions(ctx, "cold_first_rank", False)


async def scenario_warm(ctx: Ctx) -> None:
    cfg, wl, rec = ctx.cfg, ctx.wl, ctx.recorder
    pool = VariantPool(wl)
    pairs: dict = {}
    async with running_child(ctx, "warm", "warm") as run:
        port = run.child.port
        async with open_session(ctx, run) as sess:
            d = await call(ctx, run, sess, "warm.setup_describe", "cold", "describe_dataset", {"dataset": wl.dataset},
                           record=False)
            resolve_workload(ctx, d.env)

            async def rank(case, state, args, key=None, variant=None):
                r = await call(ctx, run, sess, case, state, "rank_entities", args, variant=variant)
                if key:
                    pairs[key] = (args, r)
                return r
            a0 = pool.take(wl.rank_args(year=wl.year))
            with run.monitor.window("first_rank") as w:
                await rank("warm.first_rank_after_describe", "cold", a0, "exact_year")
            run.record.setdefault("windows", []).append(w)
            with run.monitor.window("cache") as w:                              # 1. the result cache
                for _ in range(cfg.warm_samples):
                    await rank("rank_exact_year", "cache", a0)
            rec.annotate("rank_exact_year", "cache", cpu_s_total=w["cpu_s"], rss_peak_bytes=w["rss_peak_bytes"])
            run.record["windows"].append(w)
            latest = pool.take(wl.rank_args())                                  # 2. latest year (year omitted)
            await rank("rank_latest_year", "miss_warm", latest, "latest_year")
            y2 = (wl.years or [wl.year])[1 if len(wl.years or []) > 1 else 0]
            views = {}
            for k in (1, 30, 100):                                              # 3. top K at one unused year
                a = pool.take(wl.rank_args(year=y2, top_k=k))
                r = await rank(f"rank_topk_{k}", "miss_warm", a, f"k{k}")
                views[k] = ranking_view(r.env)
            ctx.checks["k_invariance"] = k_invariance(views)
            for case, counties in (("rank_year_miss", False), ("rank_county_miss", True)):   # 4. misses, metadata warm
                variants = pool.fresh(cfg.warm_samples, counties=counties)
                with run.monitor.window(case) as w:
                    for n, (variant, args) in enumerate(variants):
                        key = f"{case}_first" if n == 0 else None
                        await rank(case, "miss_warm", args, key, variant)
                rec.annotate(case, "miss_warm", cpu_s_total=w["cpu_s"], rss_peak_bytes=w["rss_peak_bytes"],
                             variant_axes=("year,K" if not counties else "county,year,K"))
                run.record["windows"].append(w)
                if len(variants) < cfg.warm_samples:
                    rec.annotate(case, "miss_warm", note=f"only {len(variants)} distinct variants available")
            # 5. metadata tools (their own warm targets): cached describe, varied then repeated discovery
            for _ in range(cfg.warm_samples):
                await call(ctx, run, sess, "describe_dataset", "cache", "describe_dataset", {"dataset": wl.dataset})
            queries = [f"{wl.discover_query} {2000 + i}" for i in range(cfg.warm_samples)]
            for q in queries:
                await call(ctx, run, sess, "discover_indicators", "miss_warm", "discover_indicators", {"query": q})
            for _ in range(cfg.warm_samples):
                await call(ctx, run, sess, "discover_indicators", "cache", "discover_indicators", {"query": queries[0]})
    ctx.parity = pairs
    run_parity(ctx, port)


def run_parity(ctx: Ctx, port: int) -> None:
    """MCP result vs the shared tool called directly in a fresh process, for the same selection/generation.
    `port` is the MCP child's: its public base URL is part of every link in the envelope."""
    pairs = {k: v for k, v in ctx.parity.items() if v[1].served and v[1].env}
    if not pairs:
        ctx.checks["parity"] = {"status": "not_run", "reason": "no served MCP answer to compare (all refused)",
                                "compared": 0}
        return
    pdir = ctx.cfg.out_dir / "parity"
    pdir.mkdir(parents=True, exist_ok=True)
    (pdir / "requests.json").write_text(json.dumps(
        [{"id": k, "tool": "rank_entities", "arguments": a} for k, (a, _r) in pairs.items()]))
    env = build_child_env(os.environ, data_dir=str(ctx.cfg.data_dir), port=port, declared=ctx.cfg.declared,
                          overrides=ctx.cfg.overrides)
    proc = subprocess.run([sys.executable, str(SCRIPT), "inproc", "--app-root", str(ROOT),
                           "--requests", str(pdir / "requests.json"), "--out", str(pdir / "direct.json")],
                          env=env, cwd=str(ROOT), capture_output=True, text=True,
                          timeout=max(60.0, ctx.budget.remaining()))
    if proc.returncode != 0:
        ctx.checks["parity"] = {"status": "fail", "reason": f"direct run failed: {proc.stderr[-300:]}", "compared": 0}
        return
    direct = json.loads((pdir / "direct.json").read_text())
    by_id = {r["id"]: r for r in direct["results"]}
    rows, bad = [], 0
    for k, (args, res) in pairs.items():
        d_env = by_id[k]["envelope"]
        diffs = diff_json(res.env, d_env)
        same = {f: (res.env.get("data", {}).get(f) == d_env.get("data", {}).get(f))
                for f in ("rows", "eligible_count", "excluded_count", "outside_class_count", "unit")}
        same["sources"] = (res.env.get("provenance", {}).get("sources") == d_env.get("provenance", {}).get("sources"))
        same["scope"] = (res.env.get("provenance", {}).get("scope") == d_env.get("provenance", {}).get("scope"))
        same["warnings"] = res.env.get("warnings") == d_env.get("warnings")
        bad += bool(diffs)
        rows.append({"id": k, "equal": not diffs, "differences": diffs, "fields_equal": same,
                     "mcp_sha256": sha256_json(res.env), "direct_sha256": sha256_json(d_env),
                     "view": ranking_view(res.env)})
    ctx.checks["parity"] = {"status": "fail" if bad else "pass", "compared": len(rows), "differing": bad,
                            "ignored_keys": sorted(IGNORED_IN_PARITY), "executed_in": "fresh local process",
                            "direct": {"wall_s": direct["wall_s"], "cpu_s": direct["cpu_s"],
                                       "rss_peak_bytes": direct["rss_peak_bytes"]},
                            "requests": rows}


async def scenario_admission(ctx: Ctx) -> None:
    cfg, wl = ctx.cfg, ctx.wl
    est = next((d["rows"] for d in ctx.report["data"]["datasets"] if d["dataset"] == wl.dataset), None)
    pool = VariantPool(wl)
    async with running_child(ctx, "admission", "admission") as run:
        async with open_session(ctx, run) as sess:
            d = await call(ctx, run, sess, "admission.setup_describe", "observed", "describe_dataset",
                           {"dataset": wl.dataset}, record=False)
            resolve_workload(ctx, d.env)
            await call(ctx, run, sess, "admission.unknown_dataset", "observed", "rank_entities",
                       wl.rank_args(year=wl.year, dataset="NOSUCH_AQ01"), expect_error=True)
            r = await call(ctx, run, sess, "admission.workload_rank", "observed", "rank_entities",
                           pool.take(wl.rank_args(year=wl.year)))
            cap = ctx.cap()
            ctx.checks["scan_admission"] = scan_admission_check(est, cap, r.sample)
            if wl.over_limit_dataset:
                over = next((x["rows"] for x in ctx.report["data"]["datasets"] if x["dataset"] == wl.over_limit_dataset), None)
                ro = await call(ctx, run, sess, "admission.over_limit_dataset", "observed", "rank_entities",
                                wl.rank_args(year=wl.year, dataset=wl.over_limit_dataset))
                ctx.checks["scan_admission_over_limit_dataset"] = scan_admission_check(over, cap, ro.sample)
            # simultaneous calls from independent sessions
            fresh = pool.fresh(cfg.concurrency, counties=False)
            async with contextlib.AsyncExitStack() as stack:
                sessions = [await stack.enter_async_context(open_session(ctx, run)) for _ in fresh]
                t0 = time.perf_counter()
                outs = await asyncio.gather(*[
                    call(ctx, run, s, "admission.concurrent_rank", "observed", "rank_entities", a, variant=v,
                         attribute=False) for s, (v, a) in zip(sessions, fresh)], return_exceptions=True)
                wall = time.perf_counter() - t0
            kinds = Counter(f"{o.sample['outcome']}/{o.sample['reason']}" for o in outs if isinstance(o, Result))
            ctx.report["observations"]["concurrency"] = {
                "clients": len(fresh), "wall_s": round(wall, 4), "results": dict(kinds),
                "max_concurrent": ((run.record.get("child") or {}).get("mcp_settings") or {}).get("max_concurrent")}
            await _cancellation(ctx, run, sess, pool)


async def _cancellation(ctx: Ctx, run: Run, sess: Sess, pool: VariantPool) -> None:
    """A caller that hangs up mid-call: the slot must stay taken until the work really ends."""
    fresh = pool.fresh(2, counties=False)
    if len(fresh) < 2:
        ctx.report["observations"]["cancellation"] = {"status": "not_run", "reason": "no unused request variants"}
        return
    (_, first), (_, second) = fresh
    started = asyncio.Event()

    async def hang_up():
        async with open_session(ctx, run) as s:
            started.set()
            await s.session.call_tool("rank_entities", first)
    run.tail.take()
    task = asyncio.ensure_future(hang_up())
    await asyncio.wait_for(started.wait(), ctx.cfg.call_timeout)
    dispatched = False
    for _ in range(100):                                       # wait (<= 2 s) until the work has really started
        if any(e["kind"] == "BENCH_DISPATCH" and e.get("tool") == "rank_entities" for e in run.tail.take()):
            dispatched = True
            break
        await asyncio.sleep(0.02)
    await asyncio.sleep(ctx.cfg.cancel_after)
    t_cancel = time.perf_counter()
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError, Exception):
        await task
    r = await call(ctx, run, sess, "admission.after_cancel", "observed", "rank_entities", second, attribute=False)
    busy = r.sample["reason"] == "busy" and r.sample["detail"] == "slot"
    free_after = None
    if busy:
        got, _ = await await_slot_free(ctx, run, sess, pool, ctx.cfg.call_timeout)
        free_after = None if got is None else round(time.perf_counter() - t_cancel, 3)
    ctx.report["observations"]["cancellation"] = {
        "status": "observed", "work_dispatched_before_cancel": dispatched if run.log_ok else None,
        "cancel_after_dispatch_s": ctx.cfg.cancel_after,
        "second_call": f"{r.sample['status']}/{r.sample['reason']}", "slot_still_held": busy,
        "slot_free_after_cancel_s": free_after,
        "note": "slot_still_held=false means the abandoned work had already ended or was interrupted before the next call"}


async def scenario_timeout_probe(ctx: Ctx) -> None:
    """A tool the cursor interrupt cannot reach (fault-injected sleep in plain Python) outlives the caller's
    deadline: the caller gets query_timeout, the slot stays taken until the work ends, then calls work again."""
    cfg, wl = ctx.cfg, ctx.wl
    probe = cfg.timeout_probe_seconds
    grace = 2.0                                                # public_mcp.DEADLINE_GRACE
    sleep_s = probe + grace + 2.5
    est = next((d["rows"] for d in ctx.report["data"]["datasets"] if d["dataset"] == wl.dataset), None)
    cap = ctx.cap()
    overrides = {"TEMPO_MCP_MAX_SECONDS": str(probe)}
    if est and cap and est > cap:                              # admit the source so the gate reaches the deadline path
        overrides["TEMPO_MCP_MAX_SCAN_ROWS"] = str(est + 1)
    pool = VariantPool(wl)
    async with running_child(ctx, "timeout_probe", "timeout_probe", fault={"rank_entities": f"{sleep_s}:1"},
                             overrides=overrides) as run:
        async with open_session(ctx, run) as sess:
            d = await call(ctx, run, sess, "timeout_probe.setup_describe", "observed", "describe_dataset",
                           {"dataset": wl.dataset}, record=False)
            resolve_workload(ctx, d.env)
            t0 = time.perf_counter()
            first = await call(ctx, run, sess, "timeout_probe.first_call", "observed", "rank_entities",
                               pool.take(wl.rank_args(year=wl.year)))
            during = await call(ctx, run, sess, "timeout_probe.call_during_work", "observed", "rank_entities",
                                pool.fresh(1, counties=False)[0][1])
            got, after_r = await await_slot_free(ctx, run, sess, pool, sleep_s + 10)
            free_after = None if got is None else round(time.perf_counter() - t0, 3)
            after = after_r or during
            if after_r is not None:
                ctx.recorder.add(**{**after_r.sample, "case": "timeout_probe.first_call_after"})
    f, dsample = first.sample, during.sample
    deadline_ok = f["reason"] == "query_timeout" and probe <= f["wall_s"] <= probe + grace + 2.0
    held = dsample["reason"] == "busy" and free_after is not None and free_after >= sleep_s - 0.5
    ctx.checks["deadline_and_slot"] = {
        "status": "pass" if (deadline_ok and held and after.sample["outcome"] in ("served", "refused")
                             and after.sample["reason"] != "busy") else "fail",
        "fault_injection": {"tool": "rank_entities", "sleep_s": sleep_s, "first_n_dispatches": 1,
                            "max_seconds": probe},
        "first_call": f"{f['status']}/{f['reason']} after {f['wall_s']}s", "call_during_work": f"{dsample['status']}/{dsample['reason']}",
        "slot_free_after_s": free_after, "first_call_after": f"{after.sample['status']}/{after.sample['reason']}",
        "note": "the work is a fault-injected sleep standing in for uninterruptible slow work; scan cap raised in this child only"
                if "TEMPO_MCP_MAX_SCAN_ROWS" in overrides else
                "the work is a fault-injected sleep standing in for uninterruptible slow work"}


def default_rest_requests(wl: Workload) -> list[dict]:
    from urllib.parse import quote
    reqs = [{"kind": "health", "path": "/api/health"},
            {"kind": "search", "path": "/api/datasets?q=" + quote(wl.discover_query) + "&limit=20"},
            {"kind": "detail", "path": f"/api/datasets/{wl.dataset}"}]
    if wl.counties:
        f = quote(json.dumps({wl.county_column: [wl.counties[0]]}, ensure_ascii=False))
        reqs.append({"kind": "county_query", "path": f"/api/datasets/{wl.dataset}/data?filters={f}"
                     + "&group_by=" + quote(json.dumps(["TIME_PERIOD"]))})
    if wl.export_dataset:
        reqs.append({"kind": "export", "path": f"/api/datasets/{wl.export_dataset}/download?format=csv"})
    return reqs


async def scenario_mixed(ctx: Ctx) -> None:
    import random
    import httpx
    cfg, wl = ctx.cfg, ctx.wl
    pool = VariantPool(wl)
    async with running_child(ctx, "mixed", "mixed") as run:
        async with open_session(ctx, run) as sess0:
            d = await call(ctx, run, sess0, "mixed.setup_describe", "observed", "describe_dataset",
                           {"dataset": wl.dataset}, record=False)
            resolve_workload(ctx, d.env)
        rest = cfg.rest_requests or default_rest_requests(wl)
        if not wl.export_dataset and not cfg.rest_requests:
            ctx.report["observations"]["mixed_export"] = "not_run: no --export-dataset given"
        lock = asyncio.Lock()
        phase_results = []
        for name, n_mcp, n_rest, seconds in cfg.mixed_phases:
            ctx.budget.check(f"mixed phase {name}")
            end = time.monotonic() + seconds
            fivexx, fourxx = [], []

            async def mcp_client(idx):
                rng = random.Random(1000 + idx)
                async with open_session(ctx, run) as sess:
                    while time.monotonic() < end:
                        kind = rng.choices(["rank_cached", "rank_miss", "describe", "discover"], [3, 2, 1, 1])[0]
                        if kind == "rank_cached":
                            tool, args = "rank_entities", wl.rank_args(year=wl.year)
                        elif kind == "rank_miss":
                            async with lock:
                                fresh = pool.fresh(1, counties=bool(wl.counties) and rng.random() < 0.5)
                            tool, args = "rank_entities", (fresh[0][1] if fresh else wl.rank_args(year=wl.year))
                        elif kind == "describe":
                            tool, args = "describe_dataset", {"dataset": wl.dataset}
                        else:
                            tool, args = "discover_indicators", {"query": wl.discover_query}
                        r = await call(ctx, run, sess, f"mixed.{name}.mcp_{kind}", "mixed", tool, args, attribute=False)
                        if r.sample["reason"] == "busy":
                            await asyncio.sleep(0.05)

            async def rest_client(idx):
                rng = random.Random(2000 + idx)
                async with httpx.AsyncClient(base_url=run.child.base_url, timeout=cfg.call_timeout) as c:
                    while time.monotonic() < end:
                        item = rng.choice(rest)
                        t0 = time.perf_counter()
                        try:
                            resp = await c.get(item["path"])
                            code, nbytes = resp.status_code, len(resp.content)
                            outcome = "served" if code == 200 else ("refused" if code in (413, 429, 503) else "http_error")
                            err = None
                        except Exception as e:  # noqa: BLE001
                            code, nbytes, outcome, err = None, None, "transport_error", f"{type(e).__name__}: {e}"
                        if code is not None and code >= 500 and code != 503:
                            fivexx.append(f"{code} {item['path'][:80]}")
                        elif code is not None and 400 <= code < 500 and code not in (413, 429):
                            fourxx.append(f"{code} {item['path'][:80]}")
                        ctx.recorder.add(f"mixed.{name}.rest_{item['kind']}", "mixed", wall_s=time.perf_counter() - t0,
                                         outcome=outcome, status=None, reason=None if code in (None, 200) else str(code),
                                         result_bytes=nbytes, run=run.name, error=err)
                        if outcome != "served":
                            await asyncio.sleep(0.05)
            with run.monitor.window(f"mixed.{name}") as w:
                await asyncio.gather(*[mcp_client(i) for i in range(n_mcp)], *[rest_client(i) for i in range(n_rest)])
            run.record.setdefault("windows", []).append(w)
            # work that outlived the phase: the slot must come free by itself
            async with open_session(ctx, run) as s:
                linger, _ = await await_slot_free(ctx, run, s, pool, 30.0)
            linger = None if linger is None else round(linger, 3)
            phase_results.append({"phase": name, "mcp_clients": n_mcp, "rest_clients": n_rest, "seconds": seconds,
                                  "unexpected_5xx": len(fivexx), "unexpected_4xx": len(fourxx), "examples": (fivexx + fourxx)[:5], "slot_free_after_phase_s": linger,
                                  "window": w})
            if fivexx or fourxx:
                ctx.problems.append(f"mixed.{name}: {len(fivexx)} unexpected REST 5xx, {len(fourxx)} unexpected 4xx")
    ctx.report["observations"]["mixed_phases"] = phase_results
    ctx.checks["mixed_load"] = {
        "status": "fail" if any(p["unexpected_5xx"] or p["unexpected_4xx"] or p["slot_free_after_phase_s"] is None
                                for p in phase_results)
        else "pass", "phases": [p["phase"] for p in phase_results]}


SCENARIO_FUNCS = {"cold_chain": scenario_cold_chain, "cold_first_rank": scenario_cold_first_rank,
                  "warm": scenario_warm, "admission": scenario_admission,
                  "timeout_probe": scenario_timeout_probe, "mixed": scenario_mixed}


# ====================================================================== report

def write_report(cfg: Cfg, report: dict, recorder: Recorder) -> Path:
    report["cases"] = recorder.summary()
    report["totals"] = totals(report)
    out = cfg.out_dir / "report.json"
    tmp = out.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(report, indent=1, default=str) + "\n")
    os.replace(tmp, out)
    (cfg.out_dir / "samples.jsonl").write_text("\n".join(json.dumps(s, default=str) for s in recorder.samples) + "\n")
    return out


def totals(report: dict) -> dict:
    """Counts across runs; latency is never aggregated here."""
    runs = report["runs"]
    ev = [r.get("events") for r in runs if r.get("events")]
    stats = [r.get("stats") for r in runs if r.get("stats")]
    return {"children": len(runs),
            "provider_calls": sum(e["provider_calls"] for e in ev) if ev else None,
            "gate_calls": sum(e["gate_calls"] for e in ev) if ev else None,
            "cache_hits": sum(e["cache_hits"] for e in ev) if ev else None,
            "refusal_results": dict(sum((Counter({k: v for k, v in e["results"].items() if k.startswith("unavailable/")})
                                        for e in ev), Counter())) if ev else None,
            "oom_suspected": sum(1 for s in stats if s.get("oom_suspected")) if stats else None,
            "restarts": (sum(s["restarts"] for s in stats if s.get("restarts") is not None)
                         if any(s.get("restarts") is not None for s in stats) else None)}


def new_report(cfg: Cfg) -> dict:
    sources = [cfg.workload.dataset] + (["GOS102A"] if cfg.workload.entity_class == "cities" else []) \
        + ([cfg.workload.over_limit_dataset] if cfg.workload.over_limit_dataset else [])
    fp = data_fingerprint(cfg.data_dir, sources)
    env = environment_info()
    mem = parse_memory_flag(cfg.container_memory) if cfg.mode == "container" else None
    env["container"] = {"mode": cfg.mode, "image": cfg.image, "memory_limit_bytes": mem,
                        "cpus": cfg.container_cpus if cfg.mode == "container" else None,
                        "data": cfg.container_data if cfg.mode == "container" else None, "daemon": None}
    est = next((d["rows"] for d in fp["datasets"] if d["dataset"] == cfg.workload.dataset), None)
    return {
        "schema": SCHEMA, "label": cfg.label, "started_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "finished_at": None, "duration_s": None, "status": "running", "blocked_reason": None,
        "mode": cfg.mode, "scale": scale_report(cfg), "code": code_identity(), "data": fp, "environment": env,
        "profile": {"name": cfg.profile_name, "settings_declared": cfg.declared,
                    "harness_overrides": cfg.overrides, "defaults_for_the_rest": True,
                    "provider_keys_in_child_env": [], "ask_enabled": False,
                    "note": "larger limits apply to the benchmark child only; app defaults are unchanged"},
        "workload": dataclasses.asdict(cfg.workload),
        "scan_estimate": {"dataset": cfg.workload.dataset, "footer_rows": est,
                          "rule": "whole-file Parquet footer rows per source (public_mcp.ScanEstimator)"},
        "gates": {"linux_512mib": {"status": "not_run", "reason": "no container run completed"}},
        "scenarios": {s: {"status": "not_run", "reason": "not started"} for s in SCENARIOS},
        "runs": [], "cases": [], "checks": {}, "observations": {}, "totals": {}, "problems": [], "errors": [],
        "samples_file": "samples.jsonl",
        "caveats": [
            "rss_peak_bytes is the sampled (0.1 s) sum of resident sizes over the child's process tree: shared pages "
            "are counted per process and it is not cgroup memory; rss_peak_kernel_bytes is the child's exact "
            "lifetime peak RSS (wait4 ru_maxrss, normalised to bytes)",
            "cpu_s is the child's CPU over a window (or its lifetime in stats.cpu_s_total), not per call",
            "a local run is not constrained to 512 MiB; only a container run on a Linux kernel can fill gates.linux_512mib",
            "the per-minute request limits are lifted in the child unless --keep-rate-limits (see profile.harness_overrides)",
            "latency percentiles use served answers only and nearest-rank; refusals and failures are counted beside them",
            "a larger scan cap or deadline applies to the benchmark child only; application defaults are unchanged",
        ],
    }


def linux_gate(r: dict, cfg: Cfg) -> dict:
    """`gates.linux_512mib`: measured only from container runs on a daemon with a Linux kernel and a cgroup peak."""
    run_containers = [x for x in r["runs"] if x.get("target", {}).get("kind") == "container"]
    peaks = [x["stats"].get("container_memory_peak_bytes") for x in run_containers if x.get("stats")]
    oom = any(x["stats"].get("oom_killed") or x["stats"].get("oom_suspected") for x in run_containers
              if x.get("stats"))
    daemon = r["environment"].get("container", {}).get("daemon") or {}
    # A killed container has no readable peak, but an OOM kill under the limit is itself the measurement.
    if run_containers and daemon.get("os_type") == "linux" and (oom or any(p is not None for p in peaks)):
        return {
            "status": "measured", "memory_limit_bytes": parse_memory_flag(cfg.container_memory),
            "container_memory_peak_bytes": max((p for p in peaks if p is not None), default=None),
            "oom_killed": oom,
            "evaluated": False, "note": "pass/fail against the 75% headroom threshold is AQ-01B's decision"}
    if run_containers:
        return {"status": "not_run",
                "reason": "the Docker daemon is not a Linux kernel or exposed no cgroup peak"}
    return {"status": "not_run",
            "reason": "local mode: an unconstrained run is not a 512 MiB result" if cfg.mode == "local"
                      else "no container ran"}


def finalize_report(ctx: Ctx) -> int:
    r, cfg = ctx.report, ctx.cfg
    t = totals(r)
    cap = ctx.cap()
    r["scan_estimate"]["scan_cap"] = cap
    est = r["scan_estimate"]["footer_rows"]
    r["scan_estimate"]["would_admit"] = None if est is None or cap is None else est <= cap
    ctx.checks["provider_calls"] = (
        {"status": "not_run", "reason": "no child log was read"} if t["provider_calls"] is None else
        {"status": "pass" if t["provider_calls"] == 0 else "fail", "count": t["provider_calls"],
         "method": "provider client entry points replaced in the child (calls logged and refused), keys unset"})
    ctx.checks.setdefault("unexpected_5xx_or_child_loss", {
        "status": "fail" if ctx.problems else "pass", "problems": ctx.problems[:20]})
    r["gates"]["linux_512mib"] = linux_gate(r, cfg)
    failed = [s for s, v in r["scenarios"].items() if v["status"] == "failed"]
    bad = [k for k, v in r["checks"].items() if v.get("status") == "fail"]
    r["finished_at"] = dt.datetime.now(dt.timezone.utc).isoformat()
    r["duration_s"] = round(time.time() - ctx.t_start, 2) if hasattr(ctx, "t_start") else None
    r["status"] = "completed_with_failures" if (failed or bad) else "completed"
    r["failed_scenarios"], r["failed_checks"] = failed, bad
    r["problems"] = ctx.problems[:50]
    ctx.flush()
    return 1 if (failed or bad) else 0


async def run_all(ctx: Ctx) -> None:
    for sid in SCENARIOS:
        entry = ctx.report["scenarios"][sid]
        if sid not in ctx.cfg.scenarios:
            entry.update(status="not_run", reason="not selected")
            continue
        if not ctx.report["data"]["available"]:
            entry.update(status="not_run", reason="corpus unavailable")
            continue
        t0 = time.monotonic()
        try:
            ctx.budget.check(sid)
            await asyncio.wait_for(SCENARIO_FUNCS[sid](ctx), timeout=max(1.0, ctx.budget.remaining()))
            entry.clear()
            entry.update(status="completed")
        except asyncio.TimeoutError:
            entry.clear()
            entry.update(status="failed", error="harness time budget exhausted")
            ctx.report["errors"].append(f"{sid}: harness time budget exhausted")
        except Exception as e:  # noqa: BLE001 — one failed scenario must not lose the others or the report
            entry.clear()
            entry.update(status="failed", error=f"{type(e).__name__}: {str(e)[:300]}")
            ctx.report["errors"].append(f"{sid}: {type(e).__name__}: {str(e)[:300]}")
        entry["seconds"] = round(time.monotonic() - t0, 2)
        ctx.flush()


def load_rest_requests(path: str | None) -> list | None:
    if not path:
        return None
    try:
        items = json.loads(Path(path).read_text())
    except (OSError, ValueError) as e:
        raise HarnessError(f"--rest-requests unreadable: {e}") from None
    if (not isinstance(items, list) or not items or not all(
            isinstance(i, dict) and isinstance(i.get("kind"), str) and str(i.get("path", "")).startswith("/")
            for i in items)):
        raise HarnessError('--rest-requests must be a non-empty JSON list of {"kind": ..., "path": "/..."}')
    return items


def make_cfg(args) -> Cfg:
    data_dir = Path(args.data_dir).expanduser().resolve()
    out_dir = Path(args.out_dir).expanduser().resolve()
    if out_dir == ROOT or ROOT in out_dir.parents:
        raise HarnessError("--out-dir must be outside the repository (reports and logs are not source)")
    declared, overrides = profile_env({k: getattr(args, k) for k in PROFILE_FLAGS}, args.setting or [],
                                      args.keep_rate_limits)
    wl = Workload(dataset=args.dataset, entity_columns=[c for c in args.entity_columns.split(",") if c],
                  entity_class=args.entity_class, county_column=args.county_column,
                  discover_query=args.discover_query, top_k=args.top_k, year=args.year,
                  years=[y for y in (args.years or "").split(",") if y] or None,
                  counties=[c for c in (args.counties or "").split(",") if c] or None,
                  over_limit_dataset=args.over_limit_dataset, export_dataset=args.export_dataset)
    scenarios = tuple(s for s in (args.scenarios.split(",") if args.scenarios else SCENARIOS))
    unknown = [s for s in scenarios if s not in SCENARIOS]
    if unknown:
        raise HarnessError(f"unknown scenario(s) {unknown}; choose from {list(SCENARIOS)}")
    if args.mode == "container" and not args.image:
        raise HarnessError("--mode container needs --image (the harness does not build images)")
    phases = tuple(parse_phase(p) for p in args.mixed_phase) if args.mixed_phase else Cfg.mixed_phases
    for n, v in (("--cold-repeats", args.cold_repeats), ("--warm-samples", args.warm_samples),
                 ("--concurrency", args.concurrency)):
        if v < 1:
            raise HarnessError(f"{n} must be at least 1")
    return Cfg(data_dir=data_dir, out_dir=out_dir, mode=args.mode, image=args.image,
               container_memory=args.container_memory, container_cpus=args.container_cpus,
               container_data=args.container_data, cold_repeats=args.cold_repeats, warm_samples=args.warm_samples,
               concurrency=args.concurrency, declared=declared, overrides=overrides, workload=wl,
               scenarios=scenarios, mixed_phases=phases,
               rest_requests=load_rest_requests(args.rest_requests),
               ports=parse_ports(args.ports), call_timeout=args.call_timeout, startup_timeout=args.startup_timeout,
               max_total_seconds=args.max_total_seconds, cancel_after=args.cancel_after,
               timeout_probe_seconds=args.timeout_probe_seconds, label=args.label or "")


def summary_lines(report: dict) -> list[str]:
    """A short human summary of a finished run (the report holds everything)."""
    lines = [f"profile: {report.get('profile', {}).get('name')}  scale: {report.get('scale', {}).get('label')}  "
             f"scan estimate: {report.get('scan_estimate', {}).get('footer_rows')} rows vs cap "
             f"{report.get('scan_estimate', {}).get('scan_cap')}"]
    for c in report.get("cases", []):
        if c["state"] == "mixed" or ("." in c["case"] and c["case"].split(".")[1] in ("startup", "initialize", "list_tools")):
            continue
        lat = c["latency_s"]
        lines.append(f"  {c['case'][:34]:34} {c['state']:9} n={c['n']:<3} "
                     + (f"p50={lat['p50']:.3f}s p95={lat['p95']:.3f}s " if lat else "no served answer ")
                     + ",".join(f"{k}={v}" for k, v in c["outcomes"].items()))
    bad = [k for k, v in report.get("checks", {}).items() if v.get("status") == "fail"]
    lines.append(f"checks failed: {bad or 'none'}  linux_512mib: {report.get('gates', {}).get('linux_512mib', {}).get('status')}")
    return lines


def run_command(args) -> int:
    out_dir = Path(args.out_dir).expanduser().resolve()
    t_start = time.time()
    try:
        cfg = make_cfg(args)
    except HarnessError as e:
        if out_dir == ROOT or ROOT in out_dir.parents:
            print(f"blocked: {e}", file=sys.stderr)
            return 2
        out_dir.mkdir(parents=True, exist_ok=True)
        blocked = {"schema": SCHEMA, "status": "blocked", "blocked_reason": str(e), "cases": [],
                   "gates": {"linux_512mib": {"status": "not_run", "reason": "harness did not start"}},
                   "started_at": dt.datetime.now(dt.timezone.utc).isoformat()}
        (out_dir / "report.json").write_text(json.dumps(blocked, indent=1) + "\n")
        print(f"blocked: {e}", file=sys.stderr)
        return 2
    out_dir.mkdir(parents=True, exist_ok=True)
    CHILDREN.install()
    report = new_report(cfg)
    ctx = Ctx(cfg, report)
    ctx.t_start = t_start
    exit_code = 1
    try:
        if cfg.mode == "container":
            ok, why = ContainerChild.available()
            if ok:
                report["environment"]["container"]["daemon"] = ContainerChild.daemon(cfg.image)
            if not ok:
                report["blocked_reason"] = f"container mode unavailable: {why}"
                for s in SCENARIOS:
                    report["scenarios"][s] = {"status": "not_run", "reason": report["blocked_reason"]}
                report["gates"]["linux_512mib"] = {"status": "not_run", "reason": report["blocked_reason"]}
                report["status"] = "blocked"
                exit_code = 2
        if report["status"] != "blocked" and not report["data"]["available"]:
            report["blocked_reason"] = f"no corpus at {cfg.data_dir}/corpus/metadata.duckdb"
            for sid in SCENARIOS:
                report["scenarios"][sid] = {"status": "not_run", "reason": report["blocked_reason"]}
            report["gates"]["linux_512mib"] = {"status": "not_run", "reason": report["blocked_reason"]}
            report["status"] = "blocked"
            exit_code = 2
        if report["status"] != "blocked":
            asyncio.run(run_all(ctx))
            exit_code = finalize_report(ctx)
    except BaseException as e:                                  # noqa: BLE001 — always leave a report behind
        report["errors"].append(f"{type(e).__name__}: {str(e)[:300]}")
        report["status"] = "failed"
        exit_code = 1
        if isinstance(e, (KeyboardInterrupt, SystemExit)):
            raise
    finally:
        CHILDREN.kill_all()
        report["finished_at"] = dt.datetime.now(dt.timezone.utc).isoformat()
        report["duration_s"] = round(time.time() - t_start, 2)
        path = write_report(cfg, report, ctx.recorder)
    print("\n".join(summary_lines(report)))
    print(f"report: {path}  status: {report['status']}  exit: {exit_code}")
    return exit_code


# ====================================================================== command line

def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run", help="launch an isolated candidate and measure it")
    r.add_argument("--data-dir", required=True, help="data directory (contains corpus/); opened read-only by the child")
    r.add_argument("--out-dir", required=True, help="where report.json, samples.jsonl and logs/ are written")
    r.add_argument("--mode", choices=("local", "container"), default="local")
    r.add_argument("--image", help="container mode: an existing image (the harness never builds one)")
    r.add_argument("--container-memory", default="512m")
    r.add_argument("--container-cpus", default="1")
    r.add_argument("--container-data", choices=("mount", "image"), default="mount",
                   help="mount --data-dir read-only, or use the data baked into the image")
    r.add_argument("--cold-repeats", type=int, default=REQUIRED_N["cold"], help="fresh-process repetitions per cold case")
    r.add_argument("--warm-samples", type=int, default=REQUIRED_N["cache"], help="samples per warm case")
    r.add_argument("--concurrency", type=int, default=5, help="simultaneous MCP calls in the admission scenario")
    for flag, var in PROFILE_FLAGS.items():
        r.add_argument("--" + flag.replace("_", "-"), default=None, help=f"candidate {var} (child only)")
    r.add_argument("--setting", action="append", metavar="TEMPO_NAME=VALUE", help="any other TEMPO_* setting (child only)")
    r.add_argument("--keep-rate-limits", action="store_true", help="do not lift the per-minute request limits")
    r.add_argument("--dataset", default=Workload.dataset)
    r.add_argument("--entity-columns", default="REF_AREA,REF_AREA_2")
    r.add_argument("--entity-class", default="cities", choices=("all", "cities"))
    r.add_argument("--county-column", default="REF_AREA")
    r.add_argument("--discover-query", default=Workload.discover_query)
    r.add_argument("--top-k", type=int, default=30)
    r.add_argument("--year", help="exact year (default: the dataset's latest)")
    r.add_argument("--years", help="comma list of years for the miss cases (default: latest 12)")
    r.add_argument("--counties", help="comma list for the county-filtered cases (default: examples from describe)")
    r.add_argument("--over-limit-dataset", help="a second source expected to exceed the scan cap")
    r.add_argument("--export-dataset", help="dataset whose CSV export joins the mixed REST load")
    r.add_argument("--rest-requests", help="JSON list of {kind, path} for the mixed REST load")
    r.add_argument("--scenarios", help=f"comma list of {','.join(SCENARIOS)} (default all)")
    r.add_argument("--mixed-phase", action="append", metavar="NAME:MCP:REST:SECONDS",
                   help="repeatable; AT-04 length: single_client:1:2:180 five_clients:5:2:300")
    r.add_argument("--ports", help="local port range for children, e.g. 8111-8115 (default: ephemeral)")
    r.add_argument("--call-timeout", type=float, default=30.0)
    r.add_argument("--startup-timeout", type=float, default=90.0)
    r.add_argument("--max-total-seconds", type=float, default=3600.0, help="the harness's own wall-clock budget")
    r.add_argument("--cancel-after", type=float, default=0.01, help="seconds after the work starts before the caller hangs up")
    r.add_argument("--timeout-probe-seconds", type=float, default=1.0)
    r.add_argument("--label", help="free text recorded in the report")
    s = sub.add_parser("serve", help="(internal) the app under uvicorn with the benchmark guards")
    s.add_argument("--host", default="127.0.0.1")
    s.add_argument("--port", type=int, required=True)
    s.add_argument("--app-root", default=os.getcwd())
    s.add_argument("--fault-delay", action="append", metavar="TOOL=SECONDS[:COUNT]",
                   help="harness self-test only: hold the first COUNT (default 1) dispatches of TOOL")
    i = sub.add_parser("inproc", help="(internal) call the shared tools directly and write their envelopes")
    i.add_argument("--app-root", default=os.getcwd())
    i.add_argument("--requests", required=True)
    i.add_argument("--out", required=True)
    return ap


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    return {"run": run_command, "serve": serve, "inproc": inproc}[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
