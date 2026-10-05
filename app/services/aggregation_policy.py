"""Shared aggregation decision (FIX-02).

One place that answers: *may these rows be combined into one number, and how?*
Composer tiles, insights KPIs and curated headlines all call `decide()` so the
same slice gets the same verdict everywhere. The module is pure/semantic — it
never executes SQL; callers pass in what they already know (dimension metadata,
the data-grounded `effective` option lists, the dimension_structure dict) and
get back a decision they apply to their own query.

Outcomes (`AggregationDecision.outcome`)
    valid_total    every collapsed dimension is pinned to a real aggregate row or
                   summed over exactly one verified/declared disjoint partition.
    valid_slice    a legitimate but partial number: some dimension is pinned to
                   a non-aggregate option, or the caller chose an explicit set.
    approximation  unweighted mean of non-additive values, only when the caller
                   passed allow_approximation=True. Never a "total".
    unavailable    uncertainty never becomes a total: see `reason`.

Reasons (`reason`, machine-readable)
    unverified_structure    overlap-prone dimension with no verified structure
    overlapping_levels      options span several grains/levels (age bands+single
                            years, counties+regions) and no single level chosen
    contains_aggregate      a Total-like option sits next to its parts, unpinned
    label_hierarchy         indentation / "- total" label-encoded tree, unpinned
    non_additive_measure    rate/%/ratio/index/average collapsed without weights
                            (see also missing_weights)
    missing_weights         same, and no aligned weights supplied
    mixed_units             unit dimension left with several options
    slice_value_missing     a requested filter value is not in the data
    declared_partition_invalid  curated partition has total-like/tree labels or
                            a non-additive measure
    ambiguous_slice         (headlines) more rows than the declared method allows
    no_data                 (headlines) slice returned nothing
    comparator_missing / comparator_zero   (changes) no usable comparison base
    arbitrary_pin           (insights) the composer had to hold a dimension at one
                            non-aggregate option, so the number is a slice, not
                            the dataset

Warnings (`warnings[].code`, non-blocking): mixed_grain_on_axis (an axis spans
several grains and none was chosen), time_collapsed (api_mode: an unfiltered
multi-period time dim is neither grouped nor pinned, so values sum across periods).

Methods (`method`): aggregate_row, sum_partition, single_row, weighted_mean,
unweighted_mean, none.
Verification (`verification`): verified (dimension_structure), curated (declared
in headline_config), profile_flat (profiler found a flat dim), metadata (parsed
geo level / age ranges / sex / residence), label (Total-like label only),
user_selected, weighted, unverified.

Provenance contract (attached by consumers under the key ``provenance``; FIX-06,
FIX-07 and FIX-08 consume these exact names — see `provenance()`):
    source_code      dataset/matrix code the number comes from
    period           observation period of the headline value (str) or None
    unit             unit label (str) or None
    filters          {column: [data values]} actually applied (caller filters +
                     pins/levels the policy required)
    levels           {column: level_id} for dimensions restricted to a level
    method           one of the methods above
    verification     one of the verification values above (weakest dimension)
    approximation    bool — True only for unweighted_mean
    outcome          valid_total | valid_slice | approximation | unavailable
    reason           reason code or None
    comparison       None or {basis, from_period, to_period, unit, status,
                     reason} — basis is yoy | qoq | mom | previous_period |
                     since_first (overall change since the first period);
                     unit is percent | points; status ok | unavailable
    dimensions       [{column, treatment, verification}] per-dimension audit
                     (treatment: grouped, pinned_aggregate, pinned_value,
                     level, partition, explicit_set, unit_pinned, time, ...)
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field

from app.services import dimension_structure as dstruct
from app.services.chart_selector import TOTAL_RE

# --- outcomes / enums --------------------------------------------------------
VALID_TOTAL = 'valid_total'
VALID_SLICE = 'valid_slice'
APPROXIMATION = 'approximation'
UNAVAILABLE = 'unavailable'

# --- the one non-additive unit policy ---------------------------------------
# Means, shares, rates, base-100 indices; currency datasets are predominantly
# per-capita/monthly averages in TEMPO, so currency is non-additive unless the
# indicator semantics say otherwise (classify_measure).
NON_ADDITIVE_UNIT_TYPES = frozenset(
    {'currency', 'percentage', 'rate', 'ratio', 'index', 'time_unit'})

# Unit types whose change is a difference in points, not a relative percent.
POINT_CHANGE_UNIT_TYPES = frozenset({'percentage', 'rate', 'ratio'})

_TOTAL_SUFFIX_RE = re.compile(r'-\s*total\s*$', re.I)

# Indicator semantics (Romanian, accent-stripped as in TEMPO names).
_NON_ADD_TEXT_RE = re.compile(
    r'\b(medi[eiu]\w*|per capita|pe locuitor|pe cap de|pret\w*|tarif\w*|'
    r'castig\w*|salari\w*|indic\w*|rata|raport|procent\w*|index|'
    r'valoare unitara|valori unitare|la 1000|la 100)\b', re.I)
_ADD_TEXT_RE = re.compile(
    r'\b(cifra de afaceri|valoarea\s+(?:totala|productiei|exporturilor|'
    r'importurilor)|investiti\w*|venituri\w*|cheltuieli\w*|export\w*|import\w*|'
    r'productia|valoare adaugata|subventi\w*|impozit\w*)\b', re.I)


def _fold(text: str) -> str:
    """Lower-case, accent-stripped text (the indicator regexes are accent-free)."""
    if not text:
        return ''
    return ''.join(c for c in unicodedata.normalize('NFKD', str(text))
                   if not unicodedata.combining(c)).lower()


def is_non_additive_unit(unit_type: str | None) -> bool:
    return (unit_type or '') in NON_ADDITIVE_UNIT_TYPES


def classify_measure(unit_type: str | None, text: str = '',
                     struct_additive: bool | None = None) -> str:
    """'additive' | 'non_additive' for the *indicator*, not just its unit label.

    A verified `additive` flag from the profiler wins. Currency amounts are
    additive only when the indicator text says so ("cifra de afaceri",
    "investitii") and nothing in it says average/price/wage; otherwise they
    stay conservative. Other unit types follow NON_ADDITIVE_UNIT_TYPES.
    """
    if struct_additive is not None:
        return 'additive' if struct_additive else 'non_additive'
    ut = unit_type or ''
    if ut not in NON_ADDITIVE_UNIT_TYPES:
        return 'additive'
    text = _fold(text)
    if ut == 'currency' and text:
        if _NON_ADD_TEXT_RE.search(text):
            return 'non_additive'
        if _ADD_TEXT_RE.search(text):
            return 'additive'
    return 'non_additive'


def dataset_measure(unit_type: str | None, text: str = '',
                    struct: dict | None = None) -> str:
    """Dataset-level 'additive' | 'non_additive' for every consumer.

    `text` is the dataset name (+ definition). A verified per-dimension
    `additive` flag from dimension_structure wins (any False -> non_additive;
    otherwise at least one True -> additive); else classify_measure decides
    from the unit type and indicator wording. Composer, insights, grouped API
    queries and the Ask agent all call this, so they agree.
    """
    flags = [s.get('additive') for s in (struct or {}).values()
             if isinstance(s, dict) and s.get('additive') is not None]
    verified = (False if flags and not all(flags)
                else True if flags else None)
    return classify_measure(unit_type, text, verified)


# --- pure arithmetic helpers -------------------------------------------------

def weighted_mean(pairs) -> float | None:
    """sum(v*w)/sum(w) over (value, weight) pairs; None if weights are unusable."""
    pairs = [(v, w) for v, w in pairs if v is not None and w is not None]
    if not pairs:
        return None
    tw = sum(w for _, w in pairs)
    if not tw or tw <= 0 or any(w < 0 for _, w in pairs):
        return None
    return sum(v * w for v, w in pairs) / tw


def combine(decision: 'AggregationDecision', values, weights=None):
    """Apply a decision's method to already-selected slice values."""
    vals = [v for v in values if v is not None]
    if decision.outcome == UNAVAILABLE or not vals:
        return None
    m = decision.method
    if m in ('aggregate_row', 'single_row'):
        return vals[0] if len(vals) == 1 else None
    if m == 'sum_partition':
        return sum(vals)
    if m == 'weighted_mean':
        return weighted_mean(list(zip(values, weights or [])))
    if m == 'unweighted_mean':
        return sum(vals) / len(vals)
    return None


