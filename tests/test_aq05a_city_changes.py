"""AQ-05A: compare_periods with entity_class "cities" (municipalities and towns in the GOS102A
SIRUTA catalogue), classified over the FULL endpoint table before eligibility, ranks and top K.

Fixture CHG (REF_AREA county, REF_AREA_2 locality with its SIRUTA, years 2010 / 2015 / 2020).
Numbers below are the fixture's definition, not derived from the code under test:

  * 230 catalogue cities CITY000..CITY229: 2015 = 5000 + 10 i, 2020 = 2015 - i, 2010 = 2015 + 3.
    The steepest decline (-229) is the LAST row of the file, beyond any 200-row raw preview.
  * COMUNA GIANT (not in the catalogue): 90000 -> 1000 (-89000), the largest decline of all.
  * "Total": a total row among its parts (outside the class, never an exclusion).
  * two cities both called VALEA, in different counties and with different SIRUTA: -150 / -10.
  * GONE: only a 2015 row (absent 2020 endpoint); NULLED: a NULL 2020 value; ZERO: 0 -> 50.
"""
import csv
import hashlib
import io
import json
import zipfile

import pytest

from at01_fixtures import GENERATION, add_dataset, call, make_env
from test_at01_changes import (PINNED, area_dim, iv, open_zip, real, recompute, time_dim,  # noqa: F401
                               unit_dim)

UNIT = "Numar persoane"
N = 230
GONE, NULLED, ZERO = "3100 ORAS GONE", "3200 ORAS NULLED", "3300 ORAS ZERO"
VALEA_A, VALEA_B = "2001 ORAS VALEA", "2002 ORAS VALEA"
COMMUNE = "9999 COMUNA GIANT"


def city(i):
    return f"{1000 + i} ORAS CITY{i:03}"


def county(i):
    return "Alba" if i % 2 == 0 else "Bihor"


# (county, locality, {year: value}) in file order; the winner of a decline ranking comes last
ENTITIES = (
    [(county(i), city(i), {"2010": 5013.0 + 10 * i, "2015": 5010.0 + 10 * i, "2020": 5010.0 + 9 * i})
     for i in range(N - 1)]
    + [("Alba", COMMUNE, {"2010": 91000.0, "2015": 90000.0, "2020": 1000.0}),
       ("Alba", "Total", {"2010": 1.0e7, "2015": 1.0e7, "2020": 9.0e6}),
       ("Alba", VALEA_A, {"2010": 1700.0, "2015": 1500.0, "2020": 1350.0}),
       ("Bihor", VALEA_B, {"2010": 900.0, "2015": 800.0, "2020": 790.0}),
       ("Alba", GONE, {"2015": 2000.0}),
       ("Bihor", NULLED, {"2010": 2000.0, "2015": 2000.0, "2020": None}),
       ("Alba", ZERO, {"2010": 0.0, "2015": 0.0, "2020": 50.0}),
       (county(N - 1), city(N - 1), {"2010": 5013.0 + 10 * (N - 1), "2015": 5010.0 + 10 * (N - 1),
                                      "2020": 5010.0 + 9 * (N - 1)})])
CATALOGUE = ([city(i) for i in range(N)] + [VALEA_A, VALEA_B, GONE, NULLED, ZERO])
YEARS = ("2010", "2015", "2020")
CITY_ROWS = {loc for _, loc, _ in ENTITIES} - {COMMUNE, "Total"}


def chg_rows(entities=ENTITIES):
    return [(c, loc, y, UNIT, v) for y in YEARS for c, loc, vals in entities
            for yy, v in vals.items() if yy == y]


def build_chg(corpus, entities=ENTITIES, catalogue=CATALOGUE, code="CHG"):
    names = [loc for _, loc, _ in entities]
    add_dataset(corpus, code,
                [area_dim(["Alba", "Bihor"], col="REF_AREA", label="Judete"),
                 area_dim(names, level="locality", col="REF_AREA_2", label="Localitati"),
                 time_dim(YEARS), unit_dim(UNIT)], chg_rows(entities), name="Populatie pe localitati")
    if catalogue is not None:
        add_dataset(corpus, "GOS102A", [area_dim(catalogue, "locality", "REF_AREA_2"),
                                        time_dim(("2024",)), unit_dim("Hectare")],
                    [(c, "2024", "Hectare", 10.0) for c in catalogue], name="Localitati")


@pytest.fixture
def env(tmp_path, monkeypatch):
    return make_env(tmp_path, monkeypatch, build=build_chg)


def cc(**kw):
    kw.setdefault("lang", "en")             # these tests pin the English wording (AQ-04C localized the prose)
    kw.setdefault("dataset", "CHG")
    kw.setdefault("entity_columns", ["REF_AREA", "REF_AREA_2"])
    kw.setdefault("intervals", [iv("2015", "2020")])
    return call("compare_periods", **kw)


def cities(**kw):
    return cc(entity_class="cities", **kw)


def loc_of(row):
    return row["entity"]["REF_AREA_2"]


