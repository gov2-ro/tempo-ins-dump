"""FIX-02 phase 2: grouped /data queries and the other consumers agree."""
import json

import duckdb
import pytest

from fix02b_corpus import make_client, POPX_NAIVE_2025, POPX_TRUE_2025

from app.services import aggregation_policy as ap


def q(client, code, group_by=None, filters=None, **kw):
    params = {"filters": json.dumps(filters or {}), **kw}
    if group_by is not None:
        params["group_by"] = json.dumps(group_by)
    r = client.get(f"/api/datasets/{code}/data", params=params)
    assert r.status_code == 200, r.text
    return r.json()


def series(body):
    return {r[0]: r[-1] for r in body["rows"]}


@pytest.fixture
def client(tmp_path, monkeypatch):
    return make_client(tmp_path, monkeypatch)


@pytest.fixture
def client_struct(tmp_path, monkeypatch):
    return make_client(tmp_path, monkeypatch, structure=True)


# ----------------------------------------------------- overlapping grains

def test_overlapping_age_grains_grouped_total_is_refused(client):
    body = q(client, "POPX", ["TIME_PERIOD"])
    assert body["unavailable"] is True and body["rows"] == []
    agg = body["aggregation"]
    assert agg["outcome"] == "unavailable"
    assert agg["reason"] == "overlapping_levels" and agg["blocking_dimension"] == "AGE"
    # the double-counted total must not appear anywhere in the payload
    assert str(POPX_NAIVE_2025) not in json.dumps(body)


def test_verified_level_applied_gives_the_true_total(client_struct):
    body = q(client_struct, "POPX", ["TIME_PERIOD"])
    assert "unavailable" not in body
    got = series(body)
    assert got["2025"] == pytest.approx(POPX_TRUE_2025)
    assert POPX_NAIVE_2025 not in got.values()
    agg = body["aggregation"]
    assert agg["outcome"] == "valid_total" and agg["method"] == "sum_partition"
    assert agg["levels"] == {"AGE": "age_y1"}


def test_axis_with_several_levels_is_restricted_to_one_grain(client_struct):
    body = q(client_struct, "POPX", ["AGE"], {"TIME_PERIOD": ["2025"]})
    ages = {r[0] for r in body["rows"]}
    assert ages == {f"{a} ani" for a in range(5)}      # no band mixed in
    assert body["aggregation"]["levels"] == {"AGE": "age_y1"}


def test_valid_explicit_slice_still_works(client):
    body = q(client, "POPX", ["TIME_PERIOD"], {"AGE": ["0-4 ani"]})
    assert "unavailable" not in body
    assert series(body)["2025"] == pytest.approx(110.0)  # 2 sexes x 50 x 1.1
    assert body["aggregation"]["outcome"] == "valid_slice"
    assert body["aggregation"]["filters"]["AGE"] == ["0-4 ani"]


def test_raw_rows_are_untouched(client):
    body = q(client, "POPX", None, {"TIME_PERIOD": ["2025"]})
    assert body["aggregation"] is None
    assert body["returned_rows"] == 12     # 6 AGE options x 2 sexes, raw


# ------------------------------------------------------ totals and rates

def test_total_row_is_pinned_not_summed_with_components(client):
    body = q(client, "ADDX", ["TIME_PERIOD"])
    assert series(body) == {"2022": 100.0, "2023": 120.0}      # never 200/240
    assert body["aggregation"]["method"] == "aggregate_row"
    assert body["aggregation"]["filters"]["CATEGORY"] == ["Total"]


def test_rate_collapse_is_refused_without_weights(client):
    body = q(client, "RATEX", ["TIME_PERIOD"])
    assert body["unavailable"] is True
    assert body["aggregation"]["reason"] == "missing_weights"


def test_rate_collapse_as_labelled_approximation_only_on_request(client):
    body = q(client, "RATEX", ["TIME_PERIOD"], approximate=1)
    agg = body["aggregation"]
    assert agg["outcome"] == "approximation" and agg["approximation"] is True
    assert agg["method"] == "unweighted_mean"
    assert series(body)["2023"] == pytest.approx(15.0)


def test_rate_by_its_own_dimension_needs_no_aggregation(client):
    body = q(client, "RATEX", ["REF_AREA", "TIME_PERIOD"])
    assert len(body["rows"]) == 4
    assert body["aggregation"]["outcome"] == "valid_total"


