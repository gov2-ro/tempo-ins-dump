"""How an Ask turn's `tempo-tools/2` results reach the browser (AT-02).

The model sees the tool envelopes; the page keeps its existing shapes. This module adapts
one into the other and nothing else:

* ``display_table`` — the last data-bearing result as the legacy ``data`` table
  ({matrix_code, columns, rows, row_count, truncated, status, aggregation, quality,
  generation, scope, warnings, links, ...}). A change ranking or a recipe is rendered as a
  bounded table of its own rows; no chart role is invented for it and two geographic series
  are never merged. A query_data table is charted from the dataset's chart spec; a ranking, a change
  ranking or a recipe is charted from the result's own `data.chart` hint (AQ-08), translated here
  into the table's column names (``table["chart"]``). The page draws nothing the hint does not say.
* ``citations`` — datasets the turn used, each with what its queries were allowed to claim.
* ``qualifications`` — the discovery warnings that change what the displayed numbers mean and that
  the data results do not repeat (the definition a default assumed), so the page can list them
  whatever the model's own prose says.

All are pure: the numbers shown are the tool's, byte for byte.
"""
from __future__ import annotations

import re

from app.services.tools import messages as M

DATA_TOOLS = ("rank_entities", "query_data", "compare_periods", "run_recipe")
# Discovery warnings that stay on the page: the definition discovery put in place of the user's
# unnamed one. (A constraint it could not apply is a note to the model: the page cannot tell
# whether the model then applied it, so it is not asserted here.)
QUALIFYING_DISCOVERY = ("assumed_definition",)


def _usable(entry: dict) -> bool:
    o = entry.get("output")
    return (entry.get("tool") in DATA_TOOLS and isinstance(o, dict)
            and o.get("contract") == "tempo-tools/2" and o.get("status") in ("ok", "partial")
            and entry.get("executed", True))


def last_data_entry(trace: list[dict]) -> dict | None:
    for e in reversed(trace):
        if _usable(e):
            o = e["output"]
            d = o.get("data") or {}
            if o["tool"] == "query_data" and not d.get("rows"):
                continue
            return e
    return None


def _warning_texts(env: dict) -> list[str]:
    return [w.get("message", "") for w in env.get("warnings") or [] if w.get("message")]


# hint field (a dotted path in a result row) -> column of the display table, per tool
_HINT_COLUMNS = {
    "rank_entities": {"value": "OBS_VALUE"},
    "compare_periods": {"percent": "PERCENT", "absolute": "ABSOLUTE"},
    "run_recipe": {"label": "LABEL", "value": "VALUE"},
}


def chart_of(tool: str, env: dict, columns: list | None) -> dict | None:
    """The result's chart hint, in the display table's column names, or None.

    query_data keeps the dataset chart spec (`chart_dataset`). For the other tools the hint is the
    only source of a chart: it is used as the tool gave it (type, sort, unit, title, link) with its
    row fields mapped to columns that really exist in the table; a hint that cannot be mapped is
    dropped rather than guessed."""
    hint = (env.get("data") or {}).get("chart")
    if tool == "query_data" or not isinstance(hint, dict) or hint.get("type") not in ("bar", "line"):
        return None

    def column(field):
        if not isinstance(field, str):
            return None
        name = field[len("entity."):] if field.startswith("entity.") else _HINT_COLUMNS.get(tool, {}).get(field)
        return name if name in (columns or []) else None
    x, y = column(hint.get("x")), column(hint.get("y"))
    if x is None or y is None:
        return None
    return {"type": hint["type"], "x": x, "y": y, "series": None, "sort": hint.get("sort"),
            "unit": hint.get("unit"), "title": hint.get("title"), "url": hint.get("url"),
            "url_note": hint.get("url_note")}


def display_table(trace: list[dict], lang: str = "ro") -> dict | None:
    """The page's `data` for the last result that returned values, or None; a ranking, change
    ranking or recipe also carries `chart` (see `chart_of`)."""
    table = _table(trace, lang)
    e = last_data_entry(trace) if table is not None else None
    if e is not None:
        chart = chart_of(e["tool"], e["output"], table.get("columns"))
        if chart:
            table["chart"] = chart
    return table


