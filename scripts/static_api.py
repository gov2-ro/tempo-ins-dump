"""Recorded API layer of the static site (S3), used by build-static.py.

Every bounded GET the pages make is answered once at build time by the real
app (fastapi TestClient, no logic copied) and written under `rec/` as gzipped
JSON. The few endpoints whose answers depend on free input are not recorded but
computed in the browser from exported inputs, and proven equal to the server by
tools/static-engine/api-parity.mjs:

  /datasets?q&filters…      catalog.json.gz (every canonical dataset, with the
                            fields search_datasets filters and sorts on)
  /search                   search/: concepts, places, per-concept facts, and the
                            BM25 index of the FTS sidecar (stemmer none), sharded
  /datasets/{c}/options     policy period bounds + the data tables
  /recipes/{id}?areas       the recorded full-year result, subset client-side

A non-200 answer is recorded as {"__status": code, "detail": ...} so the
browser raises the same error the server would.
"""
from __future__ import annotations

import gzip
import json
import re
from pathlib import Path

LANGS = ("ro", "en")
SHARDS = 64


def gz_json(obj, path: Path) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = json.dumps(obj, ensure_ascii=False, separators=(",", ":"), allow_nan=False,
                     default=str).encode("utf-8")
    data = gzip.compress(raw, 6, mtime=0)
    path.write_bytes(data)
    return len(data)


def _answer(client, url: str, params=None):
    r = client.get(url, params=params or {})
    if r.status_code == 200:
        return r.json()
    try:
        detail = r.json().get("detail")
    except ValueError:
        detail = r.text
    return {"__status": r.status_code, "detail": detail}


def shard_of(term: str) -> int:
    """Stable term shard; mirrored in engine/search.js."""
    h = 2166136261
    for b in term.encode("utf-8"):
        h = ((h ^ b) * 16777619) & 0xFFFFFFFF
    return h % SHARDS


# ------------------------------------------------------------------ catalog

def export_catalog(conn) -> dict:
    """search_datasets' output rows plus the columns it filters and sorts on."""
    from app.services.dataset_search import search_datasets
    by_lang = {lang: {d["matrix_code"]: d for d in
                      search_datasets(None, lang=lang, limit=1_000_000, offset=0, conn=conn)["datasets"]}
               for lang in LANGS}
    extra = {r[0]: r[1:] for r in conn.execute("""
        SELECT m.matrix_code, m.matrix_name, m.matrix_name_en, m.ultima_actualizare,
               m.ancestor_codes, p.has_gender, p.has_age, p.has_residence, m.mat_max_dim, o.total
        FROM matrices m LEFT JOIN matrix_profiles p ON m.matrix_code = p.matrix_code
        LEFT JOIN (SELECT matrix_code, SUM(option_count) AS total FROM dimensions
                   GROUP BY matrix_code) o ON o.matrix_code = m.matrix_code
        WHERE m.is_canonical = TRUE""").fetchall()}
    dims: dict = {}
    for code, label in conn.execute("SELECT DISTINCT matrix_code, dim_label FROM dimensions").fetchall():
        dims.setdefault(code, []).append(label)
    rows = []
    for code in sorted(by_lang["ro"]):
        ro, en = by_lang["ro"][code], by_lang["en"][code]
        name_ro, name_en, updated, ancestors, g, a, r, max_dim, options = extra[code]
        rows.append({**ro, "matrix_name": None, "names": {"ro": ro["matrix_name"], "en": en["matrix_name"]},
                     "_name_ro": name_ro, "_name_en": name_en,
                     "_updated": str(updated) if updated else None, "_ancestors": list(ancestors or []),
                     "_has_gender": g, "_has_age": a, "_has_residence": r, "_max_dim": max_dim,
                     "_options": options,
                     "_dims": sorted(set(dims.get(code, [])))})
    from app.services.dataset_search import TOTAL_BASIS
    return {"datasets": rows, "total_basis": TOTAL_BASIS}


# ------------------------------------------------------------------ search

