"""Chart hints (AQ-08): `data.chart`, a description of the one chart a result can honestly draw.

The server never renders an image and the hint never copies a row. It names the rows and the
fields of the result that a client plots, so a client (Claude Desktop, ChatGPT, the Ask page) draws
the chart from numbers it already holds. The hint is `None` (absent) when no honest chart exists,
and it is only ever added to an `ok` or `partial` result.

Shape (field names are the contract; prose follows `lang`, codes never do):

    {"type": "bar" | "line",
     "rows": "data.rows",              # dotted path to the list of rows in the result
     "row_format": "object" | "array", # object: x/y are dotted paths inside one row ("entity.REF_AREA_2")
                                       # array:  x/y/series are names listed in `columns`
     "columns": "data.columns",        # only for row_format "array"
     "x": ..., "y": ..., "series": ... | null,
     "sort": "desc" | "asc" | null,    # the order the rows are already in, by y
     "unit": ..., "title": ...,
     "url": <dataset page with the selection preselected> | null,
     "url_note": <what that page shows>}

The `url` re-computes real data on the page: no number travels in it. It is null when it would
exceed the 4 KiB link rule. `dataset-v2.html` has no stable preset for a bar view (tile ids are built
at run time), so the link carries filters, the period and the pinned levels only.
"""
from __future__ import annotations

from app.services import recipes
from app.services.tools import contract as C
from app.services.tools import messages as M

MAX_URL_BYTES = 4096
MAX_SERIES = 12            # more lines than this are not readable; no chart rather than a tangle
MIN_BARS = 2               # one bar is not a chart
CHART_TOOLS = ("query_data", "rank_entities", "compare_periods", "run_recipe")


# ------------------------------------------------------------------ helpers

def label_column(keys) -> str | None:
    """The column that names one bar, or None when the key has no single honest label.

    One entity column labels itself. A locality is keyed by county plus locality, and the locality
    label carries its SIRUTA code, so it names the bar alone. Any other combination (say a county
    by sex) has no one label: two series are never merged into one axis."""
    keys = list(keys or [])
    if len(keys) == 1:
        return keys[0]
    if "REF_AREA_2" in keys and set(keys) <= {"REF_AREA", "REF_AREA_2"}:
        return "REF_AREA_2"
    return None


def _num(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool) and v == v


def _order(values: list) -> str | None:
    vs = [v for v in values if _num(v)]
    if len(vs) < 2:
        return None
    if all(a >= b for a, b in zip(vs, vs[1:])):
        return "desc"
    if all(a <= b for a, b in zip(vs, vs[1:])):
        return "asc"
    return None


def _metric(env: dict, fallback: str) -> str:
    srcs = (env.get("provenance") or {}).get("sources") or []
    return (srcs[0].get("metric") if srcs else None) or fallback


def _page(code: str, lang: str, filters: dict | None, levels: dict | None) -> str | None:
    url = C.dataset_page(code, lang, filters or None, levels or None)
    return url if len(url.encode("utf-8")) <= MAX_URL_BYTES else None


def _page_filters(prov: dict) -> tuple[dict, dict]:
    """(filters, levels) the page should open with: what the query effectively used, else asked."""
    eff = prov.get("effective_selection") or {}
    sel = prov.get("selection") or {}
    filters = eff.get("filters") if eff.get("filters") is not None else (sel.get("filters") or {})
    return {c: list(v) for c, v in filters.items() if v}, dict(eff.get("levels") or {})


def _hint(kind, *, rows, fmt, x, y, series, sort, unit, title, url, url_note, columns=None):
    out = {"type": kind, "rows": rows, "row_format": fmt}
    if columns:
        out["columns"] = columns
    out.update(x=x, y=y, series=series, sort=sort, unit=unit, title=title, url=url,
               url_note=url_note if url else None)
    return out


# ------------------------------------------------------------------ per tool

def _rank(env, lang):
    d, prov = env["data"], env.get("provenance") or {}
    rows = d.get("rows") or []
    col = label_column(d.get("entity_columns"))
    if col is None or len(rows) < MIN_BARS:
        return None
    filters, levels = _page_filters(prov)
    period = ((prov.get("source_query") or {}).get("filters") or {}).get("TIME_PERIOD")
    if period:
        filters["TIME_PERIOD"] = list(period)
    year = d.get("year")
    metric = _metric(env, d["dataset"])
    return _hint(
        "bar", rows="data.rows", fmt="object", x=f"entity.{col}", y="value", series=None,
        sort=d.get("order"), unit=d.get("unit"),
        title=M.t(lang, "chart.title_rank", metric=metric, year=year, k=len(rows),
                  n=d.get("eligible_count", len(rows))),
        url=_page(d["dataset"], lang, filters, levels),
        url_note=M.t(lang, "chart.link_year", year=year))


