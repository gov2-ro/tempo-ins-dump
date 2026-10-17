"""POST /api/ask — user-facing NL→Data agent endpoint.

Hosted calls need TEMPO_ASK_ENABLED; own-key and keyless local (Ollama) calls need TEMPO_ASK_BYOK_ENABLED.

Request pipeline (FIX-08, AT-02): validate history -> validate follow-up context -> resolve
provider/model against the allowlist -> take a concurrency slot -> run the budgeted agent.
Nothing reaches a provider before the first four steps pass.

Cancellation: when the browser aborts or disconnects, a CancelToken stops the agent loop and
interrupts the DuckDB query running on the cursor that request owns. A provider call already in
flight cannot be interrupted: it ends at its own deadline-bounded timeout, and the concurrency
slot stays occupied until the work has really stopped.

Terminal state: the response carries ``outcome`` (answered | clarification | refused | partial |
failed) and a stable ``reason`` next to ``stop_reason``. HTTP 200 and ``end_turn`` do not mean a
substantive answer.

Logging contract
----------------
* ALWAYS: one operational line per request, ``ASK_METRICS {json}``, from a whitelist
  (ask_guard.sanitize_metrics): ids, provider/model, outcome/reason, attempt/dispatch/execution/
  cache-hit counts, durations, byte and token counts, refusal-code counts, cancellation and
  timeout flags. No question, history, answer, tool filter values, credential or exception body.
* Only when TEMPO_ASK_LOG_CHATS=true (default OFF): an additional ``CHAT_LOG {json}``
  line on stdout and logs/ask-chats.jsonl with question/answer/tool_trace. Credentials
  are redacted recursively. GET /api/ask/config tells the UI so it can disclose this
  before a question is submitted. Retention is that of the log sink (fly logs / local
  file); nothing here rotates or deletes it.
* Credentials are removed before anything is serialized: the request's own key is scrubbed from
  every log record while the request runs (ask_guard.secrets_scope), from provider error text where
  it is made, and from debug events and NDJSON lines before delivery.
* Only when TEMPO_ASK_DEBUG=true (local development, never a public server): a request
  with ``debug: true`` gets every agent step back (``debug.events``, bounded and redacted, with the
  count of dropped events) and POST /api/ask/stream streams those steps as NDJSON while it runs.
  ``ASK_DEBUG`` and ``ASK_METRICS`` lines then reach stdout.
"""
import asyncio
import json
import logging
import time
import uuid
from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel, Field

from app import config
from app.services import ask_context, ask_guard
from app.services.agent import run_agent
from app.services.llm_client import LLMError

log = logging.getLogger(__name__)
log.addFilter(ask_guard.RedactingFilter())

if config.ASK_DEBUG:
    # uvicorn configures only its own loggers: without a handler INFO lines vanish.
    _h = logging.StreamHandler()
    _h.setFormatter(logging.Formatter("%(asctime)s %(name)s %(message)s"))
    _h.addFilter(ask_guard.RedactingFilter())
    for _name in (__name__, "app.services.agent"):
        _lg = logging.getLogger(_name)
        _lg.setLevel(logging.INFO)
        _lg.addHandler(_h)


def _write_chat_log(entry: dict, secrets: tuple = ()) -> None:
    """Content log: stdout (``fly logs``) plus logs/ask-chats.jsonl. Credentials redacted."""
    line = json.dumps(ask_guard.redact(entry, secrets), ensure_ascii=False, default=str)
    log.info("CHAT_LOG %s", line)
    try:
        config.ASK_LOG_DIR.mkdir(parents=True, exist_ok=True)
        with open(config.ASK_LOG_DIR / "ask-chats.jsonl", "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        log.error("Failed to write chat log file")


def _log_metrics(**fields) -> None:
    log.info("ASK_METRICS %s", json.dumps(ask_guard.sanitize_metrics(fields), ensure_ascii=False))


router = APIRouter()


class AskRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=2000)
    # Raw list: elements are validated (role/content/size) in ask_guard.validate_history
    history: list = Field(default_factory=list)
    # Follow-up selections from the previous answers (untrusted; ask_context.validate keeps only
    # the tool, generation id and canonical selection and re-validates them)
    context: list | None = None
    # BYOK fields — optional; sent to the provider through this server, never stored
    provider: str | None = Field(default=None, max_length=40)   # one of llm_client.PROVIDERS
    model: str | None = Field(default=None, max_length=100)
    api_key: str | None = Field(default=None, max_length=400)
    debug: bool = False   # honoured only when the server runs with TEMPO_ASK_DEBUG
    # The language the site is shown in. It decides only a question that shows no language of its
    # own (answer_check.resolve_lang); with neither, tool prose stays Romanian. Anything but ro/en is a 422.
    lang: Literal["ro", "en"] | None = None


