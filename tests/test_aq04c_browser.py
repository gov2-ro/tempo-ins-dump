"""AQ-04C in a real browser: what the Ask page shows when the model's text says nothing of the caveats.

The responses are the REAL ones: a scripted provider calls the real tools on a synthetic corpus, the
real `/api/ask` router and agent build the response, and Playwright hands exactly that JSON to the
page (so the page renders what the server produced, not a hand-written imitation). The model's own
answer mentions no definition, no exclusion and no classification caveat; the warnings list and the
table captions must still carry them, in the page's language, at phone, small-phone and desktop
widths, with no console error and no horizontal page scroll. Skipped without playwright/chromium.
"""
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest

pw = pytest.importorskip("playwright.sync_api")

import test_aq04a_discovery_defaults as t04a
import test_aq05a_city_changes as t05a
from at01_fixtures import make_env
from at02_env import call_resp, scripted
from fix08_helpers import make_client, text_resp
from app import config
from app.services import agent
from test_at01_query import base_corpus, env  # noqa: F401 — the AT-01 query corpus (AGEC: single ages 0-2 only)
from test_at02_browser import Server, WIDTHS, ask, no_sideways_scroll

ROOT = Path(__file__).resolve().parent.parent
PORT = 8171                                  # this step's range is 8171-8175
URL = f"http://127.0.0.1:{PORT}"


@pytest.fixture
def server():
    try:
        socket.create_connection(("127.0.0.1", PORT), timeout=0.2).close()
        pytest.skip(f"port {PORT} already in use")
    except OSError:
        pass
    child_env = {**os.environ, "TEMPO_ASK_ENABLED": "1", "TEMPO_ASK_BYOK_ENABLED": "1", "PYTHONPATH": str(ROOT)}
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


def open_page(server, width, lang):
    """A page at `width` in `lang`; returns (page, close). Console errors are collected."""
    w, h = width
    p = pw.sync_playwright().start()
    try:
        browser = p.chromium.launch()
    except Exception as e:                                          # browser not installed
        p.stop()
        pytest.skip(f"chromium unavailable: {type(e).__name__}")
    ctx = browser.new_context(viewport={"width": w, "height": h})
    ctx.route("**/cdn.jsdelivr.net/**", lambda r: r.fulfill(status=200, body="", content_type="text/javascript"))
    ctx.add_init_script(f"try {{ localStorage.setItem('lens_lang', '{lang}'); }} catch (e) {{}}")
    pg = ctx.new_page()
    pg.problems = []
    pg.on("console", lambda m: pg.problems.append(m.text) if m.type == "error" else None)
    pg.on("pageerror", lambda e: pg.problems.append(str(e)))
    pg.goto(f"{URL}/ask.html", wait_until="domcontentloaded")
    pg.wait_for_selector("#chat-input")

    def close():
        browser.close()
        p.stop()
    return pg, close


@pytest.fixture(autouse=True)
def _ask_on(monkeypatch):
    monkeypatch.setattr(config, "ASK_ENABLED", True)
    monkeypatch.setattr(config, "ASK_BYOK_ENABLED", True)
    monkeypatch.setattr(agent, "RETRY_PAUSE_SECONDS", 0.0)


def real_response(monkeypatch, question, steps):
    """What POST /api/ask returns for `question` when the scripted model makes `steps`."""
    scripted(monkeypatch, steps)
    r = make_client().post("/api/ask", json={"question": question, "provider": "anthropic",
                                             "model": "claude-sonnet-5-5", "api_key": "k-123456"})
    assert r.status_code == 200, r.text
    return r.json()


def render(pg, response, question):
    srv = Server(pg)
    msg = ask(pg, srv, question, response)
    return msg


def warning_texts(msg):
    return msg.locator(".chat-warning-item").all_inner_texts()


@pytest.mark.parametrize("lang", ["ro", "en"])
def test_a_city_change_ranking_keeps_its_caveats_and_is_captioned_as_a_ranking(server, width, monkeypatch, tmp_path, lang):
    make_env(tmp_path, monkeypatch, build=t05a.build_chg)
    q = {"ro": "Care sunt orașele cu cea mai mare scădere între 2015 și 2020?",
         "en": "Which cities lost the most population between 2015 and 2020?"}[lang]
    answer = {"ro": "Cele mai mari scăderi sunt la CITY229, CITY228 și CITY227.",
              "en": "The largest declines are at CITY229, CITY228 and CITY227."}[lang]
    resp = real_response(monkeypatch, q, [
        call_resp("compare_periods", {"dataset": "CHG", "entity_columns": ["REF_AREA", "REF_AREA_2"],
                                      "intervals": [{"from": "2015", "to": "2020"}], "entity_class": "cities",
                                      "top_k": 3}, 0),
        text_resp(answer)])
    assert resp["data"]["ranked"] is True and resp["data"]["truncated"] is True
    pg, close = open_page(server, width, lang)
    try:
        msg = render(pg, resp, q)
        bubble = msg.locator(".chat-bubble").first.inner_text()
        assert "catalog" not in bubble.lower() and "clasa" not in bubble.lower()       # the model said nothing of it
        warnings = " | ".join(warning_texts(msg))
        meta = msg.locator(".chat-data-meta").inner_text()
        footer = msg.locator(".chat-table-truncated").inner_text()
        if lang == "ro":
            assert "nu dovedește statutul istoric de oraș sau limite neschimbate" in warnings
            assert "perechi entitate–interval nu au fost clasate" in warnings
            assert "3 din 233 entități eligibile, în ordine" in meta and "2 excluse" in meta
            assert "2 din afara clasei (comune, totaluri), neclasate" in meta
            assert "nu este un clasament" not in meta and "Previzualizare" not in meta
            assert "clasamentul complet" in footer and "Previzualizare" not in footer
        else:
            assert "does not prove historical city status or unchanged boundaries" in warnings
            assert "entity-interval pair(s) were not ranked" in warnings
            assert "3 of 233 eligible entities, ranked" in meta and "2 excluded" in meta
            assert "2 outside the class (communes, totals), not ranked" in meta
            assert "not a ranking" not in meta and "Preview" not in meta
            assert "the complete ranking" in footer and "Limited preview" not in footer
        assert msg.locator(".chat-table th").count() == 8 and msg.locator(".chat-chart").count() == 0   # 2 key columns + 6
        hrefs = msg.locator(".chat-links a").evaluate_all("els => els.map(e => e.href)")
        assert len(hrefs) >= 2 and all(h.startswith(URL + "/") or h.startswith("https://") for h in hrefs)
        no_sideways_scroll(pg)
        assert pg.problems == []
    finally:
        close()


