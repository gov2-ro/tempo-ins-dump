#!/usr/bin/env python
"""tempo-dev MCP server — introspection + eval tools for Claude Code.

Run via `.mcp.json` (repo-local) or manually:
    python tools/tempo-dev-mcp/server.py

Tools:
    tempo_dataset_info        — workhorse: full metadata + dims + charts + sample
    tempo_search_datasets     — catalog search with filters
    tempo_chart_signature     — chart_selector scores for a dataset
    tempo_sample              — labelled rows from a parquet
    tempo_query               — aggregated data queries via query_builder
    tempo_catalog_stats       — corpus-level breakdowns
    tempo_routes              — list every FastAPI route
    tempo_call_endpoint       — in-process TestClient call
    tempo_outdated            — datasets by ultima_actualizare staleness
    tempo_pipeline_status     — last run + recent logs + corpus audit
    tempo_dataset_lineage     — trace a matrix across pipeline stages
    tempo_check_view_profiles — audit view-profile JSONs vs corpus/DB
    tempo_eval_chart_selector — diff chart_selector vs committed baseline
    tempo_eval_agent          — diff search quality vs committed baseline
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
        n:           Number of rows (1..100, default 10)
        filters:     Optional JSON string: {"COLUMN": ["val1","val2"], ...}.
                     Unknown columns or malformed values are an error.
    """
    _ensure_imports()
    from app.services.request_validation import InvalidRequest, MISSING, parse_json_param
    try:
        filter_data = parse_json_param(filters, "filters")
        if filter_data is None:
            raise InvalidRequest("Invalid filters: expected a JSON object {column: [values]}")
        meta = get_dataset_meta(matrix_code)
        if meta is None:
            return json.dumps({"error": f"Dataset {matrix_code} not found"})
        rows = _sample_parquet(matrix_code, n=n, conn=None, meta=meta,
                               filters=None if filter_data is MISSING else filter_data)
    except InvalidRequest as e:
        return json.dumps({"error": str(e)})
    return json.dumps({
        "matrix_code": matrix_code,
        "row_count": len(rows),
        "rows": rows,
    }, default=str, ensure_ascii=False)


# ---------------------------------------------------------------------------
# 5. tempo_query — the shared data query (same as REST / Ask)
# ---------------------------------------------------------------------------
@mcp.tool()
def tempo_query(
    matrix_code: str,
    filters: str | None = None,
    group_by: str | None = None,
    limit: int = 1000,
    approximate: bool = False,
) -> str:
    """Query a dataset through the app's shared data query (`data_query.run_query`).

    Same validation, aggregation policy, effective filters and values as
    `GET /api/datasets/{code}/data` and the Ask tool. Without group_by, returns
    raw rows. A grouped query that cannot be computed safely returns
    `unavailable: true` with `aggregation.reason` — never an unsafe sum.

    Args:
        matrix_code: Dataset identifier (e.g. 'POP101A', 'ACC101B_judete')
        filters:     Optional JSON string: {"COLUMN": ["val1","val2"], ...}
        group_by:    Optional JSON string: ["TIME_PERIOD", "SEX"]
        limit:       Max rows (1..5000, default 1000)
        approximate: Allow a labelled unweighted mean for rates/averages without weights
    """
    _ensure_imports()
    from app.services.data_query import QueryError, run_query
    from app.services.request_validation import InvalidRequest, parse_json_param
    if not isinstance(limit, int) or not 1 <= limit <= 5000:
        return json.dumps({"error": "limit must be an integer in 1..5000"})
    conn = get_conn()
    try:
        res = run_query(conn, matrix_code, parse_json_param(filters, "filters"),
                        parse_json_param(group_by, "group_by"), limit,
                        approximate=bool(approximate))
    except InvalidRequest as e:
        return json.dumps({"error": str(e)})
    except QueryError as e:
        return json.dumps({"error": e.message, "status": e.status})
    finally:
        conn.close()
    return json.dumps({"matrix_code": matrix_code, **res}, default=str, ensure_ascii=False)


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
# 7. tempo_routes — list all FastAPI routes
# ---------------------------------------------------------------------------
@mcp.tool()
def tempo_routes() -> str:
    """List every FastAPI route registered on app.main:app.

    Useful as a sanity-check after mounting new routers, or to discover
    endpoints for tempo_call_endpoint. Returns JSON array of
    {methods, path, name, endpoint, tags}.
    """
    try:
        from app.main import app
    except Exception as e:
        return json.dumps({"error": f"Failed to import app.main: {e}"})

    routes = []
    for r in app.routes:
        path = getattr(r, "path", None)
        if not path:
            continue
        methods = sorted(getattr(r, "methods", []) or [])
        endpoint = getattr(r, "endpoint", None)
        ep_name = (
            f"{endpoint.__module__}.{endpoint.__name__}"
            if endpoint and hasattr(endpoint, "__module__")
            else None
        )
        routes.append({
            "methods": methods,
            "path": path,
            "name": getattr(r, "name", None),
            "endpoint": ep_name,
            "tags": list(getattr(r, "tags", []) or []),
        })
    # Sort API routes first, then static mounts
    routes.sort(key=lambda x: (not x["path"].startswith("/api"), x["path"]))
    return json.dumps({"total": len(routes), "routes": routes}, ensure_ascii=False, indent=2)


