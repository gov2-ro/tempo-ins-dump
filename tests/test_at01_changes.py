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
    import re
    return ("TIME_PERIOD", "Ani", "time",
            [(y, dict(year=int(m.group(1))) if (m := re.search(r"(\d{4})", y)) else {})
             for y in years])


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


# ------------------------------------------------------------ envelope and size

def test_envelope_validates_and_fits_the_budget(env):
    from app.services.tools import contract
    e = cp(intervals=[iv("1992", "2002"), iv("2010", "2020")], lang="en")
    assert contract.size(e) <= contract.MAX_RESULT_BYTES
    sel = e["provenance"]["selection"]
    assert sel["kind"] == "period_changes" and "lang" not in sel
    assert sel["intervals"] == [iv("1992", "2002"), iv("2010", "2020")]
    # the exact source query is part of the provenance
    sq = e["provenance"]["source_query"]
    assert sq["group_by"] == ["REF_AREA", "TIME_PERIOD"]
    assert sq["filters"] == {"TIME_PERIOD": ["1992", "2002", "2010", "2020"]}
    assert e["provenance"]["effective_selection"]["filters"]["TIME_PERIOD"] == sq["filters"]["TIME_PERIOD"]
    assert e["provenance"]["aggregation"]["outcome"] in ("valid_total", "valid_slice")
    assert e["provenance"]["quality"]["grain"]["status"] == "unique"
    assert e["provenance"]["generation"] == {"id": GENERATION, "status": "present",
                                              "built_at": "2026-10-15T00:00:00+00:00"}
    assert e["provenance"]["sources"][0]["unit"] == UNIT
    assert e["limits"]["time_windowed"] is False and e["limits"]["partial_period_dropped"] is None


def test_json_never_carries_nan_or_inf(env):
    e = cp(intervals=[iv("1992", "2002"), iv("2010", "2020")])
    json.dumps(e, allow_nan=False)
    assert all(r["percent"] is None or r["percent"] == r["percent"]
               for i in e["data"]["intervals"] for r in i["rows"])


# ------------------------------------------------------------ identity: full key

def build_places(corpus):
    names = ["Bihor", "Cluj"]
    add_dataset(corpus, "PLACEX",
                [area_dim(names, col="REF_AREA", label="Judete"),
                 area_dim(["X", "Y"], level="locality", col="REF_AREA_2", label="Localitati"),
                 time_dim(("2000", "2010")), unit_dim(UNIT)],
                [("Cluj", "X", "2000", UNIT, 10.0), ("Cluj", "X", "2010", UNIT, 15.0),
                 ("Bihor", "X", "2000", UNIT, 20.0), ("Bihor", "X", "2010", UNIT, 18.0),
                 ("Cluj", "Y", "2000", UNIT, 5.0), ("Cluj", "Y", "2010", UNIT, 9.0)])


@pytest.fixture
def places(tmp_path, monkeypatch):
    return make_env(tmp_path, monkeypatch, build=build_places)


def test_same_named_localities_stay_separate_with_the_full_key(places):
    e = call("compare_periods", dataset="PLACEX", entity_columns=["REF_AREA", "REF_AREA_2"],
             intervals=[iv("2000", "2010")])
    assert e["status"] == "ok" and e["data"]["key_columns"] == ["REF_AREA", "REF_AREA_2"]
    assert [(r["entity"], r["absolute"], r["rank"]) for r in rows_of(e)] == [
        ({"REF_AREA": "Bihor", "REF_AREA_2": "X"}, -2.0, 1),
        ({"REF_AREA": "Cluj", "REF_AREA_2": "Y"}, 4.0, 2),
        ({"REF_AREA": "Cluj", "REF_AREA_2": "X"}, 5.0, 3)]
    assert any(w["code"] == "boundary_continuity_unverified" for w in e["warnings"])


