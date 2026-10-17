"""AT-02 in a real browser: the Ask page renders every terminal outcome, tables with links,
follow-up context and reset, at phone, small-phone and desktop widths.

The page and router are the real ones (tests/fix08_browser_app.py, port 8098); `/api/ask` is
answered by Playwright with crafted responses of the server's exact shape, so each state is
exercised deterministically. Skipped when playwright/chromium is unavailable.
"""
import json

import pytest

from test_fix08_browser import pw, server, URL  # noqa: F401 — the server fixture

WIDTHS = [(320, 640), (390, 800), (1280, 900)]


@pytest.fixture(params=WIDTHS, ids=lambda w: f"{w[0]}px")
def page(server, request):  # noqa: F811
    w, h = request.param
    with pw.sync_playwright() as p:
        try:
            browser = p.chromium.launch()
        except Exception as e:  # browser not installed
            pytest.skip(f"chromium unavailable: {type(e).__name__}")
        ctx = browser.new_context(viewport={"width": w, "height": h})
        ctx.route("**/cdn.jsdelivr.net/**", lambda r: r.fulfill(status=200, body="", content_type="text/javascript"))
        pg = ctx.new_page()
        pg.problems = []
        pg.on("console", lambda m: pg.problems.append(m.text) if m.type == "error" else None)
        pg.on("pageerror", lambda e: pg.problems.append(str(e)))
        pg.goto(f"{URL}/ask.html", wait_until="domcontentloaded")
        pg.wait_for_selector("#chat-input")
        yield pg
        browser.close()


def result(**kw):
    base = {"answer": "Răspuns.", "citations": [], "tool_trace": [], "data": None, "chart_spec": None,
            "warnings": [], "verification": {"status": "no_values", "uncited_numbers": [], "claims": [],
                                             "claim_summary": {"matched": 0, "unverified": 0}},
            "stop_reason": "end_turn", "outcome": "answered", "reason": None, "context": [],
            "budget": {"iterations": 2, "max_iterations": 8, "tools": 1, "max_tools": 12,
                       "elapsed_s": 1.2, "max_seconds": 90}}
    base.update(kw)
    return base


def table(columns, rows, **kw):
    return {"matrix_code": "POPC", "columns": columns, "rows": rows, "row_count": len(rows),
            "status": "ok", "scope": {"description": "Domeniu complet", "domain_complete": True},
            "links": [], "warnings": [], **kw}


class Server:
    """Plays the `/api/ask` endpoint: queued responses in order, requests recorded."""

    def __init__(self, page):
        self.requests, self.queue = [], []
        page.route("**/api/ask", self.handle)

    def handle(self, route):
        self.requests.append(json.loads(route.request.post_data or "{}"))
        item = self.queue.pop(0)
        if callable(item):
            return item(route)
        status, body = item if isinstance(item, tuple) else (200, item)
        route.fulfill(status=status, content_type="application/json", body=json.dumps(body))


def ask(page, srv, question, response=None):
    if response is not None:
        srv.queue.append(response)
    n = page.locator(".chat-msg--assistant:not(.chat-msg--loading)").count()
    page.fill("#chat-input", question)
    page.click("#chat-send")
    page.wait_for_function("n => document.querySelectorAll('.chat-msg--assistant:not(.chat-msg--loading)').length > n", arg=n)
    page.wait_for_selector("#chat-loading", state="detached")
    return page.locator(".chat-msg--assistant:not(.chat-msg--loading)").last


def no_sideways_scroll(page):
    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth + 1"), "horizontal page scroll"


def test_an_answered_turn_shows_the_table_with_its_links_and_citation(page):
    srv = Server(page)
    links = [{"kind": "csv", "url": "/api/datasets/POPC/data?x=1", "description": "CSV", "generation_mode": "live_rerun"},
             {"kind": "evidence", "url": "https://evil.example/x", "description": "Evidence"},
             {"kind": "live_selection", "url": "javascript:alert(1)", "description": "x"}]
    msg = ask(page, srv, "Câți locuitori are Cluj?", result(
        answer="Cluj avea 1010 persoane în 2021 (POPC).",
        citations=[{"matrix_code": "POPC", "matrix_name": "Populație pe județe", "queries": [
            {"status": "ok", "outcome": "valid_total", "approximation": False}]}],
        data=table(["REF_AREA", "TIME_PERIOD", "OBS_VALUE"], [["Cluj", "2021", 1010.0]], links=links)))
    assert msg.get_attribute("data-outcome") == "answered"
    assert msg.locator(".chat-outcome").count() == 0
    assert msg.locator(".chat-table td").nth(2).inner_text() == "1010"
    hrefs = msg.locator(".chat-links a").evaluate_all("els => els.map(e => e.getAttribute('href'))")
    assert any(h.endswith("/api/datasets/POPC/data?x=1") for h in hrefs) and "https://evil.example/x" in hrefs
    assert len(hrefs) == 2                                                  # javascript: never becomes a link
    assert msg.locator(".chat-citation").inner_text().startswith("↗ POPC")
    assert page.locator(".chat-debug").count() == 0                         # debug is off
    no_sideways_scroll(page)
    assert page.problems == []


