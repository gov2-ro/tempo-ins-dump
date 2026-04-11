"""NL→Data agent for the INS TEMPO explorer.

Exposes run_agent(question, history) which calls an LLM in a tool-calling loop
over 4 tools: search_datasets, get_dataset_schema, query_dataset_data, list_categories.

All data access goes through the existing safe service layer — the LLM never
generates SQL directly.
"""
import json
import logging
import re
from dataclasses import dataclass, field

from app import config
from app.db import get_conn
from app.services.llm_client import complete_with_tools

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Tool definitions (JSON Schema, provider-agnostic)
# ---------------------------------------------------------------------------

TOOLS = [
    {
        "name": "search_datasets",
        "description": (
            "Search the catalog of ~3,600 Romanian INS statistical datasets. "
            "Returns top matches ranked by relevance to the query text. "
            "Supports Romanian and English keywords. "
            "Use this FIRST when you don't know the exact matrix_code. "
            "Returns: matrix_code, name, archetype, time_range, has_geo, "
            "primary_unit_type, is_split, parent_matrix_code for each hit."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query":     {"type": "string", "description": "Free-text query in Romanian or English"},
                "has_geo":   {"type": "boolean", "description": "Filter to datasets with geographic dimension"},
                "archetype": {
                    "type": "string",
                    "enum": ["geo_time", "demographic", "time_residence", "time_series"],
                    "description": "Filter by dataset archetype",
                },
                "limit": {"type": "integer", "default": 10, "maximum": 15},
            },
            "required": ["query"],
        },
    },
    {
        "name": "get_dataset_schema",
        "description": (
            "Fetch the full schema for a dataset: dimensions (with type and available values, "
            "capped to 100/dim), time coverage, splits, and definition. "
            "ALWAYS call this before query_dataset_data — never guess column names or values. "
            "If is_split=true, the response lists sub-datasets; usually pick the one matching "
            "the user's granularity (e.g. '_judete' for county-level, '_national' for totals)."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "matrix_code": {"type": "string", "description": "Dataset identifier, e.g. 'POP101A'"},
            },
            "required": ["matrix_code"],
        },
    },
    {
        "name": "query_dataset_data",
        "description": (
            "Query a dataset's data with optional filters and GROUP BY aggregation. "
            "Returns up to 5,000 rows. Filters MUST use exact dimension values from get_dataset_schema. "
            "Use group_by to aggregate (e.g. ['TIME_PERIOD','REF_AREA']) — this is essential for "
            "large datasets; do not pull raw rows when a grouped summary suffices. "
            "If 0 rows are returned, try removing 'Total'/'TOTAL' filters."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "matrix_code": {"type": "string"},
                "filters": {
                    "type": "object",
                    "description": "Dict of {column_name: [value, ...]}. Values must be exact strings from the schema.",
                },
                "group_by": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Columns to SELECT + aggregate on. Other numeric columns are SUM'd (or AVG for percentages).",
                },
            },
            "required": ["matrix_code"],
        },
    },
    {
        "name": "list_categories",
        "description": (
            "Return the top-level INS category tree (themes and sub-themes). "
            "Useful when the user asks about a broad topic area rather than a specific indicator."
        ),
        "input_schema": {"type": "object", "properties": {}},
    },
]

# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """Assistant for the Romanian National Institute of Statistics (INS) TEMPO Online explorer. Access to ~3,600 datasets covering demographics, economy, labor, health, education, agriculture, geography, from the 1990s onward.

Reply in the user's language (RO or EN). Dataset names in the catalog are Romanian — always search in Romanian first, translating key terms via the vocabulary below.