def test_a_locality_name_alone_is_identity_ambiguous_not_merged(places):
    e = call("compare_periods", dataset="PLACEX", entity_columns=["REF_AREA_2"],
             intervals=[iv("2000", "2010")])
    assert e["status"] == "unavailable" and e["reason"] == "identity_ambiguous"
    assert e["data"] == {} and e["limits"]["returned_rows"] == 0
    assert "REF_AREA" in e["message"]
    rec = e["recovery"][0]
    assert rec["tool"] == "compare_periods"
    assert rec["arguments"]["entity_columns"] == ["REF_AREA", "REF_AREA_2"]
    # the suggestion is a candidate that really works
    again = call("compare_periods", **rec["arguments"])
    assert again["status"] == "ok" and len(rows_of(again)) == 3


def test_locality_alone_proceeds_when_the_name_is_unique_within_the_selection(places):
    e = call("compare_periods", dataset="PLACEX", entity_columns=["REF_AREA_2"],
             intervals=[iv("2000", "2010")], filters={"REF_AREA": ["Cluj"]})
    assert e["status"] == "ok"
    assert e["data"]["entity_columns"] == ["REF_AREA_2"]
    assert e["data"]["key_columns"] == ["REF_AREA", "REF_AREA_2"]       # every component reported
    assert [r["entity"] for r in rows_of(e)] == [{"REF_AREA": "Cluj", "REF_AREA_2": "Y"},
                                                 {"REF_AREA": "Cluj", "REF_AREA_2": "X"}]


def test_nesting_comes_from_dimension_structure_when_present(tmp_path, monkeypatch):
    import duckdb

    def build(corpus):
        add_dataset(corpus, "NESTX",
                    [area_dim(["Cluj", "Bihor"], col="COUNTY", label="Judete"),
                     area_dim(["X", "Y"], level="locality", col="LOCALITY", label="Localitati"),
                     time_dim(("2000", "2010")), unit_dim(UNIT)],
                    [("Cluj", "X", "2000", UNIT, 10.0), ("Cluj", "X", "2010", UNIT, 15.0),
                     ("Bihor", "X", "2000", UNIT, 20.0), ("Bihor", "X", "2010", UNIT, 18.0)])
        db = duckdb.connect(str(corpus / "metadata.duckdb"))
        db.execute("""CREATE TABLE dimension_structure (matrix_code VARCHAR, dim_column VARCHAR,
                      levels VARCHAR, default_level VARCHAR, n_levels INTEGER, aggregate_value VARCHAR,
                      aggregate_verified BOOLEAN, additive BOOLEAN, nests_in VARCHAR,
                      discrimination DOUBLE, dominance DOUBLE, confidence VARCHAR, source VARCHAR)""")
        db.execute("INSERT INTO dimension_structure VALUES ('NESTX', 'LOCALITY', '[]', NULL, 0, "
                   "NULL, FALSE, NULL, 'COUNTY', NULL, NULL, 'flat', 'test')")
        db.close()
    make_env(tmp_path, monkeypatch, build=build)
    e = call("compare_periods", dataset="NESTX", entity_columns=["LOCALITY"],
             intervals=[iv("2000", "2010")])
    assert e["reason"] == "identity_ambiguous"
    assert e["recovery"][0]["arguments"]["entity_columns"] == ["COUNTY", "LOCALITY"]


# ------------------------------------------------------------ the shared policy decides

def build_split(corpus, with_total):
    sexes = ["Total", "Masculin", "Feminin"] if with_total else ["Masculin", "Feminin"]
    rows = []
    for e in ("A", "B"):
        for y, k in (("2000", 1.0), ("2010", 2.0)):
            if with_total:
                rows.append((e, "Total", y, UNIT, 100.0 * k))
            rows += [(e, "Masculin", y, UNIT, 60.0 * k), (e, "Feminin", y, UNIT, 40.0 * k)]
    add_dataset(corpus, "SPLITX", [area_dim(["A", "B"]),
                                   ("SEX", "Sexe", "gender", [(s, dict(gender="x")) for s in sexes]),
                                   time_dim(("2000", "2010")), unit_dim(UNIT)], rows)


