"""Deterministic cross-dataset recipes (PA-03b). One recipe for the alpha:
tourism intensity = overnight stays / resident population on 1 January.

Each source goes through the shared query (`data_query.run_query`): the
aggregation policy and the grain gate decide whether its series may be built,
and a refused, capped or time-windowed result stops the recipe. Each series is
reduced to one row per (county id, year) before anything is divided. County ids
are exact-label slugs within the declared county level, never fuzzy matches.
`compute()` is pure, so the rules are tested on fixtures.
"""
from __future__ import annotations

import json
import math
import re
import unicodedata
from pathlib import Path

RECIPES_PATH = Path(__file__).resolve().parent.parent / "data" / "recipes.json"


class RecipeError(Exception):
    """The recipe cannot produce a result; `reason` is a stable code."""

    def __init__(self, reason: str, message: str, **detail):
        super().__init__(message)
        self.reason, self.message, self.detail = reason, message, detail

    def to_dict(self):
        return {"reason": self.reason, "message": self.message, **self.detail}


SOURCE_KEYS = {"ratio": ("numerator", "denominator"), "weighted_mean": ("values", "weights"),
               "rate_from_counts": ("rates", "counts")}


def source_specs(r: dict) -> tuple:
    """The recipe's two source specs, in formula order."""
    return tuple(r[k] for k in SOURCE_KEYS[r.get("kind", "ratio")])


def load_recipes() -> dict:
    return {r["id"]: r for r in json.loads(RECIPES_PATH.read_text(encoding="utf-8"))["recipes"]}


def geo_id(label: str) -> str:
    """Stable county id from its exact label (accents, case and spacing only)."""
    s = unicodedata.normalize("NFKD", str(label or "").strip())
    s = "".join(c for c in s if not unicodedata.combining(c)).lower()
    return re.sub(r"[^a-z0-9]+", "-", s).strip("-")


def _year(period) -> str | None:
    m = re.fullmatch(r"(?:Anul\s+)?(\d{4})", str(period or "").strip())
    return m.group(1) if m else None


def _series(rows, role: str, multiplier: float) -> dict:
    """{(geo_id, year): (label, value)} with one row per key, or RecipeError."""
    out = {}
    for label, period, value in rows:
        y = _year(period)
        if y is None:
            raise RecipeError("unsupported_period", f"{role}: period {period!r} is not annual")
        key = (geo_id(label), y)
        if key in out:
            # Two rows for one county-year would multiply in a join; refuse first.
            raise RecipeError("duplicate_key", f"{role}: more than one row for {label} {y}",
                              source=role, key=list(key))
        v = None if value is None else float(value) * multiplier
        out[key] = (str(label).strip(), v)
    return out


def compute(num_rows, den_rows, *, num_unit: str | None, den_unit: str | None,
            multipliers: dict, year: str | None = None, areas: list[str] | None = None) -> dict:
    """Pure recipe arithmetic.

    num_rows / den_rows: [(area label, period, value)] already reduced by the
    shared policy to one value per area and period. Returns {year, rows,
    excluded, years_available, universe}. Raises RecipeError when no valid
    result exists (unknown unit, duplicate keys, no common year).
    """
    for role, unit in (("stays", num_unit), ("population", den_unit)):
        if unit not in multipliers:
            raise RecipeError("unsupported_unit", f"{role}: unit {unit!r} has no declared multiplier",
                              source=role, unit=unit)
    num = _series(num_rows, "stays", multipliers[num_unit])
    den = _series(den_rows, "population", multipliers[den_unit])
    years_num = {y for _, y in num}
    years_den = {y for _, y in den}
    common = sorted(years_num & years_den)
    if year is not None:
        year = _year(year)
        if year not in common:
            raise RecipeError("year_unavailable", f"no common data for {year}",
                              years_available=common)
    elif not common:
        raise RecipeError("no_common_year", "the two sources share no year",
                          years_numerator=sorted(years_num), years_denominator=sorted(years_den))
    else:
        year = common[-1]          # latest year both sources have; never mixed years

    want = {geo_id(a) for a in areas} if areas else None
    universe = sorted(g for g, y in den if y == year and (want is None or g in want))
    rows, excluded = [], []
    for g in universe:
        label, pop = den[(g, year)]
        stays = num.get((g, year))
        if stays is None or stays[1] is None:
            excluded.append({"geo_id": g, "label": label, "reason": "numerator_missing"})
            continue
        if pop is None:
            excluded.append({"geo_id": g, "label": label, "reason": "denominator_missing"})
            continue
        if not (math.isfinite(pop) and math.isfinite(stays[1])):
            excluded.append({"geo_id": g, "label": label, "reason": "nonfinite"})
            continue
        if pop <= 0:
            excluded.append({"geo_id": g, "label": label, "reason": "denominator_not_positive"})
            continue
        rows.append({"geo_id": g, "label": label, "year": year, "stays": stays[1],
                     "population": pop, "intensity": stays[1] / pop})
    # Areas the numerator has but the denominator (the universe) lacks.
    for (g, y), (label, _) in sorted(num.items()):
        if y == year and g not in universe and (want is None or g in want):
            excluded.append({"geo_id": g, "label": label, "reason": "not_in_denominator"})
    if want:
        for g in sorted(want - set(universe) - {e["geo_id"] for e in excluded}):
            excluded.append({"geo_id": g, "label": g, "reason": "not_in_data"})
    rows.sort(key=lambda r: (-r["intensity"], r["label"]))
    for i, r in enumerate(rows, 1):
        r["rank"] = i
    return {"year": year, "rows": rows, "excluded": excluded,
            "years_available": common, "universe": len(universe)}


