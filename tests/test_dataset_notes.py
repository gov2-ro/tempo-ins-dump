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
