"""Category tree API endpoint."""
from fastapi import APIRouter, Query
from app.db import get_conn

router = APIRouter()


@router.get("/categories")
def get_categories(lang: str = Query("ro", regex="^(ro|en)$")):
    """Return the full category tree with dataset counts per leaf node."""
    conn = get_conn()

    name_col = "COALESCE(context_name_en, context_name)" if lang == "en" else "context_name"

    # Fetch all contexts
    contexts = conn.execute(f"""
        SELECT context_code, parent_code, level, {name_col} AS context_name
        FROM contexts
        ORDER BY level, context_code
    """).fetchall()

    # Count datasets per context_code
    counts = {}
    for code, cnt in conn.execute("""
        SELECT context_code, COUNT(*) as cnt
        FROM matrices
        WHERE context_code IS NOT NULL
        GROUP BY context_code
    """).fetchall():
        counts[str(code)] = cnt

    # Build tree
    nodes = {}
    for code, parent, level, name in contexts:
        code_s = str(code)
        nodes[code_s] = {
            'code': code_s,
            'name': _clean_context_name(name),
            'level': level,
            'parent': str(parent),
            'dataset_count': counts.get(code_s, 0),
            'children': [],
        }

    # Wire up children
    roots = []
    for code_s, node in nodes.items():
        parent = node.pop('parent')
        if parent in nodes:
            nodes[parent]['children'].append(node)
        else:
            roots.append(node)

    # Propagate dataset counts upward
    def _sum_counts(node):
        total = node['dataset_count']
        for child in node['children']:
            total += _sum_counts(child)
        node['total_datasets'] = total
        return total

    for root in roots:
        _sum_counts(root)

    return {'tree': roots}


@router.get("/categories/trends")
def get_category_trends():
    """Return trend direction aggregates per context code (all levels)."""
    conn = get_conn()
    rows = conn.execute("""
        SELECT a.ancestor_code AS context_code,
               COUNT(*) AS total,
               COUNT(*) FILTER (WHERE t.trend_direction = 'increasing') AS up,
               COUNT(*) FILTER (WHERE t.trend_direction = 'decreasing') AS down,
               COUNT(*) FILTER (WHERE t.trend_direction = 'flat') AS flat,
               COUNT(*) FILTER (WHERE t.trend_direction = 'volatile') AS volatile,
               ROUND(AVG(t.yoy_growth_latest), 2) AS avg_yoy
        FROM matrices m,
             UNNEST(m.ancestor_codes) AS a(ancestor_code)
        JOIN dataset_trends t ON m.matrix_code = t.matrix_code
        GROUP BY a.ancestor_code
    """).fetchall()

    trends = {}
    for code, total, up, down, flat, volatile, avg_yoy in rows:
        trends[str(code)] = {
            'total': total, 'up': up, 'down': down,
            'flat': flat, 'volatile': volatile,
            'avg_yoy': float(avg_yoy) if avg_yoy is not None else None,
        }
    return {'trends': trends}


def _clean_context_name(name: str) -> str:
    """Remove leading numbering/prefixes like 'A. ', '1. ' from context names."""
    if not name:
        return name
    # Keep the full name for now — the frontend can format it
    return name.strip()
