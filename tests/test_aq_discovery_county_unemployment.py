"""Owner decisions of 2026-10-17 on tool discovery (policy changes to the reviewed AQ-04A configuration).

1. A county named in a city ranking narrows it to the cities of that county. Discovery offers
   rank_entities / compare_periods with filters {REF_AREA: <the county's exact label>} and the shared
   tool applies them before eligibility and top K. Two counties, a county named like a city
   (Cluj-Napoca), Municipiul Bucuresti, a county the series has no label for and a region stay reported
   as not applied.
2. The generic unemployment rate defaults by level: a county (named, or "by county") is the registered
   rate, the nation is the ILO rate, each disclosed; a region, a level that cannot be told, two levels
   at once and a question with no level at all keep the clarification. A definition the question names
   is never replaced.

Synthetic corpus with the production dataset codes and the shipped concepts and policy. Known values:

  POP107D_grupe_localitate (domicile, REF_AREA county, REF_AREA_2 locality), 2024 -> 2025
    Cluj:   CITY000..CITY229  100 -> 100 + i   (the largest, CITY229 329, is the last row of the file,
                                                beyond any 200-row preview), COMUNA GIANT 900000 -> 999999
    Iasi:   MUNICIPIUL IASI 285000 -> 290000, ORAS HARLAU 9000 -> 9500, COMUNA IASIC 800000 -> 800500
    Municipiul Bucuresti: MUNICIPIUL BUCURESTI 1900000 -> 2000000
  GOS102A lists the 233 cities. SOM103A_judete (registered: 3.0 in 2022, +10 a year, so 13.0 in 2023) and
  AMG157A_anual (ILO, 5.5 every year) carry the unemployment series; Arad has a registered rate but no
  localities.
"""
import json

import pytest

from app.services import concept_search as cs
from app.services import dataset_search
from app.services.tools import discovery_policy as dp
from app.services.tools import messages as M
from at01_fixtures import add_dataset, add_search_columns, call, make_env, said
from test_aq04a_discovery_defaults import (POP, YEARS, _series, area_dim, card, catalogue, codes, run, shipped)
from test_at01_changes import time_dim, unit_dim
from test_at01_discovery import real  # noqa: F401 — the pinned-generation probe fixture

N = 230
UNIT = "Numar persoane"
LOCALITY = "POP107D_grupe_localitate"
REGISTERED, ILO = "registered_unemployment_rate", "ilo_unemployment_rate"
BUCHAREST = "Municipiul București"


def cj(i):
    return f"{1000 + i} ORAS CITY{i:03}"


IASI, HARLAU = "95000 MUNICIPIUL IASI", "96000 ORAS HARLAU"
BUC = "179132 MUNICIPIUL BUCURESTI"
G_CLUJ, G_IASI = "9000 COMUNA GIANT", "9100 COMUNA IASIC"
ENTITIES = (
    [("Cluj", cj(i), 100.0, 100.0 + i) for i in range(N)]
    + [("Cluj", G_CLUJ, 900000.0, 999999.0),
       ("Iași", IASI, 285000.0, 290000.0), ("Iași", HARLAU, 9000.0, 9500.0), ("Iași", G_IASI, 800000.0, 800500.0),
       (BUCHAREST, BUC, 1900000.0, 2000000.0)])
CITIES = [loc for _, loc, *_ in ENTITIES if "COMUNA" not in loc]
COUNTIES = ["Cluj", "Iași", BUCHAREST]
REGIONS = ["Nord-Vest", "Sud-Est"]


def build(corpus):
    add_dataset(corpus, LOCALITY,
                [area_dim(COUNTIES), area_dim([loc for _, loc, *_ in ENTITIES], "locality", "REF_AREA_2"),
                 time_dim(["2024", "2025"]), unit_dim(UNIT)],
                [(c, loc, y, UNIT, v) for c, loc, a, b in ENTITIES for y, v in (("2024", a), ("2025", b))],
                name="Populatia dupa domiciliu pe localitati")
    add_dataset(corpus, "GOS102A", [area_dim(CITIES, "locality", "REF_AREA_2"), time_dim(["2024"]), unit_dim("Hectare")],
                [(c, "2024", "Hectare", 10.0) for c in CITIES], name="Localitati")
    base = {"Cluj": 700.0, "Iași": 800.0, BUCHAREST: 1900.0}
    _series(corpus, "POP105A_judete_grupe", "Populatia rezidenta", base)
    _series(corpus, "POP107A_judete_grupe", "Populatia dupa domiciliu", base, shift=-20)
    _series(corpus, "SOM103A_judete", "Somaj inregistrat", {**{a: 3.0 for a in COUNTIES}, "Arad": 3.0},
            names=COUNTIES + ["Arad"], unit="Procente", unit_type="percentage")
    _series(corpus, "SOM103A_regiuni", "Somaj inregistrat regiuni", {r: 4.0 for r in REGIONS}, names=REGIONS,
            level="region", unit="Procente", unit_type="percentage")
    add_dataset(corpus, "AMG157A_anual", [area_dim(["Romania"], "national"), time_dim(list(YEARS)), unit_dim("Procente")],
                [("Romania", y, "Procente", 5.5) for y in YEARS], name="Somaj BIM", unit_type="percentage")
    add_dataset(corpus, "AMG157F", [area_dim(REGIONS, "region"), time_dim(list(YEARS)), unit_dim("Procente")],
                [(r, y, "Procente", 6.5) for r in REGIONS for y in YEARS], name="Somaj BIM regiuni", unit_type="percentage")
    add_search_columns(corpus)      # datasets cannot be added after these


@pytest.fixture
def env(tmp_path, monkeypatch):
    e = make_env(tmp_path, monkeypatch, build=build)
    monkeypatch.setattr(dataset_search, "SEARCH_DB_PATH", tmp_path / "no-fts.duckdb")
    dataset_search._reset_for_tests()
    yield e
    monkeypatch.undo()
    dataset_search._reset_for_tests()