def test_a_total_row_is_used_once_not_added_to_its_parts(tmp_path, monkeypatch):
    make_env(tmp_path, monkeypatch, build=lambda c: build_split(c, True))
    e = call("compare_periods", dataset="SPLITX", entity_columns=["REF_AREA"],
             intervals=[iv("2000", "2010")])
    assert [(r["from_value"], r["to_value"], r["absolute"]) for r in rows_of(e)] == [
        (100.0, 200.0, 100.0), (100.0, 200.0, 100.0)]            # 100, not 200
    assert e["provenance"]["effective_selection"]["filters"]["SEX"] == ["Total"]


def test_disjoint_parts_without_a_total_are_summed_once(tmp_path, monkeypatch):
    make_env(tmp_path, monkeypatch, build=lambda c: build_split(c, False))
    e = call("compare_periods", dataset="SPLITX", entity_columns=["REF_AREA"],
             intervals=[iv("2000", "2010")])
    assert [(r["from_value"], r["to_value"]) for r in rows_of(e)] == [(100.0, 200.0)] * 2
    assert e["provenance"]["aggregation"]["method"] == "sum_partition"


def test_a_missing_pin_value_is_the_policys_refusal(tmp_path, monkeypatch):
    make_env(tmp_path, monkeypatch, build=lambda c: build_split(c, True))
    e = call("compare_periods", dataset="SPLITX", entity_columns=["REF_AREA"],
             intervals=[iv("2000", "2010")], filters={"SEX": ["Nope"]})
    assert (e["status"], e["reason"]) == ("unavailable", "slice_value_missing")
    assert e["data"] == {} and e["provenance"]["aggregation"]["blocking_dimension"] == "SEX"
    assert e["recovery"][0]["tool"] == "find_dimension_values"
    assert e["recovery"][0]["arguments"]["column"] == "SEX"


def test_an_entity_value_that_is_not_in_the_data_is_reported(env):
    e = cp(intervals=[iv("2010", "2020")], filters={"REF_AREA": ["Nowhere"]})
    assert (e["status"], e["reason"]) == ("unavailable", "slice_value_missing")
    assert "Nowhere" in e["message"] and e["data"] == {}


def build_units(corpus):
    rows = [(e, y, u, v * m) for e, (a, b) in (("A", (10, 30)), ("B", (20, 25)))
            for u, m in (("Numar persoane", 1), ("Mii persoane", 0.001))
            for y, v in (("2000", a), ("2010", b))]
    add_dataset(corpus, "UNITX", [area_dim(["A", "B"]), time_dim(("2000", "2010")),
                                  unit_dim("Numar persoane", "Mii persoane")], rows)


def test_incompatible_units_are_refused_unless_one_is_pinned(tmp_path, monkeypatch):
    make_env(tmp_path, monkeypatch, build=build_units)
    e = call("compare_periods", dataset="UNITX", entity_columns=["REF_AREA"],
             intervals=[iv("2000", "2010")])
    assert (e["status"], e["reason"]) == ("unavailable", "mixed_units")
    assert e["data"] == {} and e["recovery"][0]["arguments"]["column"] == "UNIT_MEASURE"
    ok = call("compare_periods", dataset="UNITX", entity_columns=["REF_AREA"],
              intervals=[iv("2000", "2010")], filters={"UNIT_MEASURE": ["Mii persoane"]})
    assert ok["status"] == "ok" and ok["data"]["unit"] == "Mii persoane"
    assert [r["absolute"] for r in rows_of(ok)] == [pytest.approx(0.005), pytest.approx(0.02)]


# ------------------------------------------------------------ grain gate

def build_dups(corpus):
    rows = countx_rows()
    rows.append(("A", "2010", UNIT, 7.0))          # the full key (A, 2010) twice
    add_dataset(corpus, "DUPX", [area_dim(list(TABLE)), time_dim(), unit_dim(UNIT)], rows)


def test_a_conflicting_duplicate_key_is_refused_by_the_grain_gate(tmp_path, monkeypatch):
    make_env(tmp_path, monkeypatch, build=build_dups, conflicting=["DUPX"])
    e = call("compare_periods", dataset="DUPX", entity_columns=["REF_AREA"],
             intervals=[iv("2010", "2020")])
    assert (e["status"], e["reason"]) == ("unavailable", "conflicting_grain")
    assert e["data"] == {} and e["limits"]["returned_rows"] == 0
    assert e["provenance"]["aggregation"]["reason"] == "conflicting_grain"
    assert not any("raw" in r["message"].lower() for r in e["recovery"])


