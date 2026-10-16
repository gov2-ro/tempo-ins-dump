"""AT-01d: query_data and its refusal recoveries (`tempo-tools/1`).

Real services end to end (run_query, aggregation policy, grain guard, scope,
dimension structure) on small synthetic corpora; nothing mocks the calculation.
Each case states the number the data implies and checks the envelope carries
that number or a refusal, never a convenient sum.

Synthetic families (on top of fix02b's POPX/ADDX/RATEX/INCX):

  GENX / GENY    SEX partition with / without a Total row: 100 once, never 200
  NOTOT          CATEGORY Total exists in metadata only (data: A 60 + B 40)
  NOTOT2         no Total anywhere
  ZERX           zero (A) vs NULL (B) vs no row (C)
  PARENTX        unique parent (SEX, REF_AREA, TIME_PERIOD)
    CHILDX       conflicting child (same key, 10 vs 11), DUPCH equal-value duplicate
    SIBNOAREA    unique sibling without REF_AREA
  PARENT2        metadata-only parent; CHILD2 conflicting, SIB2 unique sibling
  ORPHX          conflicting, no family
  POPAGE         metadata-only parent; AGEC single years 0-2 (90 people), AGES bands
                 0-2 (90) + 3 and over (10) = 100
  LEGX           legacy file (cat_nom_id / ani_nom_id / value) + sdmx_column_map
  BIGX / BIGY    200 / 250 rows of long Romanian labels (byte budget)
  WINX           8 periods x 3 rows (row-cap time window)
  LEVX           one verified level of 200 long members (effective-filter budget)
"""
import copy
import json
import shutil
from pathlib import Path

import duckdb
import pytest

from at01_fixtures import GENERATION, add_dataset, add_split, call, make_env
from fix02b_corpus import _write

ROOT = Path(__file__).resolve().parent.parent

# ------------------------------------------------------------------ corpus

def _dims(*specs):
    """specs: (col, label, type, [(value, parsed)...]) with parsed given as a dict."""
    return [(c, label, t, [(v, p) for v, p in opts]) for c, label, t, opts in specs]


YEARS = [(str(y), {"year": y}) for y in (2023, 2024)]
SEX = [("Total", {}), ("Masculin", {"gender": "M"}), ("Feminin", {"gender": "F"})]
AREAS = [("Nord", {"geo_level": "region"}), ("Sud", {"geo_level": "region"})]


def _sex_dims(total=True):
    return _dims(("SEX", "Sexe", "gender", SEX if total else SEX[1:]),
                 ("TIME_PERIOD", "Ani", "time", YEARS[1:]))


def _fam_dims():
    return _dims(("SEX", "Sexe", "gender", SEX[1:]), ("REF_AREA", "Regiuni", "geo", AREAS),
                 ("TIME_PERIOD", "Ani", "time", YEARS[1:]))


def _fam_rows(extra=()):
    return [("Masculin", "Nord", "2024", 10.0), ("Feminin", "Nord", "2024", 20.0),
            ("Masculin", "Sud", "2024", 30.0), ("Feminin", "Sud", "2024", 40.0), *extra]


AGE_OPT_CHILD = [("Total", {"age_min": 0, "age_max": 999})] + [
    (f"{a} ani", {"age_min": a, "age_max": a}) for a in range(3)]
AGE_OPT_SIB = [("Total", {"age_min": 0, "age_max": 999}), ("0-2 ani", {"age_min": 0, "age_max": 2}),
               ("3 ani si peste", {"age_min": 3, "age_max": 999})]


def _age_dims(opts):
    return _dims(("AGE", "Grupe de varsta", "age", opts),
                 ("SEX", "Sexe", "gender", SEX[1:]),
                 ("TIME_PERIOD", "Ani", "time", YEARS[1:]))


LONG = "ș" * 100          # 2 bytes per character in UTF-8


def build_base(corpus):
    add_dataset(corpus, "GENX", _sex_dims(True), [
        ("Total", "2024", 100.0), ("Masculin", "2024", 60.0), ("Feminin", "2024", 40.0)])
    add_dataset(corpus, "GENY", _sex_dims(False), [
        ("Masculin", "2024", 60.0), ("Feminin", "2024", 40.0)])
    notot = _dims(("CATEGORY", "Categorie", None, [("Total", {}), ("A", {}), ("B", {})]),
                  ("TIME_PERIOD", "Ani", "time", YEARS))
    add_dataset(corpus, "NOTOT", notot, [("A", "2023", 50.0), ("B", "2023", 30.0),
                                         ("A", "2024", 60.0), ("B", "2024", 40.0)])
    add_dataset(corpus, "NOTOT2", _dims(
        ("CATEGORY", "Categorie", None, [("A", {}), ("B", {})]),
        ("TIME_PERIOD", "Ani", "time", YEARS)), [("A", "2024", 60.0), ("B", "2024", 40.0)])
    add_dataset(corpus, "ZERX", _dims(
        ("CATEGORY", "Categorie", None, [("A", {}), ("B", {}), ("C", {})]),
        ("TIME_PERIOD", "Ani", "time", YEARS[1:])), [("A", "2024", 0.0), ("B", "2024", None)])

    add_dataset(corpus, "UNITX", _dims(
        ("UNIT_MEASURE", "Unitate", "unit", [("Lei", {}), ("Euro", {})]),
        ("TIME_PERIOD", "Ani", "time", YEARS[1:])), [("Lei", "2024", 10.0), ("Euro", "2024", 2.0)])
    add_dataset(corpus, "SCHEMX", _dims(
        ("CATEGORY", "Categorie", None, [("A", {})]), ("GHOST", "Dimensiune lipsa", None, [("g", {})]),
        ("TIME_PERIOD", "Ani", "time", YEARS[1:])), [], file=False)
    _write(corpus / "parquet" / "SCHEMX.parquet",
           "CATEGORY VARCHAR, TIME_PERIOD VARCHAR, OBS_VALUE DOUBLE", [("A", "2024", 5.0)])
    add_dataset(corpus, "COMBX", _dims(
        ("CATEGORY", "Categorie", None, [("A", {}), ("B", {})]),
        ("TIME_PERIOD", "Ani", "time", YEARS)), [("A", "2023", 1.0), ("B", "2024", 2.0)])

    # grain families
    add_dataset(corpus, "PARENTX", _fam_dims(), _fam_rows())
    add_dataset(corpus, "CHILDX", _fam_dims(), _fam_rows([("Masculin", "Nord", "2024", 11.0)]),
                parent="PARENTX")
    add_dataset(corpus, "DUPCH", _fam_dims(), _fam_rows([("Masculin", "Nord", "2024", 10.0)]),
                parent="PARENTX")
    add_dataset(corpus, "SIBNOAREA", _sex_dims(False), [
        ("Masculin", "2024", 40.0), ("Feminin", "2024", 60.0)], parent="PARENTX")
    for child in ("CHILDX", "DUPCH", "SIBNOAREA"):
        add_split(corpus, "PARENTX", child, child, {})
    add_dataset(corpus, "PARENT2", _fam_dims(), [], file=False)
    add_dataset(corpus, "CHILD2", _fam_dims(), _fam_rows([("Masculin", "Nord", "2024", 11.0)]),
                parent="PARENT2")
    add_dataset(corpus, "SIB2", _fam_dims(), _fam_rows(), parent="PARENT2")
    for child in ("CHILD2", "SIB2"):
        add_split(corpus, "PARENT2", child, child, {})
    add_dataset(corpus, "ORPHX", _fam_dims(), _fam_rows([("Masculin", "Nord", "2024", 11.0)]))

    # single-age child vs grouped-age sibling
    add_dataset(corpus, "POPAGE", _age_dims(AGE_OPT_CHILD), [], file=False)
    child_rows = [(f"{a} ani", s, "2024", 15.0) for a in range(3) for s in ("Masculin", "Feminin")]
    sib_rows = [(b, s, "2024", v) for b, v in (("0-2 ani", 45.0), ("3 ani si peste", 5.0))
                for s in ("Masculin", "Feminin")]
    add_dataset(corpus, "AGEC", _age_dims(AGE_OPT_CHILD), child_rows, parent="POPAGE")
    add_dataset(corpus, "AGES", _age_dims(AGE_OPT_SIB), sib_rows, parent="POPAGE")
    for child in ("AGEC", "AGES"):
        add_split(corpus, "POPAGE", child, child, {})

    add_dataset(corpus, "AGEORPH", _age_dims(AGE_OPT_CHILD), child_rows)     # no sibling

    # legacy-shaped file queried by canonical names
    add_dataset(corpus, "LEGX", _dims(
        ("CATEGORY", "Categorie", None, [("Total", {}), ("A", {}), ("B", {})]),
        ("TIME_PERIOD", "Ani", "time", [("Anul 2020", {"year": 2020}), ("Anul 2021", {"year": 2021})])),
        [], file=False)
    _write(corpus / "parquet" / "LEGX.parquet",
           "cat_nom_id VARCHAR, ani_nom_id VARCHAR, value DOUBLE",
           [("Total", "Anul 2020", 100.0), ("A", "Anul 2020", 40.0), ("B", "Anul 2020", 60.0),
            ("Total", "Anul 2021", 120.0), ("A", "Anul 2021", 50.0), ("B", "Anul 2021", 70.0)])
    db = duckdb.connect(str(corpus / "metadata.duckdb"))
    db.execute("UPDATE matrices SET row_count = 6 WHERE matrix_code = 'LEGX'")
    db.execute("INSERT INTO sdmx_column_map VALUES ('LEGX', 'CATEGORY', 'cat_nom_id'), "
               "('LEGX', 'TIME_PERIOD', 'ani_nom_id'), ('LEGX', 'OBS_VALUE', 'value')")
    db.close()

    # byte budget
    big = _dims(("CATEGORY", "Categorie", None, [("x", {})]), ("TIME_PERIOD", "Ani", "time", YEARS[1:]))
    add_dataset(corpus, "BIGX", big, [(f"{LONG}{i:03d}", "2024", float(i)) for i in range(200)])
    add_dataset(corpus, "BIGY", big, [(f"{LONG}{i:03d}", "2024", float(i)) for i in range(250)])
    wins = [(str(y), {"year": y}) for y in range(2017, 2025)]
    add_dataset(corpus, "WINX", _dims(("CATEGORY", "Categorie", None, [("A", {}), ("B", {}), ("C", {})]),
                                      ("TIME_PERIOD", "Ani", "time", wins)),
                [(c, str(y), float(y - 2000)) for y in range(2017, 2025) for c in "ABC"])


