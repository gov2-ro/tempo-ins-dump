"""NL→Data agent for the INS TEMPO explorer.

Exposes run_agent(question, history) which calls an LLM in a tool-calling loop
over 4 tools: search_datasets, get_dataset_schema, query_dataset_data, list_categories.

All data access goes through the existing safe service layer — the LLM never
generates SQL directly.
"""
import json
import logging
import re
import time
from dataclasses import dataclass, field

from app import config
from app.db import get_conn
from app.services import answer_check
from app.services.ask_guard import RedactingFilter, redact_text
from app.services.llm_client import LLMError, classify_provider_error, complete_with_tools

log = logging.getLogger(__name__)
log.addFilter(RedactingFilter())  # credentials never reach agent logs (FIX-08)

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

## Query results: status, aggregation, warnings
Every query_dataset_data result has `status`:
- "ok" → numbers are valid for the filters/levels listed in `aggregation`. "Auto-applied aggregate/level filters" are already corrected; trust numbers.
- "approximation" → an unweighted mean of rates/indices. State it is an approximation, never the official/national rate.
- "unavailable" → NO numbers exist for this grouped query (`reason`, `blocking_dimension`, `suggestion`). Do not state any figure for it. Re-query as the suggestion says (pin or choose one level/value), or explain the limitation.
Only cite numbers that appear in a result with status ok/approximation. If no query succeeded, say so instead of giving figures.
"Retried after removing Total" → your filter was empty; handler dropped it.

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
    # FIX-08 budgets: "end_turn" normally, else "iterations" | "tools" | "deadline" | "provider"
    stop_reason: str = "end_turn"
    budget: dict = field(default_factory=dict)
    # FIX-08 item 7: deterministic check of the answer against tool results.
    # {status: verified|unverified_numbers|values_withheld|no_values, valid_query,
    #  uncited_numbers: [...], unavailable: [{matrix_code, reason}], approximations: [codes]}
    verification: dict = field(default_factory=dict)


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
    """Query tool. Grouped requests go through the shared aggregation policy
    (FIX-02): the result carries `status` ("ok" | "approximation" |
    "unavailable"), the decision under `aggregation` and reason codes, so the
    model — and the deterministic answer check — see exactly what was allowed.
    Ungrouped requests return raw observations (`aggregation` is null)."""
    from app.services.query_builder import (
        build_data_query, resolve_parquet_schema, adapt_to_parquet, to_sdmx_name)
    from app.services.dataset_meta import get_aggregation_context, decide_grouped
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

    # Shared with dataset_data/insights: the file may be SDMX or legacy v2,
    # and the recorded dim names may be either.
    schema = resolve_parquet_schema(conn, matrix_code)

    warnings: list[str] = []
    aggregation = None
    status = "ok"
    if group_by:
        # FIX-02: the same decision composer tiles, insights and the grouped
        # API use. Unavailable => no rows, a reason code and a way forward;
        # never an unsafe sum. Unweighted means come back labelled
        # "approximation" so the answer cannot call them an official rate.
        ctx = get_aggregation_context(conn, matrix_code)
        if ctx is not None:
            sd_group = [to_sdmx_name(schema, c) for c in group_by]
            sd_filters = {to_sdmx_name(schema, k): v for k, v in filters.items()}
            decision = decide_grouped(ctx, sd_group, sd_filters, allow_approximation=True)
            aggregation = decision.to_dict()
            if not decision.available:
                return {
                    "matrix_code": matrix_code, "status": "unavailable",
                    "columns": sd_group + ["OBS_VALUE"], "rows": [], "row_count": 0,
                    "truncated": False, "aggregation": aggregation,
                    "reason": decision.reason,
                    "blocking_dimension": decision.blocking_dimension,
                    "warnings": [
                        f"AGGREGATION UNAVAILABLE ({decision.reason}"
                        + (f", dimension {decision.blocking_dimension}" if decision.blocking_dimension else "")
                        + "): this grouped total cannot be computed safely. Do not state a figure for it."],
                    "suggestion": _unavailable_hint(decision),
                }
            filters = {k: list(v) for k, v in decision.effective_filters.items()}
            group_by = sd_group
            pins = {c: v for c, v in decision.effective_filters.items()
                    if c not in sd_filters and c not in sd_group}
            if pins:
                warnings.append(
                    "Auto-applied aggregate/level filters to avoid double-counting: "
                    + ", ".join(f"{c}={_short(vs)}" for c, vs in pins.items()))
            if decision.outcome == "approximation":
                status = "approximation"
                warnings.append(
                    "APPROXIMATION: unweighted mean of non-additive values (rate/index/average) "
                    "because no aligned weights exist. Say it is an approximation; never call it "
                    "the official/national rate.")
            for w in decision.warnings:
                if w.get("code") == "time_collapsed":
                    warnings.append(f"Values are aggregated across all periods of {w['column']}; "
                                    "filter or group by time for a single-period figure.")

    dimensions, group_by, filters = adapt_to_parquet(
        schema, dimensions, group_by, filters)
    agg_func = (aggregation or {}).get("agg_func") or "SUM"

    def _execute_query(f):
        sql = build_data_query(matrix_code, dimensions, f, limit + 1, group_by=group_by,
                               agg_func=agg_func, value_column=schema['value_column'])
        return conn.execute(sql).fetchall()

    try:
        rows = _execute_query(filters)
    except Exception as e:
        return {"error": f"Query failed: {e}"}

    # Auto-retry: strip "Total"/"TOTAL" filter values if 0 rows (raw queries
    # only: for grouped ones the policy already chose its pins).
    if len(rows) == 0 and filters and not aggregation:
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

    # Report SDMX names even when the file is legacy — get_dataset_schema
    # showed the model canonical names, so returning `perioade_nom_id` here
    # would contradict what it was told.
    columns = [schema["to_sdmx"].get(d["dim_column_name"], d["dim_column_name"])
               for d in result_dims] + ["OBS_VALUE"]
    data_rows = [list(r) for r in rows]

    return {
        "matrix_code": matrix_code,
        "status": status,
        "columns": columns,
        "rows": data_rows,
        "row_count": len(data_rows),
        "truncated": truncated,
        "aggregation": aggregation,
        "warnings": warnings,
    }


