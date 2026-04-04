"""INS TEMPO Data Explorer — FastAPI application."""
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pathlib import Path

from app.config import CORPUS_DIR
from app.routers import categories, datasets, dataset_data, sdmx

app = FastAPI(title="INS TEMPO Explorer", version="0.1.0")

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

# Serve view profiles (must come before catch-all static mount)
view_profiles_dir = CORPUS_DIR / "view-profiles"
if view_profiles_dir.exists():
    app.mount("/view-profiles", StaticFiles(directory=str(view_profiles_dir)), name="view-profiles")

# Serve static frontend
static_dir = Path(__file__).parent / "static"
app.mount("/", StaticFiles(directory=str(static_dir), html=True), name="static")
