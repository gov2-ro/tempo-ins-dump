"""Public, read-only MCP endpoint over the shared analytical tools (AT-03).

A data server: the chat client's model chooses tools and writes the answer; nothing here calls a
model, asks the client for one (no sampling/elicitation), runs SQL or code, reads files or logs,
or dispatches to the app's other endpoints. `tools/list` is exactly the eight shared tools and
every call goes through `registry.call_tool`, the same service Ask and REST use, so values,
refusals, scope and generation evidence are identical across transports.

Transport: the MCP Python SDK's Streamable HTTP (stateless, JSON responses) at **`/mcp`**, mounted
by `install(app)` before the static catch-all and run inside the parent application's lifespan.
Disabled (the default) the path answers 404 for every method and trailing-path variant.

Bounds, per worker (one worker in the first release; this is not a deployment-wide quota):
  * body size, Host and Origin are checked before any parsing or tool work (CORS is not
    authentication, and the app's development CORS never applies to /mcp);
  * requests per minute (cheap, covers initialize/list) and tools/call per minute;
  * one analytical operation at a time by default, and the slot stays taken until the work has
    really stopped. A call that finds it taken waits in a short first-come queue (a few calls, up
    to `queue_seconds`; chat clients send calls in parallel) and its result says it waited; past
    that it is answered `busy` with a retry delay. TEMPO_MCP_QUEUE_SECONDS=0 answers busy at once;
  * a wall-clock deadline enforced by interrupting the cursor the operation owns;
  * an admission limit on the rows an operation may read, estimated from Parquet footers (never a
    preliminary COUNT): an unknown estimate is refused unless a generation-bound result is cached;
  * a bounded result cache (bytes, entries, TTL) keyed by generation, selection and language.

Configuration is read when the application is built (`McpSettings.from_env`), never at import, so
a fresh application sees its own flags. Invalid values fail startup clearly; zero is never
"unlimited".
"""
from __future__ import annotations

import asyncio
import contextlib
import contextvars
import hashlib
import json
import logging
import math
import os
import threading
import time
import uuid
from collections import Counter, OrderedDict, deque
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from urllib.parse import urlsplit

from starlette.responses import JSONResponse, PlainTextResponse, Response
from starlette.routing import Route

from app import config
from app.services import ask_guard, generation, recipes
from app.services.tools import contract as C
from app.services.tools import messages as M
from app.services.tools import registry

log = logging.getLogger("app.mcp")

SERVER_NAME = "ins-plus-statistics"
SERVER_VERSION = "2.0.0"
POLICY_VERSION = "mcp-2"                   # part of every cache key: bump when result policy changes
MAX_WIRE_BYTES = 72 * 1024                 # the complete JSON-RPC response (both representations)
WIRE_ALLOWANCE = 512                       # JSON-RPC wrapper around the result
DEADLINE_GRACE = 2.0                       # seconds the caller waits past the interrupt before answering
QUEUE_POLL_SECONDS = 0.05                  # how often a queued call looks for a free slot
QUEUE_NOTICE_SECONDS = 0.5                 # a wait this long is reported on the result
SCAN_TOOLS = ("rank_entities", "query_data", "compare_periods", "find_dimension_values", "run_recipe")
TRANSIENT_REASONS = frozenset({"busy", "query_timeout", "query_budget", "response_budget",
                               "generation_changed", "generation_unverified", "execution_failed"})

INSTRUCTIONS = (
    "Official Romanian statistics (INS TEMPO) as read-only tools. Start with discover_indicators using the full question (keep denominator, geography, period and ranking), "
    "then describe_dataset and find_dimension_values for exact columns and values, then query_data, "
    "compare_periods (changes between exact years), rank_entities (one-year value rankings) or run_recipe. Every result states "
    "its source, definition, unit, period, scope and data generation. A refusal means no safe value "
    "exists for that request: follow its recovery suggestion; do not total or rank raw rows yourself. "
    "Messages and warnings follow each call's `lang` (ro default, or en): pass the user's language. "
    "The server never calls a model.")
# Appended when TEMPO_MCP_LOG_CALLS is on, so a client (and its user) is told before any call.
LOGGING_NOTICE = (" This is a development server: every accepted tool call (arguments and result) is recorded "
                  "and may be published to improve the answers. The record holds no IP address or client "
                  "identity, but the hosting platform's access logs may keep connection metadata for a limited "
                  "time. Do not send personal or confidential information.")
CALL_LOG = "mcp-calls.jsonl"               # in TEMPO_ASK_LOG_DIR, next to Ask's ask-chats.jsonl
CLIENT_TABLE_KEYS = 1024                   # per-client windows kept (least recently seen are dropped)
# A refused call whose arguments are not trusted to be small or valid: the content log keeps only
# the tool, the reason, the argument size and a SHA-256, never the argument text.
NO_ARGUMENT_LOG_REASONS = frozenset({"invalid_input", "unknown_tool", "busy"})
# Set by McpEndpoint for the request being handled; the SDK's server task inherits the context.
_CLIENT: contextvars.ContextVar = contextvars.ContextVar("mcp_client", default="-")
_DISCONNECT: contextvars.ContextVar = contextvars.ContextVar("mcp_disconnect", default=None)

