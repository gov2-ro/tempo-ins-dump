#!/usr/bin/env python
"""tempo-dev MCP server — 6 introspection tools for Claude Code.

Run via `.mcp.json` (repo-local) or manually:
    python tools/tempo-dev-mcp/server.py

Tools:
    tempo_dataset_info     — workhorse: full metadata + dims + charts + sample
    tempo_search_datasets  — catalog search with filters
    tempo_chart_signature  — chart_selector scores for a dataset
    tempo_sample           — labelled rows from a parquet
    tempo_query            — aggregated data queries via query_builder
    tempo_catalog_stats    — corpus-level breakdowns
"""
import json
import logging
import os
import sys

# ---------------------------------------------------------------------------
# Ensure project root is on sys.path so `app.*` imports work
# ---------------------------------------------------------------------------
REPO_ROOT = os.environ.get(
    "TEMPO_REPO_ROOT",
    os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")),
)
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from mcp.server.fastmcp import FastMCP

logging.basicConfig(
    level=logging.INFO,
    format="%(name)s %(levelname)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stderr)],
)
log = logging.getLogger("tempo-dev")

mcp = FastMCP("tempo-dev")

# ---------------------------------------------------------------------------
# Lazy imports — only resolve on first call (keeps startup fast, avoids
# import errors if DuckDB isn't on the PATH yet when the MCP server starts)
# ---------------------------------------------------------------------------
_ready = False


def _ensure_imports():
    global _ready
    if _ready:
        return
    # These will be importable because REPO_ROOT is on sys.path
    global search_datasets, get_dataset_meta, build_signature, select_charts
    global build_data_query
    global get_conn, PARQUET_DIR, CORPUS_DIR
    from app.services.dataset_search import search_datasets
    from app.services.dataset_meta import get_dataset_meta
    from app.services.chart_selector import build_signature, select_charts
    from app.services.query_builder import build_data_query
    from app.db import get_conn
    from app.config import PARQUET_DIR, CORPUS_DIR
    _ready = True


# ---------------------------------------------------------------------------
# 1. tempo_dataset_info — the workhorse
# ---------------------------------------------------------------------------
@mcp.tool()
def tempo_dataset_info(matrix_code: str) -> str:
    """Full introspection for a single dataset in one call.

    Returns JSON with: basic metadata, dimensions (options capped to 50/dim),
    view profile, chart_selector scores + top chart eligibilities,
    dataset_value_profiles / dataset_coverage / dataset_trends rows,
    10 sample rows from the parquet, and split/parent info.

    Args:
        matrix_code: Dataset identifier (e.g. 'ACC101B', 'POP301A_judete')
    """
    _ensure_imports()
    meta = get_dataset_meta(matrix_code)
    if meta is None:
        return json.dumps({"error": f"Dataset {matrix_code} not found"})

    # Cap options per dimension to keep response size manageable
    for dim in meta.get("dimensions", []):
        opts = dim.get("options", [])
        if len(opts) > 50:
            dim["options"] = opts[:50]
            dim["_options_truncated"] = len(opts)

    # View profile (JSON file)
    vp_path = CORPUS_DIR / "view-profiles" / f"{matrix_code}.json"
    view_profile = None
    if vp_path.exists():
        try:
            view_profile = json.loads(vp_path.read_text(encoding="utf-8"))
        except Exception:
            pass

    # Enriched metadata rows
    conn = get_conn()

    def _fetch_row(table):
        row = conn.execute(
            f"SELECT * FROM {table} WHERE matrix_code = ?", [matrix_code]
        ).fetchone()
        if not row:
            return None
        cols = [d[0] for d in conn.execute(f"DESCRIBE {table}").fetchall()]
        return dict(zip(cols, row))

    value_profile = _fetch_row("dataset_value_profiles")
    coverage = _fetch_row("dataset_coverage")
    trend = _fetch_row("dataset_trends")

    # Sample rows from parquet
    sample_rows = _sample_parquet(matrix_code, n=10, conn=conn, meta=meta)

    result = {
        "matrix_code": meta["matrix_code"],
        "matrix_name": meta["matrix_name"],
        "definitie": meta.get("definitie"),
        "ultima_actualizare": meta.get("ultima_actualizare"),
        "context_path": meta.get("context_path"),
        "row_count": meta.get("row_count"),
        "dim_count": meta.get("dim_count"),
        "is_split": meta.get("is_split"),
        "parent_matrix_code": meta.get("parent_matrix_code"),
        "splits": meta.get("splits"),
        "dimensions": meta.get("dimensions"),
        "chart_config": meta.get("chart_config"),
        "view_profile": view_profile,
        "value_profile": value_profile,
        "coverage": coverage,
        "trend": trend,
        "sample_rows": sample_rows,
    }
    return json.dumps(result, default=str, ensure_ascii=False)


