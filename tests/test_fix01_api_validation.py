"""FIX-01 phase 1: /api list/data/related validation, query builder safety."""
import json
import urllib.parse

import pytest

from fix01_corpus import make_client
from app.services.query_builder import build_data_query, build_data_query_params
from app.services.request_validation import parse_filters, parse_group_by
from fastapi import HTTPException


@pytest.fixture
def client(tmp_path, monkeypatch):
    return make_client(tmp_path, monkeypatch)


def data(client, code="ANN1", **params):
    return client.get(f"/api/datasets/{code}/data", params=params)


def f(obj):
    return json.dumps(obj)


# ---------------------------------------------------------------- limits

@pytest.mark.parametrize("url", [
    "/api/datasets?limit=0", "/api/datasets?limit=-1", "/api/datasets?limit=201",
    "/api/datasets?offset=-1",
    "/api/datasets/ANN1/related?limit=0", "/api/datasets/ANN1/related?limit=-3",
    "/api/datasets/ANN1/related?limit=13",
    "/api/datasets/ANN1/data?limit=0", "/api/datasets/ANN1/data?limit=-1",
    "/api/datasets/ANN1/data?limit=abc",
])
def test_non_positive_or_oversized_limits_are_422(client, url):
    assert client.get(url).status_code == 422


def test_valid_limits_still_work(client):
    assert data(client, limit=1).json()["returned_rows"] == 1
    assert data(client).json()["returned_rows"] == 4
    r = client.get("/api/datasets/ANN1/related", params={"limit": 3})
    assert r.status_code == 200


# --------------------------------------------------------------- filters

@pytest.mark.parametrize("raw", [
    "null", "[1]", "[]", '{"TIME_PERIOD":1}', '{"TIME_PERIOD":"2020"}',
    '{"TIME_PERIOD":null}', '{"TIME_PERIOD":[null]}', '{"TIME_PERIOD":[true]}',
    '{"TIME_PERIOD":[{"a":1}]}', '{"TIME_PERIOD":[["2020"]]}',
    '{"NOPE":["x"]}', '{"OBS_VALUE":["1"]}', "not json", "{", "1", '"x"',
])
def test_invalid_filters_are_400(client, raw):
    r = data(client, filters=raw)
    assert r.status_code == 400, raw
    assert r.json()["detail"].startswith("Invalid filters")
    r = client.get("/api/datasets/ANN1/download", params={"filters": raw})
    assert r.status_code == 400, raw


def test_valid_filter_shapes(client):
    assert data(client, filters="{}").json()["returned_rows"] == 4
    assert data(client, filters=f({"TIME_PERIOD": ["2020"]})).json()["returned_rows"] == 2
    assert data(client, filters=f({"TIME_PERIOD": [2020]})).json()["returned_rows"] == 2
    # Empty array = no constraint on that column.
    assert data(client, filters=f({"TIME_PERIOD": []})).json()["returned_rows"] == 4
    both = f({"TIME_PERIOD": ["2020"], "REF_AREA": ["Iasi"]})
    assert data(client, filters=both).json()["returned_rows"] == 1


def test_apostrophe_and_specials_in_filter_values_are_literals(client):
    body = data(client, filters=f({"CATEGORY": ["O'Brien & <Co>"]})).json()
    assert body["returned_rows"] == 1
    assert body["rows"][0][0] == "O'Brien & <Co>"
    csv = client.get("/api/datasets/ANN1/download",
                     params={"filters": f({"CATEGORY": ["O'Brien & <Co>"]})})
    assert csv.status_code == 200
    assert csv.text.count("O'Brien") == 1


def test_injection_in_filter_value_matches_nothing(client):
    r = data(client, filters=f({"CATEGORY": ["x' OR '1'='1", "') OR 1=1 --"]}))
    assert r.status_code == 200
    assert r.json()["returned_rows"] == 0


def test_filter_column_name_cannot_inject(client):
    r = data(client, filters=f({'CATEGORY" IS NOT NULL OR "1': ["x"]}))
    assert r.status_code == 400


# -------------------------------------------------------------- group_by

@pytest.mark.parametrize("raw", [
    "null", "{}", '"TIME_PERIOD"', "1", "[1]", '[["TIME_PERIOD"]]', "[NOPE]",
    '["NOPE"]', '["OBS_VALUE"]', "not json",
])
def test_malformed_group_by_is_400(client, raw):
    r = data(client, group_by=raw)
    assert r.status_code == 400, raw
    assert r.json()["detail"].startswith("Invalid group_by")


