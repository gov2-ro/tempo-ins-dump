"""FIX-03c: scripts/repair-corpus.py dry-run planner and quarantine --apply (synthetic only)."""
import importlib.util
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from fix03c_corpus import make_corpus

ROOT = Path(__file__).resolve().parent.parent
REPAIR = ROOT / "scripts" / "repair-corpus.py"


@pytest.fixture(scope="module")
def rc():
    spec = importlib.util.spec_from_file_location("repair_corpus_t", REPAIR)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def tree_state(root: Path):
    return sorted((p.relative_to(root).as_posix(), p.stat().st_size, p.stat().st_mtime_ns)
                  for p in root.rglob("*"))


def run(*args):
    return subprocess.run([sys.executable, str(REPAIR), *args], capture_output=True, text=True)


@pytest.fixture
def src(tmp_path):
    return make_corpus(tmp_path / "src", with_search=False)


def test_dry_run_writes_nothing_and_plan_is_correct(src, tmp_path, rc):
    before = tree_state(src)
    r = run("--data-dir", str(src), "--report-json", str(tmp_path / "plan.json"))
    assert r.returncode == 0, r.stdout + r.stderr
    assert tree_state(src) == before                      # corpus untouched
    plan = json.loads((tmp_path / "plan.json").read_text())
    assert plan["mode"] == "dry-run"
    q = plan["quarantine"]
    assert {i["file"] for i in q["files"]} == {"LEFT1.parquet", "EMPTY1.parquet"}
    assert q["by_category"] == {"leftover": 1, "invalid": 1}
    for i in q["files"]:
        assert len(i["sha256"]) == 64 and i["reason"]
    # registered / parent files are never quarantine candidates
    assert not {"GOOD1.parquet", "PAR1.parquet", "PAR1_judet.parquet"} & {i["file"] for i in q["files"]}


def test_report_inside_corpus_is_refused(src):
    r = run("--data-dir", str(src), "--report-json", str(src / "corpus" / "plan.json"))
    assert r.returncode != 0 and not (src / "corpus" / "plan.json").exists()


def test_metadata_only_explanations(src, tmp_path):
    run("--data-dir", str(src), "--report-json", str(tmp_path / "plan.json"))
    mo = json.loads((tmp_path / "plan.json").read_text())["metadata_only"]["matrices"]
    assert mo["NOFILE1"]["class"] == "empty_at_source"
    assert mo["NOFILE1"]["fetch_log_empty_dataset_hits"] >= 1
    assert mo["NOFILE2"]["class"] == "csv_never_fetched"


def test_time_misclassification_report_proposes_remap_without_reinterpreting(src, tmp_path):
    run("--data-dir", str(src), "--report-json", str(tmp_path / "plan.json"))
    t = json.loads((tmp_path / "plan.json").read_text())["time_misclassified"]["files"]
    assert set(t) == {"SHIFT1"}
    s = t["SHIFT1"]
    assert s["class"] == "shifted_time_column/hours_worked_bands"
    assert s["proposed_remap"] == {"TIME_PERIOD": "HOURS_WORKED", "TIME_PERIOD_2": "TIME_PERIOD"}
    assert s["time_columns"]["TIME_PERIOD_2"]["invalid_share"] == 0.0


def test_county_split_policy_additive_vs_non_additive(src, tmp_path):
    run("--data-dir", str(src), "--report-json", str(tmp_path / "plan.json"))
    g = json.loads((tmp_path / "plan.json").read_text())["conflicting_grain"]["files"]
    assert set(g) == {"PAR1_judet", "PAR2_judet"}
    a, n = g["PAR1_judet"], g["PAR2_judet"]
    assert a["cause"] == n["cause"] == "county_split_dropped_locality"
    assert a["dropped_dimensions"] == ["REF_AREA_2"]
    assert a["measure"] == "additive" and a["disjoint_verified"] is False
    # additive but disjointness unverified: never summed
    assert a["decision"] == "preserve_locality_grain_until_disjointness_verified"
    assert n["measure"] == "non_additive"
    assert n["decision"] == "preserve_locality_grain_or_mark_county_aggregate_unavailable"


