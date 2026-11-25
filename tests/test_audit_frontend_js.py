"""PKG-FRONTEND renderer rules, run in headless Chromium against a stub ECharts.

C01/E3: a stacked area or bar drops the Total series.
C05: the tooltip sum shows only on stacked views and never counts a Total.
C07: a choropleth with no matching map falls back to a ranking bar chart.
Skipped when playwright/chromium is unavailable.
"""
from pathlib import Path

import pytest

pw = pytest.importorskip("playwright.sync_api")

JS = Path(__file__).resolve().parent.parent / "app" / "static" / "js"

STUB = """
window.__opts = [];
window.__disposed = 0;
window.echarts = {
  init: () => ({
    setOption: o => window.__opts.push(o),
    getDom: () => ({ clientWidth: 800 }),
    dispose: () => { window.__disposed++; },
    resize() {}, on() {}, off() {},
  }),
  registerMap() {},
};
"""


@pytest.fixture(scope="module")
def page():
    with pw.sync_playwright() as p:
        try:
            browser = p.chromium.launch()
        except Exception as e:
            pytest.skip(f"chromium unavailable: {type(e).__name__}")
        pg = browser.new_page()
        pg.set_content("<html><body><div id='c'></div></body></html>")
        pg.add_script_tag(content=STUB)
        for name in ("utils.js", "chart-new-types.js", "chart-geo.js", "chart-factory.js",
                     "dashboard-v2.js"):
            pg.add_script_tag(content=(JS / name).read_text(encoding="utf-8"))
        yield pg
        browser.close()


DATA = """{
  columns: ['TIME_PERIOD', 'FORM', 'OBS_VALUE'],
  column_labels: { TIME_PERIOD: {}, FORM: { a: 'Privata', b: 'Publica', t: 'Total' } },
  rows: [['2024', 'a', 4], ['2024', 'b', 1], ['2024', 't', 5],
         ['2025', 'a', 5], ['2025', 'b', 2], ['2025', 't', 7]],
}"""


def _chart(page, ctype, series_view=True):
    return page.evaluate(f"""() => {{
        window.__opts.length = 0;
        const data = {DATA};
        createTimeSeriesChart(document.getElementById('c'),
            {{ primary_chart: '{ctype}', time_dim: 'TIME_PERIOD', series_dim: 'FORM', _sumSeries: true }},
            data, {{ matrix_name: 'x' }});
        const o = window.__opts[0];
        const params = o.series.map(s => ({{ value: s.data[0], seriesName: s.name, marker: '', axisValue: '2024' }}));
        return {{ names: o.series.map(s => s.name), stacks: o.series.map(s => s.stack || null),
                 tip: o.tooltip.formatter(params).replace(/<[^>]+>/g, ' ') }};
    }}""")


def test_stacked_area_drops_total_series(page):
    out = _chart(page, "area_stacked")
    assert out["names"] == ["Privata", "Publica"]
    assert set(out["stacks"]) == {"total"}


def test_tooltip_sum_only_on_stacked_and_excludes_total(page):
    stacked = _chart(page, "area_stacked")
    assert "∑" in stacked["tip"] and "5" in stacked["tip"] and "10" not in stacked["tip"]
    assert "Total" not in stacked["tip"]
    for plain in ("line", "bar_vertical"):
        assert "∑" not in _chart(page, plain)["tip"]


def test_lines_keep_the_total_series(page):
    assert _chart(page, "line")["names"] == ["Privata", "Publica", "Total"]


def test_stacked_demographic_path_drops_total(page):
    out = page.evaluate(f"""() => {{
        const d = {DATA};
        const kept = dropTotalSeries(d, 'FORM');
        const only = dropTotalSeries({{ ...d, rows: d.rows.filter(r => r[1] === 't') }}, 'FORM');
        return {{ kept: kept.rows.map(r => r[1]), onlyTotal: only.rows.length }};
    }}""")
    assert set(out["kept"]) == {"a", "b"}
    assert out["onlyTotal"] == 2    # a lone Total stays: nothing to double-count


def test_choropleth_without_a_map_falls_back_to_ranking(page):
    out = page.evaluate("""() => {
        window.__opts.length = 0; window.__disposed = 0;
        const data = { columns: ['REF_AREA', 'TIME_PERIOD', 'OBS_VALUE'],
          column_labels: { REF_AREA: { fr: 'Franta', de: 'Germania' }, TIME_PERIOD: {} },
          rows: [['fr', '2023', 1], ['de', '2023', 9], ['fr', '2024', 3], ['de', '2024', 7]] };
        const meta = { dimensions: [{ dim_column_name: 'REF_AREA', options: [
          { nom_item_id: 'fr', label: 'Franta', parsed: { geo_level: 'unknown', geo_name_clean: 'Franta' } },
          { nom_item_id: 'de', label: 'Germania', parsed: { geo_level: 'unknown', geo_name_clean: 'Germania' } }] }] };
        createChoroplethChart(document.getElementById('c'),
            { geo_dim: 'REF_AREA', time_dim: 'TIME_PERIOD' }, data, meta);
        const o = window.__opts[0];
        return { disposed: window.__disposed, hasMap: JSON.stringify(o).includes('"map"'),
                 cats: o.yAxis.data, vals: o.series[0].data.map(v => v.value ?? v) };
    }""")
    assert out["hasMap"] is False
    assert out["disposed"] == 1
    assert out["cats"] == ["Franta", "Germania"] or sorted(out["cats"]) == ["Franta", "Germania"]
    # latest period only (2024): 3 and 7, not the 2023+2024 sums
    assert sorted(out["vals"]) == [3, 7]