# --- change computation ------------------------------------------------------
_PERIOD_RE = re.compile(r'^(\d{4})(-.+)?$')


def _prev_year_period(latest: str) -> str | None:
    m = _PERIOD_RE.match(str(latest).strip())
    if not m or not m.group(2):
        return None
    return f"{int(m.group(1)) - 1}{m.group(2)}"


def compute_change(series, unit: str = 'percent', prefer_yoy: bool = True) -> dict:
    """Change of the latest point against its declared comparison base.

    `series` is [(period, value)] oldest to newest. Sub-annual data compares
    with the same sub-period a year earlier when available (basis yoy);
    otherwise the previous point (qoq/mom/previous_period; annual data is yoy).
    `unit` 'percent' = relative change, 'points' = value difference.
    Zero/missing comparators return status 'unavailable' with a reason —
    never a division error and never a fabricated zero.
    """
    pts = [(str(p), v) for p, v in series if p is not None and v is not None]
    if len(pts) < 2:
        return _change_unavailable('comparator_missing', unit)
    latest_p, latest_v = pts[-1]
    target = _prev_year_period(latest_p) if prefer_yoy else None
    base = next(((p, v) for p, v in pts if p == target), None) if target else None
    if base:
        basis = 'yoy'
    else:
        base = pts[-2]
        m = _PERIOD_RE.match(latest_p)
        sub = m.group(2) if m else None
        annual_gap = (m and not sub and int(m.group(1)) - int(base[0][:4]) != 1)
        basis = ('previous_period' if annual_gap else
                 'yoy' if m and not sub else
                 'qoq' if sub and 'Q' in sub.upper() else
                 'mom' if sub else 'previous_period')
    return compute_change_against(latest_p, latest_v, base[0], base[1], basis, unit)


