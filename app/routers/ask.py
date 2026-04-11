"""POST /api/ask — user-facing NL→Data agent endpoint.

Gated by TEMPO_ASK_ENABLED. Disabled by default.
"""
import logging

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

log = logging.getLogger(__name__)

from app import config
from app.services.agent import run_agent

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
    try:
        result = run_agent(req.question, req.history,
                           provider=req.provider, model=req.model, api_key=req.api_key)
    except Exception as e:
        log.exception("Agent failed")
        raise HTTPException(status_code=500, detail=f"Agent error: {e}")
    return {
        "answer": result.answer,
        "citations": result.citations,
        "tool_trace": result.tool_trace,
        "data": result.data,
        "chart_spec": result.chart_spec,
        "warnings": result.warnings,
    }
