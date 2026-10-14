"""Ask debug mode (TEMPO_ASK_DEBUG): per-step events, the NDJSON stream, redaction."""
import json

import pytest

from fix08_helpers import FAKE_KEY, install, make_client, text_resp, tools_resp
from app import config
from app.services.llm_client import LLMError

BODY = {"question": "x", "provider": "anthropic", "model": "claude-sonnet-5-5", "api_key": FAKE_KEY}


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(config, "ASK_BYOK_ENABLED", True)
    return make_client()


def two_turns(n, messages, kw):
    return tools_resp(1) if n == 1 else text_resp("gata")


def test_debug_is_off_unless_the_server_enables_it(client, monkeypatch):
    monkeypatch.setattr(config, "ASK_DEBUG", False)
    install(monkeypatch, two_turns)
    r = client.post("/api/ask", json={**BODY, "debug": True})
    assert r.status_code == 200 and "debug" not in r.json()
    assert client.post("/api/ask/stream", json=BODY).status_code == 404
    assert client.get("/api/ask/config").json()["debug"] is False


def test_debug_response_lists_every_step(client, monkeypatch):
    monkeypatch.setattr(config, "ASK_DEBUG", True)
    install(monkeypatch, two_turns)
    d = client.post("/api/ask", json={**BODY, "debug": True}).json()
    kinds = [e["event"] for e in d["debug"]["events"]]
    assert kinds == ["start", "model_call", "model_done", "tool", "tool_done",
                     "model_call", "model_done", "answer"]
    assert d["answer"] == "gata" and all("ms" in e for e in d["debug"]["events"])
    # without debug: true the answer has no debug block
    assert "debug" not in client.post("/api/ask", json=BODY).json()


def test_stream_sends_steps_then_the_result(client, monkeypatch):
    monkeypatch.setattr(config, "ASK_DEBUG", True)
    install(monkeypatch, two_turns)
    lines = [json.loads(x) for x in client.post("/api/ask/stream", json=BODY).text.splitlines()]
    assert lines[0]["event"] == "start" and lines[-1]["event"] == "result"
    assert lines[-1]["result"]["answer"] == "gata"


def test_stream_reports_the_provider_error_without_the_key(client, monkeypatch):
    monkeypatch.setattr(config, "ASK_DEBUG", True)

    def fail(n, messages, kw):
        e = LLMError("provider_auth", "The provider rejected the API key", 401)
        e.debug_detail = f"AuthenticationError: invalid key {FAKE_KEY}"
        raise e

    install(monkeypatch, fail)
    text = client.post("/api/ask/stream", json=BODY).text
    lines = [json.loads(x) for x in text.splitlines()]
    err = next(x for x in lines if x["event"] == "model_error")
    assert err["code"] == "provider_auth" and "AuthenticationError" in err["detail"]
    assert lines[-1] == {"event": "error", "status": 401, "detail": "The provider rejected the API key"}
    assert FAKE_KEY not in text
