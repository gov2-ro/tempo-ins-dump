"""Shared helpers for the Ask tests (FIX-08, AT-02). Everything provider-facing is mocked.

The agent dispatches the eight shared tools through ``agent.call_tool``; these helpers
replace it (and the provider call) so the loop's budgets, retries and logging can be tested
without a corpus. Tests that need real statistics use the synthetic corpora instead.
"""
import itertools

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.routers import ask as ask_router
from app.services import agent
from app.services.llm_client import LLMResponse
from app.services.tools import contract as C

FAKE_KEY = "sk-ant-SENTINEL0123456789abcdef"
_ids = itertools.count()


def make_client() -> TestClient:
    app = FastAPI()
    app.include_router(ask_router.router, prefix="/api")
    return TestClient(app, raise_server_exceptions=False)


class FakeConn:
    """Stands in for the cursor the agent owns."""

    def interrupt(self):
        pass

    def close(self):
        pass


def text_resp(text="ok", **kw):
    return LLMResponse(stop_reason="end_turn", text=text, tool_calls=[], finish="complete", **kw)


def tools_resp(n, name="discover_indicators", text=None, args=None):
    """n tool calls, each with distinct arguments (so none is a repeat) unless `args` is given."""
    calls = []
    for _ in range(n):
        i = next(_ids)
        calls.append({"id": f"t{i}", "name": name, "input": dict(args) if args else {"query": f"q{i}"}})
    return LLMResponse(stop_reason="tool_use", text=text, tool_calls=calls, finish="tool_use")


def fake_env(tool="discover_indicators", status="ok", reason=None, message="", data=None,
             selection=None, sources=None, warnings=(), recovery=(), rows=None, aggregation=None,
             generation="gen-test"):
    """A valid-shaped `tempo-tools/2` envelope (the contract's own builder)."""
    ctx = C.ToolContext(conn=None, lang="ro", request_id="t",
                        generation={"id": generation, "status": "present" if generation else "missing",
                                    "built_at": None})
    prov = {}
    if selection is not None:
        prov["selection"] = selection
    if sources is not None:
        prov["sources"] = sources
    if aggregation is not None:
        prov["aggregation"] = aggregation
    data = data if data is not None else ({"columns": ["REF_AREA", "OBS_VALUE"], "rows": rows} if rows else {})
    return C.envelope(tool, ctx, status=status, reason=reason, message=message, data=data,
                      provenance=prov, limits={"returned_rows": len(rows)} if rows else None,
                      warnings=list(warnings), recovery=list(recovery))


def install(monkeypatch, responder, handler=None):
    """Patch the agent's provider call and tool dispatch. Returns the provider call log.

    `handler(name, arguments)` returns the envelope (or raises); the default answers every
    tool with an empty ok envelope. `responder(n, messages, kw)` answers the n-th model call."""
    calls = []

    def fake_complete(messages, tools, **kw):
        calls.append({"messages": list(messages), **kw})
        return responder(len(calls), messages, kw)

    def fake_call_tool(name, arguments, *, conn=None):
        if handler is not None:
            return handler(name, arguments)
        if name == "get_evidence_links":
            return fake_env(name, data={"links": []})
        return fake_env(name)

    monkeypatch.setattr(agent, "complete_with_tools", fake_complete)
    monkeypatch.setattr(agent, "get_conn", lambda: FakeConn())
    monkeypatch.setattr(agent, "call_tool", fake_call_tool)
    monkeypatch.setattr(agent, "RETRY_PAUSE_SECONDS", 0.0)
    return calls