def test_a_duplicate_key_with_equal_values_is_refused_too(tmp_path, monkeypatch):
    def build(corpus):
        rows = countx_rows() + [("A", "2010", UNIT, 90.0)]    # same value twice
        add_dataset(corpus, "DUPY", [area_dim(list(TABLE)), time_dim(), unit_dim(UNIT)], rows)
    make_env(tmp_path, monkeypatch, build=build, duplicate=["DUPY"])
    e = call("compare_periods", dataset="DUPY", entity_columns=["REF_AREA"],
             intervals=[iv("2010", "2020")])
    assert (e["status"], e["reason"]) == ("unavailable", "duplicate_keys") and e["data"] == {}


def test_the_slice_check_finds_a_duplicate_the_audit_never_listed(tmp_path, monkeypatch):
    env_ = make_env(tmp_path, monkeypatch, build=build_dups)
    m = json.loads((env_.corpus / "generation-manifest.json").read_text())
    m["audit"]["grain_checked"] = False                         # no certified grain: check the slice
    (env_.corpus / "generation-manifest.json").write_text(json.dumps(m))
    e = call("compare_periods", dataset="DUPX", entity_columns=["REF_AREA"],
             intervals=[iv("2010", "2020")])
    assert (e["status"], e["reason"]) == ("unavailable", "conflicting_grain")
    assert e["provenance"]["quality"]["slice"]["evidence"] == "slice_check"
    # a slice that avoids the duplicated key is allowed
    ok = call("compare_periods", dataset="DUPX", entity_columns=["REF_AREA"],
              intervals=[iv("1992", "2020")], filters={"REF_AREA": ["B", "C"]})
    assert ok["status"] == "ok"


def test_a_repeated_endpoint_key_is_refused_even_when_values_agree():
    from app.services import period_changes as pc
    from app.services.tools.contract import ToolFailure
    with pytest.raises(ToolFailure) as f:
        pc.build_endpoint_table([(("A",), "2000", 5.0), (("A",), "2000", 5.0)])
    assert f.value.reason == "duplicate_keys"
    assert pc.build_endpoint_table([(("A",), "2000", 5.0), (("A",), "2010", 5.0)]) == {
        (("A",), "2000"): 5.0, (("A",), "2010"): 5.0}


# ------------------------------------------------------------ missing, suppressed, negative

def test_a_missing_endpoint_year_is_not_replaced(env):
    e = cp(intervals=[iv("1992", "2005")])
    assert (e["status"], e["reason"]) == ("unavailable", "period_unavailable")
    assert "2005" in e["message"] and "1992 to 2020" in e["message"]
    assert e["data"] == {} and e["recovery"][0]["tool"] == "find_dimension_values"
    assert e["recovery"][0]["arguments"] == {"dataset": "COUNTX", "column": "TIME_PERIOD", "limit": 20}


def test_a_null_value_is_value_missing_not_zero(tmp_path, monkeypatch):
    def build(corpus):
        rows = countx_rows() + [("D", "2002", UNIT, None)]      # suppressed in the source
        add_dataset(corpus, "NULLX", [area_dim(list(TABLE)), time_dim(), unit_dim(UNIT)], rows)
    make_env(tmp_path, monkeypatch, build=build)
    e = call("compare_periods", dataset="NULLX", entity_columns=["REF_AREA"],
             intervals=[iv("1992", "2002")])
    assert e["status"] == "partial"
    x = e["data"]["intervals"][0]["excluded"]
    assert x == [{"entity": {"REF_AREA": "D"}, "reason": "value_missing", "missing": ["to"],
                  "endpoint_reasons": {"to": "value_missing"}}]
    assert "D" not in [r["entity"]["REF_AREA"] for r in rows_of(e)]


