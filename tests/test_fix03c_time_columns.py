"""Only the observation period becomes TIME_PERIOD. 'Durata ... saptamanii de lucru'
(hours bands), 'ANI/UM' (the indicator's title) and other labels that merely contain
'ani' or 'saptamani' were typed as time, so stage 11 gave them TIME_PERIOD and pushed
'Perioade' to TIME_PERIOD_2 (149 served files). Real scripts on a synthetic tree."""
import json
from pathlib import Path

import pytest

from fix03b_env import Env, Y2020, Y2021

PER = [(Y2020, "Anul 2020"), (Y2021, "Anul 2021")]


def build(tmp_path, label, options):
    e = Env(tmp_path)
    e.write_meta("TST301", periods=PER, indicators=options, ums=((300, "Numar persoane"),))
    f = e.data / "2-metas" / "ro" / "TST301.json"
    m = json.loads(f.read_text())
    m["dimensionsMap"][0]["label"] = label
    f.write_text(json.dumps(m))
    e.write_csv("TST301", [(o, "Numar persoane", p, 10.0 + i) for i, (_, o) in enumerate(options)
                           for _, p in PER])
    e.refresh("TST301", split=False)
    return e


@pytest.mark.parametrize("label,options,concept", [
    ("Durata obisnuita a saptamanii de lucru - program partial",
     [(400, "01 - 10 ore"), (401, "11 - 20 ore")], "USUAL_WEEKLY_HOURS"),
    ("Durata efectiva a saptamanii de lucru", [(400, "0 ore"), (401, "1 - 35 ore")], "ACTUAL_WEEKLY_HOURS"),
    ("ANI/UM", [(400, "Productivitatea resurselor materiale")], "INDICATOR"),
    ("Ani de baza", [(400, "An baza 1998"), (401, "An baza 2000")], "BASE_YEAR"),
])
def test_only_the_period_dimension_is_time(tmp_path, label, options, concept):
    e = build(tmp_path, label, options)
    cols = [r[0] for r in e.pq("TST301", "DESCRIBE SELECT * FROM read_parquet('{p}')")]
    assert cols == [concept, "UNIT_MEASURE", "TIME_PERIOD", "OBS_VALUE"]
    assert sorted(r[0] for r in e.pq("TST301", "SELECT DISTINCT TIME_PERIOD FROM read_parquet('{p}')")) \
        == ["2020", "2021"]
    assert e.q("SELECT DISTINCT p.dim_type FROM dimensions d JOIN dimension_options o USING (dimension_id) "
               "JOIN dimension_options_parsed p USING (nom_item_id) WHERE d.matrix_code = 'TST301' "
               "AND d.dim_code = 1") == [("indicator",)]


def test_reset_step_repairs_an_existing_misclassified_matrix(tmp_path):
    """The corpus state: canonical names already in `dimensions`, hours bands in
    TIME_PERIOD. A targeted stage 11 keeps such rows, so repair-corpus resets the parent
    to its imported state and the fixed stages rebuild it."""
    import importlib.util
    import duckdb
    e = build(tmp_path, "Durata obisnuita a saptamanii de lucru",
              [(400, "01 - 10 ore"), (401, "11 - 20 ore")])
    con = duckdb.connect(str(e.db))                        # recreate the broken generation
    old = dict(con.execute("SELECT sdmx_column_name, old_column_name FROM sdmx_column_map "
                           "WHERE matrix_code = 'TST301'").fetchall())
    con.execute("UPDATE sdmx_column_map SET sdmx_column_name = 'TIME_PERIOD' WHERE old_column_name = ?",
                [old["USUAL_WEEKLY_HOURS"]])
    con.execute("UPDATE sdmx_column_map SET sdmx_column_name = 'TIME_PERIOD_2' WHERE old_column_name = ?",
                [old["TIME_PERIOD"]])
    con.execute("UPDATE dimension_options_parsed SET dim_type = 'time' WHERE nom_item_id IN (400, 401)")
    con.close()
    e.canonicalize_dims("TST301")
    e.run("9-csv-to-parquet.py", "--matrix", "TST301", "--force")
    assert [r[0] for r in e.pq("TST301", "DESCRIBE SELECT * FROM read_parquet('{p}')")][:3] == \
        ["TIME_PERIOD", "UNIT_MEASURE", "TIME_PERIOD_2"]

    spec = importlib.util.spec_from_file_location(
        "repair_tc", Path(__file__).resolve().parent.parent / "scripts" / "repair-corpus.py")
    rc = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(rc)
    con = duckdb.connect(str(e.db), read_only=True)
    plan = rc.plan_time_columns(con, {"files": {"TST301": {}}})
    con.close()
    assert plan["problems"] == [] and plan["items"][0]["retyped_options"] == [400, 401]
    rc.apply_time_columns(plan, tmp_path / "elsewhere", e.data)
    for step in ("10-classify-dimensions.py", "11-build-sdmx-codes.py"):
        e.run(step, "--matrix", "TST301")
    e.run("9-csv-to-parquet.py", "--matrix", "TST301", "--force")
    assert [r[0] for r in e.pq("TST301", "DESCRIBE SELECT * FROM read_parquet('{p}')")] == \
        ["USUAL_WEEKLY_HOURS", "UNIT_MEASURE", "TIME_PERIOD", "OBS_VALUE"]
    assert sorted(r[0] for r in e.pq("TST301", "SELECT DISTINCT TIME_PERIOD FROM read_parquet('{p}')")) \
        == ["2020", "2021"]