# ------------------------------------------------------------------ execution

def _years(conn, code: str) -> list[str]:
    from app.services.data_query import QueryError, dimension_values
    try:
        vals = dimension_values(conn, code, "TIME_PERIOD", limit=500)["values"]
    except QueryError as e:
        raise RecipeError("source_failed", f"{code}: {e.message}")
    return sorted({y for y in (_year(v) for v in vals) if y})


def _source(conn, spec: dict, lang: str, year: str | None = None) -> dict:
    """Run one source through the shared query; refuse anything incomplete.
    `year` pins TIME_PERIOD (sources too large for one unfiltered query)."""
    from app.config import MAX_DATA_ROWS
    from app.services.concept_search import dataset_facts
    from app.services.data_query import QueryError, run_query
    code = spec["dataset"]
    try:
        flt = dict(spec.get("filters") or {})
        if year is not None:
            flt["TIME_PERIOD"] = [year]
        res = run_query(conn, code, flt, list(spec["group_by"]), MAX_DATA_ROWS)
    except QueryError as e:
        raise RecipeError("source_failed", f"{code}: {e.message}", source=spec["role"])
    agg = res.get("aggregation") or {}
    if res.get("unavailable"):
        raise RecipeError("source_unavailable", f"{code}: {agg.get('reason')}",
                          source=spec["role"], source_reason=agg.get("reason"))
    if res.get("truncated") or res.get("time_windowed") or res.get("partial_period_dropped"):
        raise RecipeError("source_incomplete", f"{code}: result was capped", source=spec["role"])
    if agg.get("outcome") == "approximation":
        raise RecipeError("source_approximation", f"{code}: approximations are not recipe inputs",
                          source=spec["role"])
    cols = res["columns"]
    gi, ti = cols.index("REF_AREA"), cols.index("TIME_PERIOD")
    facts = dataset_facts(conn, code, lang) or {}
    return {"role": spec["role"], "dataset": code, "rows": [(r[gi], r[ti], r[-1]) for r in res["rows"]],
            "columns": cols, "table": [list(r) for r in res["rows"]],
            "unit": facts.get("unit"), "title": facts.get("title"),
            "definition": facts.get("definition"), "source_updated": facts.get("source_updated"),
            "coverage": facts.get("coverage"), "concept": spec.get("concept"),
            "reference": spec.get("reference"),
            "query": {"dataset": code, "filters": {**(spec.get("filters") or {}),
                                                   **({"TIME_PERIOD": [year]} if year else {})},
                      "group_by": spec["group_by"], "approximate": False},
            "aggregation": agg, "quality": res.get("quality"), "generation": res.get("generation"),
            "contract": res.get("contract")}