# ---------------------------------------------------------------- settings

class McpConfigError(RuntimeError):
    """An impossible or unsafe MCP setting; raised when the application is built."""


def _flag(env, name: str) -> bool:
    raw = (env.get(name) or "").strip().lower()
    if raw in ("", "0", "false", "no"):
        return False
    if raw in ("1", "true", "yes"):
        return True
    raise McpConfigError(f"{name} must be true or false, not {raw!r}")


def _number(env, name: str, default, *, cast=int, minimum=None):
    """A positive number (zero is never 'unlimited'); `minimum=0` also accepts zero where it means
    'none' (no queue)."""
    raw = env.get(name)
    if raw is None or str(raw).strip() == "":
        return default
    try:
        v = cast(str(raw).strip())
    except ValueError:
        raise McpConfigError(f"{name} must be a number, not {raw!r}") from None
    ok = v >= 0 if minimum == 0 else v > 0
    if not (ok and math.isfinite(v)):
        raise McpConfigError(f"{name} must be positive (zero is not 'unlimited'), not {raw!r}")
    return v


def _csv(env, name: str) -> list[str]:
    return [x.strip() for x in (env.get(name) or "").split(",") if x.strip()]


@dataclass(frozen=True)
class McpSettings:
    enabled: bool = False
    local_test: bool = False
    base_url: str = ""
    max_body_bytes: int = 65_536
    max_concurrent: int = 1
    queue_seconds: float = 15.0
    max_waiting: int = 4
    max_seconds: float = 10.0
    max_calls_per_minute: int = 120
    max_requests_per_minute: int = 600
    max_scan_rows: int = 1_000_000
    cache_bytes: int = 4 * 1024 * 1024
    cache_entries: int = 128
    cache_ttl: float = 300.0
    allowed_hosts: tuple = ()
    allowed_origins: tuple = ()
    log_calls: bool = False
    log_max_bytes: int = 256 * 1024 * 1024
    client_requests_per_minute: int = 240
    client_calls_per_minute: int = 60
    trust_forwarded: bool = False
    on_fly: bool = False            # FLY_APP_NAME is set: Fly's proxy writes Fly-Client-IP

    @classmethod
    def from_env(cls, environ=None, *, base_url: str | None = None) -> "McpSettings":
        """Settings from the environment (default: os.environ); `base_url` defaults to the trusted
        TEMPO_PUBLIC_BASE_URL the tools build links from. Only an enabled endpoint is validated."""
        env = os.environ if environ is None else environ
        if not _flag(env, "TEMPO_MCP_ENABLED"):
            return cls()
        local = _flag(env, "TEMPO_MCP_LOCAL_TEST")
        base = (config.PUBLIC_BASE_URL if base_url is None else base_url).strip().rstrip("/")
        host, origin = _check_base_url(base, local)
        hosts = [host] + (["localhost:*", "127.0.0.1:*", "[::1]:*"] if local else []) \
            + _csv(env, "TEMPO_MCP_ALLOWED_HOSTS")
        origins = [origin] + _csv(env, "TEMPO_MCP_ALLOWED_ORIGINS")
        for what, items in (("TEMPO_MCP_ALLOWED_HOSTS", hosts), ("TEMPO_MCP_ALLOWED_ORIGINS", origins)):
            if any(i in ("*", "*:*") or "://*" in i for i in items):
                raise McpConfigError(f"{what} must list explicit values, not a wildcard")
        return cls(
            enabled=True, local_test=local, base_url=base,
            max_body_bytes=_number(env, "TEMPO_MCP_MAX_BODY_BYTES", 65_536),
            max_concurrent=_number(env, "TEMPO_MCP_MAX_CONCURRENT", 1),
            queue_seconds=_number(env, "TEMPO_MCP_QUEUE_SECONDS", 15.0, cast=float, minimum=0),
            max_waiting=_number(env, "TEMPO_MCP_MAX_WAITING", 4),
            max_seconds=_number(env, "TEMPO_MCP_MAX_SECONDS", 10.0, cast=float),
            max_calls_per_minute=_number(env, "TEMPO_MCP_MAX_CALLS_PER_MINUTE", 120),
            max_requests_per_minute=_number(env, "TEMPO_MCP_MAX_REQUESTS_PER_MINUTE", 600),
            max_scan_rows=_number(env, "TEMPO_MCP_MAX_SCAN_ROWS", 1_000_000),
            cache_bytes=_number(env, "TEMPO_MCP_CACHE_BYTES", 4 * 1024 * 1024),
            cache_entries=_number(env, "TEMPO_MCP_CACHE_ENTRIES", 128),
            cache_ttl=_number(env, "TEMPO_MCP_CACHE_TTL_SECONDS", 300.0, cast=float),
            allowed_hosts=tuple(dict.fromkeys(hosts)), allowed_origins=tuple(dict.fromkeys(origins)),
            log_calls=_flag(env, "TEMPO_MCP_LOG_CALLS"),
            log_max_bytes=_number(env, "TEMPO_MCP_LOG_MAX_BYTES", 256 * 1024 * 1024),
            client_requests_per_minute=_number(env, "TEMPO_MCP_CLIENT_REQUESTS_PER_MINUTE", 240),
            client_calls_per_minute=_number(env, "TEMPO_MCP_CLIENT_CALLS_PER_MINUTE", 60),
            trust_forwarded=_flag(env, "TEMPO_MCP_TRUST_FORWARDED"),
            on_fly=bool((env.get("FLY_APP_NAME") or "").strip()))


