"""AQ-13: INS published Total cells in the tools (query_data, rank_entities, compare_periods,
describe_dataset). A published cell appears only after a non-additive refusal for a dropped
Total, never inside the rows of a data-file result and never when the file holds the value."""
import json

import duckdb
import pytest
from at01_fixtures import add_dataset, call, make_env
from test_at01_changes import area_dim, time_dim, unit_dim

from app.services import recipes

NAMES = ["Alfa", "Beta", "Gama"]
SCHEMA = """CREATE TABLE published_totals (
    matrix_code VARCHAR NOT NULL, ref_area VARCHAR NOT NULL, time_period VARCHAR NOT NULL,
    breakdown VARCHAR NOT NULL DEFAULT '', value DOUBLE, unit VARCHAR, query_id VARCHAR, fetched_at VARCHAR,
    file_sha256 VARCHAR, meta_sha256 VARCHAR, ins_updated VARCHAR,
    PRIMARY KEY (matrix_code, ref_area, time_period, breakdown))"""
REFUSALS = ("missing_weights", "non_additive_measure", "unverified_structure")
SEX = json.dumps({"SEX": "Feminin"}, separators=(",", ":"))


def cells(db, matrix, qid, values):
    for area, period, bd, v in values:
        db.execute("INSERT INTO published_totals VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                   [matrix, area, period, bd, v, "Procente", qid, "2026-11-19T10:00:00+00:00", "abc", "def",
                    "05-01-2026"])


def build(corpus):
    res = ("RESIDENCE", "Medii", None, [("Urban", {}), ("Rural", {})])
    sex = ("SEX", "Sexe", None, [("Masculin", {}), ("Feminin", {})])
    # RATEPUB: a rate by residence; INS's Total (both areas) is not in the file
    rows = [(e, y, r, "Procente", float(i + j + (2 if r == "Rural" else 0)))
            for i, e in enumerate(NAMES) for j, y in enumerate(("2021", "2022")) for r in ("Urban", "Rural")]
    add_dataset(corpus, "RATEPUB", [area_dim(NAMES), time_dim(("2021", "2022")), res, unit_dim("Procente")],
                [(e, y, r, u, v) for e, y, r, u, v in rows], unit_type="percentage", name="Rata infantila")
    # SEXPUB: a rate by sex; the file holds the sex rows, INS's both-sexes cell is not in it
    rows2 = [(e, y, s, "Procente", 10.0 + i + (1 if s == "Feminin" else 0))
             for i, e in enumerate(NAMES) for y in ("2021", "2022") for s in ("Masculin", "Feminin")]
    add_dataset(corpus, "SEXPUB", [area_dim(NAMES), time_dim(("2021", "2022")), sex, unit_dim("Procente")],
                rows2, unit_type="percentage", name="Rata somajului pe sexe")
    # CNT: a count; never served from published cells
    add_dataset(corpus, "CNT", [area_dim(NAMES), time_dim(("2021", "2022")), res, unit_dim("Numar")],
                [(e, y, r, "Numar", 3.0) for e in NAMES for y in ("2021", "2022") for r in ("Urban", "Rural")],
                unit_type="count", name="Persoane")
    # an indicator without any cells
    add_dataset(corpus, "RATENONE", [area_dim(NAMES), time_dim(("2021", "2022")), res, unit_dim("Procente")],
                [(e, y, r, "Procente", 1.0) for e in NAMES for y in ("2021", "2022") for r in ("Urban", "Rural")],
                unit_type="percentage", name="Rata fara celule")
    db = duckdb.connect(str(corpus / "metadata.duckdb"))
    db.execute(SCHEMA)
    cells(db, "RATEPUB", "RATEPUB-total",
          [(a, y, "", 100 + i + j) for i, a in enumerate(["TOTAL"] + NAMES) for j, y in enumerate(("2021", "2022"))])
    cells(db, "SEXPUB", "SEXPUB-total",
          [(a, y, b, 50 + i + j + (1 if b else 0))
           for i, a in enumerate(["TOTAL"] + NAMES) for j, y in enumerate(("2021", "2022")) for b in ("", SEX)])
    cells(db, "CNT", "CNT-total", [("TOTAL", "2021", "", 999)])
    db.close()