def disc(query, lang="ro", **kw):
    return call("discover_indicators", query=query, lang=lang, **kw)


def use_policy(monkeypatch, tmp_path, edit):
    """Run with the shipped configuration edited by `edit` (the tests of configuration and rollback)."""
    raw = shipped()
    edit(raw)
    path = tmp_path / "policy.json"
    path.write_text(json.dumps(raw), encoding="utf-8")
    monkeypatch.setattr(dp, "POLICY_PATH", path)
    return raw


def rows_of(res):
    return [(r["rank"], r["entity"]["REF_AREA"], r["entity"]["REF_AREA_2"], r["value"]) for r in res["data"]["rows"]]


def call_of(out):
    return card(out, "domicile_population")["next_call"]


def reported(out, text=None):
    """The geography reported as not applied (and the data call withheld), or None when it was applied."""
    unapplied = [c for c in out["data"]["interpretation"]["unapplied_constraints"] if c["kind"] == "geography"]
    if not unapplied:
        return None
    assert call_of(out)["tool"] == "describe_dataset" and "constraint_not_applied" in codes(out)
    assert "place_filter_applied" not in codes(out)
    if text is not None:
        assert unapplied == [{"kind": "geography", "text": text}]
    return unapplied


# ================================================================== 1. a county narrows a city ranking

@pytest.mark.parametrize("question,lang", [
    ("top 3 cities in Cluj by population", "en"), ("top 3 orase din Cluj dupa populatie", "ro"),
    ("the 3 most populated cities of Cluj county", "en"), ("primele 3 orase din judetul Cluj dupa populatie", "ro"),
])
def test_a_named_county_narrows_the_ranking_and_the_shared_tool_applies_it_before_top_k(env, question, lang):
    out = disc(question, lang)
    assert out["status"] == "ok" and out["data"]["interpretation"]["unapplied_constraints"] == []
    nc = call_of(out)
    assert nc == {"tool": "rank_entities", "arguments": {
        "dataset": LOCALITY, "entity_columns": ["REF_AREA", "REF_AREA_2"], "entity_class": "cities", "year": None,
        "filters": {"REF_AREA": ["Cluj"]}, "top_k": 3, "order": "desc", "lang": lang}}
    res = run(nc)
    d = res["data"]
    assert d["year"] == "2025" and d["entity_class"] == "cities"
    # Iasi (290000) is larger than every Cluj city and the Cluj commune (999999) is larger than all: neither is listed
    assert rows_of(res) == [(1, "Cluj", cj(229), 329.0), (2, "Cluj", cj(228), 328.0), (3, "Cluj", cj(227), 327.0)]
    # eligibility and the outside-class count are for the county alone
    assert d["eligible_count"] == N and d["outside_class_count"] == 1 and d["excluded_count"] == 0
    assert res["limits"]["total_rows"] == N
    assert said(res["provenance"]["selection"]["filters"]["REF_AREA"][0], lang, "Cluj", "Cluj")


def test_the_winner_beyond_row_two_hundred_of_the_county_is_found(env):
    """CITY229 is the last row of the county's data: a preview of 200 rows cannot contain it, so the ranking
    cannot have been taken from one, and no top K of the national list can have been filtered afterwards."""
    raw = call("query_data", dataset=LOCALITY, filters={"REF_AREA": ["Cluj"], "TIME_PERIOD": ["2025"]},
               group_by=["REF_AREA", "REF_AREA_2"], limit=200)
    assert len(raw["data"]["rows"]) == 200 and raw["limits"]["preview_truncated"] is True
    assert not any(cj(229) in str(r) for r in raw["data"]["rows"])
    res = run(call_of(disc("top 1 cities in Cluj by population", "en")))
    assert rows_of(res) == [(1, "Cluj", cj(229), 329.0)]
    # the national top 3 holds no Cluj city at all (Bucuresti, Iasi, Harlau) and cities were ranked before the cut
    national = run(call_of(disc("top 3 cities by population", "en")))
    assert [r[2] for r in rows_of(national)] == [BUC, IASI, HARLAU]


def test_the_exact_label_of_the_series_is_used_not_the_wording_of_the_question(env):
    nc = call_of(disc("top 3 cities in Iasi by population in 2024", "en"))
    assert nc["arguments"]["filters"] == {"REF_AREA": ["Iași"]} and nc["arguments"]["year"] == "2024"
    res = run(nc)
    assert rows_of(res) == [(1, "Iași", IASI, 285000.0), (2, "Iași", HARLAU, 9000.0)]
    assert res["data"]["eligible_count"] == 2 and res["data"]["outside_class_count"] == 1


def test_the_narrowing_is_disclosed_next_to_the_call_and_replaces_the_no_county_level_note(env):
    for lang, fragment in (("en", "Cities in Cluj only"), ("ro", "Doar orașele din Cluj")):
        out = disc("top 3 cities in Cluj by population" if lang == "en" else "top 3 orase din Cluj dupa populatie", lang)
        w = next(w for w in out["warnings"] if w["code"] == "place_filter_applied")
        assert w["subject"] == "Cluj" and fragment in w["message"]
        assert "assumed_definition" in codes(out) and "constraint_not_applied" not in codes(out)   # the domicile default stays
        c = card(out, "domicile_population")
        assert "place_level_unavailable" not in [n["code"] for n in c["notes"]]
        assert "place_filter_applied" in [n["code"] for n in c["candidates"][0]["notes"]]
        assert out["data"]["interpretation"]["places"] == [{"slug": "cluj", "name": "Cluj", "type": "county"}]


