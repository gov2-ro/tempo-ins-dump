"""FIX-03 phase 2a: 12-split-datasets.py regenerates a parent's children as an atomic set.
Real stage scripts on a synthetic scratch tree; failures are injected by monkeypatching
functions of the loaded stage module."""
import pytest

from fix03b_env import Env, Y2020, Y2021, Y2022

IND = [(200, "Indicator A"), (201, "Indicator B")]
PER1 = [(Y2020, "Anul 2020"), (Y2021, "Anul 2021")]
PER2 = PER1 + [(Y2022, "Anul 2022")]
UM3 = [(300, "Numar"), (301, "Procente"), (302, "Lei")]
UM2 = UM3[:2]


def write(env, code, periods, ums):
    env.write_meta(code, periods=periods, indicators=IND, ums=ums)
    env.write_csv(code, [(i, um, p, 1.0 + n) for n, (_, i) in enumerate(IND)
                         for _, um in ums for _, p in periods])


@pytest.fixture
def env(tmp_path):
    e = Env(tmp_path)
    write(e, "TST101", PER1, UM3)
    write(e, "TST202", PER1, UM2)
    e.refresh("TST101")
    e.refresh("TST202")
    return e


def state(env, parent):
    q = env.q
    return {
        "splits": q("SELECT * FROM dataset_splits WHERE parent_matrix_code = ? ORDER BY 2", [parent]),
        "matrices": q("SELECT * EXCLUDE (created_at) FROM matrices WHERE parent_matrix_code = ? ORDER BY 1",
                      [parent]),
        "dims": q("SELECT d.* FROM dimensions d JOIN matrices m USING (matrix_code) "
                  "WHERE m.parent_matrix_code = ? ORDER BY dimension_id", [parent]),
        "opts": q("SELECT o.* FROM dimension_options o JOIN dimensions d USING (dimension_id) "
                  "JOIN matrices m USING (matrix_code) WHERE m.parent_matrix_code = ? ORDER BY option_id",
                  [parent]),
        "files": {p.name: p.read_bytes() for p in env.parquet.glob(f"{parent}_*.parquet")},
        "leftovers": sorted(p.name for p in env.parquet.iterdir() if p.name.startswith(".")),
    }


def child_codes(env, parent):
    return [r[0] for r in env.q("SELECT sub_matrix_code FROM dataset_splits "
                                "WHERE parent_matrix_code = ? ORDER BY 1", [parent])]


def new_generation(env, periods=PER2, ums=UM3):
    """Parent refreshed (new period / fewer UMs) but children not regenerated yet."""
    write(env, "TST101", periods, ums)
    env.refresh("TST101", split=False)


def test_baseline_children(env):
    assert child_codes(env, "TST101") == ["TST101_lei", "TST101_numar", "TST101_procente"]
    assert state(env, "TST101")["leftovers"] == []


def test_staging_failure_mid_set_preserves_previous_generation(env, monkeypatch):
    new_generation(env)
    before, sibling = state(env, "TST101"), state(env, "TST202")
    parent_bytes = (env.parquet / "TST101.parquet").read_bytes()

    mod = env.load_module("12-split-datasets.py")
    real, calls = mod._nom_ids_to_sdmx, []

    def flaky(conn, ids):
        calls.append(1)
        if len(calls) == 2:                      # first child staged, second blows up
            raise RuntimeError("disk full")
        return real(conn, ids)

    monkeypatch.setattr(mod, "_nom_ids_to_sdmx", flaky)
    with pytest.raises(SystemExit) as exc:
        mod.main(["--matrix", "TST101"])
    assert exc.value.code == 1
    assert state(env, "TST101") == before        # files, matrices, dimensions, options, splits
    assert state(env, "TST202") == sibling
    assert (env.parquet / "TST101.parquet").read_bytes() == parent_bytes
    # and none of the children knows the new period yet: it is the OLD usable generation
    assert all(len(env.pq(c)) == 4 for c in child_codes(env, "TST101"))


