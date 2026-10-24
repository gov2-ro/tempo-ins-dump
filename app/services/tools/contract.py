"""The `tempo-tools/2` envelope, budgets and helpers shared by every tool (AT-00).

Every invocation returns one envelope, failures included:

  {contract, tool, status, reason, message, data, provenance, limits, warnings, recovery}

Tools raise `ToolFailure` for a refusal or a clarification and return
`envelope(...)` otherwise; `registry.call_tool` builds the envelope of a
failure, checks the generation did not change during the call and fits the
result into its byte budget. Statistical decisions are not made here: query
results come from `data_query.run_query` and keep its verdicts and flags.
"""
from __future__ import annotations

import datetime as _dt
import json
import math
import re
from dataclasses import dataclass, field
from decimal import Decimal
from urllib.parse import quote, urlencode

from app import config
from app.services import generation
from app.services.tools import messages as M

CONTRACT = "tempo-tools/2"
MAX_ARGUMENT_BYTES = 16 * 1024      # logical arguments, UTF-8 JSON
MAX_RESULT_BYTES = 32 * 1024        # logical envelope, UTF-8 JSON
MAX_TABLE_ROWS = 200                # model-visible rows in one result
MAX_RECOVERY = 3
DEFINITION_CHARS = 400              # sources carry a faithful short summary + link


class ToolFailure(Exception):
    """A refusal, clarification or error with a stable public `reason`.

    `message` is shown to people and models: never SQL, paths, keys or a raw
    exception. `data`/`provenance` may carry what is still true (e.g. the
    choices of a clarification, the dataset that refused)."""

    def __init__(self, status: str, reason: str, message: str, *, recovery=(), warnings=(),
                 data: dict | None = None, provenance: dict | None = None,
                 limits: dict | None = None):
        super().__init__(message)
        self.status, self.reason, self.message = status, reason, message
        self.recovery, self.warnings = list(recovery), list(warnings)
        self.data, self.provenance, self.limits = data, provenance, limits


@dataclass
class ToolContext:
    """What one invocation owns: a cursor (closed by the registry), the
    generation captured before execution, the language and a request id."""
    conn: object
    lang: str
    generation: dict
    request_id: str
    notes: dict = field(default_factory=dict)

    def generation_summary(self) -> dict:
        g = self.generation
        return {"id": g.get("id"), "status": g.get("status"), "built_at": g.get("built_at")}

    def require_present_generation(self, tool: str):
        """Certified analytical results need present generation evidence."""
        status = self.generation.get("status")
        if status != "present" or not self.generation.get("id"):
            raise ToolFailure(
                "unavailable", "generation_unverified",
                M.t(self.lang, "contract.generation_unverified", status=status),
                recovery=[recovery("retry", M.t(self.lang, "contract.retry_generation"))],
                provenance=base_provenance(self))


# ------------------------------------------------------------------ JSON

def json_safe(v):
    """JSON-ready copy: NaN/Infinity become null (unavailable, never zero)."""
    if v is None or isinstance(v, (bool, str, int)):
        return v
    if isinstance(v, float):
        return v if math.isfinite(v) else None
    if isinstance(v, Decimal):
        return json_safe(float(v))
    if isinstance(v, (_dt.date, _dt.datetime, _dt.time)):
        return v.isoformat()
    if isinstance(v, dict):
        return {str(k): json_safe(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [json_safe(x) for x in v]
    if isinstance(v, (set, frozenset)):
        return sorted(json_safe(x) for x in v)
    return str(v)


def dumps(obj) -> str:
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":"), allow_nan=False)


def size(obj) -> int:
    """Serialized UTF-8 bytes (not characters: Romanian text is multi-byte)."""
    return len(dumps(obj).encode("utf-8"))


# ------------------------------------------------------------------ parts

def warning(code: str, message: str, subject: str | None = None) -> dict:
    w = {"code": code, "message": message}
    if subject is not None:
        w["subject"] = subject
    return w


def recovery(kind: str, message: str, tool: str | None = None,
             arguments: dict | None = None) -> dict:
    """A suggested next step. A tool_call suggestion is a candidate, not an
    executed answer; the registry drops (and logs) one whose arguments do not
    validate against that tool's schema."""
    return {"kind": kind, "message": message, "tool": tool,
            "arguments": dict(arguments) if arguments is not None else None}


def metadata_scope() -> dict:
    return {"description": "", "domain_complete": None, "limitations": []}


def base_provenance(ctx: ToolContext) -> dict:
    return {"generation": ctx.generation_summary(), "sources": [], "selection": None,
            "effective_selection": None, "aggregation": {}, "quality": {},
            "scope": metadata_scope()}


def metadata_limits() -> dict:
    return {"returned_rows": 0, "total_rows": None, "preview_truncated": False,
            "source_complete": None, "time_windowed": False, "partial_period_dropped": None}


