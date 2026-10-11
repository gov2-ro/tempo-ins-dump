"""Unique-grain gate for aggregations (PA-01b, audit A04).

Two rows with the same full dimension key are a broken grain. If their values
differ (conflicting grain) no single answer exists; if they agree, a SUM still
counts the value twice. Neither is the overlapping-categories problem the
aggregation policy handles. Both need this gate.

Evidence, in order:
  1. The generation manifest certifies a file when its grain check ran, the file
     is not listed, and duplicate keys were recorded. Such a file is `unique`.
  2. Otherwise the selected slice is checked at query time, bounded by
     GRAIN_CHECK_MAX_ROWS for unfiltered requests and by the connection's memory
     limit. A clean slice is allowed (`slice_checked`); a dirty or uncheckable
     one is refused. Nothing is deduplicated or picked.

Raw observations stay available; callers report `file_status` beside them.
"""
from __future__ import annotations

import logging
from collections import OrderedDict

from app.config import PARQUET_DIR
from app.services import generation
from app.services.query_builder import quote_ident

log = logging.getLogger(__name__)

GRAIN_CHECK_MAX_ROWS = 1_000_000   # unfiltered query-time check bound
_CACHE_MAX = 1024
_cache: OrderedDict = OrderedDict()


def file_status(code: str) -> dict:
    """What the generation evidence says about the whole file.

    status: unique | conflicting | duplicate_keys | unverified
    `unverified` covers: no/stale manifest, grain not checked, or a manifest
    that recorded conflicts but not equal-value duplicates.
    """
    g = generation.current()
    base = {"generation": g["id"]}
    if g["status"] != "present" or not g["grain_checked"]:
        return {**base, "status": "unverified", "evidence": f"manifest_{g['status']}"
                if g["status"] != "present" else "grain_not_checked"}
    if code in g["conflicting"]:
        return {**base, "status": "conflicting", "evidence": "generation_audit"}
    if code in g["duplicates"]:
        return {**base, "status": "duplicate_keys", "evidence": "generation_audit"}
    if not g["duplicates_recorded"]:
        return {**base, "status": "unverified", "evidence": "duplicates_not_recorded"}
    return {**base, "status": "unique", "evidence": "generation_audit"}


def check_slice(conn, code: str, filters: dict, row_count: int | None = None,
                value_column: str = "OBS_VALUE", path: str | None = None) -> dict:
    """May this slice of `code` be aggregated? `filters` use the file's column
    names (as passed to the query builder); `path` overrides the corpus parquet
    and `row_count` None reads it from the file. Returns
    {ok, reason, evidence, generation, duplicate_keys, conflicting_keys}."""
    fs = file_status(code)
    out = {"generation": fs["generation"], "file_status": fs["status"]}
    if fs["status"] == "unique":
        return {**out, "ok": True, "reason": None, "evidence": "generation_audit"}

    active = {c: [str(v) for v in vs] for c, vs in (filters or {}).items() if vs}
    key = (fs["generation"], code, tuple(sorted((c, tuple(v)) for c, v in active.items())))
    if key in _cache:
        _cache.move_to_end(key)
        return _cache[key]
    path = path or str(PARQUET_DIR / f"{code}.parquet")
    try:
        if not active and row_count is None:
            row_count = conn.execute("SELECT count(*) FROM read_parquet(?)", [path]).fetchone()[0]
    except Exception:
        log.exception("grain row count failed matrix=%s", code)
        return {**out, "ok": False, "reason": "grain_unverified", "evidence": "slice_check_failed"}
    if not active and (row_count or 0) > GRAIN_CHECK_MAX_ROWS:
        return {**out, "ok": False, "reason": "grain_unverified",
                "evidence": "slice_too_large_to_check"}

    try:
        cols = [r[0] for r in conn.execute(
            "DESCRIBE SELECT * FROM read_parquet(?)", [path]).fetchall()]
        dims = [c for c in cols if c not in (value_column, "OBS_VALUE")]
        where, params = [], [path]
        for c, vs in active.items():
            if c not in cols:
                continue
            where.append(f"CAST({quote_ident(c)} AS VARCHAR) IN ({', '.join('?' for _ in vs)})")
            params.extend(vs)
        where_sql = f"WHERE {' AND '.join(where)}" if where else ""
        g = ", ".join(quote_ident(c) for c in dims)
        dup, conf = conn.execute(
            f"SELECT count(*), count(*) FILTER (WHERE nv > 1) FROM ("
            f"SELECT count(DISTINCT {quote_ident(value_column)}) AS nv FROM read_parquet(?) "
            f"{where_sql} GROUP BY {g} HAVING count(*) > 1)", params).fetchone()
    except Exception:
        log.exception("grain slice check failed matrix=%s", code)
        return {**out, "ok": False, "reason": "grain_unverified", "evidence": "slice_check_failed"}

    if conf:
        res = {**out, "ok": False, "reason": "conflicting_grain"}
    elif dup:
        res = {**out, "ok": False, "reason": "duplicate_keys"}
    else:
        res = {**out, "ok": True, "reason": None}
    res.update(evidence="slice_check", duplicate_keys=dup, conflicting_keys=conf)
    _cache[key] = res
    if len(_cache) > _CACHE_MAX:
        _cache.popitem(last=False)
    return res
