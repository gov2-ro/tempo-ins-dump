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
GEMINI_API_KEY     = os.environ.get("GEMINI_API_KEY", "")  # server-side Gemini key (optional)
ASK_LOG_CHATS      = os.environ.get("TEMPO_ASK_LOG_CHATS", "false").lower() in ("1", "true", "yes")
ASK_LOG_DIR        = Path(os.environ.get("TEMPO_ASK_LOG_DIR", str(PROJECT_ROOT / "logs")))

# --- Ask request bounds, allowlist and budgets (FIX-08) --------------------
def _int_env(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except ValueError:
        return default

def _float_env(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, default))
    except ValueError:
        return default

def _csv_env(name: str) -> list[str]:
    return [x.strip() for x in os.environ.get(name, "").split(",") if x.strip()]

# History / request size (characters, after normalisation)
ASK_MAX_QUESTION_CHARS = _int_env("TEMPO_ASK_MAX_QUESTION_CHARS", 2000)
ASK_MAX_HISTORY_TURNS  = _int_env("TEMPO_ASK_MAX_HISTORY_TURNS", 20)
ASK_MAX_TURN_CHARS     = _int_env("TEMPO_ASK_MAX_TURN_CHARS", 8000)
ASK_MAX_REQUEST_CHARS  = _int_env("TEMPO_ASK_MAX_REQUEST_CHARS", 40000)

# Provider/model allowlist. Empty = derive from static/ask-models.json.
#   TEMPO_ASK_ALLOWED_PROVIDERS  comma list restricting BYOK providers
#   TEMPO_ASK_ALLOWED_MODELS     comma list of provider:model (overrides the JSON)
#   TEMPO_ASK_SERVER_MODELS      provider:model pairs a *server-funded* call may use
#                                (default: only TEMPO_LLM_PROVIDER:TEMPO_LLM_MODEL)
ASK_ALLOWED_PROVIDERS = _csv_env("TEMPO_ASK_ALLOWED_PROVIDERS")
ASK_ALLOWED_MODELS    = _csv_env("TEMPO_ASK_ALLOWED_MODELS")
ASK_SERVER_MODELS     = _csv_env("TEMPO_ASK_SERVER_MODELS")
ASK_MODELS_FILE       = Path(os.environ.get("TEMPO_ASK_MODELS_FILE",
                                            str(PROJECT_ROOT / "app" / "static" / "ask-models.json")))

# Independent per-request budgets
ASK_MAX_ITERATIONS     = _int_env("TEMPO_ASK_MAX_ITERATIONS", 8)       # model calls
ASK_MAX_TOOL_CALLS     = _int_env("TEMPO_ASK_MAX_TOOL_CALLS", 12)      # tools dispatched in total
ASK_MAX_SECONDS        = _float_env("TEMPO_ASK_MAX_SECONDS", 90.0)     # wall clock per request
ASK_MAX_CONCURRENT     = _int_env("TEMPO_ASK_MAX_CONCURRENT", 2)       # in-process semaphore
ASK_RETRY_AFTER_SECONDS = _int_env("TEMPO_ASK_RETRY_AFTER_SECONDS", 10)

# Provider call limits
ASK_PROVIDER_TIMEOUT     = _float_env("TEMPO_ASK_PROVIDER_TIMEOUT", 30.0)  # per provider call
ASK_PROVIDER_MAX_RETRIES = _int_env("TEMPO_ASK_PROVIDER_MAX_RETRIES", 1)   # SDK-level retries
