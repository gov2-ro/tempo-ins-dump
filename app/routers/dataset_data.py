"""Dataset data querying endpoint — powers all charts."""
import csv
import io
import json
import re
from fastapi import APIRouter, Query, HTTPException
from fastapi.responses import Response
from app.db import get_conn
from app.config import MAX_DATA_ROWS, LARGE_DATASET_THRESHOLD, PARQUET_DIR

from app.services.query_builder import build_data_query, AVG_UNIT_TYPES

router = APIRouter()


@router.get("/datasets/{matrix_code}/insights")
def get_dataset_insights(
    matrix_code: str,
    lang: str = Query("ro", pattern="^(ro|en)$"),
):
    """KPI headline values + template-based insight sentences (cached)."""
    from app.services.insights import compute_insights
    result = compute_insights(matrix_code, lang=lang)
    if result is None:
        raise HTTPException(404, f"Dataset {matrix_code} not found")
    return result


_POP_REFERENCE_CACHE: dict = {}
_POP_REFERENCE_FILES = {
    "county": "POP105A_judete_grupe",
    "region": "POP105A_regiuni_grupe",
    "macroregion": "POP105A_macroregiuni_grupe",
}


@router.get("/reference/population")
def get_population_reference(level: str = Query("county", pattern="^(county|region|macroregion)$")):
    """Resident population per geo area per year — reference matrix for
    per-capita normalization (clients divide count values by pop/1000).

    Source: POP105A_* parquets — flat age partition with no Total rows, so
    SUM over all dims per (REF_AREA, TIME_PERIOD) is the true population.
    Cached in-process; the underlying data changes once a year.
    """
    if level in _POP_REFERENCE_CACHE:
        return _POP_REFERENCE_CACHE[level]
    path = PARQUET_DIR / f"{_POP_REFERENCE_FILES[level]}.parquet"
    if not path.exists():
        raise HTTPException(404, "Population reference unavailable")
    conn = get_conn()
    rows = conn.execute(
        'SELECT "REF_AREA", "TIME_PERIOD", SUM("OBS_VALUE") '
        "FROM read_parquet(?) GROUP BY 1, 2", [str(path)]
    ).fetchall()
    pop: dict = {}
    for area, period, v in rows:
        if area is None or period is None or v is None:
            continue
        pop.setdefault(str(area).strip(), {})[str(period)] = v
    _POP_REFERENCE_CACHE[level] = {"level": level, "population": pop}
    return _POP_REFERENCE_CACHE[level]


def _detect_parquet_schema(conn, matrix_code: str) -> dict:
    """Peek at the parquet file to determine its column convention.

    Returns: {is_legacy: bool, value_column: str, columns: list[str]}.
    Most parquets are SDMX (OBS_VALUE + REF_AREA / TIME_PERIOD / ...);
    ~67 still use legacy v2 schema (value + *_nom_id columns).
    """
    parquet_path = PARQUET_DIR / f"{matrix_code}.parquet"
    try:
        cols = [r[0] for r in conn.execute(
            f"DESCRIBE SELECT * FROM read_parquet('{parquet_path}') LIMIT 0"
        ).fetchall()]
    except Exception:
        return {"is_legacy": False, "value_column": "OBS_VALUE", "columns": []}

    if "OBS_VALUE" in cols:
        return {"is_legacy": False, "value_column": "OBS_VALUE", "columns": cols}
    if "value" in cols and any(c.endswith("_nom_id") for c in cols):
        return {"is_legacy": True, "value_column": "value", "columns": cols}
    # Unknown convention — fall back to OBS_VALUE assumption
    return {"is_legacy": False, "value_column": "OBS_VALUE", "columns": cols}


# Legacy period labels that sort chronologically as plain strings. Annual
# labels do ("Anul 1990" < "Anul 2024"); month names do not ("Aprilie" sorts
# before "Ianuarie"), so those datasets keep the old unordered behaviour
# rather than being given a confident but wrong idea of "newest".
_ANNUAL_LABEL_RE = re.compile(r"^\s*Anul\s+\d{4}\s*$")


