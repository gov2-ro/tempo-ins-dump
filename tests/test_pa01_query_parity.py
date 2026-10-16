"""PA-01a: one validated query for REST, Ask and the dev MCP.

Audit A01 (MCP summed overlapping ages), A02 (Ask ignored an unknown filter) and
A08 (MCP samples interpolated literals). Every case runs the same request through
all three adapters on the synthetic corpus and expects the same verdict and values.
"""
import importlib.util
import json
from pathlib import Path

import pytest

from ask_adapter import ask
from at01_fixtures import make_env
from fix02b_corpus import POPX_NAIVE_2025

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def env(tmp_path, monkeypatch):
    client = make_env(tmp_path, monkeypatch).client      # with a generation manifest: Ask's tools need one
    spec = importlib.util.spec_from_file_location(
        "tempo_dev_mcp_server", ROOT / "tools" / "tempo-dev-mcp" / "server.py")
    server = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(server)
    server._ensure_imports()
    monkeypatch.setattr(server, "PARQUET_DIR", tmp_path / "corpus" / "parquet")
    return client, server


def rest(client, code, filters=None, group_by=None, approximate=False):
    params = {"approximate": int(approximate)}
    if filters is not None:
        params["filters"] = json.dumps(filters)
    if group_by is not None:
        params["group_by"] = json.dumps(group_by)
    r = client.get(f"/api/datasets/{code}/data", params=params)
    return r.status_code, r.json()


def mcp(server, code, filters=None, group_by=None, approximate=False):
    return json.loads(server.tempo_query(
        code, None if filters is None else json.dumps(filters),
        None if group_by is None else json.dumps(group_by), 1000, approximate))


# ------------------------------------------------------------ invalid input

@pytest.mark.parametrize("filters", [
    {"BOGUS": ["Cluj"]},              # A02: unknown column
    ["AGE"],                          # not an object
    {"AGE": "0 ani"},                 # value not an array
    {"AGE": [None]},                  # non-scalar member
])
def test_invalid_filters_fail_in_every_adapter(env, filters):
    client, server = env
    status, body = rest(client, "POPX", filters, ["TIME_PERIOD"])
    assert status == 400 and body["detail"].startswith("Invalid filters")
    a = ask("POPX", filters, ["TIME_PERIOD"])
    assert "filters" in a["error"].lower() and "rows" not in a      # schema layer or run_query, never a query
    m = mcp(server, "POPX", filters, ["TIME_PERIOD"])
    assert m["error"].startswith("Invalid filters") and "rows" not in m


def test_unknown_group_by_and_bad_approximate_fail(env):
    client, server = env
    assert rest(client, "POPX", group_by=["NOPE"])[0] == 400
    assert "group_by" in ask("POPX", group_by=["NOPE"])["error"].lower()
    assert mcp(server, "POPX", group_by=["NOPE"])["error"].startswith("Invalid group_by")
    assert "error" in ask("POPX", group_by=["TIME_PERIOD"], approximate="yes")


# ------------------------------------------------------------ same decision

CASES = [
    # (code, filters, group_by, approximate)
    ("POPX", None, ["TIME_PERIOD"], False),            # A01: overlapping AGE levels
    ("POPX", {"AGE": [f"{a} ani" for a in range(5)]}, ["TIME_PERIOD"], False),
    ("ADDX", None, ["TIME_PERIOD"], False),             # pinned to the Total row
    ("RATEX", None, ["TIME_PERIOD"], False),            # rates without weights
    ("RATEX", None, ["TIME_PERIOD"], True),             # explicit approximation
    ("INCX", None, ["TIME_PERIOD"], False),             # means named in options
]


def _verdict(aggregation):
    a = aggregation or {}
    return (a.get("outcome"), a.get("reason"), a.get("blocking_dimension"),
            a.get("method"), json.dumps(a.get("filters"), sort_keys=True))


@pytest.mark.parametrize("code,filters,group_by,approximate", CASES)
def test_rest_ask_mcp_agree(env, code, filters, group_by, approximate):
    client, server = env
    status, r = rest(client, code, filters, group_by, approximate)
    assert status == 200
    a = ask(code, filters, group_by, approximate)
    m = mcp(server, code, filters, group_by, approximate)

    assert _verdict(r["aggregation"]) == _verdict(a["aggregation"]) == _verdict(m["aggregation"])
    assert r["rows"] == a["rows"] == m["rows"]
    assert r["columns"] == a["columns"] == m["columns"]
    unavailable = bool(r.get("unavailable"))
    assert unavailable == bool(m.get("unavailable")) == (a["status"] == "unavailable")
    if r["aggregation"]["outcome"] == "approximation":
        assert approximate and a["status"] == "approximation"


def test_overlapping_levels_are_refused_not_summed(env):
    client, server = env
    m = mcp(server, "POPX", group_by=["TIME_PERIOD"])
    assert m["unavailable"] is True and m["rows"] == []
    assert m["aggregation"]["reason"] == "overlapping_levels"
    assert m["aggregation"]["blocking_dimension"] == "AGE"
    assert str(POPX_NAIVE_2025) not in json.dumps(m)


def test_rates_need_explicit_approximation(env):
    client, server = env
    assert mcp(server, "RATEX", group_by=["TIME_PERIOD"])["aggregation"]["reason"] == "missing_weights"
    approx = mcp(server, "RATEX", group_by=["TIME_PERIOD"], approximate=True)
    assert {r[0]: r[1] for r in approx["rows"]}["2023"] == pytest.approx(15.0)


# ------------------------------------------------------------ empty selections

def test_empty_selection_is_explicit_and_never_broadened(env):
    client, server = env
    filters = {"CATEGORY": ["Total"], "TIME_PERIOD": ["1999"]}
    _, r = rest(client, "ADDX", filters)
    a = ask("ADDX", filters)
    m = mcp(server, "ADDX", filters)
    for res in (r, a, m):
        assert res["rows"] == []
        assert res["selection"] == {"empty": True, "missing_values": {"TIME_PERIOD": ["1999"]}}
    # Ask's tool says so in words and offers the periods the data has; nothing stands in for 1999
    assert a["status"] == "unavailable" and "Nothing was substituted" in a["envelope"]["message"]
    assert a["envelope"]["recovery"][0]["tool"] == "find_dimension_values"


# ------------------------------------------------------------ MCP samples (A08)

@pytest.mark.parametrize("value", ["O'Brien", "x') OR 1=1 --", "Total'; DROP TABLE t; --"])
def test_sample_binds_adversarial_literals(env, value):
    _, server = env
    out = json.loads(server.tempo_sample("ADDX", 5, json.dumps({"CATEGORY": [value]})))
    assert out == {"matrix_code": "ADDX", "row_count": 0, "rows": []}


def test_sample_filters_and_limits(env):
    _, server = env
    out = json.loads(server.tempo_sample("ADDX", 2, json.dumps({"CATEGORY": ["A"]})))
    assert out["row_count"] == 2 and {r["CATEGORY"] for r in out["rows"]} == {"A"}
    assert "error" in json.loads(server.tempo_sample("ADDX", 5, json.dumps({"BOGUS": ["A"]})))
    assert "error" in json.loads(server.tempo_sample("ADDX", 5, "null"))
    assert "error" in json.loads(server.tempo_sample("ADDX", 0))
    assert "error" in json.loads(server.tempo_sample("ADDX", 101))
