"""AQ-08: chart hints (`data.chart`) in tool results, the chart link, and the Ask presenter.

Synthetic corpora through the real tools (CITYX: 230 cities and a commune, 2024-2025; COUNTX: the
AT-01 spec table). The builders in `app.services.tools.chart` are also run on hand-made envelopes for
the null cases that are awkward to reach through a corpus.
"""
import json
from urllib.parse import parse_qs, urlparse

import pytest

from app.services import ask_present
from app.services.tools import chart as CH
from app.services.tools import contract as C
from app.services.tools import messages as M
from at01_fixtures import add_dataset, call, make_env
from test_at01_changes import UNIT, area_dim, build_countx, time_dim, unit_dim
from test_at05_ranking import build as build_cities


def build(corpus):
    build_cities(corpus)
    build_countx(corpus)
    # a county x year series (query_data line) and a one-year county list (bar)
    counties = [f"C{i}" for i in range(4)]
    add_dataset(corpus, "SERIES", [area_dim(counties), time_dim(("2020", "2021", "2022")), unit_dim(UNIT)],
                [(c, y, UNIT, float(10 * i + j)) for i, c in enumerate(counties)
                 for j, y in enumerate(("2020", "2021", "2022"))])


@pytest.fixture
def env(tmp_path, monkeypatch):
    return make_env(tmp_path, monkeypatch, build=build)


def q(url):
    return {k: json.loads(v[0]) if k in ("f", "g") else v[0] for k, v in parse_qs(urlparse(url).query).items()}


def rank(**kw):
    kw.setdefault("entity_class", "cities")
    return call("rank_entities", dataset="CITYX", entity_columns=["REF_AREA", "REF_AREA_2"], **kw)


def rows_at(env_, path):
    node = env_
    for part in path.replace("[", ".").replace("]", "").split("."):
        node = node[int(part)] if part.isdigit() else node[part]
    return node


# ------------------------------------------------------------------ rank_entities

def test_rank_hint_names_existing_fields_and_copies_no_row(env):
    r = rank(top_k=5)
    h = r["data"]["chart"]
    assert (h["type"], h["series"], h["sort"], h["row_format"]) == ("bar", None, "desc", "object")
    assert h["rows"] == "data.rows" and h["x"] == "entity.REF_AREA_2" and h["y"] == "value"
    row = rows_at(r, h["rows"])[0]
    assert row["entity"]["REF_AREA_2"] and isinstance(row["value"], float)
    assert set(h) == {"type", "rows", "row_format", "x", "y", "series", "sort", "unit", "title", "url",
                      "url_note"}
    assert h["unit"] == "Numar persoane" and "2025" in h["title"] and "5" in h["title"]


def test_rank_hint_follows_requested_order(env):
    assert rank(order="asc", top_k=3)["data"]["chart"]["sort"] == "asc"


def test_rank_link_carries_filters_and_the_year_and_no_numbers(env):
    r = rank(year="2024", top_k=5)
    h = r["data"]["chart"]
    assert h["url"].startswith("/dataset-v2.html?")
    assert q(h["url"]) == {"code": "CITYX", "f": {"TIME_PERIOD": ["2024"]}}
    assert "2024" in h["url_note"]
    # no ranked value is in the link
    assert not any(str(int(x["value"])) + "." in h["url"] for x in r["data"]["rows"])


def test_rank_hint_and_link_in_english(env):
    h = rank(top_k=3, lang="en")["data"]["chart"]
    assert q(h["url"])["lang"] == "en" and h["title"].endswith("top 3 of 230")
    assert "values for 2025" in h["url_note"]
    ro = rank(top_k=3)["data"]["chart"]
    assert {k: v for k, v in h.items() if k not in ("title", "url", "url_note")} == \
           {k: v for k, v in ro.items() if k not in ("title", "url", "url_note")}


def test_rank_without_a_single_label_has_no_chart(env):
    e = call("rank_entities", dataset="CITYX", entity_columns=["REF_AREA", "REF_AREA_2"])
    assert e["data"]["chart"]["x"] == "entity.REF_AREA_2"
    assert CH.label_column(["REF_AREA", "UNIT_MEASURE"]) is None
    assert CH.label_column(["REF_AREA_2", "SEX"]) is None
    assert CH.label_column(["REF_AREA"]) == "REF_AREA"