def test_time_collapse_is_flagged(client):
    body = q(client, "ADDX", ["CATEGORY"], {"CATEGORY": ["A", "B"]})
    assert {"column": "TIME_PERIOD", "code": "time_collapsed"} in body["aggregation"]["warnings"]


# ------------------------------------- consumers agree on the same slice

def _insight(client, code):
    r = client.get(f"/api/datasets/{code}/insights")
    assert r.status_code == 200, r.text
    return r.json()


def test_api_insights_composer_agent_agree_when_unavailable(client):
    from app.db import get_conn
    from app.services.agent import _handle_query_dataset_data

    api = q(client, "POPX", ["TIME_PERIOD"])["aggregation"]

    ins = _insight(client, "POPX")
    sup = next(s for s in ins["suppressed"] if s["key"] == "latest")
    assert not any(k["key"] == "latest" for k in ins["kpis"])

    meta = client.get("/api/datasets/POPX").json()
    comp = meta["chart_config"]["composition"]
    # every composed tile, replayed through the grouped API, gets the same
    # verdict the composer recorded — and never a double-counted AGE sum.
    assert comp["charts"], "expected at least one valid tile"
    for c in comp["charts"]:
        spec = c["data"]
        replay = q(client, "POPX", spec["group_by"], spec["filters"])
        assert "unavailable" not in replay
        assert replay["aggregation"]["outcome"] == spec["aggregation"]["outcome"]
        assert replay["aggregation"]["method"] == spec["aggregation"]["method"]
        assert POPX_NAIVE_2025 not in [r[-1] for r in replay["rows"]]

    conn = get_conn()
    try:
        agent = _handle_query_dataset_data(
            {"matrix_code": "POPX", "group_by": ["TIME_PERIOD"]}, conn)
    finally:
        conn.close()

    assert api["reason"] == sup["reason"] == agent["reason"] == "overlapping_levels"
    assert api["blocking_dimension"] == sup["column"] == agent["blocking_dimension"] == "AGE"
    assert agent["status"] == "unavailable" and agent["rows"] == []
    assert "suggestion" in agent


def test_api_insights_agent_headline_agree_when_available(client, tmp_path):
    from app.db import get_conn
    from app.services.agent import _handle_query_dataset_data
    from app.services import headlines as hl

    api = q(client, "ADDX", ["TIME_PERIOD"])
    ins = _insight(client, "ADDX")
    latest = next(k for k in ins["kpis"] if k["key"] == "latest")
    conn = get_conn()
    try:
        agent = _handle_query_dataset_data(
            {"matrix_code": "ADDX", "group_by": ["TIME_PERIOD"]}, conn)
    finally:
        conn.close()
    card, status = hl.resolve_indicator(
        duckdb.connect(), str(tmp_path / "corpus" / "parquet"),
        {"code": "ADDX", "label_en": "x", "measure": "additive",
         "method": "aggregate_row", "slice": {"CATEGORY": ["Total"]}}, "en")

    api_latest = series(api)["2023"]
    agent_latest = {r[0]: r[1] for r in agent["rows"]}["2023"]
    assert api_latest == latest["value"] == agent_latest == card["value"] == 120.0
    prov = latest["provenance"]
    assert prov["method"] == api["aggregation"]["method"] == agent["aggregation"]["method"]
    assert prov["filters"] == api["aggregation"]["filters"]


def test_non_additive_policy_is_the_shared_one(client):
    from app.services import query_builder
    assert not hasattr(query_builder, "AVG_UNIT_TYPES")
    # unit label alone no longer decides currency; wording does
    assert ap.dataset_measure("currency", "Castigul salarial mediu") == "non_additive"
    assert ap.dataset_measure("currency", "Cifra de afaceri") == "additive"
    assert ap.dataset_measure("currency", "Investiții brute") == "additive"
    assert ap.dataset_measure("percentage", "x") == "non_additive"
    # a verified additive structure beats the unit heuristic
    assert ap.dataset_measure("index", "x", {"C": {"additive": True}}) == "additive"
    assert ap.dataset_measure("count", "x", {"C": {"additive": False}}) == "non_additive"