def build_negative(corpus):
    add_dataset(corpus, "NEGX", [area_dim(["E", "F"]), time_dim(("2000", "2010")), unit_dim(UNIT)],
                [("E", "2000", UNIT, -10.0), ("E", "2010", UNIT, 5.0),
                 ("F", "2000", UNIT, 10.0), ("F", "2010", UNIT, 20.0)])


def test_a_negative_baseline_has_no_percent(tmp_path, monkeypatch):
    make_env(tmp_path, monkeypatch, build=build_negative)
    ab = call("compare_periods", dataset="NEGX", entity_columns=["REF_AREA"],
              intervals=[iv("2000", "2010")], order="desc")
    by = {r["entity"]["REF_AREA"]: r for r in rows_of(ab)}
    assert by["E"]["absolute"] == 15.0 and by["E"]["percent"] is None
    assert by["E"]["percent_note"] == "nonpositive_baseline"
    assert by["F"]["percent"] == 100.0
    pct = call("compare_periods", dataset="NEGX", entity_columns=["REF_AREA"],
               intervals=[iv("2000", "2010")], metric="percent")
    assert [r["entity"]["REF_AREA"] for r in rows_of(pct)] == ["F"]
    assert pct["data"]["intervals"][0]["exclusion_counts"] == {"nonpositive_baseline": 1}
    assert pct["status"] == "partial"


# ------------------------------------------------------------ unsupported operations

@pytest.mark.parametrize("periods", [("2020-01", "2020-02", "2021-01"), ("2020-Q1", "2020-Q2"),
                                     ("2019", "2020", "2020-Q1")])
def test_monthly_quarterly_and_mixed_periods_are_unsupported(tmp_path, monkeypatch, periods):
    def build(corpus):
        add_dataset(corpus, "MONX", [area_dim(["A"]), time_dim(periods), unit_dim(UNIT)],
                    [("A", p, UNIT, float(i)) for i, p in enumerate(periods)])
    make_env(tmp_path, monkeypatch, build=build)
    e = call("compare_periods", dataset="MONX", entity_columns=["REF_AREA"],
             intervals=[iv("2019", "2020")])
    assert (e["status"], e["reason"]) == ("unavailable", "unsupported_frequency")
    assert e["data"] == {}


def test_legacy_anul_labels_are_annual_periods(tmp_path, monkeypatch):
    def build(corpus):
        labels = ("Anul 2000", "Anul 2010")
        add_dataset(corpus, "LEGX", [area_dim(["A", "B"]), time_dim(labels), unit_dim(UNIT)],
                    [("A", "Anul 2000", UNIT, 10.0), ("A", "Anul 2010", UNIT, 12.0),
                     ("B", "Anul 2000", UNIT, 5.0), ("B", "Anul 2010", UNIT, 4.0)])
    make_env(tmp_path, monkeypatch, build=build)
    e = call("compare_periods", dataset="LEGX", entity_columns=["REF_AREA"],
             intervals=[iv("2000", "2010")])
    assert e["status"] == "ok"
    assert [(r["entity"]["REF_AREA"], r["absolute"]) for r in rows_of(e)] == [("B", -1.0), ("A", 2.0)]
    assert e["provenance"]["source_query"]["filters"]["TIME_PERIOD"] == ["Anul 2000", "Anul 2010"]


def test_a_rate_is_an_unsupported_measure(tmp_path, monkeypatch):
    def build(corpus):
        add_dataset(corpus, "RATEZ", [area_dim(["A", "B"]), time_dim(("2000", "2010")),
                                      unit_dim("Procente")],
                    [(e, y, "Procente", v) for e, y, v in
                     (("A", "2000", 5.0), ("A", "2010", 6.0), ("B", "2000", 7.0), ("B", "2010", 8.0))],
                    unit_type="percentage", name="Rata somajului")
    make_env(tmp_path, monkeypatch, build=build)
    e = call("compare_periods", dataset="RATEZ", entity_columns=["REF_AREA"],
             intervals=[iv("2000", "2010")])
    assert (e["status"], e["reason"]) == ("unavailable", "unsupported_measure")
    assert "non_additive" in e["message"] and "percentage" in e["message"]
    assert e["data"] == {} and e["recovery"][0]["tool"] == "discover_indicators"
    assert e["recovery"][0]["arguments"]["query"] == "Rata somajului"