def _common_year(years_a, years_b, year):
    common = sorted(set(years_a) & set(years_b))
    if year is not None:
        year = _year(year)
        if year not in common:
            raise RecipeError("year_unavailable", f"no common data for {year}", years_available=common)
        return year, common
    if not common:
        raise RecipeError("no_common_year", "the two sources share no year")
    return common[-1], common


def compute_weighted_mean(values, weights, *, cell_cols, keep: dict, year=None, areas=None) -> dict:
    """Σ(value × weight) / Σ weight per county and year over a declared partition.

    values / weights: (columns, rows) with the same cell columns plus REF_AREA and
    TIME_PERIOD. `keep` = {column: regex} selects the partition (e.g. CAEN
    sections). A county-year is excluded when a weighted cell has no value
    (`value_missing`) or the weights sum to zero (`no_weights`): a partial
    average would not be the total INS publishes.
    """
    import re as _re

    def keyed(cols, rows, role):
        ix = {c: cols.index(c) for c in cell_cols + ["REF_AREA", "TIME_PERIOD"]}
        pats = {c: _re.compile(p) for c, p in keep.items()}
        out = {}
        for r in rows:
            if any(not pats[c].search(str(r[ix[c]] or "")) for c in pats):
                continue
            y = _year(r[ix["TIME_PERIOD"]])
            if y is None:
                raise RecipeError("unsupported_period", f"{role}: period {r[ix['TIME_PERIOD']]!r} is not annual")
            k = (geo_id(r[ix["REF_AREA"]]), y, tuple(str(r[ix[c]]) for c in cell_cols))
            if k in out:
                raise RecipeError("duplicate_key", f"{role}: more than one row for {k}", source=role)
            out[k] = (str(r[ix["REF_AREA"]]).strip(), r[-1])
        return out
    v = keyed(*values, "value")
    w = keyed(*weights, "weight")
    year, common = _common_year({k[1] for k in v}, {k[1] for k in w}, year)
    want = {geo_id(a) for a in areas} if areas else None
    cells: dict = {}
    for (g, y, cell), (label, wt) in w.items():
        if y == year and (want is None or g in want):
            cells.setdefault(g, {"label": label, "cells": []})["cells"].append((cell, wt, v.get((g, y, cell), (None, None))[1]))
    rows, excluded = [], []
    for g, d in sorted(cells.items()):
        used = [(val, wt) for _, wt, val in d["cells"] if wt]
        if any(val is None for val, _ in used):
            excluded.append({"geo_id": g, "label": d["label"], "reason": "value_missing"})
            continue
        tw = sum(wt for _, wt in used)
        if not tw or tw <= 0:
            excluded.append({"geo_id": g, "label": d["label"], "reason": "no_weights"})
            continue
        rows.append({"geo_id": g, "label": d["label"], "year": year,
                     "value": sum(val * wt for val, wt in used) / tw,
                     "weight_total": tw, "cells": len(used)})
    if want:
        for g in sorted(want - set(cells)):
            excluded.append({"geo_id": g, "label": g, "reason": "not_in_data"})
    rows.sort(key=lambda r: (-r["value"], r["label"]))
    for i, r in enumerate(rows, 1):
        r["rank"] = i
    return {"year": year, "rows": rows, "excluded": excluded, "years_available": common,
            "universe": len(cells)}


