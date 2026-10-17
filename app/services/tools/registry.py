"""The eight public tools and the one dispatcher every adapter calls (AT-00/01).

`call_tool(name, arguments)` is the whole service boundary: argument bytes,
schema validation (unknown keys, types, bounds) before any DB work, a cursor
owned by the call, the generation captured before execution and checked again
before return, stable error reasons, recovery-argument validation and the
32 KiB result budget. Ask and the public MCP translate transport around it;
they do not re-implement any of these rules.
"""
from __future__ import annotations

import hashlib
import importlib
import logging
import uuid
from dataclasses import dataclass

from pydantic import BaseModel, ValidationError, create_model

from app.services import generation
from app.services.tools import schemas as S
from app.services.tools.contract import (
    MAX_ARGUMENT_BYTES, MAX_RECOVERY, MAX_RESULT_BYTES, ToolContext, ToolFailure, dumps, envelope,
    failure_envelope, recovery, response_budget, shrink_rows, size)

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class ToolSpec:
    name: str
    title: str
    description: str
    args: type[BaseModel]
    data: type[BaseModel]
    handler: str            # "module:function", imported on first call
    shrink: str | None = None


_PKG = "app.services.tools"

TOOLS: dict[str, ToolSpec] = {t.name: t for t in (
    ToolSpec("discover_indicators", "Discover indicators",
             "Find official Romanian statistics (INS TEMPO) for a question: reviewed concepts "
             "with their definition, unit, actual period coverage and geographic levels, "
             "candidate datasets and the next call to make. Pass the full question, preserving "
             "denominator, geography, period and ranking. State any assumed definition; "
             "unresolved ambiguity returns needs_clarification with labelled choices.",
             S.DiscoverIndicatorsArgs, S.DiscoverData, f"{_PKG}.discovery:discover_indicators"),
    ToolSpec("describe_dataset", "Describe dataset",
             "Compact schema of one dataset: definition, measure, unit, actual first/last "
             "period, dimensions with examples and how to look up every value, parent and "
             "sub-datasets, grain status, scope and notes.",
             S.DescribeDatasetArgs, S.DescribeData, f"{_PKG}.discovery:describe_dataset"),
    ToolSpec("find_dimension_values", "Find dimension values",
             "Search and page the exact values a dimension actually has in the data "
             "(accent-insensitive). Time is newest first, with actual period bounds. Use "
             "the exact `value` in filters.",
             S.FindDimensionValuesArgs, S.FindValuesData, f"{_PKG}.discovery:find_dimension_values"),
    ToolSpec("query_data", "Query data",
             "One validated, bounded selection of a dataset. Collapsed dimensions follow the "
             "shared aggregation policy and grain checks; a refused total is returned as "
             "unavailable with a safe next step, never summed elsewhere.",
             S.QueryDataArgs, S.QueryData, f"{_PKG}.query:query_data",
             f"{_PKG}.query:shrink"),
    ToolSpec("compare_periods", "Compare periods",
             "Per-entity change between exact annual endpoints (1–4 intervals) of an additive "
             "count, ranked over every eligible entity, with exclusions stated.",
             S.ComparePeriodsArgs, S.CompareData, f"{_PKG}.changes:compare_periods",
             f"{_PKG}.changes:shrink"),
    ToolSpec("rank_entities", "Rank entities",
             "Rank a complete eligible entity set by value in one annual period. "
             "year=null selects the latest actual year. entity_class=cities uses INS's "
             "SIRUTA municipality/town catalogue, excluding communes. Never ranks a capped "
             "preview. Use for top/bottom cities or counties, not changes or density.",
             S.RankEntitiesArgs, S.RankingData, f"{_PKG}.ranking:rank_entities"),
    ToolSpec("run_recipe", "Run recipe",
             "Run a reviewed cross-dataset recipe (e.g. tourism intensity). Serves INS's own "
             "published totals where they exist, with reconstruction only as a cross-check.",
             S.RunRecipeArgs, S.RecipeData, f"{_PKG}.recipe:run_recipe",
             f"{_PKG}.recipe:shrink"),
    ToolSpec("get_evidence_links", "Get evidence links",
             "Exact dataset, live-selection, CSV and evidence-bundle links for a selection "
             "returned by another tool, checked against the result's generation.",
             S.GetEvidenceLinksArgs, S.LinksData, f"{_PKG}.links:get_evidence_links"),
)}


