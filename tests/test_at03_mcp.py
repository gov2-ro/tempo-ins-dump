"""AT-03: the public read-only MCP, driven by the real MCP Python SDK client over Streamable HTTP.

Protocol and parity, the disabled switch, configuration, the HTTP trust boundaries and the
no-model-call property. Resource behaviour (deadline, overload, cache, scan limit) is in
test_at03_resources.py. Live ChatGPT/Claude interoperability and Fly load are AT-04 evidence.
"""
import asyncio
import json
import socket
import sys
import threading
import time
from pathlib import Path

import jsonschema
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import at03_env as E
from at01_fixtures import write_manifest
from app import config
from app.services import public_mcp as P
from app.services.tools import contract as C
from app.services.tools import registry as R

pytestmark = pytest.mark.filterwarnings("ignore::DeprecationWarning")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))   # mcp_probe


def run(coro):
    return asyncio.run(coro)


# ---------------------------------------------------------------- protocol

def test_real_client_lists_exactly_the_eight_tools_with_schemas(tmp_path, monkeypatch):
    app, mcp = E.make_app(tmp_path, monkeypatch)

    async def go():
        async with E.started(app), E.session(app) as s:
            return await s.list_tools(), s.get_server_capabilities()
    listed, caps = run(go())
    assert [t.name for t in listed.tools] == R.tool_names() and len(listed.tools) == 8
    for t in listed.tools:
        assert t.title and t.description
        a = t.annotations
        assert (a.readOnlyHint, a.destructiveHint, a.idempotentHint, a.openWorldHint) == (True, False, True, False)
        jsonschema.Draft202012Validator.check_schema(t.inputSchema)
        jsonschema.Draft202012Validator.check_schema(t.outputSchema)
        assert t.inputSchema == R.inline_schema(R.input_schema(t.name))
        assert t.inputSchema["additionalProperties"] is False
        assert "$defs" not in json.dumps(t.inputSchema) and "$ref" not in json.dumps(t.inputSchema)
    assert caps.tools is not None and not caps.prompts and not caps.resources and not caps.logging


def test_every_tool_is_callable_with_matching_structured_and_text_output(tmp_path, monkeypatch):
    app, mcp = E.make_app(tmp_path, monkeypatch)

    async def go():
        out = {}
        async with E.started(app), E.session(app) as s:
            for name, args in E.CALLS.items():
                out[name] = await s.call_tool(name, args)
            sel = E.payload(out["query_data"])[0]["provenance"]
            out["get_evidence_links"] = await s.call_tool("get_evidence_links", {
                "selection": sel["selection"], "generation_id": sel["generation"]["id"]})
        return out
    out = run(go())
    assert set(out) == set(R.tool_names())
    for name, res in out.items():
        structured, text = E.payload(res)
        assert structured == text                                   # one envelope, two representations
        R.validate_result(name, structured)                         # the contract's own models
        jsonschema.validate(structured, R.output_schema(name))      # the published output schema
        assert C.size(structured) <= C.MAX_RESULT_BYTES
        assert res.isError is False and structured["status"] in ("ok", "partial", "needs_clarification")
        assert structured["provenance"]["generation"]["id"] == "gen-at01-fixture"
    assert E.payload(out["query_data"])[0]["data"]["rows"][0][0] in ("Cluj", "Iași", "Bihor")


@pytest.mark.parametrize("name,args", [
    ("query_data", {"dataset": "POPC", "group_by": ["REF_AREA", "TIME_PERIOD"]}),
    ("query_data", {"dataset": "POPX", "group_by": ["TIME_PERIOD"]}),                  # refusal
    ("compare_periods", E.CALLS["compare_periods"]),                                   # partial
    ("query_data", {"dataset": "NOPE"}),                                               # unknown dataset
    ("query_data", {"dataset": "POPC", "filters": {"REF_AREA": ["Iași"]}, "group_by": ["TIME_PERIOD"]}),
])
def test_service_and_mcp_return_the_same_envelope(tmp_path, monkeypatch, name, args):
    app, mcp = E.make_app(tmp_path, monkeypatch)
    direct = R.call_tool(name, args)

    async def go():
        async with E.started(app), E.session(app) as s:
            return await s.call_tool(name, args)
    res = run(go())
    structured, text = E.payload(res)
    assert structured == text and structured == direct              # values, verdict, scope, generation
    assert res.isError is (direct["status"] == "error")


