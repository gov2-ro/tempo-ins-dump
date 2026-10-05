"""FIX-01 phase 1: SDMX request safety (injection, period validation, errors)."""
import re

import pytest

from fix01_corpus import make_client


@pytest.fixture
def client(tmp_path, monkeypatch):
    return make_client(tmp_path, monkeypatch)


def _obs_count(resp):
    assert resp.status_code == 200, resp.text
    return len(re.findall(r"<generic:Obs>", resp.text))


def _periods(resp):
    return sorted(re.findall(r'id="TIME_PERIOD" value="([^"]*)"', resp.text))


BASE = "/sdmx/2.1/data/INS,ANN1"


def test_unfiltered_returns_all(client):
    assert _obs_count(client.get(BASE)) == 4
    assert _obs_count(client.get(BASE + "/.")) == 4


@pytest.mark.parametrize("param", ["startPeriod", "endPeriod"])
@pytest.mark.parametrize("payload", [
    "9999' OR '1'='1",
    "2020' OR 1=1 --",
    "2020'; DROP TABLE t; --",
    "2020') OR ('1'='1",
    "2020 OR 1=1",
])
def test_injection_in_periods_is_rejected_not_executed(client, param, payload):
    r = client.get(BASE, params={param: payload})
    assert r.status_code == 400
    assert "Invalid" in r.json()["detail"]


def test_injection_cannot_widen_result(client):
    # Pre-fix: startPeriod=9999 -> 0 rows, startPeriod=9999' OR '1'='1 -> all rows.
    assert _obs_count(client.get(BASE, params={"startPeriod": "9999"})) == 0
    r = client.get(BASE, params={"startPeriod": "9999' OR '1'='1"})
    assert r.status_code == 400


@pytest.mark.parametrize("bad", [
    "", " x", "20", "202", "20200", "2020-13", "2020-00", "2020-Q5", "2020-Q0",
    "2020-q1", "2020-1", "2020-001", "2020-03-01", "abc", "-2020", "2020/03",
])
def test_malformed_period_bounds_are_400(client, bad):
    if bad == "":
        # empty value == parameter not supplied
        assert client.get(BASE, params={"startPeriod": bad}).status_code == 200
        return
    assert client.get(BASE, params={"startPeriod": bad}).status_code == 400
    assert client.get(BASE, params={"endPeriod": bad}).status_code == 400


@pytest.mark.parametrize("s,e", [
    ("2021", "2020"), ("2020-Q3", "2020-Q1"), ("2020-06", "2020-03"),
    ("2021-01", "2020"), ("2020-Q3", "2020-05"),
])
def test_reversed_range_is_400(client, s, e):
    r = client.get(BASE, params={"startPeriod": s, "endPeriod": e})
    assert r.status_code == 400
    assert "later" in r.json()["detail"]


def test_valid_annual_range(client):
    r = client.get(BASE, params={"startPeriod": "2020", "endPeriod": "2020"})
    assert _periods(r) == ["2020", "2020"]
    r = client.get(BASE, params={"startPeriod": "2020"})
    assert _obs_count(r) == 3
    r = client.get(BASE, params={"endPeriod": "2019"})
    assert _periods(r) == ["2019"]


def test_same_start_and_end_allowed(client):
    r = client.get("/sdmx/2.1/data/INS,MIXED1",
                   params={"startPeriod": "2020-03", "endPeriod": "2020-03"})
    assert _periods(r) == ["2020-03"]


MIX = "/sdmx/2.1/data/INS,MIXED1"


def test_mixed_granularity_policy(client):
    # Annual bounds cover all months/quarters of the year; non-conforming
    # labels (legacy "Anul 2020") never match a bound.
    r = client.get(MIX, params={"startPeriod": "2020", "endPeriod": "2020"})
    assert _periods(r) == ["2020", "2020-03", "2020-11", "2020-Q1", "2020-Q3"]
    # Quarter bound on mixed data: a quarter spans three months; the annual
    # row is excluded (not wholly inside), monthly rows inside it are kept.
    r = client.get(MIX, params={"startPeriod": "2020-Q1", "endPeriod": "2020-Q1"})
    assert _periods(r) == ["2020-03", "2020-Q1"]
    # Month bound.
    r = client.get(MIX, params={"startPeriod": "2020-04", "endPeriod": "2021-02"})
    assert _periods(r) == ["2020-11", "2020-Q3", "2021-02"]
    # No bound: everything, including the legacy label.
    assert _obs_count(client.get(MIX)) == 8