def series_break_items(breaks: list) -> list:
    """The machine-readable form of dataset_notes.series_breaks (the note text is the warning's)."""
    return [{k: v for k, v in b.items() if k != "text"} for b in breaks]


def _query_series_breaks(prov: dict, lang: str) -> list:
    """Known series breaks inside a query_data selection: the pinned periods, else the data the
    selection reaches. Nothing recorded means unknown continuity, not a stable series."""
    sel = prov.get("selection") or {}
    if sel.get("kind") != "dataset" or not sel.get("dataset"):
        return []
    from app.services import dataset_notes
    eff = (prov.get("effective_selection") or {}).get("filters")
    filters = eff if isinstance(eff, dict) else sel.get("filters") or {}
    cov = next((s.get("coverage") for s in prov.get("sources") or []
                if s.get("dataset") == sel["dataset"]), None) or {}
    span = (cov["first"], cov["last"]) if cov.get("first") and cov.get("last") else None
    return dataset_notes.series_breaks(sel["dataset"], lang, periods=filters.get("TIME_PERIOD"),
                                       span=span, areas=filters.get("REF_AREA"))


def envelope(tool: str, ctx: ToolContext, *, status: str = "ok", reason: str | None = None,
             message: str = "", data: dict | None = None, provenance: dict | None = None,
             limits: dict | None = None, warnings=(), recovery=()) -> dict:
    prov = base_provenance(ctx)
    prov.update(provenance or {})
    lim = metadata_limits()
    lim.update(limits or {})
    warnings = list(warnings)
    if tool == "query_data" and status in ("ok", "partial"):
        # a recorded break inside the selected periods is a warning on this selection, not just a
        # source note; compare_periods raises its own, the other tools select a single period
        known = {(w.get("code"), w.get("subject")) for w in warnings}
        breaks = [b for b in _query_series_breaks(prov, ctx.lang) if ("series_break", b["id"]) not in known]
        if breaks:
            prov["series_breaks"] = series_break_items(breaks)
            warnings += [warning("series_break", b["text"], b["id"]) for b in breaks]
    return json_safe({
        "contract": CONTRACT, "tool": tool, "status": status, "reason": reason,
        "message": message, "data": data or {}, "provenance": prov, "limits": lim,
        # the registry drops invalid suggestions, then keeps the first MAX_RECOVERY
        "warnings": warnings, "recovery": list(recovery)})


def failure_envelope(tool: str, ctx: ToolContext, f: ToolFailure) -> dict:
    return envelope(tool, ctx, status=f.status, reason=f.reason, message=f.message,
                    data=f.data, provenance=f.provenance, limits=f.limits,
                    warnings=f.warnings, recovery=f.recovery)


# ------------------------------------------------------------------ links

API_PREFIXES = ("/api/", "/sdmx/", "/mcp")


def public_url(path: str) -> str:
    """Absolute URL on the configured trusted origin: API paths (/api, /sdmx, /mcp) on
    TEMPO_PUBLIC_BASE_URL, site pages on TEMPO_PUBLIC_SITE_URL when the pages are served
    elsewhere (else TEMPO_PUBLIC_BASE_URL); a root-relative path when none is configured.
    Never derived from a request's Host or forwarded headers."""
    site = not path.startswith(API_PREFIXES)
    base = ((site and config.PUBLIC_SITE_URL) or config.PUBLIC_BASE_URL or "").rstrip("/")
    return f"{base}{path}" if base else path


def dataset_page(code: str, lang: str, filters: dict | None = None) -> str:
    q = {"code": code}
    if filters:
        q["f"] = dumps(filters)
    if lang == "en":
        q["lang"] = "en"
    return public_url("/dataset-v2.html?" + urlencode(q, quote_via=quote))


# ------------------------------------------------------------------ sources

def _short(text: str | None, n: int = DEFINITION_CHARS) -> tuple[str | None, bool]:
    t = " ".join(str(text or "").split())
    if not t:
        return None, False
    if len(t) <= n:
        return t, False
    cut = t[:n].rsplit(" ", 1)[0]
    return cut + " …", True