# ---------------------------------------------------------------------------
# 8. tempo_call_endpoint — hit any route via in-process TestClient
# ---------------------------------------------------------------------------
@mcp.tool()
def tempo_call_endpoint(
    method: str,
    path: str,
    params_json: str = "",
    body_json: str = "",
) -> str:
    """Call any FastAPI endpoint in-process via starlette TestClient.

    No live server required. Response body is capped to 8000 chars; if
    the response is JSON it is also parsed into `json` alongside the raw
    `body` string.

    Args:
        method:      HTTP method (GET/POST/PUT/PATCH/DELETE).
        path:        Route path, e.g. "/api/datasets/POP107D".
        params_json: Optional JSON string of query params, e.g. '{"lang":"en"}'.
        body_json:   Optional JSON string of request body for POST/PUT/PATCH.
    """
    try:
        from fastapi.testclient import TestClient
        from app.main import app
    except Exception as e:
        return json.dumps({"error": f"Failed to import app: {e}"})

    try:
        params = json.loads(params_json) if params_json.strip() else {}
    except Exception as e:
        return json.dumps({"error": f"Invalid params_json: {e}"})
    try:
        body = json.loads(body_json) if body_json.strip() else None
    except Exception as e:
        return json.dumps({"error": f"Invalid body_json: {e}"})

    m = method.upper().strip()
    client = TestClient(app, raise_server_exceptions=False)
    try:
        if m == "GET":
            resp = client.get(path, params=params)
        elif m == "DELETE":
            resp = client.delete(path, params=params)
        elif m in ("POST", "PUT", "PATCH"):
            resp = client.request(m, path, params=params, json=body)
        else:
            return json.dumps({"error": f"Unsupported method: {method}"})
    except Exception as e:
        return json.dumps({"error": f"Request failed: {e}"})

    raw = resp.text or ""
    truncated = len(raw) > 8000
    out = {
        "status_code": resp.status_code,
        "content_type": resp.headers.get("content-type"),
        "body": raw[:8000],
        "truncated": truncated,
    }
    try:
        out["json"] = resp.json()
    except Exception:
        pass
    return json.dumps(out, ensure_ascii=False, default=str, indent=2)


