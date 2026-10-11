"""Concept-first search (PA-02a, audit A11).

Turns an ordinary question ("populatia rezidenta Cluj 2024", "somaj judete",
"net salary Bucharest") into explicit, editable selections:

  * concepts: reviewed indicator families from app/data/concepts.json, each with
    its official title/definition/unit and actual coverage from the corpus, the
    variant for the requested geography level, and the alternatives a user may
    have meant (domicile vs resident population, registered vs ILO unemployment);
  * place / level / period parsed from the text, shown back as chips;
  * families: the remaining full-text results with split children grouped under
    their parent, so one indicator does not fill the first page.

Nothing is silently chosen: a generic word ("populatie", "somaj") is marked
ambiguous and comes with its alternatives; a city named like its county is
flagged; a year without data is reported, not pinned.
"""
from __future__ import annotations

import json
import re
import threading
import unicodedata
from pathlib import Path

from app.config import PARQUET_DIR
from app.services import generation

CONCEPTS_PATH = Path(__file__).resolve().parent.parent / "data" / "concepts.json"

_LEVEL_WORDS = {
    "county": ["judet", "judete", "judetul", "judetului", "judetelor", "pe judete",
               "county", "counties", "by county"],
    "region": ["regiune", "regiuni", "regiunea", "regiunile", "regiuni de dezvoltare",
               "region", "regions", "by region"],
    "national": ["national", "nationala", "romania", "tara", "pe tara", "national level",
                 "country", "nationwide"],
}
_LATEST_WORDS = ["ultimul an", "cel mai recent", "cele mai recente", "recent", "acum", "azi",
                 "latest", "most recent", "current", "now"]
_CITY_WORDS = ["oras", "orasul", "municipiul", "municipiu", "city", "town"]
# County seats whose name differs from (and contains) the county name.
_CITY_OF_COUNTY = {"cluj napoca": "cluj", "targu mures": "mures", "drobeta turnu severin": "mehedinti",
                   "piatra neamt": "neamt", "baia mare": "maramures",
                   "ramnicu valcea": "valcea", "targu jiu": "gorj", "miercurea ciuc": "harghita",
                   "sfantu gheorghe": "covasna"}
_EN_PLACE = {"bucharest": "municipiul-bucuresti", "bucuresti": "municipiul-bucuresti",
             "capitala": "municipiul-bucuresti", "capital": "municipiul-bucuresti"}

_lock = threading.Lock()
_cache: dict = {}


def fold(text: str) -> str:
    """Lower-case, accent-free, punctuation as spaces, single-spaced."""
    s = unicodedata.normalize("NFKD", str(text or ""))
    s = "".join(c for c in s if not unicodedata.combining(c)).lower()
    s = re.sub(r"[^a-z0-9]+", " ", s)
    return " ".join(s.split())


def _has(text: str, phrase: str) -> bool:
    return f" {phrase} " in f" {text} "


def load_concepts() -> list[dict]:
    key = ("concepts", CONCEPTS_PATH.stat().st_mtime_ns)
    with _lock:
        if key not in _cache:
            _cache.clear()
            _cache[key] = json.loads(CONCEPTS_PATH.read_text(encoding="utf-8"))["concepts"]
        return _cache[key]


# ------------------------------------------------------------------ parsing

def _places(conn) -> list[dict]:
    """Counties (plus Bucharest) with folded names, from the corpus metadata."""
    from app.services.place_service import slugify
    gid = generation.current()["id"]
    ck = ("places", gid)
    with _lock:
        if ck in _cache:
            return _cache[ck]
    rows = conn.execute("""
        SELECT DISTINCT geo_name_clean FROM dimension_options_parsed
        WHERE dim_type = 'geo' AND geo_level = 'county' AND geo_name_clean IS NOT NULL
    """).fetchall()
    out = []
    for (name,) in rows:
        slug = slugify(name)
        folded = fold(name)
        names = {folded}
        if slug == "municipiul-bucuresti":
            names |= {"bucuresti", "bucharest", "municipiul bucuresti"}
        out.append({"slug": slug, "name": name, "type": "county", "names": sorted(names)})
    out.sort(key=lambda p: -max(len(n) for n in p["names"]))
    with _lock:
        _cache[ck] = out
    return out


_STOPWORDS = set("""
a al ai ale alea asta ca care cat cata cati cate ce cea cei cel cele cu cum de din dintre
mult multe multi putine putini mare mic
este e era fost sunt au are avea in intre la mai mare mari mic mici ne nu o pe pentru prin
sa se si sau spre toate tot un una unei unui despre fata evoluat evolutia evolueaza evolutie
compara comparatie compar comparati arata vreau vezi date datele statistica statistici
what which how has have had the an of in on at for by to is are was were most highest lowest
per changed change compare comparison and or with do does show me tell between over across
""".split())


