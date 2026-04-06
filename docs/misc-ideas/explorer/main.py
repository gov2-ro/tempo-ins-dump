"""StatExplorer — Tableau-inspired statistical data explorer."""
import logging
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pathlib import Path

from explorer.routers import categories, datasets, dataset_data
from explorer.services.translations import load_translations

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="StatExplorer", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Load EN translations at startup
@app.on_event("startup")
def startup():
    load_translations()
    logger.info("StatExplorer ready")

# API routers
app.include_router(categories.router, prefix="/api", tags=["categories"])
app.include_router(datasets.router, prefix="/api", tags=["datasets"])
app.include_router(dataset_data.router, prefix="/api", tags=["data"])

# Serve static frontend
static_dir = Path(__file__).parent / "static"
app.mount("/", StaticFiles(directory=str(static_dir), html=True, follow_symlink=True), name="static")
