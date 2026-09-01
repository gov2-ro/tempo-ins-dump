"""Dataset metadata fetcher service.

Returns the full dataset detail (matrix info, dimensions+options, splits,
chart_config). Reusable across the FastAPI route, the `tempo-dev` MCP
server, and the LLM agent (Step 2 of the LLM tooling plan).
"""
import json
from pathlib import Path

from app.config import PARQUET_DIR
from app.db import get_conn
from app.services.chart_selector import (
    build_signature, select_charts, assign_roles, decide_pair, TOTAL_RE)
from app.services.dashboard_composer import (
    compose_dashboard, retune_ranked_series, primary_time_dim,
    _build_slice, _non_total_options, NON_ADDITIVE_UNIT_TYPES)
from app.services import dimension_structure as dstruct
from app.services.query_builder import build_data_query


_EN_METAS_DIR = Path(__file__).parent.parent.parent / "data" / "2-metas" / "en"


def _parquet_dim_values(conn, matrix_code: str, dimensions: list) -> dict:
    """Values per dimension column as stored in the parquet, with row counts:
    {dim_column: {value: row_count}}.

    Metadata routinely lists options the data lacks (Total rows, whole
    categories) — the dashboard composer needs data reality to build slices
    that aren't empty; row counts let forced pins prefer the densest option.
    Consumers only rely on key membership, so the mapping is drop-in for the
    previous set shape. Columns that fail (legacy v2 schema, missing file)
    are simply absent; the composer falls back to metadata for those.
    """
    path = PARQUET_DIR / f"{matrix_code}.parquet"
    if not path.exists():
        return {}

    def _read(col):
        rows = conn.execute(
            f'SELECT "{col}", COUNT(*) FROM read_parquet(?) '
            f'GROUP BY "{col}"', [str(path)]
        ).fetchall()
        return {str(r[0]): r[1] for r in rows if r[0] is not None}

    out = {}
    rev_map = None  # SDMX → legacy *_nom_id, loaded on first miss
    for d in dimensions:
        col = d['dim_column_name']
        try:
            out[col] = _read(col)
            continue
        except Exception:
            pass
        # Legacy parquet: the file's columns are *_nom_id names — resolve
        # via sdmx_column_map so slices stay data-grounded there too (the
        # values are label strings with indentation metadata lacks).
        if rev_map is None:
            parent = conn.execute(
                "SELECT parent_matrix_code FROM matrices WHERE matrix_code = ?",
                [matrix_code]).fetchone()
            lookup = (parent[0] or matrix_code) if parent else matrix_code
            rev_map = dict(conn.execute(
                "SELECT sdmx_column_name, old_column_name "
                "FROM sdmx_column_map WHERE matrix_code = ?", [lookup]).fetchall())
        legacy_col = rev_map.get(col)
        if legacy_col:
            try:
                out[col] = _read(legacy_col)
            except Exception:
                pass
    return out


def _detect_composition(conn, matrix_code: str, dimensions: list,
                        actual_values: dict, unit_type: str,
                        struct: dict | None = None) -> bool | None:
    """Data-grounded parts-of-whole check for the stackable series dim.

    Picks the dim a stacked chart would use as its series (small
    categorical, else gender/residence), pins everything else exactly like
    a dashboard tile slice, and checks on the latest period whether the
    non-Total options sum to the dim's Total value (±2%) — or, for
    percentage data without a Total, to ~100. Feeds the selector's
    `is_composition` signal; None = could not verify (≠ not-composition).
    """
    candidates = []
    for d in dimensions:
        if d.get('dim_type') in ('time', 'unit', 'geo'):
            continue
        n = len(_non_total_options(d, actual_values))
        if 2 <= n <= 8:
            order = 0 if d.get('dim_type') == 'indicator' else 1
            candidates.append((order, n, d))
    if not candidates:
        return None
    candidates.sort(key=lambda t: (t[0], t[1]))
    dim = candidates[0][2]
    col = dim['dim_column_name']

    non_additive = unit_type in NON_ADDITIVE_UNIT_TYPES
    time_dim = primary_time_dim(dimensions)
    spec = _build_slice({'x_axis': col}, dimensions, time_dim,
                        'horizontal_bar', actual_values, non_additive, struct)
    try:
        sql = build_data_query(matrix_code, dimensions, spec['filters'],
                               1000, group_by=[col], agg_func='SUM')
        rows = conn.execute(sql).fetchall()
    except Exception:
        return None
    by_val = {str(r[0]): r[1] for r in rows
              if r[0] is not None and r[1] is not None}
    if not by_val:
        return None

    total_v = sum(v for k, v in by_val.items() if TOTAL_RE.match(k.strip()))
    parts = [v for k, v in by_val.items() if not TOTAL_RE.match(k.strip())]
    if len(parts) < 2:
        return None
    s = sum(parts)
    if total_v:
        return abs(s - total_v) <= abs(total_v) * 0.02
    if unit_type == 'percentage':
        return 98.0 <= s <= 102.0
    return None


