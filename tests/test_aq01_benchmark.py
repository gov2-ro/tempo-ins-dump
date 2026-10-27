"""AQ-01 / 01A: the capacity harness (scripts/benchmark-mcp.py): report schema, grouping, units, cleanup,
timeout accounting, and two end-to-end acceptance runs through a real child process and the real MCP client."""
import http.server
import importlib.util
import json
import os
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path

import duckdb
import pytest

from at01_fixtures import add_dataset, add_search_columns, make_env
from test_at01_changes import area_dim, time_dim, unit_dim
from test_at05_ranking import build as build_cities

ROOT = Path(__file__).resolve().parent.parent
PORTS = "8111-8115"                                 # this package's assigned range for child servers


def load_harness():
    spec = importlib.util.spec_from_file_location("benchmark_mcp", ROOT / "scripts" / "benchmark-mcp.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["benchmark_mcp"] = mod              # dataclasses resolve annotations through sys.modules
    spec.loader.exec_module(mod)
    return mod


B = load_harness()
FILL_YEARS, FILL_ENTITIES = 450, 2300               # the tools accept at most 500 period labels
BIG_ROWS = 2 * 231 + FILL_YEARS * FILL_ENTITIES      # 1,035,462: over the default scan limit of 1,000,000
CITY_NAMES = [f"{1000 + i} ORAS CITY{i:03}" for i in range(230)] + ["9999 COMMUNE"]


def build_fixture(root: Path) -> Path:
    """A data dir with CITYX (230 cities, the winner after row 200, a larger commune that must be excluded)
    and its GOS102A catalogue, and CITYBIG: the same 2024/2025 rows plus older filler
    observations, so its Parquet footer (1,035,462 rows) is over the default scan limit."""
    def build(corpus):
        build_cities(corpus)
        filler = [f"FILLER {i:04d}" for i in range(FILL_ENTITIES)]
        years = [str(1000 + j) for j in range(FILL_YEARS)] + ["2024", "2025"]
        rows = [("County", c, y, "Numar persoane", float(i + 100 if i < 230 else 999999))
                for y in ("2024", "2025") for i, c in enumerate(CITY_NAMES)]
        add_dataset(corpus, "CITYBIG", [area_dim(["County"]), area_dim(CITY_NAMES + filler, "locality", "REF_AREA_2"),
                                        time_dim(years), unit_dim("Numar persoane")], rows, name="Cities and history")
        path = corpus / "parquet" / "CITYBIG.parquet"
        con = duckdb.connect()
        con.execute(f"CREATE TABLE base AS SELECT * FROM read_parquet('{path}')")
        con.execute(f"COPY (SELECT * FROM base UNION ALL SELECT 'County', 'FILLER ' || lpad(i::VARCHAR, 4, '0'), "
                    f"(1000 + j)::VARCHAR, 'Numar persoane', 1.0 FROM range({FILL_ENTITIES}) a(i), range({FILL_YEARS}) b(j)) "
                    f"TO '{path}' (FORMAT PARQUET)")
        con.close()
        add_search_columns(corpus)
    with pytest.MonkeyPatch.context() as mp:
        make_env(root, mp, build=build)
    return root


@pytest.fixture(scope="module")
def data_dir(tmp_path_factory):
    return build_fixture(tmp_path_factory.mktemp("aq01a-data"))


def harness(args: list[str], timeout: float = 300):
    """The command line, as an operator runs it. Provider keys are present in this environment on purpose:
    the child must not receive them."""
    env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1", "ANTHROPIC_API_KEY": "sk-test-must-not-reach-the-child",
           "OPENAI_API_KEY": "sk-test-must-not-reach-the-child", "TEMPO_ASK_ENABLED": "true"}
    return subprocess.run([sys.executable, str(ROOT / "scripts" / "benchmark-mcp.py"), "run", *args],
                          capture_output=True, text=True, timeout=timeout, env=env, cwd=str(ROOT))


def report_of(out: Path) -> dict:
    return json.loads((out / "report.json").read_text())


def case(report: dict, name: str, state: str) -> dict:
    return next(c for c in report["cases"] if c["case"] == name and c["state"] == state)


# ---------------------------------------------------------------- units: statistics and accounting

def test_percentiles_are_nearest_rank_observed_values_and_empty_is_null():
    xs = [0.1 * i for i in range(1, 21)]                                  # 0.1 .. 2.0
    s = B.latency_summary(xs)
    assert (s["n"], s["min"], s["p50"], s["p95"], s["max"]) == (20, 0.1, 1.0, 1.9, 2.0)
    assert s["method"] == "nearest_rank" and s["mean"] == pytest.approx(1.05)
    assert B.latency_summary([]) is None and B.latency_summary([None, float("nan")]) is None   # never zeros
    assert B.latency_summary([7.0])["p95"] == 7.0                                                 # one sample: that sample


def test_states_are_never_combined_in_a_percentile():
    rec = B.Recorder()
    for _ in range(20):
        rec.add("rank_exact_year", "cache", wall_s=0.01, outcome="served", status="ok", cached=True)
    for i in range(20):
        rec.add("rank_exact_year", "miss_warm", wall_s=2.0 + i / 100, outcome="served", status="ok", cached=False)
    rec.add("rank_exact_year", "cold", wall_s=30.0, outcome="served", status="ok")
    rows = {(r["case"], r["state"]): r for r in rec.summary()}
    assert set(rows) == {("rank_exact_year", "cache"), ("rank_exact_year", "miss_warm"), ("rank_exact_year", "cold")}
    assert rows[("rank_exact_year", "cache")]["latency_s"]["p95"] == 0.01 and rows[("rank_exact_year", "cache")]["n"] == 20
    assert rows[("rank_exact_year", "miss_warm")]["latency_s"]["p50"] >= 2.0
    assert rows[("rank_exact_year", "cold")]["latency_s"]["max"] == 30.0 and rows[("rank_exact_year", "cold")]["n"] == 1
    assert rows[("rank_exact_year", "cache")]["cache_hits"] == 20 and rows[("rank_exact_year", "miss_warm")]["cache_hits"] == 0
    with pytest.raises(ValueError):
        rec.add("x", "warm", wall_s=1, outcome="served")                  # no catch-all 'warm' bucket


def test_sufficiency_follows_the_spec_counts_and_failures_stay_out_of_the_latency():
    rec = B.Recorder()
    for i in range(4):
        rec.add("cold_chain.rank_entities", "cold", wall_s=1.0 + i, outcome="served", status="ok")
    rec.add("cold_chain.rank_entities", "cold", wall_s=30.0, outcome="timeout", error="no answer within 30s")
    rec.add("cold_chain.rank_entities", "cold", wall_s=0.2, outcome="refused", status="unavailable", reason="busy")
    for _ in range(19):
        rec.add("rank_year_miss", "miss_warm", wall_s=1.0, outcome="served", status="ok")
    rec.add("rank_latest_year", "miss_warm", wall_s=1.0, outcome="served", status="ok")
    rows = {r["case"]: r for r in rec.summary()}
    cold = rows["cold_chain.rank_entities"]
    assert (cold["n"], cold["required_n"], cold["sufficient"]) == (6, 5, True)
    assert cold["outcomes"] == {"served": 4, "timeout": 1, "refused": 1}
    assert cold["latency_s"]["n"] == 4 and cold["latency_s"]["max"] == 4.0          # the 30 s timeout is not a latency
    assert cold["latency_by_outcome"]["timeout"]["max"] == 30.0 and cold["latency_by_outcome"]["refused"]["n"] == 1
    assert (rows["rank_year_miss"]["required_n"], rows["rank_year_miss"]["sufficient"]) == (20, False)   # 19 < 20
    assert (rows["rank_latest_year"]["required_n"], rows["rank_latest_year"]["sufficient"]) == (1, True)