def add_struct(corpus):
    """dimension_structure: POPX has two verified AGE levels, LEVX a verified level
    of 200 long members."""
    members = [f"{LONG}{i:03d}" for i in range(200)]
    add_dataset(corpus, "LEVX", _dims(
        ("GRP", "Grupa", None, [(m, {}) for m in members]),
        ("TIME_PERIOD", "Ani", "time", YEARS[1:])), [(m, "2024", 1.0) for m in members])
    db = duckdb.connect(str(corpus / "metadata.duckdb"))
    db.execute("""CREATE TABLE dimension_structure (matrix_code VARCHAR,
                  dim_column VARCHAR, levels VARCHAR, default_level VARCHAR,
                  n_levels INTEGER, aggregate_value VARCHAR,
                  aggregate_verified BOOLEAN, additive BOOLEAN, nests_in VARCHAR,
                  discrimination DOUBLE, dominance DOUBLE, confidence VARCHAR,
                  source VARCHAR)""")

    def level(code, col, levels, default):
        db.execute("INSERT INTO dimension_structure VALUES (?, ?, ?, ?, ?, NULL, FALSE, NULL, NULL, "
                   "1.0, 1.0, 'verified', 'test')", [code, col, json.dumps(levels), default, len(levels)])
    level("POPX", "AGE", [
        {"level_id": "age_y1", "name": "single years", "verified": True,
         "members": [f"{a} ani" for a in range(5)]},
        {"level_id": "age_w5", "name": "5-year bands", "verified": True, "members": ["0-4 ani"]}],
        "age_y1")
    level("LEVX", "GRP", [{"level_id": "grp", "name": "groups", "verified": True,
                           "members": members}], "grp")
    db.close()


def add_gate(corpus):
    """INS source-total checks (kpi_total_checks) for four copies of a SEX partition
    without a Total row: INS disagrees / has no Total / was never checked / agrees."""
    for code in ("SRCMIS", "SRCNO", "SRCUNC", "SRCOK"):
        add_dataset(corpus, code, _sex_dims(False), [("Masculin", "2024", 60.0), ("Feminin", "2024", 40.0)])
    add_dataset(corpus, "SRCPAR", _sex_dims(False), [("Masculin", "2024", 60.0), ("Feminin", "2024", 40.0)])
    add_dataset(corpus, "SRCKID", _sex_dims(False), [("Masculin", "2024", 60.0), ("Feminin", "2024", 40.0)],
                parent="SRCPAR")
    add_split(corpus, "SRCPAR", "SRCKID", "SRCKID", {})
    db = duckdb.connect(str(corpus / "metadata.duckdb"))
    db.execute("CREATE TABLE kpi_total_checks (matrix_code VARCHAR, status VARCHAR, period VARCHAR, "
               "ins DOUBLE, rel DOUBLE, reason VARCHAR)")
    db.execute("INSERT INTO kpi_total_checks VALUES ('SRCMIS', 'mismatch', '2024', 130.0, 0.3, NULL), "
               "('SRCNO', 'unresolved', NULL, NULL, NULL, 'no_total_option:SEX'), "
               "('SRCOK', 'match', '2024', 100.0, 0.0, NULL), "
               "('SRCPAR', 'match', '2024', 100.0, 0.0, NULL)")
    db.close()


@pytest.fixture(scope="module")
def base_corpus(tmp_path_factory):
    """The synthetic corpus is built once per module and copied into each test's
    own directory (DuckDB files are rewritten by every add_dataset, which is slow)."""
    from fix02b_corpus import build_corpus
    corpus = build_corpus(tmp_path_factory.mktemp("at01d_base"))
    build_base(corpus)
    return corpus


def _env(base_corpus, tmp_path, monkeypatch, extra=None, **manifest):
    def build(corpus):
        shutil.rmtree(corpus)
        shutil.copytree(base_corpus, corpus)
        if extra:
            extra(corpus)
    manifest.setdefault("conflicting", ["CHILDX", "CHILD2", "ORPHX"])
    manifest.setdefault("duplicate", ["DUPCH"])
    return make_env(tmp_path, monkeypatch, build, **manifest)


@pytest.fixture
def env(base_corpus, tmp_path, monkeypatch):
    return _env(base_corpus, tmp_path, monkeypatch)


@pytest.fixture
def senv(base_corpus, tmp_path, monkeypatch):
    return _env(base_corpus, tmp_path, monkeypatch, add_struct)


@pytest.fixture
def genv(base_corpus, tmp_path, monkeypatch):
    return _env(base_corpus, tmp_path, monkeypatch, add_gate)


def q(**kw):
    return call("query_data", **kw)


def rows(e):
    return e["data"]["rows"]


def codes(e):
    return [w["code"] for w in e["warnings"]]


def verdict(a):
    a = a or {}
    return (a.get("outcome"), a.get("reason"), a.get("blocking_dimension"), a.get("method"))


