"""AQ-11: the county variant of a concept may be a locality-grain table.

Stage 12 no longer writes a `_judet` child unless the county roll-up is verified, so the reviewed concept
`domicile_population` names POP107D_grupe_localitate (REF_AREA county, REF_AREA_2 locality) as its newer
county-level table. Discovery must prefer it and its county selection must sum the localities, once.
"""
import json
from pathlib import Path

import pytest

from at01_fixtures import add_dataset, add_search_columns, call, make_env
from test_aq04a_discovery_defaults import area_dim
from test_at01_changes import time_dim, unit_dim, UNIT
from test_at01_discovery import concept

ROOT = Path(__file__).resolve().parent.parent
COUNTIES = ["Alba", "Arad"]
LOCALITIES = {"Alba": ["1 Alba Iulia", "2 Sebes"], "Arad": ["3 Arad", "4 Curtici", "5 Ineu"]}
VALUE = {loc: 10.0 * (i + 1) for i, loc in enumerate(sum(LOCALITIES.values(), []))}


def build(corpus):
    rows = [(c, "2024", loc, UNIT, VALUE[loc]) for c, locs in LOCALITIES.items() for loc in locs]
    add_dataset(corpus, "OLDCNTY", [area_dim(COUNTIES), time_dim(("2024",)), unit_dim(UNIT)],
                [(c, "2024", UNIT, 1.0) for c in COUNTIES], updated="2025-01-01")
    add_dataset(corpus, "NEWLOC",
                [area_dim(COUNTIES), time_dim(("2024",)),
                 area_dim(sum(LOCALITIES.values(), []), "locality", "REF_AREA_2"), unit_dim(UNIT)],
                [(c, y, loc, u, v) for c, y, loc, u, v in rows], updated="2026-01-01")
    add_search_columns(corpus)


@pytest.fixture
def env(tmp_path, monkeypatch):
    e = make_env(tmp_path, monkeypatch, build=build)
    from app.services import concept_search, dataset_search
    c = concept("popv", "Population variant", ["population variant"], variants={"county": "OLDCNTY"})
    c["also_families"] = ["NEWLOC"]
    c["also_variants"] = {"county": "NEWLOC"}
    path = tmp_path / "concepts.json"
    path.write_text(json.dumps({"concepts": [c]}))
    monkeypatch.setattr(concept_search, "CONCEPTS_PATH", path)
    monkeypatch.setattr(dataset_search, "SEARCH_DB_PATH", tmp_path / "no-fts.duckdb")
    dataset_search._reset_for_tests()
    return e


def test_discovery_county_path_uses_the_locality_grain_variant(env):
    out = call("discover_indicators", query="population variant", lang="en")
    card = next(c for c in out["data"]["concepts"] if c["id"] == "popv")
    first = card["candidates"][0]
    assert first["dataset"] == "NEWLOC" and first["level"] == "county"
    assert "newer_vintage_preferred" in [n["code"] for n in first["notes"]]
    assert card["next_call"]["arguments"]["dataset"] == "NEWLOC"


def test_county_selection_on_the_locality_table_sums_each_locality_once(env):
    e = call("query_data", dataset="NEWLOC", filters={"TIME_PERIOD": ["2024"]}, group_by=["REF_AREA"], lang="en")
    assert e["status"] != "unavailable", e
    got = {r[0]: r[1] for r in e["data"]["rows"]}
    assert got == {c: sum(VALUE[loc] for loc in locs) for c, locs in LOCALITIES.items()}


def test_shipped_concepts_name_no_removed_county_child():
    """The `_judet` children are not written any more (key_drop_decision); a curated variant must exist."""
    data = json.loads((ROOT / "app" / "data" / "concepts.json").read_text(encoding="utf-8"))
    named = [v for c in data["concepts"] for key in ("variants", "also_variants") for v in (c.get(key) or {}).values()]
    assert "POP107D_grupe_localitate" in named
    assert not [v for v in named if v.endswith("_judet")]