def test_a_group_with_no_served_answer_has_null_latency_not_zero():
    rec = B.Recorder()
    for _ in range(3):
        rec.add("cold_first_rank.rank_entities", "cold", wall_s=0.05, outcome="refused", status="unavailable",
                reason="query_budget", dispatched=False)
    rec.add("probe", "observed", wall_s=None, outcome="transport_error", error="boom")
    rows = {r["case"]: r for r in rec.summary()}
    r = rows["cold_first_rank.rank_entities"]
    assert r["latency_s"] is None and r["result_bytes"] is None and r["wire_bytes"] is None   # nothing measured
    assert r["results"] == {"unavailable/query_budget": 3} and r["dispatched"] == 0 and r["cache_hits"] is None
    assert rows["probe"]["latency_s"] is None and rows["probe"]["outcomes"] == {"transport_error": 1}


@pytest.mark.parametrize("value, source, system, expected", [
    (1_000_000, "ru_maxrss", "Darwin", 1_000_000),               # bytes on macOS
    (1_000_000, "ru_maxrss", "Linux", 1_024_000_000),            # KiB on Linux
    (2048, "ps_kib", "Darwin", 2_097_152), (2048, "ps_kib", "Linux", 2_097_152),
    (512, "proc_kb", "Linux", 524_288), (None, "ps_kib", "Linux", None), (None, "ru_maxrss", "Darwin", None)])
def test_rss_units_are_normalised_to_bytes(value, source, system, expected):
    assert B.rss_to_bytes(value, source, system) == expected
    with pytest.raises(ValueError):
        B.rss_to_bytes(1, "pages")


def test_process_tree_rss_sums_descendants_only_and_a_missing_root_is_null():
    ps = "  10     1  1000\n  11    10   500\n  12    11   250\n  99     1  9999\n junk line\n"
    table = B.parse_ps_table(ps)
    assert table == [(10, 1, 1000), (11, 10, 500), (12, 11, 250), (99, 1, 9999)]
    assert B.tree_rss_bytes(table, 10) == (1000 + 500 + 250) * 1024
    assert B.tree_rss_bytes(table, 12) == 250 * 1024 and B.tree_rss_bytes(table, 4242) is None


def test_cpu_and_memory_parsers():
    assert B.parse_ps_time("0:01.23") == pytest.approx(1.23) and B.parse_ps_time("01:02:03") == 3723
    assert B.parse_ps_time("2-00:00:01") == 172801 and B.parse_ps_time("garbage") is None
    stat = "123 (my (odd) app) S 1 123 123 0 -1 4194560 100 0 0 0 250 50 0 0 20 0 1 0 100 1000 100 18446744073709551615"
    assert B.parse_proc_stat_cpu(stat, 100) == pytest.approx(3.0) and B.parse_proc_stat_cpu("x", 100) is None
    assert B.parse_docker_size("123.4MiB") == int(123.4 * 1024 ** 2) and B.parse_docker_size("1GB") == 10 ** 9
    assert B.parse_docker_size("512kB") == 512_000 and B.parse_docker_size("n/a") is None
    assert B.parse_memory_flag("512m") == 512 * 1024 ** 2 and B.parse_memory_flag("1g") == 1024 ** 3
    assert B.parse_memory_flag("lots") is None


def test_diff_json_ignores_only_the_named_keys_and_reports_paths():
    a = {"data": {"rows": [1, 2, 3], "unit": "x"}, "request_id": "aaa", "n": 1}
    assert B.diff_json(a, {"data": {"rows": [1, 2, 3], "unit": "x"}, "request_id": "bbb", "n": 1}) == []
    d = B.diff_json(a, {"data": {"rows": [1, 9, 3, 4], "unit": "y"}, "request_id": "bbb", "n": 1})
    assert any("rows: length 3 != 4" in x for x in d) and any("rows[1]" in x for x in d) and any(".unit" in x for x in d)
    assert B.diff_json({"a": 1}, {"b": 1}) == ["$.a: present in only one side", "$.b: present in only one side"]


@pytest.mark.parametrize("env, expected", [
    ({"status": "ok"}, ("served", "ok", None, None)),
    ({"status": "partial", "reason": "unverified_total"}, ("served", "partial", "unverified_total", None)),
    ({"status": "unavailable", "reason": "query_budget"}, ("refused", "unavailable", "query_budget", None)),
    ({"status": "unavailable", "reason": "busy", "message": "Another analysis is running; retry shortly."},
     ("refused", "unavailable", "busy", "slot")),
    ({"status": "unavailable", "reason": "busy", "message": "The server is handling many requests; retry shortly."},
     ("refused", "unavailable", "busy", "rate_limit")),
    ({"status": "error", "reason": "invalid_input"}, ("tool_error", "error", "invalid_input", None)),
    ({"nope": 1}, ("protocol_error", None, None, None)), (None, ("protocol_error", None, None, None))])
def test_outcomes_separate_success_refusal_and_failure(env, expected):
    assert B.classify(env) == expected