def expected(order="asc", year_from="2015", year_to="2020"):
    """[(locality, absolute)] of every catalogue city with both endpoints, from the fixture."""
    out = [(loc, vals[year_to] - vals[year_from]) for _, loc, vals in ENTITIES
           if loc in CITY_ROWS and vals.get(year_from) is not None and vals.get(year_to) is not None]
    return sorted(out, key=lambda x: ((x[1] if order == "asc" else -x[1]), x[0]))


# ============================================================ the class is applied before top K

def test_the_steepest_city_decline_wins_after_the_full_class_is_ranked(env):
    e = cities(top_k=3)
    assert e["status"] == "partial" and e["reason"] is None          # GONE and NULLED are excluded
    iv0 = e["data"]["intervals"][0]
    assert [(loc_of(r), r["absolute"], r["rank"]) for r in iv0["rows"]] == [
        (city(229), -229.0, 1), (city(228), -228.0, 2), (city(227), -227.0, 3)]
    want = expected()
    assert iv0["eligible_count"] == len(want) == N + 3               # 230 cities + 2 VALEA + ZERO
    assert (iv0["excluded_count"], iv0["exclusion_counts"]) == (2, {"no_observation": 1, "value_missing": 1})
    assert e["limits"]["total_rows"] == N + 3 and e["limits"]["preview_truncated"] is True
    assert e["data"]["entity_class"] == "cities" and e["data"]["outside_class_count"] == 2


def test_membership_is_not_a_filter_of_the_top_k_of_all_entities(env):
    """The all-entities top 3 is [commune, 229, 228]. Filtering that to cities would return two
    rows; the class answer has three because the class was applied first."""
    top_all = cc(top_k=3)["data"]["intervals"][0]["rows"]
    assert [loc_of(r) for r in top_all] == [COMMUNE, city(229), city(228)]
    top_cities = cities(top_k=3)["data"]["intervals"][0]["rows"]
    assert [loc_of(r) for r in top_cities] == [city(229), city(228), city(227)]


def test_a_commune_with_the_largest_decline_is_excluded_and_counted(env):
    e = cities(top_k=100)
    iv0 = e["data"]["intervals"][0]
    assert all(loc_of(r) not in (COMMUNE, "Total") for r in iv0["rows"])
    assert COMMUNE not in json.dumps(iv0["excluded"]) and "Total" not in json.dumps(iv0["excluded"])
    assert e["data"]["outside_class_count"] == 2                      # the commune and the total row
    assert e["provenance"]["classification"]["outside_class_count"] == 2
    allm = cc(top_k=1)["data"]["intervals"][0]
    assert loc_of(allm["rows"][0]) == COMMUNE and allm["rows"][0]["absolute"] == -89000.0


def test_the_winning_city_lies_beyond_a_raw_two_hundred_row_preview(env):
    raw = call("query_data", dataset="CHG", group_by=["REF_AREA", "REF_AREA_2", "TIME_PERIOD"],
               filters={"TIME_PERIOD": ["2020"]}, limit=200)
    assert len(raw["data"]["rows"]) == 200 and raw["limits"]["preview_truncated"] is True
    assert city(229) not in [r[raw["data"]["columns"].index("REF_AREA_2")] for r in raw["data"]["rows"]]
    assert loc_of(cities(top_k=1)["data"]["intervals"][0]["rows"][0]) == city(229)


def test_class_values_equal_the_all_entities_values_and_ranks_are_over_the_class(env):
    """Same endpoints, same arithmetic: a city's row is the row it has without the class; only the
    rank is renumbered over the class."""
    from app.db import get_conn
    from app.services import period_changes
    from app.services.tools import schemas
    conn = get_conn()
    try:
        run = lambda **kw: period_changes.run(conn, schemas.ComparePeriodsArgs.model_validate(
            {"dataset": "CHG", "entity_columns": ["REF_AREA", "REF_AREA_2"], "top_k": 100,
             "intervals": [iv("2015", "2020")], **kw}), "ro")
        full_all, full_cities = run(), run(entity_class="cities")
    finally:
        conn.close()
    rows_all = full_all["intervals"][0]["rows"]
    rows_cities = full_cities["intervals"][0]["rows"]
    in_class = [r for r in rows_all if loc_of(r) in CITY_ROWS]
    assert [(r["entity"], r["from_value"], r["to_value"], r["absolute"], r["percent"]) for r in rows_cities] == \
        [(r["entity"], r["from_value"], r["to_value"], r["absolute"], r["percent"]) for r in in_class]
    assert [r["rank"] for r in rows_cities] == list(range(1, len(rows_cities) + 1))
    assert rows_all[0]["rank"] == 1 and loc_of(rows_all[0]) == COMMUNE
    assert [(loc_of(r), r["absolute"]) for r in rows_cities] == expected()
    assert full_cities["intervals"][0]["eligible_count"] == len(in_class)
    assert full_all["intervals"][0]["eligible_count"] == len(rows_all) == len(in_class) + 1   # + the commune


# ============================================================ identity and endpoints

