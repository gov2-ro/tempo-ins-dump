"""AQ-02B: the pinned cases replayed against a read-only copied generation (TEMPO_DATA_DIR).

Kept apart from test_aq02_runner.py because that module holds a synthetic world open (it repoints
the app's corpus paths) for its whole run. Skipped, not passed, without the copy or with another
generation; the other tests never depend on it.
"""
import copy
import importlib.util
import sys
from pathlib import Path

import pytest

from aq02_tasks import load_taskset

ROOT = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location("eval_ask_tasks", ROOT / "scripts" / "eval-ask-tasks.py")
R = importlib.util.module_from_spec(_spec)
sys.modules["eval_ask_tasks"] = R
_spec.loader.exec_module(R)

DOC = load_taskset()


@pytest.mark.corpus
def test_pinned_cases_pass_against_the_read_only_copied_generation():
    reason = R.copied_prerequisite(DOC["fixtures"]["copied-9b3e065d"])
    if reason:
        pytest.skip(reason)
    run = R.run_taskset(copy.deepcopy(DOC), ids=["X01", "X02", "X03", "X03B", "X07", "X08"], surfaces=("direct",))
    pinned = [r for r in run["results"] if r["fixture"] == "copied-9b3e065d"]
    assert len(pinned) == 12 and not [r for r in pinned if r["status"] not in ("pass", "known_failure")], \
        [(r["task_id"], r["variant"], r["failure_categories"]) for r in pinned if r["status"] not in ("pass", "known_failure")]
    assert {(r["task_id"], r["variant"]) for r in pinned if r["status"] == "known_failure"} <= {("X03B", "en")}
    assert all(r["generation"].startswith("9b3e065d") for r in pinned if r["status"] == "pass")
    x01 = next(r for r in pinned if r["task_id"] == "X01" and r["variant"] == "ro")
    assert x01["evidence"]["periods"] == ["2025"] and x01["evidence"]["unit"] == "înnoptări pe locuitor"
    # the explicit-year golden is a different year from "current" and is asserted separately
    assert next(r for r in pinned if r["task_id"] == "X03B" and r["variant"] == "ro")["evidence"]["periods"] == ["2025"]
    assert next(r for r in pinned if r["task_id"] == "X03" and r["variant"] == "ro")["evidence"]["periods"] == ["2026"]
    # the synthetic counterparts of the same tasks ran in the same call and are separate results
    assert {r["fixture"] for r in run["results"] if r["task_id"] == "X03"} == {"synthetic-v1", "copied-9b3e065d"}