def test_source_cap_refuses_instead_of_ranking_a_capped_input(env, monkeypatch):
    import app.config
    monkeypatch.setattr(app.config, "MAX_DATA_ROWS", 2)
    e = cp(intervals=[iv("2010", "2020")])
    assert (e["status"], e["reason"]) == ("unavailable", "source_incomplete")
    assert e["data"] == {} and e["limits"]["returned_rows"] == 0
    assert e["recovery"][0]["kind"] == "narrow"


def test_a_missing_manifest_cannot_certify_anything(tmp_path, monkeypatch):
    make_env(tmp_path, monkeypatch, build=build_countx, generation_id=None)
    e = call("compare_periods", dataset="COUNTX", entity_columns=["REF_AREA"],
             intervals=[iv("2010", "2020")])
    assert (e["status"], e["reason"]) == ("unavailable", "generation_unverified")
    assert e["data"] == {} and e["provenance"]["generation"]["status"] == "missing"


def test_unknown_dataset_and_unknown_columns(env):
    e = call("compare_periods", dataset="NOPEX", entity_columns=["REF_AREA"],
             intervals=[iv("2010", "2020")])
    assert (e["status"], e["reason"]) == ("error", "unknown_dataset")
    e = cp(entity_columns=["NOPE"], intervals=[iv("2010", "2020")])
    assert (e["status"], e["reason"]) == ("error", "unknown_column")
    e = cp(intervals=[iv("2010", "2020")], filters={"NOPE": ["a"]})
    assert (e["status"], e["reason"]) == ("error", "unknown_column")
    assert e["recovery"][0]["tool"] == "describe_dataset"


# ------------------------------------------------------------ aggregates, levels, notes

def build_totals(corpus):
    rows = [("TOTAL", "2000", UNIT, 30.0), ("TOTAL", "2010", UNIT, 36.0),
            ("A", "2000", UNIT, 10.0), ("A", "2010", UNIT, 11.0),
            ("B", "2000", UNIT, 20.0), ("B", "2010", UNIT, 25.0)]
    add_dataset(corpus, "TOTX", [
        ("REF_AREA", "Judete", "geo", [("TOTAL", dict(geo_level="national")),
                                       ("A", dict(geo_level="county")), ("B", dict(geo_level="county"))]),
        time_dim(("2000", "2010")), unit_dim(UNIT)], rows)


def test_a_total_row_is_never_ranked_among_its_own_parts(tmp_path, monkeypatch):
    make_env(tmp_path, monkeypatch, build=build_totals)
    e = call("compare_periods", dataset="TOTX", entity_columns=["REF_AREA"],
             intervals=[iv("2000", "2010")])
    assert [(r["entity"]["REF_AREA"], r["rank"]) for r in rows_of(e)] == [("A", 1), ("B", 2)]
    assert e["status"] == "partial"
    assert e["data"]["intervals"][0]["excluded"] == [
        {"entity": {"REF_AREA": "TOTAL"}, "reason": "aggregate_row", "missing": []}]
    only = call("compare_periods", dataset="TOTX", entity_columns=["REF_AREA"],
                intervals=[iv("2000", "2010")], filters={"REF_AREA": ["TOTAL"]})
    assert only["status"] == "ok"                       # an explicit total-only series is valid
    assert [(r["entity"]["REF_AREA"], r["absolute"]) for r in rows_of(only)] == [("TOTAL", 6.0)]


