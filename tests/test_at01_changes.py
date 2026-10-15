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

import pytest

from at01_fixtures import GENERATION, add_dataset, call, make_env

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


def test_profiled_flat_categories_sum_once_and_unprofiled_ones_are_refused(tmp_path, monkeypatch):
    import duckdb

    def build(corpus, profiled):
        rows = [(e, c, y, UNIT, v * k) for e in ("A", "B") for y, k in (("2000", 1.0), ("2010", 2.0))
                for c, v in (("Parte 1", 60.0), ("Parte 2", 40.0))]
        add_dataset(corpus, "CATSUM", [area_dim(["A", "B"]),
                                       ("CATEGORY", "Categorie", None, [("Parte 1", {}), ("Parte 2", {})]),
                                       time_dim(("2000", "2010")), unit_dim(UNIT)], rows)
        if profiled:
            db = duckdb.connect(str(corpus / "metadata.duckdb"))
            db.execute("""CREATE TABLE dimension_structure (matrix_code VARCHAR, dim_column VARCHAR,
                          levels VARCHAR, default_level VARCHAR, n_levels INTEGER,
                          aggregate_value VARCHAR, aggregate_verified BOOLEAN, additive BOOLEAN,
                          nests_in VARCHAR, discrimination DOUBLE, dominance DOUBLE,
                          confidence VARCHAR, source VARCHAR)""")
            db.execute("INSERT INTO dimension_structure VALUES ('CATSUM', 'CATEGORY', '[]', 'all', 0, "
                       "NULL, FALSE, NULL, NULL, NULL, NULL, 'flat', 'test')")
            db.close()
    make_env(tmp_path / "flat", monkeypatch, build=lambda c: build(c, True))
    e = call("compare_periods", dataset="CATSUM", entity_columns=["REF_AREA"],
             intervals=[iv("2000", "2010")])
    assert [(r["from_value"], r["to_value"]) for r in rows_of(e)] == [(100.0, 200.0)] * 2   # 60 + 40
    make_env(tmp_path / "unprofiled", monkeypatch, build=lambda c: build(c, False))
    e = call("compare_periods", dataset="CATSUM", entity_columns=["REF_AREA"],
             intervals=[iv("2000", "2010")])
    assert (e["status"], e["reason"]) == ("unavailable", "unverified_structure")   # never guessed
    assert e["data"] == {} and e["recovery"][0]["arguments"]["column"] == "CATEGORY"


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


def test_a_split_parent_without_a_data_file_points_at_its_children(tmp_path, monkeypatch):
    def build(corpus):
        add_dataset(corpus, "PARENTX", [area_dim(["A"]), time_dim(("2000", "2010")), unit_dim(UNIT)],
                    [], file=False)
    make_env(tmp_path, monkeypatch, build=build)
    e = call("compare_periods", dataset="PARENTX", entity_columns=["REF_AREA"],
             intervals=[iv("2000", "2010")])
    assert (e["status"], e["reason"]) == ("error", "unknown_dataset")
    assert "sub-datasets" in e["message"] and e["recovery"][0]["tool"] == "describe_dataset"
    assert "/" not in e["message"].replace("sub-datasets", "")          # no filesystem path


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


@pytest.mark.parametrize("name,definition,expect", [
    ("POPULATIA DUPA DOMICILIU la 1 ianuarie pe judete", "Populatia dupa domiciliu reprezinta persoanele cu "
     "domiciliu in tara; nu se tine cont de resedinta obisnuita.", "domicile (domiciliu) population"),
    ("Populatia rezidenta la 1 ianuarie pe medii de rezidenta", "Populatia rezidenta reprezinta persoanele "
     "care au resedinta obisnuita; poate sa fie aceeasi cu domiciliul.", "resident (usual residence)"),
    ("Populatie pe judete", "Populatia localitatii", "does not say whether it counts domicile"),
    ("Numar de unitati", "Unitati locale active", None),
])
def test_population_definition_is_stated_not_guessed(tmp_path, monkeypatch, name, definition, expect):
    def build(corpus):
        add_dataset(corpus, "POPZ", [area_dim(["A", "B"]), time_dim(("2000", "2010")),
                                     unit_dim(UNIT)],
                    [(e, y, UNIT, v) for e, y, v in (("A", "2000", 1.0), ("A", "2010", 2.0),
                                                     ("B", "2000", 3.0), ("B", "2010", 2.0))],
                    definition=definition, name=name)
    make_env(tmp_path, monkeypatch, build=build)
    e = call("compare_periods", dataset="POPZ", entity_columns=["REF_AREA"],
             intervals=[iv("2000", "2010")])
    w = next(x for x in e["warnings"] if x["code"] == "boundary_continuity_unverified")
    assert "unchanged territory" in w["message"]
    if expect:
        assert expect in w["message"]
    else:
        assert "domicile" not in w["message"] and "resident" not in w["message"]


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


