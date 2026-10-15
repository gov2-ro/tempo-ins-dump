"""query_data: one validated, bounded selection of a dataset (AT-01d).

The data comes from exactly one `data_query.run_query` call. Its verdicts are
carried verbatim (aggregation decision, grain status, scope, native flags); this
module only wraps them in the `tempo-tools/1` envelope, says in words what the
numbers are and are not, and, when the shared policy refuses, names a safe next
step. It never chooses SUM/AVG, drops a filter, widens an empty selection,
substitutes a nearby period or sets `approximate`.

Recovery suggestions are candidates, not answers: a related dataset is offered
only after metadata checks (certified unique grain, data file, the requested
columns and values, a complete scope where scope matters); the suggested call is
then run, and judged, by the same policy. Raw rows are never offered as a way
around a grain, overlap or domain refusal.

`shrink(env)` is the registry's budget hook for an oversized envelope.
"""
from __future__ import annotations

import hashlib
import logging
import math

from pydantic import ValidationError

from app.services import data_query as dq
from app.services import dimension_structure as dstruct
from app.services import grain_guard
from app.services import scope as scope_mod
from app.services.chart_selector import TOTAL_RE
from app.services.dataset_meta import decide_grouped, get_aggregation_context, source_total_gate
from app.services.query_builder import resolve_parquet_schema, to_sdmx_name
from app.services.tools import contract as C
from app.services.tools import schemas as S

log = logging.getLogger(__name__)

MAX_ALTERNATIVES = 2          # related datasets offered at most
SUMMARIZE_OVER = 50           # effective-filter lists longer than this are summarized
_UNSET = object()


# ================================================================== entry point

def query_data(args, ctx):
    code = args.dataset
    filters, ignored = _normalize_filters(args.filters)
    request = {"filters": filters, "group_by": list(args.group_by),
               "approximate": bool(args.approximate)}
    warnings = []
    if ignored:
        warnings.append(C.warning(
            "empty_filter_ignored",
            "Empty value lists impose no constraint and were ignored: " + ", ".join(ignored) + ".",
            subject=",".join(ignored)))
    if request["group_by"]:
        ctx.require_present_generation("query_data")       # aggregated results are certified
    elif ctx.generation.get("status") != "present" or not ctx.generation.get("id"):
        warnings.append(C.warning(
            "generation_unverified",
            f"The served data generation is {ctx.generation.get('status')}; these raw "
            "observations are not certified against a generation manifest.",
            subject=str(ctx.generation.get("status"))))
    try:
        res = dq.run_query(ctx.conn, code, filters, request["group_by"], limit=args.limit,
                           approximate=request["approximate"])
    except dq.QueryError as e:
        raise C.query_failure(e, ctx, code)
    aid = _Aid(ctx, code, request, res, args.limit)
    if res.get("unavailable"):
        return _refused(aid, warnings)
    sel = res.get("selection")
    if sel and sel.get("empty"):
        return _empty_selection(aid, warnings)
    return _answer(aid, warnings)


def _normalize_filters(filters: dict) -> tuple[dict, list]:
    """Empty value lists impose no constraint (as run_query treats them)."""
    kept = {c: list(v) for c, v in filters.items() if v}
    return kept, [c for c, v in filters.items() if not v]


def _labels(res: dict) -> dict:
    """column_labels, only where a label differs from the stored value."""
    out = {}
    for col, mapping in (res.get("column_labels") or {}).items():
        diff = {str(k): v for k, v in mapping.items() if str(k) != str(v)}
        if diff:
            out[col] = diff
    return out


def _short(values, n: int = 3) -> str:
    vs = [str(v) for v in values]
    return ", ".join(vs[:n]) + (f", … ({len(vs)} values)" if len(vs) > n else "")


def _total_like(v) -> bool:
    return bool(TOTAL_RE.match(str(v).strip()))


# ================================================================== a result

