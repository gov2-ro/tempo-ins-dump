"""Audit PKG-PIPELINE A: a split child whose period dimension was relabelled by stage 12
('anual', 'trimestrial', 'lunar') still gets has_time and its year range in matrix_profiles."""
import duckdb

from fix03b_env import Env


def add_child(env, code, period_label, period_column, labels=("Anul 2020", "Anul 2021", "Anul 2022")):
    con = duckdb.connect(str(env.db))
    con.execute("INSERT INTO matrices(matrix_code, matrix_name, context_code, is_split) "
                "VALUES (?, ?, '1', true)", [code, code])
    nid = abs(hash(code)) % 100000 * 10
    for dim_id, dim_code, label, col, opts in (
            (nid, 1, "Sexe", "SEX", ["Masculin", "Feminin"]),
            (nid + 1, 2, period_label, period_column, list(labels))):
        con.execute("INSERT INTO dimensions VALUES (?,?,?,?,?,?)",
                    [dim_id, code, dim_code, label, col, len(opts)])
        for i, o in enumerate(opts):
            con.execute("INSERT INTO dimension_options VALUES (?,?,?,?,?,NULL)",
                        [dim_id * 100 + i, dim_id, dim_id * 100 + i, o, i])
    con.close()


def profile(env, code):
    return env.q("SELECT has_time, time_granularity, time_year_min, time_year_max, archetype "
                 "FROM matrix_profiles WHERE matrix_code = ?", [code])[0]


def test_relabelled_period_dimension_is_time(tmp_path):
    env = Env(tmp_path)
    add_child(env, "TST1_anual", "anual", "TIME_PERIOD")
    add_child(env, "TST1_lunar", "lunar", "TIME_PERIOD",
              labels=("Luna ianuarie 2020", "Luna februarie 2020"))
    env.run("10-classify-dimensions.py", "--matrix", "TST1_anual,TST1_lunar")
    assert profile(env, "TST1_anual") == (True, "annual", 2020, 2022, "demographic")
    assert profile(env, "TST1_lunar")[:4] == (True, "monthly", 2020, 2020)


def test_other_columns_and_undated_options_stay_categorical(tmp_path):
    env = Env(tmp_path)
    add_child(env, "TST2_a", "anual", "CATEG")                     # same label, not the period column
    add_child(env, "TST2_b", "anual", "TIME_PERIOD", labels=("alfa", "beta"))   # no year in any option
    add_child(env, "TST2_c", "anual", "TIME_PERIOD_2")             # the extra period-like column
    env.run("10-classify-dimensions.py", "--matrix", "TST2_a,TST2_b,TST2_c")
    for code in ("TST2_a", "TST2_b", "TST2_c"):
        assert profile(env, code)[0] is False, code