def _check_base_url(base: str, local_test: bool) -> tuple[str, str]:
    """(host[:port], origin) of the trusted public base URL; startup fails when it is missing or
    unsafe. Plain http is accepted only for localhost under TEMPO_MCP_LOCAL_TEST."""
    if not base:
        raise McpConfigError("TEMPO_PUBLIC_BASE_URL must be set (the trusted HTTPS origin of this "
                             "deployment) when TEMPO_MCP_ENABLED is true")
    u = urlsplit(base)
    if not u.netloc or u.username or u.password or u.path not in ("", "/") or u.query or u.fragment:
        raise McpConfigError("TEMPO_PUBLIC_BASE_URL must be a bare origin such as https://api.example.org")
    local_host = (u.hostname or "") in ("localhost", "127.0.0.1", "::1")
    if u.scheme == "https":
        pass
    elif u.scheme == "http" and local_test and local_host:
        pass
    else:
        raise McpConfigError("TEMPO_PUBLIC_BASE_URL must be https (http only for localhost with "
                             "TEMPO_MCP_LOCAL_TEST=true)")
    return u.netloc, f"{u.scheme}://{u.netloc}"


# ---------------------------------------------------------------- limiter, cache, estimator

class Window:
    """Sliding-window admission counter: at most `limit` events in `seconds`."""

    def __init__(self, limit: int, seconds: float = 60.0, clock=time.monotonic):
        self.limit, self.seconds, self.clock = limit, seconds, clock
        self._hits: deque = deque()
        self._lock = threading.Lock()

    def allow(self) -> tuple[bool, float]:
        """(admitted, seconds until a slot frees when refused)."""
        now = self.clock()
        with self._lock:
            while self._hits and now - self._hits[0] >= self.seconds:
                self._hits.popleft()
            if len(self._hits) >= self.limit:
                return False, max(0.1, self.seconds - (now - self._hits[0]))
            self._hits.append(now)
            return True, 0.0


class ClientWindows:
    """One sliding window per client key, in a table bounded to `max_keys` (least recently seen
    dropped on access). The overall ceiling stays with the global Window."""

    def __init__(self, limit: int, seconds: float = 60.0, max_keys: int = CLIENT_TABLE_KEYS,
                 clock=time.monotonic):
        self.limit, self.seconds, self.max_keys, self.clock = limit, seconds, max_keys, clock
        self._items: OrderedDict = OrderedDict()
        self._lock = threading.Lock()

    def __len__(self) -> int:
        return len(self._items)

    def allow(self, key: str) -> tuple[bool, float]:
        with self._lock:
            w = self._items.get(key)
            if w is None:
                w = self._items[key] = Window(self.limit, self.seconds, clock=self.clock)
                while len(self._items) > self.max_keys:
                    self._items.popitem(last=False)
            else:
                self._items.move_to_end(key)
        return w.allow()


class _Disconnect:
    """The client hanging up on one request: callbacks run (on the event loop) when it happens."""

    def __init__(self):
        self.gone = False
        self.event = asyncio.Event()
        self._callbacks: list = []

    def on_gone(self, fn) -> None:
        if self.gone:
            fn()
        else:
            self._callbacks.append(fn)

    def off(self, fn) -> None:
        with contextlib.suppress(ValueError):
            self._callbacks.remove(fn)

    def fire(self) -> None:
        self.gone = True
        self.event.set()
        for fn in list(self._callbacks):
            fn()