def source_entry(conn, code: str, lang: str) -> dict:
    """One source as every tool cites it: metric name, unit, a faithful short
    definition (full text behind `url`), source update date and public notes
    (definition, coverage, series breaks) that affect interpretation."""
    from app.services import dataset_notes
    from app.services.concept_search import dataset_facts
    facts = dataset_facts(conn, code, lang)
    if facts is None:
        # metadata-only split parents have no parquet; still cite what INS says
        row = conn.execute(
            "SELECT matrix_name, matrix_name_en, definitie, ultima_actualizare "
            "FROM matrices WHERE matrix_code = ?", [code]).fetchone()
        facts = {"title": (row[1] if lang == "en" and row[1] else row[0]) if row else None,
                 "definition": row[2] if row else None,
                 "source_updated": str(row[3]) if row and row[3] else None,
                 "unit": None, "unit_type": None, "coverage": None}
    definition, cut = _short(facts.get("definition"))
    notes = []
    for n in dataset_notes.for_code(code, lang):
        text, _ = _short(n.get("text"), 300)
        notes.append({"id": n["id"], "kind": n["kind"], "text": text})
    return {"dataset": code, "metric": facts.get("title"), "unit": facts.get("unit"),
            "unit_type": facts.get("unit_type"), "definition": definition,
            "definition_truncated": cut, "source_updated": facts.get("source_updated"),
            "coverage": facts.get("coverage"), "url": dataset_page(code, lang), "notes": notes}


# ------------------------------------------------------------------ run_query adapter

_SCOPE_TEXT = {
    "ro": {"age": "Vârste {covered} ani", "missing": " (fără {missing})",
           "requested": " (selecție explicită)", "complete": "Domeniu complet",
           "unknown": "Nu se poate verifica dacă domeniul este complet",
           "raw": "Observații brute, fără agregare", "and_over": "{lo} ani și peste"},
    "en": {"age": "Ages {covered}", "missing": " ({missing} not included)",
           "requested": " (explicit selection)", "complete": "Complete domain",
           "unknown": "Domain completeness cannot be verified",
           "raw": "Raw observations, not aggregated", "and_over": "{lo} and over"},
}


def _ranges(rs) -> str:
    return ", ".join(f"{lo}+" if hi is None else (str(lo) if lo == hi else f"{lo}–{hi}")
                     for lo, hi in rs)


def _gaps(covered, domain):
    """Integer age ranges of `domain` that `covered` does not reach."""
    lo, hi = domain
    out, cur = [], lo
    for a, b in sorted(covered, key=lambda r: r[0]):
        if a > cur:
            out.append([cur, a - 1])
        if b is None:
            return out
        cur = max(cur, b + 1)
    if hi is None or cur <= hi:
        out.append([cur, hi])
    return out


def scope_block(res_scope: dict | None, lang: str, *, raw: bool = False) -> dict:
    """provenance.scope from run_query's language-neutral `scope`."""
    tx = _SCOPE_TEXT.get(lang, _SCOPE_TEXT["ro"])
    restrictions = (res_scope or {}).get("restrictions") or []
    complete = (res_scope or {}).get("domain_complete")
    if raw:
        base = tx["raw"]
    else:
        base = tx["complete"] if complete is True else (tx["unknown"] if complete is None else "")
    parts, limitations = [], []
    for r in restrictions:
        if r.get("kind") != "age_range":
            continue
        missing = _gaps(r.get("covered") or [], r.get("domain") or [0, None])
        text = tx["age"].format(covered=_ranges(r.get("covered") or []))
        if missing:
            text += tx["missing"].format(missing=", ".join(
                tx["and_over"].format(lo=lo) if hi is None else _ranges([[lo, hi]])
                for lo, hi in missing))
        if r.get("requested"):
            text += tx["requested"]
        parts.append(text)
        limitations.append({"code": "age_range_restricted", "column": r.get("column"),
                            "covered": r.get("covered"), "domain": r.get("domain"),
                            "missing": missing, "requested": bool(r.get("requested")),
                            "message": text})
    description = "; ".join(p for p in [base, *parts] if p)
    return {"description": description, "domain_complete": complete, "limitations": limitations}


def query_provenance(ctx: ToolContext, code: str, request: dict, res: dict) -> dict:
    """Provenance of one run_query result. `request` is the normalized
    selection the caller asked for ({filters, group_by, approximate}). The
    aggregation decision is carried verbatim except its effective filters and
    levels, which live once under `effective_selection`."""
    agg = dict(res.get("aggregation") or {})
    eff_filters = agg.pop("filters", None)
    eff_levels = agg.pop("levels", None)
    raw = not request.get("group_by")
    return {
        "sources": [source_entry(ctx.conn, code, ctx.lang)],
        "selection": {"kind": "dataset", "dataset": code, "filters": request.get("filters") or {},
                      "group_by": list(request.get("group_by") or []),
                      "approximate": bool(request.get("approximate"))},
        "effective_selection": {"filters": eff_filters if eff_filters is not None
                                else (request.get("filters") or {}),
                                "levels": eff_levels or {}},
        "aggregation": agg,
        "quality": res.get("quality") or {},
        "scope": scope_block(res.get("scope"), ctx.lang, raw=raw),
    }


