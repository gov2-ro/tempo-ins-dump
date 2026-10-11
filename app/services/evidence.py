"""Portable evidence bundles (PA-03a/b): what was asked, what was computed,
from which inputs, by which method, from whose data.

A bundle is a ZIP that stays usable offline: manifest.json (schema, versions,
generation, sha256 of every other file), selection.json, result.csv,
method.json, attribution.json, README.txt and, for a recipe, the reduced input
series plus recompute.py (standard library only). Values are unrounded and the
display rounding is recorded. A selection that cannot be exported completely
is refused, never cut. No keys, paths or logs go in.

A live link re-runs its selection on whatever generation is current; a bundle
keeps the answer as it was. README.txt says so.
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
import os
import zipfile
from datetime import datetime, timezone

SCHEMA = "tempo-evidence/1"
INS_URL = "http://statistici.insse.ro:8077/tempo-online/"
MAX_INPUT_ROWS = 200_000      # raw input rows a single-source bundle may carry


class EvidenceError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status, self.message = status, message


def _csv(header, rows) -> str:
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(header)
    for r in rows:
        w.writerow(["" if v is None else (repr(v) if isinstance(v, float) else v) for v in r])
    return buf.getvalue()


def _json(obj) -> str:
    return json.dumps(obj, ensure_ascii=False, indent=1, default=str) + "\n"


def _zip(files: dict[str, str], manifest: dict) -> bytes:
    """Write files plus a manifest holding each file's sha256."""
    manifest = {**manifest, "files": {n: hashlib.sha256(c.encode("utf-8")).hexdigest()
                                      for n, c in sorted(files.items())}}
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for name, content in [("manifest.json", _json(manifest)), *sorted(files.items())]:
            info = zipfile.ZipInfo(name, date_time=(2026, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            z.writestr(info, content.encode("utf-8"))
    return buf.getvalue()


def _manifest(kind: str, generation: dict | None, contract: str | None, extra=None) -> dict:
    return {"schema": SCHEMA, "kind": kind,
            "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "app_version": os.environ.get("TEMPO_BUILD") or "unknown",
            "query_contract": contract, "generation": generation, **(extra or {})}


def _attribution(sources: list[dict]) -> dict:
    today = datetime.now(timezone.utc).date().isoformat()
    return {
        "sources": [{"dataset": s["dataset"], "title": s.get("title"),
                     "publisher": "Institutul Național de Statistică (INS), TEMPO Online",
                     "url": INS_URL, "source_updated": s.get("source_updated")} for s in sources],
        "reuse_terms": None,
        "reuse_terms_note": "Not verified for this bundle; consult INS terms before republishing.",
        "citation": "; ".join(
            f"INS, TEMPO Online, {s['dataset']} — {s.get('title') or ''}"
            + (f" (actualizat {s['source_updated']})" if s.get("source_updated") else "")
            for s in sources) + f". Accesat {today} prin INS+.",
    }


README_LIVE = (
    "A live link re-runs this selection on the data the site serves at the time;\n"
    "if the source is revised, the live answer changes. This bundle keeps the\n"
    "answer as it was computed, with the generation id in manifest.json.\n")


# ------------------------------------------------------------------ single source

def dataset_bundle(conn, code: str, filters, group_by, approximate: bool, lang: str,
                   link: str) -> bytes:
    """Bundle for one /data selection: result rows plus, for an aggregation,
    the raw observations it was computed from."""
    from app.config import MAX_DATA_ROWS
    from app.services.concept_search import dataset_facts
    from app.services.data_query import QueryError, run_query
    from app.services.query_builder import (build_export_query_params, resolve_parquet_schema,
                                            adapt_to_parquet)
    try:
        res = run_query(conn, code, filters, group_by, MAX_DATA_ROWS, approximate=approximate)
    except QueryError as e:
        raise EvidenceError(e.status, e.message)
    if res.get("truncated") or res.get("time_windowed") or res.get("partial_period_dropped"):
        raise EvidenceError(413, "The selection is larger than an evidence bundle can hold "
                                 "completely. Narrow it (period or area) and try again.")
    facts = dataset_facts(conn, code, lang) or {"title": code}
    agg = res.get("aggregation")
    files = {
        "selection.json": _json({
            "dataset": code, "link": link, "lang": lang,
            "requested": {"filters": filters, "group_by": group_by, "approximate": approximate},
            "effective": {"filters": (agg or {}).get("filters"), "levels": (agg or {}).get("levels")},
            "periods_in_result": sorted({str(r[res["columns"].index("TIME_PERIOD")])
                                         for r in res["rows"]}) if "TIME_PERIOD" in res["columns"] else None,
        }),
        "method.json": _json({
            "kind": "aggregation" if agg else "raw_observations",
            "decision": agg, "quality": res.get("quality"),
            "definition": facts.get("definition"), "unit": facts.get("unit"),
            "rounding": "values are unrounded; the site rounds only for display",
            "unavailable": bool(res.get("unavailable")),
        }),
        "attribution.json": _json(_attribution([{"dataset": code, **facts}])),
    }
    files["result.csv"] = _csv(res["columns"], res["rows"])
    if agg and not res.get("unavailable"):
        # The raw observations behind the aggregation, so it can be recomputed.
        schema = resolve_parquet_schema(conn, code)
        dims = [{"dim_column_name": d[0]} for d in conn.execute(
            "SELECT DISTINCT dim_column_name FROM dimensions WHERE matrix_code = ? ORDER BY 1",
            [code]).fetchall()]
        eff = {k: list(v) for k, v in (agg.get("filters") or {}).items()}
        dims, _, eff = adapt_to_parquet(schema, dims, None, eff)
        csql, cparams = build_export_query_params(code, dims, eff, value_column=schema["value_column"],
                                                  count_only=True)
        n = conn.execute(csql, cparams).fetchone()[0]
        if n > MAX_INPUT_ROWS:
            raise EvidenceError(413, f"The aggregation reads {n} observations, more than an "
                                     f"evidence bundle carries ({MAX_INPUT_ROWS}). Narrow the selection.")
        sql, params = build_export_query_params(code, dims, eff, value_column=schema["value_column"])
        cur = conn.execute(sql, params)
        cols = [schema["to_sdmx"].get(d["dim_column_name"], d["dim_column_name"]) for d in dims] + ["OBS_VALUE"]
        files["inputs/observations.csv"] = _csv(cols, cur.fetchall())
    files["README.txt"] = (
        f"Evidence for {code}: {facts.get('title')}\n\n"
        "result.csv           the answer, unrounded\n"
        + ("inputs/observations.csv  every source observation the aggregation used\n" if agg else "")
        + "selection.json       what was asked and the filters actually applied\n"
          "method.json          aggregation decision, data quality, definition, unit\n"
          "attribution.json     source, update date and a citation\n"
          "manifest.json        versions, generation id and sha256 of each file\n\n" + README_LIVE)
    return _zip(files, _manifest("dataset", res.get("generation"), res.get("contract"),
                                 {"dataset": code}))


# ------------------------------------------------------------------ recipe

RECOMPUTE_PY = '''"""Recompute result.csv from the bundled inputs, offline, standard library only.

  python recompute.py        prints the recomputed rows and checks result.csv
"""
import csv, json, math, os, re, sys, unicodedata

here = os.path.dirname(os.path.abspath(__file__))
method = json.load(open(os.path.join(here, "method.json"), encoding="utf-8"))
year = method["year"]
mult = method["unit_multipliers"]

def gid(label):
    s = unicodedata.normalize("NFKD", label.strip())
    s = "".join(c for c in s if not unicodedata.combining(c)).lower()
    return re.sub(r"[^a-z0-9]+", "-", s).strip("-")

def series(name, unit):
    out = {}
    with open(os.path.join(here, "inputs", name), encoding="utf-8") as f:
        for r in csv.DictReader(f):
            if r["TIME_PERIOD"][-4:] != year or r["OBS_VALUE"] == "":
                continue
            out[gid(r["REF_AREA"])] = (r["REF_AREA"].strip(), float(r["OBS_VALUE"]) * mult[unit])
    return out

stays = series("stays.csv", method["units"]["stays"])
pop = series("population.csv", method["units"]["population"])
rows = []
for g, (label, p) in pop.items():
    if g in stays and p > 0 and math.isfinite(p):
        rows.append((label, stays[g][1], p, stays[g][1] / p))
rows.sort(key=lambda r: (-r[3], r[0]))
with open(os.path.join(here, "result.csv"), encoding="utf-8") as f:
    published = {r["label"]: float(r["intensity"]) for r in csv.DictReader(f)}
bad = [r for r in rows if r[0] not in published or abs(published[r[0]] - r[3]) > 1e-12 * max(1, r[3])]
for r in rows:
    print(f"{r[0]},{r[1]!r},{r[2]!r},{r[3]!r}")
print(f"recomputed {len(rows)} rows; {len(bad)} differ from result.csv", file=sys.stderr)
sys.exit(1 if bad or len(rows) != len(published) else 0)
'''


def recipe_bundle(result: dict, link: str) -> bytes:
    r = result["recipe"]
    src = {s["role"]: s for s in result["sources"]}
    year = result["year"]
    files = {
        "selection.json": _json({"recipe": r["id"], "recipe_version": r["version"], "link": link,
                                 "requested": result["request"], "resolved_year": year,
                                 "years_available": result["years_available"],
                                 "source_queries": {k: v["query"] for k, v in src.items()}}),
        "method.json": _json({
            "recipe": r["id"], "version": r["version"], "formula": r["formula"],
            "definition": r["definition"], "unit": r["unit"], "year": year,
            "reference_dates": {k: v.get("reference") for k, v in src.items()},
            "units": {k: v.get("unit") for k, v in src.items()},
            "unit_multipliers": r["unit_multipliers"],
            "missing_policy": r["missing_policy"], "excluded": result["excluded"],
            "display_rounding": f"{r['display_decimals']} decimals (display only)",
            "source_aggregation": {k: v["aggregation"] for k, v in src.items()},
            "source_quality": {k: v["quality"] for k, v in src.items()},
            "status": r["status"],
        }),
        "attribution.json": _json(_attribution(result["sources"])),
        "result.csv": _csv(["rank", "geo_id", "label", "year", "stays", "population", "intensity"],
                           [[x["rank"], x["geo_id"], x["label"], x["year"], x["stays"],
                             x["population"], x["intensity"]] for x in result["rows"]]),
        "recompute.py": RECOMPUTE_PY,
    }
    for role, rows in result["inputs"].items():
        files[f"inputs/{role}.csv"] = _csv(["REF_AREA", "TIME_PERIOD", "OBS_VALUE"], rows)
    files["README.txt"] = (
        f"{r['name']} — {year}\n\n{r['definition']}\n\nFormula: {r['formula']}\n\n"
        "result.csv              ranking, unrounded (stays, population, intensity)\n"
        "inputs/stays.csv        overnight stays per county and year, as the site computed them\n"
        "inputs/population.csv   resident population on 1 January per county and year\n"
        "method.json             formula, units, reference dates, exclusions, source decisions\n"
        "selection.json          what was asked, the year used and the source queries\n"
        "attribution.json        sources, update dates and a citation\n"
        "recompute.py            python recompute.py  rebuilds result.csv from inputs/, offline\n"
        "manifest.json           versions, generation id and sha256 of each file\n\n"
        "The inputs are the validated series (one value per county and year), not raw\n"
        "source observations; they come from the generation named in manifest.json.\n\n"
        + README_LIVE)
    return _zip(files, _manifest("recipe", result.get("generation"),
                                 (result["sources"][0] or {}).get("contract"),
                                 {"recipe": r["id"], "recipe_version": r["version"]}))