def test_settings_validation_and_the_child_environment(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-secret")
    monkeypatch.setenv("TEMPO_LLM_PROVIDER", "anthropic")
    declared, overrides = B.profile_env({"max_scan_rows": "5000000", "max_seconds": None}, ["TEMPO_DB_MEMORY=300MB"], False)
    assert declared == {"TEMPO_MCP_MAX_SCAN_ROWS": "5000000", "TEMPO_DB_MEMORY": "300MB"}
    assert overrides == B.HARNESS_OVERRIDES                                # rate limits lifted, disclosed
    assert B.profile_env({}, [], True) == ({}, {})
    for bad in (["TEMPO_ASK_ENABLED=true"], ["TEMPO_LLM_MODEL=x"], ["ANTHROPIC_API_KEY=x"], ["NOT_TEMPO=1"], ["TEMPO_X"]):
        with pytest.raises(B.HarnessError):
            B.profile_env({}, bad, False)
    for bad in ("0", "-5", "nan", "inf", "lots"):                          # zero is never 'unlimited'
        with pytest.raises(B.HarnessError):
            B.profile_env({"max_scan_rows": bad}, [], False)
    env = B.build_child_env(os.environ, data_dir="/data", port=8111, declared=declared, overrides=overrides)
    assert env["TEMPO_DATA_DIR"] == "/data" and env["TEMPO_MCP_MAX_SCAN_ROWS"] == "5000000"
    assert env["TEMPO_ASK_ENABLED"] == "false" and env["TEMPO_PUBLIC_BASE_URL"] == "http://127.0.0.1:8111"
    assert "ANTHROPIC_API_KEY" not in env and "TEMPO_LLM_PROVIDER" not in env and not any(B.is_secret_name(k) for k in env)
    with pytest.raises(B.HarnessError):
        B.build_child_env({}, data_dir="/d", port=1, declared={"OPENAI_API_KEY": "x"}, overrides={})
    assert B.parse_ports("8111-8115") == [8111, 8112, 8113, 8114, 8115] and B.parse_ports(None) is None
    with pytest.raises(B.HarnessError):
        B.parse_ports("80-90")


def test_log_events_are_parsed_and_a_partial_line_waits(tmp_path):
    text = ('noise\nMCP_METRICS {"tool": "rank_entities", "status": "ok", "cached": true}\n'
            'BENCH_DISPATCH {"tool":"rank_entities"}\nBENCH_PROVIDER_CALL {"fn":"_anthropic"}\nMCP_METRICS {bad json}\n')
    ev = B.parse_log_events(text)
    assert [e["kind"] for e in ev] == ["MCP_METRICS", "BENCH_DISPATCH", "BENCH_PROVIDER_CALL"] and ev[0]["cached"] is True
    log = tmp_path / "c.log"
    tail = B.LogTail(log)
    assert tail.take() == []                                              # no file yet
    log.write_bytes(b'BENCH_DISPATCH {"tool":"a"}\nBENCH_DISPATCH {"tool":"b"')
    assert [e["tool"] for e in tail.take()] == ["a"]                       # the half line is left alone
    log.write_bytes(log.read_bytes() + b'}\n')
    assert [e["tool"] for e in tail.take()] == ["b"] and tail.take() == []
    s = B.summarize_events(tail.all + ev)
    assert s["dispatches"] == {"a": 1, "b": 1, "rank_entities": 1} and s["provider_calls"] == 1 and s["cache_hits"] == 1


def test_wire_bytes_are_unknown_not_zero_when_a_response_has_no_length():
    w = B.WireCounter()
    m = w.mark()
    w.add("120")
    w.add("80")
    assert w.since(m) == 200
    m = w.mark()
    w.add(None)
    assert w.since(m) is None


def test_scan_admission_check_requires_a_refusal_without_dispatch_over_the_cap():
    refused = {"outcome": "refused", "status": "unavailable", "reason": "query_budget", "dispatched": False}
    assert B.scan_admission_check(3_898_870, 1_000_000, refused)["status"] == "pass"
    assert B.scan_admission_check(3_898_870, 1_000_000, {**refused, "dispatched": True})["status"] == "fail"
    assert B.scan_admission_check(3_898_870, 1_000_000, {**refused, "dispatched": None})["status"] == "not_run"
    served = {"outcome": "served", "status": "ok", "reason": None, "dispatched": True}
    assert B.scan_admission_check(3_898_870, 1_000_000, served)["status"] == "fail"       # admitted over the cap
    assert B.scan_admission_check(3_898_870, 5_000_000, served)["status"] == "pass"       # candidate cap
    assert B.scan_admission_check(3_898_870, 5_000_000, refused)["status"] == "fail"
    assert B.scan_admission_check(None, 1_000_000, refused)["status"] == "not_run"
    assert B.scan_admission_check(10, None, refused)["status"] == "not_run"


def test_k_invariance_demands_one_eligible_set_for_every_top_k():
    def view(k, eligible=230, excluded=0):
        vals = [329.0 - i for i in range(min(k, eligible))]
        return {"year": "2025", "unit": "u", "eligible_count": eligible, "excluded_count": excluded,
                "outside_class_count": 1, "n_rows": len(vals), "values": vals, "source_complete": True}
    ok = B.k_invariance({1: view(1), 30: view(30), 100: view(100)})
    assert ok["status"] == "pass" and ok["eligible_count"] == 230
    bad = B.k_invariance({1: view(1), 30: view(30, eligible=229)})
    assert bad["status"] == "fail" and any("eligible_count" in p for p in bad["problems"])
    assert B.k_invariance({1: view(1), 30: None})["status"] == "not_run"               # a refused K proves nothing
    capped = {**view(30), "source_complete": False}
    assert B.k_invariance({1: view(1), 30: capped})["status"] == "fail"


def test_scale_is_labelled_reduced_unless_the_spec_counts_were_met(tmp_path):
    full = B.Cfg(data_dir=tmp_path, out_dir=tmp_path, mixed_phases=(("single_client", 1, 2, 180.0), ("five_clients", 5, 2, 300.0)))
    assert B.scale_report(full)["label"] == "full" and B.scale_report(full)["shortfalls"] == []
    small = B.Cfg(data_dir=tmp_path, out_dir=tmp_path, cold_repeats=2, warm_samples=3)
    s = B.scale_report(small)
    assert s["label"] == "reduced" and not s["meets_spec_counts"]
    assert any("cold repetitions 2" in x for x in s["shortfalls"]) and any("warm samples 3" in x for x in s["shortfalls"])
    assert B.parse_phase("p:2:1:5.5") == ("p", 2, 1, 5.5)
    for bad in ("p:0:0:5", "p:1:0:0", "p:x:0:5", "p"):
        with pytest.raises(B.HarnessError):
            B.parse_phase(bad)


# ---------------------------------------------------------------- units: report, blocked runs, accounting of failures

def args_for(tmp_path, *extra, data="nodata"):
    return B.build_parser().parse_args(["run", "--data-dir", str(tmp_path / data), "--out-dir", str(tmp_path / "out"),
                                        *extra])


def test_report_schema_with_every_missing_measurement_null_or_not_run(tmp_path):
    cfg = B.Cfg(data_dir=tmp_path / "nodata", out_dir=tmp_path)
    rep = B.new_report(cfg)
    assert {"schema", "label", "started_at", "finished_at", "status", "mode", "scale", "code", "data", "environment",
            "profile", "workload", "scan_estimate", "gates", "scenarios", "runs", "cases", "checks", "observations",
            "totals", "problems", "errors", "samples_file"} <= set(rep)
    assert rep["schema"] == "benchmark-mcp/1" and rep["profile"]["name"] == "control"
    assert {"commit", "branch", "dirty", "diff_sha256"} == set(rep["code"])
    assert {"os", "python", "cpu_count", "packages", "container"} <= set(rep["environment"])
    assert rep["environment"]["container"]["memory_limit_bytes"] is None        # local: not a 512 MiB run
    data = rep["data"]
    assert data["available"] is False and data["generation"] is None and data["metadata_db"] is None
    assert [d["dataset"] for d in data["datasets"]] == ["POP107D_grupe_localitate", "GOS102A"]
    assert all(d[k] is None for d in data["datasets"] for k in ("bytes", "rows", "row_groups", "footer_sha256"))
    assert rep["scan_estimate"]["footer_rows"] is None
    assert rep["gates"]["linux_512mib"]["status"] == "not_run"
    assert all(v["status"] == "not_run" for v in rep["scenarios"].values())
    out = B.write_report(cfg, rep, B.Recorder())
    again = json.loads(out.read_text())
    assert again["cases"] == [] and again["totals"]["provider_calls"] is None and again["totals"]["restarts"] is None
    assert (tmp_path / "samples.jsonl").exists()


def test_a_run_without_a_corpus_writes_a_blocked_report_and_leaves_the_gate_unrun(tmp_path, monkeypatch):
    monkeypatch.setattr(B.CHILDREN, "install", lambda: None)
    (tmp_path / "nodata").mkdir()
    assert B.run_command(args_for(tmp_path)) == 2
    rep = report_of(tmp_path / "out")
    assert rep["status"] == "blocked" and "no corpus" in rep["blocked_reason"]
    assert all(v["status"] == "not_run" and "no corpus" in v["reason"] for v in rep["scenarios"].values())
    assert rep["cases"] == [] and rep["gates"]["linux_512mib"]["status"] == "not_run"
    assert rep["checks"].get("provider_calls", {"status": "not_run"})["status"] == "not_run"


def test_invalid_settings_block_the_run_with_a_report(tmp_path):
    bad_rest = tmp_path / "rest.json"
    bad_rest.write_text('[{"kind": "x", "path": "no-slash"}]')
    for extra in (["--max-scan-rows", "0"], ["--setting", "TEMPO_ASK_ENABLED=true"], ["--scenarios", "bogus"],
                  ["--mode", "container"], ["--rest-requests", str(bad_rest)]):
        assert B.run_command(args_for(tmp_path, *extra)) == 2
        rep = report_of(tmp_path / "out")
        assert rep["status"] == "blocked" and rep["blocked_reason"]


def test_reports_are_never_written_inside_the_repository(tmp_path, capsys):
    a = B.build_parser().parse_args(["run", "--data-dir", str(tmp_path), "--out-dir", str(ROOT / "aq01-report-must-not-exist")])
    assert B.run_command(a) == 2 and not (ROOT / "aq01-report-must-not-exist").exists()
    assert "outside the repository" in capsys.readouterr().err


def test_container_mode_without_docker_is_blocked_and_the_linux_gate_stays_unrun(tmp_path, monkeypatch):
    monkeypatch.setattr(B.CHILDREN, "install", lambda: None)
    monkeypatch.setattr(B.shutil, "which", lambda name: None)
    assert B.ContainerChild.available() == (False, "docker executable not found")
    (tmp_path / "nodata").mkdir()
    assert B.run_command(args_for(tmp_path, "--mode", "container", "--image", "tempo:test")) == 2
    rep = report_of(tmp_path / "out")
    assert rep["status"] == "blocked" and "docker" in rep["blocked_reason"]
    assert rep["gates"]["linux_512mib"] == {"status": "not_run", "reason": rep["blocked_reason"]}
    assert rep["environment"]["container"]["memory_limit_bytes"] == 512 * 1024 ** 2
    assert all(v["status"] == "not_run" for v in rep["scenarios"].values())


def test_the_harness_bounds_itself_with_a_total_time_budget(data_dir, tmp_path, monkeypatch):
    monkeypatch.setattr(B.CHILDREN, "install", lambda: None)
    a = B.build_parser().parse_args(["run", "--data-dir", str(data_dir), "--out-dir", str(tmp_path / "out"),
                                     "--dataset", "CITYX", "--scenarios", "cold_chain,warm",
                                     "--max-total-seconds", "0.000001"])
    assert B.run_command(a) == 1
    rep = report_of(tmp_path / "out")
    assert rep["status"] == "completed_with_failures" and rep["runs"] == []        # no child was even started
    assert rep["scenarios"]["cold_chain"]["status"] == "failed" and "time budget" in rep["scenarios"]["cold_chain"]["error"]
    assert rep["scenarios"]["admission"]["reason"] == "not selected"


class FakeSession:
    def __init__(self, behaviour):
        self.behaviour = behaviour

    async def call_tool(self, name, arguments):
        return await self.behaviour(name, arguments)


class NoTail:
    path = Path("/nonexistent")

    def take(self):
        return []


def fake_result(env, is_error=False):
    from mcp import types
    return types.CallToolResult(content=[types.TextContent(type="text", text=json.dumps(env))],
                                structuredContent=env, isError=is_error)


def drive(tmp_path, behaviour, **kw):
    import asyncio
    cfg = B.Cfg(data_dir=tmp_path / "nodata", out_dir=tmp_path, call_timeout=0.3)
    ctx = B.Ctx(cfg, B.new_report(cfg))
    run = B.Run("r1", None, NoTail(), None, {})
    sess = B.Sess(FakeSession(behaviour), B.WireCounter(), 0.0)
    return ctx, asyncio.run(B.call(ctx, run, sess, "rank", "miss_warm", "rank_entities", {"dataset": "X"}, **kw))


def test_a_client_side_timeout_is_counted_as_a_timeout_not_as_a_latency(tmp_path):
    import asyncio

    async def hang(name, args):
        await asyncio.sleep(10)
    t0 = time.monotonic()
    ctx, r = drive(tmp_path, hang)
    assert time.monotonic() - t0 < 5
    s = r.sample
    assert (s["outcome"], s["status"], s["reason"]) == ("timeout", None, None) and "no answer within" in s["error"]
    assert s["wall_s"] >= 0.3 and r.env is None and not r.served
    row = ctx.recorder.summary()[0]
    assert row["outcomes"] == {"timeout": 1} and row["latency_s"] is None and row["latency_by_outcome"]["timeout"]["n"] == 1
    assert ctx.problems and "timeout" in ctx.problems[0]


def test_transport_failures_and_tool_errors_are_counted_and_flagged(tmp_path):
    async def explode(name, args):
        raise ConnectionResetError("peer closed")
    ctx, r = drive(tmp_path, explode)
    assert r.sample["outcome"] == "transport_error" and "ConnectionResetError" in r.sample["error"]
    assert ctx.problems

    async def bad_input(name, args):
        return fake_result({"status": "error", "reason": "unknown_dataset", "message": "nope"}, is_error=True)
    ctx, r = drive(tmp_path, bad_input)
    assert r.sample["outcome"] == "tool_error" and r.sample["reason"] == "unknown_dataset" and ctx.problems
    ctx, r = drive(tmp_path, bad_input, expect_error=True)                     # asked for on purpose
    assert r.sample["outcome"] == "tool_error" and not ctx.problems


def test_a_refusal_is_a_counted_answer_not_a_failure_and_a_cache_hit_relabels_the_state(tmp_path):
    async def budget(name, args):
        return fake_result({"status": "unavailable", "reason": "query_budget", "message": "too big"})
    ctx, r = drive(tmp_path, budget)
    assert (r.sample["outcome"], r.sample["reason"]) == ("refused", "query_budget") and not ctx.problems
    assert r.sample["wall_s"] is not None and r.sample["dispatched"] is None and r.sample["cached"] is None

    class Tail(NoTail):
        def take(self):
            return [{"kind": "MCP_METRICS", "tool": "rank_entities", "cached": True}]

    async def ok(name, args):
        return fake_result({"status": "ok", "data": {}})
    import asyncio
    cfg = B.Cfg(data_dir=tmp_path / "nodata", out_dir=tmp_path, call_timeout=1)
    ctx = B.Ctx(cfg, B.new_report(cfg))
    run = B.Run("r1", None, Tail(), None, {})
    run.log_ok = True
    sess = B.Sess(FakeSession(ok), B.WireCounter(), 0.0)
    hit = asyncio.run(B.call(ctx, run, sess, "rank", "miss_warm", "rank_entities", {}))
    assert hit.sample["cached"] is True and hit.sample["state"] == "cache" and hit.sample["dispatched"] is False


def test_a_resource_window_with_no_reading_reports_null_not_zero():
    class Silent:
        def sample(self):
            return {"rss_tree_bytes": None, "container_memory_bytes": None}

        def cpu_seconds(self):
            return None
    mon = B.ResourceMonitor(Silent(), interval=0.01)
    mon.start()
    with mon.window("w") as w:
        time.sleep(0.05)
    mon.stop()
    assert w["rss_peak_bytes"] is None and w["container_memory_peak_bytes"] is None and w["cpu_s"] is None
    assert w["samples"] > 0 and w["wall_s"] >= 0.04

    class Rising:
        n = 0

        def sample(self):
            Rising.n += 1
            return {"rss_tree_bytes": 1000 * Rising.n, "container_memory_bytes": None}

        def cpu_seconds(self):
            return 1.5
    mon = B.ResourceMonitor(Rising(), interval=0.01)
    mon.start()
    with mon.window("w") as w:
        time.sleep(0.05)
    mon.stop()
    assert w["rss_peak_bytes"] >= 3000 and w["cpu_s"] == 0.0 and w["container_memory_peak_bytes"] is None


# ---------------------------------------------------------------- units: children are always cleaned up

def alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    try:
        return os.waitpid(pid, os.WNOHANG) == (0, 0)
    except ChildProcessError:
        return True


def local_child(tmp_path, code, port, **kw):
    child = B.LocalChild(name="stub", port=port, env={"PATH": os.environ["PATH"]}, log_path=tmp_path / "stub.log",
                         startup_timeout=kw.pop("startup_timeout", 0.6), cmd=[sys.executable, "-c", code], **kw)
    child.term_grace, child.kill_grace = 0.3, 2.0
    return child


def test_a_child_that_never_starts_listening_is_killed_and_unregistered(tmp_path):
    child = local_child(tmp_path, "import time; print('up but deaf', flush=True); time.sleep(120)", 8111)
    with pytest.raises(B.HarnessError, match="did not listen"):
        child.start()
    assert child.pid and not alive(child.pid) and child not in B.CHILDREN.children
    assert child.stop()["stopped_by_harness"] is True and child.stop() is child.stop()      # idempotent


def test_a_child_that_dies_during_startup_reports_its_log_tail(tmp_path):
    child = local_child(tmp_path, "import sys; print('port already in use', flush=True); sys.exit(3)", 8112,
                        startup_timeout=5.0)
    with pytest.raises(B.HarnessError, match="exited before.*port already in use"):
        child.start()
    assert child.stop()["exit_code"] == 3 and child.stop()["oom_suspected"] is False


LISTEN = ("import socket, signal, time; s = socket.socket(); s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1); "
          "s.bind(('127.0.0.1', {port})); s.listen(); {ignore} time.sleep(120)")


def test_the_registry_kills_a_running_child_even_when_it_ignores_sigterm(tmp_path):
    code = LISTEN.format(port=8113, ignore="signal.signal(signal.SIGTERM, signal.SIG_IGN);")
    child = local_child(tmp_path, code, 8113, startup_timeout=10.0)
    child.start()
    assert child.alive() and child in B.CHILDREN.children and child.startup_s is not None
    assert child.sample()["rss_tree_bytes"] > 1_000_000 and child.cpu_seconds() is not None
    assert B.CHILDREN.kill_all() >= 1
    assert not alive(child.pid) and child not in B.CHILDREN.children
    stats = child.stop()
    assert stats["signal"] == 9 and stats["stopped_by_harness"] and stats["oom_suspected"] is False   # our SIGKILL, not an OOM
    assert stats["rss_peak_kernel_bytes"] > 1_000_000 and stats["cpu_s_total"] is not None


def test_an_unrequested_sigkill_is_reported_as_a_suspected_oom_kill(tmp_path):
    child = local_child(tmp_path, LISTEN.format(port=8114, ignore=""), 8114, startup_timeout=10.0)
    child.start()
    os.kill(child.pid, 9)
    deadline = time.monotonic() + 5
    while child.alive() and time.monotonic() < deadline:
        time.sleep(0.02)
    stats = child.stop()
    assert stats["signal"] == 9 and stats["stopped_by_harness"] is False and stats["oom_suspected"] is True


def test_a_failing_scenario_still_stops_its_child_and_the_report_says_so(data_dir, tmp_path, monkeypatch):
    monkeypatch.setattr(B.CHILDREN, "install", lambda: None)
    pids = []

    async def explode(ctx):
        async with B.running_child(ctx, "doomed", "cold_chain") as run:
            pids.append(run.child.pid)
            raise RuntimeError("scenario exploded after the child started")
    monkeypatch.setitem(B.SCENARIO_FUNCS, "cold_chain", explode)
    a = B.build_parser().parse_args(["run", "--data-dir", str(data_dir), "--out-dir", str(tmp_path / "out"),
                                     "--dataset", "CITYX", "--scenarios", "cold_chain", "--ports", PORTS])
    assert B.run_command(a) == 1
    rep = report_of(tmp_path / "out")
    assert pids and not alive(pids[0]) and not B.CHILDREN.children
    assert rep["scenarios"]["cold_chain"]["status"] == "failed" and "exploded" in rep["scenarios"]["cold_chain"]["error"]
    run = rep["runs"][0]
    assert "exploded" in run["error"] and run["stats"]["stopped_by_harness"] and run["stats"]["oom_suspected"] is False
    assert rep["status"] == "completed_with_failures" and rep["failed_scenarios"] == ["cold_chain"]


def test_a_failed_cold_repetition_does_not_cancel_the_others(tmp_path, monkeypatch):
    import asyncio
    done = []

    async def repetition(ctx, i, scenario, chain):
        if i == 1:
            raise B.HarnessError("the child did not start")
        done.append(i)
    monkeypatch.setattr(B, "_cold_repetition", repetition)
    cfg = B.Cfg(data_dir=tmp_path / "d", out_dir=tmp_path, cold_repeats=3)
    ctx = B.Ctx(cfg, B.new_report(cfg))
    with pytest.raises(B.HarnessError, match=r"1 of 3 repetitions failed.*cold_chain-2.*did not start"):
        asyncio.run(B.scenario_cold_chain(ctx))
    assert done == [0, 2]


# ---------------------------------------------------------------- units: container mode (Docker is not required)

class FakeDocker:
    """A stand-in for the docker CLI: records the calls and answers the few the harness makes."""

    def __init__(self, oom=False):
        self.calls, self.running, self.oom = [], False, oom

    def __call__(self, cmd, **kw):
        self.calls.append(list(cmd))
        sub = cmd[1]
        out = ""
        if sub == "run":
            self.running, out = True, "cid\n"
        elif sub == "inspect":
            out = ("true\n" if self.running else "false\n") if "Running" in cmd[3] else f"{str(self.oom).lower()} 0 0\n"
        elif sub == "exec":
            files = {"memory.current": "250000000\n", "memory.peak": "300000000\n", "memory.events": "oom_kill 0\n",
                     "memory.stat": "anon 180000000\nfile 60000000\nkernel 1\n",
                     "cpu.stat": "usage_usec 2500000\nuser_usec 1\n"}
            out = "".join(next((v for k, v in files.items() if path.endswith(k)), "") for path in cmd[4:])
        elif sub in ("stop", "rm"):
            self.running = False
        return subprocess.CompletedProcess(cmd, 0, out, "")


class Follower:
    def __init__(self, *a, **k):
        self.terminated = False

    def terminate(self):
        self.terminated = True


def container(tmp_path, docker, port, **kw):
    return B.ContainerChild(name="warm", port=port, image="tempo:cand", log_path=tmp_path / "c.log",
                            startup_timeout=kw.pop("startup_timeout", 0.4), data_dir=tmp_path,
                            env={"TEMPO_DATA_DIR": "/bench-data", "TEMPO_MCP_ENABLED": "true"},
                            runner=docker, popen=Follower, **kw)


def test_the_container_command_enforces_the_limit_mounts_read_only_and_passes_no_host_environment(tmp_path):
    c = container(tmp_path, FakeDocker(), 8111, fault={"rank_entities": "5.5:1"})
    cmd = c.command()
    flat = " ".join(cmd)
    assert cmd[:3] == ["docker", "run", "-d"] and "--memory 512m --memory-swap 512m" in flat and "--cpus 1" in flat
    assert "--restart no" in flat and "-p 127.0.0.1:8111:8080" in flat
    assert f"{tmp_path}:/bench-data:ro" in flat and "benchmark-mcp.py:/bench/benchmark-mcp.py:ro" in flat
    assert "-e TEMPO_MCP_ENABLED=true" in flat and "-e TEMPO_DATA_DIR=/bench-data" in flat
    assert not any(B.is_secret_name(a.split("=")[0]) for a in cmd if "=" in a)
    assert cmd[cmd.index("tempo:cand"):][:3] == ["tempo:cand", "python", "/bench/benchmark-mcp.py"]
    assert "--fault-delay" in cmd and "rank_entities=5.5:1" in cmd and c.describe()["memory_limit_bytes"] == 512 * 1024 ** 2


def test_a_container_that_does_not_come_up_is_stopped_and_removed(tmp_path):
    docker = FakeDocker()
    c = container(tmp_path, docker, 8115)
    with pytest.raises(B.HarnessError, match="did not answer /api/health"):
        c.start()
    subs = [x[1] for x in docker.calls]
    assert "stop" in subs and "rm" in subs and not docker.running and c not in B.CHILDREN.children
    assert c._logger.terminated


class _Health(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200 if self.path == "/api/health" else 404)
        self.end_headers()

    def log_message(self, *a):
        pass


def test_a_published_port_that_accepts_tcp_is_not_ready_until_health_answers(tmp_path):
    """Docker's port forwarder accepts connections before the app listens (seen with Colima)."""
    srv = socket.socket()
    srv.bind(("127.0.0.1", 8116))
    srv.listen()
    try:
        assert B.wait_listening(8116, 0.5) < 0.5                               # the old check: "ready"
        with pytest.raises(B.HarnessError, match="did not answer /api/health"):
            B.wait_http_ready(8116, 0.6)
    finally:
        srv.close()


def test_container_measurements_come_from_the_cgroup_and_inspect(tmp_path):
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 8115), _Health)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        c = container(tmp_path, FakeDocker(), 8115)
        c.start()
        assert c.startup_s is not None and c.alive()
        assert c.sample() == {"rss_tree_bytes": None, "container_memory_bytes": 250_000_000,
                              "container_anon_bytes": 180_000_000, "container_file_bytes": 60_000_000}
        assert c.cpu_seconds() == pytest.approx(2.5)
        stats = c.stop()
    finally:
        srv.shutdown()
        srv.server_close()
    assert stats["container_memory_peak_bytes"] == 300_000_000 and stats["oom_killed"] is False
    assert stats["oom_kill_events"] == 0 and stats["restarts"] == 0 and stats["oom_suspected"] is False
    assert stats["rss_peak_kernel_bytes"] is None and stats["cpu_s_total"] == pytest.approx(2.5)
    oomed = container(tmp_path, FakeDocker(oom=True), 8115)
    oomed._started = True
    assert oomed.stop()["oom_suspected"] is True


