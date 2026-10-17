"""`tempo-evidence/1` bundle of a compare_periods result (AT-01e).

Same container as the dataset and recipe bundles (`evidence._zip/_manifest`):
manifest.json with the generation and a sha256 of every file, the normalized
request and exact source query, the COMPLETE ranking (every eligible entity of
every interval, not the top_k preview), every exclusion, the validated endpoint
table and `recompute.py` (standard library only), which recomputes absolute,
percent, eligibility and ranks from the endpoint table and checks them against
result.csv exactly.

The endpoint table is what the site's shared query returned for the declared
source query (aggregated by the shared policy), not raw INS observations.
"""
from __future__ import annotations

import json
from urllib.parse import quote, urlencode

from app.services import evidence as ev
from app.services.tools import contract

MAX_URL_BYTES = 4096


def live_link(args: dict, *, evidence: bool = False, expected_generation: str | None = None) -> str | None:
    """URL of the JSON route (live rerun) or the evidence route for a normalized
    request (`ComparePeriodsArgs.model_dump(by_alias=True)`); None when it would
    exceed 4 KiB, because a shorter link would not be the same selection."""
    q = {"dataset": args["dataset"],
         "entity_columns": contract.dumps(args["entity_columns"]),
         "intervals": contract.dumps(args["intervals"])}
    if args.get("filters"):
        q["filters"] = contract.dumps(args["filters"])
    q.update(metric=args.get("metric", "absolute"), order=args.get("order", "asc"),
             top_k=str(args.get("top_k", 20)), lang=args.get("lang", "ro"))
    if args.get("entity_class") not in (None, "all"):       # the default class adds nothing
        q["entity_class"] = args["entity_class"]
    if expected_generation:
        q["expected_generation"] = expected_generation
    path = "/api/period-changes" + ("/evidence" if evidence else "")
    url = contract.public_url(path + "?" + urlencode(q, quote_via=quote))
    return url if len(url.encode("utf-8")) <= MAX_URL_BYTES else None


RECOMPUTE_PY = '''"""Recompute result.csv and exclusions.csv from the bundled endpoint table, offline.

  python recompute.py      prints the recomputed ranking and checks result.csv

Standard library only. inputs/endpoints.csv holds aggregated endpoints (one value
per entity and year) computed by the site's shared query from the source query in
selection.json; it is not a set of raw INS observations. method.json names the key
columns, intervals, metric, order and the entities treated as totals.
Exit status 0: every interval's ranking and exclusions equal the bundle's. 1: they differ.
"""
import csv, json, math, os, sys

here = os.path.dirname(os.path.abspath(__file__))
method = json.load(open(os.path.join(here, "method.json"), encoding="utf-8"))
cols = method["key_columns"]
metric, order = method["ranking"]["metric"], method["ranking"]["order"]
aggregate = {tuple(k) for k in method["aggregate_rows"]}
sign = 1 if order == "asc" else -1


def fmt(v):
    return "" if v is None else repr(v)


table = {}
with open(os.path.join(here, "inputs", "endpoints.csv"), encoding="utf-8", newline="") as f:
    for r in csv.DictReader(f):
        table[(tuple(r[c] for c in cols), r["year"])] = None if r["value"] == "" else float(r["value"])
entities = sorted({k for k, _ in table})


def endpoint(key, year):
    if (key, year) not in table:
        return "no_observation", None
    v = table[(key, year)]
    if v is None:
        return "value_missing", None
    if not math.isfinite(v):
        return "value_not_finite", None
    return None, v


result_head = ["interval_from", "interval_to", "rank", *cols, "from_value", "to_value",
               "absolute", "percent", "percent_note"]
excl_head = ["interval_from", "interval_to", *cols, "reason", "missing", "from_value",
             "to_value", "absolute"]
result_rows, excl_rows = [], []
for iv in method["intervals"]:
    yf, yt = iv["from"], iv["to"]
    ranked = []
    for key in entities:
        if key in aggregate:
            excl_rows.append([yf, yt, *key, "aggregate_row", "", "", "", ""])
            continue
        pf, f = endpoint(key, yf)
        pt, t = endpoint(key, yt)
        if pf or pt:
            bad = [(n, p) for n, p in (("from", pf), ("to", pt)) if p]
            excl_rows.append([yf, yt, *key, bad[0][1], ";".join(n for n, _ in bad), "", "", ""])
            continue
        absolute = t - f
        if not math.isfinite(absolute):
            excl_rows.append([yf, yt, *key, "value_not_finite", "", fmt(f), fmt(t), ""])
            continue
        percent, note = None, ""
        if f > 0:
            percent = 100 * absolute / f
            if not math.isfinite(percent):
                percent, note = None, "value_not_finite"
        elif f == 0:
            note = "zero_baseline"
        else:
            note = "nonpositive_baseline"
        if metric == "percent" and percent is None:
            excl_rows.append([yf, yt, *key, note or "value_not_finite", "", fmt(f), fmt(t), fmt(absolute)])
            continue
        ranked.append((sign * (percent if metric == "percent" else absolute), key, f, t, absolute, percent, note))
    ranked.sort(key=lambda x: (x[0], x[1]))
    for i, (_, key, f, t, absolute, percent, note) in enumerate(ranked, 1):
        result_rows.append([yf, yt, str(i), *key, fmt(f), fmt(t), fmt(absolute), fmt(percent), note])
        print(f"{yf},{yt},{i},{'/'.join(key)},{absolute!r},{percent!r}")


def read(name):
    with open(os.path.join(here, name), encoding="utf-8", newline="") as f:
        return list(csv.reader(f))


got_result, got_excl = read("result.csv"), read("exclusions.csv")
bad_result = got_result != [result_head] + result_rows
bad_excl = got_excl != [excl_head] + excl_rows
print(f"recomputed {len(result_rows)} ranked rows and {len(excl_rows)} exclusions over "
      f"{len(method['intervals'])} interval(s); result.csv {'DIFFERS' if bad_result else 'matches'}, "
      f"exclusions.csv {'DIFFERS' if bad_excl else 'matches'}", file=sys.stderr)
sys.exit(1 if bad_result or bad_excl else 0)
'''


