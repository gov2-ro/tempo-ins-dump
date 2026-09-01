"""Access layer for the `dimension_structure` table (13-dimension-structure.py).

What a dimension's options *mean*, as opposed to how many there are:

  levels           mutually-exclusive option sets that tile the domain.
                   POP107D's AGE has two — 85 single years and 17 five-year
                   bands — so summing the whole dim double-counts everybody.
  aggregate_value  the roll-up option, but only when its value was verified
                   against the level sum. "Total fructe" is an indicator name,
                   not a total, and does not survive that check.
  nests_in         REF_AREA_2 (3,179 localities) sits inside REF_AREA (41
                   counties), so it is a drill-down, not a filter dropdown.
  additive         whether options can be SUMmed, decided per dataset rather
                   than guessed from the unit type.

Every accessor returns None/empty when the profiler has no verified answer, so
callers fall back to their existing behaviour and an unprofiled dataset renders
exactly as it does today.
"""
import json
import logging

log = logging.getLogger(__name__)

_cache: dict = {}
CACHE_MAX = 512

_TABLE_OK: bool | None = None


def _table_exists(conn) -> bool:
    """Cached probe — the table is absent until the profiler has been run."""
    global _TABLE_OK
    if _TABLE_OK is None:
        try:
            _TABLE_OK = bool(conn.execute(
                "SELECT 1 FROM information_schema.tables "
                "WHERE table_name = 'dimension_structure'").fetchone())
        except Exception:
            _TABLE_OK = False
    return _TABLE_OK


def load(conn, matrix_code: str) -> dict:
    """{dim_column: structure} for one dataset. Empty dict when unprofiled."""
    hit = _cache.get(matrix_code)
    if hit is not None:
        return hit

    out: dict = {}
    if _table_exists(conn):
        try:
            rows = conn.execute("""
                SELECT dim_column, levels, default_level, n_levels,
                       aggregate_value, aggregate_verified, additive, nests_in,
                       discrimination, dominance, confidence, source
                FROM dimension_structure WHERE matrix_code = ?
            """, [matrix_code]).fetchall()
        except Exception as e:            # table dropped mid-flight, bad JSON…
            log.warning("dimension_structure read failed for %s: %s", matrix_code, e)
            rows = []
        for (col, levels_json, default_level, n_levels, agg, agg_ok, additive,
             nests_in, disc, dom, confidence, source) in rows:
            try:
                levels = json.loads(levels_json) if levels_json else []
            except (TypeError, json.JSONDecodeError):
                levels = []
            out[col] = {
                'levels': levels,
                'default_level': default_level,
                'n_levels': n_levels or 0,
                'aggregate_value': agg if agg_ok else None,
                'additive': additive,
                'nests_in': nests_in,
                'discrimination': disc,
                'dominance': dom,
                'confidence': confidence,
                'source': source,
            }

    if len(_cache) > CACHE_MAX:
        _cache.clear()
    _cache[matrix_code] = out
    return out


def _verified_levels(struct: dict, col: str) -> list:
    """Levels only when the data confirmed them — a 'proposed' partition must
    never change what a chart shows."""
    s = (struct or {}).get(col)
    if not s or s.get('confidence') != 'verified':
        return []
    return [l for l in s.get('levels', []) if l.get('verified')]


def is_multi_level(struct: dict, col: str) -> bool:
    return len(_verified_levels(struct, col)) >= 2


def level_members(struct: dict, col: str, level_id: str | None = None) -> list | None:
    """Data values of one level — the default level unless another is named.

    A single verified level is still a restriction worth applying: ART101C's
    category dim has one honest partition (5 top-level types) plus three
    options that drill into just one of them, and summing all eight
    overcounts by 22%.

    None means "no verified partition": the caller should leave the dimension
    alone rather than inventing a restriction.
    """
    levels = _verified_levels(struct, col)
    if not levels:
        return None
    wanted = level_id or (struct[col].get('default_level'))
    lvl = next((l for l in levels if l.get('level_id') == wanted), None)
    if lvl is None:
        lvl = min(levels, key=lambda l: len(l.get('members') or []))
    members = [str(m) for m in (lvl.get('members') or [])]
    return members or None


def level_choices(struct: dict, col: str) -> list:
    """Level switcher options: [{level_id, name, n}], coarsest first.
    Empty when the dimension has nothing to switch between."""
    levels = _verified_levels(struct, col)
    if len(levels) < 2:
        return []
    ordered = sorted(levels, key=lambda l: len(l.get('members') or []))
    return [{'level_id': l['level_id'], 'name': l.get('name') or l['level_id'],
             'n': len(l.get('members') or [])} for l in ordered]


def aggregate_value(struct: dict, col: str) -> str | None:
    """The verified roll-up option's data value, or None."""
    s = (struct or {}).get(col)
    return s.get('aggregate_value') if s else None


def additive(struct: dict, col: str) -> bool | None:
    """True/False when verified, None when undecidable (caller keeps its
    unit-type heuristic)."""
    s = (struct or {}).get(col)
    return s.get('additive') if s else None


def nests_in(struct: dict, col: str) -> str | None:
    s = (struct or {}).get(col)
    return s.get('nests_in') if s else None


def discrimination(struct: dict, col: str) -> float | None:
    """Coefficient of variation across the default level's options.

    Near zero means splitting by this dimension draws lines on top of each
    other — POP107D's SEX sits at 0.02.
    """
    s = (struct or {}).get(col)
    return s.get('discrimination') if s else None
