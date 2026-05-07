"""Tests for place_service.py — place resolution, slugify, dataset list."""
import sys
sys.path.insert(0, '.')
import pytest
from app.services.place_service import slugify, resolve_place, get_place_datasets


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
