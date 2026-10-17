"""Harness for the AT-03 tests: a fresh FastAPI app with the public MCP installed from an explicit
environment (never from import-time state), on a synthetic generation, driven by the real MCP
Python SDK client over Streamable HTTP through an in-process ASGI transport."""
import contextlib
import json

import httpx
from fastapi import FastAPI

from at02_env import full_env
from app import config
from app.services import public_mcp

BASE = "https://mcp.example.org"
HOST = "mcp.example.org"
ENV = {"TEMPO_MCP_ENABLED": "true", "TEMPO_MCP_ALLOWED_HOSTS": HOST}


def make_app(tmp_path, monkeypatch, environ=None, *, extra=(), env=None):
    """(app, mcp) with the synthetic corpus patched in. `environ` overrides the MCP env."""
    corpus_env = env or full_env(tmp_path, monkeypatch, extra=extra)
    monkeypatch.setattr(config, "PUBLIC_BASE_URL", BASE)
    app = FastAPI(lifespan=public_mcp.lifespan)
    mcp = public_mcp.install(app, {**ENV, **(environ or {})})
    app.state.corpus_env = corpus_env
    return app, mcp


@contextlib.asynccontextmanager
async def started(app):
    """The app inside its own lifespan (what uvicorn does)."""
    async with app.router.lifespan_context(app):
        yield


def http(app, *, host=HOST, headers=None):
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=f"https://{host}",
                             headers=headers or {}, timeout=30)


@contextlib.asynccontextmanager
async def session(app, *, host=HOST, headers=None, sampling=None, path="/mcp"):
    """An initialized SDK ClientSession over Streamable HTTP. The app must be started."""
    from mcp import ClientSession
    from mcp.client.streamable_http import streamable_http_client
    async with http(app, host=host, headers=headers) as client:
        async with streamable_http_client(f"https://{host}{path}", http_client=client) as (r, w, _):
            async with ClientSession(r, w, sampling_callback=sampling) as s:
                await s.initialize()
                yield s


def payload(result):
    """(structuredContent, parsed text fallback) of a CallToolResult."""
    text = json.loads(result.content[0].text)
    return result.structuredContent, text


RPC = {"jsonrpc": "2.0", "id": 1, "method": "initialize",
       "params": {"protocolVersion": "2025-03-26", "capabilities": {},
                  "clientInfo": {"name": "t", "version": "1"}}}
HEADERS = {"content-type": "application/json", "accept": "application/json, text/event-stream"}


def big_localities(corpus, n=2732):
    """BIGL: one period, n named localities: a result far over the model-visible row/byte budget."""
    from at01_fixtures import add_dataset
    from test_at01_changes import area_dim, time_dim, unit_dim
    rows = [(f"Localitatea {i:04d}", "2020", "Numar persoane", float(i)) for i in range(n)]
    add_dataset(corpus, "BIGL", [area_dim([r[0] for r in rows], level="locality"),
                                 time_dim(("2020",)), unit_dim("Numar persoane")], rows, name="Localitati")


HEAVY = "select sum(a.range * b.range) from range(200000) a, range(200000) b"

# one valid call per tool on the synthetic generation (get_evidence_links is filled in by the test)
CALLS = {
    "discover_indicators": {"query": "populatie pe judete"},
    "describe_dataset": {"dataset": "POPC"},
    "find_dimension_values": {"dataset": "POPC", "column": "REF_AREA", "query": "cl"},
    "query_data": {"dataset": "POPC", "group_by": ["REF_AREA", "TIME_PERIOD"]},
    "compare_periods": {"dataset": "COUNTX", "entity_columns": ["REF_AREA"],
                        "intervals": [{"from": "1992", "to": "2002"}]},
    "rank_entities": {"dataset": "COUNTX", "entity_columns": ["REF_AREA"], "year": "2002"},
    "run_recipe": {"recipe": "fx_intensity", "year": "2024"},
}
