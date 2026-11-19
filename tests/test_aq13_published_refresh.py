"""AQ-13: the orchestrator re-fetches and re-loads every matrix that the shipped spec lists,
and only the queries of the matrix INS updated."""
import json
from pathlib import Path

import pytest

from test_fix03_orchestrator import pipe  # noqa: F401  (fixture)

ROOT = Path(__file__).resolve().parent.parent
SPEC = json.loads((ROOT / "app" / "data" / "published_totals.json").read_text(encoding="utf-8"))
MATRICES = sorted({q["matrix"] for q in SPEC["queries"]})


def test_the_spec_lists_the_aq13_indicators():
    assert {"TCP0341", "POP217A", "POP209A", "POP209B", "IPC102A", "IPC102B", "IPC102E", "FOM106E",
            "FOM107E", "SOM103A", "AMG157A", "CON103H"} <= set(MATRICES)


@pytest.mark.parametrize("code", MATRICES)
def test_an_updated_listed_matrix_is_refetched_and_reloaded(pipe, monkeypatch, code):
    monkeypatch.setattr(pipe.mod, "PUBLISHED_TOTALS_SPEC", ROOT / "app" / "data" / "published_totals.json")
    pipe.feed([("05.05.2026", code)])
    assert pipe.go() == 0
    fetched = [a[a.index("--only") + 1] for s, a in pipe.cmds if s == "fetch-ins-reference-cells.py"]
    assert fetched == [q["id"] for q in SPEC["queries"] if q["matrix"] == code]
    assert any(s == "load-published-totals.py" for s, _ in pipe.cmds)
    assert pipe.state()["matrices"][code]["stages"]["published_totals"]["outcome"] == "ok"
