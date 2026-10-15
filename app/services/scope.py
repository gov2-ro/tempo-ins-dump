"""Shared scope disclosure (AT-01b).

A grouped total can be statistically valid (a disjoint partition, summed once)
and still describe only part of the population: `POP107D_varste_judet` holds
ages 0-84, "85 ani si peste" lives in the `_grupe_` sibling, yet its summed
headline is `valid_total`. Disjointness does not prove exhaustive coverage, so
this module answers the other question, from metadata and the values actually in
the data: *which part of the dimension's domain does this number cover?*

Everything here is pure over the aggregation context `ctx` that
`dataset_meta.get_aggregation_context` returns (`dimensions`, `actual_values`,
`struct`, `measure`, `unit_type`). Nothing mutates `ctx` or a decision (both are
cached and shared). REST `/data` (`data_query.run_query`), the static engine
(`app/static/js/engine/scope.js`, a line-for-line port), the insights KPI and the
dashboards all use these functions, so every surface reports the same scope.
Python is the specification.

Age ranges
    An option's range comes from `parsed.age_min/age_max` (integers). 999 or
    more is the open-ended sentinel ("85 ani si peste"). Only `age_max` missing
    means open-ended; both missing means *unknown*. Ranges are merged as integer
    intervals (adjacent ones join), JSON-shaped as `[lo, hi]` with `hi = null`
    for open-ended.

`dimension_coverage(ctx, column, values=None)`
    `{"kind": "age_range", "covered": [[lo, hi], ...], "domain": [lo, hi],
    "complete": bool}` or None.
    - covered: merged ranges of the options the given data `values` select (all
      must match an option); with `values=None`, of every non-Total value
      present in the data (the Total itself if nothing else is present).
    - domain: the range of the dimension's Total option(s) in metadata (the
      all-ages range), else the hull of all metadata option ranges. `complete`
      means covered contains every interval of that domain.
    - None when the column is not an age dimension, when any included value has
      no parsed range or matches no option, or when the domain cannot be
      established (a Total option without a parsed range). None means *unknown*,
      never "complete".
    Data values are matched to options exactly like the aggregation policy does
    (`dashboard_composer._effective`, normalized sdmx_value/label/data value).

`dataset_restrictions(ctx)`
    One `{"column", "kind", "covered", "domain"}` per age dimension whose
    present data values do not cover its domain (e.g. the single-age children:
    covered [[0, 84]], domain [0, null]). Discovery uses it to label such a
    dataset instead of promoting it as an all-ages population.

`result_scope(ctx, decision, caller_filters, group_by)` - the `scope` of a
grouped (aggregated) result:

    {"domain_complete": true | false | null,
     "restrictions": [{"column": "AGE", "kind": "age_range", "covered": [[0, 84]],
                       "domain": [0, null], "requested": false}]}

    - Covered values of a dimension: the decision's effective filter values for
      that column when present, else every present non-Total data value.
    - `restrictions` lists every age dimension, collapsed or grouped, whose
      covered intervals do not contain its domain. `requested` is true when the
      caller filtered that column explicitly: the asked scope, still disclosed.
    - `domain_complete`, relative to the requested scope:
        false  some restriction is not requested;
        else from the decision's audit (`decision["dimensions"]`):
          time, grouped, singleton, unit_pinned, pinned_value, explicit_set
                                         neutral (the caller's own choices)
          pinned_aggregate               complete
          level + verified               complete
          partition + curated/verified   complete
          partition + any weaker verification (profile_flat, metadata, label,
          unverified, none)              unknown, unless `dimension_coverage`
                                         proves the age dimension fully covered
          anything else                  unknown
        any unknown -> null; otherwise true.
      Only age dimensions are examined for numeric coverage; other dimensions
      count through their treatment above.
    - Returns None for no decision or an `unavailable` one: a refused
      aggregation has no result to disclose a scope for.
"""
from __future__ import annotations

import math

from app.services.aggregation_policy import _is_total_option, _norm, _opt_keys
from app.services.dashboard_composer import _effective

OPEN_AGE = 999            # parsed age_max >= this means "and over"
_INF = math.inf

# decision["dimensions"] treatments that never widen or narrow the domain
# beyond what the caller asked for
_NEUTRAL = frozenset({'time', 'grouped', 'singleton', 'unit_pinned',
                      'pinned_value', 'explicit_set'})
_STRONG = frozenset({'curated', 'verified'})


# --- age ranges ----------------------------------------------------------------

def _age_range(opt: dict):
    """(lo, hi) of an option, hi = inf when open-ended; None when unparsed."""
    p = opt.get('parsed') or {}
    lo, hi = p.get('age_min'), p.get('age_max')
    if lo is None and hi is None:
        return None
    lo = 0 if lo is None else lo
    hi = _INF if hi is None or hi >= OPEN_AGE else hi
    return None if hi < lo else (lo, hi)


