"""PKG-MCP-HARDEN (audit findings S1, S2, S3, S5, S6, S7) on the public MCP.

Per-client fair share in front of the global ceilings, a bounded and argument-free refusal log,
a deadline that keeps interrupting, a normalized cache key, hang-up cancellation, privacy wording.
"""
import asyncio
import json
import time

import pytest

import at03_env as E
from app import config
from app.services import public_mcp as P
from app.services.tools import registry as R
from test_at03_resources import QUERY, Counting, heavy, run, wait_until

pytestmark = pytest.mark.filterwarnings("ignore::DeprecationWarning")

CALL = {"jsonrpc": "2.0", "id": 2, "method": "tools/call",
        "params": {"name": "describe_dataset", "arguments": {"dataset": "POPC"}}}


def fly(ip, **extra):
    return {**E.HEADERS, "fly-client-ip": ip, **extra}


# ---------------------------------------------------------------- S1: per-client windows

def test_refused_origins_of_one_client_do_not_throttle_another(tmp_path, monkeypatch):
    app, mcp = E.make_app(tmp_path, monkeypatch, environ={
        "TEMPO_MCP_CLIENT_REQUESTS_PER_MINUTE": "3", "TEMPO_MCP_MAX_REQUESTS_PER_MINUTE": "5"})

    async def go():
        async with E.started(app), E.http(app) as c:
            bad = [await c.post("/mcp", json=E.RPC, headers=fly("1.1.1.1", origin="https://evil.example"))
                   for _ in range(5)]
            ok = await c.post("/mcp", json=E.RPC, headers=fly("2.2.2.2"))
            again = await c.post("/mcp", json=E.RPC, headers=fly("1.1.1.1"))
            return bad, ok, again
    bad, ok, again = run(go())
    assert [r.status_code for r in bad] == [403, 403, 403, 429, 429]      # A pays for its own refusals
    assert "retry-after" in bad[3].headers
    assert ok.status_code == 200                                           # B is not throttled
    assert again.status_code == 429                                        # A stays throttled
    assert len(mcp.endpoint.requests._hits) == 1                            # only B's request used the global window


def test_the_global_request_ceiling_still_applies_across_clients(tmp_path, monkeypatch):
    app, _ = E.make_app(tmp_path, monkeypatch, environ={"TEMPO_MCP_MAX_REQUESTS_PER_MINUTE": "3"})

    async def go():
        async with E.started(app), E.http(app) as c:
            return [(await c.post("/mcp", json=E.RPC, headers=fly(f"9.9.9.{i}"))).status_code for i in range(5)]
    assert run(go()) == [200, 200, 200, 429, 429]


def test_x_forwarded_for_is_ignored_unless_trusted(tmp_path, monkeypatch):
    env = {}

    async def codes(environ):
        app, _ = E.make_app(tmp_path, monkeypatch, env=env.get("e"),
                            environ={"TEMPO_MCP_CLIENT_REQUESTS_PER_MINUTE": "2", **environ})
        env["e"] = app.state.corpus_env
        async with E.started(app), E.http(app) as c:
            return [(await c.post("/mcp", json=E.RPC, headers={**E.HEADERS, "x-forwarded-for": f"5.5.5.{i}"}))
                    .status_code for i in range(3)]
    assert run(codes({})) == [200, 200, 429]                              # rotating the header buys nothing
    assert run(codes({"TEMPO_MCP_TRUST_FORWARDED": "true"})) == [200, 200, 200]
    with pytest.raises(P.McpConfigError):
        P.McpSettings.from_env({"TEMPO_MCP_ENABLED": "true", "TEMPO_MCP_TRUST_FORWARDED": "maybe"},
                               base_url="https://mcp.example.org")


def test_calls_are_throttled_per_client_and_the_client_reaches_the_gate(tmp_path, monkeypatch):
    app, mcp = E.make_app(tmp_path, monkeypatch, environ={"TEMPO_MCP_CLIENT_CALLS_PER_MINUTE": "2"})

    async def go():
        async with E.started(app), E.http(app) as c:
            a = [await c.post("/mcp", json=CALL, headers=fly("1.1.1.1")) for _ in range(3)]
            b = await c.post("/mcp", json=CALL, headers=fly("2.2.2.2"))
            return a, b
    a, b = run(go())
    status = [r.json()["result"]["structuredContent"] for r in a]
    assert [s["status"] for s in status] == ["ok", "ok", "unavailable"] and status[2]["reason"] == "busy"
    assert b.json()["result"]["structuredContent"]["status"] == "ok"
    assert mcp.gate.stats["throttled"] == 1


