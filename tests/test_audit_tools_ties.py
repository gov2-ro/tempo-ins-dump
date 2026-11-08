"""PKG-TOOLS F4: equal values share a rank, a cut through a tie is disclosed."""
import pytest

from at01_fixtures import add_dataset, call, make_env
from test_at01_changes import area_dim, time_dim, unit_dim, UNIT
from app.services.tools.registry import validate_result

# 2020 -> 2021 per entity: change +5 for A, B, C (a tie), +1 for D, +9 for E
TABLE = {"A": (10, 15), "B": (20, 25), "C": (30, 35), "D": (40, 41), "E": (50, 59)}
# TIEV has three equal 2021 values
EQ = {"A": (1, 7), "B": (2, 7), "C": (3, 7), "D": (4, 9), "E": (5, 3)}


def _rows(table):
    return [(e, y, UNIT, float(v)) for e, vals in table.items() for y, v in zip(("2020", "2021"), vals)]


def build(corpus):
    for code, table in (("TIEX", TABLE), ("TIEV", EQ)):
        add_dataset(corpus, code, [area_dim(list(table)), time_dim(("2020", "2021")), unit_dim(UNIT)],
                    _rows(table))


@pytest.fixture
def env(tmp_path, monkeypatch):
    return make_env(tmp_path, monkeypatch, build=build)


def codes(env_):
    return [w["code"] for w in env_["warnings"]]


def rank(top_k, **kw):
    return call("rank_entities", dataset="TIEV", entity_columns=["REF_AREA"], year="2021",
                order="desc", top_k=top_k, lang="en", **kw)


def test_rank_entities_ties_share_rank_and_split_is_warned(env):
    r = rank(2)
    validate_result("rank_entities", r)
    rows = r["data"]["rows"]
    assert [(x["entity"]["REF_AREA"], x["rank"], x["tied_with"]) for x in rows] == [("D", 1, 1), ("A", 2, 3)]
    w = next(w for w in r["warnings"] if w["code"] == "tie_split")
    assert "2 more" in w["message"] and "rank 2" in w["message"]


def test_rank_entities_whole_tie_group_inside_top_k_has_no_warning(env):
    r = rank(4)
    assert [(x["rank"], x["tied_with"]) for x in r["data"]["rows"]] == [(1, 1), (2, 3), (2, 3), (2, 3)]
    assert "tie_split" not in codes(r)
    assert [x["rank"] for x in rank(5)["data"]["rows"]] == [1, 2, 2, 2, 5]    # the rank after a group skips it


def test_compare_periods_ties(env):
    kw = dict(dataset="TIEX", entity_columns=["REF_AREA"], intervals=[{"from": "2020", "to": "2021"}], order="desc", lang="en")
    e = call("compare_periods", top_k=2, **kw)
    validate_result("compare_periods", e)
    rows = e["data"]["intervals"][0]["rows"]
    assert [(r["entity"]["REF_AREA"], r["rank"], r["tied_with"]) for r in rows] == [("E", 1, 1), ("A", 2, 3)]
    w = next(w for w in e["warnings"] if w["code"] == "tie_split")
    assert "2020→2021" in w["message"] and "2 more" in w["message"]
    assert "tie_split" not in codes(call("compare_periods", top_k=4, **kw))


def test_tie_message_romanian(env):
    e = call("compare_periods", dataset="TIEX", entity_columns=["REF_AREA"], lang="ro",
             intervals=[{"from": "2020", "to": "2021"}], order="desc", top_k=2)
    assert "egalit" in next(w for w in e["warnings"] if w["code"] == "tie_split")["message"]
