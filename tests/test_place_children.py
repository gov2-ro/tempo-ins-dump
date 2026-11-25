"""Place children: UATs of a county, counties of a region, regions of a macroregion.
Synthetic fixtures only (no corpus, no writes to data/)."""
import json
import sys
from pathlib import Path

import duckdb
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
from app.services import place_service as ps  # noqa: E402
import static_api  # noqa: E402

UATS = {
    "by_siruta": {
        111: {"siruta": 111, "name": "Bigcity", "kind": "municipiu", "county_slug": "arad"},
        222: {"siruta": 222, "name": "Smalltown", "kind": "oras", "county_slug": "arad"},
        333: {"siruta": 333, "name": "Village", "kind": "comuna", "county_slug": "arad"},
        444: {"siruta": 444, "name": "Village", "kind": "comuna", "county_slug": "timis"},
        555: {"siruta": 555, "name": "Zed", "kind": "comuna", "county_slug": "timis"},
    },
}
UATS["by_county"] = {}
for _it in UATS["by_siruta"].values():
    UATS["by_county"].setdefault(_it["county_slug"], []).append(_it)


@pytest.fixture
def conn(monkeypatch):
    con = duckdb.connect()
    con.execute("CREATE TABLE dimension_options_parsed (nom_item_id INTEGER, dim_type VARCHAR, geo_level VARCHAR, "
                "geo_name_clean VARCHAR, siruta_code INTEGER)")
    con.executemany("INSERT INTO dimension_options_parsed VALUES (?,?,?,?,?)", [
        (1, "geo", "county", "Arad", None), (2, "geo", "county", "Timis", None),
        (3, "geo", "locality", "MUNICIPIUL BIGCITY", 111), (4, "geo", "locality", "ORAS SMALLTOWN", 222),
        (5, "geo", "locality", "VILLAGE", 333), (6, "geo", "locality", "VILLAGE", 444),   # same name, two counties
        (7, "geo", "locality", "ZED", 555),
    ])
    monkeypatch.setattr(ps, "_county_uats", lambda: UATS)
    monkeypatch.setattr(ps, "_kpi_config", {"locality": [], "county": [], "featured_localities": {
        "items": [{"type": "locality", "slug": "municipiul-bigcity", "siruta": 111, "name": "Bigcity",
                   "county": "Arad", "county_slug": "arad"}]}})
    yield con
    con.close()


def test_county_children_group_municipalities_first_and_mark_the_listed_city(conn):
    kids = ps.get_place_children("county", "arad", conn=conn)
    assert [(k["name"], k["kind"]) for k in kids] == \
        [("Bigcity", "municipiu"), ("Smalltown", "oras"), ("Village", "comuna")]
    assert [k.get("featured") for k in kids] == [True, None, None]
    assert all(k["type"] == "locality" for k in kids)


def test_a_repeated_name_gets_a_unique_slug_and_every_child_resolves(conn):
    arad = {k["slug"] for k in ps.get_place_children("county", "arad", conn=conn)}
    timis = {k["slug"] for k in ps.get_place_children("county", "timis", conn=conn)}
    assert "village-333" in arad and "village-444" in timis and "zed" in timis
    for slug in arad | timis:
        assert ps.resolve_place("locality", slug, conn=conn), slug
    assert ps.resolve_place("locality", "village", conn=conn) is None      # ambiguous bare slug
    p = ps.resolve_place("locality", "village-444", conn=conn)
    assert (p["parent_slug"], p["parent_name"], p["siruta"]) == ("timis", "Timis", None)  # KPI gate stays closed


def test_a_listed_city_keeps_its_siruta_for_the_kpis(conn):
    assert ps.resolve_place("locality", "municipiul-bigcity", conn=conn)["siruta"] == "111"


def test_region_children_are_its_counties_and_macroregion_children_its_regions(conn):
    assert [c["slug"] for c in ps.get_place_children("region", "vest", conn=conn)] == \
        ["arad", "caras-severin", "hunedoara", "timis"]
    mac = ps.get_place_children("macroregion", "macroregiunea-patru", conn=conn)
    assert [(c["type"], c["slug"]) for c in mac] == [("region", "sud-vest-oltenia"), ("region", "vest")]
    assert ps.get_place_children("locality", "municipiul-bigcity", conn=conn) == []
    assert ps.get_place_children("county", "municipiul-bucuresti", conn=conn) == []


def test_every_county_region_and_macroregion_is_covered():
    regions = {r for ms in ps.MACROREGION_REGIONS.values() for r in ms}
    assert regions == set(ps.REGION_NAMES)
    assert all(len(v) == 2 for v in ps.MACROREGION_REGIONS.values())


def test_the_shipped_uat_list_matches_the_county_slugs():
    data = json.loads((Path(ps.__file__).parent.parent / "data" / "county_uats.json").read_text(encoding="utf-8"))
    counties = {ps.slugify(k) for k in ps.COUNTY_REGION} - {"municipiul-bucuresti"}
    assert {i["county_slug"] for i in data["items"]} == counties
    assert len({i["siruta"] for i in data["items"]}) == len(data["items"])


def test_static_recording_covers_every_child_link_once():
    profiles = {
        "/api/places": {"places": [{"type": "county", "slug": "arad", "name": "Arad"},
                                   {"type": "locality", "slug": "municipiul-bigcity", "name": "Bigcity"}]},
        "/api/places/county/arad": {"kpis": [], "children": [
            {"type": "locality", "slug": "municipiul-bigcity"}, {"type": "locality", "slug": "village-333"}]},
        "/api/places/locality/municipiul-bigcity": {"kpis": [], "children": []},
        "/api/places/locality/village-333": {"kpis": [], "children": [], "datasets": []},
    }
    asked, put = [], {}

    class Client:
        def get(self, url, params=None):
            asked.append(url)

            class R:
                status_code = 200
                def json(self_):
                    return profiles[url]
            return R()

    static_api.record_places(Client(), lambda obj, rel: put.__setitem__(rel, obj))
    assert "place/locality/village-333.json.gz" in put          # a non-featured UAT is recorded
    assert asked.count("/api/places/locality/municipiul-bigcity") == 1   # a listed city is not recorded twice
    assert set(put) == {"places.json.gz", "place/county/arad.json.gz", "place/locality/municipiul-bigcity.json.gz",
                        "place/locality/village-333.json.gz"}
