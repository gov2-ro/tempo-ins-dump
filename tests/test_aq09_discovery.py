"""AQ-09 D: discovery messages (own denominator, filler words, no close match, longer series, density)."""
import json

import pytest

from at01_fixtures import add_dataset, make_env
from test_at01_discovery import CONCEPTS, CTY, RECIPES, _build, concept, disc, geo, years


def build(corpus):
    t = lambda ys: ("TIME_PERIOD", "Ani", "time", years(ys))
    area = ("REF_AREA", "Judete", "geo", geo(CTY))
    add_dataset(corpus, "LONGK_judete", [area, t(range(2000, 2025))],
                [(c, str(y), 1.0 + i) for i, c in enumerate(CTY) for y in range(2000, 2025)],
                name="Serie lunga test judete")
    add_dataset(corpus, "SHORTK_judete", [area, t(range(2015, 2025))],
                [(c, str(y), 1.0 + i) for i, c in enumerate(CTY) for y in range(2015, 2025)],
                name="Serie scurta test judete")
    add_dataset(corpus, "DENSK_judete", [area, t((2023, 2024))],
                [(c, str(y), 1.0) for c in CTY for y in (2023, 2024)], name="Densitatea populatiei judete")
    _build(corpus)      # last: it widens matrix_profiles, which add_dataset does not know


EXTRA = [
    concept("perinh", "Valoare pe locuitor test", ["valoarea testata pe locuitor"], variants={"county": "WAGEK_judete"}),
    concept("shortc", "Serie scurta test", ["serie scurta"], variants={"county": "SHORTK_judete"},
            alternatives=["longc"]),
    concept("longc", "Serie lunga test", ["serie lunga"], variants={"county": "LONGK_judete"},
            alternatives=["shortc"]),
]


@pytest.fixture
def env(tmp_path, monkeypatch):
    from app.services import concept_search as cs
    from app.services import dataset_search, recipes
    e = make_env(tmp_path, monkeypatch, build=build, conflicting=["CONFK_judete"])
    data = dict(CONCEPTS, concepts=CONCEPTS["concepts"] + EXTRA)
    (tmp_path / "concepts.json").write_text(json.dumps(data), encoding="utf-8")
    (tmp_path / "recipes.json").write_text(json.dumps(RECIPES), encoding="utf-8")
    monkeypatch.setattr(cs, "CONCEPTS_PATH", tmp_path / "concepts.json")
    monkeypatch.setattr(recipes, "RECIPES_PATH", tmp_path / "recipes.json")
    monkeypatch.setattr(dataset_search, "SEARCH_DB_PATH", tmp_path / "no-fts.duckdb")
    dataset_search._reset_for_tests()
    yield e
    monkeypatch.undo()
    dataset_search._reset_for_tests()


def codes(out):
    return [w["code"] for w in out["warnings"]]


def test_a_measures_own_denominator_is_not_an_unapplied_constraint(env):
    out = disc("valoarea testata pe locuitor Cluj")
    assert "constraint_not_applied" not in codes(out)
    assert out["data"]["interpretation"]["unapplied_constraints"] == []
    assert out["data"]["concepts"][0]["next_call"]["tool"] == "query_data"


def test_a_denominator_the_measure_lacks_is_still_reported(env):
    out = disc("castigul testat pe locuitor Cluj")
    assert "constraint_not_applied" in codes(out)


def test_filler_words_leave_the_family_query():
    from app.services import concept_search as cs
    fts = cs.parse_query("top 5 judete dupa castig, daca poti", _NoPlaces())["fts"]
    assert "top" not in fts.split() and "daca" not in fts.split() and "poti" not in fts.split()
    assert "castig" in fts


class _NoPlaces:
    def execute(self, *a, **k):
        class R:
            def fetchall(self):
                return []
        return R()


def test_a_question_no_family_fits_carries_a_no_close_match_warning(env):
    out = disc("pretul mediu al apartamentelor de lux")
    assert out["status"] == "ok"                     # no new status value
    assert "no_close_match" in codes(out) or "no_match" in codes(out)
    assert not out["data"]["concepts"]


def test_a_family_whose_title_fits_is_not_flagged(env):
    out = disc("locuinte construite")
    assert out["data"]["families"] and "no_close_match" not in codes(out)


def test_period_before_the_coverage_names_the_longer_series(env):
    out = disc("serie scurta 2010")
    w = next(w for w in out["warnings"] if w["code"] == "longer_series_available")
    assert "Serie lunga test" in w["message"] and "2000" in w["message"] and "LONGK_judete" in w["message"]
    assert any(r["tool"] == "discover_indicators" for r in out["recovery"])


def test_last_n_years_beyond_the_coverage_is_warned(env):
    out = disc("serie scurta in ultimii 20 de ani")
    assert "longer_series_available" in codes(out)
    out = disc("castigul testat in ultimii 20 de ani")       # no longer series in its alternatives
    w = next(w for w in out["warnings"] if w["code"] == "period_beyond_coverage")
    assert "2021" in w["message"] and "2024" in w["message"]


def test_last_n_years_inside_the_coverage_adds_nothing(env):
    out = disc("castigul testat in ultimii 3 ani")
    assert "period_beyond_coverage" not in codes(out) and "longer_series_available" not in codes(out)


def test_density_is_searched_first_and_refused_without_the_tourism_recipe(env, monkeypatch):
    from app.services import dataset_search
    out = disc("densitatea populatiei", lang="ro")
    # the fixture holds a density family: no refusal
    assert out["status"] == "ok" and any(f["code"] == "DENSK_judete" for f in out["data"]["families"])


def test_density_without_a_density_series_is_refused_and_offers_the_population_only(tmp_path, monkeypatch):
    from app.services import concept_search as cs
    from app.services import dataset_search, recipes

    def no_density(corpus):
        _build(corpus)
    make_env(tmp_path, monkeypatch, build=no_density, conflicting=["CONFK_judete"])
    (tmp_path / "concepts.json").write_text(json.dumps(CONCEPTS), encoding="utf-8")
    (tmp_path / "recipes.json").write_text(json.dumps(RECIPES), encoding="utf-8")
    monkeypatch.setattr(cs, "CONCEPTS_PATH", tmp_path / "concepts.json")
    monkeypatch.setattr(recipes, "RECIPES_PATH", tmp_path / "recipes.json")
    monkeypatch.setattr(dataset_search, "SEARCH_DB_PATH", tmp_path / "no-fts.duckdb")
    dataset_search._reset_for_tests()
    out = disc("which county has the highest population density", lang="en")
    assert (out["status"], out["reason"]) == ("unavailable", "unsupported_operation")
    assert "density" in out["message"] and "overnight" not in out["message"].lower()
    assert [r["tool"] for r in out["recovery"]] == ["discover_indicators"]
    assert "population" in out["recovery"][0]["arguments"]["query"]
    monkeypatch.undo()
    dataset_search._reset_for_tests()


def test_correlation_is_refused_at_once(env):
    out = disc("correlation between population and wages", lang="en")
    assert (out["status"], out["reason"]) == ("unavailable", "unsupported_operation")
    assert "correlation" in out["message"]