def test_non_ascii_results_are_bounded_by_bytes_and_identical_in_both_forms(tmp_path, monkeypatch):
    app, mcp = E.make_app(tmp_path, monkeypatch, extra=(E.big_localities,),
                          environ={"TEMPO_MCP_MAX_SCAN_ROWS": "100000"})

    async def go():
        async with E.started(app):
            async with E.http(app) as c:
                init = await c.post("/mcp", json=E.RPC, headers=E.HEADERS)
                call = {"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {
                    "name": "query_data", "arguments": {"dataset": "BIGL", "limit": 200}}}
                big = await c.post("/mcp", json=call, headers=E.HEADERS)
                ro = {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {
                    "name": "query_data", "arguments": {"dataset": "POPC", "filters": {"REF_AREA": ["Iași"]},
                                                        "group_by": ["REF_AREA", "TIME_PERIOD"]}}}
                small = await c.post("/mcp", json=ro, headers=E.HEADERS)
        return init, big, small
    init, big, small = run(go())
    assert init.status_code == 200
    for resp in (big, small):
        result = resp.json()["result"]
        assert result["structuredContent"] == json.loads(result["content"][0]["text"])
        assert len(resp.content) <= public_budget()                    # the wire, not the Python string
        assert C.size(result["structuredContent"]) <= C.MAX_RESULT_BYTES
    assert big.json()["result"]["structuredContent"]["status"] in ("ok", "partial")
    assert "Iași" in small.text and len(small.text.encode()) > len(small.text)     # multi-byte on the wire


def public_budget():
    return P.MAX_WIRE_BYTES


def test_a_response_too_large_for_the_wire_budget_shrinks_its_preview_then_budgets(tmp_path, monkeypatch):
    from mcp import types
    E.make_app(tmp_path, monkeypatch)
    env = R.call_tool("query_data", {"dataset": "POPC", "group_by": ["REF_AREA", "TIME_PERIOD"]})
    rows = env["data"]["rows"]
    env["data"]["rows"] = [[f"Județ {i} " + "ș" * 400, "2020", 1.0 * i] for i in range(180)]   # bulky, non-ASCII
    env["limits"]["returned_rows"] = 180
    res = P.build_result("query_data", env, {"dataset": "POPC"})
    assert P.wire_bytes(res) <= P.MAX_WIRE_BYTES
    assert res.structuredContent == json.loads(res.content[0].text)
    assert res.structuredContent["limits"]["preview_truncated"] is True
    assert any(w["code"] == "preview_shortened" for w in res.structuredContent["warnings"])
    # nothing can shrink: the required content cannot fit -> response_budget, no data, no selection
    env2 = R.call_tool("describe_dataset", {"dataset": "POPC"})
    env2["provenance"]["sources"][0]["definition"] = "x" * 80_000
    res2 = P.build_result("describe_dataset", env2, {"dataset": "POPC"})
    assert res2.structuredContent["reason"] == "response_budget" and res2.structuredContent["data"].get("request")
    assert P.wire_bytes(res2) <= P.MAX_WIRE_BYTES and isinstance(res2, types.CallToolResult) and rows


# ---------------------------------------------------------------- the switch

DISABLED_PATHS = ["/mcp", "/mcp/", "/mcp/mcp", "/mcp/anything/else"]


def test_disabled_endpoint_is_404_for_every_method_and_path(tmp_path, monkeypatch):
    app, mcp = E.make_app(tmp_path, monkeypatch, environ={"TEMPO_MCP_ENABLED": "false"})
    assert mcp is None and app.state.public_mcp is None

    async def go():
        async with E.started(app), E.http(app) as c:
            codes = []
            for path in DISABLED_PATHS:
                for method in ("POST", "GET", "DELETE", "PUT", "OPTIONS"):
                    r = await c.request(method, path, json=E.RPC if method == "POST" else None,
                                        headers=E.HEADERS)
                    codes.append((path, method, r.status_code))
            return codes
    assert all(code == 404 for _, _, code in run(go()))


