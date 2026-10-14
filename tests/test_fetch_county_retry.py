"""Stage 6 county split: an empty or failed INS answer is retried, never filed as "no rows".

INS answers 200 with an empty body when degraded (2026-10-12/14), and a laptop
sleep drops DNS. Either used to lose a county silently or end the whole run.
Offline: a fake /pivot endpoint.
"""
import importlib.util
from pathlib import Path

import pytest
import requests

ROOT = Path(__file__).resolve().parent.parent
HEADER = b"Judete, Localitati, Ani, Valoare\n"


def load():
    spec = importlib.util.spec_from_file_location("fetch_csv_county_t", ROOT / "6-fetch-csv.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class FakeINS:
    """Answers each county with one row; `bad` lists call numbers that fail (an exception or b"")."""

    def __init__(self, bad=None):
        self.bad, self.calls = bad or {}, 0

    def __call__(self, url, json=None, **kw):
        self.calls += 1
        r = self.bad.get(self.calls, None)
        if isinstance(r, Exception):
            raise r
        body = b"" if r == "empty" else HEADER + f"C{self.calls}, L, 2020, 1\n".encode()
        return type("R", (), {"content": body, "status_code": 200,
                              "raise_for_status": lambda self: None})()


@pytest.fixture
def stage6(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)            # stage 6 resolves data/ from cwd
    mod = load()
    monkeypatch.setattr(mod, "COUNTY_RETRY_WAITS", (0, 0))
    monkeypatch.setattr(mod, "group_localities_by_judet", lambda *a: {
        1: {"judet_name": "Alba", "localities": []},
        2: {"judet_name": "Arad", "localities": []}})
    monkeypatch.setattr(mod, "convert_to_pivot_payload", lambda *a, **k: {})
    (tmp_path / "out").mkdir()
    return mod, tmp_path / "out"


def run(mod, out):
    return mod.fetch_by_judet_split("X1", {"dimensionsMap": []}, str(out), {}, {}, {})


def test_empty_answer_is_retried_and_every_county_is_written(stage6, monkeypatch):
    mod, out = stage6
    ins = FakeINS(bad={1: "empty", 3: requests.ConnectionError("dns")})
    monkeypatch.setattr(mod.requests, "post", ins)
    assert run(mod, out) is True
    rows = (out / "X1.csv").read_text().splitlines()[1:]
    assert len(rows) == 2 and ins.calls == 4


def test_county_still_empty_after_retries_fails_the_matrix(stage6, monkeypatch):
    mod, out = stage6
    monkeypatch.setattr(mod.requests, "post", FakeINS(bad={2: "empty", 3: "empty", 4: "empty"}))
    assert run(mod, out) is False
    assert not (out / "X1.csv").exists()
