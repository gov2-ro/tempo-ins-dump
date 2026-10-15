"""Per-entity change between exact annual endpoints (AT-01e).

`compute()` is the pure calculator; `run()` is the one runner the `compare_periods`
tool and the evidence route share. Every data selection goes through
`data_query.run_query`, so the aggregation policy and the grain gate decide
whether and how collapsed dimensions are combined; nothing here chooses SUM/AVG,
sums raw rows, fills a gap with zero or substitutes a nearby year.

Rules (docs/plans/ask-and-public-mcp/01-analytical-tools.md section 5):

  * additive measures and exact annual periods only; anything else is refused
    with a specific reason
  * the entity key is the full key (a locality needs its county); display labels
    never merge entities, and a name that occurs under several parents is refused
  * at most one finite value per (full key, year); a repeated key is refused even
    when the values agree
  * absolute = to - from; percent = 100 * absolute / from only when from > 0
  * ranks are ordinal over EVERY eligible entity (ties: full key ascending);
    top_k only limits what is returned
"""
from __future__ import annotations

import math
import re
import uuid

from app.services import generation
from app.services.tools import contract
from app.services.tools.contract import ToolContext, ToolFailure, recovery

MAX_PERIODS = 500           # distinct period labels an annual series may have
EXCLUDED_SAMPLE = 20        # exclusions the tool returns per interval (the bundle has all)

# reasons an entity is not ranked in an interval
NO_OBSERVATION = "no_observation"        # no row for that entity and year
VALUE_MISSING = "value_missing"          # the source row is NULL (suppressed / not available)
VALUE_NOT_FINITE = "value_not_finite"
ZERO_BASELINE = "zero_baseline"          # percent ranking only: from == 0
NONPOSITIVE_BASELINE = "nonpositive_baseline"   # percent ranking only: from < 0
AGGREGATE_ROW = "aggregate_row"          # a total/national row among its own parts


# ------------------------------------------------------------------ pure calculator

def _skey(key: tuple) -> tuple:
    """Sort key of an entity: the full key as strings, ascending."""
    return tuple("" if v is None else str(v) for v in key)


def build_endpoint_table(rows) -> dict:
    """{(key, year): value} from (key, year, value) rows. A repeated (key, year)
    is refused even when the values agree: two rows would double a sum."""
    table: dict = {}
    for key, year, value in rows:
        k = (tuple(key), str(year))
        if k in table:
            raise ToolFailure(
                "unavailable", "duplicate_keys",
                "More than one value for the same entity and year came back from the source "
                "query, so no single endpoint value exists. No change was computed.",
                recovery=[recovery("narrow", "Pin the dimension that repeats the key with "
                                             "filters, or compare a different dataset.")])
        table[k] = value
    return table


def _endpoint(table: dict, key: tuple, year: str):
    """(problem, value): problem is None for a finite value."""
    if (key, year) not in table:
        return NO_OBSERVATION, None
    v = table[(key, year)]
    if v is None:
        return VALUE_MISSING, None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return VALUE_MISSING, None
    if not math.isfinite(f):
        return VALUE_NOT_FINITE, None
    return None, f


