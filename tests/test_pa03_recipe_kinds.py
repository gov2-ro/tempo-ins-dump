"""Reconstruction recipes (Q2 weighted mean, Q3 rate from counts): arithmetic on
small hand-checked tables, the evidence round trip, and the corpus checks
recorded in docs/plans/public-alpha/pa-00/answer-records.md."""
import csv
import json
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


def _cells(rows):
    return {(rc.geo_id(a), y): {"label": a, "year": y, "value": v, "unit": "%", "query_id": "q",
                                 "fetched_at": "t", "sha256": "s", "ins_updated": "u"}
            for a, y, v in rows}


def test_published_values_win_and_the_reconstruction_is_only_a_check():
    cells = _cells([("TOTAL", "2024", 2.0), ("Regiunea R", "2024", 2.1), ("X", "2024", 2.0),
                    ("Y", "2024", 2.1), ("Y", "2023", 5.0), ("Z", "2024", None)])
    rec = {"rows": [{"geo_id": "x", "value": 2.04, "count_total": 40.0, "base_total": 2000.0},
                    {"geo_id": "y", "value": 2.0, "count_total": 10.0, "base_total": 500.0}]}
    out = rc.compute_published(cells, {"x", "y", "z"}, reconstruction=rec, decimals=1)
    assert out["year"] == "2024" and out["years_available"] == ["2023", "2024"]
    assert [(x["label"], x["value"], x["reconstructed"]) for x in out["rows"]] == \
        [("Y", 2.1, 2.0), ("X", 2.0, 2.04)]
    assert out["excluded"] == [{"geo_id": "z", "label": "Z", "reason": "not_published"}]
    assert {a["geo_id"]: a["value"] for a in out["aggregates"]} == {"total": 2.0, "regiunea-r": 2.1}
    assert out["check"] == {"compared": 2, "max_abs_diff": pytest.approx(0.1), "equal_when_rounded": 1}
    sub = rc.compute_published(cells, {"x", "y", "z"}, reconstruction=rec, decimals=1, areas=["X", "Q"])
    assert [x["label"] for x in sub["rows"]] == ["X"] and sub["universe"] == 1
    assert sub["check"] == out["check"]                       # the year's check, not the selection's
    assert sub["excluded"] == [{"geo_id": "q", "label": "q", "reason": "not_in_data"}]
    with pytest.raises(RecipeError) as e:
        rc.compute_published(cells, {"x", "y"}, year="2020")
    assert e.value.reason == "year_unavailable"


def test_published_bundle_checks_values_and_reconstruction_offline(tmp_path):
    from app.services.evidence import recipe_bundle
    rates = [["M", "X", "2024", 3.0], ["F", "X", "2024", 1.0]]
    counts = [["M", "X", "2024", 30.0], ["F", "X", "2024", 10.0]]
    rec = compute_rate_from_counts((RT_COLS, rates), (RT_COLS, counts), by="SEX")   # X = 2.0
    out = rc.compute_published(_cells([("X", "2024", 2.1), ("TOTAL", "2024", 2.1)]), {"x"},
                               reconstruction=rec, decimals=1)
    r = rc.load_recipes()["registered_unemployment_county"]
    src = lambda role: {"role": role, "dataset": role.upper(), "unit": "u", "title": role,
                        "reference": "x", "source_updated": None, "query": {}, "aggregation": {},
                        "quality": {}, "contract": "tempo-query/1"}
    result = {"recipe": {"id": r["id"], "version": r["version"], "kind": r["kind"], "name": "Q3",
                         "unit": "%", "definition": "d", "formula": "f", "status": "s",
                         "missing_policy": "m", "display_decimals": 1, "unit_multipliers": None,
                         "columns": [{"key": "value"}, {"key": "reconstructed"}],
                         "parameters": {"by": "SEX"}, "value_source": "ins_published",
                         "reconstruction_formula": r["formula"]},
              "request": {}, **out, "sources": [src("published"), src("rates"), src("counts")],
              "inputs": {"published": [["REF_AREA", "TIME_PERIOD", "OBS_VALUE"], ["X", "2024", 2.1],
                                       ["TOTAL", "2024", 2.1]],
                         "rates": [RT_COLS] + rates, "counts": [RT_COLS] + counts},
              "generation": {"id": "g1"}}
    z = zipfile.ZipFile(io.BytesIO(recipe_bundle(result, "l")))
    assert json.loads(z.read("method.json"))["value_source"] == "ins_published"
    z.extractall(tmp_path)
    p = subprocess.run([sys.executable, "-I", "recompute.py"], cwd=tmp_path,
                       capture_output=True, text=True, timeout=60)
    assert p.returncode == 0, p.stderr
    assert "1 values; 0 differ from inputs/published.csv" in p.stderr
    # a tampered value is caught
    res = (tmp_path / "result.csv").read_text().replace(",2.1,", ",2.2,")
    (tmp_path / "result.csv").write_text(res)
    p = subprocess.run([sys.executable, "-I", "recompute.py"], cwd=tmp_path,
                       capture_output=True, text=True, timeout=60)
    assert p.returncode == 1


