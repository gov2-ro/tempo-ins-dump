"""scripts/check-kpi-totals.py: a summed KPI resolves to the one INS cell that should
equal it (Total on summed dims, the period, pinned and split-fixed values). Offline:
answers come from a pre-seeded cache."""
import importlib.util
import json
from pathlib import Path

import duckdb
import pytest

from fix03b_env import DDL

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="module")
def ck():
    spec = importlib.util.spec_from_file_location("check_kpi_totals_t", ROOT / "scripts" / "check-kpi-totals.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


META = {
    "details": {"matMaxDim": 3, "matUMSpec": 1, "matRegJ": 0},
    "dimensionsMap": [
        {"dimCode": 1, "label": "Categorii", "options": [
            {"label": "Total ", "nomItemId": 10}, {"label": "Mortale", "nomItemId": 11},
            {"label": "Incapacitate temporara", "nomItemId": 12}]},
        {"dimCode": 2, "label": "Perioade", "options": [
            {"label": "Anul 2022", "nomItemId": 20}, {"label": "Anul 2023", "nomItemId": 21}]},
        {"dimCode": 3, "label": "UM", "options": [
            {"label": "Numar persoane", "nomItemId": 30}, {"label": "Promile", "nomItemId": 31}]},
    ],
}
ROWS = [(cat, y, um, v) for cat, base in (("Mortale", 10.0), ("Incapacitate temporara", 100.0))
        for y in ("2022", "2023") for um, f in (("Numar persoane", 1), ("Promile", 0.01))
        for v in [base * f + (1 if y == "2023" else 0)]]


@pytest.fixture
def tree(tmp_path):
    d = tmp_path / "data"
    (d / "2-metas" / "ro").mkdir(parents=True)
    (d / "corpus" / "parquet").mkdir(parents=True)
    (d / "2-metas" / "ro" / "ACC1.json").write_text(json.dumps(META))
    con = duckdb.connect(str(d / "corpus" / "metadata.duckdb"))
    con.execute(DDL)
    con.execute("CREATE TABLE sdmx_column_map (matrix_code VARCHAR, old_column_name VARCHAR, "
                "sdmx_column_name VARCHAR)")
    con.execute("INSERT INTO matrices (matrix_code, matrix_name, context_code) VALUES "
                "('ACC1', 'Accidente', '1'), ('ACC1_numar', 'Accidente numar', '1')")
    con.execute("""INSERT INTO dimensions VALUES (1, 'ACC1', 1, 'Categorii', 'CATEGORY', 2),
        (2, 'ACC1', 2, 'Perioade', 'TIME_PERIOD', 2), (3, 'ACC1', 3, 'UM', 'unitati_nom_id', 2),
        (4, 'ACC1_numar', 1, 'Categorii', 'CATEGORY', 2), (5, 'ACC1_numar', 2, 'Perioade', 'TIME_PERIOD', 2)""")
    con.execute("INSERT INTO sdmx_column_map VALUES ('ACC1', 'unitati_nom_id', 'UNIT_MEASURE')")
    con.execute("INSERT INTO dataset_splits (parent_matrix_code, sub_matrix_code) VALUES ('ACC1', 'ACC1_numar')")
    pq = d / "corpus" / "parquet"
    con.execute("CREATE TABLE r (CATEGORY VARCHAR, TIME_PERIOD VARCHAR, UNIT_MEASURE VARCHAR, OBS_VALUE DOUBLE)")
    con.executemany("INSERT INTO r VALUES (?, ?, ?, ?)", ROWS)
    con.execute(f"COPY r TO '{pq / 'ACC1.parquet'}' (FORMAT parquet)")
    con.execute(f"COPY (SELECT CATEGORY, TIME_PERIOD, OBS_VALUE FROM r WHERE UNIT_MEASURE = 'Numar persoane') "
                f"TO '{pq / 'ACC1_numar.parquet'}' (FORMAT parquet)")
    con.close()
    return d


def kpi(value, dims, filters=None):
    return {"value": value, "period": "2023", "filters": filters or {}, "verification": "profile_flat",
            "dimensions": dims}


SUM_CAT = {"column": "CATEGORY", "treatment": "partition", "verification": "profile_flat"}
TIME = {"column": "TIME_PERIOD", "treatment": "time", "verification": None}


def test_parent_kpi_resolves_total_period_and_pinned_unit(ck, tree):
    r = ck.Resolver(tree)
    q = r.resolve("ACC1", kpi(112.0, [SUM_CAT, TIME, {"column": "UNIT_MEASURE", "treatment": "unit_pinned"}],
                              {"UNIT_MEASURE": ["Numar persoane"]}))
    assert q["matrix"] == "ACC1" and q["ids"] == [10, 21, 30]
    assert q["labels"] == ["Total", "Anul 2023", "Numar persoane"]


def test_child_kpi_recovers_the_split_fixed_unit_from_the_data(ck, tree):
    q = ck.Resolver(tree).resolve("ACC1_numar", kpi(112.0, [SUM_CAT, TIME]))
    assert q["matrix"] == "ACC1" and q["ids"] == [10, 21, 30]


def test_missing_total_option_is_unresolved_not_guessed(ck, tree):
    meta = json.loads(json.dumps(META))
    meta["dimensionsMap"][0]["options"] = meta["dimensionsMap"][0]["options"][1:]
    (tree / "2-metas" / "ro" / "ACC1.json").write_text(json.dumps(meta))
    q = ck.Resolver(tree).resolve("ACC1_numar", kpi(112.0, [SUM_CAT, TIME]))
    assert q == {"unresolved": "no_total_option:CATEGORY"}


def test_unpinned_extra_dimension_is_unresolved(ck, tree):
    q = ck.Resolver(tree).resolve("ACC1", kpi(112.0, [SUM_CAT, TIME]))     # UNIT_MEASURE not covered
    assert q["unresolved"].startswith("dimension_not_covered")


def test_parse_cell(ck):
    assert ck.parse_cell("a, b, Valoare\n") is None                       # ':' at INS
    assert ck.parse_cell("a, b, Valoare\nTotal, Anul 2023, 4960\n") == 4960.0
    with pytest.raises(ValueError):
        ck.parse_cell("h\nx, 1\ny, 2\n")


def seed(ck, cache, q, body):
    import hashlib
    key = hashlib.sha1(f"{q['matrix']}:{q['ids']}".encode()).hexdigest()[:20]
    cache.mkdir(parents=True, exist_ok=True)
    (cache / f"{q['matrix']}-{key}.csv").write_text(body)


def test_check_flags_a_double_counted_sum(ck, tree, tmp_path):
    cache = tmp_path / "cache"
    k_ok, k_bad = kpi(112.0, [SUM_CAT, TIME]), kpi(224.0, [SUM_CAT, TIME])
    q = ck.Resolver(tree).resolve("ACC1_numar", k_ok)
    seed(ck, cache, q, "Categorii, Perioade, UM, Valoare\nTotal, Anul 2023, Numar persoane, 112\n")
    ok = ck.check(tree, {"ACC1_numar": k_ok}, cache, 0.005, 0, offline=True)["ACC1_numar"]
    bad = ck.check(tree, {"ACC1_numar": k_bad}, cache, 0.005, 0, offline=True)["ACC1_numar"]
    assert ok["status"] == "match" and ok["ins"] == 112.0 and ok["cell"] == ["Total", "Anul 2023", "Numar persoane"]
    assert bad["status"] == "mismatch" and bad["rel"] == pytest.approx(1.0)


def test_offline_without_cache_fetches_nothing(ck, tree, tmp_path):
    r = ck.check(tree, {"ACC1_numar": kpi(112.0, [SUM_CAT, TIME])}, tmp_path / "c", 0.005, 0, offline=True)
    assert r["ACC1_numar"]["status"] == "not_fetched"
