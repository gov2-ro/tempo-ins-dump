"""FIX-03 phase 1: scripts/audit-corpus.py on a synthetic corpus (read-only, deterministic)."""
import hashlib
import importlib.util
import json
from pathlib import Path

import duckdb
import pytest

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="module")
def audit_mod():
    spec = importlib.util.spec_from_file_location("audit_corpus_t", ROOT / "scripts" / "audit-corpus.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def write_parquet(path: Path, rows, cols=("REF_AREA", "TIME_PERIOD", "OBS_VALUE")):
    c = duckdb.connect()
    c.execute(f"CREATE TABLE t ({', '.join(f'{k} VARCHAR' if k != 'OBS_VALUE' and k != 'value' else f'{k} DOUBLE' for k in cols)})")
    for r in rows:
        c.execute(f"INSERT INTO t VALUES ({', '.join('?' for _ in cols)})", list(r))
    c.execute(f"COPY t TO '{path}' (FORMAT PARQUET)")
    c.close()


@pytest.fixture
def corpus(tmp_path):
    d = tmp_path / "data"
    pq = d / "corpus" / "parquet"
    vp = d / "corpus" / "view-profiles"
    pq.mkdir(parents=True)
    vp.mkdir(parents=True)
    good = [("RO", "2020", 1.0), ("RO", "2021", 2.0)]
    write_parquet(pq / "GOOD1.parquet", good)                                  # served canonical
    write_parquet(pq / "PARENT.parquet", good)                                 # noncanonical parent
    write_parquet(pq / "PARENT_a.parquet", good)                               # registered split
    write_parquet(pq / "PARENT_b.parquet", good)                               # registered split
    write_parquet(pq / "LEFT1.parquet", good)                                  # leftover
    write_parquet(pq / "NULLD.parquet", [(None, "2020", 1.0), ("RO", "2021", 2.0)])   # NULL dim
    write_parquet(pq / "BADT.parquet", [("RO", "6 ore", 1.0), ("RO", "2021", 2.0)])   # invalid time share
    write_parquet(pq / "DUPS.parquet", [("RO", "2020", 1.0), ("RO", "2020", 9.0),
                                        ("RO", "2021", 2.0), ("RO", "2021", 2.0)])    # conflicting + equal dup
    write_parquet(pq / "LEGACY.parquet", [("Romania", "2020", 5.0)],
                  cols=("area_nom_id", "an_nom_id", "value"))                  # legacy shape
    write_parquet(pq / "EMPTY.parquet", [])                                    # zero rows -> invalid
    (pq / "BROKEN.parquet").write_bytes(b"not a parquet")                      # unreadable -> invalid
    for code in ("GOOD1", "PARENT_a", "NULLD"):
        (vp / f"{code}.json").write_text("{}")
    (vp / "_index.json").write_text("{}")
    (vp / "GHOST.json").write_text("{}")                                       # profile without parquet

    db = d / "corpus" / "metadata.duckdb"
    c = duckdb.connect(str(db))
    c.execute("""CREATE TABLE matrices (matrix_code VARCHAR, is_canonical BOOLEAN, is_split BOOLEAN,
                 parent_matrix_code VARCHAR, parquet_path VARCHAR, row_count BIGINT, ultima_actualizare DATE)""")
    rows = [("GOOD1", True, False, None, "x/GOOD1.parquet", 2, "2026-01-02"),
            ("PARENT", False, False, None, "x/PARENT.parquet", 2, None),
            ("PARENT_a", True, True, "PARENT", "x/PARENT_a.parquet", 2, None),
            ("PARENT_b", True, True, "PARENT", "x/PARENT_b.parquet", 99, None),     # row count mismatch
            ("NULLD", True, False, None, "x/NULLD.parquet", 2, None),
            ("BADT", True, False, None, "x/BADT.parquet", 2, None),
            ("DUPS", True, False, None, "x/DUPS.parquet", 4, None),
            ("LEGACY", True, False, None, "x/LEGACY.parquet", 1, None),
            ("EMPTY", True, False, None, None, 0, None),
            ("UNAV1", False, False, None, None, None, None),                          # intentional unavailable
            ("MISS1", True, False, None, None, None, None),                           # canonical, no file -> invalid
            ]
    for r in rows:
        c.execute("INSERT INTO matrices VALUES (?,?,?,?,?,?,?)", list(r))
    c.execute("""CREATE TABLE dataset_splits (parent_matrix_code VARCHAR, sub_matrix_code VARCHAR,
                 parquet_path VARCHAR, row_count BIGINT)""")
    c.execute("INSERT INTO dataset_splits VALUES ('PARENT','PARENT_a','x',2), ('PARENT','PARENT_b','x',2)")
    c.execute("CREATE TABLE sdmx_column_map (matrix_code VARCHAR)")
    c.execute("INSERT INTO sdmx_column_map VALUES ('GOOD1')")
    c.execute("CREATE TABLE matrix_profiles (matrix_code VARCHAR)")
    c.close()
    return d


def test_categories(audit_mod, corpus):
    rep = audit_mod.audit(corpus)
    cat = {c: r["category"] for c, r in rep["files"].items()}
    assert cat["GOOD1"] == "served_canonical"
    assert cat["PARENT"] == "noncanonical_parent"
    assert cat["PARENT_a"] == cat["PARENT_b"] == "registered_split"
    assert cat["LEFT1"] == "leftover"
    assert cat["EMPTY"] == cat["BROKEN"] == "invalid"
    assert rep["files"]["BROKEN"]["readable"] is False
    assert rep["files"]["EMPTY"]["invalid_reason"] == "zero rows"
    mo = rep["metadata_only"]
    assert mo["UNAV1"]["category"] == "intentional_unavailable"
    assert mo["MISS1"]["category"] == "invalid"
    s = rep["summary"]
    assert s["files_by_category"]["leftover"] == 1
    assert s["files_without_matrices_row"] == 2          # LEFT1 + BROKEN
    assert s["matrices_without_file"] == 2


def test_check_findings(audit_mod, corpus):
    f = audit_mod.audit(corpus)["findings"]
    assert f["null_dims"] == ["NULLD"]
    assert f["time_invalid_gt_20pct"] == ["BADT"]
    assert f["duplicate_grain"] == ["DUPS"]
    assert f["conflicting_grain"] == ["DUPS"]
    assert f["legacy_shape"] == ["LEGACY"]
    assert "LEGACY" in f["no_time_period_column"]
    assert f["unreadable"] == ["BROKEN"]


def test_registration_and_coverage(audit_mod, corpus):
    rep = audit_mod.audit(corpus)
    assert rep["registration_issues"]["split_row_count_mismatch"] == []
    assert rep["registration_issues"]["row_count_mismatch"] == ["PARENT_b"]
    cov = rep["coverage"]["column_map"]
    assert cov["served_with"] == 1 and "NULLD" in cov["served_missing"]
    assert rep["coverage"]["trend"]["served_with"] == 0    # missing table => empty, with a warning
    assert any("dataset_trends" in w for w in rep["warnings"])


def test_view_profile_path_is_corpus_view_profiles(audit_mod, corpus):
    vp = audit_mod.audit(corpus)["view_profiles"]
    assert vp["dir"].endswith("corpus/view-profiles")
    assert vp["total"] == 4                         # underscore-prefixed index excluded
    assert vp["profiles_without_parquet"] == ["GHOST"]
    assert "GOOD1" not in vp["served_without_profile"] and "PARENT_b" in vp["served_without_profile"]
    assert "LEFT1" not in vp["served_without_profile"]   # leftovers don't need profiles


def test_violations_cover_served_only(audit_mod, corpus):
    v = audit_mod.audit(corpus)["violations"]
    assert v["null_dims"] == ["NULLD"] and v["conflicting_grain"] == ["DUPS"]
    assert "EMPTY" in v["invalid"] and "BROKEN" not in v["invalid"]   # BROKEN is an unregistered leftover-like file
    assert v["metadata_only_should_be_served"] == ["MISS1"]


def test_deterministic_and_data_dir_untouched(audit_mod, corpus, tmp_path, capsys):
    def snapshot():
        return {str(p): (hashlib.sha256(p.read_bytes()).hexdigest(), p.stat().st_mtime_ns)
                for p in sorted(corpus.rglob("*")) if p.is_file()}
    before = snapshot()
    out1, out2 = tmp_path / "a.json", tmp_path / "b.json"
    assert audit_mod.main(["--data-dir", str(corpus), "--json-out", str(out1), "--quiet", "--hashes"]) == 0
    assert audit_mod.main(["--data-dir", str(corpus), "--json-out", str(out2), "--quiet", "--hashes"]) == 0
    assert out1.read_text() == out2.read_text()
    assert snapshot() == before                      # nothing created or modified in the corpus
    rep = json.loads(out1.read_text())
    assert "files" not in rep and rep["summary"]["parquet_files"] == 11
    assert audit_mod.main(["--data-dir", str(corpus), "--json-out", str(tmp_path / "c.json"),
                           "--quiet", "--full", "--hashes"]) == 0
    full = json.loads((tmp_path / "c.json").read_text())
    assert len(full["files"]["GOOD1"]["sha256"]) == 64


def test_json_out_inside_corpus_refused(audit_mod, corpus):
    with pytest.raises(SystemExit):
        audit_mod.main(["--data-dir", str(corpus), "--json-out", str(corpus / "corpus" / "x.json")])


def test_strict_exit_code_and_human_summary(audit_mod, corpus, capsys):
    assert audit_mod.main(["--data-dir", str(corpus), "--strict"]) == 1
    out = capsys.readouterr().out
    assert "Files by category" in out and "served_canonical" in out


def test_missing_data_dir_does_not_crash(audit_mod, tmp_path):
    rep = audit_mod.audit(tmp_path / "nope")
    assert rep["summary"]["parquet_files"] == 0 and rep["warnings"]
