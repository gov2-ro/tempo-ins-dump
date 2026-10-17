"""AT-03: resource bounds of the public MCP: deadline, overload, cancellation, cache, scan limit.

Real DuckDB cursors and the real SDK client; the tool service is replaced only where a test needs a
slow, blocking or failing operation. A slot is released when the work has really ended, never
earlier, and never leaks.
"""
import asyncio
import json
import threading
import time

import duckdb
import pytest

import at03_env as E
from at01_fixtures import write_manifest
from app import config
from app.services import public_mcp as P
from app.services.tools import registry as R

pytestmark = pytest.mark.filterwarnings("ignore::DeprecationWarning")

QUERY = {"dataset": "POPC", "group_by": ["REF_AREA", "TIME_PERIOD"]}


def run(coro):
    return asyncio.run(coro)


def wait_until(predicate, seconds=6.0):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        if predicate():
            return True
        time.sleep(0.02)
    return predicate()


class Counting:
    """Wraps the real tool service and counts executions per tool."""

    def __init__(self, monkeypatch):
        self.calls = []
        self.real = R.call_tool
        monkeypatch.setattr(R, "call_tool", self)

    def __call__(self, name, arguments, **kw):
        self.calls.append(name)
        return self.real(name, arguments, **kw)


def heavy(monkeypatch, seen):
    """The tool is a heavy query on the cursor the gate gave it (interruptible)."""
    def call(name, arguments, *, conn=None):
        t0 = time.monotonic()
        try:
            conn.execute(E.HEAVY).fetchall()
            seen.append(("finished", time.monotonic() - t0))
        except duckdb.InterruptException:
            seen.append(("interrupted", time.monotonic() - t0))
            raise
        return R.__dict__["_real"](name, arguments, conn=conn)
    monkeypatch.setattr(R, "_real", R.call_tool, raising=False)
    monkeypatch.setattr(R, "call_tool", call)


# ---------------------------------------------------------------- deadline and slot

def test_a_slow_query_is_interrupted_at_the_deadline_and_the_next_call_works(tmp_path, monkeypatch):
    app, mcp = E.make_app(tmp_path, monkeypatch, environ={"TEMPO_MCP_MAX_SECONDS": "1"})
    seen = []
    heavy(monkeypatch, seen)
    other = {}

    async def go():
        async with E.started(app), E.session(app) as s:
            async def watch():                                       # while it runs: slot taken, others fine
                await asyncio.sleep(0.4)
                other["active"] = mcp.gate.active
                from app.db import get_conn
                other["cursor"] = get_conn().execute("select 42").fetchone()
            t0 = time.monotonic()
            res, _ = await asyncio.gather(s.call_tool("query_data", QUERY), watch())
            took = time.monotonic() - t0
            monkeypatch.setattr(R, "call_tool", R._real)
            after = await s.call_tool("query_data", QUERY)
            return res, took, after
    res, took, after = run(go())
    env = E.payload(res)[0]
    assert (env["status"], env["reason"]) == ("unavailable", "query_timeout") and res.isError is False
    assert env["recovery"][0]["kind"] == "narrow" and took < 6
    assert seen == [("interrupted", pytest.approx(1.0, abs=1.2))]
    assert other == {"active": 1, "cursor": (42,)}                    # slot held; another cursor unaffected
    assert wait_until(lambda: mcp.gate.active == 0)
    assert E.payload(after)[0]["status"] == "ok"
    assert len(mcp.gate.executor._threads) == 1                       # no thread accumulation


