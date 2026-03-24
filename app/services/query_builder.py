"""Dynamic SQL builder for parquet queries with filter pushdown."""
from app.config import PARQUET_DIR, PARQUET_V2_DIR, MAX_DATA_ROWS
from app.db import get_conn


# Module-level cache for nomItemId → sdmx_value lookup
_id_to_sdmx_cache = None


def _get_id_to_sdmx():
    """Lazy-load the nomItemId → sdmx_value mapping from DuckDB."""
    global _id_to_sdmx_cache
    if _id_to_sdmx_cache is None:
        try:
            conn = get_conn()
            rows = conn.execute("SELECT nom_item_id, sdmx_value FROM sdmx_codes").fetchall()
            _id_to_sdmx_cache = {nom_id: val for nom_id, val in rows}
        except Exception:
            _id_to_sdmx_cache = {}
    return _id_to_sdmx_cache


def _resolve_parquet_path(matrix_code: str):
    """Find the parquet file for a matrix code. Checks v3 first, then v2 fallback."""
    v3_path = PARQUET_DIR / f"{matrix_code}.parquet"
    if v3_path.exists():
        return v3_path
    v2_path = PARQUET_V2_DIR / f"{matrix_code}.parquet"
    if v2_path.exists():
        return v2_path
    return v3_path  # Will fail at query time with clear error


def _is_v3(parquet_path) -> bool:
    return "parquet-v3" in str(parquet_path)


def build_data_query(matrix_code: str, dimensions: list, filters: dict,
                     limit: int = MAX_DATA_ROWS) -> str:
    """Build a DuckDB query against a parquet file.

    Parquet-v3 columns contain human-readable string values (SDMX format).
    Filters may contain integer nom_item_ids (from frontend) which are
    transparently translated to sdmx_value strings for v3 queries.

    Args:
        matrix_code: Dataset identifier
        dimensions: List of dimension dicts with dim_column_name
        filters: Column name → list of values (nomItemIds or strings)
        limit: Max rows to return

    Returns:
        SQL query string
    """
    parquet_path = _resolve_parquet_path(matrix_code)
    is_v3 = _is_v3(parquet_path)

    # Use OBS_VALUE for v3 parquets, value for legacy v2
    value_col = "OBS_VALUE" if is_v3 else "value"
    cols = [d['dim_column_name'] for d in dimensions] + [value_col]
    select_clause = ", ".join(f'"{c}"' for c in cols)

    where_parts = []
    valid_cols = {d['dim_column_name'] for d in dimensions}

    # For v3: translate nomItemId filter values → sdmx_value strings
    id_to_sdmx = _get_id_to_sdmx() if is_v3 else {}

    for col_name, values in filters.items():
        if col_name not in valid_cols:
            continue
        if not values:
            continue

        safe_values = []
        for v in values:
            if _is_int(v):
                int_v = int(v)
                if is_v3 and int_v in id_to_sdmx:
                    # Translate nomItemId → sdmx_value for v3
                    safe_values.append(id_to_sdmx[int_v])
                else:
                    safe_values.append(str(int_v))
            elif isinstance(v, str):
                safe_values.append(v)

        if not safe_values:
            continue

        # Build IN clause — cast to VARCHAR for consistent matching
        placeholders = ", ".join(f"'{_escape_sql(str(v))}'" for v in safe_values)
        where_parts.append(f'CAST("{col_name}" AS VARCHAR) IN ({placeholders})')

    where_sql = f"WHERE {' AND '.join(where_parts)}" if where_parts else ""

    return f"""
        SELECT {select_clause}
        FROM read_parquet('{parquet_path}')
        {where_sql}
        LIMIT {int(limit)}
    """


def _is_int(v) -> bool:
    """Check if value can be safely cast to int."""
    try:
        int(v)
        return True
    except (ValueError, TypeError):
        return False


def _escape_sql(s: str) -> str:
    """Escape single quotes in SQL string literals."""
    return s.replace("'", "''")