# ---------------------------------------------------------------- end to end: a real child, the real MCP client

def test_default_profile_refuses_the_over_limit_fixture_and_never_dispatches_the_handler(data_dir, tmp_path):
    out = tmp_path / "out"
    r = harness(["--data-dir", str(data_dir), "--out-dir", str(out), "--dataset", "CITYBIG", "--years", "2025,2024",
                 "--scenarios", "cold_first_rank,admission", "--cold-repeats", "1", "--ports", PORTS])
    assert r.returncode == 0, r.stdout + r.stderr
    rep = report_of(out)
    assert rep["status"] == "completed" and rep["profile"]["name"] == "control"
    assert rep["profile"]["settings_declared"] == {} and rep["profile"]["harness_overrides"] == B.HARNESS_OVERRIDES
    est = rep["scan_estimate"]
    assert (est["footer_rows"], est["scan_cap"], est["would_admit"]) == (BIG_ROWS, 1_000_000, False)
    big = next(d for d in rep["data"]["datasets"] if d["dataset"] == "CITYBIG")
    assert big["rows"] == BIG_ROWS and big["footer_sha256"] and big["bytes"] > 0 and rep["data"]["generation"]["id"] == "gen-at01-fixture"
    first = case(rep, "cold_first_rank.rank_entities", "cold")
    assert first["outcomes"] == {"refused": 1} and first["results"] == {"unavailable/query_budget": 1}
    assert first["dispatched"] == 0 and first["latency_s"] is None             # refused: nothing served, nothing zero
    run = next(x for x in rep["runs"] if x["name"] == "cold_first_rank-1")
    assert run["events"]["dispatches"] == {} and run["events"]["results"] == {"unavailable/query_budget": 1}
    log = (out / "logs" / "cold_first_rank-1.log").read_text()
    assert "BENCH_DISPATCH" not in log and "query_budget" in log               # the log, independently of the harness
    chk = rep["checks"]["scan_admission"]
    assert chk["status"] == "pass" and chk["observed"] == "unavailable/query_budget" and chk["dispatched"] is False
    assert chk["estimated_rows"] == BIG_ROWS and chk["scan_cap"] == 1_000_000
    assert case(rep, "admission.workload_rank", "observed")["dispatched"] == 0
    assert rep["checks"]["provider_calls"]["status"] == "pass" and rep["totals"]["provider_calls"] == 0
    for x in rep["runs"]:                                                       # the child never saw a provider key
        assert not any(B.is_secret_name(n) for n in x["env_names"]) and "TEMPO_LLM_PROVIDER" not in x["env_names"]
        assert x["stats"]["stopped_by_harness"] and x["stats"]["oom_suspected"] is False
        assert x["child"]["env_ask_enabled"] is False and x["child"]["mcp_settings"]["max_scan_rows"] == 1_000_000
    assert rep["gates"]["linux_512mib"]["status"] == "not_run" and rep["scale"]["label"] == "reduced"
    conc = rep["observations"]["concurrency"]
    assert conc["results"] == {"refused/query_budget": 5}                      # every simultaneous call refused at the gate


