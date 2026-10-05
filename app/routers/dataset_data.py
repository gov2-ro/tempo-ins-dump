"""Dataset data querying endpoint — powers all charts."""
import csv
import io
import json
import logging
import os
import re
from fastapi import APIRouter, Query, HTTPException
from fastapi.responses import Response, StreamingResponse
from app.db import get_conn
from app.config import MAX_DATA_ROWS, LARGE_DATASET_THRESHOLD, PARQUET_DIR

from app.services.query_builder import (
    build_data_query_params, build_export_query_params, resolve_parquet_schema, adapt_to_parquet,
    quote_ident)
from app.services.request_validation import parse_filters, parse_group_by

log = logging.getLogger(__name__)

router = APIRouter()


@router.get("/datasets/{matrix_code}/insights")
def get_dataset_insights(
    matrix_code: str,
    lang: str = Query("ro", pattern="^(ro|en)$"),
):
    """KPI headline values + template-based insight sentences (cached)."""
    from app.services.insights import compute_insights
    try:
        result = compute_insights(matrix_code, lang=lang)
    except Exception:
        log.exception("insights failed matrix=%s", matrix_code)
        raise HTTPException(500, "Insights unavailable")
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
    try:
        rows = conn.execute(
            'SELECT "REF_AREA", "TIME_PERIOD", SUM("OBS_VALUE") '
            "FROM read_parquet(?) GROUP BY 1, 2", [str(path)]
        ).fetchall()
    finally:
        conn.close()
    pop: dict = {}
    for area, period, v in rows:
        if area is None or period is None or v is None:
            continue
        pop.setdefault(str(area).strip(), {})[str(period)] = v
    _POP_REFERENCE_CACHE[level] = {"level": level, "population": pop}
    return _POP_REFERENCE_CACHE[level]


# Legacy period labels that sort chronologically as plain strings. Annual
# labels do ("Anul 1990" < "Anul 2024"); month names do not ("Aprilie" sorts
# before "Ianuarie"), so those datasets keep the old unordered behaviour
# rather than being given a confident but wrong idea of "newest".
_ANNUAL_LABEL_RE = re.compile(r"^\s*Anul\s+\d{4}\s*$")


def _resolve_time_column(conn, dimensions, schema, matrix_code: str) -> str | None:
    """The parquet column holding time, or None if there isn't a usable one.

    SDMX parquets name it TIME_PERIOD. The legacy ones carry a *_nom_id whose
    SDMX counterpart is TIME_PERIOD, and store label strings rather than
    dates — usable only while those labels sort chronologically.
    """
    cols = {d['dim_column_name'] for d in dimensions}
    if 'TIME_PERIOD' in cols:
        return 'TIME_PERIOD'
    legacy = next((c for c in cols
                   if schema['to_sdmx'].get(c) == 'TIME_PERIOD'), None)
    if not legacy:
        return None
    path = PARQUET_DIR / f"{matrix_code}.parquet"
    try:
        vals = [r[0] for r in conn.execute(
            f'SELECT DISTINCT {quote_ident(legacy)} FROM read_parquet(?) LIMIT 500',
            [str(path)]
        ).fetchall()]
    except Exception:
        return None
    if vals and all(_ANNUAL_LABEL_RE.match(str(v or '')) for v in vals):
        return legacy
    return None


def _to_sdmx_name(schema, col: str) -> str:
    """A request column name (SDMX, or the file's legacy *_nom_id spelling) as
    the SDMX name the aggregation context uses."""
    if schema.get("is_legacy"):
        return (schema.get("to_sdmx") or {}).get(col, col)
    if col.endswith("_nom_id"):
        return (schema.get("to_file") or {}).get(col, col)
    return col


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


def _allowed_columns(dimensions, schema) -> set:
    """Every column name a request may legitimately mention for this dataset:
    the recorded dimension names plus both spellings from the schema maps
    (SDMX and legacy file names). The value column is excluded."""
    cols = {d['dim_column_name'] for d in dimensions}
    for m in (schema.get("to_file") or {}, schema.get("to_sdmx") or {}):
        cols.update(m.keys())
        cols.update(m.values())
    cols.discard(schema.get("value_column"))
    cols.discard("OBS_VALUE")
    return cols


