"""One validated data query for every consumer (PA-01a).

REST `/api/datasets/{code}/data`, the Ask `query_dataset_data` tool and the dev
MCP `tempo_query` all call `run_query`, so the same request gets the same
validation, aggregation decision, effective filters and values everywhere.
Adapters only translate transport: HTTP status codes, tool error objects.

Callers must not choose SUM/AVG, drop a filter, broaden an empty selection or
override a refusal; those decisions live here and in aggregation_policy.
"""
import logging
import re

from app.config import MAX_DATA_ROWS, LARGE_DATASET_THRESHOLD, PARQUET_DIR
from app.services.query_builder import (
    build_data_query_params, resolve_parquet_schema, adapt_to_parquet,
    quote_ident, to_sdmx_name)
from app.services import generation, grain_guard
from app.services.request_validation import (
    MISSING, InvalidRequest, validate_filters, validate_group_by)

log = logging.getLogger(__name__)

# Version of the result shape below. Bump when a field changes meaning; adding a
# field does not. PA-02/03 lock the serialized schema against this.
CONTRACT = "tempo-query/1"


class QueryError(Exception):
    """A request the shared query refuses to run. `status` follows HTTP
    (400 invalid, 404 not found, 500 failed); adapters map it to transport."""

    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status
        self.message = message


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


def run_query(conn, matrix_code: str, filters=MISSING, group_by=MISSING,
              limit: int = MAX_DATA_ROWS, approximate: bool = False) -> dict:
    """Validate, decide and execute one data query; the REST, Ask and MCP shape.

    `filters` / `group_by` are decoded JSON values (`MISSING` when absent).
    Raises QueryError (400 invalid request, 404 unknown dataset or no data
    file, 500 execution failure). A refused aggregation is not an error: the
    result has `unavailable: true`, no rows and the decision under
    `aggregation`. Approximations happen only with `approximate=True`.
    """
    if not isinstance(limit, int) or isinstance(limit, bool) \
            or not 1 <= limit <= MAX_DATA_ROWS:
        raise QueryError(400, f"Invalid limit: must be an integer in 1..{MAX_DATA_ROWS}")
    # Get matrix info
    matrix = conn.execute(
        "SELECT row_count FROM matrices WHERE matrix_code = ?", [matrix_code]
    ).fetchone()
    if not matrix:
        raise QueryError(404, f"Dataset {matrix_code} not found")

    row_count = matrix[0] or 0

    if not (PARQUET_DIR / f"{matrix_code}.parquet").exists():
        # Split parents keep a `matrices` row but publish data only through
        # their children. A large one used to be masked by the row-count gate
        # and a small one leaked an absolute server path in a 500.
        raise QueryError(
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
    try:
        filter_dict = validate_filters(filters, allowed)
        group_by_cols = validate_group_by(group_by, allowed)
    except InvalidRequest as e:
        raise QueryError(400, str(e))
    requested = {to_sdmx_name(schema, c) for c, v in filter_dict.items() if v}

    # FIX-02: a grouped request collapses every dim it does not group by, so the
    # shared policy decides whether (and how) that is allowed. The decision's
    # filters (aggregate pins, verified levels) are applied to the query.
    aggregation = None
    agg_func = "SUM"
    if group_by_cols:
        from app.services.dataset_meta import get_aggregation_context, decide_grouped
        ctx = get_aggregation_context(conn, matrix_code)
        if ctx is not None:
            to_sdmx = lambda c: to_sdmx_name(schema, c)
            sd_group = [to_sdmx(c) for c in group_by_cols]
            sd_filters = {to_sdmx(k): v for k, v in filter_dict.items()}
            decision = decide_grouped(ctx, sd_group, sd_filters,
                                      allow_approximation=approximate)
            aggregation = decision.to_dict()
            # The headline series (every non-time dim collapsed, no caller
            # filter) is the insights KPI's query: same source-total gate, so
            # v1's headline card cannot show a sum INS contradicts.
            time_cols = {d['dim_column_name'] for d in ctx['dimensions']
                         if d.get('dim_type') == 'time'}
            if decision.available and not sd_filters and len(sd_group) == 1 \
                    and sd_group[0] in time_cols:
                from app.services.dataset_meta import source_total_gate
                reason, _ = source_total_gate(conn, matrix_code, decision)
                if reason:
                    aggregation.update(outcome='unavailable', reason=reason)
                    return _unavailable(matrix_code, sd_group, row_count, aggregation)
            if not decision.available:
                return _unavailable(matrix_code, sd_group, row_count, aggregation)
            group_by_cols = sd_group
            filter_dict = {k: list(v) for k, v in decision.effective_filters.items()}
            agg_func = decision.agg_func or "SUM"
        else:
            # No context means no decision; an unguarded SUM is not a fallback.
            aggregation = {'outcome': 'unavailable', 'reason': 'no_aggregation_context',
                           'blocking_dimension': None, 'method': 'none'}
            return _unavailable(matrix_code, [to_sdmx_name(schema, c) for c in group_by_cols],
                                row_count, aggregation)
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
        raise QueryError(
            400,
            f"Dataset has {row_count:,} rows. Please apply at least one filter "
            f"to narrow results (max {MAX_DATA_ROWS:,} rows returned)."
        )

    # PA-01b: an aggregation needs a unique grain on the rows it reads (after
    # pins and windowing). Raw rows are returned with the file's status instead.
    grain = None
    if group_by_cols:
        grain = grain_guard.check_slice(conn, matrix_code, filter_dict, row_count,
                                        schema["value_column"])
        if not grain['ok']:
            aggregation = {**(aggregation or {}), 'outcome': 'unavailable',
                           'reason': grain['reason'], 'blocking_dimension': None,
                           'method': 'none'}
            return _unavailable(matrix_code, [legacy_to_sdmx.get(c, c) for c in group_by_cols],
                                row_count, aggregation, grain)

    # Build and execute query
    sql, params = build_data_query_params(
        matrix_code, dimensions, filter_dict, limit + 1,
        group_by=group_by_cols, agg_func=agg_func,
        value_column=schema["value_column"], time_column=time_col)

    try:
        result = conn.execute(sql, params).fetchall()
    except Exception:
        log.exception("data query failed matrix=%s", matrix_code)
        raise QueryError(500, "Query failed")

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
        **_envelope(matrix_code, grain),
    }
    if time_windowed:
        resp['time_windowed'] = True
    if partial_period is not None:
        resp['partial_period_dropped'] = str(partial_period)
    if not data_rows and requested and not resp.get('unavailable'):
        # An empty result is reported as such, with the requested values that
        # do not exist — never broadened into a different question.
        resp['selection'] = {'empty': True, 'missing_values': _missing_values(
            conn, matrix_code, filter_dict, requested, legacy_to_sdmx)}
    return resp