# ---------------------------------------------------------------------------
# 9. tempo_outdated — datasets by ultima_actualizare staleness
# ---------------------------------------------------------------------------
@mcp.tool()
def tempo_outdated(days: int = 180, limit: int = 50) -> str:
    """List datasets with stale or missing `ultima_actualizare`.

    CAVEAT: per `docs/BACKLOG.md`, `ultima_actualizare` values sourced from
    INS metadata JSONs are often stale — the column reflects what INS *claims*
    rather than the actual data freshness. Treat the list as a hint, not
    ground truth. A proposed fix (sync from `insse_news.csv`) is tracked
    in the backlog.

    Args:
        days:  Threshold in days. A dataset is "stale" if its last update is
               older than today minus this many days. Default 180.
        limit: Cap on oldest/null lists. Default 50.
    """
    _ensure_imports()
    conn = get_conn()
    days_int = int(days)  # validated/coerced — safe to inline (DuckDB INTERVAL won't bind)
    try:
        total = conn.execute("SELECT COUNT(*) FROM matrices").fetchone()[0]
        null_count = conn.execute(
            "SELECT COUNT(*) FROM matrices WHERE ultima_actualizare IS NULL"
        ).fetchone()[0]
        stale_count = conn.execute(
            "SELECT COUNT(*) FROM matrices "
            "WHERE ultima_actualizare IS NOT NULL "
            f"  AND ultima_actualizare < CURRENT_DATE - INTERVAL {days_int} DAY"
        ).fetchone()[0]
        fresh_count = total - null_count - stale_count

        oldest = conn.execute(
            "SELECT matrix_code, matrix_name, ultima_actualizare, row_count "
            "FROM matrices WHERE ultima_actualizare IS NOT NULL "
            "ORDER BY ultima_actualizare ASC LIMIT ?",
            [int(limit)],
        ).fetchall()

        null_sample = conn.execute(
            "SELECT matrix_code, matrix_name, row_count "
            "FROM matrices WHERE ultima_actualizare IS NULL "
            "ORDER BY matrix_code LIMIT ?",
            [int(limit)],
        ).fetchall()
    except Exception as e:
        return json.dumps({"error": f"Query failed: {e}"})

    return json.dumps({
        "threshold_days": int(days),
        "caveat": (
            "ultima_actualizare is sourced from INS metadata JSONs and is "
            "often stale. Treat as a hint, not ground truth."
        ),
        "counts": {
            "total": total,
            "fresh": fresh_count,
            "stale": stale_count,
            "unknown_null": null_count,
        },
        "oldest": [
            {
                "matrix_code": r[0],
                "name": r[1],
                "ultima_actualizare": r[2].isoformat() if r[2] else None,
                "row_count": r[3],
            }
            for r in oldest
        ],
        "null_sample": [
            {"matrix_code": r[0], "name": r[1], "row_count": r[2]}
            for r in null_sample
        ],
    }, ensure_ascii=False, default=str, indent=2)


# ---------------------------------------------------------------------------
# 10. tempo_pipeline_status — last run + recent logs + corpus audit
# ---------------------------------------------------------------------------
@mcp.tool()
def tempo_pipeline_status(recent_log_count: int = 10) -> str:
    """Report pipeline state: last run marker, recent log files, corpus audit.

    Reads `data/logs/last-pipeline-run.txt`, lists the most recently-modified
    log files under `data/logs/`, and loads `data/logs/corpus-audit.json`
    if present. Each recent log entry includes a count of ERROR/WARNING
    lines so you can spot regressions without opening files.

    Args:
        recent_log_count: How many recent log files to summarise. Default 10.
    """
    from pathlib import Path
    _ensure_imports()
    logs_dir = (CORPUS_DIR.parent / "logs").resolve() if CORPUS_DIR else None
    # CORPUS_DIR = data/corpus; logs_dir = data/logs
    if not logs_dir or not logs_dir.exists():
        # Fall back to repo-relative path
        logs_dir = Path(REPO_ROOT) / "data" / "logs"

    out: dict = {"logs_dir": str(logs_dir)}

    marker = logs_dir / "last-pipeline-run.txt"
    if marker.exists():
        out["last_pipeline_run"] = marker.read_text().strip()
    else:
        out["last_pipeline_run"] = None

    audit = logs_dir / "corpus-audit.json"
    if audit.exists():
        try:
            data = json.loads(audit.read_text())
            out["corpus_audit"] = {
                "timestamp": data.get("timestamp"),
                "summary": data.get("summary"),
            }
        except Exception as e:
            out["corpus_audit_error"] = str(e)

    # Recent log files by mtime
    try:
        log_files = sorted(
            [p for p in logs_dir.glob("*.log") if p.is_file()],
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )[: int(recent_log_count)]
    except Exception as e:
        return json.dumps({"error": f"Failed to list logs: {e}", **out})

    recent = []
    from datetime import datetime
    for p in log_files:
        st = p.stat()
        err_count = warn_count = 0
        try:
            # Only scan small-ish logs to avoid blowing up — cap at 2 MB
            if st.st_size < 2_000_000:
                text = p.read_text(errors="ignore")
                err_count = text.count(" - ERROR - ") + text.count("ERROR:")
                warn_count = text.count(" - WARNING - ") + text.count("WARNING:")
        except Exception:
            pass
        recent.append({
            "file": p.name,
            "mtime": datetime.fromtimestamp(st.st_mtime).isoformat(timespec="seconds"),
            "size_bytes": st.st_size,
            "errors": err_count,
            "warnings": warn_count,
        })
    out["recent_logs"] = recent
    return json.dumps(out, ensure_ascii=False, default=str, indent=2)


