"""Configuration for INS TEMPO Explorer app"""
import os
from pathlib import Path

# Paths
PROJECT_ROOT = Path(__file__).parent.parent
DATA_DIR = Path(os.environ.get("TEMPO_DATA_DIR", str(PROJECT_ROOT / "data")))
DB_PATH = DATA_DIR / "tempo_metadata.duckdb"
PARQUET_DIR = DATA_DIR / "parquet-v3" / "ro"

# API settings
DEFAULT_PAGE_SIZE = 50
MAX_DATA_ROWS = int(os.environ.get("TEMPO_MAX_ROWS", "50000"))
LARGE_DATASET_THRESHOLD = 50_000  # Require filters above this row count

DEBUG = os.environ.get("TEMPO_DEBUG", "false").lower() in ("1", "true", "yes")