def _merge(ranges) -> list:
    """Merge integer intervals; adjacent ones (hi + 1 == next lo) join."""
    out: list = []
    for lo, hi in sorted(ranges):
        if out and lo <= out[-1][1] + 1:
            out[-1] = (out[-1][0], max(out[-1][1], hi))
        else:
            out.append((lo, hi))
    return out


def _json(interval) -> list:
    lo, hi = interval
    return [lo, None if hi == _INF else hi]


def _contains(covered, domain) -> bool:
    """Every domain interval sits inside one (maximal, merged) covered interval."""
    return all(any(clo <= dlo and chi >= dhi for clo, chi in covered)
               for dlo, dhi in domain)


def _age_dims(ctx) -> list:
    seen, out = set(), []
    for d in (ctx or {}).get('dimensions') or ():
        col = d.get('dim_column_name')
        if d.get('dim_type') == 'age' and col not in seen:
            seen.add(col)
            out.append(d)
    return out


def _domain(dim, struct):
    """Merged intervals of the dimension's domain, or None when unknown."""
    opts = dim.get('options') or []
    totals = [o for o in opts if _is_total_option(dim, o, None, struct)]
    ranges = []
    for o in totals or opts:
        r = _age_range(o)
        if r is None:
            if totals:
                return None           # a Total of unknown range: no domain
            continue                  # an unparsed plain option adds no range
        ranges.append(r)
    return _merge(ranges) or None


# --- public API -------------------------------------------------------------------

def dimension_coverage(ctx, column, values=None):
    """Age coverage of one dimension (see module docstring); None = unknown."""
    dim = next((d for d in _age_dims(ctx) if d['dim_column_name'] == column), None)
    if dim is None:
        return None
    struct = ctx.get('struct') or {}
    eff = _effective(dim, ctx.get('actual_values'))
    if values is None:
        parts = [(o, dv) for o, dv in eff if not _is_total_option(dim, o, dv, struct)]
        chosen = parts or eff
    else:
        index: dict = {}
        for o, dv in eff:
            for k in _opt_keys(o, dv):
                index.setdefault(k, []).append(o)
        chosen, seen = [], set()
        for v in values:
            hits = index.get(_norm(v))
            if not hits:
                return None           # a value matching no option has no range
            for o in hits:
                if id(o) not in seen:
                    seen.add(id(o))
                    chosen.append((o, None))
    ranges = []
    for o, _ in chosen:
        r = _age_range(o)
        if r is None:
            return None
        ranges.append(r)
    domain = _domain(dim, struct)
    if not ranges or domain is None:
        return None
    covered = _merge(ranges)
    return {'kind': 'age_range',
            'covered': [_json(c) for c in covered],
            'domain': _json((domain[0][0], domain[-1][1])),
            'complete': _contains(covered, domain)}


def dataset_restrictions(ctx) -> list:
    """Age dimensions whose present data values leave part of the domain out."""
    out = []
    for dim in _age_dims(ctx):
        col = dim['dim_column_name']
        cov = dimension_coverage(ctx, col)
        if cov is not None and not cov['complete']:
            out.append({'column': col, 'kind': cov['kind'],
                        'covered': cov['covered'], 'domain': cov['domain']})
    return out


def result_scope(ctx, decision, caller_filters, group_by):
    """The REST `scope` of one grouped result, or None without an available decision."""
    if not decision or decision.get('outcome') == 'unavailable':
        return None
    flt = decision.get('filters') or {}
    caller = caller_filters or {}
    coverage, restrictions = {}, []
    for dim in _age_dims(ctx):
        col = dim['dim_column_name']
        chosen = flt.get(col)
        cov = dimension_coverage(ctx, col, list(chosen) if chosen else None)
        coverage[col] = cov
        if cov is not None and not cov['complete']:
            restrictions.append({'column': col, 'kind': cov['kind'],
                                 'covered': cov['covered'], 'domain': cov['domain'],
                                 'requested': bool(caller.get(col))})
    if any(not r['requested'] for r in restrictions):
        complete = False
    else:
        complete = True
        for entry in decision.get('dimensions') or ():
            state = _state(entry, coverage.get(entry.get('column')))
            if state == 'unknown':
                complete = None
                break
    return {'domain_complete': complete, 'restrictions': restrictions}


def _state(entry, cov) -> str:
    """'complete' | 'neutral' | 'unknown' for one decision audit entry."""
    treatment, verification = entry.get('treatment'), entry.get('verification')
    if treatment in _NEUTRAL:
        return 'neutral'
    if treatment == 'pinned_aggregate':
        return 'complete'
    if treatment == 'level':
        return 'complete' if verification == 'verified' else 'unknown'
    if treatment == 'partition':
        if verification in _STRONG or (cov is not None and cov['complete']):
            return 'complete'
    return 'unknown'