def test_the_slot_stays_taken_until_work_that_cannot_be_interrupted_really_ends(tmp_path, monkeypatch):
    app, mcp = E.make_app(tmp_path, monkeypatch, environ={"TEMPO_MCP_MAX_SECONDS": "0.5"})
    monkeypatch.setattr(P, "DEADLINE_GRACE", 0.2)
    release = threading.Event()
    real = R.call_tool

    def stubborn(name, arguments, *, conn=None):                      # pure Python: no interrupt reaches it
        release.wait(5)
        return real(name, arguments, conn=conn)
    monkeypatch.setattr(R, "call_tool", stubborn)

    async def go():
        async with E.started(app), E.session(app) as s:
            first = await s.call_tool("query_data", QUERY)             # the caller is answered at the deadline
            during = await s.call_tool("query_data", {**QUERY, "limit": 5})
            listing = await s.list_tools()                              # protocol metadata is still served
            still = mcp.gate.active
            release.set()
            assert wait_until(lambda: mcp.gate.active == 0)
            monkeypatch.setattr(R, "call_tool", real)
            after = await s.call_tool("query_data", QUERY)
            return first, during, listing, still, after
    first, during, listing, still, after = run(go())
    assert E.payload(first)[0]["reason"] == "query_timeout"
    assert E.payload(during)[0]["reason"] == "busy" and len(listing.tools) == 8
    assert still == 1 and E.payload(after)[0]["status"] == "ok"


def test_overload_answers_busy_at_once_with_a_retry_and_never_queues(tmp_path, monkeypatch):
    app, mcp = E.make_app(tmp_path, monkeypatch)
    gate_open, entered = threading.Event(), threading.Event()
    real = R.call_tool

    def blocked(name, arguments, *, conn=None):
        entered.set()
        gate_open.wait(5)
        return real(name, arguments, conn=conn)
    monkeypatch.setattr(R, "call_tool", blocked)

    async def go():
        async with E.started(app), E.session(app) as a, E.session(app) as b:
            first = asyncio.ensure_future(a.call_tool("query_data", QUERY))
            while not entered.is_set():
                await asyncio.sleep(0.01)
            t0 = time.monotonic()
            busy = await b.call_tool("query_data", {**QUERY, "limit": 7, "lang": "en"})
            quick = time.monotonic() - t0
            gate_open.set()
            ok = await first
            monkeypatch.setattr(R, "call_tool", real)
            again = await b.call_tool("query_data", {**QUERY, "limit": 7})
            return busy, quick, ok, again
    busy, quick, ok, again = run(go())
    env = E.payload(busy)[0]
    assert (env["status"], env["reason"]) == ("unavailable", "busy") and quick < 1.0
    assert env["recovery"][0]["kind"] == "retry" and "second" in env["recovery"][0]["message"]
    assert E.payload(ok)[0]["status"] == "ok" and E.payload(again)[0]["status"] == "ok"
    assert wait_until(lambda: mcp.gate.active == 0)


def test_two_concurrent_operations_when_configured(tmp_path, monkeypatch):
    app, mcp = E.make_app(tmp_path, monkeypatch, environ={"TEMPO_MCP_MAX_CONCURRENT": "2"})
    hold, in_flight, lock = threading.Event(), [], threading.Lock()
    real = R.call_tool

    def blocked(name, arguments, *, conn=None):
        with lock:
            in_flight.append(1)
        hold.wait(5)
        return real(name, arguments, conn=conn)
    monkeypatch.setattr(R, "call_tool", blocked)

    async def go():
        async with E.started(app), E.session(app) as s1, E.session(app) as s2, E.session(app) as s3:
            t1 = asyncio.ensure_future(s1.call_tool("query_data", QUERY))
            t2 = asyncio.ensure_future(s2.call_tool("query_data", {**QUERY, "limit": 3}))
            while len(in_flight) < 2:
                await asyncio.sleep(0.01)
            third = await s3.call_tool("query_data", {**QUERY, "limit": 4})
            hold.set()
            await asyncio.gather(t1, t2)
            return third
    assert E.payload(run(go()))[0]["reason"] == "busy"


def test_a_failing_query_releases_its_slot_and_leaks_nothing(tmp_path, monkeypatch):
    app, mcp = E.make_app(tmp_path, monkeypatch)
    real = R.call_tool

    def boom(name, arguments, *, conn=None):
        raise RuntimeError(f"disk exploded at {tmp_path}/secret.parquet")
    monkeypatch.setattr(R, "call_tool", boom)

    async def go():
        async with E.started(app), E.session(app) as s:
            bad = [await s.call_tool("query_data", {**QUERY, "limit": n, "lang": "en"}) for n in (1, 2, 3)]
            monkeypatch.setattr(R, "call_tool", real)
            return bad, await s.call_tool("query_data", QUERY)
    bad, good = run(go())
    for r in bad:
        env = E.payload(r)[0]
        assert r.isError and env["reason"] == "execution_failed" and "reference" in env["message"]
        assert "disk exploded" not in r.content[0].text and str(tmp_path) not in r.content[0].text
    assert E.payload(good)[0]["status"] == "ok" and wait_until(lambda: mcp.gate.active == 0)