def test_a_clarification_is_labelled_as_one(page):
    srv = Server(page)
    msg = ask(page, srv, "Cât este șomajul?", result(
        answer="Vă referiți la șomajul înregistrat sau la cel ILO?", outcome="clarification",
        reason="ambiguous_definition"))
    assert msg.get_attribute("data-outcome") == "clarification"
    assert "Precizare necesară" in msg.locator(".chat-outcome--clarification").inner_text()
    no_sideways_scroll(page)


def test_a_partial_turn_says_why_and_shows_what_part_it_covers(page):
    srv = Server(page)
    msg = ask(page, srv, "Populația României?", result(
        answer="Cifrele de mai jos acoperă doar o parte.", outcome="partial", reason="tools", stop_reason="tools",
        warnings=["Reached the tool-call limit before the exploration finished; the answer is partial."],
        data=table(["TIME_PERIOD", "OBS_VALUE"], [["2026", 21179764.0]], status="partial",
                   scope={"description": "Vârste 0–84 ani (85 și peste nu sunt incluse)", "domain_complete": False})))
    banner = msg.locator(".chat-outcome--partial").inner_text()
    assert "Răspuns parțial" in banner and "limita de apeluri" in banner
    assert "85" in msg.locator(".chat-data-scope").inner_text()
    assert msg.locator(".chat-data-meta .agg-badge").inner_text() == "parțial"
    assert msg.locator(".chat-warning-item").count() == 1
    no_sideways_scroll(page)


def test_a_refusal_and_a_failure_are_not_dressed_as_answers(page):
    srv = Server(page)
    refused = ask(page, srv, "Totalul populației pe vârste?", result(
        answer="Nu există un total sigur.", outcome="refused", reason="overlapping_levels"))
    assert "Nu se poate calcula în siguranță" in refused.locator(".chat-outcome--refused").inner_text()
    assert "se suprapun" in refused.locator(".chat-outcome--refused").inner_text()
    failed = ask(page, srv, "Încă o dată?", result(
        answer="Modelul nu a returnat niciun răspuns.", outcome="failed", reason="empty_output",
        stop_reason="empty_output"))
    assert "Răspunsul nu a putut fi generat" in failed.locator(".chat-outcome--failed").inner_text()
    assert failed.get_attribute("data-outcome") == "failed"
    no_sideways_scroll(page)


def test_a_change_ranking_and_a_recipe_are_plain_tables_without_a_chart(page):
    srv = Server(page)
    change = ask(page, srv, "Ce județ a scăzut cel mai mult?", result(
        answer="B, cu 50.", data=table(
            ["REF_AREA", "INTERVAL", "FROM_VALUE", "TO_VALUE", "ABSOLUTE", "PERCENT", "RANK"],
            [["B", "1992→2002", 200.0, 150.0, -50.0, -25.0, 1]], tool="compare_periods", status="partial",
            matrix_code="COUNTX")))
    assert change.locator(".chat-table th").count() == 7 and change.locator(".chat-chart").count() == 0
    recipe = ask(page, srv, "Intensitatea turistică 2024?", result(
        answer="Alfa: 2.", data=table(["LABEL", "VALUE"], [["Alfa", 2.0]], tool="run_recipe", matrix_code=None,
                                      recipe="fx_intensity", links=[{"kind": "evidence", "url": "/x", "description": "e"}])))
    assert recipe.locator(".chat-table td").nth(1).inner_text() == "2" and recipe.locator(".chat-chart").count() == 0
    assert recipe.locator(".chat-links a").count() == 1
    no_sideways_scroll(page)


