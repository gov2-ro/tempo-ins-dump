"""Dynamic SQL builder for parquet queries with filter pushdown."""
from app.config import PARQUET_DIR, MAX_DATA_ROWS

# Unit types whose values are levels/shares, not additive quantities —
# grouped queries must AVG them. SUMming percentages, base-100 indices or
# rates across a dimension produces meaningless numbers. Single source of
# truth for dataset_data.py, insights.py and agent.py.
AVG_UNIT_TYPES = {'percentage', 'time_unit', 'index', 'rate', 'ratio'}


def _resolve_parquet_path(matrix_code: str):
    """Find the v3 parquet file for a matrix code."""
    return PARQUET_DIR / f"{matrix_code}.parquet"


def build_data_query(matrix_code: str, dimensions: list, filters: dict,
                     limit: int = MAX_DATA_ROWS,
                     group_by: list[str] | None = None,
                     agg_func: str = "SUM",
                     value_column: str = "OBS_VALUE",
                     time_column: str | None = "TIME_PERIOD") -> str:
    """Build a DuckDB query against a parquet file for this matrix.

    Most parquets are SDMX-canonical (OBS_VALUE + string dim values), but
    a small set (~67 of 3,706 as of 2026-05) still use the legacy v2 schema
    with `value` as the value column and `*_nom_id` dim names. The caller
    passes value_column accordingly; dim_column_name in `dimensions` must
    match the parquet's actual column names.

    Args:
        matrix_code: Dataset identifier
        dimensions: List of dimension dicts with dim_column_name (must
                    match the parquet's actual column names)
        filters: Column name → list of string values
        limit: Max rows to return
        group_by: If provided, SELECT only these dims + agg(value),
                  GROUP BY these dims. Dramatically reduces rows for chart
                  queries. Filters still apply to all dimensions.
        agg_func: Aggregation function for group_by mode (SUM, AVG, ...)
        value_column: Name of the parquet's value column. Defaults to
                      OBS_VALUE; pass "value" for legacy parquets.
        time_column: Name of the parquet's time column, used to order the
                     result newest-first before truncation. Legacy parquets
                     carry a *_nom_id here. Pass None when the dataset has no
                     column whose ordering means anything chronologically —
                     the result is then left in whatever order the scan
                     produced, as it was before.

    Returns:
        SQL query string. The output value column is always aliased to
        OBS_VALUE for downstream consistency.
    """
    parquet_path = _resolve_parquet_path(matrix_code)
    vc = value_column

    all_dim_cols = [d['dim_column_name'] for d in dimensions]
    valid_cols = set(all_dim_cols)

    if group_by:
        # Only keep requested columns that actually exist in this dataset
        keep_cols = [c for c in group_by if c in valid_cols]
        if not keep_cols:
            keep_cols = all_dim_cols  # fallback to all
        dim_select = ", ".join(f'"{c}"' for c in keep_cols)
        select_clause = f'{dim_select}, {agg_func}("{vc}") AS "OBS_VALUE"'
        group_clause = f'GROUP BY {dim_select}'
        output_cols = keep_cols
    else:
        dim_select = ", ".join(f'"{c}"' for c in all_dim_cols)
        # Alias to OBS_VALUE so the response shape is uniform regardless
        # of the parquet's underlying value-column name.
        select_clause = f'{dim_select}, "{vc}" AS "OBS_VALUE"' if vc != "OBS_VALUE" else f'{dim_select}, "OBS_VALUE"'
        group_clause = ""
        output_cols = all_dim_cols

    where_parts = []
    if group_by:
        # Some parquets carry NULL dim values (unmapped SDMX codes); grouping
        # them produces a meaningless summed "null" bucket in charts.
        where_parts = [f'"{c}" IS NOT NULL' for c in keep_cols]
    for col_name, values in filters.items():
        if col_name not in valid_cols or not values:
            continue

        safe_values = [str(v) for v in values if v is not None]
        if not safe_values:
            continue

        placeholders = ", ".join(f"'{_escape_sql(v)}'" for v in safe_values)
        where_parts.append(f'CAST("{col_name}" AS VARCHAR) IN ({placeholders})')

    where_sql = f"WHERE {' AND '.join(where_parts)}" if where_parts else ""

    body = f"""
        SELECT {select_clause}
        FROM read_parquet('{parquet_path}')
        {where_sql}
        {group_clause}
    """

    if not time_column or time_column not in output_cols:
        return f"{body} LIMIT {int(limit)}"

    # Ordering ASC and then LIMITing throws away the NEWEST periods whenever
    # truncation fires — the exact opposite of what a first overview needs.
    # Take the newest rows, then restore ascending order for the client.
    # The caller is expected to discard the oldest period in a truncated
    # result: that one is cut mid-period and would understate itself.
    return f"""
        SELECT * FROM (
            {body}
            ORDER BY "{time_column}" DESC
            LIMIT {int(limit)}
        )
        ORDER BY "{time_column}" ASC
    """