def compute(table: dict, key_cols, intervals, metric: str = "absolute", order: str = "asc",
            aggregate_keys=frozenset()) -> list[dict]:
    """Rank every eligible entity of every interval.

    `table` is {(key tuple, year): value | None}; `intervals` is [(from, to)].
    Returns one dict per interval with the FULL ranked `rows`, every `excluded`
    record, `eligible_count`, `excluded_count` and `exclusion_counts`. Entities
    are every key present in the table at any queried year."""
    entities = sorted({k for k, _ in table}, key=_skey)
    sign = 1 if order == "asc" else -1
    out = []
    for yf, yt in intervals:
        ranked, excluded = [], []
        for key in entities:
            entity = dict(zip(key_cols, key))
            if key in aggregate_keys:
                excluded.append({"entity": entity, "reason": AGGREGATE_ROW, "missing": []})
                continue
            pf, f = _endpoint(table, key, yf)
            pt, t = _endpoint(table, key, yt)
            if pf or pt:
                bad = [(n, p) for n, p in (("from", pf), ("to", pt)) if p]
                excluded.append({"entity": entity, "reason": bad[0][1],
                                 "missing": [n for n, _ in bad],
                                 "endpoint_reasons": {n: p for n, p in bad}})
                continue
            absolute = t - f
            if not math.isfinite(absolute):
                excluded.append({"entity": entity, "reason": VALUE_NOT_FINITE, "missing": [],
                                 "from_value": f, "to_value": t})
                continue
            percent, note = None, None
            if f > 0:
                percent = 100 * absolute / f
                if not math.isfinite(percent):
                    percent, note = None, VALUE_NOT_FINITE
            elif f == 0:
                note = ZERO_BASELINE
            else:
                note = NONPOSITIVE_BASELINE
            if metric == "percent" and percent is None:
                excluded.append({"entity": entity, "reason": note or VALUE_NOT_FINITE,
                                 "missing": [], "from_value": f, "to_value": t,
                                 "absolute": absolute})
                continue
            row = {"entity": entity, "from_value": f, "to_value": t, "absolute": absolute,
                   "percent": percent, "rank": None}
            if note:
                row["percent_note"] = note
            ranked.append((sign * (percent if metric == "percent" else absolute), _skey(key), row))
        ranked.sort(key=lambda x: (x[0], x[1]))
        rows = []
        for i, (_, _, row) in enumerate(ranked, 1):
            row["rank"] = i
            rows.append(row)
        counts: dict = {}
        for e in excluded:
            counts[e["reason"]] = counts.get(e["reason"], 0) + 1
        out.append({"from": yf, "to": yt, "rows": rows, "eligible_count": len(rows),
                    "excluded_count": len(excluded), "excluded": excluded,
                    "exclusion_counts": dict(sorted(counts.items())), "exclusions_truncated": False})
    return out


# ------------------------------------------------------------------ helpers

def _selection(args) -> dict:
    """The normalized compare request (what a citation or link replays)."""
    d = args.model_dump(by_alias=True)
    d.pop("lang", None)
    return {"kind": "period_changes", **d}


def _unavailable(reason, message, *, rec=(), provenance=None, limits=None, warnings=()):
    return ToolFailure("unavailable", reason, message, recovery=list(rec),
                       provenance=provenance, limits=limits, warnings=list(warnings))


def _periods(conn, code: str, time_col: str, ctx: ToolContext) -> tuple[dict, tuple]:
    """{year: actual period value} and (first, last) year, or a refusal."""
    from app.services.data_query import QueryError, dimension_values
    from app.services.recipes import _year
    try:
        out = dimension_values(conn, code, time_col, limit=MAX_PERIODS)
    except QueryError as e:
        raise contract.query_failure(e, ctx, code)
    describe = recovery("tool_call", "Read the dataset's periods and frequency.",
                        "describe_dataset", {"dataset": code, "lang": ctx.lang})
    if out["total"] > MAX_PERIODS:
        raise _unavailable(
            "unsupported_frequency",
            f"{code} has more than {MAX_PERIODS} distinct period labels; only exact annual "
            "periods are supported.", rec=[describe])
    by_year: dict = {}
    other = []
    for v in out["values"]:
        y = _year(v)
        if y is None:
            other.append(str(v))
        else:
            by_year.setdefault(y, []).append(v)
    if other:
        e = ", ".join(repr(x) for x in other[:3])
        raise _unavailable(
            "unsupported_frequency",
            f"{code} has non-annual period values (e.g. {e}); compare_periods supports exact "
            "annual periods only, not monthly, quarterly or mixed series.", rec=[describe])
    multi = [y for y, vs in by_year.items() if len(vs) > 1]
    if multi:
        raise _unavailable(
            "unsupported_frequency",
            f"{code} labels the year {multi[0]} in more than one way ({by_year[multi[0]]}); "
            "the periods cannot be matched exactly.", rec=[describe])
    if not by_year:
        raise _unavailable("period_unavailable", f"{code} has no period values.", rec=[describe])
    years = sorted(by_year)
    return {y: vs[0] for y, vs in by_year.items()}, (years[0], years[-1])


def _key_columns(mctx: dict, requested: list[str]) -> tuple[list[str], list[str]]:
    """(key columns, added parents). A requested geographic column that nests in
    another geographic column which was not requested brings that parent along:
    a locality is identified by county + locality, not by its name."""
    dims = {d["dim_column_name"]: d for d in mctx["dimensions"]}
    struct = mctx.get("struct") or {}
    key = list(requested)
    added: list[str] = []
    changed = True
    while changed:
        changed = False
        for col in list(key):
            parent = (struct.get(col) or {}).get("nests_in")
            if parent and not (parent in dims and dims[parent].get("dim_type") == "geo"
                               and dims[col].get("dim_type") == "geo"):
                parent = None
            if not parent and col == "REF_AREA_2" and "REF_AREA" in dims:
                parent = "REF_AREA"          # the corpus convention: localities sit in counties
            if parent and parent != col and parent not in key:
                key.insert(0, parent)
                added.insert(0, parent)
                changed = True
    return key, added