# ---------------------------------------------------------------------------
# 11. tempo_dataset_lineage — trace a matrix across pipeline stages
# ---------------------------------------------------------------------------
@mcp.tool()
def tempo_dataset_lineage(matrix_code: str) -> str:
    """Trace a dataset through every pipeline stage.

    Reports presence/mtime/size for artifacts in data/2-metas, data/4-datasets,
    data/parquet-v2, data/corpus/parquet, and data/corpus/view-profiles, plus
    DuckDB row presence (matrices, matrix_profiles, dataset_coverage,
    dataset_trends, dataset_value_profiles) and split/parent relationships.

    Args:
        matrix_code: Dataset identifier (e.g. 'POP107D').
    """
    from pathlib import Path
    from datetime import datetime
    _ensure_imports()
    conn = get_conn()
    root = Path(REPO_ROOT)

    mx = matrix_code.strip()
    if not mx:
        return json.dumps({"error": "matrix_code is required"})

    def _stat(p: Path) -> dict | None:
        if not p.exists():
            return None
        st = p.stat()
        return {
            "path": str(p.relative_to(root)),
            "size_bytes": st.st_size,
            "mtime": datetime.fromtimestamp(st.st_mtime).isoformat(timespec="seconds"),
        }

    stages = {
        "metadata_json": _stat(root / "data" / "2-metas" / "ro" / f"{mx}.json"),
        "raw_csv":       _stat(root / "data" / "4-datasets" / "ro" / f"{mx}.csv"),
        "parquet_v2":    _stat(root / "data" / "parquet-v2" / "ro" / f"{mx}.parquet"),
        "corpus_parquet":_stat(root / "data" / "corpus" / "parquet" / f"{mx}.parquet"),
        "view_profile":  _stat(root / "data" / "corpus" / "view-profiles" / f"{mx}.json"),
    }

    # DuckDB state
    matrix_row = conn.execute(
        "SELECT matrix_code, matrix_name, row_count, ultima_actualizare, "
        "       is_split, parent_matrix_code, is_canonical "
        "FROM matrices WHERE matrix_code = ?",
        [mx],
    ).fetchone()

    if not matrix_row:
        return json.dumps({
            "matrix_code": mx,
            "error": "Not found in matrices table",
            "stages": stages,
        }, ensure_ascii=False, default=str, indent=2)

    db_state = {
        "matrices": {
            "name": matrix_row[1],
            "row_count": matrix_row[2],
            "ultima_actualizare": matrix_row[3].isoformat() if matrix_row[3] else None,
            "is_split": matrix_row[4],
            "parent_matrix_code": matrix_row[5],
            "is_canonical": matrix_row[6],
        },
    }

    # Presence checks for auxiliary tables
    for table in (
        "matrix_profiles",
        "dataset_coverage",
        "dataset_trends",
        "dataset_value_profiles",
    ):
        try:
            row = conn.execute(
                f"SELECT COUNT(*) FROM {table} WHERE matrix_code = ?", [mx]
            ).fetchone()
            db_state[table] = {"exists": bool(row and row[0] > 0)}
        except Exception as e:
            db_state[table] = {"error": str(e)}

    # Dimensions count
    try:
        dim_count = conn.execute(
            "SELECT COUNT(*) FROM dimensions WHERE matrix_code = ?", [mx]
        ).fetchone()[0]
        db_state["dimensions_count"] = dim_count
    except Exception:
        pass

    # Splits + parent info
    splits_info: dict = {}
    try:
        children = conn.execute(
            "SELECT matrix_code FROM matrices WHERE parent_matrix_code = ? "
            "ORDER BY matrix_code",
            [mx],
        ).fetchall()
        splits_info["children"] = [r[0] for r in children]
    except Exception:
        pass
    if matrix_row[5]:  # parent_matrix_code
        splits_info["parent"] = matrix_row[5]

    return json.dumps({
        "matrix_code": mx,
        "stages": stages,
        "db_state": db_state,
        "splits": splits_info,
    }, ensure_ascii=False, default=str, indent=2)


