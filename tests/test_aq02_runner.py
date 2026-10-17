"""AQ-02B: the offline task runner (scripts/eval-ask-tasks.py).

One complete offline run is shared by the report tests; focused runs (a wrong answer, a deviating tool,
a leaking logger, an MCP server that calls a model) use a second synthetic world. Real tools, the real
Ask loop and the real MCP transport run in every case; only the provider is a script, so nothing here
says anything about a live model.
"""
import copy
import importlib.util
import json
import sys
from pathlib import Path

import pytest

from aq02_tasks import load_taskset, turns_of, validate_taskset
from app.services.tools import registry

ROOT = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location("eval_ask_tasks", ROOT / "scripts" / "eval-ask-tasks.py")
R = importlib.util.module_from_spec(_spec)
sys.modules["eval_ask_tasks"] = R
_spec.loader.exec_module(R)

DOC = load_taskset()
TASKS = {t["id"]: t for t in DOC["tasks"]}


def find(results, task_id, variant="ro", surface="direct", kind="positive", negative=None):
    return next(r for r in results if (r["task_id"], r["variant"], r["surface"], r["kind"], r["negative_id"])
                == (task_id, variant, surface, kind, negative))


@pytest.fixture(scope="module")
def full_run():
    """Every task, both languages, both surfaces, with the intentionally wrong answers."""
    return R.run_taskset(copy.deepcopy(DOC))


@pytest.fixture(scope="module")
def world():
    with R.World("synthetic") as w:
        yield w


# ------------------------------------------------------------------ the supported set

def test_every_supported_task_passes_and_known_limitations_are_the_only_blockers(full_run):
    results = full_run["results"]
    positives = [r for r in results if r["kind"] == "positive" and r["status"] != "skipped"]
    assert positives and not [r for r in positives if r["status"] == "fail"], \
        [(r["task_id"], r["variant"], r["surface"], r["failure_categories"]) for r in positives if r["status"] == "fail"]
    declared = {t["id"] for t in DOC["tasks"] if t.get("known_failure")}
    assert {r["task_id"] for r in positives if r["status"] == "known_failure"} <= declared
    summary = R.summarize(results)
    assert summary["failed"] == 0 and summary["negative_controls"]["mismatch"] == 0
    assert summary["verdict"] in ("pass", "blocked_by_known_limitations")
    assert all(r["tool_choice"] == "scripted" and r["live_model_quality"] == "not_measured" for r in positives)


def test_direct_and_mcp_surfaces_run_separately_in_both_languages(full_run):
    results = full_run["results"]
    for tid in ("T01", "T08", "X03"):
        got = {(r["variant"], r["surface"]) for r in results if r["task_id"] == tid and r["kind"] == "positive"}
        assert got == {("ro", "direct"), ("en", "direct"), ("ro", "mcp"), ("en", "mcp")}, tid
    assert {r["surface"] for r in results if r["task_id"] in ("T15", "T16", "T20")} == {"direct"}
    assert {r["surface"] for r in results if r["task_id"] in ("T20C", "X11")} == {"mcp"}
    mcp = find(full_run["results"], "T01", "en", "mcp")
    assert mcp["counts"]["provider_calls"] == 0 and mcp["counts"]["model_attempts"] is None   # no model behind MCP
    direct = find(full_run["results"], "T01", "en", "direct")
    assert direct["counts"]["model_attempts"] == 3 and direct["counts"]["dispatches"] == 2
    assert direct["verification"]["status"] == "verified" and mcp["outcome"]["final_tool_status"] == ["ok", None]


def test_the_same_scripted_calls_give_the_same_values_on_both_surfaces(full_run):
    for tid in ("T01", "T08", "X03", "X08"):
        for lang in ("ro", "en"):
            d, m = find(full_run["results"], tid, lang, "direct"), find(full_run["results"], tid, lang, "mcp")
            assert d["evidence"] == m["evidence"], (tid, lang)


def test_runs_are_repeatable(world):
    first = R.run_task(world, TASKS["T08"], "ro", "direct", canaries=[])
    second = R.run_task(world, TASKS["T08"], "ro", "direct", canaries=[])
    timing = ("latency_ms", "_obs")
    assert {k: v for k, v in first.items() if k not in timing} == {k: v for k, v in second.items() if k not in timing}
    assert first["status"] == "pass" and first["counts"]["dispatches"] == 1