def test_a_county_narrows_a_city_change_ranking_too(env):
    out = disc("top 3 cities in Cluj by population growth between 2024 and 2025", "en")
    nc = call_of(out)
    assert nc["tool"] == "compare_periods" and nc["arguments"]["filters"] == {"REF_AREA": ["Cluj"]}
    assert nc["arguments"]["entity_class"] == "cities" and nc["arguments"]["intervals"] == [{"from": "2024", "to": "2025"}]
    assert {"classification_reference", "place_filter_applied", "assumed_definition"} <= set(codes(out))
    res = run(nc)
    iv = res["data"]["intervals"][0]
    # nationally the Cluj commune (+99999), Bucuresti (+100000), Iasi (+5000) lead; within Cluj the cities rank by their own change
    assert [(r["rank"], r["entity"]["REF_AREA_2"], r["absolute"]) for r in iv["rows"]] == [
        (1, cj(229), 229.0), (2, cj(228), 228.0), (3, cj(227), 227.0)]
    assert iv["eligible_count"] == N and res["data"]["outside_class_count"] == 1
    assert "Iași" not in json.dumps(res["data"]) and G_CLUJ not in json.dumps(res["data"])
    everyone = run(call_of(disc("top 3 cities by population growth between 2024 and 2025", "en")))
    assert everyone["data"]["intervals"][0]["rows"][0]["entity"]["REF_AREA_2"] == BUC


def test_the_shared_tools_filter_before_eligibility_and_top_k(env):
    """What discovery relies on, checked on the tools themselves with their existing `filters`."""
    args = dict(dataset=LOCALITY, entity_columns=["REF_AREA", "REF_AREA_2"], entity_class="cities", top_k=2)
    inside = call("rank_entities", filters={"REF_AREA": ["Cluj"]}, **args)
    assert [r[2] for r in rows_of(inside)] == [cj(229), cj(228)] and inside["data"]["eligible_count"] == N
    after_cut = [r for r in rows_of(call("rank_entities", **args)) if r[1] == "Cluj"]
    assert after_cut == [] and len(rows_of(inside)) == 2         # filtering a national top K afterwards would return nothing
    change = call("compare_periods", filters={"REF_AREA": ["Iași"]}, dataset=LOCALITY, entity_columns=["REF_AREA", "REF_AREA_2"],
                  entity_class="cities", intervals=[{"from": "2024", "to": "2025"}], order="desc", top_k=5)
    assert [r["entity"]["REF_AREA_2"] for r in change["data"]["intervals"][0]["rows"]] == [IASI, HARLAU]
    assert change["data"]["intervals"][0]["eligible_count"] == 2 and change["data"]["outside_class_count"] == 1


# ------------------------------------------------------------------ what is NOT narrowed

@pytest.mark.parametrize("question,lang,text", [
    ("top 3 cities in Cluj and Iasi by population", "en", "Cluj, Iași"),
    ("top 3 orase din Cluj si Iasi dupa populatie", "ro", "Cluj, Iași"),
    ("top 3 cities in Cluj-Napoca by population", "en", "Cluj"),                 # a city's name, not the county
    ("top 3 orase din Cluj-Napoca dupa populatie", "ro", "Cluj"),
    ("top 3 cities in the city Cluj by population", "en", "Cluj"),
    ("top 3 orase din orasul Cluj dupa populatie", "ro", "Cluj"),
    ("top 3 cities in the Nord-Vest region by population", "en", "Nord-Vest"),     # regions are not in scope
    ("top 3 orase din regiunea Nord-Vest dupa populatie", "ro", "Nord-Vest"),
    ("top 3 orase din Nord-Vest dupa populatie", "ro", "Nord-Vest"),
    ("top 3 cities in Cluj and the Nord-Vest region by population", "en", "Cluj, Nord-Vest"),
])
def test_two_counties_a_city_name_and_a_region_are_reported_not_applied(env, question, lang, text):
    out = disc(question, lang)
    assert out["status"] == "ok"
    assert reported(out, text)
    assert card(out, "domicile_population")["next_call"]["arguments"]["dataset"] == LOCALITY


@pytest.mark.parametrize("question,lang", [
    ("top 3 cities in Bucuresti by population", "en"), ("top 3 cities in Bucharest by population", "en"),
    ("top 3 orase din Bucuresti dupa populatie", "ro"), ("top 3 orase din Municipiul București dupa populatie", "ro"),
])
def test_bucharest_is_one_municipality_and_never_a_county_filter(env, question, lang):
    """Decision (documented in the record): "Bucuresti" names the municipality and the county-level unit
    "Municipiul Bucuresti" at once, and that unit holds exactly one city. Narrowing to it would answer a
    one-row ranking for a question that probably means something else (the sectors, the area around it), so
    it is reported as not applied, like a city's name."""
    out = disc(question, lang)
    assert reported(out, BUCHAREST)
    assert not [c for c in out["data"]["concepts"][0]["candidates"] if (c["next_call"] or {}).get("tool") == "rank_entities"]


def test_removing_the_exception_is_the_one_line_that_narrows_to_bucharest(env, monkeypatch, tmp_path):
    use_policy(monkeypatch, tmp_path, lambda p: p["population"]["cities"]["place_filter"].update({"except": []}))
    out = disc("top 3 cities in Bucharest by population", "en")
    nc = call_of(out)
    assert nc["arguments"]["filters"] == {"REF_AREA": [BUCHAREST]}
    res = run(nc)
    assert rows_of(res) == [(1, BUCHAREST, BUC, 2000000.0)] and res["data"]["eligible_count"] == 1


def test_a_county_the_series_has_no_label_for_is_reported_not_guessed(env):
    out = disc("top 3 cities in Arad by population", "en")        # Arad has a county series, but no localities
    assert reported(out, "Arad")


def test_a_county_with_two_labels_is_never_resolved_to_one(env, monkeypatch):
    from app.services import data_query
    real_values = data_query.dimension_values

    def doubled(conn, code, column, **kw):
        out = real_values(conn, code, column, **kw)
        if code == LOCALITY and column == "REF_AREA":
            out = {**out, "values": out["values"] + ["CLUJ", "Cluj "], "total": out["total"] + 2}
        return out
    monkeypatch.setattr(data_query, "dimension_values", doubled)
    assert reported(disc("top 3 cities in Cluj by population", "en"), "Cluj")