def query_limits(res: dict, returned: int) -> dict:
    """limits from run_query's native flags. `total_rows` is the result size
    only when the result was not cut; run_query's own `total_rows` is the
    dataset's row count, so it is not reused here."""
    truncated = bool(res.get("truncated"))
    windowed = bool(res.get("time_windowed"))
    dropped = res.get("partial_period_dropped")
    unavailable = bool(res.get("unavailable"))
    complete = None if unavailable else not (truncated or windowed or dropped is not None)
    # a windowed or period-dropped result has rows beyond what was read: size unknown
    unknown = truncated or unavailable or windowed or dropped is not None
    return {"returned_rows": returned,
            "total_rows": None if unknown else res.get("returned_rows"),
            "preview_truncated": truncated or returned < (res.get("returned_rows") or 0),
            "source_complete": complete, "time_windowed": windowed,
            "partial_period_dropped": None if dropped is None else str(dropped)}


# The few data_query.QueryError texts a tool user meets; any other text is the shared service's own.
_QUERY_ERRORS = (
    (re.compile(r"Dataset (?P<code>\w+) not found"), "contract.dataset_not_found"),
    (re.compile(r"Dataset (?P<code>\w+) has no data file — it may be published as sub-datasets\."),
     "contract.no_data_file"),
    (re.compile(r"Dataset has (?P<rows>[\d,]+) rows\. Please apply at least one filter to narrow results "
                r"\(max (?P<max>[\d,]+) rows returned\)\."), "contract.filter_needed"),
    (re.compile(r"Invalid column: unknown column (?P<col>.+)"), "contract.unknown_column"),
)


def _query_error_text(text: str, lang: str) -> str:
    for rx, key in _QUERY_ERRORS:
        m = rx.fullmatch(text)
        if m:
            vals = m.groupdict()
            if "col" in vals:
                vals["col"] = vals["col"].strip("'")
            return M.t(lang, key, **vals)
    return text


def query_failure(e, ctx: ToolContext, dataset: str, message: str | None = None) -> ToolFailure:
    """ToolFailure for a data_query.QueryError (validation, unknown id, budget). The reason comes
    from the error; the text is shown in the request's language where it is one of the few known
    ones (the rest is the shared service's own), or is `message` when the caller has its own."""
    raw = e.message
    msg = message or _query_error_text(raw, ctx.lang)
    prov = base_provenance(ctx)
    describe = recovery("tool_call", M.t(ctx.lang, "contract.read_dataset"),
                        "describe_dataset", {"dataset": dataset, "lang": ctx.lang})
    if e.status == 404:
        return ToolFailure("error", "unknown_dataset", msg, provenance=prov,
                           recovery=[describe] if "sub-datasets" in raw else [
                               recovery("tool_call", M.t(ctx.lang, "contract.find_dataset"),
                                        "discover_indicators", {"query": dataset[:200],
                                                                "lang": ctx.lang})])
    if e.status == 400 and "unknown column" in raw:
        return ToolFailure("error", "unknown_column", msg, provenance=prov, recovery=[describe])
    if e.status == 400 and "Please apply at least one filter" in raw:
        return ToolFailure("unavailable", "query_budget", msg, provenance=prov, recovery=[
            recovery("narrow", M.t(ctx.lang, "contract.filter_one"))])
    if e.status == 400:
        return ToolFailure("error", "invalid_input", msg, provenance=prov, recovery=[describe])
    return ToolFailure("error", "execution_failed",
                       M.t(ctx.lang, "contract.query_failed", ref=ctx.request_id), provenance=prov)


# ------------------------------------------------------------------ budget

def shrink_rows(env: dict, rows_path: tuple = ("data", "rows"), lang: str = "ro") -> bool:
    """Halve a model-visible table; False when there is nothing left to cut. `lang` is the
    language of the warning it adds."""
    node = env
    for k in rows_path[:-1]:
        node = node.get(k) or {}
    rows = node.get(rows_path[-1])
    if not rows:
        return False
    node[rows_path[-1]] = rows[:len(rows) // 2]
    lim = env["limits"]
    if rows_path == ("data", "rows"):
        lim["returned_rows"] = len(node[rows_path[-1]])
    lim["preview_truncated"] = True
    if not any(w.get("code") == "preview_shortened" for w in env["warnings"]):
        env["warnings"].append(warning("preview_shortened", M.t(lang, "contract.preview_shortened")))
    return True


def response_budget(env: dict, arguments_hash: str, argument_bytes: int, lang: str = "ro") -> dict:
    """Required content cannot fit: no data, no selection, a narrowing hint."""
    prov = {**env["provenance"], "selection": None, "effective_selection": None}
    return {**env, "status": "unavailable", "reason": "response_budget",
            "message": M.t(lang, "contract.response_budget"),
            "data": {"request": {"sha256": arguments_hash, "argument_bytes": argument_bytes}},
            "provenance": prov,
            "limits": {**metadata_limits()},
            "recovery": [recovery("narrow", M.t(lang, "contract.response_budget_narrow"))]}