class ResultCache:
    """Serialized tool envelopes, bounded by entries, bytes and age. Nothing else is stored (no
    observations beyond the envelope, no credentials, no failures that depend on load)."""

    def __init__(self, max_bytes: int, max_entries: int, ttl: float, clock=time.monotonic):
        self.max_bytes, self.max_entries, self.ttl, self.clock = max_bytes, max_entries, ttl, clock
        self._items: OrderedDict = OrderedDict()      # key -> (stored_at, text)
        self._bytes = 0
        self._lock = threading.Lock()

    def __len__(self) -> int:
        return len(self._items)

    @property
    def bytes_used(self) -> int:
        return self._bytes

    def get(self, key) -> dict | None:
        with self._lock:
            item = self._items.get(key)
            if item is None:
                return None
            stored, text = item
            if self.clock() - stored >= self.ttl:
                self._drop(key)
                return None
            self._items.move_to_end(key)
        return json.loads(text)

    def put(self, key, env: dict) -> bool:
        text = C.dumps(env)
        n = len(text.encode("utf-8"))
        if n > self.max_bytes:
            return False
        with self._lock:
            if key in self._items:
                self._drop(key)
            self._items[key] = (self.clock(), text)
            self._bytes += n
            while self._items and (len(self._items) > self.max_entries or self._bytes > self.max_bytes):
                self._drop(next(iter(self._items)))
        return True

    def purge_generations_other_than(self, generation_id) -> None:
        with self._lock:
            for k in [k for k in self._items if k[2] != generation_id]:
                self._drop(k)

    def _drop(self, key) -> None:
        stored, text = self._items.pop(key)
        self._bytes -= len(text.encode("utf-8"))


class ScanEstimator:
    """Upper bound of the rows an operation may read, from Parquet footers (num_rows): the
    whole file of every source, summed over a multi-source recipe. Never a COUNT, never a scan.
    None means the footer could not be read: such an operation is refused (fail closed)."""

    def __init__(self):
        self._rows: dict = {}                     # path -> (mtime_ns, rows)
        self._lock = threading.Lock()

    def file_rows(self, code: str) -> int | None:
        from app.services import data_query as dq
        path = dq.PARQUET_DIR / f"{code}.parquet"
        try:
            mtime = path.stat().st_mtime_ns
        except OSError:
            return 0                              # no such file: the tool refuses it without any read
        with self._lock:
            cached = self._rows.get(str(path))
            if cached and cached[0] == mtime:
                return cached[1]
        try:
            import duckdb
            con = duckdb.connect(config={"memory_limit": "32MB", "threads": 1})
            try:
                rows = con.execute("SELECT num_rows FROM parquet_file_metadata(?)", [str(path)]).fetchone()[0]
            finally:
                con.close()
        except Exception:  # noqa: BLE001 — an unreadable footer is an unknown estimate
            return None
        with self._lock:
            self._rows[str(path)] = (mtime, int(rows))
        return int(rows)

    def sources(self, name: str, arguments: dict) -> list[str]:
        if name == "run_recipe":
            r = recipes.load_recipes().get(arguments.get("recipe"))
            return [s["dataset"] for s in recipes.source_specs(r)] if r else []
        return [arguments["dataset"]]

    def estimate(self, name: str, arguments: dict) -> int | None:
        total = 0
        for code in self.sources(name, arguments):
            n = self.file_rows(code)
            if n is None:
                return None
            total += n
        return total


# ---------------------------------------------------------------- envelopes the gate itself produces

def _lang(arguments) -> str:
    lang = arguments.get("lang") if isinstance(arguments, dict) else None
    return lang if lang in ("ro", "en") else "ro"


def _gate_envelope(name: str, arguments, status: str, reason: str, message: str, recovery=()) -> dict:
    ctx = C.ToolContext(conn=None, lang=_lang(arguments),
                        generation=generation.current(), request_id=uuid.uuid4().hex[:12])
    return C.failure_envelope(str(name)[:64], ctx, C.ToolFailure(status, reason, message,
                                                                 recovery=list(recovery)))


def _retry(seconds: float, arguments) -> dict:
    return C.recovery("retry", M.t(_lang(arguments), "gate.retry_in", s=max(1, round(seconds))))


# ---------------------------------------------------------------- the gate

