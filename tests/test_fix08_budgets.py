"""FIX-08 items 3, 4 (reworked by AT-02): independent budgets, deadlines, concurrency bound.

The loop reserves its last model call for the final answer with tools disabled, so a model
that keeps asking for tools is answered from what was gathered rather than discarded.
"""
import threading
import time

import pytest

from fix08_helpers import install, make_client, text_resp, tools_resp
from app import config
from app.services import agent, ask_guard


@pytest.fixture(autouse=True)
def _ask_on(monkeypatch):
    monkeypatch.setattr(config, "ASK_ENABLED", True)
    monkeypatch.setattr(config, "ASK_BYOK_ENABLED", True)


def run(**kw):
    return agent.run_agent("Care este rata șomajului?", [], **kw)


def test_many_tools_in_one_response_never_exceed_budget(monkeypatch):
    monkeypatch.setattr(config, "ASK_MAX_TOOL_CALLS", 5)
    dispatched = []
    install(monkeypatch, lambda n, m, kw: tools_resp(50),
            handler=lambda name, args: dispatched.append(1) or agent._synthetic(name, "ok", None, "ok"))
    res = run()
    assert len(dispatched) == 5
    assert res.stop_reason == "tools"
    assert res.budget["tools"] == 5 and len(res.tool_trace) == 5
    assert any("tool-call limit" in w for w in res.warnings)
    assert res.answer  # useful bounded message, not an exception


def test_calls_over_the_tool_budget_still_get_a_result_for_the_provider(monkeypatch):
    """The 45 calls that cannot run are answered (call/result pairing), just not executed."""
    monkeypatch.setattr(config, "ASK_MAX_TOOL_CALLS", 5)
    calls = install(monkeypatch, lambda n, m, kw: tools_resp(50) if n == 1 else text_resp("gata"))
    res = run()
    sent = calls[1]["messages"]
    ids = {b["id"] for b in sent[-2]["content"] if b["type"] == "tool_use"}      # anthropic blocks
    answered = {b["tool_use_id"] for b in sent[-1]["content"]}
    assert ids == answered and len(ids) == 50
    assert res.answer == "gata" and res.outcome == "partial" and res.reason == "tools"


def test_tool_budget_spans_iterations(monkeypatch):
    monkeypatch.setattr(config, "ASK_MAX_TOOL_CALLS", 7)
    dispatched = []
    install(monkeypatch, lambda n, m, kw: tools_resp(3),
            handler=lambda name, args: dispatched.append(1) or agent._synthetic(name, "ok", None, "ok"))
    res = run()
    assert len(dispatched) == 7 and res.stop_reason == "tools"


def test_iteration_budget_reserves_the_last_call_for_the_answer(monkeypatch):
    monkeypatch.setattr(config, "ASK_MAX_ITERATIONS", 3)
    monkeypatch.setattr(config, "ASK_MAX_TOOL_CALLS", 100)
    calls = install(monkeypatch, lambda n, m, kw: tools_resp(1, text="partial thoughts"))
    res = run()
    assert len(calls) == 3
    assert [c["tool_choice"] for c in calls] == ["auto", "auto", "none"]   # tools off on the last
    assert res.stop_reason == "iterations"
    assert res.answer == "partial thoughts"
    # the last response still asked for a tool: it could never be read, so it was not run
    assert res.budget["tools"] == 2


def test_the_final_call_is_a_real_answer_not_a_discarded_tool_request(monkeypatch):
    monkeypatch.setattr(config, "ASK_MAX_ITERATIONS", 3)
    calls = install(monkeypatch,
                    lambda n, m, kw: tools_resp(1) if kw["tool_choice"] == "auto" else text_resp("din ce am"))
    res = run()
    assert [c["tool_choice"] for c in calls] == ["auto", "auto", "none"]
    assert res.answer == "din ce am"
    assert (res.outcome, res.reason, res.stop_reason) == ("partial", "iterations", "iterations")


def test_normal_answer_reports_budget(monkeypatch):
    calls = install(monkeypatch, lambda n, m, kw: tools_resp(2) if n == 1 else text_resp("gata"))
    res = run()
    assert res.stop_reason == "end_turn" and res.answer == "gata"
    assert res.budget["tools"] == 2 and res.budget["iterations"] == 2 and len(calls) == 2
    assert res.outcome == "answered" and res.reason is None


def test_deadline_stops_before_next_call_and_caps_provider_timeout(monkeypatch):
    monkeypatch.setattr(config, "ASK_MAX_SECONDS", 0.3)
    monkeypatch.setattr(config, "ASK_PROVIDER_TIMEOUT", 30)
    monkeypatch.setattr(agent, "MIN_CALL_SECONDS", 0.05)

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


def test_no_provider_call_starts_without_time_for_it(monkeypatch):
    monkeypatch.setattr(config, "ASK_MAX_SECONDS", 1.0)             # < MIN_CALL_SECONDS
    calls = install(monkeypatch, lambda n, m, kw: text_resp())
    res = run()
    assert calls == [] and res.stop_reason == "deadline" and res.outcome == "failed"
    assert res.answer


def test_deadline_between_tools(monkeypatch):
    monkeypatch.setattr(config, "ASK_MAX_SECONDS", 0.3)
    monkeypatch.setattr(agent, "MIN_CALL_SECONDS", 0.05)
    n_done = []

    def slow(name, args):
        time.sleep(0.2)
        n_done.append(1)
        return agent._synthetic(name, "ok", None, "ok")

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

    calls = install(monkeypatch, resp)
    res = run()
    assert res.stop_reason == "provider" and len(res.tool_trace) == 1
    assert len(calls) == 3                       # the first call, the failure, its one retry
    assert res.outcome in ("partial", "failed") and res.reason == "provider"


def test_one_provider_retry_recovers_a_transient_failure(monkeypatch):
    class APITimeoutError(Exception):
        pass

    def resp(n, m, kw):
        if n == 1:
            raise APITimeoutError("stalled")
        return text_resp("gata")

    calls = install(monkeypatch, resp)
    res = run()
    assert res.answer == "gata" and len(calls) == 2 and res.budget["iterations"] == 2
    assert res.metrics["retries"] == 1


def test_the_loop_owns_retries_so_the_sdk_gets_none(monkeypatch):
    calls = install(monkeypatch, lambda n, m, kw: text_resp())
    run()
    assert calls[0]["max_retries"] == 0


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