def _answer(aid: "_Aid", warnings: list) -> dict:
    ctx, res, request = aid.ctx, aid.res, aid.request
    rows, columns = res["rows"], res["columns"]
    grouped = bool(request["group_by"])
    prov = C.query_provenance(ctx, aid.code, request, res)
    limits = C.query_limits(res, len(rows))
    warnings = warnings + _result_warnings(aid, rows, columns, grouped)
    recs = []
    status, reason = "ok", None
    n = len(rows)
    noun = "raw observation row" if not grouped else "row"
    message = f"{n} {noun}{'' if n == 1 else 's'} returned."
    if not grouped:
        message += " Raw observations are not a verified total."
    elif (res.get("aggregation") or {}).get("outcome") == "approximation":
        message += " APPROXIMATION: unweighted mean of non-additive values, not an official rate."
    if limits["preview_truncated"]:
        message += " This is a preview: more rows exist."
    if not rows:
        message = "The selection returned no rows; this is not a zero."
        warnings.append(C.warning(
            "no_rows", "The data has no observations for this selection. Absence of a row "
                       "is not the value zero."))

    native_scope = res.get("scope") or {}
    if grouped and native_scope.get("domain_complete") is False:
        status, reason = "partial", "incomplete_domain"
        restr = [r for r in native_scope.get("restrictions") or [] if not r.get("requested")]
        cols = sorted({r["column"] for r in restr if r.get("column")})
        desc = prov["scope"]["description"]
        warnings.append(C.warning(
            "incomplete_domain",
            f"This total covers only part of the domain ({desc}); it is not an all-ages / "
            "all-population total. Do not present it as one.", subject=",".join(cols) or None))
        alts = aid.complete_alternatives(cols, limit=1) if cols else []
        message = (f"Valid only for the covered part of the domain: {desc}. "
                   f"{message} It is not a complete-domain total.")
        if alts:
            recs.append(aid.query_rec(
                f"{alts[0]} covers the whole domain of {', '.join(cols)} with the same "
                "columns: run the same selection there. This is a candidate, not a verified "
                "answer; its values and labels may differ.", alts[0]))
        else:
            recs.append(C.recovery(
                "narrow", "No related dataset with a verified complete domain was found. "
                          "Quote the figure only for the covered range above, or choose "
                          "another dataset with discover_indicators."))
    elif grouped and native_scope.get("domain_complete") is None:
        # unknown, not a failure: say so rather than imply a verified full-domain total
        message += " Whether it covers the whole domain is unverified (provenance.scope)."
    if limits["preview_truncated"] or limits["time_windowed"]:
        recs.append(aid.narrowing_rec())
    data = {"columns": columns, "rows": rows, "column_labels": _labels(res),
            "selection": res.get("selection")}
    return C.envelope("query_data", ctx, status=status, reason=reason, message=message, data=data,
                      provenance=prov, limits=limits, warnings=warnings, recovery=recs)


def _result_warnings(aid: "_Aid", rows: list, columns: list, grouped: bool) -> list:
    res, request = aid.res, aid.request
    agg = res.get("aggregation") or {}
    out = []
    pins = {c: v for c, v in (agg.get("filters") or {}).items() if c not in request["filters"]}
    if pins:
        levels = agg.get("levels") or {}
        parts = [f"{c}={_short(vs)}" + (f" (level {levels[c]})" if levels.get(c) else "")
                 for c, vs in pins.items()]
        out.append(C.warning(
            "auto_pinned", "Pins applied automatically to avoid double-counting: "
            + "; ".join(parts) + ". The full list is in provenance.effective_selection.",
            subject=",".join(pins)))
    if agg.get("outcome") == "approximation" and request["approximate"]:
        out.append(C.warning(
            "approximation", "APPROXIMATION: unweighted mean of non-additive values "
            "(rate, index or average) because no aligned weights exist. It is not the official "
            "or national rate; say so when quoting it."))
    for w in agg.get("warnings") or []:
        if w.get("code") == "time_collapsed":
            out.append(C.warning(
                "time_collapsed", f"Values are aggregated across all periods of {w.get('column')}; "
                "filter or group by time for a single-period figure.", subject=w.get("column")))
        elif w.get("code") == "mixed_grain_on_axis":
            out.append(C.warning(
                "mixed_grain_on_axis", f"{w.get('column')} spans several grains (levels) on this "
                "axis; do not compare or add values across levels.", subject=w.get("column")))
    grain = ((res.get("quality") or {}).get("grain") or {}).get("status")
    if grain in ("conflicting", "duplicate_keys"):
        if grouped:
            out.append(C.warning(
                "data_quality", f"This file has repeated observation keys ({grain}) elsewhere; "
                "the requested slice was checked and has none.", subject=grain))
        else:
            out.append(C.warning(
                "data_quality", f"DATA QUALITY: this dataset has repeated observation keys "
                f"({grain}); raw rows may disagree with each other. Do not total or rank them.",
                subject=grain))
    if not grouped:
        out.append(C.warning(
            "raw_rows", "Raw observations, not a verified total. Do not add them up by hand; "
            "request a grouped selection (group_by) to get a policy-checked total."))
    if res.get("time_windowed"):
        out.append(C.warning(
            "time_windowed", "Only the most recent periods were returned (row cap); filter "
            "TIME_PERIOD to reach earlier periods."))
    if res.get("partial_period_dropped"):
        out.append(C.warning(
            "partial_period_dropped", f"Period {res['partial_period_dropped']} was incomplete "
            "under the row cap and was dropped.", subject=str(res["partial_period_dropped"])))
    if res.get("truncated"):
        out.append(C.warning(
            "preview", "More rows exist than were returned (the result was capped). Use filters "
            "or the evidence links for the rest; a preview never establishes a total or an "
            "exhaustive ranking."))
    vi = columns.index("OBS_VALUE") if "OBS_VALUE" in columns else len(columns) - 1
    nulls = sum(1 for r in rows if r[vi] is None
                or (isinstance(r[vi], float) and not math.isfinite(r[vi])))
    if nulls:
        out.append(C.warning(
            "null_values", f"{nulls} of {len(rows)} row(s) have no value (null: suppressed or "
            "unavailable at the source). Null is not zero; do not include it in sums.",
            subject=str(nulls)))
    if rows and not res.get("truncated") and not res.get("time_windowed"):
        for col, vals in request["filters"].items():
            name = aid.canon(col)
            if name not in columns:
                continue
            idx = columns.index(name)
            present = {str(r[idx]) for r in rows}
            absent = [str(v) for v in vals if isinstance(v, (str, int)) and str(v) not in present]
            if absent:
                out.append(C.warning(
                    "no_rows_for_value", f"No rows for {name} = {_short(absent)} in this "
                    "selection (no observation exists; that is not a zero).", subject=name))
    return out


