"""Shared helpers for the FIX-08 Ask tests. Everything provider-facing is mocked."""
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.routers import ask as ask_router
from app.services import agent
from app.services.llm_client import LLMResponse

FAKE_KEY = "sk-ant-SENTINEL0123456789abcdef"


def make_client() -> TestClient:
    app = FastAPI()
    app.include_router(ask_router.router, prefix="/api")
    return TestClient(app, raise_server_exceptions=False)


class FakeConn:
    pass


def text_resp(text="ok"):
    return LLMResponse(stop_reason="end_turn", text=text, tool_calls=[])


def tools_resp(n, name="list_categories", text=None):
    return LLMResponse(stop_reason="tool_use", text=text,
                       tool_calls=[{"id": f"t{i}", "name": name, "input": {}} for i in range(n)])


def install(monkeypatch, responder, handler=None):
    """Patch the agent's provider call and tool handlers. Returns the call log."""
    calls = []

    def fake_complete(messages, tools, **kw):
        calls.append({"messages": list(messages), **kw})
        return responder(len(calls), messages, kw)

    monkeypatch.setattr(agent, "complete_with_tools", fake_complete)
    monkeypatch.setattr(agent, "get_conn", lambda: FakeConn())
    monkeypatch.setitem(agent.TOOL_HANDLERS, "list_categories",
                        handler or (lambda inp, conn: {"categories": []}))
    return calls
