"""Curated dataset notes: file shape, inheritance by split children, page and API
exposure, and the generated decision log staying in sync with the JSON."""
import importlib.util
import json
from pathlib import Path

import pytest

from app.services import dataset_notes as dn

ROOT = Path(__file__).resolve().parent.parent


def test_notes_file_is_well_formed():
    notes = dn.load()
    ids = [n["id"] for n in notes]
    assert len(ids) == len(set(ids))
    for n in notes:
        assert n["kind"] in dn.KINDS, n["id"]
        assert n["codes"] and all(isinstance(c, str) and c for c in n["codes"]), n["id"]
        assert n["text"].get("ro") and n["text"].get("en"), n["id"]
        assert isinstance(n.get("public"), bool), n["id"]
        if n.get("ins", {}).get("raise"):
            assert n["ins"].get("question"), n["id"]


NOTES = [
    {"id": "a", "codes": ["P1"], "kind": "caveat", "public": True, "text": {"ro": "ra", "en": "ea"}},
    {"id": "b", "codes": ["P1_judete"], "kind": "excluded", "public": True,
     "text": {"ro": "rb", "en": "eb"}, "data": {"x": 1}},
    {"id": "c", "codes": ["P1"], "kind": "decision", "public": False, "text": {"ro": "rc", "en": "ec"}},
    {"id": "d", "codes": ["P10"], "kind": "caveat", "public": True, "text": {"ro": "rd", "en": "ed"}},
]


def test_parent_notes_cover_split_children_only():
    assert [n["id"] for n in dn.for_code("P1", notes=NOTES)] == ["a"]
    kid = dn.for_code("P1_judete", "en", notes=NOTES)
    assert [(n["id"], n["text"]) for n in kid] == [("a", "ea"), ("b", "eb")]
    assert kid[1]["data"] == {"x": 1}
    assert [n["id"] for n in dn.for_code("P1_regiuni", notes=NOTES)] == ["a"]
    assert [n["id"] for n in dn.for_code("P10", notes=NOTES)] == ["d"]      # no prefix match
    assert [n["id"] for n in dn.for_code("P1", public_only=False, notes=NOTES)] == ["a", "c"]


def test_report_is_in_sync_with_the_notes():
    spec = importlib.util.spec_from_file_location("notes_report", ROOT / "scripts/build-notes-report.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    committed = (ROOT / "docs/reports/ins-notes.md").read_text(encoding="utf-8")
    assert committed == mod.render(dn.load()), "run scripts/build-notes-report.py"


@pytest.mark.corpus
def test_notes_reach_the_api_and_the_page():
    from fastapi.testclient import TestClient
    from app.main import app
    c = TestClient(app)
    meta = c.get("/api/datasets/POP105A_judete_grupe").json()
    assert "POP105A-census-break" in [n["id"] for n in meta["notes"]]
    page = c.get("/dataset/POP105A_judete_grupe").text
    assert "dbv2-ssr-notes" in page and "recensământul din 2021" in page


@pytest.mark.corpus
def test_note_codes_name_real_datasets():
    from app.db import get_conn
    con = get_conn()
    try:
        known = {r[0] for r in con.execute("SELECT matrix_code FROM matrices").fetchall()}
    finally:
        con.close()
    missing = {c for n in dn.load() for c in n["codes"] if c not in known}
    assert not missing, sorted(missing)


def _tiny_db():
    import duckdb
    con = duckdb.connect()
    con.execute("CREATE TABLE matrices (matrix_code VARCHAR, parent_matrix_code VARCHAR)")
    con.execute("CREATE TABLE dimensions (dimension_id INT, matrix_code VARCHAR, dim_code INT, "
                "dim_column_name VARCHAR, dim_label VARCHAR, option_count INT)")
    con.execute("CREATE TABLE dimension_options (dimension_id INT, option_label VARCHAR)")
    con.executemany("INSERT INTO matrices VALUES (?, ?)", [("M1", None), ("M1_judete", "M1")])
    con.executemany("INSERT INTO dimensions VALUES (?,?,?,?,?,?)", [
        (1, "M1", 1, "SEX", "Sexe", 3), (2, "M1", 2, "REF_AREA", "Judete", 43),
        (3, "M1", 3, "TIME_PERIOD", "Ani", 5), (4, "M1", 4, "AGE", "Varste", 4),
        (5, "M1_judete", 1, "SEX", "Sexe", 2), (6, "M1_judete", 2, "REF_AREA", "judete", 42)])
    con.executemany("INSERT INTO dimension_options VALUES (?, ?)", [
        (1, "Total"), (1, "Masculin"), (2, " TOTAL "), (2, "Cluj"), (3, "Anul 2024"),
        (4, "0-4 ani"), (4, "5-9 ani")])
    return con


def test_generated_note_names_the_dropped_totals_of_a_non_additive_dataset():
    con = _tiny_db()
    n = dn.source_totals_note(con, "M1_judete", "non_additive", "ro")
    assert n["id"] == "source-totals-not-downloaded"
    assert n["data"] == {"matrix": "M1", "dimensions": ["Sexe", "Judete"]}   # AGE has no Total
    assert "„Sexe”" in n["text"] and "nu îl calculează" in n["text"]
    assert dn.source_totals_note(con, "M1_judete", "additive") is None       # counts are summed
    assert dn.source_totals_note(con, "NOPE", "non_additive") is None


@pytest.mark.corpus
def test_generated_note_on_a_real_mean_dataset():
    from fastapi.testclient import TestClient
    from app.main import app
    c = TestClient(app)
    ids = [n["id"] for n in c.get("/api/datasets/FOM106E_judete").json()["notes"]]
    assert "source-totals-not-downloaded" in ids
    ids = [n["id"] for n in c.get("/api/datasets/POP105A_judete_grupe").json()["notes"]]
    assert "source-totals-not-downloaded" not in ids                      # a count: summed exactly
    assert "descărcarea noastră nu o conține" in c.get("/dataset/FOM106E_judete").text
