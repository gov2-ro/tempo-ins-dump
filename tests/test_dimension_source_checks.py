"""INS-backed dimension check: a dimension whose INS options do not add up to
INS's own Total is never collapsed by summing (kpi_dimension_checks)."""
import importlib.util
from pathlib import Path

import duckdb
import pytest

from app.services import dimension_structure as dstruct
from app.services.aggregation_policy import UNAVAILABLE, VALID_TOTAL, decide

ROOT = Path(__file__).resolve().parent.parent


def opt(label):
    return {'label': label, 'sdmx_value': label, 'parsed': {}}


def dim(col, dtype, labels):
    return {'dim_column_name': col, 'dim_type': dtype, 'options': [opt(l) for l in labels]}


TIME = dim('TIME_PERIOD', 'time', ['2024'])
LEVEL = dim('NIVEL', 'indicator', ['Crese', 'Preuniversitar', 'Primar si gimnazial', 'Liceal'])


def run(struct, **kw):
    dims = [TIME, LEVEL]
    return decide(dimensions=dims, effective={d['dim_column_name']: [(o, o['label']) for o in d['options']]
                                              for d in dims},
                  group_by=['TIME_PERIOD'], unit_type='count', struct=struct, **kw)


def test_a_dimension_ins_disproves_is_not_summed():
    flat = {'NIVEL': {'levels': [], 'confidence': 'flat', 'source': 'flat'}}
    assert run(flat).outcome == VALID_TOTAL                      # profiled flat: summed today
    bad = {'NIVEL': {**flat['NIVEL'], 'source_mismatch': {'period': '2024', 'parts_sum': 9, 'total': 5}}}
    d = run(bad)
    assert d.outcome == UNAVAILABLE and d.reason == 'source_total_mismatch'
    # a single chosen option is a slice, still allowed
    assert run(bad, filters={'NIVEL': ['Liceal']}).available


def test_loader_reads_mismatches_only():
    con = duckdb.connect()
    con.execute("CREATE TABLE kpi_dimension_checks (matrix_code VARCHAR, dim_column VARCHAR, period VARCHAR, "
                "status VARCHAR, parts_sum DOUBLE, total DOUBLE)")
    con.executemany("INSERT INTO kpi_dimension_checks VALUES (?,?,?,?,?,?)", [
        ("X1", "NIVEL", "2024", "mismatch", 9, 5), ("X1", "REF_AREA", "2024", "match", 5, 5)])
    dstruct._cache.pop("X1", None)
    s = dstruct.load(con, "X1")
    assert dstruct.source_mismatch(s, "NIVEL") == {"period": "2024", "parts_sum": 9.0, "total": 5.0}
    assert dstruct.source_mismatch(s, "REF_AREA") is None
    dstruct._cache.pop("X1", None)


def _ck():
    spec = importlib.util.spec_from_file_location("ckt", ROOT / "scripts/check-kpi-totals.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_parts_against_total():
    ck = _ck()
    text = ("Nivel, Judete, Ani, UM, Valoare\n"
            "Total, TOTAL, Anul 2024, Numar, 100\nA, TOTAL, Anul 2024, Numar, 60\n"
            "B, TOTAL, Anul 2024, Numar, 40\nB din care C, TOTAL, Anul 2024, Numar, 10\n")
    got = ck.parse_dim_answer(text, 0)
    assert got == {"Total": 100.0, "A": 60.0, "B": 40.0, "B din care C": 10.0}
    assert ck.compare_parts(got["Total"], [got["A"], got["B"]], 0.005)[0] == "match"
    assert ck.compare_parts(got["Total"], [got["A"], got["B"], got["B din care C"]], 0.005)[0] == "mismatch"
    assert ck.compare_parts(None, [1.0], 0.005)[0] == "unresolved:ins_total_blank"


def test_empty_ins_answers_are_not_cached(tmp_path, monkeypatch):
    import types
    ck = _ck()
    import requests
    monkeypatch.setattr(requests, "post", lambda *a, **k: types.SimpleNamespace(
        content=b"", raise_for_status=lambda: None))
    monkeypatch.setattr(ck.time, "sleep", lambda s: None)
    det = {"matMaxDim": 2, "matUMSpec": 0, "matRegJ": 0}
    with pytest.raises(RuntimeError):
        ck.fetch_cells("X", [[1, 2], [3]], det, tmp_path, 0, False)
    assert list(tmp_path.iterdir()) == []
    # the cache key ignores option order
    (tmp_path / "x").mkdir()
    monkeypatch.setattr(requests, "post", lambda *a, **k: types.SimpleNamespace(
        content=b"a,b\n1,2\n", raise_for_status=lambda: None))
    ck.fetch_cells("X", [[2, 1], [3]], det, tmp_path / "x", 0, False)
    assert ck.fetch_cells("X", [[1, 2], [3]], det, tmp_path / "x", 0, True) == "a,b\n1,2\n"