# ------------------------------------------------------------ the byte budget

def build_many(corpus, n=300, nulls=40):
    """300 entities with long Romanian names; the last `nulls` have a suppressed 2010 value."""
    names = [f"Comuna Șugătag-Câmpulung între Dunăre și Prutul de Sus nr. {i:04d}" for i in range(n)]
    rows = []
    for i, name in enumerate(names):
        rows.append((name, "2000", UNIT, 1000.0 + i))
        rows.append((name, "2010", UNIT, None if i >= n - nulls else 1000.0 + i * 3 - 200))
        rows.append((name, "2020", UNIT, 1500.0 + i * 7))
    add_dataset(corpus, "MANYX", [area_dim(names), time_dim(("2000", "2010", "2020")),
                                  unit_dim(UNIT)], rows)
    return names


@pytest.fixture
def many(tmp_path, monkeypatch):
    names = []
    env_ = make_env(tmp_path, monkeypatch, build=lambda c: names.extend(build_many(c)))
    env_.names = names
    return env_


def test_a_large_result_is_shortened_to_the_budget_without_losing_counts_or_warnings(many):
    from app.services.tools import contract
    e = call("compare_periods", dataset="MANYX", entity_columns=["REF_AREA"],
             intervals=[iv("2000", "2010"), iv("2000", "2020")], top_k=100)
    assert contract.size(e) <= contract.MAX_RESULT_BYTES
    first, second = e["data"]["intervals"]
    assert (first["eligible_count"], first["excluded_count"]) == (260, 40)      # every entity counted
    assert (second["eligible_count"], second["excluded_count"]) == (300, 0)
    assert first["exclusion_counts"] == {"value_missing": 40}
    assert first["exclusions_truncated"] is True and len(first["excluded"]) < 40
    for i in (first, second):
        assert 0 < len(i["rows"]) < 100
        assert [r["rank"] for r in i["rows"]] == list(range(1, len(i["rows"]) + 1))   # a ranking prefix
    assert e["limits"]["preview_truncated"] is True
    assert e["limits"]["returned_rows"] == len(first["rows"]) + len(second["rows"])
    assert e["limits"]["total_rows"] == 560
    assert sum(w["code"] == "preview_shortened" for w in e["warnings"]) == 1
    assert {"entities_excluded", "boundary_continuity_unverified"} <= {w["code"] for w in e["warnings"]}
    assert e["recovery"][0]["tool"] == "get_evidence_links"
    # provenance is untouched by the shortening
    assert e["provenance"]["source_query"]["group_by"] == ["REF_AREA", "TIME_PERIOD"]
    assert e["provenance"]["sources"][0]["unit"] == UNIT


def test_the_table_never_exceeds_the_model_visible_row_cap(tmp_path, monkeypatch):
    from app.services.tools import contract
    names = [f"E{i:03d}" for i in range(150)]

    def build(corpus):
        add_dataset(corpus, "WIDEX", [area_dim(names), time_dim(("2000", "2005", "2010", "2020")),
                                      unit_dim(UNIT)],
                    [(n, y, UNIT, float(i * (k + 1))) for i, n in enumerate(names)
                     for k, y in enumerate(("2000", "2005", "2010", "2020"))])
    make_env(tmp_path, monkeypatch, build=build)
    e = call("compare_periods", dataset="WIDEX", entity_columns=["REF_AREA"], top_k=100,
             intervals=[iv("2000", "2005"), iv("2000", "2010"), iv("2000", "2020"), iv("2005", "2020")])
    assert [len(i["rows"]) for i in e["data"]["intervals"]] == [50] * 4
    assert e["limits"]["returned_rows"] == 200 <= contract.MAX_TABLE_ROWS
    assert e["limits"]["total_rows"] == 600 and e["limits"]["preview_truncated"] is True