# ================================================================== empty selection

def _empty_selection(aid: "_Aid", warnings: list) -> dict:
    """No row matches: report which requested values are absent. Never a nearest
    period, another area or a broader selection."""
    res = aid.res
    missing = (res.get("selection") or {}).get("missing_values") or {}
    tcol = aid.time_column()
    periods = missing.get(tcol) if tcol else None
    others = {c: v for c, v in missing.items() if c != tcol}
    recs, parts = [], []
    bounds = None
    if periods:
        bounds = aid.period_bounds(tcol)
        text = f"{tcol} {_short(periods)} has no observations"
        if bounds and bounds.get("first") is not None:
            text += f" (the data covers {bounds['first']} to {bounds['last']})"
        parts.append(text)
        recs.append(aid.find_values_rec(tcol, "", "List the periods the data actually has."))
    for col, vals in others.items():
        totals = [v for v in vals if _total_like(v)]
        if totals:
            msg, more = _missing_total(aid, col, totals, vals)
            parts.append(msg)
            recs.extend(more)
        else:
            parts.append(f"{col} {_short(vals)} does not exist in the data")
            recs.append(aid.find_values_rec(col, str(vals[0])[:200],
                                            f"Look up the exact {col} values the data has."))
    if not missing:
        parts.append("each requested value exists, but no observation matches all of them "
                     "together")
        recs += [C.recovery("narrow", "Relax or check one filter at a time (find_dimension_values "
                                      "lists the values); nothing was widened for you."),
                 aid.describe_rec()]
    reason = "period_unavailable" if periods else "slice_value_missing"
    message = ("No rows match: " + "; ".join(parts) + ". Nothing was substituted: no other "
               "period, area or category stands in for the requested one.")
    data = {"columns": res["columns"], "rows": [], "column_labels": {},
            "selection": res.get("selection")}
    if bounds is not None:
        data["period_bounds"] = bounds
    return C.envelope("query_data", aid.ctx, status="unavailable", reason=reason, message=message,
                      data=data, provenance=_refusal_provenance(aid),
                      limits=C.query_limits(res, 0), warnings=warnings, recovery=recs)


def _refusal_provenance(aid: "_Aid") -> dict:
    prov = C.query_provenance(aid.ctx, aid.code, aid.request, aid.res)
    prov["scope"] = C.metadata_scope()          # no result, so no scope to disclose
    return prov


# ================================================================== a refusal

def _refused(aid: "_Aid", warnings: list) -> dict:
    res = aid.res
    agg = res.get("aggregation") or {}
    reason = agg.get("reason") or "unavailable"
    col = agg.get("blocking_dimension")
    try:
        message, recs, extra = _PLANS.get(reason, _plan_generic)(aid, reason, col)
    except Exception:
        log.exception("recovery planning failed code=%s reason=%s", aid.code, reason)
        message, recs, extra = _plan_generic(aid, reason, col, simple=True)
    data = {"columns": res["columns"], "rows": [], "column_labels": {}, "selection": None,
            "blocking_dimension": col}
    return C.envelope("query_data", aid.ctx, status="unavailable", reason=reason, message=message,
                      data=data, provenance=_refusal_provenance(aid),
                      limits=C.query_limits(res, 0), warnings=warnings + extra, recovery=recs)


def _plan_generic(aid, reason, col, simple: bool = False):
    where = f" (dimension {col})" if col else ""
    msg = (f"The shared aggregation policy refused this selection ({reason}{where}); no value "
           "was computed. Do not state a figure for it.")
    recs = [aid.describe_rec()]
    if not simple:
        recs.append(C.recovery("narrow", "Pin the other dimensions to explicit values or group "
                                         "by them so nothing has to be combined."))
    return msg, recs, []