def test_the_global_calls_ceiling_still_applies_across_clients(tmp_path, monkeypatch):
    app, mcp = E.make_app(tmp_path, monkeypatch, environ={"TEMPO_MCP_MAX_CALLS_PER_MINUTE": "2"})

    async def go():
        async with E.started(app), E.http(app) as c:
            return [(await c.post("/mcp", json=CALL, headers=fly(f"3.3.3.{i}"))).json()["result"]["structuredContent"]
                    ["status"] for i in range(3)]
    assert run(go()) == ["ok", "ok", "unavailable"]


def test_the_client_table_is_bounded_and_forgets_old_hits():
    now = {"t": 0.0}
    w = P.ClientWindows(1, 60.0, max_keys=3, clock=lambda: now["t"])
    assert all(w.allow(k)[0] for k in "abc") and not w.allow("a")[0]
    assert w.allow("d")[0] and len(w) == 3                                 # "b" (least recent) was dropped
    assert w.allow("b")[0]                                                 # a dropped key starts fresh
    now["t"] = 61.0
    assert w.allow("a")[0]


# ---------------------------------------------------------------- S2: content log

def _gate(tmp_path, monkeypatch, cap):
    monkeypatch.setattr(config, "ASK_LOG_DIR", tmp_path / "logs")
    return P.Gate(P.McpSettings(enabled=True, log_calls=True, log_max_bytes=cap))


def test_the_call_log_rotates_to_one_old_file_at_the_cap(tmp_path, monkeypatch):
    gate = _gate(tmp_path, monkeypatch, 1000)
    try:
        for i in range(40):
            gate._write_log(f"{i:03d}" + "x" * 96)                         # 100 bytes with the newline
    finally:
        gate.close()
    logs = tmp_path / "logs"
    assert sorted(p.name for p in logs.iterdir()) == [P.CALL_LOG, P.CALL_LOG + ".1"]
    assert (logs / P.CALL_LOG).stat().st_size <= 1000 and (logs / (P.CALL_LOG + ".1")).stat().st_size <= 1000
    assert (logs / P.CALL_LOG).read_text().splitlines()[-1].startswith("039")      # newest kept


def test_a_refused_oversize_call_logs_no_argument_text(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "ASK_LOG_DIR", tmp_path / "logs")
    app, mcp = E.make_app(tmp_path, monkeypatch, environ={"TEMPO_MCP_LOG_CALLS": "true"})
    secret = "needle-" * 4000                                              # about 28 KB of argument
    bad = {**CALL, "params": {"name": "discover_indicators", "arguments": {"query": secret}}}
    unknown = {**CALL, "params": {"name": "describe_dataset", "arguments": {"dataset": "POPC", "oops": "needle"}}}

    async def go():
        async with E.started(app), E.http(app) as c:
            for body in (bad, unknown, CALL):
                await c.post("/mcp", json=body, headers=E.HEADERS)
    run(go())
    text = (tmp_path / "logs" / P.CALL_LOG).read_text(encoding="utf-8")
    assert "needle" not in text
    recs = [json.loads(x) for x in text.splitlines()]
    assert [r["reason"] for r in recs] == ["invalid_input", "invalid_input", None]
    assert recs[0]["tool"] == "discover_indicators" and recs[0]["argument_bytes"] > 28000
    assert len(recs[0]["arguments_sha256"]) == 64 and "arguments" not in recs[0] and "result" not in recs[0]
    assert recs[2]["arguments"] == {"dataset": "POPC"} and "result" in recs[2]   # accepted calls stay in full


def test_the_log_write_does_not_run_on_the_event_loop(tmp_path, monkeypatch):
    import threading
    app, mcp = E.make_app(tmp_path, monkeypatch, environ={"TEMPO_MCP_LOG_CALLS": "true"})
    monkeypatch.setattr(config, "ASK_LOG_DIR", tmp_path / "logs")
    threads = []
    real = mcp.gate._write_log
    mcp.gate._write_log = lambda line: (threads.append(threading.current_thread().name), real(line))[1]

    async def go():
        async with E.started(app):
            await mcp.gate.call("describe_dataset", {"dataset": "POPC"})
    run(go())
    assert threads and threads[0].startswith("mcp-log") and threading.current_thread().name not in threads


# ---------------------------------------------------------------- S3: the deadline keeps interrupting