def _short(vs, n=3) -> str:
    vs = [str(v) for v in vs]
    return ",".join(vs[:n]) + (f",... ({len(vs)})" if len(vs) > n else "")


_REASON_HINTS = {
    "overlapping_levels": "Filter {col} to ONE level (e.g. only single years or only one band size, "
                          "only counties) with filters, or group by {col}; or query without group_by.",
    "unverified_structure": "Pin {col} to one explicit value (or its Total) in filters, or group by {col}.",
    "contains_aggregate": "Remove the Total/aggregate value from the {col} filter or filter to it alone.",
    "label_hierarchy": "Pin {col} to a single explicit value or its Total in filters.",
    "missing_weights": "Filter every other dimension to one value, or group by it. "
                       "Rates/indices cannot be summed or averaged across categories.",
    "non_additive_measure": "Filter every other dimension to one value, or group by it.",
    "mixed_units": "Filter {col} to exactly one unit.",
    "slice_value_missing": "A filter value for {col} does not exist; use exact values from get_dataset_schema.",
    "declared_partition_invalid": "Pin {col} to one explicit value.",
}


def _unavailable_hint(decision) -> str:
    col = decision.blocking_dimension or "the blocking dimension"
    tmpl = _REASON_HINTS.get(decision.reason or "", "Narrow the query with explicit filters.")
    return tmpl.format(col=col) + " Raw rows (no group_by, with filters) remain available."


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

    # FIX-08: independent budgets. Each is checked BEFORE the call it would forbid.
    started = time.monotonic()
    deadline = started + config.ASK_MAX_SECONDS
    iterations = 0
    tools_used = 0
    prov_name = provider or config.LLM_PROVIDER

    def _budget() -> dict:
        return {
            "iterations": iterations, "max_iterations": config.ASK_MAX_ITERATIONS,
            "tools": tools_used, "max_tools": config.ASK_MAX_TOOL_CALLS,
            "elapsed_s": round(time.monotonic() - started, 3), "max_seconds": config.ASK_MAX_SECONDS,
        }

    def _finalize(answer: str) -> tuple[str, dict]:
        """Deterministic answer check (outside the prompt): keep aggregation
        warnings on the answer, flag numbers no valid query contains, and
        withhold an answer that claims values without any valid query."""
        ans, ver = _check_answer(answer, question, tool_trace)
        for w in ver.pop("_warnings"):
            if w not in agent_warnings:
                agent_warnings.append(w)
        return ans, ver

    def _stopped(reason: str, text: str | None = None) -> AgentResult:
        msgs = {
            "iterations": "Reached the model-call limit",
            "tools": "Reached the tool-call limit",
            "deadline": "Reached the time limit",
            "provider": "The model provider became unavailable",
        }
        agent_warnings.append(f"{msgs[reason]} before a final answer; the result is partial.")
        answer = text or (
            "I could not finish within the request limits. "
            + ("Partial data is attached. " if last_query_result else "")
            + "Please retry with a more specific question.")
        answer, verification = _finalize(answer)
        return AgentResult(
            answer=answer,
            citations=_extract_citations(answer, tool_trace),
            tool_trace=tool_trace,
            data=last_query_result,
            chart_spec=_get_chart_spec(last_queried_matrix, conn) if last_queried_matrix else None,
            warnings=agent_warnings,
            stop_reason=reason,
            budget=_budget(),
            verification=verification,
        )

    while True:
        if iterations >= config.ASK_MAX_ITERATIONS:
            return _stopped("iterations")
        if time.monotonic() >= deadline:
            return _stopped("deadline")
        if config.DEBUG:
            log.debug("Agent iteration %d, %d messages", iterations, len(messages))

        iterations += 1
        try:
            resp = complete_with_tools(
                messages, TOOLS, system=SYSTEM_PROMPT,
                provider=provider, model=model, api_key=api_key,
                timeout=max(1.0, min(config.ASK_PROVIDER_TIMEOUT, deadline - time.monotonic())))
        except Exception as e:  # noqa: BLE001
            err = classify_provider_error(e)
            if tool_trace and err.code in ("provider_timeout", "provider_unavailable", "provider_rate_limited"):
                log.warning("Provider error after %d tools: %s", len(tool_trace), err.code)
                return _stopped("provider")
            raise err from None

        if not resp.tool_calls:
            # Guardrail: model gave up without querying data, but search returned results.
            # Inject one synthetic user turn to force schema + query. Fires once per run.
            # Primarily targets OpenAI models that ignore "MUST call query_dataset_data".
            search_had_results = any(
                t["tool"] == "search_datasets" and t["output"].get("total", 0) > 0
                for t in tool_trace
            )
            query_attempted = any(t["tool"] == "query_dataset_data" for t in tool_trace)
            if (not _guardrail_fired and last_query_result is None and search_had_results
                    and not query_attempted):
                _guardrail_fired = True
                if resp.text or resp.tool_calls:
                    messages.append(_assistant_turn(resp, provider=prov_name))
                messages.append({
                    "role": "user",
                    "content": (
                        "You found relevant datasets but did not query any data. "
                        "Please call get_dataset_schema on the most relevant dataset, "
                        "then call query_dataset_data to retrieve actual numbers before answering."
                    ),
                })
                agent_warnings.append("Guardrail: model skipped data query — injected follow-up turn.")
                log.debug("Guardrail fired at iteration %d", iterations)
                continue

            # Done — extract final answer
            answer, verification = _finalize(resp.text or "(no answer)")
            citations = _extract_citations(answer, tool_trace)
            chart_spec = _get_chart_spec(last_queried_matrix, conn) if last_queried_matrix else None
            return AgentResult(
                answer=answer,
                citations=citations,
                tool_trace=tool_trace,
                data=last_query_result,
                chart_spec=chart_spec,
                warnings=agent_warnings,
                budget=_budget(),
                verification=verification,
            )

        if iterations >= config.ASK_MAX_ITERATIONS:
            # The model wants tools but there is no model call left to read their results.
            return _stopped("iterations", resp.text)

        # Append the assistant turn (with tool_use blocks for Anthropic)
        messages.append(_assistant_turn(resp, provider=prov_name))

        # Dispatch the tool calls in this turn, counting EVERY one against the budget.
        tool_result_messages = []
        over_budget = None
        for tc in resp.tool_calls:
            if tools_used >= config.ASK_MAX_TOOL_CALLS:
                over_budget = "tools"
                break
            if time.monotonic() >= deadline:
                over_budget = "deadline"
                break
            tools_used += 1
            handler = TOOL_HANDLERS.get(tc["name"])
            if handler:
                try:
                    result = handler(tc["input"], conn)
                except Exception as e:  # noqa: BLE001
                    log.error("Tool %s failed: %s", tc["name"], type(e).__name__)
                    result = {"error": redact_text(str(e))[:300]}
            else:
                result = {"error": "Unknown tool"}

            result_str = json.dumps(result, ensure_ascii=False, default=str)

            tool_trace.append({
                "tool": tc["name"],
                "input": tc["input"],
                "output": result,
            })

            if tc["name"] == "query_dataset_data" and "error" not in result:
                # FIX-08 item 7: the tool's aggregation outcome decides what the
                # answer may claim. Only ok/approximation results are data; an
                # "unavailable" one carries a reason code and no rows. Warnings
                # (approximation, pins, unavailable reasons) always reach the
                # final response; see _check_answer for the deterministic part.
                if result.get("status") in ("ok", "approximation"):
                    last_query_result = result
                    last_queried_matrix = tc["input"].get("matrix_code")
                for w in result.get("warnings") or []:
                    if w not in agent_warnings:
                        agent_warnings.append(w)

            tool_result_messages.append({
                "role": "tool",
                "tool_use_id": tc["id"],
                "content": result_str,
            })

        if over_budget:
            # Tool results for the skipped calls do not exist, so the conversation cannot
            # continue; stop with whatever was gathered.
            return _stopped(over_budget, resp.text)

        # For Anthropic: all tool results go in a single user turn
        # For OpenAI/Gemini: each tool result is its own message
        if prov_name == "anthropic":
            messages.append(_anthropic_tool_results_turn(tool_result_messages))
        else:
            messages.extend(tool_result_messages)


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