@pytest.fixture
def env(tmp_path, monkeypatch):
    return make_env(tmp_path, monkeypatch, build=build)


def conn_of(env):
    from app.services import data_query
    return data_query.get_conn() if hasattr(data_query, "get_conn") else None


# ------------------------------------------------------------------ the lookup

def test_published_cell_returns_value_and_provenance(env):
    from app.db import get_conn
    c = get_conn()
    cell = recipes.published_cell(c, "RATEPUB", "alfa", "2021", "")
    assert cell["value"] == 101 and cell["area"] == "Alfa" and cell["matrix"] == "RATEPUB"
    assert cell["query_id"] == "RATEPUB-total" and cell["ins_updated"] == "05-01-2026"
    assert recipes.published_cell(c, "RATEPUB", "Alfa", "1999", "") is None            # no such period
    assert recipes.published_cell(c, "RATENONE", "Alfa", "2021", "") is None           # no cells
    assert recipes.published_cell(c, "SEXPUB", "Alfa", "2021", {"SEX": "Feminin"})["value"] == 52
    assert recipes.published_cell(c, "SEXPUB", "Alfa", "2021", "")["value"] == 51
    assert recipes.published_cell(c, "SEXPUB", "Alfa", "2021", {"SEX": "Neutru"}) is None


def test_the_recipe_reader_ignores_breakdown_rows(env):
    from app.db import get_conn
    cells_ = recipes._published_cells(get_conn(), "SEXPUB")
    assert cells_[("total", "2021")]["value"] == 50          # the both-sexes cell, not the Feminin one


def test_a_generation_without_the_breakdown_column_reads_its_rows_as_totals(tmp_path):
    db = duckdb.connect(str(tmp_path / "old.duckdb"))
    db.execute("CREATE TABLE matrices (matrix_code VARCHAR, parent_matrix_code VARCHAR)")
    db.execute("CREATE TABLE published_totals (matrix_code VARCHAR, ref_area VARCHAR, time_period VARCHAR, "
               "value DOUBLE, unit VARCHAR, query_id VARCHAR, fetched_at VARCHAR, file_sha256 VARCHAR, "
               "meta_sha256 VARCHAR, ins_updated VARCHAR)")
    db.execute("INSERT INTO published_totals VALUES ('M1','TOTAL','2020',5,'Lei','q','t','s','m','u')")
    assert recipes.published_cell(db, "M1", "TOTAL", "2020")["value"] == 5
    assert recipes._published_cells(db, "M1")[("total", "2020")]["value"] == 5
    db2 = duckdb.connect(str(tmp_path / "none.duckdb"))                                 # no table at all
    db2.execute("CREATE TABLE matrices (matrix_code VARCHAR, parent_matrix_code VARCHAR)")
    assert recipes.published_cell(db2, "M1", "TOTAL", "2020") is None
    assert recipes.published_coverage(db2, "M1") is None


def test_a_split_child_reads_its_parents_cells(tmp_path):
    db = duckdb.connect(str(tmp_path / "c.duckdb"))
    db.execute("CREATE TABLE matrices (matrix_code VARCHAR, parent_matrix_code VARCHAR)")
    db.execute("INSERT INTO matrices VALUES ('P1', NULL), ('P1_judete', 'P1')")
    db.execute(SCHEMA)
    cells(db, "P1", "q", [("TOTAL", "2020", "", 7)])
    assert recipes.published_cell(db, "P1_judete", "TOTAL", "2020")["matrix"] == "P1"