def compute_change_against(latest_p, latest_v, base_p, base_v, basis: str,
                           unit: str = 'percent') -> dict:
    if base_v is None or latest_v is None:
        return _change_unavailable('comparator_missing', unit, basis)
    if unit == 'points':
        val = round(latest_v - base_v, 2)
    else:
        if base_v == 0:
            return _change_unavailable('comparator_zero', unit, basis)
        val = round((latest_v - base_v) / abs(base_v) * 100, 1)
    return {'status': 'ok', 'reason': None, 'value': val, 'unit': unit,
            'basis': basis, 'from_period': str(base_p), 'to_period': str(latest_p)}


def _change_unavailable(reason, unit, basis=None):
    return {'status': 'unavailable', 'reason': reason, 'value': None,
            'unit': unit, 'basis': basis, 'from_period': None, 'to_period': None}


# --- structure probes (pure) -------------------------------------------------

def label_hierarchy_cues(labels) -> bool:
    """Indentation or "- total" suffixes: a tree encoded in the labels."""
    labels = [str(l or '') for l in labels]
    return (any(l != l.lstrip() for l in labels)
            or any(_TOTAL_SUFFIX_RE.search(l.strip()) for l in labels))


def age_ranges_overlap(options) -> bool | None:
    """True/False from parsed age_min/age_max; None when any option lacks them."""
    spans = []
    for o in options:
        p = o.get('parsed') or {}
        lo, hi = p.get('age_min'), p.get('age_max')
        if lo is None and hi is None:
            return None
        spans.append((lo if lo is not None else 0,
                      hi if hi is not None else 10 ** 6))
    spans.sort()
    return any(spans[i][1] >= spans[i + 1][0] for i in range(len(spans) - 1))


