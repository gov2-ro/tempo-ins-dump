"""FIX-03c: generation manifest + release-check consumption (synthetic corpus only)."""
import importlib.util
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from fix03c_corpus import fts_available, make_corpus

ROOT = Path(__file__).resolve().parent.parent
BUILD = ROOT / "scripts" / "build-generation-manifest.py"
CHECK = ROOT / "scripts" / "release-check.py"
PREPARE = ROOT / "scripts" / "prepare-deploy-data.sh"

needs_fts = pytest.mark.skipif(not fts_available(), reason="duckdb fts extension unavailable")


@pytest.fixture(scope="module")
def bm():
    spec = importlib.util.spec_from_file_location("bgm", BUILD)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def build_manifest(data_dir: Path, out: Path, *extra):
    r = subprocess.run([sys.executable, str(BUILD), "--data-dir", str(data_dir), "--out", str(out),
                        "--built-at", "2026-01-01T00:00:00+00:00", *extra], capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    return json.loads(out.read_text())


def prepare(src_corpus: Path, out: Path):
    env = {**os.environ, "TEMPO_CORPUS_SRC": str(src_corpus), "TEMPO_DEPLOY_OUT": str(out),
           "PYTHON": sys.executable}
    return subprocess.run(["bash", str(PREPARE), "--no-tarball"], env=env, capture_output=True, text=True)


def check(stage: Path, *extra):
    return subprocess.run([sys.executable, str(CHECK), "--stage", str(stage), "--skip-tests", *extra],
                          capture_output=True, text=True)


def test_manifest_is_deterministic_and_consistent(tmp_path, bm):
    root = make_corpus(tmp_path / "d", with_search=False)
    m1 = build_manifest(root, tmp_path / "m1.json")
    m2 = build_manifest(root, tmp_path / "m2.json")
    assert (tmp_path / "m1.json").read_bytes() == (tmp_path / "m2.json").read_bytes()
    # id is derived from the component digests only
    assert m1["generation_id"] == bm.compute_generation_id(
        m1["db"]["sha256"], m1["parquet"]["digest"], m1["view_profiles"]["digest"], None)
    assert m1["search_index"] is None
    assert m1["parquet"]["count"] == 8 == len(m1["parquet"]["files"])
    assert m1["view_profiles"]["count"] == 4
    cats = {c: f["category"] for c, f in m1["parquet"]["files"].items()}
    assert cats["GOOD1"] == "served_canonical" and cats["PAR1"] == "noncanonical_parent"
    assert cats["PAR1_judet"] == "registered_split" and cats["LEFT1"] == "leftover"
    assert cats["EMPTY1"] == "invalid"
    assert m1["parquet"]["files"]["GOOD1"]["rows"] == 2
    assert m1["db"]["row_counts"]["matrices"] == 8
    assert m1["provenance"]["latest_observation_date"] == "2026-04-20"
    # strict violations are carried, not hidden
    assert "PAR1_judet" in m1["audit"]["violations"]["conflicting_grain"]
    assert "SHIFT1" in m1["audit"]["violations"]["time_invalid_gt_20pct"]
    assert set(m1["audit"]["violations"]["metadata_only_should_be_served"]) == {"NOFILE1", "NOFILE2"}


def test_manifest_changes_when_any_artifact_changes(tmp_path):
    root = make_corpus(tmp_path / "d", with_search=False)
    a = build_manifest(root, tmp_path / "a.json")["generation_id"]
    (root / "corpus" / "view-profiles" / "GOOD1.json").write_text('{"x": 1}')
    b = build_manifest(root, tmp_path / "b.json")["generation_id"]
    assert a != b


def test_manifest_refuses_output_inside_corpus_and_never_writes_corpus(tmp_path):
    root = make_corpus(tmp_path / "d", with_search=False)
    before = sorted((p.relative_to(root).as_posix(), p.stat().st_size, p.stat().st_mtime_ns)
                    for p in root.rglob("*") if p.is_file())
    r = subprocess.run([sys.executable, str(BUILD), "--data-dir", str(root),
                        "--out", str(root / "corpus" / "generation-manifest.json")], capture_output=True, text=True)
    assert r.returncode != 0 and not (root / "corpus" / "generation-manifest.json").exists()
    build_manifest(root, tmp_path / "ok.json")
    after = sorted((p.relative_to(root).as_posix(), p.stat().st_size, p.stat().st_mtime_ns)
                   for p in root.rglob("*") if p.is_file())
    assert before == after


@needs_fts
def test_release_check_passes_with_consistent_manifest(tmp_path):
    root = make_corpus(tmp_path / "d", nofile=False)
    m = build_manifest(root, tmp_path / "gm.json")
    shutil.copy(tmp_path / "gm.json", root / "corpus" / "generation-manifest.json")
    out = tmp_path / "dd"
    r = prepare(root / "corpus", out)
    assert r.returncode == 0, r.stdout + r.stderr
    sm = json.loads((out / "MANIFEST.json").read_text())
    assert sm["generation"]["status"] == "present" and sm["generation"]["id"] == m["generation_id"]
    assert "corpus/generation-manifest.json" in sm["files"]
    c = check(out, "--source", str(root / "corpus"))
    assert c.returncode == 0, c.stdout
    assert "generation manifest" in c.stdout and "consistent" in c.stdout
    # known audit violations are warned about, and fail only on request
    assert "audit has violations" in c.stdout
    assert check(out, "--require-clean-audit").returncode == 1


@needs_fts
def test_release_check_fails_when_manifest_absent_but_staging_still_works(tmp_path):
    root = make_corpus(tmp_path / "d", nofile=False)
    out = tmp_path / "dd"
    r = prepare(root / "corpus", out)
    assert r.returncode == 0, r.stdout + r.stderr          # backward compatible staging
    assert "no generation-manifest.json" in r.stdout
    assert json.loads((out / "MANIFEST.json").read_text())["generation"]["status"] == "absent"
    c = check(out)
    assert c.returncode == 1 and "generation-manifest.json missing" in c.stdout
    assert check(out, "--allow-missing-generation").returncode == 0


@needs_fts
def test_release_check_fails_when_manifest_inconsistent_with_staged_files(tmp_path):
    root = make_corpus(tmp_path / "d", nofile=False)
    build_manifest(root, tmp_path / "gm.json")
    gm = json.loads((tmp_path / "gm.json").read_text())
    gm["parquet"]["files"]["GOOD1"]["sha256"] = "0" * 64   # manifest describes another generation
    shutil.copy(tmp_path / "gm.json", root / "corpus" / "generation-manifest.json")
    (root / "corpus" / "generation-manifest.json").write_text(json.dumps(gm))
    out = tmp_path / "dd"
    # the staging step tolerates a missing manifest but not a wrong one
    r = prepare(root / "corpus", out)
    assert r.returncode != 0 and "generation manifest vs staged files" in r.stdout
    assert not out.exists()


@needs_fts
def test_release_check_detects_wrong_id_and_db_counts(tmp_path):
    root = make_corpus(tmp_path / "d", nofile=False)
    build_manifest(root, tmp_path / "gm.json")
    good = json.loads((tmp_path / "gm.json").read_text())
    for label, mutate in (("id", lambda g: g.update(generation_id="f" * 64)),
                          ("counts", lambda g: g["db"]["row_counts"].update(matrices=99)),
                          ("vp", lambda g: g["view_profiles"].update(digest="a" * 64))):
        g = json.loads(json.dumps(good))
        mutate(g)
        (root / "corpus" / "generation-manifest.json").write_text(json.dumps(g))
        out = tmp_path / f"dd_{label}"
        r = prepare(root / "corpus", out)
        assert r.returncode != 0 and "generation manifest vs staged files" in r.stdout, (label, r.stdout)
