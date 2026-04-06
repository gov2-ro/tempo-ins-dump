"""DuckDB connection management."""
import duckdb
from explorer.config import DB_PATH

_conn = None


def get_conn() -> duckdb.DuckDBPyConnection:
    """Get a thread-safe cursor from the shared DuckDB connection."""
    global _conn
    if _conn is None:
        _conn = duckdb.connect(str(DB_PATH), read_only=True)
    return _conn.cursor()