def _resolve(ref: str):
    mod, fn = ref.split(":")
    return getattr(importlib.import_module(mod), fn)


def input_schema(name: str) -> dict:
    return TOOLS[name].args.model_json_schema(by_alias=True)


def inline_schema(schema: dict) -> dict:
    """A JSON Schema without $defs/$ref, title annotations and the OpenAPI `discriminator` (its
    mapping points into $defs; each oneOf branch already pins `kind` with a const): clients and
    providers differ in how much of JSON Schema they accept, and the service validates regardless."""
    defs = schema.get("$defs", {})

    def walk(node):
        if isinstance(node, dict):
            if "$ref" in node:
                return walk(defs[node["$ref"].rsplit("/", 1)[-1]])
            return {k: walk(v) for k, v in node.items()
                    if k not in ("$defs", "discriminator") and not (k == "title" and isinstance(v, str))}
        if isinstance(node, list):
            return [walk(x) for x in node]
        return node
    return walk(schema)


_OUTPUT_MODELS: dict[str, type[BaseModel]] = {}


def output_model(name: str) -> type[BaseModel]:
    """Envelope with this tool's `data`: its result shape, or empty on a refusal."""
    if name not in _OUTPUT_MODELS:
        class Empty(BaseModel):
            model_config = {"extra": "forbid"}
        Empty.__name__ = f"{TOOLS[name].data.__name__}Empty"
        _OUTPUT_MODELS[name] = create_model(
            f"{TOOLS[name].data.__name__}Envelope", __base__=S.Envelope,
            data=(TOOLS[name].data | Empty | dict, ...))
    return _OUTPUT_MODELS[name]


def output_schema(name: str) -> dict:
    return output_model(name).model_json_schema(by_alias=True)


def validate_result(name: str, env: dict) -> None:
    """Raise ValidationError unless `env` is a valid envelope whose data has the
    tool's minimum shape (required when the status reports a result)."""
    S.Envelope.model_validate(env)
    if env["status"] in ("ok", "partial") or (
            name == "discover_indicators" and env["status"] == "needs_clarification"):
        TOOLS[name].data.model_validate(env["data"])
    for r in env["recovery"]:
        if r["kind"] == "tool_call":
            TOOLS[r["tool"]].args.model_validate(r["arguments"])


def _validation_message(e: ValidationError) -> str:
    seen, parts = set(), []
    for err in e.errors(include_input=False, include_url=False):
        loc = [str(x) for x in err["loc"] if not (isinstance(x, str) and x in (
            "str", "int", "float", "function-after[v_ordered(), Interval]"))]
        key = ".".join(loc) or "arguments"
        if key in seen:
            continue
        seen.add(key)
        msg = "unknown argument" if err["type"] == "extra_forbidden" else \
            err["msg"].removeprefix("Value error, ")
        parts.append(f"{key}: {msg}")
        if len(parts) == 4:
            break
    return "Invalid arguments — " + "; ".join(parts) + ". Correct them and call again."


def _valid_recovery(env: dict) -> dict:
    keep = []
    for r in env.get("recovery") or []:
        if r.get("kind") == "tool_call":
            spec = TOOLS.get(r.get("tool") or "")
            try:
                if spec is None:
                    raise ValueError("unknown tool")
                spec.args.model_validate(r.get("arguments") or {})
            except (ValidationError, ValueError):
                log.error("dropped invalid recovery suggestion tool=%s", r.get("tool"))
                continue
        keep.append(r)
    env["recovery"] = keep[:MAX_RECOVERY]
    return env


def _fit(env: dict, spec: ToolSpec | None, args_hash: str, args_bytes: int) -> dict:
    if size(env) <= MAX_RESULT_BYTES:
        return env
    shrink = _resolve(spec.shrink) if spec and spec.shrink else shrink_rows
    while size(env) > MAX_RESULT_BYTES:
        if not shrink(env):
            return response_budget(env, args_hash, args_bytes)
    return env