def recs(e, tool=None):
    return [r for r in e["recovery"] if tool is None or r["tool"] == tool]


def by_first(e):
    return {r[0]: r[-1] for r in rows(e)}


def rest(env, code, filters=None, group_by=None, approximate=False, limit=50000):
    params = {"approximate": int(approximate), "limit": limit}
    if filters is not None:
        params["filters"] = json.dumps(filters)
    if group_by is not None:
        params["group_by"] = json.dumps(group_by)
    r = env.client.get(f"/api/datasets/{code}/data", params=params)
    assert r.status_code == 200, r.text
    return r.json()


def direct(code, filters=None, group_by=None, approximate=False, limit=100):
    from app.db import get_conn
    from app.services.data_query import run_query
    conn = get_conn()
    try:
        return run_query(conn, code, filters or {}, group_by or [], limit=limit, approximate=approximate)
    finally:
        conn.close()


# ================================================================== input and shape

def test_empty_filter_lists_are_ignored_and_reported(env):
    e = q(dataset="ADDX", filters={"CATEGORY": [], "TIME_PERIOD": ["2023"]}, group_by=["CATEGORY"])
    assert e["status"] == "ok"
    assert e["provenance"]["selection"]["filters"] == {"TIME_PERIOD": ["2023"]}    # normalized
    w = [w for w in e["warnings"] if w["code"] == "empty_filter_ignored"]
    assert len(w) == 1 and w[0]["subject"] == "CATEGORY" and "CATEGORY" in w[0]["message"]
    plain = q(dataset="ADDX", filters={"TIME_PERIOD": ["2023"]}, group_by=["CATEGORY"])
    assert rows(plain) == rows(e) and "empty_filter_ignored" not in codes(plain)


def test_unknown_dataset_column_and_split_parent_are_errors_with_a_next_step(env):
    e = q(dataset="NOSUCH")
    assert e["status"] == "error" and e["reason"] == "unknown_dataset"
    e = q(dataset="ADDX", filters={"BOGUS": ["x"]})
    assert e["reason"] == "unknown_column" and e["data"] == {}
    e = q(dataset="POPAGE", group_by=["TIME_PERIOD"])          # metadata-only split parent
    assert e["reason"] == "unknown_dataset" and recs(e, "describe_dataset")


# ================================================================== parity

CASES = [
    # (code, filters, group_by, approximate)            PA-01 CASES, then raw requests
    ("POPX", None, ["TIME_PERIOD"], False),                    # overlapping AGE grains
    ("POPX", {"AGE": [f"{a} ani" for a in range(5)]}, ["TIME_PERIOD"], False),
    ("ADDX", None, ["TIME_PERIOD"], False),                    # pinned to the Total row
    ("RATEX", None, ["TIME_PERIOD"], False),                   # rates without weights
    ("RATEX", None, ["TIME_PERIOD"], True),                    # explicit approximation
    ("INCX", None, ["TIME_PERIOD"], False),                    # means named in the options
    ("POPX", {"TIME_PERIOD": ["2025"], "SEX": ["Masculin"]}, None, False),
    ("ADDX", {"TIME_PERIOD": ["2023"]}, None, False),
    ("RATEX", {"REF_AREA": ["Nord"]}, None, False),
    ("INCX", {"TIME_PERIOD": ["2024"]}, None, False),
    ("LEGX", None, ["TIME_PERIOD"], False),                    # legacy file, canonical names
    ("LEGX", {"CATEGORY": ["A"]}, None, False),
    ("LEGX", {"CATEGORY": ["A", "B"], "TIME_PERIOD": ["Anul 2021"]}, ["CATEGORY"], False),
]


@pytest.mark.parametrize("code,filters,group_by,approximate", CASES)
def test_tool_agrees_with_rest_and_run_query(env, code, filters, group_by,
                                                                  approximate):
    kw = {"dataset": code, "approximate": approximate, "limit": 200}
    if filters is not None:
        kw["filters"] = filters
    if group_by is not None:
        kw["group_by"] = group_by
    e = q(**kw)
    r = rest(env, code, filters, group_by, approximate, limit=200)
    d = direct(code, filters, group_by, approximate, limit=200)

    assert e["data"]["columns"] == r["columns"] == d["columns"]
    assert rows(e) == r["rows"] == d["rows"]
    agg = e["provenance"]["aggregation"]
    assert verdict(agg) == verdict(r["aggregation"]) == verdict(d["aggregation"])
    native = r["aggregation"] or {}
    want_filters = native["filters"] if "filters" in native else (filters or {})
    assert e["provenance"]["effective_selection"]["filters"] == want_filters
    assert e["provenance"]["effective_selection"]["levels"] == (native.get("levels") or {})
    assert e["provenance"]["generation"]["id"] == r["generation"]["id"] == GENERATION
    assert e["provenance"]["generation"]["status"] == r["generation"]["status"] == "present"
    refused = bool(r.get("unavailable"))
    assert (e["status"] == "unavailable") == refused
    assert ("approximation" in codes(e)) == (agg.get("outcome") == "approximation")
    if refused:
        assert rows(e) == [] and e["reason"] == native["reason"]
        assert e["limits"]["returned_rows"] == 0 and e["limits"]["source_complete"] is None
    if group_by is None:
        assert agg == {} and "raw_rows" in codes(e)           # raw is labelled raw
    assert e["limits"]["total_rows"] == (None if refused else len(rows(e)))


def test_refused_inputs_never_become_values(env):
    from fix02b_corpus import INCX_NAIVE_2024, POPX_NAIVE_2025
    for kw, naive in ((dict(dataset="POPX", group_by=["TIME_PERIOD"]), POPX_NAIVE_2025),
                      (dict(dataset="INCX", group_by=["TIME_PERIOD"]), INCX_NAIVE_2024),
                      (dict(dataset="RATEX", group_by=["TIME_PERIOD"]), 30.0)):
        e = q(**kw)
        assert e["status"] == "unavailable" and rows(e) == []
        text = json.dumps(e)
        assert str(naive) not in text and e["limits"]["total_rows"] is None


def test_legacy_file_is_queried_by_canonical_names(env):
    e = q(dataset="LEGX", filters={"CATEGORY": ["A"]})
    assert e["data"]["columns"] == ["CATEGORY", "TIME_PERIOD", "OBS_VALUE"]
    assert rows(e) == [["A", "Anul 2020", 40.0], ["A", "Anul 2021", 50.0]]
    g = q(dataset="LEGX", group_by=["TIME_PERIOD"])
    assert rows(g) == [["Anul 2020", 100.0], ["Anul 2021", 120.0]]       # pinned Total, not 200/240
    assert g["provenance"]["effective_selection"]["filters"] == {"CATEGORY": ["Total"]}


# ================================================================== additivity

def test_total_and_parts_are_counted_once(env):
    e = q(dataset="ADDX", group_by=["TIME_PERIOD"], filters={"TIME_PERIOD": ["2022"]})
    assert rows(e) == [["2022", 100.0]]                       # Total row 100 = 40 + 60, never 200
    assert e["provenance"]["aggregation"]["method"] == "aggregate_row"
    assert e["provenance"]["effective_selection"]["filters"]["CATEGORY"] == ["Total"]
    pin = [w for w in e["warnings"] if w["code"] == "auto_pinned"]
    assert pin and "CATEGORY=Total" in pin[0]["message"] and pin[0]["subject"] == "CATEGORY"
    # SEX with a Total row (100 = 60 + 40) and without one: 100 once in both
    with_total = q(dataset="GENX", group_by=["TIME_PERIOD"])
    without = q(dataset="GENY", group_by=["TIME_PERIOD"])
    assert rows(with_total) == rows(without) == [["2024", 100.0]]
    assert with_total["provenance"]["aggregation"]["method"] == "aggregate_row"
    assert without["provenance"]["aggregation"]["method"] == "sum_partition"
    assert 200.0 not in [r[-1] for r in rows(with_total) + rows(without)]


