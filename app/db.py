"""DuckDB connection management"""
import os

import duckdb
from app.config import DB_PATH

# Short-lived in-memory connections (place KPIs, grain checks on other files)
# get their own bounded budget: an unconfigured DuckDB instance may use 80% of
# the machine's RAM, which on a 512 MiB VM is an OOM (PA-04 workload).
SCRATCH_MEMORY = os.environ.get("TEMPO_SCRATCH_MEMORY", "128MB")
# 160MB: the main connection caches every table page it scans up to this limit, next to the FTS
# sidecar, scratch instances and the Python heap, all inside 512 MiB. 400MB let the cache alone
# approach the machine; 160MB cost ~5-10% p50 latency in the AT-04 mix (AQ-01C record).
DB_MEMORY = os.environ.get("TEMPO_DB_MEMORY", "160MB")
DB_THREADS = int(os.environ.get("TEMPO_DB_THREADS", "0"))   # 0 = DuckDB's default, at most MAX_DEFAULT_THREADS
# Each thread keeps its own aggregation state: at 160MB the heaviest admitted MCP query
# (a 3.9M-row parquet grouped to 108k rows) failed with 8 threads and passed 16/16 with 1-2.
# Fly's one vCPU already gives 1; this keeps a many-core dev machine inside the same budget.
MAX_DEFAULT_THREADS = 2

_conn = None


def get_conn() -> duckdb.DuckDBPyConnection:
    """Get a thread-safe cursor from the shared DuckDB connection.

    DuckDB doesn't support concurrent queries on the same connection,
    so we return a new cursor each time to allow parallel API requests.
    """
    global _conn
    if _conn is None:
        cfg = {"memory_limit": DB_MEMORY}
        if DB_THREADS:
            cfg["threads"] = DB_THREADS
        conn = duckdb.connect(str(DB_PATH), read_only=True, config=cfg)
        if not DB_THREADS and conn.execute("SELECT current_setting('threads')").fetchone()[0] > MAX_DEFAULT_THREADS:
            conn.execute(f"SET threads = {MAX_DEFAULT_THREADS}")
        _conn = conn
    return _conn.cursor()


def scratch_conn() -> duckdb.DuckDBPyConnection:
    """A new in-memory DuckDB connection with a bounded memory budget."""
    return duckdb.connect(config={"memory_limit": SCRATCH_MEMORY, "threads": 2})