# ------------------------------------------------------------ corpus checks

@pytest.fixture(scope="module")
def conn():
    from app.db import get_conn
    return get_conn()


def _reconstruct(conn, rid, year):
    return rc._run_reconstruction(conn, rc.load_recipes()[rid], year=year)


def _published(conn):
    return bool(rc._published_cells(conn, "FOM106E"))


@pytest.mark.corpus
def test_q2_reproduces_the_national_ins_total(conn):
    r = _reconstruct(conn, "net_earnings_county", "2024")
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
    r = _reconstruct(conn, "registered_unemployment_county", "2024")
    res = run_query(conn, "SOM103A_judete", {"TIME_PERIOD": ["2024"]}, ["SEX", "REF_AREA"])
    by_area = {}
    for sex, area, v in res["rows"]:
        by_area.setdefault(rc.geo_id(area), []).append(v)
    for x in r["rows"]:
        lo, hi = min(by_area[x["geo_id"]]), max(by_area[x["geo_id"]])
        assert lo - 1e-9 <= x["value"] <= hi + 1e-9, x
    # Generations fetched before the 2026-10-12 locality fix have no Bucharest
    # SOM101E rows: Bucharest is then a range, otherwise a row like the others.
    if len(r["rows"]) == 41:
        assert r["excluded"] == [{"geo_id": "municipiul-bucuresti", "label": "Municipiul Bucuresti",
                                  "reason": "group_missing", "bounds": [0.6, 0.7]}]
    else:
        assert len(r["rows"]) == 42 and r["excluded"] == []
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
    published = _published(conn)
    assert k["net_monthly_wage"]["method"]["code"] == ("source_total" if published else "reconstruction")
    rep = ps.get_place_kpi_report("county", "municipiul-bucuresti")
    if published:       # INS publishes Bucharest's rate: no range, the value itself
        assert next(x for x in rep["kpis"] if x["key"] == "registered_unemployment_rate")["value"] == \
            next(x["value"] for x in r["rows"] if x["geo_id"] == "municipiul-bucuresti")
    else:
        assert [o for o in rep["omitted"] if o["key"] == "registered_unemployment_rate"][0]["bounds"] == \
            r["excluded"][0]["bounds"]
    b = ps.get_kpi_baselines("county", "cluj", "net_monthly_wage")
    assert round(b["national"][-1]["value"]) == 4959


@pytest.mark.corpus
def test_published_totals_are_served_with_the_reconstruction_as_a_check(conn):
    if not _published(conn):
        pytest.skip("this generation has no published_totals")
    r = rc.run(conn, "net_earnings_county", year="2024")
    assert r["recipe"]["value_source"] == "ins_published" and r["sources"][0]["role"] == "published"
    got = {x["label"]: x["value"] for x in r["rows"]}
    assert (got["Cluj"], got["Iasi"], got["Municipiul Bucuresti"]) == (5921, 5098, 6730)   # INS cells
    iasi = next(x for x in r["rows"] if x["label"] == "Iasi")
    assert round(iasi["reconstructed"]) == 5097                    # off by one: rounding
    assert {a["geo_id"]: a["value"] for a in r["aggregates"]}["total"] == 4959
    assert r["check"]["compared"] == 42 and r["check"]["max_abs_diff"] < 1.5
    q3 = rc.run(conn, "registered_unemployment_county", year="2024")
    assert len(q3["rows"]) == 42 and q3["excluded"] == []
    assert {x["label"]: x["value"] for x in q3["rows"]}["Municipiul Bucuresti"] == 0.7
    assert q3["rows"][0]["label"] == "Teleorman" and q3["rows"][0]["value"] == 9.6
    early = rc.run(conn, "registered_unemployment_county", year="1995")    # no SOM101E: INS only
    assert early["check"] is None and all(x["reconstructed"] is None for x in early["rows"])

