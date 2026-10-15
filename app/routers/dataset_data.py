"""Dataset data querying endpoint — powers all charts."""
import csv
import io
import json
import logging
import os
from fastapi import APIRouter, Query, HTTPException, Request
from fastapi.responses import Response, StreamingResponse
from app.db import get_conn
from app.config import MAX_DATA_ROWS, PARQUET_DIR

from app.services.query_builder import (
    build_export_query_params, resolve_parquet_schema, adapt_to_parquet)
from app.services.request_validation import parse_filters

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
    from app.services import grain_guard
    conn = get_conn()
    try:
        grain = grain_guard.check_slice(conn, path.stem, {}, path=str(path))
        if not grain["ok"]:
            raise HTTPException(503, f"Population reference unavailable ({grain['reason']})")
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
    from app.services.data_query import QueryError, run_query
    from app.services.request_validation import InvalidRequest, parse_json_param
    try:
        f = parse_json_param(filters, "filters")
        g = parse_json_param(group_by, "group_by")
    except InvalidRequest as e:
        raise HTTPException(400, str(e))
    conn = get_conn()
    try:
        return run_query(conn, matrix_code, f, g, limit, approximate=bool(approximate))
    except QueryError as e:
        raise HTTPException(e.status, e.message)
    finally:
        conn.close()


@router.get("/datasets/{matrix_code}/options")
def get_dimension_values(
    matrix_code: str,
    column: str = Query(..., max_length=64, description="Dimension column, e.g. REF_AREA or TIME_PERIOD"),
    q: str = Query(None, max_length=200, description="Accent-insensitive substring match"),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    """Actual values of one dimension, searchable and paginated (PA-02a).

    Time columns are newest first and include `period_bounds` (first/last
    period with an observation). `next_offset`/`truncated` say whether more
    values follow. 4xx: 404 unknown dataset/no data file; 400 unknown column.
    """
    from app.services.data_query import QueryError, dimension_values
    conn = get_conn()
    try:
        return dimension_values(conn, matrix_code, column, q, limit, offset)
    except QueryError as e:
        raise HTTPException(e.status, e.message)
    finally:
        conn.close()


@router.get("/datasets/{matrix_code}/evidence")
def get_dataset_evidence(
    request: Request,
    matrix_code: str,
    filters: str = Query("{}", description="JSON object: {column_name: [scalar, ...]}"),
    group_by: str = Query("", description="JSON array, as for /data"),
    approximate: int = Query(0, ge=0, le=1),
    lang: str = Query("ro", pattern="^(ro|en)$"),
    expected_generation: str = Query(
        None, max_length=128, pattern=r"^[A-Za-z0-9._-]+$",
        description="Refuse (409 generation_changed) unless the served data generation is "
                    "this one, before the bundle is built and again before it is sent."),
):
    """ZIP evidence bundle for one /data selection (PA-03a): unrounded result,
    the raw observations behind an aggregation, the decision, definition,
    source and a manifest with hashes. Complete or 413, never cut."""
    from urllib.parse import urlencode
    from app.services import export as ex, generation
    from app.services.evidence import EvidenceError, dataset_bundle
    from app.services.request_validation import InvalidRequest, parse_json_param
    try:
        f = parse_json_param(filters, "filters")
        g = parse_json_param(group_by, "group_by")
    except InvalidRequest as e:
        raise HTTPException(400, str(e))
    stale = generation.precondition(expected_generation)
    if stale:
        raise HTTPException(409, stale)
    slot = ex.try_acquire("csv")
    if slot is None:
        raise ex.busy_error()
    conn = get_conn()
    try:
        q = {"code": matrix_code}
        if filters and filters != "{}":
            q["f"] = filters
        if lang != "ro":
            q["lang"] = lang
        link = f"{str(request.base_url).rstrip('/')}/dataset-v2.html?{urlencode(q)}"
        data = dataset_bundle(conn, matrix_code, f, g, bool(approximate), lang, link)
        stale = generation.precondition(expected_generation)    # swapped while building
        if stale:
            raise HTTPException(409, stale)
    except EvidenceError as e:
        raise HTTPException(e.status, e.message)
    finally:
        conn.close()
        slot()
    return Response(data, media_type="application/zip", headers={
        "Content-Disposition": f"attachment; filename={matrix_code}_evidence.zip"})


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
    from app.services.data_query import _allowed_columns
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
