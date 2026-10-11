"""PA-01c pure frontend rules, run in headless Chromium on fixtures (no server).

A03: Ask chart series keep every varying dimension (two counties stay two lines).
A06: comparison aligns on the latest common period; constant axes have no r.
Skipped when playwright/chromium is unavailable.
"""
from pathlib import Path

import pytest

pw = pytest.importorskip("playwright.sync_api")

JS = Path(__file__).resolve().parent.parent / "app" / "static" / "js"


@pytest.fixture(scope="module")
def page():
    with pw.sync_playwright() as p:
        try:
            browser = p.chromium.launch()
        except Exception as e:
            pytest.skip(f"chromium unavailable: {type(e).__name__}")
        pg = browser.new_page()
        pg.set_content("<html><body></body></html>")
        for name in ("ask.js", "compare.js"):
            pg.add_script_tag(content=(JS / name).read_text(encoding="utf-8"))
        yield pg
        browser.close()


def test_ask_chart_keeps_geographic_series(page):
    out = page.evaluate("""() => chartSeries(['REF_AREA', 'TIME_PERIOD', 'OBS_VALUE'],
        [['Cluj', '2023', 10], ['Cluj', '2024', 11], ['Iasi', '2023', 20], ['Iasi', '2024', 21]])""")
    assert out["xData"] == ["2023", "2024"]
    assert {s["name"]: s["data"] for s in out["series"]} == {"Cluj": [10, 11], "Iasi": [20, 21]}


def test_ask_chart_names_series_by_every_varying_dimension(page):
    out = page.evaluate("""() => chartSeries(['SEX', 'REF_AREA', 'UNIT_MEASURE', 'TIME_PERIOD', 'OBS_VALUE'],
        [['M', 'Cluj', 'Pers', '2024', 1], ['F', 'Cluj', 'Pers', '2024', 2],
         ['M', 'Iasi', 'Pers', '2024', 3], ['F', 'Iasi', 'Pers', '2024', 4]])""")
    assert sorted(s["name"] for s in out["series"]) == ["F · Cluj", "F · Iasi", "M · Cluj", "M · Iasi"]


def test_ask_chart_refuses_repeated_keys(page):
    out = page.evaluate("""() => chartSeries(['REF_AREA', 'TIME_PERIOD', 'OBS_VALUE'],
        [['Cluj', '2024', 10], ['Cluj', '2024', 11]])""")
    assert out["error"] == "duplicate_key"


def test_citation_target_is_the_v2_page(page):
    assert page.evaluate("() => datasetHref('POP105A')") == "/dataset-v2.html?code=POP105A"


@pytest.mark.parametrize("pts", [
    "[[1, 5], [2, 5], [3, 5]]",          # constant y
    "[[1, 2]]",                          # one pair
    "[[1, NaN], [2, 3], [3, 4]]",        # non-finite
])
def test_pearson_undefined_is_null_not_zero(page, pts):
    assert page.evaluate(f"() => pearson({pts})") is None


def test_pearson_value(page):
    assert page.evaluate("() => pearson([[1, 2], [2, 4], [3, 6]])") == pytest.approx(1.0)


_BUILD = """([a, b]) => {
  const m = o => new Map(Object.entries(o).map(([p, v]) => [p, new Map(Object.entries(v))]));
  return ComparePage.alignCounties({byPeriod: m(a), duplicate: new Map()},
                                   {byPeriod: m(b), duplicate: new Map()}); }"""


def test_scatter_uses_latest_common_period(page):
    a = {"2023": {"Cluj": 1, "Iasi": 2, "Alba": 3}, "2025": {"Cluj": 9, "Iasi": 8, "Alba": 7}}
    b = {"2023": {"Cluj": 10, "Iasi": 20, "Alba": 30}, "2024": {"Cluj": 1, "Iasi": 1, "Alba": 1}}
    out = page.evaluate(_BUILD, [a, b])
    assert out["period"] == "2023" and out["r"] == pytest.approx(1.0)


def test_scatter_without_common_period_is_unavailable(page):
    out = page.evaluate(_BUILD, [{"2023": {"Cluj": 1}}, {"2025": {"Cluj": 2}}])
    assert out == {"error": "no_common_period", "periods": ["2023", "2025"]}


def test_scatter_reports_exclusions(page):
    a = {"2024": {"Cluj": 1, "Iasi": 2, "Alba": 3, "Arad": None}}
    b = {"2024": {"Cluj": 5, "Iasi": 6, "Arad": 4, "Bihor": 7}}
    out = page.evaluate(_BUILD, [a, b])
    assert [p[2] for p in out["pts"]] == ["Cluj", "Iasi"]
    assert out["onlyA"] == ["Alba"] and out["onlyB"] == ["Arad", "Bihor"]
