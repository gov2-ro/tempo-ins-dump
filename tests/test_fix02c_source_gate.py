"""insights._source_total_gate: a summed KPI is published only when INS's own total
for the same slice agrees (kpi_total_checks, written by scripts/check-kpi-totals.py)."""
from types import SimpleNamespace

import duckdb
import pytest

from app.services.dataset_meta import source_total_gate as _source_total_gate

DDL = ("CREATE TABLE kpi_total_checks (matrix_code VARCHAR PRIMARY KEY, period VARCHAR, ours DOUBLE, "
       "ins DOUBLE, rel DOUBLE, status VARCHAR, reason VARCHAR)")


def decision(*verifs, treatment='partition'):
    return SimpleNamespace(dimensions=[{'column': f'D{i}', 'treatment': treatment, 'verification': v}
                                       for i, v in enumerate(verifs)]
                           + [{'column': 'TIME_PERIOD', 'treatment': 'time', 'verification': None}])


@pytest.fixture
def conn():
    c = duckdb.connect()
    c.execute(DDL)
    c.executemany("INSERT INTO kpi_total_checks VALUES (?, ?, ?, ?, ?, ?, ?)", [
        ('OK1', '2023', 4862, 4862, 0.0, 'match', None),
        ('BAD1', '2023', 4960, 4862, 0.02, 'mismatch', None),
        ('NOTOT1', '2023', 7.0, None, None, 'unresolved', 'no_total_option:CATEGORY'),
        ('BLANK1', '2023', 7.0, None, None, 'ins_blank', None),
    ])
    return c


def test_match_publishes_with_the_source_value(conn):
    assert _source_total_gate(conn, 'OK1', decision('profile_flat')) == (
        None, {'source': 'INS', 'period': '2023', 'value': 4862.0, 'relative_diff': 0.0})


def test_mismatch_withholds_even_verified_structure(conn):
    assert _source_total_gate(conn, 'BAD1', decision('verified'))[0] == 'source_total_mismatch'


@pytest.mark.parametrize('code,reason', [('NOTOT1', 'no_source_total'), ('BLANK1', 'source_total_unchecked'),
                                         ('NEVER1', 'source_total_unchecked')])
def test_weak_verification_needs_a_match(conn, code, reason):
    assert _source_total_gate(conn, code, decision('verified', 'profile_flat'))[0] == reason
    assert _source_total_gate(conn, code, decision('metadata'))[0] == reason


def test_verified_sum_without_a_check_stands(conn):
    assert _source_total_gate(conn, 'NEVER1', decision('verified', 'curated')) == (None, None)


def test_unsummed_kpi_and_older_generation_are_untouched(conn):
    assert _source_total_gate(conn, 'BAD1', decision('profile_flat', treatment='pinned_value')) == (None, None)
    assert _source_total_gate(duckdb.connect(), 'BAD1', decision('profile_flat')) == (None, None)


# ------------------------------------------------- grouped /data and insights agree
def _client_with_check(tmp_path, monkeypatch, status):
    import json as _json
    from fix02b_corpus import make_client
    client = make_client(tmp_path, monkeypatch, structure=True)
    db = duckdb.connect(str(tmp_path / "corpus" / "metadata.duckdb"))
    db.execute(DDL)
    db.execute("INSERT INTO kpi_total_checks VALUES ('POPX', '2025', 110, ?, ?, ?, NULL)",
               [110.0 if status == 'match' else 100.0, 0.0 if status == 'match' else 0.1, status])
    db.close()
    return client


def _data(client, group_by, filters=None):
    import json as _json
    r = client.get("/api/datasets/POPX/data", params={
        "group_by": _json.dumps(group_by), "filters": _json.dumps(filters or {})})
    assert r.status_code == 200, r.text
    return r.json()


def test_headline_series_refused_when_ins_disagrees(tmp_path, monkeypatch):
    client = _client_with_check(tmp_path, monkeypatch, 'mismatch')
    body = _data(client, ["TIME_PERIOD"])
    assert body["unavailable"] and body["rows"] == []
    assert body["aggregation"]["reason"] == "source_total_mismatch"
    ins = client.get("/api/datasets/POPX/insights").json()
    assert not any(k["key"] == "latest" for k in ins["kpis"])
    assert {"key": "latest", "reason": "source_total_mismatch"}.items() <= next(
        s for s in ins["suppressed"] if s["key"] == "latest").items()
    # other queries are not the checked slice and are left alone
    assert not _data(client, ["SEX"]).get("unavailable")
    assert not _data(client, ["TIME_PERIOD"], {"SEX": ["Feminin"]}).get("unavailable")


def test_headline_series_kept_when_ins_agrees(tmp_path, monkeypatch):
    client = _client_with_check(tmp_path, monkeypatch, 'match')
    body = _data(client, ["TIME_PERIOD"])
    assert not body.get("unavailable")
    assert {r[0]: r[-1] for r in body["rows"]}["2025"] == pytest.approx(110.0)