def _aggregate_value_set(dim: dict, struct: dict) -> set:
    from app.services import dimension_structure as dstruct
    out = set()
    agg = dstruct.aggregate_value(struct, dim["dim_column_name"])
    if agg is not None:
        out.add(str(agg).strip())
    for o in dim.get("options") or []:
        if (o.get("parsed") or {}).get("geo_level") == "national":
            out.update(str(x).strip() for x in (o.get("label"), o.get("sdmx_value")) if x)
    return out


def _aggregate_keys(table: dict, key_cols, mctx: dict) -> frozenset:
    """Entities whose key has a total/national component, but only when ordinary
    entities are present too: ranking a total among its own parts is wrong, while
    an explicit total-only comparison (the caller pinned it) is a valid series."""
    from app.services.chart_selector import TOTAL_RE
    dims = {d["dim_column_name"]: d for d in mctx["dimensions"]}
    struct = mctx.get("struct") or {}
    sets = [_aggregate_value_set(dims[c], struct) if c in dims else set() for c in key_cols]
    keys = {k for k, _ in table}
    flagged = {k for k in keys
               if any(v is not None and (str(v).strip() in s or TOTAL_RE.match(str(v).strip()))
                      for v, s in zip(k, sets))}
    return frozenset(flagged) if flagged and len(flagged) < len(keys) else frozenset()


_NATIVE_TEXT = {
    "overlapping_levels": "{col} mixes levels that overlap (for example counties with regions, "
                          "or single years with age bands); no single total or ranking exists "
                          "until one level is chosen.",
    "unverified_structure": "The structure of {col} is not verified, so the source cannot say how "
                            "its options combine.",
    "contains_aggregate": "{col} contains a total next to its parts; combining them would "
                          "double count.",
    "label_hierarchy": "{col} encodes a hierarchy in its labels; summing it would double count.",
    "declared_partition_invalid": "{col} is not a valid disjoint partition.",
    "source_total_mismatch": "INS's own options of {col} do not add up to INS's total, so the "
                             "dimension is not summed.",
    "mixed_units": "{col} has several units; values in different units are never combined.",
    "slice_value_missing": "A requested value of {col} is not in the data.",
    "conflicting_grain": "The selected rows repeat a full key with different values, so no "
                         "single value exists.",
    "duplicate_keys": "The selected rows repeat a full key, so a sum would count it twice.",
    "grain_unverified": "The grain of the selected rows could not be verified.",
    "schema_mismatch": "The dataset's recorded dimension {col} is not in its data file.",
    "missing_weights": "The measure cannot be combined without weights.",
    "no_aggregation_context": "The dataset's aggregation rules are unavailable.",
}
_PIN = frozenset({"overlapping_levels", "unverified_structure", "contains_aggregate",
                  "label_hierarchy", "declared_partition_invalid", "source_total_mismatch",
                  "mixed_units", "slice_value_missing"})


def _native_refusal(res: dict, code: str, lang: str, prov, limits) -> ToolFailure:
    agg = res.get("aggregation") or {}
    reason = agg.get("reason") or "aggregation_unavailable"
    col = agg.get("blocking_dimension")
    text = _NATIVE_TEXT.get(reason, "The shared aggregation policy refused this selection "
                                    f"({reason}).").format(col=col or "a dimension")
    rec = []
    if reason in _PIN and col:
        rec.append(recovery("tool_call", f"List the actual values of {col}, then pin it to one "
                                         "value or one level with filters.",
                            "find_dimension_values", {"dataset": code, "column": col, "limit": 20}))
    rec.append(recovery("tool_call", "Read the dataset's dimensions, levels and grain status.",
                        "describe_dataset", {"dataset": code, "lang": lang}))
    return _unavailable(reason, f"No change was computed: {text}", rec=rec, provenance=prov,
                        limits=limits)


