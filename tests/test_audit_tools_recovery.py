"""PKG-TOOLS F8-F13 on the served corpus (read-only), pinned to generation 062bd2b0."""
import pytest

from at01_fixtures import call
from test_audit_tools_corpus import real  # noqa: F401  (fixture)


def disc(q, lang):
    return call("discover_indicators", query=q, lang=lang)


@pytest.mark.corpus
def test_recipe_year_across_a_series_break_warns(real):
    old = call("run_recipe", recipe="tourism_intensity", year="2019", areas=["Brasov"], lang="en")
    w = [x for x in old["warnings"] if x["code"] == "series_break"]
    assert w and "latest year" in w[0]["message"]
    new = call("run_recipe", recipe="tourism_intensity", year="2025", areas=["Brasov"], lang="en")
    assert not [x for x in new["warnings"] if x["code"] == "series_break"]


@pytest.mark.corpus
def test_national_question_level_note_points_the_right_way(real):
    out = disc("population of Romania 2025", "en")
    cand = out["data"]["concepts"][0]["candidates"][0]
    notes = {n["code"]: n["message"] for n in cand["notes"]}
    assert "level_differs" not in notes and "smaller area" not in str(notes)
    assert "not an INS national figure" in notes["level_aggregated"]
    assert cand["next_call"]["tool"] == "query_data" and cand["next_call"]["arguments"]["group_by"] == ["TIME_PERIOD"]


@pytest.mark.corpus
def test_non_annual_refusal_names_the_calling_tool_and_offers_the_annual_child(real):
    r = call("rank_entities", dataset="SOM101E", entity_columns=["REF_AREA"], lang="en")
    assert r["reason"] == "unsupported_frequency" and "rank_entities supports" in r["message"]
    assert "compare_periods" not in r["message"]
    rec = r["recovery"][0]
    assert rec["tool"] == "rank_entities" and rec["arguments"]["dataset"] == "SOM101E_anual_localitate"
    c = call("compare_periods", dataset="SOM101E", entity_columns=["REF_AREA"],
             intervals=[{"from": "2015", "to": "2020"}], lang="en")
    assert "compare_periods supports" in c["message"] and c["recovery"][0]["tool"] == "compare_periods"


@pytest.mark.corpus
@pytest.mark.parametrize("code,recipe", [("FOM106E_judete", "net_earnings_county"),
                                         ("SOM103A_judete", "registered_unemployment_county")])
def test_rate_refusals_route_to_the_published_recipe(real, code, recipe):
    r = call("rank_entities", dataset=code, entity_columns=["REF_AREA"], year="2024", lang="en")
    assert r["reason"] == "unsupported_measure"
    assert r["recovery"][0]["tool"] == "run_recipe" and r["recovery"][0]["arguments"]["recipe"] == recipe


@pytest.mark.corpus
def test_missing_weights_routes_to_the_recipe_and_compare_too(real):
    q = call("query_data", dataset="FOM106E_judete", filters={"REF_AREA": ["Cluj"], "TIME_PERIOD": ["2024"]},
             group_by=["REF_AREA"], lang="en")
    assert q["reason"] == "missing_weights" and q["recovery"][0]["arguments"]["recipe"] == "net_earnings_county"
    c = call("compare_periods", dataset="FOM106E_judete", entity_columns=["REF_AREA"],
             intervals=[{"from": "2020", "to": "2024"}], lang="en")
    assert c["recovery"][0]["tool"] == "run_recipe"


@pytest.mark.corpus
def test_conflicting_grain_is_reported_the_same_by_every_tool(real):
    q = call("query_data", dataset="SCL104A_judete", group_by=["TIME_PERIOD"], lang="en")
    r = call("rank_entities", dataset="SCL104A_judete", entity_columns=["REF_AREA"], lang="en")
    c = call("compare_periods", dataset="SCL104A_judete", entity_columns=["REF_AREA"],
             intervals=[{"from": "2010", "to": "2014"}], lang="en")
    assert q["reason"] == r["reason"] == c["reason"] == "conflicting_grain"
    raw = call("query_data", dataset="SCL104A_judete", filters={"TIME_PERIOD": ["2014"], "REF_AREA": ["Cluj"]},
               limit=5, lang="en")
    assert raw["status"] == "partial" and raw["reason"] == "conflicting_grain"
    assert "data_quality" in [w["code"] for w in raw["warnings"]]


@pytest.mark.corpus
def test_rank_entities_copies_auto_pinned(real):
    q = call("query_data", dataset="AGR101B", filters={"TIME_PERIOD": ["2014"]}, group_by=["REF_AREA"], lang="en")
    r = call("rank_entities", dataset="AGR101B", entity_columns=["REF_AREA"], lang="en")
    assert "auto_pinned" in [w["code"] for w in q["warnings"]]
    assert "auto_pinned" in [w["code"] for w in r["warnings"]]
