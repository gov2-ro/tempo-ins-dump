"""The Ask page and the site's language, in a real browser (Chromium via Playwright).

The page is the real one served by the real static files. Its `/api/ask` calls are answered by the REAL router
and agent in this process (a scripted provider behind them, the real tools on the AT-01 synthetic corpus): the
route handler hands the page's own request body to the router and the router's own response back to the page.
So what is asserted is the whole chain: the language the page sends, the language the server resolves, and what
the page renders from it.

An ambiguous question ("AGEC 2024": no Romanian letter, no hint word) takes the site's language; a question that
shows its own language keeps it. Its captions and badges follow the answer's language, the page's own errors
follow the site. 320, 390 and 1280 px, no console error, no horizontal scroll. Skipped without playwright/chromium.
"""
import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest

pw = pytest.importorskip("playwright.sync_api")

from at02_env import call_resp, scripted
from fix08_helpers import make_client, text_resp
from test_at01_query import base_corpus, env  # noqa: F401 — the AT-01 query corpus (AGEC: single ages 0-2 only)
from test_at02_browser import WIDTHS, ask, no_sideways_scroll
from app import config
from app.services import agent

ROOT = Path(__file__).resolve().parent.parent
PORT = 8191                                  # this step's range is 8191-8195
URL = f"http://127.0.0.1:{PORT}"
KEY = {"provider": "anthropic", "model": "claude-sonnet-5-5", "api_key": "k-123456"}

AMBIGUOUS = "AGEC 2024"
EN_ONLY = "How many people are in AGEC in 2024?"
RO_ONLY = "Câte persoane sunt în AGEC în 2024?"
TEXT = {"ro": {"warning": "Acest total acoperă doar o parte din domeniu", "scope": "Vârste 0–2 ani (fără 3 ani și peste)",
               "badge": "parțial", "rows": "rânduri"},
        "en": {"warning": "This total covers only part of the domain", "scope": "Ages 0–2 (3 and over not included)",
               "badge": "partial", "rows": "rows"}}


@pytest.fixture
def server():
    try:
        socket.create_connection(("127.0.0.1", PORT), timeout=0.2).close()
        pytest.skip(f"port {PORT} already in use")
    except OSError:
        pass
    child_env = {k: v for k, v in os.environ.items() if not k.endswith("_API_KEY")}
    child_env.update(TEMPO_ASK_ENABLED="1", TEMPO_ASK_BYOK_ENABLED="1", PYTHONPATH=str(ROOT))
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "fix08_browser_app:app", "--app-dir", str(ROOT / "tests"),
         "--port", str(PORT), "--log-level", "warning"],
        cwd=ROOT, env=child_env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for _ in range(60):
        try:
            socket.create_connection(("127.0.0.1", PORT), timeout=0.2).close()
            break
        except OSError:
            time.sleep(0.2)
    else:
        proc.kill()
        pytest.skip(f"could not start the test server on {PORT}")
    yield
    proc.terminate()
    proc.wait(5)


@pytest.fixture(params=WIDTHS, ids=lambda w: f"{w[0]}px")
def width(request):
    return request.param


@pytest.fixture(autouse=True)
def _ask_on(monkeypatch):
    monkeypatch.setattr(config, "ASK_ENABLED", True)
    monkeypatch.setattr(config, "ASK_BYOK_ENABLED", True)
    monkeypatch.setattr(agent, "RETRY_PAUSE_SECONDS", 0.0)


def model_script(monkeypatch):
    """The scripted provider: one query of AGEC, then a short answer. It says nothing of the caveats."""
    def respond(n, messages, kw):
        last = messages[-1].get("content")
        done = isinstance(last, list) and any(b.get("type") == "tool_result" for b in last)
        if done or kw.get("tool_choice") == "none":
            return text_resp("2024: 90 (AGEC).")
        return call_resp("query_data", {"dataset": "AGEC", "group_by": ["TIME_PERIOD"]}, n)
    return scripted(monkeypatch, respond)


