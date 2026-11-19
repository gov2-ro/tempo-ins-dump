"""TEMPO response rules (tempo_http) and where the fetchers use them.

- TEMPO declares UTF-8 but sends stray Windows-1250 bytes: JUS109B's metadata has
  b"viol sav\\xe2rsit" (2026-11-19), which a "replace" decode stored as U+FFFD.
- A failed query answers HTTP 200 with one sentence. Stage 6 must treat it as a
  retryable failure (exit 1), never as an empty dataset (exit 3, never retried).
- The orchestrator stops before any state change when a one-cell data probe fails.
Offline: fake INS endpoints.
"""
import importlib.util
import json
from pathlib import Path

import pytest

from tempo_http import decode_body, is_error_envelope
from test_fix03_orchestrator import pipe  # noqa: F401  (fixture)

ROOT = Path(__file__).resolve().parent.parent
ENVELOPE_EN = b'[["The results to your query could not be returned. Please try again later."]]'
ENVELOPE_RO = "Rezultatul solicitat nu poate fi returnat momentan.".encode("utf-8")
HEADER = b"Grupe, Ani, Valoare\n"


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, ROOT / path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def response(body):
    return type("R", (), {"content": body, "status_code": 200, "headers": {},
                          "raise_for_status": lambda self: None})()


# ------------------------------------------------------------------ tempo_http
def test_decode_body_reads_stray_cp1250_bytes():
    assert decode_body(b"viol sav\xe2rsit") == "viol savârsit"
    assert decode_body("Începând în 2020".encode("utf-8")) == "Începând în 2020"
    assert decode_body(b"on\xa0January") == "on January"


@pytest.mark.parametrize("body", [ENVELOPE_EN, ENVELOPE_RO])
def test_error_envelope_is_detected(body):
    assert is_error_envelope(decode_body(body))


def test_data_and_long_bodies_are_not_envelopes():
    assert not is_error_envelope("Grupe, Ani, Valoare\nG1, Anul 2020, 3\n")
    assert not is_error_envelope("")
    long_text = "x" * 3000 + " results to your query could not be returned"
    assert not is_error_envelope(long_text)


# ------------------------------------------------------------------ stage 3
def test_fetch_metas_stores_cp1250_bytes_as_text(tmp_path, monkeypatch):
    mod_src = (ROOT / "3-fetch-metas.py").read_text(encoding="utf-8")
    assert "decode_body(response.content)" in mod_src   # the script runs at import; check the source
    body = b'{"label": "Din total: viol sav\xe2rsit asupra unui minor"}'
    assert "�" not in decode_body(body)
    assert json.loads(decode_body(body))["label"].endswith("savârsit asupra unui minor")


# ------------------------------------------------------------------ stage 6
@pytest.fixture
def stage6(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)            # stage 6 resolves data/ from cwd
    mod = load("fetch_csv_envelope_t", "6-fetch-csv.py")
    metas = tmp_path / "data" / "2-metas" / "ro"
    metas.mkdir(parents=True)
    (metas / "ENV1.json").write_text(json.dumps({
        "dimensionsMap": [
            {"label": "Grupe", "options": [{"label": "G1", "nomItemId": 1}]},
            {"label": "Ani", "options": [{"label": "Anul 2020", "nomItemId": 1001}]},
        ],
        "details": {"matMaxDim": 2, "matUMSpec": 0},
    }))
    return mod


def test_envelope_is_a_retryable_failure_and_writes_no_csv(stage6, monkeypatch):
    monkeypatch.setattr(stage6.requests, "post", lambda *a, **k: response(ENVELOPE_EN))
    assert stage6.main(["--matrix", "ENV1", "--force"]) == stage6.EXIT_FETCH_FAILED
    assert not Path("data/4-datasets/ro/ENV1.csv").exists()


def test_envelope_on_the_totals_retry_is_retryable(stage6, monkeypatch):
    answers = iter([response(HEADER), response(ENVELOPE_RO)])   # header-only, then the envelope
    monkeypatch.setattr(stage6.requests, "post", lambda *a, **k: next(answers))
    assert stage6.main(["--matrix", "ENV1", "--force"]) == stage6.EXIT_FETCH_FAILED


def test_failed_totals_retry_request_is_retryable_not_empty(stage6, monkeypatch):
    calls = []

    def post(*a, **k):
        calls.append(1)
        if len(calls) == 1:
            return response(HEADER)
        raise ConnectionError("down")

    monkeypatch.setattr(stage6.requests, "post", post)
    assert stage6.main(["--matrix", "ENV1", "--force"]) == stage6.EXIT_FETCH_FAILED


def test_header_only_answers_are_still_an_empty_dataset(stage6, monkeypatch):
    monkeypatch.setattr(stage6.requests, "post", lambda *a, **k: response(HEADER))
    monkeypatch.setattr(stage6, "fetch_insse_excel_data", lambda *a, **k: None)
    assert stage6.main(["--matrix", "ENV1", "--force"]) == stage6.EXIT_EMPTY_DATASET


# ------------------------------------------------------------------ orchestrator
def test_failed_probe_stops_before_any_state_change(pipe):
    pipe.seed_watermark()
    before = pipe.state_path.read_text()
    pipe.feed([("05.05.2026", "AAA1")])
    pipe.probe_fail = "TEMPO answered with its error message"
    assert pipe.go() == 1
    assert pipe.calls == [] and pipe.meta_calls == []
    assert pipe.state_path.read_text() == before


def test_dry_run_does_not_probe(pipe, monkeypatch):
    pipe.feed([("05.05.2026", "AAA1")])
    monkeypatch.setattr(pipe.mod, "probe_tempo_data", lambda lang: pytest.fail("network in dry-run"))
    assert pipe.go("--dry-run") == 0


@pytest.mark.parametrize("body, ok", [
    (HEADER + b"G1, Anul 2020, 3\n", True),
    (ENVELOPE_EN, False),
    (HEADER, False),
])
def test_probe_reads_one_cell(tmp_path, monkeypatch, body, ok):
    mod = load("update_pipeline_probe_t", "update-pipeline.py")
    monkeypatch.setattr(mod, "data_dir", lambda: tmp_path / "data")
    metas = tmp_path / "data" / "2-metas" / "ro"
    metas.mkdir(parents=True)
    (metas / f"{mod.PROBE_MATRIX}.json").write_text(json.dumps({
        "dimensionsMap": [{"options": [{"nomItemId": 7}, {"nomItemId": 8}]},
                          {"options": [{"nomItemId": 9}]}],
        "details": {"matMaxDim": 2, "matUMSpec": 0},
    }))
    sent = []
    monkeypatch.setattr(mod.requests, "post",
                        lambda url, json=None, **k: sent.append(json) or response(body))
    assert (mod.probe_tempo_data("ro") is None) is ok
    assert sent[0]["encQuery"] == "7:9" and sent[0]["matCode"] == mod.PROBE_MATRIX


def test_probe_without_metadata_reports_why(tmp_path, monkeypatch):
    mod = load("update_pipeline_probe_t2", "update-pipeline.py")
    monkeypatch.setattr(mod, "data_dir", lambda: tmp_path / "data")
    assert "cannot build the probe" in mod.probe_tempo_data("ro")