def precheck(name: str, arguments) -> dict | None:
    """The failure envelope of a call that cannot run (unknown tool, arguments that are not
    plain JSON, over 16 KiB, or failing the strict schema), or None when it is valid. No database
    work: an adapter uses it to refuse a bad call before it takes an execution slot."""
    spec = TOOLS.get(name)
    lang = arguments.get("lang") if isinstance(arguments, dict) else None
    ctx = ToolContext(conn=None, lang=lang if lang in ("ro", "en") else "ro",
                      generation=generation.current(), request_id=uuid.uuid4().hex[:12])
    tool = str(name)[:64]

    def fail(status, reason, message, **kw):
        return failure_envelope(tool, ctx, ToolFailure(status, reason, message, **kw))

    if spec is None:
        return fail("error", "unknown_tool", f"Unknown tool {tool!r}; available: " + ", ".join(TOOLS) + ".")
    if not isinstance(arguments, dict):
        return fail("error", "invalid_input", "Arguments must be a JSON object.")
    try:
        raw = dumps(arguments)
    except (TypeError, ValueError):
        return fail("error", "invalid_input", "Arguments must be plain JSON (no NaN/Infinity).")
    nbytes = len(raw.encode("utf-8"))
    if nbytes > MAX_ARGUMENT_BYTES:
        return fail("error", "invalid_input",
                    f"Arguments are {nbytes} bytes; the limit is {MAX_ARGUMENT_BYTES}. Ask for fewer values.",
                    recovery=[recovery("narrow", "Send fewer filter values or areas.")])
    try:
        spec.args.model_validate(arguments)
    except ValidationError as e:
        return fail("error", "invalid_input", _validation_message(e))
    return None


def shrinker(name: str):
    """The tool's hook for shortening an oversized envelope in place (False: nothing left to cut)."""
    spec = TOOLS.get(name)
    return _resolve(spec.shrink) if spec and spec.shrink else shrink_rows


def call_tool(name: str, arguments, *, conn=None) -> dict:
    """Run one tool and return its `tempo-tools/2` envelope (never raises for
    bad input, refusals or execution failures)."""
    request_id = uuid.uuid4().hex[:12]
    gen0 = generation.current()
    lang = arguments.get("lang") if isinstance(arguments, dict) else None
    ctx = ToolContext(conn=None, lang=lang if lang in ("ro", "en") else "ro",
                      generation=gen0, request_id=request_id)
    tool = str(name)[:64]
    spec = TOOLS.get(name)

    def fail(status, reason, message, **kw):
        return failure_envelope(tool, ctx, ToolFailure(status, reason, message, **kw))

    if spec is None:
        return fail("error", "unknown_tool", f"Unknown tool {tool!r}; available: "
                    + ", ".join(TOOLS) + ".")
    if not isinstance(arguments, dict):
        return fail("error", "invalid_input", "Arguments must be a JSON object.")
    try:
        raw = dumps(arguments)
    except (TypeError, ValueError):
        return fail("error", "invalid_input", "Arguments must be plain JSON (no NaN/Infinity).")
    args_bytes = len(raw.encode("utf-8"))
    args_hash = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    if args_bytes > MAX_ARGUMENT_BYTES:
        return fail("error", "invalid_input",
                    f"Arguments are {args_bytes} bytes; the limit is {MAX_ARGUMENT_BYTES}. "
                    "Ask for fewer values.",
                    recovery=[recovery("narrow", "Send fewer filter values or areas.")])
    try:
        args = spec.args.model_validate(arguments)
    except ValidationError as e:
        return fail("error", "invalid_input", _validation_message(e))

    own = conn is None
    try:
        if own:
            from app.db import get_conn
            conn = get_conn()
        ctx.conn = conn
        env = _resolve(spec.handler)(args, ctx)
    except ToolFailure as f:
        env = failure_envelope(tool, ctx, f)
    except Exception:
        log.exception("tool failed tool=%s request=%s", tool, request_id)
        env = fail("error", "execution_failed",
                   f"The tool failed (reference {request_id}); nothing was computed.")
    finally:
        ctx.conn = None
        if own and conn is not None:
            try:
                conn.close()
            except Exception:
                pass

    gen1 = generation.current()
    if (gen1.get("id"), gen1.get("status")) != (gen0.get("id"), gen0.get("status")):
        return fail("unavailable", "generation_changed",
                    "The served data generation changed during this call; nothing from it "
                    "is reported. Run the request again.",
                    recovery=[recovery("retry", "Run the same request again on the new "
                                                "generation.")])
    return _fit(_valid_recovery(env), spec, args_hash, args_bytes)


def tool_names() -> list[str]:
    return list(TOOLS)


__all__ = ["TOOLS", "ToolSpec", "call_tool", "precheck", "shrinker", "input_schema", "inline_schema",
           "output_schema", "output_model", "validate_result", "tool_names", "envelope", "MAX_RESULT_BYTES"]