def test_a_label_list_that_cannot_be_read_in_full_applies_nothing(env, monkeypatch):
    from app.services import data_query
    real_values = data_query.dimension_values

    def cut(conn, code, column, **kw):
        out = real_values(conn, code, column, **kw)
        return {**out, "total": out["total"] + 1} if code == LOCALITY else out
    monkeypatch.setattr(data_query, "dimension_values", cut)
    assert reported(disc("top 3 cities in Cluj by population", "en"), "Cluj")


def test_another_unapplied_constraint_leaves_the_county_reported_too(env):
    """Nothing is half-applied: with a sex constraint no data call is offered at all, so the county is
    reported with it instead of being dropped."""
    out = disc("top 3 cities in Cluj by female population", "en")
    kinds = {c["kind"] for c in out["data"]["interpretation"]["unapplied_constraints"]}
    assert kinds == {"sex", "geography"} and "place_filter_applied" not in codes(out)
    assert call_of(out)["tool"] == "describe_dataset"


def test_questions_without_a_county_are_exactly_as_before(env):
    nc = call_of(disc("top 3 cities by population", "en"))
    assert nc["arguments"]["filters"] == {} and "place_filter_applied" not in codes(disc("top 3 cities by population", "en"))
    out = disc("population of Cluj in 2024", "en")            # a county around a county question: unchanged
    assert out["data"]["interpretation"]["unapplied_constraints"] == [] and "place_filter_applied" not in codes(out)


def test_the_county_narrowing_is_configuration_and_its_removal_restores_the_report(env, monkeypatch, tmp_path):
    use_policy(monkeypatch, tmp_path, lambda p: p["population"]["cities"].pop("place_filter"))
    for q in ("top 3 cities in Cluj by population", "top 3 cities in Cluj by population growth between 2024 and 2025"):
        out = disc(q, "en")
        assert reported(out, "Cluj")
        assert card(out, "domicile_population")["notes"][0]["code"] == "place_level_unavailable"
    assert call_of(disc("top 3 cities by population", "en"))["tool"] == "rank_entities"


# ------------------------------------------------------------------ the pure pieces

def place(slug="cluj", name="Cluj", **extra):
    return {"slug": slug, "name": name, "type": "county", **extra}


RULE = {"level": "county", "column": "REF_AREA", "except": ["municipiul-bucuresti"]}


@pytest.mark.parametrize("places,labels,rule,expected", [
    ([place()], ["Alba", "Cluj", "Iași"], RULE, {"REF_AREA": ["Cluj"]}),
    ([place("bistrita-nasaud", "Bistrița-Năsăud")], ["Bistrita-Nasaud", "Cluj"], RULE, {"REF_AREA": ["Bistrita-Nasaud"]}),
    ([place("iasi", "Iași")], ["Iași"], RULE, {"REF_AREA": ["Iași"]}),
    ([place()], ["Alba", "Iași"], RULE, None),                                       # no such label
    ([place()], ["Cluj", "CLUJ"], RULE, None),                                       # two labels
    ([place(), place("iasi", "Iași")], ["Cluj", "Iași"], RULE, None),                # two counties
    ([], ["Cluj"], RULE, None),
    ([place(ambiguous=True, note="city_not_county")], ["Cluj"], RULE, None),         # Cluj-Napoca, "orasul Cluj"
    ([place("municipiul-bucuresti", BUCHAREST)], [BUCHAREST], RULE, None),           # excepted
    ([place("municipiul-bucuresti", BUCHAREST)], [BUCHAREST], {**RULE, "except": []}, {"REF_AREA": [BUCHAREST]}),
    ([place()], ["Cluj"], None, None),                                                # no rule: nothing is narrowed
])
def test_county_filter(places, labels, rule, expected):
    assert dp.county_filter(places, labels, rule) == expected


def test_geography_levels(env):
    from app.db import get_conn
    conn = get_conn()
    read = lambda q: dp.read_geography(q, conn)            # noqa: E731
    cases = {
        "rata somajului in Cluj": ("county", ["Cluj"], []), "unemployment rate by county": ("county", [], []),
        "somaj pe judete in Romania": ("county", [], []), "somaj in Cluj, Romania": ("county", ["Cluj"], []),
        "somaj Romania": ("national", [], []), "unemployment nationwide": ("national", [], []),
        "somaj la nivel national": ("national", [], []), "somaj pe tara": ("national", [], []),
        "somaj in regiunea Nord-Vest": ("region", [], ["Nord-Vest"]), "somaj Sud Est": ("region", [], ["Sud-Est"]),
        "unemployment by region": ("region", [], []), "unemployment by macroregion": ("region", [], []),
        "somaj pe judete si regiuni": ("ambiguous", [], []), "somaj Cluj Nord-Vest": ("ambiguous", ["Cluj"], ["Nord-Vest"]),
        "somaj in Cluj si pe regiuni": ("ambiguous", ["Cluj"], []),
        "somaj": ("unspecified", [], []), "unemployment rate 2023": ("unspecified", [], []),
    }
    for q, (level, counties, regions) in cases.items():
        g = read(q)
        assert (g.level(), [p["name"] for p in g.places], list(g.regions)) == (level, counties, regions), q


# ================================================================== 2. unemployment by level

def asked(out):
    assert out["status"] == "needs_clarification" and out["reason"] == "ambiguous_definition"
    assert {c["id"] for c in out["data"]["choices"]} == {REGISTERED, ILO}
    assert out["data"]["interpretation"]["assumed_definition"] is None and "assumed_definition" not in codes(out)
    assert all(c["next_call"] is None and c["requires_choice"] for c in out["data"]["concepts"])
    for choice in out["data"]["choices"]:                  # choosing stays a separate, specific call
        assert run(choice["next_call"])["data"]["concepts"][0]["id"] == choice["id"]