def test_mixed_levels_on_an_entity_column_are_refused(tmp_path, monkeypatch):
    def build(corpus):
        add_dataset(corpus, "LVLX", [
            ("REF_AREA", "Zone", "geo", [("A", dict(geo_level="county")),
                                         ("Regiunea R", dict(geo_level="region"))]),
            time_dim(("2000", "2010")), unit_dim(UNIT)],
            [("A", "2000", UNIT, 1.0), ("A", "2010", UNIT, 2.0),
             ("Regiunea R", "2000", UNIT, 5.0), ("Regiunea R", "2010", UNIT, 6.0)])
    make_env(tmp_path, monkeypatch, build=build)
    e = call("compare_periods", dataset="LVLX", entity_columns=["REF_AREA"],
             intervals=[iv("2000", "2010")])
    assert (e["status"], e["reason"]) == ("unavailable", "overlapping_levels")
    assert e["data"] == {}
    ok = call("compare_periods", dataset="LVLX", entity_columns=["REF_AREA"],
              intervals=[iv("2000", "2010")], filters={"REF_AREA": ["A"]})
    assert ok["status"] == "ok"


def test_series_breaks_and_definition_notes_are_warnings(tmp_path, monkeypatch):
    # TUR105D has curated notes (a series break between 2020 and 2021, a coverage note)
    def build(corpus):
        add_dataset(corpus, "TUR105D", [area_dim(["A"]), time_dim(("2019", "2022")), unit_dim(UNIT)],
                    [("A", "2019", UNIT, 5.0), ("A", "2022", UNIT, 9.0)])
    make_env(tmp_path, monkeypatch, build=build)
    e = call("compare_periods", dataset="TUR105D", entity_columns=["REF_AREA"],
             intervals=[iv("2019", "2022")])
    w = {x["code"]: x for x in e["warnings"]}
    assert "Inside the compared interval 2019→2022" in w["series_break"]["message"]
    assert w["series_break"]["subject"] == "TUR105D-rented-rooms"
    assert "coverage_note" in w
    assert e["provenance"]["sources"][0]["notes"]


@pytest.mark.parametrize("definition,expect", [
    ("Populatia cu domiciliul in localitate la 1 iulie", "domicile (domiciliu)"),
    ("Populatia stabila a localitatii", "resident (usual residence)"),
    ("Populatia localitatii", "does not say whether it counts domicile or usual residence"),
])
def test_population_definition_is_stated_not_guessed(tmp_path, monkeypatch, definition, expect):
    def build(corpus):
        add_dataset(corpus, "POPZ", [area_dim(["A", "B"]), time_dim(("2000", "2010")),
                                     unit_dim(UNIT)],
                    [(e, y, UNIT, v) for e, y, v in (("A", "2000", 1.0), ("A", "2010", 2.0),
                                                     ("B", "2000", 3.0), ("B", "2010", 2.0))],
                    definition=definition, name="Populatie")
    make_env(tmp_path, monkeypatch, build=build)
    e = call("compare_periods", dataset="POPZ", entity_columns=["REF_AREA"],
             intervals=[iv("2000", "2010")])
    w = next(x for x in e["warnings"] if x["code"] == "boundary_continuity_unverified")
    assert expect in w["message"] and "unchanged territory" in w["message"]


def test_a_non_geographic_entity_gets_no_boundary_warning(tmp_path, monkeypatch):
    def build(corpus):
        add_dataset(corpus, "CATX", [("CATEGORY", "Categorie", None, [("P", {}), ("Q", {})]),
                                     time_dim(("2000", "2010")), unit_dim(UNIT)],
                    [("P", "2000", UNIT, 1.0), ("P", "2010", UNIT, 3.0),
                     ("Q", "2000", UNIT, 2.0), ("Q", "2010", UNIT, 2.0)])
    make_env(tmp_path, monkeypatch, build=build)
    e = call("compare_periods", dataset="CATX", entity_columns=["CATEGORY"],
             intervals=[iv("2000", "2010")])
    assert e["status"] == "ok"
    assert not any(w["code"] == "boundary_continuity_unverified" for w in e["warnings"])


def test_multi_interval_exclusions_are_per_interval(env):
    e = cp(intervals=[iv("1992", "2002"), iv("1992", "2010"), iv("2002", "2020")])
    counts = [(i["eligible_count"], i["excluded_count"]) for i in e["data"]["intervals"]]
    assert counts == [(3, 1), (4, 0), (3, 1)]
    assert e["data"]["intervals"][2]["excluded"][0]["missing"] == ["from"]