def test_same_named_localities_in_two_counties_stay_separate(env):
    only = {"REF_AREA_2": [VALEA_A, VALEA_B]}
    e = cities(filters=only)
    assert [(r["entity"], r["absolute"], r["rank"]) for r in e["data"]["intervals"][0]["rows"]] == [
        ({"REF_AREA": "Alba", "REF_AREA_2": VALEA_A}, -150.0, 1),
        ({"REF_AREA": "Bihor", "REF_AREA_2": VALEA_B}, -10.0, 2)]
    assert e["data"]["intervals"][0]["eligible_count"] == 2
    # the locality alone is enough to ask: the parent county is added to the key, not guessed
    one = cities(entity_columns=["REF_AREA_2"], filters=only)
    assert one["data"]["key_columns"] == ["REF_AREA", "REF_AREA_2"]
    assert one["data"]["intervals"][0]["rows"] == e["data"]["intervals"][0]["rows"]


def test_one_siruta_under_two_entities_is_ambiguous_and_refuses(tmp_path, monkeypatch):
    twin = [("Alba", "3001 ORAS TWIN", {"2015": 10.0, "2020": 9.0}),
            ("Bihor", "3001 ORAS TWIN", {"2015": 20.0, "2020": 19.0}),
            ("Alba", "3002 ORAS OTHER", {"2015": 5.0, "2020": 6.0})]
    make_env(tmp_path, monkeypatch, build=lambda c: build_chg(c, twin, ["3001 ORAS TWIN", "3002 ORAS OTHER"]))
    e = cities(top_k=5)
    assert (e["status"], e["reason"]) == ("unavailable", "identity_ambiguous")
    assert e["data"] == {} and e["limits"]["returned_rows"] == 0
    assert "SIRUTA" in e["message"] and e["provenance"]["classification"]["dataset"] == "GOS102A"
    # without the class nothing changes: two entities with their own counties
    assert cc(top_k=5)["status"] == "ok"


def test_a_locality_without_an_exact_siruta_refuses_instead_of_matching_names(tmp_path, monkeypatch):
    names = [("Alba", "ORAS CITY000", {"2015": 10.0, "2020": 9.0}),
             ("Alba", "1001 ORAS CITY001", {"2015": 10.0, "2020": 8.0})]
    make_env(tmp_path, monkeypatch, build=lambda c: build_chg(c, names, ["1001 ORAS CITY001", "1000 ORAS CITY000"]))
    e = cities()
    assert (e["status"], e["reason"]) == ("unavailable", "identity_ambiguous")
    assert "exact SIRUTA" in e["message"] and e["data"] == {}


def test_a_missing_or_ambiguous_catalogue_refuses(tmp_path, monkeypatch):
    make_env(tmp_path, monkeypatch, build=lambda c: build_chg(c, catalogue=None))
    e = cities()
    assert (e["status"], e["reason"]) == ("unavailable", "classification_unavailable")
    assert cc()["status"] in ("ok", "partial")                         # the default class needs no catalogue


def test_a_catalogue_that_repeats_a_siruta_under_two_labels_refuses(tmp_path, monkeypatch):
    make_env(tmp_path, monkeypatch, build=lambda c: build_chg(c, catalogue=[city(0), "1000 ORAS OTHER NAME"]))
    e = cities()
    assert (e["status"], e["reason"]) == ("unavailable", "identity_ambiguous")
    assert "repeats a SIRUTA key" in e["message"]


def test_an_absent_endpoint_is_excluded_not_zero(env):
    e = cities(top_k=100)
    iv0 = e["data"]["intervals"][0]
    by = {loc_of(x): x for x in iv0["excluded"]}
    assert set(by) == {GONE, NULLED}
    assert (by[GONE]["reason"], by[GONE]["missing"]) == ("no_observation", ["to"])
    assert (by[NULLED]["reason"], by[NULLED]["missing"]) == ("value_missing", ["to"])
    ranked = [loc_of(r) for r in iv0["rows"]]
    assert GONE not in ranked and NULLED not in ranked               # as zero, GONE would lead with -2000
    assert iv0["rows"][0]["absolute"] == -229.0
    assert iv0["eligible_count"] + iv0["excluded_count"] == len(CITY_ROWS)
    assert any(w["code"] == "entities_excluded" for w in e["warnings"])


def test_a_selection_without_a_catalogue_city_ranks_nothing_and_says_so(env):
    e = cities(filters={"REF_AREA_2": [COMMUNE]})
    assert (e["status"], e["reason"]) == ("unavailable", "no_eligible_entities")
    assert e["data"]["outside_class_count"] == 1 and e["data"]["intervals"][0]["rows"] == []
    assert "No municipality or town in the referenced catalogue" in e["message"]
    assert "does not prove historical city status" in e["message"]
    assert e["provenance"]["classification"]["member_count"] == 0


