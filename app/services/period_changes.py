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
  * entity_class "cities" (AQ-05A) classifies the FULL endpoint table with the shared
    GOS102A SIRUTA catalogue (`tools.ranking.classify_cities`) before eligibility, ranks
    and top_k; it is a catalogue class, not historical city status or constant boundaries
"""
from __future__ import annotations

import math
import re
import uuid

from app.services import generation
from app.services.tools import contract
from app.services.tools import messages as M
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


def build_endpoint_table(rows, lang: str = "ro") -> dict:
    """{(key, year): value} from (key, year, value) rows. A repeated (key, year)
    is refused even when the values agree: two rows would double a sum."""
    table: dict = {}
    for key, year, value in rows:
        k = (tuple(key), str(year))
        if k in table:
            raise ToolFailure(
                "unavailable", "duplicate_keys", M.t(lang, "period.duplicate_keys"),
                recovery=[recovery("narrow", M.t(lang, "period.duplicate_keys_narrow"))])
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
    lang = ctx.lang
    describe = recovery("tool_call", M.t(lang, "period.read_periods"),
                        "describe_dataset", {"dataset": code, "lang": lang})
    if out["total"] > MAX_PERIODS:
        raise _unavailable("unsupported_frequency",
                           M.t(lang, "period.too_many_periods", code=code, max=MAX_PERIODS), rec=[describe])
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
        raise _unavailable("unsupported_frequency",
                           M.t(lang, "period.non_annual", code=code, examples=e), rec=[describe])
    multi = [y for y, vs in by_year.items() if len(vs) > 1]
    if multi:
        raise _unavailable("unsupported_frequency",
                           M.t(lang, "period.year_two_ways", code=code, year=multi[0], labels=by_year[multi[0]]),
                           rec=[describe])
    if not by_year:
        raise _unavailable("period_unavailable", M.t(lang, "period.no_periods", code=code), rec=[describe])
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


_NATIVE_REASONS = ("overlapping_levels", "unverified_structure", "contains_aggregate", "label_hierarchy",
                   "declared_partition_invalid", "source_total_mismatch", "mixed_units", "slice_value_missing",
                   "conflicting_grain", "duplicate_keys", "grain_unverified", "schema_mismatch",
                   "missing_weights", "no_aggregation_context")      # texts: messages `period.native.<reason>`
_PIN = frozenset({"overlapping_levels", "unverified_structure", "contains_aggregate",
                  "label_hierarchy", "declared_partition_invalid", "source_total_mismatch",
                  "mixed_units", "slice_value_missing"})


def _native_refusal(res: dict, code: str, lang: str, prov, limits) -> ToolFailure:
    agg = res.get("aggregation") or {}
    reason = agg.get("reason") or "aggregation_unavailable"
    col = agg.get("blocking_dimension")
    text = M.t(lang, f"period.native.{reason}" if reason in _NATIVE_REASONS else "period.native.default",
               col=col or M.t(lang, "period.a_dimension"), reason=reason)
    rec = []
    if reason in _PIN and col:
        rec.append(recovery("tool_call", M.t(lang, "period.list_pin", col=col),
                            "find_dimension_values", {"dataset": code, "column": col, "limit": 20}))
    rec.append(recovery("tool_call", M.t(lang, "period.read_dims_grain"),
                        "describe_dataset", {"dataset": code, "lang": lang}))
    return _unavailable(reason, M.t(lang, "period.no_change", text=text), rec=rec, provenance=prov,
                        limits=limits)


_DOMICILE_RE = re.compile(r"\b(?:populati\w*\s+(?:dupa\s+)?domiciliu\w*|dupa domiciliu|"
                          r"population\s+(?:by|according to)\s+domicile|domicile population)\b")
_RESIDENT_RE = re.compile(r"\b(?:populati\w*\s+(?:rezident\w*|stabil\w*)|resedinta obisnuita|"
                          r"resident population|usual residence)\b")


def _population_note(title: str, definition: str, lang: str) -> str | None:
    """What the source says its population counts: domicile or usual residence.
    Judged on the title, else the opening of the definition (a definition that
    leads with one concept may mention the other in passing: "usual residence may
    differ from domicile"); the unit-type word "medii de rezidenta" (urban/rural)
    is not a resident-population statement. Nothing is guessed."""
    from app.services.concept_search import fold
    for text in (fold(title), fold(definition)[:240]):
        dom, res = bool(_DOMICILE_RE.search(text)), bool(_RESIDENT_RE.search(text))
        if dom and not res:
            return M.t(lang, "period.pop_domicile")
        if res and not dom:
            return M.t(lang, "period.pop_resident")
        if dom and res:
            return M.t(lang, "period.pop_both")
    if "populati" in fold(f"{title} {definition[:240]}") or "population" in fold(title):
        return M.t(lang, "period.pop_unsaid")
    return None


CLASS_WARNING = M.t("en", "period.class_warning")      # the evidence bundle is English whatever the request's lang


def _warnings(notes: list, facts: dict | None, geo: bool, intervals, counts: dict, lang: str = "ro") -> list:
    out = []
    if counts:
        total = sum(counts.values())
        reasons = ", ".join(f"{r} {n}" for r, n in sorted(counts.items()))
        out.append(contract.warning("entities_excluded", M.t(lang, "period.pairs_not_ranked",
                                                             total=total, reasons=reasons)))
    if geo:
        text = M.t(lang, "period.boundary")
        pop = _population_note((facts or {}).get("title") or "", (facts or {}).get("definition") or "", lang)
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
                text = M.t(lang, "period.inside_interval", hit=", ".join(hit), text=text)
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
    from app.services.tools import ranking          # city catalogue, shared with rank_entities

    code = args.dataset
    if ctx is None:
        ctx = ToolContext(conn=conn, lang=lang, generation=generation.current(),
                          request_id=uuid.uuid4().hex[:12])
    ctx.require_present_generation("compare_periods")
    lang = ctx.lang
    mctx = dataset_meta.get_aggregation_context(conn, code)
    if mctx is None:
        raise contract.query_failure(QueryError(404, f"Dataset {code} not found"), ctx, code)

    # additive count/amount measures only: no invented rate-change policy
    measure = mctx.get("measure")
    if measure != "additive":
        title = (dataset_facts(conn, code, lang) or {}).get("title") or code
        raise _unavailable(
            "unsupported_measure",
            M.t(lang, "period.unsupported_measure", code=code, measure=measure or M.t(lang, "period.non_additive"),
                unit_type=mctx.get("unit_type") or M.t(lang, "period.unknown_unit_type")),
            rec=[recovery("tool_call", M.t(lang, "period.find_recipe"),
                          "discover_indicators", {"query": str(title)[:200], "lang": lang})])

    dims = {d["dim_column_name"]: d for d in mctx["dimensions"]}
    time_cols = [c for c, d in dims.items() if d.get("dim_type") == "time"]
    if not time_cols:
        raise _unavailable("unsupported_frequency", M.t(lang, "period.no_time", code=code),
                           rec=[recovery("tool_call", M.t(lang, "period.read_dims"),
                                         "describe_dataset", {"dataset": code, "lang": lang})])
    time_col = "TIME_PERIOD" if "TIME_PERIOD" in time_cols else time_cols[0]

    schema = resolve_parquet_schema(conn, code)
    for c in args.filters:
        if to_sdmx_name(schema, c) == time_col or c == time_col:
            raise ToolFailure("error", "invalid_input", M.t(lang, "period.filter_is_period", col=c))
    for c in args.entity_columns:
        if c == time_col or (c in dims and dims[c].get("dim_type") == "time"):
            raise ToolFailure("error", "invalid_input", M.t(lang, "period.entity_is_period", col=c))
        if c not in dims:
            raise contract.query_failure(
                QueryError(400, f"Invalid entity_columns: unknown column {c!r}"), ctx, code,
                message=M.t(lang, "period.unknown_entity_column", col=c))

    years_actual, (first, last) = _periods(conn, code, time_col, ctx)
    wanted = sorted({y for i in args.intervals for y in (i.from_, i.to)})
    absent = [y for y in wanted if y not in years_actual]
    if absent:
        raise _unavailable(
            "period_unavailable",
            M.t(lang, "period.year_absent", years=", ".join(absent), code=code, first=first, last=last),
            rec=[recovery("tool_call", M.t(lang, "period.list_values", col=time_col),
                          "find_dimension_values",
                          {"dataset": code, "column": time_col, "limit": 20})])

    key_cols, added = _key_columns(mctx, list(args.entity_columns))
    cities = args.entity_class == "cities"
    if cities:
        catalogue = ranking.city_codes(conn, lang)      # refuses when GOS102A's catalogue is unusable
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
            "source_incomplete", M.t(lang, "period.source_capped", cap=f"{MAX_DATA_ROWS:,}"),
            rec=[recovery("narrow", M.t(lang, "period.source_capped_narrow"))],
            provenance=prov, limits=contract.query_limits(res, 0))
    if agg.get("outcome") == "approximation":
        raise _unavailable("unsupported_measure", M.t(lang, "period.approximation"),
                           provenance=prov, limits=contract.query_limits(res, 0))
    mixed = [w.get("column") for w in agg.get("warnings") or []
             if w.get("code") == "mixed_grain_on_axis" and w.get("column") in key_cols]
    if mixed:
        col = mixed[0]
        raise _unavailable(
            "overlapping_levels", M.t(lang, "period.mixed_levels", col=col),
            rec=[recovery("tool_call", M.t(lang, "period.list_one_level", col=col),
                          "find_dimension_values", {"dataset": code, "column": col, "limit": 20}),
                 recovery("tool_call", M.t(lang, "period.read_levels"),
                          "describe_dataset", {"dataset": code, "lang": lang})],
            provenance=prov, limits=contract.query_limits(res, 0))
    if not res["rows"]:
        missing = ((res.get("selection") or {}).get("missing_values")) or {}
        if missing:
            col, vals = next(iter(missing.items()))
            raise _unavailable(
                "slice_value_missing",
                M.t(lang, "period.values_missing", col=col, values=", ".join(repr(v) for v in vals[:5])),
                rec=[recovery("tool_call", M.t(lang, "period.list_values", col=col),
                              "find_dimension_values",
                              {"dataset": code, "column": col, "limit": 20})],
                provenance=prov, limits=contract.query_limits(res, 0))
        raise _unavailable("no_eligible_entities", M.t(lang, "period.no_observations"),
                           provenance=prov, limits=contract.query_limits(res, 0))

    cols = res["columns"]
    try:
        ki = [cols.index(c) for c in key_cols]
        ti = cols.index(time_col)
    except ValueError:
        raise ToolFailure("error", "execution_failed", M.t(lang, "period.unexpected_shape", ref=ctx.request_id))
    year_of = {v: y for y, v in years_actual.items()}
    rows = []
    for r in res["rows"]:
        key = tuple(r[i] for i in ki)
        if any(v is None or str(v).strip() == "" for v in key):
            raise _unavailable("identity_ambiguous", M.t(lang, "period.empty_key"), provenance=prov)
        year = year_of.get(str(r[ti]))
        if year is None:
            raise ToolFailure("error", "execution_failed", M.t(lang, "period.unexpected_period", ref=ctx.request_id))
        rows.append((tuple(str(v) for v in key), year, r[-1]))
    try:
        table = build_endpoint_table(rows, lang)
    except ToolFailure as f:
        f.provenance = prov
        raise

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
                fix = recovery("tool_call", M.t(lang, "period.full_key", cols=", ".join(cols_fixed)),
                               "compare_periods", a)
            raise _unavailable(
                "identity_ambiguous",
                M.t(lang, "period.identity_ambiguous", n=len(clash), requested="/".join(args.entity_columns),
                    example="/".join(k), added=", ".join(added), parents=ex),
                rec=[fix] if fix else [], provenance=prov)

    aggregate_keys = _aggregate_keys(table, key_cols, mctx)
    intervals_in = [(i.from_, i.to) for i in args.intervals]
    scored, scored_aggregates, outside = table, aggregate_keys, 0
    if cities:
        # membership comes first: eligible counts, ranks and top_k only ever see catalogue cities
        prov["sources"].append({**contract.source_entry(conn, ranking.CITY_CATALOGUE, ctx.lang),
                                "role": "entity_classification"})
        prov["classification"] = {
            **ranking.classification_entry(), "generation": ctx.generation.get("id"),
            "applied": "before eligibility, ranks and top_k", "catalogue_count": len(catalogue)}
        try:
            classes = ranking.classify_cities(
                sorted({k for k, _ in table}, key=_skey), key_cols, catalogue, aggregate_keys, lang)
        except ToolFailure as f:
            f.provenance = prov
            raise
        members = ranking.members_of(classes)
        outside = len(classes) - len(members)
        prov["classification"].update(member_count=len(members), outside_class_count=outside)
        scored = {(k, y): v for (k, y), v in table.items() if k in members}
        scored_aggregates = frozenset()                 # totals are outside the class, not exclusions
    intervals = compute(scored, key_cols, intervals_in, args.metric, args.order, scored_aggregates)

    src = prov["sources"][0]
    # what the source says its population counts is judged on its own (Romanian) words in either language:
    # INS's English titles are translations ("LEGALLY RESIDENT POPULATION" for a domicile series)
    facts = dataset_facts(conn, code, "ro")
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
    warnings = _warnings(dataset_notes.for_code(code, lang), facts, geo, intervals, counts, lang)
    if cities:
        warnings.append(contract.warning("classification_reference", M.t(lang, "period.class_warning")))

    scope = prov["scope"]
    if not any(iv["eligible_count"] for iv in intervals):
        status, reason = "unavailable", "no_eligible_entities"
    elif counts or scope.get("domain_complete") is False:
        status = "partial"
        reason = "incomplete_domain" if scope.get("domain_complete") is False else None
    else:
        status, reason = "ok", None

    result = {
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
    if cities:      # additive, and only for the class: the default result keeps its exact shape
        result.update(entity_class="cities", outside_class_count=outside, key_classes=classes,
                      class_catalogue=catalogue, classification=prov["classification"])
    return result