def export_search(conn, out: Path) -> dict:
    """Concepts, places, card facts and the BM25 index (see engine/search.js)."""
    from app.services import concept_search as cs, grain_guard
    from app.services.dataset_search import SEARCH_DB_PATH, search_status
    from app.services.recipes import load_recipes, source_specs
    concepts = cs.load_concepts()
    recipes = load_recipes()
    codes = set()
    for c in concepts:
        codes |= set((c.get("variants") or {}).values())
    for r in recipes.values():
        codes |= {s["dataset"] for s in source_specs(r)}
    facts = {lang: {c: cs.dataset_facts(conn, c, lang) for c in sorted(codes)} for lang in LANGS}
    areas = {}
    for c in sorted(codes):
        areas[c] = sorted({v for (v,) in conn.execute(
            "SELECT DISTINCT REF_AREA FROM read_parquet(?) WHERE REF_AREA IS NOT NULL",
            [str(cs.PARQUET_DIR / f"{c}.parquet")]).fetchall()}) if _has_col(conn, c, "REF_AREA") else []
    grain = {c: grain_guard.file_status(c)["status"] for c in sorted(codes)}
    rcp = {rid: {"id": r["id"], "kind": r.get("kind", "ratio"), "name": r["name"], "unit": r["unit"],
                 "definition": r["definition"], "status": r["status"],
                 "sources": [s["dataset"] for s in source_specs(r)]}
           for rid, r in recipes.items()}
    size = gz_json({"concepts": concepts, "places": cs._places(conn), "facts": facts, "areas": areas,
                    "grain": grain, "recipes": rcp}, out / "search" / "concepts.json.gz")
    # BM25 index: exactly the FTS sidecar's tables, so ranking is reproducible.
    from app.services.dataset_search import _get_search_conn
    st = search_status()
    index = {"mode": st["mode"]}
    if st["mode"] == "fts" and Path(SEARCH_DB_PATH).exists():
        s = _get_search_conn().cursor()
        try:
            num_docs, avgdl = s.execute("SELECT num_docs, avgdl FROM fts_main_search_docs.stats").fetchone()
            docs = s.execute("SELECT docid, name, len FROM fts_main_search_docs.docs ORDER BY docid").fetchall()
            pos = {d[0]: i for i, d in enumerate(docs)}
            shards: list[dict] = [{} for _ in range(SHARDS)]
            terms = {tid: (term, df) for tid, term, df in s.execute(
                "SELECT termid, term, df FROM fts_main_search_docs.dict").fetchall()}
            post: dict = {}
            for tid, did, tf in s.execute(
                    "SELECT termid, docid, count(*) FROM fts_main_search_docs.terms "
                    "GROUP BY termid, docid ORDER BY termid, docid").fetchall():
                post.setdefault(tid, []).append((pos[did], tf))
            for tid, (term, df) in terms.items():
                pl = post.get(tid, [])
                shards[shard_of(term)][term] = [df, [d for d, _ in pl], [t for _, t in pl]]
        finally:
            s.close()
        for i, sh in enumerate(shards):
            size += gz_json(sh, out / "search" / "terms" / f"{i:02d}.json.gz")
        index.update(num_docs=num_docs, avgdl=avgdl, shards=SHARDS,
                     docs=[d[1] for d in docs], lens=[d[2] for d in docs])
    size += gz_json(index, out / "search" / "index.json.gz")
    return {"bytes": size, "fts": index["mode"]}


def _has_col(conn, code, col) -> bool:
    from app.config import PARQUET_DIR
    path = PARQUET_DIR / f"{code}.parquet"
    if not path.exists():
        return False
    cols = [r[0] for r in conn.execute("DESCRIBE SELECT * FROM read_parquet(?)", [str(path)]).fetchall()]
    return col in cols


# ------------------------------------------------------------------ recorded

def _category_codes(tree) -> list[str]:
    out = []
    def walk(nodes):
        for n in nodes or []:
            if n.get("code"):
                out.append(n["code"])
            walk(n.get("children"))
    walk(tree if isinstance(tree, list) else tree.get("categories") or tree.get("tree") or [])
    return out