def _population_note(text: str) -> str | None:
    from app.services.concept_search import fold
    t = fold(text)
    if "populati" not in t:
        return None
    dom = "domicili" in t
    res = "rezident" in t or "stabil" in t
    if dom and res:
        return ("The source text mentions both domicile and resident/usual-residence wording; "
                "check which one this series counts.")
    if dom:
        return "The source definition refers to domicile (domiciliu) population, which is not a count of residents."
    if res:
        return "The source definition refers to resident (usual residence) population."
    return ("The source definition does not say whether it counts domicile or usual residence; "
            "do not read it as a resident count.")


def _warnings(notes: list, facts: dict | None, geo: bool, intervals, counts: dict) -> list:
    out = []
    if counts:
        total = sum(counts.values())
        reasons = ", ".join(f"{r} {n}" for r, n in sorted(counts.items()))
        out.append(contract.warning(
            "entities_excluded",
            f"{total} entity-interval pair(s) were not ranked ({reasons}); they are listed "
            "per interval, never filled with zero."))
    if geo:
        text = ("Stable labels or codes do not prove unchanged territory: boundary changes, mergers "
                "and splits between the endpoint years are not tracked, so a change can reflect "
                "territory as well as real change.")
        pop = _population_note(f"{(facts or {}).get('title') or ''} "
                               f"{(facts or {}).get('definition') or ''}")
        out.append(contract.warning("boundary_continuity_unverified",
                                    f"{text} {pop}" if pop else text))
    spans = [(iv["from"], iv["to"]) for iv in intervals]
    for n in notes:
        if n.get("kind") not in ("series_break", "definition", "coverage"):
            continue
        text = n.get("text") or ""
        code = {"series_break": "series_break", "definition": "definition_note",
                "coverage": "coverage_note"}[n["kind"]]
        if n["kind"] == "series_break":
            between = (n.get("data") or {}).get("between")
            hit = [f"{a}→{b}" for a, b in spans
                   if between and len(between) == 2 and a <= str(between[0]) and str(between[1]) <= b]
            if hit:
                text = f"Inside the compared interval {', '.join(hit)}: {text}"
        out.append(contract.warning(code, text, n.get("id")))
    return out


# ------------------------------------------------------------------ runner