def compute_rate_from_counts(rates, counts, *, by: str, year=None, areas=None) -> dict:
    """Total rate from per-group rates and counts: 100·ΣU / Σ(U / (rate/100)).

    A rate is U / A × 100, so each group's base A = U / (rate/100); summing U
    and A over the groups (here both sexes) gives the published total rate.
    A county-year needs every group of the rates present with rate > 0 (or
    U = 0 and rate = 0), else it is excluded (`group_missing`, `rate_zero`).
    The total always lies between the group rates, so an area with every rate
    but some counts missing is excluded with those `bounds`.
    """
    def keyed(cols, rows, role):
        ix = {c: cols.index(c) for c in (by, "REF_AREA", "TIME_PERIOD")}
        out = {}
        for r in rows:
            y = _year(r[ix["TIME_PERIOD"]])
            if y is None:
                raise RecipeError("unsupported_period", f"{role}: period {r[ix['TIME_PERIOD']]!r} is not annual")
            k = (geo_id(r[ix["REF_AREA"]]), y, str(r[ix[by]]))
            if k in out:
                raise RecipeError("duplicate_key", f"{role}: more than one row for {k}", source=role)
            out[k] = (str(r[ix["REF_AREA"]]).strip(), r[-1])
        return out
    rt = keyed(*rates, "rate")
    ct = keyed(*counts, "count")
    year, common = _common_year({k[1] for k in rt}, {k[1] for k in ct}, year)
    want = {geo_id(a) for a in areas} if areas else None
    groups = sorted({k[2] for k in rt if k[1] == year})
    geos = {}
    for (g, y, grp), (label, val) in rt.items():
        if y == year and (want is None or g in want):
            geos.setdefault(g, label)
    rows, excluded = [], []
    for g, label in sorted(geos.items()):
        U = A = 0.0
        reason = None
        for grp in groups:
            r = rt.get((g, year, grp), (None, None))[1]
            u = ct.get((g, year, grp), (None, None))[1]
            if r is None or u is None:
                reason = "group_missing"
                break
            if r <= 0:
                if u == 0:
                    continue
                reason = "rate_zero"
                break
            U += u
            A += u / (r / 100)
        if reason or A <= 0:
            ex = {"geo_id": g, "label": label, "reason": reason or "no_base"}
            rs = [rt.get((g, year, grp), (None, None))[1] for grp in groups]
            if None not in rs:
                ex["bounds"] = [min(rs), max(rs)]
            excluded.append(ex)
            continue
        rows.append({"geo_id": g, "label": label, "year": year, "value": 100 * U / A,
                     "count_total": U, "base_total": A})
    if want:
        for g in sorted(want - set(geos)):
            excluded.append({"geo_id": g, "label": g, "reason": "not_in_data"})
    rows.sort(key=lambda r: (-r["value"], r["label"]))
    for i, r in enumerate(rows, 1):
        r["rank"] = i
    return {"year": year, "rows": rows, "excluded": excluded, "years_available": common,
            "universe": len(geos)}


# ------------------------------------------------------------------ published totals
#
# A recipe with `published: {"matrix": M}` serves INS's own Total cell for each
# area and year (table `published_totals`, scripts/load-published-totals.py) and
# keeps its reconstruction as a cross-check: a mean or rate rebuilt from rounded
# published parts can differ from INS's total by one unit (docs/METHODOLOGY.md §4).

def _published_cells(conn, matrix: str) -> dict:
    """{(geo_id, year): row} for one matrix, or {} when the generation has none."""
    try:
        rows = conn.execute(
            "SELECT ref_area, time_period, value, unit, query_id, fetched_at, file_sha256, "
            "ins_updated FROM published_totals WHERE matrix_code = ?", [matrix]).fetchall()
    except Exception:           # older generations have no published_totals table
        return {}
    return {(geo_id(a), y): {"label": a, "year": y, "value": v, "unit": u, "query_id": q,
                             "fetched_at": f, "sha256": s, "ins_updated": iu}
            for a, y, v, u, q, f, s, iu in rows}


def _county_ids(conn, code: str) -> set:
    from app.services.data_query import QueryError, dimension_values
    try:
        vals = dimension_values(conn, code, "REF_AREA", limit=500)["values"]
    except QueryError as e:
        raise RecipeError("source_failed", f"{code}: {e.message}")
    return {geo_id(v) for v in vals}