class Bridge:
    """Answers the page's `/api/ask` and `/api/ask/stream` calls with the real router in this process.
    `requests` keeps what the PAGE sent (the key is added only on the way into the router)."""

    def __init__(self, page, stream_config=False):
        self.client = make_client()
        self.requests, self.fail_next = [], None
        page.route("**/api/ask", self.ask)
        page.route("**/api/ask/stream", self.stream)
        if stream_config:                      # the debug switch the page reads from /api/ask/config
            page.route("**/api/ask/config", lambda r: r.fulfill(
                status=200, content_type="application/json", body=self.client.get("/api/ask/config").text))

    def ask(self, route):
        body = json.loads(route.request.post_data or "{}")
        self.requests.append(body)
        if self.fail_next:
            status, self.fail_next = self.fail_next, None
            return route.fulfill(status=status, content_type="application/json",
                                 body=json.dumps({"detail": "Server busy"}))
        r = self.client.post("/api/ask", json={**body, **KEY})
        route.fulfill(status=r.status_code, content_type="application/json", body=r.text)

    def stream(self, route):
        body = json.loads(route.request.post_data or "{}")
        self.requests.append(body)
        r = self.client.post("/api/ask/stream", json={**body, **KEY})
        route.fulfill(status=r.status_code, content_type="application/x-ndjson", body=r.text)


def open_page(server, width, lang, query=""):
    """Chromium at `width` with the site language `lang` in localStorage (as the switcher leaves it)."""
    w, h = width
    p = pw.sync_playwright().start()
    try:
        browser = p.chromium.launch()
    except Exception as e:                                          # browser not installed
        p.stop()
        pytest.skip(f"chromium unavailable: {type(e).__name__}")
    ctx = browser.new_context(viewport={"width": w, "height": h})
    ctx.route("**/cdn.jsdelivr.net/**", lambda r: r.fulfill(status=200, body="", content_type="text/javascript"))
    pg = ctx.new_page()
    pg.problems = []
    pg.on("console", lambda m: pg.problems.append(m.text) if m.type == "error" else None)
    pg.on("pageerror", lambda e: pg.problems.append(str(e)))
    pg.goto(f"{URL}/ask.html", wait_until="domcontentloaded")
    pg.evaluate(f"localStorage.setItem('lens_lang', '{lang}')")
    pg.goto(f"{URL}/ask.html{query}", wait_until="domcontentloaded")
    pg.wait_for_selector("#chat-input")

    def close():
        browser.close()
        p.stop()
    return pg, close


def set_site_lang(pg, lang):
    """What the language switcher does to storage; no reload (the next submit must read it afresh)."""
    pg.evaluate(f"localStorage.setItem('lens_lang', '{lang}')")


def shown(msg):
    """What a turn shows that the tool results (not the model) wrote or the page captions."""
    return {"warnings": " | ".join(msg.locator(".chat-warning-item").all_inner_texts()),
            "scope": msg.locator(".chat-data-scope").inner_text(),
            "badge": msg.locator(".chat-data-meta .agg-badge").inner_text(),
            "meta": msg.locator(".chat-data-meta").inner_text()}


def assert_turn_in(msg, lang):
    t, got = TEXT[lang], shown(msg)
    assert t["warning"] in got["warnings"], got
    assert got["scope"] == t["scope"] and got["badge"] == t["badge"], got
    assert t["rows"] in got["meta"], got
    other = TEXT["en" if lang == "ro" else "ro"]
    assert other["warning"] not in got["warnings"] and other["badge"] != got["badge"], got


def test_an_ambiguous_question_takes_the_sites_language_and_follows_it_when_it_changes(server, width, env, monkeypatch):
    calls = model_script(monkeypatch)
    pg, close = open_page(server, width, "en")
    try:
        bridge = Bridge(pg)
        # site shown in English -> English warnings, scope and captions, for a question that shows no language
        ask(pg, None, AMBIGUOUS)
        first = pg.locator(".chat-msg--assistant:not(.chat-msg--loading)").first
        assert bridge.requests[0]["lang"] == "en"
        assert_turn_in(first, "en")
        assert "the user reads the site in English" in calls[0].kw["system"]      # the model is told, too
        no_sideways_scroll(pg)

        # a follow-up is a new submit: it sends the language again, history and all
        again = ask(pg, None, AMBIGUOUS)
        assert bridge.requests[1]["lang"] == "en" and len(bridge.requests[1]["history"]) == 2
        assert_turn_in(again, "en")

        # the visitor switches the site to Romanian (the switcher writes lens_lang) and asks again
        set_site_lang(pg, "ro")
        ro = ask(pg, None, AMBIGUOUS)
        assert bridge.requests[2]["lang"] == "ro"
        assert_turn_in(ro, "ro")
        assert "the user reads the site in Romanian" in calls[-2].kw["system"]
        assert_turn_in(first, "en")                                              # earlier answers are not rewritten
        no_sideways_scroll(pg)

        # ... and back
        set_site_lang(pg, "en")
        assert_turn_in(ask(pg, None, AMBIGUOUS), "en")
        assert [r["lang"] for r in bridge.requests] == ["en", "en", "ro", "en"]
        assert pg.problems == []
    finally:
        close()