# ================================================================== overlapping levels

def test_overlapping_ages_are_refused_without_a_level_to_choose(env):
    e = q(dataset="POPX", group_by=["TIME_PERIOD"])
    assert e["status"] == "unavailable" and e["reason"] == "overlapping_levels"
    assert e["provenance"]["aggregation"]["blocking_dimension"] == "AGE"
    assert e["data"]["blocking_dimension"] == "AGE" and rows(e) == []
    assert "220.0" not in json.dumps(e)                       # the naive 2x sum never appears
    assert [r["arguments"]["column"] for r in recs(e, "find_dimension_values")] == ["AGE"]
    assert all(r["arguments"]["group_by"] for r in recs(e, "query_data"))     # never raw rows


def test_overlap_recovery_offers_each_verified_level_and_they_validate(senv):
    e = q(dataset="POPX", group_by=["TIME_PERIOD"], filters={"AGE": ["0 ani", "0-4 ani"]})
    assert e["status"] == "unavailable" and e["reason"] == "overlapping_levels"
    assert "220.0" not in json.dumps(e)
    cands = recs(e, "query_data")
    assert [c["arguments"]["filters"]["AGE"] for c in cands] == [
        ["0-4 ani"], [f"{a} ani" for a in range(5)]]          # coarsest level first, one level each
    for c in cands:                                            # each runs under the same policy
        out = q(**c["arguments"])
        assert out["status"] == "ok"
        assert [r[0] for r in rows(out)] == ["2024", "2025"]
        assert [r[1] for r in rows(out)] == pytest.approx([100.0, 110.0])
    # the unfiltered request is answered by the default verified level, with a pin warning
    ok = q(dataset="POPX", group_by=["TIME_PERIOD"])
    assert ok["status"] == "ok" and [r[1] for r in rows(ok)] == pytest.approx([100.0, 110.0])
    assert ok["provenance"]["effective_selection"]["levels"]["AGE"] == "age_y1"
    assert "level age_y1" in [w for w in ok["warnings"] if w["code"] == "auto_pinned"][0]["message"]


# ================================================================== grain

def _run_candidate(rec):
    assert rec["tool"] == "query_data"
    return q(**rec["arguments"])


def test_conflicting_child_names_a_verified_parent_or_sibling(env):
    e = q(dataset="CHILDX", group_by=["TIME_PERIOD"])
    assert e["status"] == "unavailable" and e["reason"] == "conflicting_grain" and rows(e) == []
    targets = [r["arguments"]["dataset"] for r in recs(e, "query_data")]
    assert targets == ["PARENTX", "SIBNOAREA"]               # parent first, then unique siblings
    assert "candidate, not a verified answer" in recs(e, "query_data")[0]["message"]
    for r in recs(e, "query_data"):
        assert r["arguments"]["group_by"] == ["TIME_PERIOD"]   # same group_by, never raw rows
    alt = _run_candidate(recs(e, "query_data")[0])
    assert alt["status"] == "ok" and rows(alt) == [["2024", 100.0]]       # 10+20+30+40, once
    assert "10.0" not in json.dumps(e) and "11.0" not in json.dumps(e)


def test_alternative_must_have_every_requested_column_and_value(env):
    e = q(dataset="CHILDX", group_by=["TIME_PERIOD"], filters={"REF_AREA": ["Nord"]})
    assert e["reason"] == "conflicting_grain"
    assert [r["arguments"]["dataset"] for r in recs(e, "query_data")] == ["PARENTX"]
    assert "SIBNOAREA" not in json.dumps(e["recovery"])      # it has no REF_AREA column
    assert rows(_run_candidate(recs(e, "query_data")[0])) == [["2024", 30.0]]


def test_metadata_only_parent_is_skipped_and_the_sibling_is_named(env):
    e = q(dataset="CHILD2", group_by=["TIME_PERIOD"])
    assert e["reason"] == "conflicting_grain"
    assert [r["arguments"]["dataset"] for r in recs(e, "query_data")] == ["SIB2"]


def test_duplicate_keys_get_the_same_treatment(env):
    e = q(dataset="DUPCH", group_by=["TIME_PERIOD"])
    assert e["reason"] == "duplicate_keys" and rows(e) == []
    assert recs(e, "query_data")[0]["arguments"]["dataset"] == "PARENTX"
    assert "20.0" not in json.dumps(e["data"])


def test_no_alternative_means_an_explained_restriction_not_raw_sums(env):
    e = q(dataset="ORPHX", group_by=["TIME_PERIOD"])
    assert e["status"] == "unavailable" and e["reason"] == "conflicting_grain"
    assert not recs(e, "query_data")
    assert recs(e, "discover_indicators") and recs(e, "describe_dataset")
    assert "must not be totalled or ranked by hand" in e["message"]
    for r in e["recovery"]:
        assert "raw" not in r["message"].lower()


def test_unverifiable_slice_asks_for_a_narrower_one(env, monkeypatch):
    from app.services import grain_guard
    monkeypatch.setattr(grain_guard, "GRAIN_CHECK_MAX_ROWS", 1)
    e = q(dataset="CHILDX", group_by=["TIME_PERIOD"])
    assert e["status"] == "unavailable" and e["reason"] == "grain_unverified"
    assert [r["kind"] for r in e["recovery"]] == ["tool_call", "tool_call", "narrow"]
    assert e["recovery"][0]["arguments"]["dataset"] == "PARENTX"
    assert "one area or one period" in e["recovery"][2]["message"]
    orphan = q(dataset="ORPHX", group_by=["TIME_PERIOD"])
    assert orphan["reason"] == "grain_unverified" and not recs(orphan, "query_data")
    assert any(r["kind"] == "narrow" for r in orphan["recovery"])


def test_a_clean_slice_of_a_flagged_file_is_answered_and_labelled(env):
    e = q(dataset="CHILDX", group_by=["TIME_PERIOD"], filters={"SEX": ["Feminin"]})
    assert e["status"] == "ok" and rows(e) == [["2024", 60.0]]               # 20 + 40
    assert e["provenance"]["quality"]["grain"]["status"] == "conflicting"
    assert e["provenance"]["quality"]["slice"]["ok"] is True
    assert "data_quality" in codes(e)


def test_raw_rows_of_a_flagged_file_are_marked_do_not_total(env):
    e = q(dataset="CHILDX", filters={"REF_AREA": ["Nord"], "SEX": ["Masculin"]})
    assert e["status"] == "ok" and sorted(r[-1] for r in rows(e)) == [10.0, 11.0]
    dq_ = [w for w in e["warnings"] if w["code"] == "data_quality"]
    assert dq_ and "Do not total or rank them" in dq_[0]["message"]
    assert "raw_rows" in codes(e)


# ================================================================== missing Total

def _concepts(tmp_path, monkeypatch, recipe="net_earnings_county", family="NOTOT"):
    from app.services import concept_search
    path = tmp_path / f"concepts-{family}-{recipe}.json"
    path.write_text(json.dumps({"concepts": [
        {"id": "fixture_concept", "family": family, "variants": {"county": family},
         "total_recipe": recipe}]}))
    monkeypatch.setattr(concept_search, "CONCEPTS_PATH", path)


