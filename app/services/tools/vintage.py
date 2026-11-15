"""Newer-vintage disclosure (PKG-TOOLS F1).

INS publishes some concepts in more than one table, and a later table can revise years that an
earlier one still shows (births 2024: POP201A 148,916, POP201D 157,270). A reviewed concept in
app/data/concepts.json lists its tables: `family`, optional `also_families` (other tables of the same
concept) and `also_variants` (the same level in a newer table, which discovery prefers). When the
table a tool answers from was updated before a sibling of its concept, the result carries a
`newer_vintage` warning that names the newer table and both dates.
"""
from __future__ import annotations

import logging

from app.services import concept_search
from app.services.tools import contract as C
from app.services.tools import messages as M

log = logging.getLogger(__name__)
TOOLS = ("query_data", "rank_entities", "compare_periods", "run_recipe", "describe_dataset")


def _date(conn, code: str):
    row = conn.execute("SELECT ultima_actualizare FROM matrices WHERE matrix_code = ?", [code]).fetchone()
    return row[0] if row and row[0] else None


def _family_of(conn, code: str) -> str:
    row = conn.execute("SELECT parent_matrix_code FROM matrices WHERE matrix_code = ?", [code]).fetchone()
    return row[0] if row and row[0] else code


def newer_sibling(conn, code: str):
    """(newer table, its date, this table's date) or None. Tables compare at family level."""
    own = _family_of(conn, code)
    best = None
    for c in concept_search.load_concepts():
        fams = [f for f in [c.get("family"), *(c.get("also_families") or [])] if f]
        if len(set(fams)) < 2:
            continue
        members = set(fams) | set((c.get("variants") or {}).values()) | set((c.get("also_variants") or {}).values())
        if code not in members and own not in members:
            continue
        mine = _date(conn, own)
        if mine is None:
            continue
        for f in fams:
            if f == own:
                continue
            theirs = _date(conn, f)
            if theirs is not None and theirs > mine and (best is None or theirs > best[1]):
                best = (f, theirs, mine)
    return best


def prefers(conn, code: str, alt: str) -> bool:
    """Is `alt` a newer table than `code` whose file passes the grain gate?"""
    from app.services import grain_guard
    a, b = _date(conn, _family_of(conn, alt)), _date(conn, _family_of(conn, code))
    return bool(a and b and a > b and grain_guard.file_status(alt)["status"] not in ("conflicting", "duplicate_keys"))


def apply(env: dict, ctx) -> dict:
    """Add one `newer_vintage` warning per older cited table of a result, in place."""
    if env.get("tool") not in TOOLS or ctx.conn is None:
        return env
    seen = set()
    for src in ((env.get("provenance") or {}).get("sources") or []):
        code = src.get("dataset") if isinstance(src, dict) else None
        if not code or src.get("role") == "entity_classification" or code in seen:
            continue
        seen.add(code)
        try:
            hit = newer_sibling(ctx.conn, code)
        except Exception:
            log.exception("vintage lookup failed code=%s", code)
            continue
        if hit:
            newer, new_date, own_date = hit
            env.setdefault("warnings", []).append(C.warning(
                "newer_vintage", M.t(ctx.lang, "discover.vintage_newer", code=code, own_date=own_date,
                                     newer=newer, new_date=new_date), code))
    return env