# ---------------------------------------------------------------------------
# 2. tempo_search_datasets
# ---------------------------------------------------------------------------
@mcp.tool()
def tempo_search_datasets(
    query: str,
    has_geo: bool | None = None,
    archetype: str | None = None,
    limit: int = 10,
) -> str:
    """Search the catalog of ~3,600 Romanian INS TEMPO datasets.

    Returns top matches by name, tags, and category.
    Supports Romanian and English keywords.

    Args:
        query:     Free-text search (Romanian or English)
        has_geo:   Filter to datasets with geographic dimension
        archetype: Filter by archetype (geo_time, demographic, time_residence, time_series)
        limit:     Max results (default 10, max 25)
    """
    _ensure_imports()
    limit = min(limit, 25)
    result = search_datasets(
        query, has_geo=has_geo, archetype=archetype, limit=limit,
    )
    return json.dumps(result, default=str, ensure_ascii=False)


# ---------------------------------------------------------------------------
# 3. tempo_chart_signature
# ---------------------------------------------------------------------------
@mcp.tool()
def tempo_chart_signature(matrix_code: str) -> str:
    """Run build_signature() + select_charts() and return the full
    eligibility table with scores per chart type.

    Useful for tuning chart selection — see scores, confidence, and
    complementary pairings at a glance.

    Args:
        matrix_code: Dataset identifier
    """
    _ensure_imports()
    meta = get_dataset_meta(matrix_code)
    if meta is None:
        return json.dumps({"error": f"Dataset {matrix_code} not found"})

    sig = meta["chart_config"]["dataset_signature"]
    ranked = meta["chart_config"]["ranked_charts"]
    return json.dumps({
        "matrix_code": matrix_code,
        "archetype": meta["chart_config"]["archetype"],
        "signature": sig,
        "ranked_charts": ranked,
    }, default=str, ensure_ascii=False)


# ---------------------------------------------------------------------------
# 4. tempo_sample
# ---------------------------------------------------------------------------
@mcp.tool()
def tempo_sample(
    matrix_code: str,
    n: int = 10,
    filters: str | None = None,
) -> str:
    """Return labelled sample rows from a dataset's parquet file.

    Dimension values are already human-readable (SDMX strings).
    Useful for "what does this dataset actually look like?"

    Args:
        matrix_code: Dataset identifier
        n:           Number of rows (default 10, max 100)
        filters:     Optional JSON string: {"COLUMN": ["val1","val2"], ...}
    """
    _ensure_imports()
    n = min(n, 100)

    filter_dict = {}
    if filters:
        try:
            filter_dict = json.loads(filters)
        except json.JSONDecodeError:
            return json.dumps({"error": "Invalid JSON in filters parameter"})

    meta = get_dataset_meta(matrix_code)
    if meta is None:
        return json.dumps({"error": f"Dataset {matrix_code} not found"})

    rows = _sample_parquet(matrix_code, n=n, conn=None, meta=meta, filters=filter_dict)
    return json.dumps({
        "matrix_code": matrix_code,
        "row_count": len(rows),
        "rows": rows,
    }, default=str, ensure_ascii=False)


# ---------------------------------------------------------------------------
# 5. tempo_query — aggregated data queries
# ---------------------------------------------------------------------------
@mcp.tool()
def tempo_query(
    matrix_code: str,
    filters: str | None = None,
    group_by: str | None = None,
    limit: int = 1000,
) -> str:
    """Query a dataset with filters and optional GROUP BY aggregation.

    Wraps query_builder.build_data_query() — SQL is never LLM-generated.
    Use group_by to aggregate (e.g. SUM by TIME_PERIOD, REF_AREA).
    Without group_by, returns raw rows.

    Args:
        matrix_code: Dataset identifier (e.g. 'POP101A', 'ACC101B_judete')
        filters:     Optional JSON string: {"COLUMN": ["val1","val2"], ...}
        group_by:    Optional JSON string: ["TIME_PERIOD", "SEX"]
        limit:       Max rows (default 1000, max 5000)
    """
    _ensure_imports()
    limit = min(limit, 5000)

    filter_dict = {}
    if filters:
        try:
            filter_dict = json.loads(filters)
        except json.JSONDecodeError:
            return json.dumps({"error": "Invalid JSON in filters parameter"})

    group_list = None
    if group_by:
        try:
            group_list = json.loads(group_by)
            if not isinstance(group_list, list):
                return json.dumps({"error": "group_by must be a JSON array"})
        except json.JSONDecodeError:
            return json.dumps({"error": "Invalid JSON in group_by parameter"})

    meta = get_dataset_meta(matrix_code)
    if meta is None:
        return json.dumps({"error": f"Dataset {matrix_code} not found"})

    # Determine aggregation function based on unit type
    unit_type = meta.get("profile", {}).get("primary_unit_type", "count")
    agg_func = "AVG" if unit_type in ("percentage", "time_unit") else "SUM"

    query_sql = build_data_query(
        matrix_code,
        meta["dimensions"],
        filter_dict,
        limit=limit,
        group_by=group_list,
        agg_func=agg_func,
    )

    conn = get_conn()
    try:
        rows = conn.execute(query_sql).fetchall()
        cols = [d[0] for d in conn.description]
        return json.dumps({
            "matrix_code": matrix_code,
            "columns": cols,
            "rows": [dict(zip(cols, r)) for r in rows],
            "row_count": len(rows),
            "agg_func": agg_func if group_list else None,
            "query_sql": query_sql.strip(),
        }, default=str, ensure_ascii=False)
    except Exception as e:
        log.warning("Failed to query %s: %s", matrix_code, e)
        return json.dumps({"error": f"Query failed: {e}"})


