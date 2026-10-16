"""AT-02: credential redaction before logging, bounded debug fields, content-free metrics,
and cancellation of a running DuckDB query without touching another cursor."""
import json
import logging
import threading
import time

import duckdb
import pytest

from app.services import ask_guard as G
from app.services import llm_client as lc

# Not an sk-/AIza/xai- shape: a Mistral/OpenRouter-style key no pattern can recognise.
ODD_KEY = "q7Zp-LmNoP.9rStUvWx_1234AbCdEf"


# ---------------------------------------------------------------- redaction

def _record(msg, *args):
    return logging.LogRecord("app.services.agent", logging.INFO, __file__, 1, msg, args, None)


def test_pattern_redaction_alone_misses_an_arbitrary_format_key():
    assert ODD_KEY in G.redact_text(f"provider said: {ODD_KEY}")      # why the exact key is needed


def test_the_active_request_key_is_removed_from_log_records():
    f = G.RedactingFilter()
    with G.secrets_scope(ODD_KEY):
        r = _record("model_error %s", {"detail": f"AuthenticationError: bad key {ODD_KEY}"})
        f.filter(r)
        assert ODD_KEY not in r.getMessage() and "[REDACTED]" in r.getMessage()
    r2 = _record("later %s", ODD_KEY)                                # scope ended: nothing to match
    f.filter(r2)
    assert ODD_KEY in r2.getMessage()


def test_scope_is_per_context_and_nests():
    seen = []
    with G.secrets_scope("aaaa-1111"):
        def other_thread():                                          # a new thread has no scope
            seen.append(G.active_secrets())
        t = threading.Thread(target=other_thread)
        t.start(); t.join()
        assert G.active_secrets() == ("aaaa-1111",)
    assert seen == [()] and G.active_secrets() == ()


def test_short_or_empty_secrets_are_ignored():
    with G.secrets_scope("", None, "ab"):
        assert G.active_secrets() == ()


def test_provider_error_detail_never_carries_the_request_or_server_key(monkeypatch):
    class Boom(Exception):
        status_code = 401

    def fail(*a, **k):
        raise Boom(f"invalid x-api-key {ODD_KEY} / server {'SRVKEY-abcdef123456'}")

    monkeypatch.setenv("MISTRAL_API_KEY", "SRVKEY-abcdef123456")
    monkeypatch.setattr(lc, "_openai", fail)
    with pytest.raises(lc.LLMError) as e:
        lc.complete_with_tools([{"role": "user", "content": "x"}], [], provider="mistral", model="m",
                               api_key=ODD_KEY)
    assert e.value.code == "provider_auth"
    assert ODD_KEY not in e.value.debug_detail and "SRVKEY-abcdef123456" not in e.value.debug_detail
    assert "Boom" in e.value.debug_detail                            # the useful part survives


# ---------------------------------------------------------------- bounded fields

def test_bound_keeps_json_valid_and_small():
    big = {"rows": [[i, "x" * 500] for i in range(1000)], "note": "é" * 2000, "deep": {"a": {"b": {"c": {"d": 1}}}}}
    out = G.bound(big)
    text = json.dumps(out, ensure_ascii=False)
    assert json.loads(text) == out and len(text) < 8000      # 20 rows x 300 chars at most
    assert out["rows"][-1] == "…(+980 items)" and out["note"].endswith("…(+1700 chars)")
    assert out["deep"]["a"]["b"]["c"] == "<dict of 1>"


def test_bound_leaves_small_values_alone():
    v = {"a": [1, 2.5, None, True], "b": "ok"}
    assert G.bound(v) == v


# ---------------------------------------------------------------- metrics

def test_metrics_keep_counts_and_drop_content():
    dirty = {
        "request_id": "r1", "provider": "anthropic", "model": "m", "outcome": "answered",
        "tool_executions": 3, "cache_hits": 1, "duration_ms": 1234,
        "usage": {"input_tokens": 10, "output_tokens": 5, "reasoning_tokens": None, "secret": "x"},
        "refusal_codes": {"conflicting_grain": 2, "Not A Code": 1, "ok": "x"},
        # content that must never reach an ordinary metrics line
        "question": "câți locuitori are Cluj?", "answer": "…", "filters": {"REF_AREA": ["Cluj"]},
        "api_key": ODD_KEY, "error": f"Boom {ODD_KEY}", "tool_trace": [{"input": {"a": 1}}],
    }
    out = G.sanitize_metrics(dirty)
    assert out["tool_executions"] == 3 and out["usage"] == {"input_tokens": 10, "output_tokens": 5,
                                                            "reasoning_tokens": None}
    assert out["refusal_codes"] == {"conflicting_grain": 2}
    text = json.dumps(out)
    for forbidden in ("Cluj", "câți", ODD_KEY, "REF_AREA", "Boom", "tool_trace", '"answer"', '"question"'):
        assert forbidden not in text


# ---------------------------------------------------------------- cancellation

HEAVY = "select sum(a.range * b.range) from range(200000) a, range(200000) b"


def _run(cursor, out):
    t0 = time.monotonic()
    try:
        cursor.execute(HEAVY).fetchall()
        out["result"] = "finished"
    except duckdb.InterruptException:
        out["result"] = "interrupted"
    except Exception as e:  # noqa: BLE001
        out["result"] = type(e).__name__
    out["secs"] = time.monotonic() - t0


def test_cancel_interrupts_only_the_attached_cursor():
    parent = duckdb.connect(":memory:")
    mine, theirs = parent.cursor(), parent.cursor()
    token = G.CancelToken()
    mine_out, their_out = {}, {}
    with token.running(mine):
        a = threading.Thread(target=_run, args=(mine, mine_out)); a.start()
        b = threading.Thread(target=_run, args=(theirs, their_out)); b.start()
        time.sleep(0.4)
        token.cancel("client_disconnected")
        a.join(10)
    assert mine_out["result"] == "interrupted" and mine_out["secs"] < 8
    assert token.cancelled and token.reason == "client_disconnected"
    # the other cursor, same parent database, was not interrupted and still answers
    assert parent.cursor().execute("select 42").fetchone() == (42,)
    assert b.is_alive() or their_out.get("result") == "finished"
    theirs.interrupt()                                               # test cleanup only
    b.join(10)


def test_running_refuses_to_start_after_cancel():
    token = G.CancelToken()
    token.cancel("x")
    with pytest.raises(G.Cancelled):
        with token.running(duckdb.connect(":memory:").cursor()):
            pytest.fail("must not start")


def test_a_deadline_interrupts_the_running_query():
    cur = duckdb.connect(":memory:").cursor()
    token, out = G.CancelToken(), {}
    with token.running(cur, deadline_in=0.3):
        _run(cur, out)
    assert out["result"] == "interrupted" and token.timed_out and not token.cancelled


def test_a_query_that_finishes_before_the_deadline_is_untouched():
    cur = duckdb.connect(":memory:").cursor()
    token = G.CancelToken()
    with token.running(cur, deadline_in=5):
        assert cur.execute("select 1").fetchone() == (1,)
    time.sleep(0.05)
    assert not token.timed_out
