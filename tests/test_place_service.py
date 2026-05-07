"""Tests for place_service.py — place resolution, slugify, dataset list."""
import sys
sys.path.insert(0, '.')
import pytest
from app.services.place_service import slugify, resolve_place, get_place_datasets, get_place_kpis, get_place_peers, get_kpi_baselines


def test_slugify_county():
    assert slugify("Bihor") == "bihor"

def test_slugify_with_hyphen():
    assert slugify("Bistrita-Nasaud") == "bistrita-nasaud"

def test_slugify_region_strip_prefix():
    # All region name variants normalize to the same slug
    assert slugify("Regiunea NORD-VEST") == "nord-vest"
    assert slugify("Regiunea Nord-Vest") == "nord-vest"
    assert slugify("REGIUNEA NORD-VEST") == "nord-vest"

def test_slugify_spaces_to_hyphens():
    assert slugify("Satu Mare") == "satu-mare"

def test_slugify_diacritics():
    assert slugify("Mureș") == "mures"
    assert slugify("Brăila") == "braila"


def test_resolve_county_returns_geo_names():
    result = resolve_place("county", "bihor")
    assert result is not None
    assert result["name"] == "Bihor"
    assert result["type"] == "county"
    assert isinstance(result["ref_area_values"], list)
    assert "Bihor" in result["ref_area_values"]


def test_resolve_region_returns_multiple_names():
    result = resolve_place("region", "nord-vest")
    assert result is not None
    assert result["type"] == "region"
    # Region has multiple raw names in DB — all normalized to same slug
    assert len(result["ref_area_values"]) >= 1


def test_resolve_unknown_returns_none():
    result = resolve_place("county", "notaplace99")
    assert result is None


def test_get_place_datasets_returns_list():
    datasets = get_place_datasets("county", "bihor")
    assert isinstance(datasets, list)
    assert len(datasets) > 50  # Bihor has 443 datasets
    # Each entry has required fields
    for d in datasets[:5]:
        assert "code" in d
        assert "title" in d
        assert "has_data" in d
        assert d["has_data"] is True


def test_get_place_datasets_unknown_returns_empty():
    datasets = get_place_datasets("county", "notaplace99")
    assert datasets == []


def test_get_place_kpis_county_returns_list():
    kpis = get_place_kpis("county", "bihor")
    assert isinstance(kpis, list)
    assert len(kpis) > 0
    kpi = kpis[0]
    assert "label" in kpi
    assert "unit" in kpi
    # value may be None if data missing, but sparkline must be a list
    assert isinstance(kpi["sparkline"], list)


def test_get_place_kpis_has_unemployment():
    kpis = get_place_kpis("county", "bihor")
    labels = [k["label"] for k in kpis]
    assert any("șomaj" in l.lower() or "somaj" in l.lower() for l in labels)


def test_get_place_kpis_sparkline_ordered():
    kpis = get_place_kpis("county", "bihor")
    pop_kpi = next((k for k in kpis if "opulat" in k["label"]), None)
    if pop_kpi and len(pop_kpi["sparkline"]) >= 2:
        years = [entry["year"] for entry in pop_kpi["sparkline"]]
        assert years == sorted(years)  # ascending


def test_get_place_kpis_missing_locality_returns_empty():
    # Localities have no KPI config — must return empty list, not error
    kpis = get_place_kpis("locality", "oradea")
    assert isinstance(kpis, list)  # empty list OK


def test_get_place_peers_county_has_same_region():
    peers = get_place_peers("county", "bihor")
    assert "same_region" in peers
    assert isinstance(peers["same_region"], list)
    slugs = [p["slug"] for p in peers["same_region"]]
    assert "cluj" in slugs  # Cluj is also Nord-Vest


def test_get_place_peers_county_has_similar_size():
    peers = get_place_peers("county", "bihor")
    assert "similar_size" in peers
    assert len(peers["similar_size"]) <= 3


def test_get_place_peers_self_excluded():
    peers = get_place_peers("county", "bihor")
    all_peer_slugs = (
        [p["slug"] for p in peers.get("same_region", [])] +
        [p["slug"] for p in peers.get("similar_size", [])]
    )
    assert "bihor" not in all_peer_slugs


def test_get_kpi_baselines_returns_national():
    baselines = get_kpi_baselines("county", "bihor", "Rata șomajului BIM")
    assert "national" in baselines
    assert isinstance(baselines["national"], list)
    assert len(baselines["national"]) > 0


def test_get_kpi_baselines_returns_region():
    baselines = get_kpi_baselines("county", "bihor", "Rata șomajului BIM")
    assert "region" in baselines
    assert isinstance(baselines["region"], list)


def test_get_place_peers_region_returns_siblings():
    peers = get_place_peers("region", "nord-vest")
    assert "same_region" in peers
    assert isinstance(peers["same_region"], list)
    # Should have other regions as siblings
    assert len(peers["same_region"]) > 0
    # similar_size is empty for non-county
    assert peers["similar_size"] == []


# --- Route tests ---

from fastapi.testclient import TestClient
from app.main import app

_client = TestClient(app)


def test_api_places_list():
    resp = _client.get("/api/places")
    assert resp.status_code == 200
    data = resp.json()
    assert "places" in data
    county_slugs = [p["slug"] for p in data["places"] if p["type"] == "county"]
    assert "bihor" in county_slugs
    assert "cluj" in county_slugs


def test_api_place_profile_county():
    resp = _client.get("/api/places/county/bihor")
    assert resp.status_code == 200
    data = resp.json()
    assert data["place"]["name"] == "Bihor"
    assert data["place"]["type"] == "county"
    assert isinstance(data["kpis"], list)
    assert isinstance(data["datasets"], list)
    assert "same_region" in data["peers"]


def test_api_place_profile_not_found():
    resp = _client.get("/api/places/county/notaplace")
    assert resp.status_code == 404


def test_api_place_baselines():
    # Get the first KPI label for county
    import json
    config = json.load(open("app/static/data/place_kpi_config.json"))
    label = config["county"][0]["label"]
    from urllib.parse import quote
    resp = _client.get(f"/api/places/county/bihor/baselines/{quote(label)}")
    assert resp.status_code == 200
    data = resp.json()
    assert "national" in data
    assert "region" in data
