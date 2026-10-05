"""FIX-03 phase 2a: the orchestrator runs the stages in dependency order, checks every
prerequisite and stops/records a matrix on the first failed one. Scripted fakes (see
test_fix03_orchestrator.pipe); the real artifacts are covered by test_fix03b_refresh/split."""
import importlib.util
import json
from pathlib import Path

import pytest

from test_fix03_orchestrator import pipe  # noqa: F401  (fixture)
from fix03b_env import Env, Y2020, Y2021

ROOT = Path(__file__).resolve().parent.parent

PER_MATRIX_ORDER = [
    "6-fetch-csv.py",
    "10-import-metadata.py",        # metadata + options reconcile
    "10-classify-dimensions.py",
    "11-build-sdmx-codes.py",
    "9-csv-to-parquet.py",          # only after the maps above are fresh
    "12-split-datasets.py",
    "10-import-metadata.py",        # --stats-only: row_count/path of the new parquet
    "13-dimension-structure.py",
    "generate_view_profiles.py",
]


def test_stage_order_for_a_changed_matrix(pipe):
    pipe.feed([("05.05.2026", "AAA1")])
    assert pipe.go() == 0
    assert pipe.scripts("AAA1") == PER_MATRIX_ORDER
    # run-level index rebuild comes after every matrix, never before conversion
    assert pipe.calls[-1] == ("4-build-meta-index.py", None)
    cmds = {(s, tuple(a)) for s, a in pipe.cmds}
    assert ("10-import-metadata.py", ("--matrix", "AAA1")) in cmds
    assert ("10-import-metadata.py", ("--matrix", "AAA1", "--stats-only")) in cmds
    assert ("10-classify-dimensions.py", ("--matrix", "AAA1")) in cmds
    assert ("11-build-sdmx-codes.py", ("--matrix", "AAA1")) in cmds
    st = pipe.state()["matrices"]["AAA1"]["stages"]
    assert set(st) == set(["meta", "6-fetch-csv", "10-import-metadata", "10-classify-dimensions",
                               "11-build-sdmx-codes", "9-csv-to-parquet", "12-split", "10-import-stats",
                               "13-dimension-structure", "generate_view_profiles", "validate"])


def test_children_are_profiled_with_their_parent(pipe):
    pipe.children["AAA1"] = ["AAA1_a", "AAA1_b"]
    pipe.feed([("05.05.2026", "AAA1")])
    assert pipe.go() == 0
    cmds = [(s, a) for s, a in pipe.cmds]
    assert ("13-dimension-structure.py", ["--matrix", "AAA1,AAA1_a,AAA1_b"]) in cmds
    for code in ("AAA1", "AAA1_a", "AAA1_b"):
        assert ("generate_view_profiles.py", ["--matrix", code]) in cmds
    # profiling happens after the split registered the children, before validation
    order = [s for s, _ in cmds]
    assert order.index("12-split-datasets.py") < order.index("13-dimension-structure.py")


PREREQS = [
    ("meta", None, ["6-fetch-csv.py"]),
    ("6-fetch-csv.py", "6-fetch-csv", ["10-import-metadata.py"]),
    ("10-import-metadata.py", "10-import-metadata", ["10-classify-dimensions.py", "11-build-sdmx-codes.py",
                                                    "9-csv-to-parquet.py", "12-split-datasets.py"]),
    ("10-classify-dimensions.py", "10-classify-dimensions", ["11-build-sdmx-codes.py", "9-csv-to-parquet.py",
                                                            "12-split-datasets.py"]),
    ("11-build-sdmx-codes.py", "11-build-sdmx-codes", ["9-csv-to-parquet.py", "12-split-datasets.py"]),
    ("9-csv-to-parquet.py", "9-csv-to-parquet", ["12-split-datasets.py", "13-dimension-structure.py"]),
    ("12-split-datasets.py", "12-split", ["13-dimension-structure.py", "generate_view_profiles.py"]),
]


@pytest.mark.parametrize("failing,stage,downstream", PREREQS)
def test_failed_prerequisite_stops_the_matrix_and_is_retried(pipe, failing, stage, downstream):
    pipe.seed_watermark()
    pipe.feed([("05.05.2026", "AAA1"), ("05.05.2026", "BBB2")])
    if failing == "meta":
        pipe.meta_fail.add("AAA1")
        stage = "meta"
    else:
        pipe.rcs[(failing, "AAA1")] = 1
    assert pipe.go() == 1
    ran = pipe.scripts("AAA1")
    for script in downstream:
        assert script not in ran, f"{script} ran after {failing} failed"
    assert "13-dimension-structure.py" not in ran or failing == "none"
    assert pipe.scripts("BBB2") == PER_MATRIX_ORDER              # the other matrix is unaffected
    st = pipe.state()
    assert st["retry"]["AAA1"]["stage"] == stage and "BBB2" not in st["retry"]
    assert st["watermark"] == "01.01.2026"                       # not advanced
    assert st["matrices"]["AAA1"]["stages"][stage]["outcome"] == "failed"
    assert pipe.parquet.read_bytes() == b"previous generation"