@router.get("/datasets/{matrix_code}/data")
def get_dataset_data(
    matrix_code: str,
    filters: str = Query("{}", description="JSON object: {column_name: [scalar, ...]}"),
    limit: int = Query(MAX_DATA_ROWS, ge=1, le=MAX_DATA_ROWS),
    group_by: str = Query("", description="JSON array of dim columns to GROUP BY, e.g. [\"TIME_PERIOD\",\"SEX\"]. "
                          "Other dims are collapsed only when the shared aggregation policy "
                          "allows it (see `aggregation` in the response). Empty = raw rows."),
    approximate: int = Query(0, ge=0, le=1, description="1 = allow an explicitly labelled unweighted "
                             "mean when a non-additive measure must be collapsed"),
):
    """Query dataset parquet with dimension filters.

    Returns compact format: rows as value arrays + column_labels dict.
    Parquet-v3 values are human-readable strings (SDMX format).

    4xx: 404 unknown dataset / no data file; 400 malformed filters or group_by
    (not JSON, wrong shape, unknown column, non-scalar value) or an unbounded
    request on a large dataset; 422 limit < 1 or > MAX rows.

    Grouped requests (FIX-02): the collapsed dimensions go through the shared
    aggregation policy. The response carries `aggregation` (the decision dict:
    outcome, reason, method, verification, approximation, filters actually
    applied, levels, per-dimension audit, warnings). Totals are pinned to real
    aggregate rows, a verified level is applied to collapsed AND multi-level
    axis dims. When the policy refuses, the response is still HTTP 200 but
    `unavailable: true`, `rows: []` and `aggregation.reason` /
    `aggregation.blocking_dimension` say why; an unsafe sum is never returned.
    Raw (ungrouped) requests and valid explicit slices are unaffected, and
    `aggregation` is null for raw rows.
    """
    conn = get_conn()
    try:
        return _dataset_data(conn, matrix_code, filters, limit, group_by,
                             approximate=bool(approximate))
    finally:
        conn.close()


def _dataset_data(conn, matrix_code: str, filters: str, limit: int, group_by: str,
                  approximate: bool = False):
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
    # The recorded name is sometimes SDMX-canonical, sometimes legacy v2
    # (*_nom_id), depending on which pipeline phase last touched the row, and
    # the file can be in either format too. resolve_parquet_schema owns that
    # translation for every consumer — it used to be reimplemented here, in
    # dataset_meta and in agent, and omitted in insights, which is why 188
    # datasets published a single KPI.
    schema = resolve_parquet_schema(conn, matrix_code)
    legacy_to_sdmx = schema["to_sdmx"]
    allowed = _allowed_columns(dimensions, schema)
    filter_dict = parse_filters(filters, allowed)
    group_by_cols = parse_group_by(group_by, allowed)

    # FIX-02: a grouped request collapses every dim it does not group by, so the
    # shared policy decides whether (and how) that is allowed. The decision's
    # filters (aggregate pins, verified levels) are applied to the query.
    aggregation = None
    agg_func = "SUM"
    if group_by_cols:
        from app.services.dataset_meta import get_aggregation_context, decide_grouped
        ctx = get_aggregation_context(conn, matrix_code)
        if ctx is not None:
            to_sdmx = lambda c: _to_sdmx_name(schema, c)
            sd_group = [to_sdmx(c) for c in group_by_cols]
            sd_filters = {to_sdmx(k): v for k, v in filter_dict.items()}
            decision = decide_grouped(ctx, sd_group, sd_filters,
                                      allow_approximation=approximate)
            aggregation = decision.to_dict()
            if not decision.available:
                return {
                    'columns': sd_group + ['OBS_VALUE'], 'column_labels': {},
                    'rows': [], 'total_rows': row_count, 'returned_rows': 0,
                    'truncated': False, 'unavailable': True,
                    'aggregation': aggregation,
                }
            group_by_cols = sd_group
            filter_dict = {k: list(v) for k, v in decision.effective_filters.items()}
            agg_func = decision.agg_func or "SUM"
    dimensions, group_by_cols, filter_dict = adapt_to_parquet(
        schema, dimensions, group_by_cols, filter_dict)

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
    time_col = _resolve_time_column(conn, dimensions, schema, matrix_code)
    if row_count > TIME_WINDOW_THRESHOLD and time_col:
        time_dim = time_col if time_col not in filter_dict else None
        if time_dim:
            # Try parquet scan first (fast for moderate files), fall back to metadata
            parquet_path = PARQUET_DIR / f"{matrix_code}.parquet"
            time_vals = []
            try:
                time_vals = [r[0] for r in conn.execute(f"""
                    SELECT DISTINCT {quote_ident(time_dim)}
                    FROM read_parquet(?)
                    ORDER BY {quote_ident(time_dim)} DESC
                """, [str(parquet_path)]).fetchall()]
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

    # Build and execute query
    sql, params = build_data_query_params(
        matrix_code, dimensions, filter_dict, limit + 1,
        group_by=group_by_cols, agg_func=agg_func,
        value_column=schema["value_column"], time_column=time_col)

    try:
        result = conn.execute(sql, params).fetchall()
    except Exception:
        log.exception("data query failed matrix=%s", matrix_code)
        raise HTTPException(500, "Query failed")

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
        'aggregation': aggregation,
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
    filters: str = Query("{}", description="JSON object: {column_name: [scalar, ...]}"),
    lang: str = Query("ro", pattern="^(ro|en)$"),
    safe: int = Query(1, ge=0, le=1, description="1 = neutralise formula-like labels in CSV"),
    preflight: int = Query(0, ge=0, le=1, description="1 = return JSON counts/policy, no file"),
):
    """Download every raw observation matching the filters, as CSV or XLSX.

    Not bound by the chart cap. Headers on file responses:
    X-Export-Matching-Rows / X-Export-Rows (equal: the file is complete) and
    X-Export-Complete: true. XLSX over the worksheet limit, or any export over
    TEMPO_EXPORT_MAX_ROWS, is rejected with 413 before any file is sent.

    4xx: 404 unknown dataset / no data file; 400 malformed filters (same
    rules as /data); 413 selection too large for the format; 422 bad
    format or lang.
    """
    conn = get_conn()
    release = conn.close
    try:
        resp = _download(conn, matrix_code, format, filters, lang, bool(safe),
                         bool(preflight), release)
    except BaseException:
        release()
        raise
    # Streaming responses own the cursor and close it when the stream ends.
    if not getattr(resp, "_owns_conn", False):
        release()
    return resp


