"""repair-corpus.py --apply --step dim-columns: dimensions sharing one dim_column_name
(INT109A: two CAEN dimensions both 'ECON_ACTIVITY') are renamed to the parquet columns
stage 9 wrote, in the COPY only. The fixture DB has the real FKs and indexes, which make
a plain UPDATE of dim_column_name fail."""
import shutil
import subprocess
import sys
from pathlib import Path

import duckdb
import pytest

from fix03b_env import DDL

ROOT = Path(__file__).resolve().parent.parent
REPAIR = ROOT / "scripts" / "repair-corpus.py"
PARQUET_COLS = ["ECON_ACTIVITY", "CAEN_SUBSECTIUNI", "ECON_ACTIVITY_2", "TIME_PERIOD", "OBS_VALUE"]


def run(*args):
    return subprocess.run([sys.executable, str(REPAIR), *args], capture_output=True, text=True)


def make_tree(root: Path, parquet_cols=PARQUET_COLS) -> Path:
    pq = root / "corpus" / "parquet"
    pq.mkdir(parents=True)
    con = duckdb.connect(str(root / "corpus" / "metadata.duckdb"))
    con.execute(DDL)
    con.execute("INSERT INTO matrices (matrix_code, matrix_name, context_code) VALUES "
                "('INT1', 'Intreprinderi', '1'), ('OK1', 'Fine', '1')")
    con.execute("""INSERT INTO dimensions VALUES
        (10, 'INT1', 1, 'CAEN - sectiuni', 'ECON_ACTIVITY', 2),
        (11, 'INT1', 2, 'CAEN - subsectiuni', 'CAEN_SUBSECTIUNI', 2),
        (12, 'INT1', 3, 'CAEN (activitati)', 'ECON_ACTIVITY', 2),
        (13, 'INT1', 4, 'Perioade', 'TIME_PERIOD', 1),
        (20, 'OK1', 1, 'CAEN', 'ECON_ACTIVITY', 2)""")
    con.execute("""INSERT INTO dimension_options VALUES
        (1, 10, 501, 'C Industrie', 0, NULL), (2, 10, 502, 'D Energie', 1, NULL),
        (3, 11, 511, 'CA Extractiva', 0, NULL), (4, 11, 512, 'DA Energie', 1, NULL),
        (5, 12, 521, '10 Carbune', 0, NULL), (6, 12, 522, '40 Energie', 1, NULL),
        (7, 13, 100, 'Anul 2020', 0, NULL), (8, 20, 501, 'C Industrie', 0, NULL),
        (9, 20, 502, 'D Energie', 1, NULL)""")
    cols = ", ".join(f"'{i}' AS {c}" if c != "OBS_VALUE" else "1.0 AS OBS_VALUE"
                     for i, c in enumerate(parquet_cols))
    con.execute(f"COPY (SELECT {cols}) TO '{pq / 'INT1.parquet'}' (FORMAT parquet)")
    con.execute(f"COPY (SELECT 'C' AS ECON_ACTIVITY, '2020' AS TIME_PERIOD, 1.0 AS OBS_VALUE) "
                f"TO '{pq / 'OK1.parquet'}' (FORMAT parquet)")
    con.close()
    return root


def dims(root, mc="INT1"):
    con = duckdb.connect(str(root / "corpus" / "metadata.duckdb"), read_only=True)
    try:
        return con.execute("SELECT dimension_id, dim_column_name FROM dimensions WHERE matrix_code = ? "
                           "ORDER BY 1", [mc]).fetchall(), \
            con.execute("SELECT * FROM dimension_options ORDER BY option_id").fetchall()
    finally:
        con.close()


@pytest.fixture
def trees(tmp_path):
    src = make_tree(tmp_path / "src")
    copy = tmp_path / "copy"
    shutil.copytree(src, copy)
    return src, copy


def test_renames_duplicates_in_the_copy_only(trees):
    src, copy = trees
    src_before, opts_before = dims(src)
    r = run("--data-dir", str(src), "--apply", "--step", "dim-columns", "--target-dir", str(copy))
    assert r.returncode == 0, r.stdout + r.stderr
    assert "renamed 1 dimensions in 1 matrices (0 duplicate columns left)" in r.stdout
    got, opts = dims(copy)
    assert got == [(10, "ECON_ACTIVITY"), (11, "CAEN_SUBSECTIUNI"), (12, "ECON_ACTIVITY_2"),
                   (13, "TIME_PERIOD")]
    assert opts == opts_before                                   # same ids, same options
    assert dims(copy, "OK1")[0] == [(20, "ECON_ACTIVITY")]       # unrelated matrix untouched
    assert dims(src) == (src_before, opts_before)                # source untouched


def test_every_dimension_name_exists_in_the_parquet_after_repair(trees):
    src, copy = trees
    run("--data-dir", str(src), "--apply", "--step", "dim-columns", "--target-dir", str(copy))
    names = {n for _, n in dims(copy)[0]}
    assert names <= set(PARQUET_COLS)


def test_refuses_in_place(trees):
    src, _ = trees
    before = dims(src)
    r = run("--data-dir", str(src), "--apply", "--step", "dim-columns", "--target-dir", str(src))
    assert r.returncode != 0 and "source corpus" in r.stdout + r.stderr
    assert dims(src) == before


def test_refuses_when_parquet_columns_do_not_explain_the_duplicates(tmp_path):
    src = make_tree(tmp_path / "src", parquet_cols=["ECON_ACTIVITY", "CAEN_SUBSECTIUNI",
                                                    "TIME_PERIOD", "OBS_VALUE"])
    copy = tmp_path / "copy"
    shutil.copytree(src, copy)
    before = dims(copy)
    r = run("--data-dir", str(src), "--apply", "--step", "dim-columns", "--target-dir", str(copy))
    assert r.returncode != 0 and "count mismatch" in r.stdout + r.stderr
    assert dims(copy) == before


def test_failed_reinsert_restores_the_original_rows(trees):
    import importlib.util
    spec = importlib.util.spec_from_file_location("repair_corpus_dc", REPAIR)
    rc = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(rc)
    src, copy = trees
    before = dims(copy)
    bad = {"problems": [], "changes": [{"matrix_code": "INT1", "dimension_id": 12,
                                        "old": "ECON_ACTIVITY", "new": None}]}   # NOT NULL violation
    with pytest.raises(duckdb.ConstraintException):
        rc.apply_dim_columns(bad, src, copy)
    assert dims(copy) == before