def _norm(v) -> str:
    return str(v).strip()


def _opt_keys(opt, dv) -> set:
    keys = {_norm(x) for x in (dv, opt.get('label'), opt.get('sdmx_value')) if x is not None}
    return keys


def _is_total_option(dim, opt, dv, struct) -> bool:
    agg = dstruct.aggregate_value(struct, dim['dim_column_name']) if struct else None
    if agg is not None and _norm(agg) in _opt_keys(opt, dv):
        return True
    if dim.get('dim_type') == 'geo' and (opt.get('parsed') or {}).get('geo_level') == 'national':
        return True
    # Language-independent: judge the stored data value, not the display label
    # (labels are translated, so en and ro would otherwise decide differently).
    return bool(TOTAL_RE.match(_norm(dv if dv is not None else (opt.get('label') or ''))))


# --- the decision ------------------------------------------------------------

@dataclass
class WeightSpec:
    """Aligned denominators/weights for a weighted mean (same grain as values)."""
    source_code: str
    aligned: bool = True
    note: str = ''


@dataclass
class AggregationDecision:
    outcome: str = UNAVAILABLE
    reason: str | None = None
    method: str = 'none'
    verification: str = 'unverified'
    approximation: bool = False
    agg_func: str | None = None            # SUM | AVG | WEIGHTED_AVG | None
    effective_filters: dict = field(default_factory=dict)
    levels: dict = field(default_factory=dict)
    dimensions: list = field(default_factory=list)
    warnings: list = field(default_factory=list)
    weights_source: str | None = None
    blocking_dimension: str | None = None

    @property
    def available(self) -> bool:
        return self.outcome != UNAVAILABLE

    def to_dict(self) -> dict:
        return {
            'outcome': self.outcome, 'reason': self.reason,
            'method': self.method, 'verification': self.verification,
            'approximation': self.approximation, 'agg_func': self.agg_func,
            'filters': self.effective_filters, 'levels': self.levels,
            'dimensions': self.dimensions, 'warnings': self.warnings,
            'weights_source': self.weights_source,
            'blocking_dimension': self.blocking_dimension,
        }


# weakest-link ordering for the dataset-level verification
_VERIF_RANK = ['verified', 'curated', 'weighted', 'user_selected', 'profile_flat',
               'metadata', 'label', 'unverified']


def _weakest(verifs) -> str:
    vs = [v for v in verifs if v]
    return max(vs, key=_VERIF_RANK.index) if vs else 'verified'


def _unavailable(reason, col, dims_audit, filters) -> AggregationDecision:
    return AggregationDecision(
        outcome=UNAVAILABLE, reason=reason, blocking_dimension=col,
        dimensions=dims_audit, effective_filters=filters)


