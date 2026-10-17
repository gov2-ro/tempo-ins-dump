"""What Ask answers for one query, in the shape the pre-AT-02 adapter returned.

The Ask loop now calls the shared `query_data` tool (`registry.call_tool`), so consumer-parity
tests compare REST and the dev MCP with the tool's envelope, flattened to the old keys:
{status, columns, rows, aggregation (with effective filters/levels), reason, blocking_dimension}
or {error} for a malformed request.
"""
from app.services.tools.registry import call_tool


def ask(code, filters=None, group_by=None, approximate=None):
    args = {"dataset": code, "lang": "en"}          # the parity tests pin the English wording of the prose
    if filters is not None:
        args["filters"] = filters
    if group_by is not None:
        args["group_by"] = group_by
    if approximate is not None:
        args["approximate"] = approximate
    env = call_tool("query_data", args)
    if env["status"] == "error":
        return {"error": env["message"], "reason": env["reason"]}
    prov = env["provenance"]
    agg = {**prov["aggregation"], **(prov.get("effective_selection") or {})}
    status = ("unavailable" if env["status"] == "unavailable"
              else "approximation" if agg.get("approximation") else "ok")
    return {"status": status, "columns": env["data"].get("columns"), "rows": env["data"].get("rows"),
            "aggregation": agg, "reason": env["reason"], "selection": env["data"].get("selection"),
            "warnings": [w["message"] for w in env["warnings"]],
            "blocking_dimension": agg.get("blocking_dimension"), "envelope": env}