class Gate:
    """Every tools/call passes here: precheck, cache, rate, scan estimate, slot, deadline."""

    def __init__(self, settings: McpSettings, clock=time.monotonic):
        self.s = settings
        self.clock = clock
        self.slots = threading.BoundedSemaphore(settings.max_concurrent)
        self.calls = Window(settings.max_calls_per_minute, clock=clock)
        self.client_calls = ClientWindows(settings.client_calls_per_minute, clock=clock)
        self.cache = ResultCache(settings.cache_bytes, settings.cache_entries, settings.cache_ttl, clock=clock)
        self.estimator = ScanEstimator()
        self.executor = ThreadPoolExecutor(max_workers=settings.max_concurrent,
                                           thread_name_prefix="mcp-tool")
        self.active = 0                           # operations holding a slot (tests, health of the gate)
        self._waiting: deque = deque()            # calls queued for a slot, first come first served
        self.stats: Counter = Counter()
        self._lock = threading.Lock()
        self._log_lock = threading.Lock()
        self.log_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="mcp-log")

    def close(self) -> None:
        self.executor.shutdown(wait=False, cancel_futures=True)
        self.log_executor.shutdown(wait=False)

    def _key(self, name: str, arguments: dict, gen: dict):
        """Keyed on the validated arguments with defaults (sorted keys), so a reordered object or an
        omitted `lang` versus "ro" is the same selection."""
        args = registry.TOOLS[name].args.model_validate(arguments).model_dump(mode="json")
        norm = json.dumps(args, sort_keys=True, ensure_ascii=False, separators=(",", ":"), default=str)
        return (C.CONTRACT, self.s.base_url, gen.get("id"), name, args.get("lang", "ro"), norm, POLICY_VERSION)

    async def call(self, name: str, arguments) -> dict:
        t0 = self.clock()
        self.stats["calls"] += 1
        env, cached = await self._call(name, arguments)
        self.stats[env["status"]] += 1
        ms = int((self.clock() - t0) * 1000)
        log.info("MCP_METRICS %s", json.dumps({
            "tool": str(name)[:40], "status": env["status"], "reason": env.get("reason"),
            "cached": cached, "duration_ms": ms, "result_bytes": C.size(env)}))
        if self.s.log_calls:
            line = self._log_line(name, arguments, env, cached, ms)
            await asyncio.get_running_loop().run_in_executor(self.log_executor, self._write_log, line)
        return env

    @staticmethod
    def _log_line(name, arguments, env: dict, cached: bool, ms: int) -> str:
        """Content log (TEMPO_MCP_LOG_CALLS, disclosed in the server instructions): the call and its
        whole result, one JSON line. Nothing about the caller: no IP, headers or client name. A
        refusal before any work (invalid, too big, throttled, busy) keeps only the tool, the
        reason, the argument size and a SHA-256: the arguments are never stored."""
        head = {"ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "tool": str(name)[:64],
                "status": env.get("status"), "reason": env.get("reason"), "cached": cached, "duration_ms": ms}
        if env.get("reason") in NO_ARGUMENT_LOG_REASONS:
            try:
                raw = C.dumps(arguments).encode("utf-8")
            except (TypeError, ValueError):
                raw = b""
            head |= {"argument_bytes": len(raw), "arguments_sha256": hashlib.sha256(raw).hexdigest()}
            return json.dumps(head, ensure_ascii=False)
        head |= {"arguments": ask_guard.redact(arguments) if isinstance(arguments, dict) else None,
                 "generation": (env.get("provenance") or {}).get("generation"), "result": env}
        return json.dumps(head, ensure_ascii=False, default=str)

    def _write_log(self, line: str) -> None:
        """Append one line; when it would pass TEMPO_MCP_LOG_MAX_BYTES the file becomes `.1`
        (the previous `.1` is replaced), so at most about twice the cap is kept."""
        data = (line + "\n").encode("utf-8")
        try:
            with self._log_lock:
                config.ASK_LOG_DIR.mkdir(parents=True, exist_ok=True)
                path = config.ASK_LOG_DIR / CALL_LOG
                try:
                    size = path.stat().st_size
                except OSError:
                    size = 0
                if size and size + len(data) > self.s.log_max_bytes:
                    os.replace(path, path.with_name(CALL_LOG + ".1"))
                with open(path, "ab") as f:
                    f.write(data)
        except Exception:                           # a full disk must not fail the call
            log.error("MCP call log write failed")

    async def _call(self, name: str, arguments) -> tuple[dict, bool]:
        bad = registry.precheck(name, arguments)
        if bad is not None:
            return bad, False                       # nothing ran: no slot, no budget, no scan
        gen = generation.current()
        certified = gen.get("status") == "present" and bool(gen.get("id"))
        key = self._key(name, arguments, gen) if certified else None
        if certified:
            self.cache.purge_generations_other_than(gen.get("id"))
        ok, wait = self.client_calls.allow(_CLIENT.get())
        if ok:
            ok, wait = self.calls.allow()
        if not ok:
            self.stats["throttled"] += 1
            return _gate_envelope(name, arguments, "unavailable", "busy",
                                  M.t(_lang(arguments), "gate.busy_rate"), [_retry(wait, arguments)]), False
        if key is not None:
            hit = self.cache.get(key)
            if hit is not None:
                self.stats["cache_hits"] += 1
                return hit, True
        if name in SCAN_TOOLS:
            est = self.estimator.estimate(name, arguments)
            if est is None or est > self.s.max_scan_rows:
                self.stats["scan_refused"] += 1
                lang = _lang(arguments)
                what = (M.t(lang, "gate.scan_unbounded") if est is None
                        else M.t(lang, "gate.scan_over", est=f"{est:,}", limit=f"{self.s.max_scan_rows:,}"))
                return _gate_envelope(
                    name, arguments, "unavailable", "query_budget", M.t(lang, "gate.query_budget", what=what),
                    [C.recovery("tool_call", M.t(lang, "gate.query_budget_describe"),
                                "describe_dataset", {"dataset": arguments["dataset"], "lang": arguments.get("lang", "ro")})
                     if "dataset" in arguments else C.recovery("narrow", M.t(lang, "gate.query_budget_narrow"))]), False
        waited = await self._acquire()
        if waited is None:
            self.stats["busy"] += 1
            return _gate_envelope(name, arguments, "unavailable", "busy",
                                  M.t(_lang(arguments), "gate.busy_slot"), [_retry(2.0, arguments)]), False
        with self._lock:
            self.active += 1
        token = ask_guard.CancelToken()
        loop = asyncio.get_running_loop()
        try:
            fut = loop.run_in_executor(self.executor, self._work, name, arguments, token)
        except BaseException:                       # the pool is shut down: give the slot back
            self._release()
            raise
        gone = _DISCONNECT.get()
        hangup = lambda: token.cancel("client_disconnected")        # noqa: E731
        if gone is not None:                        # the client hung up: stop the work, free the slot when it ends
            gone.on_gone(hangup)
        try:
            env = await asyncio.wait_for(asyncio.shield(fut), self.s.max_seconds + DEADLINE_GRACE)
        except asyncio.TimeoutError:
            token.cancel("deadline")
            self.stats["timeouts"] += 1
            return self._timeout(name, arguments), False
        except asyncio.CancelledError:              # the client went away: stop the work, free the slot when it ends
            token.cancel("client_disconnected")
            raise
        except Exception:  # noqa: BLE001 — the registry does not raise; never leak what did
            if token.timed_out:                     # the deadline interrupted it: that is the answer
                self.stats["timeouts"] += 1
                return self._timeout(name, arguments), False
            ref = uuid.uuid4().hex[:12]
            log.exception("MCP tool failed tool=%s ref=%s", str(name)[:40], ref)
            return _gate_envelope(name, arguments, "error", "execution_failed",
                                  M.t(_lang(arguments), "registry.failed", ref=ref)), False
        finally:
            if gone is not None:
                gone.off(hangup)
        if env is None:
            return self._timeout(name, arguments), False
        if token.timed_out:                         # an answer that arrives after the deadline is not served or cached
            self.stats["timeouts"] += 1
            return self._timeout(name, arguments), False
        if key is not None and self._cacheable(env) and generation.current().get("id") == gen.get("id"):
            self.cache.put(key, env)
        if waited >= QUEUE_NOTICE_SECONDS:            # said on this answer only, never on a cached copy
            self.stats["queued"] += 1
            env = {**env, "warnings": [*env.get("warnings", []), C.warning(
                "queued", M.t(_lang(arguments), "gate.queued", s=f"{waited:.0f}" if waited >= 1 else "<1"))]}
        return env, False

    async def _acquire(self) -> float | None:
        """Seconds this call waited for a slot, or None when none came free in time. Waiters are
        served in arrival order; a new call never overtakes one already waiting."""
        if not self._waiting and self.slots.acquire(blocking=False):
            return 0.0
        if self.s.queue_seconds <= 0 or len(self._waiting) >= self.s.max_waiting:
            return None
        me, t0 = object(), time.monotonic()        # real time: the queue bound is wall clock
        self._waiting.append(me)
        try:
            gone = _DISCONNECT.get()
            while time.monotonic() - t0 < self.s.queue_seconds and not (gone and gone.gone):
                if self._waiting[0] is me and self.slots.acquire(blocking=False):
                    return time.monotonic() - t0
                await asyncio.sleep(QUEUE_POLL_SECONDS)
            return None
        finally:
            self._waiting.remove(me)

    def _timeout(self, name, arguments) -> dict:
        lang = _lang(arguments)
        return _gate_envelope(
            name, arguments, "unavailable", "query_timeout",
            M.t(lang, "gate.timeout", s=f"{self.s.max_seconds:g}"),
            [C.recovery("narrow", M.t(lang, "gate.timeout_narrow"))])

    @staticmethod
    def _cacheable(env: dict) -> bool:
        return (env["status"] in ("ok", "partial", "needs_clarification")
                or (env["status"] == "unavailable" and env.get("reason") not in TRANSIENT_REASONS))

    def _work(self, name, arguments, token) -> dict | None:
        """Runs in the pool: its own cursor, interrupted at the deadline or on cancel. The slot is
        released here, when the work has really ended, not when the caller stopped waiting."""
        from app.db import get_conn
        cursor = None
        try:
            cursor = get_conn()
            with token.running(cursor, deadline_in=self.s.max_seconds, repeat_interrupt=True):
                return registry.call_tool(name, arguments, conn=cursor)
        except ask_guard.Cancelled:
            return None
        finally:
            if cursor is not None:
                with contextlib.suppress(Exception):
                    cursor.close()
            self._release()

    def _release(self) -> None:
        with self._lock:
            self.active -= 1
        self.slots.release()


