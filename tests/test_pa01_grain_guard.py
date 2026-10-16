"""PA-01b: aggregations need a unique grain; raw rows carry their status (A04).

Synthetic: DUPX repeats one full key with different values (conflicting grain),
EQX repeats one with the same value (a SUM would count it twice). Generation
evidence comes from corpus/generation-manifest.json, as in a staged release.
"""
import json

import duckdb
import pytest

from fix02b_corpus import _write, make_client
from ask_adapter import ask
from test_pa01_query_parity import mcp, rest  # same adapters


def _add_dataset(corpus, code, rows):
    _write(corpus / "parquet" / f"{code}.parquet",
           "CATEGORY VARCHAR, TIME_PERIOD VARCHAR, OBS_VALUE DOUBLE", rows)
    db = duckdb.connect(str(corpus / "metadata.duckdb"))
    did = db.execute("SELECT max(dimension_id) FROM dimensions").fetchone()[0]
    db.execute("INSERT INTO matrices (matrix_code, matrix_name, matrix_name_en, row_count, "
               "definitie) VALUES (?, ?, ?, ?, ?)", [code, code, code, len(rows), code])
    db.execute("INSERT INTO matrix_profiles VALUES (?, 'count', 'x', 2023, 2023, '[]')", [code])
    db.execute("INSERT INTO dimensions VALUES (?, ?, 1, 'Categorie', 'CATEGORY', 2)", [did + 1, code])
    db.execute("INSERT INTO dimensions VALUES (?, ?, 2, 'Ani', 'TIME_PERIOD', 1)", [did + 2, code])
    db.close()


def _manifest(corpus, *, duplicate=(), conflicting=(), db_size=None, recorded=True):
    m = {"generation_id": "g-test", "built_at": "2026-10-11T00:00:00+00:00",
         "db": {"size": db_size or (corpus / "metadata.duckdb").stat().st_size},
         "audit": {"grain_checked": True,
                   "violations": {"conflicting_grain": list(conflicting)},
                   "grain_findings": ({"duplicate_grain": list(duplicate),
                                       "conflicting_grain": list(conflicting)}
                                      if recorded else None)}}
    (corpus / "generation-manifest.json").write_text(json.dumps(m))


@pytest.fixture
def env(tmp_path, monkeypatch):
    client = make_client(tmp_path, monkeypatch)
    corpus = tmp_path / "corpus"
    _add_dataset(corpus, "DUPX", [("A", "2023", 10.0), ("A", "2023", 11.0), ("B", "2023", 5.0)])
    _add_dataset(corpus, "EQX", [("A", "2023", 10.0), ("A", "2023", 10.0), ("B", "2023", 5.0)])
    from app.services import grain_guard
    grain_guard._cache.clear()
    import importlib.util
    from pathlib import Path
    spec = importlib.util.spec_from_file_location(
        "tempo_dev_mcp_server_gg",
        Path(__file__).resolve().parent.parent / "tools" / "tempo-dev-mcp" / "server.py")
    server = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(server)
    server._ensure_imports()
    monkeypatch.setattr(server, "PARQUET_DIR", corpus / "parquet")
    return client, server, corpus


GROUP = ["TIME_PERIOD", "CATEGORY"]


@pytest.mark.parametrize("code,reason", [("DUPX", "conflicting_grain"), ("EQX", "duplicate_keys")])
def test_repeated_keys_refuse_aggregation_everywhere(env, code, reason):
    client, server, corpus = env
    # a present generation without recorded findings: Ask's tools need the generation, and the
    # slice is then checked at query time, in every adapter alike
    _manifest(corpus, recorded=False)
    from app.services import grain_guard
    grain_guard._cache.clear()
    status, r = rest(client, code, group_by=GROUP)
    assert status == 200 and r["unavailable"] is True and r["rows"] == []
    assert r["aggregation"]["reason"] == reason
    assert r["quality"]["slice"]["ok"] is False
    a = ask(code, group_by=GROUP)
    assert a["status"] == "unavailable" and a["reason"] == reason and a["rows"] == []
    m = mcp(server, code, group_by=GROUP)
    assert m["unavailable"] is True and m["aggregation"]["reason"] == reason
    # never 21 (both A rows) or 20 (counted twice)
    assert "21.0" not in json.dumps(r) and "20.0" not in json.dumps(r)