# ---------------------------------------------------------------------------
# Legacy-parquet adaptation
#
# 188 of 3,863 parquets (2026-09) still carry the v2 schema: `value` instead of
# `OBS_VALUE`, and `*_nom_id` dimension names instead of SDMX ones. Callers
# speak SDMX; the file may not. Every consumer used to carry its own copy of
# the translation — dataset_data.py, dataset_meta.py and agent.py each had one,
# and insights.py had none, which is why all 188 of those datasets showed a
# single KPI and an empty "Pe scurt". One implementation, here.
# ---------------------------------------------------------------------------

def resolve_parquet_schema(conn, matrix_code: str) -> dict:
    """How to address this matrix's parquet.

    Returns is_legacy / value_column / columns plus two name maps:
      to_file — SDMX name  -> the column name the file actually uses
      to_sdmx — file column -> SDMX name, for translating results back

    Both maps are empty for an already-canonical file, so callers can apply
    them unconditionally.
    """
    path = _resolve_parquet_path(matrix_code)
    try:
        cols = [r[0] for r in conn.execute(
            f"DESCRIBE SELECT * FROM read_parquet('{path}') LIMIT 0").fetchall()]
    except Exception:
        return {"is_legacy": False, "value_column": "OBS_VALUE", "columns": [],
                "to_file": {}, "to_sdmx": {}}

    if "OBS_VALUE" in cols:
        is_legacy, value_column = False, "OBS_VALUE"
    elif "value" in cols and any(c.endswith("_nom_id") for c in cols):
        is_legacy, value_column = True, "value"
    else:
        # Unknown convention — assume canonical, as the old code did.
        is_legacy, value_column = False, "OBS_VALUE"

    # sdmx_column_map is keyed by the parent for split children.
    parent = conn.execute(
        "SELECT parent_matrix_code FROM matrices WHERE matrix_code = ?",
        [matrix_code]).fetchone()
    lookup = (parent[0] or matrix_code) if parent else matrix_code
    pairs = conn.execute(
        "SELECT sdmx_column_name, old_column_name FROM sdmx_column_map "
        "WHERE matrix_code = ?", [lookup]).fetchall()

    if is_legacy:
        to_file = {sdmx: old for sdmx, old in pairs}
        to_sdmx = {old: sdmx for sdmx, old in pairs}
    else:
        # File is canonical; only the *recorded* dim names may be stale.
        to_file = {old: sdmx for sdmx, old in pairs}
        to_sdmx = {}

    return {"is_legacy": is_legacy, "value_column": value_column,
            "columns": cols, "to_file": to_file, "to_sdmx": to_sdmx}


def adapt_to_parquet(schema: dict, dimensions: list,
                     group_by: list | None = None,
                     filters: dict | None = None) -> tuple:
    """Rewrite dimension names, group_by and filter keys onto the file.

    `dimensions` is copied, not mutated — several callers reuse the list they
    pass in for labelling the response, which must stay in SDMX terms.
    Returns (dimensions, group_by, filters).
    """
    to_file = schema.get("to_file") or {}
    legacy = schema.get("is_legacy")

    def _rename(col: str) -> str:
        if legacy:
            # Anything not already a file column gets translated if we can.
            return col if col.endswith("_nom_id") else to_file.get(col, col)
        return to_file.get(col, col) if col.endswith("_nom_id") else col

    dims = [{**d, "dim_column_name": _rename(d["dim_column_name"])}
            for d in dimensions]
    gb = [_rename(c) for c in group_by] if group_by else group_by
    flt = {_rename(k): v for k, v in (filters or {}).items()} if filters is not None else filters
    return dims, gb, flt


def _escape_sql(s: str) -> str:
    """Escape single quotes in SQL string literals."""
    return s.replace("'", "''")