def test_percent_ranking_in_the_class_keeps_the_zero_baseline_rule(env):
    e = cities(metric="percent", order="desc", top_k=100)
    iv0 = e["data"]["intervals"][0]
    assert iv0["exclusion_counts"] == {"no_observation": 1, "value_missing": 1, "zero_baseline": 1}
    assert next(x for x in iv0["excluded"] if loc_of(x) == ZERO)["reason"] == "zero_baseline"
    top = iv0["rows"][0]
    # the best percent change among the catalogue cities, computed from the fixture
    best = max(((vals["2020"] - vals["2015"]) / vals["2015"] * 100, loc)
               for _, loc, vals in ENTITIES if loc in CITY_ROWS and loc not in (GONE, NULLED, ZERO))
    assert (top["percent"], loc_of(top)) == (pytest.approx(best[0], abs=1e-12), best[1])


def test_ties_break_by_the_full_key_inside_the_class(env):
    e = cities(intervals=[iv("2010", "2015")], top_k=6, order="asc")
    rows = e["data"]["intervals"][0]["rows"]
    # the two VALEA cities fell most (-200, -100); every other city with both endpoints moved by -3
    assert [(loc_of(r), r["absolute"]) for r in rows[:2]] == [(VALEA_A, -200.0), (VALEA_B, -100.0)]
    tied = rows[2:]
    assert [r["absolute"] for r in tied] == [-3.0] * 4
    keys = [(r["entity"]["REF_AREA"], r["entity"]["REF_AREA_2"]) for r in tied]
    assert keys == sorted(keys) == [("Alba", city(0)), ("Alba", city(2)), ("Alba", city(4)), ("Alba", city(6))]
    assert [r["rank"] for r in rows] == [1, 2, 3, 4, 5, 6]


# ============================================================ default "all" is unchanged

def test_the_default_class_is_the_existing_behavior(env):
    omitted = cc(top_k=10)
    explicit = cc(top_k=10, entity_class="all")
    assert omitted == explicit
    assert "entity_class" not in omitted["provenance"]["selection"] and "entity_class" not in omitted["data"]
    assert "classification" not in omitted["provenance"] and len(omitted["provenance"]["sources"]) == 1
    assert all(w["code"] != "classification_reference" for w in omitted["warnings"])
    # the existing all-entities ranking, from the fixture: the commune is first, totals are aggregates
    iv0 = omitted["data"]["intervals"][0]
    assert [(loc_of(r), r["absolute"]) for r in iv0["rows"][:3]] == [
        (COMMUNE, -89000.0), (city(229), -229.0), (city(228), -228.0)]
    assert iv0["exclusion_counts"] == {"aggregate_row": 1, "no_observation": 1, "value_missing": 1}


def test_default_replay_links_and_bundle_keep_their_exact_shape(env):
    omitted = cc(top_k=2)
    gid = omitted["provenance"]["generation"]["id"]
    links = call("get_evidence_links", selection=omitted["provenance"]["selection"], generation_id=gid)
    assert all("entity_class" not in link["url"] for link in links["data"]["links"])
    assert "entity_class" not in links["data"]["selection"]
    assert [s["dataset"] for s in links["provenance"]["sources"]] == ["CHG"]
    r = env.client.get("/api/period-changes/evidence", params=_params())
    z, _ = open_zip(r.content)
    assert sorted(z.namelist()) == sorted([
        "manifest.json", "selection.json", "result.csv", "exclusions.csv", "inputs/endpoints.csv",
        "method.json", "attribution.json", "README.txt", "recompute.py"])
    # recompute.py of a bundle without a class is the exact script of the baseline (955d81f)
    assert hashlib.sha256(z.read("recompute.py")).hexdigest() == \
        "b6ff242f22eb3b53d2eb0e649fac1463f4e4e4bdc50f6bf32fc6217533f905fe"
    method = json.loads(z.read("method.json"))
    assert "entity_class" not in method and "entity_class" not in json.loads(z.read("selection.json"))["normalized"]


def test_the_schema_accepts_all_and_cities_only_and_cities_need_the_locality_key():
    from app.services.tools import schemas as S
    base = {"dataset": "CHG", "entity_columns": ["REF_AREA", "REF_AREA_2"], "intervals": [iv("2015", "2020")]}
    assert S.ComparePeriodsArgs.model_validate(base).entity_class == "all"
    assert "entity_class" not in S.ComparePeriodsArgs.model_validate(base).model_dump(by_alias=True)
    assert S.ComparePeriodsArgs.model_validate({**base, "entity_class": "cities"}).model_dump(
        by_alias=True)["entity_class"] == "cities"
    for bad in ({"entity_class": "villages"}, {"entity_class": None}, {"entity_class": "cities", "entity_columns": ["REF_AREA"]}):
        with pytest.raises(Exception):
            S.ComparePeriodsArgs.model_validate({**base, **bad})
    props = S.ComparePeriodsArgs.model_json_schema(by_alias=True)["properties"]["entity_class"]
    assert props["default"] == "all" and props["enum"] == ["all", "cities"]
    assert "historical" in props["description"]


