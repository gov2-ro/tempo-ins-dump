"""Dynamic SQL builder for parquet queries with filter pushdown."""
from app.config import PARQUET_DIR, MAX_DATA_ROWS


def _resolve_parquet_path(matrix_code: str):
    """Find the v3 parquet file for a matrix code."""
    return PARQUET_DIR / f"{matrix_code}.parquet"


def build_data_query(matrix_code: str, dimensions: list, filters: dict,
                     limit: int = MAX_DATA_ROWS) -> str:
    """Build a DuckDB query against a v3 SDMX parquet file.

    All parquets use OBS_VALUE column and string dimension values.

    Args:
        matrix_code: Dataset identifier
        dimensions: List of dimension dicts with dim_column_name
        filters: Column name → list of string values
        limit: Max rows to return

    Returns:
        SQL query string
    """
    parquet_path = _resolve_parquet_path(matrix_code)

    cols = [d['dim_column_name'] for d in dimensions] + ["OBS_VALUE"]
    select_clause = ", ".join(f'"{c}"' for c in cols)

    where_parts = []
    valid_cols = {d['dim_column_name'] for d in dimensions}

    for col_name, values in filters.items():
        if col_name not in valid_cols or not values:
            continue

        safe_values = [str(v) for v in values if v is not None]
        if not safe_values:
            continue

        placeholders = ", ".join(f"'{_escape_sql(v)}'" for v in safe_values)
        where_parts.append(f'CAST("{col_name}" AS VARCHAR) IN ({placeholders})')

    where_sql = f"WHERE {' AND '.join(where_parts)}" if where_parts else ""

    col_names = {d['dim_column_name'] for d in dimensions}
    order_clause = 'ORDER BY "TIME_PERIOD" ASC' if "TIME_PERIOD" in col_names else ""

    return f"""
        SELECT {select_clause}
        FROM read_parquet('{parquet_path}')
        {where_sql}
        {order_clause}
        LIMIT {int(limit)}
    """


def _escape_sql(s: str) -> str:
    """Escape single quotes in SQL string literals."""
    return s.replace("'", "''")