def parse_query(q: str, conn) -> dict:
    """{text, places, place, level, period, latest, fts}: explicit selections in q.

    `places` lists every county named (in order of appearance); `place` is the
    first, kept for single-place callers. `fts` is the text with question words,
    places, levels and years removed, for the full-text family results.
    """
    text = fold(q)
    found, used = [], []          # [(position, place, city)], phrases consumed
    places = _places(conn)
    for city, county in _CITY_OF_COUNTY.items():
        if _has(text, city):
            p = next((x for x in places if x["slug"] == county), None)
            if p:
                found.append((f" {text} ".index(f" {city} "), p, True))
                used.append(city)
    masked = f" {text} "
    for u in used:
        masked = masked.replace(f" {u} ", " ")
    for p in places:                       # longest names first
        for n in p["names"]:
            if f" {n} " in masked and all(x[1]["slug"] != p["slug"] for x in found):
                found.append((f" {text} ".find(f" {n} "), p, False))
                masked = masked.replace(f" {n} ", " ")
                used.append(n)
    for word, slug in _EN_PLACE.items():
        if f" {word} " in masked and all(x[1]["slug"] != slug for x in found):
            p = next((x for x in places if x["slug"] == slug), None)
            if p:
                found.append((f" {text} ".find(f" {word} "), p, False))
                used.append(word)
    found.sort(key=lambda x: x[0])
    level = None
    for lv, words in _LEVEL_WORDS.items():
        if any(_has(text, w) for w in words):
            level = lv
            break
    if found and not level:
        level = "county"
    years = [int(y) for y in re.findall(r"\b(19[5-9]\d|20[0-4]\d)\b", text)]
    out_places = []
    for _, place, city in found:
        p = {"slug": place["slug"], "name": place["name"], "type": place["type"]}
        is_city = city or (place["slug"] != "municipiul-bucuresti" and any(
            _has(text, w + " " + n) for w in _CITY_WORDS for n in place["names"]))
        if is_city:
            # "Cluj-Napoca" / "orasul Cluj": a city, not the county. County data
            # is what these indicators have; say so instead of switching silently.
            p["ambiguous"] = True
            p["note"] = "city_not_county"
        out_places.append(p)
    drop = set(_STOPWORDS) | {w for u in used for w in u.split()} | set(_CITY_WORDS) \
        | {w for ws in _LEVEL_WORDS.values() for p_ in ws for w in p_.split()} \
        | {w for p_ in _LATEST_WORDS for w in p_.split()}
    fts = " ".join(w for w in text.split() if w not in drop and not re.fullmatch(r"\d+", w))
    return {"text": text, "places": out_places, "place": out_places[0] if out_places else None,
            "level": level, "period": years[-1] if years else None,
            "latest": any(_has(text, w) for w in _LATEST_WORDS), "fts": fts or text}


def match_concepts(text: str, lang: str = "ro") -> list[dict]:
    """[(concept, alias, generic)] best first; aliases in both languages count,
    the requested language breaks ties."""
    hits = []
    for c in load_concepts():
        best = None
        for kind in ("aliases", "generic"):
            for lg in ("ro", "en"):
                for a in (c.get(kind) or {}).get(lg, []):
                    fa = fold(a)
                    if _has(text, fa):
                        score = (len(fa.split()), kind == "aliases", lg == lang, len(fa))
                        if best is None or score > best[0]:
                            best = (score, a, kind == "generic")
        if best:
            hits.append({"concept": c, "alias": best[1], "generic": best[2], "score": best[0]})
    hits.sort(key=lambda h: h["score"], reverse=True)
    # A specific match beats generic ones it explains (e.g. "salariu mediu brut"
    # also contains the generic "salariu mediu" of net earnings).
    if hits and not hits[0]["generic"]:
        hits = [h for h in hits if not h["generic"] or h["score"][0] > hits[0]["score"][0]]
    return hits


# ------------------------------------------------------------------ facts

