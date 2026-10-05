"""FIX-03 phase 2a: refreshing an existing matrix end to end (real stage scripts on a
synthetic scratch tree) and targeted refresh leaving other matrices untouched."""
import pytest

from fix03b_env import Env, Y2020, Y2021, Y2022

pytestmark = pytest.mark.filterwarnings("ignore")

IND_V1 = [(200, "Indicator A"), (201, "Indicator B")]
IND_V2 = IND_V1 + [(202, "Indicator C")]                   # new option
PER_V1 = [(Y2020, "Anul 2020"), (Y2021, "Anul 2021")]
PER_V2 = PER_V1 + [(Y2022, "Anul 2022")]                    # new period


def rows(inds, pers):
    return [(i, um, p, 1.5 + n) for n, (_, i) in enumerate(inds)
            for um in ("Numar", "Procente") for _, p in pers]


@pytest.fixture(params=["fresh-import", "canonical-dims"])
def env(tmp_path, request):
    """canonical-dims mimics most of the real corpus: dim_column_name already SDMX."""
    e = Env(tmp_path)
    # TST101: will be refreshed.  TST202: bystander (shares year ids, own indicators)
    e.write_meta("TST101", periods=PER_V1, indicators=IND_V1)
    e.write_csv("TST101", rows(IND_V1, PER_V1))
    e.write_meta("TST202", periods=PER_V1, indicators=[(210, "Other X"), (211, "Other Y")])
    e.write_csv("TST202", rows([(0, "Other X"), (0, "Other Y")], PER_V1))
    e.refresh("TST101")
    e.refresh("TST202")
    if request.param == "canonical-dims":
        e.canonicalize_dims("TST101", "TST202")
    return e


def fingerprint(env, code):
    """Everything the DB and corpus hold for one matrix, comparable byte for byte."""
    return {
        "matrices": env.q("SELECT * EXCLUDE (created_at) FROM matrices WHERE matrix_code = ?", [code]),
        "dimensions": env.q("SELECT dimension_id, dim_code, dim_label, dim_column_name, option_count "
                            "FROM dimensions WHERE matrix_code = ? ORDER BY dim_code", [code]),
        "options": env.q("SELECT o.option_id, d.dim_code, o.nom_item_id, o.option_label, o.option_offset "
                         "FROM dimension_options o JOIN dimensions d USING (dimension_id) "
                         "WHERE d.matrix_code = ? ORDER BY 1", [code]),
        "colmap": env.q("SELECT * FROM sdmx_column_map WHERE matrix_code = ? ORDER BY 2", [code]),
        "profile": env.q("SELECT * FROM matrix_profiles WHERE matrix_code = ?", [code]),
        "parquet": (env.parquet / f"{code}.parquet").read_bytes(),
        "children": env.q("SELECT * FROM dataset_splits WHERE parent_matrix_code = ? ORDER BY 2", [code]),
    }


def test_baseline_pipeline_builds_parent_and_children(env):
    assert len(env.pq("TST101")) == 8
    assert [r[0] for r in env.q("SELECT sub_matrix_code FROM dataset_splits "
                                "WHERE parent_matrix_code = 'TST101' ORDER BY 1")] == \
        ["TST101_numar", "TST101_procente"]


