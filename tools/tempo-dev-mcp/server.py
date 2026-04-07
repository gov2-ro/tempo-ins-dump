#!/usr/bin/env python
"""tempo-dev MCP server — 4 introspection tools for Claude Code.

Run via `.mcp.json` (repo-local) or manually:
    python tools/tempo-dev-mcp/server.py

Tools:
    tempo_dataset_info     — workhorse: full metadata + dims + charts + sample
    tempo_search_datasets  — catalog search with filters
    tempo_chart_signature  — chart_selector scores for a dataset
    tempo_sample           — labelled rows from a parquet
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
    global get_conn, PARQUET_DIR, CORPUS_DIR
    from app.services.dataset_search import search_datasets
    from app.services.dataset_meta import get_dataset_meta
    from app.services.chart_selector import build_signature, select_charts
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