## Workflow — mandatory
1. search_datasets with 2-3 Romanian keywords. Strip stopwords ("rate", "by", "in", "for", year numbers). Never set has_geo=true on the first search (it excludes national-level datasets, which are often the best match).
2. Scan ALL results, not just position 1. A good match at position 6 beats a poor match at position 1. Look for keyword matches in the `name` field.
3. If the first results look unrelated, retry with different keywords (RO↔EN swap, drop a qualifier). Don't give up after one search.
4. Before concluding "no match", you MUST call get_dataset_schema on the best candidate AND query_dataset_data to fetch actual numbers. "The name doesn't look exact" is never a valid reason to stop — call get_dataset_schema to find out.
5. Never ask "would you like me to fetch X?". Just fetch it and caveat in the answer.
6. If the user's requested granularity doesn't exist (e.g. wants county-level but only regional exists), use the closest available and state the limitation in one sentence. INS publishes most labor-market and macro indicators at `regiuni de dezvoltare` (8 NUTS-2 regions), NOT `județe` (42 counties).
7. For split datasets (is_split=true), pick the sub-dataset matching user granularity: "_judete" for county, "_national" for national.
8. Always get_dataset_schema before query_dataset_data — never guess columns or values.
9. Use group_by for aggregate questions (trends, comparisons, rankings). Don't pull raw rows when a grouped summary suffices.

## Vocabulary
- șomaj / rata șomajului → unemployment / rate
- pe județe → by county (REF_AREA, 42)
- pe regiuni → by region (REF_AREA, 8 NUTS-2)
- pe sexe → by gender (SEX: Masculin/Feminin)
- pe grupe de vârstă → by age (AGE)
- IPC → CPI, PIB → GDP, salarii → wages, natalitate → births, mortalitate → deaths

## Warnings on query results
- "Auto-applied Total filters" → already corrected; trust numbers.
- "POSSIBLE DOUBLE-COUNTING" → re-query with one explicit Total filter as suggested.
- "Retried after removing Total" → your filter was empty; handler dropped it.
If a Total-filtered query returns 0 rows, retry without the Total filter.

