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

def _source(conn, spec: dict, lang: str) -> dict:
    """Run one source through the shared query; refuse anything incomplete."""
    from app.config import MAX_DATA_ROWS
    from app.services.concept_search import dataset_facts
    from app.services.data_query import QueryError, run_query
    code = spec["dataset"]
    try:
        res = run_query(conn, code, dict(spec.get("filters") or {}), list(spec["group_by"]),
                        MAX_DATA_ROWS)
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
            "unit": facts.get("unit"), "title": facts.get("title"),
            "definition": facts.get("definition"), "source_updated": facts.get("source_updated"),
            "coverage": facts.get("coverage"), "concept": spec.get("concept"),
            "reference": spec.get("reference"),
            "query": {"dataset": code, "filters": spec.get("filters") or {},
                      "group_by": spec["group_by"], "approximate": False},
            "aggregation": agg, "quality": res.get("quality"), "generation": res.get("generation"),
            "contract": res.get("contract")}


def run(conn, recipe_id: str, *, year=None, areas=None, lang: str = "ro") -> dict:
    recipes = load_recipes()
    if recipe_id not in recipes:
        raise RecipeError("unknown_recipe", f"no recipe {recipe_id!r}")
    r = recipes[recipe_id]
    num = _source(conn, r["numerator"], lang)
    den = _source(conn, r["denominator"], lang)
    out = compute(num["rows"], den["rows"], num_unit=num["unit"], den_unit=den["unit"],
                  multipliers=r["unit_multipliers"], year=year, areas=areas)
    pick = lambda d: d.get(lang) or d.get("ro") if isinstance(d, dict) else d
    sources = []
    for s in (num, den):
        sources.append({k: (pick(v) if k == "reference" else v) for k, v in s.items() if k != "rows"})
    return {"recipe": {"id": r["id"], "version": r["version"], "name": pick(r["name"]),
                       "unit": pick(r["unit"]), "definition": pick(r["definition"]),
                       "formula": r["formula"], "status": pick(r["status"]),
                       "missing_policy": r["missing_policy"],
                       "display_decimals": r["display_decimals"],
                       "unit_multipliers": r["unit_multipliers"]},
            "request": {"year": year, "areas": areas or None, "lang": lang},
            **out, "sources": sources, "inputs": {"stays": num["rows"], "population": den["rows"]},
            "generation": den["generation"]}