def decide(*, dimensions: list, effective: dict, group_by=(), filters=None,
           struct: dict | None = None, unit_type: str | None = None,
           measure: str | None = None, levels: dict | None = None,
           weights: WeightSpec | None = None, allow_approximation: bool = False,
           declared_partitions=None, declared_aggregates=None,
           api_mode: bool = False) -> AggregationDecision:
    """Decide how (and whether) the slice can be reduced to one number per
    group_by cell.

    dimensions   metadata dims ({dim_column_name, dim_type, options[...]}).
    effective    {column: [(option, data_value)]} — data-grounded options (the
                 composer's `_effective`). Dims absent from it use metadata options.
    group_by     axis columns (kept, not collapsed).
    filters      caller filters {column: [data values]}.
    struct       dimension_structure.load() dict (empty/None = unprofiled).
    unit_type    profile.primary_unit_type; `measure` ('additive' |
                 'non_additive', e.g. from classify_measure) overrides it.
    levels       {column: level_id} caller-chosen grains.
    declared_partitions  iterable of columns a curator declares as one complete,
                 disjoint partition (headline_config `sum_over`).
    declared_aggregates  columns whose pinned filter value a curator declares to
                 be a real aggregate row (headline_config `aggregates`).
    api_mode     grouped API / agent queries (FIX-02 phase 2): an axis dim with
                 several verified levels and no caller filter is restricted to
                 its default level (reported in `levels`), and an unfiltered,
                 uncollapsed multi-period time dim is flagged `time_collapsed`
                 (the query would sum across periods).
    """
    struct = struct or {}
    filters = {k: list(v) for k, v in (filters or {}).items()}
    levels = levels or {}
    declared = set(declared_partitions or ())
    declared_agg = set(declared_aggregates or ())
    group_by = set(group_by)
    if measure is None:
        measure = classify_measure(unit_type)
    non_additive = measure == 'non_additive'

    out_filters = dict(filters)
    out_levels: dict = {}
    audit: list = []
    summed = False          # some dim is summed over a partition
    slice_like = False      # something pinned to a non-aggregate / explicit set
    warnings: list = []
    verifs: list = []

    def note(col, treatment, verif=None):
        audit.append({'column': col, 'treatment': treatment, 'verification': verif})
        verifs.append(verif)

    for dim in dimensions:
        col = dim['dim_column_name']
        dtype = dim.get('dim_type')
        eff = effective.get(col)
        if eff is None:
            eff = [(o, None) for o in dim.get('options', [])]
        if dtype == 'time':
            if api_mode and col not in group_by and not filters.get(col) \
                    and len(eff) > 1:
                warnings.append({'column': col, 'code': 'time_collapsed'})
            note(col, 'time')
            continue
        if col in group_by:
            _axis_checks(dim, eff, struct, filters.get(col), warnings)
            if api_mode and not filters.get(col):
                members = _axis_level_members(struct, col, eff, levels.get(col))
                if members:
                    out_filters[col] = members
                    out_levels[col] = levels.get(col) or struct[col].get('default_level')
                    warnings[:] = [w for w in warnings if not (
                        w.get('column') == col and w.get('code') == 'mixed_grain_on_axis')]
            note(col, 'grouped')
            continue
        sel = filters.get(col)
        if len(eff) <= 1 and not sel:
            note(col, 'singleton', 'verified')
            continue

        # ---- unit dimension: never summed across units ----
        if dtype == 'unit' or col == 'UNIT_MEASURE':
            if sel and len(_match(eff, sel)) == 1:
                note(col, 'unit_pinned', 'user_selected')
                continue
            return _unavailable('mixed_units', col, audit + [
                {'column': col, 'treatment': 'unit_unpinned', 'verification': None}],
                out_filters)

        # ---- caller selected something ----
        if sel:
            matched = _match(eff, sel)
            if not matched:
                return _unavailable('slice_value_missing', col, audit, out_filters)
            if len(matched) == 1:
                o, dv = matched[0]
                if col in declared_agg:
                    note(col, 'pinned_aggregate', 'curated')
                elif _is_total_option(dim, o, dv, struct):
                    note(col, 'pinned_aggregate', _total_verif(dim, struct))
                else:
                    slice_like = True
                    note(col, 'pinned_value', 'user_selected')
                continue
            if _equals_level(struct, col, matched):
                # exactly one verified level: a complete partition, not a slice
                summed = True
                out_levels[col] = _applied_level(struct, col, sel)
                note(col, 'level', 'verified')
                continue
            bad = _explicit_set_problem(dim, matched, struct)
            if bad:
                return _unavailable(bad, col, audit, out_filters)
            summed = True
            slice_like = True
            note(col, 'explicit_set', 'user_selected')
            continue

        # ---- unfiltered, several options: needs structure ----
        total = next(((o, dv) for o, dv in eff
                      if _is_total_option(dim, o, dv, struct)), None)
        if total is not None:
            o, dv = total
            out_filters[col] = [dv if dv is not None else (o.get('label') or '')]
            note(col, 'pinned_aggregate', _total_verif(dim, struct))
            continue

        verified = dstruct._verified_levels(struct, col)
        if verified:
            members = dstruct.level_members(struct, col, levels.get(col))
            present = {dv for _, dv in eff if dv is not None}
            if members and present:
                members = [m for m in members if m in present]
            if members:
                out_filters[col] = members
                out_levels[col] = levels.get(col) or struct[col].get('default_level')
                summed = True
                note(col, 'level', 'verified')
                continue
            return _unavailable('overlapping_levels', col, audit, out_filters)

        if col in declared:
            labels = [dv if dv is not None else (o.get('label') or '') for o, dv in eff]
            if non_additive or label_hierarchy_cues(labels) \
                    or any(TOTAL_RE.match(_norm(l)) for l in labels):
                return _unavailable('declared_partition_invalid', col, audit, out_filters)
            summed = True
            note(col, 'partition', 'curated')
            continue

        verdict = _unprofiled_partition(dim, eff, struct)
        if isinstance(verdict, str) and verdict.startswith('!'):
            return _unavailable(verdict[1:], col, audit, out_filters)
        summed = True
        note(col, 'partition', verdict)

    verification = _weakest(verifs)

    # ---- measure semantics ----
    if summed and non_additive:
        if weights is not None and weights.aligned:
            return AggregationDecision(
                outcome=VALID_SLICE if slice_like else VALID_TOTAL,
                method='weighted_mean', verification='weighted',
                agg_func='WEIGHTED_AVG', effective_filters=out_filters,
                levels=out_levels, dimensions=audit, warnings=warnings,
                weights_source=weights.source_code)
        if allow_approximation:
            return AggregationDecision(
                outcome=APPROXIMATION, reason='missing_weights',
                method='unweighted_mean', verification=verification,
                approximation=True, agg_func='AVG',
                effective_filters=out_filters, levels=out_levels,
                dimensions=audit, warnings=warnings)
        return _unavailable('missing_weights', None, audit, out_filters)

    if summed:
        method = 'sum_partition'
    elif slice_like:
        method = 'single_row'
    else:
        method = 'aggregate_row'
    return AggregationDecision(
        outcome=VALID_SLICE if slice_like else VALID_TOTAL,
        method=method, verification=verification, agg_func='SUM',
        effective_filters=out_filters, levels=out_levels,
        dimensions=audit, warnings=warnings)