def test_the_real_app_ships_with_mcp_off(monkeypatch):
    from app.main import app as real
    assert real.state.public_mcp is None
    c = TestClient(real)
    assert c.post("/mcp", json=E.RPC, headers=E.HEADERS).status_code == 404
    assert c.post("/mcp/", json=E.RPC, headers=E.HEADERS).status_code == 404
    assert c.get("/api/health").json()["mcp"] == {"enabled": False, "contract": "tempo-tools/2",
                                                  "generation": c.get("/api/health").json()["generation"]["status"],
                                                  "call_logging": False}


def test_the_ask_and_mcp_switches_are_independent(tmp_path, monkeypatch):
    from app.routers import ask as ask_router
    monkeypatch.setattr(config, "ASK_ENABLED", False)
    monkeypatch.setattr(config, "ASK_BYOK_ENABLED", False)
    app, mcp = E.make_app(tmp_path, monkeypatch)                     # MCP on, Ask off
    app.include_router(ask_router.router, prefix="/api")

    async def go():
        async with E.started(app), E.http(app) as c:
            cfg = (await c.get("/api/ask/config")).json()
            ask = await c.post("/api/ask", json={"question": "x"})
            init = await c.post("/mcp", json=E.RPC, headers=E.HEADERS)
            return cfg, ask.status_code, init.status_code
    cfg, ask_status, init_status = run(go())
    assert cfg["available"] is False and ask_status == 404 and init_status == 200
    # and the other way round: Ask on, MCP off
    monkeypatch.setattr(config, "ASK_ENABLED", True)
    app2, mcp2 = E.make_app(tmp_path, monkeypatch, environ={"TEMPO_MCP_ENABLED": "false"}, env=app.state.corpus_env)
    app2.include_router(ask_router.router, prefix="/api")

    async def go2():
        async with E.started(app2), E.http(app2) as c:
            return (await c.get("/api/ask/config")).json()["available"], \
                (await c.post("/mcp", json=E.RPC, headers=E.HEADERS)).status_code
    assert run(go2()) == (True, 404)


def test_a_fresh_application_sees_its_own_flags_not_a_previous_ones(tmp_path, monkeypatch):
    a, _ = E.make_app(tmp_path, monkeypatch)
    b, _ = E.make_app(tmp_path, monkeypatch, environ={"TEMPO_MCP_ENABLED": "false"}, env=a.state.corpus_env)
    c, _ = E.make_app(tmp_path, monkeypatch, env=a.state.corpus_env)       # enabled again, new instance

    async def go(app):
        async with E.started(app), E.http(app) as cl:
            return (await cl.post("/mcp", json=E.RPC, headers=E.HEADERS)).status_code
    assert (run(go(a)), run(go(b)), run(go(c))) == (200, 404, 200)
    assert a.state.public_mcp is not c.state.public_mcp and b.state.public_mcp is None


# ---------------------------------------------------------------- configuration

BAD = [   # (settings override, base url, message)
    ({}, "", "TEMPO_PUBLIC_BASE_URL"),
    ({}, "http://mcp.example.org", "https"),
    ({}, "https://user:pw@mcp.example.org", "bare origin"),
    ({}, "https://mcp.example.org/path", "bare origin"),
    ({"TEMPO_MCP_MAX_CONCURRENT": "0"}, "https://mcp.example.org", "positive"),
    ({"TEMPO_MCP_MAX_SECONDS": "-1"}, "https://mcp.example.org", "positive"),
    ({"TEMPO_MCP_MAX_BODY_BYTES": "lots"}, "https://mcp.example.org", "number"),
    ({"TEMPO_MCP_MAX_SCAN_ROWS": "0"}, "https://mcp.example.org", "unlimited"),
    ({"TEMPO_MCP_CACHE_BYTES": "-5"}, "https://mcp.example.org", "positive"),
    ({"TEMPO_MCP_ALLOWED_HOSTS": "*"}, "https://mcp.example.org", "wildcard"),
    ({"TEMPO_MCP_ALLOWED_ORIGINS": "https://*"}, "https://mcp.example.org", "wildcard"),
    ({"TEMPO_MCP_LOCAL_TEST": "maybe"}, "https://mcp.example.org", "true or false"),
]


