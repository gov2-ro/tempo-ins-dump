"""Category tree API endpoint."""
from fastapi import APIRouter
from app.db import get_conn

router = APIRouter()


@router.get("/categories")
def get_categories():
    """Return the full category tree with dataset counts per leaf node."""
    conn = get_conn()

    # Fetch all contexts
    contexts = conn.execute("""
        SELECT context_code, parent_code, level, context_name
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


def _clean_context_name(name: str) -> str:
    """Remove leading numbering/prefixes like 'A. ', '1. ' from context names."""
    if not name:
        return name
    # Keep the full name for now — the frontend can format it
    return name.strip()