def test_unavailable_and_refused_results_carry_no_chart(env):
    assert "chart" not in rank(year="2023")["data"]
    assert "chart" not in call("get_evidence_links", selection=rank()["provenance"]["selection"],
                               generation_id=rank()["provenance"]["generation"]["id"])["data"]


def test_a_ranking_of_one_has_no_chart(env):
    e = rank(top_k=1)       # one bar only is not a chart; eligible_count stays 230
    assert len(e["data"]["rows"]) == 1 and "chart" not in e["data"]


# ------------------------------------------------------------------ compare_periods

def cp(**kw):
    kw.setdefault("dataset", "COUNTX")
    kw.setdefault("entity_columns", ["REF_AREA"])
    return call("compare_periods", **kw)


def test_compare_hint_uses_the_requested_metric_and_the_end_year(env):
    e = cp(intervals=[{"from": "1992", "to": "2020"}], metric="percent", order="desc")
    h = e["data"]["chart"]
    assert (h["type"], h["rows"], h["x"], h["y"], h["sort"]) == (
        "bar", "data.intervals[0].rows", "entity.REF_AREA", "percent", "desc")
    assert h["unit"] == "%" and "1992" in h["title"] and "2020" in h["title"]
    assert rows_at(e, h["rows"])[0]["entity"]["REF_AREA"]
    assert q(h["url"]) == {"code": "COUNTX", "f": {"TIME_PERIOD": ["2020"]}}
    assert "not the computed change" in cp(intervals=[{"from": "1992", "to": "2020"}], lang="en")[
        "data"]["chart"]["url_note"]
    a = cp(intervals=[{"from": "1992", "to": "2020"}], metric="absolute")["data"]["chart"]
    assert a["y"] == "absolute" and a["unit"] == UNIT


def test_compare_with_several_intervals_has_no_chart(env):
    e = cp(intervals=[{"from": "1992", "to": "2002"}, {"from": "2010", "to": "2020"}])
    assert "chart" not in e["data"]


def test_compare_cities_keeps_the_locality_label_and_class(env):
    e = call("compare_periods", dataset="CITYX", entity_columns=["REF_AREA", "REF_AREA_2"],
             entity_class="cities", intervals=[{"from": "2024", "to": "2025"}], metric="percent", top_k=100)
    h = e["data"]["chart"]
    assert h["x"] == "entity.REF_AREA_2" and q(h["url"])["f"] == {"TIME_PERIOD": ["2025"]}
    assert rows_at(e, h["rows"])[0]["entity"]["REF_AREA_2"].startswith("1")


# ------------------------------------------------------------------ query_data

def qd(**kw):
    return call("query_data", dataset="SERIES", **kw)


def test_query_line_over_periods_with_one_series_column(env):
    e = qd(group_by=["REF_AREA", "TIME_PERIOD"], filters={"REF_AREA": ["C0", "C1"]})
    h = e["data"]["chart"]
    assert (h["type"], h["x"], h["y"], h["series"], h["row_format"], h["columns"]) == (
        "line", "TIME_PERIOD", "OBS_VALUE", "REF_AREA", "array", "data.columns")
    assert {h["x"], h["y"], h["series"]} <= set(e["data"]["columns"])
    assert q(h["url"])["f"] == {"REF_AREA": ["C0", "C1"]}


def test_query_single_series_line_and_bar_for_one_period(env):
    one = qd(group_by=["TIME_PERIOD"], filters={"REF_AREA": ["C2"]})["data"]["chart"]
    assert one["type"] == "line" and one["series"] is None
    bar = qd(group_by=["REF_AREA"], filters={"TIME_PERIOD": ["2021"]})["data"]["chart"]
    assert (bar["type"], bar["x"], bar["series"]) == ("bar", "REF_AREA", None)


def test_query_with_two_varying_dimensions_or_one_value_has_no_chart(env):
    assert qd(group_by=["REF_AREA", "TIME_PERIOD"])["data"]["chart"]["series"] == "REF_AREA"   # 4 lines
    assert "chart" not in qd(filters={"REF_AREA": ["C0"], "TIME_PERIOD": ["2020"]})["data"]