@router.get("/ask/config")
def ask_config() -> dict:
    """Public, non-secret settings the chat UI needs (logging disclosure, limits)."""
    return {
        "enabled": config.ASK_ENABLED,
        "byok_enabled": config.ASK_BYOK_ENABLED,
        "available": config.ASK_ENABLED or config.ASK_BYOK_ENABLED,
        "chat_logging": config.ASK_LOG_CHATS,
        "limits": {
            "max_history_turns": config.ASK_MAX_HISTORY_TURNS,
            "max_turn_chars": config.ASK_MAX_TURN_CHARS,
            "max_request_chars": config.ASK_MAX_REQUEST_CHARS,
            "max_seconds": config.ASK_MAX_SECONDS,
            "max_context_entries": ask_context.FOLLOWUP_MAX_ENTRIES,
            "max_context_bytes": ask_context.FOLLOWUP_MAX_BYTES,
        },
        "byok_models": ask_guard.byok_allowlist(),
        "debug": config.ASK_DEBUG,
    }


def _http_from_llm(e: LLMError) -> HTTPException:
    headers = {"Retry-After": str(e.retry_after)} if e.retry_after else None
    return HTTPException(status_code=e.status, detail=e.message, headers=headers)


def _swallow(fut) -> None:
    """The worker of an abandoned request ends on its own; its outcome is nobody's to read."""
    if not fut.cancelled():
        fut.exception()


async def _run_cancellable(work, request: Request, cancel: ask_guard.CancelToken):
    """Run the blocking `work` in a thread; if the client disconnects meanwhile, cancel it.
    Returns its result, or None when the client is gone (the thread finishes and releases its
    concurrency slot by itself)."""
    loop = asyncio.get_running_loop()
    fut = loop.run_in_executor(None, work)
    while True:
        done, _ = await asyncio.wait({fut}, timeout=0.5)
        if done:
            return fut.result()
        if await request.is_disconnected():
            cancel.cancel("client_disconnected")
            fut.add_done_callback(_swallow)
            return None


@router.post("/ask")
async def ask(req: AskRequest, request: Request):
    debug = req.debug and config.ASK_DEBUG
    events: list[dict] = []
    cancel = ask_guard.CancelToken()
    t0 = time.monotonic()

    def work():
        try:
            return _answer(req, events.append if debug else None, cancel)
        except HTTPException as e:
            if debug:
                raise HTTPException(e.status_code, detail={"message": e.detail, "debug": _debug(req, events, t0)},
                                    headers=e.headers) from None
            raise

    out = await _run_cancellable(work, request, cancel)
    if out is None:
        return Response(status_code=499)          # the browser left; nothing to send
    if debug:
        out["debug"] = _debug(req, events, t0, out["budget"].get("dropped_debug_events", 0))
    return out


@router.post("/ask/stream")
async def ask_stream(req: AskRequest, request: Request):
    """Debug only: the agent's steps as NDJSON lines while it runs, then the result
    (``{"event": "result", "result": …}``) or the error (``{"event": "error", …}``). Closing the
    connection cancels the work; the stream always ends with a result or an error event."""
    if not config.ASK_DEBUG:
        raise HTTPException(status_code=404, detail="Not found")
    loop = asyncio.get_running_loop()
    queue: asyncio.Queue = asyncio.Queue()
    cancel = ask_guard.CancelToken()
    secrets = (req.api_key,) if req.api_key else ()

    def put(ev) -> None:
        try:
            loop.call_soon_threadsafe(queue.put_nowait, ev)
        except RuntimeError:       # the loop is closed: the server is shutting down
            pass

    def work():
        try:
            put({"event": "result", "result": _answer(req, put, cancel)})
        except HTTPException as e:
            put({"event": "error", "status": e.status_code, "detail": e.detail})
        except Exception as e:  # noqa: BLE001
            put({"event": "error", "status": 500, "detail": type(e).__name__})
        finally:
            put(None)

    fut = loop.run_in_executor(None, work)
    fut.add_done_callback(_swallow)

    async def lines():
        try:
            while (ev := await queue.get()) is not None:
                yield json.dumps(ask_guard.redact(ev, secrets), ensure_ascii=False, default=str) + "\n"
        finally:
            if not fut.done():                 # closed early: stop the work, free the slot when it ends
                cancel.cancel("client_disconnected")

    return StreamingResponse(lines(), media_type="application/x-ndjson")