def _extract_citations(answer: str, tool_trace: list[dict]) -> list[dict]:
    """Citations from the tool trace (+ parenthesised codes in the answer).

    Each carries the aggregation outcome of the queries behind it so a UI can
    show "official total" vs "approximation" vs "unavailable":
    {matrix_code, matrix_name, queries: [{status, outcome, method, reason,
    approximation, filters, levels}]}.
    """
    codes: dict[str, dict] = {}

    def entry(code):
        return codes.setdefault(code, {"matrix_code": code, "matrix_name": "", "queries": []})

    for t in tool_trace:
        if t["tool"] not in ("get_dataset_schema", "query_dataset_data"):
            continue
        mc = t["input"].get("matrix_code")
        if not mc:
            continue
        e = entry(mc)
        out = t.get("output") if isinstance(t.get("output"), dict) else {}
        name = out.get("name") or out.get("matrix_name") or ""
        if name:
            e["matrix_name"] = name
        if t["tool"] == "query_dataset_data" and "error" not in out:
            agg = out.get("aggregation") or {}
            e["queries"].append({
                "status": out.get("status"),
                "outcome": agg.get("outcome") or ("raw" if out.get("status") == "ok" else None),
                "method": agg.get("method"), "reason": agg.get("reason") or out.get("reason"),
                "approximation": bool(agg.get("approximation")),
                "filters": agg.get("filters") if agg else (t["input"].get("filters") or {}),
                "levels": agg.get("levels") or {},
            })
    for match in re.finditer(r'\(([A-Z][A-Z0-9_]{3,})\)', answer):
        entry(match.group(1))
    return [codes[k] for k in sorted(codes)]