def _table(trace: list[dict], lang: str = "ro") -> dict | None:
    """The page's `data` for the last result that returned values, or None. `lang` is the language
    of the texts this module adds (the tools' own follow the language they were called with)."""
    e = last_data_entry(trace)
    if e is None:
        return None
    env, tool = e["output"], e["tool"]
    prov, data, limits = env.get("provenance") or {}, env.get("data") or {}, env.get("limits") or {}
    agg = {**(prov.get("aggregation") or {}), **(prov.get("effective_selection") or {})}
    common = {
        "tool": tool, "tool_call_id": e.get("id"), "status": env["status"],
        "aggregation": agg or None, "quality": prov.get("quality"),
        "generation": prov.get("generation"), "scope": prov.get("scope"),
        "warnings": _warning_texts(env), "message": env.get("message"),
        "truncated": bool(limits.get("preview_truncated") or limits.get("source_complete") is False),
        "links": [],
    }
    if tool == "query_data":
        sel = prov.get("selection") or {}
        if (prov.get("aggregation") or {}).get("approximation"):
            common["status"] = "approximation"
        return {**common, "matrix_code": sel.get("dataset"), "columns": data.get("columns"),
                "rows": data.get("rows"), "preview": bool(limits.get("preview_truncated")), "unit": (prov.get("sources") or [{}])[0].get("unit"), "row_count": limits.get("returned_rows", len(data.get("rows") or []))}
    if tool == "rank_entities":
        keys = data["entity_columns"]
        return {**common, "matrix_code": data["dataset"],
                "columns": ["RANK", *keys, "TIME_PERIOD", "OBS_VALUE"],
                "rows": [[r["rank"], *[r["entity"].get(k) for k in keys], data["year"], r["value"]]
                         for r in data["rows"]], "row_count": len(data["rows"]),
                "eligible_count": data["eligible_count"], "unit": data["unit"], "ranked": True,
                "excluded_count": data.get("excluded_count"),
                "outside_class_count": data.get("outside_class_count") if data.get("entity_class") == "cities" else None}
    if tool == "compare_periods":
        ent_cols = list(data.get("entity_columns") or [])
        cols = [*ent_cols, "INTERVAL", "FROM_VALUE", "TO_VALUE", "ABSOLUTE", "PERCENT", "RANK"]
        rows = []
        for iv in data.get("intervals") or []:
            for r in iv.get("rows") or []:
                rows.append([*[(r.get("entity") or {}).get(c) for c in ent_cols],
                             f"{iv.get('from')}→{iv.get('to')}", r.get("from_value"), r.get("to_value"),
                             r.get("absolute"), r.get("percent"), r.get("rank")])
        excluded = sum(iv.get("excluded_count") or 0 for iv in data.get("intervals") or [])
        if excluded:
            common["warnings"] = [*common["warnings"], M.t(lang, "present.pairs_excluded", n=excluded)]
        # ranked over every eligible entity of each interval before top K: a cut list is still the ranking
        return {**common, "matrix_code": data.get("dataset"), "columns": cols, "rows": rows,
                "row_count": len(rows), "metric": data.get("metric"), "unit": data.get("unit"),
                "ranked": True, "eligible_count": sum(iv.get("eligible_count") or 0 for iv in data.get("intervals") or []),
                "interval_count": len(data.get("intervals") or []), "excluded_count": excluded,
                "outside_class_count": data.get("outside_class_count")}
    rec = data.get("recipe") or {}
    rows = [[r.get("label") or r.get("area"), r.get("value")] for r in data.get("rows") or []]
    return {**common, "matrix_code": None, "columns": ["LABEL", "VALUE"], "rows": rows,
            "row_count": len(rows), "recipe": rec.get("id"), "year": data.get("year"),
            "unit": rec.get("unit") or data.get("unit")}


def _datasets_of(env: dict) -> set:
    """The datasets a data result stands on: its selection and every source it cites."""
    prov = env.get("provenance") or {}
    out = {s.get("dataset") for s in prov.get("sources") or []}
    out.add((prov.get("selection") or {}).get("dataset"))
    return out - {None}


