"""FIX-08 item 6: logging contract and credential redaction."""
import json
import logging
import re
from pathlib import Path

import pytest

from fix08_helpers import FAKE_KEY, install, make_client, text_resp, tools_resp
from app import config
from app.services import ask_guard

ROOT = Path(__file__).resolve().parent.parent
SENTINEL = "SENTINEL0123456789abcdef"


@pytest.fixture(autouse=True)
def _ask_on(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "ASK_ENABLED", True)
    monkeypatch.setattr(config, "ASK_LOG_DIR", tmp_path)


def test_content_logging_off_by_default():
    import importlib
    import os
    assert "TEMPO_ASK_LOG_CHATS" not in os.environ or os.environ["TEMPO_ASK_LOG_CHATS"] != "true"
    assert config.ASK_LOG_CHATS is False
    # shipped deployment config must not enable it either
    fly = (ROOT / "fly.toml").read_text()
    m = re.search(r"TEMPO_ASK_LOG_CHATS\s*=\s*'?(\w+)'?", fly)
    assert m is None or m.group(1).lower() in ("false", "0")


def test_default_request_writes_metrics_only(monkeypatch, caplog, tmp_path):
    install(monkeypatch, lambda n, m, kw: text_resp("TOP-SECRET-ANSWER"))
    caplog.set_level(logging.DEBUG)
    r = make_client().post("/api/ask", json={"question": "PRIVATE-QUESTION"})
    assert r.status_code == 200
    text = caplog.text
    assert "ASK_METRICS" in text
    assert "PRIVATE-QUESTION" not in text and "TOP-SECRET-ANSWER" not in text
    assert "CHAT_LOG" not in text
    assert not (tmp_path / "ask-chats.jsonl").exists()


def test_opt_in_content_log_is_separate_and_redacted(monkeypatch, caplog, tmp_path):
    monkeypatch.setattr(config, "ASK_LOG_CHATS", True)

    def handler(inp, conn):
        # sentinel nested inside tool output
        return {"categories": [{"meta": {"headers": {"Authorization": f"Bearer {FAKE_KEY}"},
                                         "note": f"url?api_key={FAKE_KEY}"}}]}

    install(monkeypatch, lambda n, m, kw: tools_resp(1) if n == 1 else text_resp(f"answer {FAKE_KEY}"),
            handler=handler)
    caplog.set_level(logging.DEBUG)
    r = make_client().post("/api/ask", json={"question": f"q with {FAKE_KEY}", "api_key": FAKE_KEY,
                                             "provider": "anthropic", "model": "claude-sonnet-4-6"})
    assert r.status_code == 200
    file_text = (tmp_path / "ask-chats.jsonl").read_text()
    for blob in (caplog.text, file_text):
        assert SENTINEL not in blob
        assert "CHAT_LOG" in caplog.text
    entry = json.loads(file_text.splitlines()[0])
    assert "q with" in entry["question"] and "api_key" not in entry
    # operational metrics line carries no content
    metrics = [rec.getMessage() for rec in caplog.records if "ASK_METRICS" in rec.getMessage()]
    assert metrics and all("q with" not in m and "answer" not in m for m in metrics)


def test_sentinel_in_tool_exception_and_provider_error_never_logged(monkeypatch, caplog):
    def bad_tool(inp, conn):
        raise RuntimeError(f"db down; Authorization: Bearer {FAKE_KEY}; api_key={FAKE_KEY}")

    install(monkeypatch, lambda n, m, kw: tools_resp(1) if n == 1 else text_resp("done"), handler=bad_tool)
    caplog.set_level(logging.DEBUG)
    r = make_client().post("/api/ask", json={"question": "x"})
    assert r.status_code == 200
    assert SENTINEL not in caplog.text and SENTINEL not in r.text

    class APIError(Exception):
        status_code = 400

    def boom(n, m, kw):
        raise APIError(f"invalid x-api-key {FAKE_KEY}")

    install(monkeypatch, boom)
    caplog.clear()
    r = make_client().post("/api/ask", json={"question": "x", "api_key": FAKE_KEY,
                                             "provider": "anthropic", "model": "claude-sonnet-4-6"})
    assert r.status_code == 502
    assert SENTINEL not in caplog.text and SENTINEL not in r.text


def test_recursive_redaction():
    obj = {"a": [{"api_key": "plain-nonpattern-value", "x": ("keep", f"sk-{SENTINEL}")}],
           "headers": {"X-Api-Key": "zzzz1234", "authorization": "Bearer abcdefghijkl"},
           "deep": {"deeper": {"s": f"prefix {FAKE_KEY} suffix", "n": 5}},
           "custom": "my-weird-secret-value used"}
    out = json.dumps(ask_guard.redact(obj, secrets=("my-weird-secret-value",)))
    for leaked in ("plain-nonpattern-value", SENTINEL, "zzzz1234", "abcdefghijkl", "my-weird-secret-value"):
        assert leaked not in out
    assert "keep" in out and '"n": 5' in out  # non-secrets survive
    assert obj["deep"]["deeper"]["s"].count(FAKE_KEY) == 1  # input not mutated


def test_logging_filter_scrubs_tracebacks(caplog):
    lg = logging.getLogger("app.routers.ask")
    caplog.set_level(logging.DEBUG)
    try:
        raise RuntimeError(f"boom {FAKE_KEY}")
    except RuntimeError:
        lg.exception("failed %s", FAKE_KEY)
    assert SENTINEL not in caplog.text


def test_ask_config_discloses_logging(monkeypatch):
    c = make_client()
    assert c.get("/api/ask/config").json()["chat_logging"] is False
    monkeypatch.setattr(config, "ASK_LOG_CHATS", True)
    body = c.get("/api/ask/config").json()
    assert body["chat_logging"] is True and "byok_models" in body
    assert "key" not in json.dumps(body).lower().replace("byok", "")
