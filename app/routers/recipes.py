"""Recipe API (PA-03b): tourism intensity and its evidence bundle."""
import json
from urllib.parse import urlencode

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import Response

from app.db import get_conn

router = APIRouter()


def _areas(raw: str | None) -> list[str] | None:
    if not raw:
        return None
    try:
        v = json.loads(raw)
    except ValueError:
        raise HTTPException(400, "Invalid areas: expected a JSON array of area names")
    if not isinstance(v, list) or not all(isinstance(a, str) for a in v) or len(v) > 60:
        raise HTTPException(400, "Invalid areas: expected a JSON array of up to 60 area names")
    return v or None


def _run(recipe_id, year, areas, lang):
    from app.services.recipes import RecipeError, run
    conn = get_conn()
    try:
        return run(conn, recipe_id, year=year, areas=_areas(areas), lang=lang)
    except RecipeError as e:
        status = 404 if e.reason == "unknown_recipe" else 422
        raise HTTPException(status, e.to_dict())
    finally:
        conn.close()


@router.get("/recipes")
def list_recipes(lang: str = Query("ro", pattern="^(ro|en)$")):
    from app.services.recipes import load_recipes
    return {"recipes": [{"id": r["id"], "version": r["version"], "question": r.get("question"),
                         "name": r["name"].get(lang) or r["name"]["ro"],
                         "status": r["status"].get(lang) or r["status"]["ro"]}
                        for r in load_recipes().values()]}


@router.get("/recipes/{recipe_id}")
def get_recipe_result(recipe_id: str,
                      year: str = Query(None, pattern=r"^\d{4}$"),
                      areas: str = Query(None, max_length=2000, description="JSON array of county names"),
                      lang: str = Query("ro", pattern="^(ro|en)$")):
    """Run a reviewed recipe. Without `year`, the latest year both sources have.
    422 with `reason` when no valid result exists (year unavailable, source
    refused or capped, duplicate keys, unknown unit)."""
    out = _run(recipe_id, year, areas, lang)
    out.pop("inputs", None)          # inputs travel in the evidence bundle
    return out


@router.get("/recipes/{recipe_id}/evidence")
def get_recipe_evidence(request: Request, recipe_id: str,
                        year: str = Query(None, pattern=r"^\d{4}$"),
                        areas: str = Query(None, max_length=2000),
                        lang: str = Query("ro", pattern="^(ro|en)$")):
    """ZIP evidence bundle for the recipe result (see app/services/evidence.py)."""
    from app.services import export as ex
    from app.services.evidence import recipe_bundle
    slot = ex.try_acquire("csv")
    if slot is None:
        raise ex.busy_error()
    try:
        result = _run(recipe_id, year, areas, lang)
        params = {k: v for k, v in {"recipe": recipe_id, "year": result["year"],
                                    "areas": areas, "lang": lang}.items() if v}
        link = f"{str(request.base_url).rstrip('/')}/compare.html?{urlencode(params)}"
        data = recipe_bundle(result, link)
    finally:
        slot()
    name = f"{recipe_id}_{result['year']}_evidence.zip"
    return Response(data, media_type="application/zip",
                    headers={"Content-Disposition": f"attachment; filename={name}"})
