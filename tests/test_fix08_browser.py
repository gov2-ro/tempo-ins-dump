"""FIX-08 item 5/6 in a real browser (Playwright, headless Chromium).

Serves the real Ask page + router on port 8098 with the provider mocked. Skipped
when playwright/chromium is unavailable. Fake key only.
"""
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest

pw = pytest.importorskip("playwright.sync_api")

ROOT = Path(__file__).resolve().parent.parent
PORT = 8098
URL = f"http://127.0.0.1:{PORT}"
KEY = "sk-ant-BROWSERSENTINEL0123456789"


def _serve(env_extra):
    env = {**os.environ, "TEMPO_ASK_ENABLED": "1", "PYTHONPATH": str(ROOT), **env_extra}
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "fix08_browser_app:app", "--app-dir", str(ROOT / "tests"),
         "--port", str(PORT), "--log-level", "warning"],
        cwd=ROOT, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for _ in range(60):
        try:
            socket.create_connection(("127.0.0.1", PORT), timeout=0.2).close()
            return proc
        except OSError:
            time.sleep(0.2)
    proc.kill()
    pytest.skip(f"could not start test server on {PORT}")


@pytest.fixture
def server():
    try:
        socket.create_connection(("127.0.0.1", PORT), timeout=0.2).close()
        pytest.skip(f"port {PORT} already in use")
    except OSError:
        pass
    proc = _serve({})
    yield
    proc.terminate()
    proc.wait(5)


@pytest.fixture
def page(server):
    with pw.sync_playwright() as p:
        try:
            browser = p.chromium.launch()
        except Exception as e:  # browser not installed
            pytest.skip(f"chromium unavailable: {type(e).__name__}")
        ctx = browser.new_context()
        # the page pulls echarts from a CDN; the test must not depend on the network
        ctx.route("**/cdn.jsdelivr.net/**", lambda r: r.fulfill(status=200, body="", content_type="text/javascript"))
        pg = ctx.new_page()
        pg.goto(f"{URL}/ask.html", wait_until="domcontentloaded")
        pg.wait_for_selector("#settings-toggle")
        yield pg
        browser.close()


def local_ask_items(pg):
    return pg.evaluate("Object.keys(localStorage).filter(k => k.startsWith('ask_'))")


def session_ask_items(pg):
    return pg.evaluate("Object.keys(sessionStorage).filter(k => k.startsWith('ask_'))")


def open_settings(pg):
    pg.click("#settings-toggle")
    pg.wait_for_selector("#ask-settings:not(.hidden)")


def test_disclosure_visible_and_remember_off_by_default(page):
    open_settings(page)
    assert not page.is_checked("#s-remember")
    transit = page.inner_text("#s-transit-note")
    assert "sent to this server" in transit and "pass through" in transit
    assert "browser only" not in page.content()
    assert "unencrypted" in page.inner_text("#s-remember-note")


def test_default_submission_does_not_touch_localstorage(page):
    open_settings(page)
    page.fill("#s-key", KEY)
    page.click("#s-save")
    # key is not left in the DOM (value cleared) and not in localStorage
    assert page.input_value("#s-key") == ""
    assert KEY not in page.content()
    assert local_ask_items(page) == []
    assert "ask_api_key" in session_ask_items(page)

    page.fill("#chat-input", "Care este populația României?")
    with page.expect_response("**/api/ask") as resp_info:
        page.press("#chat-input", "Enter")
    assert resp_info.value.status == 200
    page.wait_for_selector(".chat-msg--assistant .chat-bubble")
    assert "Răspuns de test" in page.inner_text("#chat-messages")
    assert local_ask_items(page) == []
    assert page.request.get(f"{URL}/__last").json()["got_key"] is True  # BYOK key reached the (mock) provider
    assert KEY not in page.content()


def test_opt_in_persists_across_reload_and_clear_removes(page):
    open_settings(page)
    page.fill("#s-key", KEY)
    page.check("#s-remember")
    page.click("#s-save")
    assert "ask_api_key" in local_ask_items(page)
    assert session_ask_items(page) == []

    page.reload(wait_until="domcontentloaded")
    page.wait_for_selector("#settings-toggle")
    open_settings(page)
    assert page.is_checked("#s-remember")
    assert "saved on this device" in page.inner_text("#s-key-status")
    assert KEY not in page.content()

    page.click("#s-clear")
    assert local_ask_items(page) == [] and session_ask_items(page) == []
    page.reload(wait_until="domcontentloaded")
    open_settings(page)
    assert "No key set" in page.inner_text("#s-key-status")


def test_legacy_localstorage_key_is_visible_and_clearable(page):
    page.evaluate(f"localStorage.setItem('ask_api_key', '{KEY}');"
                  "localStorage.setItem('ask_provider','openai');localStorage.setItem('ask_model','gpt-4o')")
    page.reload(wait_until="domcontentloaded")
    page.wait_for_selector("#settings-toggle")
    open_settings(page)
    assert "saved on this device" in page.inner_text("#s-key-status")
    assert page.is_checked("#s-remember")
    assert page.input_value("#s-key") == "" and KEY not in page.content()
    page.click("#s-clear")
    assert local_ask_items(page) == []


def test_logging_banner_hidden_by_default(page):
    page.wait_for_function("fetch('/api/ask/config').then(r => r.ok)")
    assert not page.is_visible("#ask-logging-banner")


def test_logging_banner_shown_when_enabled():
    try:
        socket.create_connection(("127.0.0.1", PORT), timeout=0.2).close()
        pytest.skip(f"port {PORT} already in use")
    except OSError:
        pass
    proc = _serve({"TEMPO_ASK_LOG_CHATS": "true"})
    try:
        with pw.sync_playwright() as p:
            try:
                browser = p.chromium.launch()
            except Exception as e:
                pytest.skip(f"chromium unavailable: {type(e).__name__}")
            ctx = browser.new_context()
            ctx.route("**/cdn.jsdelivr.net/**", lambda r: r.fulfill(status=200, body="", content_type="text/javascript"))
            pg = ctx.new_page()
            pg.goto(f"{URL}/ask.html", wait_until="domcontentloaded")
            pg.wait_for_selector("#ask-logging-banner:not(.hidden)", timeout=5000)
            assert "logging is ON" in pg.inner_text("#ask-logging-banner")
            browser.close()
    finally:
        proc.terminate()
        proc.wait(5)