def test_missing_total_explains_and_offers_the_policy_checked_route(env):
    e = q(dataset="NOTOT", filters={"CATEGORY": ["Total"]})
    assert e["status"] == "unavailable" and e["reason"] == "slice_value_missing" and rows(e) == []
    assert e["data"]["selection"]["missing_values"] == {"CATEGORY": ["Total"]}
    assert "no such Total row" in e["message"] and "metadata lists a Total option" in e["message"]
    assert not recs(e, "run_recipe")
    pol, find = recs(e, "query_data")[0], recs(e, "find_dimension_values")[0]
    assert "CATEGORY" not in pol["arguments"]["filters"] and pol["arguments"]["group_by"] == ["TIME_PERIOD"]
    assert "not promised to be safe" in pol["message"] or "Candidate only" in pol["message"]
    assert find["arguments"] == {"dataset": "NOTOT", "column": "CATEGORY", "query": ""}
    # the policy, not this tool, decides: it does not hand out a sum for an unverified partition
    out = q(**pol["arguments"])
    assert out["status"] == "unavailable" and out["reason"] == "unverified_structure"
    assert rows(out) == [] and "100.0" not in json.dumps(out)


def test_missing_total_grouped_is_the_native_refusal_with_the_same_recoveries(env):
    e = q(dataset="NOTOT", filters={"CATEGORY": ["Total"]}, group_by=["TIME_PERIOD"])
    assert e["status"] == "unavailable" and e["reason"] == "slice_value_missing"
    assert e["provenance"]["aggregation"]["blocking_dimension"] == "CATEGORY"
    assert "no such Total row" in e["message"]
    pol = recs(e, "query_data")[0]
    assert pol["arguments"]["filters"] == {} and pol["arguments"]["group_by"] == ["TIME_PERIOD"]
    assert recs(e, "find_dimension_values")


@pytest.mark.parametrize("value", ["TOTAL", "Total județ", "Toate categoriile"])
def test_total_like_spellings(env, value):
    e = q(dataset="NOTOT2", filters={"CATEGORY": [value]})
    assert e["reason"] == "slice_value_missing" and "no such Total row" in e["message"]
    assert "metadata lists a Total option" not in e["message"]       # NOTOT2 never listed one


def test_missing_total_offers_a_reviewed_recipe_when_the_concept_has_one(env, tmp_path, monkeypatch):
    _concepts(tmp_path, monkeypatch)
    e = q(dataset="NOTOT", filters={"CATEGORY": ["Total"], "TIME_PERIOD": ["2024"]},
          group_by=["TIME_PERIOD"])
    first = e["recovery"][0]
    assert first["tool"] == "run_recipe"
    assert first["arguments"] == {"recipe": "net_earnings_county", "lang": "ro", "year": "2024"}
    assert [r["tool"] for r in e["recovery"]] == ["run_recipe", "query_data", "find_dimension_values"]
    # an unknown recipe id is never offered
    _concepts(tmp_path, monkeypatch, recipe="no_such_recipe")
    assert not recs(q(dataset="NOTOT", filters={"CATEGORY": ["Total"]}), "run_recipe")


def test_a_missing_non_total_value_is_looked_up_not_summed(env):
    e = q(dataset="NOTOT", filters={"CATEGORY": ["C"]})
    assert e["reason"] == "slice_value_missing" and "Total" not in e["message"]
    assert recs(e, "find_dimension_values")[0]["arguments"]["query"] == "C"
    assert not recs(e, "query_data") and not recs(e, "run_recipe")


# ================================================================== other policy refusals

def test_mixed_units_ask_for_exactly_one_unit(env):
    e = q(dataset="UNITX", group_by=["TIME_PERIOD"])
    assert e["status"] == "unavailable" and e["reason"] == "mixed_units" and rows(e) == []
    assert e["provenance"]["aggregation"]["blocking_dimension"] == "UNIT_MEASURE"
    assert e["recovery"][0]["tool"] == "find_dimension_values"
    assert e["recovery"][0]["arguments"]["column"] == "UNIT_MEASURE"
    assert e["recovery"][1]["kind"] == "narrow" and "exactly one unit" in e["recovery"][1]["message"]
    assert "12.0" not in json.dumps(e)                          # 10 lei + 2 euro is never a number
    one = q(dataset="UNITX", group_by=["TIME_PERIOD"], filters={"UNIT_MEASURE": ["Lei"]})
    assert one["status"] == "ok" and rows(one) == [["2024", 10.0]]


def test_dimension_missing_from_the_file_is_explained(env):
    e = q(dataset="SCHEMX", group_by=["TIME_PERIOD"])
    assert e["status"] == "unavailable" and e["reason"] == "schema_mismatch"
    assert e["provenance"]["aggregation"]["blocking_dimension"] == "GHOST" and rows(e) == []
    assert "not a column of its data file" in e["message"]
    assert [r["tool"] for r in e["recovery"]] == ["describe_dataset"]


def test_missing_aggregation_context_is_explained_not_summed(env, monkeypatch):
    from app.services import dataset_meta
    monkeypatch.setattr(dataset_meta, "get_aggregation_context", lambda conn, code: None)
    e = q(dataset="ADDX", group_by=["TIME_PERIOD"])
    assert e["status"] == "unavailable" and e["reason"] == "no_aggregation_context" and rows(e) == []
    assert "not usable for a safe aggregation" in e["message"]
    assert [r["tool"] for r in e["recovery"]] == ["describe_dataset"]
    assert "120.0" not in json.dumps(e["data"]) and not recs(e, "query_data")


def test_total_together_with_its_parts_is_split_into_two_safe_requests(env):
    e = q(dataset="ADDX", group_by=["TIME_PERIOD"], filters={"CATEGORY": ["Total", "A"]})
    assert e["status"] == "unavailable" and e["reason"] == "contains_aggregate" and rows(e) == []
    total_only, parts = [r["arguments"]["filters"]["CATEGORY"] for r in recs(e, "query_data")][:2]
    assert total_only == ["Total"] and parts == ["A"]
    out = q(**recs(e, "query_data")[0]["arguments"])
    assert out["status"] == "ok" and rows(out) == [["2022", 100.0], ["2023", 120.0]]


def test_unverified_structure_can_stay_on_the_axis_instead(env):
    e = q(dataset="NOTOT2", group_by=["TIME_PERIOD"])
    assert e["status"] == "unavailable" and e["reason"] == "unverified_structure"
    keep = recs(e, "query_data")[0]
    assert keep["arguments"]["group_by"] == ["TIME_PERIOD", "CATEGORY"]
    out = q(**keep["arguments"])
    assert out["status"] == "ok" and sorted(rows(out)) == [["2024", "A", 60.0], ["2024", "B", 40.0]]


# ================================================================== INS source totals

def test_source_total_disagreement_withholds_the_sum(genv, tmp_path, monkeypatch):
    e = q(dataset="SRCMIS", group_by=["TIME_PERIOD"])
    assert e["status"] == "unavailable" and e["reason"] == "source_total_mismatch" and rows(e) == []
    assert "disagree" in e["message"] and "100.0" not in json.dumps(e["data"])
    assert not recs(e, "run_recipe")
    _concepts(tmp_path, monkeypatch, family="SRCMIS")
    again = q(dataset="SRCMIS", group_by=["TIME_PERIOD"])
    assert again["recovery"][0]["tool"] == "run_recipe"
    assert again["recovery"][0]["arguments"]["recipe"] == "net_earnings_county"


@pytest.mark.parametrize("code,reason,text", [
    ("SRCNO", "no_source_total", "no Total row"),
    ("SRCUNC", "source_total_unchecked", "not been checked")])
def test_unchecked_or_unanchored_sums_are_withheld(genv, code, reason, text):
    e = q(dataset=code, group_by=["TIME_PERIOD"])
    assert e["status"] == "unavailable" and e["reason"] == reason and rows(e) == []
    assert text in e["message"]
    assert any(r["kind"] == "narrow" for r in e["recovery"]) and recs(e, "describe_dataset")