def _resolve_time_column(conn, dimensions, schema, legacy_to_sdmx,
                         matrix_code: str) -> str | None:
    """The parquet column holding time, or None if there isn't a usable one.

    SDMX parquets name it TIME_PERIOD. The 67 legacy ones carry a *_nom_id
    whose SDMX counterpart is TIME_PERIOD, and store label strings rather
    than dates — usable only while those labels sort chronologically.
    """
    cols = {d['dim_column_name'] for d in dimensions}
    if 'TIME_PERIOD' in cols:
        return 'TIME_PERIOD'
    legacy = next((c for c in cols
                   if legacy_to_sdmx.get(c) == 'TIME_PERIOD'), None)
    if not legacy:
        return None
    path = PARQUET_DIR / f"{matrix_code}.parquet"
    try:
        vals = [r[0] for r in conn.execute(
            f'SELECT DISTINCT "{legacy}" FROM read_parquet(\'{path}\') LIMIT 500'
        ).fetchall()]
    except Exception:
        return None
    if vals and all(_ANNUAL_LABEL_RE.match(str(v or '')) for v in vals):
        return legacy
    return None


def _rows_per_period(dimensions, group_by_cols, filter_dict, time_dim,
                     row_count: int, n_periods: int) -> float:
    """How many result rows one time period is expected to contribute.

    Ungrouped, that is just the parquet's rows spread over its periods.
    Grouped, the result is one row per surviving combination of the grouped
    dimensions, so the estimate is the product of their cardinalities — a
    filtered dimension contributes only the values the caller asked for.

    Cardinalities come from `dimensions.option_count`, which is metadata and
    therefore an upper bound: it counts every option the dataset declares,
    including combinations that never occur in the data. Over-estimating is
    the safe direction here — it windows a period or two more than strictly
    needed rather than letting the query blow past the cap.
    """
    if not group_by_cols:
        return row_count / max(n_periods, 1)

    # A handful of datasets (INT109C) declare several dimensions under the
    # same column name; take the widest, which is the bound that matters.
    declared: dict[str, int] = {}
    for d in dimensions:
        col = d['dim_column_name']
        declared[col] = max(declared.get(col, 1), d.get('option_count') or 1)

    cells = 1
    for col in group_by_cols:
        if col == time_dim:
            continue
        picked = filter_dict.get(col)
        n = len(picked) if picked else declared.get(col, 1)
        cells *= max(n, 1)
    return float(cells)


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

    if not (PARQUET_DIR / f"{matrix_code}.parquet").exists():
        # Split parents keep a `matrices` row but publish data only through
        # their children. A large one used to be masked by the row-count gate
        # and a small one leaked an absolute server path in a 500.
        raise HTTPException(
            404, f"Dataset {matrix_code} has no data file — it may be "
                 f"published as sub-datasets."
        )

    # Parse group_by early (needed for large dataset check)
    group_by_cols = None
    if group_by:
        try:
            group_by_cols = json.loads(group_by)
            if not isinstance(group_by_cols, list):
                group_by_cols = None
        except json.JSONDecodeError:
            pass

    # Get dimensions for this matrix
    dims = conn.execute("""
        SELECT dim_code, dim_label, dim_column_name, option_count
        FROM dimensions
        WHERE matrix_code = ?
        ORDER BY dim_code
    """, [matrix_code]).fetchall()

    dimensions = [
        {'dim_code': d[0], 'dim_label': d[1], 'dim_column_name': d[2],
         'option_count': d[3] or 1}
        for d in dims
    ]

    # Reconcile dim_column_name with the parquet's actual column names.
    # The dim_column_name recorded in `dimensions` is sometimes SDMX-canonical
    # (REF_AREA, TIME_PERIOD, ...), sometimes legacy v2 (*_nom_id), depending
    # on which pipeline phase last touched the row. The parquet itself can
    # also be in either format. We use sdmx_column_map (SDMX ↔ legacy) to
    # rewrite dim names so they match the file.
    schema = _detect_parquet_schema(conn, matrix_code)

    def _load_col_map(direction: str) -> dict:
        parent_row = conn.execute(
            "SELECT parent_matrix_code FROM matrices WHERE matrix_code = ?", [matrix_code]
        ).fetchone()
        lookup_code = (parent_row[0] or matrix_code) if parent_row else matrix_code
        if direction == "legacy_to_sdmx":
            sql = "SELECT old_column_name, sdmx_column_name FROM sdmx_column_map WHERE matrix_code = ?"
        else:  # sdmx_to_legacy
            sql = "SELECT sdmx_column_name, old_column_name FROM sdmx_column_map WHERE matrix_code = ?"
        return dict(conn.execute(sql, [lookup_code]).fetchall())

    legacy_to_sdmx = {}
    if schema["is_legacy"]:
        # Parquet is legacy. Any dim names that look SDMX-canonical need to
        # be rewritten BACK to *_nom_id to match the file — and the same goes
        # for the caller's group_by / filter keys (charts always send SDMX
        # names). Without this, group_by silently falls back to "all dims"
        # (unaggregated) and filters never match. Responses are translated
        # back to SDMX names below so clients see one canonical schema.
        rev_map = _load_col_map("sdmx_to_legacy")
        if rev_map:
            legacy_to_sdmx = {v: k for k, v in rev_map.items()}
            for d in dimensions:
                if not d['dim_column_name'].endswith('_nom_id'):
                    d['dim_column_name'] = rev_map.get(d['dim_column_name'], d['dim_column_name'])
            if group_by_cols:
                group_by_cols = [rev_map.get(c, c) for c in group_by_cols]
            filter_dict = {rev_map.get(k, k): v for k, v in filter_dict.items()}
    elif any(d['dim_column_name'].endswith('_nom_id') for d in dimensions):
        # Parquet is SDMX. Any dim names still in *_nom_id form need rewriting
        # forward to canonical names.
        col_map = _load_col_map("legacy_to_sdmx")
        for d in dimensions:
            if d['dim_column_name'].endswith('_nom_id'):
                d['dim_column_name'] = col_map.get(d['dim_column_name'], d['dim_column_name'])

    # Auto time-window when the projected result would exceed MAX_DATA_ROWS and
    # the user hasn't already constrained time. Threshold matches the row cap
    # so we limit periods *before* the result gets silently truncated; the
    # frontend can still page through earlier periods via the period browser.
    #
    # This used to skip grouped queries on the theory that GROUP BY already
    # shrinks the output. It does not always: the output is the product of the
    # grouped dimensions' cardinalities, which for POP107D grouped by
    # (TIME_PERIOD, REF_AREA_2) is 34 x 3,182 = 108k rows — over the cap. And
    # since every v2 chart query sets group_by, the guard never fired for the
    # queries that need it most, leaving four concurrent full scans of a
    # 21.6M-row parquet to race a 400MB memory limit.
    TIME_WINDOW_THRESHOLD = MAX_DATA_ROWS
    time_windowed = False
    # The time column is TIME_PERIOD on SDMX parquets and a *_nom_id on the
    # 67 legacy ones. Everything downstream — windowing, newest-first
    # ordering, the partial-period drop — keys off this one name.
    time_col = _resolve_time_column(conn, dimensions, schema, legacy_to_sdmx,
                                    matrix_code)
    if row_count > TIME_WINDOW_THRESHOLD and time_col:
        time_dim = time_col if time_col not in filter_dict else None
        if time_dim:
            # Try parquet scan first (fast for moderate files), fall back to metadata
            parquet_path = PARQUET_DIR / f"{matrix_code}.parquet"
            time_vals = []
            try:
                time_vals = [r[0] for r in conn.execute(f"""
                    SELECT DISTINCT "{time_dim}"
                    FROM read_parquet('{parquet_path}')
                    ORDER BY "{time_dim}" DESC
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
                rows_per_period = _rows_per_period(
                    dimensions, group_by_cols, filter_dict, time_dim,
                    row_count, n_periods)
                # For extremely large datasets, allow a smaller minimum to avoid OOM
                min_periods = 2 if row_count > 5_000_000 else 5
                safe_periods = max(min_periods, int(MAX_DATA_ROWS / max(rows_per_period, 1)))
                safe_periods = min(safe_periods, n_periods)
                if safe_periods < n_periods:
                    filter_dict[time_dim] = time_vals[:safe_periods]
                    time_windowed = True

    # Refuse only what is genuinely unbounded. This used to reject every
    # unfiltered raw-row request on a large dataset, which also broke the
    # dataset page's own table view: it asks for 1,000 rows and got a 400 on
    # all 127 datasets above the threshold. A bounded request is safe now —
    # the window above cuts to the newest periods, the query takes the newest
    # rows, and DuckDB answers it with a streaming top-N. What remains
    # unbounded is a big dataset with no filters, no grouping and no time
    # dimension to window on.
    if (row_count > LARGE_DATASET_THRESHOLD and not filter_dict
            and not group_by_cols and not time_windowed):
        raise HTTPException(
            400,
            f"Dataset has {row_count:,} rows. Please apply at least one filter "
            f"to narrow results (max {MAX_DATA_ROWS:,} rows returned)."
        )

    # Determine aggregation function based on unit type
    agg_func = "SUM"
    if group_by_cols:
        unit_row = conn.execute(
            "SELECT primary_unit_type FROM matrix_profiles WHERE matrix_code = ?",
            [matrix_code]
        ).fetchone()
        if unit_row and unit_row[0] in AVG_UNIT_TYPES:
            agg_func = "AVG"

    # Build and execute query
    sql = build_data_query(matrix_code, dimensions, filter_dict, limit + 1,
                           group_by=group_by_cols, agg_func=agg_func,
                           value_column=schema["value_column"],
                           time_column=time_col)

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

    # A truncated result is cut mid-period. The query now takes the NEWEST
    # rows, so the incomplete one is the oldest period present — charting it
    # draws a first point that dips for no reason, and any total computed over
    # it is simply wrong. Drop it: a shorter honest series beats a longer one
    # that lies at the edge. Keep it when it is the only period, where there
    # is nothing better to show.
    partial_period = None
    if truncated:
        tidx = next((i for i, d in enumerate(result_dims)
                     if d['dim_column_name'] == time_col), None) if time_col else None
        if tidx is not None:
            periods = {r[tidx] for r in rows if r[tidx] is not None}
            if len(periods) > 1:
                partial_period = min(periods)
                rows = [r for r in rows if r[tidx] != partial_period]

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

    # Format column names — legacy parquet columns are translated back to
    # SDMX-canonical names so every client sees one schema.
    def _out_col(c):
        return legacy_to_sdmx.get(c, c)
    columns = [_out_col(d['dim_column_name']) for d in result_dims] + ['OBS_VALUE']
    if legacy_to_sdmx:
        column_labels = {_out_col(c): v for c, v in column_labels.items()}

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
    if partial_period is not None:
        resp['partial_period_dropped'] = str(partial_period)
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

    if not (PARQUET_DIR / f"{matrix_code}.parquet").exists():
        raise HTTPException(
            404, f"Dataset {matrix_code} has no data file — it may be "
                 f"published as sub-datasets."
        )

    dims = conn.execute("""
        SELECT dim_code, dim_label, dim_column_name
        FROM dimensions WHERE matrix_code = ? ORDER BY dim_code
    """, [matrix_code]).fetchall()

    dimensions = [{'dim_code': d[0], 'dim_label': d[1], 'dim_column_name': d[2]} for d in dims]

    # Same parquet-schema reconciliation as /data endpoint
    schema = _detect_parquet_schema(conn, matrix_code)
    parent_row = conn.execute(
        "SELECT parent_matrix_code FROM matrices WHERE matrix_code = ?", [matrix_code]
    ).fetchone()
    lookup_code = (parent_row[0] or matrix_code) if parent_row else matrix_code
    if schema["is_legacy"]:
        if any(not d['dim_column_name'].endswith('_nom_id') for d in dimensions):
            rev_map = dict(conn.execute(
                "SELECT sdmx_column_name, old_column_name FROM sdmx_column_map WHERE matrix_code = ?",
                [lookup_code]
            ).fetchall())
            for d in dimensions:
                if not d['dim_column_name'].endswith('_nom_id'):
                    d['dim_column_name'] = rev_map.get(d['dim_column_name'], d['dim_column_name'])
    elif any(d['dim_column_name'].endswith('_nom_id') for d in dimensions):
        col_map = dict(conn.execute(
            "SELECT old_column_name, sdmx_column_name FROM sdmx_column_map WHERE matrix_code = ?",
            [lookup_code]
        ).fetchall())
        for d in dimensions:
            if d['dim_column_name'].endswith('_nom_id'):
                d['dim_column_name'] = col_map.get(d['dim_column_name'], d['dim_column_name'])

    sql = build_data_query(matrix_code, dimensions, filter_dict, MAX_DATA_ROWS,
                           value_column=schema["value_column"])

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