# ---------------------------------------------------------------------------
# 12. tempo_check_view_profiles — audit view-profile JSONs
# ---------------------------------------------------------------------------
@mcp.tool()
def tempo_check_view_profiles() -> str:
    """Audit `data/corpus/view-profiles/` for inconsistencies.

    Cross-checks the view-profile JSON files against the parquet corpus and
    the DB `matrix_profiles` table. Surfaces:

      - missing_vps        — parquet files with no corresponding VP JSON
      - orphan_vps         — VP JSONs with no corresponding parquet
      - version_drift      — VPs whose profile_version < current version
      - archetype_mismatches — VPs whose `archetype` differs from the
        canonical `matrix_profiles.archetype` (only checked for codes
        that appear in the matrices table)
      - profiles_with_warnings — count of VPs carrying non-empty `warnings[]`
      - stale_files         — files with `_stale` in the name

    Output is purely diagnostic — no baseline to diff against. Use before
    running the generator after a schema change, or to investigate "why is
    dataset X missing from the UI?".
    """
    from pathlib import Path
    _ensure_imports()

    root = Path(REPO_ROOT)
    vp_dir = root / "data" / "corpus" / "view-profiles"
    parquet_dir = root / "data" / "corpus" / "parquet"

    if not vp_dir.exists():
        return json.dumps({"error": f"View profiles dir not found: {vp_dir.relative_to(root)}"})
    if not parquet_dir.exists():
        return json.dumps({"error": f"Parquet dir not found: {parquet_dir.relative_to(root)}"})

    # Resolve the current profile_version from the generator module (best-effort)
    current_version: int | None = None
    try:
        import importlib.util
        gen_path = root / "generate_view_profiles.py"
        if gen_path.exists():
            spec = importlib.util.spec_from_file_location("_gen", gen_path)
            gen = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(gen)  # type: ignore[union-attr]
            current_version = getattr(gen, "PROFILE_VERSION", None)
    except Exception as e:
        log.warning("Could not load PROFILE_VERSION from generate_view_profiles.py: %s", e)

    # Skip leading-underscore files (e.g. `_index.json`), they're meta files
    # emitted by the generator, not per-dataset profiles.
    vp_files = sorted(p for p in vp_dir.glob("*.json") if not p.name.startswith("_"))
    stale_files = sorted(p.name for p in vp_dir.glob("*_stale*"))
    parquet_files = {p.stem for p in parquet_dir.glob("*.parquet")}
    vp_codes = {p.stem for p in vp_files}

    missing_vps = sorted(parquet_files - vp_codes)
    orphan_vps = sorted(vp_codes - parquet_files)

    conn = get_conn()
    db_archetypes: dict[str, str | None] = dict(conn.execute(
        "SELECT matrix_code, archetype FROM matrix_profiles"
    ).fetchall())

    version_drift: list[dict] = []
    archetype_mismatches: list[dict] = []
    profiles_with_warnings = 0
    warning_buckets: dict[str, list[str]] = {}
    parse_errors: list[dict] = []

    for p in vp_files:
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except Exception as e:
            parse_errors.append({"matrix_code": p.stem, "error": str(e)})
            continue

        meta = data.get("meta") or {}
        vp_version = meta.get("profile_version")
        if current_version is not None and vp_version != current_version:
            version_drift.append({
                "matrix_code": p.stem,
                "vp_version": vp_version,
                "current_version": current_version,
            })

        mc = data.get("matrix_code") or p.stem
        db_arch = db_archetypes.get(mc)
        vp_arch = data.get("archetype")
        if db_arch is not None and vp_arch != db_arch:
            archetype_mismatches.append({
                "matrix_code": mc,
                "vp_archetype": vp_arch,
                "db_archetype": db_arch,
            })

        warnings = data.get("warnings") or []
        if warnings:
            profiles_with_warnings += 1
            for w in warnings:
                key = w if isinstance(w, str) else (w.get("type") or w.get("code") or "unknown")
                warning_buckets.setdefault(key, []).append(mc)

    top_warnings = [
        {"warning": k, "count": len(v), "sample_matrix_codes": sorted(v)[:5]}
        for k, v in sorted(warning_buckets.items(), key=lambda kv: len(kv[1]), reverse=True)
    ][:10]

    return json.dumps({
        "summary": {
            "parquet_files": len(parquet_files),
            "view_profiles": len(vp_files),
            "stale_files": len(stale_files),
            "missing_vps": len(missing_vps),
            "orphan_vps": len(orphan_vps),
            "version_drift": len(version_drift),
            "archetype_mismatches": len(archetype_mismatches),
            "profiles_with_warnings": profiles_with_warnings,
            "parse_errors": len(parse_errors),
            "current_profile_version": current_version,
        },
        "missing_vps": missing_vps[:30],
        "orphan_vps": orphan_vps[:30],
        "version_drift": version_drift[:30],
        "archetype_mismatches": archetype_mismatches[:30],
        "top_warnings": top_warnings,
        "parse_errors": parse_errors[:20],
        "stale_files": stale_files[:20],
    }, ensure_ascii=False, default=str, indent=2)