def test_an_unchecked_child_points_to_a_related_dataset_that_passes_its_checks(genv):
    e = q(dataset="SRCKID", group_by=["TIME_PERIOD"])
    assert e["status"] == "unavailable" and e["reason"] == "source_total_unchecked"
    alt = recs(e, "query_data")
    assert [r["arguments"]["dataset"] for r in alt] == ["SRCPAR"]
    out = q(**alt[0]["arguments"])
    assert out["status"] == "ok" and rows(out) == [["2024", 100.0]]
    # a dataset with no such relative offers none
    assert not recs(q(dataset="SRCUNC", group_by=["TIME_PERIOD"]), "query_data")


def test_a_sum_that_ins_confirms_is_served(genv):
    e = q(dataset="SRCOK", group_by=["TIME_PERIOD"])
    assert e["status"] == "ok" and rows(e) == [["2024", 100.0]]


# ================================================================== empty and missing

def test_missing_year_reports_actual_bounds_and_never_a_nearest_year(env):
    for kw in (dict(filters={"TIME_PERIOD": ["1999"], "CATEGORY": ["Total"]}),
               dict(filters={"TIME_PERIOD": ["1999"]}, group_by=["TIME_PERIOD"])):
        e = q(dataset="ADDX", **kw)
        assert e["status"] == "unavailable" and e["reason"] == "period_unavailable"
        assert rows(e) == [] and e["data"]["selection"]["missing_values"] == {"TIME_PERIOD": ["1999"]}
        assert e["data"]["period_bounds"] == {"first": "2022", "last": "2023", "periods_with_data": 2}
        assert "1999" in e["message"] and "2022 to 2023" in e["message"]
        assert recs(e)[0]["arguments"] == {"dataset": "ADDX", "column": "TIME_PERIOD", "query": ""}
        assert e["provenance"]["selection"]["filters"]["TIME_PERIOD"] == ["1999"]   # preserved
        assert "100.0" not in json.dumps(e["data"]) and "120.0" not in json.dumps(e["data"])


def test_missing_area_is_slice_value_missing_raw_and_grouped(env):
    raw = q(dataset="RATEX", filters={"REF_AREA": ["Vest"]})
    assert raw["reason"] == "slice_value_missing" and rows(raw) == []
    assert raw["data"]["selection"]["missing_values"] == {"REF_AREA": ["Vest"]}
    assert recs(raw, "find_dimension_values")[0]["arguments"]["query"] == "Vest"
    grouped = q(dataset="RATEX", filters={"REF_AREA": ["Vest"]}, group_by=["TIME_PERIOD"])
    assert grouped["reason"] == "slice_value_missing"
    assert grouped["provenance"]["aggregation"]["blocking_dimension"] == "REF_AREA"
    assert recs(grouped, "find_dimension_values")[0]["arguments"] == {
        "dataset": "RATEX", "column": "REF_AREA", "query": "Vest"}


def test_values_that_exist_but_never_together_are_not_widened(env):
    e = q(dataset="COMBX", filters={"CATEGORY": ["A"], "TIME_PERIOD": ["2024"]})
    assert e["status"] == "unavailable" and e["reason"] == "slice_value_missing"
    assert e["data"]["selection"] == {"empty": True, "missing_values": {}}
    assert "together" in e["message"] and rows(e) == []


def test_zero_null_and_no_row_are_three_different_things(env):
    e = q(dataset="ZERX", filters={"CATEGORY": ["A", "B", "C"]})
    assert e["status"] == "ok"
    assert rows(e) == [["A", "2024", 0.0], ["B", "2024", None]]     # a real zero; a null
    by = {w["code"]: w for w in e["warnings"]}
    assert "null_values" in by and "Null is not zero" in by["null_values"]["message"]
    assert by["no_rows_for_value"]["subject"] == "CATEGORY" and "C" in by["no_rows_for_value"]["message"]
    only_zero = q(dataset="ZERX", filters={"CATEGORY": ["A"]})
    assert rows(only_zero) == [["A", "2024", 0.0]]
    assert "null_values" not in codes(only_zero) and "no_rows_for_value" not in codes(only_zero)
    assert json.loads(json.dumps(e))["data"]["rows"][1][2] is None


# ================================================================== approximation

def test_rates_need_consent_and_the_tool_never_gives_it(env):
    e = q(dataset="RATEX", group_by=["TIME_PERIOD"])
    assert e["status"] == "unavailable" and e["reason"] == "missing_weights" and rows(e) == []
    clarify = [r for r in e["recovery"] if r["kind"] == "clarify"]
    assert len(clarify) == 1 and clarify[0]["tool"] is None and "approximate=true" in clarify[0]["message"]
    keep = recs(e, "query_data")[0]
    assert keep["arguments"]["group_by"] == ["TIME_PERIOD", "REF_AREA"]
    assert all(r["arguments"]["approximate"] is False for r in recs(e, "query_data"))
    per_region = q(**keep["arguments"])                      # nothing combined: one value each
    assert per_region["status"] == "ok"
    assert sorted(rows(per_region)) == [["2023", "Nord", 10.0], ["2023", "Sud", 20.0],
                                        ["2024", "Nord", 12.0], ["2024", "Sud", 22.0]]
    assert "approximation" not in codes(per_region)


def test_opted_in_approximation_is_ok_but_labelled_everywhere(env):
    e = q(dataset="RATEX", group_by=["TIME_PERIOD"], approximate=True)
    assert e["status"] == "ok" and rows(e) == [["2023", 15.0], ["2024", 17.0]]
    w = [w for w in e["warnings"] if w["code"] == "approximation"]
    assert w and "not the official" in w[0]["message"]
    agg = e["provenance"]["aggregation"]
    assert agg["outcome"] == "approximation" and agg["method"] == "unweighted_mean"
    assert agg["approximation"] is True and "APPROXIMATION" in e["message"]
    assert e["provenance"]["selection"]["approximate"] is True


# ================================================================== incomplete domain

def test_single_age_child_is_partial_and_names_the_complete_sibling(env):
    e = q(dataset="AGEC", group_by=["TIME_PERIOD"])
    assert e["status"] == "partial" and e["reason"] == "incomplete_domain"
    assert rows(e) == [["2024", 90.0]]                         # kept, never promoted to 100
    sc = e["provenance"]["scope"]
    assert sc["domain_complete"] is False
    assert sc["description"] == "Vârste 0–2 ani (fără 3 ani și peste)"
    assert sc["limitations"][0]["requested"] is False and sc["limitations"][0]["missing"] == [[3, None]]
    assert sc["description"] in e["message"] and "not a complete-domain total" in e["message"]
    w = [w for w in e["warnings"] if w["code"] == "incomplete_domain"]
    assert w and "not an all-ages / all-population total" in w[0]["message"]
    rec = recs(e, "query_data")
    assert [r["arguments"]["dataset"] for r in rec] == ["AGES"]
    assert "candidate, not a verified answer" in rec[0]["message"]
    full = q(**rec[0]["arguments"])                            # the sibling gives 100, status ok
    assert full["status"] == "ok" and rows(full) == [["2024", 100.0]]
    assert full["provenance"]["scope"]["domain_complete"] is not False
    assert full["provenance"]["scope"]["limitations"] == []


def test_scope_text_follows_the_language(env):
    e = q(dataset="AGEC", group_by=["TIME_PERIOD"], lang="en")
    assert e["provenance"]["scope"]["description"] == "Ages 0–2 (3 and over not included)"