@pytest.mark.parametrize("override,base,message", BAD)
def test_invalid_settings_fail_startup_clearly(monkeypatch, override, base, message):
    env = {"TEMPO_MCP_ENABLED": "true", **override}
    with pytest.raises(P.McpConfigError, match=message):
        P.McpSettings.from_env(env, base_url=base)
    monkeypatch.setattr(config, "PUBLIC_BASE_URL", base)
    with pytest.raises(P.McpConfigError, match=message):                  # and when the app is built
        P.install(FastAPI(), env)


def test_defaults_and_local_test_origin():
    s = P.McpSettings.from_env({"TEMPO_MCP_ENABLED": "true"}, base_url="https://mcp.example.org")
    assert (s.max_body_bytes, s.max_concurrent, s.max_seconds, s.max_calls_per_minute,
            s.max_scan_rows, s.cache_bytes) == (65_536, 1, 10.0, 120, 1_000_000, 4_194_304)
    assert s.allowed_hosts == ("mcp.example.org",) and s.allowed_origins == ("https://mcp.example.org",)
    local = P.McpSettings.from_env({"TEMPO_MCP_ENABLED": "true", "TEMPO_MCP_LOCAL_TEST": "true"},
                                   base_url="http://127.0.0.1:8080")
    assert "127.0.0.1:*" in local.allowed_hosts and local.local_test
    assert P.McpSettings.from_env({}, base_url="") == P.McpSettings()       # disabled: nothing validated


# ---------------------------------------------------------------- HTTP trust boundaries

class Spy:
    def __init__(self, monkeypatch):
        self.calls = []
        real = R.call_tool
        monkeypatch.setattr(R, "call_tool", lambda *a, **k: self.calls.append(a[0]) or real(*a, **k))


def post(c, body=None, *, data=None, headers=None):
    return c.post("/mcp", json=body, content=data, headers={**E.HEADERS, **(headers or {})})


def test_a_wrong_host_is_refused_before_any_tool_runs(tmp_path, monkeypatch):
    app, mcp = E.make_app(tmp_path, monkeypatch)
    spy = Spy(monkeypatch)
    call = {"jsonrpc": "2.0", "id": 2, "method": "tools/call",
            "params": {"name": "describe_dataset", "arguments": {"dataset": "POPC"}}}

    async def go():
        async with E.started(app), E.http(app, host="evil.example") as c:
            return (await post(c, E.RPC)).status_code, (await post(c, call)).status_code
    assert run(go()) == (421, 421) and spy.calls == []


def test_origin_policy_approved_absent_and_foreign(tmp_path, monkeypatch):
    app, mcp = E.make_app(tmp_path, monkeypatch, environ={"TEMPO_MCP_ALLOWED_ORIGINS": "https://claude.example"})
    spy = Spy(monkeypatch)
    call = {"jsonrpc": "2.0", "id": 2, "method": "tools/call",
            "params": {"name": "describe_dataset", "arguments": {"dataset": "POPC"}}}

    async def go():
        async with E.started(app), E.http(app) as c:
            absent = await post(c, E.RPC)                                    # server-to-server: no Origin
            approved = await post(c, E.RPC, headers={"origin": "https://claude.example"})
            foreign = await post(c, call, headers={"origin": "https://evil.example"})
            pre_ok = await c.options("/mcp", headers={"origin": "https://claude.example"})
            pre_bad = await c.options("/mcp", headers={"origin": "https://evil.example"})
            return absent, approved, foreign, pre_ok, pre_bad
    absent, approved, foreign, pre_ok, pre_bad = run(go())
    assert absent.status_code == 200 and "access-control-allow-origin" not in absent.headers
    assert approved.status_code == 200 and approved.headers["access-control-allow-origin"] == "https://claude.example"
    assert foreign.status_code == 403 and "access-control-allow-origin" not in foreign.headers
    assert spy.calls == []                                                   # rejected before tool execution
    assert pre_ok.status_code == 204 and pre_ok.headers["access-control-allow-origin"] == "https://claude.example"
    assert pre_bad.status_code == 403