# ---------------------------------------------------------------- MCP server

def wire_bytes(result) -> int:
    return len(result.model_dump_json(by_alias=True, exclude_none=True).encode("utf-8")) + WIRE_ALLOWANCE


def build_result(name: str, env: dict, arguments):
    """The CallToolResult for an envelope: the identical envelope as structuredContent and as the
    text fallback, within the wire budget (both representations and the JSON-RPC wrapper). The
    optional preview is shortened first; if the required content cannot fit, `response_budget`."""
    from mcp import types
    try:
        raw = C.dumps(arguments)
    except (TypeError, ValueError):
        raw = "{}"
    args_hash = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    args_bytes = len(raw.encode("utf-8"))

    def make(e):
        return types.CallToolResult(
            content=[types.TextContent(type="text", text=C.dumps(e))],
            structuredContent=e, isError=e["status"] == "error")

    result = make(env)
    shrink = registry.shrinker(name)
    lang = _lang(arguments)
    while wire_bytes(result) > MAX_WIRE_BYTES:
        if not shrink(env, lang=lang):
            env = C.response_budget(env, args_hash, args_bytes, lang)
            result = make(env)
            if wire_bytes(result) > MAX_WIRE_BYTES:      # even the refusal carries too much: bare minimum
                bare = _gate_envelope(name, arguments, "unavailable", "response_budget",
                                      env["message"], env["recovery"])
                bare["data"] = {"request": {"sha256": args_hash, "argument_bytes": args_bytes}}
                result = make(bare)
            break
        result = make(env)
    return result


