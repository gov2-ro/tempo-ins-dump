"""Request validation, provider allowlist, redaction and concurrency gate for Ask (FIX-08).

Kept separate from agent.py so the rules are testable without a provider.
All limits are read from ``app.config`` at call time.
"""
from __future__ import annotations

import contextvars
import json
import logging
import re
import threading
from contextlib import contextmanager

from fastapi import HTTPException

from app import config

# ---------------------------------------------------------------------------
# History validation
# ---------------------------------------------------------------------------

ALLOWED_ROLES = ("user", "assistant")


def _err(status: int, msg: str) -> HTTPException:
    return HTTPException(status, msg)


def _normalise_content(content, where: str) -> str:
    """Accept a plain string, or a list of {"type": "text", "text": str} blocks.

    Anything else (tool_use / tool_result blocks, images, nested dicts) is rejected:
    clients cannot inject internal tool messages.
    """
    if isinstance(content, str):
        text = content
    elif isinstance(content, list) and content:
        parts = []
        for b in content:
            if (isinstance(b, dict) and set(b) <= {"type", "text"}
                    and b.get("type") == "text" and isinstance(b.get("text"), str)):
                parts.append(b["text"])
            else:
                raise _err(400, f"{where}: unsupported content block")
        text = "\n".join(parts)
    else:
        raise _err(400, f"{where}: content must be a string or a list of text blocks")
    if not text.strip():
        raise _err(400, f"{where}: content must not be empty")
    if len(text) > config.ASK_MAX_TURN_CHARS:
        raise _err(413, f"{where}: content exceeds {config.ASK_MAX_TURN_CHARS} characters")
    return text


def validate_history(history, question: str) -> list[dict]:
    """Return a clean ``[{role, content: str}]`` list or raise HTTPException (400/413)."""
    if history is None:
        history = []
    if not isinstance(history, list):
        raise _err(400, "history must be a list")
    if len(history) > config.ASK_MAX_HISTORY_TURNS:
        raise _err(413, f"history exceeds {config.ASK_MAX_HISTORY_TURNS} turns")
    clean: list[dict] = []
    total = len(question or "")
    for i, turn in enumerate(history):
        where = f"history[{i}]"
        if not isinstance(turn, dict):
            raise _err(400, f"{where}: must be an object")
        if set(turn) - {"role", "content"}:
            raise _err(400, f"{where}: only 'role' and 'content' are allowed")
        role = turn.get("role")
        if role not in ALLOWED_ROLES:
            raise _err(400, f"{where}: role must be 'user' or 'assistant'")
        text = _normalise_content(turn.get("content"), where)
        total += len(text)
        clean.append({"role": role, "content": text})
    if total > config.ASK_MAX_REQUEST_CHARS:
        raise _err(413, f"request exceeds {config.ASK_MAX_REQUEST_CHARS} characters")
    return clean


# ---------------------------------------------------------------------------
# Provider / model allowlist
# ---------------------------------------------------------------------------

from app.services.llm_client import KEYLESS, PROVIDERS as KNOWN_PROVIDERS, provider_available  # noqa: E402


def _json_models() -> dict[str, list[str]]:
    try:
        raw = json.loads(config.ASK_MODELS_FILE.read_text(encoding="utf-8"))
        return {p: [m["id"] for m in ms if isinstance(m, dict) and "id" in m]
                for p, ms in raw.items() if p in KNOWN_PROVIDERS}
    except Exception:
        return {}


def _pairs(items: list[str]) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for it in items:
        if ":" in it:
            p, m = it.split(":", 1)
            out.setdefault(p.strip(), []).append(m.strip())
    return out


def byok_allowlist() -> dict[str, list[str]]:
    """provider -> allowed model ids for user-key (BYOK) calls."""
    allow = _pairs(config.ASK_ALLOWED_MODELS) if config.ASK_ALLOWED_MODELS else _json_models()
    if config.ASK_ALLOWED_PROVIDERS:
        allow = {p: m for p, m in allow.items() if p in config.ASK_ALLOWED_PROVIDERS}
    return {p: m for p, m in allow.items() if provider_available(p) and m}


def is_keyless(provider: str | None) -> bool:
    """A provider that takes no key (local Ollama): its calls follow the own-key rules."""
    return (provider or "").strip().lower() in KEYLESS


def server_allowlist() -> dict[str, list[str]]:
    """provider -> model ids a server-funded call may use (default: the configured pair only)."""
    if config.ASK_SERVER_MODELS:
        return _pairs(config.ASK_SERVER_MODELS)
    return {config.LLM_PROVIDER: [config.LLM_MODEL]}