def dataset_facts(conn, code: str, lang: str = "ro") -> dict | None:
    """Title, definition, unit and actual coverage of one served dataset."""
    gid = generation.current()["id"]
    ck = ("facts", gid, code, lang)
    with _lock:
        if ck in _cache:
            return _cache[ck]
    row = conn.execute("""
        SELECT m.matrix_code, m.matrix_name, m.matrix_name_en, m.parent_matrix_code,
               COALESCE(m.definitie, pm.definitie), COALESCE(m.ultima_actualizare, pm.ultima_actualizare),
               p.primary_unit_type
        FROM matrices m
        LEFT JOIN matrices pm ON pm.matrix_code = m.parent_matrix_code
        LEFT JOIN matrix_profiles p ON p.matrix_code = m.matrix_code
        WHERE m.matrix_code = ?""", [code]).fetchone()
    path = PARQUET_DIR / f"{code}.parquet"
    if not row or not path.exists():
        return None
    cols = [r[0] for r in conn.execute("DESCRIBE SELECT * FROM read_parquet(?)", [str(path)]).fetchall()]
    coverage = None
    if "TIME_PERIOD" in cols:
        first, last, n = conn.execute(
            "SELECT min(TIME_PERIOD), max(TIME_PERIOD), count(DISTINCT TIME_PERIOD) "
            "FROM read_parquet(?) WHERE OBS_VALUE IS NOT NULL", [str(path)]).fetchone()
        coverage = {"first": first, "last": last, "periods": n,
                    "frequency": "monthly" if last and len(str(last)) == 7 and "-" in str(last)
                    and "Q" not in str(last) else
                    "quarterly" if last and "Q" in str(last) else "annual"}
    unit = None
    if "UNIT_MEASURE" in cols:
        units = [r[0] for r in conn.execute(
            "SELECT DISTINCT UNIT_MEASURE FROM read_parquet(?) LIMIT 3", [str(path)]).fetchall()]
        unit = units[0] if len(units) == 1 else None
    title = (row[2] if lang == "en" and row[2] else row[1]) or code
    facts = {"code": code, "title": re.sub(r"\s*\[[^\]]*\]\s*$", "", title).strip(),
             "family": row[3] or code, "definition": (row[4] or "").strip() or None,
             "source_updated": str(row[5]) if row[5] else None, "unit": unit,
             "unit_type": row[6], "coverage": coverage}
    with _lock:
        _cache[ck] = facts
    return facts


def _area_value(conn, code: str, slug: str) -> str | None:
    """The REF_AREA data value of a place in this dataset (names differ by accents)."""
    from app.services.place_service import slugify
    path = PARQUET_DIR / f"{code}.parquet"
    try:
        vals = [r[0] for r in conn.execute(
            "SELECT DISTINCT REF_AREA FROM read_parquet(?)", [str(path)]).fetchall()]
    except Exception:
        return None
    return next((v for v in vals if v and slugify(v) == slug), None)


def _href(code: str, lang: str, filters: dict | None = None) -> str:
    from urllib.parse import quote
    h = f"/dataset-v2.html?code={quote(code)}"
    if filters:
        h += "&f=" + quote(json.dumps(filters, ensure_ascii=False, separators=(",", ":")))
    return h + ("&lang=en" if lang == "en" else "")


def recipe_card(conn, concept: dict, parsed: dict, lang: str, alias=None, generic=False) -> dict | None:
    """A concept answered by a reviewed recipe: link to its page with the parsed
    places and year; coverage is the latest year both sources share."""
    from app.services.recipes import load_recipes
    r = load_recipes().get(concept["recipe"])
    if not r:
        return None
    num, den = (dataset_facts(conn, r[k]["dataset"], lang) for k in ("numerator", "denominator"))
    if not num or not den:
        return None
    first = max(str(num["coverage"]["first"]), str(den["coverage"]["first"]))
    last = min(str(num["coverage"]["last"])[:4], str(den["coverage"]["last"])[:4])
    params, notes = {"recipe": r["id"]}, []
    if parsed.get("places"):
        params["areas"] = json.dumps([p["name"] for p in parsed["places"]], ensure_ascii=False)
    year = parsed.get("period")
    if year:
        if int(first[:4]) <= year <= int(last):
            params["year"] = str(year)
        else:
            notes.append("period_unavailable")
    if lang == "en":
        params["lang"] = "en"
    from urllib.parse import urlencode
    pick = lambda d: d.get(lang) or d["ro"]
    return {"id": concept["id"], "question": concept.get("question"), "name": pick(concept["name"]),
            "note": pick(concept["note"]), "matched": alias, "ambiguous": bool(generic),
            "code": f"{r['numerator']['dataset']} ÷ {r['denominator']['dataset']}",
            "family": None, "title": pick(r["name"]), "definition": pick(r["definition"]),
            "unit": pick(r["unit"]), "coverage": {"first": first[:4], "last": last, "frequency": "annual"},
            "quality": "unique", "level": "county", "selection": {k: v for k, v in params.items()
                                                                if k in ("areas", "year")},
            "notes": notes, "href": "/compare.html?" + urlencode(params), "variants": [],
            "recipe": r["id"], "status": pick(r["status"])}


