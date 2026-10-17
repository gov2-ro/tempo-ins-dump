"""Period-change API (AT-01e): the compare_periods tool as REST, plus its evidence bundle.

  GET /api/period-changes           the tool envelope, re-run on the current generation
  GET /api/period-changes/evidence  ZIP (tempo-evidence/1): complete ranking, every
                                    exclusion, the endpoint table and recompute.py

Both take the tool's arguments as query parameters: `dataset`, `entity_columns`
(JSON array), `intervals` (JSON array of {"from","to"}), `filters` (JSON object),
`metric`, `order`, `top_k`, `lang`. The evidence route also takes
`expected_generation`: it is checked before the bundle is built and again
before it is sent (409 `generation_changed`), and a generation that changes while
the bundle is being built is refused whether or not one was expected.
"""
from __future__ import annotations

import logging
import re
import uuid

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import JSONResponse, Response
from pydantic import ValidationError

from app.db import get_conn
from app.services import generation
from app.services.request_validation import MISSING, InvalidRequest, parse_json_param

router = APIRouter()
log = logging.getLogger(__name__)


class _BadParam(Exception):
    pass


def _arguments(dataset, entity_columns, intervals, filters, metric, order, top_k, lang) -> dict:
    """Tool arguments from the query string. Only decoding happens here; the
    tool's schema validates types, bounds and unknown keys."""
    raw = {"entity_columns": entity_columns, "intervals": intervals, "filters": filters}
    args: dict = {}
    if dataset is not None:
        args["dataset"] = dataset
    for name in ("entity_columns", "intervals", "filters"):
        try:
            v = parse_json_param(raw[name], name)
        except InvalidRequest as e:
            raise _BadParam(str(e))
        if v is not MISSING:
            args[name] = v
    for name, v in (("metric", metric), ("order", order), ("lang", lang)):
        if v is not None:
            args[name] = v
    if top_k is not None:
        # an integer literal becomes an int; anything else stays a string and the
        # tool's strict schema rejects it (no coercion of "20.5" or "abc")
        args["top_k"] = int(top_k) if re.fullmatch(r"-?\d{1,9}", top_k) else top_k
    return args


def _status(env: dict) -> int:
    if env["status"] != "error":
        return 200
    return {"unknown_dataset": 404, "execution_failed": 500}.get(env["reason"], 400)


def _bad_param_envelope(message: str) -> JSONResponse:
    from app.services.tools import contract
    ctx = contract.ToolContext(conn=None, lang="ro", generation=generation.current(),
                               request_id=uuid.uuid4().hex[:12])
    env = contract.failure_envelope("compare_periods", ctx, contract.ToolFailure(
        "error", "invalid_input", f"{message}. Correct it and call again."))
    return JSONResponse(env, status_code=400)


@router.get("/period-changes")
def period_changes(dataset: str = Query(None, max_length=200),
                   entity_columns: str = Query(None, max_length=4000, description="JSON array"),
                   intervals: str = Query(None, max_length=4000,
                                          description='JSON array of {"from","to"} years'),
                   filters: str = Query(None, max_length=16000, description="JSON object"),
                   metric: str = Query(None, max_length=20),
                   order: str = Query(None, max_length=20),
                   top_k: str = Query(None, max_length=10),
                   lang: str = Query(None, max_length=10)):
    """The compare_periods envelope (tempo-tools/2) for the current generation:
    200 for ok/partial/needs_clarification/unavailable, 400 invalid_input or
    unknown_column, 404 unknown_dataset, 500 execution_failed."""
    from app.services.tools import registry
    try:
        args = _arguments(dataset, entity_columns, intervals, filters, metric, order, top_k, lang)
    except _BadParam as e:
        return _bad_param_envelope(str(e))
    env = registry.call_tool("compare_periods", args)
    return JSONResponse(env, status_code=_status(env))


def _http_for(f) -> int:
    if f.status == "error":
        return {"unknown_dataset": 404, "execution_failed": 500}.get(f.reason, 400)
    return 422


