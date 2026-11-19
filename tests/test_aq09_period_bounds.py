"""AQ-09 E: period bounds from the parquet footer and coverage metadata equal the scan's answer."""
import duckdb
import pytest

from app.services import data_query, query_builder


def _scan(path, col, value_col):
    return duckdb.connect().execute(
        f'SELECT min(CAST("{col}" AS VARCHAR)), max(CAST("{col}" AS VARCHAR)), count(DISTINCT "{col}") '
        f'FROM read_parquet(?) WHERE "{value_col}" IS NOT NULL', [str(path)]).fetchone()


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(data_query, "PARQUET_DIR", tmp_path)
    monkeypatch.setattr(query_builder, "PARQUET_DIR", tmp_path)
    conn = duckdb.connect()
    conn.execute("CREATE TABLE matrices(matrix_code VARCHAR, parent_matrix_code VARCHAR)")
    conn.execute("CREATE TABLE sdmx_column_map(matrix_code VARCHAR, sdmx_column_name VARCHAR, old_column_name VARCHAR)")
    for code in ("A", "NULLS", "NUM", "MON"):
        conn.execute("INSERT INTO matrices VALUES (?, NULL)", [code])
    return conn, tmp_path


def _write(d, name, sql):
    duckdb.connect().execute(f"COPY ({sql}) TO '{d / (name + '.parquet')}' (FORMAT parquet, ROW_GROUP_SIZE 10)")
    return d / f"{name}.parquet"


def test_footer_bounds_equal_the_scan_and_read_no_value_rows(env, monkeypatch):
    conn, d = env
    p = _write(d, "A", "SELECT CAST(2000 + i % 7 AS VARCHAR) AS TIME_PERIOD, i * 1.0 AS OBS_VALUE FROM range(100) t(i)")
    monkeypatch.setattr(data_query, "dimension_values",
                        lambda *a, **k: pytest.fail("the footer answers; no scan expected"))
    assert data_query.period_bounds(conn, "A") == {"first": "2000", "last": "2006", "periods_with_data": 7}
    assert tuple(data_query.period_bounds(conn, "A").values()) == _scan(p, "TIME_PERIOD", "OBS_VALUE")


def test_monthly_periods(env):
    conn, d = env
    p = _write(d, "MON", "SELECT strftime(DATE '2020-01-01' + INTERVAL (i % 30) MONTH, '%Y-%m') AS TIME_PERIOD, "
                         "1.0 AS OBS_VALUE FROM range(90) t(i)")
    got = data_query.period_bounds(conn, "MON")
    assert (got["first"], got["last"], got["periods_with_data"]) == _scan(p, "TIME_PERIOD", "OBS_VALUE")


def test_null_values_fall_back_to_the_scan(env):
    conn, d = env
    p = _write(d, "NULLS", "SELECT CAST(2000 + i % 8 AS VARCHAR) AS TIME_PERIOD, "
                           "CASE WHEN i % 8 = 7 THEN NULL ELSE i * 1.0 END AS OBS_VALUE FROM range(100) t(i)")
    got = data_query.period_bounds(conn, "NULLS")
    assert (got["first"], got["last"], got["periods_with_data"]) == _scan(p, "TIME_PERIOD", "OBS_VALUE")
    assert got["last"] == "2006"


def test_numeric_period_column_falls_back_to_the_scan(env):
    conn, d = env
    p = _write(d, "NUM", "SELECT v AS TIME_PERIOD, 1.0 AS OBS_VALUE FROM (VALUES (9), (10), (100)) t(v)")
    got = data_query.period_bounds(conn, "NUM")
    assert (got["first"], got["last"], got["periods_with_data"]) == _scan(p, "TIME_PERIOD", "OBS_VALUE")


def test_unknown_dataset_raises(env):
    conn, _ = env
    with pytest.raises(data_query.QueryError):
        data_query.period_bounds(conn, "NOPE")


@pytest.mark.corpus
def test_corpus_bounds_equal_the_scan_for_a_sample():
    """Every annual/monthly/quarterly family and a sample of split children, against the scan."""
    from app import config
    from app.db import get_conn
    conn = get_conn()
    codes = [r[0] for r in conn.execute(
        "SELECT matrix_code FROM matrices ORDER BY matrix_code").fetchall()]
    parents = [c for c in codes if "_" not in c]
    children = [c for c in codes if "_" in c]
    sample = parents[::25] + children[::40] + ["POP107D", "POP107A", "CON103H_judete", "SOM101E", "IPC102A",
                                               "POP107D_grupe_localitate", "TUR104B_judete"]
    checked = freq = 0
    for code in dict.fromkeys(sample):
        path = config.PARQUET_DIR / f"{code}.parquet"
        if not path.exists():
            continue
        cols = [r[0] for r in conn.execute("DESCRIBE SELECT * FROM read_parquet(?)", [str(path)]).fetchall()]
        if "TIME_PERIOD" not in cols or "OBS_VALUE" not in cols:
            continue
        want = _scan(path, "TIME_PERIOD", "OBS_VALUE")
        got = data_query.period_bounds(conn, code)
        assert (got["first"], got["last"], got["periods_with_data"]) == tuple(want), code
        old = data_query.dimension_values(conn, code, "TIME_PERIOD", limit=1)["period_bounds"]
        assert got == old, code
        checked += 1
        freq += "-" in str(want[1]) or "Q" in str(want[1])
    assert checked >= 40
    assert freq >= 1, "the sample holds no sub-annual series"