def test_the_url_parameter_beats_storage_and_both_beat_the_default(server, width, env, monkeypatch):
    """The switcher puts ?lang= in the URL and lens_lang in storage; a shared link may carry only the parameter."""
    model_script(monkeypatch)
    for query, stored, sent, lang in (("?lang=en", "ro", "en", "en"),       # the parameter wins over storage
                                      ("?lang=ro", "en", "ro", "ro"),
                                      ("", "en", "en", "en"),               # storage alone
                                      ("?lang=fr", "en", "ro", "ro")):      # an unknown parameter reads as the default, like site-chrome
        pg, close = open_page(server, width, stored, query)
        try:
            bridge = Bridge(pg)
            msg = ask(pg, None, AMBIGUOUS)
            assert bridge.requests[0]["lang"] == sent, (query, stored)
            assert_turn_in(msg, lang)
            assert pg.problems == []
        finally:
            close()


def test_nothing_stored_means_romanian(server, width, env, monkeypatch):
    model_script(monkeypatch)
    pg, close = open_page(server, width, "ro")
    try:
        pg.evaluate("localStorage.removeItem('lens_lang')")
        bridge = Bridge(pg)
        msg = ask(pg, None, AMBIGUOUS)
        assert bridge.requests[0]["lang"] == "ro"
        assert_turn_in(msg, "ro")
    finally:
        close()


def test_a_question_that_shows_its_language_keeps_it_and_the_captions_follow_the_answer(server, width, env, monkeypatch):
    """English words on a Romanian site: the answer, warnings, scope and the page's captions for it are English;
    the page's own error text stays in the site's language."""
    model_script(monkeypatch)
    pg, close = open_page(server, width, "ro")
    try:
        bridge = Bridge(pg)
        en = ask(pg, None, EN_ONLY)
        assert bridge.requests[0]["lang"] == "ro"                  # the site's language is sent, the question decides
        assert_turn_in(en, "en")
        bridge.fail_next = 503                                     # a failure is the page's own text: the site's language
        failed = ask(pg, None, AMBIGUOUS)
        assert "Caută direct în date" in failed.inner_text() and "Search the data directly" not in failed.inner_text()

        set_site_lang(pg, "en")
        ro = ask(pg, None, RO_ONLY)
        assert bridge.requests[-1]["lang"] == "en"
        assert_turn_in(ro, "ro")
        bridge.fail_next = 503
        failed = ask(pg, None, AMBIGUOUS)
        assert "Search the data directly" in failed.inner_text()
        no_sideways_scroll(pg)
        assert [m for m in pg.problems if "503" not in m] == []    # the two forced failures log a network error, nothing else
    finally:
        close()


def test_the_streaming_debug_path_sends_the_language_and_shows_where_it_came_from(server, width, env, monkeypatch):
    monkeypatch.setattr(config, "ASK_DEBUG", True)
    model_script(monkeypatch)
    pg, close = open_page(server, width, "en")
    try:
        pg.evaluate("localStorage.setItem('ask_debug', '1')")
        bridge = Bridge(pg, stream_config=True)
        pg.reload(wait_until="domcontentloaded")
        pg.wait_for_selector("#chat-input")
        pg.wait_for_function("document.getElementById('s-debug-row') && !document.getElementById('s-debug-row').classList.contains('hidden')")
        msg = ask(pg, None, AMBIGUOUS)
        assert bridge.requests[0]["lang"] == "en"                  # the stream request, not /api/ask
        assert_turn_in(msg, "en")
        steps = msg.locator(".chat-debug pre").first.text_content()      # a closed <details>: not visible text
        assert "start" in steps and "en (site)" in steps
        set_site_lang(pg, "ro")
        ro = ask(pg, None, AMBIGUOUS)
        assert bridge.requests[1]["lang"] == "ro"
        assert_turn_in(ro, "ro")
        assert "ro (site)" in ro.locator(".chat-debug pre").first.text_content()
        no_sideways_scroll(pg)
        assert pg.problems == []
    finally:
        close()
