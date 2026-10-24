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
MAX_DATA_ROWS = int(os.environ.get("TEMPO_MAX_ROWS", "50000"))  # chart/query cap only
# Downloads (FIX-04) are NOT bound by MAX_DATA_ROWS. 0 = no cap (CSV streams in
# bounded memory). XLSX is always capped by Excel's sheet size (1,048,575 data rows).
EXPORT_MAX_ROWS = int(os.environ.get("TEMPO_EXPORT_MAX_ROWS", "0"))
EXPORT_XLSX_MAX_ROWS = int(os.environ.get("TEMPO_EXPORT_XLSX_MAX_ROWS", "1048575"))
# SDMX-ML is verbose (~350 B/obs) and streamed; over this many observations the
# request is rejected (413) rather than truncated.
SDMX_MAX_OBS = int(os.environ.get("TEMPO_SDMX_MAX_OBS", "250000"))
# Concurrent file exports (CSV+XLSX+SDMX share one pool); XLSX is further limited.
EXPORT_MAX_CONCURRENT = int(os.environ.get("TEMPO_EXPORT_MAX_CONCURRENT", "2"))
EXPORT_XLSX_MAX_CONCURRENT = int(os.environ.get("TEMPO_EXPORT_XLSX_MAX_CONCURRENT", "1"))
EXPORT_BATCH_ROWS = int(os.environ.get("TEMPO_EXPORT_BATCH_ROWS", "5000"))
LARGE_DATASET_THRESHOLD = 50_000  # Require filters above this row count

DEBUG = os.environ.get("TEMPO_DEBUG", "false").lower() in ("1", "true", "yes")

# Trusted public origin for citations, downloads and evidence links of the
# analytical tools (e.g. https://ins.gov2.ro). Unset: root-relative links. Links
# are never derived from a request's Host or forwarded headers.
PUBLIC_BASE_URL = os.environ.get("TEMPO_PUBLIC_BASE_URL", "").strip()
# Trusted origin of the site's pages when they are served apart from the API (the static
# site, e.g. https://ins.gov2.ro, with the API on its own host). Page links (dataset,
# recipe pages) use it; /api, /sdmx and /mcp links keep TEMPO_PUBLIC_BASE_URL. Unset: the
# pages are on TEMPO_PUBLIC_BASE_URL too.
PUBLIC_SITE_URL = os.environ.get("TEMPO_PUBLIC_SITE_URL", "").strip()


def cors_origins(environ=None) -> list[str]:
    """TEMPO_CORS_ORIGINS: the web origins allowed to call the API from a browser (comma list
    of bare origins, e.g. https://ins.gov2.ro). Unset: none listed, and only local development
    origins (localhost, 127.0.0.1, any port) are allowed. No wildcard: an open policy has to
    be the explicit list of sites, and /mcp keeps its own Host/Origin gate either way."""
    from urllib.parse import urlsplit
    env = os.environ if environ is None else environ
    out = []
    for o in (x.strip().rstrip("/") for x in env.get("TEMPO_CORS_ORIGINS", "").split(",")):
        if not o:
            continue
        u = urlsplit(o)
        if "*" in o or u.scheme not in ("http", "https") or not u.hostname or u.username \
                or u.password or u.path or u.query or u.fragment:
            raise ValueError(f"TEMPO_CORS_ORIGINS: {o!r} is not a bare http(s) origin "
                             "such as https://ins.gov2.ro (no wildcard, path or credentials)")
        out.append(f"{u.scheme}://{u.netloc}")
    return list(dict.fromkeys(out))


CORS_ORIGINS = cors_origins()

# LLM agent (POST /api/ask) — disabled by default
ASK_ENABLED        = os.environ.get("TEMPO_ASK_ENABLED", "false").lower() in ("1", "true", "yes")
# Bring-your-own-key Ask is a separate switch, also off by default: Ask stays out
# of the public alpha until its exposure gate passes (PA-01/PA-04).
ASK_BYOK_ENABLED   = os.environ.get("TEMPO_ASK_BYOK_ENABLED", "false").lower() in ("1", "true", "yes")
LLM_PROVIDER       = os.environ.get("TEMPO_LLM_PROVIDER", "anthropic")   # see llm_client.PROVIDERS
LLM_MODEL          = os.environ.get("TEMPO_LLM_MODEL", "claude-sonnet-5-5")
# Server-funded keys are read per provider (ANTHROPIC_API_KEY, OPENAI_API_KEY, GEMINI_API_KEY,
# MISTRAL_API_KEY, DEEPSEEK_API_KEY, XAI_API_KEY, OPENROUTER_API_KEY).
# Local Ollama (OpenAI-compatible), e.g. http://localhost:11434/v1. Unset: no Ollama provider.
OLLAMA_BASE_URL    = os.environ.get("TEMPO_OLLAMA_BASE_URL", "")
ASK_LOG_CHATS      = os.environ.get("TEMPO_ASK_LOG_CHATS", "false").lower() in ("1", "true", "yes")
# Local debugging only: per-step agent events in responses and POST /api/ask/stream.
ASK_DEBUG          = os.environ.get("TEMPO_ASK_DEBUG", "false").lower() in ("1", "true", "yes")
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
# SDK-level retries for callers outside the Ask loop. The loop itself passes 0: it owns
# the one retry its policy allows, inside the request deadline (AT-02).
ASK_PROVIDER_MAX_RETRIES = _int_env("TEMPO_ASK_PROVIDER_MAX_RETRIES", 1)

# --- AT-02: model output, context and debug bounds -------------------------
# Output tokens requested per model call. Reasoning tokens count against the limit, so a
# reasoning-capable model gets a larger allowance (provider:model, a trailing * matches
# any model). The defaults are engineering starting points, not measured guarantees;
# revisit them with the AT-04 cost/quality evidence.
ASK_OUTPUT_TOKENS            = _int_env("TEMPO_ASK_OUTPUT_TOKENS", 2048)
ASK_REASONING_OUTPUT_TOKENS  = _int_env("TEMPO_ASK_REASONING_OUTPUT_TOKENS", 8000)
ASK_REASONING_MODELS         = _csv_env("TEMPO_ASK_REASONING_MODELS") or ["deepseek:*"]
ASK_RESPONSES_MIN_OUTPUT_TOKENS = _int_env("TEMPO_ASK_RESPONSES_MIN_OUTPUT_TOKENS", 8000)  # OpenAI Responses
# Aggregate requested output tokens per Ask turn (every call, retry and the final answer).
ASK_TURN_OUTPUT_TOKENS       = _int_env("TEMPO_ASK_TURN_OUTPUT_TOKENS", 64000)
# Serialized tool output kept in the model's context across one turn (UTF-8 bytes).
ASK_CONTEXT_BYTES            = _int_env("TEMPO_ASK_CONTEXT_BYTES", 96 * 1024)
# Debug events kept per request (the rest are counted, not stored).
ASK_DEBUG_MAX_EVENTS         = _int_env("TEMPO_ASK_DEBUG_MAX_EVENTS", 200)