# ------------------------------------------------------------------ wrong answers fail for the right reason

def test_every_wrong_answer_is_flagged_for_the_declared_reason(full_run):
    controls = [r for r in full_run["results"] if r["kind"] == "negative_control"]
    assert len(controls) >= 30
    for r in controls:
        assert r["control"] in ("detected", "known_limitation", "resolved"), (r["task_id"], r["negative_id"], r["control_problems"])
        failed = {c["id"] for c in r["checks"] if not c["passed"]}
        for need in r["control_declared"]["fails"]:
            assert any(f == need or f.startswith(need + ".") for f in failed), (r["task_id"], r["negative_id"], need, failed)
        assert r["control"] == "resolved" or r["outcome"]["app_verdict"] == r["control_declared"]["app"]
        assert set(r["hard_failures"]) == (set(r["control_declared"]["hard"]) if r["control"] == "known_limitation" else set())


def test_a_wrong_unit_is_withheld_and_a_reversed_sign_is_an_unsafe_accepted_claim_today(full_run):
    unit = find(full_run["results"], "X10", "ro", "direct", "negative_control", "wrong_unit")
    assert unit["control"] == "detected" and unit["outcome"]["app_verdict"] == "withheld"
    assert unit["verification"]["status"] == "claim_mismatch" and not unit["hard_failures"]
    sign = find(full_run["results"], "X10B", "en", "direct", "negative_control", "increase_for_a_decrease")
    assert sign["control"] in ("known_limitation", "resolved")                     # AQ-03 may fix it: either is recorded
    if sign["control"] == "known_limitation":
        assert sign["hard_failures"] == ["numerical_deviation", "unsafe_claim_accepted"] and sign["status"] == "known_failure"
        assert sign["known_limitation"]["package"] == "AQ-03"


def test_a_wrong_figure_in_the_answer_fails_without_a_hard_failure_when_the_app_flags_it(world):
    r = R.run_task(world, TASKS["T01"], "ro", "direct", canaries=[],
                   answer_override="Populația rezidentă a județului Cluj era de 1100 persoane în 2021 (POPC).")
    assert r["status"] == "fail" and r["outcome"]["app_verdict"] == "flagged"
    assert {"number_not_stated", "unexpected_number", "outcome_mismatch", "verification_mismatch"} <= set(r["failure_categories"])
    assert not r["hard_failures"]
    failed = {c["id"]: c["detail"] for c in r["checks"] if not c["passed"]}
    assert "1010" in failed["stated.cluj_2021"] and "1100" in failed["answer_numbers"]


def test_a_tool_value_that_deviates_from_the_hand_checked_number_is_a_hard_failure(world, monkeypatch):
    from app.services import data_query
    real = data_query.run_query

    def off_by_one(*a, **kw):
        out = real(*a, **kw)
        out["rows"] = [r[:-1] + [r[-1] + 1] if isinstance(r[-1], float) else r for r in out["rows"]]
        return out
    monkeypatch.setattr(data_query, "run_query", off_by_one)
    r = R.run_task(world, TASKS["T01"], "ro", "direct", canaries=[], answer_override="Cluj: 1011 persoane în 2021 (POPC).")
    assert "numerical_deviation" in r["hard_failures"]
    assert next(c for c in r["checks"] if c["id"] == "number.cluj_2021")["detail"].startswith("tool gave 1011")
    summary = R.summarize([r] + [dict(r, status="pass", hard_failures=[], failure_categories=[]) for _ in range(99)])
    assert summary["numerical_deviations"] == 1 and summary["verdict"] == "fail"       # not averaged away by 99 passes
    assert summary["pass_rate_of_executed"] == 0.99


