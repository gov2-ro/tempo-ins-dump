"""Curated notes per dataset: caveats, series breaks, decisions, source issues.

Notes live in `app/data/dataset_notes.json` (tracked, so they survive a corpus
rebuild). A note names datasets in `codes`; a parent code also covers its split
children (`POP105A` covers `POP105A_judete_grupe`). Public notes are shown on the
dataset page and returned by `/api/datasets/{code}`; every note, public or not,
feeds the decision log `docs/reports/ins-notes.md`
(`scripts/build-notes-report.py`).

Note fields: id, codes, kind (KINDS), public, text {ro, en}, optional data
(structured, e.g. {"between": ["2021", "2022"]}), decided {by, date, context},
evidence, and ins {raise, question} for points to take up with INS.
"""
from __future__ import annotations

import json
import threading
from pathlib import Path

NOTES_PATH = Path(__file__).resolve().parent.parent / "data" / "dataset_notes.json"

KINDS = ("definition", "coverage", "series_break", "provisional", "caveat",
         "excluded", "decision", "source_issue")

_lock = threading.Lock()
_cache: dict = {"mtime": None, "notes": []}


def load(path: Path = NOTES_PATH) -> list[dict]:
    """All notes, re-read when the file changes."""
    mtime = path.stat().st_mtime_ns
    with _lock:
        if path == NOTES_PATH and _cache["mtime"] == mtime:
            return _cache["notes"]
    notes = json.loads(path.read_text(encoding="utf-8"))["notes"]
    if path == NOTES_PATH:
        with _lock:
            _cache.update(mtime=mtime, notes=notes)
    return notes


def _applies(note: dict, code: str) -> bool:
    parent = code.split("_", 1)[0]
    return any(c == code or c == parent for c in note["codes"])


def for_code(code: str, lang: str = "ro", *, public_only: bool = True,
             notes: list[dict] | None = None) -> list[dict]:
    """Notes for one dataset (and its parent), text in `lang`, file order."""
    out = []
    for n in notes if notes is not None else load():
        if (public_only and not n.get("public")) or not _applies(n, code):
            continue
        text = n["text"].get(lang) or n["text"]["ro"]
        out.append({"id": n["id"], "kind": n["kind"], "text": text,
                    **({"data": n["data"]} if n.get("data") else {})})
    return out