def test_refresh_existing_matrix_new_option_and_new_period(env):
    other_before = fingerprint(env, "TST202")
    colmap_before = env.q("SELECT * FROM sdmx_column_map WHERE matrix_code = 'TST101' ORDER BY 2")

    env.write_meta("TST101", periods=PER_V2, indicators=IND_V2)
    env.write_csv("TST101", rows(IND_V2, PER_V2))
    env.refresh("TST101")
    env.run("13-dimension-structure.py", "--matrix", "TST101,TST101_numar,TST101_procente")
    # coverage / trends / value profiles have no per-matrix mode (whole-table scripts)
    for script in ("11-coverage-profiler.py", "detect_trends.py", "scripts/profile-values.py"):
        env.run(script)
    for code in ("TST101", "TST101_numar", "TST101_procente"):
        env.run("generate_view_profiles.py", "--matrix", code)

    # dimension options (the old existing-record guard would have skipped these)
    labels = {r[0] for r in env.q(
        "SELECT o.option_label FROM dimension_options o JOIN dimensions d USING (dimension_id) "
        "WHERE d.matrix_code = 'TST101'")}
    assert {"Indicator C", "Anul 2022"} <= labels
    assert env.q("SELECT dim_code, option_count FROM dimensions WHERE matrix_code = 'TST101' "
                 "ORDER BY 1") == [(1, 3), (2, 2), (3, 3)]
    # code maps: new ids coded, the column map still maps the same columns
    codes = dict(env.q("SELECT nom_item_id, sdmx_value FROM sdmx_codes WHERE nom_item_id IN (202, ?)",
                       [Y2022]))
    assert codes == {202: "Indicator C", Y2022: "2022"}
    assert colmap_before == env.q("SELECT * FROM sdmx_column_map WHERE matrix_code = 'TST101' ORDER BY 2")
    assert ("value", "OBS_VALUE") in [(r[1], r[2]) for r in colmap_before]   # legacy keys kept
    # parquet: new option and period present, every cell matched (no raw labels left)
    assert len(env.pq("TST101")) == 18
    assert ("2022",) in env.pq("TST101", "SELECT DISTINCT TIME_PERIOD FROM read_parquet('{p}')")
    assert ("Indicator C",) in env.pq("TST101", "SELECT DISTINCT INDICATORI FROM read_parquet('{p}')")
    # parent metadata row follows the new file
    row_count, size, path = env.q("SELECT row_count, file_size_bytes, parquet_path FROM matrices "
                                  "WHERE matrix_code = 'TST101'")[0]
    assert row_count == 18 and size == (env.parquet / "TST101.parquet").stat().st_size
    assert path == str(env.parquet / "TST101.parquet")
    # children: rebuilt from the new parent, registered, options include the new period
    for child in ("TST101_numar", "TST101_procente"):
        assert len(env.pq(child)) == 9
        assert env.q("SELECT row_count, is_split, parent_matrix_code FROM matrices WHERE matrix_code = ?",
                     [child]) == [(9, True, "TST101")]
        child_labels = {r[0] for r in env.q(
            "SELECT o.option_label FROM dimension_options o JOIN dimensions d USING (dimension_id) "
            "WHERE d.matrix_code = ?", [child])}
        assert {"Indicator C", "Anul 2022"} <= child_labels
        assert ("2022",) in env.pq(child, "SELECT DISTINCT TIME_PERIOD FROM read_parquet('{p}')")
    assert env.q("SELECT COUNT(*) FROM dataset_splits WHERE parent_matrix_code = 'TST101'") == [(2,)]
    # profiling reflects the refresh: structure rows for parent + children, view profiles written
    prof = env.q("SELECT DISTINCT matrix_code FROM dimension_structure ORDER BY 1")
    assert {r[0] for r in prof} >= {"TST101", "TST101_numar", "TST101_procente"}
    for code, expected in (("TST101", 3), ("TST101_numar", 3), ("TST101_procente", 3)):
        levels = env.q("SELECT n_effective, levels FROM dimension_structure WHERE matrix_code = ? "
                       "AND dim_column = 'INDICATORI'", [code])
        assert levels and levels[0][0] == expected and "Indicator C" in levels[0][1]
    assert env.q("SELECT actual_rows FROM dataset_coverage WHERE matrix_code = 'TST101'") == [(18,)]
    vp = env.data / "corpus" / "view-profiles"
    assert {f.stem for f in vp.glob("*.json")} >= {"TST101", "TST101_numar", "TST101_procente"}
    assert "Indicator C" in (vp / "TST101.json").read_text() or "2022" in (vp / "TST101.json").read_text()

    # the bystander is byte-identical in every table and file
    assert fingerprint(env, "TST202") == other_before


def test_refresh_is_idempotent_and_never_duplicates(env):
    before = fingerprint(env, "TST101")
    ids_before = env.q("SELECT COUNT(*), COUNT(DISTINCT option_id) FROM dimension_options")
    for _ in range(2):
        env.refresh("TST101")
    after = fingerprint(env, "TST101")
    assert after["options"] == before["options"] and after["dimensions"] == before["dimensions"]
    assert env.q("SELECT COUNT(*), COUNT(DISTINCT option_id) FROM dimension_options") == ids_before
    assert env.q("SELECT COUNT(*), COUNT(DISTINCT sub_matrix_code) FROM dataset_splits") == [(4, 4)]


def test_removed_option_and_changed_label_are_reconciled(env):
    env.write_meta("TST101", periods=[(Y2020, "Anul 2020")],
                   indicators=[(200, "Indicator A renamed"), (201, "Indicator B")])
    env.run("10-import-metadata.py", "--matrix", "TST101")
    opts = env.q("SELECT o.nom_item_id, o.option_label FROM dimension_options o JOIN dimensions d "
                 "USING (dimension_id) WHERE d.matrix_code = 'TST101' AND d.dim_code IN (1, 3) ORDER BY 1")
    assert opts == [(100, "Anul 2020"), (200, "Indicator A renamed"), (201, "Indicator B")]


