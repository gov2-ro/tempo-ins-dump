"""Dataset data querying endpoint — powers all charts."""
import json
from fastapi import APIRouter, Query, HTTPException
from app.db import get_conn
from app.config import MAX_DATA_ROWS, LARGE_DATASET_THRESHOLD

from app.services.query_builder import build_data_query

router = APIRouter()


@router.get("/datasets/{matrix_code}/data")
def get_dataset_data(
    matrix_code: str,
    filters: str = Query("{}", description="JSON: {column_name: [value, ...]}"),
    limit: int = Query(MAX_DATA_ROWS, le=MAX_DATA_ROWS),
):
    """Query dataset parquet with dimension filters.

    Returns compact format: rows as value arrays + column_labels dict.
    Parquet-v3 values are human-readable strings (SDMX format).
    """
    conn = get_conn()

    # Parse filters
    try:
        filter_dict = json.loads(filters)
    except json.JSONDecodeError:
        raise HTTPException(400, "Invalid filters JSON")

    # Get matrix info
    matrix = conn.execute(
        "SELECT row_count FROM matrices WHERE matrix_code = ?", [matrix_code]
    ).fetchone()
    if not matrix:
        raise HTTPException(404, f"Dataset {matrix_code} not found")

    row_count = matrix[0] or 0

    # Require filters for large datasets
    if row_count > LARGE_DATASET_THRESHOLD and not filter_dict:
        raise HTTPException(
            400,
            f"Dataset has {row_count:,} rows. Please apply at least one filter "
            f"to narrow results (max {MAX_DATA_ROWS:,} rows returned)."
        )

    # Get dimensions for this matrix
    dims = conn.execute("""
        SELECT dim_code, dim_label, dim_column_name
        FROM dimensions
        WHERE matrix_code = ?
        ORDER BY dim_code
    """, [matrix_code]).fetchall()

    dimensions = [
        {'dim_code': d[0], 'dim_label': d[1], 'dim_column_name': d[2]}
        for d in dims
    ]

    # Build and execute query
    sql = build_data_query(matrix_code, dimensions, filter_dict, limit + 1)

    try:
        result = conn.execute(sql).fetchall()
    except Exception as e:
        raise HTTPException(500, f"Query error: {e}")

    truncated = len(result) > limit
    rows = result[:limit]

    # Build column_labels: map data values to display labels.
    # Detect v3 (SDMX) vs v2 (nomItemId) by checking if values are strings.
    column_labels = {}
    for i, dim in enumerate(dimensions):
        col = dim['dim_column_name']
        values = set()
        for row in rows:
            if row[i] is not None:
                values.add(row[i])

        if not values:
            continue

        # Check if values are strings (v3 SDMX) or integers (v2 nomItemIds)
        has_string_values = any(isinstance(v, str) for v in values)

        if has_string_values:
            # v3: values are human-readable labels — identity mapping
            column_labels[col] = {str(v): str(v) for v in values}
        else:
            # v2 fallback: values are integer nomItemIds — resolve via DB
            int_values = [int(v) for v in values if v is not None]
            if int_values:
                id_list = ",".join(str(x) for x in int_values)
                labels = conn.execute(f"""
                    SELECT nom_item_id, option_label
                    FROM dimension_options
                    WHERE nom_item_id IN ({id_list})
                """).fetchall()
                column_labels[col] = {str(nom_id): label for nom_id, label in labels}

    # Format column names
    columns = [d['dim_column_name'] for d in dimensions] + ['OBS_VALUE']

    # Convert rows to plain lists
    data_rows = [list(r) for r in rows]

    return {
        'columns': columns,
        'column_labels': column_labels,
        'rows': data_rows,
        'total_rows': row_count,
        'returned_rows': len(data_rows),
        'truncated': truncated,
    }