def test_cancelling_the_caller_interrupts_the_work_and_frees_the_slot(tmp_path, monkeypatch):
    app, mcp = E.make_app(tmp_path, monkeypatch)
    seen = []
    heavy(monkeypatch, seen)

    async def go():
        async with E.started(app):
            task = asyncio.ensure_future(mcp.gate.call("query_data", QUERY))
            while mcp.gate.active == 0:
                await asyncio.sleep(0.01)
            await asyncio.sleep(0.3)                                  # the heavy query is running
            t0 = time.monotonic()
            task.cancel()                                            # the client went away
            with pytest.raises(asyncio.CancelledError):
                await task
            return t0
    t0 = run(go())
    assert wait_until(lambda: mcp.gate.active == 0, 5)
    assert seen and seen[0][0] == "interrupted" and time.monotonic() - t0 < 5   # interrupted, not run to the end
    assert len(mcp.gate.executor._threads) == 1


def test_a_client_that_hangs_up_on_a_real_connection_frees_the_slot_by_the_deadline(tmp_path, monkeypatch):
    import http.client
    from fastapi import FastAPI
    from test_at03_mcp import free_port, serve
    port = free_port()
    monkeypatch.setattr(config, "PUBLIC_BASE_URL", f"http://127.0.0.1:{port}")
    E.full_env(tmp_path, monkeypatch)
    app = FastAPI(lifespan=P.lifespan)
    mcp = P.install(app, {"TEMPO_MCP_ENABLED": "true", "TEMPO_MCP_LOCAL_TEST": "true",
                          "TEMPO_MCP_MAX_SECONDS": "2"})
    seen = []
    heavy(monkeypatch, seen)
    server, thread = serve(app, port)
    try:
        body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {
            "name": "query_data", "arguments": QUERY}})
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=0.6)
        conn.request("POST", "/mcp", body=body, headers=E.HEADERS)
        with pytest.raises(OSError):
            conn.getresponse()                                        # we give up after 0.6 s
        conn.close()
        assert wait_until(lambda: mcp.gate.active == 0, 8)            # released once the work ended
        assert seen and seen[0][0] == "interrupted"
    finally:
        server.should_exit = True
        thread.join(10)


# ---------------------------------------------------------------- cache

def test_an_identical_call_is_served_from_the_cache_without_running_the_tool(tmp_path, monkeypatch):
    app, mcp = E.make_app(tmp_path, monkeypatch)
    count = Counting(monkeypatch)

    async def go():
        async with E.started(app), E.session(app) as s:
            a = await s.call_tool("query_data", QUERY)
            b = await s.call_tool("query_data", QUERY)
            ro = await s.call_tool("describe_dataset", {"dataset": "POPC", "lang": "ro"})
            en = await s.call_tool("describe_dataset", {"dataset": "POPC", "lang": "en"})
            return a, b, ro, en
    a, b, ro, en = run(go())
    assert E.payload(a)[0] == E.payload(b)[0] and count.calls.count("query_data") == 1
    assert mcp.gate.stats["cache_hits"] == 1
    assert count.calls.count("describe_dataset") == 2                  # language is part of the key