def test_invalid_class_requests_are_invalid_input_in_every_adapter(env):
    for kw in ({"entity_class": "villages"}, {"entity_class": "cities", "entity_columns": ["REF_AREA"]}):
        e = cc(**kw)
        assert (e["status"], e["reason"]) == ("error", "invalid_input")
    r = env.client.get("/api/period-changes", params={**_params(), "entity_class": "cities",
                                                      "entity_columns": json.dumps(["REF_AREA"])})
    assert r.status_code == 400 and r.json()["reason"] == "invalid_input"
    r = env.client.get("/api/period-changes/evidence", params={**_params(), "entity_class": "x"})
    assert r.status_code == 400


# ============================================================ wording and warnings

def test_the_class_is_worded_as_a_catalogue_class_with_its_qualification(env):
    e = cities(top_k=3)
    w = {x["code"]: x for x in e["warnings"]}
    msg = w["classification_reference"]["message"]
    assert "municipalities and towns in the referenced catalogue" in msg and "GOS102A" in msg
    assert "does not prove historical city status or unchanged boundaries" in msg
    assert "unchanged territory" in w["boundary_continuity_unverified"]["message"]
    assert "every eligible entity of the class 'municipalities and towns in the referenced catalogue' was ranked" \
        in e["message"]
    assert "does not prove historical city status or unchanged boundaries" in e["message"]
    assert "2 source entities outside the catalogue" in e["message"]
    assert "referenced catalogue" not in cc(top_k=3)["message"]
    cl = e["provenance"]["classification"]
    assert (cl["dataset"], cl["key"], cl["class"], cl["temporal_status"]) == (
        "GOS102A", "SIRUTA", "municipalities_and_towns", "catalogue_not_historical")
    assert cl["generation"] == GENERATION == e["provenance"]["generation"]["id"]
    assert cl["applied"] == "before eligibility, ranks and top_k"
    assert (cl["catalogue_count"], cl["member_count"]) == (len(CATALOGUE), len(CITY_ROWS))
    assert [s["role"] for s in e["provenance"]["sources"] if s.get("role")] == ["entity_classification"]
    assert e["provenance"]["selection"]["entity_class"] == "cities"


def test_series_break_notes_and_mixed_units_keep_their_existing_policy_inside_the_class(tmp_path, monkeypatch):
    # TUR105D has curated notes (a series break between 2020 and 2021): still a warning, now for a city class
    def build(corpus):
        names = ["1001 ORAS A", "1002 ORAS B"]
        add_dataset(corpus, "TUR105D", [area_dim(["Alba"]), area_dim(names, "locality", "REF_AREA_2"),
                                         time_dim(("2019", "2022")), unit_dim(UNIT)],
                    [("Alba", n, y, UNIT, v) for n, vs in zip(names, ((5.0, 9.0), (7.0, 6.0)))
                     for y, v in zip(("2019", "2022"), vs)])
        add_dataset(corpus, "GOS102A", [area_dim(names, "locality", "REF_AREA_2"), time_dim(("2024",)),
                                        unit_dim("Hectare")], [(n, "2024", "Hectare", 1.0) for n in names])
        add_dataset(corpus, "UNITX", [area_dim(["Alba"]), area_dim(names, "locality", "REF_AREA_2"),
                                      time_dim(("2000", "2010")), unit_dim(UNIT, "Mii persoane")],
                    [("Alba", n, y, u, 1.0) for n in names for y in ("2000", "2010") for u in (UNIT, "Mii persoane")])
    make_env(tmp_path, monkeypatch, build=build)
    e = call("compare_periods", dataset="TUR105D", entity_columns=["REF_AREA", "REF_AREA_2"],
             intervals=[iv("2019", "2022")], entity_class="cities", lang="en")
    w = {x["code"]: x for x in e["warnings"]}
    assert "Inside the compared interval 2019→2022" in w["series_break"]["message"]
    assert "coverage_note" in w and "classification_reference" in w
    assert [(r["entity"]["REF_AREA_2"], r["absolute"]) for r in e["data"]["intervals"][0]["rows"]] == [
        ("1002 ORAS B", -1.0), ("1001 ORAS A", 4.0)]
    u = call("compare_periods", dataset="UNITX", entity_columns=["REF_AREA", "REF_AREA_2"],
             intervals=[iv("2000", "2010")], entity_class="cities")
    assert (u["status"], u["reason"]) == ("unavailable", "mixed_units") and u["data"] == {}


# ============================================================ replay, links, evidence

def _params(**kw):
    p = {"dataset": "CHG", "entity_columns": json.dumps(["REF_AREA", "REF_AREA_2"]),
         "intervals": json.dumps([iv("2015", "2020")])}
    for k, v in kw.items():
        p[k] = v if isinstance(v, str) else json.dumps(v)
    return p


def _link(links, kind):
    return next(x["url"] for x in links["data"]["links"] if x["kind"] == kind)