def test_published_selection_rules(env):
    from app.db import get_conn
    c = get_conn()
    sel = recipes.published_selection(c, "RATEPUB", {"REF_AREA": ["Beta"], "TIME_PERIOD": ["2022"]}, ["TIME_PERIOD"])
    assert sel["rows"] == [["Beta", "2022", "Procente", 103]] and sel["columns"][-1] == "OBS_VALUE"
    # an area left out means the country
    sel = recipes.published_selection(c, "RATEPUB", {"TIME_PERIOD": ["2021"]}, ["TIME_PERIOD"])
    assert sel["rows"][0][:2] == ["TOTAL", "2021"]
    # a non-Total pin on a dimension the cells do not break down by: no cell exists for that cut
    assert recipes.published_selection(c, "RATEPUB", {"RESIDENCE": ["Urban"], "TIME_PERIOD": ["2021"]},
                                       ["TIME_PERIOD"]) is None
    # a Total pin is the collapse itself
    assert recipes.published_selection(c, "RATEPUB", {"RESIDENCE": ["Total"], "TIME_PERIOD": ["2021"]},
                                       ["TIME_PERIOD"]) is not None
    # no period: no single cell
    assert recipes.published_selection(c, "RATEPUB", {}, ["REF_AREA"]) is None
    # a raw request leaves dimensions open: it must name them
    assert recipes.published_selection(c, "RATEPUB", {"TIME_PERIOD": ["2021"]}, [],
                                       require_pinned=["RESIDENCE"]) is None
    # breakdown: a named label, the Total when left out, every label when grouped
    f = {"TIME_PERIOD": ["2021"], "REF_AREA": ["Alfa"]}
    assert recipes.published_selection(c, "SEXPUB", {**f, "SEX": ["Feminin"]}, ["TIME_PERIOD"])["rows"][0][2:] == [
        "Feminin", "Procente", 52]
    assert recipes.published_selection(c, "SEXPUB", f, ["TIME_PERIOD"])["rows"][0][2:] == ["Procente", 51]
    both = recipes.published_selection(c, "SEXPUB", f, ["TIME_PERIOD", "SEX"])
    assert [r[2] for r in both["rows"]] == ["Feminin"]            # only the labels INS published here
    assert recipes.published_selection(c, "SEXPUB", {**f, "SEX": ["Feminin", "Masculin"]}, ["TIME_PERIOD"]) is None


# ------------------------------------------------------------------ query_data

def test_a_refused_rate_total_is_served_as_the_published_cell(env):
    e = call("query_data", dataset="RATEPUB", filters={"REF_AREA": ["Beta"], "TIME_PERIOD": ["2022"]},
             group_by=["TIME_PERIOD"], lang="en")
    assert e["status"] == "ok" and e["reason"] is None
    assert e["data"]["rows"] == [["Beta", "2022", "Procente", 103]]
    assert e["data"]["value_source"] == "ins_published"
    codes = [w["code"] for w in e["warnings"]]
    assert "published_total" in codes and "unverified_total" not in codes
    assert e["data"]["published_total"]["matrix"] == "RATEPUB"
    assert e["data"]["published_total"]["fetches"][0]["query_id"] == "RATEPUB-total"
    assert e["provenance"]["sources"][0]["published_total"]["matrix"] == "RATEPUB"
    assert "INS" in e["message"] and "published" in e["message"]
    ro = call("query_data", dataset="RATEPUB", filters={"REF_AREA": ["Beta"], "TIME_PERIOD": ["2022"]},
              group_by=["TIME_PERIOD"], lang="ro")
    assert "publicat de INS" in ro["message"] and ro["warnings"][-1]["code"] == "published_total"


