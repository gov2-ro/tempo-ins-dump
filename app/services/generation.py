"""Identity and quality evidence of the corpus generation the app serves (PA-01b).

Reads `corpus/generation-manifest.json` (scripts/build-generation-manifest.py,
staged by prepare-deploy-data.sh). Evidence is tied to that generation: if the
manifest is missing, does not match the DB it sits next to, or never ran the
grain check, `status`/`grain_checked` say so and nothing is certified.

The DB match is a size check (hashing 400MB per process start is too slow); it
catches a swapped DB, not an in-place edit of equal size.
"""
from __future__ import annotations

import json
import logging
import threading

from app import config

log = logging.getLogger(__name__)

MANIFEST_NAME = "generation-manifest.json"

_lock = threading.Lock()
_cache: dict = {"key": None, "value": None}


def _empty(status: str) -> dict:
    return {"id": None, "status": status, "built_at": None, "grain_checked": False,
            "conflicting": frozenset(), "duplicates": frozenset(),
            "duplicates_recorded": False}


def current() -> dict:
    """{id, status: present|stale|missing|unreadable, built_at, grain_checked,
    conflicting, duplicates, duplicates_recorded}. Cached per manifest file."""
    path = config.CORPUS_DIR / MANIFEST_NAME
    try:
        st = path.stat()
    except FileNotFoundError:
        return _empty("missing")
    key = (str(path), st.st_mtime_ns, st.st_size, str(config.DB_PATH))
    with _lock:
        if _cache["key"] == key:
            return _cache["value"]
    try:
        m = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        log.exception("generation manifest unreadable: %s", path)
        return _empty("unreadable")
    status = "present"
    try:
        if (m.get("db") or {}).get("size") != config.DB_PATH.stat().st_size:
            status = "stale"
    except OSError:
        status = "stale"
    audit = m.get("audit") or {}
    findings = audit.get("grain_findings") or {}
    conflicting = set((audit.get("violations") or {}).get("conflicting_grain") or [])
    conflicting |= set(findings.get("conflicting_grain") or [])
    dups = findings.get("duplicate_grain")
    value = {"id": m.get("generation_id"), "status": status, "built_at": m.get("built_at"),
             "grain_checked": bool(audit.get("grain_checked")),
             "conflicting": frozenset(conflicting),
             "duplicates": frozenset(dups or []) | frozenset(conflicting),
             "duplicates_recorded": dups is not None}
    with _lock:
        _cache.update(key=key, value=value)
    return value


def summary() -> dict:
    """JSON-safe identity for responses and /api/health."""
    g = current()
    return {"id": g["id"], "status": g["status"], "built_at": g["built_at"]}


def precondition(expected: str | None) -> dict | None:
    """None when there is no precondition or the served generation is `expected`;
    otherwise the 409 detail of a stale evidence request (`generation_changed`).
    Evidence routes check it before building a bundle and again before sending."""
    if expected is None or expected == "":
        return None
    g = current()
    if g["status"] == "present" and g["id"] == expected:
        return None
    return {"reason": "generation_changed",
            "message": "The data generation changed since this answer was computed; "
                       "re-run the selection to cite the current data.",
            "expected_generation": expected, "served_generation": g["id"],
            "served_status": g["status"]}
