"""FIX-08 items 3, 4: independent budgets, deadlines, concurrency bound."""
import threading
import time

import pytest

from fix08_helpers import install, make_client, text_resp, tools_resp
from app import config
from app.services import agent, ask_guard


@pytest.fixture(autouse=True)
def _ask_on(monkeypatch):
    monkeypatch.setattr(config, "ASK_ENABLED", True)


def run(**kw):
    return agent.run_agent("Care este rata șomajului?", [], **kw)


def test_many_tools_in_one_response_never_exceed_budget(monkeypatch):
    monkeypatch.setattr(config, "ASK_MAX_TOOL_CALLS", 5)
    dispatched = []
    install(monkeypatch, lambda n, m, kw: tools_resp(50),
            handler=lambda inp, conn: dispatched.append(1) or {"categories": []})
    res = run()
    assert len(dispatched) == 5
    assert res.stop_reason == "tools"
    assert res.budget["tools"] == 5 and len(res.tool_trace) == 5
    assert any("tool-call limit" in w for w in res.warnings)
    assert res.answer  # useful bounded message, not an exception


def test_tool_budget_spans_iterations(monkeypatch):
    monkeypatch.setattr(config, "ASK_MAX_TOOL_CALLS", 7)
    dispatched = []
    install(monkeypatch, lambda n, m, kw: tools_resp(3),
            handler=lambda inp, conn: dispatched.append(1) or {"categories": []})
    res = run()
    assert len(dispatched) == 7 and res.stop_reason == "tools"


def test_iteration_budget_stops_before_extra_provider_call(monkeypatch):
    monkeypatch.setattr(config, "ASK_MAX_ITERATIONS", 3)
    monkeypatch.setattr(config, "ASK_MAX_TOOL_CALLS", 100)
    calls = install(monkeypatch, lambda n, m, kw: tools_resp(1, text="partial thoughts"))
    res = run()
    assert len(calls) == 3
    assert res.stop_reason == "iterations"
    assert res.answer == "partial thoughts"
    # the last model response asked for a tool that could never be read: not dispatched
    assert res.budget["tools"] == 2


def test_normal_answer_reports_budget(monkeypatch):
    calls = install(monkeypatch, lambda n, m, kw: tools_resp(2) if n == 1 else text_resp("gata"))
    res = run()
    assert res.stop_reason == "end_turn" and res.answer == "gata"
    assert res.budget["tools"] == 2 and res.budget["iterations"] == 2 and len(calls) == 2


def test_deadline_stops_before_next_call_and_caps_provider_timeout(monkeypatch):
    monkeypatch.setattr(config, "ASK_MAX_SECONDS", 0.3)
    monkeypatch.setattr(config, "ASK_PROVIDER_TIMEOUT", 30)

    def stall(n, m, kw):
        time.sleep(0.4)  # a provider call that overruns the whole request budget
        return tools_resp(1)

    calls = install(monkeypatch, stall)
    t0 = time.monotonic()
    res = run()
    assert time.monotonic() - t0 < 2
    assert len(calls) == 1
    assert calls[0]["timeout"] <= 1.0  # provider timeout is clamped to remaining budget
    assert res.stop_reason == "deadline"


def test_deadline_between_tools(monkeypatch):
    monkeypatch.setattr(config, "ASK_MAX_SECONDS", 0.3)
    n_done = []

    def slow(inp, conn):
        time.sleep(0.2)
        n_done.append(1)
        return {"categories": []}

    install(monkeypatch, lambda n, m, kw: tools_resp(10), handler=slow)
    res = run()
    assert res.stop_reason == "deadline" and len(n_done) < 10


def test_transient_provider_failure_after_tools_returns_partial(monkeypatch):
    class APITimeoutError(Exception):
        pass

    def resp(n, m, kw):
        if n == 1:
            return tools_resp(1)
        raise APITimeoutError("stalled")

    install(monkeypatch, resp)
    res = run()
    assert res.stop_reason == "provider" and len(res.tool_trace) == 1


def test_provider_retry_limit_is_passed_to_sdk(monkeypatch):
    """Explicit timeout/max_retries reach the SDK constructors (mocked, no network)."""
    import sys
    import types
    import app.services.llm_client as lc
    seen = {}

    class FakeAnthropic:
        def __init__(self, **kw):
            seen.update(kw)
            self.messages = types.SimpleNamespace(
                create=lambda **k: types.SimpleNamespace(content=[], stop_reason="end_turn"))

    monkeypatch.setitem(sys.modules, "anthropic", types.SimpleNamespace(Anthropic=FakeAnthropic))
    monkeypatch.setattr(config, "ASK_PROVIDER_MAX_RETRIES", 1)
    lc.complete_with_tools([{"role": "user", "content": "x"}], [], provider="anthropic",
                           model="claude-sonnet-4-6", api_key="k", timeout=12)
    assert seen["timeout"] == 12 and seen["max_retries"] == 1


# --- concurrency ----------------------------------------------------------

def test_concurrency_bound_rejects_with_retry_after_and_releases(monkeypatch):
    monkeypatch.setattr(config, "ASK_MAX_CONCURRENT", 2)
    monkeypatch.setattr(config, "ASK_RETRY_AFTER_SECONDS", 7)
    gate, entered = threading.Event(), threading.Semaphore(0)

    def blocked(n, m, kw):
        entered.release()
        gate.wait(5)
        return text_resp("ok")

    install(monkeypatch, blocked)
    client = make_client()
    results = []

    def go():
        results.append(client.post("/api/ask", json={"question": "x"}))

    threads = [threading.Thread(target=go) for _ in range(2)]
    for t in threads:
        t.start()
    assert entered.acquire(timeout=5) and entered.acquire(timeout=5)
    assert ask_guard.active_requests() == 2

    r = client.post("/api/ask", json={"question": "third"})
    assert r.status_code == 503 and r.headers["Retry-After"] == "7"

    gate.set()
    for t in threads:
        t.join(5)
    assert sorted(x.status_code for x in results) == [200, 200]
    assert ask_guard.active_requests() == 0  # no leak
    assert client.post("/api/ask", json={"question": "again"}).status_code == 200


def test_slot_released_after_agent_exception(monkeypatch):
    def boom(n, m, kw):
        raise RuntimeError("x")
    install(monkeypatch, boom)
    client = make_client()
    for _ in range(5):  # more failures than slots: a leak would turn these into 503
        assert client.post("/api/ask", json={"question": "x"}).status_code in (500, 502)
    assert ask_guard.active_requests() == 0


def test_invalid_request_does_not_take_a_slot(monkeypatch):
    monkeypatch.setattr(config, "ASK_MAX_CONCURRENT", 1)
    install(monkeypatch, lambda n, m, kw: text_resp())
    client = make_client()
    for _ in range(3):
        assert client.post("/api/ask", json={"question": "x", "provider": "nope",
                                             "api_key": "k"}).status_code == 400
    assert ask_guard.active_requests() == 0