def test_the_series_over_time_and_the_total_filter_are_served(env):
    e = call("query_data", dataset="RATEPUB", filters={"REF_AREA": ["Alfa"]}, group_by=["TIME_PERIOD"])
    assert [r[1] for r in e["data"]["rows"]] == ["2021", "2022"] and e["status"] == "ok"
    t = call("query_data", dataset="RATEPUB",
             filters={"REF_AREA": ["Alfa"], "TIME_PERIOD": ["2021"], "RESIDENCE": ["Total"]})
    assert t["status"] == "ok" and t["data"]["rows"] == [["Alfa", "2021", "Procente", 101]]


def test_the_country_is_the_cell_when_the_area_is_collapsed(env):
    e = call("query_data", dataset="RATEPUB", filters={"TIME_PERIOD": ["2021"]}, group_by=["TIME_PERIOD"])
    assert e["status"] == "ok" and e["data"]["rows"] == [["TOTAL", "2021", "Procente", 100]]


def test_by_sex_uses_the_breakdown_cell(env):
    e = call("query_data", dataset="SEXPUB", filters={"SEX": ["Feminin"], "TIME_PERIOD": ["2022"]},
             group_by=["TIME_PERIOD"])
    assert e["status"] == "ok"
    assert e["data"]["rows"] == [["TOTAL", "2022", "Feminin", "Procente", 52]]
    both = call("query_data", dataset="SEXPUB", filters={"TIME_PERIOD": ["2022"]}, group_by=["TIME_PERIOD"])
    assert both["data"]["rows"] == [["TOTAL", "2022", "Procente", 51]]


def test_the_published_cell_never_replaces_a_value_the_file_has(env):
    # every dimension pinned: the file has the row, so the file answers (raw rows, no published cell)
    e = call("query_data", dataset="SEXPUB",
             filters={"REF_AREA": ["Alfa"], "TIME_PERIOD": ["2021"], "SEX": ["Feminin"]})
    assert e["status"] == "ok" and "published_total" not in [w["code"] for w in e["warnings"]]
    assert e["data"]["rows"][0][-1] == 11.0 and "value_source" not in e["data"]
    r = call("query_data", dataset="RATEPUB",
             filters={"REF_AREA": ["Alfa"], "TIME_PERIOD": ["2021"], "RESIDENCE": ["Urban"]})
    assert r["data"]["rows"][0][-1] == 0.0 and "value_source" not in r["data"]


def test_no_published_cell_for_another_cut_or_without_cells_or_for_a_count(env):
    # a pinned residence area has no published Total: the refusal of the policy stays
    pinned = call("query_data", dataset="RATEPUB", filters={"RESIDENCE": ["Urban"], "TIME_PERIOD": ["2021"]},
                  group_by=["TIME_PERIOD"])
    assert pinned["status"] == "unavailable" and pinned["reason"] in REFUSALS
    none = call("query_data", dataset="RATENONE", filters={"TIME_PERIOD": ["2021"]}, group_by=["TIME_PERIOD"])
    assert none["status"] == "unavailable" and none["reason"] in REFUSALS
    # a count is the policy's to sum or refuse; its (stray) published row is never used
    cnt = call("query_data", dataset="CNT", filters={"TIME_PERIOD": ["2021"]}, group_by=["TIME_PERIOD"])
    assert "published_total" not in [w["code"] for w in cnt["warnings"]]
    assert "value_source" not in cnt["data"] and not any(999 in r for r in cnt["data"]["rows"])


# ------------------------------------------------------------------ rank_entities, compare_periods

def test_a_ranking_with_no_total_in_the_file_ranks_the_published_cells_only(env):
    r = call("rank_entities", dataset="RATEPUB", entity_columns=["REF_AREA"], year="2022", top_k=3, lang="en")
    assert r["status"] == "ok"
    assert [(x["entity"]["REF_AREA"], x["value"]) for x in r["data"]["rows"]] == [
        ("Gama", 104), ("Beta", 103), ("Alfa", 102)]
    assert r["data"]["value_source"] == "ins_published"
    assert r["data"]["aggregates"][0]["entity"] == {"REF_AREA": "TOTAL"} and r["data"]["aggregates"][0]["value"] == 101
    assert "TOTAL" not in [x["entity"]["REF_AREA"] for x in r["data"]["rows"]]     # the country is not ranked
    assert [w["code"] for w in r["warnings"]].count("published_total") == 2