def test_valid_group_by(client):
    body = data(client, group_by=f(["TIME_PERIOD"])).json()
    assert body["columns"] == ["TIME_PERIOD", "OBS_VALUE"]
    sums = {r[0]: r[1] for r in body["rows"]}
    assert sums == {"2019": 10.0, "2020": 50.0, "2021": 40.0}
    assert data(client, group_by="[]").json()["returned_rows"] == 4
    assert data(client, group_by="").json()["returned_rows"] == 4


# -------------------------------------------------------------- 404s

def test_unknown_dataset_is_404(client):
    for url in ("/api/datasets/NOPE", "/api/datasets/NOPE/data",
                "/api/datasets/NOPE/download", "/api/datasets/NOPE/related",
                "/api/datasets/NOPE/insights"):
        assert client.get(url).status_code == 404, url
    # Unknown dataset wins over a bad filter (checked first).
    assert data(client, "NOPE", filters="null").status_code == 404
    assert data(client, "x'y", filters="{}").status_code == 404


# ------------------------------------------------ errors / connections

def test_query_failure_does_not_leak_paths_or_sql(client, tmp_path):
    # A corrupt parquet makes the query itself fail.
    (tmp_path / "corpus" / "parquet" / "ANN1.parquet").write_bytes(b"not parquet")
    for url in ("/api/datasets/ANN1/data", "/api/datasets/ANN1/download"):
        r = client.get(url)
        assert r.status_code == 500
        assert r.json() == {"detail": "Query failed"}
        assert str(tmp_path) not in r.text


def test_unhandled_exception_is_generic(client, monkeypatch):
    import app.routers.dataset_data as dd

    def boom():
        raise RuntimeError("/Users/secret/path select * from x")
    monkeypatch.setattr(dd, "get_conn", boom)
    r = client.get("/api/datasets/ANN1/data")
    assert r.status_code == 500
    assert r.json() == {"detail": "Internal server error"}


def test_cursor_closed_on_success_and_error(client, monkeypatch, tmp_path):
    import app.routers.dataset_data as dd
    closed = []
    real = dd.get_conn

    class Spy:
        def __init__(self, c):
            self._c = c

        def execute(self, *a, **k):
            return self._c.execute(*a, **k)

        def close(self):
            closed.append(1)
            self._c.close()

    monkeypatch.setattr(dd, "get_conn", lambda: Spy(real()))
    assert data(client).status_code == 200
    assert data(client, filters="null").status_code == 400
    assert data(client, "NOPE").status_code == 404
    assert client.get("/api/datasets/ANN1/download").status_code == 200
    assert len(closed) == 4
    (tmp_path / "corpus" / "parquet" / "ANN1.parquet").write_bytes(b"x")
    assert data(client).status_code == 500
    assert len(closed) == 5


# -------------------------------------------------------- query builder

DIMS = [{"dim_column_name": c} for c in ("CATEGORY", "REF_AREA", "TIME_PERIOD")]


def test_builder_params_bind_values_and_path():
    sql, params = build_data_query_params(
        "ANN1", DIMS, {"CATEGORY": ["O'Brien", "x"], "NOPE": ["y"]}, 10)
    assert "O'Brien" not in sql and "ANN1" not in sql
    assert sql.count("?") == 3
    assert params[0].endswith("ANN1.parquet") and params[1:] == ["O'Brien", "x"]


def test_builder_inline_literals_are_escaped():
    sql = build_data_query("ANN1", DIMS, {"CATEGORY": ["a' OR '1'='1"]}, 10)
    assert "'a'' OR ''1''=''1'" in sql


def test_builder_quotes_identifiers():
    dims = [{"dim_column_name": 'we"ird'}]
    sql, _ = build_data_query_params("ANN1", dims, {}, 5, time_column=None)
    assert '"we""ird"' in sql


def test_builder_rejects_unsupported_aggregate():
    with pytest.raises(ValueError):
        build_data_query_params("ANN1", DIMS, {}, 5, group_by=["CATEGORY"],
                                agg_func="SUM(x); DROP TABLE y; --")


# ------------------------------------------------ helper unit behaviour

def test_parse_filters_unit():
    assert parse_filters(None, {"A"}) == {}
    assert parse_filters('{"A":["x",1,2.5]}', {"A"}) == {"A": ["x", 1, 2.5]}
    with pytest.raises(HTTPException) as e:
        parse_filters('{"B":["x"]}', {"A"})
    assert e.value.status_code == 400
    assert parse_group_by('["A"]', {"A"}) == ["A"]
    assert parse_group_by("[]", {"A"}) is None
