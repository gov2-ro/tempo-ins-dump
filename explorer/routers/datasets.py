"""Dataset listing, search, and detail API endpoints."""
import json
from fastapi import APIRouter, Query, HTTPException
from explorer.db import get_conn
from explorer.config import DEFAULT_PAGE_SIZE
from explorer.services.chart_selector import build_signature, select_charts, assign_roles
from explorer.services.translations import get_matrix_name_en, get_context_name_en

router = APIRouter()


@router.get("/datasets")
def list_datasets(
    q: str = Query(None),
    context: str = Query(None),
    ancestor: str = Query(None),
    sort: str = Query("updated"),
    lang: str = Query("ro"),
    limit: int = Query(DEFAULT_PAGE_SIZE, le=200),
    offset: int = Query(0, ge=0),
):
    conn = get_conn()

    where = ["m.parquet_path IS NOT NULL"]
    params = []

    if q:
        where.append("LOWER(m.matrix_name) LIKE LOWER(?)")
        params.append(f"%{q}%")
    if context:
        where.append("m.context_code = ?")
        params.append(context)
    if ancestor:
        where.append("? = ANY(m.ancestor_codes)")
        params.append(ancestor)

    sort_map = {
        'updated': 'm.ultima_actualizare DESC NULLS LAST',
        'name': 'm.matrix_name',
        'rows': 'm.row_count DESC NULLS LAST',
    }
    order_by = sort_map.get(sort, sort_map['updated'])
    where_sql = " AND ".join(where)

    total = conn.execute(f"""
        SELECT COUNT(*) FROM matrices m
        LEFT JOIN matrix_profiles p ON m.matrix_code = p.matrix_code
        WHERE {where_sql}
    """, params).fetchone()[0]

    rows = conn.execute(f"""
        SELECT
            m.matrix_code, m.matrix_name, m.context_code,
            m.ultima_actualizare, m.row_count, m.mat_max_dim,
            p.archetype, p.has_time, p.has_geo,
            p.time_year_min, p.time_year_max, p.primary_unit_type
        FROM matrices m
        LEFT JOIN matrix_profiles p ON m.matrix_code = p.matrix_code
        WHERE {where_sql}
        ORDER BY {order_by}
        LIMIT ? OFFSET ?
    """, params + [limit, offset]).fetchall()

    datasets = []
    for r in rows:
        time_range = f"{r[9]}-{r[10]}" if r[9] and r[10] else None
        d = {
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
        }
        if lang == 'en':
            en = get_matrix_name_en(r[0])
            if en:
                d['matrix_name_en'] = en
        datasets.append(d)

    return {'total': total, 'datasets': datasets}