# The city class (AQ-05A) adds one step to the offline script: classify every entity of
# inputs/endpoints.csv from the bundled catalogue BEFORE eligibility and ranks, then check
# classification.csv. The default script above is untouched, so bundles without a class keep
# their exact recompute.py.
_CLASS_ANCHOR = "entities = sorted({k for k, _ in table})\n"
_EXIT_ANCHOR = "sys.exit(1 if bad_result or bad_excl else 0)\n"
_CLASS_STEP = '''# entity class "cities": membership comes from the bundled GOS102A catalogue, before any
# eligibility, rank or top_k. A locality value is a member when its leading integer (SIRUTA) is a
# catalogue key; totals are outside the class; an inexact or shared SIRUTA refuses.
import re
catalogue = {}
with open(os.path.join(here, "inputs", "city_catalogue.csv"), encoding="utf-8", newline="") as f:
    for r in csv.DictReader(f):
        catalogue[r["siruta"]] = r["label"]
loc = cols.index("REF_AREA_2")
class_rows, entities, owner = [], [], {}
for key in sorted({k for k, _ in table}):
    if key in aggregate:
        class_rows.append([*key, "", "aggregate_row"])
        continue
    m = re.match(r"^(\\d+)\\s+\\S", key[loc].strip())
    if m is None:
        sys.exit("a locality value has no exact SIRUTA key: the classification is refused")
    siruta = str(int(m[1]))
    if siruta not in catalogue:
        class_rows.append([*key, siruta, "outside_class"])
        continue
    if siruta in owner:
        sys.exit("one SIRUTA key appears under several entities: the classification is refused")
    owner[siruta] = key
    entities.append(key)
    class_rows.append([*key, siruta, "member"])
'''
_CLASS_CHECK = '''bad_class = read("classification.csv") != [[*cols, "siruta", "class"]] + class_rows
print(f"classified {len(class_rows)} entities ({len(entities)} municipalities/towns in the catalogue); "
      f"classification.csv {'DIFFERS' if bad_class else 'matches'}", file=sys.stderr)
sys.exit(1 if bad_result or bad_excl or bad_class else 0)
'''
assert RECOMPUTE_PY.count(_CLASS_ANCHOR) == 1 and RECOMPUTE_PY.count(_EXIT_ANCHOR) == 1
RECOMPUTE_CITIES_PY = RECOMPUTE_PY.replace(_CLASS_ANCHOR, _CLASS_STEP).replace(_EXIT_ANCHOR, _CLASS_CHECK)


def _result_head(key_cols):
    return ["interval_from", "interval_to", "rank", *key_cols, "from_value", "to_value",
            "absolute", "percent", "percent_note"]