def test_dimension_relabel_and_indexed_matrix_change_survive_fk(env):
    """dim_label / mat_active are indexed: a plain UPDATE hits DuckDB's FK limitation."""
    data = meta_dict = __import__("fix03b_env").meta("TST101", periods=PER_V1, indicators=IND_V1)
    data["dimensionsMap"][0]["label"] = "Indicatori noi"
    data["details"]["matActive"] = 0
    data["details"]["matMaxDim"] = 4
    import json
    (env.data / "2-metas" / "ro" / "TST101.json").write_text(json.dumps(data), encoding="utf-8")
    other = fingerprint(env, "TST202")
    env.run("10-import-metadata.py", "--matrix", "TST101")
    assert env.q("SELECT mat_active, mat_max_dim FROM matrices WHERE matrix_code = 'TST101'") == [(False, 4)]
    assert env.q("SELECT dim_label, option_count FROM dimensions WHERE matrix_code = 'TST101' "
                 "AND dim_code = 1") == [("Indicatori noi", 2)]
    assert env.q("SELECT COUNT(*) FROM dimensions WHERE matrix_code = 'TST101'") == [(3,)]
    assert fingerprint(env, "TST202") == other


def test_targeted_stages_leave_other_matrix_byte_identical(env):
    other = fingerprint(env, "TST202")
    shared = "SELECT * FROM {t} WHERE nom_item_id IN (100, 101, 300, 301) ORDER BY nom_item_id"
    parsed_before = env.q(shared.format(t="dimension_options_parsed"))
    codes_before = env.q(shared.format(t="sdmx_codes"))
    n_parsed = env.q("SELECT COUNT(*) FROM dimension_options_parsed")[0][0]

    env.write_meta("TST101", periods=PER_V2, indicators=IND_V2)
    env.run("10-import-metadata.py", "--matrix", "TST101")
    env.run("10-classify-dimensions.py", "--matrix", "TST101")
    env.run("11-build-sdmx-codes.py", "--matrix", "TST101")

    assert fingerprint(env, "TST202") == other
    assert env.q(shared.format(t="dimension_options_parsed")) == parsed_before   # not rewritten
    assert env.q(shared.format(t="sdmx_codes")) == codes_before
    assert env.q("SELECT COUNT(*) FROM dimension_options_parsed")[0][0] > n_parsed  # table kept, grown
    assert env.q("SELECT COUNT(*) FROM matrix_profiles") == [(2,)]                   # never dropped


def test_targeted_stages_fail_loudly_on_unknown_matrix(env):
    assert env.run("10-import-metadata.py", "--matrix", "NOPE1", check=False).returncode == 1
    assert env.run("10-classify-dimensions.py", "--matrix", "NOPE1", check=False).returncode == 1
    assert env.run("11-build-sdmx-codes.py", "--matrix", "NOPE1", check=False).returncode == 1


def test_dry_run_is_side_effect_free(env):
    import hashlib

    def snap():
        files = {str(p.relative_to(env.data)): hashlib.sha256(p.read_bytes()).hexdigest()
                 for p in sorted(env.data.rglob("*")) if p.is_file() and "logs" not in p.parts}
        return files
    env.write_meta("TST101", periods=PER_V2, indicators=IND_V2)
    before = snap()
    env.run("10-import-metadata.py", "--matrix", "TST101", "--dry-run")
    env.run("11-build-sdmx-codes.py", "--matrix", "TST101", "--dry-run")
    env.run("12-split-datasets.py", "--matrix", "TST101", "--dry-run")
    assert snap() == before
    assert not [p for p in env.parquet.iterdir() if p.name.startswith(".")]


def test_global_import_reconciles_only_what_changed(env):
    idx = env.data / "1-indexes" / "ro"
    (idx / "context.csv").write_text("context_code,parentCode,level,context_name\n1,,1,Ctx\n")
    (idx / "matrices.csv").write_text("code,name\nTST101,One\nTST202,Two\n")
    other = fingerprint(env, "TST202")
    env.write_meta("TST101", periods=PER_V2, indicators=IND_V2)
    r = env.run("10-import-metadata.py")
    assert "Changed: 1" in r.stdout and "Unchanged: 1" in r.stdout
    assert {"Indicator C", "Anul 2022"} <= {x[0] for x in env.q(
        "SELECT o.option_label FROM dimension_options o JOIN dimensions d USING (dimension_id) "
        "WHERE d.matrix_code = 'TST101'")}
    assert fingerprint(env, "TST202") == other
    assert "Changed: 0" in env.run("10-import-metadata.py").stdout       # converged: a no-op


def test_real_command_line_smoke(env):
    """The same targeted refresh through real subprocesses (TEMPO_PIPELINE_DATA_DIR)."""
    env.write_meta("TST101", periods=PER_V2, indicators=IND_V2)
    env.write_csv("TST101", rows(IND_V2, PER_V2))
    for script, extra in (("10-import-metadata.py", []), ("10-classify-dimensions.py", []),
                          ("11-build-sdmx-codes.py", []), ("9-csv-to-parquet.py", ["--force"]),
                          ("12-split-datasets.py", [])):
        env.run(script, "--matrix", "TST101", *extra, subprocess_mode=True)
    assert len(env.pq("TST101")) == 18