def _download(conn, matrix_code: str, format: str, filters: str, lang: str,
              safe: bool, preflight: bool, release):
    import app.config as cfg
    from app.services import export as ex

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
    schema = resolve_parquet_schema(conn, matrix_code)
    filter_dict = parse_filters(filters, _allowed_columns(dimensions, schema))
    dimensions, _, filter_dict = adapt_to_parquet(
        schema, dimensions, None, filter_dict)

    # Matching row count first: it drives the size policy and the headers.
    try:
        csql, cparams = build_export_query_params(
            matrix_code, dimensions, filter_dict,
            value_column=schema["value_column"], count_only=True)
        total = conn.execute(csql, cparams).fetchone()[0]
    except Exception:
        log.exception("download count failed matrix=%s", matrix_code)
        raise HTTPException(500, "Query failed")

    # Size policy: reject BEFORE any file bytes/headers are sent.
    if format == "xlsx" and total > ex.xlsx_row_limit():
        raise HTTPException(
            413, f"Selection has {total} rows, more than the XLSX limit of "
                 f"{ex.xlsx_row_limit()} data rows. Narrow the filters or "
                 f"download CSV, which has no row limit.")
    if cfg.EXPORT_MAX_ROWS and total > cfg.EXPORT_MAX_ROWS:
        raise HTTPException(
            413, f"Selection has {total} rows, more than the export limit of "
                 f"{cfg.EXPORT_MAX_ROWS}. Narrow the filters.")

    if preflight:
        return {"matrix_code": matrix_code, "format": format,
                "matching_rows": total, "complete": True,
                "xlsx_row_limit": ex.xlsx_row_limit(),
                "export_row_limit": cfg.EXPORT_MAX_ROWS or None}

    # Concurrency slot (non-blocking, before any headers). Released with the
    # cursor: when the stream ends, errors or the client disconnects.
    slot = ex.try_acquire("xlsx" if format == "xlsx" else "csv")
    if slot is None:
        raise ex.busy_error()

    def release_all():
        slot()
        release()

    try:
        return _stream_file(conn, matrix_code, format, lang, safe, dimensions,
                            filter_dict, schema, total, release_all)
    except BaseException:
        release_all()
        raise


def _stream_file(conn, matrix_code, format, lang, safe, dimensions,
                 filter_dict, schema, total, release):
    import app.config as cfg
    from app.services import export as ex

    col_names = [d['dim_column_name'] for d in dimensions] + ['OBS_VALUE']
    value_maps = ex.load_value_maps(conn, matrix_code, dimensions) if lang == "en" else {}
    transform = ex.make_row_transform(col_names, value_maps, safe, format == "csv")

    sql, params = build_export_query_params(
        matrix_code, dimensions, filter_dict, value_column=schema["value_column"])
    try:
        cur = conn.execute(sql, params)
    except Exception:
        log.exception("download query failed matrix=%s", matrix_code)
        raise HTTPException(500, "Query failed")

    headers = {"X-Export-Matching-Rows": str(total), "X-Export-Rows": str(total),
               "X-Export-Complete": "true",
               "Access-Control-Expose-Headers":
                   "X-Export-Matching-Rows, X-Export-Rows, X-Export-Complete"}

    if format == "csv":
        headers["Content-Disposition"] = f"attachment; filename={matrix_code}.csv"
        resp = StreamingResponse(
            ex.iter_csv(cur, col_names, transform, cfg.EXPORT_BATCH_ROWS, release),
            media_type="text/csv; charset=utf-8", headers=headers)
        resp._owns_conn = True
        return resp

    try:
        path, written = ex.write_xlsx_tempfile(
            cur, matrix_code, col_names, transform, cfg.EXPORT_BATCH_ROWS,
            ex.xlsx_row_limit(), safe)
    except OverflowError:
        raise HTTPException(
            413, "Selection grew past the XLSX row limit while exporting. "
                 "Download CSV instead.")
    except Exception:
        log.exception("xlsx export failed matrix=%s", matrix_code)
        raise HTTPException(500, "Export failed")
    headers["X-Export-Rows"] = str(written)
    headers["Content-Length"] = str(os.path.getsize(path))
    headers["Content-Disposition"] = f"attachment; filename={matrix_code}.xlsx"
    resp = StreamingResponse(
        ex.iter_file_then_delete(path, release),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers=headers)
    resp._owns_conn = True
    return resp
