"""AQ-06A: Ask served to pages on another origin.

Explicit CORS origins instead of an open policy (local development origins only by default,
/mcp never), API links on the API origin and page links on the site origin, and the static
build's `api_origin`. The browser side is tests/test_aq06a_browser.py.
"""
import importlib.util
import json
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import config
from app.main import _CorsExceptMcp, cors_options
from app.services.tools import contract as C

ROOT = Path(__file__).resolve().parent.parent
SITE = "https://ins.example"


def preflight(c, path, origin):
    return c.options(path, headers={"origin": origin, "access-control-request-method": "POST",
                                    "access-control-request-headers": "content-type"})


# ---------------------------------------------------------------- TEMPO_CORS_ORIGINS

def test_cors_origins_are_bare_origins_normalized_and_deduplicated():
    env = {"TEMPO_CORS_ORIGINS": " https://ins.gov2.ro/ ,http://localhost:8097,https://ins.gov2.ro"}
    assert config.cors_origins(env) == ["https://ins.gov2.ro", "http://localhost:8097"]
    assert config.cors_origins({}) == [] and config.cors_origins({"TEMPO_CORS_ORIGINS": " , "}) == []


@pytest.mark.parametrize("bad", ["*", "https://*.gov2.ro", "https://ins.gov2.ro/ask", "ins.gov2.ro",
                                 "ftp://ins.gov2.ro", "https://u:p@ins.gov2.ro", "https://ins.gov2.ro?x=1"])
def test_a_wildcard_path_or_credential_is_a_configuration_error(bad):
    with pytest.raises(ValueError, match="TEMPO_CORS_ORIGINS"):
        config.cors_origins({"TEMPO_CORS_ORIGINS": f"https://ok.example,{bad}"})


def test_by_default_only_local_development_origins_get_cors():
    from app.main import app as real
    c = TestClient(real)
    for local in ("http://localhost:8080", "http://127.0.0.1:5173", "http://[::1]:8000"):
        r = c.get("/api/health", headers={"origin": local})
        assert r.headers.get("access-control-allow-origin") == local
    for foreign in ("https://anywhere.example", "http://localhost.evil.example", "http://127.0.0.1.evil.example"):
        assert "access-control-allow-origin" not in c.get("/api/health", headers={"origin": foreign}).headers
        assert preflight(c, "/api/ask", foreign).status_code == 400


def _app(origins):
    """The real middleware and options around stand-ins for /api/ask and /mcp."""
    app = FastAPI()

    @app.post("/api/ask")
    def ask():
        from fastapi.responses import JSONResponse
        return JSONResponse({"detail": "busy"}, status_code=503, headers={"Retry-After": "7"})

    @app.post("/mcp")
    def mcp():
        return {}

    app.add_middleware(_CorsExceptMcp, **cors_options(origins))
    return TestClient(app)


def test_a_listed_site_may_post_to_ask_and_read_retry_after():
    c = _app([SITE])
    p = preflight(c, "/api/ask", SITE)
    assert p.status_code == 200 and p.headers["access-control-allow-origin"] == SITE
    assert "POST" in p.headers["access-control-allow-methods"]
    assert "content-type" in p.headers["access-control-allow-headers"].lower()
    assert "access-control-allow-credentials" not in p.headers                  # no cookies, ever
    r = c.post("/api/ask", json={}, headers={"origin": SITE})
    assert r.headers["access-control-allow-origin"] == SITE
    assert "retry-after" in r.headers["access-control-expose-headers"].lower()


def test_an_explicit_list_replaces_the_local_default_and_foreign_sites_fail():
    c = _app([SITE])
    for other in ("http://localhost:8080", "https://evil.example", "https://ins.example.evil.example"):
        p = preflight(c, "/api/ask", other)
        assert p.status_code == 400 and "access-control-allow-origin" not in p.headers
        assert "access-control-allow-origin" not in c.post("/api/ask", json={}, headers={"origin": other}).headers


