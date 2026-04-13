"""Dataset listing, search, and detail API endpoints.

Thin wrappers around app/services/dataset_search.py and
app/services/dataset_meta.py — all logic lives in the service layer.
"""
from fastapi import APIRouter, Query, HTTPException
from app.config import DEFAULT_PAGE_SIZE
from app.services.dataset_search import search_datasets
from app.services.dataset_meta import get_dataset_meta

router = APIRouter()


@router.get("/datasets")
def list_datasets(
    q: str = Query(None, description="Search in dataset name"),
    context: str = Query(None, description="Filter by context_code"),
    ancestor: str = Query(None, description="Filter by ancestor code"),
    archetype: str = Query(None, description="Filter by archetype"),
    has_geo: bool = Query(None),
    granularity: str = Query(None, description="Filter by time_granularity: annual|monthly|quarterly"),
    has_gender: bool = Query(None),
    has_age: bool = Query(None),
    has_residence: bool = Query(None),
    lang: str = Query("ro", description="Language: ro|en"),
    sort: str = Query("updated", description="Sort: updated|name|rows|dims|options"),
    limit: int = Query(DEFAULT_PAGE_SIZE, le=200),
    offset: int = Query(0, ge=0),
):
    """List datasets with search and filters."""
    return search_datasets(
        q, context=context, ancestor=ancestor, archetype=archetype,
        has_geo=has_geo, granularity=granularity, has_gender=has_gender,
        has_age=has_age, has_residence=has_residence,
        lang=lang, sort=sort, limit=limit, offset=offset,
    )


@router.get("/datasets/{matrix_code}")
def get_dataset(matrix_code: str, lang: str = Query("ro", description="Language: ro|en")):
    """Get full dataset metadata, dimensions, options, and chart config."""
    result = get_dataset_meta(matrix_code, lang)
    if result is None:
        raise HTTPException(404, f"Dataset {matrix_code} not found")
    return result