def test_follow_up_context_is_sent_back_and_cleared_by_reset(page):
    srv = Server(page)
    ctx = [{"tool": "query_data", "generation": "gen-1",
            "selection": {"kind": "dataset", "dataset": "POPC", "filters": {"REF_AREA": ["Cluj"]},
                          "group_by": [], "approximate": False},
            "sources": [{"dataset": "POPC", "unit": "persoane", "definition": "d"}], "summary": {"rows": 2}}]
    ask(page, srv, "Câți locuitori are Cluj?", result(context=ctx))
    assert srv.requests[0].get("context") is None                           # nothing to send yet
    page.wait_for_selector("#chat-reset:not(.hidden)")
    ask(page, srv, "Același lucru pentru Iași?", result(context=ctx))
    assert srv.requests[1]["context"] == ctx and len(srv.requests[1]["history"]) == 2
    page.click("#chat-reset")                                                # a new conversation
    assert page.locator(".chat-msg").count() == 0 and page.locator("#chat-empty").is_visible()
    ask(page, srv, "Altă întrebare?", result())
    assert "context" not in srv.requests[2] and srv.requests[2]["history"] == []
    assert page.problems == []


def test_a_stale_generation_clears_the_context_and_offers_a_new_conversation(page):
    srv = Server(page)
    ctx = [{"tool": "query_data", "generation": "gen-1", "selection": {"kind": "dataset", "dataset": "POPC",
            "filters": {}, "group_by": [], "approximate": False}}]
    ask(page, srv, "Prima?", result(context=ctx))
    msg = ask(page, srv, "A doua?", (409, {"detail": {"reason": "generation_changed", "action": "refresh",
                                                     "message": "The data was updated since this conversation's earlier answers."}}))
    assert "updated" in msg.inner_text() and msg.locator("button").count() == 1
    assert page.input_value("#chat-input") == "A doua?"                      # the question is kept for editing
    ask(page, srv, "A doua?", result())
    assert "context" not in srv.requests[2]                                  # the stale selections are gone


def test_busy_and_network_errors_keep_the_question_and_suggest_a_next_step(page):
    srv = Server(page)
    msg = ask(page, srv, "Prima?", (503, {"detail": "Ask is busy; retry shortly"}))
    assert "busy" in msg.inner_text() and msg.locator(".chat-next a").inner_text() == "Caută direct în date"
    assert page.input_value("#chat-input") == "Prima?"
    srv.queue.append(lambda route: route.abort("failed"))
    page.fill("#chat-input", "A doua?")
    page.click("#chat-send")
    page.wait_for_selector(".chat-msg--error >> text=Network error")
    assert page.locator("#chat-loading").count() == 0 and page.locator("#chat-send").is_enabled()
    no_sideways_scroll(page)


def test_a_timeout_stops_the_spinner_and_offers_what_to_do(page):
    srv = Server(page)
    page.evaluate("MAX_SECONDS = -29")                                      # client gives up after 1 s
    srv.queue.append(lambda route: (page.wait_for_timeout(2500), route.abort("failed")))
    page.fill("#chat-input", "Întrebare lentă?")
    page.click("#chat-send")
    page.wait_for_selector(".chat-msg--error", timeout=8000)
    assert page.locator("#chat-loading").count() == 0 and page.locator("#chat-send").is_enabled()
    assert "narrower question" in page.locator(".chat-msg--error").inner_text().lower() \
        or "mai restrânsă" in page.locator(".chat-msg--error").inner_text()
    assert page.input_value("#chat-input") == "Întrebare lentă?"
    no_sideways_scroll(page)


def test_ranked_table_has_readable_headings_and_eligible_count(page):
    srv = Server(page)
    msg = ask(page, srv, 'Top orașe', result(data=table(
        ['RANK', 'REF_AREA', 'REF_AREA_2', 'TIME_PERIOD', 'OBS_VALUE'],
        [[1, 'Cluj', '54975 MUNICIPIUL CLUJ-NAPOCA', '2025', 324000]],
        ranked=True, eligible_count=230, unit='Numar persoane')))
    headers = msg.locator('.chat-table th').all_inner_texts()
    assert 'REF_AREA_2' not in headers and 'OBS_VALUE' not in headers
    assert '230' in msg.inner_text() and 'Numar persoane' in msg.inner_text()
    assert msg.locator('.chat-table th[title="OBS_VALUE"]').count() == 1
    no_sideways_scroll(page)
    assert page.problems == []


def test_truncated_preview_renders_its_footer_without_console_errors(page):
    srv = Server(page)
    msg = ask(page, srv, 'Datele disponibile', result(data=table(
        ['REF_AREA', 'TIME_PERIOD', 'OBS_VALUE'], [['Cluj', '2025', 324000]],
        truncated=True, preview=True)))
    assert 'Previzualizare' in msg.locator('.chat-data-meta').inner_text()
    assert 'nu este un clasament' in msg.locator('.chat-data-meta').inner_text()
    assert 'Previzualizare limitată' in msg.locator('.chat-table-truncated').inner_text()
    no_sideways_scroll(page)
    assert page.problems == []