def bundle(result: dict, link: str | None = None) -> bytes:
    """ZIP of a full `period_changes.run` result."""
    code, key_cols = result["dataset"], result["key_columns"]
    prov = result["provenance"]
    src = prov["sources"][0]
    ents = lambda e: [e["entity"][c] for c in key_cols]

    result_rows, excl_rows = [], []
    for iv in result["intervals"]:
        for r in iv["rows"]:
            result_rows.append([iv["from"], iv["to"], r["rank"], *ents(r), r["from_value"],
                                r["to_value"], r["absolute"], r["percent"], r.get("percent_note")])
        for x in iv["excluded"]:
            excl_rows.append([iv["from"], iv["to"], *ents(x), x["reason"],
                              ";".join(x["missing"]), x.get("from_value"), x.get("to_value"),
                              x.get("absolute")])

    selection = result["selection"]
    files = {
        "selection.json": ev._json({
            "dataset": code, "link": link, "lang": result["lang"],
            "requested": result["args"],
            "normalized": selection,
            "key_columns": key_cols, "period_column": result["time_column"],
            "periods": result["periods"],
            "source_query": result["source_query"],
            "effective": {"filters": (prov.get("effective_selection") or {}).get("filters"),
                          "levels": (prov.get("effective_selection") or {}).get("levels")},
        }),
        "result.csv": ev._csv(_result_head(key_cols), result_rows),
        "exclusions.csv": ev._csv(["interval_from", "interval_to", *key_cols, "reason", "missing",
                                   "from_value", "to_value", "absolute"], excl_rows),
        "inputs/endpoints.csv": ev._csv(
            [*key_cols, "year", "value"], [[*k, y, v] for k, y, v in result["endpoints"]]),
        "method.json": ev._json({
            "kind": "period_changes", "dataset": code, "definition": src.get("definition"),
            "unit": result["unit"], "key_columns": key_cols, "entity_columns": result["entity_columns"],
            "period_column": result["time_column"],
            "intervals": [{"from": i["from"], "to": i["to"]} for i in result["intervals"]],
            "formulas": {"absolute": "to_value - from_value",
                         "percent": "100 * absolute / from_value, only when from_value > 0"},
            "percent_rules": {
                "zero_baseline": "from_value == 0: percent is null (absolute is valid)",
                "nonpositive_baseline": "from_value < 0: percent is null (absolute is valid)",
                "percent_metric": "entities without a percent are not ranked and are listed in "
                                  "exclusions.csv with that reason"},
            "eligibility": "an entity is eligible for an interval when it has a finite value at "
                           "both endpoint years; a missing row is no_observation, a NULL value is "
                           "value_missing (suppressed or not available in the source); neither is "
                           "ever filled with zero",
            "ranking": {"metric": result["metric"], "order": result["order"],
                        "tie_break": "full entity key (key_columns order), ascending string "
                                     "comparison",
                        "rank": "ordinal position over every eligible entity; not a measure of "
                                "statistical significance",
                        "top_k_in_request": result["top_k"],
                        "note": "result.csv holds every ranked entity, not only top_k"},
            "aggregate_rows": [list(k) for k in result["aggregate_keys"]],
            "aggregation": result["source_response"].get("aggregation"),
            "quality": result["source_response"].get("quality"),
            "scope": prov.get("scope"),
            "notes": src.get("notes"),
            "warnings": result["warnings"],
            "rounding": "values are unrounded; the site rounds only for display",
            "endpoints": "aggregated endpoints computed by the site's shared query "
                         "(data_query.run_query: aggregation policy and grain gate) from the "
                         "source_query in selection.json; not raw INS observations",
        }),
        "attribution.json": ev._json(ev._attribution([{
            "dataset": code, "title": src.get("metric"), "source_updated": src.get("source_updated")}])),
        "recompute.py": RECOMPUTE_PY,
    }
    files["README.txt"] = (
        f"Period changes for {code}: {src.get('metric') or code}\n\n"
        f"Metric: {result['metric']} ({result['order']}); unit: {result['unit'] or 'unknown'}.\n"
        "Rank is an ordinal position, not a claim of statistical significance.\n\n"
        "result.csv              every ranked entity of every interval, unrounded\n"
        "exclusions.csv          every entity that was not ranked, with the reason\n"
        "inputs/endpoints.csv    aggregated endpoints computed by the site's shared query from the\n"
        "                        declared source query (selection.json), NOT raw INS observations;\n"
        "                        verify them by running that source query\n"
        "selection.json          the normalized request, the exact source query and the periods\n"
        "method.json             formulas, percent and baseline rules, ranking, aggregation decision,\n"
        "                        data quality, scope and notes\n"
        "attribution.json        source, update date and a citation\n"
        "recompute.py            python recompute.py  recomputes absolute, percent, eligibility and\n"
        "                        ranks from inputs/endpoints.csv and checks result.csv (exit 0 = equal)\n"
        "manifest.json           versions, generation id and sha256 of each file\n\n"
        "Stable labels or codes do not prove unchanged territory; boundary continuity is not\n"
        "verified (see warnings in method.json).\n\n" + ev.README_LIVE)
    if result.get("entity_class") == "cities":
        _add_city_class(files, result, key_cols)
    return ev._zip(files, ev._manifest("period_changes", result.get("generation"),
                                       (result["source_response"] or {}).get("contract"),
                                       {"dataset": code}))