@router.get("/datasets/{matrix_code}")
def get_dataset(matrix_code: str, lang: str = Query("ro")):
    conn = get_conn()

    m = conn.execute("""
        SELECT matrix_code, matrix_name, context_code, ancestor_codes,
               definitie, metodologie, ultima_actualizare, observatii,
               row_count, mat_max_dim
        FROM matrices WHERE matrix_code = ?
    """, [matrix_code]).fetchone()

    if not m:
        raise HTTPException(404, f"Dataset {matrix_code} not found")

    # Profile
    profile_row = conn.execute(
        "SELECT * FROM matrix_profiles WHERE matrix_code = ?", [matrix_code]
    ).fetchone()
    profile = {}
    if profile_row:
        cols = [d[0] for d in conn.execute("DESCRIBE matrix_profiles").fetchall()]
        profile = dict(zip(cols, profile_row))

    # Dimensions
    dims_raw = conn.execute("""
        SELECT dim_code, dim_label, dim_column_name, option_count, dimension_id
        FROM dimensions WHERE matrix_code = ? ORDER BY dim_code
    """, [matrix_code]).fetchall()

    dimensions = []
    for dim_code, dim_label, dim_col, opt_count, dim_id in dims_raw:
        options = conn.execute("""
            SELECT o.nom_item_id, o.option_label, o.option_offset, o.parent_id,
                   p.dim_type, p.year, p.quarter, p.month,
                   p.geo_level, p.geo_name_clean, p.gender,
                   p.age_min, p.age_max, p.unit_type, p.unit_scale, p.parse_confidence
            FROM dimension_options o
            LEFT JOIN dimension_options_parsed p ON o.nom_item_id = p.nom_item_id
            WHERE o.dimension_id = ?
            ORDER BY o.option_offset
        """, [dim_id]).fetchall()

        type_counts = {}
        option_list = []
        for opt in options:
            nom_id, label, offset, parent_id, dt = opt[0], opt[1], opt[2], opt[3], opt[4]
            if dt:
                type_counts[dt] = type_counts.get(dt, 0) + 1

            parsed = {}
            if dt == 'time':
                parsed = {'year': opt[5], 'quarter': opt[6], 'month': opt[7]}
            elif dt == 'geo':
                parsed = {'geo_level': opt[8], 'geo_name_clean': opt[9]}
            elif dt == 'gender':
                parsed = {'gender': opt[10]}
            elif dt == 'age':
                parsed = {'age_min': opt[11], 'age_max': opt[12]}
            elif dt == 'unit':
                parsed = {'unit_type': opt[13], 'unit_scale': opt[14]}
            elif dt == 'residence':
                parsed = {'geo_level': opt[8], 'geo_name_clean': opt[9]}

            option_list.append({
                'nom_item_id': nom_id,
                'label': label,
                'offset': offset,
                'parent_id': parent_id,
                'dim_type': dt,
                'parsed': parsed,
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

    # Context path
    context_path = None
    context_path_en = None
    if m[3]:
        ancestor_codes = m[3] if isinstance(m[3], list) else []
        if ancestor_codes:
            names_ro, names_en = [], []
            for ac in ancestor_codes:
                r = conn.execute(
                    "SELECT context_name FROM contexts WHERE context_code = ?", [str(ac)]
                ).fetchone()
                if r:
                    names_ro.append(r[0])
                    en = get_context_name_en(str(ac))
                    names_en.append(en or r[0])
            context_path = " > ".join(names_ro)
            context_path_en = " > ".join(names_en)

    # Chart recommendations
    def fetch_row(table):
        row = conn.execute(f"SELECT * FROM {table} WHERE matrix_code = ?", [matrix_code]).fetchone()
        if not row:
            return {}
        cols = [d[0] for d in conn.execute(f"DESCRIBE {table}").fetchall()]
        return dict(zip(cols, row))

    coverage = fetch_row('dataset_coverage')
    value_profile = fetch_row('dataset_value_profiles')
    trend = fetch_row('dataset_trends')

    sig = build_signature(profile, dimensions, coverage, value_profile, trend)
    ranked = select_charts(sig)
    for entry in ranked:
        entry['roles'] = assign_roles(entry['chart_type'], dimensions)

    primary = ranked[0]['chart_type'] if ranked else 'table'

    # Chart config
    geo_dim = next((d for d in dimensions if d['dim_type'] == 'geo'), None)
    time_dim = next((d for d in dimensions if d['dim_type'] == 'time'), None)

    chart_config = {
        'ranked_charts': ranked,
        'primary_chart': primary,
        'supports': [r['chart_type'] for r in ranked],
        'archetype': sig['_archetype'],
        'geo_dim': geo_dim['dim_column_name'] if geo_dim else None,
        'time_dim': time_dim['dim_column_name'] if time_dim else None,
    }

    result = {
        'matrix_code': m[0],
        'matrix_name': m[1],
        'context_code': m[2],
        'context_path': context_path,
        'definitie': m[4],
        'ultima_actualizare': str(m[6]) if m[6] else None,
        'row_count': m[8],
        'dim_count': m[9],
        'profile': profile,
        'dimensions': dimensions,
        'chart_config': chart_config,
    }

    if lang == 'en':
        en = get_matrix_name_en(m[0])
        if en:
            result['matrix_name_en'] = en
        if context_path_en:
            result['context_path_en'] = context_path_en

    return result
