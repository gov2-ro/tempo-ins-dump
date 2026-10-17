"""AQ-05A: discovery offers a city change only for its exact supported meaning.

Runs on the AQ-04A synthetic corpus (shipped concepts and policy, production dataset codes).
POP107D_grupe_localitate, domicile population, 2024 -> 2025:

  Cluj-Napoca 320000 -> 324000 (+4000)   Iasi 285000 -> 290000 (+5000)
  Turda        53000 ->  55000 (+2000)   Harlau 9000 ->   9500 (+500)
  Apahida (a COMMUNE, not in GOS102A) 900000 -> 999999 (+99999)

The supported meaning: cities, the domicile population series, exactly two years, a stated
direction (decline = most negative first, growth = largest first), absolute or percent change.
"""
import json

import pytest

from app.services.tools import discovery_policy as dp
from test_aq04a_discovery_defaults import (  # noqa: F401 — fixtures of the AQ-04A corpus
    build_env, card, codes, disc, env, run, shipped)

DATASET = "POP107D_grupe_localitate"
CLUJ, IASI = "54975 MUNICIPIUL CLUJ-NAPOCA", "95000 MUNICIPIUL IASI"
TURDA, HARLAU = "55400 MUNICIPIUL TURDA", "96000 ORAS HARLAU"
COMMUNE = "56000 COMUNA APAHIDA"


def call_of(out):
    return card(out, "domicile_population")["next_call"]


def rows(res):
    return [(r["entity"]["REF_AREA_2"], r["absolute"], r["rank"]) for r in res["data"]["intervals"][0]["rows"]]


@pytest.mark.parametrize("question,lang,order,top_k", [
    ("which cities had the largest population growth between 2024 and 2025?", "en", "desc", 30),
    ("top 4 cities by population growth 2024 2025", "en", "desc", 4),
    ("orasele cu cea mai mare crestere a populatiei intre 2024 si 2025", "ro", "desc", 30),
    ("top 10 cities by population decline between 2025 and 2024", "en", "asc", 10),      # years sorted
    ("orasele care au pierdut populatie intre 2024 si 2025", "ro", "asc", 30),
])
def test_a_city_change_with_two_years_and_a_direction_reaches_compare_periods(env, question, lang, order, top_k):
    out = disc(question, lang)
    assert out["status"] == "ok"
    assert out["data"]["interpretation"]["operation"] == "change"
    nc = call_of(out)
    assert nc == {"tool": "compare_periods", "arguments": {
        "dataset": DATASET, "entity_columns": ["REF_AREA", "REF_AREA_2"], "entity_class": "cities",
        "intervals": [{"from": "2024", "to": "2025"}], "metric": "absolute", "order": order,
        "filters": {}, "top_k": top_k, "lang": lang}}
    w = {x["code"]: x for x in out["warnings"]}
    assert "does not prove historical city status or unchanged boundaries" in w["classification_reference"]["message"]
    assert "assumed_definition" in w                                   # domicile is still disclosed
    res = run(nc)
    assert res["status"] == "partial" or res["status"] == "ok"
    assert res["data"]["entity_class"] == "cities" and res["data"]["outside_class_count"] == 1
    iv = res["data"]["intervals"][0]
    assert iv["eligible_count"] == 4 and COMMUNE not in json.dumps(res["data"])
    growth = [(IASI, 5000.0), (CLUJ, 4000.0), (TURDA, 2000.0), (HARLAU, 500.0)]
    want = growth if order == "desc" else growth[::-1]
    assert [(loc, a) for loc, a, _ in rows(res)] == want[:top_k]


def test_percent_wording_ranks_the_percent_change(env):
    out = disc("top 3 cities by percent population growth between 2024 and 2025", "en")
    nc = call_of(out)
    assert nc["arguments"]["metric"] == "percent" and nc["arguments"]["order"] == "desc"
    res = run(nc)
    got = [(r["entity"]["REF_AREA_2"], r["percent"]) for r in res["data"]["intervals"][0]["rows"]]
    assert got == [(HARLAU, pytest.approx(100 * 500 / 9000, abs=1e-12)),
                   (TURDA, pytest.approx(100 * 2000 / 53000, abs=1e-12)),
                   (IASI, pytest.approx(100 * 5000 / 285000, abs=1e-12))]


@pytest.mark.parametrize("question,fragment", [
    ("orasele care au pierdut populatie", "two exact years"),                 # none given
    ("cities that lost population since 2024 decline", "two exact years"),    # one year
    ("cities population decline 2020 2022 2024", "two exact years"),          # three years
    ("cities population change 2020 2024", "stated direction"),               # neutral
    ("cities population growth and decline between 2024 and 2025", "stated direction"),
])
def test_unclear_city_change_questions_are_refused_not_defaulted(env, question, fragment):
    out = disc(question, "en")
    assert (out["status"], out["reason"]) == ("unavailable", "unsupported_operation")
    assert "change rankings" in out["message"] and fragment in out["message"]
    assert out["data"] == {} and not out["warnings"]


