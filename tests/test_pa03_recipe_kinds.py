"""Reconstruction recipes (Q2 weighted mean, Q3 rate from counts): arithmetic on
small hand-checked tables, the evidence round trip, and the corpus checks
recorded in docs/plans/public-alpha/pa-00/answer-records.md."""
import csv
import io
import subprocess
import sys
import zipfile

import pytest

from app.services import recipes as rc
from app.services.recipes import RecipeError, compute_rate_from_counts, compute_weighted_mean

WM_COLS = ["ECON_ACTIVITY", "SEX", "REF_AREA", "TIME_PERIOD", "OBS_VALUE"]
RT_COLS = ["SEX", "REF_AREA", "TIME_PERIOD", "OBS_VALUE"]
KEEP = {"ECON_ACTIVITY": "^[A-S]  "}


def _wm(values, weights, **kw):
    return compute_weighted_mean((WM_COLS, values), (WM_COLS, weights),
                                 cell_cols=["ECON_ACTIVITY", "SEX"], keep=KEEP, **kw)


def test_weighted_mean_uses_weights_and_only_the_partition():
    v = [["A  Agri", "M", "X", "2024", 1000.0], ["B  Mine", "M", "X", "2024", 3000.0],
         ["05 Division", "M", "X", "2024", 99999.0]]          # a division: outside `keep`
    w = [["A  Agri", "M", "X", "2024", 3.0], ["B  Mine", "M", "X", "2024", 1.0],
         ["05 Division", "M", "X", "2024", 50.0]]
    out = _wm(v, w)
    assert out["rows"][0]["value"] == pytest.approx(1500.0)   # (3000 + 3000) / 4, not 2000
    assert out["rows"][0]["weight_total"] == 4.0 and out["rows"][0]["cells"] == 2


def test_weighted_mean_refuses_a_partial_average():
    v = [["A  Agri", "M", "X", "2024", 1000.0], ["A  Agri", "M", "Y", "2024", 1000.0]]
    w = [["A  Agri", "M", "X", "2024", 3.0], ["B  Mine", "M", "X", "2024", 1.0],
         ["A  Agri", "M", "Y", "2024", 0.0]]
    out = _wm(v, w, areas=["X", "Y", "Z"])
    assert out["rows"] == []
    assert {e["geo_id"]: e["reason"] for e in out["excluded"]} == \
        {"x": "value_missing", "y": "no_weights", "z": "not_in_data"}


def test_weighted_mean_duplicate_cell_refused():
    v = [["A  Agri", "M", "X", "2024", 1.0], ["A  Agri", "M", "X", "2024", 2.0]]
    with pytest.raises(RecipeError) as e:
        _wm(v, [["A  Agri", "M", "X", "2024", 1.0]])
    assert e.value.reason == "duplicate_key"


def test_rate_from_counts_recovers_the_base():
    # men: 30 unemployed at 3 % -> 1000 active; women: 10 at 1 % -> 1000 active
    rates = [["M", "X", "2024", 3.0], ["F", "X", "2024", 1.0]]
    counts = [["M", "X", "2024", 30.0], ["F", "X", "2024", 10.0]]
    out = compute_rate_from_counts((RT_COLS, rates), (RT_COLS, counts), by="SEX")
    row = out["rows"][0]
    assert row["value"] == pytest.approx(2.0)                 # 40 / 2000, not the mean of counts
    assert row["base_total"] == pytest.approx(2000.0)


def test_rate_from_counts_missing_group_reports_bounds():
    rates = [["M", "X", "2024", 0.6], ["F", "X", "2024", 0.7],
             ["M", "Y", "2024", 0.0], ["F", "Y", "2024", 1.0]]
    counts = [["F", "X", "2024", 10.0], ["M", "Y", "2024", 5.0], ["F", "Y", "2024", 1.0]]
    out = compute_rate_from_counts((RT_COLS, rates), (RT_COLS, counts), by="SEX")
    ex = {e["geo_id"]: e for e in out["excluded"]}
    assert ex["x"]["reason"] == "group_missing" and ex["x"]["bounds"] == [0.6, 0.7]
    assert ex["y"]["reason"] == "rate_zero"
    assert out["rows"] == []