def _check_answer(answer: str, question: str, tool_trace: list[dict]) -> tuple[str, dict]:
    """FIX-08 item 7, deterministic and outside the prompt.

    * no valid query (rows under an ok/approximation outcome) but the answer
      states numbers -> the answer is replaced (values_withheld);
    * valid query but numbers the results do not contain -> flagged
      (unverified_numbers) in `warnings` and `verification.uncited_numbers`;
    * an approximation the answer did not qualify gets an explicit note.
    """
    lang = answer_check.guess_lang(question)
    valid = answer_check.valid_queries(tool_trace)
    unavailable = [
        {"matrix_code": t["output"].get("matrix_code"), "reason": t["output"].get("reason")}
        for t in tool_trace
        if t["tool"] == "query_dataset_data" and isinstance(t.get("output"), dict)
        and t["output"].get("status") == "unavailable"]
    approx = sorted({v.get("matrix_code") for v in valid if v.get("status") == "approximation"})
    warns: list[str] = []
    ver = {"valid_query": bool(valid), "uncited_numbers": [],
           "unavailable": unavailable, "approximations": approx, "status": "no_values"}

    if not valid:
        if answer_check.has_value_claims(answer, question):
            ver["status"] = "values_withheld"
            ver["uncited_numbers"] = [c["raw"] for c in answer_check.find_numbers(answer, question)]
            warns.append("Answer withheld: it stated figures but no data query succeeded.")
            answer = answer_check.NOTICES[lang]["withheld"]
            if unavailable:
                reasons = ", ".join(sorted({u["reason"] or "?" for u in unavailable}))
                answer += f" ({reasons})"
        ver["_warnings"] = warns
        return answer, ver

    unc = answer_check.uncited_numbers(answer, valid, question)
    if unc:
        ver["status"] = "unverified_numbers"
        ver["uncited_numbers"] = unc
        warns.append("Numbers not found in any query result (derived or unverified): "
                     + ", ".join(unc[:8]))
    else:
        ver["status"] = "verified"
    notes = answer_check.approximation_notes(answer, tool_trace, lang)
    if notes:
        answer = answer.rstrip() + "\n\n" + "\n".join(notes)
    ver["_warnings"] = warns
    return answer, ver


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
