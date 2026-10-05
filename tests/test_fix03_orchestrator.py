"""FIX-03 phase 1: update-pipeline.py success semantics, retry state, watermark,
dry-run and language safety. No network, no real pipeline scripts: subprocess.run
and the metadata fetch are replaced by scripted fakes and everything lives in tmp_path.
"""
import importlib.util
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parent.parent
STATE_OLD_WM = "01.01.2026"


@pytest.fixture
def pipe(tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location("update_pipeline_t", ROOT / "update-pipeline.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    logs = tmp_path / "data" / "logs"
    monkeypatch.setattr(mod, "BASE_DIR", tmp_path)
    monkeypatch.setattr(mod, "LOG_DIR", logs)
    monkeypatch.setattr(mod, "NEWS_CSV", tmp_path / "data" / "insse_news.csv")
    monkeypatch.setattr(mod, "LAST_RUN_FILE", logs / "last-pipeline-run.txt")
    monkeypatch.setattr(mod, "STATE_FILE", logs / "update-pipeline-state.json")
    monkeypatch.delenv("TEMPO_LANG", raising=False)

    # a "usable artifact" that must survive any failure
    parquet = tmp_path / "data" / "corpus" / "parquet" / "AAA1.parquet"
    parquet.parent.mkdir(parents=True)
    parquet.write_bytes(b"previous generation")

    ctl = SimpleNamespace(
        mod=mod, tmp=tmp_path, parquet=parquet, calls=[], envs=[], meta_calls=[],
        rcs={}, meta_fail=set(), sync_calls=[], sync_error=None, raise_on=None,
        children={}, validate_fail={},
        state_path=logs / "update-pipeline-state.json",
        legacy=logs / "last-pipeline-run.txt",
    )

    def fake_run(cmd, cwd=None, env=None, **kw):
        script = Path(cmd[1]).name
        arg = cmd[2:]
        code = arg[arg.index("--matrix") + 1] if "--matrix" in arg else None
        ctl.calls.append((script, code))
        ctl.envs.append(env)
        if ctl.raise_on == (script, code):
            raise RuntimeError("simulated crash")
        rc = ctl.rcs.get((script, code), ctl.rcs.get(script, 0))
        return SimpleNamespace(returncode=rc)

    def fake_meta(code, lang, force):
        ctl.meta_calls.append(code)
        return code not in ctl.meta_fail

    def fake_sync(codes, lang, dry_run=False):
        ctl.sync_calls.append(list(codes))
        if ctl.sync_error:
            raise ctl.sync_error
        return len(codes)

    def fake_children(code):
        return list(ctl.children.get(code, []))

    def fake_validate(code, children, check_split=True):
        return ctl.validate_fail.get(code)

    monkeypatch.setattr(mod, "fetch_children", fake_children)
    monkeypatch.setattr(mod, "validate_matrix", fake_validate)
    monkeypatch.setattr(mod.subprocess, "run", fake_run)
    monkeypatch.setattr(mod, "fetch_meta", fake_meta)
    monkeypatch.setattr(mod, "sync_ultima_actualizare", fake_sync)

    def feed(rows):
        """rows: [(DD.MM.YYYY, CODE)]"""
        lines = ["Activitatea,Data,Domeniu,Cod matrice,Denumire,Perioada,Date,Metadate,Nom"]
        lines += [f"Actualizare,{d},X,{c},Name,2025,1,1,1" for d, c in rows]
        mod.NEWS_CSV.parent.mkdir(parents=True, exist_ok=True)
        # parse_news uses skiprows=1 (header row) then names=...
        mod.NEWS_CSV.write_text("\n".join(lines) + "\n", encoding="utf-8-sig")

    ctl.feed = feed
    ctl.go = lambda *a: mod.run_pipeline(list(a))
    ctl.state = lambda: json.loads(ctl.state_path.read_text())
    ctl.scripts = lambda code=None: [s for s, c in ctl.calls if code is None or c == code]
    ctl.seed_watermark = lambda wm=STATE_OLD_WM: (
        ctl.state_path.parent.mkdir(parents=True, exist_ok=True),
        ctl.state_path.write_text(json.dumps({"version": 1, "watermark": wm, "retry": {}})),
        ctl.legacy.write_text(wm),
    )
    return ctl


# ---------------------------------------------------------------- success path
def test_success_advances_watermark_to_feed_date_not_today(pipe):
    pipe.feed([("02.02.2026", "AAA1"), ("05.03.2026", "AAA1"), ("03.03.2026", "BBB2")])
    assert pipe.go() == 0
    st = pipe.state()
    assert st["watermark"] == "05.03.2026"          # newest feed date, not wall clock
    assert pipe.legacy.read_text() == "05.03.2026"
    assert st["retry"] == {}
    assert st["matrices"]["AAA1"]["source_update"] == "05.03.2026"  # latest of its updates
    assert st["matrices"]["AAA1"]["outcome"] == "ok"
    assert all(v["outcome"] == "ok" for v in st["matrices"]["AAA1"]["stages"].values())
    assert pipe.sync_calls == [["AAA1", "BBB2"]]
    assert [c for c in pipe.calls if c[1] == "AAA1"][0][0] == "6-fetch-csv.py"


def test_children_get_explicit_romanian_language(pipe):
    pipe.feed([("02.02.2026", "AAA1")])
    pipe.go()
    assert pipe.envs and all(e["TEMPO_LANG"] == "ro" for e in pipe.envs)


def test_watermark_never_regresses_with_older_since(pipe):
    pipe.seed_watermark("10.04.2026")
    pipe.feed([("02.02.2026", "AAA1")])
    assert pipe.go("--since", "01.01.2026") == 0
    assert pipe.state()["watermark"] == "10.04.2026"


# ---------------------------------------------------------------- failures
@pytest.mark.parametrize("failing", [
    ("meta", None), ("6-fetch-csv.py", "AAA1"), ("9-csv-to-parquet.py", "AAA1"),
    ("12-split-datasets.py", "AAA1"), ("10-import-metadata.py", "AAA1"),
    ("10-classify-dimensions.py", "AAA1"), ("11-build-sdmx-codes.py", "AAA1"),
    ("4-build-meta-index.py", None), ("sync", None),
])
def test_required_failure_exit_retry_watermark_artifacts(pipe, failing):
    pipe.seed_watermark()
    pipe.feed([("05.05.2026", "AAA1")])
    key, code = failing
    if key == "meta":
        pipe.meta_fail.add("AAA1")
    elif key == "sync":
        pipe.sync_error = RuntimeError("db locked")
    else:
        pipe.rcs[(key, code)] = 1
    assert pipe.go() == 1
    st = pipe.state()
    assert st["watermark"] == STATE_OLD_WM          # not advanced
    assert pipe.legacy.read_text() == STATE_OLD_WM
    assert "AAA1" in st["retry"] and st["retry"]["AAA1"]["attempts"] == 1
    assert st["matrices"]["AAA1"]["outcome"] == "failed"
    assert pipe.parquet.read_bytes() == b"previous generation"   # nothing deleted
    assert st["last_run"]["exit_code"] == 1 and st["last_run"]["failed"] == ["AAA1"]


def test_downstream_stages_skipped_after_required_failure(pipe):
    pipe.feed([("05.05.2026", "AAA1")])
    pipe.rcs[("9-csv-to-parquet.py", "AAA1")] = 1
    pipe.go()
    assert "12-split-datasets.py" not in pipe.scripts("AAA1")
    assert "generate_view_profiles.py" not in pipe.scripts("AAA1")


@pytest.mark.parametrize("script", ["13-dimension-structure.py", "generate_view_profiles.py"])
def test_optional_profile_failure_visible_not_fatal(pipe, script):
    pipe.feed([("05.05.2026", "AAA1")])
    pipe.rcs[(script, "AAA1")] = 1
    assert pipe.go() == 0
    st = pipe.state()
    assert st["matrices"]["AAA1"]["outcome"] == "ok_degraded"
    stage = script.replace(".py", "").replace("13-dimension-structure", "13-dimension-structure")
    assert st["matrices"]["AAA1"]["stages"][stage]["outcome"] == "failed"
    assert st["last_run"]["optional_failed"] == ["AAA1"]
    assert st["retry"] == {} and st["watermark"] == "05.05.2026"


def test_strict_makes_optional_failure_fatal(pipe):
    pipe.feed([("05.05.2026", "AAA1")])
    pipe.rcs[("13-dimension-structure.py", "AAA1")] = 1
    assert pipe.go("--strict") == 1


def test_empty_dataset_is_recorded_not_retried(pipe):
    pipe.feed([("05.05.2026", "AAA1")])
    pipe.rcs[("6-fetch-csv.py", "AAA1")] = 3
    assert pipe.go() == 0
    st = pipe.state()
    assert st["matrices"]["AAA1"]["outcome"] == "empty"
    assert st["retry"] == {}
    assert "9-csv-to-parquet.py" not in pipe.scripts("AAA1")
    assert st["last_run"]["empty"] == ["AAA1"]


def test_fetch_context_failure_aborts_before_matrices(pipe):
    pipe.feed([("05.05.2026", "AAA1")])
    pipe.rcs[("1-fetch-context.py", None)] = 1
    assert pipe.go("--fetch-context") == 1
    assert "6-fetch-csv.py" not in pipe.scripts()
    assert not pipe.state_path.exists()


def test_crash_mid_run_keeps_earlier_failures_durable(pipe):
    pipe.seed_watermark()
    pipe.feed([("05.05.2026", "AAA1"), ("05.05.2026", "BBB2")])
    pipe.rcs[("9-csv-to-parquet.py", "AAA1")] = 1
    pipe.raise_on = ("6-fetch-csv.py", "BBB2")
    with pytest.raises(RuntimeError):
        pipe.go()
    st = pipe.state()
    assert "AAA1" in st["retry"] and st["watermark"] == STATE_OLD_WM


def test_corrupt_state_is_an_error_not_a_silent_reset(pipe):
    pipe.state_path.parent.mkdir(parents=True, exist_ok=True)
    pipe.state_path.write_text("{not json")
    pipe.feed([("05.05.2026", "AAA1")])
    assert pipe.go() == 1
    assert pipe.calls == []
    assert pipe.state_path.read_text() == "{not json"


# ---------------------------------------------------------------- resume / merge
def test_resume_no_lost_updates_no_duplicates(pipe):
    pipe.feed([("02.02.2026", "AAA1"), ("03.03.2026", "BBB2")])
    pipe.rcs[("9-csv-to-parquet.py", "BBB2")] = 1
    assert pipe.go() == 1
    assert list(pipe.state()["retry"]) == ["BBB2"]
    assert pipe.state()["watermark"] is None

    # INS fixed / transient error gone; feed unchanged
    pipe.rcs.clear()
    pipe.calls.clear()
    assert pipe.go() == 0
    st = pipe.state()
    assert st["retry"] == {} and st["watermark"] == "03.03.2026"
    assert pipe.scripts("BBB2").count("9-csv-to-parquet.py") == 1   # once, not duplicated
    assert pipe.scripts("AAA1").count("9-csv-to-parquet.py") == 1


def test_retry_merged_even_when_feed_window_excludes_it(pipe):
    pipe.seed_watermark("01.04.2026")
    pipe.feed([("10.04.2026", "AAA1")])
    pipe.state_path.write_text(json.dumps({
        "version": 1, "watermark": "01.04.2026",
        "retry": {"OLD9": {"stage": "9-csv-to-parquet", "reason": "x", "source_update": "02.03.2026",
                           "attempts": 2, "first_failed": "t", "last_failed": "t"}}}))
    assert pipe.go() == 0
    assert "OLD9" in {c for _, c in pipe.calls}
    st = pipe.state()
    assert st["retry"] == {} and st["watermark"] == "10.04.2026"
    assert st["matrices"]["OLD9"]["source_update"] == "02.03.2026"


def test_retry_attempts_accumulate(pipe):
    pipe.feed([("05.05.2026", "AAA1")])
    pipe.rcs[("6-fetch-csv.py", "AAA1")] = 1
    pipe.go()
    pipe.go()
    r = pipe.state()["retry"]["AAA1"]
    assert r["attempts"] == 2 and r["stage"] == "6-fetch-csv"


def test_failed_matrix_cleared_while_others_still_fail(pipe):
    pipe.feed([("05.05.2026", "AAA1"), ("05.05.2026", "BBB2")])
    pipe.rcs[("9-csv-to-parquet.py", "BBB2")] = 1
    pipe.state_path.parent.mkdir(parents=True, exist_ok=True)
    pipe.state_path.write_text(json.dumps({"version": 1, "watermark": None, "retry": {
        "AAA1": {"stage": "6-fetch-csv", "reason": "old", "attempts": 1}}}))
    assert pipe.go() == 1
    assert list(pipe.state()["retry"]) == ["BBB2"]    # AAA1 succeeded, no longer owed


# ---------------------------------------------------------------- modes
def test_manual_matrix_does_not_touch_watermark_but_tracks_retry(pipe):
    pipe.seed_watermark()
    pipe.rcs[("9-csv-to-parquet.py", "ZZZ9")] = 1
    assert pipe.go("--matrix", "ZZZ9") == 1
    assert "ZZZ9" in pipe.state()["retry"] and pipe.state()["watermark"] == STATE_OLD_WM
    pipe.rcs.clear()
    assert pipe.go("--matrix", "ZZZ9") == 0
    st = pipe.state()
    assert st["retry"] == {} and st["watermark"] == STATE_OLD_WM
    assert pipe.legacy.read_text() == STATE_OLD_WM


@pytest.mark.parametrize("flag", ["--skip-existing", "--no-split", "--skip-duckdb"])
def test_partial_runs_never_advance_watermark(pipe, flag):
    pipe.seed_watermark()
    pipe.feed([("05.05.2026", "AAA1")])
    assert pipe.go(flag) == 0
    assert pipe.state()["watermark"] == STATE_OLD_WM


def test_option_conflicts_are_usage_errors(pipe):
    assert pipe.go("--matrix", "A1B2", "--since", "01.01.2026") == 2
    assert pipe.go("--since", "bogus") == 2
    assert pipe.go("--since", "01.01.2026", "--all") == 2
    assert pipe.calls == []


def test_all_ignores_watermark(pipe):
    pipe.seed_watermark("01.04.2026")
    pipe.feed([("02.02.2026", "AAA1"), ("10.04.2026", "BBB2")])
    assert pipe.go("--all") == 0
    assert {c for _, c in pipe.calls if c} == {"AAA1", "BBB2"}


def test_watermark_filter_is_inclusive(pipe):
    pipe.seed_watermark("10.04.2026")
    pipe.feed([("09.04.2026", "OLD1"), ("10.04.2026", "AAA1")])
    assert pipe.go() == 0
    assert {c for _, c in pipe.calls if c} == {"AAA1"}


def test_legacy_last_run_file_used_when_no_state(pipe):
    pipe.legacy.parent.mkdir(parents=True, exist_ok=True)
    pipe.legacy.write_text("10.04.2026")
    pipe.feed([("09.04.2026", "OLD1"), ("11.04.2026", "AAA1")])
    assert pipe.go() == 0
    assert {c for _, c in pipe.calls if c} == {"AAA1"}


# ---------------------------------------------------------------- dry-run
def test_dry_run_changes_nothing(pipe, monkeypatch):
    pipe.seed_watermark()
    pipe.feed([("05.05.2026", "AAA1")])
    before = {p: p.read_bytes() for p in pipe.tmp.rglob("*") if p.is_file()}
    monkeypatch.setattr(pipe.mod, "fetch_news", lambda: pytest.fail("network in dry-run"))
    assert pipe.go("--dry-run", "--refetch-news", "--fetch-context") == 0
    assert pipe.calls == [] and pipe.meta_calls == []
    after = {p: p.read_bytes() for p in pipe.tmp.rglob("*") if p.is_file()}
    assert before == after            # no state, watermark, log, or corpus change
    assert pipe.sync_calls == [] or pipe.sync_calls == [["AAA1"]]  # sync is itself dry-run aware


def test_dry_run_does_not_create_state_when_none_exists(pipe):
    pipe.feed([("05.05.2026", "AAA1")])
    assert pipe.go("--dry-run") == 0
    assert not pipe.state_path.exists() and not pipe.legacy.exists()
    assert not list((pipe.tmp / "data" / "logs").glob("*.log")) if (pipe.tmp / "data" / "logs").exists() else True


# ---------------------------------------------------------------- language safety
def test_lang_en_rejected_before_any_work(pipe):
    pipe.feed([("05.05.2026", "AAA1")])
    with pytest.raises(SystemExit) as e:
        pipe.go("--lang", "en")
    assert e.value.code == 2
    assert pipe.calls == [] and pipe.meta_calls == [] and not pipe.state_path.exists()


def test_tempo_lang_env_en_rejected(pipe, monkeypatch):
    monkeypatch.setenv("TEMPO_LANG", "en")
    pipe.feed([("05.05.2026", "AAA1")])
    with pytest.raises(SystemExit) as e:
        pipe.go()
    assert e.value.code == 2 and pipe.calls == []


def test_help_does_not_advertise_english_support(pipe, capsys):
    with pytest.raises(SystemExit):
        pipe.go("--help")
    out = capsys.readouterr().out
    assert "rejected" in out