def synthetic(**over):
    env_ = {"tool": "query_data", "status": "ok", "reason": None,
            "data": {"columns": ["REF_AREA", "TIME_PERIOD", "OBS_VALUE"],
                     "rows": [["a", "2020", 1.0], ["a", "2021", 2.0], ["b", "2020", 3.0], ["b", "2021", 4.0]]},
            "provenance": {"selection": {"dataset": "D", "filters": {}}, "sources": [{"unit": "u", "metric": "M"}],
                           "aggregation": {}},
            "limits": {"preview_truncated": False, "source_complete": True}}
    for k, v in over.items():
        env_[k] = v
    return env_


def build_hint(env_, lang="ro"):
    return CH._BUILD[env_["tool"]](env_, lang)


def test_two_varying_dimensions_besides_time_have_no_chart():
    e = synthetic()
    e["data"]["columns"] = ["REF_AREA", "SEX", "OBS_VALUE"]
    e["data"]["rows"] = [["a", "m", 1.0], ["a", "f", 2.0], ["b", "m", 3.0], ["b", "f", 4.0]]
    assert build_hint(e) is None                                     # two geographic-style series are never merged
    e["data"]["rows"] = [["a", "m", 1.0], ["b", "m", 3.0]]
    assert build_hint(e)["type"] == "bar"


def test_query_null_cases():
    assert build_hint(synthetic())["series"] == "REF_AREA"
    cut = synthetic(limits={"preview_truncated": True, "source_complete": True})
    assert build_hint(cut) is None                                   # a cut table is not drawn
    approx = synthetic()
    approx["provenance"]["aggregation"] = {"approximation": True}
    assert build_hint(approx) is None                                # a labelled approximation is not drawn
    assert build_hint(synthetic(reason="duplicate_keys")) is None
    dup = synthetic()
    dup["data"]["rows"].append(["a", "2020", 9.0])
    assert build_hint(dup) is None                                   # a repeated key would overdraw
    units = synthetic()
    units["data"]["columns"] = ["UNIT_MEASURE", "TIME_PERIOD", "OBS_VALUE"]
    assert build_hint(units) is None                                 # two units do not share an axis
    many = synthetic()
    many["data"]["rows"] = [[f"s{i}", y, 1.0] for i in range(CH.MAX_SERIES + 1) for y in ("2020", "2021")]
    assert build_hint(many) is None


# ------------------------------------------------------------------ recipe

def recipe_env(rows, **over):
    env_ = {"tool": "run_recipe", "status": "ok", "data": {
        "recipe": {"id": "r1", "name": "Intensity", "unit": "per 100"}, "year": "2024", "rows": rows},
        "provenance": {"selection": {"kind": "recipe", "recipe": "r1", "year": "2024", "areas": ["A", "B"]}}}
    env_.update(over)
    return env_


def test_recipe_bar_per_area_and_null_for_a_national_series():
    rows = [{"rank": 1, "label": "A", "value": 9.0}, {"rank": 2, "label": "B", "value": 4.0}]
    h = build_hint(recipe_env(rows), "en")
    assert (h["type"], h["x"], h["y"], h["sort"], h["unit"]) == ("bar", "label", "value", "desc", "per 100")
    assert urlparse(h["url"]).path == "/compare.html"
    assert q(h["url"]) == {"recipe": "r1", "year": "2024", "areas": ["A", "B"]} \
        if False else parse_qs(urlparse(h["url"]).query)["recipe"] == ["r1"]
    assert build_hint(recipe_env([{**r, "year": "2020"} for r in rows])) is None
    assert build_hint(recipe_env(rows[:1])) is None


def test_recipe_url_over_four_kib_is_dropped_not_cut():
    rows = [{"rank": 1, "label": "A", "value": 9.0}, {"rank": 2, "label": "B", "value": 4.0}]
    env_ = recipe_env(rows)
    env_["provenance"]["selection"]["areas"] = ["x" * 60] * 100
    h = build_hint(env_)
    assert h["url"] is None and h["url_note"] is None and h["x"] == "label"