def test_failures_and_load_dependent_outcomes_are_never_cached(tmp_path, monkeypatch):
    app, mcp = E.make_app(tmp_path, monkeypatch)
    real = R.call_tool
    n = {"calls": 0}

    def flaky(name, arguments, *, conn=None):
        n["calls"] += 1
        if n["calls"] == 1:
            raise RuntimeError("transient")
        return real(name, arguments, conn=conn)
    monkeypatch.setattr(R, "call_tool", flaky)

    async def go():
        async with E.started(app), E.session(app) as s:
            first = await s.call_tool("query_data", QUERY)
            second = await s.call_tool("query_data", QUERY)           # re-executed, not served the failure
            refusal = await s.call_tool("query_data", {"dataset": "POPX", "group_by": ["TIME_PERIOD"]})
            refusal2 = await s.call_tool("query_data", {"dataset": "POPX", "group_by": ["TIME_PERIOD"]})
            unknown = await s.call_tool("query_data", {"dataset": "NOPE"})
            return first, second, refusal, refusal2, unknown
    first, second, refusal, refusal2, unknown = run(go())
    assert E.payload(first)[0]["reason"] == "execution_failed" and E.payload(second)[0]["status"] == "ok"
    assert E.payload(refusal)[0] == E.payload(refusal2)[0] and E.payload(refusal)[0]["reason"] == "overlapping_levels"
    assert mcp.gate.stats["cache_hits"] == 1                           # only the statistical refusal repeats
    assert E.payload(unknown)[0]["status"] == "error" and len(mcp.gate.cache) == 2


def test_a_new_generation_invalidates_every_cached_answer(tmp_path, monkeypatch):
    app, mcp = E.make_app(tmp_path, monkeypatch)
    count = Counting(monkeypatch)

    async def go():
        async with E.started(app), E.session(app) as s:
            a = await s.call_tool("query_data", QUERY)
            held = len(mcp.gate.cache)
            write_manifest(app.state.corpus_env.corpus, "gen-next")
            b = await s.call_tool("query_data", QUERY)
            return a, b, held
    a, b, held = run(go())
    assert E.payload(a)[0]["provenance"]["generation"]["id"] == "gen-at01-fixture"
    assert E.payload(b)[0]["provenance"]["generation"]["id"] == "gen-next"
    assert count.calls.count("query_data") == 2 and held == 1
    assert len(mcp.gate.cache) == 1 and all(k[2] == "gen-next" for k in mcp.gate.cache._items)


def test_without_generation_evidence_nothing_is_cached_or_certified(tmp_path, monkeypatch):
    app, mcp = E.make_app(tmp_path, monkeypatch)
    (app.state.corpus_env.corpus / "generation-manifest.json").unlink()
    count = Counting(monkeypatch)

    async def go():
        async with E.started(app), E.session(app) as s:
            return [await s.call_tool("query_data", QUERY) for _ in range(2)]
    a, b = run(go())
    assert E.payload(a)[0]["reason"] == "generation_unverified" and len(mcp.gate.cache) == 0
    assert count.calls.count("query_data") == 2


def test_the_cache_is_bounded_by_entries_bytes_and_age():
    now = {"t": 0.0}
    clock = lambda: now["t"]                                          # noqa: E731
    env = lambda i, pad=0: {"status": "ok", "tool": "t", "i": i, "pad": "x" * pad}   # noqa: E731
    key = lambda i, gen="g": ("tempo-tools/2", "b", gen, "t", "ro", str(i), "p")      # noqa: E731

    c = P.ResultCache(max_bytes=10_000, max_entries=3, ttl=300, clock=clock)
    for i in range(5):
        assert c.put(key(i), env(i))
    assert len(c) == 3 and c.get(key(0)) is None and c.get(key(4))["i"] == 4         # oldest evicted first
    c.get(key(2))                                                                    # touched: now newest
    c.put(key(9), env(9))
    assert c.get(key(2)) is not None and c.get(key(3)) is None

    b = P.ResultCache(max_bytes=2_000, max_entries=100, ttl=300, clock=clock)
    for i in range(40):
        b.put(key(i), env(i, 300))
    assert b.bytes_used <= 2_000 and 1 <= len(b) <= 6
    assert not b.put(key("big"), env(1, 5_000)) and b.get(key("big")) is None        # larger than the cache

    t = P.ResultCache(max_bytes=10_000, max_entries=10, ttl=300, clock=clock)
    t.put(key(1), env(1))
    now["t"] = 299.0
    assert t.get(key(1)) is not None
    now["t"] = 301.0
    assert t.get(key(1)) is None and len(t) == 0 and t.bytes_used == 0                # expired and dropped

    g = P.ResultCache(max_bytes=10_000, max_entries=10, ttl=300, clock=clock)
    g.put(key(1, "old"), env(1))
    g.put(key(2, "new"), env(2))
    g.purge_generations_other_than("new")
    assert len(g) == 1 and g.get(key(2, "new")) is not None