def _envelope(matrix_code: str, grain: dict | None = None) -> dict:
    """Contract version, generation and grain status carried by every result."""
    quality = {'grain': grain_guard.file_status(matrix_code)}
    if grain is not None:
        quality['slice'] = {k: grain.get(k) for k in
                            ('ok', 'reason', 'evidence', 'duplicate_keys', 'conflicting_keys')}
    return {'contract': CONTRACT, 'generation': generation.summary(), 'quality': quality}


def _unavailable(matrix_code, columns, row_count, aggregation, grain=None) -> dict:
    return {'columns': list(columns) + ['OBS_VALUE'], 'column_labels': {}, 'rows': [],
            'total_rows': row_count, 'returned_rows': 0, 'truncated': False,
            'unavailable': True, 'aggregation': aggregation,
            **_envelope(matrix_code, grain)}


def _missing_values(conn, matrix_code, filter_dict, requested, legacy_to_sdmx) -> dict:
    """{column: [requested values absent from the file]} for the caller's filters."""
    path = str(PARQUET_DIR / f"{matrix_code}.parquet")
    out = {}
    for col, vals in filter_dict.items():
        name = legacy_to_sdmx.get(col, col)
        if name not in requested or not vals:
            continue
        want = [str(v) for v in vals]
        try:
            found = {r[0] for r in conn.execute(
                f"SELECT DISTINCT CAST({quote_ident(col)} AS VARCHAR) FROM read_parquet(?) "
                f"WHERE CAST({quote_ident(col)} AS VARCHAR) IN ({', '.join('?' for _ in want)})",
                [path, *want]).fetchall()}
        except Exception:
            log.exception("missing-value probe failed matrix=%s col=%s", matrix_code, col)
            continue
        miss = [v for v in want if v not in found]
        if miss:
            out[name] = miss
    return out