def _missing_total(aid: "_Aid", col: str, totals: list, all_missing: list):
    """Message part and recoveries for a requested Total the data does not have."""
    meta = aid.metadata_lists_total(col)
    shown = _short(totals)
    msg = (f"{col} = {shown} does not exist in the data of {aid.code}: the source export has no "
           "such Total row" + (" although INS's metadata lists a Total option" if meta else ""))
    recs = []
    rid = aid.total_recipe()
    if rid:
        recs.append(C.recovery(
            "tool_call", f"INS's own total is served by the reviewed recipe '{rid}' (published "
                         "values, with a reconstruction only as a cross-check).",
            "run_recipe", aid.recipe_args(rid)))
    q = aid.query_without_pin(col, totals)
    if q:
        recs.append(C.recovery(
            "tool_call", f"Ask the policy for the same selection without the {col} pin: it "
                         f"combines the remaining {col} values only if it can verify they are "
                         "a complete, non-overlapping partition. Candidate only: the sum may "
                         "still be refused and is not promised to be safe.", "query_data", q))
    recs.append(aid.find_values_rec(col, "", f"List the exact {col} values the data has."))
    return msg, recs


def _plan_slice_value_missing(aid, reason, col):
    wanted = aid.canon_filters().get(col) or []
    totals = [v for v in wanted if _total_like(v)]
    if totals or (col and aid.metadata_lists_total(col) and any(_total_like(v) for v in wanted)):
        msg, recs = _missing_total(aid, col, totals or wanted, wanted)
        return (msg + ". Nothing was computed, and no other value was substituted.", recs, [])
    msg = (f"None of the requested {col} values ({_short(wanted)}) exists in the data of "
           f"{aid.code}; nothing was computed and no other value was substituted.")
    return msg, [aid.find_values_rec(col, str(wanted[0])[:200] if wanted else "",
                                     f"Look up the exact {col} values the data has."),
                 aid.describe_rec()], []


def _plan_grain(aid, reason, col):
    what = {
        "conflicting_grain": f"This slice of {aid.code} repeats the same observation key with "
                             "different values (conflicting grain), so no single total or "
                             "breakdown exists.",
        "duplicate_keys": f"This slice of {aid.code} repeats the same observation key "
                          "(duplicate keys), so a total would count it twice.",
        "grain_unverified": f"This slice of {aid.code} is too large to verify as free of "
                            "repeated observation keys, so no total was computed.",
    }[reason]
    alts = aid.verified_alternatives(limit=MAX_ALTERNATIVES)
    recs = [aid.query_rec(
        f"{a} has certified unique keys and the requested columns and values: run the same "
        "selection there. This is a candidate, not a verified answer; check its definition "
        "and scope.", a) for a in alts]
    if alts:
        msg = f"{what} Nothing was summed. A related dataset can express the selection: " \
              f"{', '.join(alts)} (a candidate, not a verified answer)."
    else:
        msg = (f"{what} Nothing was summed, and no related dataset with certified unique keys "
               "and the requested columns was found. The rows of this dataset must not be "
               "totalled or ranked by hand; choose another dataset for this indicator.")
    if reason == "grain_unverified":
        recs.append(C.recovery("narrow", "Filter the selection to one area or one period so the "
                                         "slice can be checked, then ask again."))
    if len(recs) < 3 and not alts:
        recs.append(aid.discover_rec())
    if len(recs) < 3:
        recs.append(aid.describe_rec())
    return msg, recs, []


def _plan_overlap(aid, reason, col):
    msg = (f"The options of {col} overlap (several levels or grains, e.g. single years and "
           f"age bands), so adding them would count the same units more than once. Nothing was "
           f"summed; restrict {col} to one verified level.")
    recs = []
    actx = aid.agg_ctx()
    if actx and col:
        struct = actx.get("struct") or {}
        present = set((actx.get("actual_values") or {}).get(col) or {})
        for ch in dstruct.level_choices(struct, col)[:MAX_ALTERNATIVES]:
            members = dstruct.level_members(struct, col, ch["level_id"]) or []
            if present:
                members = [m for m in members if m in present]
            if not members:
                continue
            label = f"the verified level '{ch['name']}' ({len(members)} value{'s' if len(members) != 1 else ''})"
            if len(members) <= S.MAX_VALUES_PER_COLUMN:
                q = aid.query_args(filters={**aid.canon_filters(), col: members})
                text = f"Restrict {col} to {label}. Candidate: the policy still decides."
            else:
                gb = aid.canon_group_by()
                q = aid.query_args(filters={k: v for k, v in aid.canon_filters().items()
                                            if k != col},
                                   group_by=gb if col in gb else gb + [col])
                text = (f"Group by {col}: the axis is limited to one verified level (the "
                        f"default, not all {len(members)}-value levels combined). Candidate.")
            if q:
                recs.append(C.recovery("tool_call", text, "query_data", q))
        if len(recs) < 3:
            for child in aid.complete_children(col, limit=1):
                recs.append(aid.query_rec(
                    f"{child} is a related dataset whose {col} domain is complete and "
                    "non-overlapping: run the same selection there. Candidate, not a "
                    "verified answer.", child))
    if len(recs) < 3:
        recs.append(aid.find_values_rec(col, "", f"List the exact {col} values and choose ONE "
                                                 "level (never all levels together)."))
    if len(recs) < 3:
        recs.append(aid.describe_rec())
    return msg, recs, []