def test_an_answer_that_arrives_after_the_deadline_is_a_timeout_and_is_not_cached(tmp_path, monkeypatch):
    app, mcp = E.make_app(tmp_path, monkeypatch, environ={"TEMPO_MCP_MAX_SECONDS": "0.5"})
    real = R.call_tool

    def slow_between_queries(name, arguments, *, conn=None):
        conn.execute("select 1").fetchall()
        time.sleep(1.2)                                                    # the timer fires here: nothing to interrupt
        return real(name, arguments, conn=conn)                            # a good answer, but too late
    monkeypatch.setattr(R, "call_tool", slow_between_queries)

    async def go():
        async with E.started(app):
            return await mcp.gate.call("describe_dataset", {"dataset": "POPC"})
    env = run(go())
    assert (env["status"], env["reason"]) == ("unavailable", "query_timeout")
    assert len(mcp.gate.cache) == 0 and wait_until(lambda: mcp.gate.active == 0)


def test_a_query_started_after_the_deadline_is_interrupted(tmp_path, monkeypatch):
    app, mcp = E.make_app(tmp_path, monkeypatch, environ={"TEMPO_MCP_MAX_SECONDS": "0.5"})
    seen = []

    def two_queries(name, arguments, *, conn=None):
        import duckdb
        conn.execute("select 1").fetchall()
        time.sleep(0.9)                                                    # deadline passes between the queries
        t0 = time.monotonic()
        try:
            conn.execute(E.HEAVY).fetchall()
        except duckdb.InterruptException:
            seen.append(time.monotonic() - t0)
            raise
        seen.append(None)
    monkeypatch.setattr(R, "call_tool", two_queries)

    async def go():
        async with E.started(app):
            t0 = time.monotonic()
            return await mcp.gate.call("describe_dataset", {"dataset": "POPC"}), time.monotonic() - t0
    env, took = run(go())
    assert env["reason"] == "query_timeout" and took < 2.5
    assert seen and seen[0] is not None and seen[0] < 1.0                   # stopped within moments, not run to the end
    assert wait_until(lambda: mcp.gate.active == 0, 3)


# ---------------------------------------------------------------- S5: normalized cache key

def test_reordered_keys_and_a_default_lang_hit_the_same_cache_entry(tmp_path, monkeypatch):
    app, mcp = E.make_app(tmp_path, monkeypatch)
    counting = Counting(monkeypatch)

    async def go():
        async with E.started(app):
            out = [await mcp.gate.call("query_data", a) for a in (
                {"dataset": "POPC", "group_by": ["REF_AREA", "TIME_PERIOD"]},
                {"group_by": ["REF_AREA", "TIME_PERIOD"], "dataset": "POPC"},
                {"dataset": "POPC", "group_by": ["REF_AREA", "TIME_PERIOD"], "lang": "ro"},
                {"lang": "en", "dataset": "POPC", "group_by": ["REF_AREA", "TIME_PERIOD"]})]
            return out
    out = run(go())
    assert [e["status"] for e in out] == ["ok"] * 4
    assert counting.calls == ["query_data", "query_data"]                   # ro once, en once
    assert mcp.gate.stats["cache_hits"] == 2


# ---------------------------------------------------------------- S6: hang-up on a real socket

def test_a_client_hang_up_cancels_the_work_long_before_the_deadline(tmp_path, monkeypatch):
    import http.client
    from fastapi import FastAPI
    from test_at03_mcp import free_port, serve
    port = free_port()
    monkeypatch.setattr(config, "PUBLIC_BASE_URL", f"http://127.0.0.1:{port}")
    E.full_env(tmp_path, monkeypatch)
    app = FastAPI(lifespan=P.lifespan)
    mcp = P.install(app, {"TEMPO_MCP_ENABLED": "true", "TEMPO_MCP_LOCAL_TEST": "true",
                          "TEMPO_MCP_MAX_SECONDS": "20"})
    seen = []
    heavy(monkeypatch, seen)
    server, thread = serve(app, port)
    try:
        body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {
            "name": "query_data", "arguments": QUERY}})
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=0.3)
        conn.request("POST", "/mcp", body=body, headers=E.HEADERS)
        t0 = time.monotonic()
        with pytest.raises(OSError):
            conn.getresponse()
        conn.close()
        assert wait_until(lambda: mcp.gate.active == 0, 5)                  # freed by the hang-up, not by the 20 s deadline
        assert time.monotonic() - t0 < 5 and seen and seen[0][0] == "interrupted"
    finally:
        server.should_exit = True
        thread.join(10)


# ---------------------------------------------------------------- S7: privacy wording

def test_the_notice_does_not_claim_the_platform_keeps_no_ip():
    n = P.LOGGING_NOTICE
    assert "no IP address or client identity" in n and "access logs may keep connection metadata" in n
    assert "(arguments and result, no IP" not in n
