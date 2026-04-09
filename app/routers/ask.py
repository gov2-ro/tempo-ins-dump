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


@router.post("/ask")
def ask(req: AskRequest) -> dict:
    if not config.ASK_ENABLED:
        raise HTTPException(status_code=404, detail="Ask endpoint is disabled")
    try:
        result = run_agent(req.question, req.history)
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
