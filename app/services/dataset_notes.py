"""Curated notes per dataset: caveats, series breaks, decisions, source issues.

Notes live in `app/data/dataset_notes.json` (tracked, so they survive a corpus
rebuild). A note names datasets in `codes`; a parent code also covers its split
children (`POP105A` covers `POP105A_judete_grupe`). Public notes are shown on the
dataset page and returned by `/api/datasets/{code}`; every note, public or not,
feeds the decision log `docs/reports/ins-notes.md`
(`scripts/build-notes-report.py`).

Besides the curated notes, `source_totals_note` derives one per dataset: a mean,
rate or index whose INS matrix has "Total" options our download leaves out.

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


PUBLISHED_TOTALS_PATH = NOTES_PATH.parent / "published_totals.json"


def _published_matrices() -> set:
    try:
        spec = json.loads(PUBLISHED_TOTALS_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return set()
    return {q["matrix"] for q in spec.get("queries", [])}


def source_totals_note(conn, code: str, measure: str | None, lang: str = "ro") -> dict | None:
    """Generated note for a non-additive dataset whose INS matrix publishes "Total"
    options (kept in dimension_options from the metadata) that the fetch dropped:
    such a total cannot be rebuilt by adding values, and the site does not compute
    it. None for additive datasets or when nothing was dropped."""
    if measure != "non_additive":
        return None
    row = conn.execute("SELECT COALESCE(parent_matrix_code, matrix_code) FROM matrices "
                       "WHERE matrix_code = ?", [code]).fetchone()
    if not row:
        return None
    parent = row[0]
    own = {r[0] for r in conn.execute(
        "SELECT dim_column_name FROM dimensions WHERE matrix_code = ?", [code]).fetchall()}
    dropped = conn.execute(
        "SELECT d.dim_column_name, d.dim_label FROM dimensions d "
        "WHERE d.matrix_code = ? AND d.option_count > 1 AND EXISTS (SELECT 1 FROM dimension_options o "
        "WHERE o.dimension_id = d.dimension_id AND lower(trim(o.option_label)) = 'total') "
        "ORDER BY d.dim_code", [parent]).fetchall()
    dims = [label for col, label in dropped
            if col in own and col not in ("TIME_PERIOD", "UNIT_MEASURE")]
    if not dims:
        return None
    names = ", ".join(f"„{d.strip()}”" if lang != "en" else f"'{d.strip()}'" for d in dims)
    if lang == "en":
        text = (f"INS also publishes the total ('Total' option) for {names}; our download does not "
                "include it. For an average, a rate or an index the total is not the sum of the "
                "values, so the site does not compute it.")
        if parent in _published_matrices():
            text += " INS's own totals for the main indicator are shown on the comparison and county pages."
    else:
        text = (f"INS publică și valoarea totală (opțiunea „Total”) pentru {names}; descărcarea noastră "
                "nu o conține. La o medie, o rată sau un indice totalul nu este suma valorilor, așa că "
                "site-ul nu îl calculează.")
        if parent in _published_matrices():
            text += " Totalurile publicate de INS pentru indicatorul principal apar în pagina de comparație și pe paginile județelor."
    return {"id": "source-totals-not-downloaded", "kind": "caveat", "text": text,
            "data": {"matrix": parent, "dimensions": [d.strip() for d in dims]}}