def test_a_file_ranking_gets_the_national_value_beside_it_not_inside_it(env):
    r = call("rank_entities", dataset="SEXPUB", entity_columns=["REF_AREA"], year="2022", filters={"SEX": ["Feminin"]},
             top_k=3)
    assert r["status"] in ("ok", "partial")
    assert [x["value"] for x in r["data"]["rows"]] == [13.0, 12.0, 11.0] and "value_source" not in r["data"]
    assert r["data"]["aggregates"] == [dict(r["data"]["aggregates"][0], value=52, year="2022")]
    assert all(x["entity"]["REF_AREA"] != "TOTAL" for x in r["data"]["rows"])
    # a pin the cells do not carry: no national value for that cut
    u = call("rank_entities", dataset="RATEPUB", entity_columns=["REF_AREA"], year="2022",
             filters={"RESIDENCE": ["Urban"]})
    assert "aggregates" not in u["data"] and "value_source" not in u["data"]


def test_compare_periods_lists_the_national_endpoints_in_aggregates(env):
    e = call("compare_periods", dataset="SEXPUB", entity_columns=["REF_AREA"], filters={"SEX": ["Feminin"]},
             intervals=[{"from": "2021", "to": "2022"}], lang="en")
    assert e["status"] in ("ok", "partial")
    agg = e["data"]["aggregates"]
    assert agg[0]["from_value"] == 51 and agg[0]["to_value"] == 52 and agg[0]["entity"] == {"REF_AREA": "TOTAL"}
    assert "published_total" in [w["code"] for w in e["warnings"]]
    assert all(r["entity"]["REF_AREA"] != "TOTAL" for iv in e["data"]["intervals"] for r in iv["rows"])


def test_compare_periods_keeps_its_refusal_for_a_dropped_total(env):
    e = call("compare_periods", dataset="RATEPUB", entity_columns=["REF_AREA"],
             intervals=[{"from": "2021", "to": "2022"}])
    assert e["status"] == "unavailable"


# ------------------------------------------------------------------ describe_dataset

def test_describe_says_which_periods_areas_and_breakdowns_are_published(env):
    d = call("describe_dataset", dataset="SEXPUB", lang="en")["data"]
    pt = d["published_total"]
    assert pt["matrix"] == "SEXPUB" and (pt["first"], pt["last"]) == ("2021", "2022")
    assert pt["national"] is True and pt["breakdowns"] == {"SEX": ["Feminin"]}
    note = [n for n in d["notes"] if n["id"] == "published_total"][0]["text"]
    assert "SEXPUB" in note and "2021" in note and "SEX" in note
    assert "published_total" not in call("describe_dataset", dataset="RATENONE")["data"]


def test_a_published_ranking_never_mixes_geographic_levels(env, monkeypatch):
    """Review fix: a split parent lists counties, regions and macroregions; its published cells must
    not be ranked together (FOM107E ranked 'Regiunea BUCURESTI - ILFOV' beside counties)."""
    from app.services.tools import ranking
    monkeypatch.setattr(ranking, "_area_levels", lambda conn, code: {"county", "region"})
    r = call("rank_entities", dataset="RATEPUB", entity_columns=["REF_AREA"], year="2022", top_k=3, lang="en")
    assert r["status"] != "ok" and r["data"].get("value_source") != "ins_published"
    monkeypatch.setattr(ranking, "_area_levels", lambda conn, code: {"county"})
    r = call("rank_entities", dataset="RATEPUB", entity_columns=["REF_AREA"], year="2022", top_k=3, lang="en")
    assert r["status"] == "ok" and r["data"]["value_source"] == "ins_published"
