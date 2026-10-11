"""Static engine parity on synthetic corpora (CI) and on the real copy (corpus).

Builds the static data layer with scripts/build-static.py, records
data_query.run_query answers with scripts/gen-parity-cases.py and replays them
through the browser engine (tools/static-engine/parity.mjs, Node). Any
difference in errors, decisions, columns, rows, ordering or flags fails.
Skipped when Node is not installed.
"""
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
NODE = shutil.which("node")
pytestmark = pytest.mark.skipif(NODE is None, reason="node not installed")


def _run(cmd, env=None):
    r = subprocess.run(cmd, cwd=ROOT, env={**os.environ, **(env or {})},
                       capture_output=True, text=True, timeout=1800)
    assert r.returncode == 0, r.stdout[-3000:] + r.stderr[-3000:]
    return r.stdout


def _parity(data_dir: Path, out: Path, codes=None, per_dataset=30):
    env = {"TEMPO_DATA_DIR": str(data_dir)}
    sel = ["--codes", ",".join(codes)] if codes else []
    _run([sys.executable, "scripts/build-static.py", "--out", str(out / "static"), "--no-record", *sel], env)
    _run([sys.executable, "scripts/gen-parity-cases.py", "--out", str(out / "cases.jsonl"),
          "--per-dataset", str(per_dataset), *sel], env)
    res = _run([NODE, "--max-old-space-size=4096", "tools/static-engine/parity.mjs",
                "--build", str(out / "static"), "--cases", str(out / "cases.jsonl")])
    summary = json.loads(res.strip().splitlines()[-1])
    assert summary["fail"] == 0 and summary["cases"] > 0, res
    return summary


def test_parity_on_synthetic_corpus(tmp_path):
    from fix02b_corpus import build_corpus
    from test_pa01_grain_guard import _add_dataset
    corpus = build_corpus(tmp_path / "data")
    _add_dataset(corpus, "DUPX", [("A", "2023", 10.0), ("A", "2023", 11.0), ("B", "2023", 5.0)])
    _add_dataset(corpus, "EQX", [("A", "2023", 10.0), ("A", "2023", 10.0), ("B", "2023", 5.0)])
    # a recorded dimension the file does not carry (ART124A on the corpus)
    _add_dataset(corpus, "STALEX", [("A", "2023", 10.0), ("B", "2023", 5.0)])
    import duckdb
    db = duckdb.connect(str(corpus / "metadata.duckdb"))
    db.execute("UPDATE dimensions SET dim_column_name = 'categorie_nom_id' "
               "WHERE matrix_code = 'STALEX' AND dim_column_name = 'CATEGORY'")
    db.close()
    s = _parity(tmp_path / "data", tmp_path / "out",
                ["POPX", "ADDX", "RATEX", "INCX", "DUPX", "EQX", "STALEX"], per_dataset=60)
    assert s["ok"] == s["cases"]
    cases = [json.loads(l) for l in (tmp_path / "out" / "cases.jsonl").read_text().splitlines()]
    stale = [c["response"]["aggregation"] for c in cases
             if c["code"] == "STALEX" and "response" in c]
    assert stale and all(a["reason"] == "schema_mismatch" for a in stale)


def test_partitioned_layout_matches_whole_file(tmp_path):
    """The same synthetic dataset forced into partitions gives identical answers."""
    from fix02b_corpus import build_corpus
    corpus = build_corpus(tmp_path / "data")
    env = {"TEMPO_DATA_DIR": str(tmp_path / "data")}
    out = tmp_path / "out"
    _run([sys.executable, "scripts/build-static.py", "--out", str(out / "static"),
          "--codes", "RATEX,POPX", "--partition-rows", "1", "--no-record"], env)
    assert (out / "static" / "data" / "RATEX.index.json").exists()
    _run([sys.executable, "scripts/gen-parity-cases.py", "--out", str(out / "cases.jsonl"),
          "--codes", "RATEX,POPX", "--per-dataset", "40"], env)
    res = _run([NODE, "tools/static-engine/parity.mjs", "--build", str(out / "static"),
                "--cases", str(out / "cases.jsonl")])
    assert json.loads(res.strip().splitlines()[-1])["fail"] == 0
    # with a 1-byte budget every partitioned read is refused, never answered wrongly
    _run([sys.executable, "scripts/build-static.py", "--out", str(out / "tiny"),
          "--codes", "RATEX,POPX", "--partition-rows", "1", "--max-query-bytes", "1",
          "--no-record"], env)
    res = _run([NODE, "tools/static-engine/parity.mjs", "--build", str(out / "tiny"),
                "--cases", str(out / "cases.jsonl")])
    s = json.loads(res.strip().splitlines()[-1])
    assert s["fail"] == 0 and s["browser_budget_refusals"] > 0