def test_new_kinds_bundle_recomputes_offline(tmp_path):
    from app.services.evidence import recipe_bundle
    rates = [["M", "X", "2024", 3.0], ["F", "X", "2024", 1.0],
             ["M", "Y", "2024", 2.0], ["F", "Y", "2024", 2.0]]
    counts = [["M", "X", "2024", 30.0], ["F", "X", "2024", 10.0],
              ["M", "Y", "2024", 4.0], ["F", "Y", "2024", 6.0]]
    out = compute_rate_from_counts((RT_COLS, rates), (RT_COLS, counts), by="SEX")
    r = rc.load_recipes()["registered_unemployment_county"]
    src = lambda role: {"role": role, "dataset": role.upper(), "unit": "u", "title": role,
                        "reference": "x", "source_updated": None, "query": {}, "aggregation": {},
                        "quality": {}, "contract": "tempo-query/1"}
    result = {"recipe": {"id": r["id"], "version": r["version"], "kind": r["kind"], "name": "Q3",
                         "unit": "%", "definition": "d", "formula": r["formula"], "status": "s",
                         "missing_policy": "m", "display_decimals": 1, "unit_multipliers": None,
                         "columns": [{"key": "value"}, {"key": "count_total"}],
                         "parameters": {"by": "SEX"}},
              "request": {}, **out, "sources": [src("rates"), src("counts")],
              "inputs": {"rates": [RT_COLS] + rates, "counts": [RT_COLS] + counts},
              "generation": {"id": "g1"}}
    z = zipfile.ZipFile(io.BytesIO(recipe_bundle(result, "l")))
    rows = list(csv.DictReader(io.StringIO(z.read("result.csv").decode())))
    assert [x["label"] for x in rows] == ["X", "Y"]          # equal rates: by name
    assert [float(x["value"]) for x in rows] == pytest.approx([2.0, 2.0])
    z.extractall(tmp_path)
    p = subprocess.run([sys.executable, "-I", "recompute.py"], cwd=tmp_path,
                       capture_output=True, text=True, timeout=60)
    assert p.returncode == 0, p.stderr
    assert "recomputed 2 rows; 0 differ" in p.stderr


# ------------------------------------------------------------ corpus checks

@pytest.fixture(scope="module")
def conn():
    from app.db import get_conn
    return get_conn()


@pytest.mark.corpus
def test_q2_reproduces_the_national_ins_total(conn):
    r = rc.run(conn, "net_earnings_county", year="2024")
    assert len(r["rows"]) == 42 and r["excluded"] == []
    assert {"2008", "2023", "2024"} <= set(r["years_available"])   # not just the year read
    national = sum(x["value"] * x["weight_total"] for x in r["rows"]) / \
        sum(x["weight_total"] for x in r["rows"])
    assert round(national) == 4959                            # INS TOTAL 2024, retained cell
    got = {x["label"]: round(x["value"]) for x in r["rows"]}
    assert (got["Cluj"], got["Iasi"], got["Municipiul Bucuresti"]) == (5921, 5097, 6730)


@pytest.mark.corpus
def test_q3_lies_between_the_sex_rates_and_bucharest_is_a_range(conn):
    from app.services.data_query import run_query
    r = rc.run(conn, "registered_unemployment_county", year="2024")
    res = run_query(conn, "SOM103A_judete", {"TIME_PERIOD": ["2024"]}, ["SEX", "REF_AREA"])
    by_area = {}
    for sex, area, v in res["rows"]:
        by_area.setdefault(rc.geo_id(area), []).append(v)
    assert len(r["rows"]) == 41
    for x in r["rows"]:
        lo, hi = min(by_area[x["geo_id"]]), max(by_area[x["geo_id"]])
        assert lo - 1e-9 <= x["value"] <= hi + 1e-9, x
    assert r["excluded"] == [{"geo_id": "municipiul-bucuresti", "label": "Municipiul Bucuresti",
                              "reason": "group_missing", "bounds": [0.6, 0.7]}]
    assert r["rows"][0]["label"] == "Teleorman"


@pytest.mark.corpus
def test_place_pages_use_the_reconstructions(conn):
    from app.services import place_service as ps
    ps._kpi_config = None
    k = {x["key"]: x for x in ps.get_place_kpi_report("county", "cluj")["kpis"]}
    assert k["net_monthly_wage"]["value"] == 5921.0 and k["net_monthly_wage"]["period"] == "2024"
    # the latest year follows the generation (2024 or 2025); the KPI is the recipe's value for it
    u = k["registered_unemployment_rate"]
    r = rc.run(conn, "registered_unemployment_county", year=u["period"])
    assert u["value"] == round(next(x["value"] for x in r["rows"] if x["geo_id"] == "cluj"), 1)
    assert k["net_monthly_wage"]["method"]["code"] == "reconstruction"
    rep = ps.get_place_kpi_report("county", "municipiul-bucuresti")
    assert [o for o in rep["omitted"] if o["key"] == "registered_unemployment_rate"][0]["bounds"] == \
        r["excluded"][0]["bounds"]
    b = ps.get_kpi_baselines("county", "cluj", "net_monthly_wage")
    assert round(b["national"][-1]["value"]) == 4959
