"""Place profile routes — directory listing and individual place profiles."""
from pathlib import Path
from urllib.parse import unquote
from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from app.db import get_conn
from app.services.place_service import (
    resolve_place, get_place_datasets, get_place_kpis,
    get_place_peers, get_kpi_baselines, slugify,
)

router = APIRouter()

_STATIC = Path(__file__).parent.parent / "static"

GEO_LEVELS = ("county", "region", "macroregion", "locality")


@router.get("/places", include_in_schema=False)
def places_directory_html():
    path = _STATIC / "places.html"
    if not path.exists():
        raise HTTPException(404, "places.html not yet created")
    return FileResponse(path)


@router.get("/place/{place_type}/{slug}", include_in_schema=False)
def place_profile_html(place_type: str, slug: str):
    if place_type not in GEO_LEVELS:
        raise HTTPException(404, "Unknown place type")
    path = _STATIC / "place.html"
    if not path.exists():
        raise HTTPException(404, "place.html not yet created")
    return FileResponse(path)


@router.get("/api/places")
def list_places():
    """List all known places grouped by type."""
    conn = get_conn()
    rows = conn.execute("""
        SELECT DISTINCT geo_level, geo_name_clean
        FROM dimension_options_parsed
        WHERE dim_type = 'geo'
          AND geo_level IN ('county', 'region', 'macroregion')
          AND geo_name_clean IS NOT NULL
        ORDER BY geo_level, geo_name_clean
    """).fetchall()

    seen: set = set()
    places = []
    for geo_level, name in rows:
        sl = slugify(name)
        key = (geo_level, sl)
        if key in seen:
            continue
        seen.add(key)
        places.append({"type": geo_level, "slug": sl, "name": name})

    return {"places": places, "total": len(places)}


@router.get("/api/places/{place_type}/{slug}/baselines/{kpi_label}")
def get_place_baselines(place_type: str, slug: str, kpi_label: str):
    """National + region baseline series for a single KPI."""
    if place_type not in GEO_LEVELS:
        raise HTTPException(404, "Unknown place type")
    label = unquote(kpi_label)
    return get_kpi_baselines(place_type, slug, label)


@router.get("/api/places/{place_type}/{slug}")
def get_place_profile(place_type: str, slug: str):
    """Full place profile: KPIs, dataset list, peers."""
    if place_type not in GEO_LEVELS:
        raise HTTPException(404, "Unknown place type")

    conn = get_conn()
    place = resolve_place(place_type, slug, conn=conn)
    if not place:
        raise HTTPException(404, f"Place not found: {place_type}/{slug}")

    parent = None
    if place.get("parent_slug"):
        parent = {
            "type": "region",
            "slug": place["parent_slug"],
            "name": place.get("parent_name", place["parent_slug"]),
        }

    kpis = get_place_kpis(place_type, slug, conn=conn)
    datasets = get_place_datasets(place_type, slug, conn=conn)
    peers = get_place_peers(place_type, slug, conn=conn)

    return {
        "place": {
            "name": place["name"],
            "type": place_type,
            "slug": slug,
            "parent": parent,
        },
        "kpis": kpis,
        "datasets": datasets,
        "peers": peers,
        "dataset_count": len(datasets),
    }