def test_candidate_profile_ranks_cities_correctly_through_the_real_client_with_parity(data_dir, tmp_path):
    out = tmp_path / "out"
    r = harness(["--data-dir", str(data_dir), "--out-dir", str(out), "--dataset", "CITYBIG", "--years", "2025,2024",
                 "--max-scan-rows", "2000000", "--scenarios", "cold_first_rank,warm,admission", "--cold-repeats", "1",
                 "--warm-samples", "4", "--ports", PORTS])
    assert r.returncode == 0, r.stdout + r.stderr
    rep = report_of(out)
    assert rep["status"] == "completed" and rep["profile"]["name"] == "candidate"
    assert rep["profile"]["settings_declared"] == {"TEMPO_MCP_MAX_SCAN_ROWS": "2000000"}
    assert rep["scan_estimate"]["would_admit"] is True and rep["scan_estimate"]["scan_cap"] == 2_000_000
    warm = next(x for x in rep["runs"] if x["name"] == "warm")
    assert warm["child"]["mcp_settings"]["max_scan_rows"] == 2_000_000 and warm["child"]["policy_version"] == "mcp-2"
    par = rep["checks"]["parity"]
    assert par["status"] == "pass" and par["compared"] >= 6 and par["differing"] == 0
    assert all(all(q["fields_equal"].values()) and q["equal"] for q in par["requests"])
    exact = next(q for q in par["requests"] if q["id"] == "exact_year")["view"]
    assert (exact["year"], exact["eligible_count"], exact["excluded_count"], exact["outside_class_count"]) == ("2025", 230, 0, 1)
    assert exact["values"][:3] == [329.0, 328.0, 327.0] and 999999.0 not in exact["values"]       # the commune is out
    assert exact["top"][0]["entity"]["REF_AREA_2"] == "1229 ORAS CITY229" and exact["n_rows"] == 30
    assert exact["unit"] == "Numar persoane" and exact["source_complete"] is True
    k = {q["id"]: q["view"] for q in par["requests"]}
    assert [k[f"k{n}"]["n_rows"] for n in (1, 30, 100)] == [1, 30, 100]
    assert {k[f"k{n}"]["eligible_count"] for n in (1, 30, 100)} == {230}                          # K never changes the set
    assert rep["checks"]["k_invariance"]["status"] == "pass"
    cache = case(rep, "rank_exact_year", "cache")
    assert cache["n"] == 4 and cache["cache_hits"] == 4 and cache["dispatched"] == 0 and cache["latency_s"]["n"] == 4
    miss = case(rep, "rank_year_miss", "miss_warm")
    assert miss["n"] == 4 and miss["cache_hits"] == 0 and miss["dispatched"] == 4 and miss["sufficient"] is False
    assert ("rank_exact_year", "miss_warm") not in {(c["case"], c["state"]) for c in rep["cases"]}   # not mixed in
    first = case(rep, "cold_first_rank.rank_entities", "cold")
    assert first["outcomes"] == {"served": 1} and first["latency_s"]["n"] == 1 and first["wire_bytes"]["min"] > first["result_bytes"]["min"]
    assert rep["checks"]["scan_admission"]["status"] == "pass"
    conc = rep["observations"]["concurrency"]
    assert sum(conc["results"].values()) == 5 and conc["results"].get("served/None", 0) >= 1
    assert set(conc["results"]) <= {"served/None", "refused/busy"} and conc["max_concurrent"] == 1
    assert warm["stats"]["cpu_s_total"] > 0 and warm["stats"]["rss_peak_kernel_bytes"] > 50_000_000
    assert warm["windows"][0]["rss_peak_bytes"] > 50_000_000