def test_raw_rows_stay_available_with_their_status(env):
    client, _, corpus = env
    _manifest(corpus, duplicate=["DUPX", "EQX"], conflicting=["DUPX"])
    status, r = rest(client, "DUPX", {"CATEGORY": ["A"]})
    assert status == 200 and sorted(row[-1] for row in r["rows"]) == [10.0, 11.0]
    assert r["quality"]["grain"]["status"] == "conflicting"
    assert r["generation"]["id"] == "g-test" and r["contract"] == "tempo-query/1"
    a = ask("DUPX", {"CATEGORY": ["A"]})
    assert any("DATA QUALITY" in w for w in a["warnings"])


def test_clean_slice_of_a_flagged_file_is_allowed(env):
    client, _, corpus = env
    _manifest(corpus, duplicate=["DUPX"], conflicting=["DUPX"])
    status, r = rest(client, "DUPX", {"CATEGORY": ["B"]}, GROUP)
    assert status == 200 and r["rows"] == [["2023", "B", 5.0]]
    assert r["quality"]["slice"] == {**r["quality"]["slice"], "ok": True, "evidence": "slice_check"}


def test_certified_file_needs_no_slice_check(env):
    client, _, corpus = env
    _manifest(corpus, duplicate=["DUPX", "EQX"], conflicting=["DUPX"])
    _, r = rest(client, "ADDX", group_by=["TIME_PERIOD"])
    assert r["quality"]["grain"]["status"] == "unique"
    assert r["quality"]["slice"]["evidence"] == "generation_audit"


@pytest.mark.parametrize("kw,evidence", [
    ({"db_size": 1}, "manifest_stale"),            # manifest belongs to another DB
    ({"recorded": False}, "duplicates_not_recorded"),  # older manifest: conflicts only
])
def test_stale_or_partial_evidence_certifies_nothing(env, kw, evidence):
    client, _, corpus = env
    _manifest(corpus, **kw)
    _, r = rest(client, "ADDX", group_by=["TIME_PERIOD"])
    assert r["quality"]["grain"] == {**r["quality"]["grain"], "status": "unverified",
                                     "evidence": evidence}
    assert r["quality"]["slice"]["evidence"] == "slice_check"   # checked, not assumed
    assert {row[0]: row[1] for row in r["rows"]}["2023"] == 120.0


def test_unfiltered_check_is_bounded(env, monkeypatch):
    client, _, _ = env
    from app.services import grain_guard
    monkeypatch.setattr(grain_guard, "GRAIN_CHECK_MAX_ROWS", 1)
    _, r = rest(client, "EQX", group_by=GROUP)
    assert r["aggregation"]["reason"] == "grain_unverified"
    assert r["quality"]["slice"]["evidence"] == "slice_too_large_to_check"


def test_headline_refuses_repeated_keys(env):
    _, _, corpus = env
    from app.services import headlines as hl
    card, status = hl.resolve_indicator(
        duckdb.connect(), str(corpus / "parquet"),
        {"code": "EQX", "label_en": "x", "measure": "additive",
         "method": "aggregate_row", "slice": {"CATEGORY": ["A"]}}, "en")
    assert card is None and status == "duplicate_keys"


def test_health_reports_served_generation(env):
    client, _, corpus = env
    _manifest(corpus)
    g = client.get("/api/health").json()["generation"]
    assert g == {"id": "g-test", "status": "present", "built_at": "2026-10-11T00:00:00+00:00"}