def test_shrink_cuts_exclusion_samples_first_then_rows_then_reports_nothing_left():
    from app.services.tools import changes, contract
    rows = [{"entity": {"A": str(i)}, "from_value": 1.0, "to_value": 2.0, "absolute": 1.0,
             "percent": 100.0, "rank": i + 1} for i in range(8)]
    env_ = {"data": {"intervals": [{"from": "2000", "to": "2010", "rows": list(rows),
                                    "eligible_count": 8, "excluded_count": 4,
                                    "excluded": [{"entity": {"A": "x"}, "reason": "no_observation",
                                                  "missing": ["to"]}] * 4,
                                    "exclusion_counts": {"no_observation": 4},
                                    "exclusions_truncated": False}]},
            "limits": {"returned_rows": 8, "preview_truncated": False}, "warnings": [],
            "recovery": [], "provenance": {"selection": None, "generation": {"id": "g"}}}
    iv0 = env_["data"]["intervals"][0]
    steps = 0
    while changes.shrink(env_):
        steps += 1
        if iv0["excluded"]:
            assert len(iv0["rows"]) == 8                          # samples go first
    assert iv0["excluded"] == [] and iv0["exclusions_truncated"] is True
    assert len(iv0["rows"]) == 1 and iv0["rows"][0]["rank"] == 1  # then rows, halved to one
    assert env_["limits"]["returned_rows"] == 1 and env_["limits"]["preview_truncated"] is True
    assert iv0["eligible_count"] == 8 and iv0["excluded_count"] == 4
    assert [w["code"] for w in env_["warnings"]] == ["preview_shortened"]    # once
    assert steps == 6                                             # samples 4->2->1->0, rows 8->4->2->1
    assert changes.shrink(env_) is False
    assert contract.size(env_) < 2000


def test_a_selection_that_cannot_fit_gets_response_budget(many, monkeypatch):
    from app.services.tools import changes
    monkeypatch.setattr(changes, "shrink", lambda env: False)
    e = call("compare_periods", dataset="MANYX", entity_columns=["REF_AREA"],
             intervals=[iv("2000", "2010"), iv("2000", "2020")], top_k=100)
    assert (e["status"], e["reason"]) == ("unavailable", "response_budget")
    assert e["data"]["request"]["sha256"] and e["provenance"]["selection"] is None


# ------------------------------------------------------------ routes

def params(**kw):
    p = {"dataset": "COUNTX", "entity_columns": json.dumps(["REF_AREA"]),
         "intervals": json.dumps([iv("1992", "2002"), iv("2010", "2020")])}
    for k, v in kw.items():
        p[k] = v if isinstance(v, str) else json.dumps(v)
    return p


def test_json_route_returns_the_tool_envelope(env):
    from app.services.tools import registry
    r = env.client.get("/api/period-changes", params=params(top_k="2", metric="percent"))
    assert r.status_code == 200
    body = r.json()
    direct = registry.call_tool("compare_periods", {
        "dataset": "COUNTX", "entity_columns": ["REF_AREA"],
        "intervals": [iv("1992", "2002"), iv("2010", "2020")], "top_k": 2, "metric": "percent"})
    registry.validate_result("compare_periods", body)
    assert body == direct
    assert [[r_["entity"]["REF_AREA"] for r_ in i["rows"]] for i in body["data"]["intervals"]] == [
        ["B", "A"], ["D", "A"]]


def test_json_route_filters_and_status_codes(env):
    ok = env.client.get("/api/period-changes", params=params(filters={"REF_AREA": ["A", "B"]}))
    assert ok.status_code == 200 and len(ok.json()["data"]["intervals"][0]["rows"]) == 2
    # refusals are ordinary 200 outcomes
    r = env.client.get("/api/period-changes", params={**params(), "intervals": json.dumps([iv("1992", "2005")])})
    assert r.status_code == 200 and r.json()["reason"] == "period_unavailable"
    # malformed or invalid input -> 400 with the envelope
    for bad in (params(entity_columns="not json"), params(top_k="abc"), params(top_k="0"),
                params(metric="median"), params(lang="fr"),
                {k: v for k, v in params().items() if k != "entity_columns"},
                {**params(), "intervals": json.dumps([iv("2020", "2010")])}):
        r = env.client.get("/api/period-changes", params=bad)
        assert r.status_code == 400, bad
        assert r.json()["reason"] == "invalid_input" and r.json()["contract"] == "tempo-tools/1"
    r = env.client.get("/api/period-changes", params=params(entity_columns=["NOPE"]))
    assert r.status_code == 400 and r.json()["reason"] == "unknown_column"
    r = env.client.get("/api/period-changes", params={**params(), "dataset": "NOPEX"})
    assert r.status_code == 404 and r.json()["reason"] == "unknown_dataset"