def test_an_unsafe_accepted_claim_is_hard_even_among_many_passes(world):
    r = R.run_task(world, TASKS["X10B"], "en", "direct", canaries=[],
                   answer_override="B changed by -50 persons between 1992 and 2002, from 150 to 200 (COUNTX).")
    if "unsafe_claim_accepted" not in r["hard_failures"]:
        pytest.skip("the app now contains an endpoint swap (AQ-03): nothing left to count as accepted")
    assert r["status"] == "fail" and r["outcome"]["app_verdict"] == "accepted"
    summary = R.summarize([r] + [dict(r, status="pass", hard_failures=[], failure_categories=[]) for _ in range(199)])
    assert summary["unsafe_accepted_claims"] == 1 and summary["verdict"] == "fail"
    assert summary["hard_failures"][0]["known"] is False


def test_a_leaked_credential_is_a_hard_failure_in_any_surface_of_the_response(world, monkeypatch):
    ok = R.run_task(world, TASKS["T19"], "ro", "direct", canaries=[])
    assert ok["status"] == "pass" and ok["outcome"]["raised"]["code"] == "provider_auth"
    from app.services import ask_guard
    monkeypatch.setattr(ask_guard, "active_secrets", lambda: ())            # the exact-key scrub stops working
    leaked = R.run_task(world, TASKS["T19"], "ro", "direct", canaries=[])
    assert "secret_leak" in leaked["hard_failures"] and leaked["status"] == "fail"
    assert R.summarize([leaked])["secret_leaks"] == 1


def test_a_model_call_from_the_mcp_surface_is_reported(world, monkeypatch):
    from app.services import agent
    real = registry.call_tool

    def calls_a_model(name, arguments, **kw):
        agent.complete_with_tools([], [])
        return real(name, arguments, **kw)
    monkeypatch.setattr(registry, "call_tool", calls_a_model)
    r = R.run_task(world, TASKS["T01"], "en", "mcp", canaries=[])
    assert "model_call_on_mcp" in r["failure_categories"] and r["counts"]["provider_calls"] >= 1


# ------------------------------------------------------------------ failures, refusals, cancellation

def test_failed_providers_repeated_refusals_and_cancellations_are_complete_results(full_run):
    results = full_run["results"]
    for tid, surface in (("T14B", "direct"), ("T14C", "direct"), ("T15", "direct"), ("T19", "direct"), ("T20", "direct"),
                         ("T20B", "direct"), ("T20C", "mcp"), ("T17", "direct")):
        r = find(results, tid, "en", surface)
        assert r["status"] == "pass", (tid, r["failure_categories"])
        assert any(c["id"] == "invariant.slot_released" and c["passed"] for c in r["checks"]) or tid in ("T19", "T17"), tid
    t15 = find(results, "T15", "ro")
    assert t15["counts"]["dispatches"] == 3 and t15["counts"]["executions"] == 1 and t15["counts"]["cache_hits"] == 2
    assert t15["outcome"]["outcome"] == "refused" and t15["outcome"]["reason"] == "overlapping_levels"
    t14b = find(results, "T14B", "ro")
    assert (t14b["outcome"]["outcome"], t14b["outcome"]["reason"]) == ("failed", "output_limit") and t14b["counts"]["retries"] == 1
    t20 = find(results, "T20", "ro")                       # the cancelled turn did not cancel the next request
    assert t20["turns"] == 2 and t20["outcome"]["outcome"] == "answered"
    assert {c["turn"] for c in t20["checks"]} == {0, 1} and all(c["passed"] for c in t20["checks"])
    t20c = find(results, "T20C", "ro", "mcp")
    assert any(c["id"] == "call[1].reason" and c["passed"] for c in t20c["checks"])
    t17 = find(results, "T17", "en")                       # the stale follow-up never reached a provider
    assert any(c["id"] == "raises" and c["passed"] for c in t17["checks"]) and t17["counts"]["provider_calls"] == 0


def test_an_oversized_result_stays_bounded_on_both_surfaces(full_run):
    d, m = find(full_run["results"], "T13", "ro"), find(full_run["results"], "T13", "ro", "mcp")
    assert d["status"] == m["status"] == "pass"
    assert any(c["id"] == "limit.min_compacted_results" and c["passed"] for c in d["checks"])
    assert any(c["id"] == "table.links" and c["passed"] for c in d["checks"])
    assert any(c["id"] == "invariant.context_pairing" and c["passed"] for c in d["checks"])
    assert m["bytes"]["wire_max"] <= 72 * 1024