def test_the_apps_development_cors_never_applies_to_mcp():
    from app.main import app as real
    c = TestClient(real)
    web = c.get("/api/health", headers={"origin": "http://localhost:5173"})
    assert web.headers.get("access-control-allow-origin") == "http://localhost:5173"  # web app CORS (AQ-06A)
    mcp = c.options("/mcp", headers={"origin": "http://localhost:5173",
                                     "access-control-request-method": "POST"})
    assert mcp.status_code == 404 and "access-control-allow-origin" not in mcp.headers


def test_an_oversized_body_is_refused_before_parsing_or_tool_work(tmp_path, monkeypatch):
    app, mcp = E.make_app(tmp_path, monkeypatch, environ={"TEMPO_MCP_MAX_BODY_BYTES": "2048"})
    spy = Spy(monkeypatch)
    handled = []
    real = mcp.manager.handle_request
    monkeypatch.setattr(mcp.manager, "handle_request", lambda *a, **k: handled.append(1) or real(*a, **k))
    big = {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {
        "name": "query_data", "arguments": {"dataset": "POPC", "filters": {"REF_AREA": ["x" * 90] * 40}}}}

    async def chunks():                                                       # no Content-Length: streamed
        for _ in range(8):
            yield b"x" * 1024

    async def go():
        async with E.started(app), E.http(app) as c:
            declared = await post(c, big)
            streamed = await c.post("/mcp", content=chunks(), headers=E.HEADERS)
            at_limit = await post(c, E.RPC)                                   # a normal request still works
            return declared.status_code, streamed.status_code, at_limit.status_code
    assert run(go()) == (413, 413, 200)
    assert handled == [1] and spy.calls == []


def test_oversized_or_unknown_arguments_never_reach_the_database(tmp_path, monkeypatch):
    app, mcp = E.make_app(tmp_path, monkeypatch)
    spy = Spy(monkeypatch)

    async def go():
        async with E.started(app), E.session(app) as s:
            huge = await s.call_tool("query_data", {"dataset": "POPC", "filters": {
                "REF_AREA": [f"v{i}-" + "x" * 150 for i in range(100)], "TIME_PERIOD": ["y" * 150] * 50}})
            unknown_key = await s.call_tool("query_data", {"dataset": "POPC", "sql": "select 1"})
            unknown_tool = await s.call_tool("run_sql", {"query": "select 1", "lang": "en"})
            bad_type = await s.call_tool("query_data", {"dataset": 5})
            return huge, unknown_key, unknown_tool, bad_type
    huge, unknown_key, unknown_tool, bad_type = run(go())
    assert all(r.isError for r in (huge, unknown_key, unknown_tool, bad_type))
    reasons = [E.payload(r)[0]["reason"] for r in (huge, unknown_key, unknown_tool, bad_type)]
    assert reasons == ["invalid_input", "invalid_input", "unknown_tool", "invalid_input"]
    assert "available:" in E.payload(unknown_tool)[0]["message"] and spy.calls == []


def test_unknown_columns_and_adversarial_literals_are_harmless(tmp_path, monkeypatch):
    app, mcp = E.make_app(tmp_path, monkeypatch)
    secret_bits = [str(tmp_path), "parquet", "SELECT", "metadata.duckdb", "Traceback"]

    async def go():
        async with E.started(app), E.session(app) as s:
            out = [await s.call_tool("query_data", {"dataset": "POPC", "group_by": ["NOPE"]}),
                   await s.call_tool("query_data", {"dataset": "POPC/../../etc/passwd"}),
                   await s.call_tool("describe_dataset", {"dataset": "POPC; DROP TABLE matrices"})]
            for lit in ("O'Brien", "x') OR 1=1 --", "Total'; DROP TABLE t; --", "\u0000"):
                out.append(await s.call_tool("query_data", {"dataset": "POPC", "filters": {"REF_AREA": [lit]},
                                                            "group_by": ["TIME_PERIOD"]}))
            after = await s.call_tool("query_data", {"dataset": "POPC", "group_by": ["REF_AREA", "TIME_PERIOD"]})
            return out, after
    out, after = run(go())
    for r in out:
        text = r.content[0].text
        assert not any(bit in text for bit in secret_bits)
    assert [E.payload(r)[0]["reason"] for r in out[:3]] == ["unknown_column", "invalid_input", "invalid_input"]
    assert all(E.payload(r)[0]["status"] in ("unavailable", "ok", "error") for r in out[3:])
    assert E.payload(after)[0]["status"] == "ok"                              # the database is intact


