"""Category tree and corpus summary API endpoints."""
from fastapi import APIRouter, Query
from app.db import get_conn
from app.config import PARQUET_DIR
from app.services.headlines import compute_headlines

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


@router.get("/corpus/summary")
def get_corpus_summary(lang: str = Query("ro", regex="^(ro|en)$")):
    """Return corpus-level stats, headline indicators, and recently updated datasets."""
    conn = get_conn()

    # Corpus stats
    stats = conn.execute("""
        SELECT
            COUNT(*) AS datasets,
            SUM(row_count) AS observations,
            COUNT(DISTINCT context_code) AS categories,
            MIN(p.time_year_min) AS year_min,
            MAX(p.time_year_max) AS year_max,
            COUNT(*) FILTER (WHERE p.has_geo) AS geo_datasets
        FROM matrices m
        LEFT JOIN matrix_profiles p ON m.matrix_code = p.matrix_code
        WHERE m.is_canonical = TRUE
    """).fetchone()

    corpus = {
        'datasets': stats[0],
        'observations': stats[1],
        'categories': stats[2],
        'time_span': {'min': stats[3], 'max': stats[4]},
        'geo_datasets': stats[5],
    }

    # Headline indicators from parquet files
    headlines = compute_headlines(conn, PARQUET_DIR, lang)

    # Recently updated datasets
    name_col = "COALESCE(m.matrix_name_en, m.matrix_name)" if lang == "en" else "m.matrix_name"
    def_col = "COALESCE(m.definitie_en, m.definitie)" if lang == "en" else "m.definitie"
    recent_rows = conn.execute(f"""
        SELECT m.matrix_code, {name_col} AS matrix_name,
               m.ultima_actualizare,
               t.trend_direction, t.yoy_growth_latest,
               p.time_year_min, p.time_year_max,
               {def_col} AS definitie
        FROM matrices m
        LEFT JOIN dataset_trends t ON m.matrix_code = t.matrix_code
        LEFT JOIN matrix_profiles p ON m.matrix_code = p.matrix_code
        WHERE m.is_canonical = TRUE AND m.ultima_actualizare IS NOT NULL
        ORDER BY m.ultima_actualizare DESC
        LIMIT 12
    """).fetchall()

    recently_updated = []
    for r in recent_rows:
        time_range = f"{r[5]}-{r[6]}" if r[5] and r[6] else None
        definitie = r[7] or ''
        words = definitie.split()
        excerpt = ' '.join(words[:15]) + ('…' if len(words) > 15 else '')
        recently_updated.append({
            'matrix_code': r[0],
            'matrix_name': r[1],
            'ultima_actualizare': str(r[2]) if r[2] else None,
            'trend_direction': r[3],
            'yoy_growth_latest': float(r[4]) if r[4] is not None else None,
            'time_range': time_range,
            'excerpt': excerpt,
        })

    return {
        'corpus': corpus,
        'headlines': headlines,
        'recently_updated': recently_updated,
    }


@router.get("/categories/{code}/summary")
def get_category_summary(code: str, lang: str = Query("ro", regex="^(ro|en)$")):
    """Return summary stats for a specific category (context code)."""
    conn = get_conn()

    stats = conn.execute("""
        SELECT
            COUNT(*) AS datasets,
            SUM(m.row_count) AS observations,
            MIN(p.time_year_min) AS year_min,
            MAX(p.time_year_max) AS year_max,
            COUNT(*) FILTER (WHERE t.trend_direction = 'increasing') AS up,
            COUNT(*) FILTER (WHERE t.trend_direction = 'decreasing') AS down,
            COUNT(*) FILTER (WHERE t.trend_direction = 'flat') AS flat,
            COUNT(*) FILTER (WHERE t.trend_direction = 'volatile') AS volatile
        FROM matrices m
        LEFT JOIN matrix_profiles p ON m.matrix_code = p.matrix_code
        LEFT JOIN dataset_trends t ON m.matrix_code = t.matrix_code
        WHERE m.is_canonical = TRUE AND ? = ANY(m.ancestor_codes)
    """, [code]).fetchone()

    return {
        'code': code,
        'datasets': stats[0],
        'observations': stats[1],
        'time_span': {'min': stats[2], 'max': stats[3]} if stats[2] else None,
        'trends': {
            'up': stats[4], 'down': stats[5],
            'flat': stats[6], 'volatile': stats[7],
        },
    }


@router.get("/dimensions")
def list_dimensions(limit: int = Query(100, le=500)):
    """Return dimension labels ranked by number of datasets that have them."""
    conn = get_conn()
    rows = conn.execute("""
        SELECT dim_label,
               COUNT(DISTINCT matrix_code) AS dataset_count,
               SUM(option_count)           AS total_options
        FROM dimensions
        GROUP BY dim_label
        ORDER BY dataset_count DESC, dim_label ASC
        LIMIT ?
    """, [limit]).fetchall()
    return [
        {'label': r[0], 'dataset_count': r[1], 'total_options': r[2] or 0}
        for r in rows
    ]


def _clean_context_name(name: str) -> str:
    """Remove leading numbering/prefixes like 'A. ', '1. ' from context names."""
    if not name:
        return name
    # Keep the full name for now — the frontend can format it
    return name.strip()