def resolve_provider_model(provider: str | None, model: str | None, byok: bool) -> tuple[str, str]:
    """Validate and complete the (provider, model) pair. Raises 400/403 for anything unlisted.

    Server-funded calls are limited to the server allowlist; BYOK calls use the wider
    public allowlist. Unknown providers never fall through to another provider.
    """
    allow = byok_allowlist() if byok else server_allowlist()
    prov = (provider or config.LLM_PROVIDER).strip().lower()
    if prov not in KNOWN_PROVIDERS:
        raise _err(400, "unsupported provider")
    if prov not in allow:
        raise _err(400 if byok else 403, "provider not allowed")
    mdl = (model or "").strip()
    if not mdl:
        if not byok and prov == config.LLM_PROVIDER and config.LLM_MODEL in allow[prov]:
            mdl = config.LLM_MODEL
        else:
            mdl = allow[prov][0]
    if mdl not in allow[prov]:
        raise _err(400 if byok else 403, "model not allowed")
    return prov, mdl


# ---------------------------------------------------------------------------
# Credential redaction
# ---------------------------------------------------------------------------

REDACTED = "[REDACTED]"
_SECRET_KEY_RE = re.compile(
    r"(api[-_]?key|authorization|x-api-key|x-goog-api-key|token|secret|password|credential)", re.I)
_PLAIN_VALUE_RES = [
    re.compile(r"sk-[A-Za-z0-9_\-]{8,}"),                 # OpenAI / Anthropic style
    re.compile(r"AIza[0-9A-Za-z_\-]{20,}"),               # Google API keys
    re.compile(r"xai-[A-Za-z0-9_\-]{8,}"),                # xAI
    re.compile(r"(?i)bearer\s+[A-Za-z0-9._\-]{8,}"),
]
_KV_RE = re.compile(r"(?i)(api[-_]?key|x-api-key|authorization)(\"?\s*[:=]\s*\"?)[^\s\"',}]+")


def redact_text(s: str, secrets: tuple = ()) -> str:
    for sec in secrets:
        if sec and len(sec) >= 4:
            s = s.replace(sec, REDACTED)
    for rx in _PLAIN_VALUE_RES:
        s = rx.sub(REDACTED, s)
    return _KV_RE.sub(lambda m: m.group(1) + m.group(2) + REDACTED, s)


def redact(obj, secrets: tuple = ()):
    """Recursively redact credentials from dict/list/str structures (returns a copy)."""
    if isinstance(obj, dict):
        # a number or flag cannot carry a credential: `max_tokens: 2048` is a count, not a token
        return {k: (REDACTED if isinstance(k, str) and _SECRET_KEY_RE.search(k)
                    and not isinstance(v, (bool, int, float, type(None)))
                    else redact(v, secrets)) for k, v in obj.items()}
    if isinstance(obj, (list, tuple, set)):
        return [redact(v, secrets) for v in obj]
    if isinstance(obj, str):
        return redact_text(obj, secrets)
    return obj


# The key of the request being served, visible to every log record emitted while it runs.
# Pattern redaction alone cannot know an arbitrary-format key (a Mistral or OpenRouter key has
# no recognizable prefix); the actual secrets of the request can be removed exactly.
_request_secrets: contextvars.ContextVar[tuple] = contextvars.ContextVar("ask_request_secrets", default=())


def active_secrets() -> tuple:
    return _request_secrets.get()


@contextmanager
def secrets_scope(*secrets):
    """Within this block, RedactingFilter also removes these exact strings from log records."""
    token = _request_secrets.set(tuple(s for s in secrets if s and len(s) >= 4))
    try:
        yield
    finally:
        _request_secrets.reset(token)


class RedactingFilter(logging.Filter):
    """Scrubs credential patterns, and the active request's own key, from any record on the
    loggers it is attached to."""

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            msg = record.getMessage()
        except Exception:
            msg = str(record.msg)
        record.msg = redact_text(msg, active_secrets())
        record.args = None
        if record.exc_info:  # tracebacks may embed provider messages; keep the type only
            record.exc_text = None
            et = record.exc_info[0]
            record.msg += f" [{et.__name__ if et else 'error'}]"
            record.exc_info = None
        return True


# ---------------------------------------------------------------------------
# Concurrency gate (in-process; one Fly machine, one worker)
# ---------------------------------------------------------------------------

_gate_lock = threading.Lock()
_active = 0


def active_requests() -> int:
    return _active


@contextmanager
def concurrency_slot():
    """Non-blocking slot; raises 503 + Retry-After when ASK_MAX_CONCURRENT are in flight."""
    global _active
    with _gate_lock:
        if _active >= max(1, config.ASK_MAX_CONCURRENT):
            raise HTTPException(
                503, "Ask is busy; retry shortly",
                headers={"Retry-After": str(config.ASK_RETRY_AFTER_SECONDS)})
        _active += 1
    try:
        yield
    finally:
        with _gate_lock:
            _active -= 1


# ---------------------------------------------------------------------------
# Bounded debug fields and content-free metrics (AT-02)
# ---------------------------------------------------------------------------