def concept_card(conn, concept: dict, parsed: dict, lang: str, alias=None, generic=False) -> dict | None:
    if concept.get("recipe"):
        return recipe_card(conn, concept, parsed, lang, alias, generic)
    variants = concept.get("variants") or {}
    level = parsed.get("level")
    code = variants.get(level) or variants.get("county") or next(iter(variants.values()), None)
    facts = dataset_facts(conn, code, lang) if code else None
    if not facts:
        return None
    from app.services import grain_guard
    card = {"id": concept["id"], "question": concept.get("question"),
            "name": concept["name"].get(lang) or concept["name"]["ro"],
            "note": concept["note"].get(lang) or concept["note"]["ro"],
            "matched": alias, "ambiguous": bool(generic), **facts,
            "quality": grain_guard.file_status(code)["status"],
            "level": next((lv for lv, c in variants.items() if c == code), None)}
    selection, notes = {}, []
    if parsed.get("places"):
        if card["level"] == "county":
            values = [v for v in (_area_value(conn, code, p["slug"]) for p in parsed["places"]) if v]
            if values:
                selection["REF_AREA"] = values[0] if len(values) == 1 else values
            if len(values) < len(parsed["places"]):
                notes.append("place_not_in_dataset")
        else:
            notes.append("place_level_unavailable")      # e.g. ILO: no county data
    year = parsed.get("period")
    cov = facts.get("coverage") or {}
    if year:
        if cov.get("frequency") == "annual" and cov.get("first") and \
                int(str(cov["first"])[:4]) <= year <= int(str(cov["last"])[:4]):
            selection["TIME_PERIOD"] = str(year)
        else:
            notes.append("period_unavailable")
    card["selection"] = selection
    card["notes"] = notes
    card["href"] = _href(code, lang, selection or None)
    card["variants"] = [{"level": lv, "code": c, "href": _href(c, lang)}
                        for lv, c in variants.items() if c != code]
    return card


# ------------------------------------------------------------------ search

def search(q: str, conn, lang: str = "ro", limit: int = 10, offset: int = 0) -> dict:
    parsed = parse_query(q, conn)
    hits = match_concepts(parsed["text"], lang)
    by_id = {c["id"]: c for c in load_concepts()}
    concepts, shown = [], set()
    for h in hits[:3]:
        c = h["concept"]
        if c["id"] in shown:
            continue
        card = concept_card(conn, c, parsed, lang, h["alias"], h["generic"])
        if not card:
            continue
        shown.add(c["id"])
        alts = []
        for aid in c.get("alternatives") or []:
            if aid in shown or aid not in by_id:
                continue
            alt = concept_card(conn, by_id[aid], parsed, lang)
            if alt:
                alts.append({k: alt[k] for k in ("id", "name", "note", "code", "title", "href",
                                                 "coverage", "notes")})
        card["alternatives"] = alts
        concepts.append(card)
    families = family_results(parsed["fts"], conn, lang, limit, offset,
                              exclude={card["family"] for card in concepts if card.get("family")})
    return {"query": q, "lang": lang,
            "interpretation": {k: parsed[k] for k in ("places", "level", "period", "latest", "fts")},
            "concepts": concepts, "families": families,
            "generation": generation.summary()}


def family_results(q: str, conn, lang: str, limit: int, offset: int, exclude=()) -> dict:
    """Full-text results, one entry per indicator family (split children grouped)."""
    from app.services.dataset_search import search_datasets
    res = search_datasets(q, lang=lang, limit=200, offset=0, conn=conn)
    groups: dict[str, dict] = {}
    order = []
    for d in res["datasets"]:
        fam = d.get("parent_matrix_code") if d.get("is_split") else d["matrix_code"]
        fam = fam or d["matrix_code"]
        if fam in exclude:
            continue
        if fam not in groups:
            groups[fam] = {"family": fam, "code": d["matrix_code"],
                           "title": re.sub(r"\s*\[[^\]]*\]\s*$", "", d["matrix_name"] or "").strip(),
                           "time_range": d.get("time_range"), "members": []}
            order.append(fam)
        label = None
        m = re.search(r"\[([^\]]*)\]\s*$", d["matrix_name"] or "")
        if m:
            label = m.group(1)
        groups[fam]["members"].append({"code": d["matrix_code"], "label": label,
                                       "time_range": d.get("time_range")})
    items = [groups[f] for f in order]
    return {"total": len(items), "truncated": res["total"] > len(res["datasets"]),
            "matching_datasets": res["total"], "items": items[offset:offset + limit],
            "search_mode": res.get("search_mode")}