def test_json_route_server_fault_is_500_with_an_envelope(env, monkeypatch):
    from app.services import period_changes
    monkeypatch.setattr(period_changes, "run", lambda *a, **k: 1 / 0)
    r = env.client.get("/api/period-changes", params=params())
    assert r.status_code == 500 and r.json()["reason"] == "execution_failed"
    assert "division" not in r.text and "Traceback" not in r.text


# ------------------------------------------------------------ evidence bundle

def open_zip(data):
    z = zipfile.ZipFile(io.BytesIO(data))
    m = json.loads(z.read("manifest.json"))
    for name, h in m["files"].items():
        assert hashlib.sha256(z.read(name)).hexdigest() == h, name
    assert sorted(m["files"]) == sorted(n for n in z.namelist() if n != "manifest.json")
    return z, m


def recompute(directory):
    return subprocess.run([sys.executable, "-I", "recompute.py"], cwd=directory, capture_output=True,
                          text=True, timeout=60)


def get_zip(env_, **kw):
    r = env_.client.get("/api/period-changes/evidence", params=params(**kw))
    assert r.status_code == 200, r.text
    assert r.headers["content-type"] == "application/zip"
    return r


def test_bundle_holds_the_complete_ranking_and_recomputes_offline(env, tmp_path):
    r = get_zip(env, top_k="1")                                  # the preview is 1 row; the bundle has all
    z, m = open_zip(r.content)
    assert m["schema"] == "tempo-evidence/1" and m["kind"] == "period_changes"
    assert m["generation"]["id"] == GENERATION and m["dataset"] == "COUNTX"
    assert sorted(z.namelist()) == sorted([
        "manifest.json", "selection.json", "result.csv", "exclusions.csv", "inputs/endpoints.csv",
        "method.json", "attribution.json", "README.txt", "recompute.py"])
    res = list(csv.reader(io.StringIO(z.read("result.csv").decode())))
    assert res[0] == ["interval_from", "interval_to", "rank", "REF_AREA", "from_value", "to_value",
                      "absolute", "percent", "percent_note"]
    assert [(x[0], x[1], x[2], x[3], x[6]) for x in res[1:]] == [
        ("1992", "2002", "1", "B", "-50.0"), ("1992", "2002", "2", "A", "-20.0"),
        ("1992", "2002", "3", "C", "0.0"),
        ("2010", "2020", "1", "D", "-90.0"), ("2010", "2020", "2", "A", "-30.0"),
        ("2010", "2020", "3", "B", "-20.0"), ("2010", "2020", "4", "C", "5.0")]
    c_row = next(x for x in res[1:] if x[1] == "2020" and x[3] == "C")
    assert c_row[7] == "" and c_row[8] == "zero_baseline"
    assert [x[7] for x in res[1:] if x[3] == "A"] == ["-20.0", repr(100 * -30.0 / 90.0)]
    exc = list(csv.reader(io.StringIO(z.read("exclusions.csv").decode())))
    assert exc[1:] == [["1992", "2002", "D", "no_observation", "to", "", "", ""]]
    ep = list(csv.reader(io.StringIO(z.read("inputs/endpoints.csv").decode())))
    assert ep[0] == ["REF_AREA", "year", "value"] and ["D", "2002", ""] not in ep
    assert ["A", "1992", "100.0"] in ep and len(ep) == 1 + 15            # 4 years x 4 entities - D's 2002
    sel = json.loads(z.read("selection.json"))
    assert sel["source_query"]["group_by"] == ["REF_AREA", "TIME_PERIOD"]
    assert sel["normalized"]["kind"] == "period_changes" and sel["link"].startswith("/api/period-changes?")
    method = json.loads(z.read("method.json"))
    assert method["formulas"]["percent"].endswith("only when from_value > 0")
    assert method["ranking"]["tie_break"].startswith("full entity key")
    assert method["aggregation"]["outcome"] in ("valid_total", "valid_slice")
    assert "NOT raw INS observations" in z.read("README.txt").decode()
    # offline recomputation
    out = tmp_path / "bundle"
    z.extractall(out)
    p = recompute(out)
    assert p.returncode == 0, p.stderr
    assert "1992,2002,1,B,-50.0,-25.0" in p.stdout and "2010,2020,1,D,-90.0,-100.0" in p.stdout
    assert "result.csv matches" in p.stderr and "exclusions.csv matches" in p.stderr