def _add_city_class(files: dict, result: dict, key_cols) -> None:
    """The membership input of entity_class "cities": the catalogue, the class of every entity
    of the endpoint table and the rule, so recompute.py can reproduce the classification."""
    from app.services.tools import ranking
    from app.services.period_changes import CLASS_WARNING
    prov = result["provenance"]
    cat = result["class_catalogue"]
    cls = result["classification"]
    ref = next((s for s in prov["sources"] if s.get("role") == "entity_classification"), {})
    files["inputs/city_catalogue.csv"] = ev._csv(
        ["siruta", "label"], [[k, cat[k]] for k in sorted(cat, key=int)])
    files["classification.csv"] = ev._csv(
        [*key_cols, "siruta", "class"],
        [[*k, siruta or "", c] for k, (siruta, c) in sorted(result["key_classes"].items())])
    method = json.loads(files["method.json"])
    method["entity_class"] = {
        "class": "cities", "wording": "municipalities and towns in the referenced catalogue",
        "reference": {"dataset": ranking.CITY_CATALOGUE, "title": ref.get("metric"),
                      "source_updated": ref.get("source_updated"), "key": "SIRUTA",
                      "file": "inputs/city_catalogue.csv", "generation": cls["generation"]},
        "rule": "SIRUTA = the leading integer of the REF_AREA_2 value; an entity is a city when its "
                "SIRUTA is a key of the catalogue; total/aggregate rows are outside the class; a "
                "locality value without an exact SIRUTA, or one SIRUTA under two entities, refuses",
        "applied": "before eligibility, ranks and top_k: result.csv, exclusions.csv and every count "
                   "cover catalogue cities only; inputs/endpoints.csv keeps every entity so the "
                   "classification can be reproduced (classification.csv lists the outcome)",
        "temporal_status": cls["temporal_status"], "qualification": CLASS_WARNING,
        "member_count": cls["member_count"], "outside_class_count": cls["outside_class_count"],
        "catalogue_count": cls["catalogue_count"]}
    files["method.json"] = ev._json(method)
    files["recompute.py"] = RECOMPUTE_CITIES_PY
    files["attribution.json"] = ev._json(ev._attribution([
        {"dataset": result["dataset"], "title": prov["sources"][0].get("metric"),
         "source_updated": prov["sources"][0].get("source_updated")},
        {"dataset": ranking.CITY_CATALOGUE, "title": ref.get("metric"),
         "source_updated": ref.get("source_updated")}]))
    files["README.txt"] = files["README.txt"].replace(
        "recompute.py            python recompute.py  recomputes absolute, percent, eligibility and\n"
        "                        ranks from inputs/endpoints.csv and checks result.csv (exit 0 = equal)\n",
        "recompute.py            python recompute.py  classifies the entities with the catalogue, then\n"
        "                        recomputes absolute, percent, eligibility and ranks from\n"
        "                        inputs/endpoints.csv and checks result.csv, exclusions.csv and\n"
        "                        classification.csv (exit 0 = equal)\n"
        "inputs/city_catalogue.csv  INS GOS102A's municipalities and towns (SIRUTA, label)\n"
        "classification.csv      the class of every entity of inputs/endpoints.csv\n"
    ).replace(
        "Stable labels or codes do not prove unchanged territory;",
        "Entity class: cities = " + CLASS_WARNING + "\n\n"
        "Stable labels or codes do not prove unchanged territory;")