def defaulted(out, cid, lang):
    assert out["status"] == "ok" and out["data"]["choices"] == []
    assert out["data"]["interpretation"]["assumed_definition"] == cid
    warn = next(w for w in out["warnings"] if w["code"] == "assumed_definition")
    assert warn["subject"] == cid
    c = card(out, cid)
    assert c["assumed"] is True and not c["requires_choice"] and c["next_call"]["tool"] == "query_data"
    assert [a["id"] for a in c["alternatives"]] == [ILO if cid == REGISTERED else REGISTERED]    # the other stays one call away
    return warn["message"], c


COUNTY_LEVEL = [
    ("rata somajului in Cluj 2023", "ro"), ("unemployment rate in Cluj 2023", "en"), ("somaj Cluj", "ro"),
    ("rata somajului in judetul Iasi", "ro"), ("unemployment in Iasi county", "en"),
    ("rata somajului pe judete 2023", "ro"), ("unemployment rate by county 2023", "en"),
    ("rata somajului pe judete in Romania", "ro"), ("rata somajului in Cluj, Romania", "ro"),
    ("unemployment rate in Bucharest", "en"),
]


@pytest.mark.parametrize("question,lang", COUNTY_LEVEL)
def test_a_county_level_question_defaults_to_the_registered_rate_and_says_ilo_has_no_county_series(env, question, lang):
    out = disc(question, lang)
    msg, c = defaulted(out, REGISTERED, lang)
    assert said(msg, lang, "Registered unemployment rate, taking the question at the county level",
                "Rata șomajului înregistrat, luând întrebarea la nivel de județ")
    assert said(msg, lang, "ILO unemployment rate (survey) has no county-level series in the reviewed catalogue (it covers: national, region)",
                "Rata șomajului BIM (anchetă) nu are serie la nivel de județ în catalogul revizuit (acoperă: țară, regiune)")
    assert said(msg, lang, "alternatives remain available", "alternativele rămân disponibile")
    assert c["candidates"][0]["dataset"] == "SOM103A_judete" and c["candidates"][0]["level"] == "county"
    named = out["data"]["interpretation"]["places"]
    if named:
        assert c["next_call"]["arguments"]["filters"]["REF_AREA"] and c["next_call"]["arguments"]["dataset"] == "SOM103A_judete"
    assert "ambiguous_definition" not in [a["reason"] for a in out["data"]["interpretation"]["ambiguities"] if "reason" in a]


def test_the_county_default_answers_with_the_registered_figure_of_the_named_county_and_year(env):
    out = disc("unemployment rate in Cluj 2023", "en")
    nc = card(out, REGISTERED)["next_call"]
    assert nc["arguments"]["filters"] == {"REF_AREA": ["Cluj"], "TIME_PERIOD": ["2023"]}
    assert run(nc)["data"]["rows"] == [["Cluj", "2023", 13.0]]       # 3.0 in 2022, +10 a year


def with_national(monkeypatch, tmp_path):
    """The national ILO default is not shipped (owner, 2026-10-18), but the mechanism stays tested."""
    use_policy(monkeypatch, tmp_path, lambda p: _entry(p)["levels"].update(national=ILO))


NATIONAL_LEVEL = [
    ("rata somajului in Romania 2023", "ro"), ("unemployment rate in Romania 2023", "en"),
    ("rata somajului la nivel national", "ro"), ("national unemployment rate", "en"), ("unemployment rate nationwide", "en"),
    ("rata somajului pe tara", "ro"), ("Cum a evoluat rata somajului in Romania in ultimii ani?", "ro"),
]


@pytest.mark.parametrize("question,lang", NATIONAL_LEVEL)
def test_the_shipped_policy_still_asks_at_national_level(env, question, lang):
    asked(disc(question, lang))


@pytest.mark.parametrize("question,lang", NATIONAL_LEVEL)
def test_a_national_rule_would_default_to_the_ilo_rate_and_say_registered_has_no_national_series(
        env, monkeypatch, tmp_path, question, lang):
    with_national(monkeypatch, tmp_path)
    out = disc(question, lang)
    msg, c = defaulted(out, ILO, lang)
    assert said(msg, lang, "ILO unemployment rate (survey), taking the question at the national level",
                "Rata șomajului BIM (anchetă), luând întrebarea la nivel de țară")
    assert said(msg, lang, "Registered unemployment rate has no national-level series in the reviewed catalogue "
                           "(it covers: county, region, macroregion)",
                "Rata șomajului înregistrat nu are serie la nivel de țară în catalogul revizuit "
                "(acoperă: județ, regiune, macroregiune)")
    assert c["candidates"][0]["dataset"] == "AMG157A_anual" and c["candidates"][0]["level"] == "national"
    assert out["data"]["interpretation"]["level"] == "national"


def test_a_national_default_would_answer_with_the_ilo_figure(env, monkeypatch, tmp_path):
    with_national(monkeypatch, tmp_path)
    out = disc("unemployment rate in Romania 2023", "en")
    assert run(card(out, ILO)["next_call"])["data"]["rows"] == [["Romania", "2023", 5.5]]


STILL_ASKED = [
    # a region, by name or by word, and a macroregion
    ("rata somajului in regiunea Nord-Vest 2023", "ro"), ("unemployment rate Nord-Vest 2023", "en"),
    ("rata somajului Sud-Est", "ro"), ("rata somajului pe regiuni", "ro"), ("unemployment rate by region", "en"),
    ("unemployment rate by macroregion", "en"), ("rata somajului pe regiuni de dezvoltare", "ro"),
    # no place and no level word: the level is unknown
    ("somaj", "ro"), ("rata somajului", "ro"), ("rata somajului 2023", "ro"), ("unemployment", "en"),
    ("unemployment rate", "en"), ("unemployment rate 2023", "en"),
    # two levels at once
    ("rata somajului pe regiuni si in Cluj", "ro"), ("unemployment rate in Cluj and Nord-Vest", "en"),
    ("unemployment rate in Cluj and by region", "en"),
]