def test_the_cache_keeps_only_envelopes_as_text(tmp_path, monkeypatch):
    app, mcp = E.make_app(tmp_path, monkeypatch)

    async def go():
        async with E.started(app), E.session(app) as s:
            await s.call_tool("query_data", QUERY)
    run(go())
    (stored, text), = mcp.gate.cache._items.values()
    assert isinstance(text, str) and json.loads(text)["contract"] == "tempo-tools/2"
    assert all(isinstance(part, str) or part is None for part in next(iter(mcp.gate.cache._items)))


# ---------------------------------------------------------------- scan limit

def test_a_selection_over_the_scan_limit_is_refused_without_running_or_counting(tmp_path, monkeypatch):
    app, mcp = E.make_app(tmp_path, monkeypatch, environ={"TEMPO_MCP_MAX_SCAN_ROWS": "5"})
    count = Counting(monkeypatch)
    sql = []
    real_connect = duckdb.connect

    class Proxy:
        def __init__(self, con):
            self.con = con

        def execute(self, q, *a, **k):
            sql.append(q)
            return self.con.execute(q, *a, **k)

        def __getattr__(self, name):
            return getattr(self.con, name)
    monkeypatch.setattr(P, "ScanEstimator", P.ScanEstimator)
    mcp.gate.estimator = P.ScanEstimator()
    import duckdb as _d
    monkeypatch.setattr(_d, "connect", lambda *a, **k: Proxy(real_connect(*a, **k)))

    async def go():
        async with E.started(app), E.session(app) as s:
            return (await s.call_tool("query_data", {**QUERY, "lang": "en"}),
                    await s.call_tool("compare_periods", {**E.CALLS["compare_periods"], "lang": "en"}))
    qd, cp = run(go())
    for res in (qd, cp):
        env = E.payload(res)[0]
        assert (env["status"], env["reason"]) == ("unavailable", "query_budget") and "limit is 5" in env["message"]
    rec = E.payload(qd)[0]["recovery"][0]
    assert rec["tool"] == "describe_dataset"
    R.TOOLS["describe_dataset"].args.model_validate(rec["arguments"])  # a valid suggested call
    assert count.calls == [] and mcp.gate.stats["scan_refused"] == 2
    assert sql and all("parquet_file_metadata" in q and "count(" not in q.lower() for q in sql)


def test_a_multi_source_recipe_counts_every_source_cumulatively(tmp_path, monkeypatch):
    app, mcp = E.make_app(tmp_path, monkeypatch)
    est = mcp.gate.estimator
    one, two = est.file_rows("STAYS1"), est.file_rows("RESPOP")
    assert one and two
    assert est.estimate("run_recipe", {"recipe": "fx_intensity"}) == one + two
    assert est.estimate("run_recipe", {"recipe": "no_such_recipe"}) == 0       # the tool refuses it, no read
    assert est.estimate("query_data", {"dataset": "NOPE"}) == 0
    app2, mcp2 = E.make_app(tmp_path, monkeypatch, environ={"TEMPO_MCP_MAX_SCAN_ROWS": str(max(one, two))},
                            env=app.state.corpus_env)

    async def go():
        async with E.started(app2), E.session(app2) as s:
            return await s.call_tool("run_recipe", E.CALLS["run_recipe"])
    assert E.payload(run(go()))[0]["reason"] == "query_budget"                  # each source fits; the sum does not