def test_a_timed_out_worker_keeps_its_slot_and_the_first_request_after_it_is_served(data_dir, tmp_path):
    out = tmp_path / "out"
    r = harness(["--data-dir", str(data_dir), "--out-dir", str(out), "--dataset", "CITYX", "--scenarios", "timeout_probe",
                 "--ports", PORTS])
    assert r.returncode == 0, r.stdout + r.stderr
    rep = report_of(out)
    chk = rep["checks"]["deadline_and_slot"]
    assert chk["status"] == "pass" and chk["fault_injection"]["sleep_s"] == 5.5
    assert chk["first_call"].startswith("unavailable/query_timeout") and chk["call_during_work"] == "unavailable/busy"
    assert chk["slot_free_after_s"] >= 5.5 and chk["first_call_after"] == "ok/None"
    assert case(rep, "timeout_probe.first_call", "observed")["results"] == {"unavailable/query_timeout": 1}
    assert case(rep, "timeout_probe.first_call_after", "observed")["outcomes"] == {"served": 1}
    run = rep["runs"][0]
    assert run["fault_delays"] == {"rank_entities": "5.5:1"} and run["profile_overrides"] == {"TEMPO_MCP_MAX_SECONDS": "1.0"}


def test_mixed_load_keeps_rest_and_mcp_kinds_and_phases_in_separate_groups(data_dir, tmp_path):
    out = tmp_path / "out"
    r = harness(["--data-dir", str(data_dir), "--out-dir", str(out), "--dataset", "CITYX", "--scenarios", "mixed",
                 "--mixed-phase", "one:1:1:2", "--mixed-phase", "many:3:2:2", "--ports", PORTS])
    assert r.returncode == 0, r.stdout + r.stderr
    rep = report_of(out)
    assert rep["checks"]["mixed_load"]["status"] == "pass" and rep["checks"]["unexpected_5xx_or_child_loss"]["status"] == "pass"
    mixed = [c for c in rep["cases"] if c["state"] == "mixed"]
    names = {c["case"] for c in mixed}
    assert {"mixed.one.rest_health", "mixed.many.rest_health", "mixed.one.mcp_rank_cached", "mixed.many.mcp_rank_miss"} <= names
    assert all(c["case"].startswith(("mixed.one.", "mixed.many.")) for c in mixed)           # per phase, never pooled
    assert rep["observations"]["mixed_export"].startswith("not_run")
    phases = rep["observations"]["mixed_phases"]
    assert [p["phase"] for p in phases] == ["one", "many"]
    assert all(p["unexpected_5xx"] == 0 and p["unexpected_4xx"] == 0 for p in phases)
    assert all(p["slot_free_after_phase_s"] is not None and p["window"]["rss_peak_bytes"] > 50_000_000 for p in phases)