def test_county_split_sums_only_when_additive_and_disjoint_verified(src, tmp_path):
    import duckdb
    c = duckdb.connect(str(src / "corpus" / "metadata.duckdb"))
    c.execute("INSERT INTO dimension_structure VALUES ('PAR1','REF_AREA_2', ?)",
              [json.dumps([{"level_id": "all", "kind": "flat", "verified": True}])])
    c.execute("INSERT INTO dimension_structure VALUES ('PAR2','REF_AREA_2', ?)",
              [json.dumps([{"level_id": "all", "kind": "flat", "verified": True}])])
    c.close()
    run("--data-dir", str(src), "--report-json", str(tmp_path / "plan.json"))
    g = json.loads((tmp_path / "plan.json").read_text())["conflicting_grain"]["files"]
    assert g["PAR1_judet"]["decision"] == "sum_localities_by_remaining_dims"
    # verification never rescues a non-additive measure
    assert g["PAR2_judet"]["decision"] == "preserve_locality_grain_or_mark_county_aggregate_unavailable"


# --------------------------------------------------------------- --apply
def make_copy(src: Path, dst: Path) -> Path:
    shutil.copytree(src, dst)
    return dst


def test_apply_requires_explicit_target_and_target_requires_apply(src):
    assert run("--data-dir", str(src), "--apply").returncode != 0
    assert run("--data-dir", str(src), "--target-dir", str(src)).returncode != 0


def test_apply_refuses_in_place_targets(src):
    before = tree_state(src)
    for target in (src, src / "corpus", src.parent):
        r = run("--data-dir", str(src), "--apply", "--target-dir", str(target))
        assert r.returncode != 0, target
    assert tree_state(src) == before
    assert not (src / "quarantine").exists()


def test_apply_refuses_symlinked_parquet_dir(src, tmp_path):
    tgt = tmp_path / "copy"
    (tgt / "corpus").mkdir(parents=True)
    (tgt / "corpus" / "parquet").symlink_to(src / "corpus" / "parquet")
    before = tree_state(src)
    r = run("--data-dir", str(src), "--apply", "--target-dir", str(tgt))
    assert r.returncode != 0 and "source corpus" in (r.stdout + r.stderr)
    assert tree_state(src) == before


def test_apply_moves_only_in_copy_and_writes_manifest(src, tmp_path):
    tgt = make_copy(src, tmp_path / "copy")
    src_before = tree_state(src)
    r = run("--data-dir", str(src), "--apply", "--target-dir", str(tgt))
    assert r.returncode == 0, r.stdout + r.stderr
    assert tree_state(src) == src_before                   # source untouched
    q = tgt / "quarantine"
    assert sorted(p.name for p in q.glob("*.parquet")) == ["EMPTY1.parquet", "LEFT1.parquet"]
    assert not (tgt / "corpus" / "parquet" / "LEFT1.parquet").exists()
    assert (tgt / "corpus" / "parquet" / "GOOD1.parquet").exists()
    man = json.loads((q / "quarantine-manifest.json").read_text())
    assert man["count"] == 2 and {f["file"] for f in man["files"]} == {"LEFT1.parquet", "EMPTY1.parquet"}
    import hashlib
    for f in man["files"]:   # manifest hash == hash of the moved file
        assert hashlib.sha256((q / f["file"]).read_bytes()).hexdigest() == f["sha256"]
    # a second apply refuses (quarantine dir not empty) rather than overwriting
    assert run("--data-dir", str(src), "--apply", "--target-dir", str(tgt)).returncode != 0


def test_apply_refuses_when_copy_differs_from_audited_generation(src, tmp_path):
    tgt = make_copy(src, tmp_path / "copy")
    (tgt / "corpus" / "parquet" / "LEFT1.parquet").write_bytes(b"changed")
    r = run("--data-dir", str(src), "--apply", "--target-dir", str(tgt))
    assert r.returncode != 0 and "hash" in (r.stdout + r.stderr)
    assert not (tgt / "quarantine").exists()               # nothing moved


def test_registered_files_never_quarantined(src, rc):
    import importlib
    audit = rc._load_audit()
    rep = audit.audit(src, do_grain=False, do_hashes=True)
    import duckdb
    conn = duckdb.connect(str(src / "corpus" / "metadata.duckdb"), read_only=True)
    matrices = {r[0]: r for r in conn.execute("SELECT matrix_code FROM matrices").fetchall()}
    subs = {r[0] for r in conn.execute("SELECT sub_matrix_code FROM dataset_splits").fetchall()}
    conn.close()
    # an invalid-but-registered file stays out of the plan
    rep["files"]["GOOD1"]["category"] = "invalid"
    plan = rc.plan_quarantine(rep, matrices, subs)
    assert "GOOD1.parquet" not in {i["file"] for i in plan["files"]}
