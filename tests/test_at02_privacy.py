"""AT-02 acceptance: an arbitrary-format key echoed by a provider error appears nowhere.

HTTP body, NDJSON stream, every logger record (agent debug lines included) and the persisted
metrics line are captured. With chat logging off, ordinary metrics carry no content fields.
"""
import json
import logging

import pytest

from fix08_helpers import fake_env, install, make_client, text_resp, tools_resp
from app import config
from app.services import ask_guard
from app.services.llm_client import LLMError

# Not an sk-/AIza/xai- shape: only the exact-key scrub can remove it.
ODD_KEY = "q7Zp-LmNoP.9rStUvWx_1234AbCdEf"
BODY = {"question": "întrebare-privată", "provider": "mistral", "model": "mistral-large-latest",
        "api_key": ODD_KEY}


@pytest.fixture(autouse=True)
def _on(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "ASK_ENABLED", True)
    monkeypatch.setattr(config, "ASK_BYOK_ENABLED", True)
    monkeypatch.setattr(config, "ASK_DEBUG", True)
    monkeypatch.setattr(config, "ASK_LOG_CHATS", False)
    monkeypatch.setattr(config, "ASK_LOG_DIR", tmp_path)


def leaky_provider(n, m, kw):
    e = LLMError("provider_auth", "The provider rejected the API key", 401)
    e.debug_detail = f"AuthenticationError: invalid api key '{ODD_KEY}' (Authorization: Bearer {ODD_KEY})"
    raise e


def metrics_lines(caplog):
    return [r.getMessage() for r in caplog.records if "ASK_METRICS" in r.getMessage()]


def test_the_key_is_nowhere_in_http_ndjson_logs_or_metrics(monkeypatch, caplog, tmp_path):
    install(monkeypatch, leaky_provider)
    caplog.set_level(logging.DEBUG)
    client = make_client()
    plain = client.post("/api/ask", json={**BODY, "debug": True})
    stream = client.post("/api/ask/stream", json=BODY)
    assert plain.status_code == 401 and ODD_KEY not in plain.text
    lines = [json.loads(x) for x in stream.text.splitlines()]
    assert ODD_KEY not in stream.text
    assert lines[-1]["event"] == "error" and lines[-1]["status"] == 401
    assert any(e["event"] == "model_error" and "AuthenticationError" in e["detail"] for e in lines)
    assert ODD_KEY not in caplog.text                       # every record of every logger
    assert any("ASK_DEBUG" in r.getMessage() for r in caplog.records)   # the debug lines did exist
    assert not list(tmp_path.glob("*.jsonl"))               # no content log with chat logging off


def test_a_tool_failure_that_echoes_the_key_is_not_logged(monkeypatch, caplog):
    def bad_tool(name, args):
        raise RuntimeError(f"db down; api_key={ODD_KEY}; token {ODD_KEY}")

    install(monkeypatch, lambda n, m, kw: tools_resp(1) if n == 1 else text_resp("gata"), handler=bad_tool)
    caplog.set_level(logging.DEBUG)
    r = make_client().post("/api/ask", json={**BODY, "debug": True})
    assert r.status_code == 200
    assert ODD_KEY not in r.text and ODD_KEY not in caplog.text


def test_ordinary_metrics_hold_no_content_when_chat_logging_is_off(monkeypatch, caplog):
    install(monkeypatch, lambda n, m, kw: tools_resp(1) if n == 1 else text_resp("RĂSPUNS-PRIVAT"),
            handler=lambda name, args: fake_env(name, status="unavailable", reason="conflicting_grain",
                                                message="mesaj-intern", selection=None))
    caplog.set_level(logging.DEBUG)
    r = make_client().post("/api/ask", json={**BODY, "api_key": "k-ok-123456", "debug": False})
    assert r.status_code == 200
    lines = metrics_lines(caplog)
    assert len(lines) == 1
    payload = json.loads(lines[0].split("ASK_METRICS ", 1)[1])
    allowed = set(ask_guard.METRIC_SCALARS) | {"usage", "refusal_codes"}
    assert set(payload) <= allowed
    assert payload["outcome"] in ("refused", "answered", "partial") and payload["tool_executions"] == 1
    assert payload["refusal_codes"] == {"conflicting_grain": 1}
    for forbidden in ("întrebare-privată", "RĂSPUNS-PRIVAT", "mesaj-intern", "k-ok-123456", "query"):
        assert forbidden not in lines[0]
    assert "CHAT_LOG" not in caplog.text


def test_with_chat_logging_on_the_key_is_still_redacted_from_the_content_log(monkeypatch, caplog, tmp_path):
    monkeypatch.setattr(config, "ASK_LOG_CHATS", True)
    install(monkeypatch, lambda n, m, kw: text_resp(f"răspuns cu {ODD_KEY}"))
    caplog.set_level(logging.DEBUG)
    r = make_client().post("/api/ask", json={**BODY, "question": f"cheia mea este {ODD_KEY}"})
    assert r.status_code == 200
    blob = (tmp_path / "ask-chats.jsonl").read_text() + caplog.text
    assert ODD_KEY not in blob and "cheia mea este" in blob