def test_explicit_request_for_the_covered_range_is_an_ok_restricted_answer(env):
    ages = ["0 ani", "1 ani", "2 ani"]
    e = q(dataset="AGEC", group_by=["TIME_PERIOD"], filters={"AGE": ages})
    assert e["status"] == "ok" and e["reason"] is None and rows(e) == [["2024", 90.0]]
    lim = e["provenance"]["scope"]["limitations"][0]
    assert lim["requested"] is True and lim["covered"] == [[0, 2]]
    assert "Vârste 0–2 ani" in e["provenance"]["scope"]["description"]
    assert "selecție explicită" in e["provenance"]["scope"]["description"]
    assert e["provenance"]["scope"]["domain_complete"] is not False
    assert "incomplete_domain" not in codes(e)


def test_a_child_without_a_verified_complete_alternative_says_so(env):
    e = q(dataset="AGEORPH", group_by=["TIME_PERIOD"])
    assert e["status"] == "partial" and rows(e) == [["2024", 90.0]]
    assert not recs(e, "query_data") and e["recovery"][0]["kind"] == "narrow"
    assert "discover_indicators" in e["recovery"][0]["message"]


def test_unknown_completeness_is_stated_not_failed(env):
    e = q(dataset="AGES", group_by=["TIME_PERIOD"])
    assert e["status"] == "ok" and rows(e) == [["2024", 100.0]]
    assert e["provenance"]["scope"]["domain_complete"] is None
    assert "unverified" in e["message"] and "Nu se poate verifica" in e["provenance"]["scope"]["description"]
    assert not any(w["code"] == "incomplete_domain" for w in e["warnings"])


# ================================================================== budgets and flags

def test_romanian_preview_is_shortened_by_bytes_and_keeps_its_total(env):
    from app.services.tools import contract as C
    full = direct("BIGX", limit=200)
    assert full["returned_rows"] == 200 and not full["truncated"]
    assert len(C.dumps(full["rows"])) < 32 * 1024 < len(C.dumps(full["rows"]).encode("utf-8"))
    e = q(dataset="BIGX", limit=200)
    assert C.size(e) <= C.MAX_RESULT_BYTES
    n = len(rows(e))
    assert 0 < n < 200 and rows(e) == full["rows"][:n]          # whole rows, in order, no cut strings
    lim = e["limits"]
    assert lim["returned_rows"] == n and lim["preview_truncated"] is True
    assert lim["total_rows"] == 200 and lim["source_complete"] is True
    assert "preview_shortened" in codes(e) and "raw_rows" in codes(e)    # safety notes survive
    assert e["provenance"]["sources"] and e["provenance"]["scope"]["description"]


def test_capped_result_flags_map_to_limits(env):
    e = q(dataset="BIGY", limit=200)
    assert e["limits"]["total_rows"] is None and e["limits"]["preview_truncated"] is True
    assert "preview" in codes(e) and "never establishes a total" in \
        [w for w in e["warnings"] if w["code"] == "preview"][0]["message"]
    assert e["limits"]["returned_rows"] == len(rows(e)) < 200
    small = q(dataset="BIGY", limit=5)
    assert small["limits"]["returned_rows"] == 5 and small["limits"]["total_rows"] is None
    assert small["recovery"][0]["kind"] == "narrow"


def test_time_window_maps_to_limits_and_warns(env, monkeypatch):
    import app.services.data_query as dq
    monkeypatch.setattr(dq, "MAX_DATA_ROWS", 20)
    e = q(dataset="WINX", limit=20)
    assert e["status"] == "ok" and e["limits"]["time_windowed"] is True
    assert e["limits"]["source_complete"] is False and e["limits"]["total_rows"] is None
    periods = sorted({r[1] for r in rows(e)})
    assert periods[-1] == "2024" and periods[0] > "2017"       # newest periods only
    assert "earlier periods" in [w for w in e["warnings"] if w["code"] == "time_windowed"][0]["message"]
    older = q(dataset="WINX", limit=20, filters={"TIME_PERIOD": ["2017"]})
    assert older["limits"]["time_windowed"] is False and {r[1] for r in rows(older)} == {"2017"}


def test_missing_manifest_blocks_totals_but_not_raw_rows(base_corpus, tmp_path, monkeypatch):
    _env(base_corpus, tmp_path, monkeypatch, generation_id=None)
    g = q(dataset="ADDX", group_by=["TIME_PERIOD"])
    assert g["status"] == "unavailable" and g["reason"] == "generation_unverified" and g["data"] == {}
    assert g["provenance"]["generation"] == {"id": None, "status": "missing", "built_at": None}
    raw = q(dataset="ADDX", filters={"TIME_PERIOD": ["2023"]})
    assert raw["status"] == "ok" and len(rows(raw)) == 3
    assert raw["provenance"]["generation"]["status"] == "missing"
    assert "generation_unverified" in codes(raw)


def test_long_effective_filters_are_summarized_before_rows_are_cut(senv):
    import hashlib
    from app.services.tools import contract as C
    members = [f"{LONG}{i:03d}" for i in range(200)]
    e = q(dataset="LEVX", group_by=["TIME_PERIOD"])
    assert C.size(e) <= C.MAX_RESULT_BYTES
    assert rows(e) == [["2024", 200.0]] and e["limits"]["preview_truncated"] is False
    summary = e["provenance"]["effective_selection"]["filters"]["GRP"]
    assert summary["values_count"] == 200 and summary["first"] == members[:10]
    assert summary["sha256"] == hashlib.sha256(C.dumps(members).encode("utf-8")).hexdigest()
    w = [w for w in e["warnings"] if w["code"] == "effective_filters_summarized"]
    assert len(w) == 1 and w[0]["subject"] == "GRP"
    assert e["provenance"]["effective_selection"]["levels"] == {"GRP": "grp"}


def test_shrink_cuts_labels_then_rows_then_filters(env):
    from app.services.tools.query import shrink
    base = q(dataset="ADDX", group_by=["TIME_PERIOD"])
    e = json.loads(json.dumps(base))
    e["data"]["column_labels"] = {"A": {"x": "y" * 50}, "B": {"x": "y" * 500}}
    e["data"]["rows"] = [["r", float(i)] for i in range(5)]
    e["limits"]["returned_rows"] = 5
    e["provenance"]["effective_selection"]["filters"] = {"K": [f"v{i}" for i in range(60)],
                                                          "S": ["small"]}
    assert shrink(e) and list(e["data"]["column_labels"]) == ["A"]          # largest labels first
    assert shrink(e) and e["data"]["column_labels"] == {} and "labels_omitted" in codes(e)
    assert len(e["data"]["rows"]) == 5                                       # rows untouched so far
    assert shrink(e) and len(e["data"]["rows"]) == 2 and e["limits"]["returned_rows"] == 2
    assert e["limits"]["preview_truncated"] is True
    assert shrink(e) and shrink(e) and e["data"]["rows"] == []
    assert shrink(e)                                                         # now the filters
    assert e["provenance"]["effective_selection"]["filters"]["K"]["values_count"] == 60
    assert e["provenance"]["effective_selection"]["filters"]["S"] == ["small"]
    assert codes(e).count("preview_shortened") == 1
    assert not shrink(e)                                                     # nothing left


# ================================================================== immutability

def test_tool_calls_never_mutate_the_shared_metadata_caches(senv):
    from app.services import dataset_meta, dimension_structure
    calls = [dict(dataset="POPX", group_by=["TIME_PERIOD"]),
             dict(dataset="POPX", group_by=["TIME_PERIOD"], filters={"AGE": ["0 ani", "0-4 ani"]}),
             dict(dataset="CHILDX", group_by=["TIME_PERIOD"]),
             dict(dataset="AGEC", group_by=["TIME_PERIOD"]),
             dict(dataset="NOTOT", filters={"CATEGORY": ["Total"]}),
             dict(dataset="RATEX", group_by=["TIME_PERIOD"]),
             dict(dataset="ADDX", filters={"TIME_PERIOD": ["1999"]})]
    for kw in calls:
        q(**kw)                                                   # warm every cache
    snap = copy.deepcopy(dict(dataset_meta._CTX_CACHE))
    struct = copy.deepcopy(dict(dimension_structure._cache))
    assert snap and struct
    for kw in calls * 2:
        q(**kw)
    for key, entry in snap.items():
        assert dataset_meta._CTX_CACHE[key] == entry, key
    for key, entry in struct.items():
        assert dimension_structure._cache[key] == entry, key