def bound(obj, *, max_str: int = 300, max_items: int = 20, max_depth: int = 4):
    """A bounded copy for debug events: long strings, lists and dicts are shortened with an
    explicit marker and depth is capped, so the serialized record stays valid JSON (never
    sliced mid-string) and small."""
    if isinstance(obj, str):
        return obj if len(obj) <= max_str else obj[:max_str] + f"…(+{len(obj) - max_str} chars)"
    if max_depth <= 0 and isinstance(obj, (dict, list, tuple, set)):
        return f"<{type(obj).__name__} of {len(obj)}>"
    if isinstance(obj, dict):
        items = list(obj.items())
        out = {str(k)[:60]: bound(v, max_str=max_str, max_items=max_items, max_depth=max_depth - 1)
               for k, v in items[:max_items]}
        if len(items) > max_items:
            out["…"] = f"+{len(items) - max_items} keys"
        return out
    if isinstance(obj, (list, tuple, set)):
        seq = list(obj)
        out = [bound(v, max_str=max_str, max_items=max_items, max_depth=max_depth - 1)
               for v in seq[:max_items]]
        if len(seq) > max_items:
            out.append(f"…(+{len(seq) - max_items} items)")
        return out
    if obj is None or isinstance(obj, (bool, int, float)):
        return obj
    return bound(str(obj), max_str=max_str)


# What an ordinary (chat logging off) metrics line may contain: ids, counts, sizes, durations
# and stable codes. Never the question, history, answer, tool filter values, a credential or
# an exception body: anything else is dropped here, not trusted to the caller.
METRIC_SCALARS = (
    "request_id", "ts", "provider", "model", "byok", "status", "reason", "outcome", "stop_reason",
    "question_chars", "history_turns", "context_entries", "model_attempts", "retries",
    "tool_dispatches", "tool_executions", "cache_hits", "iterations", "tools", "elapsed_s",
    "duration_ms", "request_bytes", "tool_result_bytes", "requested_output_tokens",
    "dropped_debug_events", "cancelled", "timed_out",
)
_CODE_RE = re.compile(r"^[a-z0-9_]{1,40}$")


def sanitize_metrics(fields: dict) -> dict:
    out = {}
    for k in METRIC_SCALARS:
        v = fields.get(k)
        if v is None or isinstance(v, (bool, int, float)):
            out[k] = v
        elif isinstance(v, str):
            out[k] = v[:80]
    usage = fields.get("usage")
    if isinstance(usage, dict):
        out["usage"] = {k: v for k, v in usage.items()
                        if k in ("input_tokens", "output_tokens", "reasoning_tokens", "cached_tokens")
                        and (v is None or isinstance(v, int))}
    for name in ("refusal_codes", "claim_codes"):
        codes = fields.get(name)
        if isinstance(codes, dict) and (codes or name == "refusal_codes"):    # claim_codes only when claims were checked
            out[name] = {k: v for k, v in codes.items()
                         if isinstance(k, str) and _CODE_RE.match(k) and isinstance(v, int)}
    return {k: v for k, v in out.items() if v is not None}


# ---------------------------------------------------------------------------
# Cancellation (AT-02)
# ---------------------------------------------------------------------------

class Cancelled(Exception):
    """The request was abandoned (browser abort / disconnect) or its deadline passed mid-operation."""


class CancelToken:
    """Carries a cancellation from the HTTP layer into the agent loop and, through the cursor
    the agent owns, into a running DuckDB query.

    `cancel()` is safe from any thread. It interrupts only the cursor currently attached with
    `running()`: that cursor belongs to this request (the agent opens its own), so another
    user's query and the shared parent connection are never touched. A provider call already
    in flight cannot be interrupted; it ends at its own (deadline-bounded) timeout, and the
    caller's concurrency slot stays occupied until the work actually stops."""

    def __init__(self):
        self._event = threading.Event()
        self._lock = threading.Lock()
        self._cursor = None
        self.reason: str | None = None
        self.timed_out = False

    @property
    def cancelled(self) -> bool:
        return self._event.is_set()

    def cancel(self, reason: str = "cancelled") -> None:
        with self._lock:
            if not self._event.is_set():
                self.reason = reason
                self._event.set()
            cursor = self._cursor
        self._interrupt(cursor)

    @staticmethod
    def _interrupt(cursor) -> None:
        if cursor is not None:
            try:
                cursor.interrupt()
            except Exception:  # noqa: BLE001 — a closed cursor has nothing left to interrupt
                pass

    @contextmanager
    def running(self, cursor, deadline_in: float | None = None):
        """Attach `cursor` while one operation runs; optionally interrupt it when
        `deadline_in` seconds pass. Raises Cancelled up front if already cancelled."""
        with self._lock:
            if self._event.is_set():
                raise Cancelled(self.reason or "cancelled")
            self._cursor = cursor
        timer = None
        if deadline_in is not None:
            def expire():
                self.timed_out = True
                self._interrupt(cursor)
            timer = threading.Timer(max(0.0, deadline_in), expire)
            timer.daemon = True
            timer.start()
        try:
            yield
        finally:
            if timer is not None:
                timer.cancel()
            with self._lock:
                self._cursor = None
