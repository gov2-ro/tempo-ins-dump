"""Dataset listing and search service.

Reusable across the FastAPI route (`app/routers/datasets.py`), the
`tempo-dev` MCP server, and the LLM agent (Step 2 of the LLM tooling plan).
The route handler is a thin wrapper around `search_datasets()`.
"""
from app.db import get_conn
from app.config import DEFAULT_PAGE_SIZE


def search_datasets(
    q: str | None = None,
    *,
    context: str | None = None,
    ancestor: str | None = None,
    archetype: str | None = None,
    has_geo: bool | None = None,
    lang: str = "ro",
    sort: str = "updated",
    limit: int = DEFAULT_PAGE_SIZE,
    offset: int = 0,
    conn=None,
) -> dict:
    """Search the canonical dataset catalog with optional filters.

    Args:
        q:         Free-text match against matrix_name (lang-aware) and matrix_code
        context:   Exact context_code match
        ancestor:  Match a code anywhere in m.ancestor_codes
        archetype: matrix_profiles.archetype filter
        has_geo:   matrix_profiles.has_geo filter
        lang:      'ro' or 'en' — affects display_name + search column
        sort:      'updated' | 'name' | 'rows'
        limit:     Page size
        offset:    Page offset
        conn:      Optional DuckDB cursor; defaults to `get_conn()`

    Returns:
        {'total': int, 'datasets': [DatasetCard, ...]}
    """
    if conn is None:
        conn = get_conn()

    where = ["m.is_canonical = TRUE"]
    params: list = []

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

    count_sql = f"""
        SELECT COUNT(DISTINCT m.matrix_code)
        FROM matrices m
        LEFT JOIN matrix_profiles p ON m.matrix_code = p.matrix_code
        WHERE {where_sql}
    """
    total = conn.execute(count_sql, params).fetchone()[0]

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