def test_percent_bundle_recomputes_with_baseline_exclusions(env, tmp_path):
    z, _ = open_zip(get_zip(env, metric="percent", order="desc").content)
    exc = list(csv.reader(io.StringIO(z.read("exclusions.csv").decode())))
    assert ["2010", "2020", "C", "zero_baseline", "", "0.0", "5.0", "5.0"] in exc
    z.extractall(tmp_path)
    assert recompute(tmp_path).returncode == 0


def test_tampering_with_the_bundle_is_detected(env, tmp_path):
    z, _ = open_zip(get_zip(env).content)
    z.extractall(tmp_path)
    p = tmp_path / "result.csv"
    text = p.read_text()
    assert "-50.0" in text
    p.write_text(text.replace("-50.0", "-49.0", 1))
    r = recompute(tmp_path)
    assert r.returncode == 1 and "result.csv DIFFERS" in r.stderr
    p.write_text(text)
    assert recompute(tmp_path).returncode == 0
    e = tmp_path / "inputs" / "endpoints.csv"
    e.write_text(e.read_text().replace("B,1992,200.0", "B,1992,300.0"))   # the inputs changed
    assert recompute(tmp_path).returncode == 1


def test_bundle_for_a_large_selection_has_every_row_and_exclusion(many, tmp_path):
    r = many.client.get("/api/period-changes/evidence", params={
        "dataset": "MANYX", "entity_columns": json.dumps(["REF_AREA"]),
        "intervals": json.dumps([iv("2000", "2010")]), "top_k": "5"})
    assert r.status_code == 200
    z, _ = open_zip(r.content)
    res = list(csv.reader(io.StringIO(z.read("result.csv").decode())))
    exc = list(csv.reader(io.StringIO(z.read("exclusions.csv").decode())))
    assert len(res) - 1 == 260 and len(exc) - 1 == 40
    assert {x[3] for x in exc[1:]} == {"value_missing"}
    z.extractall(tmp_path)
    assert recompute(tmp_path).returncode == 0
    # the tool preview of the same request carries far fewer rows and says so
    t = call("compare_periods", dataset="MANYX", entity_columns=["REF_AREA"],
             intervals=[iv("2000", "2010")], top_k=5)
    assert len(t["data"]["intervals"][0]["rows"]) == 5 and t["limits"]["total_rows"] == 260


def test_localities_bundle_keeps_every_key_column(places, tmp_path):
    r = places.client.get("/api/period-changes/evidence", params={
        "dataset": "PLACEX", "entity_columns": json.dumps(["REF_AREA_2"]),
        "intervals": json.dumps([iv("2000", "2010")]), "filters": json.dumps({"REF_AREA": ["Cluj"]})})
    z, _ = open_zip(r.content)
    assert z.read("result.csv").decode().splitlines()[0].split(",")[3:5] == ["REF_AREA", "REF_AREA_2"]
    z.extractall(tmp_path)
    assert recompute(tmp_path).returncode == 0


def test_evidence_route_refuses_what_is_not_certifiable(env, tmp_path, monkeypatch):
    r = env.client.get("/api/period-changes/evidence",
                       params={**params(), "intervals": json.dumps([iv("1992", "2005")])})
    assert r.status_code == 422 and r.json()["detail"]["reason"] == "period_unavailable"
    assert r.headers["content-type"].startswith("application/json")
    r = env.client.get("/api/period-changes/evidence", params=params(entity_columns=["NOPE"]))
    assert r.status_code == 400 and r.json()["detail"]["reason"] == "unknown_column"
    r = env.client.get("/api/period-changes/evidence", params={**params(), "dataset": "NOPEX"})
    assert r.status_code == 404
    r = env.client.get("/api/period-changes/evidence", params=params(top_k="0"))
    assert r.status_code == 400 and r.json()["detail"]["reason"] == "invalid_input"
    r = env.client.get("/api/period-changes/evidence", params=params(entity_columns="[oops"))
    assert r.status_code == 400
    # nothing to rank: no bundle
    r = env.client.get("/api/period-changes/evidence", params={
        **params(), "intervals": json.dumps([iv("1992", "2002")]),
        "filters": json.dumps({"REF_AREA": ["D"]})})
    assert r.status_code == 422 and r.json()["detail"]["reason"] == "no_eligible_entities"


