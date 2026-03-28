"""Dynamic SQL builder for parquet queries with filter pushdown."""
from app.config import PARQUET_DIR, MAX_DATA_ROWS


def _resolve_parquet_path(matrix_code: str):
    """Find the v3 parquet file for a matrix code."""
    return PARQUET_DIR / f"{matrix_code}.parquet"


def build_data_query(matrix_code: str, dimensions: list, filters: dict,
                     limit: int = MAX_DATA_ROWS,
                     group_by: list[str] | None = None,
                     agg_func: str = "SUM") -> str:
    """Build a DuckDB query against a v3 SDMX parquet file.

    All parquets use OBS_VALUE column and string dimension values.

    Args:
        matrix_code: Dataset identifier
        dimensions: List of dimension dicts with dim_column_name
        filters: Column name → list of string values
        limit: Max rows to return
        group_by: If provided, SELECT only these dims + SUM(OBS_VALUE),
                  GROUP BY these dims. Dramatically reduces rows for chart
                  queries (e.g. 101k → 110 for a time×gender chart).
                  Filters still apply to all dimensions.

    Returns:
        SQL query string
    """
    parquet_path = _resolve_parquet_path(matrix_code)

    all_dim_cols = [d['dim_column_name'] for d in dimensions]
    valid_cols = set(all_dim_cols)

    if group_by:
        # Only keep requested columns that actually exist in this dataset
        keep_cols = [c for c in group_by if c in valid_cols]
        if not keep_cols:
            keep_cols = all_dim_cols  # fallback to all
        dim_select = ", ".join(f'"{c}"' for c in keep_cols)
        select_clause = f'{dim_select}, {agg_func}("OBS_VALUE") AS "OBS_VALUE"'
        group_clause = f'GROUP BY {dim_select}'
        output_cols = keep_cols
    else:
        dim_select = ", ".join(f'"{c}"' for c in all_dim_cols)
        select_clause = f'{dim_select}, "OBS_VALUE"'
        group_clause = ""
        output_cols = all_dim_cols

    where_parts = []
    for col_name, values in filters.items():
        if col_name not in valid_cols or not values:
            continue

        safe_values = [str(v) for v in values if v is not None]
        if not safe_values:
            continue

        placeholders = ", ".join(f"'{_escape_sql(v)}'" for v in safe_values)
        where_parts.append(f'CAST("{col_name}" AS VARCHAR) IN ({placeholders})')

    where_sql = f"WHERE {' AND '.join(where_parts)}" if where_parts else ""

    order_clause = 'ORDER BY "TIME_PERIOD" ASC' if "TIME_PERIOD" in output_cols else ""

    return f"""
        SELECT {select_clause}
        FROM read_parquet('{parquet_path}')
        {where_sql}
        {group_clause}
        {order_clause}
        LIMIT {int(limit)}
    """


def _escape_sql(s: str) -> str:
    """Escape single quotes in SQL string literals."""
    return s.replace("'", "''")