def test_cors_never_applies_to_mcp_even_for_a_listed_site():
    c = _app([SITE])
    assert "access-control-allow-origin" not in preflight(c, "/mcp", SITE).headers
    assert "access-control-allow-origin" not in c.post("/mcp", json={}, headers={"origin": SITE}).headers


# ---------------------------------------------------------------- link origins

def test_api_links_stay_on_the_api_origin_and_pages_go_to_the_site(monkeypatch):
    monkeypatch.setattr(config, "PUBLIC_BASE_URL", "https://api-ins.example")
    monkeypatch.setattr(config, "PUBLIC_SITE_URL", "https://ins.example/")
    assert C.public_url("/api/entity-rankings?x=1") == "https://api-ins.example/api/entity-rankings?x=1"
    assert C.public_url("/sdmx/2.1/data/INS,POPC/") == "https://api-ins.example/sdmx/2.1/data/INS,POPC/"
    assert C.public_url("/mcp") == "https://api-ins.example/mcp"
    assert C.dataset_page("POPC", "en").startswith("https://ins.example/dataset-v2.html?code=POPC")
    assert C.public_url("/apiary.html") == "https://ins.example/apiary.html"     # a page, not /api/


def test_without_a_site_origin_every_link_keeps_the_single_base(monkeypatch):
    monkeypatch.setattr(config, "PUBLIC_SITE_URL", "")
    monkeypatch.setattr(config, "PUBLIC_BASE_URL", "https://ins.example")
    assert C.dataset_page("POPC", "ro").startswith("https://ins.example/dataset-v2.html?")
    assert C.public_url("/api/x") == "https://ins.example/api/x"
    monkeypatch.setattr(config, "PUBLIC_BASE_URL", "")
    assert C.public_url("/api/x") == "/api/x" and C.dataset_page("POPC", "ro").startswith("/dataset-v2.html?")


def test_a_site_origin_alone_moves_pages_and_leaves_api_links_relative(monkeypatch):
    monkeypatch.setattr(config, "PUBLIC_BASE_URL", "")
    monkeypatch.setattr(config, "PUBLIC_SITE_URL", "https://ins.example")
    assert C.public_url("/api/x") == "/api/x"
    assert C.public_url("/compare.html?y=2021") == "https://ins.example/compare.html?y=2021"


# ---------------------------------------------------------------- static build

def _build_static():
    spec = importlib.util.spec_from_file_location("build_static", ROOT / "scripts" / "build-static.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.mark.parametrize("value,expected", [
    ("", None), ("https://api-ins.gov2.ro/", "https://api-ins.gov2.ro"),
    ("http://localhost:8098", "http://localhost:8098"), ("http://127.0.0.1:8098", "http://127.0.0.1:8098")])
def test_static_api_origin_accepts_a_bare_origin(value, expected):
    assert _build_static().ask_api_origin(value) == expected


@pytest.mark.parametrize("bad", ["http://api-ins.gov2.ro", "https://api-ins.gov2.ro/api",
                                 "javascript:alert(1)", "https://u:p@api.example", "api-ins.gov2.ro"])
def test_static_api_origin_refuses_anything_else(bad):
    with pytest.raises(ValueError, match="--api-origin"):
        _build_static().ask_api_origin(bad)


def test_the_static_config_names_the_ask_api_only_when_given(tmp_path, monkeypatch):
    bs = _build_static()
    monkeypatch.setattr(config, "CORPUS_DIR", tmp_path / "no-corpus")         # no view profiles to copy

    def cfg(out):
        text = (out / "js" / "config.js").read_text()
        return json.loads(text.split("window.TEMPO_CONFIG = ", 1)[1].rstrip().rstrip(";"))

    bs.assemble_site(tmp_path / "a", {"generation": {"id": "g1"}, "commit": "c1"})
    assert cfg(tmp_path / "a") == {"mode": "static", "generation": "g1", "commit": "c1"}
    bs.assemble_site(tmp_path / "b", {"generation": {"id": "g1"}}, "https://api-ins.example")
    assert cfg(tmp_path / "b")["api_origin"] == "https://api-ins.example"