def test_evidence_route_413_when_the_endpoint_table_is_too_large(env, monkeypatch):
    from app.services import evidence
    monkeypatch.setattr(evidence, "MAX_INPUT_ROWS", 3)
    r = env.client.get("/api/period-changes/evidence", params=params())
    assert r.status_code == 413 and r.json()["detail"]["reason"] == "bundle_too_large"


def test_evidence_route_uses_the_export_slots(env, monkeypatch):
    from app.services import export
    assert export._active["all"] == 0
    r = env.client.get("/api/period-changes/evidence", params={
        **params(), "intervals": json.dumps([iv("1992", "2005")])})     # a 422 still frees its slot
    assert r.status_code == 422 and export._active["all"] == 0
    monkeypatch.setattr(export, "try_acquire", lambda kind: None)
    r = env.client.get("/api/period-changes/evidence", params=params())
    assert r.status_code == 503 and r.headers["retry-after"] == "15"


def test_expected_generation_is_checked_before_and_after(env, monkeypatch):
    from app.services import change_evidence
    ok = get_zip(env, expected_generation=GENERATION)
    assert json.loads(zipfile.ZipFile(io.BytesIO(ok.content)).read("manifest.json"))["generation"]["id"] == GENERATION
    r = env.client.get("/api/period-changes/evidence", params=params(expected_generation="gen-old"))
    assert r.status_code == 409
    d = r.json()["detail"]
    assert d["reason"] == "generation_changed" and d["expected_generation"] == "gen-old"
    assert d["served_generation"] == GENERATION
    assert r.headers["content-type"].startswith("application/json")          # no ZIP

    real = change_evidence.bundle

    def swap_generation(result, link=None):
        data = real(result, link)
        p = env.corpus / "generation-manifest.json"
        m = json.loads(p.read_text())
        m["generation_id"] = "gen-swapped-during-build"
        p.write_text(json.dumps(m))
        return data
    monkeypatch.setattr(change_evidence, "bundle", swap_generation)
    r = env.client.get("/api/period-changes/evidence", params=params(expected_generation=GENERATION))
    assert r.status_code == 409 and r.json()["detail"]["reason"] == "generation_changed"
    assert r.json()["detail"]["served_generation"] == "gen-swapped-during-build"


def test_a_generation_swapped_mid_build_is_refused_without_an_expectation_too(env, monkeypatch):
    from app.services import change_evidence
    real = change_evidence.bundle

    def swap(result, link=None):
        data = real(result, link)
        p = env.corpus / "generation-manifest.json"
        m = json.loads(p.read_text())
        m["generation_id"] = "gen-other"
        p.write_text(json.dumps(m))
        return data
    monkeypatch.setattr(change_evidence, "bundle", swap)
    r = env.client.get("/api/period-changes/evidence", params=params())
    assert r.status_code == 409 and r.json()["detail"]["reason"] == "generation_changed"


def test_bundle_link_is_none_when_the_url_would_exceed_4_kib(env):
    from app.services import change_evidence
    a = {"dataset": "COUNTX", "entity_columns": ["REF_AREA"], "intervals": [iv("1992", "2002")],
         "filters": {"REF_AREA": [f"Entity number {i} with a long label" for i in range(200)]},
         "metric": "absolute", "order": "asc", "top_k": 20, "lang": "ro"}
    assert change_evidence.live_link(a) is None                  # never a shorter, different selection
    short = {**a, "filters": {}}
    url = change_evidence.live_link(short, evidence=True, expected_generation="g1")
    assert url.startswith("/api/period-changes/evidence?") and "expected_generation=g1" in url
    from urllib.parse import parse_qs, urlparse
    q = parse_qs(urlparse(url).query)
    assert json.loads(q["intervals"][0]) == [iv("1992", "2002")] and "filters" not in q


# ------------------------------------------------------------ scope (shared run_query scope metadata)

