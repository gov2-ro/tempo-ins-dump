"""PKG-TOOLS F1: a result from an older table of a concept names the newer table."""
import json

import pytest

from at01_fixtures import add_dataset, add_search_columns, call, make_env
from test_at01_changes import area_dim, time_dim, unit_dim, UNIT
from test_at01_discovery import concept

ROWS = [(e, y, UNIT, float(v)) for e, v in (("A", 10), ("B", 20)) for y in ("2020", "2021")]


def build(corpus):
    for code, updated in (("OLDV", "2025-01-01"), ("NEWV", "2026-01-01"), ("LONE", "2024-01-01")):
        add_dataset(corpus, code, [area_dim(["A", "B"]), time_dim(("2020", "2021")), unit_dim(UNIT)], ROWS,
                    updated=updated)
    add_search_columns(corpus)


@pytest.fixture
def env(tmp_path, monkeypatch):
    e = make_env(tmp_path, monkeypatch, build=build)
    from app.services import concept_search
    c = concept("vint", "Vintage test", ["vintage test"], variants={"county": "OLDV"})
    c["also_families"] = ["NEWV"]
    c["also_variants"] = {"county": "NEWV"}
    solo = concept("solo", "Solo test", ["solo test"], variants={"county": "LONE"})
    path = tmp_path / "concepts.json"
    path.write_text(json.dumps({"concepts": [c, solo]}))
    monkeypatch.setattr(concept_search, "CONCEPTS_PATH", path)
    from app.services import dataset_search
    monkeypatch.setattr(dataset_search, "SEARCH_DB_PATH", tmp_path / "no-fts.duckdb")
    dataset_search._reset_for_tests()
    return e


def codes(env_):
    return [w["code"] for w in env_["warnings"]]


def test_older_table_carries_the_warning_in_every_tool(env):
    q = call("query_data", dataset="OLDV", filters={"TIME_PERIOD": ["2021"]}, group_by=["TIME_PERIOD"], lang="en")
    w = next(w for w in q["warnings"] if w["code"] == "newer_vintage")
    assert "NEWV" in w["message"] and "2025-01-01" in w["message"] and "2026-01-01" in w["message"]
    r = call("rank_entities", dataset="OLDV", entity_columns=["REF_AREA"], lang="en")
    c = call("compare_periods", dataset="OLDV", entity_columns=["REF_AREA"], lang="en",
             intervals=[{"from": "2020", "to": "2021"}])
    d = call("describe_dataset", dataset="OLDV", lang="en")
    assert all("newer_vintage" in codes(x) for x in (r, c, d))


def test_newest_and_unrelated_tables_have_no_warning(env):
    for code in ("NEWV", "LONE"):
        q = call("query_data", dataset=code, filters={"TIME_PERIOD": ["2021"]}, group_by=["TIME_PERIOD"])
        assert "newer_vintage" not in codes(q), code


def test_romanian_message(env):
    q = call("query_data", dataset="OLDV", filters={"TIME_PERIOD": ["2021"]}, group_by=["TIME_PERIOD"], lang="ro")
    assert "actualizat la" in next(w for w in q["warnings"] if w["code"] == "newer_vintage")["message"]


def test_discovery_prefers_the_newest_table_of_the_concept(env):
    out = call("discover_indicators", query="vintage test", lang="en")
    card = next(c for c in out["data"]["concepts"] if c["id"] == "vint")
    assert card["candidates"][0]["dataset"] == "NEWV"
    assert "newer_vintage_preferred" in [n["code"] for n in card["candidates"][0]["notes"]]
    assert card["next_call"]["arguments"]["dataset"] == "NEWV"
