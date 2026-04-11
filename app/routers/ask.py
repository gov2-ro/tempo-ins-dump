"""POST /api/ask — user-facing NL→Data agent endpoint.

Gated by TEMPO_ASK_ENABLED. Disabled by default.

Set TEMPO_ASK_LOG_CHATS=true to write chat sessions to logs/ask-chats.jsonl.
Each line is a JSON object: {ts, question, provider, model, answer, tool_trace, warnings, error?}
API keys are NEVER logged.
"""
import json
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

log = logging.getLogger(__name__)

from app import config
from app.services.agent import run_agent


def _write_chat_log(entry: dict) -> None:
    """Log a chat entry to stdout (always) and to logs/ask-chats.jsonl (local dev).

    Stdout output is visible via `fly logs` on Fly.io.
    File output is for local debugging convenience.
    API keys are NEVER included.
    """
    line = json.dumps(entry, ensure_ascii=False, default=str)
    # Always emit to stdout so `fly logs` captures it
    log.info("CHAT_LOG %s", line)
    # Also write to file when a log dir is configured (local dev)
    try:
        config.ASK_LOG_DIR.mkdir(parents=True, exist_ok=True)
        log_path = config.ASK_LOG_DIR / "ask-chats.jsonl"
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        log.exception("Failed to write chat log file")

router = APIRouter()


class AskRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=2000)
    history: list[dict] = Field(default_factory=list)
    # BYOK fields — optional, never logged or stored server-side
    provider: str | None = None   # "anthropic" | "openai"
    model: str | None = None      # e.g. "gpt-4o", "claude-sonnet-4-6"
    api_key: str | None = None    # user-supplied API key


@router.post("/ask")
def ask(req: AskRequest) -> dict:
    # Allow if server is enabled OR if user supplies their own key (BYOK)
    if not config.ASK_ENABLED and not req.api_key:
        raise HTTPException(status_code=404, detail="Ask endpoint is disabled")

    ts = datetime.now(timezone.utc).isoformat()
    try:
        result = run_agent(req.question, req.history,
                           provider=req.provider, model=req.model, api_key=req.api_key)
    except Exception as e:
        log.exception("Agent failed")
        if config.ASK_LOG_CHATS:
            _write_chat_log({
                "ts": ts,
                "question": req.question,
                "provider": req.provider,
                "model": req.model,
                # api_key intentionally omitted
                "error": str(e),
            })
        raise HTTPException(status_code=500, detail=f"Agent error: {e}")

    response = {
        "answer": result.answer,
        "citations": result.citations,
        "tool_trace": result.tool_trace,
        "data": result.data,
        "chart_spec": result.chart_spec,
        "warnings": result.warnings,
    }

    if config.ASK_LOG_CHATS:
        _write_chat_log({
            "ts": ts,
            "question": req.question,
            "provider": req.provider,
            "model": req.model,
            # api_key intentionally omitted
            "answer": result.answer,
            "tool_trace": result.tool_trace,
            "warnings": result.warnings,
            "citations": result.citations,
        })

    return response