# ------------------------------------------------------------------ report

def test_the_report_carries_the_required_fields_and_exact_versions(full_run, tmp_path):
    path = R.write_report(full_run, tmp_path)
    body = json.loads(path.read_text())
    assert body["mode"] == "offline_replay" and body["tool_choice"] == "scripted" and body["live_model_quality"] == "not_measured"
    v = body["versions"]
    assert v["task_set"] == DOC["version"] and v["tool_contract"] == "tempo-tools/2" and len(v["system_prompt_sha256"]) == 16
    assert {"head", "dirty", "dirty_hash"} <= set(body["code"])                  # None when git is unavailable
    assert body["code"]["head"] is None or len(body["code"]["head"]) == 40
    assert body["config"]["ask"]["ASK_MAX_ITERATIONS"] == 8 and body["config"]["ask"]["ASK_MAX_TOOL_CALLS"] == 12
    gate = body["config"]["mcp_public_gate"]                  # the default public gate, as configured
    assert gate["max_concurrent"] == 1 and gate["max_scan_rows"] == 1_000_000 and gate["max_seconds"] == 10.0
    r = next(x for x in body["results"] if x["task_id"] == "X03" and x["variant"] == "en" and x["surface"] == "direct" and x["kind"] == "positive")
    for key in ("outcome", "evidence", "verification", "checks", "generation", "counts", "bytes", "latency_ms", "tokens", "cost", "status"):
        assert key in r, key
    assert r["generation"] == "gen-at01-fixture" and r["evidence"]["unit"] == "Numar persoane"
    assert r["evidence"]["keys"] == ["REF_AREA", "REF_AREA_2"] and r["evidence"]["periods"] == ["2025"]
    assert {c["kind"] for c in r["checks"]} >= {"outcome", "envelope", "numerical", "qualification", "forbidden", "evidence", "budget"}
    assert r["counts"] == {"model_attempts": 3, "retries": 0, "dispatches": 2, "executions": 2, "cache_hits": 0, "provider_calls": 3}
    assert r["bytes"]["tool_results"] > 0 and r["latency_ms"]["total"] is not None and r["latency_ms"]["tool_calls"]
    assert body["human_review"] and all("variants" in h for h in body["human_review"])
    assert body["content_retention"] == "none"


def test_missing_usage_and_pricing_are_unknown_and_reported_usage_is_summed(full_run, world):
    assert all(r["tokens"]["known"] is False and r["tokens"]["usage"] is None for r in full_run["results"]
               if r["status"] != "skipped" and r["surface"] == "direct")
    assert all(r["cost"]["usd"] is None and "unknown" in r["cost"]["status"] for r in full_run["results"] if r["status"] != "skipped")
    task = copy.deepcopy(TASKS["T01"])
    task["usage"] = {"input_tokens": 100, "output_tokens": 20, "reasoning_tokens": None, "cached_tokens": 10}
    r = R.run_task(world, task, "ro", "direct", canaries=[])
    assert r["tokens"]["known"] is True and r["tokens"]["usage"] == {"input_tokens": 300, "output_tokens": 60,
                                                                       "reasoning_tokens": None, "cached_tokens": 30}
    assert r["cost"]["usd"] is None                                    # usage is not a price


def test_reports_hold_metadata_not_prompts_answers_or_traces(full_run, tmp_path):
    path = R.write_report(full_run, tmp_path)
    text = path.read_text()
    forbidden_text = []
    for t in DOC["tasks"]:
        for turn in turns_of(t):
            forbidden_text += [turn["prompt"]["ro"], turn["prompt"]["en"]] + list((turn.get("answer") or {}).values())
        forbidden_text += [v for n in t.get("negatives", []) for v in n["answer"].values()]
    assert not [x for x in forbidden_text if len(x) > 20 and x in text]
    assert not list(tmp_path.glob("ask-task-contents-*"))
    for secret in [s for t in DOC["tasks"] for s in t.get("secrets", [])] + DOC["canaries"]:
        assert secret not in text


