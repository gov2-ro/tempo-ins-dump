"""FIX-03 phase 1: pipeline child scripts must exit nonzero on handled errors.

Offline: network calls are replaced, all files live in tmp_path (scripts that
resolve paths from cwd are run with cwd=tmp_path).
"""
import importlib.util
import json
import subprocess
import sys
import textwrap
from pathlib import Path
from types import SimpleNamespace

import duckdb
import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def load(name, filename, monkeypatch=None):
    spec = importlib.util.spec_from_file_location(name, ROOT / filename)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ------------------------------------------------------------ 3-fetch-metas.py
def run_fetch_metas(tmp_path, mode):
    """Run a copy of 3-fetch-metas.py in tmp_path with requests.get faked."""
    script = tmp_path / "3-fetch-metas.py"
    script.write_text((ROOT / "3-fetch-metas.py").read_text())
    runner = tmp_path / "runner.py"
    runner.write_text(textwrap.dedent(f"""
        import runpy, sys, types, requests
        def fake_get(url, **kw):
            mode = {mode!r}
            if mode == "down":
                raise requests.exceptions.ConnectionError("down")
            r = types.SimpleNamespace()
            r.text = "<html>not json</html>" if mode == "html" else '{{"ok": 1}}'
            r.raise_for_status = lambda: None
            return r
        requests.get = fake_get
        sys.argv = ["3-fetch-metas.py", "--force"]
        runpy.run_path({str(script)!r}, run_name="__main__")
    """))
    return subprocess.run([sys.executable, str(runner)], cwd=tmp_path, capture_output=True, text=True)


def seed_matrices_csv(tmp_path):
    d = tmp_path / "data" / "1-indexes" / "ro"
    d.mkdir(parents=True)
    (d / "matrices.csv").write_text("code,name\nAAA1,One\n")


def test_fetch_metas_missing_index_exits_nonzero(tmp_path):
    assert run_fetch_metas(tmp_path, "ok").returncode == 1


@pytest.mark.parametrize("mode,rc", [("down", 1), ("html", 1), ("ok", 0)])
def test_fetch_metas_exit_codes(tmp_path, mode, rc):
    seed_matrices_csv(tmp_path)
    res = run_fetch_metas(tmp_path, mode)
    assert res.returncode == rc, res.stdout + res.stderr
    out = tmp_path / "data" / "2-metas" / "ro" / "AAA1.json"
    assert out.exists() == (rc == 0)       # a non-JSON body is never persisted


# ------------------------------------------------------------- 6-fetch-csv.py
@pytest.fixture
def fetch_csv(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)           # the script writes data/logs and reads data/2-metas relative to cwd
    mod = load("fetch_csv_t", "6-fetch-csv.py")
    metas = tmp_path / "data" / "2-metas" / "ro"
    metas.mkdir(parents=True)
    (metas / "AAA1.json").write_text("{}")
    monkeypatch.setattr(mod, "load_matrix_definition", lambda p: {})
    monkeypatch.setattr(mod, "calculate_cell_count", lambda d, include_totals=False: 10)
    monkeypatch.setattr(mod, "convert_to_pivot_payload", lambda d, c, include_totals=False: {})
    monkeypatch.setattr(mod, "has_judete_and_localitati", lambda d: (False, None, None))
    return mod


def fake_post(body: bytes):
    def post(url, **kw):
        return SimpleNamespace(content=body, status_code=200, headers={},
                               raise_for_status=lambda: None)
    return post


def test_fetch_csv_success_exit_zero(fetch_csv, monkeypatch):
    monkeypatch.setattr(fetch_csv.requests, "post", fake_post(b"a,b\n1,2\n3,4\n"))
    assert fetch_csv.main(["--matrix", "AAA1", "--force"]) == 0


def test_fetch_csv_empty_dataset_exit_3(fetch_csv, monkeypatch):
    monkeypatch.setattr(fetch_csv.requests, "post", fake_post(b"a,b\n"))
    assert fetch_csv.main(["--matrix", "AAA1", "--force"]) == fetch_csv.EXIT_EMPTY_DATASET == 3


def test_fetch_csv_api_cell_limit_exit_1(fetch_csv, monkeypatch):
    body = "Selectia dvs actuala ar solicita 99999 celule, pragul de 30000 de celule".encode()
    monkeypatch.setattr(fetch_csv.requests, "post", fake_post(body))
    assert fetch_csv.main(["--matrix", "AAA1", "--force"]) == 1
    assert not (Path("data/4-datasets/ro/AAA1.csv")).exists()   # error text never saved as CSV


def test_fetch_csv_oversized_unhandled_exit_1(fetch_csv, monkeypatch):
    monkeypatch.setattr(fetch_csv, "calculate_cell_count", lambda d, include_totals=False: 10**7)
    monkeypatch.setattr(fetch_csv, "fetch_by_generic_chunks", lambda *a, **k: False)
    assert fetch_csv.main(["--matrix", "AAA1", "--force"]) == 1


