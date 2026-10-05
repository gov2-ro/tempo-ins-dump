"""Regression: `12-split-datasets.py --dry-run` must never delete existing children.

Dry-run results carry row_count=0 with the real child paths, and the 0-row
cleanup (and the cross-product false-positive guard) used to unlink them.
"""
import importlib.util
import sys
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from split_rules import SplitGroup, SplitRule  # noqa: E402


def _load_stage12():
    spec = importlib.util.spec_from_file_location("stage12", ROOT / "12-split-datasets.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _setup(tmp_path, monkeypatch):
    mod = _load_stage12()
    v3, v2 = tmp_path / "v3", tmp_path / "v2"
    v3.mkdir()
    v2.mkdir()
    monkeypatch.setattr(mod, "PARQUET_V3_DIR", v3)
    monkeypatch.setattr(mod, "PARQUET_V2_DIR", v2)
    con = duckdb.connect()
    # v2-shaped source so no metadata DB lookups are needed
    con.execute(f"""COPY (SELECT * FROM (VALUES (1, 'a', 1.0), (2, 'b', 2.0))
                 t(sex_nom_id, label, value)) TO '{v2 / "TST1.parquet"}' (FORMAT parquet)""")
    groups = [SplitGroup(label="g1", option_ids=[1], option_labels={1: "a"}),
              SplitGroup(label="g2", option_ids=[2], option_labels={2: "b"})]
    rule = SplitRule(matrix_code="TST1", pattern="multi_um", split_dimension="sex_nom_id",
                     split_dimension_id=1, groups=groups)
    children = []
    for g in ("g1", "g2"):
        child = v2 / f"{mod.generate_sub_matrix_code('TST1', g)}.parquet"
        child.write_bytes(b"existing child")
        children.append(child)
    return mod, con, rule, children


def test_filter_split_dry_run_keeps_existing_children(tmp_path, monkeypatch):
    mod, con, rule, children = _setup(tmp_path, monkeypatch)
    results = mod.split_parquet_by_filter(con, rule, dry_run=True)
    assert len(results) == 2
    assert all(c.exists() and c.read_bytes() == b"existing child" for c in children)


def test_cross_product_dry_run_keeps_existing_children(tmp_path, monkeypatch):
    mod, con, rule, _ = _setup(tmp_path, monkeypatch)
    monkeypatch.setattr(mod, "_sdmx_to_v2_col_map", lambda *a, **k: {})  # no metadata DB
    v2 = mod.PARQUET_V2_DIR
    child = v2 / "TST1_g1.parquet"
    child.write_bytes(b"existing child")
    mod.split_parquet_cross_product(con, "TST1", [rule], dry_run=True)
    assert child.exists() and child.read_bytes() == b"existing child"