def test_content_retention_needs_an_explicit_option_and_consent_and_is_redacted(full_run, tmp_path, capsys):
    assert R.main(["--retain-content", "--report-dir", str(tmp_path)]) == 2
    assert "consent" in capsys.readouterr().err and not list(tmp_path.iterdir())
    secrets = [s for t in DOC["tasks"] for s in t.get("secrets", [])]
    leak = dict(find(full_run["results"], "T01"))
    leak["_obs"] = dict(leak["_obs"], answer=f"cheia mea este {secrets[0]} și Cluj are 1010")
    R.write_report({"meta": full_run["meta"], "results": [leak]}, tmp_path, retain_content=True, canaries=secrets)
    contents = next(tmp_path.glob("ask-task-contents-*.jsonl")).read_text()
    assert "Cluj are 1010" in contents and secrets[0] not in contents and "[REDACTED]" in contents
    assert json.loads(next(tmp_path.glob("ask-task-report-*.json")).read_text())["content_retention"] == "consented"


def test_a_credential_that_reaches_the_report_is_removed_and_fails_the_run(full_run, tmp_path):
    victim = dict(find(full_run["results"], "T01"), checks=[dict(find(full_run["results"], "T01")["checks"][0],
                  detail="echo q7Zp-LmNoP.9rStUvWx_1234AbCdEf")])
    path = R.write_report({"meta": full_run["meta"], "results": [victim]}, tmp_path, canaries=["q7Zp-LmNoP.9rStUvWx_1234AbCdEf"])
    text = path.read_text()
    assert "q7Zp" not in text
    summary = json.loads(text)["summary"]
    assert summary["secret_leaks"] >= 1 and summary["verdict"] == "fail"


def test_reports_are_never_written_inside_the_repository_and_live_mode_does_not_exist(tmp_path, capsys):
    target = ROOT / "aq02-report-must-not-exist"
    assert R.main(["--validate-only", "--report-dir", str(target)]) == 2 and not target.exists()
    assert "inside the repository" in capsys.readouterr().err
    with pytest.raises(SystemExit):
        R.main(["--mode", "live"])
    assert R.default_report_dir().resolve() != ROOT and ROOT not in R.default_report_dir().resolve().parents


# ------------------------------------------------------------------ aggregation, skips, known failures

def test_denominators_exclude_skips_and_controls_and_refusals_are_not_unsafe_answers(full_run, monkeypatch):
    monkeypatch.setattr(R, "copied_prerequisite", lambda fixture: "prerequisite_missing: copied generation not provided")
    run = R.run_taskset(copy.deepcopy(DOC), ids=["X01", "X03", "X04", "T05"])
    summary = R.summarize(run["results"])
    skipped = [r for r in run["results"] if r["status"] == "skipped"]
    assert len(skipped) == 4 and {r["task_id"] for r in skipped} == {"X01", "X03"} and all(r["surface"] == "direct" for r in skipped)
    assert summary["skipped"] == 4 and summary["skip_reasons"] == ["prerequisite_missing: copied generation not provided"]
    positives = [r for r in run["results"] if r["kind"] == "positive" and r["status"] != "skipped"]
    assert summary["executed"] == len(positives) == summary["passed"] + summary["failed"] + summary["known_failures"]
    assert summary["pass_rate_of_executed"] == round(summary["passed"] / summary["executed"], 4)
    assert summary["legitimate_refusals_or_clarifications"] >= 2                                    # T05 and X04 refuse
    assert not [h for h in summary["hard_failures"] if h["kind"] == "positive"]                      # a refusal is not an unsafe answer
    assert all(h["known"] for h in summary["hard_failures"])                                        # only documented control limitations
    assert all(r["skipped"].startswith("prerequisite_missing") and r["fixture"] == "copied-9b3e065d" for r in skipped)
    # only the pinned cases skipped: their synthetic counterparts and the other tasks ran
    assert {r["task_id"] for r in positives} == {"X01", "X03", "X04", "T05"}


