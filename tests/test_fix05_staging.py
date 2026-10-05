"""FIX-05: staging + release-check on a tiny synthetic corpus (no real data)."""
import importlib.util
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import duckdb
import pytest

ROOT = Path(__file__).resolve().parent.parent
PREPARE = ROOT / "scripts" / "prepare-deploy-data.sh"
CHECK = ROOT / "scripts" / "release-check.py"
CODES = ["AAA001", "BBB001"]

pytestmark = pytest.mark.skipif(shutil.which("bash") is None, reason="needs bash")


def _fts_ok():
    c = duckdb.connect(":memory:")
    try:
        c.execute("LOAD fts")
        return True
    except Exception:
        return False


needs_fts = pytest.mark.skipif(not _fts_ok(), reason="duckdb fts extension unavailable")


def make_corpus(d: Path, index_codes=CODES):
    (d / "parquet").mkdir(parents=True)
    (d / "view-profiles").mkdir()
    for c in CODES:
        duckdb.connect(":memory:").execute(
            f"COPY (SELECT 1 AS v) TO '{d / 'parquet' / (c + '.parquet')}' (FORMAT parquet)")
        (d / "view-profiles" / f"{c}.json").write_text("{}")
    m = duckdb.connect(str(d / "metadata.duckdb"))
    m.execute("CREATE TABLE matrices(matrix_code VARCHAR, is_canonical BOOLEAN, ultima_actualizare DATE)")
    m.execute("CREATE TABLE dataset_splits(sub_matrix_code VARCHAR)")
    for c in CODES:
        m.execute("INSERT INTO matrices VALUES (?, TRUE, DATE '2024-05-06')", [c])
    m.close()
    s = duckdb.connect(str(d / "search.duckdb"))
    s.execute("LOAD fts")
    s.execute("CREATE TABLE search_docs(matrix_code VARCHAR PRIMARY KEY, search_text VARCHAR)")
    for c in index_codes:
        s.execute("INSERT INTO search_docs VALUES (?, ?)", [c, f"populatia {c}"])
    s.execute("PRAGMA create_fts_index('search_docs','matrix_code','search_text',overwrite=1)")
    s.close()


def prepare(src: Path, out: Path):
    env = {**os.environ, "TEMPO_CORPUS_SRC": str(src), "TEMPO_DEPLOY_OUT": str(out),
           "PYTHON": sys.executable}
    return subprocess.run(["bash", str(PREPARE), "--no-tarball"], env=env,
                          capture_output=True, text=True)


def check(out: Path, *extra):
    return subprocess.run([sys.executable, str(CHECK), "--stage", str(out),
                           "--skip-tests", *extra], capture_output=True, text=True)


@needs_fts
def test_stage_success_manifest_and_search_included(tmp_path):
    src, out = tmp_path / "src", tmp_path / "dd"
    make_corpus(src)
    r = prepare(src, out)
    assert r.returncode == 0, r.stdout + r.stderr
    assert (out / "corpus" / "search.duckdb").exists()
    m = json.loads((out / "MANIFEST.json").read_text())
    assert m["generation"]["status"] == "absent"
    assert m["source"]["latest_observation_date"] == "2024-05-06"
    assert "metadata.duckdb" in str(m["source"]["generation_built_at"])
    assert m["files"]["corpus/search.duckdb"]["sha256"]
    assert m["counts"]["parquet"] == 2
    assert check(out, "--source", str(src), "--allow-missing-generation").returncode == 0
    assert not list(tmp_path.glob("dd.tmp.*"))


@needs_fts
def test_index_generation_mismatch_blocks_and_keeps_previous(tmp_path):
    src, out = tmp_path / "src", tmp_path / "dd"
    make_corpus(src)
    assert prepare(src, out).returncode == 0
    before = (out / "MANIFEST.json").read_text()
    shutil.rmtree(src)
    make_corpus(src, index_codes=["AAA001"])  # stale index
    r = prepare(src, out)
    assert r.returncode != 0 and "index generation mismatch" in r.stdout
    assert (out / "MANIFEST.json").read_text() == before  # previous staging untouched
    assert not list(tmp_path.glob("dd.tmp.*"))
    assert check(out, "--allow-missing-generation").returncode == 0


def test_missing_search_db_blocks(tmp_path):
    src, out = tmp_path / "src", tmp_path / "dd"
    if not _fts_ok():
        pytest.skip("fts unavailable")
    make_corpus(src)
    (src / "search.duckdb").unlink()
    r = prepare(src, out)
    assert r.returncode != 0 and not out.exists()


@needs_fts
def test_tampered_stage_hash_blocks_release(tmp_path):
    src, out = tmp_path / "src", tmp_path / "dd"
    make_corpus(src)
    assert prepare(src, out).returncode == 0
    with open(out / "corpus" / "view-profiles" / "AAA001.json", "a") as f:
        f.write(" ")
    r = check(out)
    assert r.returncode == 1 and "hash/size mismatch" in r.stdout


@needs_fts
def test_stale_staging_vs_source_blocks(tmp_path):
    src, out = tmp_path / "src", tmp_path / "dd"
    make_corpus(src)
    assert prepare(src, out).returncode == 0
    with open(src / "metadata.duckdb", "ab") as f:
        f.write(b"\0")
    r = check(out, "--source", str(src))
    assert r.returncode == 1 and "STALE" in r.stdout


@needs_fts
def test_rollback_restores_previous_generation(tmp_path):
    src, out = tmp_path / "src", tmp_path / "dd"
    make_corpus(src)
    assert prepare(src, out).returncode == 0
    first = json.loads((out / "MANIFEST.json").read_text())["generation"]["id"]
    (src / "view-profiles" / "AAA001.json").write_text('{"changed": true}')
    assert prepare(src, out).returncode == 0
    # content changed but DBs identical -> same placeholder id; compare file hash instead
    h2 = json.loads((out / "MANIFEST.json").read_text())["files"]["corpus/view-profiles/AAA001.json"]["sha256"]
    assert (tmp_path / "dd.prev").is_dir()
    r = subprocess.run([sys.executable, str(CHECK), "--stage", str(out), "--rollback"],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    m = json.loads((out / "MANIFEST.json").read_text())
    assert m["files"]["corpus/view-profiles/AAA001.json"]["sha256"] != h2
    assert m["generation"]["id"] == first


def test_snapshot_detects_source_change(tmp_path):
    spec = importlib.util.spec_from_file_location("release_check", CHECK)
    rc = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(rc)
    if not _fts_ok():
        pytest.skip("fts unavailable")
    src = tmp_path / "src"
    make_corpus(src)
    a = rc.snapshot(src)
    assert a == rc.snapshot(src)
    (src / "parquet" / "AAA001.parquet").write_bytes(b"changed")
    assert a != rc.snapshot(src)
