"""Dynamic SQL builder for parquet queries with filter pushdown."""
from explorer.config import PARQUET_DIR, MAX_DATA_ROWS


def build_data_query(matrix_code: str, dimensions: list, filters: dict,
                     limit: int = MAX_DATA_ROWS) -> str:
    parquet_path = PARQUET_DIR / f"{matrix_code}.parquet"
    cols = [d['dim_column_name'] for d in dimensions] + ['value']
    select_clause = ", ".join(cols)

    where_parts = []
    for col_name, ids in filters.items():
        valid_cols = {d['dim_column_name'] for d in dimensions}
        if col_name not in valid_cols:
            continue
        safe_ids = [str(int(i)) for i in ids if _is_int(i)]
        if safe_ids:
            where_parts.append(f'"{col_name}" IN ({", ".join(safe_ids)})')

    where_sql = f"WHERE {' AND '.join(where_parts)}" if where_parts else ""

    return f"""
        SELECT {select_clause}
        FROM read_parquet('{parquet_path}')
        {where_sql}
        LIMIT {int(limit)}
    """


def _is_int(v) -> bool:
    try:
        int(v)
        return True
    except (ValueError, TypeError):
        return False