def test_swap_failure_after_files_moved_rolls_back_files_and_rows(env, monkeypatch):
    new_generation(env)
    before = state(env, "TST101")

    mod = env.load_module("12-split-datasets.py")
    real, n = mod.register_sub_dataset, []

    def failing_register(conn, rule, sub):
        n.append(sub["sub_code"])
        if len(n) == 2:
            raise RuntimeError("registration blew up")
        return real(conn, rule, sub)

    monkeypatch.setattr(mod, "register_sub_dataset", failing_register)
    with pytest.raises(SystemExit) as exc:
        mod.main(["--matrix", "TST101"])
    assert exc.value.code == 1
    assert len(n) == 2                           # it really failed mid-registration
    assert state(env, "TST101") == before        # old rows re-inserted, old files moved back

    # the very same run without the fault succeeds and installs the new generation
    monkeypatch.setattr(mod, "register_sub_dataset", real)
    mod.SPLIT_FAILURES.clear()
    mod.main(["--matrix", "TST101"])
    assert all(len(env.pq(c)) == 6 for c in child_codes(env, "TST101"))
    assert state(env, "TST101")["leftovers"] == []


def test_successful_swap_replaces_whole_set_and_retires_stale_child(env):
    sibling = state(env, "TST202")
    old_lei = (env.parquet / "TST101_lei.parquet")
    assert old_lei.exists()
    new_generation(env, periods=PER2, ums=UM2)    # INS dropped the "Lei" unit
    env.run("12-split-datasets.py", "--matrix", "TST101")

    assert child_codes(env, "TST101") == ["TST101_numar", "TST101_procente"]
    assert not old_lei.exists()                   # retired together with its rows
    assert env.q("SELECT COUNT(*) FROM matrices WHERE matrix_code = 'TST101_lei'") == [(0,)]
    assert env.q("SELECT COUNT(*) FROM dimensions WHERE matrix_code = 'TST101_lei'") == [(0,)]
    for c in child_codes(env, "TST101"):
        assert len(env.pq(c)) == 6                # 2 indicators x 3 periods
        assert ("2022",) in env.pq(c, "SELECT DISTINCT TIME_PERIOD FROM read_parquet('{p}')")
    assert state(env, "TST101")["leftovers"] == []
    assert state(env, "TST202") == sibling


def test_rerun_never_duplicates_and_never_splits_children(env):
    for _ in range(2):
        env.run("12-split-datasets.py")           # every parent, twice
    codes = child_codes(env, "TST101") + child_codes(env, "TST202")
    assert len(codes) == len(set(codes)) == 3 + 2
    assert env.q("SELECT COUNT(*) FROM matrices WHERE is_split") == [(5,)]
    assert env.q("SELECT COUNT(*), COUNT(DISTINCT sub_matrix_code) FROM dataset_splits") == [(5, 5)]
    assert env.q("SELECT COUNT(*) FROM matrices WHERE matrix_code LIKE '%\\_%\\_%' ESCAPE '\\'") == [(0,)]
    ids = env.q("SELECT COUNT(*), COUNT(DISTINCT dimension_id) FROM dimensions")[0]
    assert ids[0] == ids[1]
    ids = env.q("SELECT COUNT(*), COUNT(DISTINCT option_id) FROM dimension_options")[0]
    assert ids[0] == ids[1]
    before = state(env, "TST101")
    r = env.run("12-split-datasets.py", "--matrix", "TST101_numar")   # a child is not a parent
    assert r.returncode == 0 and state(env, "TST101") == before


def test_code_collision_with_a_real_matrix_is_refused_and_nothing_changes(env):
    new_generation(env)
    con = __import__("duckdb").connect(str(env.db))
    con.execute("INSERT INTO matrices (matrix_code, matrix_name, is_split) VALUES ('TST101_extra', 'x', false)")
    con.close()
    before = state(env, "TST101")
    mod = env.load_module("12-split-datasets.py")
    # make the new set want a code that belongs to a real, non-child matrix
    real = mod.generate_sub_matrix_code
    mod.generate_sub_matrix_code = lambda m, suf: "TST101_extra" if suf == "lei" else real(m, suf)
    with pytest.raises(SystemExit) as exc:
        mod.main(["--matrix", "TST101"])
    assert exc.value.code == 1
    assert state(env, "TST101") == before
    assert env.q("SELECT matrix_name FROM matrices WHERE matrix_code = 'TST101_extra'") == [("x",)]


def test_dry_run_leaves_live_children_alone(env):
    before = state(env, "TST101")
    env.run("12-split-datasets.py", "--matrix", "TST101", "--dry-run")
    assert state(env, "TST101") == before
