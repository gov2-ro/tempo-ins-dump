"""AQ-13: the published-totals loader (breakdown column, area position, periods, migration)."""
import hashlib
import importlib.util
import json
from pathlib import Path

import duckdb
import pytest

ROOT = Path(__file__).resolve().parent.parent


def _load_module():
    spec = importlib.util.spec_from_file_location("load_published_totals", ROOT / "scripts" / "load-published-totals.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


L = _load_module()


def _csv(tmp_path, name, text):
    p = tmp_path / name
    p.write_text(text, encoding="utf-8")
    return p


def test_total_only_cells_have_empty_breakdown(tmp_path):
    p = _csv(tmp_path, "a.csv", "Sexe, Judete, Ani, UM: Procente, Valoare\n"
                                "Total, TOTAL, Anul 2020, Procente, 5.1\n"
                                "Total, Cluj, Anul 2020, Procente, 3\n")
    assert L.read_cells(p) == [("TOTAL", "2020", "", 5.1, "Procente"), ("Cluj", "2020", "", 3.0, "Procente")]


def test_non_total_pin_is_refused_unless_named_as_breakdown(tmp_path):
    p = _csv(tmp_path, "a.csv", "Sexe, Judete, Ani, UM: Procente, Valoare\n"
                                "Feminin, Cluj, Anul 2020, Procente, 3\n")
    with pytest.raises(ValueError, match="not a Total cell"):
        L.read_cells(p)
    assert L.read_cells(p, {"SEX": 0}) == [("Cluj", "2020", '{"SEX":"Feminin"}', 3.0, "Procente")]


def test_breakdown_total_label_means_empty_breakdown(tmp_path):
    p = _csv(tmp_path, "a.csv", "Sexe, Judete, Ani, UM: Procente, Valoare\n"
                                "Total, Cluj, Anul 2020, Procente, 4\n"
                                "Masculin, Cluj, Anul 2020, Procente, 3\n")
    rows = L.read_cells(p, {"SEX": 0})
    assert [r[2] for r in rows] == ["", '{"SEX":"Masculin"}']


def test_another_dimension_must_stay_total_even_with_a_breakdown(tmp_path):
    p = _csv(tmp_path, "a.csv", "Medii, Sexe, Judete, Ani, UM: Ani, Valoare\n"
                                "Urban, Feminin, Cluj, Anul 2020, Ani, 79\n")
    with pytest.raises(ValueError, match="not a Total cell"):
        L.read_cells(p, {"SEX": 1})


def test_area_position_and_no_area(tmp_path):
    p = _csv(tmp_path, "a.csv", "Judete, Sexe, Ani, UM: Ani, Valoare\n"
                                "Cluj, Feminin, Anul 2020, Ani, 79\n")
    # the area is not the dimension just before the period: name its position
    assert L.read_cells(p, {"SEX": 1}, area=0) == [("Cluj", "2020", '{"SEX":"Feminin"}', 79.0, "Ani")]
    q = _csv(tmp_path, "b.csv", "Categorii, Luni, UM: Procente, Valoare\n"
                                "Total, Luna mai 2026, Procente, 100.58\n")
    assert L.read_cells(q, area=False) == [("TOTAL", "2026-05", "", 100.58, "Procente")]


def test_periods_are_parsed_like_the_pipeline(tmp_path):
    p = _csv(tmp_path, "a.csv", "Categorii, Luni, UM: P, Valoare\n"
                                "Total, Luna ianuarie 1991, P, 1\n"
                                "Total, Trimestrul II 2025, P, 2\n")
    assert [r[1] for r in L.read_cells(p, area=False)] == ["1991-01", "2025-Q2"]
    bad = _csv(tmp_path, "c.csv", "A, Luni, UM: P, Valoare\nTotal, ceva, P, 1\n")
    with pytest.raises(ValueError, match="unsupported period"):
        L.read_cells(bad, area=False)


def test_duplicate_cell_and_suppressed_value(tmp_path):
    p = _csv(tmp_path, "a.csv", "Judete, Ani, UM: P, Valoare\nCluj, Anul 2020, P, :\n")
    assert L.read_cells(p)[0][3] is None
    d = _csv(tmp_path, "d.csv", "Judete, Ani, UM: P, Valoare\nCluj, Anul 2020, P, 1\nCluj, Anul 2020, P, 2\n")
    with pytest.raises(ValueError, match="duplicate"):
        L.read_cells(d)


def _manifest(tmp_path, entries):
    fetches = {}
    for qid, (matrix, text, extra) in entries.items():
        f = _csv(tmp_path, f"{qid}.csv", text)
        fetches[qid] = {"matrix": matrix, "file": f.name, "sha256": hashlib.sha256(f.read_bytes()).hexdigest(),
                        "fetched_at": "2026-11-19T10:00:00+00:00", "meta_file": str(tmp_path / "none.json"), **extra}
    (tmp_path / "manifest.json").write_text(json.dumps({"fetches": fetches}), encoding="utf-8")


def test_main_loads_breakdown_rows_and_replaces_a_matrix(tmp_path):
    db = tmp_path / "m.duckdb"
    _manifest(tmp_path, {"Q1": ("AAA1", "Sexe, Judete, Ani, UM: P, Valoare\n"
                                        "Total, TOTAL, Anul 2020, P, 5\nFeminin, TOTAL, Anul 2020, P, 6\n",
                                {"breakdown": {"SEX": 0}})})
    assert L.main(["--cells", str(tmp_path), "--db", str(db)]) == 0
    con = duckdb.connect(str(db))
    assert con.execute("SELECT breakdown, value FROM published_totals ORDER BY breakdown").fetchall() == [
        ("", 5.0), ('{"SEX":"Feminin"}', 6.0)]
    con.close()
    # a second load replaces the matrix and leaves others alone
    con = duckdb.connect(str(db))
    con.execute("INSERT INTO published_totals (matrix_code, ref_area, time_period, value) VALUES ('ZZZ9','TOTAL','2020',1)")
    con.close()
    assert L.main(["--cells", str(tmp_path), "--db", str(db)]) == 0
    con = duckdb.connect(str(db))
    assert con.execute("SELECT count(*) FROM published_totals").fetchone()[0] == 3
    con.close()


def test_main_rebuilds_a_table_without_the_breakdown_column(tmp_path):
    db = tmp_path / "old.duckdb"
    con = duckdb.connect(str(db))
    con.execute("""CREATE TABLE published_totals (
        matrix_code VARCHAR NOT NULL, ref_area VARCHAR NOT NULL, time_period VARCHAR NOT NULL,
        value DOUBLE, unit VARCHAR, query_id VARCHAR, fetched_at VARCHAR,
        file_sha256 VARCHAR, meta_sha256 VARCHAR, ins_updated VARCHAR,
        PRIMARY KEY (matrix_code, ref_area, time_period))""")
    con.execute("INSERT INTO published_totals (matrix_code, ref_area, time_period, value) VALUES ('OLD1','TOTAL','2019',7)")
    con.close()
    _manifest(tmp_path, {"Q1": ("AAA1", "Judete, Ani, UM: P, Valoare\nTOTAL, Anul 2020, P, 5\n", {})})
    assert L.main(["--cells", str(tmp_path), "--db", str(db)]) == 0
    con = duckdb.connect(str(db))
    assert con.execute("SELECT matrix_code, breakdown, value FROM published_totals ORDER BY 1").fetchall() == [
        ("AAA1", "", 5.0), ("OLD1", "", 7.0)]
    con.close()


def test_the_shipped_spec_names_its_breakdowns_and_areas():
    spec = json.loads((ROOT / "app" / "data" / "published_totals.json").read_text(encoding="utf-8"))
    ids = [q["id"] for q in spec["queries"]]
    assert len(ids) == len(set(ids))
    for q in spec["queries"]:
        n = len(q["select"])
        for pos in (q.get("breakdown") or {}).values():
            assert 0 <= pos < n - 1                        # not the unit dimension
        if isinstance(q.get("area"), int) and q["area"] is not False:
            assert 0 <= q["area"] < n - 1