def _changes(env, lang):
    d, prov = env["data"], env.get("provenance") or {}
    ivs = d.get("intervals") or []
    if len(ivs) != 1:
        return None          # one chart is one ranking; several intervals rank differently
    iv = ivs[0]
    rows = iv.get("rows") or []
    col = label_column(d.get("key_columns") or d.get("entity_columns"))
    metric = d.get("metric")
    if col is None or len(rows) < MIN_BARS or metric not in ("percent", "absolute"):
        return None
    filters, levels = _page_filters(prov)
    to = str(iv.get("to"))
    values = ((prov.get("source_query") or {}).get("filters") or {}).get("TIME_PERIOD") or []
    match = [v for v in values if recipes._year(v) == to]
    if match:
        filters["TIME_PERIOD"] = match
    else:
        filters.pop("TIME_PERIOD", None)
    name = _metric(env, d["dataset"])
    return _hint(
        "bar", rows="data.intervals[0].rows", fmt="object", x=f"entity.{col}", y=metric, series=None,
        sort=d.get("order"), unit="%" if metric == "percent" else d.get("unit"),
        title=M.t(lang, "chart.title_changes", metric=name, a=iv.get("from"), b=to,
                  what=M.t(lang, f"chart.what_{metric}")),
        url=_page(d["dataset"], lang, filters, levels),
        url_note=M.t(lang, "chart.link_changes", year=to))


def _query(env, lang):
    d, prov, limits = env["data"], env.get("provenance") or {}, env.get("limits") or {}
    cols, rows = d.get("columns") or [], d.get("rows") or []
    agg = prov.get("aggregation") or {}
    if (agg.get("approximation") or env.get("reason") in ("conflicting_grain", "duplicate_keys")
            or limits.get("preview_truncated") or limits.get("source_complete") is False
            or "OBS_VALUE" not in cols or not rows):
        return None          # a labelled approximation, a repeated-key file or a cut table is not drawn
    vi = cols.index("OBS_VALUE")
    if not any(_num(r[vi]) for r in rows):
        return None
    varying = [c for i, c in enumerate(cols)
               if c != "OBS_VALUE" and len({str(r[i]) for r in rows}) > 1]
    if "UNIT_MEASURE" in varying:
        return None          # different units do not share one axis
    time_varies = "TIME_PERIOD" in varying
    others = [c for c in varying if c != "TIME_PERIOD"]
    if time_varies and len(others) <= 1:
        kind, x, series = "line", "TIME_PERIOD", (others[0] if others else None)
    elif not time_varies and len(others) == 1:
        kind, x, series = "bar", others[0], None
    else:
        return None          # two varying dimensions, or one value: no honest single chart
    xi = cols.index(x)
    si = cols.index(series) if series else None
    keys = [(r[xi], r[si] if si is not None else None) for r in rows]
    if len(set(keys)) != len(keys):
        return None          # repeated keys: the chart would overdraw or sum cells
    if series and len({k[1] for k in keys}) > MAX_SERIES:
        return None
    if kind == "bar" and len(rows) < MIN_BARS:
        return None
    code = (prov.get("selection") or {}).get("dataset")
    filters, levels = _page_filters(prov)
    src = (prov.get("sources") or [{}])[0]
    return _hint(
        kind, rows="data.rows", fmt="array", columns="data.columns", x=x, y="OBS_VALUE",
        series=series, sort=_order([r[vi] for r in rows]) if kind == "bar" else None,
        unit=src.get("unit"), title=_metric(env, code or ""),
        url=_page(code, lang, filters, levels) if code else None,
        url_note=M.t(lang, "chart.link_query"))


def _recipe(env, lang):
    d, prov = env["data"], env.get("provenance") or {}
    rows = d.get("rows") or []
    if len(rows) < MIN_BARS or any("year" in r or "label" not in r for r in rows):
        return None          # a national time series, or rows without an area label
    if not all(_num(r.get("value")) for r in rows):
        return None
    from app.services.tools import links
    rec = d.get("recipe") or {}
    sel = prov.get("selection") or {}
    year = d.get("year")
    url = links.recipe_page_url(sel.get("recipe") or rec.get("id"), year, sel.get("areas"), lang)
    return _hint(
        "bar", rows="data.rows", fmt="object", x="label", y="value", series=None,
        sort=_order([r["value"] for r in rows]), unit=rec.get("unit"),
        title=M.t(lang, "chart.title_recipe", name=rec.get("name") or rec.get("id"), year=year),
        url=url if len(url.encode("utf-8")) <= MAX_URL_BYTES else None,
        url_note=M.t(lang, "chart.link_recipe", year=year))


_BUILD = {"rank_entities": _rank, "compare_periods": _changes, "query_data": _query, "run_recipe": _recipe}


def apply(env: dict, ctx) -> dict:
    """Set `data.chart` on an ok or partial result of a chart tool when a chart is honest, in place."""
    if env.get("tool") not in CHART_TOOLS or env.get("status") not in ("ok", "partial"):
        return env
    try:
        hint = _BUILD[env["tool"]](env, ctx.lang)
    except Exception:      # a hint is optional: never let it fail a result
        import logging
        logging.getLogger(__name__).exception("chart hint failed tool=%s", env.get("tool"))
        return env
    if hint:
        env["data"]["chart"] = hint
    return env
