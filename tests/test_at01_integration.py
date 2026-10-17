"""AT-01 end to end: the seven tools as one flow on one synthetic generation.

Network, model providers and DuckDB writers fail if touched: the tools need
none of them. Each result is a valid `tempo-tools/2` envelope within 32 KiB, its
canonical selection is accepted by get_evidence_links, the live links re-run to
the same values and the evidence links refuse once the generation changes.
"""
import io
import json
import socket
import zipfile
from urllib.parse import urlsplit

import duckdb
import pytest

from app.services.tools import contract as C
from app.services.tools import registry as R
from at01_fixtures import add_search_columns, call, make_env, write_manifest
from test_at01_changes import build_countx
from test_at01_recipes_links import RECIPES, build_core, install_recipes


@pytest.fixture
def env(tmp_path, monkeypatch):
    def build(corpus):
        build_countx(corpus)
        build_core(corpus)
        add_search_columns(corpus)
    e = make_env(tmp_path, monkeypatch, build=build)
    install_recipes(tmp_path, monkeypatch, *RECIPES)
    return e


@pytest.fixture
def sealed(monkeypatch):
    """No network, no model call, no DuckDB writer on a database file."""
    def no_net(*a, **k):
        raise AssertionError("network access")

    def no_model(*a, **k):
        raise AssertionError("model call")
    monkeypatch.setattr(socket.socket, "connect", no_net)
    monkeypatch.setattr(socket, "create_connection", no_net)
    from app.services import agent, llm_client
    monkeypatch.setattr(llm_client, "complete_with_tools", no_model)
    monkeypatch.setattr(agent, "complete_with_tools", no_model)
    monkeypatch.setattr(agent, "run_agent", no_model)
    real = duckdb.connect

    def read_only_connect(database=":memory:", read_only=False, **kw):
        if database not in (":memory:", "") and not read_only:
            raise AssertionError("writer connection to a database file")
        return real(database, read_only=read_only, **kw)
    monkeypatch.setattr(duckdb, "connect", read_only_connect)


def tool(name, **args):
    env = call(name, **args)                       # validates against the published schemas
    assert C.size(env) <= C.MAX_RESULT_BYTES
    assert env["provenance"]["generation"]["id"] == "gen-at01-fixture"
    return env


def path_of(url):
    p = urlsplit(url)
    return p.path + ("?" + p.query if p.query else "")


def links_for(selection):
    out = tool("get_evidence_links", selection=selection, generation_id="gen-at01-fixture")
    assert out["status"] == "ok", out["message"]
    return {link["kind"]: link for link in out["data"]["links"]}


def test_the_seven_tools_need_no_network_model_or_writer(env, sealed):
    client = env.client

    d = tool("describe_dataset", dataset="COUNTX")
    assert d["status"] == "ok" and d["data"]["time"]["first"] == "1992" \
        and d["data"]["time"]["last"] == "2020"
    v = tool("find_dimension_values", dataset="COUNTX", column="TIME_PERIOD", query="199")
    assert [x["value"] for x in v["data"]["values"]] == ["1992"]
    disc = tool("discover_indicators", query="populatie Cluj 2024")
    assert disc["status"] in ("ok", "needs_clarification")

    # one county's series, through the shared policy
    q = tool("query_data", dataset="COUNTX", filters={"REF_AREA": ["A"]},
             group_by=["REF_AREA", "TIME_PERIOD"])
    assert q["status"] == "ok"
    series = {r[1]: r[-1] for r in q["data"]["rows"]}
    assert series == {"1992": 100.0, "2002": 80.0, "2010": 90.0, "2020": 60.0}

    # per-entity change over every eligible entity, D excluded for its missing 2002
    cp = tool("compare_periods", dataset="COUNTX", entity_columns=["REF_AREA"],
              intervals=[{"from": "1992", "to": "2002"}, {"from": "2010", "to": "2020"}])
    assert cp["status"] == "partial"
    first, second = cp["data"]["intervals"]
    assert [(r["entity"]["REF_AREA"], r["absolute"]) for r in first["rows"]] == \
        [("B", -50.0), ("A", -20.0), ("C", 0.0)]
    assert first["excluded"][0]["entity"] == {"REF_AREA": "D"}
    assert [r["entity"]["REF_AREA"] for r in second["rows"]] == ["D", "A", "B", "C"]

    rec = tool("run_recipe", recipe="fx_intensity", year="2024")
    assert rec["status"] == "partial"
    assert {r["label"]: r["value"] for r in rec["data"]["rows"]}["Alfa"] == 2.0

    # every result's canonical selection gets links; the live ones re-run to the same values
    q_links = links_for(q["provenance"]["selection"])
    live = client.get(path_of(q_links["live_selection"]["url"])).json()
    assert {r[1]: r[-1] for r in live["rows"]} == series
    assert live["aggregation"]["outcome"] == q["provenance"]["aggregation"]["outcome"]

    cp_links = links_for(cp["provenance"]["selection"])
    live_cp = client.get(path_of(cp_links["live_selection"]["url"])).json()
    assert live_cp["data"]["intervals"] == cp["data"]["intervals"]

    rec_links = links_for(rec["provenance"]["selection"])
    live_rec = client.get(path_of(rec_links["live_selection"]["url"])).json()
    assert {r["label"]: r["value"] for r in live_rec["rows"]} == \
        {r["label"]: r["value"] for r in rec["data"]["rows"]}

    # evidence bundles are bound to the generation the answers came from
    for links in (q_links, cp_links, rec_links):
        r = client.get(path_of(links["evidence"]["url"]))
        assert r.status_code == 200, r.text
        manifest = json.loads(zipfile.ZipFile(io.BytesIO(r.content)).read("manifest.json"))
        assert manifest["generation"]["id"] == "gen-at01-fixture"


def test_a_new_generation_refuses_the_old_answers_evidence(env, sealed):
    q = tool("query_data", dataset="COUNTX", filters={"REF_AREA": ["B"]},
             group_by=["REF_AREA", "TIME_PERIOD"])
    cp = tool("compare_periods", dataset="COUNTX", entity_columns=["REF_AREA"],
              intervals=[{"from": "2010", "to": "2020"}])
    links = [links_for(q["provenance"]["selection"]), links_for(cp["provenance"]["selection"])]
    write_manifest(env.corpus, "gen-next")
    for ls in links:
        r = env.client.get(path_of(ls["evidence"]["url"]))
        assert r.status_code == 409 and r.json()["detail"]["reason"] == "generation_changed"
    stale = R.call_tool("get_evidence_links", {"selection": q["provenance"]["selection"],
                                              "generation_id": "gen-at01-fixture"})
    assert stale["status"] == "unavailable" and stale["reason"] == "generation_changed"
    assert "links" not in stale["data"]


def test_every_tool_publishes_matching_schemas():
    for name, spec in R.TOOLS.items():
        assert R.input_schema(name)["additionalProperties"] is False
        out = R.output_schema(name)
        assert set(out["required"]) >= {"contract", "tool", "status", "reason", "message", "data",
                                        "provenance", "limits", "warnings", "recovery"}
        assert spec.description and len(spec.description) < 600