@pytest.mark.parametrize("question", [
    "bottom 5 cities by population growth between 2024 and 2025",
    "smallest population decline of cities between 2024 and 2025",
    "oraselor cu cea mai mica crestere a populatiei intre 2024 si 2025",
])
def test_bottom_or_smallest_wording_is_not_reinterpreted_as_a_direction(env, question):
    out = disc(question, "en")
    assert (out["status"], out["reason"]) == ("unavailable", "unsupported_operation")
    assert "ambiguous for changes" in out["message"] and out["data"] == {}


@pytest.mark.parametrize("question,lang", [
    ("cities population decline between 2024 and 2025 within the same boundaries", "en"),
    ("population decline of cities with unchanged boundaries between 2024 and 2025", "en"),
    ("population decline between 2024 and 2025 of cities that were already cities in 2010", "en"),
    ("cities by historical status: population decline between 2024 and 2025", "en"),
    ("scaderea populatiei oraselor in aceleasi granite intre 2024 si 2025", "ro"),
    ("scaderea populatiei orase care erau orase la acea data intre 2024 si 2025", "ro"),
])
def test_historical_membership_or_constant_boundaries_stay_unavailable(env, question, lang):
    out = disc(question, lang)
    assert (out["status"], out["reason"]) == ("unavailable", "unsupported_operation")
    assert "historical city status or constant boundaries" in out["message"] and out["data"] == {}


def test_other_refusals_of_the_city_policy_still_come_first(env):
    resident = disc("cities resident population decline between 2024 and 2025", "en")
    assert (resident["status"], resident["reason"]) == ("unavailable", "level_unavailable")
    assert "County data was not substituted" in resident["message"]
    density = disc("population density of cities, decline between 2024 and 2025", "en")
    assert (density["status"], density["reason"]) == ("unavailable", "unsupported_operation")
    assert "density" in density["message"]
    none = disc("cities net salary decline between 2024 and 2025", "en")
    assert (none["status"], none["reason"]) == ("unavailable", "level_unavailable")


def test_an_unapplied_constraint_withholds_the_change_call(env):
    for q, kind in (("female population decline of cities between 2024 and 2025", "sex"),
                    ("population decline of cities in Cluj between 2024 and 2025", "geography")):
        out = disc(q, "en")
        assert out["status"] == "ok"
        assert kind in {c["kind"] for c in out["data"]["interpretation"]["unapplied_constraints"]}
        c = card(out, "domicile_population")
        assert (c["next_call"] or {}).get("tool") != "compare_periods"
        assert "classification_reference" not in codes(out) and "constraint_not_applied" in codes(out)


def test_top_k_bounds_still_apply_to_a_city_change(env):
    out = disc("top 200 cities by population decline between 2024 and 2025", "en")
    assert (out["status"], out["reason"]) == ("error", "invalid_input") and "At most 100" in out["message"]


def test_county_and_one_year_questions_are_untouched(env):
    out = disc("which counties had the largest population decline between 2024 and 2025?", "en")
    assert out["status"] == "ok" and out["data"]["interpretation"]["operation"] == "change"
    assert "classification_reference" not in codes(out)
    assert all((c.get("next_call") or {}).get("tool") != "compare_periods"
               for c in out["data"]["concepts"])
    rank = disc("top 3 cities by population", "en")
    assert call_of(rank)["tool"] == "rank_entities" and call_of(rank)["arguments"]["entity_class"] == "cities"
    assert "classification_reference" not in codes(rank)


def test_the_change_operation_is_configuration_and_rolls_back_to_the_old_refusal(env, monkeypatch, tmp_path):
    raw = shipped()
    raw["population"]["cities"]["operations"] = ["rank"]
    path = tmp_path / "rank-only.json"
    path.write_text(json.dumps(raw), encoding="utf-8")
    monkeypatch.setattr(dp, "POLICY_PATH", path)
    out = disc("top 10 cities by population decline between 2024 and 2025", "en")
    assert (out["status"], out["reason"]) == ("unavailable", "unsupported_operation")
    assert "City-only change rankings are not yet supported" in out["message"]
    assert call_of(disc("top 10 cities by population", "en"))["tool"] == "rank_entities"


def test_a_change_rule_needs_the_city_class_and_the_catalogue_rule_is_pinned():
    assert shipped()["population"]["cities"]["operations"] == ["rank", "change"]
    assert dp.SERVED["locality"] == {"rank", "change"}                   # lookup is still not served
    bad = shipped()
    bad["population"]["cities"]["entity_class"] = "all"
    assert any("only through entity_class 'cities'" in p for p in dp.validate(bad))
    bad = shipped()
    bad["population"]["cities"]["operations"] = ["lookup"]
    assert any("cannot be served at level 'locality'" in p for p in dp.validate(bad))
    assert "does not prove historical city status" in dp.CITY_CHANGE_NOTE
