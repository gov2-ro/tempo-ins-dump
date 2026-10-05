"""Request validation, provider allowlist, redaction and concurrency gate for Ask (FIX-08).

Kept separate from agent.py so the rules are testable without a provider.
All limits are read from ``app.config`` at call time.
"""
from __future__ import annotations

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

KNOWN_PROVIDERS = ("anthropic", "openai", "gemini")


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
    return {p: m for p, m in allow.items() if p in KNOWN_PROVIDERS and m}


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
        return {k: (REDACTED if isinstance(k, str) and _SECRET_KEY_RE.search(k)
                    else redact(v, secrets)) for k, v in obj.items()}
    if isinstance(obj, (list, tuple, set)):
        return [redact(v, secrets) for v in obj]
    if isinstance(obj, str):
        return redact_text(obj, secrets)
    return obj


class RedactingFilter(logging.Filter):
    """Scrubs credential patterns from any record on the loggers it is attached to."""

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            msg = record.getMessage()
        except Exception:
            msg = str(record.msg)
        record.msg = redact_text(msg)
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