def _card_datasets(card: dict) -> set:
    out = set()
    for cand in card.get("candidates") or []:
        out.add(cand.get("dataset"))
        out.update(cand.get("sources") or [])
    return out - {None}


def qualifications(trace: list[dict]) -> list[dict]:
    """[{code, subject, message}] of the discovery warnings in `QUALIFYING_DISCOVERY` that bear on the
    displayed result: the warned concept's card offered a dataset the result stands on. Taken from the
    tool results of the turn, never from the model's text; none when nothing is displayed."""
    shown = last_data_entry(trace)
    if shown is None:
        return []
    stands_on = _datasets_of(shown["output"])
    out = []
    for t in trace:
        env = t.get("output")
        if t.get("tool") != "discover_indicators" or not t.get("executed", True) \
                or not isinstance(env, dict) or env.get("status") != "ok":
            continue
        cards = {c.get("id"): c for c in (env.get("data") or {}).get("concepts") or []}
        for w in env.get("warnings") or []:
            card = cards.get(w.get("subject"))
            if w.get("code") in QUALIFYING_DISCOVERY and card and stands_on & _card_datasets(card):
                out.append({"code": w["code"], "subject": w.get("subject"), "message": w.get("message")})
    return out


def chart_dataset(trace: list[dict]) -> str | None:
    """The dataset whose chart spec the page may use: only a query_data table has one."""
    e = last_data_entry(trace)
    if e is None or e["tool"] != "query_data":
        return None
    return ((e["output"].get("provenance") or {}).get("selection") or {}).get("dataset")


def selection_of(trace: list[dict]) -> tuple[dict, str] | None:
    """(canonical selection, generation id) of the displayed result, for its links."""
    e = last_data_entry(trace)
    if e is None:
        return None
    prov = e["output"].get("provenance") or {}
    gen = (prov.get("generation") or {})
    if prov.get("selection") and gen.get("status") == "present" and gen.get("id"):
        return prov["selection"], gen["id"]
    return None


def _query_info(e: dict) -> dict:
    env = e["output"]
    prov = env.get("provenance") or {}
    agg = prov.get("aggregation") or {}
    eff = prov.get("effective_selection") or {}
    approx = bool(agg.get("approximation"))
    status = "approximation" if approx and env["status"] == "ok" else env["status"]
    return {"tool": e["tool"], "tool_call_id": e.get("id"), "status": status,
            "outcome": agg.get("outcome") or ("raw" if env["status"] == "ok" else None),
            "method": agg.get("method"), "reason": env.get("reason") or agg.get("reason"),
            "approximation": approx,
            "filters": eff.get("filters") or ((prov.get("selection") or {}).get("filters") or {}),
            "levels": eff.get("levels") or {}}


def citations(answer: str, trace: list[dict]) -> list[dict]:
    """Datasets the turn used (queries, change rankings, recipes, described schemas), each with
    the verdict of the queries behind it, plus any `(CODE)` the answer names."""
    codes: dict[str, dict] = {}

    def entry(code, name=""):
        e = codes.setdefault(code, {"matrix_code": code, "matrix_name": "", "queries": []})
        if name and not e["matrix_name"]:
            e["matrix_name"] = name
        return e

    for t in trace:
        env = t.get("output")
        if not (isinstance(env, dict) and env.get("contract") == "tempo-tools/2") \
                or not t.get("executed", True):
            continue
        prov = env.get("provenance") or {}
        names = {s.get("dataset"): s.get("metric") or "" for s in prov.get("sources") or []}
        if t["tool"] == "describe_dataset" and env.get("status") in ("ok", "partial"):
            code = (env.get("data") or {}).get("dataset")
            if code:
                entry(code, (env["data"].get("name") or names.get(code) or ""))
        elif t["tool"] in DATA_TOOLS:
            sel_code = (prov.get("selection") or {}).get("dataset")
            for code in ([sel_code] if sel_code else list(names)):
                if code:
                    e = entry(code, names.get(code, ""))
                    e["queries"].append(_query_info(t))
    for m in re.finditer(r"\(([A-Z][A-Z0-9_]{3,})\)", answer or ""):
        entry(m.group(1))
    return [codes[k] for k in sorted(codes)]
