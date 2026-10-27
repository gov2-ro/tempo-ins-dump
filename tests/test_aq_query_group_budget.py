"""query_data refuses a grouping too large for one query before running it (AQ-01B follow-up).

A grouping over nearly every dimension of a multi-million-row file is close to the raw table.
DuckDB does not spill such an aggregate at the 160MB budget and the call failed with
`execution_failed`. The tools now estimate the groups first and answer `query_budget` with the
column to narrow. REST `/data` is unchanged (it windows time instead).

LOCX: 2 counties x 30 localities x 5 years = 300 rows. The locality column declares no options,
as split children's locality columns do, so only the data can say how wide it is.
"""
import re

import pytest

from at01_fixtures import add_dataset, call, make_env, said

YEARS = [(str(y), {"year": y}) for y in range(2020, 2025)]
AREAS = [("Alba", {"geo_level": "county"}), ("Cluj", {"geo_level": "county"})]


def build(corpus):
    rows = [(a, f"{a} loc {i:02d}", y, float(i)) for a in ("Alba", "Cluj") for i in range(30)
            for y in map(str, range(2020, 2025))]
    add_dataset(corpus, "LOCX", [("REF_AREA", "Judete", "geo", AREAS), ("REF_AREA_2", "Localitati", None, []),
                                 ("TIME_PERIOD", "Ani", "time", YEARS)], rows)


@pytest.fixture
def env(tmp_path, monkeypatch):
    from app.services.tools import query
    monkeypatch.setattr(query, "MAX_GROUPS", 50)
    return make_env(tmp_path, monkeypatch, build)


@pytest.mark.parametrize("lang", ["en", "ro"])
def test_a_grouping_over_the_limit_is_refused_with_the_column_to_narrow(env, lang):
    e = call("query_data", dataset="LOCX", group_by=["REF_AREA", "REF_AREA_2", "TIME_PERIOD"], lang=lang)
    assert (e["status"], e["reason"]) == ("unavailable", "query_budget")
    assert not (e["data"] or {}).get("rows")
    assert said(e["message"], lang, "Filter REF_AREA_2", "Filtrează REF_AREA_2")
    groups = int(re.search(r"(\d+) (rows|rânduri)", e["message"]).group(1))
    assert 270 <= groups <= 330 and " 50 " in e["message"]        # 300, by HyperLogLog
    lookup = [r for r in e["recovery"] if r["kind"] == "tool_call"]
    assert lookup == [{"kind": "tool_call", "message": lookup[0]["message"], "tool": "find_dimension_values",
                       "arguments": {"dataset": "LOCX", "column": "REF_AREA_2", "lang": lang}}]
    assert any(r["kind"] == "narrow" for r in e["recovery"])


def test_the_same_grouping_narrowed_by_filters_is_answered(env):
    e = call("query_data", dataset="LOCX", group_by=["REF_AREA", "REF_AREA_2", "TIME_PERIOD"],
             filters={"REF_AREA": ["Cluj"], "TIME_PERIOD": ["2024"]}, lang="en")
    assert e["status"] in ("ok", "partial") and e["reason"] != "query_budget"
    assert e["limits"]["returned_rows"] == 30


def test_declared_option_counts_bound_a_small_grouping_without_a_scan(env, monkeypatch):
    from app.services import data_query
    scans = []
    real = data_query._group_estimate

    def spy(conn, *a):
        r = real(conn, *a)
        scans.append(r)
        return r
    monkeypatch.setattr(data_query, "_group_estimate", spy)
    e = call("query_data", dataset="LOCX", group_by=["REF_AREA", "TIME_PERIOD"], lang="en")
    assert e["reason"] != "query_budget"
    assert scans == [(10, {"REF_AREA": 2, "TIME_PERIOD": 5})]     # 2 x 5 from metadata


def test_rest_data_has_no_group_limit(env):
    from app.services import data_query
    from app.db import get_conn
    res = data_query.run_query(get_conn(), "LOCX", {}, ["REF_AREA", "REF_AREA_2", "TIME_PERIOD"], limit=1000)
    assert res["returned_rows"] == 300