def _plan_weights(aid, reason, col):
    msg = ("This measure is a rate, index or average: values of different categories cannot be "
           "added, and no aligned weights exist for a weighted mean. Nothing was combined. "
           "A labelled unweighted mean is available only if the user accepts it explicitly.")
    recs = []
    agg = aid.res.get("aggregation") or {}
    collapsed = [d["column"] for d in agg.get("dimensions") or []
                 if d.get("treatment") in ("partition", "level", "explicit_set")]
    gb = aid.canon_group_by()
    keep = gb + [c for c in collapsed if c not in gb]
    if collapsed and len(keep) <= S.MAX_GROUP_COLUMNS:
        q = aid.query_args(group_by=keep)
        if q:
            recs.append(C.recovery(
                "tool_call", f"Keep {', '.join(collapsed)} on the axis instead of combining it "
                             "(one value per category; nothing is averaged).", "query_data", q))
    recs.append(C.recovery(
        "narrow", "Pin every other dimension to one explicit value (find_dimension_values lists "
                  "them) or add it to group_by."))
    recs.append(C.recovery(
        "clarify", "Ask the user whether an UNWEIGHTED mean of these values is acceptable: it "
                   "is a labelled approximation, not the official or national rate. Only if "
                   "they agree, repeat this call with approximate=true."))
    return msg, recs, []


def _plan_mixed_units(aid, reason, col):
    msg = (f"{col} holds several measurement units and the selection does not pin one, so values "
           "were not combined across units. Nothing was computed.")
    return msg, [aid.find_values_rec(col, "", f"List the units in {col}, then pin exactly one."),
                 C.recovery("narrow", f"Filter {col} to exactly one unit and ask again.")], []


def _plan_source_total(aid, reason, col):
    which = {
        "source_total_mismatch": "INS's own published figures disagree: the parts of "
                                 f"{col or 'this dimension'} do not add up to INS's Total, so no "
                                 "summed value is reported.",
        "no_source_total": "The source has no Total row to check this summed series against, and "
                           "the grouping is not verified, so the sum was withheld.",
        "source_total_unchecked": "This summed series has not been checked against INS's own Total "
                                  "(no check on record) and the grouping is not verified, so the "
                                  "sum was withheld.",
    }[reason]
    recs = []
    rid = aid.total_recipe()
    if rid:
        recs.append(C.recovery(
            "tool_call", f"INS's own published total is served by the reviewed recipe '{rid}'.",
            "run_recipe", aid.recipe_args(rid)))
    recs.append(C.recovery(
        "narrow", "Ask for an explicit slice (pin the dimensions to single values or group by "
                  "them) instead of a combined total."))
    recs.append(aid.describe_rec())
    return f"{which} Nothing was summed.", recs, []


def _plan_unusable(aid, reason, col):
    msg = {
        "schema_mismatch": f"A dimension recorded for {aid.code}"
                           + (f" ({col})" if col else "") + " is not a column of its data file, "
                           "so no selection can be aggregated safely.",
        "no_aggregation_context": f"The metadata of {aid.code} is not usable for a safe "
                                  "aggregation, so no total can be computed here.",
    }[reason]
    return msg + " Nothing was computed.", [aid.describe_rec()], []


def _plan_unverified(aid, reason, col):
    msg = (f"The options of {col} have no verified structure (they may nest or include totals), "
           "so combining them was refused. Nothing was summed.")
    recs = [aid.find_values_rec(col, "", f"List the exact {col} values and pin ONE of them (or its "
                                         "Total).")]
    gb = aid.canon_group_by()
    if col and col not in gb and len(gb) < S.MAX_GROUP_COLUMNS:
        q = aid.query_args(group_by=gb + [col])
        if q:
            recs.append(C.recovery("tool_call", f"Keep {col} on the axis instead of combining "
                                                "it. Candidate.", "query_data", q))
    recs.append(aid.describe_rec())
    return msg, recs, []


def _plan_contains_aggregate(aid, reason, col):
    wanted = aid.canon_filters().get(col) or []
    totals = [v for v in wanted if _total_like(v)]
    parts = [v for v in wanted if not _total_like(v)]
    msg = (f"The selected {col} values mix a Total with its own parts, which would count the "
           "same units twice. Nothing was summed; choose the Total alone or the parts alone.")
    recs = []
    if totals:
        q = aid.query_args(filters={**aid.canon_filters(), col: totals})
        if q:
            recs.append(C.recovery("tool_call", f"Use the Total alone ({_short(totals)}).",
                                   "query_data", q))
    if parts:
        q = aid.query_args(filters={**aid.canon_filters(), col: parts})
        if q:
            recs.append(C.recovery("tool_call", "Use the parts alone; the policy still decides "
                                                "whether they can be combined. Candidate.",
                                   "query_data", q))
    recs.append(aid.find_values_rec(col, "", f"List the exact {col} values."))
    return msg, recs, []