def run(conn, args, lang: str = "ro", *, ctx: ToolContext | None = None) -> dict:
    """Run one compare_periods request against the served corpus.

    `args` is a `schemas.ComparePeriodsArgs`. Returns the full result (every
    ranked row and every exclusion of every interval, the validated endpoint
    table, the source query and its provenance); callers cut it for display.
    Raises `ToolFailure` for a refusal or an error."""
    from app.config import MAX_DATA_ROWS            # call time: tests patch the cap
    from app.services import dataset_meta
    from app.services.concept_search import dataset_facts
    from app.services.data_query import QueryError, run_query
    from app.services.query_builder import resolve_parquet_schema, to_sdmx_name

    code = args.dataset
    if ctx is None:
        ctx = ToolContext(conn=conn, lang=lang, generation=generation.current(),
                          request_id=uuid.uuid4().hex[:12])
    ctx.require_present_generation("compare_periods")
    mctx = dataset_meta.get_aggregation_context(conn, code)
    if mctx is None:
        raise contract.query_failure(QueryError(404, f"Dataset {code} not found"), ctx, code)

    # additive count/amount measures only: no invented rate-change policy
    measure = mctx.get("measure")
    if measure != "additive":
        title = (dataset_facts(conn, code, lang) or {}).get("title") or code
        raise _unavailable(
            "unsupported_measure",
            f"{code} is classified as a {measure or 'non-additive'} measure (unit type "
            f"{mctx.get('unit_type') or 'unknown'}): rates, means, indices and unknown units "
            "are not compared here, because the change of such a value has no single "
            "definition. A reviewed recipe may exist.",
            rec=[recovery("tool_call", "Look for a reviewed recipe or indicator for this measure.",
                          "discover_indicators", {"query": str(title)[:200], "lang": lang})])

    dims = {d["dim_column_name"]: d for d in mctx["dimensions"]}
    time_cols = [c for c, d in dims.items() if d.get("dim_type") == "time"]
    if not time_cols:
        raise _unavailable("unsupported_frequency",
                           f"{code} has no time dimension, so there are no annual endpoints.",
                           rec=[recovery("tool_call", "Read the dataset's dimensions.",
                                         "describe_dataset", {"dataset": code, "lang": lang})])
    time_col = "TIME_PERIOD" if "TIME_PERIOD" in time_cols else time_cols[0]

    schema = resolve_parquet_schema(conn, code)
    for c in args.filters:
        if to_sdmx_name(schema, c) == time_col or c == time_col:
            raise ToolFailure("error", "invalid_input",
                              f"Invalid filters: {c} is the period column; periods come from "
                              "the intervals.")
    for c in args.entity_columns:
        if c == time_col or (c in dims and dims[c].get("dim_type") == "time"):
            raise ToolFailure("error", "invalid_input",
                              f"Invalid entity_columns: {c} is the period column, not an entity.")
        if c not in dims:
            raise contract.query_failure(
                QueryError(400, f"Invalid entity_columns: unknown column {c!r}"), ctx, code)

    years_actual, (first, last) = _periods(conn, code, time_col, ctx)
    wanted = sorted({y for i in args.intervals for y in (i.from_, i.to)})
    absent = [y for y in wanted if y not in years_actual]
    if absent:
        raise _unavailable(
            "period_unavailable",
            f"Year {', '.join(absent)} has no observations in {code}; the data covers {first} to "
            f"{last}. No nearby year was substituted.",
            rec=[recovery("tool_call", f"List the actual values of {time_col}.",
                          "find_dimension_values",
                          {"dataset": code, "column": time_col, "limit": 20})])

    key_cols, added = _key_columns(mctx, list(args.entity_columns))
    filters = {c: list(v) for c, v in args.filters.items()}
    filters[time_col] = [years_actual[y] for y in wanted]
    group_by = key_cols + [time_col]
    source_query = {"dataset": code, "filters": filters, "group_by": group_by,
                    "approximate": False}

    try:
        res = run_query(conn, code, filters, group_by, MAX_DATA_ROWS)
    except QueryError as e:
        raise contract.query_failure(e, ctx, code)

    prov = contract.query_provenance(ctx, code, source_query, res)
    prov["selection"] = _selection(args)
    prov["source_query"] = source_query
    agg = res.get("aggregation") or {}
    if res.get("unavailable"):
        raise _native_refusal(res, code, lang, prov, contract.query_limits(res, 0))
    if res.get("truncated") or res.get("time_windowed") or res.get("partial_period_dropped") \
            is not None:
        raise _unavailable(
            "source_incomplete",
            f"The source query for the endpoint years is larger than the {MAX_DATA_ROWS:,}-row "
            "cap (or was windowed), so the entity set is incomplete. No ranking was computed "
            "from a capped input.",
            rec=[recovery("narrow", "Filter an entity column (for example one county) or pin "
                                    "other dimensions so the endpoint table fits the cap.")],
            provenance=prov, limits=contract.query_limits(res, 0))
    if agg.get("outcome") == "approximation":
        raise _unavailable("unsupported_measure",
                           "An approximate (unweighted) aggregation is not used for period "
                           "changes.", provenance=prov, limits=contract.query_limits(res, 0))
    mixed = [w.get("column") for w in agg.get("warnings") or []
             if w.get("code") == "mixed_grain_on_axis" and w.get("column") in key_cols]
    if mixed:
        col = mixed[0]
        raise _unavailable(
            "overlapping_levels",
            f"{col} mixes levels that overlap (for example counties with regions), so ranking "
            "its values would compare an area with its own parts. Choose one level.",
            rec=[recovery("tool_call", f"List the actual values of {col}, then filter to one "
                                       "level's values.",
                          "find_dimension_values", {"dataset": code, "column": col, "limit": 20}),
                 recovery("tool_call", "Read the dataset's dimensions and levels.",
                          "describe_dataset", {"dataset": code, "lang": lang})],
            provenance=prov, limits=contract.query_limits(res, 0))
    if not res["rows"]:
        missing = ((res.get("selection") or {}).get("missing_values")) or {}
        if missing:
            col, vals = next(iter(missing.items()))
            raise _unavailable(
                "slice_value_missing",
                f"Requested value(s) of {col} are not in the data: "
                f"{', '.join(repr(v) for v in vals[:5])}.",
                rec=[recovery("tool_call", f"List the actual values of {col}.",
                              "find_dimension_values",
                              {"dataset": code, "column": col, "limit": 20})],
                provenance=prov, limits=contract.query_limits(res, 0))
        raise _unavailable("no_eligible_entities",
                           "The selection has no observations at the endpoint years.",
                           provenance=prov, limits=contract.query_limits(res, 0))

    cols = res["columns"]
    try:
        ki = [cols.index(c) for c in key_cols]
        ti = cols.index(time_col)
    except ValueError:
        raise ToolFailure("error", "execution_failed",
                          f"The source query returned an unexpected shape (reference "
                          f"{ctx.request_id}); nothing was computed.")
    year_of = {v: y for y, v in years_actual.items()}
    rows = []
    for r in res["rows"]:
        key = tuple(r[i] for i in ki)
        if any(v is None or str(v).strip() == "" for v in key):
            raise _unavailable(
                "identity_ambiguous",
                "Some rows have an empty component in the entity key, so those entities "
                "cannot be identified.", provenance=prov)
        year = year_of.get(str(r[ti]))
        if year is None:
            raise ToolFailure("error", "execution_failed",
                              f"The source query returned an unexpected period (reference "
                              f"{ctx.request_id}); nothing was computed.")
        rows.append((tuple(str(v) for v in key), year, r[-1]))
    table = build_endpoint_table(rows)

    if added:
        parents: dict = {}
        for key, _ in table:
            parents.setdefault(key[len(added):], set()).add(key[:len(added)])
        clash = sorted(((k, p) for k, p in parents.items() if len(p) > 1), key=lambda x: _skey(x[0]))
        if clash:
            k, p = clash[0]
            ex = ", ".join("/".join(x) for x in sorted(p)[:3])
            fix = None
            cols_fixed = added + list(args.entity_columns)
            if len(cols_fixed) <= 8:
                a = args.model_dump(by_alias=True)
                a["entity_columns"] = cols_fixed
                fix = recovery("tool_call", f"Compare with the full key ({', '.join(cols_fixed)}) "
                                            "so same-named places stay separate.",
                               "compare_periods", a)
            raise _unavailable(
                "identity_ambiguous",
                f"{len(clash)} requested {'/'.join(args.entity_columns)} value(s), e.g. "
                f"{'/'.join(k)!r}, occur under several {', '.join(added)} values ({ex}); a name "
                f"alone does not identify a place. Include {', '.join(added)} in entity_columns.",
                rec=[fix] if fix else [], provenance=prov)

    aggregate_keys = _aggregate_keys(table, key_cols, mctx)
    intervals_in = [(i.from_, i.to) for i in args.intervals]
    intervals = compute(table, key_cols, intervals_in, args.metric, args.order, aggregate_keys)

    src = prov["sources"][0]
    facts = dataset_facts(conn, code, lang)
    unit = src.get("unit")
    pinned = filters.get("UNIT_MEASURE")
    if unit is None and pinned and len(pinned) == 1:
        unit = str(pinned[0])
    counts: dict = {}
    for iv in intervals:
        for r, n in iv["exclusion_counts"].items():
            counts[r] = counts.get(r, 0) + n
    geo = any((dims.get(c) or {}).get("dim_type") == "geo" or c.startswith("REF_AREA")
              for c in key_cols)
    from app.services import dataset_notes
    warnings = _warnings(dataset_notes.for_code(code, lang), facts, geo, intervals, counts)

    scope = prov["scope"]
    if not any(iv["eligible_count"] for iv in intervals):
        status, reason = "unavailable", "no_eligible_entities"
    elif counts or scope.get("domain_complete") is False:
        status = "partial"
        reason = "incomplete_domain" if scope.get("domain_complete") is False else None
    else:
        status, reason = "ok", None

    return {
        "dataset": code, "lang": lang, "args": args.model_dump(by_alias=True),
        "selection": prov["selection"], "time_column": time_col,
        "entity_columns": list(args.entity_columns), "key_columns": key_cols,
        "added_key_columns": added, "metric": args.metric, "order": args.order,
        "top_k": args.top_k, "unit": unit, "intervals": intervals,
        "endpoints": sorted(((k, y, v) for (k, y), v in table.items()),
                            key=lambda x: (_skey(x[0]), x[1])),
        "aggregate_keys": sorted(aggregate_keys, key=_skey),
        "periods": {y: years_actual[y] for y in wanted}, "source_query": source_query,
        "source_response": {k: res.get(k) for k in ("aggregation", "quality", "scope",
                                                    "generation", "contract")},
        "provenance": prov, "limits": contract.query_limits(res, 0),
        "warnings": warnings, "status": status, "reason": reason,
        "generation": res.get("generation"),
    }