def compute_published(cells: dict, counties: set, *, year=None, areas=None,
                      reconstruction: dict | None = None, decimals: int = 0) -> dict:
    """Pure: INS's published value per county for one year, ranked, with the
    non-county cells (country, regions) as `aggregates` and, when a
    reconstruction for the same year is given, each row's `reconstructed`
    value and a summary `check` over every county of that year (not only the
    requested areas: the check describes the year's data)."""
    years = sorted({y for (g, y), c in cells.items() if g in counties and c["value"] is not None})
    if not years:
        raise RecipeError("no_published_data", "no published county values")
    if year is not None:
        year = _year(year)
        if year not in years:
            raise RecipeError("year_unavailable", f"no common data for {year}", years_available=years)
    else:
        year = years[-1]
    rec = {x["geo_id"]: x for x in (reconstruction or {}).get("rows", [])}
    rows, excluded, aggregates = [], [], []
    for (g, y), c in sorted(cells.items()):
        if y != year:
            continue
        if g not in counties:
            if c["value"] is not None:
                aggregates.append({"geo_id": g, "label": c["label"], "value": c["value"]})
            continue
        if c["value"] is None:
            excluded.append({"geo_id": g, "label": c["label"], "reason": "not_published"})
            continue
        row = {"geo_id": g, "label": c["label"], "year": year, "value": c["value"],
               "reconstructed": rec[g]["value"] if g in rec else None}
        for k in ("weight_total", "count_total", "base_total"):
            if g in rec and k in rec[g]:
                row[k] = rec[g][k]
        rows.append(row)
    check = None
    if reconstruction is not None:
        both = [x for x in rows if x["reconstructed"] is not None]
        q = 10 ** decimals
        check = {"compared": len(both),
                 "max_abs_diff": max((abs(x["value"] - x["reconstructed"]) for x in both), default=None),
                 "equal_when_rounded": sum(1 for x in both
                                           if math.floor(x["reconstructed"] * q + 0.5) / q == x["value"])}
    if areas:
        want = {geo_id(a) for a in areas}
        known = {x["geo_id"] for x in rows} | {e["geo_id"] for e in excluded}
        rows = [x for x in rows if x["geo_id"] in want]
        excluded = [e for e in excluded if e["geo_id"] in want]
        excluded += [{"geo_id": g, "label": g, "reason": "not_in_data"} for g in sorted(want - known)]
    rows.sort(key=lambda r: (-r["value"], r["label"]))
    for i, r in enumerate(rows, 1):
        r["rank"] = i
    universe = len(rows) + sum(1 for e in excluded if e["reason"] != "not_in_data")
    return {"year": year, "rows": rows, "excluded": excluded, "years_available": years,
            "universe": universe, "aggregates": aggregates, "check": check,
            "value_source": "ins_published"}


def run(conn, recipe_id: str, *, year=None, areas=None, lang: str = "ro") -> dict:
    recipes = load_recipes()
    if recipe_id not in recipes:
        raise RecipeError("unknown_recipe", f"no recipe {recipe_id!r}")
    r = recipes[recipe_id]
    if r.get("published"):
        cells = _published_cells(conn, r["published"]["matrix"])
        if cells:
            return _run_published(conn, r, cells, year=year, areas=areas, lang=lang)
    return _run_reconstruction(conn, r, year=year, areas=areas, lang=lang)


def _pick(d, lang):
    return d.get(lang) or d.get("ro") if isinstance(d, dict) else d


def _recipe_info(r: dict, kind: str, lang: str) -> dict:
    pick = lambda d: _pick(d, lang)
    return {"id": r["id"], "version": r["version"], "kind": kind, "name": pick(r["name"]),
            "unit": pick(r["unit"]), "definition": pick(r["definition"]),
            "formula": r["formula"], "status": pick(r["status"]),
            "missing_policy": r["missing_policy"],
            "display_decimals": r["display_decimals"],
            "unit_multipliers": r.get("unit_multipliers"),
            "columns": [{**c, "label": pick(c["label"])} for c in r.get("columns", [])],
            "question": r.get("question"),
            "parameters": {k: r[k] for k in ("cell_columns", "keep", "by") if k in r},
            "value_source": "reconstruction"}


