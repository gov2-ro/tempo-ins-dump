"""Category tree API endpoint with i18n support."""
from fastapi import APIRouter, Query
from explorer.db import get_conn
from explorer.services.translations import get_context_name_en

router = APIRouter()


@router.get("/categories")
def get_categories(lang: str = Query("ro")):
    """Return the full category tree with dataset counts."""
    conn = get_conn()

    contexts = conn.execute("""
        SELECT context_code, parent_code, level, context_name
        FROM contexts
        ORDER BY level, context_code
    """).fetchall()

    counts = {}
    for code, cnt in conn.execute("""
        SELECT context_code, COUNT(*) as cnt
        FROM matrices
        WHERE context_code IS NOT NULL
        GROUP BY context_code
    """).fetchall():
        counts[str(code)] = cnt

    nodes = {}
    for code, parent, level, name in contexts:
        code_s = str(code)
        node = {
            'code': code_s,
            'name': name.strip() if name else '',
            'level': level,
            'parent': str(parent),
            'dataset_count': counts.get(code_s, 0),
            'children': [],
        }
        if lang == 'en':
            en_name = get_context_name_en(code_s)
            if en_name:
                node['name'] = en_name
        nodes[code_s] = node

    roots = []
    for code_s, node in nodes.items():
        parent = node.pop('parent')
        if parent in nodes:
            nodes[parent]['children'].append(node)
        else:
            roots.append(node)

    def _sum_counts(node):
        total = node['dataset_count']
        for child in node['children']:
            total += _sum_counts(child)
        node['total_datasets'] = total
        return total

    for root in roots:
        _sum_counts(root)

    return {'tree': roots}
