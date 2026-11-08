"""PKG-TOOLS F7: a percent ranking led by a tiny base is flagged; a zero base stays excluded."""
import pytest

from at01_fixtures import add_dataset, call, make_env
from test_at01_changes import area_dim, time_dim, unit_dim, UNIT

TABLE = {"A": (1, 46), "B": (100, 150), "C": (0, 10), "D": (20, 40), "E": (19, 30)}


def build(corpus):
    rows = [(e, y, UNIT, float(v)) for e, vals in TABLE.items() for y, v in zip(("2020", "2021"), vals)]
    add_dataset(corpus, "BASEX", [area_dim(list(TABLE)), time_dim(("2020", "2021")), unit_dim(UNIT)], rows)


@pytest.fixture
def env(tmp_path, monkeypatch):
    return make_env(tmp_path, monkeypatch, build=build)


def cp(**kw):
    return call("compare_periods", dataset="BASEX", entity_columns=["REF_AREA"], lang="en",
                intervals=[{"from": "2020", "to": "2021"}], **kw)


def test_percent_ranking_flags_small_bases(env):
    e = cp(metric="percent", order="desc", top_k=10)
    rows = e["data"]["intervals"][0]["rows"]
    assert [(r["entity"]["REF_AREA"], r.get("small_base")) for r in rows] == [
        ("A", True), ("D", None), ("E", True), ("B", None)]          # base 20 is not below the threshold
    w = next(w for w in e["warnings"] if w["code"] == "small_base")
    assert "2 returned rows" in w["message"] and "below 20" in w["message"]
    assert e["data"]["intervals"][0]["exclusion_counts"] == {"zero_baseline": 1}    # unchanged


def test_warning_counts_only_returned_rows(env):
    e = cp(metric="percent", order="desc", top_k=1)
    assert "1 returned rows" in next(w for w in e["warnings"] if w["code"] == "small_base")["message"]
    e = cp(metric="percent", order="asc", top_k=1)           # B: +50% from 100
    assert not any(w["code"] == "small_base" for w in e["warnings"])


def test_absolute_ranking_has_no_small_base(env):
    e = cp(metric="absolute", order="desc", top_k=10)
    assert not any(w["code"] == "small_base" for w in e["warnings"])
    assert all("small_base" not in r for r in e["data"]["intervals"][0]["rows"])


def test_romanian_message(env):
    e = call("compare_periods", dataset="BASEX", entity_columns=["REF_AREA"], lang="ro", metric="percent",
             intervals=[{"from": "2020", "to": "2021"}], order="desc", top_k=3)
    assert "bază mică" in next(w for w in e["warnings"] if w["code"] == "small_base")["message"]