def test_class_period_and_generation_survive_the_json_replay(env):
    first = cities(top_k=3, intervals=[iv("2010", "2015"), iv("2015", "2020")])
    sel, gid = first["provenance"]["selection"], first["provenance"]["generation"]["id"]
    assert sel["entity_class"] == "cities" and sel["intervals"] == [iv("2010", "2015"), iv("2015", "2020")]
    links = call("get_evidence_links", selection=sel, generation_id=gid, lang="en")     # the link carries the language
    assert links["status"] == "ok" and links["data"]["selection"]["entity_class"] == "cities"
    assert sorted(s["dataset"] for s in links["provenance"]["sources"]) == ["CHG", "GOS102A"]
    live = _link(links, "live_selection")
    assert "entity_class=cities" in live and "entity_class=cities" in _link(links, "evidence")
    replay = env.client.get(live)
    assert replay.status_code == 200 and replay.json() == first
    # a stale generation id produces no link at all
    stale = call("get_evidence_links", selection=sel, generation_id="gen-old")
    assert (stale["status"], stale["reason"]) == ("unavailable", "generation_changed")
    assert env.client.get(_link(links, "evidence").replace(gid, "gen-old")).status_code == 409
    # the recovery that points at the complete ranking carries the class
    rec = next(r for r in first["recovery"] if r["tool"] == "get_evidence_links")
    assert rec["arguments"]["selection"]["entity_class"] == "cities"


def _bundle(env, tmp_path, **kw):
    r = env.client.get("/api/period-changes/evidence", params=_params(entity_class="cities", **kw))
    assert r.status_code == 200, r.text
    z, m = open_zip(r.content)
    z.extractall(tmp_path)
    return z, m


def test_the_evidence_bundle_reproduces_the_classification_and_the_ranking_offline(env, tmp_path):
    z, m = _bundle(env, tmp_path, top_k="1")
    assert m["generation"]["id"] == GENERATION and m["kind"] == "period_changes"
    names = set(z.namelist())
    assert {"inputs/city_catalogue.csv", "classification.csv", "inputs/endpoints.csv", "recompute.py"} <= names
    sel = json.loads(z.read("selection.json"))
    assert sel["normalized"]["entity_class"] == "cities" and sel["requested"]["entity_class"] == "cities"
    assert sel["periods"] == {"2015": "2015", "2020": "2020"}
    method = json.loads(z.read("method.json"))
    assert method["intervals"] == [{"from": "2015", "to": "2020"}]
    ec = method["entity_class"]
    assert ec["class"] == "cities" and ec["reference"]["dataset"] == "GOS102A"
    assert ec["reference"]["generation"] == GENERATION and ec["reference"]["file"] == "inputs/city_catalogue.csv"
    assert "does not prove historical city status or unchanged boundaries" in ec["qualification"]
    assert (ec["member_count"], ec["outside_class_count"], ec["catalogue_count"]) == (len(CITY_ROWS), 2, len(CATALOGUE))
    assert any(w["code"] == "classification_reference" for w in method["warnings"])
    assert [s["dataset"] for s in json.loads(z.read("attribution.json"))["sources"]] == ["CHG", "GOS102A"]
    assert "referenced catalogue" in z.read("README.txt").decode() and "classification.csv" in z.read("README.txt").decode()

    # the complete class ranking, not the 1-row preview, and no commune anywhere in the outputs
    res = list(csv.reader(io.StringIO(z.read("result.csv").decode())))
    assert res[0][:9] == ["interval_from", "interval_to", "rank", "REF_AREA", "REF_AREA_2", "from_value",
                          "to_value", "absolute", "percent"]
    assert [(x[2], x[4], x[7]) for x in res[1:4]] == [
        ("1", city(229), "-229.0"), ("2", city(228), "-228.0"), ("3", city(227), "-227.0")]
    assert len(res) - 1 == len(expected())
    exc = list(csv.reader(io.StringIO(z.read("exclusions.csv").decode())))
    assert sorted((x[3], x[4], x[5]) for x in exc[1:]) == [
        (GONE, "no_observation", "to"), (NULLED, "value_missing", "to")]
    assert COMMUNE not in z.read("result.csv").decode() + z.read("exclusions.csv").decode()
    # the classification input stays: every entity, with its class
    cls = list(csv.reader(io.StringIO(z.read("classification.csv").decode())))
    assert cls[0] == ["REF_AREA", "REF_AREA_2", "siruta", "class"]
    by = {x[1]: (x[2], x[3]) for x in cls[1:]}
    assert by[COMMUNE] == ("9999", "outside_class") and by["Total"] == ("", "aggregate_row")
    assert by[city(229)] == ("1229", "member") and by[VALEA_B] == ("2002", "member")
    ep = list(csv.reader(io.StringIO(z.read("inputs/endpoints.csv").decode())))
    assert ["Alba", COMMUNE, "2015", "90000.0"] in ep
    cat = list(csv.reader(io.StringIO(z.read("inputs/city_catalogue.csv").decode())))
    assert cat[0] == ["siruta", "label"] and len(cat) - 1 == len(CATALOGUE) and ["1229", city(229)] in cat

    p = recompute(tmp_path)
    assert p.returncode == 0, p.stderr
    assert "classification.csv matches" in p.stderr and "result.csv matches" in p.stderr
    assert f"2015,2020,1,{county(N - 1)}/{city(N - 1)},-229.0," in p.stdout