# ---------------------------------------------------------------------------
# 6. tempo_catalog_stats — corpus-level breakdowns
# ---------------------------------------------------------------------------
@mcp.tool()
def tempo_catalog_stats(
    group_by: str = "archetype",
) -> str:
    """Corpus-level statistics about the ~3,600 canonical datasets.

    Returns breakdown counts grouped by the chosen dimension.
    Useful for understanding what the corpus contains.

    Args:
        group_by: Grouping dimension — one of:
                  'archetype' (geo_time, demographic, etc.),
                  'category' (top-level INS themes),
                  'unit_type' (percentage, count, currency, etc.),
                  'geo' (has_geo true/false breakdown),
                  'time_granularity' (monthly, quarterly, yearly)
    """
    _ensure_imports()
    conn = get_conn()

    queries = {
        "archetype": """
            SELECT COALESCE(p.archetype, 'unknown') AS label,
                   COUNT(*) AS count
            FROM matrices m
            LEFT JOIN matrix_profiles p ON m.matrix_code = p.matrix_code
            WHERE m.is_canonical = TRUE
            GROUP BY label ORDER BY count DESC
        """,
        "category": """
            SELECT c.context_name AS label,
                   COUNT(*) AS count
            FROM matrices m
            JOIN contexts c ON m.ancestor_codes[1]::VARCHAR = c.context_code
            WHERE m.is_canonical = TRUE
            GROUP BY c.context_name ORDER BY count DESC
        """,
        "unit_type": """
            SELECT COALESCE(p.primary_unit_type, 'unknown') AS label,
                   COUNT(*) AS count
            FROM matrices m
            LEFT JOIN matrix_profiles p ON m.matrix_code = p.matrix_code
            WHERE m.is_canonical = TRUE
            GROUP BY label ORDER BY count DESC
        """,
        "geo": """
            SELECT CASE WHEN p.has_geo THEN 'has_geo' ELSE 'no_geo' END AS label,
                   COUNT(*) AS count
            FROM matrices m
            LEFT JOIN matrix_profiles p ON m.matrix_code = p.matrix_code
            WHERE m.is_canonical = TRUE
            GROUP BY label ORDER BY count DESC
        """,
        "time_granularity": """
            SELECT COALESCE(p.time_granularity, 'unknown') AS label,
                   COUNT(*) AS count
            FROM matrices m
            LEFT JOIN matrix_profiles p ON m.matrix_code = p.matrix_code
            WHERE m.is_canonical = TRUE
            GROUP BY label ORDER BY count DESC
        """,
    }

    if group_by not in queries:
        return json.dumps({
            "error": f"Invalid group_by: {group_by}. Must be one of: {', '.join(queries.keys())}"
        })

    try:
        rows = conn.execute(queries[group_by]).fetchall()
        total = sum(r[1] for r in rows)
        return json.dumps({
            "group_by": group_by,
            "total_datasets": total,
            "breakdown": [{"label": r[0], "count": r[1]} for r in rows],
        }, default=str, ensure_ascii=False)
    except Exception as e:
        log.warning("Failed to get catalog stats: %s", e)
        return json.dumps({"error": f"Query failed: {e}"})


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _sample_parquet(matrix_code, *, n=10, conn=None, meta=None, filters=None):
    """Read n rows from the parquet, optionally filtered."""
    _ensure_imports()
    if conn is None:
        conn = get_conn()
    parquet_path = PARQUET_DIR / f"{matrix_code}.parquet"
    if not parquet_path.exists():
        return []

    where_parts = []
    if filters:
        dims = {d["dim_column_name"] for d in (meta or {}).get("dimensions", [])}
        for col, vals in filters.items():
            if col not in dims or not vals:
                continue
            safe = ", ".join(f"'{v}'" for v in vals)
            where_parts.append(f'CAST("{col}" AS VARCHAR) IN ({safe})')

    where_sql = f"WHERE {' AND '.join(where_parts)}" if where_parts else ""

    try:
        rows = conn.execute(f"""
            SELECT * FROM read_parquet('{parquet_path}')
            {where_sql}
            LIMIT {int(n)}
        """).fetchall()
        cols = [d[0] for d in conn.description]
        return [dict(zip(cols, r)) for r in rows]
    except Exception as e:
        log.warning("Failed to sample %s: %s", matrix_code, e)
        return []


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
def main():
    log.info("Starting tempo-dev MCP server (repo=%s)", REPO_ROOT)
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