# --- decide() internals ------------------------------------------------------

def _match(eff, values):
    want = {_norm(v) for v in values}
    return [(o, dv) for o, dv in eff if _opt_keys(o, dv) & want]


def _total_verif(dim, struct) -> str:
    agg = dstruct.aggregate_value(struct, dim['dim_column_name']) if struct else None
    return 'verified' if agg is not None else 'label'


def _equals_level(struct, col, matched) -> bool:
    got = {_norm(dv if dv is not None else o.get('label')) for o, dv in matched}
    for lvl in dstruct._verified_levels(struct, col):
        if got == {_norm(m) for m in (lvl.get('members') or [])}:
            return True
    return False


def _applied_level(struct, col, applied):
    got = {_norm(m) for m in applied}
    for lvl in dstruct._verified_levels(struct, col):
        if got == {_norm(m) for m in (lvl.get('members') or [])}:
            return lvl.get('level_id')
    return None


def _explicit_set_problem(dim, matched, struct) -> str | None:
    col = dim['dim_column_name']
    if any(_is_total_option(dim, o, dv, struct) for o, dv in matched):
        return 'contains_aggregate'
    verified = dstruct._verified_levels(struct, col)
    if len(verified) >= 2:
        keys = [{_norm(dv if dv is not None else o.get('label')) for o, dv in matched}]
        hit = [l for l in verified
               if keys[0] & {_norm(m) for m in (l.get('members') or [])}]
        if len(hit) >= 2:
            return 'overlapping_levels'
    return _metadata_overlap(dim, [o for o, _ in matched])