def test_bad_content_type_and_paths_reveal_nothing(tmp_path, monkeypatch):
    app, mcp = E.make_app(tmp_path, monkeypatch)

    async def go():
        async with E.started(app), E.http(app) as c:
            return [await c.post("/mcp", content=b"{}", headers={"content-type": "text/plain"}),
                    await c.post("/mcp/mcp", json=E.RPC, headers=E.HEADERS),
                    await c.post("/mcp/", json=E.RPC, headers=E.HEADERS),
                    await c.post("/mcp", content=b"not json", headers=E.HEADERS),
                    await c.get("/mcp", headers={"accept": "text/event-stream"})]
    rs = run(go())
    assert [r.status_code for r in rs[:3]] == [400, 404, 404]
    assert rs[3].status_code in (400, 422) and rs[4].status_code in (400, 405, 406)
    for r in rs:
        assert str(tmp_path) not in r.text and "Traceback" not in r.text


def test_a_request_before_the_lifespan_started_is_a_clean_503(tmp_path, monkeypatch):
    app, mcp = E.make_app(tmp_path, monkeypatch)

    async def go():
        async with E.http(app) as c:                                          # lifespan not entered
            return (await post(c, E.RPC)).status_code
    assert run(go()) == 503


# ---------------------------------------------------------------- no model, no sampling

@pytest.fixture
def sealed(monkeypatch):
    def no_model(*a, **k):
        raise AssertionError("a model/provider call was attempted")
    from app.services import agent, llm_client
    for k in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "GEMINI_API_KEY", "MISTRAL_API_KEY",
              "DEEPSEEK_API_KEY", "XAI_API_KEY", "OPENROUTER_API_KEY"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setattr(agent, "run_agent", no_model)
    monkeypatch.setattr(agent, "complete_with_tools", no_model)
    monkeypatch.setattr(llm_client, "complete_with_tools", no_model)
    monkeypatch.setattr(llm_client, "_anthropic", no_model)
    monkeypatch.setattr(llm_client, "_openai", no_model)
    monkeypatch.setattr(llm_client, "_openai_responses", no_model)


