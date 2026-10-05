"""POST /api/ask — user-facing NL→Data agent endpoint.

Gated by TEMPO_ASK_ENABLED (BYOK requests are allowed even when it is off).

Request pipeline (FIX-08): validate history -> resolve provider/model against the
allowlist -> take a concurrency slot -> run the budgeted agent. Nothing reaches a
provider before the first three steps pass.

Logging contract
----------------
* ALWAYS: one operational line per request, ``ASK_METRICS {json}``, containing only
  status, provider/model, byok flag, budgets used and sizes. No question, answer,
  history, tool payload or credential.
* Only when TEMPO_ASK_LOG_CHATS=true (default OFF): an additional ``CHAT_LOG {json}``
  line on stdout and logs/ask-chats.jsonl with question/answer/tool_trace. Credentials
  are redacted recursively. GET /api/ask/config tells the UI so it can disclose this
  before a question is submitted. Retention is that of the log sink (fly logs / local
  file); nothing here rotates or deletes it.
"""
import json
import logging
import time
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app import config
from app.services import ask_guard
from app.services.agent import run_agent
from app.services.llm_client import LLMError

log = logging.getLogger(__name__)
log.addFilter(ask_guard.RedactingFilter())


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
    log.info("ASK_METRICS %s", json.dumps(fields, ensure_ascii=False, default=str))


router = APIRouter()


class AskRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=2000)
    # Raw list: elements are validated (role/content/size) in ask_guard.validate_history
    history: list = Field(default_factory=list)
    # BYOK fields — optional; sent to the provider through this server, never stored
    provider: str | None = Field(default=None, max_length=40)   # "anthropic" | "openai" | "gemini"
    model: str | None = Field(default=None, max_length=100)
    api_key: str | None = Field(default=None, max_length=400)


@router.get("/ask/config")
def ask_config() -> dict:
    """Public, non-secret settings the chat UI needs (logging disclosure, limits)."""
    return {
        "enabled": config.ASK_ENABLED,
        "chat_logging": config.ASK_LOG_CHATS,
        "limits": {
            "max_history_turns": config.ASK_MAX_HISTORY_TURNS,
            "max_turn_chars": config.ASK_MAX_TURN_CHARS,
            "max_request_chars": config.ASK_MAX_REQUEST_CHARS,
            "max_seconds": config.ASK_MAX_SECONDS,
        },
        "byok_models": ask_guard.byok_allowlist(),
    }


def _http_from_llm(e: LLMError) -> HTTPException:
    headers = {"Retry-After": str(e.retry_after)} if e.retry_after else None
    return HTTPException(status_code=e.status, detail=e.message, headers=headers)


@router.post("/ask")
def ask(req: AskRequest) -> dict:
    # Allow if server is enabled OR if user supplies their own key (BYOK)
    byok = bool(req.api_key)
    if not config.ASK_ENABLED and not byok:
        raise HTTPException(status_code=404, detail="Ask endpoint is disabled")

    # 1-2. Reject bad input before any provider work.
    history = ask_guard.validate_history(req.history, req.question)
    provider, model = ask_guard.resolve_provider_model(req.provider, req.model, byok)

    secrets = (req.api_key,) if req.api_key else ()
    ts = datetime.now(timezone.utc).isoformat()
    t0 = time.monotonic()
    base = {"ts": ts, "provider": provider, "model": model, "byok": byok,
            "question_chars": len(req.question), "history_turns": len(history)}

    # 3. Concurrency bound (raises 503 + Retry-After; slot is always released).
    try:
        slot = ask_guard.concurrency_slot()
        slot.__enter__()
    except HTTPException:
        _log_metrics(**base, status=503, reason="busy")
        raise
    try:
        result = run_agent(req.question, history,
                           provider=provider, model=model, api_key=req.api_key)
    except LLMError as e:
        _log_metrics(**base, status=e.status, reason=e.code,
                     elapsed_ms=int((time.monotonic() - t0) * 1000))
        if config.ASK_LOG_CHATS:
            _write_chat_log({**base, "question": req.question, "error": e.code}, secrets)
        raise _http_from_llm(e) from None
    except Exception as e:
        # Never echo str(e): it may carry provider text, paths or credentials.
        log.error("Agent failed: %s", type(e).__name__)
        _log_metrics(**base, status=500, reason=type(e).__name__,
                     elapsed_ms=int((time.monotonic() - t0) * 1000))
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
        "stop_reason": result.stop_reason,
        "budget": result.budget,
    }

    _log_metrics(**base, status=200, stop_reason=result.stop_reason, **{
        k: v for k, v in result.budget.items() if k in ("iterations", "tools", "elapsed_s")})

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
