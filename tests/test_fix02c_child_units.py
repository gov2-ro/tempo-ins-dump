"""10-classify-dimensions profiles split children whose unit was the split key: the
unit type comes from the split value, so a 'procente' child is never summed as a
count (FIX-02 measure classification). Real scripts on a synthetic scratch tree."""
import pytest

from fix03b_env import Env, Y2020, Y2021

IND = [(200, "Indicator A"), (201, "Indicator B")]
PER = [(Y2020, "Anul 2020"), (Y2021, "Anul 2021")]
UMS = [(300, "Numar"), (301, "Procente"), (302, "Lei")]


@pytest.fixture
def env(tmp_path):
    e = Env(tmp_path)
    e.write_meta("TST101", periods=PER, indicators=IND, ums=UMS)
    e.write_csv("TST101", [(i, um, p, 1.0 + n) for n, (_, i) in enumerate(IND)
                           for _, um in UMS for _, p in PER])
    e.refresh("TST101")
    return e


def test_unit_split_children_get_their_unit_type(env):
    kids = [r[0] for r in env.q("SELECT sub_matrix_code FROM dataset_splits ORDER BY 1")]
    assert kids == ["TST101_lei", "TST101_numar", "TST101_procente"]
    assert env.q("SELECT COUNT(*) FROM dimensions WHERE matrix_code = 'TST101_procente' "
                 "AND dim_column_name IN ('UNIT_MEASURE', 'um_nom_id')") == [(0,)]   # unit was the split key
    env.run("10-classify-dimensions.py", "--matrix", ",".join(kids))
    got = dict(env.q("SELECT matrix_code, primary_unit_type FROM matrix_profiles "
                     "WHERE matrix_code LIKE 'TST101_%'"))
    assert got == {"TST101_lei": "currency", "TST101_numar": "count", "TST101_procente": "percentage"}