def test_all_eight_tools_work_with_no_model_and_the_server_never_asks_for_one(tmp_path, monkeypatch, sealed):
    app, mcp = E.make_app(tmp_path, monkeypatch)
    asked = []

    async def sampling(context, params):
        asked.append(params)
        from mcp import types
        return types.ErrorData(code=-1, message="no sampling")

    async def go():
        out = {}
        async with E.started(app), E.session(app, sampling=sampling) as s:
            for name, args in E.CALLS.items():
                out[name] = (await s.call_tool(name, args)).structuredContent["status"]
            sel = (await s.call_tool("query_data", E.CALLS["query_data"])).structuredContent["provenance"]
            out["get_evidence_links"] = (await s.call_tool("get_evidence_links", {
                "selection": sel["selection"], "generation_id": sel["generation"]["id"]})).structuredContent["status"]
        return out
    out = run(go())
    assert set(out) == set(R.tool_names()) and all(v in ("ok", "partial", "needs_clarification") for v in out.values())
    assert asked == []
    import ast
    tree = ast.parse(open(P.__file__, encoding="utf-8").read())
    names = {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)} | \
        {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
    assert not names & {"create_message", "elicit", "elicit_form", "elicit_url", "send_request",
                        "run_agent", "complete_with_tools", "Anthropic", "OpenAI"}


# ---------------------------------------------------------------- health and a real server

def test_health_reports_the_mcp_capability_without_secrets(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from app.main import health
    app, mcp = E.make_app(tmp_path, monkeypatch)
    summary = P.health_summary(app)
    assert summary == {"enabled": True, "contract": "tempo-tools/2", "generation": "present", "call_logging": False}
    off, _ = E.make_app(tmp_path, monkeypatch, environ={"TEMPO_MCP_ENABLED": "false"}, env=app.state.corpus_env)
    assert P.health_summary(off)["enabled"] is False
    body = health(SimpleNamespace(app=app))
    assert body["mcp"] == summary
    assert "TEMPO" not in json.dumps(body["mcp"]) and str(tmp_path) not in json.dumps(body["mcp"])


def serve(app, port):
    import uvicorn
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning", lifespan="on"))
    t = threading.Thread(target=server.run, daemon=True)
    t.start()
    for _ in range(100):
        try:
            socket.create_connection(("127.0.0.1", port), timeout=0.2).close()
            return server, t
        except OSError:
            time.sleep(0.05)
    raise RuntimeError("server did not start")


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def test_a_real_server_starts_serves_mcp_and_shuts_down_cleanly(tmp_path, monkeypatch):
    """The advertised /mcp path through uvicorn's real lifespan: no /mcp/mcp, no redirect."""
    port = free_port()
    monkeypatch.setattr(config, "PUBLIC_BASE_URL", f"http://127.0.0.1:{port}")
    corpus_env = E.full_env(tmp_path, monkeypatch)
    app = FastAPI(lifespan=P.lifespan)
    mcp = P.install(app, {"TEMPO_MCP_ENABLED": "true", "TEMPO_MCP_LOCAL_TEST": "true"})
    server, thread = serve(app, port)
    try:
        import urllib.request
        from importlib import import_module
        probe = import_module("mcp_probe")
        report = probe.probe(f"http://127.0.0.1:{port}", dataset="POPC")
        assert report["tools"] == R.tool_names() and report["call_status"] == "ok" and report["same_representation"]
        req = urllib.request.Request(f"http://127.0.0.1:{port}/mcp/", data=b"{}", method="POST",
                                     headers={"content-type": "application/json"})
        with pytest.raises(Exception) as e:
            urllib.request.urlopen(req)
        assert "404" in str(e.value)                                           # a trailing slash is not an alias
    finally:
        server.should_exit = True
        thread.join(10)
    assert not thread.is_alive() and mcp.gate.executor._shutdown and corpus_env


# ---------------------------------------------------------------- content log (dev servers)

def test_the_call_log_is_off_by_default_and_disclosed_when_on(tmp_path, monkeypatch):
    from app import config
    logs = tmp_path / "logs"
    monkeypatch.setattr(config, "ASK_LOG_DIR", logs)
    off, mcp_off = E.make_app(tmp_path, monkeypatch)
    assert P.LOGGING_NOTICE not in P.build_server(mcp_off.gate, mcp_off.settings).instructions

    async def call(app):
        async with E.started(app), E.session(app) as s:
            return await s.call_tool("describe_dataset", {"dataset": "POPC", "lang": "en"})
    run(call(off))
    assert not (logs / P.CALL_LOG).exists()

    on, mcp_on = E.make_app(tmp_path, monkeypatch, environ={"TEMPO_MCP_LOG_CALLS": "true"}, env=off.state.corpus_env)
    assert P.build_server(mcp_on.gate, mcp_on.settings).instructions.endswith(P.LOGGING_NOTICE)
    assert P.health_summary(on)["call_logging"] is True
    env = E.payload(run(call(on)))[0]
    lines = (logs / P.CALL_LOG).read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    rec = json.loads(lines[0])
    assert rec["tool"] == "describe_dataset" and rec["arguments"] == {"dataset": "POPC", "lang": "en"}
    assert rec["status"] == env["status"] and rec["result"]["data"] == env["data"]
    assert not {"ip", "client", "host", "headers", "user_agent"} & set(rec)       # nothing about the caller
