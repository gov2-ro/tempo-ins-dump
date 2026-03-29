"""Dataset listing, search, and detail API endpoints."""
import json
from fastapi import APIRouter, Query, HTTPException
from app.db import get_conn
from app.config import DEFAULT_PAGE_SIZE
from app.services.chart_selector import build_signature, select_charts, assign_roles

router = APIRouter()


@router.get("/datasets")
def list_datasets(
    q: str = Query(None, description="Search in dataset name"),
    context: str = Query(None, description="Filter by context_code"),
    ancestor: str = Query(None, description="Filter by ancestor code"),
    archetype: str = Query(None, description="Filter by archetype"),
    has_geo: bool = Query(None),
    lang: str = Query("ro", description="Language: ro|en"),
    sort: str = Query("updated", description="Sort: updated|name|rows"),
    limit: int = Query(DEFAULT_PAGE_SIZE, le=200),
    offset: int = Query(0, ge=0),
):
    """List datasets with search and filters."""
    conn = get_conn()

    where = ["m.is_canonical = TRUE"]
    params = []

    # Use EN name for search if lang=en
    name_col = "m.matrix_name_en" if lang == "en" else "m.matrix_name"

    if q:
        where.append(f"(LOWER({name_col}) LIKE LOWER(?) OR LOWER(m.matrix_code) LIKE LOWER(?))")
        params.extend([f"%{q}%", f"%{q}%"])

    if context:
        where.append("m.context_code = ?")
        params.append(context)

    if ancestor:
        where.append("? = ANY(m.ancestor_codes)")
        params.append(ancestor)

    if archetype:
        where.append("p.archetype = ?")
        params.append(archetype)

    if has_geo is not None:
        where.append(f"p.has_geo = {has_geo}")

    sort_map = {
        'updated': 'm.ultima_actualizare DESC NULLS LAST',
        'name': 'm.matrix_name',
        'rows': 'm.row_count DESC NULLS LAST',
    }
    order_by = sort_map.get(sort, sort_map['updated'])

    where_sql = " AND ".join(where)

    # Count total
    count_sql = f"""
        SELECT COUNT(DISTINCT m.matrix_code)
        FROM matrices m
        LEFT JOIN matrix_profiles p ON m.matrix_code = p.matrix_code
        WHERE {where_sql}
    """
    total = conn.execute(count_sql, params).fetchone()[0]

    # Fetch page
    display_name = "COALESCE(m.matrix_name_en, m.matrix_name)" if lang == "en" else "m.matrix_name"
    data_sql = f"""
        SELECT
            m.matrix_code,
            {display_name} as display_name,
            m.context_code,
            m.ultima_actualizare,
            m.row_count,
            m.mat_max_dim as dim_count,
            p.archetype,
            p.has_time,
            p.has_geo,
            p.time_year_min,
            p.time_year_max,
            p.primary_unit_type,
            p.time_granularity,
            m.is_split,
            m.parent_matrix_code,
            COUNT(ds.sub_matrix_code) as split_count
        FROM matrices m
        LEFT JOIN matrix_profiles p ON m.matrix_code = p.matrix_code
        LEFT JOIN dataset_splits ds ON ds.parent_matrix_code = m.matrix_code
        WHERE {where_sql}
        GROUP BY m.matrix_code, m.matrix_name, m.matrix_name_en, m.context_code,
                 m.ultima_actualizare, m.row_count, m.mat_max_dim, p.archetype,
                 p.has_time, p.has_geo, p.time_year_min, p.time_year_max,
                 p.primary_unit_type, p.time_granularity, m.is_split, m.parent_matrix_code
        ORDER BY {order_by}
        LIMIT ? OFFSET ?
    """
    rows = conn.execute(data_sql, params + [limit, offset]).fetchall()

    datasets = []
    for r in rows:
        time_range = None
        if r[9] and r[10]:
            time_range = f"{r[9]}-{r[10]}"
        datasets.append({
            'matrix_code': r[0],
            'matrix_name': r[1],
            'context_code': r[2],
            'ultima_actualizare': str(r[3]) if r[3] else None,
            'row_count': r[4],
            'dim_count': r[5],
            'archetype': r[6],
            'has_time': r[7],
            'has_geo': r[8],
            'time_range': time_range,
            'primary_unit_type': r[11],
            'time_granularity': r[12],
            'is_split': bool(r[13]),
            'parent_matrix_code': r[14],
            'split_count': r[15] or 0,
        })

    return {'total': total, 'datasets': datasets}


@router.get("/datasets/{matrix_code}")
def get_dataset(matrix_code: str, lang: str = Query("ro", description="Language: ro|en")):
    """Get full dataset metadata, dimensions, options, and chart config."""
    conn = get_conn()

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
        raise HTTPException(404, f"Dataset {matrix_code} not found")

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

    dimensions = []
    for dim_code, dim_label, dim_col, opt_count, dim_id in dims_raw:
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
                sc.sdmx_value
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
            nom_id, label, offset, parent_id, dt, year, q, mo, geo_lvl, geo_name, gender, age_min, age_max, unit_type, unit_scale, conf, sdmx_val = opt
            if dt:
                type_counts[dt] = type_counts.get(dt, 0) + 1

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
                'label': label,
                'offset': offset,
                'parent_id': parent_id,
                'dim_type': dt,
                'parsed': parsed,
                'sdmx_value': sdmx_val,
            })

        dim_type = max(type_counts, key=type_counts.get) if type_counts else 'indicator'

        dimensions.append({
            'dim_code': dim_code,
            'dim_label': dim_label,
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
        for ac in ancestor_codes:
            r = conn.execute("SELECT context_name FROM contexts WHERE context_code = ?", [str(ac)]).fetchone()
            if r:
                context_path.append({'code': str(ac), 'name': r[0]})

    # Split variant relationships
    is_split = bool(m[10])
    parent_matrix_code = m[11]

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

    parent_info = None
    if is_split and parent_matrix_code:
        pr = conn.execute("""
            SELECT matrix_code, matrix_name FROM matrices WHERE matrix_code = ?
        """, [parent_matrix_code]).fetchone()
        if pr:
            parent_info = {"matrix_code": pr[0], "matrix_name": pr[1]}

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

    # Build chart config via scoring engine
    sig = build_signature(profile, dimensions, coverage, value_profile, trend)
    ranked = select_charts(sig)

    # Roles for each ranked chart
    for entry in ranked:
        entry['roles'] = assign_roles(entry['chart_type'], dimensions)

    primary = ranked[0]['chart_type'] if ranked else 'table'

    # Backward-compat fields (frontend still uses these for choropleth/filter logic)
    geo_dim = next((d for d in dimensions if d['dim_type'] == 'geo'), None)
    time_dim = next((d for d in dimensions if d['dim_type'] == 'time'), None)

    chart_config = {
        'ranked_charts': ranked,
        'primary_chart': primary,
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

    return {
        'matrix_code': m[0],
        'matrix_name': display_name,
        'matrix_name_ro': m[1],
        'context_code': m[2],
        'context_path': context_path,
        'definitie': m[4],
        'metodologie': m[5],
        'ultima_actualizare': str(m[6]) if m[6] else None,
        'observatii': m[7],
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