def test_a_copied_generation_other_than_the_one_checked_is_a_skip_not_a_pass(tmp_path, monkeypatch):
    from app import config
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    (corpus / "metadata.duckdb").write_text("")
    (corpus / "generation-manifest.json").write_text(json.dumps({"generation_id": "deadbeef" + "0" * 56}))
    monkeypatch.setattr(config, "CORPUS_DIR", corpus)
    fixture = DOC["fixtures"]["copied-9b3e065d"]
    assert R.copied_prerequisite(fixture).startswith("prerequisite_mismatch")
    (corpus / "generation-manifest.json").write_text(json.dumps({"generation_id": "9b3e065d" + "0" * 56}))
    assert R.copied_prerequisite(fixture) is None
    (corpus / "metadata.duckdb").unlink()
    assert R.copied_prerequisite(fixture).startswith("prerequisite_missing")


def test_a_documented_known_failure_is_listed_apart_and_a_resolved_one_is_noted(world):
    plain = copy.deepcopy(TASKS["T06"])
    plain.pop("known_failure")
    failing = R.run_task(world, plain, "ro", "direct", canaries=[])
    assert failing["status"] == "fail" and failing["failure_categories"] == ["claim_not_bound"]
    declared = copy.deepcopy(TASKS["T06"])
    res = R.run_task(world, declared, "ro", "direct", canaries=[])
    R.apply_known_failure(declared, res)
    assert res["status"] == "known_failure" and res["known_failure"]["package"] == "AQ-03"
    stale = copy.deepcopy(TASKS["T01"])
    stale["known_failure"] = {"package": "AQ-03", "categories": ["claim_not_bound"], "note": "fixed long ago"}
    ok = R.run_task(world, stale, "ro", "direct", canaries=[])
    R.apply_known_failure(stale, ok)
    assert ok["status"] == "pass" and ok["known_failure_resolved"]["package"] == "AQ-03"
    summary = R.summarize([res, ok])
    assert summary["known_failures"] == 1 and summary["known_failures_resolved"] == ["T01"]
    assert summary["verdict"] == "blocked_by_known_limitations"


def test_a_crashing_task_becomes_a_failed_result_not_a_lost_run(world, monkeypatch):
    monkeypatch.setattr(R, "run_direct_turn", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    res = R.guarded(R.run_task, world, TASKS["T01"], "ro", "direct", canaries=[], fixture="synthetic-v1")
    assert res["status"] == "fail" and res["failure_categories"] == ["runner_error"] and res["error"]["type"] == "RuntimeError"


# ------------------------------------------------------------------ the task file validator

def broken(mutate):
    doc = copy.deepcopy(DOC)
    mutate(doc)
    return validate_taskset(doc, registry.tool_names())


def test_the_validator_rejects_broken_task_files():
    assert any("duplicate id" in e for e in broken(lambda d: d["tasks"].append(copy.deepcopy(d["tasks"][0]))))
    assert any("prompt needs ro and en" in e for e in broken(lambda d: d["tasks"][0].update(prompt={"ro": "x"})))
    assert any("unknown fixture" in e for e in broken(lambda d: d["tasks"][0].update(fixture="nope")))
    assert any("unknown tool" in e for e in broken(lambda d: d["tasks"][0]["steps"].append({"tool": "drop_table"})))
    assert any("not in fixture" in e for e in broken(lambda d: d["tasks"][0]["steps"].append({"tool": "query_data", "arguments": {"dataset": "NOPE"}})))
    assert any("derivation" in e for e in broken(lambda d: d["tasks"][0]["expect"]["numbers"][0].update(derivation="1011")))
    assert any("not evaluable" in e for e in broken(lambda d: d["tasks"][0]["expect"]["numbers"][0].update(derivation="open('x')")))
    assert any("unknown expect keys" in e for e in broken(lambda d: d["tasks"][0]["expect"].update(vibes=True)))
    assert any("known_limitation" in e for e in broken(lambda d: d["tasks"][6]["negatives"].append(
        {"id": "x", "answer": {"ro": "a", "en": "b"}, "detect": {"app": "accepted", "fails": ["forbidden.x"]}})))
    assert any("pinned.fixture" in e for e in broken(lambda d: d["tasks"][0].update(pinned={"fixture": "synthetic-v1"})))
    assert any("answer needs ro and en" in e for e in broken(lambda d: d["tasks"][0].update(answer={"ro": "x"})))
    assert any(e.startswith("schema") for e in broken(lambda d: d.update(schema="ask-tasks/0")))