@pytest.mark.parametrize("question,lang", STILL_ASKED)
def test_a_region_an_unknown_level_and_two_levels_keep_the_clarification(env, question, lang):
    asked(disc(question, lang))


EXPLICIT = [
    # ILO, by alias or by term only; a county or the nation named next to it changes nothing
    ("rata somajului BIM in Cluj 2023", "ro", ILO), ("ilo unemployment rate in Cluj 2023", "en", ILO),
    ("rata somajului BIM", "ro", ILO), ("somaj bim Romania", "ro", ILO),
    ("rata somajului dupa ILO in Cluj", "ro", ILO), ("unemployment rate according to ILO in Cluj", "en", ILO),
    ("AMIGO unemployment rate", "en", ILO), ("rata somajului din ancheta AMIGO", "ro", ILO),
    ("unemployment rate from the LFS survey", "en", ILO),
    # registered, by alias or by term only; the nation named next to it changes nothing
    ("rata somajului inregistrat in Romania 2023", "ro", REGISTERED), ("registered unemployment rate in Romania", "en", REGISTERED),
    ("rata somajului inregistrat in Cluj", "ro", REGISTERED), ("somaj inregistrat", "ro", REGISTERED),
    ("rata somajului ANOFM in Romania", "ro", REGISTERED), ("unemployment rate registered with ANOFM in Romania", "en", REGISTERED),
    ("rata somajului dupa ANOFM", "ro", REGISTERED),
]


@pytest.mark.parametrize("question,lang,cid", EXPLICIT)
def test_a_definition_the_question_names_is_respected_and_never_replaced(env, question, lang, cid):
    out = disc(question, lang)
    assert out["status"] == "ok" and out["data"]["choices"] == []
    assert out["data"]["interpretation"]["assumed_definition"] is None and "assumed_definition" not in codes(out)
    assert out["data"]["concepts"][0]["id"] == cid and not any(c.get("assumed") for c in out["data"]["concepts"])


def test_naming_both_definitions_is_not_defaulted(env):
    out = disc("registered and ILO unemployment rate in Romania", "en")
    assert out["data"]["interpretation"]["assumed_definition"] is None and "assumed_definition" not in codes(out)


def test_an_ilo_question_about_a_county_still_gets_the_national_series_with_the_level_notes(env):
    """Unchanged from AQ-04A: a definition named explicitly is not turned into the registered one because a
    county was named; the card says the county level is not available."""
    c = card(disc("ilo unemployment rate in Cluj 2023", "en"), ILO)
    assert "place_level_unavailable" in [n["code"] for n in c["notes"]]
    assert "level_differs" in [n["code"] for n in c["candidates"][0]["notes"]]


def test_the_terms_cover_every_definitional_alias_and_the_exceptions_are_the_county_aliases(env):
    """A specific alias that carries none of the definition's terms would name a definition the policy cannot
    see. The only ones are the county-level aliases of the registered rate, which is why they are defaulted
    and disclosed instead of silently respected."""
    pol = dp.load_policy()
    by_id = {c["id"]: c for c in catalogue()}
    uncovered = set()
    for cid, rx in pol.level_res.items():
        for lang_aliases in by_id[cid]["aliases"].values():
            uncovered |= {a for a in lang_aliases if not rx.search(cs.fold(a))}
    assert uncovered == {"rata somajului pe judete", "somaj pe judete", "somaj judete",
                         "unemployment rate by county", "unemployment by county", "county unemployment"}


def test_a_city_named_place_keeps_the_county_question_next_to_the_disclosed_default(env):
    """"Cluj-Napoca" is a city, and the registered series is by county: the place question of AQ-04A stays,
    and the level default is disclosed next to it, as the population default is."""
    out = disc("unemployment rate in Cluj-Napoca 2023", "en")
    assert out["status"] == "needs_clarification" and out["reason"] == "ambiguous_place"
    assert out["data"]["interpretation"]["assumed_definition"] == REGISTERED and "assumed_definition" in codes(out)
    assert {c["id"] for c in out["data"]["choices"]} == {"county", "all_counties"}
    assert card(out, REGISTERED)["next_call"] is None                      # no headline before the choice
    picked = run(next(c for c in out["data"]["choices"] if c["id"] == "county")["next_call"])
    assert picked["status"] == "ok"
    assert card(picked, REGISTERED)["next_call"]["arguments"]["filters"] == {"REF_AREA": ["Cluj"], "TIME_PERIOD": ["2023"]}


def test_one_assumption_per_question(env):
    out = disc("populatia si rata somajului in Cluj 2023", "ro")
    assert out["data"]["interpretation"]["assumed_definition"] == "resident_population"


def test_a_generic_population_question_is_untouched(env):
    out = disc("population of Cluj in 2023", "en")
    assert out["data"]["interpretation"]["assumed_definition"] == "resident_population"
    assert run(card(out, "resident_population")["next_call"])["data"]["rows"] == [["Cluj", "2023", 710.0]]


# ------------------------------------------------------------------ configuration and rollback

def test_the_level_rule_is_configuration_and_its_removal_restores_the_clarification(env, monkeypatch, tmp_path):
    use_policy(monkeypatch, tmp_path, lambda p: p.update(level_defaults=[]))
    for q, lang in COUNTY_LEVEL[:3] + NATIONAL_LEVEL[:3] + STILL_ASKED[:3]:
        if q.startswith("rata somajului pe judete") or "by county" in q:
            continue          # these two county aliases were specific matches before: they never asked
        asked(disc(q, lang))
    # an explicit definition never needed the rule
    assert disc("rata somajului BIM in Cluj", "ro")["data"]["concepts"][0]["id"] == ILO


def test_a_rule_that_covers_a_single_level_defaults_only_that_level(env, monkeypatch, tmp_path):
    assert "national" not in shipped()["level_defaults"][0]["levels"]       # shipped: county only
    asked(disc("rata somajului in Romania 2023"))
    defaulted(disc("rata somajului in Cluj 2023"), REGISTERED, "ro")