def record(conn, out: Path, codes: list[str], *, all_datasets: bool, base_url: str = "",
           log=print) -> dict:
    """Answer every bounded endpoint once with the real app."""
    from fastapi.testclient import TestClient
    from app.main import app
    from app.services.recipes import load_recipes
    client = TestClient(app, base_url=base_url.rstrip("/") or "http://testserver",
                        raise_server_exceptions=False)
    rec = out / "rec"
    n = size = 0

    def put(obj, rel):
        nonlocal n, size
        n += 1
        size += gz_json(obj, rec / rel)

    for lang in LANGS:
        cats = _answer(client, "/api/categories", {"lang": lang})
        put(cats, f"categories.{lang}.json.gz")
        put(_answer(client, "/api/corpus/summary", {"lang": lang}), f"corpus-summary.{lang}.json.gz")
        for cc in _category_codes(cats):
            put(_answer(client, f"/api/categories/{cc}/summary", {"lang": lang}),
                f"category-summary/{cc}.{lang}.json.gz")
        put(_answer(client, "/api/recipes", {"lang": lang}), f"recipes.{lang}.json.gz")
    put(_answer(client, "/api/categories/trends"), "categories-trends.json.gz")
    put(_answer(client, "/api/dimensions", {"limit": 500}), "dimensions.json.gz")
    for level in ("county", "region", "macroregion"):
        put(_answer(client, "/api/reference/population", {"level": level}), f"population.{level}.json.gz")
    log(f"  recorded globals ({n})")

    places = _answer(client, "/api/places")
    put(places, "places.json.gz")
    for p in places.get("places", []):
        prof = _answer(client, f"/api/places/{p['type']}/{p['slug']}")
        put(prof, f"place/{p['type']}/{p['slug']}.json.gz")
        for k in sorted({x.get("key") for x in (prof.get("kpis") or []) if x.get("key")}):
            if not re.fullmatch(r"[a-z0-9_]{1,80}", k):
                raise SystemExit(f"KPI key {k!r} is not file-safe")
            put(_answer(client, f"/api/places/{p['type']}/{p['slug']}/baselines/{k}"),
                f"place/{p['type']}/{p['slug']}/baselines/{k}.json.gz")
    log(f"  recorded places ({n})")

    for rid in load_recipes():
        for lang in LANGS:
            latest = _answer(client, f"/api/recipes/{rid}", {"lang": lang})
            put(latest, f"recipe/{rid}/latest.{lang}.json.gz")
            for y in latest.get("years_available") or []:
                put(_answer(client, f"/api/recipes/{rid}", {"year": y, "lang": lang}),
                    f"recipe/{rid}/{y}.{lang}.json.gz")
                r = client.get(f"/api/recipes/{rid}/evidence", params={"year": y, "lang": lang})
                if r.status_code == 200:
                    p = rec / "recipe" / rid / f"{y}.{lang}.zip"
                    p.write_bytes(r.content)
                    n += 1
                    size += len(r.content)
    log(f"  recorded recipes ({n})")

    if all_datasets:
        record_codes = [r[0] for r in conn.execute(
            "SELECT matrix_code FROM matrices WHERE is_canonical ORDER BY 1").fetchall()]
    else:   # a partial build: the requested datasets and their split parents
        parents = {r[0] for r in conn.execute(
            "SELECT DISTINCT parent_matrix_code FROM matrices WHERE matrix_code = ANY(?) "
            "AND parent_matrix_code IS NOT NULL", [list(codes)]).fetchall()}
        record_codes = sorted(set(codes) | parents)
    for i, code in enumerate(record_codes, 1):
        for lang in LANGS:
            put(_answer(client, f"/api/datasets/{code}", {"lang": lang}), f"datasets/{code}.{lang}.json.gz")
            put(_answer(client, f"/api/datasets/{code}/insights", {"lang": lang}),
                f"insights/{code}.{lang}.json.gz")
            put(_answer(client, f"/api/datasets/{code}/related", {"lang": lang}),
                f"related/{code}.{lang}.json.gz")
        if i % 500 == 0:
            log(f"  recorded {i}/{len(record_codes)} datasets ({n} files)")
    put(export_catalog(conn), "catalog.json.gz")
    return {"files": n, "bytes": size}

