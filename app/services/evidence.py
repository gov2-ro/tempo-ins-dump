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


RECOMPUTE_TABLES_PY = '''"""Recompute result.csv from the bundled inputs, offline, standard library only.

  python recompute.py        prints the recomputed rows and checks result.csv

method.json names the recipe kind and its parameters:
  weighted_mean     value = sum(value x weight) / sum(weight) per area, over the
                    cells whose columns match `keep`
  rate_from_counts  rate = 100 x sum(U) / sum(U / (rate / 100)) per area, over `by`
"""
import csv, json, os, re, sys, unicodedata

here = os.path.dirname(os.path.abspath(__file__))
method = json.load(open(os.path.join(here, "method.json"), encoding="utf-8"))
year, kind, p = method["year"], method["kind"], method["parameters"]

def gid(label):
    s = unicodedata.normalize("NFKD", label.strip())
    s = "".join(c for c in s if not unicodedata.combining(c)).lower()
    return re.sub(r"[^a-z0-9]+", "-", s).strip("-")

def table(name, cols, keep=None):
    out = {}
    path = os.path.join(here, "inputs", name)
    if not os.path.exists(path) and method.get("value_source") == "ins_published":
        return out             # no reconstruction for this year: INS values only
    with open(path, encoding="utf-8") as f:
        for r in csv.DictReader(f):
            if re.sub(r"^Anul\\s+", "", r["TIME_PERIOD"].strip()) != year:
                continue
            if keep and any(not re.search(rx, r[c]) for c, rx in keep.items()):
                continue
            v = None if r["OBS_VALUE"] == "" else float(r["OBS_VALUE"])
            out[(gid(r["REF_AREA"]), tuple(r[c] for c in cols))] = (r["REF_AREA"].strip(), v)
    return out

rows = []
if kind == "weighted_mean":
    cols = p["cell_columns"]
    val, wt = table("values.csv", cols, p["keep"]), table("weights.csv", cols, p["keep"])
    areas = {}
    for (g, cell), (label, w) in wt.items():
        areas.setdefault(g, [label, []])[1].append((w, val.get((g, cell), (None, None))[1]))
    for g, (label, cells) in areas.items():
        used = [(v, w) for w, v in cells if w]
        tw = sum(w for _, w in used)
        if used and all(v is not None for v, _ in used) and tw > 0:
            rows.append((label, sum(v * w for v, w in used) / tw))
elif kind == "rate_from_counts":
    rt, ct = table("rates.csv", [p["by"]]), table("counts.csv", [p["by"]])
    groups = sorted({k[1] for k in rt})
    for g in sorted({k[0] for k in rt}):
        U = A = 0.0
        ok = True
        for grp in groups:
            r, u = rt.get((g, grp), (None, None))[1], ct.get((g, grp), (None, None))[1]
            if r is None or u is None or (r <= 0 and u != 0):
                ok = False
                break
            if r > 0:
                U, A = U + u, A + u / (r / 100)
        if ok and A > 0:
            rows.append((rt[(g, groups[0])][0], 100 * U / A))
else:
    sys.exit(f"unknown recipe kind {kind!r}")

rows.sort(key=lambda r: (-r[1], r[0]))
with open(os.path.join(here, "result.csv"), encoding="utf-8") as f:
    result = list(csv.DictReader(f))
if method.get("value_source") == "ins_published":
    # value = INS's published cell (inputs/published.csv); the reconstruction is
    # only a cross-check and must equal result.csv's `reconstructed` column
    with open(os.path.join(here, "inputs", "published.csv"), encoding="utf-8") as f:
        ins = {r["REF_AREA"].strip(): r["OBS_VALUE"] for r in csv.DictReader(f)}
    wrong = [r["label"] for r in result if r["label"] not in ins or float(ins[r["label"]]) != float(r["value"])]
    print(f"{len(result)} values; {len(wrong)} differ from inputs/published.csv", file=sys.stderr)
    recon = {r["label"]: float(r["reconstructed"]) for r in result if r.get("reconstructed")}
    got = {label: v for label, v in rows}
    bad = [k for k, v in recon.items() if k not in got or abs(got[k] - v) > 1e-9 * max(1, abs(v))]
    for r in rows:
        print(f"{r[0]},{r[1]!r}")
    print(f"recomputed {len(rows)} reconstructions; {len(bad)} differ from result.csv", file=sys.stderr)
    sys.exit(1 if wrong or bad else 0)
published = {r["label"]: float(r["value"]) for r in result}
bad = [r for r in rows if r[0] not in published or abs(published[r[0]] - r[1]) > 1e-9 * max(1, abs(r[1]))]
for r in rows:
    print(f"{r[0]},{r[1]!r}")
print(f"recomputed {len(rows)} rows; {len(bad)} differ from result.csv", file=sys.stderr)
sys.exit(1 if bad or len(rows) != len(published) else 0)
'''


