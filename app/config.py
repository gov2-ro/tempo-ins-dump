"""Configuration for INS TEMPO Explorer app"""
import os
from pathlib import Path

# Paths
PROJECT_ROOT = Path(__file__).parent.parent
DATA_DIR = Path(os.environ.get("TEMPO_DATA_DIR", str(PROJECT_ROOT / "data")))
CORPUS_DIR = DATA_DIR / "corpus"
DB_PATH = CORPUS_DIR / "metadata.duckdb"
PARQUET_DIR = CORPUS_DIR / "parquet"
PARQUET_V2_DIR = DATA_DIR / "parquet-v2" / "ro"  # Legacy fallback (unused if corpus is present)

# API settings
DEFAULT_PAGE_SIZE = 50
MAX_DATA_ROWS = int(os.environ.get("TEMPO_MAX_ROWS", "50000"))
LARGE_DATASET_THRESHOLD = 50_000  # Require filters above this row count

DEBUG = os.environ.get("TEMPO_DEBUG", "false").lower() in ("1", "true", "yes")

# LLM agent (POST /api/ask) — disabled by default
ASK_ENABLED        = os.environ.get("TEMPO_ASK_ENABLED", "false").lower() in ("1", "true", "yes")
LLM_PROVIDER       = os.environ.get("TEMPO_LLM_PROVIDER", "anthropic")   # anthropic | openai | gemini
LLM_MODEL          = os.environ.get("TEMPO_LLM_MODEL", "claude-sonnet-4-6")
ASK_MAX_TOOL_CALLS = int(os.environ.get("TEMPO_ASK_MAX_TOOL_CALLS", "8"))
GEMINI_API_KEY     = os.environ.get("GEMINI_API_KEY", "")  # server-side Gemini key (optional)