_PLANS = {
    "slice_value_missing": _plan_slice_value_missing,
    "conflicting_grain": _plan_grain, "duplicate_keys": _plan_grain, "grain_unverified": _plan_grain,
    "overlapping_levels": _plan_overlap,
    "missing_weights": _plan_weights, "non_additive_measure": _plan_weights,
    "mixed_units": _plan_mixed_units,
    "source_total_mismatch": _plan_source_total, "no_source_total": _plan_source_total,
    "source_total_unchecked": _plan_source_total,
    "schema_mismatch": _plan_unusable, "no_aggregation_context": _plan_unusable,
    "unverified_structure": _plan_unverified, "label_hierarchy": _plan_unverified,
    "contains_aggregate": _plan_contains_aggregate,
}


# ================================================================== metadata helpers

class _Aid:
    """Read-only metadata lookups for messages and recovery candidates. Nothing
    here runs an aggregation or sums rows; cached contexts are never mutated."""

    def __init__(self, ctx, code, request, res, limit):
        self.ctx, self.conn, self.code, self.lang = ctx, ctx.conn, code, ctx.lang
        self.request, self.res, self.limit = request, res, limit
        self._schema = None
        self._actx = _UNSET
        self._peers = None

    # -- names
    def schema(self) -> dict:
        if self._schema is None:
            self._schema = resolve_parquet_schema(self.conn, self.code)
        return self._schema

    def canon(self, col: str) -> str:
        return to_sdmx_name(self.schema(), col)

    def canon_filters(self) -> dict:
        return {self.canon(c): list(v) for c, v in self.request["filters"].items()}

    def canon_group_by(self) -> list:
        return [self.canon(c) for c in self.request["group_by"]]

    def time_column(self) -> str | None:
        return "TIME_PERIOD" if "TIME_PERIOD" in _columns_of(self.schema()) else None

    def agg_ctx(self):
        if self._actx is _UNSET:
            try:
                self._actx = get_aggregation_context(self.conn, self.code)
            except Exception:
                log.exception("aggregation context unavailable code=%s", self.code)
                self._actx = None
        return self._actx

    def metadata_lists_total(self, col: str) -> bool:
        actx = self.agg_ctx()
        if not actx:
            return False
        for d in actx.get("dimensions") or []:
            if d.get("dim_column_name") != col:
                continue
            present = set((actx.get("actual_values") or {}).get(col) or {})
            for o in d.get("options") or []:
                for v in (o.get("sdmx_value"), o.get("label")):
                    if v and _total_like(v) and str(v).strip() not in present:
                        return True
        return False

    def period_bounds(self, tcol: str) -> dict | None:
        try:
            return dq.dimension_values(self.conn, self.code, tcol, limit=1).get("period_bounds")
        except dq.QueryError:
            return None

    # -- recoveries
    def describe_rec(self) -> dict:
        return C.recovery("tool_call", "Read the dataset's columns, values, sub-datasets and "
                                       "notes.", "describe_dataset",
                          {"dataset": self.code, "lang": self.lang})

    def find_values_rec(self, col: str, query: str, message: str) -> dict:
        return C.recovery("tool_call", message, "find_dimension_values",
                          {"dataset": self.code, "column": col, "query": query[:200]})

    def discover_rec(self) -> dict:
        from app.services.concept_search import dataset_facts
        try:
            facts = dataset_facts(self.conn, self.code, self.lang) or {}
        except Exception:
            facts = {}
        text = (facts.get("title") or self.code).strip()[:200] or self.code
        return C.recovery("tool_call", "Find another dataset for this indicator.",
                          "discover_indicators", {"query": text, "lang": self.lang})

    def narrowing_rec(self) -> dict:
        return C.recovery(
            "narrow", "Narrow the selection (filter a period or an area, or group by fewer "
                      "columns) to see the remaining rows; a preview is not the whole result.")

    def query_args(self, *, dataset: str | None = None, filters: dict | None = None,
                   group_by: list | None = None) -> dict | None:
        """Arguments of a candidate query_data call, or None when they would not
        validate (the registry would drop them anyway). `approximate` is the
        caller's own value, never set here."""
        args = {"dataset": dataset or self.code,
                "filters": self.canon_filters() if filters is None else filters,
                "group_by": self.canon_group_by() if group_by is None else group_by,
                "limit": self.limit, "approximate": self.request["approximate"],
                "lang": self.lang}
        try:
            S.QueryDataArgs.model_validate(args)
        except ValidationError:
            return None
        return args

    def query_rec(self, message: str, dataset: str) -> dict:
        args = self.query_args(dataset=dataset)
        if args is None:
            return C.recovery("narrow", f"Try {dataset} with a narrower selection.")
        return C.recovery("tool_call", message, "query_data", args)

    def query_without_pin(self, col: str, drop: list) -> dict | None:
        """The same selection without the missing Total pin; always grouped, so
        the aggregation policy (not this tool) decides what may be combined."""
        drop = {str(v) for v in drop}
        filters = {c: list(v) for c, v in self.canon_filters().items()}
        keep = [v for v in filters.get(col, []) if str(v) not in drop]
        if keep:
            filters[col] = keep
        else:
            filters.pop(col, None)
        gb = self.canon_group_by()
        tcol = self.time_column()
        if not gb and tcol:
            gb = [tcol]
        return self.query_args(filters=filters, group_by=gb) if gb else None

    def total_recipe(self) -> str | None:
        """Reviewed recipe serving the total of the concept this dataset (or its
        parent) belongs to, per concepts.json `total_recipe`."""
        from app.services import concept_search, recipes
        peers = self._family()
        wanted = {self.code} | ({peers["parent"]} if peers["parent"] else set())
        try:
            known = recipes.load_recipes()
            for c in concept_search.load_concepts():
                rid = c.get("total_recipe")
                if not rid or rid not in known:
                    continue
                codes = set((c.get("variants") or {}).values()) | {c.get("family")}
                if wanted & codes:
                    return rid
        except Exception:
            log.exception("total recipe lookup failed code=%s", self.code)
        return None

    def recipe_args(self, rid: str) -> dict:
        args = {"recipe": rid, "lang": self.lang}
        flt = self.canon_filters()
        years = [str(v) for v in flt.get("TIME_PERIOD", [])]
        if len(years) == 1 and len(years[0]) == 4 and years[0].isdigit():
            args["year"] = years[0]
        areas = [v for v in flt.get("REF_AREA", []) if isinstance(v, str) and 0 < len(v) <= 100]
        if areas and len(areas) <= S.MAX_AREAS and len(areas) == len(flt.get("REF_AREA", [])):
            args["areas"] = areas
        try:
            S.RunRecipeArgs.model_validate(args)
        except ValidationError:
            return {"recipe": rid, "lang": self.lang}
        return args

    # -- related datasets
    def _family(self) -> dict:
        """{parent, siblings, children}: codes of the split family (metadata only)."""
        if self._peers is None:
            q = self.conn.execute
            row = q("SELECT parent_matrix_code FROM matrices WHERE matrix_code = ?",
                    [self.code]).fetchone()
            parent = row[0] if row and row[0] else None

            def kids(p):
                try:
                    a = {r[0] for r in q("SELECT sub_matrix_code FROM dataset_splits "
                                         "WHERE parent_matrix_code = ?", [p]).fetchall()}
                except Exception:
                    a = set()
                b = {r[0] for r in q("SELECT matrix_code FROM matrices WHERE "
                                     "parent_matrix_code = ?", [p]).fetchall()}
                return sorted((a | b) - {self.code})
            self._peers = {"parent": parent, "siblings": kids(parent) if parent else [],
                           "children": kids(self.code)}
        return self._peers

    def _need_columns(self) -> set:
        return set(self.canon_filters()) | set(self.canon_group_by())

    def _usable(self, cand: str, need: set) -> bool:
        """A data file, certified unique keys and every requested column and value."""
        if not (dq.PARQUET_DIR / f"{cand}.parquet").exists():
            return False
        if grain_guard.file_status(cand)["status"] != "unique":
            return False
        return need <= _columns_of(resolve_parquet_schema(self.conn, cand))

    def _values_exist(self, cand: str) -> bool:
        """Requested filter values exist in the candidate (bounded lookups)."""
        for col, vals in list(self.canon_filters().items())[:4]:
            want = [str(v) for v in vals[:20]]
            try:
                page = dq.dimension_values(self.conn, cand, col, limit=500)
                if page["total"] <= 500:
                    have = set(page["values"])
                else:
                    want = want[:3]
                    have = set()
                    for v in want:
                        have |= set(dq.dimension_values(self.conn, cand, col, q=v[:200],
                                                        limit=50)["values"])
            except dq.QueryError:
                return False
            if not all(v in have for v in want):
                return False
        return True

    def _candidates(self, kinds) -> list:
        """Parent first, then siblings or children, each once, never this dataset."""
        fam = self._family()
        out = []
        for k in kinds:
            v = fam[k]
            out += [v] if k == "parent" and v else ([] if k == "parent" else v)
        return [c for c in dict.fromkeys(out) if c != self.code]

    def _context_of(self, cand: str):
        try:
            return get_aggregation_context(self.conn, cand)
        except Exception:
            log.exception("candidate context failed cand=%s", cand)
            return None

    def _policy_ok(self, cand: str) -> bool:
        """Would the shared aggregation policy accept this selection on `cand`?
        A pure evaluation over cached metadata (no SQL, nothing aggregated), mirroring
        run_query's own checks, so a candidate that the policy would refuse at once is
        not offered. The grain of the slice is still checked when the call runs."""
        gb, flt = self.canon_group_by(), self.canon_filters()
        if not gb:
            return True
        cctx = self._context_of(cand)
        if not cctx:
            return False
        try:
            decision = decide_grouped(cctx, gb, flt, allow_approximation=self.request["approximate"])
            if not decision.available:
                return False
            time_cols = {d["dim_column_name"] for d in cctx["dimensions"]
                         if d.get("dim_type") == "time"}
            if not flt and len(gb) == 1 and gb[0] in time_cols:
                reason, _ = source_total_gate(self.conn, cand, decision)
                if reason:
                    return False
        except Exception:
            log.exception("candidate policy check failed cand=%s", cand)
            return False
        return True

    def _complete_for(self, cand: str, cols: list) -> bool:
        """The candidate's data covers the whole domain of `cols` (scope metadata)."""
        cctx = self._context_of(cand)
        if not cctx:
            return False
        restricted = {r["column"] for r in scope_mod.dataset_restrictions(cctx)}
        return all(c not in restricted and scope_mod.dimension_coverage(cctx, c) is not None
                   for c in cols)

    def _alternatives(self, kinds, need: set, limit: int, cols=()) -> list:
        out = []
        for cand in self._candidates(kinds):
            try:
                if (self._usable(cand, need) and self._policy_ok(cand)
                        and (not cols or self._complete_for(cand, list(cols)))
                        and self._values_exist(cand)):
                    out.append(cand)
            except Exception:
                log.exception("alternative check failed cand=%s", cand)
            if len(out) >= limit:
                break
        return out

    def verified_alternatives(self, limit: int) -> list:
        """Parent/sibling datasets with certified unique keys that can express this
        selection and that the policy does not refuse at once."""
        return self._alternatives(("parent", "siblings"), self._need_columns(), limit)

    def complete_alternatives(self, cols: list, limit: int) -> list:
        """Parent/sibling datasets whose domain on `cols` is verified complete."""
        return self._alternatives(("parent", "siblings"), self._need_columns() | set(cols),
                                  limit, cols)

    def complete_children(self, col: str, limit: int) -> list:
        return self._alternatives(("children",), self._need_columns() | {col}, limit, (col,))