def test_a_two_interval_class_bundle_recomputes_every_interval(env, tmp_path):
    z, _ = _bundle(env, tmp_path, intervals=[iv("2010", "2015"), iv("2015", "2020")])
    assert [(i["from"], i["to"]) for i in json.loads(z.read("method.json"))["intervals"]] == [
        ("2010", "2015"), ("2015", "2020")]
    res = list(csv.reader(io.StringIO(z.read("result.csv").decode())))[1:]
    first = [x for x in res if x[0] == "2010"]
    second = [x for x in res if x[0] == "2015"]
    assert len(first) == len(expected("asc", "2010", "2015")) and len(second) == len(expected())
    assert (first[0][4], first[0][7]) == (VALEA_A, "-200.0")           # the 2010 to 2015 leader
    p = recompute(tmp_path)
    assert p.returncode == 0, p.stderr
    assert "over 2 interval(s)" in p.stderr and "classification.csv matches" in p.stderr


def test_changing_the_membership_input_changes_the_offline_outcome(env, tmp_path):
    _bundle(env, tmp_path)
    assert recompute(tmp_path).returncode == 0
    cat = tmp_path / "inputs" / "city_catalogue.csv"
    original = cat.read_text()
    # the commune becomes a catalogue member: classification.csv and the ranking no longer match
    cat.write_text(original + f"9999,{COMMUNE}\n")
    r = recompute(tmp_path)
    assert r.returncode == 1 and "classification.csv DIFFERS" in r.stderr
    cat.write_text(original.replace(f"1229,{city(229)}\n", ""))        # the winner leaves the catalogue
    assert recompute(tmp_path).returncode == 1
    cat.write_text(original)
    cls = tmp_path / "classification.csv"
    text = cls.read_text()
    cls.write_text(text.replace("9999,outside_class", "9999,member"))
    assert recompute(tmp_path).returncode == 1
    cls.write_text(text)
    assert recompute(tmp_path).returncode == 0


def test_the_bundle_route_enforces_the_generation_and_the_class_in_its_link(env, tmp_path):
    r = env.client.get("/api/period-changes/evidence", params=_params(entity_class="cities",
                                                                      expected_generation="gen-old"))
    assert r.status_code == 409
    sel = json.loads(open_zip(env.client.get("/api/period-changes/evidence",
                                             params=_params(entity_class="cities")).content)[0].read("selection.json"))
    assert "entity_class=cities" in sel["link"] and sel["link"].startswith("/api/period-changes?")


def test_bundle_with_a_refused_class_is_not_built(tmp_path, monkeypatch):
    e = make_env(tmp_path, monkeypatch, build=lambda c: build_chg(c, catalogue=None))
    r = e.client.get("/api/period-changes/evidence", params=_params(entity_class="cities"))
    assert r.status_code == 422 and r.json()["detail"]["reason"] == "classification_unavailable"


# ============================================================ Ask follow-ups and presentation

def test_ask_follow_ups_keep_the_class_and_reject_a_forged_one(env):
    from fastapi import HTTPException
    from app.services import ask_context, ask_present
    e = cities(top_k=3)
    entry = ask_context.entry_from_envelope("compare_periods", e)
    assert entry["selection"]["entity_class"] == "cities" and entry["generation"] == GENERATION
    assert "GOS102A" in [s["dataset"] for s in entry["sources"]]
    clean = ask_context.validate([entry])[0]
    from app.services.tools import schemas as S
    assert S.PeriodChangesSelection.model_validate(clean["selection"]) == \
        S.PeriodChangesSelection.model_validate(entry["selection"])      # same class, same years
    assert clean["selection"]["entity_class"] == "cities" and clean["generation"] == GENERATION
    assert [(i["to"]) for i in clean["selection"]["intervals"]] == ["2020"]
    assert "entity_class" in ask_context.prompt_section([clean])
    forged = {**entry, "selection": {**entry["selection"], "entity_class": "villages"}}
    with pytest.raises(HTTPException) as ex:
        ask_context.validate([forged])
    assert ex.value.status_code == 400
    no_key = {**entry, "selection": {**entry["selection"], "entity_columns": ["REF_AREA"]}}
    with pytest.raises(HTTPException):
        ask_context.validate([no_key])
    # the default selection is still a valid follow-up, without any class key
    plain = ask_context.entry_from_envelope("compare_periods", cc(top_k=2))
    assert "entity_class" not in ask_context.validate([plain])[0]["selection"]

    packed = ask_context.compact(e, "call-1")
    assert packed["result"]["entity_class"] == "cities" and packed["result"]["outside_class_count"] == 2
    assert packed["classification"]["dataset"] == "GOS102A" and packed["classification"]["generation"] == GENERATION
    assert packed["selection"]["entity_class"] == "cities"
    assert any("does not prove historical city status" in w["message"] for w in packed["warnings"])
    assert "entity_class" not in ask_context.compact(cc(top_k=2), "call-2")["result"]

    table = ask_present.display_table([{"tool": "compare_periods", "id": "c", "output": e}])
    assert any("does not prove historical city status or unchanged boundaries" in w for w in table["warnings"])
    assert table["rows"][0][:2] == [county(N - 1), city(N - 1)]


