"""PA-02a: concept-first search and dimension value lookup.

Concept matching and query parsing run on the reviewed judgments without the
corpus (a tiny place table stands in for metadata). The full /api/search check
against the judgments is corpus-marked. Option lookup uses the synthetic corpus.
"""
import json
from pathlib import Path

import duckdb
import pytest

from app.services import concept_search as cs

JUDGMENTS = json.loads((Path(__file__).resolve().parent.parent / "data" / "eval"
                        / "pa02_concept_judgments.json").read_text(encoding="utf-8"))


@pytest.fixture
def places_conn():
    c = duckdb.connect()
    c.execute("CREATE TABLE dimension_options_parsed (dim_type VARCHAR, geo_level VARCHAR, geo_name_clean VARCHAR)")
    for n in ("Cluj", "Iasi", "Municipiul București", "Mures", "Alba", "Satu Mare", "Ilfov"):
        c.execute("INSERT INTO dimension_options_parsed VALUES ('geo', 'county', ?)", [n])
    cs._cache.clear()
    yield c
    cs._cache.clear()


def test_fold():
    assert cs.fold("Câți locuitori are Județul IAȘI?") == "cati locuitori are judetul iasi"


@pytest.mark.parametrize("j", JUDGMENTS["judgments"], ids=lambda j: j["q"][:40])
def test_reviewed_phrases(places_conn, j):
    parsed = cs.parse_query(j["q"], places_conn)
    hits = cs.match_concepts(parsed["text"], j["lang"])
    assert hits, "no concept"
    top = hits[0]
    assert top["concept"]["id"] == j["concept"]
    assert top["generic"] == j["ambiguous"]
    for alt in j.get("alternatives", []):
        assert alt in top["concept"]["alternatives"]
    if "places" in j:
        assert [p["slug"] for p in parsed["places"]] == j["places"]
    if j.get("place_ambiguous"):
        assert parsed["places"][0]["note"] == "city_not_county"
    if "period" in j:
        assert parsed["period"] == j["period"]


@pytest.mark.parametrize("q", JUDGMENTS["no_concept"])
def test_unrelated_queries_get_no_concept(places_conn, q):
    assert cs.match_concepts(cs.parse_query(q, places_conn)["text"]) == []


def test_specific_alias_beats_generic_one():
    hits = cs.match_concepts(cs.fold("salariul mediu brut"))
    assert [h["concept"]["id"] for h in hits] == ["gross_earnings"]


def test_question_words_and_places_leave_the_fulltext_query(places_conn):
    p = cs.parse_query("Cum se compară salariul mediu net în Cluj, Iași și București în 2024?", places_conn)
    assert p["fts"] == "salariul mediu net"
    assert p["level"] == "county" and p["period"] == 2024


def test_bucharest_municipality_is_the_county(places_conn):
    p = cs.parse_query("populatia municipiul bucuresti", places_conn)
    assert p["places"] == [{"slug": "municipiul-bucuresti", "name": "Municipiul București", "type": "county"}]


def test_every_concept_variant_and_alternative_resolves():
    concepts = cs.load_concepts()
    ids = {c["id"] for c in concepts}
    for c in concepts:
        assert set(c.get("alternatives", [])) <= ids
        assert c["variants"] and c["name"]["ro"] and c["name"]["en"] and c["note"]["en"]


# ------------------------------------------------------------ option lookup

@pytest.fixture
def client(tmp_path, monkeypatch):
    from fix02b_corpus import make_client
    return make_client(tmp_path, monkeypatch)


def opts(client, code, **params):
    r = client.get(f"/api/datasets/{code}/options", params=params)
    return r.status_code, r.json()


def test_time_values_newest_first_with_bounds(client):
    st, d = opts(client, "POPX", column="TIME_PERIOD", limit=1)
    assert st == 200 and d["values"] == ["2025"] and d["total"] == 2
    assert d["truncated"] is True and d["next_offset"] == 1
    assert d["period_bounds"] == {"first": "2024", "last": "2025", "periods_with_data": 2}
    st, d = opts(client, "POPX", column="TIME_PERIOD", limit=1, offset=1)
    assert d["values"] == ["2024"] and d["next_offset"] is None and d["truncated"] is False


def test_value_search_is_accent_insensitive_and_paged(client):
    st, d = opts(client, "POPX", column="AGE", q="ANI", limit=2)
    assert st == 200 and d["total"] == 6 and len(d["values"]) == 2 and d["truncated"]
    st, d = opts(client, "POPX", column="SEX", q="feminín")
    assert d["values"] == ["Feminin"]


def test_unknown_column_and_dataset(client):
    assert opts(client, "POPX", column="BOGUS")[0] == 400
    assert opts(client, "POPX", column="OBS_VALUE")[0] == 400
    assert opts(client, "NOPE", column="AGE")[0] == 404
    assert opts(client, "POPX", column="AGE", limit=0)[0] == 422


# ------------------------------------------------------------ real corpus

@pytest.mark.corpus
@pytest.mark.parametrize("j", JUDGMENTS["judgments"], ids=lambda j: j["q"][:40])
def test_api_search_meets_judgments(j):
    from fastapi.testclient import TestClient
    from app.main import app
    d = TestClient(app).get("/api/search", params={"q": j["q"], "lang": j["lang"]}).json()
    top = d["concepts"][0]
    assert top["id"] == j["concept"] and top["ambiguous"] == j["ambiguous"]
    if "code" in j:
        assert top["code"] == j["code"]
    if j.get("places") and top["level"] == "county":
        assert top["selection"].get("REF_AREA"), "place not carried into the selection"
    assert top["family"] not in {f["family"] for f in d["families"]["items"]}