def test_a_restricted_source_scope_makes_the_result_partial(env, monkeypatch):
    """run_query reports a restricted domain (e.g. single ages 0-84 without 85+) as
    `scope`; the comparison must carry it and not present itself as complete."""
    import app.services.data_query as dq
    real = dq.run_query

    def with_scope(*a, **k):
        res = real(*a, **k)
        res["scope"] = {"domain_complete": False, "restrictions": [
            {"kind": "age_range", "column": "AGE", "covered": [[0, 84]], "domain": [0, None],
             "requested": False}]}
        return res
    monkeypatch.setattr(dq, "run_query", with_scope)
    e = cp(intervals=[iv("2010", "2020")], lang="en")
    assert e["status"] == "partial" and e["reason"] == "incomplete_domain"
    sc = e["provenance"]["scope"]
    assert sc["domain_complete"] is False and "0–84" in sc["description"]
    assert sc["limitations"][0]["code"] == "age_range_restricted"
    assert "Restricted domain: Ages 0–84" in e["message"]
    assert len(rows_of(e)) == 4                                   # still ranked, with the limit stated


# ------------------------------------------------------------ real corpus (read-only, generation-pinned)

PINNED = "9b3e065d"


@pytest.fixture
def real():
    from app.services import generation
    if not (generation.current().get("id") or "").startswith(PINNED):
        pytest.skip("probe numbers are for corpus generation 9b3e065d")


@pytest.mark.corpus
def test_real_counties_bundle_recomputes_offline(real, tmp_path):
    from fastapi.testclient import TestClient
    from app.main import app
    p = {"dataset": "POP105A", "entity_columns": json.dumps(["REF_AREA"]),
         "intervals": json.dumps([iv("2012", "2021")]), "top_k": "3"}
    t = TestClient(app).get("/api/period-changes", params=p).json()
    i = t["data"]["intervals"][0]
    assert t["status"] == "ok" and i["eligible_count"] == 42 and i["excluded_count"] == 0
    top = i["rows"][0]
    assert (top["entity"], top["from_value"], top["to_value"], top["absolute"]) == (
        {"REF_AREA": "Prahova"}, 761699.0, 703580.0, -58119.0)
    brk = next(w for w in t["warnings"] if w["code"] == "series_break")       # shown, but the
    assert not brk["message"].startswith("Inside the compared interval")      # 2021/2022 break is outside
    z = TestClient(app).get("/api/period-changes/evidence", params=p)
    assert z.status_code == 200
    zf, m = open_zip(z.content)
    assert m["generation"]["id"].startswith(PINNED)
    zf.extractall(tmp_path)
    assert recompute(tmp_path).returncode == 0
    assert len(list(csv.reader(io.StringIO(zf.read("result.csv").decode())))) - 1 == 42


@pytest.mark.corpus
def test_real_refusals(real):
    def run(code, **kw):
        kw.setdefault("entity_columns", ["REF_AREA"])
        kw.setdefault("intervals", [iv("2015", "2020")])
        return call("compare_periods", dataset=code, **kw)
    e = run("POP107A")                                            # AGE spans singles and bands
    assert (e["reason"], e["provenance"]["aggregation"]["blocking_dimension"]) == (
        "overlapping_levels", "AGE")
    assert run("SOM103A")["reason"] == "unsupported_measure"      # unemployment rate
    assert run("SOM101E_lunar_localitate", entity_columns=["REF_AREA", "REF_AREA_2"])["reason"] == \
        "unsupported_frequency"
    e = run("POP105A", intervals=[iv("1990", "2020")])
    assert e["reason"] == "period_unavailable" and "2012 to " in e["message"]


@pytest.mark.corpus
def test_real_localities_keep_county_and_locality(real):
    e = call("compare_periods", dataset="POP107D", entity_columns=["REF_AREA_2"],
             intervals=[iv("2012", "2021")], top_k=1)
    i = e["data"]["intervals"][0]
    assert e["data"]["key_columns"] == ["REF_AREA", "REF_AREA_2"]
    assert i["eligible_count"] == 3181 and i["rows"][0]["entity"] == {
        "REF_AREA": "Braila", "REF_AREA_2": "42682 MUNICIPIUL BRAILA"}
    w = next(x for x in e["warnings"] if x["code"] == "boundary_continuity_unverified")
    assert "domicile (domiciliu) population" in w["message"]