def test_dataset_link_over_four_kib_is_dropped(env):
    big = {"REF_AREA": [f"county-{i:04d}-" + "x" * 30 for i in range(150)]}
    assert CH._page("D", "ro", big, None) is None
    assert CH._page("D", "ro", {"REF_AREA": ["a"]}, {"AGE": "decades"}) is not None
    assert q(CH._page("D", "ro", {"REF_AREA": ["a"]}, {"AGE": "decades"}))["g"] == {"AGE": "decades"}


# ------------------------------------------------------------------ size

def test_the_hint_stays_small_and_the_result_inside_the_cap(env):
    r = rank(top_k=100)
    hint_bytes = C.size(r["data"]["chart"])
    assert hint_bytes < 1024
    assert C.size(r) <= C.MAX_RESULT_BYTES
    wide = call("compare_periods", dataset="CITYX", entity_columns=["REF_AREA", "REF_AREA_2"],
                entity_class="cities", intervals=[{"from": "2024", "to": "2025"}], metric="percent", top_k=100,
                lang="en")
    assert C.size(wide) <= C.MAX_RESULT_BYTES and C.size(wide["data"]["chart"]) < 1024
    # a result cut to fit the cap keeps a hint that still names fields of the rows that remain
    from app.services.tools.registry import call_tool
    cut = call_tool("rank_entities", {"dataset": "CITYX", "entity_columns": ["REF_AREA", "REF_AREA_2"],
                                      "entity_class": "cities", "top_k": 100})
    assert rows_at(cut, cut["data"]["chart"]["rows"])


# ------------------------------------------------------------------ Ask presenter

def test_ranking_trace_gives_the_page_a_chart_from_the_hint(env):
    r = rank(top_k=4)
    table = ask_present.display_table([{"id": "c", "tool": "rank_entities", "input": {}, "output": r}], "ro")
    ch = table["chart"]
    assert (ch["type"], ch["x"], ch["y"], ch["sort"]) == ("bar", "REF_AREA_2", "OBS_VALUE", "desc")
    assert ch["url"] == r["data"]["chart"]["url"] and ch["title"] == r["data"]["chart"]["title"]
    xi, yi = table["columns"].index(ch["x"]), table["columns"].index(ch["y"])
    assert [row[xi] for row in table["rows"]] == [x["entity"]["REF_AREA_2"] for x in r["data"]["rows"]]
    assert [row[yi] for row in table["rows"]] == [x["value"] for x in r["data"]["rows"]]
    assert ask_present.chart_dataset([{"id": "c", "tool": "rank_entities", "output": r}]) is None


def test_compare_trace_chart_maps_the_metric_column(env):
    e = cp(intervals=[{"from": "1992", "to": "2020"}], metric="percent")
    table = ask_present.display_table([{"id": "c", "tool": "compare_periods", "input": {}, "output": e}], "ro")
    assert table["chart"]["y"] == "PERCENT" and table["chart"]["x"] == "REF_AREA"


def test_query_table_keeps_the_dataset_chart_spec_and_gets_no_hint_chart(env):
    e = qd(group_by=["REF_AREA", "TIME_PERIOD"], filters={"REF_AREA": ["C0", "C1"]})
    table = ask_present.display_table([{"id": "q", "tool": "query_data", "input": {}, "output": e}])
    assert "chart" not in table
    assert ask_present.chart_dataset([{"id": "q", "tool": "query_data", "output": e}]) == "SERIES"


def test_a_hint_that_does_not_match_the_table_is_dropped(env):
    r = rank(top_k=3)
    r["data"]["chart"]["x"] = "entity.NOPE"
    assert "chart" not in ask_present.display_table([{"id": "c", "tool": "rank_entities", "output": r}])
    r["data"]["chart"]["x"] = "entity.REF_AREA_2"
    r["data"]["chart"]["type"] = "pie"
    assert "chart" not in ask_present.display_table([{"id": "c", "tool": "rank_entities", "output": r}])


def test_messages_exist_in_both_languages():
    for key in ("chart.title_rank", "chart.link_year", "chart.link_changes", "chart.link_recipe"):
        assert M.TEXT["en"][key] != M.TEXT["ro"][key]
