"""AQ-06A in a real browser: the Ask page on one origin, its API on another.

The API is the real Ask router with the provider mocked (tests/fix08_browser_app.py) and the
app's own CORS, listing only the site origin. Two plain static servers play the site and a
foreign site; both serve a copy of app/static whose js/config.js names the API origin, as a
static build with --api-origin writes it. Skipped when playwright/chromium is unavailable.
Fake key only.

The foreign-site test routes no request: with interception on, Playwright answers CORS
preflights itself and the browser sends the POST (it then hides the answer). Without it, the
browser's own preflight is refused and the POST never reaches the API, which the test checks.
"""
import json
import os
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest

pw = pytest.importorskip("playwright.sync_api")

from test_at02_browser import result, table  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
API_PORT, SITE_PORT, FOREIGN_PORT = 8096, 8095, 8094
API = f"http://127.0.0.1:{API_PORT}"
SITE = f"http://127.0.0.1:{SITE_PORT}"
FOREIGN = f"http://127.0.0.1:{FOREIGN_PORT}"
KEY = "sk-ant-CROSSORIGINSENTINEL0123456789"
WIDTHS = [(320, 640), (390, 800), (1280, 900)]


def _wait(port, proc):
    for _ in range(60):
        try:
            socket.create_connection(("127.0.0.1", port), timeout=0.2).close()
            return proc
        except OSError:
            time.sleep(0.2)
    proc.kill()
    pytest.skip(f"could not start a test server on {port}")


def site_copy(root, api_origin):
    shutil.copytree(ROOT / "app" / "static", root)
    cfg = {"mode": "static", "generation": "g-test", "api_origin": api_origin}
    (root / "js" / "config.js").write_text(f"window.TEMPO_CONFIG = {json.dumps(cfg)};\n")
    return root


@pytest.fixture(scope="module")
def servers(tmp_path_factory):
    for port in (API_PORT, SITE_PORT, FOREIGN_PORT):
        try:
            socket.create_connection(("127.0.0.1", port), timeout=0.2).close()
            pytest.skip(f"port {port} already in use")
        except OSError:
            pass
    env = {**os.environ, "TEMPO_ASK_ENABLED": "1", "TEMPO_ASK_BYOK_ENABLED": "1", "TEMPO_ASK_DEBUG": "1",
           "TEMPO_CORS_ORIGINS": SITE, "PYTHONPATH": str(ROOT)}
    procs = [_wait(API_PORT, subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "fix08_browser_app:app", "--app-dir", str(ROOT / "tests"),
         "--port", str(API_PORT), "--log-level", "warning"],
        cwd=ROOT, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))]
    site = site_copy(tmp_path_factory.mktemp("aq06a") / "site", API)
    for port in (SITE_PORT, FOREIGN_PORT):
        procs.append(_wait(port, subprocess.Popen(
            [sys.executable, "-m", "http.server", str(port), "--bind", "127.0.0.1", "--directory", str(site)],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)))
    yield
    for p in procs:
        p.terminate()
        p.wait(5)


def open_page(p, origin, size=(1280, 900), api_origin=None, query="", route=True):
    """`route=False`: no interception at all (the CDN is unreachable instead, so the page does
    not depend on the network); `api_origin` overrides the site's config.js."""
    try:
        browser = p.chromium.launch(args=[] if route else ["--host-resolver-rules=MAP cdn.jsdelivr.net 127.0.0.1:9"])
    except Exception as e:  # browser not installed
        pytest.skip(f"chromium unavailable: {type(e).__name__}")
    ctx = browser.new_context(viewport={"width": size[0], "height": size[1]})
    if route:
        ctx.route("**/cdn.jsdelivr.net/**", lambda r: r.fulfill(status=200, body="", content_type="text/javascript"))
    if api_origin:
        cfg = {"mode": "static", "generation": "g-test", "api_origin": api_origin}
        ctx.route(f"{origin}/js/config.js*", lambda r: r.fulfill(
            status=200, content_type="text/javascript", body=f"window.TEMPO_CONFIG = {json.dumps(cfg)};"))
    pg = ctx.new_page()
    pg.requests, pg.problems = [], []
    pg.on("request", lambda r: pg.requests.append((r.method, r.url, r.post_data or "")))
    pg.on("console", lambda m: pg.problems.append(m.text) if m.type in ("error", "warning") else None)
    pg.on("pageerror", lambda e: pg.problems.append(str(e)))
    pg.goto(f"{origin}/ask.html{query}", wait_until="domcontentloaded")
    pg.wait_for_selector("#chat-input")
    return browser, pg


def calls(pg):
    return pg.request.get(f"{API}/__last").json().get("calls", 0)


def submit(pg, question):
    n = pg.locator(".chat-msg--assistant:not(.chat-msg--loading)").count()
    pg.fill("#chat-input", question)
    pg.click("#chat-send")
    pg.wait_for_function("n => document.querySelectorAll('.chat-msg--assistant:not(.chat-msg--loading)').length > n", arg=n)
    return pg.locator(".chat-msg--assistant:not(.chat-msg--loading)").last


def set_key(pg):
    pg.click("#settings-toggle")
    pg.wait_for_selector("#ask-settings:not(.hidden)")
    pg.fill("#s-key", KEY)
    pg.click("#s-save")