def _columns_of(schema: dict) -> set:
    """Canonical (SDMX) dimension column names of a file."""
    skip = {schema.get("value_column"), "OBS_VALUE"}
    return {to_sdmx_name(schema, c) for c in schema.get("columns") or [] if c not in skip}


# ================================================================== budget hook

def shrink(env: dict) -> bool:
    """Cut an oversized envelope one step; False when nothing is left to cut.

    Order: display labels (largest column first); then rows (halved, flagged
    as a preview by `contract.shrink_rows`); then the long effective-filter
    lists, summarized as {values_count, first, sha256}. A long filter list is
    summarized before the rows if the envelope would not fit even with no rows.
    """
    data = env.get("data") or {}
    labels = data.get("column_labels")
    if labels:
        col = max(labels, key=lambda c: C.size(labels[c]))
        del labels[col]
        _flag(env, "labels_omitted", col, "Display labels were omitted to fit the response "
              "budget for column(s): {subjects}. The values are the exact stored values.")
        return True
    rows = data.get("rows")
    long_lists = _long_filter_lists(env)
    if rows and long_lists:
        if C.size({**env, "data": {**data, "rows": []}}) > C.MAX_RESULT_BYTES:
            return _summarize(env, long_lists)       # no amount of row cutting would fit
    if rows:
        return C.shrink_rows(env)
    if long_lists:
        return _summarize(env, long_lists)
    return False