def test_v1_offers_no_stacked_view_for_non_additive_measure(page):
    page.add_script_tag(content=(JS / "explore-app.js").read_text(encoding="utf-8"))
    out = page.evaluate("""() => {
        const dims = [
          { dim_column_name: 'TIME_PERIOD', dim_type: 'time', option_count: 10, options: [] },
          { dim_column_name: 'SEX', dim_type: 'gender', option_count: 2, options: [] },
          { dim_column_name: 'AGE', dim_type: 'age', option_count: 5, options: [] }];
        const run = measure => LensApp.prototype.determinePanelSetup.call({
          metadata: { dimensions: dims, measure }, profile: null, chartConfig: {}, lang: 'ro' });
        return { pct: run('non_additive'), add: run('additive') };
    }""")
    stacked = {"area_stacked", "stacked_bar"}
    assert not stacked & set(out["pct"]["timeChartTypes"])
    assert not stacked & set(out["pct"]["snapshotChartTypes"])
    assert stacked <= set(out["add"]["timeChartTypes"])


def test_v1_yearly_view_marks_an_incomplete_last_year(page):
    page.add_script_tag(content=(JS / "explore-app.js").read_text(encoding="utf-8"))
    out = page.evaluate("""() => {
        const rows = [];
        for (let m = 1; m <= 12; m++) rows.push(['2024-' + String(m).padStart(2, '0'), 1]);
        for (let m = 1; m <= 3; m++) rows.push(['2025-' + String(m).padStart(2, '0'), 1]);
        const data = { columns: ['TIME_PERIOD', 'OBS_VALUE'], column_labels: { TIME_PERIOD: {} }, rows };
        const r = LensApp.prototype._aggregateByYear.call(
          { metadata: { measure: 'additive' }, timeGranularity: 'monthly', ui: { incompleteYear: 'an incomplet' } },
          data, 'TIME_PERIOD', null);
        return { labels: r.column_labels.TIME_PERIOD, rows: r.rows };
    }""")
    assert out["labels"]["2024"] == "2024"
    assert out["labels"]["2025"] == "2025 (an incomplet)"
    assert [r[1] for r in out["rows"]] == [12, 3]


# DP-01: index/delta notes, option pills, series name

def test_transformed_chart_carries_its_own_unit_and_series_name(page):
    out = page.evaluate("""() => {
        window.__opts.length = 0;
        const data = { columns: ['TIME_PERIOD', 'OBS_VALUE'], column_labels: { TIME_PERIOD: {} },
                       rows: [['1990', 100], ['1991', 121.1]] };
        createTimeSeriesChart(document.getElementById('c'),
            { primary_chart: 'line', time_dim: 'TIME_PERIOD', _valueFormat: 'index',
              _yAxisName: 'indice, 1990 = 100', _seriesName: 'Bauturi' },
            data, { matrix_name: 'Titlu [Litri]' });
        const o = window.__opts[0];
        const tip = o.tooltip.formatter([{ value: 121.1, seriesName: o.series[0].name,
                                           marker: '', axisValue: '1991' }]).replace(/<[^>]+>/g, ' ');
        return { name: o.series[0].name, axis: o.yAxis.name, tip };
    }""")
    assert out["name"] == "Bauturi"
    assert out["axis"] == "indice, 1990 = 100"
    assert "indice, 1990 = 100" in out["tip"] and "Litri" not in out["tip"]


def test_option_picker_pills_up_to_six_dropdown_above(page):
    out = page.evaluate("""() => {
        const mk = n => Array.from({ length: n }, (_, i) => ({ value: 'v' + i, label: 'Opt ' + i }));
        const picked = [];
        const six = DashboardV2.prototype._optionPicker.call({}, mk(6), 'v0', 't', v => picked.push(v));
        const seven = DashboardV2.prototype._optionPicker.call({}, mk(7), 'v0', 't', v => picked.push(v));
        six.querySelectorAll('button')[2].click();
        return { sixTag: six.tagName, pills: six.querySelectorAll('button').length,
                 active: [...six.querySelectorAll('.active')].map(b => b.textContent),
                 sevenTag: seven.tagName, picked };
    }""")
    assert out["sixTag"] == "SPAN" and out["pills"] == 6
    assert out["active"] == ["Opt 2"] and out["picked"] == ["v2"]
    assert out["sevenTag"] == "SELECT"


def test_index_base_is_first_period_and_notes_name_the_grain(page):
    out = page.evaluate("""() => {
        const self = DashboardV2.prototype;
        const data = { columns: ['T', 'OBS_VALUE'], column_labels: { T: { '1990': 'Anul 1990' } },
                       rows: [['2001', 1], ['1990', 2]] };
        return { base: self.firstPeriodLabel(data, 'T'),
                 ro: UI_STRINGS.ro.indexNote('1990'), en: UI_STRINGS.en.indexNote('1990'),
                 yoyM: UI_STRINGS.ro.yoyNote('monthly'), yoyA: UI_STRINGS.en.yoyNote('annual') };
    }""")
    assert out["base"] == "1990"
    assert out["ro"] == "Indice: 1990 = 100. Peste 100 = mai mult decât în 1990."
    assert "1990 = 100" in out["en"]
    assert "luna anterioară" in out["yoyM"] and "previous year" in out["yoyA"]
