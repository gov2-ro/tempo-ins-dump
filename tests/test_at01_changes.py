"""AT-01e: compare_periods, its evidence route and the offline bundle.

Synthetic temporary corpora through the real shared services (run_query,
aggregation policy, grain gate, generation manifest); nothing here mocks the
calculator's output. The spec fixture (docs/plans/ask-and-public-mcp/
01-analytical-tools.md, "Numerical fixtures"):

    entity   1992   2002   2010   2020
    A         100     80     90     60
    B         200    150    120    100
    C         100    100      0      5
    D         100  missing     90      0
"""
import csv
import hashlib
import io
import json
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

from at01_fixtures import GENERATION, add_dataset, call, make_env, write_manifest

YEARS = ("1992", "2002", "2010", "2020")
TABLE = {"A": (100, 80, 90, 60), "B": (200, 150, 120, 100), "C": (100, 100, 0, 5),
         "D": (100, None, 90, 0)}          # D has no 2002 row at all
UNIT = "Numar persoane"


def time_dim(years=YEARS):
    return ("TIME_PERIOD", "Ani", "time", [(y, dict(year=int(y))) for y in years])


def area_dim(names, level="county", col="REF_AREA", label="Entitati"):
    return (col, label, "geo", [(n, dict(geo_level=level)) for n in names])


def unit_dim(*units):
    return ("UNIT_MEASURE", "Unitate", "unit", [(u, {}) for u in units])


def countx_rows(table=TABLE, years=YEARS, unit=UNIT):
    rows = []
    for e, vals in table.items():
        for y, v in zip(years, vals):
            if v is None:
                continue
            rows.append((e, y, unit, float(v)))
    return rows


def build_countx(corpus, code="COUNTX", table=TABLE, **kw):
    add_dataset(corpus, code, [area_dim(list(table)), time_dim(), unit_dim(UNIT)],
                countx_rows(table), **kw)


@pytest.fixture
def env(tmp_path, monkeypatch):
    return make_env(tmp_path, monkeypatch, build=build_countx)


def iv(a, b):
    return {"from": a, "to": b}


def cp(**kw):
    kw.setdefault("dataset", "COUNTX")
    kw.setdefault("entity_columns", ["REF_AREA"])
    return call("compare_periods", **kw)


def rows_of(env_, i=0):
    return env_["data"]["intervals"][i]["rows"]


def ents(rows):
    return [(r["entity"]["REF_AREA"], r["absolute"]) for r in rows]


# ------------------------------------------------------------ the spec fixture

def test_absolute_ascending_both_intervals(env):
    e = cp(intervals=[iv("1992", "2002"), iv("2010", "2020")])
    assert e["status"] == "partial" and e["reason"] is None       # D has no 2002 row
    assert e["contract"] == "tempo-tools/1"
    first, second = e["data"]["intervals"]
    assert ents(first["rows"]) == [("B", -50.0), ("A", -20.0), ("C", 0.0)]
    assert [r["rank"] for r in first["rows"]] == [1, 2, 3]
    assert first["eligible_count"] == 3 and first["excluded_count"] == 1
    assert first["excluded"] == [{"entity": {"REF_AREA": "D"}, "reason": "no_observation",
                                  "missing": ["to"], "endpoint_reasons": {"to": "no_observation"}}]
    assert first["exclusion_counts"] == {"no_observation": 1}
    assert ents(second["rows"]) == [("D", -90.0), ("A", -30.0), ("B", -20.0), ("C", 5.0)]
    assert second["excluded_count"] == 0 and second["excluded"] == []
    assert e["data"]["key_columns"] == ["REF_AREA"] and e["data"]["entity_columns"] == ["REF_AREA"]
    assert e["data"]["unit"] == UNIT and e["data"]["metric"] == "absolute"
    assert e["limits"]["returned_rows"] == 7 and e["limits"]["total_rows"] == 7
    assert e["limits"]["source_complete"] is True and e["limits"]["preview_truncated"] is False


def test_values_are_the_endpoint_values_unrounded(env):
    e = cp(intervals=[iv("2010", "2020")])
    by = {r["entity"]["REF_AREA"]: r for r in rows_of(e)}
    assert (by["A"]["from_value"], by["A"]["to_value"], by["A"]["absolute"]) == (90.0, 60.0, -30.0)
    assert by["A"]["percent"] == -100 * 30 / 90


def test_ok_when_nothing_is_excluded(env):
    e = cp(intervals=[iv("2010", "2020")])
    assert e["status"] == "ok" and e["reason"] is None
    assert not any(w["code"] == "entities_excluded" for w in e["warnings"])
    assert "not a claim of statistical significance" in e["message"]