def _run_published(conn, r: dict, cells: dict, *, year, areas, lang) -> dict:
    """INS's published values; the reconstruction, when its sources have the
    year, rides along as a cross-check (never as the value)."""
    from app.services import generation
    from app.services.concept_search import dataset_facts
    pub = r["published"]
    counties = _county_ids(conn, source_specs(r)[0]["dataset"])
    probe = compute_published(cells, counties, year=year, areas=areas)
    try:
        rec = _run_reconstruction(conn, r, year=probe["year"], lang=lang)
    except RecipeError:
        rec = None             # e.g. SOM103A before 2010: no SOM101E counts
    out = compute_published(cells, counties, year=probe["year"], areas=areas, reconstruction=rec,
                            decimals=r["display_decimals"])
    yc = [c for (g, y), c in cells.items() if y == out["year"]]
    facts = dataset_facts(conn, pub["matrix"], lang) or {}
    gen = rec["generation"] if rec else (lambda g: {"id": g["id"], "status": g["status"],
                                                    "built_at": g["built_at"]})(generation.current())
    published = {
        "role": "published", "dataset": pub["matrix"], "title": facts.get("title"),
        "definition": facts.get("definition"), "unit": yc[0]["unit"] if yc else None,
        "source_updated": yc[0]["ins_updated"] if yc else None, "coverage": facts.get("coverage"),
        "concept": source_specs(r)[0].get("concept"), "reference": _pick(pub.get("reference"), lang),
        "query": {"dataset": pub["matrix"], "cells": pub.get("cells"), "year": out["year"],
                  "query_id": yc[0]["query_id"] if yc else None,
                  "fetched_at": yc[0]["fetched_at"] if yc else None,
                  "sha256": yc[0]["sha256"] if yc else None},
        "aggregation": {"outcome": "valid_total", "method": "source_total"},
        "quality": None, "generation": gen, "contract": rec["sources"][0].get("contract") if rec else None}
    info = _recipe_info(r, r.get("kind", "ratio"), lang)
    info.update(value_source="ins_published", status=_pick(pub.get("status") or r["status"], lang),
                formula=pub.get("formula", r["formula"]), reconstruction_formula=r["formula"])
    inputs = {"published": [["REF_AREA", "TIME_PERIOD", "OBS_VALUE"]]
              + [[c["label"], c["year"], c["value"]] for c in sorted(yc, key=lambda c: c["label"])]}
    if rec:
        inputs.update(rec["inputs"])
    return {"recipe": info, "request": {"year": year, "areas": areas or None, "lang": lang},
            **out, "sources": [published] + (rec["sources"] if rec else []),
            "inputs": inputs, "generation": gen}


def _run_reconstruction(conn, r: dict, *, year=None, areas=None, lang: str = "ro") -> dict:
    kind = r.get("kind", "ratio")
    pick = lambda d: _pick(d, lang)
    if kind == "ratio":
        a_, b_ = _source(conn, r["numerator"], lang), _source(conn, r["denominator"], lang)
        out = compute(a_["rows"], b_["rows"], num_unit=a_["unit"], den_unit=b_["unit"],
                      multipliers=r["unit_multipliers"], year=year, areas=areas)
        for row in out["rows"]:
            row["value"] = row["intensity"]
        inputs = {"stays": a_["rows"], "population": b_["rows"]}
    elif kind in ("weighted_mean", "rate_from_counts"):
        # these sources are too large for one unfiltered query: pick the year first
        sa, sb = source_specs(r)
        y, years_all = _common_year(_years(conn, sa["dataset"]), _years(conn, sb["dataset"]), year)
        a_, b_ = _source(conn, sa, lang, y), _source(conn, sb, lang, y)
    if kind == "weighted_mean":
        out = compute_weighted_mean((a_["columns"], a_["table"]), (b_["columns"], b_["table"]),
                                    cell_cols=r["cell_columns"], keep=r.get("keep") or {},
                                    year=y, areas=areas)
        inputs = {"values": [a_["columns"]] + a_["table"], "weights": [b_["columns"]] + b_["table"]}
    elif kind == "rate_from_counts":
        out = compute_rate_from_counts((a_["columns"], a_["table"]), (b_["columns"], b_["table"]),
                                       by=r["by"], year=y, areas=areas)
        inputs = {"rates": [a_["columns"]] + a_["table"], "counts": [b_["columns"]] + b_["table"]}
    elif kind != "ratio":
        raise RecipeError("unknown_recipe", f"recipe kind {kind!r} is not supported")
    if kind != "ratio":
        out["years_available"] = years_all     # the sources were read for one year only
    sources = []
    for src in (a_, b_):
        sources.append({k: (pick(v) if k == "reference" else v) for k, v in src.items()
                        if k not in ("rows", "table", "columns")})
    return {"recipe": _recipe_info(r, kind, lang),
            "request": {"year": year, "areas": areas or None, "lang": lang},
            **out, "sources": sources, "inputs": inputs,
            "generation": b_["generation"]}