def test_two_identical_calls_give_identical_envelopes(env):
    a = q(dataset="ADDX", group_by=["TIME_PERIOD"])
    b = q(dataset="ADDX", group_by=["TIME_PERIOD"])
    assert a == b


# ================================================================== native flags and hygiene

def test_collapsed_time_and_dropped_partial_period_are_flagged(env):
    e = q(dataset="ADDX", group_by=["CATEGORY"])
    tc = [w for w in e["warnings"] if w["code"] == "time_collapsed"]
    assert tc and tc[0]["subject"] == "TIME_PERIOD" and "single-period" in tc[0]["message"]
    assert sorted(rows(e)) == [["A", 90.0], ["B", 130.0], ["Total", 220.0]]     # summed over 2022+2023
    # a capped raw result is cut mid-period: the oldest period is dropped, and said so
    cut = q(dataset="WINX", limit=10)
    assert cut["limits"]["partial_period_dropped"] == "2021" and cut["limits"]["total_rows"] is None
    assert "2021" not in {r[1] for r in rows(cut)} and rows(cut)
    assert {"preview", "partial_period_dropped"} <= set(codes(cut))
    assert cut["limits"]["source_complete"] is False


def test_each_call_runs_one_query_and_never_aggregates_for_a_recovery(senv, monkeypatch):
    import app.services.data_query as dq
    from app.services import grain_guard
    seen = {"run": 0, "slice": 0}
    real_run, real_slice = dq.run_query, grain_guard.check_slice

    def run(*a, **k):
        seen["run"] += 1
        return real_run(*a, **k)

    def check(*a, **k):
        seen["slice"] += 1
        return real_slice(*a, **k)
    monkeypatch.setattr(dq, "run_query", run)
    monkeypatch.setattr(grain_guard, "check_slice", check)
    for kw in (dict(dataset="CHILDX", group_by=["TIME_PERIOD"]),
               dict(dataset="AGEC", group_by=["TIME_PERIOD"]),
               dict(dataset="POPX", group_by=["TIME_PERIOD"], filters={"AGE": ["0 ani", "0-4 ani"]}),
               dict(dataset="NOTOT", filters={"CATEGORY": ["Total"]}, group_by=["TIME_PERIOD"]),
               dict(dataset="RATEX", group_by=["TIME_PERIOD"])):
        seen.update(run=0, slice=0)
        e = q(**kw)
        assert e["recovery"] and seen["run"] == 1 and seen["slice"] <= 1, kw


def test_no_message_leaks_sql_paths_or_internals(senv):
    battery = [dict(dataset="POPX", group_by=["TIME_PERIOD"]),
               dict(dataset="CHILDX", group_by=["TIME_PERIOD"]),
               dict(dataset="AGEC", group_by=["TIME_PERIOD"]),
               dict(dataset="ADDX", filters={"TIME_PERIOD": ["1999"]}),
               dict(dataset="NOTOT", filters={"CATEGORY": ["Total"]}),
               dict(dataset="SCHEMX", group_by=["TIME_PERIOD"]),
               dict(dataset="POPAGE", group_by=["TIME_PERIOD"]),
               dict(dataset="ADDX", filters={"BOGUS": ["x"]}),
               dict(dataset="ZERX", filters={"CATEGORY": ["A", "B", "C"]}),
               dict(dataset="BIGX", limit=200)]
    for kw in battery:
        e = q(**kw)
        text = json.dumps(e, ensure_ascii=False)
        for bad in ("SELECT", "read_parquet", ".parquet", "/private", "/var/", "Traceback",
                    "Binder", "duckdb", "OBS_VALUE IN"):
            assert bad not in text, (kw, bad)
        assert len(e["recovery"]) <= 3


def test_the_selection_it_reports_is_accepted_by_the_evidence_tool(env):
    e = q(dataset="ADDX", group_by=["TIME_PERIOD"], filters={"TIME_PERIOD": ["2023"]})
    links = call("get_evidence_links", selection=e["provenance"]["selection"],
                 generation_id=e["provenance"]["generation"]["id"])
    assert links["status"] == "ok" and links["data"]["selection"]["dataset"] == "ADDX"
    stale = call("get_evidence_links", selection=e["provenance"]["selection"],
                 generation_id="gen-of-another-corpus")
    assert stale["status"] == "unavailable" and stale["reason"] == "generation_changed"


# ================================================================== real corpus (read-only)

PINNED = "9b3e065d"


def _pinned():
    from app.services import generation
    if not (generation.summary()["id"] or "").startswith(PINNED):
        pytest.skip(f"pinned to generation {PINNED} (copied 2026-10-12 corpus)")


@pytest.mark.corpus
def test_real_pop107a_overlap_is_refused_with_a_compatible_complete_child():
    _pinned()
    e = call("query_data", dataset="POP107A", group_by=["TIME_PERIOD"])
    assert e["status"] == "unavailable" and e["reason"] == "overlapping_levels"
    assert e["provenance"]["aggregation"]["blocking_dimension"] == "AGE" and e["data"]["rows"] == []
    targets = [r["arguments"]["dataset"] for r in recs(e, "query_data")]
    assert targets and all(t.startswith("POP107A_") and t.endswith("_grupe") for t in targets)
    assert all(r["arguments"]["group_by"] == ["TIME_PERIOD"] for r in recs(e, "query_data"))


@pytest.mark.corpus
def test_real_tur105e_conflicting_child_names_unique_alternatives():
    _pinned()
    e = call("query_data", dataset="TUR105E_judet", group_by=["TIME_PERIOD"],
             filters={"REF_AREA": ["Cluj"]})
    assert e["status"] == "unavailable" and e["reason"] == "conflicting_grain"
    targets = [r["arguments"]["dataset"] for r in recs(e, "query_data")]
    assert targets and set(targets) <= {"TUR105E", "TUR105E_localitate"}
    assert e["data"]["rows"] == []


@pytest.mark.corpus
def test_real_single_age_localitate_child_is_partial_with_a_complete_alternative():
    _pinned()
    kw = dict(group_by=["TIME_PERIOD"], filters={"TIME_PERIOD": ["2026"]})
    e = call("query_data", dataset="POP107D_varste_localitate", **kw)
    assert e["status"] == "partial" and e["reason"] == "incomplete_domain"
    assert e["provenance"]["scope"]["description"] == "Vârste 0–84 ani (fără 85 ani și peste)"
    assert e["data"]["rows"] == [["2026", 21179764.0]]
    alt = recs(e, "query_data")
    assert alt and alt[0]["arguments"]["dataset"] in ("POP107D", "POP107D_grupe_localitate")
    full = call("query_data", **alt[0]["arguments"])
    assert full["status"] == "ok" and full["data"]["rows"] == [["2026", 21646220.0]]
    assert 21646220.0 - 21179764.0 == 466456.0                  # exactly the aged 85 and over
    # the county-level child of this generation is refused outright
    refused = call("query_data", dataset="POP107D_varste_judet", group_by=["TIME_PERIOD"])
    assert refused["status"] == "unavailable"
    assert refused["reason"] in ("source_total_unchecked", "conflicting_grain")