def build_server(gate: Gate, settings: McpSettings):
    from mcp import types
    from mcp.server.lowlevel import Server

    server = Server(SERVER_NAME, version=SERVER_VERSION,
                    instructions=INSTRUCTIONS + (LOGGING_NOTICE if settings.log_calls else ""),
                    website_url=settings.base_url or None)
    tools = [types.Tool(
        name=name, title=spec.title, description=spec.description,
        inputSchema=registry.inline_schema(registry.input_schema(name)),
        outputSchema=registry.inline_schema(registry.output_schema(name)),
        annotations=types.ToolAnnotations(title=spec.title, readOnlyHint=True, destructiveHint=False,
                                          idempotentHint=True, openWorldHint=False))
        for name, spec in registry.TOOLS.items()]

    @server.list_tools()
    async def list_tools():
        return tools

    @server.call_tool(validate_input=False)       # the service validates strictly, before any work
    async def call_tool(name: str, arguments: dict | None):
        args = arguments if arguments is not None else {}
        env = await gate.call(name, args)
        return build_result(name, env, args)

    return server


# ---------------------------------------------------------------- HTTP endpoint

class McpEndpoint:
    """ASGI app at /mcp: body, request-rate, Host/Origin checks in front of the SDK transport."""

    def __init__(self, manager, settings: McpSettings, requests: Window, client_requests=None):
        self.manager, self.s, self.requests = manager, settings, requests
        self.client_requests = client_requests or ClientWindows(settings.client_requests_per_minute)

    @staticmethod
    def _header(scope, name: bytes) -> str | None:
        for k, v in scope.get("headers") or []:
            if k.lower() == name:
                return v.decode("latin-1")
        return None

    def _client_key(self, scope) -> str:
        """Who is calling: Fly's `Fly-Client-IP` (only on Fly, whose proxy overwrites it; elsewhere a
        client could forge it), else (only with TEMPO_MCP_TRUST_FORWARDED) the first `X-Forwarded-For`
        address, else the peer address. Used only for fair-share windows."""
        fly = self._header(scope, b"fly-client-ip") if self.s.on_fly else None
        if fly and fly.strip():
            return fly.strip()[:64]
        if self.s.trust_forwarded:
            fwd = (self._header(scope, b"x-forwarded-for") or "").split(",")[0].strip()
            if fwd:
                return fwd[:64]
        peer = scope.get("client")
        return str(peer[0])[:64] if peer else "-"

    def _headers_ok(self, scope) -> bool:
        """The SDK's Host/Origin test (it will answer 421/403 itself): checked here only to keep
        such a request out of the global window."""
        host, origin = self._header(scope, b"host"), self._header(scope, b"origin")

        def match(value, allowed):
            return value in allowed or any(a.endswith(":*") and value.startswith(a[:-2] + ":") for a in allowed)
        return bool(host) and match(host, self.s.allowed_hosts) \
            and (not origin or match(origin, self.s.allowed_origins))

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return
        origin = self._header(scope, b"origin")
        approved = origin is not None and origin in self.s.allowed_origins
        if scope["method"] == "OPTIONS":                       # CORS preflight: approved origins only
            resp = (Response(status_code=204, headers=self._cors(origin) | {
                "access-control-allow-methods": "POST, GET, DELETE, OPTIONS",
                "access-control-allow-headers": "content-type, accept, mcp-protocol-version, mcp-session-id",
                "access-control-max-age": "600"})
                    if approved else PlainTextResponse("Invalid Origin header", status_code=403))
            return await resp(scope, receive, send)
        if scope["method"] != "POST":                          # stateless: no sessions, no server-sent stream
            return await PlainTextResponse("Method Not Allowed", status_code=405,
                                           headers={"allow": "POST, OPTIONS"})(scope, receive, send)
        client = self._client_key(scope)
        ok, wait = self.client_requests.allow(client)
        if ok and not self._headers_ok(scope):                  # refused below by the SDK: the client's own cost only
            _CLIENT.set(client)
            return await self.manager.handle_request(scope, receive, send)
        if ok:
            ok, wait = self.requests.allow()
        if not ok:
            return await JSONResponse({"error": "too many requests"}, status_code=429,
                                      headers={"retry-after": str(max(1, round(wait)))})(scope, receive, send)
        declared = self._header(scope, b"content-length")
        if declared is not None and declared.isdigit() and int(declared) > self.s.max_body_bytes:
            return await self._too_large(scope, receive, send)
        body = bytearray()
        more = True
        while more:                                             # bounded read, before any parsing
            msg = await receive()
            if msg["type"] == "http.disconnect":
                return
            body += msg.get("body", b"")
            if len(body) > self.s.max_body_bytes:
                return await self._too_large(scope, receive, send)
            more = msg.get("more_body", False)
        sent = False
        gone = _Disconnect()

        async def watch():                                      # the only reader of `receive` from here on
            while True:
                if (await receive())["type"] == "http.disconnect":
                    return gone.fire()

        async def replay():
            nonlocal sent
            if not sent:
                sent = True
                return {"type": "http.request", "body": bytes(body), "more_body": False}
            await gone.event.wait()                             # then the real disconnect
            return {"type": "http.disconnect"}

        async def cors_send(message):
            if approved and message["type"] == "http.response.start":
                message.setdefault("headers", []).extend(
                    (k.encode(), v.encode()) for k, v in self._cors(origin).items())
            await send(message)

        _CLIENT.set(client)
        _DISCONNECT.set(gone)
        watcher = asyncio.ensure_future(watch())
        try:
            await self.manager.handle_request(scope, replay, cors_send if approved else send)
        except RuntimeError as e:                               # lifespan did not start the manager
            if "Task group is not initialized" not in str(e):
                raise
            await PlainTextResponse("MCP server is not running", status_code=503)(scope, receive, send)
        finally:
            watcher.cancel()

    @staticmethod
    def _cors(origin: str) -> dict:
        return {"access-control-allow-origin": origin, "vary": "Origin"}

    async def _too_large(self, scope, receive, send):
        await JSONResponse({"error": f"request body exceeds {self.s.max_body_bytes} bytes"},
                           status_code=413)(scope, receive, send)