def test_no_level_can_be_configured_as_national(env, monkeypatch, tmp_path):
    """Whether a question with no place and no level word is the nation is a product reading the owner can
    flip: `no_level` names the level it is taken at. Shipped as `clarify`."""
    assert shipped()["level_defaults"][0]["no_level"] == "clarify"
    use_policy(monkeypatch, tmp_path, lambda p: (p["level_defaults"][0].update(no_level="national"),
                                                 p["level_defaults"][0]["levels"].update(national=ILO)))
    for q, lang in (("rata somajului", "ro"), ("unemployment rate", "en"), ("somaj 2023", "ro")):
        defaulted(disc(q, lang), ILO, lang)
    asked(disc("unemployment rate by region", "en"))                       # a region still asks
    asked(disc("unemployment rate in Cluj and Nord-Vest", "en"))


def test_a_region_level_default_would_need_a_series_at_that_level(env, monkeypatch, tmp_path):
    use_policy(monkeypatch, tmp_path, lambda p: p["level_defaults"][0]["levels"].update(region="ilo_unemployment_rate"))
    out = disc("unemployment rate Nord-Vest 2023", "en")
    assert out["data"]["interpretation"]["assumed_definition"] == ILO       # the ILO rate has a region series (AMG157F)
    w = next(w for w in out["warnings"] if w["code"] == "assumed_definition")
    assert "taking the question at the region level. State the definition explicitly" in w["message"]   # both cover it: nothing is missing
    use_policy(monkeypatch, tmp_path, lambda p: _entry(p)["levels"].update(region="registered_unemployment_rate"))
    assert disc("unemployment rate Nord-Vest 2023", "en")["data"]["interpretation"]["assumed_definition"] == REGISTERED


def test_a_default_whose_phrase_is_not_an_alias_of_the_catalogue_in_use_is_inert(env, tmp_path, monkeypatch):
    raw = json.loads(cs.CONCEPTS_PATH.read_text(encoding="utf-8"))
    reg = next(c for c in raw["concepts"] if c["id"] == REGISTERED)
    reg["aliases"]["ro"].remove("rata somajului inregistrat")
    (tmp_path / "concepts.json").write_text(json.dumps(raw), encoding="utf-8")
    monkeypatch.setattr(cs, "CONCEPTS_PATH", tmp_path / "concepts.json")
    asked(disc("rata somajului in Cluj 2023"))              # the county default cannot be put in front: the question is asked
    with_national(monkeypatch, tmp_path)
    defaulted(disc("rata somajului in Romania 2023"), ILO, "ro")     # a national one would still apply


def test_a_default_whose_concept_is_absent_is_inert(env, tmp_path, monkeypatch):
    raw = json.loads(cs.CONCEPTS_PATH.read_text(encoding="utf-8"))
    raw["concepts"] = [c for c in raw["concepts"] if c["id"] != ILO]
    (tmp_path / "concepts.json").write_text(json.dumps(raw), encoding="utf-8")
    monkeypatch.setattr(cs, "CONCEPTS_PATH", tmp_path / "concepts.json")
    out = disc("rata somajului in Cluj 2023")
    assert out["data"]["interpretation"]["assumed_definition"] is None and "assumed_definition" not in codes(out)


# ------------------------------------------------------------------ validation of the new configuration

def _entry(p):
    return p["level_defaults"][0]


def _cities(p):
    return p["population"]["cities"]


STRUCTURAL = [
    ("place_filter level", lambda p: _cities(p)["place_filter"].update(level="region"), "place_filter.level must be 'county'"),
    ("place_filter not an object", lambda p: _cities(p).update(place_filter="county"), "place_filter.level must be 'county'"),
    ("place_filter column", lambda p: _cities(p)["place_filter"].update(column="REF_AREA_9"), "must be one of the entity_columns"),
    ("place_filter except", lambda p: _cities(p)["place_filter"].update({"except": ["Municipiul Bucuresti"]}),
     "list of county slugs"),
    ("place_filter without ranking", lambda p: _cities(p).update(operations=["change"]), "needs the 'rank' operation"),
    ("level_defaults not a list", lambda p: p.update(level_defaults={}), "level_defaults must be a list"),
    ("entry without a topic", lambda p: _entry(p).pop("topic"), "needs a topic"),
    ("one definition", lambda p: _entry(p)["definitions"].pop(ILO), "at least two concepts"),
    ("terms", lambda p: _entry(p)["definitions"][ILO].update(terms=["BIM"]), "terms must be a non-empty list of folded words"),
    ("phrase", lambda p: _entry(p)["definitions"][ILO].update(phrase="Rata Somajului BIM"), "phrase must be a non-empty folded phrase"),
    ("unknown level", lambda p: _entry(p)["levels"].update(macroregion=ILO), "unknown level 'macroregion'"),
    ("level names a stranger", lambda p: _entry(p)["levels"].update(county="net_earnings"), "which is not a definition"),
    ("no levels", lambda p: _entry(p).update(levels={}), "levels must map at least one level"),
    ("no_level", lambda p: _entry(p).update(no_level="region"), "no_level must be 'clarify' or one of its levels"),
    ("shared with the population default", lambda p: _entry(p)["definitions"].update(
        resident_population={"terms": ["rezident"], "phrase": "populatia rezidenta"}), "also has another default"),
    ("listed in two entries", lambda p: p["level_defaults"].append(json.loads(json.dumps(_entry(p)))), "also has another default"),
]


@pytest.mark.parametrize("name,edit,expected", STRUCTURAL, ids=[s[0] for s in STRUCTURAL])
def test_invalid_structure_is_rejected(name, edit, expected, tmp_path, monkeypatch):
    bad = shipped()
    edit(bad)
    problems = dp.validate(bad)
    assert any(expected in p for p in problems), problems
    (tmp_path / "bad.json").write_text(json.dumps(bad), encoding="utf-8")
    monkeypatch.setattr(dp, "POLICY_PATH", tmp_path / "bad.json")
    with pytest.raises(dp.PolicyError, match="invalid"):
        dp.load_policy()