def _long_filter_lists(env: dict) -> list:
    eff = ((env.get("provenance") or {}).get("effective_selection") or {}).get("filters") or {}
    return [c for c, v in eff.items() if isinstance(v, list) and len(v) > SUMMARIZE_OVER]


def _summarize(env: dict, cols: list) -> bool:
    eff = env["provenance"]["effective_selection"]["filters"]
    for c in cols:
        vals = eff[c]
        eff[c] = {"values_count": len(vals), "first": vals[:10],
                  "sha256": hashlib.sha256(C.dumps(vals).encode("utf-8")).hexdigest()}
    for c in cols:
        _flag(env, "effective_filters_summarized", c, "Long effective filter lists were "
              "summarized to fit the response budget for: {subjects}; the full lists are "
              "reproduced by repeating the canonical selection.")
    return True


def _flag(env: dict, code: str, subject: str, template: str):
    """Add (or extend) one warning naming the affected columns."""
    for w in env["warnings"]:
        if w.get("code") == code:
            subjects = [s for s in (w.get("subject") or "").split(",") if s]
            if subject not in subjects:
                subjects.append(subject)
            w["subject"] = ",".join(subjects)
            w["message"] = template.format(subjects=", ".join(subjects))
            return
    env["warnings"].append(C.warning(code, template.format(subjects=subject), subject=subject))
