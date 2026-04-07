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
                "limit": {"type": "integer", "default": 10, "maximum": 25},
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

SYSTEM_PROMPT = """You are an assistant for the Romanian National Institute of Statistics (INS) TEMPO Online data explorer. You have access to ~3,600 statistical datasets covering demographics, economy, labor, health, education, agriculture, and geography, with data going back to the 1990s.

## Language policy
Respond in the same language the user writes in (Romanian or English). When searching, try both languages — e.g. for "unemployment" also search "somaj".

## Workflow
1. Always call search_datasets first (unless you already know the matrix_code).
2. Disambiguate among candidates by relevance and recency.
3. ALWAYS call get_dataset_schema before query_dataset_data — never guess column names or values.
4. For split datasets (is_split=true), pick the sub-dataset that matches the user's granularity:
   - "pe județe" / "by county" → sub-dataset with "_judete" in its name
   - "național" / "total" → sub-dataset with "_national" or lowest dim count
5. Use group_by for aggregate questions (trends, comparisons, rankings). Never pull raw rows when a grouped summary suffices.

## Romanian statistical vocabulary
- șomaj / rata șomajului → unemployment / unemployment rate
- populație activă → labor force / active population
- pe județe / județe → by county (REF_AREA at county level)
- pe medii → by residence (RESIDENCE: urban/rural)
- pe sexe / pe sex → by gender (SEX: Masculin/Feminin)
- pe grupe de vârstă → by age group (AGE)
- IPC / indice preturi consum → consumer price index (CPI)
- PIB → GDP
- salarii / câștiguri salariale → wages / earnings
- natalitate / nașteri → births / birth rate
- mortalitate / decese → deaths / mortality
- migrație → migration
- comerț exterior → foreign trade
- producție industrială → industrial production

## "Total" rows
Some datasets include aggregated "Total" rows. If a query returns 0 rows and you used a "Total" filter value, retry the query without that filter.

## Response format
End every answer with:
- A plain-language paragraph summarising the result in the user's language.
- The cited matrix_code(s) in parentheses, e.g. (SOM101D_judete).
- If data was retrieved, briefly describe what the numbers show.

## Honesty
If search_datasets returns no relevant results, say so — never invent matrix codes or fabricate data. Decline questions unrelated to Romanian statistics.
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
        limit=min(int(inp.get("limit", 10)), 25),
        conn=conn,
    )
    # Return compact cards — strip fields the LLM doesn't need
    cards = []
    for d in result.get("datasets", []):
        cards.append({
            "matrix_code": d["matrix_code"],
            "name": d["matrix_name"],
            "archetype": d.get("archetype"),
            "time_range": d.get("time_range"),
            "has_geo": d.get("has_geo"),
            "primary_unit_type": d.get("primary_unit_type"),
            "is_split": d.get("is_split"),
            "parent_matrix_code": d.get("parent_matrix_code"),
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
            "values": [o["sdmx_value"] for o in opts[:100] if o.get("sdmx_value")],
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

def run_agent(question: str, history: list[dict] | None = None) -> AgentResult:
    """Run the NL→Data agent loop.

    Args:
        question: User's natural language question.
        history:  Prior conversation turns in the format [{role, content}, ...].
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

    for iteration in range(config.ASK_MAX_TOOL_CALLS + 1):
        if config.DEBUG:
            log.debug("Agent iteration %d, %d messages", iteration, len(messages))

        resp = complete_with_tools(messages, TOOLS, system=SYSTEM_PROMPT)

        if resp.text:
            # LLM produced a text response — may be mixed with tool calls
            pass

        if not resp.tool_calls or resp.stop_reason == "end_turn":
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
        messages.append(_assistant_turn(resp))

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
        # For OpenAI: each tool result is its own message
        if config.LLM_PROVIDER == "anthropic":
            messages.append(_anthropic_tool_results_turn(tool_result_messages))
        else:
            messages.extend(tool_result_messages)

    # Should not reach here
    return AgentResult(answer="Unexpected agent termination.", warnings=["Agent loop exited unexpectedly."])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _assistant_turn(resp) -> dict:
    """Build an assistant message from an LLMResponse."""
    if config.LLM_PROVIDER == "anthropic":
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