def recipe_bundle(result: dict, link: str) -> bytes:
    r = result["recipe"]
    src = {s["role"]: s for s in result["sources"]}
    year = result["year"]
    ratio = r.get("kind", "ratio") == "ratio"
    files = {
        "selection.json": _json({"recipe": r["id"], "recipe_version": r["version"], "link": link,
                                 "requested": result["request"], "resolved_year": year,
                                 "years_available": result["years_available"],
                                 "source_queries": {k: v["query"] for k, v in src.items()}}),
        "method.json": _json({
            "recipe": r["id"], "version": r["version"], "kind": r.get("kind", "ratio"),
            "parameters": r.get("parameters") or {}, "formula": r["formula"],
            "definition": r["definition"], "unit": r["unit"], "year": year,
            "reference_dates": {k: v.get("reference") for k, v in src.items()},
            "units": {k: v.get("unit") for k, v in src.items()},
            "unit_multipliers": r["unit_multipliers"],
            "missing_policy": r["missing_policy"], "excluded": result["excluded"],
            "display_rounding": f"{r['display_decimals']} decimals (display only)",
            "source_aggregation": {k: v["aggregation"] for k, v in src.items()},
            "source_quality": {k: v["quality"] for k, v in src.items()},
            "status": r["status"],
            "value_source": r.get("value_source", "reconstruction"),
            **({"reconstruction_formula": r["reconstruction_formula"], "check": result.get("check"),
                "aggregates": result.get("aggregates")} if r.get("value_source") == "ins_published" else {}),
        }),
        "attribution.json": _json(_attribution(result["sources"])),
        "recompute.py": RECOMPUTE_PY if ratio else RECOMPUTE_TABLES_PY,
    }
    if ratio:
        files["result.csv"] = _csv(
            ["rank", "geo_id", "label", "year", "stays", "population", "intensity"],
            [[x["rank"], x["geo_id"], x["label"], x["year"], x["stays"], x["population"],
              x["intensity"]] for x in result["rows"]])
        for role, rows in result["inputs"].items():
            files[f"inputs/{role}.csv"] = _csv(["REF_AREA", "TIME_PERIOD", "OBS_VALUE"], rows)
        listing = ("result.csv              ranking, unrounded (stays, population, intensity)\n"
                   "inputs/stays.csv        overnight stays per county and year, as the site computed them\n"
                   "inputs/population.csv   resident population on 1 January per county and year\n")
    else:
        keys = [c["key"] for c in r.get("columns") or []]
        keys = ["value"] + [k for k in keys if k != "value"]
        files["result.csv"] = _csv(["rank", "geo_id", "label", "year", *keys],
                                   [[x["rank"], x["geo_id"], x["label"], x["year"],
                                     *[x.get(k) for k in keys]] for x in result["rows"]])
        listing = ("result.csv              ranking; value = INS's published cell, reconstructed = our cross-check\n"
                   if r.get("value_source") == "ins_published" else
                   "result.csv              ranking, unrounded (value = the recipe's result)\n")
        for role, (head, *rows) in result["inputs"].items():
            files[f"inputs/{role}.csv"] = _csv(head, rows)
            listing += f"inputs/{role}.csv".ljust(24) + f"{(src.get(role) or {}).get('dataset', role)}, " \
                       "the query result the site used (one row per cell)\n"
    files["README.txt"] = (
        f"{r['name']} — {year}\n\n{r['definition']}\n\nFormula: {r['formula']}\n\n"
        + listing +
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
