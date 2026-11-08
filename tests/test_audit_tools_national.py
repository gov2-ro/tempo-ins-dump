"""PKG-TOOLS F3: INS's published national cell is a runnable recipe result."""
import duckdb
import pytest

from at01_fixtures import call, make_env
from test_at01_recipes_links import RECIPES, build_core, install_recipes


def build(corpus):
    build_core(corpus)
    db = duckdb.connect(str(corpus / "metadata.duckdb"))
    db.execute("INSERT INTO published_totals VALUES ('PUBM', 'Romania', '2022', 6.5, 'Lei', 'PUBM-total', "
               "'2026-10-12T00:00:00+00:00', 'f2022', 'm2022', '04-09-2025')")
    db.close()


@pytest.fixture
def env(tmp_path, monkeypatch):
    e = make_env(tmp_path, monkeypatch, build=build)
    install_recipes(tmp_path, monkeypatch, *RECIPES)
    return e


def test_national_area_returns_the_published_series(env):
    out = call("run_recipe", recipe="fx_published", areas=["Romania"], lang="en")
    assert out["status"] == "ok" and out["reason"] is None
    assert [(r["year"], r["label"], r["value"]) for r in out["data"]["rows"]] == [
        ("2022", "Romania", 6.5), ("2024", "Romania", 7.5)]
    assert all("rank" not in r for r in out["data"]["rows"])
    assert out["data"]["excluded"] == [] and out["provenance"]["scope"]["domain_complete"] is True
    assert "not a sum of counties" in out["provenance"]["scope"]["description"]
    assert "one row per year" in out["message"]


def test_national_synonym_resolves_to_the_same_cell(env):
    a = call("run_recipe", recipe="fx_published", areas=["ROMÂNIA"])
    assert a["status"] == "ok" and [r["value"] for r in a["data"]["rows"]] == [6.5, 7.5]


def test_national_with_a_county_keeps_the_county_ranking(env):
    out = call("run_recipe", recipe="fx_published", areas=["Alfa", "Romania"], lang="en")
    assert out["status"] == "ok"
    assert [(r["label"], r["rank"]) for r in out["data"]["rows"]] == [("Alfa", 1)]
    assert out["data"]["aggregates"][0]["label"] == "Romania"


def test_unknown_area_still_excluded(env):
    out = call("run_recipe", recipe="fx_published", areas=["Nowhere"], lang="en")
    assert out["status"] == "unavailable" and out["data"]["exclusion_counts"] == {"not_in_data": 1}


def test_recipe_without_a_published_cell_is_unchanged(env):
    out = call("run_recipe", recipe="fx_intensity", areas=["Romania"], lang="en")
    assert out["data"]["exclusion_counts"] == {"not_in_data": 1}