def _debug(req: AskRequest, events: list[dict], t0: float, dropped: int = 0) -> dict:
    secrets = (req.api_key,) if req.api_key else ()
    return {"events": ask_guard.redact(events, secrets), "dropped_events": dropped,
            "elapsed_ms": int((time.monotonic() - t0) * 1000)}


def _answer(req: AskRequest, on_event=None, cancel: ask_guard.CancelToken | None = None) -> dict:
    """The /ask pipeline. ``on_event`` (debug only) receives every agent step."""
    # Hosted calls need TEMPO_ASK_ENABLED, own-key calls TEMPO_ASK_BYOK_ENABLED.
    # A key does not reopen an Ask the server has switched off.
    byok = bool(req.api_key) or ask_guard.is_keyless(req.provider)
    if byok and not config.ASK_BYOK_ENABLED:
        raise HTTPException(status_code=404, detail="Ask with your own key is not available on this server")
    if not byok and not config.ASK_ENABLED:
        raise HTTPException(status_code=404, detail="Ask endpoint is disabled")

    # 1-3. Reject bad input before any provider work.
    history = ask_guard.validate_history(req.history, req.question)
    context = ask_context.validate(req.context)
    provider, model = ask_guard.resolve_provider_model(req.provider, req.model, byok)

    secrets = (req.api_key,) if req.api_key else ()
    ts = datetime.now(timezone.utc).isoformat()
    t0 = time.monotonic()
    request_id = uuid.uuid4().hex[:12]
    base = {"request_id": request_id, "ts": ts, "provider": provider, "model": model, "byok": byok,
            "question_chars": len(req.question), "history_turns": len(history),
            "context_entries": len(context), "site_lang": req.lang}

    # 4. Concurrency bound (raises 503 + Retry-After; the slot is released only when the work ends).
    try:
        slot = ask_guard.concurrency_slot()
        slot.__enter__()
    except HTTPException:
        _log_metrics(**base, status=503, reason="busy")
        raise
    with ask_guard.secrets_scope(*secrets):        # also covers the handlers below that log
        try:
            result = run_agent(req.question, history, provider=provider, model=model,
                               api_key=req.api_key, on_event=on_event, context=context,
                               cancel=cancel, request_id=request_id, site_lang=req.lang)
        except LLMError as e:
            _log_metrics(**base, status=e.status, reason=e.code,
                         duration_ms=int((time.monotonic() - t0) * 1000))
            if config.ASK_LOG_CHATS:
                _write_chat_log({**base, "question": req.question, "error": e.code}, secrets)
            raise _http_from_llm(e) from None
        except Exception as e:
            # Never echo str(e): it may carry provider text, paths or credentials.
            log.error("Agent failed: %s", type(e).__name__)
            if on_event:
                on_event({"event": "server_error", "detail": ask_guard.redact_text(
                    f"{type(e).__name__}: {str(e)[:500]}", secrets)})
            _log_metrics(**base, status=500, reason=type(e).__name__[:40],
                         duration_ms=int((time.monotonic() - t0) * 1000))
            raise HTTPException(status_code=500, detail="Ask failed") from None
        finally:
            slot.__exit__(None, None, None)

    response = {
        "answer": result.answer,
        "citations": result.citations,
        "tool_trace": result.tool_trace,
        "data": result.data,
        "chart_spec": result.chart_spec,
        "warnings": result.warnings,
        "verification": result.verification,
        "stop_reason": result.stop_reason,
        "outcome": result.outcome,
        "reason": result.reason,
        "context": result.context,
        "budget": result.budget,
        "lang": result.lang,
    }

    _log_metrics(**{**base, **result.metrics, "status": 200,
                    "elapsed_s": result.budget.get("elapsed_s")})

    if config.ASK_LOG_CHATS:
        _write_chat_log({
            **base,
            "question": req.question,
            "answer": result.answer,
            "tool_trace": result.tool_trace,
            "warnings": result.warnings,
            "citations": result.citations,
        }, secrets)

    return response