def test_percent_changes_and_the_zero_baseline(env):
    e = cp(intervals=[iv("1992", "2002"), iv("2010", "2020")])
    a1 = {r["entity"]["REF_AREA"]: r for r in rows_of(e, 0)}
    a2 = {r["entity"]["REF_AREA"]: r for r in rows_of(e, 1)}
    assert a1["A"]["percent"] == -20.0 and a1["B"]["percent"] == -25.0 and a1["C"]["percent"] == 0.0
    assert a2["A"]["percent"] == pytest.approx(-100 / 3, rel=0, abs=1e-12)
    assert a2["B"]["percent"] == pytest.approx(-100 / 6, rel=0, abs=1e-12)
    assert a2["D"]["percent"] == -100.0
    # C starts the second interval at 0: valid absolute change, percent null, never inf or 0
    assert a2["C"]["absolute"] == 5.0 and a2["C"]["percent"] is None
    assert a2["C"]["percent_note"] == "zero_baseline"


def test_percent_ranking_excludes_the_zero_baseline_while_absolute_keeps_it(env):
    absolute = cp(intervals=[iv("2010", "2020")], metric="absolute")
    assert "C" in [r["entity"]["REF_AREA"] for r in rows_of(absolute)]
    pct = cp(intervals=[iv("2010", "2020")], metric="percent")
    assert pct["status"] == "partial"
    r = rows_of(pct)
    assert [(x["entity"]["REF_AREA"], x["rank"]) for x in r] == [("D", 1), ("A", 2), ("B", 3)]
    assert r[0]["percent"] == -100.0
    ex = pct["data"]["intervals"][0]["excluded"]
    assert [(x["entity"]["REF_AREA"], x["reason"], x["absolute"]) for x in ex] == [
        ("C", "zero_baseline", 5.0)]
    assert pct["data"]["intervals"][0]["eligible_count"] == 3
    assert pct["data"]["intervals"][0]["exclusion_counts"] == {"zero_baseline": 1}


def test_descending_order(env):
    e = cp(intervals=[iv("2010", "2020")], order="desc")
    assert ents(rows_of(e)) == [("C", 5.0), ("B", -20.0), ("A", -30.0), ("D", -90.0)]


def test_top_k_ranks_every_eligible_entity_first(env):
    e = cp(intervals=[iv("1992", "2002"), iv("2010", "2020")], top_k=1)
    assert [ents(i["rows"]) for i in e["data"]["intervals"]] == [[("B", -50.0)], [("D", -90.0)]]
    assert [i["eligible_count"] for i in e["data"]["intervals"]] == [3, 4]
    assert e["limits"]["returned_rows"] == 2 and e["limits"]["total_rows"] == 7
    assert e["limits"]["preview_truncated"] is True
    assert [r["tool"] for r in e["recovery"]] == ["get_evidence_links"]
    assert e["recovery"][0]["arguments"]["generation_id"] == GENERATION


def test_ties_break_by_the_full_entity_key(tmp_path, monkeypatch):
    tied = {"Zeta": (10, 15), "Alfa": (10, 15), "Mid": (20, 25), "Beta": (10, 15), "Low": (50, 40)}

    def build(corpus):
        add_dataset(corpus, "TIEX", [area_dim(list(tied)), time_dim(("2000", "2010")),
                                     unit_dim(UNIT)],
                    [(e, y, UNIT, float(v)) for e, vs in tied.items()
                     for y, v in zip(("2000", "2010"), vs)])
    make_env(tmp_path, monkeypatch, build=build)
    asc = call("compare_periods", dataset="TIEX", entity_columns=["REF_AREA"],
               intervals=[iv("2000", "2010")])
    # Low -10 first; then the +5 tie in key order; rank is ordinal 1..n
    assert [(r["entity"]["REF_AREA"], r["rank"]) for r in rows_of(asc)] == [
        ("Low", 1), ("Alfa", 2), ("Beta", 3), ("Mid", 4), ("Zeta", 5)]
    desc = call("compare_periods", dataset="TIEX", entity_columns=["REF_AREA"],
                intervals=[iv("2000", "2010")], order="desc")
    assert [r["entity"]["REF_AREA"] for r in rows_of(desc)] == ["Alfa", "Beta", "Mid", "Zeta", "Low"]
    pct = call("compare_periods", dataset="TIEX", entity_columns=["REF_AREA"],
               intervals=[iv("2000", "2010")], metric="percent")
    # +50% (Alfa, Beta, Zeta) ties by key; Mid +25%; Low -20% first ascending
    assert [r["entity"]["REF_AREA"] for r in rows_of(pct)] == ["Low", "Mid", "Alfa", "Beta", "Zeta"]
