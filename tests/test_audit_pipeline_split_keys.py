"""Audit PKG-PIPELINE B: a split child may drop a key column only when it sums the rows
to the remaining key and the measure is additive with a verified column structure.
Synthetic scratch tree; the real 12-split-datasets.py runs against it."""
import duckdb

from fix03b_env import Env

PARENT = "LOC101"
# county -> localities; two counties, two localities each, two years
LOCALITIES = {"C1": ["L1", "L2"], "C2": ["L3", "L4"]}
YEARS = ["2020", "2021"]


def build(env: Env, unit_type: str, name: str, locality_additive, aggregate=None):
    rows = []
    for county, locs in LOCALITIES.items():
        for i, loc in enumerate(locs, 1):
            for y in YEARS:
                rows.append((county, loc, y, "NR", float(i * 10 + int(y) % 10)))
    if aggregate:
        for county in LOCALITIES:
            for y in YEARS:   # a roll-up option INS publishes next to the localities
                rows.append((county, aggregate, y, "NR", 999.0))
    pq = duckdb.connect()
    pq.execute("CREATE TABLE t(REF_AREA VARCHAR, REF_AREA_2 VARCHAR, TIME_PERIOD VARCHAR, "
               "UNIT_MEASURE VARCHAR, OBS_VALUE DOUBLE)")
    pq.executemany("INSERT INTO t VALUES (?,?,?,?,?)", rows)
    pq.execute(f"COPY t TO '{env.parquet / (PARENT + '.parquet')}' (FORMAT PARQUET)")
    pq.close()

    con = duckdb.connect(str(env.db))
    con.execute("INSERT INTO matrices(matrix_code, matrix_name, context_code) VALUES (?, ?, '1')",
                [PARENT, name])
    dims = [(1, "Judete", "REF_AREA"), (2, "Localitati ", "REF_AREA_2"), (3, "Ani", "TIME_PERIOD"),
            (4, "UM: Numar", "UNIT_MEASURE")]
    for code, label, col in dims:
        con.execute("INSERT INTO dimensions VALUES (?,?,?,?,?,1)", [code, PARENT, code, label, col])
    con.execute("CREATE TABLE dimension_options_parsed(nom_item_id INTEGER, dim_type VARCHAR, "
                "geo_level VARCHAR, age_min INTEGER, age_max INTEGER, year INTEGER, quarter INTEGER, "
                "month INTEGER, time_granularity VARCHAR)")
    con.execute("CREATE TABLE sdmx_column_map(matrix_code VARCHAR, old_column_name VARCHAR, "
                "sdmx_column_name VARCHAR, dim_type VARCHAR)")
    con.execute("CREATE TABLE matrix_profiles(matrix_code VARCHAR PRIMARY KEY, primary_unit_type VARCHAR)")
    con.execute("INSERT INTO matrix_profiles VALUES (?, ?)", [PARENT, unit_type])
    con.execute("CREATE TABLE dimension_structure(matrix_code VARCHAR, dim_column VARCHAR, dim_type VARCHAR, "
                "levels VARCHAR, default_level VARCHAR, n_levels INTEGER, aggregate_value VARCHAR, "
                "aggregate_verified BOOLEAN, additive BOOLEAN, nests_in VARCHAR, n_effective INTEGER, "
                "discrimination DOUBLE, dominance DOUBLE, source VARCHAR, confidence VARCHAR, "
                "created_at TIMESTAMP DEFAULT current_timestamp)")
    con.execute("INSERT INTO dimension_structure(matrix_code, dim_column, dim_type, levels, n_levels, "
                "aggregate_value, aggregate_verified, additive, source, confidence) "
                "VALUES (?, 'REF_AREA_2', 'geo', '[]', 0, ?, ?, ?, 'flat', 'flat')",
                [PARENT, aggregate, aggregate is not None, locality_additive])
    con.close()


def children(env):
    return [r[0] for r in env.q("SELECT sub_matrix_code FROM dataset_splits "
                                "WHERE parent_matrix_code = ? ORDER BY 1", [PARENT])]


def test_additive_verified_column_is_aggregated_with_unique_grain(tmp_path):
    env = Env(tmp_path)
    build(env, "count", "Nascuti vii pe judete si localitati", True)
    env.run("12-split-datasets.py", "--matrix", PARENT)
    assert children(env) == [f"{PARENT}_judet", f"{PARENT}_localitate"]
    rows = env.pq(f"{PARENT}_judet", "SELECT REF_AREA, TIME_PERIOD, OBS_VALUE, "
                  "COUNT(*) OVER (PARTITION BY REF_AREA, TIME_PERIOD, UNIT_MEASURE) "
                  "FROM read_parquet('{p}') ORDER BY 1, 2")
    assert all(r[3] == 1 for r in rows)                       # unique grain
    assert [r[:3] for r in rows] == [("C1", "2020", 30.0), ("C1", "2021", 32.0),
                                     ("C2", "2020", 30.0), ("C2", "2021", 32.0)]
    cols = [c[0] for c in env.pq(f"{PARENT}_judet", "DESCRIBE SELECT * FROM read_parquet('{p}')")]
    assert "REF_AREA_2" not in cols and cols[-1] == "OBS_VALUE"
    assert len(env.pq(f"{PARENT}_localitate")) == 8           # locality child untouched