class _NotFound:
    """An ASGI app answering 404 to every method (a plain function endpoint would only get GET)."""

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http":
            await PlainTextResponse("Not Found", status_code=404)(scope, receive, send)


class PublicMcp:
    """One application's MCP: settings, gate, server and session manager (built per app)."""

    def __init__(self, settings: McpSettings):
        from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
        from mcp.server.transport_security import TransportSecuritySettings
        self.settings = settings
        self.gate = Gate(settings)
        self.server = build_server(self.gate, settings)
        self.manager = StreamableHTTPSessionManager(
            app=self.server, json_response=True, stateless=True,
            security_settings=TransportSecuritySettings(
                enable_dns_rebinding_protection=True,
                allowed_hosts=list(settings.allowed_hosts),
                allowed_origins=list(settings.allowed_origins)))
        self.endpoint = McpEndpoint(self.manager, settings, Window(settings.max_requests_per_minute),
                                    ClientWindows(settings.client_requests_per_minute))

    @contextlib.asynccontextmanager
    async def lifespan(self):
        try:
            async with self.manager.run():
                yield
        finally:
            self.gate.close()


def install(app, environ=None):
    """Mount /mcp on `app` (before any catch-all). Disabled: every method and subpath of /mcp is a
    404. Raises McpConfigError at build time for an enabled endpoint with invalid settings."""
    settings = McpSettings.from_env(environ)
    mcp = PublicMcp(settings) if settings.enabled else None
    app.state.public_mcp = mcp
    not_found = _NotFound()
    exact = Route("/mcp", endpoint=mcp.endpoint if mcp else not_found)
    app.router.routes.insert(0, Route("/mcp/{rest:path}", endpoint=not_found))   # never /mcp/mcp or a redirect
    app.router.routes.insert(0, exact)
    return mcp


@contextlib.asynccontextmanager
async def lifespan(app):
    """Run the application's MCP session manager (if any) for the life of the app."""
    mcp = getattr(app.state, "public_mcp", None)
    if mcp is None:
        yield
        return
    async with mcp.lifespan():
        yield


def health_summary(app) -> dict:
    """Capability summary for /api/health: no secrets, paths, contents or client identifiers."""
    mcp = getattr(app.state, "public_mcp", None)
    return {"enabled": mcp is not None, "contract": C.CONTRACT,
            "generation": generation.current().get("status"),
            "call_logging": bool(mcp is not None and mcp.settings.log_calls)}