@pytest.mark.parametrize("lang", ["ro", "en"])
def test_an_assumed_definition_is_listed_first_although_the_model_does_not_say_it(server, width, monkeypatch,
                                                                                  tmp_path, lang):
    t04a.make(tmp_path, monkeypatch)
    q = {"ro": "Câți locuitori are Cluj în 2023?", "en": "How many people live in Cluj in 2023?"}[lang]
    resp = real_response(monkeypatch, q, [
        call_resp("discover_indicators", {"query": "populatia Cluj 2023"}, 0),
        call_resp("query_data", {"dataset": "POP105A_judete_grupe", "group_by": ["REF_AREA", "TIME_PERIOD"],
                                 "filters": {"REF_AREA": ["Cluj"], "TIME_PERIOD": ["2023"]}}, 1),
        text_resp("Cluj avea 710 persoane în 2023 (POP105A_judete_grupe)." if lang == "ro"
                  else "Cluj had 710 people in 2023 (POP105A_judete_grupe).")])
    assert resp["warnings"] and "assumed" in resp["warnings"][0].lower() or "presupus" in resp["warnings"][0].lower()
    pg, close = open_page(server, width, lang)
    try:
        msg = render(pg, resp, q)
        first = msg.locator(".chat-warning-item").first.inner_text()
        assert first.startswith("Definiție presupusă:" if lang == "ro" else "Definition assumed:")
        assert ("rezidentă" if lang == "ro" else "esident") in first
        bubble = msg.locator(".chat-bubble").first.inner_text()
        assert "presupus" not in bubble and "assumed" not in bubble
        assert msg.locator(".chat-table td").nth(2).inner_text() == "710"
        no_sideways_scroll(pg)
        assert pg.problems == []
    finally:
        close()


@pytest.mark.parametrize("lang", ["ro", "en"])
def test_a_partial_scope_is_shown_with_its_table_when_the_model_does_not_say_it(server, width, env, monkeypatch, lang):
    q = {"ro": "Câte persoane sunt în AGEC în 2024?", "en": "How many people are in AGEC in 2024?"}[lang]
    resp = real_response(monkeypatch, q, [
        call_resp("query_data", {"dataset": "AGEC", "group_by": ["TIME_PERIOD"]}, 0),
        text_resp("În 2024: 90 de persoane." if lang == "ro" else "In 2024: 90 people.")])
    pg, close = open_page(server, width, lang)
    try:
        msg = render(pg, resp, q)
        scope = "Vârste 0–2 ani (fără 3 ani și peste)" if lang == "ro" else "Ages 0–2 (3 and over not included)"
        assert msg.locator(".chat-data-scope").inner_text() == scope
        assert msg.locator(".chat-data-meta .agg-badge").inner_text() == ("parțial" if lang == "ro" else "partial")
        warnings = " | ".join(warning_texts(msg))
        assert ("Acest total acoperă doar o parte din domeniu" if lang == "ro"
                else "This total covers only part of the domain") in warnings
        assert "0–2" not in msg.locator(".chat-bubble").first.inner_text()
        no_sideways_scroll(pg)
        assert pg.problems == []
    finally:
        close()


def test_the_ranked_caption_wraps_on_a_small_phone_with_long_warnings(server, width, monkeypatch, tmp_path):
    """A long Romanian warning list and caption must not widen the page at any width."""
    make_env(tmp_path, monkeypatch, build=t05a.build_chg)
    resp = real_response(monkeypatch, "Care sunt orașele cu scădere?", [
        call_resp("compare_periods", {"dataset": "CHG", "entity_columns": ["REF_AREA", "REF_AREA_2"],
                                      "intervals": [{"from": "2010", "to": "2015"}, {"from": "2015", "to": "2020"}],
                                      "entity_class": "cities", "top_k": 5}, 0),
        text_resp("Vezi tabelul.")])
    pg, close = open_page(server, width, "ro")
    try:
        msg = render(pg, resp, "Care sunt orașele cu scădere?")
        assert "perechi entitate–interval eligibile, clasate pe interval" in msg.locator(".chat-data-meta").inner_text()
        assert msg.locator(".chat-warning-item").count() >= 3
        no_sideways_scroll(pg)
        assert pg.evaluate("document.querySelector('.chat-warnings').scrollWidth <= document.querySelector('.chat-warnings').clientWidth + 1")
        assert pg.problems == []
    finally:
        close()
