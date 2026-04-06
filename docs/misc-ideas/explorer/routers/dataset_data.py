"""Dataset data querying endpoint."""
import json
from fastapi import APIRouter, Query, HTTPException
from explorer.db import get_conn
from explorer.config import MAX_DATA_ROWS, LARGE_DATASET_THRESHOLD
from explorer.services.query_builder import build_data_query

router = APIRouter()


@router.get("/datasets/{matrix_code}/data")
def get_dataset_data(
    matrix_code: str,
    filters: str = Query("{}", description="JSON: {column_name: [nom_item_id, ...]}"),
    limit: int = Query(MAX_DATA_ROWS, le=MAX_DATA_ROWS),
):
    conn = get_conn()

    try:
        filter_dict = json.loads(filters)
    except json.JSONDecodeError:
        raise HTTPException(400, "Invalid filters JSON")

    matrix = conn.execute(
        "SELECT row_count FROM matrices WHERE matrix_code = ?", [matrix_code]
    ).fetchone()
    if not matrix:
        raise HTTPException(404, f"Dataset {matrix_code} not found")

    row_count = matrix[0] or 0
    if row_count > LARGE_DATASET_THRESHOLD and not filter_dict:
        raise HTTPException(
            400,
            f"Dataset has {row_count:,} rows. Apply at least one filter (max {MAX_DATA_ROWS:,})."
        )

    dims = conn.execute("""
        SELECT dim_code, dim_label, dim_column_name
        FROM dimensions WHERE matrix_code = ? ORDER BY dim_code
    """, [matrix_code]).fetchall()

    dimensions = [
        {'dim_code': d[0], 'dim_label': d[1], 'dim_column_name': d[2]}
        for d in dims
    ]

    sql = build_data_query(matrix_code, dimensions, filter_dict, limit + 1)

    try:
        result = conn.execute(sql).fetchall()
    except Exception as e:
        raise HTTPException(500, f"Query error: {e}")

    truncated = len(result) > limit
    rows = result[:limit]

    # Build column_labels
    column_labels = {}
    for i, dim in enumerate(dimensions):
        col = dim['dim_column_name']
        ids = set()
        for row in rows:
            if row[i] is not None:
                ids.add(int(row[i]))
        if ids:
            id_list = ",".join(str(x) for x in ids)
            labels = conn.execute(f"""
                SELECT nom_item_id, option_label
                FROM dimension_options WHERE nom_item_id IN ({id_list})
            """).fetchall()
            column_labels[col] = {str(nom_id): label for nom_id, label in labels}

    columns = [d['dim_column_name'] for d in dimensions] + ['value']

    return {
        'columns': columns,
        'column_labels': column_labels,
        'rows': [list(r) for r in rows],
        'total_rows': row_count,
        'returned_rows': len(rows),
        'truncated': truncated,
    }
