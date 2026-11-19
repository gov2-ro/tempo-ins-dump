"""AQ-09 A: a rate is ranked or compared when each entity is one source cell."""
import pytest
from at01_fixtures import add_dataset, make_env, call
from test_at01_changes import area_dim, time_dim, unit_dim

NAMES = ["A", "B", "C"]


def build(corpus):
    vals = {"A": (5.0, 6.0), "B": (7.0, 4.0), "C": (1.0, 9.0)}
    rows = [(e, y, "Lei", v[i]) for e, v in vals.items() for i, y in enumerate(("2021", "2022"))]
    add_dataset(corpus, "PERCAP", [area_dim(NAMES), time_dim(("2021", "2022")), unit_dim("Lei")],
                rows, unit_type="currency", name="Produs intern brut pe locuitor")
    sex = ("SEX", "Sexe", None, [("Masculin", {}), ("Feminin", {})])
    rows2 = [(e, "2022", s, "Procente", 1.0) for e in NAMES for s in ("Masculin", "Feminin")]
    add_dataset(corpus, "RATESEX", [area_dim(NAMES), time_dim(("2022",)), sex, unit_dim("Procente")],
                rows2, unit_type="percentage", name="Rata somajului")
    rows3 = [(e, y, "Procente", v) for e, y, v in
             (("A", "2021", 5.0), ("A", "2022", 6.0), ("B", "2021", 7.0), ("B", "2022", 8.0))]
    add_dataset(corpus, "RATEPCT", [area_dim(["A", "B"]), time_dim(("2021", "2022")), unit_dim("Procente")],
                rows3, unit_type="percentage", name="Rata somajului")


@pytest.fixture
def env(tmp_path, monkeypatch):
    return make_env(tmp_path, monkeypatch, build=build)


def test_a_per_capita_value_ranks_in_both_orders(env):
    top = call("rank_entities", dataset="PERCAP", entity_columns=["REF_AREA"], year="2022", order="desc", top_k=2)
    assert top["reason"] != "unsupported_measure" and top["status"] in ("ok", "partial")
    assert [(r["entity"]["REF_AREA"], r["value"]) for r in top["data"]["rows"]] == [("C", 9.0), ("A", 6.0)]
    low = call("rank_entities", dataset="PERCAP", entity_columns=["REF_AREA"], year="2022", order="asc", top_k=1)
    assert [r["entity"]["REF_AREA"] for r in low["data"]["rows"]] == ["B"]


def test_a_rate_that_needs_a_sum_is_still_refused(env):
    r = call("rank_entities", dataset="RATESEX", entity_columns=["REF_AREA"], year="2022")
    assert r["status"] == "unavailable" and r["reason"] in ("unsupported_measure", "missing_weights", "unverified_structure")
    assert not r["data"].get("rows")


def test_the_refusal_text_says_what_is_refused_and_has_a_recovery(env, monkeypatch):
    from app.services import period_changes
    monkeypatch.setattr(period_changes, "rate_values_combined", lambda m, a: True)
    for lang, word in (("en", "combine"), ("ro", "combina")):
        r = call("rank_entities", dataset="PERCAP", entity_columns=["REF_AREA"], year="2022", lang=lang)
        assert r["reason"] == "unsupported_measure" and word in r["message"] and r["recovery"]


def test_compare_periods_accepts_a_rate_in_absolute_points(env):
    e = call("compare_periods", dataset="RATEPCT", entity_columns=["REF_AREA"],
             intervals=[{"from": "2021", "to": "2022"}], order="desc")
    assert e["status"] in ("ok", "partial")
    rows = e["data"]["intervals"][0]["rows"]
    assert sorted(r["absolute"] for r in rows) == [1.0, 1.0]


def test_percent_change_of_a_percentage_is_refused(env):
    e = call("compare_periods", dataset="RATEPCT", entity_columns=["REF_AREA"],
             intervals=[{"from": "2021", "to": "2022"}], metric="percent")
    assert e["status"] == "unavailable" and e["reason"] == "unsupported_measure"
    assert e["recovery"]


def test_percent_change_of_a_per_capita_amount_is_allowed(env):
    e = call("compare_periods", dataset="PERCAP", entity_columns=["REF_AREA"],
             intervals=[{"from": "2021", "to": "2022"}], metric="percent")
    assert e["status"] in ("ok", "partial")


def test_duplicate_keys_still_refused_for_a_rate(env, monkeypatch):
    from app.services import data_query
    original = data_query.run_query

    def dup(*a, **kw):
        out = original(*a, **kw)
        out["rows"].append(out["rows"][0])
        return out
    monkeypatch.setattr(data_query, "run_query", dup)
    r = call("rank_entities", dataset="PERCAP", entity_columns=["REF_AREA"], year="2022")
    assert r["reason"] == "duplicate_keys"


@pytest.fixture
def real():
    from app.services import generation
    if not str(generation.current().get("id") or ""):
        pytest.skip("no served corpus generation")


@pytest.mark.corpus
def test_con103h_counties_rank_in_both_orders(real):
    for order, first in (("desc", "Bucuresti"), ("asc", "Vaslui")):
        r = call("rank_entities", dataset="CON103H_judete", entity_columns=["REF_AREA"], year="2022",
                 order=order, top_k=5, lang="ro")
        assert r["status"] in ("ok", "partial"), r["message"]
        assert len(r["data"]["rows"]) == 5 and first in r["data"]["rows"][0]["entity"]["REF_AREA"]