## Answer format
Plain-language summary in the user's language + cited matrix_code(s) in parentheses (e.g. AMG159E). Don't invent codes. Decline questions unrelated to Romanian statistics.
"""

# ---------------------------------------------------------------------------
# Agent result
# ---------------------------------------------------------------------------

@dataclass
class AgentResult:
    answer: str
    citations: list[str] = field(default_factory=list)
    tool_trace: list[dict] = field(default_factory=list)
    data: dict | None = None
    chart_spec: dict | None = None
    warnings: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Tool handlers
# ---------------------------------------------------------------------------

def _handle_search_datasets(inp: dict, conn) -> dict:
    from app.services.dataset_search import search_datasets
    result = search_datasets(
        q=inp.get("query", ""),
        has_geo=inp.get("has_geo"),
        archetype=inp.get("archetype"),
        limit=min(int(inp.get("limit", 10)), 15),
        conn=conn,
    )
    # Return compact cards — strip fields the LLM doesn't need
    cards = []
    for d in result.get("datasets", []):
        cards.append({
            "matrix_code": d["matrix_code"],
            "name": d["matrix_name"],
            "time_range": d.get("time_range"),
            "has_geo": d.get("has_geo"),
            "is_split": d.get("is_split"),
        })
    return {"total": result.get("total", 0), "datasets": cards}


def _handle_get_dataset_schema(inp: dict, conn) -> dict:
    from app.services.dataset_meta import get_dataset_meta
    matrix_code = inp.get("matrix_code", "").strip()
    meta = get_dataset_meta(matrix_code, conn=conn)
    if meta is None:
        return {"error": f"Dataset '{matrix_code}' not found"}

    dims = []
    for d in meta.get("dimensions", []):
        opts = d.get("options", [])
        dims.append({
            "column": d["dim_column_name"],
            "label": d["dim_label"],
            "type": d.get("dim_type"),
            "option_count": d.get("option_count"),
            "values": [o["sdmx_value"] for o in opts[:20] if o.get("sdmx_value")],
        })

    cov = meta.get("coverage") or {}
    return {
        "matrix_code": meta["matrix_code"],
        "name": meta["matrix_name"],
        "definition": (meta.get("definitie") or "")[:400],
        "row_count": meta.get("row_count"),
        "archetype": meta.get("profile", {}).get("archetype"),
        "time_range": f"{cov.get('time_min_year')}–{cov.get('time_max_year')}" if cov.get("time_min_year") else None,
        "time_granularity": cov.get("time_granularity"),
        "is_split": meta.get("is_split"),
        "splits": [
            {"matrix_code": s["matrix_code"], "label": s.get("label")}
            for s in meta.get("splits", [])
        ],
        "parent_matrix_code": meta.get("parent_matrix_code"),
        "dimensions": dims,
    }


def _handle_query_dataset_data(inp: dict, conn) -> dict:
    from app.services.query_builder import build_data_query
    from app.config import LARGE_DATASET_THRESHOLD

    matrix_code = inp.get("matrix_code", "").strip()
    filters = inp.get("filters") or {}
    group_by = inp.get("group_by") or None
    limit = 5000

    if not matrix_code:
        return {"error": "matrix_code is required"}

    # Check dataset exists
    matrix = conn.execute(
        "SELECT row_count FROM matrices WHERE matrix_code = ?", [matrix_code]
    ).fetchone()
    if not matrix:
        return {"error": f"Dataset '{matrix_code}' not found"}

    row_count = matrix[0] or 0

    # Require filters or group_by for large datasets
    if row_count > LARGE_DATASET_THRESHOLD and not filters and not group_by:
        return {
            "error": f"Dataset has {row_count:,} rows. Provide filters or group_by to narrow results.",
            "suggestion": "Use get_dataset_schema to see available dimension values, then filter or group.",
        }

    # Get dimensions (with legacy column resolution)
    dims = conn.execute(
        "SELECT dim_code, dim_label, dim_column_name FROM dimensions WHERE matrix_code = ? ORDER BY dim_code",
        [matrix_code],
    ).fetchall()
    dimensions = [{"dim_code": d[0], "dim_label": d[1], "dim_column_name": d[2]} for d in dims]

    if any(d["dim_column_name"].endswith("_nom_id") for d in dimensions):
        parent_row = conn.execute(
            "SELECT parent_matrix_code FROM matrices WHERE matrix_code = ?", [matrix_code]
        ).fetchone()
        lookup_code = (parent_row[0] or matrix_code) if parent_row else matrix_code
        col_map = dict(conn.execute(
            "SELECT old_column_name, sdmx_column_name FROM sdmx_column_map WHERE matrix_code = ?",
            [lookup_code],
        ).fetchall())
        for d in dimensions:
            if d["dim_column_name"].endswith("_nom_id"):
                d["dim_column_name"] = col_map.get(d["dim_column_name"], d["dim_column_name"])

    # Aggregation function
    agg_func = "SUM"
    if group_by:
        unit_row = conn.execute(
            "SELECT primary_unit_type FROM matrix_profiles WHERE matrix_code = ?", [matrix_code]
        ).fetchone()
        if unit_row and unit_row[0] in ("percentage", "time_unit"):
            agg_func = "AVG"

    warnings = []

    def _execute_query(f):
        sql = build_data_query(matrix_code, dimensions, f, limit + 1, group_by=group_by, agg_func=agg_func)
        return conn.execute(sql).fetchall()

    # ----------------------------------------------------------------------
    # Anti double-counting: when aggregating, dims that are neither grouped
    # nor explicitly filtered will be SUM'd over. If such a dim publishes a
    # marginal `Total` row alongside its breakdown rows, the SUM adds the
    # aggregate + the components and double-counts. Detect those dims, lock
    # them to their Total value, and warn. If locking returns 0 rows (the
    # dataset uses non-cross-product marginals — see AMG1010), fall back to
    # the unfiltered query but emit a loud warning so the LLM can re-query.
    # ----------------------------------------------------------------------
    rows = None
    if group_by:
        total_locks = _detect_total_locks(matrix_code, dimensions, filters, group_by, conn)
        if total_locks:
            locked_filters = {**filters, **total_locks}
            try:
                test_rows = _execute_query(locked_filters)
            except Exception:
                test_rows = None
            if test_rows:
                filters = locked_filters
                rows = test_rows
                warnings.append(
                    "Auto-applied Total filters to prevent double-counting: "
                    + ", ".join(f"{c}={vs[0]}" for c, vs in total_locks.items())
                )
            else:
                first_dim = next(iter(total_locks))
                first_val = total_locks[first_dim][0]
                warnings.append(
                    "POSSIBLE DOUBLE-COUNTING: dim(s) "
                    + ", ".join(total_locks.keys())
                    + " have 'Total' options. Locking them all returned 0 rows, so the "
                    + "dataset publishes non-cross-product marginal totals. The current "
                    + "result may sum aggregate + breakdown rows. Re-query with a single "
                    + f"explicit Total filter, e.g. filters={{'{first_dim}': ['{first_val}']}}."
                )

    if rows is None:
        try:
            rows = _execute_query(filters)
        except Exception as e:
            return {"error": f"Query failed: {e}"}

    # Auto-retry: strip "Total"/"TOTAL" filter values if 0 rows
    if len(rows) == 0 and filters:
        stripped = {
            col: [v for v in vals if str(v).upper() != "TOTAL"]
            for col, vals in filters.items()
        }
        stripped = {col: vals for col, vals in stripped.items() if vals}
        if stripped != filters:
            try:
                rows = _execute_query(stripped)
                if rows:
                    warnings.append("Retried query after removing 'Total' filter values.")
                    filters = stripped
            except Exception:
                pass

    truncated = len(rows) > limit
    rows = rows[:limit]

    # Determine result columns
    if group_by:
        dim_by_col = {d["dim_column_name"]: d for d in dimensions}
        result_dims = [dim_by_col[c] for c in group_by if c in dim_by_col]
        if not result_dims:
            result_dims = dimensions
    else:
        result_dims = dimensions

    columns = [d["dim_column_name"] for d in result_dims] + ["OBS_VALUE"]
    data_rows = [list(r) for r in rows]

    return {
        "matrix_code": matrix_code,
        "columns": columns,
        "rows": data_rows,
        "row_count": len(data_rows),
        "truncated": truncated,
        "warnings": warnings,
    }


def _detect_total_locks(
    matrix_code: str,
    dimensions: list[dict],
    filters: dict,
    group_by: list[str],
    conn,
) -> dict[str, list[str]]:
    """Find dims eligible for auto-Total locking to prevent double-counting.

    A dim is eligible when, for the given query shape, it is neither in
    `group_by` nor in `filters`, and the parquet contains at least one row
    where TRIM(LOWER(col)) == 'total'. Returns {col: [actual_value]} using
    the value as it appears in the parquet (preserves case/whitespace).

    `TIME_PERIOD` is never locked.
    """
    from pathlib import Path
    from app.config import PARQUET_DIR

    p = Path(PARQUET_DIR) / f"{matrix_code}.parquet"
    if not p.exists():
        return {}

    grouped = set(group_by or [])
    filtered = set(filters.keys())
    candidates = [
        d["dim_column_name"] for d in dimensions
        if d["dim_column_name"] not in grouped
        and d["dim_column_name"] not in filtered
        and d["dim_column_name"] != "TIME_PERIOD"
    ]
    if not candidates:
        return {}

    locks: dict[str, list[str]] = {}
    for col in candidates:
        try:
            rows = conn.execute(
                f'SELECT DISTINCT "{col}" FROM read_parquet(\'{p}\') '
                f'WHERE LOWER(TRIM(CAST("{col}" AS VARCHAR))) = \'total\''
            ).fetchall()
            if rows:
                locks[col] = [r[0] for r in rows]
        except Exception:
            continue
    return locks


def _handle_list_categories(inp: dict, conn) -> dict:
    # Return top-2 levels only (themes + sub-themes) — the full tree has ~200 nodes
    rows = conn.execute(
        "SELECT context_code, context_name, parent_code, level "
        "FROM contexts WHERE level <= 2 ORDER BY context_code"
    ).fetchall()
    return {
        "categories": [
            {"code": r[0], "name": r[1], "parent_code": r[2], "level": r[3]}
            for r in rows
        ]
    }


TOOL_HANDLERS = {
    "search_datasets":    _handle_search_datasets,
    "get_dataset_schema": _handle_get_dataset_schema,
    "query_dataset_data": _handle_query_dataset_data,
    "list_categories":    _handle_list_categories,
}

# ---------------------------------------------------------------------------
# Agent loop
# ---------------------------------------------------------------------------

def run_agent(
    question: str,
    history: list[dict] | None = None,
    *,
    provider: str | None = None,
    model: str | None = None,
    api_key: str | None = None,
) -> AgentResult:
    """Run the NL→Data agent loop.

    Args:
        question: User's natural language question.
        history:  Prior conversation turns in the format [{role, content}, ...].
        provider: LLM provider override ("anthropic" | "openai"). None → env default.
        model:    Model ID override. None → env default.
        api_key:  BYOK API key. None → reads from env (default behaviour).
                  Passed directly to the LLM as message history.

    Returns:
        AgentResult with answer, citations, tool_trace, data, chart_spec, warnings.
    """
    conn = get_conn()
    messages = list(history or [])
    messages.append({"role": "user", "content": question})

    tool_trace = []
    last_query_result = None
    last_queried_matrix = None
    agent_warnings = []
    _guardrail_fired = False  # one-shot: only inject the data-query nudge once per run

    for iteration in range(config.ASK_MAX_TOOL_CALLS + 1):
        if config.DEBUG:
            log.debug("Agent iteration %d, %d messages", iteration, len(messages))

        resp = complete_with_tools(messages, TOOLS, system=SYSTEM_PROMPT,
                                   provider=provider, model=model, api_key=api_key)

        if resp.text:
            # LLM produced a text response — may be mixed with tool calls
            pass

        if not resp.tool_calls or resp.stop_reason == "end_turn":
            # Guardrail: model gave up without querying data, but search returned results.
            # Inject one synthetic user turn to force schema + query. Fires once per run.
            # Primarily targets OpenAI models that ignore "MUST call query_dataset_data".
            search_had_results = any(
                t["tool"] == "search_datasets" and t["output"].get("total", 0) > 0
                for t in tool_trace
            )
            if not _guardrail_fired and last_query_result is None and search_had_results:
                _guardrail_fired = True
                if resp.text or resp.tool_calls:
                    messages.append(_assistant_turn(resp, provider=provider or config.LLM_PROVIDER))
                messages.append({
                    "role": "user",
                    "content": (
                        "You found relevant datasets but did not query any data. "
                        "Please call get_dataset_schema on the most relevant dataset, "
                        "then call query_dataset_data to retrieve actual numbers before answering."
                    ),
                })
                agent_warnings.append("Guardrail: model skipped data query — injected follow-up turn.")
                log.debug("Guardrail fired at iteration %d", iteration)
                continue

            # Done — extract final answer
            answer = resp.text or "(no answer)"
            citations = _extract_citations(answer, tool_trace)
            chart_spec = _get_chart_spec(last_queried_matrix, conn) if last_queried_matrix else None
            return AgentResult(
                answer=answer,
                citations=citations,
                tool_trace=tool_trace,
                data=last_query_result,
                chart_spec=chart_spec,
                warnings=agent_warnings,
            )

        if iteration >= config.ASK_MAX_TOOL_CALLS:
            agent_warnings.append("Reached tool call limit without a final answer.")
            answer = resp.text or "I reached the maximum number of tool calls. Please try a more specific question."
            citations = _extract_citations(answer, tool_trace)
            return AgentResult(
                answer=answer,
                citations=citations,
                tool_trace=tool_trace,
                data=last_query_result,
                chart_spec=_get_chart_spec(last_queried_matrix, conn) if last_queried_matrix else None,
                warnings=agent_warnings,
            )

        # Append the assistant turn (with tool_use blocks for Anthropic)
        messages.append(_assistant_turn(resp, provider=provider or config.LLM_PROVIDER))

        # Dispatch all tool calls in this turn
        tool_result_messages = []
        for tc in resp.tool_calls:
            handler = TOOL_HANDLERS.get(tc["name"])
            if handler:
                try:
                    result = handler(tc["input"], conn)
                except Exception as e:
                    log.exception("Tool %s failed", tc["name"])
                    result = {"error": str(e)}
            else:
                result = {"error": f"Unknown tool: {tc['name']}"}

            result_str = json.dumps(result, ensure_ascii=False, default=str)

            tool_trace.append({
                "tool": tc["name"],
                "input": tc["input"],
                "output": result,
            })

            if tc["name"] == "query_dataset_data" and "error" not in result:
                last_query_result = result
                last_queried_matrix = tc["input"].get("matrix_code")
                if result.get("warnings"):
                    agent_warnings.extend(result["warnings"])

            tool_result_messages.append({
                "role": "tool",
                "tool_use_id": tc["id"],
                "content": result_str,
            })

        # For Anthropic: all tool results go in a single user turn
        # For OpenAI/Gemini: each tool result is its own message
        prov = provider or config.LLM_PROVIDER
        if prov == "anthropic":
            messages.append(_anthropic_tool_results_turn(tool_result_messages))
        else:
            messages.extend(tool_result_messages)

    # Should not reach here
    return AgentResult(answer="Unexpected agent termination.", warnings=["Agent loop exited unexpectedly."])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _assistant_turn(resp, provider: str | None = None) -> dict:
    """Build an assistant message from an LLMResponse."""
    prov = provider or config.LLM_PROVIDER
    if prov == "anthropic":
        content = []
        if resp.text:
            content.append({"type": "text", "text": resp.text})
        for tc in resp.tool_calls:
            content.append({"type": "tool_use", "id": tc["id"], "name": tc["name"], "input": tc["input"]})
        return {"role": "assistant", "content": content}
    else:
        # OpenAI format
        import json as _json
        return {
            "role": "assistant",
            "content": resp.text,
            "tool_calls": [
                {
                    "id": tc["id"],
                    "type": "function",
                    "function": {"name": tc["name"], "arguments": _json.dumps(tc["input"])},
                }
                for tc in resp.tool_calls
            ] if resp.tool_calls else None,
        }


def _anthropic_tool_results_turn(tool_result_messages: list[dict]) -> dict:
    """Anthropic expects all tool results in a single user message."""
    return {
        "role": "user",
        "content": [
            {
                "type": "tool_result",
                "tool_use_id": m["tool_use_id"],
                "content": m["content"],
            }
            for m in tool_result_messages
        ],
    }


def _extract_citations(answer: str, tool_trace: list[dict]) -> list[str]:
    """Extract matrix_codes from the answer text and tool trace."""
    codes = set()
    # From tool trace
    for entry in tool_trace:
        if entry["tool"] in ("get_dataset_schema", "query_dataset_data"):
            mc = entry["input"].get("matrix_code")
            if mc:
                codes.add(mc)
    # Also scan answer for parenthesised codes like (POP101A_judete)
    for match in re.finditer(r'\(([A-Z][A-Z0-9_]{3,})\)', answer):
        codes.add(match.group(1))
    return sorted(codes)


def _get_chart_spec(matrix_code: str, conn) -> dict | None:
    """Build chart spec for the last queried dataset."""
    try:
        from app.services.dataset_meta import get_dataset_meta
        meta = get_dataset_meta(matrix_code, conn=conn)
        if meta:
            return meta.get("chart_config")
    except Exception:
        pass
    return None