@pytest.mark.corpus
def test_parity_on_real_sample(tmp_path):
    data_dir = Path(os.environ.get("TEMPO_DATA_DIR", ROOT / "data"))
    codes = ["POP105A_judete_grupe", "FOM106F", "SOM103A_judete", "TUR105D_judete",
             "TUR105E_judet", "FOM106E_judete"]
    _parity(data_dir, tmp_path, codes, per_dataset=25)


def _api_parity(data_dir: Path, out: Path, codes: list[str], n=40):
    env = {"TEMPO_DATA_DIR": str(data_dir)}
    sel = ["--codes", ",".join(codes)]
    _run([sys.executable, "scripts/build-static.py", "--out", str(out / "static"), *sel], env)
    _run([sys.executable, "scripts/gen-api-cases.py", "--out", str(out / "api.jsonl"),
          "--n", str(n), *sel], env)
    res = _run([NODE, "--max-old-space-size=4096", "tools/static-engine/api-parity.mjs",
                "--build", str(out / "static"), "--cases", str(out / "api.jsonl")])
    summary = json.loads(res.strip().splitlines()[-1])
    assert summary["fail"] == 0 and summary["cases"] > 0, res
    return summary


def test_static_api_matches_server_on_synthetic_corpus(tmp_path):
    """Catalog, search, options, downloads, evidence and recipes answered by the
    static site (engine/static-api.js) equal the FastAPI answers."""
    import duckdb
    from fix02b_corpus import build_corpus
    corpus = build_corpus(tmp_path / "data")
    db = duckdb.connect(str(corpus / "metadata.duckdb"))     # the catalog's columns
    for ddl in ("matrices ADD COLUMN is_canonical BOOLEAN DEFAULT TRUE",
                "matrices ADD COLUMN mat_max_dim INTEGER DEFAULT 3",
                "matrices ADD COLUMN is_split BOOLEAN DEFAULT FALSE",
                "matrix_profiles ADD COLUMN has_time BOOLEAN DEFAULT TRUE",
                "matrix_profiles ADD COLUMN has_geo BOOLEAN DEFAULT TRUE",
                "matrix_profiles ADD COLUMN time_granularity VARCHAR DEFAULT 'annual'",
                "matrix_profiles ADD COLUMN has_gender BOOLEAN DEFAULT FALSE",
                "matrix_profiles ADD COLUMN has_age BOOLEAN",
                "matrix_profiles ADD COLUMN has_residence BOOLEAN DEFAULT FALSE"):
        db.execute("ALTER TABLE " + ddl.replace("ADD COLUMN", "ADD COLUMN IF NOT EXISTS"))
    db.close()
    s = _api_parity(tmp_path / "data", tmp_path / "out", ["POPX", "ADDX", "RATEX", "INCX"])
    assert s["ok"] == s["cases"] - s.get("browser_budget_refusals", 0)
    site = tmp_path / "out" / "static"
    assert "static" in (site / "js" / "config.js").read_text()
    assert (site / "rec" / "catalog.json.gz").exists() and (site / "search" / "concepts.json.gz").exists()


@pytest.mark.corpus
def test_static_api_matches_server_on_real_sample(tmp_path):
    data_dir = Path(os.environ.get("TEMPO_DATA_DIR", ROOT / "data"))
    _api_parity(data_dir, tmp_path, ["POP105A_judete_grupe", "FOM106E_judete", "FOM104F_judete",
                                     "SOM103A_judete", "SOM101E", "TUR105D_judete", "ART124A"], n=80)
