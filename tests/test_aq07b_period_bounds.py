"""AQ-07B: period bounds from the distinct-period read when the footer proves no NULL value.

Each case compares `dimension_values` with the old bounds SQL run on the same file.
"""
import duckdb
import pytest

from app.services import data_query, query_builder


def _write(tmp_path, name, select_sql, row_group_size=None):
    path = tmp_path / f"{name}.parquet"
    opt = f", ROW_GROUP_SIZE {row_group_size}" if row_group_size else ""
    duckdb.connect().execute(f"COPY ({select_sql}) TO '{path}' (FORMAT parquet{opt})")
    return path


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(data_query, "PARQUET_DIR", tmp_path)
    monkeypatch.setattr(query_builder, "PARQUET_DIR", tmp_path)
    conn = duckdb.connect()
    conn.execute("CREATE TABLE matrices(matrix_code VARCHAR, parent_matrix_code VARCHAR)")
    conn.execute("CREATE TABLE sdmx_column_map(matrix_code VARCHAR, sdmx_column_name VARCHAR, "
                 "old_column_name VARCHAR)")
    for code in ("FAST", "NULLS", "LEG", "SORT", "TNULL", "EMPTY", "ALLNULL"):
        conn.execute("INSERT INTO matrices VALUES (?, NULL)", [code])
    conn.execute("INSERT INTO sdmx_column_map VALUES ('LEG', 'TIME_PERIOD', 'ani_nom_id')")
    return conn, tmp_path


def _old_bounds(path, time_col, value_col):
    return duckdb.connect().execute(
        f'SELECT min(CAST("{time_col}" AS VARCHAR)), max(CAST("{time_col}" AS VARCHAR)), '
        f'count(DISTINCT "{time_col}") FROM read_parquet(?) WHERE "{value_col}" IS NOT NULL',
        [str(path)]).fetchone()


def _check(conn, code, path, time_col, value_col, column, fast, monkeypatch):
    calls = []
    real = data_query._value_column_has_no_nulls

    def spy(*a):
        calls.append(real(*a))
        return calls[-1]
    monkeypatch.setattr(data_query, "_value_column_has_no_nulls", spy)
    out = data_query.dimension_values(conn, code, column)
    first, last, n = _old_bounds(path, time_col, value_col)
    assert out["period_bounds"] == {"first": first, "last": last, "periods_with_data": n}
    assert calls == [fast]
    return out


def test_no_null_values_use_fast_path(env, monkeypatch):
    conn, d = env
    p = _write(d, "FAST", "SELECT CAST(2000 + i % 7 AS VARCHAR) AS TIME_PERIOD, 'a' AS X, "
                          "i * 1.0 AS OBS_VALUE FROM range(100) t(i)", row_group_size=10)
    out = _check(conn, "FAST", p, "TIME_PERIOD", "OBS_VALUE", "TIME_PERIOD", True, monkeypatch)
    assert out["period_bounds"] == {"first": "2000", "last": "2006", "periods_with_data": 7}


def test_null_values_keep_current_query(env, monkeypatch):
    conn, d = env
    # 2007 only has NULL values: it must not count as a period with data.
    p = _write(d, "NULLS", "SELECT CAST(2000 + i % 8 AS VARCHAR) AS TIME_PERIOD, "
                           "CASE WHEN i % 8 = 7 THEN NULL ELSE i * 1.0 END AS OBS_VALUE "
                           "FROM range(100) t(i)", row_group_size=10)
    out = _check(conn, "NULLS", p, "TIME_PERIOD", "OBS_VALUE", "TIME_PERIOD", False, monkeypatch)
    assert out["period_bounds"]["last"] == "2006"
    assert out["period_bounds"]["periods_with_data"] == 7
    assert "2007" in out["values"]          # the value list itself is unchanged


def test_legacy_shaped_file(env, monkeypatch):
    conn, d = env
    p = _write(d, "LEG", "SELECT CAST(1990 + i % 5 AS VARCHAR) AS ani_nom_id, "
                         "i * 1.0 AS value FROM range(50) t(i)")
    out = _check(conn, "LEG", p, "ani_nom_id", "value", "TIME_PERIOD", True, monkeypatch)
    assert out["period_bounds"]["first"] == "1990" and out["period_bounds"]["last"] == "1994"


def test_text_order_differs_from_numeric_order(env, monkeypatch):
    conn, d = env
    # As numbers 9 < 10 < 100; as text '10' < '100' < '9'.
    p = _write(d, "SORT", "SELECT CAST(v AS VARCHAR) AS TIME_PERIOD, 1.0 AS OBS_VALUE "
                          "FROM (VALUES (9), (10), (100), (9), (2)) t(v)")
    out = _check(conn, "SORT", p, "TIME_PERIOD", "OBS_VALUE", "TIME_PERIOD", True, monkeypatch)
    assert out["period_bounds"] == {"first": "10", "last": "9", "periods_with_data": 4}


def test_numeric_time_column(env, monkeypatch):
    conn, d = env
    p = _write(d, "SORT2", "SELECT v AS TIME_PERIOD, 1.0 AS OBS_VALUE FROM (VALUES (9), (10), (100)) t(v)")
    conn.execute("INSERT INTO matrices VALUES ('SORT2', NULL)")
    out = _check(conn, "SORT2", p, "TIME_PERIOD", "OBS_VALUE", "TIME_PERIOD", True, monkeypatch)
    assert out["period_bounds"] == {"first": "10", "last": "9", "periods_with_data": 3}


def test_null_time_values(env, monkeypatch):
    conn, d = env
    p = _write(d, "TNULL", "SELECT CASE WHEN i % 4 = 0 THEN NULL ELSE CAST(2010 + i % 4 AS VARCHAR) END "
                           "AS TIME_PERIOD, 1.0 AS OBS_VALUE FROM range(40) t(i)")
    out = _check(conn, "TNULL", p, "TIME_PERIOD", "OBS_VALUE", "TIME_PERIOD", True, monkeypatch)
    assert out["period_bounds"] == {"first": "2011", "last": "2013", "periods_with_data": 3}


def test_empty_file_and_all_null_values(env, monkeypatch):
    conn, d = env
    p = _write(d, "EMPTY", "SELECT CAST('x' AS VARCHAR) AS TIME_PERIOD, 1.0 AS OBS_VALUE WHERE false")
    out = _check(conn, "EMPTY", p, "TIME_PERIOD", "OBS_VALUE", "TIME_PERIOD", False, monkeypatch)
    assert out["period_bounds"] == {"first": None, "last": None, "periods_with_data": 0}
    p = _write(d, "ALLNULL", "SELECT '2020' AS TIME_PERIOD, CAST(NULL AS DOUBLE) AS OBS_VALUE")
    out = _check(conn, "ALLNULL", p, "TIME_PERIOD", "OBS_VALUE", "TIME_PERIOD", False, monkeypatch)
    assert out["period_bounds"] == {"first": None, "last": None, "periods_with_data": 0}


def test_q_filter_does_not_change_bounds(env, monkeypatch):
    conn, d = env
    _write(d, "FAST", "SELECT CAST(2000 + i % 7 AS VARCHAR) AS TIME_PERIOD, 1.0 AS OBS_VALUE FROM range(30) t(i)")
    out = data_query.dimension_values(conn, "FAST", "TIME_PERIOD", q="2003")
    assert out["total"] == 1
    assert out["period_bounds"] == {"first": "2000", "last": "2006", "periods_with_data": 7}
