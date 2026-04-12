"""DuckDB connection management"""
import duckdb
from app.config import DB_PATH

_conn = None


def get_conn() -> duckdb.DuckDBPyConnection:
    """Get a thread-safe cursor from the shared DuckDB connection.

    DuckDB doesn't support concurrent queries on the same connection,
    so we return a new cursor each time to allow parallel API requests.
    """
    global _conn
    if _conn is None:
        _conn = duckdb.connect(str(DB_PATH), read_only=True, config={"memory_limit": "400MB"})
    return _conn.cursor()
