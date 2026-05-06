"""Dataset data querying endpoint — powers all charts."""
import csv
import io
import json
from fastapi import APIRouter, Query, HTTPException
from fastapi.responses import Response
from app.db import get_conn
from app.config import MAX_DATA_ROWS, LARGE_DATASET_THRESHOLD

from app.services.query_builder import build_data_query

router = APIRouter()


@router.get("/datasets/{matrix_code}/data")
def get_dataset_data(
    matrix_code: str,
    filters: str = Query("{}", description="JSON: {column_name: [value, ...]}"),
    limit: int = Query(MAX_DATA_ROWS, le=MAX_DATA_ROWS),
    group_by: str = Query("", description="JSON array of dim columns to GROUP BY, e.g. [\"TIME_PERIOD\",\"SEX\"]. "
                          "Other dims are summed. Empty = no aggregation (raw rows)."),
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

    # Parse group_by early (needed for large dataset check)
    group_by_cols = None
    if group_by:
        try:
            group_by_cols = json.loads(group_by)
            if not isinstance(group_by_cols, list):
                group_by_cols = None
        except json.JSONDecodeError:
            pass

    # Require filters for large datasets — skip when GROUP BY aggregates
    if row_count > LARGE_DATASET_THRESHOLD and not filter_dict and not group_by_cols:
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

    # Resolve legacy v2 _nom_id column names to SDMX names for split sub-datasets
    if any(d['dim_column_name'].endswith('_nom_id') for d in dimensions):
        parent_row = conn.execute(
            "SELECT parent_matrix_code FROM matrices WHERE matrix_code = ?", [matrix_code]
        ).fetchone()
        lookup_code = (parent_row[0] or matrix_code) if parent_row else matrix_code
        col_map = dict(conn.execute("""
            SELECT old_column_name, sdmx_column_name
            FROM sdmx_column_map WHERE matrix_code = ?
        """, [lookup_code]).fetchall())
        for d in dimensions:
            if d['dim_column_name'].endswith('_nom_id'):
                d['dim_column_name'] = col_map.get(d['dim_column_name'], d['dim_column_name'])

    # Auto time-window when projected result would exceed MAX_DATA_ROWS and
    # the user hasn't already constrained time. Skip when group_by is set —
    # that already aggregates row count down. Threshold matches the row cap
    # so we limit periods *before* the result gets silently truncated; the
    # frontend can still page through earlier periods via the period browser.
    TIME_WINDOW_THRESHOLD = MAX_DATA_ROWS
    time_windowed = False
    if row_count > TIME_WINDOW_THRESHOLD and not group_by_cols:
        time_dim = next((d['dim_column_name'] for d in dimensions
                         if d['dim_column_name'] == 'TIME_PERIOD'), None)
        if time_dim and time_dim not in filter_dict:
            # Try parquet scan first (fast for moderate files), fall back to metadata
            from app.config import PARQUET_DIR
            parquet_path = PARQUET_DIR / f"{matrix_code}.parquet"
            time_vals = []
            try:
                time_vals = [r[0] for r in conn.execute(f"""
                    SELECT DISTINCT "TIME_PERIOD"
                    FROM read_parquet('{parquet_path}')
                    ORDER BY "TIME_PERIOD" DESC
                """).fetchall()]
            except Exception:
                pass
            # Fallback: generate year strings from metadata year range
            if not time_vals:
                yr_row = conn.execute(
                    "SELECT time_year_min, time_year_max FROM matrix_profiles WHERE matrix_code = ?",
                    [matrix_code]
                ).fetchone()
                if yr_row and yr_row[0] and yr_row[1]:
                    time_vals = [str(y) for y in range(yr_row[1], yr_row[0] - 1, -1)]
            if time_vals:
                n_periods = len(time_vals)
                rows_per_period = row_count / max(n_periods, 1)
                # For extremely large datasets, allow a smaller minimum to avoid OOM
                min_periods = 2 if row_count > 5_000_000 else 5
                safe_periods = max(min_periods, int(MAX_DATA_ROWS / max(rows_per_period, 1)))
                safe_periods = min(safe_periods, n_periods)
                if safe_periods < n_periods:
                    filter_dict[time_dim] = time_vals[:safe_periods]
                    time_windowed = True

    # Determine aggregation function based on unit type
    agg_func = "SUM"
    if group_by_cols:
        unit_row = conn.execute(
            "SELECT primary_unit_type FROM matrix_profiles WHERE matrix_code = ?",
            [matrix_code]
        ).fetchone()
        if unit_row and unit_row[0] in ('percentage', 'time_unit'):
            agg_func = "AVG"

    # Build and execute query
    sql = build_data_query(matrix_code, dimensions, filter_dict, limit + 1,
                           group_by=group_by_cols, agg_func=agg_func)

    try:
        result = conn.execute(sql).fetchall()
    except Exception as e:
        raise HTTPException(500, f"Query error: {e}")

    truncated = len(result) > limit
    rows = result[:limit]

    # Determine which dimension columns are in the result
    if group_by_cols:
        # Order must match SQL output: group_by order, filtered to valid cols
        dim_by_col = {d['dim_column_name']: d for d in dimensions}
        result_dims = [dim_by_col[c] for c in group_by_cols if c in dim_by_col]
        if not result_dims:
            result_dims = dimensions  # fallback
    else:
        result_dims = dimensions

    # Build column_labels: map data values to display labels.
    column_labels = {}
    for i, dim in enumerate(result_dims):
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
    columns = [d['dim_column_name'] for d in result_dims] + ['OBS_VALUE']

    # Convert rows to plain lists
    data_rows = [list(r) for r in rows]

    resp = {
        'columns': columns,
        'column_labels': column_labels,
        'rows': data_rows,
        'total_rows': row_count,
        'returned_rows': len(data_rows),
        'truncated': truncated,
    }
    if time_windowed:
        resp['time_windowed'] = True
    return resp


@router.get("/datasets/{matrix_code}/download")
def download_dataset(
    matrix_code: str,
    format: str = Query("csv", pattern="^(csv|xlsx)$"),
    filters: str = Query("{}", description="JSON: {column_name: [value, ...]}"),
    lang: str = Query("ro", pattern="^(ro|en)$"),
):
    """Download dataset as CSV or XLSX, respecting active filters and language."""
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

    dims = conn.execute("""
        SELECT dim_code, dim_label, dim_column_name
        FROM dimensions WHERE matrix_code = ? ORDER BY dim_code
    """, [matrix_code]).fetchall()

    dimensions = [{'dim_code': d[0], 'dim_label': d[1], 'dim_column_name': d[2]} for d in dims]

    # Resolve legacy v2 column names (same as /data endpoint)
    if any(d['dim_column_name'].endswith('_nom_id') for d in dimensions):
        parent_row = conn.execute(
            "SELECT parent_matrix_code FROM matrices WHERE matrix_code = ?", [matrix_code]
        ).fetchone()
        lookup_code = (parent_row[0] or matrix_code) if parent_row else matrix_code
        col_map = dict(conn.execute("""
            SELECT old_column_name, sdmx_column_name
            FROM sdmx_column_map WHERE matrix_code = ?
        """, [lookup_code]).fetchall())
        for d in dimensions:
            if d['dim_column_name'].endswith('_nom_id'):
                d['dim_column_name'] = col_map.get(d['dim_column_name'], d['dim_column_name'])

    sql = build_data_query(matrix_code, dimensions, filter_dict, MAX_DATA_ROWS)

    try:
        rows = conn.execute(sql).fetchall()
    except Exception as e:
        raise HTTPException(500, f"Query error: {e}")

    col_names = [d['dim_column_name'] for d in dimensions] + ['OBS_VALUE']

    # Build EN translation maps if requested
    value_maps: dict = {}
    if lang == "en":
        for d in dimensions:
            col = d['dim_column_name']
            mapping = conn.execute("""
                SELECT dopt.option_label, COALESCE(sc.display_label_en, dopt.option_label)
                FROM dimension_options dopt
                JOIN dimensions dim ON dim.dimension_id = dopt.dimension_id
                LEFT JOIN sdmx_codes sc ON sc.nom_item_id = dopt.nom_item_id
                WHERE dim.matrix_code = ? AND dim.dim_column_name = ?
            """, [matrix_code, col]).fetchall()
            if mapping:
                value_maps[col] = {ro: en for ro, en in mapping}

    def _translate(row):
        if not value_maps:
            return row
        translated = []
        for i, v in enumerate(row[:-1]):
            col = col_names[i]
            if v is not None and col in value_maps:
                translated.append(value_maps[col].get(str(v), v))
            else:
                translated.append(v)
        translated.append(row[-1])
        return translated

    if format == "csv":
        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow(col_names)
        for row in rows:
            writer.writerow(_translate(row))
        return Response(
            buf.getvalue(),
            media_type="text/csv; charset=utf-8",
            headers={"Content-Disposition": f"attachment; filename={matrix_code}.csv"},
        )
    else:
        from openpyxl import Workbook
        wb = Workbook()
        ws = wb.active
        ws.title = matrix_code
        ws.append(col_names)
        for row in rows:
            ws.append([v if v is not None else "" for v in _translate(row)])
        buf = io.BytesIO()
        wb.save(buf)
        buf.seek(0)
        return Response(
            buf.read(),
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": f"attachment; filename={matrix_code}.xlsx"},
        )
