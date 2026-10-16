"""AT-02: abandoning a request stops its work without touching anyone else's.

Real DuckDB cursors: a heavy query on the cancelled request's own cursor is interrupted, a
second request on another cursor of the same database succeeds, and every slot is released.
"""
import asyncio
import threading
import time

import duckdb
import pytest

from fix08_helpers import fake_env, text_resp, tools_resp
from app import config
from app.routers import ask as ask_router
from app.services import agent, ask_guard

HEAVY = "select sum(a.range * b.range) from range(200000) a, range(200000) b"


@pytest.fixture(autouse=True)
def _ask_on(monkeypatch):
    monkeypatch.setattr(config, "ASK_ENABLED", True)
    monkeypatch.setattr(config, "ASK_BYOK_ENABLED", True)
    monkeypatch.setattr(config, "ASK_DEBUG", True)
    monkeypatch.setattr(agent, "RETRY_PAUSE_SECONDS", 0.0)


@pytest.fixture
def parent():
    return duckdb.connect(":memory:")


def wire(monkeypatch, parent, responder, slow=True):
    """Each run gets its own cursor of `parent`; the tool is a heavy query on that cursor."""
    ran = []

    def get_conn():
        return parent.cursor()

    def call_tool(name, args, *, conn=None):
        if name == "get_evidence_links":
            return fake_env(name, data={"links": []})
        started = time.monotonic()
        try:
            conn.execute(HEAVY if slow and args.get("heavy") else "select 1").fetchall()
            ran.append(("finished", time.monotonic() - started))
        except duckdb.InterruptException:
            ran.append(("interrupted", time.monotonic() - started))
            raise
        return fake_env(name)

    calls = []

    def complete(messages, tools, **kw):
        calls.append(kw)
        return responder(len(calls), messages, kw)

    monkeypatch.setattr(agent, "get_conn", get_conn)
    monkeypatch.setattr(agent, "call_tool", call_tool)
    monkeypatch.setattr(agent, "complete_with_tools", complete)
    return ran, calls


def test_cancel_between_model_calls_ends_the_loop(monkeypatch, parent):
    token, gate, entered = ask_guard.CancelToken(), threading.Event(), threading.Event()

    def responder(n, m, kw):
        entered.set()
        gate.wait(5)                                   # a provider call in flight
        return tools_resp(1)

    ran, calls = wire(monkeypatch, parent, responder)
    out = {}
    t = threading.Thread(target=lambda: out.setdefault("r", agent.run_agent("Care?", provider="anthropic",
                                                                            api_key="k", cancel=token)))
    t.start()
    assert entered.wait(5)
    token.cancel("client_disconnected")
    gate.set()
    t.join(5)
    r = out["r"]
    assert (r.outcome, r.reason, r.stop_reason) == ("failed", "cancelled", "cancelled")
    assert len(calls) == 1 and ran == [] and r.metrics["cancelled"] is True


def test_cancel_interrupts_the_running_query_and_another_request_succeeds(monkeypatch, parent):
    token, started = ask_guard.CancelToken(), threading.Event()

    def responder(n, m, kw):
        if kw["max_tokens"] and n == 1 and not started.is_set():
            started.set()
            return tools_resp(1, args={"heavy": True})
        return text_resp("gata")

    ran, calls = wire(monkeypatch, parent, responder)
    out = {}
    t0 = time.monotonic()
    a = threading.Thread(target=lambda: out.setdefault("a", agent.run_agent(
        "Care?", provider="anthropic", api_key="k", cancel=token)))
    a.start()
    assert started.wait(5)
    time.sleep(0.4)                                    # the heavy query is running on A's cursor

    # a second request, other cursor, same database, meanwhile
    b = agent.run_agent("Altă întrebare?", provider="anthropic", api_key="k")
    assert b.answer == "gata" and b.outcome == "answered"

    token.cancel("client_disconnected")
    a.join(10)
    assert not a.is_alive() and time.monotonic() - t0 < 8
    assert [x[0] for x in ran if x[0] == "interrupted"] == ["interrupted"]
    ra = out["a"]
    assert ra.outcome == "failed" and ra.reason == "cancelled"


def test_the_deadline_interrupts_a_tool_that_would_run_past_it(monkeypatch, parent):
    monkeypatch.setattr(config, "ASK_MAX_SECONDS", 1.5)
    monkeypatch.setattr(agent, "MIN_CALL_SECONDS", 0.05)
    ran, _ = wire(monkeypatch, parent, lambda n, m, kw: tools_resp(1, args={"heavy": True}))
    t0 = time.monotonic()
    r = agent.run_agent("Care?", provider="anthropic", api_key="k")
    assert time.monotonic() - t0 < 6
    assert ran[0][0] == "interrupted"
    assert r.stop_reason == "deadline" and r.metrics["timed_out"] is True


def test_closing_the_stream_cancels_the_work_and_frees_the_slot(monkeypatch, parent):
    started = threading.Event()

    def responder(n, m, kw):
        started.set()
        return tools_resp(1, args={"heavy": True}) if n == 1 else text_resp("nu ajunge")

    ran, calls = wire(monkeypatch, parent, responder)
    req = ask_router.AskRequest(question="Care?", provider="anthropic", model="claude-sonnet-5-5",
                                api_key="k-123456", debug=True)
    seen = {}

    async def go():
        resp = await ask_router.ask_stream(req, None)
        it = resp.body_iterator
        seen["first"] = await it.__anext__()                      # the stream has started
        await asyncio.get_running_loop().run_in_executor(None, started.wait, 5)
        await asyncio.sleep(0.4)                                  # the heavy query is running
        assert ask_guard.active_requests() == 1
        await it.aclose()                                         # the browser went away

    asyncio.run(go())
    deadline = time.monotonic() + 8
    while ask_guard.active_requests() and time.monotonic() < deadline:
        time.sleep(0.05)
    assert ask_guard.active_requests() == 0                       # the slot was released
    assert [x[0] for x in ran] == ["interrupted"] and len(calls) == 1


def test_a_disconnect_on_the_plain_endpoint_cancels_the_token(monkeypatch):
    class Gone:
        polls = 0

        async def is_disconnected(self):
            Gone.polls += 1
            return Gone.polls >= 2

    token = ask_guard.CancelToken()
    stopped = threading.Event()

    def work():
        while not token.cancelled:
            time.sleep(0.02)
        stopped.set()
        return {"never": "sent"}

    async def go():
        return await ask_router._run_cancellable(work, Gone(), token)

    assert asyncio.run(go()) is None
    assert token.cancelled and token.reason == "client_disconnected"
    assert stopped.wait(3)                                        # the worker noticed and ended
