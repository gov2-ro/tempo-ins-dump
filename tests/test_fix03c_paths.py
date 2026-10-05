"""Global profilers resolve parquet files by matrix code, not by the stored
matrices.parquet_path (absolute paths from another tree, some into the deleted
data/parquet-v3/). Real scripts on a synthetic scratch tree.

11-coverage-profiler.py uses the same corpus_parquet() lookup but still matches values
by legacy *_nom_id ids, so it finds no years in SDMX files (backlog); not tested here."""
import duckdb
import pytest

from fix03b_env import Env, Y2020, Y2021

IND = [(200, "Indicator A"), (201, "Indicator B")]
PER = [(Y2020, "Anul 2020"), (Y2021, "Anul 2021")]


@pytest.fixture
def env(tmp_path):
    e = Env(tmp_path)
    e.write_meta("TST101", periods=PER, indicators=IND, ums=((300, "Numar"),))
    e.write_csv("TST101", [(i, "Numar", p, 10.0 * (n + 1) + k)
                           for n, (_, i) in enumerate(IND) for k, (_, p) in enumerate(PER)])
    e.refresh("TST101", split=False)
    con = duckdb.connect(str(e.db))
    con.execute("UPDATE matrices SET parquet_path = ?, is_canonical = TRUE",
                [str(tmp_path / "gone" / "parquet-v3" / "ro" / "TST101.parquet")])
    con.close()
    return e


def test_value_profiles_read_the_trees_own_file(env):
    env.run("scripts/profile-values.py")
    assert env.q("SELECT row_count, val_min, val_max FROM dataset_value_profiles "
                 "WHERE matrix_code = 'TST101'") == [(4, 10.0, 21.0)]


def test_trends_read_the_trees_own_file(env):
    env.run("detect_trends.py")
    assert env.q("SELECT COUNT(*) FROM dataset_trends WHERE matrix_code = 'TST101'") == [(1,)]