class InfoDocker(FakeDocker):
    def __init__(self, info: dict | None, image="sha256:abc arm64\n", **kw):
        super().__init__(**kw)
        self.info, self.image = info, image

    def __call__(self, cmd, **kw):
        if cmd[1] == "info":
            self.calls.append(list(cmd))
            return subprocess.CompletedProcess(cmd, 0 if self.info else 1, json.dumps(self.info or {}), "")
        if cmd[1:3] == ["image", "inspect"]:
            self.calls.append(list(cmd))
            return subprocess.CompletedProcess(cmd, 0, self.image, "")
        return super().__call__(cmd, **kw)


def test_the_daemon_facts_come_from_docker_info_and_the_image(tmp_path):
    info = {"OSType": "linux", "KernelVersion": "6.8.0", "OperatingSystem": "Ubuntu 24.04", "Architecture": "aarch64",
            "CgroupVersion": "2", "MemTotal": 6_000_000_000, "NCPU": 4, "ServerVersion": "29.5.2"}
    d = B.ContainerChild.daemon("tempo:cand", runner=InfoDocker(info))
    assert d == {"os_type": "linux", "kernel": "6.8.0", "operating_system": "Ubuntu 24.04", "architecture": "aarch64",
                 "cgroup_version": "2", "mem_total_bytes": 6_000_000_000, "ncpu": 4, "server_version": "29.5.2",
                 "image_id": "sha256:abc", "image_architecture": "arm64"}
    assert B.ContainerChild.daemon("tempo:cand", runner=InfoDocker(None)) is None