def test_an_unknown_estimate_is_refused_unless_a_generation_bound_result_is_cached(tmp_path, monkeypatch):
    app, mcp = E.make_app(tmp_path, monkeypatch)
    (app.state.corpus_env.corpus / "parquet" / "BADP.parquet").write_bytes(b"not a parquet file")
    count = Counting(monkeypatch)

    async def go():
        async with E.started(app), E.session(app) as s:
            warm = await s.call_tool("query_data", QUERY)                       # cached under this generation
            monkeypatch.setattr(mcp.gate.estimator, "estimate", lambda *a: None)
            cached = await s.call_tool("query_data", QUERY)                     # still served: bound to the generation
            fresh = await s.call_tool("query_data", {"dataset": "POPC", "limit": 11, "lang": "en"})
            bad = await s.call_tool("query_data", {"dataset": "BADP", "lang": "en"})
            return warm, cached, fresh, bad
    warm, cached, fresh, bad = run(go())
    assert E.payload(warm)[0] == E.payload(cached)[0] and E.payload(cached)[0]["status"] == "ok"
    for res in (fresh, bad):
        assert E.payload(res)[0]["reason"] == "query_budget" and "could not be bounded" in E.payload(res)[0]["message"]
    assert count.calls.count("query_data") == 1


def test_metadata_only_tools_are_not_scan_gated(tmp_path, monkeypatch):
    app, mcp = E.make_app(tmp_path, monkeypatch, environ={"TEMPO_MCP_MAX_SCAN_ROWS": "1"})

    async def go():
        async with E.started(app), E.session(app) as s:
            return [await s.call_tool("describe_dataset", {"dataset": "POPC"}),
                    await s.call_tool("discover_indicators", {"query": "populatie"})]
    assert all(E.payload(r)[0]["status"] != "unavailable" or E.payload(r)[0]["reason"] != "query_budget"
               for r in run(go()))


# ---------------------------------------------------------------- admission rates

def test_calls_per_minute_is_an_aggregate_admission_budget(tmp_path, monkeypatch):
    app, mcp = E.make_app(tmp_path, monkeypatch, environ={"TEMPO_MCP_MAX_CALLS_PER_MINUTE": "3"})

    async def go():
        async with E.started(app), E.session(app) as s:
            out = [await s.call_tool("query_data", {**QUERY, "limit": n}) for n in (1, 2, 3, 4)]
            return out, await s.list_tools()                                  # metadata is not a call
    out, listing = run(go())
    assert [E.payload(r)[0]["status"] for r in out] == ["ok", "ok", "ok", "unavailable"]
    assert E.payload(out[3])[0]["reason"] == "busy" and E.payload(out[3])[0]["recovery"][0]["kind"] == "retry"
    assert len(listing.tools) == 8 and mcp.gate.stats["throttled"] == 1


def test_initialize_and_list_are_throttled_cheaply_too(tmp_path, monkeypatch):
    app, mcp = E.make_app(tmp_path, monkeypatch, environ={"TEMPO_MCP_MAX_REQUESTS_PER_MINUTE": "3"})

    async def go():
        async with E.started(app), E.http(app) as c:
            return [await c.post("/mcp", json=E.RPC, headers=E.HEADERS) for _ in range(5)]
    rs = run(go())
    assert [r.status_code for r in rs] == [200, 200, 200, 429, 429]
    assert int(rs[3].headers["retry-after"]) >= 1


def test_the_window_forgets_old_hits():
    now = {"t": 0.0}
    w = P.Window(2, 60.0, clock=lambda: now["t"])
    assert w.allow() == (True, 0.0) and w.allow() == (True, 0.0)
    ok, wait = w.allow()
    assert not ok and 59 <= wait <= 60
    now["t"] = 61.0
    assert w.allow()[0] is True


def test_the_wire_response_of_a_large_result_stays_within_budget(tmp_path, monkeypatch):
    app, mcp = E.make_app(tmp_path, monkeypatch, extra=(E.big_localities,),
                          environ={"TEMPO_MCP_MAX_SCAN_ROWS": "100000"})

    async def go():
        async with E.started(app), E.http(app) as c:
            await c.post("/mcp", json=E.RPC, headers=E.HEADERS)
            call = {"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {
                "name": "query_data", "arguments": {"dataset": "BIGL", "limit": 200}}}
            return await c.post("/mcp", json=call, headers=E.HEADERS)
    r = run(go())
    env = r.json()["result"]["structuredContent"]
    assert len(r.content) <= P.MAX_WIRE_BYTES and env["status"] in ("ok", "partial")
    assert env["limits"]["returned_rows"] <= 200 and env["provenance"]["generation"]["status"] == "present"