def _metadata_overlap(dim, options) -> str | None:
    dtype = dim.get('dim_type')
    if dtype == 'geo':
        lv = {(o.get('parsed') or {}).get('geo_level') for o in options}
        lv.discard(None)
        lv.discard('national')
        if len(lv) >= 2:
            return 'overlapping_levels'
    elif dtype == 'age':
        if age_ranges_overlap(options):
            return 'overlapping_levels'
    return None


def _axis_checks(dim, eff, struct, sel, warnings):
    """Axis dims are kept, not summed; mixed grains are flagged (enforced for
    grouped API queries in phase 2)."""
    col = dim['dim_column_name']
    opts = [o for o, dv in (_match(eff, sel) if sel else eff)]
    if not sel and len(dstruct._verified_levels(struct, col)) >= 2:
        warnings.append({'column': col, 'code': 'mixed_grain_on_axis'})
    elif _metadata_overlap(dim, opts):
        warnings.append({'column': col, 'code': 'mixed_grain_on_axis'})


def _axis_level_members(struct, col, eff, level_id):
    """Members of the chosen/default verified level for an axis dim that spans
    several verified levels, restricted to values present in the data."""
    if len(dstruct._verified_levels(struct, col)) < 2:
        return None
    members = dstruct.level_members(struct, col, level_id)
    present = {dv for _, dv in eff if dv is not None}
    if members and present:
        members = [m for m in members if m in present]
    return members or None


def _unprofiled_partition(dim, eff, struct):
    """Verdict for an unfiltered, un-pinned, multi-option dim with no verified
    level. Returns a verification label (partition accepted) or '!reason'."""
    col = dim['dim_column_name']
    dtype = dim.get('dim_type')
    opts = [o for o, _ in eff]
    labels = [dv if dv is not None else (o.get('label') or '') for o, dv in eff]
    prof = (struct or {}).get(col)

    ov = _metadata_overlap(dim, opts)
    if ov:
        return '!' + ov
    if dtype == 'geo':
        lv = {(o.get('parsed') or {}).get('geo_level') for o in opts}
        if None not in lv and len(lv) == 1:
            return 'profile_flat' if prof and prof.get('confidence') == 'flat' else 'metadata'
    elif dtype == 'age':
        if age_ranges_overlap(opts) is False:
            return 'profile_flat' if prof and prof.get('confidence') == 'flat' else 'metadata'
    elif dtype in ('gender', 'residence') and not label_hierarchy_cues(labels):
        return 'metadata'

    if label_hierarchy_cues(labels):
        return '!label_hierarchy'
    if prof and prof.get('confidence') == 'flat':
        return 'profile_flat'   # profiler examined it and found no nesting
    return '!unverified_structure'


# --- provenance --------------------------------------------------------------

def comparison_of(change: dict | None) -> dict | None:
    """provenance.comparison: a change dict without its value."""
    if not change:
        return None
    return {k: change.get(k) for k in
            ('basis', 'from_period', 'to_period', 'unit', 'status', 'reason')}


def provenance(decision: AggregationDecision, *, source_code: str,
               period=None, unit=None, comparison: dict | None = None) -> dict:
    """The ``provenance`` payload (field names are the cross-package contract)."""
    return {
        'source_code': source_code,
        'period': period,
        'unit': unit,
        'filters': decision.effective_filters,
        'levels': decision.levels,
        'method': decision.method,
        'verification': decision.verification,
        'approximation': decision.approximation,
        'outcome': decision.outcome,
        'reason': decision.reason,
        'comparison': comparison,
        'dimensions': decision.dimensions,
    }