# ---------------------------------------------------------------------------
# 13. tempo_eval_chart_selector — diff chart selector vs committed baseline
# ---------------------------------------------------------------------------
@mcp.tool()
def tempo_eval_chart_selector(score_threshold: float = 0.05) -> str:
    """Re-score every dataset and diff against the committed chart_selector baseline.

    Loads `data/eval/chart_selector_baseline.json` (produced by
    `scripts/build_chart_selector_baseline.py`), re-runs `evaluate_all()` on
    the current code, and returns a compact regression report.

    Flags four kinds of drift:
      - primary_changes   — top-ranked chart_type changed (always full list)
      - top_set_changes   — topN set of chart types changed
      - confidence_changes — same primary but different confidence bucket
      - score_drifts      — primary unchanged, score moved by ≥ threshold

    Also reports `missing` (in baseline but not in current) and `added`
    (in current but not in baseline) — useful after adding/removing datasets.

    To refresh the baseline after intentional changes, run:
        python scripts/build_chart_selector_baseline.py

    Args:
        score_threshold: Min primary-score delta to flag as drift (default 0.05).
    """
    from pathlib import Path
    _ensure_imports()
    from app.services.chart_selector_eval import evaluate_all, diff_against_baseline

    baseline_path = Path(REPO_ROOT) / "data" / "eval" / "chart_selector_baseline.json"
    if not baseline_path.exists():
        return json.dumps({
            "error": f"Baseline not found at {baseline_path.relative_to(Path(REPO_ROOT))}. "
                     f"Run: python scripts/build_chart_selector_baseline.py",
        })

    try:
        baseline_doc = json.loads(baseline_path.read_text(encoding="utf-8"))
    except Exception as e:
        return json.dumps({"error": f"Failed to parse baseline: {e}"})

    baseline = baseline_doc.get("datasets") or {}
    baseline_version = baseline_doc.get("version")

    try:
        current = evaluate_all(top_n=3)
    except Exception as e:
        log.exception("evaluate_all failed")
        return json.dumps({"error": f"evaluate_all failed: {e}"})

    report = diff_against_baseline(baseline, current, score_threshold=float(score_threshold))
    report["baseline_path"] = str(baseline_path.relative_to(Path(REPO_ROOT)))
    report["baseline_version"] = baseline_version
    return json.dumps(report, ensure_ascii=False, default=str, indent=2)


