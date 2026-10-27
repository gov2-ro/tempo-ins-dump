"""query_data: one validated, bounded selection of a dataset (AT-01d).

The data comes from exactly one `data_query.run_query` call. Its verdicts are
carried verbatim (aggregation decision, grain status, scope, native flags); this
module only wraps them in the `tempo-tools/2` envelope, says in words what the
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
from app.services.aggregation_policy import _is_total_option
from app.services.chart_selector import TOTAL_RE
from app.services.dataset_meta import decide_grouped, get_aggregation_context, source_total_gate
from app.services.query_builder import resolve_parquet_schema, to_sdmx_name
from app.services.tools import contract as C
from app.services.tools import messages as M
from app.services.tools import schemas as S

log = logging.getLogger(__name__)

MAX_ALTERNATIVES = 2          # related datasets offered at most
SUMMARIZE_OVER = 50           # effective-filter lists longer than this are summarized
# Groups one grouped query may build. At the 160MB DuckDB budget a 4-dimension grouping of
# POP107D_grupe_localitate fit with 570k groups and failed with 860k (AQ-01B); half leaves
# room for the REST traffic sharing that budget.
MAX_GROUPS = 250_000
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
            "empty_filter_ignored", M.t(ctx.lang, "query.empty_filter", cols=", ".join(ignored)),
            subject=",".join(ignored)))
    if request["group_by"]:
        ctx.require_present_generation("query_data")       # aggregated results are certified
    elif ctx.generation.get("status") != "present" or not ctx.generation.get("id"):
        warnings.append(C.warning(
            "generation_unverified",
            M.t(ctx.lang, "query.raw_uncertified", status=ctx.generation.get("status")),
            subject=str(ctx.generation.get("status"))))
    try:
        res = dq.run_query(ctx.conn, code, filters, request["group_by"], limit=args.limit,
                           approximate=request["approximate"], max_groups=MAX_GROUPS)
    except dq.TooManyGroups as e:
        raise _too_many_groups(e, ctx, code, request["group_by"])
    except dq.QueryError as e:
        raise C.query_failure(e, ctx, code)
    aid = _Aid(ctx, code, request, res, args.limit)
    if res.get("unavailable"):
        return _refused(aid, warnings)
    sel = res.get("selection")
    if sel and sel.get("empty"):
        return _empty_selection(aid, warnings)
    return _answer(aid, warnings)


def _too_many_groups(e: "dq.TooManyGroups", ctx, code: str, group_by: list) -> C.ToolFailure:
    """Refused before execution: the grouping is close to the raw table, and the tool would
    only show a preview of it anyway. The way on is fewer groups, never raw rows."""
    col = e.widest[0] if e.widest else group_by[-1]
    rec = [C.recovery("narrow", M.t(ctx.lang, "query.too_many_groups_narrow"))]
    if e.widest:
        rec.append(C.recovery("tool_call", M.t(ctx.lang, "query.too_many_groups_values", col=col),
                              "find_dimension_values", {"dataset": code, "column": col, "lang": ctx.lang}))
    return C.ToolFailure("unavailable", "query_budget", M.t(
        ctx.lang, "query.too_many_groups", cols=", ".join(group_by), groups=f"{e.groups:,}",
        limit=f"{e.limit:,}", col=col), provenance=C.base_provenance(ctx), recovery=rec)


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


def _short(values, lang: str, n: int = 3) -> str:
    vs = [str(v) for v in values]
    return ", ".join(vs[:n]) + (M.t(lang, "query.more_values", n=len(vs)) if len(vs) > n else "")


def _total_like(v) -> bool:
    return bool(TOTAL_RE.match(str(v).strip()))


# ================================================================== a result

def _answer(aid: "_Aid", warnings: list) -> dict:
    ctx, res, request = aid.ctx, aid.res, aid.request
    lang = ctx.lang
    rows, columns = res["rows"], res["columns"]
    grouped = bool(request["group_by"])
    prov = C.query_provenance(ctx, aid.code, request, res)
    limits = C.query_limits(res, len(rows))
    warnings = warnings + _result_warnings(aid, rows, columns, grouped)
    recs = []
    status, reason = "ok", None
    n = len(rows)
    kind = "rows" if grouped else "raw_rows"
    message = M.t(lang, f"query.{kind}_{'one' if n == 1 else 'many'}", n=n)
    if not grouped:
        message += M.t(lang, "query.raw_not_total")
    elif (res.get("aggregation") or {}).get("outcome") == "approximation":
        message += M.t(lang, "query.approximation_tail")
    if limits["preview_truncated"]:
        message += M.t(lang, "query.preview_tail")
    if not rows:
        message = M.t(lang, "query.no_rows")
        warnings.append(C.warning("no_rows", M.t(lang, "query.no_rows_warning")))

    native_scope = res.get("scope") or {}
    if grouped and native_scope.get("domain_complete") is False:
        status, reason = "partial", "incomplete_domain"
        restr = [r for r in native_scope.get("restrictions") or [] if not r.get("requested")]
        cols = sorted({r["column"] for r in restr if r.get("column")})
        desc = prov["scope"]["description"]
        warnings.append(C.warning(
            "incomplete_domain", M.t(lang, "query.incomplete_domain", desc=desc),
            subject=",".join(cols) or None))
        try:
            alts = aid.complete_alternatives(cols, limit=1) if cols else []
        except Exception:
            log.exception("complete-domain alternative lookup failed code=%s", aid.code)
            alts = []
        message = M.t(lang, "query.partial_message", desc=desc, message=message)
        if alts:
            recs.append(aid.query_rec(
                M.t(lang, "query.complete_alternative", alt=alts[0], cols=", ".join(cols)), alts[0]))
        else:
            recs.append(C.recovery("narrow", M.t(lang, "query.no_complete_alternative")))
    elif grouped and native_scope.get("domain_complete") is None:
        message += M.t(lang, "query.unverified_domain")
        if (res.get("aggregation") or {}).get("method") == "sum_partition":
            status, reason = "partial", "unverified_total"
            warnings.append(C.warning("unverified_total", M.t(lang, "query.unverified_total")))
    if limits["preview_truncated"] or limits["time_windowed"]:
        recs.append(aid.narrowing_rec())
    data = {"columns": columns, "rows": rows, "column_labels": _labels(res),
            "selection": res.get("selection")}
    return C.envelope("query_data", ctx, status=status, reason=reason, message=message, data=data,
                      provenance=prov, limits=limits, warnings=warnings, recovery=recs)


def _result_warnings(aid: "_Aid", rows: list, columns: list, grouped: bool) -> list:
    res, request = aid.res, aid.request
    lang = aid.lang
    agg = res.get("aggregation") or {}
    out = []
    pins = {c: v for c, v in (agg.get("filters") or {}).items() if c not in request["filters"]}
    if pins:
        levels = agg.get("levels") or {}
        parts = [f"{c}={_short(vs, lang)}" + (M.t(lang, "query.level_suffix", level=levels[c]) if levels.get(c) else "")
                 for c, vs in pins.items()]
        out.append(C.warning("auto_pinned", M.t(lang, "query.auto_pinned", parts="; ".join(parts)),
                             subject=",".join(pins)))
    if agg.get("outcome") == "approximation" and request["approximate"]:
        out.append(C.warning("approximation", M.t(lang, "query.approximation")))
    for w in agg.get("warnings") or []:
        if w.get("code") == "time_collapsed":
            out.append(C.warning("time_collapsed", M.t(lang, "query.time_collapsed", col=w.get("column")),
                                 subject=w.get("column")))
        elif w.get("code") == "mixed_grain_on_axis":
            out.append(C.warning("mixed_grain_on_axis", M.t(lang, "query.mixed_grain", col=w.get("column")),
                                 subject=w.get("column")))
    grain = ((res.get("quality") or {}).get("grain") or {}).get("status")
    if grain in ("conflicting", "duplicate_keys"):
        out.append(C.warning(
            "data_quality", M.t(lang, "query.quality_grouped" if grouped else "query.quality_raw", grain=grain),
            subject=grain))
    if not grouped:
        out.append(C.warning("raw_rows", M.t(lang, "query.raw_rows")))
    if res.get("time_windowed"):
        out.append(C.warning("time_windowed", M.t(lang, "query.time_windowed")))
    if res.get("partial_period_dropped"):
        out.append(C.warning(
            "partial_period_dropped", M.t(lang, "query.partial_period", period=res["partial_period_dropped"]),
            subject=str(res["partial_period_dropped"])))
    if res.get("truncated"):
        out.append(C.warning("preview", M.t(lang, "query.preview")))
    vi = columns.index("OBS_VALUE") if "OBS_VALUE" in columns else len(columns) - 1
    nulls = sum(1 for r in rows if r[vi] is None
                or (isinstance(r[vi], float) and not math.isfinite(r[vi])))
    if nulls:
        out.append(C.warning("null_values", M.t(lang, "query.null_values", nulls=nulls, n=len(rows)),
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
                    "no_rows_for_value", M.t(lang, "query.no_rows_for_value", col=name, absent=_short(absent, lang)),
                    subject=name))
    return out


# ================================================================== empty selection

def _empty_selection(aid: "_Aid", warnings: list) -> dict:
    """No row matches: report which requested values are absent. Never a nearest
    period, another area or a broader selection."""
    res = aid.res
    sel = res.get("selection") or {}
    missing = sel.get("missing_values") or {}
    try:
        reason, message, recs, bounds = _plan_empty(aid, missing)
    except Exception:
        log.exception("recovery planning failed code=%s", aid.code)
        reason = "period_unavailable" if "TIME_PERIOD" in missing else "slice_value_missing"
        message = aid.t("query.empty_fallback")
        recs, bounds = [aid.describe_rec()], None
    data = {"columns": res["columns"], "rows": [], "column_labels": {}, "selection": sel}
    if bounds is not None:
        data["period_bounds"] = bounds
    return C.envelope("query_data", aid.ctx, status="unavailable", reason=reason, message=message,
                      data=data, provenance=_refusal_provenance(aid),
                      limits=C.query_limits(res, 0), warnings=warnings, recovery=recs)


def _plan_empty(aid: "_Aid", missing: dict):
    tcol = aid.time_column()
    periods = missing.get(tcol) if tcol else None
    others = {c: v for c, v in missing.items() if c != tcol}
    recs, parts = [], []
    bounds = None
    if periods:
        bounds = aid.period_bounds(tcol)
        text = aid.t("query.no_period_obs", col=tcol, periods=_short(periods, aid.lang))
        if bounds and bounds.get("first") is not None:
            text += aid.t("query.data_covers", first=bounds["first"], last=bounds["last"])
        parts.append(text)
        recs.append(aid.find_values_rec(tcol, "", aid.t("query.list_periods")))
    for col, vals in others.items():
        totals = [v for v in vals if aid.is_total_value(col, v)]
        if totals:
            msg, more = _missing_total(aid, col, totals)
            parts.append(msg)
            recs.extend(more)
        else:
            parts.append(aid.t("query.value_missing", col=col, values=_short(vals, aid.lang)))
            recs.append(aid.find_values_rec(col, str(vals[0])[:200], aid.t("query.lookup_values", col=col)))
    if not missing:
        parts.append(aid.t("query.each_exists"))
        recs += [C.recovery("narrow", aid.t("query.check_one_filter")), aid.describe_rec()]
    message = aid.t("query.no_rows_match", parts="; ".join(parts))
    return ("period_unavailable" if periods else "slice_value_missing"), message, recs, bounds


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


def refusal(ctx, code: str, request: dict, res: dict, limit: int) -> tuple[str, list]:
    """The message and recovery query_data gives for a selection the shared query refused, for
    the tools that run the same query underneath (rank_entities), so a refusal says why."""
    env = _refused(_Aid(ctx, code, request, res, limit), [])
    return env["message"], env["recovery"]


def _plan_generic(aid, reason, col, simple: bool = False):
    where = aid.t("query.dimension_suffix", col=col) if col else ""
    msg = aid.t("query.refused", reason=reason, where=where)
    recs = [aid.describe_rec()]
    if not simple:
        recs.append(C.recovery("narrow", aid.t("query.pin_others")))
    return msg, recs, []


def _missing_total(aid: "_Aid", col: str, totals: list):
    """Message part and recoveries for a requested Total the data does not have."""
    meta = aid.metadata_lists_total(col)
    shown = _short(totals, aid.lang)
    msg = aid.t("query.missing_total", col=col, shown=shown, code=aid.code) \
        + (aid.t("query.missing_total_meta") if meta else "")
    recs = []
    rid = aid.total_recipe()
    if rid:
        recs.append(C.recovery("tool_call", aid.t("query.total_recipe_cross_check", rid=rid),
                               "run_recipe", aid.recipe_args(rid)))
    q = aid.query_without_pin(col, totals)
    if q:
        recs.append(C.recovery("tool_call", aid.t("query.without_pin", col=col), "query_data", q))
    recs.append(aid.find_values_rec(col, "", aid.t("query.list_exact", col=col)))
    return msg, recs


def _plan_slice_value_missing(aid, reason, col):
    wanted = aid.canon_filters().get(col) or []
    totals = [v for v in wanted if aid.is_total_value(col, v, meta=True)]
    if totals:
        msg, recs = _missing_total(aid, col, totals)
        return (msg + aid.t("query.nothing_substituted"), recs, [])
    msg = aid.t("query.none_exist", col=col, wanted=_short(wanted, aid.lang), code=aid.code)
    return msg, [aid.find_values_rec(col, str(wanted[0])[:200] if wanted else "",
                                     aid.t("query.lookup_values", col=col)),
                 aid.describe_rec()], []


def _plan_grain(aid, reason, col):
    what = aid.t({"conflicting_grain": "query.grain_conflicting", "duplicate_keys": "query.grain_duplicate",
                  "grain_unverified": "query.grain_unverified"}[reason], code=aid.code)
    alts = aid.verified_alternatives(limit=MAX_ALTERNATIVES)
    recs = [aid.query_rec(aid.t("query.grain_alternative", alt=a), a) for a in alts]
    if alts:
        msg = aid.t("query.grain_with_alt", what=what, alts=", ".join(alts))
    else:
        msg = aid.t("query.grain_no_alt", what=what)
    if reason == "grain_unverified":
        recs.append(C.recovery("narrow", aid.t("query.grain_narrow")))
    if len(recs) < 3 and not alts:
        recs.append(aid.discover_rec())
    if len(recs) < 3:
        recs.append(aid.describe_rec())
    return msg, recs, []


def _plan_overlap(aid, reason, col):
    msg = aid.t("query.overlap", col=col)
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
            label = aid.t("query.level_one" if len(members) == 1 else "query.level_many",
                          name=ch["name"], n=len(members))
            if len(members) <= S.MAX_VALUES_PER_COLUMN:
                q = aid.query_args(filters={**aid.canon_filters(), col: members})
                text = aid.t("query.restrict_level", col=col, label=label)
            else:
                gb = aid.canon_group_by()
                q = aid.query_args(filters={k: v for k, v in aid.canon_filters().items()
                                            if k != col},
                                   group_by=gb if col in gb else gb + [col])
                text = aid.t("query.group_by_level", col=col, n=len(members))
            if q:
                recs.append(C.recovery("tool_call", text, "query_data", q))
        if len(recs) < 3:
            for child in aid.complete_children(col, limit=1):
                recs.append(aid.query_rec(aid.t("query.complete_child", child=child, col=col), child))
    if len(recs) < 3:
        recs.append(aid.find_values_rec(col, "", aid.t("query.choose_one_level", col=col)))
    if len(recs) < 3:
        recs.append(aid.describe_rec())
    return msg, recs, []


def _plan_weights(aid, reason, col):
    msg = aid.t("query.weights")
    recs = []
    agg = aid.res.get("aggregation") or {}
    collapsed = [d["column"] for d in agg.get("dimensions") or []
                 if d.get("treatment") in ("partition", "level", "explicit_set")]
    gb = aid.canon_group_by()
    keep = gb + [c for c in collapsed if c not in gb]
    if collapsed and len(keep) <= S.MAX_GROUP_COLUMNS:
        q = aid.query_args(group_by=keep)
        if q:
            recs.append(C.recovery("tool_call", aid.t("query.keep_on_axis", cols=", ".join(collapsed)),
                                   "query_data", q))
    recs.append(C.recovery("narrow", aid.t("query.pin_every_other")))
    recs.append(C.recovery("clarify", aid.t("query.ask_unweighted")))
    return msg, recs, []


def _plan_mixed_units(aid, reason, col):
    msg = aid.t("query.mixed_units", col=col)
    return msg, [aid.find_values_rec(col, "", aid.t("query.list_units", col=col)),
                 C.recovery("narrow", aid.t("query.filter_one_unit", col=col))], []


def _plan_source_total(aid, reason, col):
    which = aid.t({"source_total_mismatch": "query.total_mismatch", "no_source_total": "query.no_source_total",
                   "source_total_unchecked": "query.total_unchecked"}[reason],
                  col=col or aid.t("query.this_dimension"))
    recs = []
    rid = aid.total_recipe()
    if rid:
        recs.append(C.recovery("tool_call", aid.t("query.total_recipe", rid=rid), "run_recipe",
                               aid.recipe_args(rid)))
    alts = aid.verified_alternatives(limit=1)       # related dataset whose own checks pass
    recs += [aid.query_rec(aid.t("query.total_alternative", alt=a), a) for a in alts]
    recs.append(C.recovery("narrow", aid.t("query.explicit_slice")))
    recs.append(aid.describe_rec())
    return aid.t("query.nothing_summed", which=which), recs, []


def _plan_unusable(aid, reason, col):
    what = aid.t("query.schema_mismatch", code=aid.code, col=aid.t("query.col_suffix", col=col) if col else "") \
        if reason == "schema_mismatch" else aid.t("query.no_context", code=aid.code)
    return aid.t("query.nothing_computed", what=what), [aid.describe_rec()], []


def _plan_unverified(aid, reason, col):
    msg = aid.t("query.unverified_structure", col=col)
    recs = [aid.find_values_rec(col, "", aid.t("query.pin_one", col=col))]
    gb = aid.canon_group_by()
    if col and col not in gb and len(gb) < S.MAX_GROUP_COLUMNS:
        q = aid.query_args(group_by=gb + [col])
        if q:
            recs.append(C.recovery("tool_call", aid.t("query.keep_col", col=col), "query_data", q))
    recs.append(aid.describe_rec())
    return msg, recs, []


def _plan_contains_aggregate(aid, reason, col):
    wanted = aid.canon_filters().get(col) or []
    totals = [v for v in wanted if _total_like(v)]
    parts = [v for v in wanted if not _total_like(v)]
    msg = aid.t("query.contains_aggregate", col=col)
    recs = []
    if totals:
        q = aid.query_args(filters={**aid.canon_filters(), col: totals})
        if q:
            recs.append(C.recovery("tool_call", aid.t("query.use_total", totals=_short(totals, aid.lang)),
                                   "query_data", q))
    if parts:
        q = aid.query_args(filters={**aid.canon_filters(), col: parts})
        if q:
            recs.append(C.recovery("tool_call", aid.t("query.use_parts"), "query_data", q))
    recs.append(aid.find_values_rec(col, "", aid.t("query.list_values", col=col)))
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

    def t(self, key: str, **values) -> str:
        return M.t(self.lang, key, **values)

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

    def is_total_value(self, col: str, v, meta: bool = False) -> bool:
        """Does a requested value look like a Total? By its spelling; with `meta`,
        also when it is a verified roll-up or a metadata option the policy treats
        as a total (national geography, ...). Reads cached metadata only."""
        if _total_like(v):
            return True
        actx = self.agg_ctx() if meta else None
        if not actx:
            return False
        want = str(v).strip()
        struct = actx.get("struct") or {}
        agg = dstruct.aggregate_value(struct, col)
        if agg is not None and str(agg).strip() == want:
            return True
        for d in actx.get("dimensions") or []:
            if d.get("dim_column_name") != col:
                continue
            for o in d.get("options") or []:
                keys = {str(x).strip() for x in (o.get("label"), o.get("sdmx_value")) if x}
                if want in keys and _is_total_option(d, o, None, struct):
                    return True
        return False

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
        return C.recovery("tool_call", self.t("query.describe_rec"), "describe_dataset",
                          {"dataset": self.code, "lang": self.lang})

    def find_values_rec(self, col: str | None, query: str, message: str) -> dict:
        if not col:
            return C.recovery("narrow", message)
        return C.recovery("tool_call", message, "find_dimension_values",
                          {"dataset": self.code, "column": col, "query": query[:200]})

    def discover_rec(self) -> dict:
        from app.services.concept_search import dataset_facts
        try:
            facts = dataset_facts(self.conn, self.code, self.lang) or {}
        except Exception:
            facts = {}
        text = (facts.get("title") or self.code).strip()[:200] or self.code
        return C.recovery("tool_call", self.t("query.find_another"),
                          "discover_indicators", {"query": text, "lang": self.lang})

    def narrowing_rec(self) -> dict:
        return C.recovery("narrow", self.t("query.narrowing"))

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
            return C.recovery("narrow", self.t("query.try_narrower", dataset=dataset))
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

def shrink(env: dict, lang: str = "ro") -> bool:
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
        _flag(env, "labels_omitted", col, "query.labels_omitted", lang)
        return True
    rows = data.get("rows")
    long_lists = _long_filter_lists(env)
    if rows and long_lists:
        if C.size({**env, "data": {**data, "rows": []}}) > C.MAX_RESULT_BYTES:
            return _summarize(env, long_lists, lang)       # no amount of row cutting would fit
    if rows:
        return C.shrink_rows(env, lang=lang)
    if long_lists:
        return _summarize(env, long_lists, lang)
    return False


def _long_filter_lists(env: dict) -> list:
    eff = ((env.get("provenance") or {}).get("effective_selection") or {}).get("filters") or {}
    return [c for c, v in eff.items() if isinstance(v, list) and len(v) > SUMMARIZE_OVER]


def _summarize(env: dict, cols: list, lang: str) -> bool:
    eff = env["provenance"]["effective_selection"]["filters"]
    for c in cols:
        vals = eff[c]
        eff[c] = {"values_count": len(vals), "first": vals[:10],
                  "sha256": hashlib.sha256(C.dumps(vals).encode("utf-8")).hexdigest()}
    for c in cols:
        _flag(env, "effective_filters_summarized", c, "query.filters_summarized", lang)
    return True


def _flag(env: dict, code: str, subject: str, key: str, lang: str):
    """Add (or extend) one warning naming the affected columns."""
    for w in env["warnings"]:
        if w.get("code") == code:
            subjects = [s for s in (w.get("subject") or "").split(",") if s]
            if subject not in subjects:
                subjects.append(subject)
            w["subject"] = ",".join(subjects)
            w["message"] = M.t(lang, key, subjects=", ".join(subjects))
            return
    env["warnings"].append(C.warning(code, M.t(lang, key, subjects=subject), subject=subject))