@pytest.mark.parametrize("size", WIDTHS, ids=lambda w: f"{w[0]}px")
def test_config_submit_and_follow_up_cross_origins_and_the_key_goes_only_to_the_api(servers, size):
    with pw.sync_playwright() as p:
        # a query parameter naming another host is not configuration
        browser, pg = open_page(p, SITE, size, query=f"?api_origin={FOREIGN}")
        pg.wait_for_function("document.getElementById('s-provider').options.length > 0")  # config from the API
        set_key(pg)
        before = calls(pg)
        first = submit(pg, "Câți locuitori are Cluj?")
        assert "Răspuns de test" in first.inner_text() and first.get_attribute("data-outcome") != "interrupted"
        second = submit(pg, "Și în 2020?")
        assert "Răspuns de test" in second.inner_text()
        assert calls(pg) >= before + 2 and pg.request.get(f"{API}/__last").json()["got_key"] is True

        posts = [(u, b) for m, u, b in pg.requests if m == "POST"]
        assert [u for u, _ in posts] == [f"{API}/api/ask"] * 2
        follow = json.loads(posts[1][1])
        assert [h["role"] for h in follow["history"]] == ["user", "assistant"]   # the follow-up carries the thread
        with_key = [u for _, u, b in pg.requests if KEY in b or KEY in u]
        assert with_key == [f"{API}/api/ask"] * 2                               # the key went nowhere else
        assert not [u for _, u, _ in pg.requests if u.startswith((f"{SITE}/api", FOREIGN))]
        assert KEY not in pg.content()
        assert pg.evaluate("document.documentElement.scrollWidth <= window.innerWidth + 1"), "horizontal scroll"
        assert pg.problems == []
        browser.close()


def test_the_debug_stream_crosses_origins(servers):
    with pw.sync_playwright() as p:
        browser, pg = open_page(p, SITE, query="?debug=1")
        pg.wait_for_function("!document.getElementById('s-debug-row').classList.contains('hidden')")  # API allows debug
        set_key(pg)
        msg = submit(pg, "Câți locuitori are Cluj?")
        assert "Răspuns de test" in msg.inner_text() and msg.locator(".chat-debug").count() == 1
        assert [u for m, u, _ in pg.requests if m == "POST"] == [f"{API}/api/ask/stream"]
        assert pg.problems == []
        browser.close()


def test_relative_evidence_links_open_on_the_api_and_pages_on_the_site(servers):
    links = [{"kind": "csv", "url": "/api/datasets/POPC/data?x=1", "description": "CSV"},
             {"kind": "evidence", "url": "/api/entity-rankings?request=%7B%7D&expected_generation=g", "description": "E"},
             {"kind": "dataset", "url": "/dataset-v2.html?code=POPC", "description": "D"},
             {"kind": "share", "url": "https://elsewhere.example/x", "description": "S"}]
    crafted = result(answer="Cluj avea 1010 persoane în 2021 (POPC).",
                     data=table(["REF_AREA", "TIME_PERIOD", "OBS_VALUE"], [["Cluj", "2021", 1010.0]], links=links))

    def answer(route):
        if route.request.method != "POST":
            return route.continue_()
        real = route.fetch()                                                  # the real cross-origin response,
        route.fulfill(response=real, body=json.dumps(crafted))                # its CORS headers, a crafted body

    with pw.sync_playwright() as p:
        browser, pg = open_page(p, SITE)
        pg.wait_for_function("document.getElementById('s-provider').options.length > 0")
        set_key(pg)
        pg.route(f"{API}/api/ask", answer)
        msg = submit(pg, "Câți locuitori are Cluj?")
        hrefs = msg.locator(".chat-links a").evaluate_all("els => els.map(e => e.href)")
        assert hrefs == [f"{API}/api/datasets/POPC/data?x=1",
                         f"{API}/api/entity-rankings?request=%7B%7D&expected_generation=g",
                         f"{SITE}/dataset-v2.html?code=POPC", "https://elsewhere.example/x"]
        assert pg.problems == []
        browser.close()


def test_a_site_the_api_does_not_list_is_refused_and_says_so_without_falling_back(servers):
    with pw.sync_playwright() as p:
        browser, pg = open_page(p, FOREIGN, route=False)
        pg.wait_for_selector("#ask-unavailable:not(.hidden)")
        assert "nu poate fi contactat" in pg.inner_text("#ask-unavailable")
        assert pg.locator("#ask-unavailable button").inner_text() == "Încearcă din nou"
        set_key(pg)
        before = calls(pg)
        msg = submit(pg, "Câți locuitori are Cluj?")
        assert msg.get_attribute("data-outcome") == "interrupted"
        assert "nu a putut fi contactat" in msg.inner_text() and KEY not in msg.inner_text()
        assert pg.input_value("#chat-input") == "Câți locuitori are Cluj?"     # kept for the retry
        assert msg.locator(".chat-next button").first.inner_text() == "Încearcă din nou"
        assert calls(pg) == before                                            # the POST never ran
        assert not [u for _, u, _ in pg.requests if u.startswith(f"{FOREIGN}/api")]  # no same-origin fallback
        # only the browser's own reports of the refused requests and of the unreachable CDN
        assert all("CORS" in t or "Failed to load" in t or "ERR_" in t for t in pg.problems), pg.problems
        browser.close()


def test_a_malformed_api_origin_switches_ask_off(servers):
    with pw.sync_playwright() as p:
        browser, pg = open_page(p, SITE, api_origin="javascript:alert(1)")
        pg.wait_for_selector("#ask-unavailable:not(.hidden)")
        assert pg.is_disabled("#chat-input") and pg.is_disabled("#chat-send")
        assert not [u for _, u, _ in pg.requests if "/api/" in u]
        browser.close()