# ---------------------------------------------------------------------------
# 14. tempo_eval_agent — regression test for the agent's retrieval layer
# ---------------------------------------------------------------------------
@mcp.tool()
def tempo_eval_agent() -> str:
    """Re-run the search-quality eval and diff against the committed baseline.

    Runs `search_datasets()` for every question in
    `data/eval/agent_questions.yaml` and compares the top-K hits to the
    baseline at `data/eval/agent_search_baseline.json`. Use after any
    change that could affect retrieval: FTS index rebuild, ranking
    tweaks, corpus updates, new splits.

    Drift categories:
      - top_set_changes   — top-K set of matrix_codes differs (always full)
      - order_changes     — same set but ordering shifted (cap 30)
      - total_hit_drifts  — `total_hits` changed by >20% (cap 20, signals
        FTS scope shifts)
      - missing / added   — questions gained/lost between runs

    To refresh the baseline after an intentional change:

        python scripts/build_agent_search_baseline.py

    This is search-quality regression detection, NOT a golden-answer test.
    The baseline captures whatever the search returns today — a human
    still has to review the diff to decide if a drift is an improvement
    or a regression.
    """
    from pathlib import Path
    _ensure_imports()
    from app.services.agent_eval import (
        load_questions,
        run_search_eval,
        diff_against_baseline,
    )

    root = Path(REPO_ROOT)
    questions_path = root / "data" / "eval" / "agent_questions.yaml"
    baseline_path = root / "data" / "eval" / "agent_search_baseline.json"

    if not questions_path.exists():
        return json.dumps({
            "error": f"Questions file not found at {questions_path.relative_to(root)}",
        })
    if not baseline_path.exists():
        return json.dumps({
            "error": f"Baseline not found at {baseline_path.relative_to(root)}. "
                     f"Run: python scripts/build_agent_search_baseline.py",
        })

    try:
        baseline_doc = json.loads(baseline_path.read_text(encoding="utf-8"))
    except Exception as e:
        return json.dumps({"error": f"Failed to parse baseline: {e}"})

    try:
        questions = load_questions(questions_path)
    except Exception as e:
        return json.dumps({"error": f"Failed to load questions: {e}"})

    try:
        current = run_search_eval(questions, top_k=int(baseline_doc.get("top_k") or 10))
    except Exception as e:
        log.exception("run_search_eval failed")
        return json.dumps({"error": f"run_search_eval failed: {e}"})

    report = diff_against_baseline(baseline_doc, current)
    report["baseline_path"] = str(baseline_path.relative_to(root))
    report["questions_path"] = str(questions_path.relative_to(root))
    report["baseline_version"] = baseline_doc.get("version")
    return json.dumps(report, ensure_ascii=False, default=str, indent=2)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _sample_parquet(matrix_code, *, n=10, conn=None, meta=None, filters=None):
    """Read n rows from the parquet, optionally filtered.

    Filters are validated against the file's own columns (unknown column or bad
    shape -> InvalidRequest) and every value and the path are bound parameters.
    """
    _ensure_imports()
    from app.services.query_builder import quote_ident
    from app.services.request_validation import InvalidRequest, MISSING, validate_filters
    if not isinstance(n, int) or isinstance(n, bool) or not 1 <= n <= 100:
        raise InvalidRequest("n must be an integer in 1..100")
    if conn is None:
        conn = get_conn()
    parquet_path = PARQUET_DIR / f"{matrix_code}.parquet"
    if not parquet_path.exists():
        return []
    path = str(parquet_path)
    cols = [r[0] for r in conn.execute(
        "DESCRIBE SELECT * FROM read_parquet(?)", [path]).fetchall()]
    allowed = [c for c in cols if c not in ("OBS_VALUE", "value")]
    checked = validate_filters(MISSING if filters is None else filters, allowed)

    where, params = [], [path]
    for col, vals in checked.items():
        if not vals:
            continue
        where.append(f"CAST({quote_ident(col)} AS VARCHAR) IN ({', '.join('?' for _ in vals)})")
        params.extend(str(v) for v in vals)
    where_sql = f"WHERE {' AND '.join(where)}" if where else ""
    try:
        rows = conn.execute(
            f"SELECT * FROM read_parquet(?) {where_sql} LIMIT ?", [*params, n]).fetchall()
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