# ============================================================ public MCP: same results, same limits

def test_public_mcp_serves_the_city_change_and_keeps_its_scan_and_deadline_limits(env, tmp_path, monkeypatch):
    import asyncio
    import at03_env as E
    from app.services.tools import registry
    from test_at03_resources import heavy, wait_until
    args = {"dataset": "CHG", "entity_columns": ["REF_AREA", "REF_AREA_2"], "entity_class": "cities",
            "intervals": [iv("2015", "2020")], "top_k": 3}
    app, mcp = E.make_app(tmp_path, monkeypatch, env=env)

    async def invoke(app):
        async with E.started(app), E.session(app) as client:
            tools = {t.name: t for t in (await client.list_tools()).tools}
            return tools["compare_periods"], E.payload(await client.call_tool("compare_periods", args))
    tool, (structured, text) = asyncio.run(invoke(app))
    assert structured == text and structured["data"]["entity_class"] == "cities"
    assert structured["data"]["intervals"][0]["rows"] == registry.call_tool("compare_periods", args)["data"]["intervals"][0]["rows"]
    prop = tool.inputSchema["properties"]["entity_class"]
    assert prop["enum"] == ["all", "cities"] and prop["default"] == "all"
    assert "historical" in tool.description and "classification_reference" in {w["code"] for w in structured["warnings"]}

    limited, _ = E.make_app(tmp_path, monkeypatch, env=env, environ={"TEMPO_MCP_MAX_SCAN_ROWS": "100"})
    structured, _ = asyncio.run(invoke(limited))[1]
    assert structured["status"] == "unavailable" and structured["reason"] == "query_budget"

    slow, mcp2 = E.make_app(tmp_path, monkeypatch, env=env, environ={"TEMPO_MCP_MAX_SECONDS": "1"})
    seen = []
    heavy(monkeypatch, seen)

    async def timed(app):
        async with E.started(app), E.session(app) as client:
            return E.payload(await client.call_tool("compare_periods", args))[0]
    out = asyncio.run(timed(slow))
    assert (out["status"], out["reason"]) == ("unavailable", "query_timeout")
    assert seen and seen[0][0] == "interrupted" and wait_until(lambda: mcp2.gate.active == 0)


# ============================================================ real corpus (read-only, generation-pinned)

@pytest.mark.corpus
def test_real_city_decline_between_2015_and_2020(real, tmp_path):
    """Generation 9b3e065d: POP107D_grupe_localitate (population by domicile), 319 catalogue
    cities of 3,181 localities with both endpoints. Values verified independently by DuckDB over
    the parquet and the GOS102A catalogue (aq05a record)."""
    args = {"dataset": "POP107D_grupe_localitate", "entity_columns": ["REF_AREA", "REF_AREA_2"],
            "intervals": [iv("2015", "2020")], "order": "asc", "top_k": 3, "entity_class": "cities"}
    e = call("compare_periods", **args)
    iv0 = e["data"]["intervals"][0]
    assert iv0["eligible_count"] == 319 and iv0["excluded_count"] == 0
    assert e["data"]["outside_class_count"] == 2862 and e["data"]["unit"] == "Numar persoane"
    assert [(loc_of(r), r["from_value"], r["to_value"], r["absolute"]) for r in iv0["rows"]] == [
        ("42682 MUNICIPIUL BRAILA", 213169.0, 200342.0, -12827.0),
        ("130534 MUNICIPIUL PLOIESTI", 235114.0, 225171.0, -9943.0),
        ("155243 MUNICIPIUL TIMISOARA", 333998.0, 325583.0, -8415.0)]
    # where the class matters: Floresti, a commune, is 4th by growth until the class is applied
    grow = {**args, "order": "desc", "top_k": 5}
    top = lambda **kw: [loc_of(r) for r in call("compare_periods", **{**grow, **kw})["data"]["intervals"][0]["rows"]]
    assert "57706 FLORESTI" in top(entity_class="all") and "57706 FLORESTI" not in top()
    assert top()[-1] == "146263 MUNICIPIUL SUCEAVA"
    from fastapi.testclient import TestClient
    from app.main import app
    q = {"dataset": args["dataset"], "entity_columns": json.dumps(args["entity_columns"]),
         "intervals": json.dumps(args["intervals"]), "order": "asc", "top_k": "3", "entity_class": "cities"}
    r = TestClient(app).get("/api/period-changes/evidence", params=q)
    assert r.status_code == 200
    z, m = open_zip(r.content)
    assert m["generation"]["id"].startswith(PINNED)
    z.extractall(tmp_path)
    p = recompute(tmp_path)
    assert p.returncode == 0, p.stderr
    assert "recomputed 319 ranked rows" in p.stderr and "classified 3181 entities (319 municipalities/towns" in p.stderr
