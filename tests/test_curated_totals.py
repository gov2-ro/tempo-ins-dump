"""DP-01 part 1 (option B): app/data/curated_totals.json names total options that the
label rule (TOTAL_RE) cannot recognise. Their KPI is INS's own total, never a sum."""
import json
from pathlib import Path

import duckdb
import pytest

import app.services.dimension_structure as dstruct

from fix02b_corpus import make_client

LISTED = Path(dstruct.CURATED_TOTALS_FILE)
TOTAL = "Consum total de X"


def _client(tmp_path, monkeypatch, curated):
    client = make_client(tmp_path, monkeypatch)
    corpus = tmp_path / "corpus"
    pq = str(corpus / "parquet" / "ADDX.parquet")
    tmp = str(corpus / "parquet" / "ADDX.tmp.parquet")
    c = duckdb.connect()
    c.execute(f"COPY (SELECT replace(CATEGORY, 'Total', '{TOTAL}') AS CATEGORY, TIME_PERIOD, OBS_VALUE "
              f"FROM read_parquet('{pq}')) TO '{tmp}' (FORMAT PARQUET)")
    c.close()
    Path(tmp).replace(pq)
    db = duckdb.connect(str(corpus / "metadata.duckdb"))
    db.execute(f"UPDATE dimension_options SET option_label = '{TOTAL}' WHERE option_label = 'Total'")
    db.execute(f"UPDATE sdmx_codes SET sdmx_value = '{TOTAL}', display_label_en = '{TOTAL}' "
               "WHERE sdmx_value = 'Total'")
    db.execute("CREATE TABLE kpi_total_checks (matrix_code VARCHAR PRIMARY KEY, period VARCHAR, "
               "ours DOUBLE, ins DOUBLE, rel DOUBLE, status VARCHAR, reason VARCHAR)")
    db.execute("INSERT INTO kpi_total_checks VALUES ('ADDX', '2023', 170, NULL, NULL, 'unresolved', "
               "'no_total_option:CATEGORY')")
    db.close()
    monkeypatch.setattr(dstruct, "_curated", curated)
    return client


def _latest(client):
    ins = client.get("/api/datasets/ADDX/insights").json()
    return next((k for k in ins["kpis"] if k["key"] == "latest"), None), ins


def test_listed_total_is_the_kpi(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch, {("ADDX", "CATEGORY"): TOTAL})
    latest, _ = _latest(client)
    assert latest is not None
    assert latest["value"] == pytest.approx(120.0)          # the total's own cell, not a sum
    assert latest["provenance"]["method"] == "aggregate_row"
    assert latest["provenance"]["filters"] == {"CATEGORY": [TOTAL]}


def test_unlisted_dataset_is_still_refused(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch, {})
    latest, ins = _latest(client)
    assert latest is None
    assert any(s["key"] == "latest" for s in ins["suppressed"])


def test_load_marks_the_curated_entry(tmp_path, monkeypatch):
    _client(tmp_path, monkeypatch, {("ADDX", "CATEGORY"): TOTAL})
    conn = duckdb.connect(str(tmp_path / "corpus" / "metadata.duckdb"), read_only=True)
    s = dstruct.load(conn, "ADDX")["CATEGORY"]
    assert (s["aggregate_value"], s["additive"], s["source"]) == (TOTAL, False, "curated")


# ------------------------------------------------------------------ the list itself
def _entries():
    return json.loads(LISTED.read_text(encoding="utf-8"))["totals"]


def test_list_entries_are_complete_and_unique():
    entries = _entries()
    assert entries
    for e in entries:
        assert all(isinstance(e.get(k), str) and e[k].strip() for k in ("code", "column", "option", "reason")), e
    keys = [(e["code"], e["column"]) for e in entries]
    assert len(keys) == len(set(keys))


@pytest.mark.corpus
def test_listed_options_exist_in_the_parquet():
    from app.config import PARQUET_DIR
    for e in _entries():
        path = Path(PARQUET_DIR) / f"{e['code']}.parquet"
        assert path.exists(), e
        got = duckdb.connect().execute(
            f'SELECT count(*) FROM read_parquet(?) WHERE "{e["column"]}" = ?',
            [str(path), e["option"]]).fetchone()[0]
        assert got > 0, f"{e['code']}: option not found: {e['option']!r}"