def _gate(tmp_path, daemon, stats, mode="container"):
    cfg = B.Cfg(data_dir=tmp_path / "nodata", out_dir=tmp_path, mode=mode, image="tempo:cand")
    r = B.new_report(cfg)
    r["environment"]["container"]["daemon"] = daemon
    r["runs"] = [{"target": {"kind": "container"}, "stats": s} for s in stats]
    return B.linux_gate(r, cfg)


def test_the_linux_gate_follows_the_daemon_kernel_not_the_host(tmp_path, monkeypatch):
    monkeypatch.setattr(B.platform, "system", lambda: "Darwin")      # a Linux VM on a Mac still counts
    ok = {"container_memory_peak_bytes": 300_000_000, "oom_killed": False, "oom_suspected": False}
    g = _gate(tmp_path, {"os_type": "linux"}, [ok, dict(ok, container_memory_peak_bytes=350_000_000)])
    assert g["status"] == "measured" and g["container_memory_peak_bytes"] == 350_000_000 and g["oom_killed"] is False
    assert g["container_anon_peak_bytes_sampled"] is None                     # no measured window
    cfg = B.Cfg(data_dir=tmp_path / "nodata", out_dir=tmp_path, mode="container", image="tempo:cand")
    r = B.new_report(cfg)
    r["environment"]["container"]["daemon"] = {"os_type": "linux"}
    r["runs"] = [{"target": {"kind": "container"}, "stats": ok,
                  "windows": [{"container_anon_peak_bytes": 200_000_000}, {"container_anon_peak_bytes": None}]}]
    assert B.linux_gate(r, cfg)["container_anon_peak_bytes_sampled"] == 200_000_000
    assert g["memory_limit_bytes"] == 512 * 1024 ** 2 and g["evaluated"] is False
    assert _gate(tmp_path, {"os_type": "windows"}, [ok])["status"] == "not_run"
    assert _gate(tmp_path, None, [ok])["status"] == "not_run"
    assert _gate(tmp_path, {"os_type": "linux"}, [dict(ok, container_memory_peak_bytes=None)])["status"] == "not_run"
    assert _gate(tmp_path, {"os_type": "linux"}, [], mode="local")["reason"].startswith("local mode")


def test_an_oom_killed_container_is_a_measured_failure_even_without_a_peak(tmp_path):
    killed = {"container_memory_peak_bytes": None, "oom_killed": True, "oom_suspected": True}
    g = _gate(tmp_path, {"os_type": "linux"}, [killed])
    assert g["status"] == "measured" and g["oom_killed"] is True and g["container_memory_peak_bytes"] is None


def test_the_slot_probe_reuses_a_busy_answered_request_and_can_use_a_reserved_one(monkeypatch):
    """A `busy` answer is neither dispatched nor cached, so polling must not burn the variant pool:
    a 300 s mixed phase used up every fresh variant and the slot check then reported nothing."""
    import asyncio
    import types
    sent, answers = [], iter(["busy", "busy", None])

    async def fake_call(ctx, run, sess, case, state, tool, args, **kw):
        sent.append(json.dumps(args, sort_keys=True))
        return types.SimpleNamespace(sample={"reason": next(answers)})

    monkeypatch.setattr(B, "call", fake_call)
    pool = B.VariantPool(B.Workload(year="2025"))
    reserved = pool.fresh(1, counties=False)
    secs, r = asyncio.run(B.await_slot_free(None, None, None, pool, 5.0, reserved=reserved))
    assert secs is not None and r.sample["reason"] is None
    assert len(sent) == 3 and len(set(sent)) == 1 and reserved == []          # one variant, polled three times
    assert len(pool.used) == 1                                                # nothing else taken from the pool


def test_the_default_worst_set_covers_every_scan_gated_tool_and_every_recipe():
    wl = B.Workload(year="2025", years=["2025", "2024", "2023"])
    reqs = B.default_worst_requests(wl, ["r1", "r2"])
    assert {q["tool"] for q in reqs} == set(B.WORST_TOOLS)
    assert [q["arguments"]["recipe"] for q in reqs if q["tool"] == "run_recipe"] == ["r1", "r2"]
    iv = next(q for q in reqs if q["tool"] == "compare_periods")["arguments"]["intervals"]
    assert len(iv) == len({(i["from"], i["to"]) for i in iv}) and all(i["from"] < i["to"] for i in iv)
    two = B.default_worst_requests(B.Workload(year="2025", years=["2025", "2024"]), [])
    assert next(q for q in two if q["tool"] == "compare_periods")["arguments"]["intervals"] == [{"from": "2024", "to": "2025"}]


def test_worst_case_runs_every_scan_gated_tool_with_parity_and_the_one_slot_gate(data_dir, tmp_path):
    out = tmp_path / "out"
    wl = B.Workload(dataset="CITYBIG", year="2025", years=["2025", "2024"])
    reqs = tmp_path / "worst.json"                       # the fixture has no recipe sources: tools only
    reqs.write_text(json.dumps(B.default_worst_requests(wl, [])))
    r = harness(["--data-dir", str(data_dir), "--out-dir", str(out), "--dataset", "CITYBIG", "--years", "2025,2024",
                 "--max-scan-rows", "2000000", "--scenarios", "worst_case", "--worst-requests", str(reqs),
                 # the fixture's entities-by-year group is ~1M groups: the harness logic is under test here,
                 # not whether the 160MB default budget fits it (see aq-01b-linux-run-record.md)
                 "--setting", "TEMPO_DB_MEMORY=400MB", "--ports", PORTS])
    assert r.returncode == 0, r.stdout + r.stderr
    rep = report_of(out)
    reqs = rep["observations"]["worst_case_requests"]
    assert {q["tool"] for q in reqs} == set(B.WORST_TOOLS) - {"run_recipe"}
    wc = rep["checks"]["worst_case"]
    assert wc["status"] == "pass" and wc["failed"] == {} and wc["requests"] == len(reqs)
    obs = rep["observations"]["worst_case"]
    assert set(obs) == {q["name"] for q in reqs} and all(v["outcome"] in ("served", "refused") for v in obs.values())
    par = rep["checks"]["worst_case_parity"]
    assert par["status"] == "pass" and par["compared"] == wc["served"] and par["differing"] == 0
    conc = rep["observations"]["worst_case_concurrent"]
    assert conc["requests"] == len(reqs) and sum(conc["results"].values()) == len(reqs)


def test_worst_requests_file_is_validated(tmp_path):
    bad = tmp_path / "w.json"
    for items in ([], [{"name": "x", "tool": "describe_dataset", "arguments": {}}], [{"name": "x", "tool": "query_data"}]):
        bad.write_text(json.dumps(items))
        with pytest.raises(B.HarnessError, match="worst-requests"):
            B.load_worst_requests(str(bad))
    bad.write_text(json.dumps([{"name": "q", "tool": "query_data", "arguments": {"dataset": "X"}}]))
    assert B.load_worst_requests(str(bad))[0]["tool"] == "query_data"