def test_the_level_rule_is_checked_against_the_catalogue():
    assert dp.validate(shipped(), catalogue()) == []
    bad = shipped()
    _entry(bad)["levels"]["county"] = ILO                 # ILO has no county series
    assert any("ilo_unemployment_rate has no county-level variant" in p for p in dp.validate(bad, catalogue()))
    bad = shipped()
    _entry(bad)["definitions"][REGISTERED]["phrase"] = "rata somajului pe judete"      # an alias, but not a definitional one
    assert dp.validate(bad, catalogue()) == []
    _entry(bad)["definitions"][REGISTERED]["phrase"] = "rata somajului neinregistrat"
    assert any("is not a specific alias of registered_unemployment_rate" in p for p in dp.validate(bad, catalogue()))
    gone = [c for c in catalogue() if c["id"] != ILO]
    assert any("'ilo_unemployment_rate' is not in the concept catalogue" in p for p in dp.validate(shipped(), gone))


def test_the_shipped_level_rule_is_pinned():
    entry = _entry(shipped())
    # national is deliberately absent (owner, 2026-10-18): neither definition gives one national figure
    assert entry["levels"] == {"county": REGISTERED} and entry["no_level"] == "clarify"
    assert entry["definitions"][REGISTERED]["phrase"] == "rata somajului inregistrat"
    assert entry["definitions"][ILO]["phrase"] == "rata somajului bim"
    # region is deliberately absent: both definitions have a regional series, so the user is asked
    assert "region" not in entry["levels"]
    assert dp.serves_level({"variants": {"macroregion": "X"}}, "region") and not dp.serves_level({"variants": {}}, "county")


def test_the_new_texts_exist_in_both_languages_and_name_the_county_and_the_level():
    for key in ("discover.place_filter", "discover.assumed_level", "discover.level_missing"):
        assert M.TEXT["en"][key] != M.TEXT["ro"][key]
    assert "{county}" in M.TEXT["en"]["discover.place_filter"] and "{county}" in M.TEXT["ro"]["discover.place_filter"]


# ================================================================== the real generation (read-only copy)

PINNED = "9b3e065d"


@pytest.mark.corpus
def test_corpus_top_cities_of_cluj_match_the_source(real):
    import duckdb
    from app import config
    out = disc("top 5 orase din Cluj dupa populatie")
    nc = call_of(out)
    assert nc["arguments"]["filters"] == {"REF_AREA": ["Cluj"]} and nc["arguments"]["top_k"] == 5
    res = run(nc)
    d = res["data"]
    assert d["year"] == "2026" and d["eligible_count"] == 6 and d["outside_class_count"] == 75
    got = [(r["entity"]["REF_AREA_2"], r["value"]) for r in d["rows"]]
    assert got == [("54975 MUNICIPIUL CLUJ-NAPOCA", 324860.0), ("55259 MUNICIPIUL TURDA", 51377.0),
                   ("55008 MUNICIPIUL DEJ", 35981.0), ("55357 MUNICIPIUL CAMPIA TURZII", 25468.0),
                   ("55384 MUNICIPIUL GHERLA", 21677.0)]
    # independent check: plain DuckDB over the parquet, no application code
    sirutas = [g[0].split()[0] for g in got]
    src = duckdb.connect().execute(
        "select REF_AREA_2, sum(OBS_VALUE) from read_parquet(?) where REF_AREA = 'Cluj' and TIME_PERIOD = '2026' "
        "group by REF_AREA_2", [str(config.PARQUET_DIR / f"{LOCALITY}.parquet")]).fetchall()
    by = dict(src)
    assert len(by) == 81 and all(by[g[0]] == g[1] for g in got)
    assert sorted(by.values(), reverse=True)[0] == 324860.0 and sirutas[0] == "54975"
    assert "place_filter_applied" in codes(out)


@pytest.mark.corpus
def test_corpus_a_larger_city_elsewhere_is_excluded_and_a_region_is_reported(real):
    res = run(call_of(disc("top 5 cities in Bihor by population", "en")))
    # recomputed with plain DuckDB over the parquet and the GOS102A catalogue: 10 cities and 91 communes in Bihor
    assert [(r["entity"]["REF_AREA"], r["entity"]["REF_AREA_2"], r["value"]) for r in res["data"]["rows"]] == [
        ("Bihor", "26564 MUNICIPIUL ORADEA", 212775.0), ("Bihor", "26975 MUNICIPIUL SALONTA", 17788.0),
        ("Bihor", "26877 MUNICIPIUL MARGHITA", 16304.0), ("Bihor", "30915 ORAS SACUENI", 12286.0),
        ("Bihor", "26699 ORAS ALESD", 10930.0)]
    assert res["data"]["eligible_count"] == 10 and res["data"]["outside_class_count"] == 91
    assert reported(disc("top 5 orase din Municipiul Bucuresti dupa populatie"), BUCHAREST)
    assert reported(disc("top 5 cities in the Nord-Vest region by population", "en"), "Regiunea Nord-Vest")
    assert reported(disc("top 5 orase din regiunea Bucuresti-Ilfov dupa populatie"), "Regiunea Bucuresti-Ilfov")    # not two counties


@pytest.mark.corpus
def test_corpus_unemployment_defaults_by_level(real):
    county = disc("rata somajului in Cluj 2023")
    assert county["data"]["interpretation"]["assumed_definition"] == REGISTERED
    nc = card(county, REGISTERED)["next_call"]
    assert nc == {"tool": "run_recipe", "arguments": {"recipe": "registered_unemployment_county", "lang": "ro",
                                                      "year": "2023", "areas": ["Cluj"]}}
    assert run(nc)["data"]["rows"][0]["label"] == "Cluj"
    asked(disc("rata somajului in Romania 2023"))                           # national: still asked (2026-10-18)
    asked(disc("unemployment rate Nord-Vest 2023", "en"))
    asked(disc("rata somajului"))