def _load_en_meta(matrix_code: str) -> dict:
    """Load English metadata JSON for a dataset, or empty dict if unavailable."""
    # For split datasets like POP301A_judete, try base code first
    base = matrix_code.split("_")[0] if "_" in matrix_code else matrix_code
    for code in (matrix_code, base):
        p = _EN_METAS_DIR / f"{code}.json"
        if p.exists():
            try:
                return json.loads(p.read_text(encoding="utf-8"))
            except Exception:
                pass
    return {}


def get_dataset_meta(matrix_code: str, lang: str = "ro", *, conn=None) -> dict | None:
    """Fetch full metadata + dimensions + chart config for a dataset.

    Args:
        matrix_code: Dataset identifier
        lang:        'ro' or 'en'
        conn:        Optional DuckDB cursor; defaults to `get_conn()`

    Returns:
        Dict with the full dataset shape (see `app/routers/datasets.py:get_dataset`),
        or None if the matrix_code is not found. Callers decide whether to
        raise an HTTPException or handle the missing case differently.
    """
    if conn is None:
        conn = get_conn()
    en_meta = _load_en_meta(matrix_code) if lang == "en" else {}

    # Fetch matrix info
    m = conn.execute("""
        SELECT matrix_code, matrix_name, context_code, ancestor_codes,
               definitie, metodologie, ultima_actualizare, observatii,
               row_count, mat_max_dim, is_split, parent_matrix_code,
               matrix_name_en
        FROM matrices
        WHERE matrix_code = ?
    """, [matrix_code]).fetchone()

    if not m:
        return None

    # Fetch profile
    profile_row = conn.execute("""
        SELECT * FROM matrix_profiles WHERE matrix_code = ?
    """, [matrix_code]).fetchone()

    profile = {}
    if profile_row:
        profile_cols = [d[0] for d in conn.execute("DESCRIBE matrix_profiles").fetchall()]
        profile = dict(zip(profile_cols, profile_row))

    # Fetch dimensions with options and parsed metadata
    dims_raw = conn.execute("""
        SELECT
            d.dim_code,
            d.dim_label,
            d.dim_column_name,
            d.option_count,
            d.dimension_id
        FROM dimensions d
        WHERE d.matrix_code = ?
        ORDER BY d.dim_code
    """, [matrix_code]).fetchall()

    # Resolve legacy v2 _nom_id column names to SDMX names for split sub-datasets
    col_map = {}
    if any(r[2].endswith('_nom_id') for r in dims_raw):
        parent_row = conn.execute(
            "SELECT parent_matrix_code FROM matrices WHERE matrix_code = ?", [matrix_code]
        ).fetchone()
        lookup_code = (parent_row[0] or matrix_code) if parent_row else matrix_code
        col_map = dict(conn.execute("""
            SELECT old_column_name, sdmx_column_name
            FROM sdmx_column_map WHERE matrix_code = ?
        """, [lookup_code]).fetchall())

    # Build dim_label EN lookup from file (indexed by 1-based dim_code)
    en_dims_map = {}  # dim_code (int) → {"label": ..., "options": [{label, ...}]}
    if lang == "en":
        for i, dim in enumerate(en_meta.get("dimensionsMap", []), start=1):
            en_dims_map[i] = {
                "label": dim.get("label", ""),
                "options": {o.get("label", "").strip(): o.get("label", "").strip()
                            for o in dim.get("options", [])},
            }

    dimensions = []
    for dim_code, dim_label, dim_col_raw, opt_count, dim_id in dims_raw:
        dim_col = col_map.get(dim_col_raw, dim_col_raw) if dim_col_raw.endswith('_nom_id') else dim_col_raw
        # Get options with parsed fields
        options = conn.execute("""
            SELECT
                o.nom_item_id,
                o.option_label,
                o.option_offset,
                o.parent_id,
                p.dim_type,
                p.year,
                p.quarter,
                p.month,
                p.geo_level,
                p.geo_name_clean,
                p.gender,
                p.age_min,
                p.age_max,
                p.unit_type,
                p.unit_scale,
                p.parse_confidence,
                sc.sdmx_value,
                sc.display_label_en
            FROM dimension_options o
            LEFT JOIN dimension_options_parsed p ON o.nom_item_id = p.nom_item_id
            LEFT JOIN sdmx_codes sc ON o.nom_item_id = sc.nom_item_id
            WHERE o.dimension_id = ?
            ORDER BY o.option_offset
        """, [dim_id]).fetchall()

        # Determine dimension type from majority of parsed options
        type_counts = {}
        option_list = []
        for opt in options:
            nom_id, label, offset, parent_id, dt, year, q, mo, geo_lvl, geo_name, gender, age_min, age_max, unit_type, unit_scale, conf, sdmx_val, label_en = opt
            if dt:
                type_counts[dt] = type_counts.get(dt, 0) + 1

            # Use EN label from sdmx_codes when available
            display_label = (label_en or label) if lang == "en" else label

            parsed = {}
            if dt == 'time':
                parsed = {'year': year, 'quarter': q, 'month': mo}
            elif dt == 'geo':
                parsed = {'geo_level': geo_lvl, 'geo_name_clean': geo_name}
            elif dt == 'gender':
                parsed = {'gender': gender}
            elif dt == 'age':
                parsed = {'age_min': age_min, 'age_max': age_max}
            elif dt == 'unit':
                parsed = {'unit_type': unit_type, 'unit_scale': unit_scale}
            elif dt == 'residence':
                parsed = {'geo_level': geo_lvl, 'geo_name_clean': geo_name}

            option_list.append({
                'nom_item_id': nom_id,
                'label': display_label,
                'offset': offset,
                'parent_id': parent_id,
                'dim_type': dt,
                'parsed': parsed,
                'sdmx_value': sdmx_val,
            })

        dim_type = max(type_counts, key=type_counts.get) if type_counts else 'indicator'

        # Use EN dim label from file if available
        en_dim = en_dims_map.get(dim_code, {})
        display_dim_label = en_dim.get("label") or dim_label if lang == "en" else dim_label

        dimensions.append({
            'dim_code': dim_code,
            'dim_label': display_dim_label,
            'dim_column_name': dim_col,
            'dim_type': dim_type,
            'option_count': opt_count,
            'options': option_list,
        })

    # Build context path from ancestor_codes as structured array
    # For sub-datasets without ancestor_codes, inherit from parent
    ancestor_codes_raw = m[3]
    if not ancestor_codes_raw and m[11]:  # no ancestors but has parent_matrix_code
        parent_row = conn.execute(
            "SELECT ancestor_codes FROM matrices WHERE matrix_code = ?", [m[11]]
        ).fetchone()
        if parent_row:
            ancestor_codes_raw = parent_row[0]

    context_path = []
    if ancestor_codes_raw:
        ancestor_codes = ancestor_codes_raw if isinstance(ancestor_codes_raw, list) else []
        ctx_name_col = "COALESCE(context_name_en, context_name)" if lang == "en" else "context_name"
        for ac in ancestor_codes:
            r = conn.execute(
                f"SELECT {ctx_name_col} FROM contexts WHERE context_code = ?", [str(ac)]
            ).fetchone()
            if r:
                context_path.append({'code': str(ac), 'name': r[0]})

    # Split variant relationships
    is_split = bool(m[10])
    parent_matrix_code = m[11]

    has_parquet = (PARQUET_DIR / f"{matrix_code}.parquet").exists()

    splits = []
    try:
        split_rows = conn.execute("""
            SELECT sub_matrix_code, split_value, row_count, split_dimensions
            FROM dataset_splits WHERE parent_matrix_code = ?
            ORDER BY sub_matrix_code
        """, [matrix_code]).fetchall()
        splits = [
            {"matrix_code": r[0], "label": r[1], "row_count": r[2],
             "split_dimensions": json.loads(r[3]) if r[3] else None}
            for r in split_rows
        ]
    except Exception:
        pass
    if not splits and not has_parquet:
        # Some split children exist only as parquet files, never registered
        # in dataset_splits (e.g. AMG101A_anual) — derive them from the
        # corpus so split parents can still route somewhere useful.
        splits = [
            {"matrix_code": p.stem,
             "label": p.stem[len(matrix_code) + 1:].replace("_", " "),
             "row_count": None, "split_dimensions": None}
            for p in sorted(PARQUET_DIR.glob(f"{matrix_code}_*.parquet"))
        ]

    parent_info = None
    if is_split and parent_matrix_code:
        pr = conn.execute("""
            SELECT matrix_code, matrix_name, matrix_name_en FROM matrices WHERE matrix_code = ?
        """, [parent_matrix_code]).fetchone()
        if pr:
            parent_display = (pr[2] or pr[1]) if lang == 'en' else pr[1]
            parent_info = {"matrix_code": pr[0], "matrix_name": parent_display}

    # Fetch enriched metadata for scoring
    def fetch_row(table):
        row = conn.execute(f"SELECT * FROM {table} WHERE matrix_code = ?", [matrix_code]).fetchone()
        if not row:
            return {}
        cols = [d[0] for d in conn.execute(f"DESCRIBE {table}").fetchall()]
        return dict(zip(cols, row))

    coverage = fetch_row('dataset_coverage')
    value_profile = fetch_row('dataset_value_profiles')
    trend = fetch_row('dataset_trends')

    # Build chart config via scoring engine. Parquet reality comes first:
    # value presence grounds role defaults and slices, and the composition
    # probe feeds the selector's is_composition signal.
    actual_values = _parquet_dim_values(conn, matrix_code, dimensions)
    # What this dataset's options mean: verified levels, real aggregates,
    # nesting, additivity. Empty for unprofiled datasets — every consumer
    # falls back to its label-based heuristic.
    struct = dstruct.load(conn, matrix_code)
    unit_type = profile.get('primary_unit_type', 'count') or 'count'
    data_signals = {'is_composition': _detect_composition(
        conn, matrix_code, dimensions, actual_values, unit_type, struct)}
    sig = build_signature(profile, dimensions, coverage, value_profile, trend,
                          data_signals)
    ranked = select_charts(sig)

    # Roles for each ranked chart, then align evolution-series defaults with
    # the composer so both surfaces present the same default split.
    for entry in ranked:
        entry['roles'] = assign_roles(entry['chart_type'], dimensions, sig,
                                      actual_values)
    retune_ranked_series(ranked, dimensions, sig, actual_values, struct)

    primary = ranked[0]['chart_type'] if ranked else 'table'

    # Backward-compat fields (frontend still uses these for choropleth/filter logic)
    geo_dim = next((d for d in dimensions if d['dim_type'] == 'geo'), None)
    time_dim = next((d for d in dimensions if d['dim_type'] == 'time'), None)

    pair = decide_pair(ranked)
    # No parquet → no data to slice: split parents (data lives in the
    # children) must not get a composition, or every tile 500s. The v2
    # frontend shows the sub-dataset pills instead.
    composition = compose_dashboard(sig, ranked, dimensions, trend,
                                    actual_values, struct) if has_parquet else None

    chart_config = {
        'ranked_charts': ranked,
        # v2 dashboard recipe: 1-4 charts with layout slots + data slice specs
        'composition': composition,
        'primary_chart': primary,
        # When non-null, frontend should render primary + complement side-by-side.
        # When null, render the primary chart alone.
        'pair': pair,
        'supports': [r['chart_type'] for r in ranked],
        'archetype': sig['_archetype'],
        'dataset_signature': {k: v for k, v in sig.items() if not k.startswith('_')},
        # Backward-compat
        'geo_dim': geo_dim['dim_column_name'] if geo_dim else None,
        'time_dim': time_dim['dim_column_name'] if time_dim else None,
        'multi_unit': profile.get('primary_unit_type') is not None and len(
            json.loads(profile.get('unit_types', '[]') or '[]')
        ) > 1,
        'unit_types': json.loads(profile.get('unit_types', '[]') or '[]'),
        'primary_unit_type': profile.get('primary_unit_type', 'count'),
    }

    matrix_name_en = m[12]
    display_name = (matrix_name_en or m[1]) if lang == 'en' else m[1]

    # Use English text fields from JSON file when available
    if lang == 'en' and en_meta:
        definitie   = en_meta.get('definitie') or m[4]
        metodologie = en_meta.get('metodologie') or m[5]
        observatii  = en_meta.get('observatii') or m[7]
    else:
        definitie, metodologie, observatii = m[4], m[5], m[7]

    return {
        'matrix_code': m[0],
        'matrix_name': display_name,
        'matrix_name_ro': m[1],
        'context_code': m[2],
        'context_path': context_path,
        'definitie': definitie,
        'metodologie': metodologie,
        'ultima_actualizare': str(m[6]) if m[6] else None,
        'observatii': observatii,
        'row_count': m[8],
        'dim_count': m[9],
        'is_split': is_split,
        'parent_matrix_code': parent_matrix_code,
        'splits': splits,
        'parent': parent_info,
        'profile': profile,
        'dimensions': dimensions,
        'chart_config': chart_config,
    }