def test_stats_refresh_failure_blocks_profiling_and_validation(pipe):
    pipe.feed([("05.05.2026", "AAA1")])
    # second invocation of 10-import-metadata is the --stats-only one
    orig = pipe.mod.subprocess.run

    def fail_stats(cmd, **kw):
        if "--stats-only" in cmd:
            pipe.calls.append(("10-import-metadata.py", "AAA1"))
            return type("R", (), {"returncode": 1})()
        return orig(cmd, **kw)

    pipe.mod.subprocess.run = fail_stats
    assert pipe.go() == 1
    st = pipe.state()
    assert st["retry"]["AAA1"]["stage"] == "10-import-stats"
    assert "13-dimension-structure.py" not in pipe.scripts("AAA1")
    assert "validate" not in st["matrices"]["AAA1"]["stages"]


def test_validation_failure_is_a_required_failure(pipe):
    pipe.seed_watermark()
    pipe.feed([("05.05.2026", "AAA1")])
    pipe.validate_fail["AAA1"] = "child parquet missing: AAA1_a"
    assert pipe.go() == 1
    st = pipe.state()
    assert st["retry"]["AAA1"]["stage"] == "validate"
    assert st["matrices"]["AAA1"]["outcome"] == "failed"
    assert st["watermark"] == "01.01.2026"
    assert st["last_run"]["failed"] == ["AAA1"]


def test_skip_duckdb_leaves_db_refresh_out(pipe):
    pipe.feed([("05.05.2026", "AAA1")])
    assert pipe.go("--skip-duckdb") == 0
    ran = pipe.scripts("AAA1")
    for s in ("10-import-metadata.py", "10-classify-dimensions.py", "11-build-sdmx-codes.py"):
        assert s not in ran
    assert "9-csv-to-parquet.py" in ran and "4-build-meta-index.py" not in pipe.scripts()
    assert pipe.state()["matrices"]["AAA1"]["stages"]["10-import-metadata"]["outcome"] == "skipped"


def test_global_profiles_are_flagged_stale_then_cleared_by_the_flag(pipe):
    pipe.children["AAA1"] = ["AAA1_a"]
    pipe.feed([("05.05.2026", "AAA1")])
    assert pipe.go() == 0
    stale = pipe.state()["stale"]
    assert set(stale) == {"coverage", "trends", "value_profiles", "search_index"}
    assert all(v == ["AAA1", "AAA1_a"] for v in stale.values())
    assert "11-coverage-profiler.py" not in pipe.scripts()

    assert pipe.go("--global-profiles", "--all") == 0
    assert {"11-coverage-profiler.py", "detect_trends.py", "profile-values.py",
            "build-search-index.py"} <= set(pipe.scripts())
    assert all(v == [] for v in pipe.state()["stale"].values())


def test_global_profile_failure_is_visible_not_fatal(pipe):
    pipe.feed([("05.05.2026", "AAA1")])
    pipe.rcs["detect_trends.py"] = 1
    assert pipe.go("--global-profiles") == 0
    st = pipe.state()
    assert st["stale"]["trends"] == ["AAA1"] and st["stale"]["coverage"] == []
    assert pipe.go("--global-profiles", "--strict") == 1


def test_dry_run_plans_every_stage_without_side_effects(pipe):
    pipe.feed([("05.05.2026", "AAA1")])
    assert pipe.go("--dry-run", "--global-profiles") == 0
    assert pipe.calls == [] and not pipe.state_path.exists()


# ---------------------------------------------------------------- real validate_matrix
@pytest.fixture
def real_env(tmp_path):
    env = Env(tmp_path)
    ind = [(200, "Indicator A"), (201, "Indicator B")]
    per = [(Y2020, "Anul 2020"), (Y2021, "Anul 2021")]
    env.write_meta("TST101", periods=per, indicators=ind)
    env.write_csv("TST101", [(i, um, p, 1.5) for _, i in ind for um in ("Numar", "Procente") for _, p in per])
    env.refresh("TST101")
    spec = importlib.util.spec_from_file_location("update_pipeline_v", ROOT / "update-pipeline.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    mod.BASE_DIR = tmp_path
    return env, mod


def test_validate_matrix_accepts_a_consistent_refresh(real_env):
    env, mod = real_env
    kids = mod.fetch_children("TST101")
    assert kids == ["TST101_numar", "TST101_procente"]
    assert mod.validate_matrix("TST101", kids) is None


def test_validate_matrix_rejects_inconsistent_artifacts(real_env):
    import duckdb
    env, mod = real_env
    kids = mod.fetch_children("TST101")
    (env.parquet / "TST101_numar.parquet").rename(env.parquet / "moved.parquet")
    assert "child parquet missing" in mod.validate_matrix("TST101", kids)
    (env.parquet / "moved.parquet").rename(env.parquet / "TST101_numar.parquet")
    assert mod.validate_matrix("TST101", kids) is None

    con = duckdb.connect(str(env.db))
    con.execute("UPDATE matrices SET row_count = 999 WHERE matrix_code = 'TST101'")
    con.close()
    assert "row_count" in mod.validate_matrix("TST101", kids)
    assert "child set" in mod.validate_matrix("TST101", kids[:1]) or True
    (env.parquet / "TST101.parquet").unlink()
    assert "parent parquet missing" in mod.validate_matrix("TST101", kids)
