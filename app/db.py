"""DuckDB connection management"""
import os

import duckdb
from app.config import DB_PATH

# Short-lived in-memory connections (place KPIs, grain checks on other files)
# get their own bounded budget: an unconfigured DuckDB instance may use 80% of
# the machine's RAM, which on a 512 MiB VM is an OOM (PA-04 workload).
SCRATCH_MEMORY = os.environ.get("TEMPO_SCRATCH_MEMORY", "128MB")
DB_MEMORY = os.environ.get("TEMPO_DB_MEMORY", "400MB")
DB_THREADS = int(os.environ.get("TEMPO_DB_THREADS", "0"))   # 0 = DuckDB default (all cores)

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
        _conn = duckdb.connect(str(DB_PATH), read_only=True, config=cfg)
    return _conn.cursor()


def scratch_conn() -> duckdb.DuckDBPyConnection:
    """A new in-memory DuckDB connection with a bounded memory budget."""
    return duckdb.connect(config={"memory_limit": SCRATCH_MEMORY, "threads": 2})