def test_verified_rollup_option_is_not_counted_twice(tmp_path):
    env = Env(tmp_path)
    build(env, "count", "Nascuti vii pe judete si localitati", True, aggregate="TOTAL")
    env.run("12-split-datasets.py", "--matrix", PARENT)
    rows = env.pq(f"{PARENT}_judet", "SELECT OBS_VALUE FROM read_parquet('{p}') WHERE REF_AREA = 'C1' "
                  "AND TIME_PERIOD = '2020'")
    assert rows == [(30.0,)]                                   # 10 + 20, without the 999 roll-up


def test_average_measure_gets_no_county_child(tmp_path, caplog):
    env = Env(tmp_path)
    build(env, "currency", "Castigul salarial mediu pe judete si localitati", True)
    env.run("12-split-datasets.py", "--matrix", PARENT, "--dry-run")
    assert "no county-level child" in caplog.text and "non_additive" in caplog.text   # reason logged
    env.run("12-split-datasets.py", "--matrix", PARENT)
    # the locality child is kept; the county child is not generated
    assert children(env) == [f"{PARENT}_localitate"]
    assert not (env.parquet / f"{PARENT}_judet.parquet").exists()


def test_unverified_column_structure_gets_no_county_child(tmp_path):
    env = Env(tmp_path)
    build(env, "count", "Nascuti vii pe judete si localitati", None)
    env.run("12-split-datasets.py", "--matrix", PARENT)
    assert children(env) == [f"{PARENT}_localitate"]


def test_previous_county_child_is_removed_when_policy_refuses(tmp_path):
    env = Env(tmp_path)
    build(env, "count", "Nascuti vii pe judete si localitati", True)
    env.run("12-split-datasets.py", "--matrix", PARENT)
    assert f"{PARENT}_judet" in children(env)
    con = duckdb.connect(str(env.db))
    con.execute("UPDATE dimension_structure SET additive = NULL")
    con.close()
    env.run("12-split-datasets.py", "--matrix", PARENT)
    assert children(env) == [f"{PARENT}_localitate"]
    assert not (env.parquet / f"{PARENT}_judet.parquet").exists()


def _cross(env, additive, tmp_path):
    """SOM101E-style: hierarchy x time-granularity rules through the cross-product path."""
    build(env, "count", "Someri pe judete si localitati", additive)
    con = duckdb.connect(str(env.db))
    con.execute("CREATE TABLE sdmx_codes(nom_item_id INTEGER, sdmx_value VARCHAR)")
    con.execute("INSERT INTO sdmx_codes VALUES (1, '2020'), (2, '2021')")
    con.close()
    mod = env.load_module("12-split-datasets.py")
    from split_rules import SplitGroup, SplitRule
    hier = SplitRule(PARENT, "hierarchy", "REF_AREA_2", 2,
                     [SplitGroup("judet", [], {}), SplitGroup("localitate", [], {})])
    time = SplitRule(PARENT, "mixed_time_granularity", "TIME_PERIOD", 3,
                     [SplitGroup("a", [1], {}), SplitGroup("b", [2], {})])
    conn = duckdb.connect(str(env.db))
    stage = tmp_path / "stage"
    stage.mkdir()
    try:
        return mod.split_parquet_cross_product(conn, PARENT, [time, hier], stage_dir=stage), mod
    finally:
        conn.close()


def test_cross_product_county_view_is_aggregated(tmp_path):
    env = Env(tmp_path)
    subs, _ = _cross(env, True, tmp_path)
    by = {s["sub_code"]: s for s in subs}
    assert sorted(by) == [f"{PARENT}_a_judet", f"{PARENT}_a_localitate",
                          f"{PARENT}_b_judet", f"{PARENT}_b_localitate"]
    con = duckdb.connect()
    rows = con.execute(f"SELECT REF_AREA, OBS_VALUE FROM read_parquet('{by[PARENT + '_a_judet']['staged_path']}') "
                       "ORDER BY 1").fetchall()
    assert rows == [("C1", 30.0), ("C2", 30.0)]


def test_cross_product_skips_county_view_when_policy_refuses(tmp_path):
    env = Env(tmp_path)
    subs, mod = _cross(env, None, tmp_path)
    assert sorted(s["sub_code"] for s in subs) == [f"{PARENT}_a_localitate", f"{PARENT}_b_localitate"]
    assert mod.POLICY_SKIPPED[PARENT] == 2
