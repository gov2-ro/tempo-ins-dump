"""Configuration for INS TEMPO Explorer app"""
from pathlib import Path

# Paths
PROJECT_ROOT = Path(__file__).parent.parent
DATA_DIR = PROJECT_ROOT / "data"
DB_PATH = DATA_DIR / "tempo_metadata.duckdb"
PARQUET_DIR = DATA_DIR / "parquet-v2" / "ro"

# API settings
DEFAULT_PAGE_SIZE = 50
MAX_DATA_ROWS = 50000
LARGE_DATASET_THRESHOLD = 50_000  # Require filters above this row count

DEBUG = True
