#!/usr/bin/env python3
"""Record the server's answers for the API paths the static site computes in the
browser (engine/static-api.js), as parity cases for tools/static-engine/api-parity.mjs.

  /api/datasets       sorts x filters x languages x pages, and free-text queries
                      (FTS words, codes, partial words that fall back to LIKE)
  /api/search         the PA-02 judgment questions plus place x concept x year phrases
  /api/datasets/{c}/options   columns x q x pages
  /api/recipes/{id}   years x area subsets x languages
  plus a few recorded paths (they must round-trip unchanged)

One JSON line per case: {"path", "params", "status", "body"}.

  TEMPO_DATA_DIR=<gen>/data python scripts/gen-api-cases.py --out api-cases.jsonl [--codes A,B] [--seed 1]
"""
import argparse
import json
import random
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--out", required=True)
    ap.add_argument("--codes", help="datasets for /options cases (default: a sample)")
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--n", type=int, default=60, help="fuzzed cases per family")
    a = ap.parse_args(argv)
    from fastapi.testclient import TestClient
    from app.main import app
    from app.db import get_conn
    from app.services import concept_search as cs
    from app.services.recipes import load_recipes
    rnd = random.Random(a.seed)
    client = TestClient(app, raise_server_exceptions=False)
    conn = get_conn()
    cases = []

    def add(path, params):
        r = client.get(path, params=params)
        if r.headers.get("content-type", "").startswith("application/zip"):
            import io
            import zipfile
            z = zipfile.ZipFile(io.BytesIO(r.content))
            body = {"__zip": {n: z.read(n).decode("utf-8") for n in z.namelist()
                              if n in ("result.csv", "inputs/observations.csv", "README.txt")}}
        elif r.headers.get("content-type", "").startswith("text/csv"):
            body = r.text
            if len(body) > 2_000_000:          # keep the case file small: compare by hash
                import hashlib
                body = {"__csv_sha256": hashlib.sha256(body.encode("utf-8")).hexdigest(),
                        "__csv_bytes": len(body.encode("utf-8"))}
        else:
            try:
                body = r.json()
            except ValueError:
                body = r.text
        cases.append({"path": path, "params": params, "status": r.status_code, "body": body})

    # ---- catalog
    cat = client.get("/api/datasets", params={"limit": 200}).json()["datasets"]
    contexts = sorted({d["context_code"] for d in cat if d.get("context_code")})
    archetypes = sorted({d["archetype"] for d in cat if d.get("archetype")})
    dims = [r[0] for r in conn.execute(
        "SELECT dim_label FROM dimensions GROUP BY 1 ORDER BY count(*) DESC LIMIT 30").fetchall()]
    ancestors = [r[0] for r in conn.execute(
        "SELECT DISTINCT unnest(ancestor_codes) FROM matrices WHERE is_canonical ORDER BY 1").fetchall()]
    names = [r[0] for r in conn.execute(
        "SELECT matrix_name FROM matrices WHERE is_canonical ORDER BY matrix_code").fetchall() if r[0]]
    words = sorted({w for n in names for w in cs.fold(n).split() if len(w) > 3})
    for sort in ("updated", "name", "rows", "dims", "options", "bogus"):
        for lang in ("ro", "en"):
            add("/api/datasets", {"sort": sort, "lang": lang, "limit": 200})
    for _ in range(a.n):
        p = {"lang": rnd.choice(["ro", "en"]), "sort": rnd.choice(["updated", "name", "rows", "dims", "options"]),
             "limit": rnd.choice([10, 50, 200]), "offset": rnd.choice([0, 0, 20, 100])}
        for key, pool in (("context", contexts), ("ancestor", ancestors), ("archetype", archetypes),
                          ("dim", dims), ("granularity", ["annual", "monthly", "quarterly"])):
            if pool and rnd.random() < 0.25:
                p[key] = rnd.choice(pool)
        for key in ("has_geo", "has_gender", "has_age", "has_residence"):
            if rnd.random() < 0.15:
                p[key] = rnd.choice(["true", "false"])
        r = rnd.random()
        if r < 0.35:
            p["q"] = " ".join(rnd.sample(words, rnd.randint(1, 3)))
        elif r < 0.45:
            p["q"] = rnd.choice(cat)["matrix_code"].lower()[:5]
        elif r < 0.55:
            w = rnd.choice(words)
            p["q"] = w[:max(3, len(w) - 2)]          # partial word: FTS misses, LIKE
        add("/api/datasets", p)

    # ---- search
    judg = json.loads((REPO / "data/eval/pa02_concept_judgments.json").read_text())
    qs = [(j["q"], j.get("lang", "ro")) for j in judg["judgments"]]
    qs += [(x["q"] if isinstance(x, dict) else x, (x.get("lang", "ro") if isinstance(x, dict) else "ro"))
           for x in judg.get("no_concept", [])]
    concepts = cs.load_concepts()
    places = [p["name"] for p in cs._places(conn)] or ["Cluj", "Iasi"]
    for _ in range(a.n):
        c = rnd.choice(concepts)
        lang = rnd.choice(["ro", "en"])
        alias = rnd.choice(((c.get("aliases") or {}).get(lang) or []) + ((c.get("generic") or {}).get(lang) or []) or ["x"])
        parts = [alias]
        if rnd.random() < 0.6:
            parts.append(rnd.choice(places + ["Cluj-Napoca", "orasul Iasi", "Bucharest", "pe judete"]))
        if rnd.random() < 0.3:
            parts.append(rnd.choice(places))
        if rnd.random() < 0.5:
            parts.append(str(rnd.choice([1990, 2010, 2020, 2023, 2024, 2049])))
        rnd.shuffle(parts)
        qs.append((" ".join(parts), lang))
    for q, lang in qs:
        add("/api/search", {"q": q, "lang": lang})
    add("/api/search", {"q": "populatie", "lang": "ro", "limit": 3, "offset": 2})

    # ---- options
    codes = a.codes.split(",") if a.codes else [
        "POP105A_judete_grupe", "FOM106E_judete", "SOM103A_judete", "TUR105D_judete", "POP107D",
        "ART124A", "SOM101E"]
    for code in codes:
        cols = [r[0] for r in conn.execute(
            "DESCRIBE SELECT * FROM read_parquet(?)",
            [str(Path(cs.PARQUET_DIR) / f"{code}.parquet")]).fetchall()]
        for col in cols + ["BOGUS"]:
            add(f"/api/datasets/{code}/options", {"column": col})
            add(f"/api/datasets/{code}/options", {"column": col, "limit": 5, "offset": 3})
            add(f"/api/datasets/{code}/options", {"column": col, "q": rnd.choice(["a", "ș", "20", "CLUJ", "zzz"])})
    add("/api/datasets/NOPE_X/options", {"column": "REF_AREA"})

    # ---- downloads (CSV text and preflight; XLSX only as preflight)
    for code in codes:
        vals = client.get(f"/api/datasets/{code}/options", params={"column": "TIME_PERIOD", "limit": 3})
        years = vals.json().get("values", []) if vals.status_code == 200 else []
        areas = client.get(f"/api/datasets/{code}/options", params={"column": "REF_AREA", "limit": 4})
        areas = areas.json().get("values", []) if areas.status_code == 200 else []
        flts = [{}, {"TIME_PERIOD": years[:1]}, {"REF_AREA": areas[:2], "TIME_PERIOD": years[:2]},
                {"BOGUS": ["x"]}, {"TIME_PERIOD": ["1066"]}]
        for f in flts:
            for lang in ("ro", "en"):
                add(f"/api/datasets/{code}/download",
                    {"format": "csv", "lang": lang, "filters": json.dumps(f, ensure_ascii=False)})
            add(f"/api/datasets/{code}/download",
                {"format": "xlsx", "preflight": 1, "filters": json.dumps(f, ensure_ascii=False)})
        add(f"/api/datasets/{code}/download", {"format": "csv", "safe": 0, "filters": "{}"})
    add("/api/datasets/POP105A_judete_grupe/download", {"filters": "not json"})

    # ---- the dashboard's default tile requests (recorded for partitioned datasets)
    for code in codes:
        meta = client.get(f"/api/datasets/{code}", params={"lang": "ro"})
        comp = ((meta.json().get("chart_config") or {}).get("composition") or {}) if meta.status_code == 200 else {}
        for ch in comp.get("charts") or []:
            d = ch.get("data") or {}
            p = {"filters": json.dumps(d.get("filters") or {}, ensure_ascii=False, separators=(",", ":")),
                 "limit": 50000}
            if d.get("group_by"):
                p["group_by"] = json.dumps(d["group_by"], ensure_ascii=False)
            add(f"/api/datasets/{code}/data", p)

    # ---- dataset evidence (compared file by file)
    ev = [(c, {}, ["TIME_PERIOD"]) for c in codes] + [(c, {}, None) for c in codes[:2]]
    if not a.codes:
        ev += [("POP105A_judete_grupe", {"REF_AREA": ["Cluj"]}, ["TIME_PERIOD"]),
               ("FOM106E_judete", {"TIME_PERIOD": ["2024"]}, ["REF_AREA"]),
               ("SOM103A_judete", {"REF_AREA": ["Cluj"]}, None),
               ("TUR105D_judete", {"TIME_PERIOD": ["2024"]}, ["REF_AREA"])]
    for code, f, g in ev:
        p = {"filters": json.dumps(f, ensure_ascii=False), "lang": "ro"}
        if g:
            p["group_by"] = json.dumps(g)
        add(f"/api/datasets/{code}/evidence", p)

    # ---- recipes
    county_names = places + ["Bucharest", "Nowhere"]
    for rid in load_recipes():
        for lang in ("ro", "en"):
            latest = client.get(f"/api/recipes/{rid}", params={"lang": lang}).json()
            add(f"/api/recipes/{rid}", {"lang": lang})
            years = latest.get("years_available") or []
            for y in rnd.sample(years, min(3, len(years))) + ["1900"]:
                add(f"/api/recipes/{rid}", {"lang": lang, "year": y})
            for _ in range(6):
                areas = rnd.sample(county_names, min(len(county_names), rnd.randint(1, 5)))
                p = {"lang": lang, "areas": json.dumps(areas, ensure_ascii=False)}
                if years and rnd.random() < 0.5:
                    p["year"] = rnd.choice(years)
                add(f"/api/recipes/{rid}", p)
    add("/api/recipes/nope", {})
    add("/api/recipes/tourism_intensity", {"areas": "not json"})

    # ---- recorded paths
    for path, p in [("/api/categories", {"lang": "en"}), ("/api/places", {}),
                    ("/api/places/county/cluj", {}), ("/api/datasets/POP105A_judete_grupe", {"lang": "ro"}),
                    ("/api/datasets/POP105A_judete_grupe/insights", {"lang": "en"}),
                    ("/api/datasets/POP105A_judete_grupe/related", {}),
                    ("/api/reference/population", {"level": "region"}),
                    ("/api/dimensions", {"limit": 300}), ("/api/corpus/summary", {}),
                    ("/api/datasets/POP105A_judete_grupe/data",
                     {"filters": '{"REF_AREA":["Cluj"]}', "group_by": '["TIME_PERIOD"]'})]:
        add(path, p)

    with open(a.out, "w", encoding="utf-8") as fh:
        for c in cases:
            fh.write(json.dumps(c, ensure_ascii=False, default=str) + "\n")
    print(f"{len(cases)} api cases -> {a.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