def _changed(expected: str | None, before: dict) -> dict | None:
    """409 detail when the precondition fails or the generation moved during the build."""
    err = generation.precondition(expected)
    if err:
        return err
    now = generation.current()
    if (now.get("id"), now.get("status")) != (before.get("id"), before.get("status")):
        return {"reason": "generation_changed",
                "message": "The data generation changed while the bundle was being built; "
                           "re-run the selection.",
                "expected_generation": before.get("id"), "served_generation": now.get("id"),
                "served_status": now.get("status")}
    return None


@router.get("/period-changes/evidence")
def period_changes_evidence(
        dataset: str = Query(None, max_length=200),
        entity_columns: str = Query(None, max_length=4000),
        intervals: str = Query(None, max_length=4000),
        filters: str = Query(None, max_length=16000),
        metric: str = Query(None, max_length=20),
        order: str = Query(None, max_length=20),
        top_k: str = Query(None, max_length=10),
        lang: str = Query(None, max_length=10),
        expected_generation: str = Query(None, max_length=128, pattern=r"^[A-Za-z0-9._-]*$")):
    """ZIP evidence bundle with the COMPLETE ranking of every interval (not the
    top_k preview). 409 when the generation differs from `expected_generation` or
    changes during the build, 422 when there is no result to certify (unavailable,
    unsupported, refused), 413 when the endpoint table is larger than a bundle holds."""
    from app.services import change_evidence, evidence as ev, export as ex, period_changes
    from app.services.tools import contract, schemas
    try:
        arguments = _arguments(dataset, entity_columns, intervals, filters, metric, order,
                               top_k, lang)
        if len(contract.dumps(arguments).encode("utf-8")) > contract.MAX_ARGUMENT_BYTES:
            raise _BadParam("Invalid arguments: more than 16 KiB")
        args = schemas.ComparePeriodsArgs.model_validate(arguments)
    except _BadParam as e:
        raise HTTPException(400, {"reason": "invalid_input", "message": str(e)})
    except ValidationError as e:
        from app.services.tools.registry import _validation_message
        raise HTTPException(400, {"reason": "invalid_input", "message": _validation_message(e)})
    err = generation.precondition(expected_generation)
    if err:
        raise HTTPException(409, err)
    before = generation.current()
    slot = ex.try_acquire("csv")
    if slot is None:
        raise ex.busy_error()
    conn = None
    try:
        conn = get_conn()
        try:
            result = period_changes.run(conn, args, args.lang)
        except contract.ToolFailure as f:
            raise HTTPException(_http_for(f), {"reason": f.reason, "message": f.message})
        except Exception:
            log.exception("period-changes evidence failed")
            raise HTTPException(500, {"reason": "execution_failed",
                                      "message": "The bundle could not be built; nothing was computed."})
        if result["status"] not in ("ok", "partial"):
            raise HTTPException(422, {"reason": result["reason"] or result["status"],
                                      "message": "No entity could be ranked, so there is no "
                                                 "result to certify."})
        if len(result["endpoints"]) > ev.MAX_INPUT_ROWS:
            raise HTTPException(413, {"reason": "bundle_too_large", "message": (
                f"The endpoint table has {len(result['endpoints'])} rows, more than an evidence "
                f"bundle carries ({ev.MAX_INPUT_ROWS}). Narrow the selection.")})
        link = change_evidence.live_link(args.model_dump(by_alias=True))
        data = change_evidence.bundle(result, link)
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass
        slot()
    err = _changed(expected_generation, before)
    if err:
        raise HTTPException(409, err)
    return Response(data, media_type="application/zip", headers={
        "Content-Disposition": f"attachment; filename={args.dataset}_period_changes_evidence.zip"})


@router.get("/entity-rankings")
def entity_rankings(request: str = Query(..., max_length=16000),
                    expected_generation: str | None = Query(None, max_length=128)):
    """Replay a rank_entities selection, optionally bound to its cited generation."""
    from app.services.tools.registry import call_tool
    import json
    try:
        args = json.loads(request)
    except (ValueError, TypeError):
        raise HTTPException(400, "request must be a JSON object") from None
    before = generation.current()
    if expected_generation and (before.get("status") != "present" or before.get("id") != expected_generation):
        raise HTTPException(409, detail={"reason": "generation_changed"})
    env = call_tool("rank_entities", args)
    if generation.current() != before or env.get("reason") == "generation_changed":
        raise HTTPException(409, detail={"reason": "generation_changed"})
    return JSONResponse(env, status_code=_status(env))