def test_fetch_csv_http_error_exit_1(fetch_csv, monkeypatch):
    def boom(url, **kw):
        raise fetch_csv.requests.exceptions.ConnectionError("down")
    monkeypatch.setattr(fetch_csv.requests, "post", boom)
    assert fetch_csv.main(["--matrix", "AAA1", "--force"]) == 1


def test_fetch_csv_missing_metadata_exit_1(fetch_csv):
    assert fetch_csv.main(["--matrix", "NOPE9", "--force"]) == 1


def test_fetch_csv_existing_file_without_force_is_ok(fetch_csv, tmp_path):
    out = tmp_path / "data" / "4-datasets" / "ro"
    out.mkdir(parents=True)
    (out / "AAA1.csv").write_text("a\n1\n")
    assert fetch_csv.main(["--matrix", "AAA1"]) == 0


# ------------------------------------------------------ 13-dimension-structure.py
def test_dimension_structure_failure_exits_nonzero_and_keeps_old_rows(tmp_path, monkeypatch):
    mod = load("dimstruct_t", "13-dimension-structure.py")
    db = tmp_path / "meta.duckdb"
    con = duckdb.connect(str(db))
    con.execute(mod.DDL)
    con.execute(f"INSERT INTO {mod.TABLE} (matrix_code, dim_column, levels, confidence) VALUES ('BAD1', 'd', '[]', 'verified')")
    con.close()
    monkeypatch.setattr(mod, "DB_PATH", str(db))
    monkeypatch.setattr(mod, "FALLBACK_DB", str(tmp_path / "fallback.duckdb"))

    def boom(rconn, pconn, code):
        raise ValueError("profiling exploded")
    monkeypatch.setattr(mod, "profile_matrix", boom)
    monkeypatch.setattr(sys, "argv", ["13-dimension-structure.py", "--matrix", "BAD1"])
    with pytest.raises(SystemExit) as e:
        mod.main()
    assert e.value.code == 1
    con = duckdb.connect(str(db), read_only=True)
    assert con.execute(f"SELECT COUNT(*) FROM {mod.TABLE} WHERE matrix_code='BAD1'").fetchone()[0] == 1
    con.close()


def test_dimension_structure_success_exits_zero(tmp_path, monkeypatch):
    mod = load("dimstruct_t2", "13-dimension-structure.py")
    db = tmp_path / "meta.duckdb"
    duckdb.connect(str(db)).close()
    monkeypatch.setattr(mod, "DB_PATH", str(db))
    monkeypatch.setattr(mod, "FALLBACK_DB", str(tmp_path / "fallback.duckdb"))
    monkeypatch.setattr(mod, "profile_matrix", lambda r, p, c: [])
    monkeypatch.setattr(sys, "argv", ["13-dimension-structure.py", "--matrix", "OK1"])
    mod.main()   # returns normally


# -------------------------------------------------------- 12-split-datasets.py
def run_split_main(mod, tmp_path, monkeypatch, split_impl):
    db = tmp_path / "meta.duckdb"
    duckdb.connect(str(db)).close()
    monkeypatch.setattr(mod, "DB_FILE", db)
    monkeypatch.setattr(mod, "PARQUET_V3_DIR", tmp_path / "parquet")
    rule = SimpleNamespace(matrix_code="AAA1", pattern="multi_um", groups=[1, 2])
    monkeypatch.setattr(mod, "detect_all", lambda conn: [rule])
    monkeypatch.setattr(mod, "ensure_schema", lambda conn: conn.execute(
        "CREATE TABLE IF NOT EXISTS dataset_splits(parent_matrix_code VARCHAR)"))
    monkeypatch.setattr(mod, "clean_previous_splits", lambda conn, parent_matrix_code=None: None)
    monkeypatch.setattr(mod, "split_parquet_by_filter", split_impl)
    monkeypatch.setattr(mod, "register_sub_dataset", lambda *a, **k: None)
    monkeypatch.setattr(sys, "argv", ["12-split-datasets.py", "--matrix", "AAA1"])
    mod.SPLIT_FAILURES.clear()
    mod.main()


def test_split_handled_failure_exits_nonzero(tmp_path, monkeypatch):
    mod = load("split_t", "12-split-datasets.py")

    def failing(conn, rule, dry_run=False):
        mod.record_failure("Failed to split AAA1 -> AAA1_x: boom")
        return []
    with pytest.raises(SystemExit) as e:
        run_split_main(mod, tmp_path, monkeypatch, failing)
    assert e.value.code == 1


def test_split_empty_child_counts_as_failure(tmp_path, monkeypatch):
    mod = load("split_t2", "12-split-datasets.py")
    with pytest.raises(SystemExit) as e:
        run_split_main(mod, tmp_path, monkeypatch,
                       lambda conn, rule, dry_run=False: [{"sub_code": "AAA1_x", "row_count": 0}])
    assert e.value.code == 1


def test_split_clean_run_exits_zero(tmp_path, monkeypatch):
    mod = load("split_t3", "12-split-datasets.py")
    run_split_main(mod, tmp_path, monkeypatch,
                   lambda conn, rule, dry_run=False: [{"sub_code": "AAA1_x", "row_count": 5},
                                                      {"sub_code": "AAA1_y", "row_count": 3}])