def test_last_n_validation_and_semantics(client):
    for bad in ("0", "-1"):
        assert client.get(BASE, params={"lastNObservations": bad}).status_code == 422
    assert client.get(BASE, params={"lastNObservations": "abc"}).status_code == 422
    r = client.get(BASE, params={"lastNObservations": "1"})
    assert _periods(r) == ["2021"]
    r = client.get(BASE, params={"lastNObservations": "2"})
    assert _periods(r) == ["2020", "2020", "2021"]
    # Combined with period bound and a key.
    r = client.get(BASE + "/Total", params={"lastNObservations": "1", "endPeriod": "2020"})
    assert _periods(r) == ["2020", "2020"]


def test_key_values_are_literals(client):
    # Apostrophe and XML specials in a key value work as a literal.
    r = client.get(BASE + "/O'Brien & <Co>")
    assert _obs_count(r) == 1
    # The legacy raw-value key still works; the emitted code is the canonical ID
    # (FIX-01 phase 2), never the raw label.
    assert "O&#x27;Brien" not in r.text and "&lt;Co&gt;" not in r.text
    # Injection-shaped key matches nothing instead of everything.
    r = client.get(BASE + "/x' OR '1'='1")
    assert _obs_count(r) == 0
    r = client.get(BASE + "/Total+Nope.Cluj")
    assert _obs_count(r) == 2


def test_key_with_too_many_segments_is_400(client):
    assert client.get(BASE + "/Total.Cluj.2020.extra").status_code == 400
    assert client.get(BASE + "/Total.Cluj.2020..").status_code == 200


def test_unknown_or_malformed_flow_is_404(client):
    assert client.get("/sdmx/2.1/data/INS,NOPE").status_code == 404
    assert client.get("/sdmx/2.1/data/INS,AN'N1").status_code == 404
    assert client.get("/sdmx/2.1/data/INS,..%2Fmetadata").status_code == 404
    assert client.get("/sdmx/2.1/datastructure/INS/NOPE/1.0").status_code == 404
    assert client.get("/sdmx/2.1/dataflow/INS/NOPE/1.0").status_code == 404


def test_dataflow_version_is_escaped(client):
    r = client.get('/sdmx/2.1/dataflow/INS/ANN1/1.0"%20x=%22y')
    assert r.status_code == 200
    import xml.etree.ElementTree as ET
    ET.fromstring(r.content)           # well-formed
    assert "x=" not in r.text          # attribute injection impossible


def test_no_leak_on_query_failure(client, monkeypatch):
    import app.routers.sdmx as sdmx_router
    # Break the parquet: schema mismatch makes the query fail internally.
    monkeypatch.setattr(sdmx_router, "_parquet_path",
                        lambda flow: "/nonexistent/secret/dir/x.parquet")
    r = client.get(BASE)
    assert r.status_code == 500
    assert r.json() == {"detail": "Query failed"}
    assert "/nonexistent" not in r.text and "parquet" not in r.text.lower()


def test_cursor_closed_on_success_and_failure(client, monkeypatch):
    import app.routers.sdmx as sdmx_router
    closed = []
    real_get_conn = sdmx_router.get_conn

    class Spy:
        def __init__(self, c):
            self._c = c

        def execute(self, *a, **k):
            return self._c.execute(*a, **k)

        def close(self):
            closed.append(1)
            self._c.close()

    monkeypatch.setattr(sdmx_router, "get_conn", lambda: Spy(real_get_conn()))
    assert client.get(BASE).status_code == 200
    assert len(closed) == 1
    assert client.get(BASE, params={"startPeriod": "bad"}).status_code == 400
    monkeypatch.setattr(sdmx_router, "_parquet_path",
                        lambda flow: "/nonexistent/x.parquet")
    assert client.get(BASE).status_code == 500
    assert len(closed) == 2


def test_no_unconstrained_connection():
    import inspect
    import app.routers.sdmx as sdmx_router
    assert "duckdb.connect" not in inspect.getsource(sdmx_router)
    assert "memory_limit" in inspect.getsource(__import__("app.db").db)
