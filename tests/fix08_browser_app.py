"""Tiny ASGI app for the FIX-08 browser test: the real Ask router + real static files,
with the provider mocked (no network, no keys, no corpus needed).

Run: uvicorn fix08_browser_app:app --app-dir tests --port 8098
"""
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.routers import ask as ask_router
from app.services import agent
from app.services.llm_client import LLMResponse

LAST_REQUEST = {}


def _fake_complete(messages, tools, **kw):
    LAST_REQUEST.update(provider=kw.get("provider"), model=kw.get("model"),
                        got_key=bool(kw.get("api_key")))
    return LLMResponse(stop_reason="end_turn", text="Răspuns de test (mock).", tool_calls=[])


agent.complete_with_tools = _fake_complete
agent.get_conn = lambda: object()

app = FastAPI()
app.include_router(ask_router.router, prefix="/api")


@app.get("/__last")
def last():
    return LAST_REQUEST


app.mount("/", StaticFiles(directory=Path(__file__).resolve().parent.parent / "app" / "static", html=True))
