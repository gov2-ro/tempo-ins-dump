"""INS TEMPO Data Explorer — FastAPI application."""
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
import logging
from fastapi.middleware.cors import CORSMiddleware
from pathlib import Path

from app.config import CORPUS_DIR
from app.routers import categories, datasets, dataset_data, sdmx, ask, places

app = FastAPI(title="INS TEMPO Explorer", version="0.1.0")

log = logging.getLogger("app.api")


@app.exception_handler(Exception)
async def _unhandled(request, exc):
    """Last-resort handler: log with context, never echo SQL or server paths."""
    log.error("Unhandled error on %s %s", request.method, request.url.path,
              exc_info=exc)
    return JSONResponse({"detail": "Internal server error"}, status_code=500)


# CORS for development
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# API routers
app.include_router(categories.router, prefix="/api", tags=["categories"])
app.include_router(datasets.router, prefix="/api", tags=["datasets"])
app.include_router(dataset_data.router, prefix="/api", tags=["data"])
app.include_router(sdmx.router, prefix="/sdmx", tags=["sdmx"])
app.include_router(ask.router, prefix="/api", tags=["ask"])
app.include_router(places.router, tags=["places"])

_LLMS_TXT = Path(__file__).parent.parent / "llms.txt"

@app.get("/llms.txt", include_in_schema=False)
async def llms_txt():
    return FileResponse(_LLMS_TXT, media_type="text/plain")

@app.get("/api/health", include_in_schema=False)
def health():
    """Release/ops status: FTS mode (observable production fallback) + manifest."""
    import json
    from app.services.dataset_search import search_status
    st = {k: v for k, v in search_status().items() if k != "path"}
    manifest = None
    mp = CORPUS_DIR.parent / "MANIFEST.json"
    if mp.exists():
        try:
            m = json.loads(mp.read_text())
            manifest = {
                "generation_id": m.get("generation", {}).get("id"),
                "generation_status": m.get("generation", {}).get("status"),
                "staged_at": m.get("staged_at"),
                "latest_observation_date": m.get("source", {}).get("latest_observation_date"),
            }
        except Exception:
            manifest = {"error": "unreadable"}
    return {"status": "ok" if st["mode"] == "fts" else "degraded",
            "search": st, "manifest": manifest}


# Serve view profiles (must come before catch-all static mount)
view_profiles_dir = CORPUS_DIR / "view-profiles"
if view_profiles_dir.exists():
    app.mount("/view-profiles", StaticFiles(directory=str(view_profiles_dir)), name="view-profiles")

# Serve static frontend
static_dir = Path(__file__).parent / "static"
app.mount("/", StaticFiles(directory=str(static_dir), html=True), name="static")
