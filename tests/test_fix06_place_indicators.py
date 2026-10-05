"""FIX-06: place indicators — latest period first, explicit provenance/units,
FIX-02 weighted/approximate combination, SOM103A identity. Synthetic parquet
fixtures only (no corpus, no writes to data/)."""
import json
import sys
from pathlib import Path

import duckdb
import pytest

sys.path.insert(0, '.')
from app.services import place_service as ps
from app.services import aggregation_policy as agg

ROOT = Path(__file__).resolve().parent.parent
PLACE = {"name": "Testland", "type": "county", "slug": "testland",
         "ref_area_values": ["Testland"], "parent_slug": None, "parent_name": None}


def _write(path: Path, cols: list[str], rows: list[tuple]):
    con = duckdb.connect()
    con.execute("CREATE TABLE t (" + ", ".join(
        f'"{c}" {"DOUBLE" if c == "OBS_VALUE" else "VARCHAR"}' for c in cols) + ")")
    con.executemany("INSERT INTO t VALUES (" + ",".join("?" * len(cols)) + ")", rows)
    con.execute(f"COPY t TO '{path}' (FORMAT PARQUET)")
    con.close()


def _spec(**kw):
    base = {"key": "k", "label": "K", "label_en": "K", "unit": "pers.", "unit_kind": "count",
            "source_code": "TST001", "measure": "additive", "parquet": "k.parquet"}
    base.update(kw)
    return base


@pytest.fixture
def env(tmp_path, monkeypatch):
    """Point the service at a temp parquet dir + injected KPI config."""
    monkeypatch.setattr(ps, "PARQUET_DIR", tmp_path)
    monkeypatch.setattr(ps, "resolve_place", lambda *a, **k: dict(PLACE))

    def install(*specs, place_type="county"):
        monkeypatch.setattr(ps, "_kpi_config", {place_type: list(specs)})
    return tmp_path, install


def _count_rows(values: dict, areas=("Testland",), split=(25, 25, 25, 25)):
    """values {year: total}; spread over SEX x RESIDENCE evenly."""
    rows = []
    for y, tot in values.items():
        for a in areas:
            for i, (sx, rs) in enumerate([("M", "U"), ("M", "R"), ("F", "U"), ("F", "R")]):
                rows.append((sx, rs, a, str(y), "n", tot / 4))
    return rows


COUNT_COLS = ["SEX", "RESIDENCE", "REF_AREA", "TIME_PERIOD", "UNIT_MEASURE", "OBS_VALUE"]


def _kpi(tmp, install, spec, cols, rows, place_type="county"):
    _write(tmp / spec["parquet"], cols, rows)
    install(spec, place_type=place_type)
    rep = ps.get_place_kpi_report(place_type, "testland")
    return rep


# ---- latest period first ------------------------------------------------------

def test_34_year_series_returns_latest_year_not_year_30(env):
    tmp, install = env
    vals = {1991 + i: 1000 + i for i in range(34)}            # 1991..2024
    spec = _spec(partitions=["SEX", "RESIDENCE"])
    rep = _kpi(tmp, install, spec, COUNT_COLS, _count_rows(vals))
    k = rep["kpis"][0]
    assert k["period"] == "2024"
    assert k["value"] == 1033.0
    years = [r["year"] for r in k["sparkline"]]
    assert years == sorted(years) and years[-1] == "2024"
    assert len(years) == ps.SERIES_CAP and years[0] == "1995"   # newest 30, oldest dropped


def test_baselines_use_latest_periods_and_agree_with_current(env):
    tmp, install = env
    vals = {1991 + i: 1000 + i for i in range(34)}
    areas = ("Testland", "Other")
    spec = _spec(partitions=["SEX", "RESIDENCE"])
    _write(tmp / spec["parquet"], COUNT_COLS, _count_rows(vals, areas))
    install(spec)
    k = ps.get_place_kpi_report("county", "testland")["kpis"][0]
    b = ps.get_kpi_baselines("county", "testland", "k")
    assert b["national"][-1]["year"] == k["period"] == "2024"
    assert [r["year"] for r in b["national"]] == sorted(r["year"] for r in b["national"])
    assert b["national"][-1]["value"] == 2 * 1033.0            # both areas, summed
    assert b["national_meta"]["period"] == "2024"


def test_incomplete_latest_period_is_absent_not_zero(env):
    tmp, install = env
    rows = _count_rows({2022: 400, 2023: 400, 2024: 400})
    rows = [r for r in rows if not (r[3] == "2024" and r[0] == "F" and r[1] == "R")]  # one group missing
    spec = _spec(partitions=["SEX", "RESIDENCE"])
    k = _kpi(tmp, install, spec, COUNT_COLS, rows)["kpis"][0]
    assert k["period"] == "2023"            # 2024 would be an undercount of 300
    assert k["value"] == 400.0


# ---- change semantics ----------------------------------------------------------

def test_count_change_is_relative_percent(env):
    tmp, install = env
    spec = _spec(partitions=["SEX", "RESIDENCE"])
    k = _kpi(tmp, install, spec, COUNT_COLS, _count_rows({2023: 100, 2024: 110}))["kpis"][0]
    ch = k["change"]
    assert ch["status"] == "ok" and ch["value"] == 10.0
    assert ch["unit"] == "percent" and ch["display_unit"] == "percent"
    assert (ch["from_period"], ch["to_period"], ch["basis"]) == ("2023", "2024", "yoy")
    assert k["change_yoy"] == 10.0
    assert k["provenance"]["comparison"]["unit"] == "percent"


def _rate_rows(by_year, col="SEX", labels=("M", "F")):
    rows = []
    for y, v in by_year.items():
        for lab in labels:
            rows.append((lab, "Testland", str(y), "pct", v))
    return rows


def test_percent_rate_change_is_percentage_points(env):
    tmp, install = env
    spec = _spec(unit="%", unit_kind="percent_rate", measure="non_additive",
                 allow_approximation=True, partitions=["SEX"])
    cols = ["SEX", "REF_AREA", "TIME_PERIOD", "UNIT_MEASURE", "OBS_VALUE"]
    k = _kpi(tmp, install, spec, cols, _rate_rows({2023: 2.0, 2024: 2.4}))["kpis"][0]
    ch = k["change"]
    assert ch["value"] == 0.4 and ch["unit"] == "points" and ch["display_unit"] == "percentage_points"
    assert k["value"] == 2.4


def test_per_mille_rate_has_own_change_unit(env):
    tmp, install = env
    spec = _spec(unit="‰", unit_kind="per_mille_rate", measure="non_additive",
                 allow_approximation=True, partitions=["RESIDENCE"])
    cols = ["RESIDENCE", "REF_AREA", "TIME_PERIOD", "UNIT_MEASURE", "OBS_VALUE"]
    rows = [(r, "Testland", str(y), "pm", v) for y, v in {2023: 8.0, 2024: 7.5}.items() for r in ("Urban", "Rural")]
    k = _kpi(tmp, install, spec, cols, rows)["kpis"][0]
    assert k["change"]["display_unit"] == "per_mille_points"
    assert k["change"]["value"] == -0.5 and k["change"]["unit"] == "points"


def test_zero_current_value_is_valid_and_zero_comparator_unavailable(env):
    tmp, install = env
    spec = _spec(partitions=["SEX", "RESIDENCE"])
    k = _kpi(tmp, install, spec, COUNT_COLS, _count_rows({2023: 50, 2024: 0}))["kpis"][0]
    assert k["value"] == 0.0 and k["period"] == "2024"        # zero is data
    assert k["change"]["status"] == "ok" and k["change"]["value"] == -100.0

    k = _kpi(tmp, install, spec, COUNT_COLS, _count_rows({2023: 0, 2024: 5}))["kpis"][0]
    assert k["value"] == 5.0
    assert k["change"]["status"] == "unavailable" and k["change"]["reason"] == "comparator_zero"
    assert k["change_yoy"] is None


def test_single_period_has_unavailable_change(env):
    tmp, install = env
    spec = _spec(partitions=["SEX", "RESIDENCE"])
    k = _kpi(tmp, install, spec, COUNT_COLS, _count_rows({2024: 10}))["kpis"][0]
    assert k["change"]["status"] == "unavailable" and k["change"]["reason"] == "comparator_missing"


def test_gap_comparison_is_flagged_not_yoy(env):
    tmp, install = env
    spec = _spec(partitions=["SEX", "RESIDENCE"])
    k = _kpi(tmp, install, spec, COUNT_COLS, _count_rows({2019: 100, 2024: 110}))["kpis"][0]
    assert k["change"]["basis"] == "previous_period"
    assert k["change"]["from_period"] == "2019"


# ---- FIX-02: weighted and approximation ---------------------------------------

def test_weighted_rate_agrees_with_fix02(env):
    tmp, install = env
    w = {"parquet": "w.parquet", "source_code": "POPW", "join": ["RESIDENCE"]}
    spec = _spec(unit="‰", unit_kind="per_mille_rate", measure="non_additive",
                 weights=w, partitions=["RESIDENCE"])
    cols = ["RESIDENCE", "REF_AREA", "TIME_PERIOD", "UNIT_MEASURE", "OBS_VALUE"]
    rows = []
    wrows = []
    for y in (2023, 2024):
        rows += [("Urban", "Testland", str(y), "pm", 10.0), ("Rural", "Testland", str(y), "pm", 20.0)]
        for age in ("0-4", "5+"):
            wrows += [(age, "F", "Urban", "Testland", str(y), "p", 1500.0),
                      (age, "F", "Rural", "Testland", str(y), "p", 500.0)]
    _write(tmp / "w.parquet", ["AGE", "SEX", "RESIDENCE", "REF_AREA", "TIME_PERIOD", "UNIT_MEASURE", "OBS_VALUE"], wrows)
    k = _kpi(tmp, install, spec, cols, rows)["kpis"][0]
    expected = agg.weighted_mean([(10.0, 3000.0), (20.0, 1000.0)])      # 12.5
    assert k["value"] == round(expected, 1) == 12.5
    assert k["method"]["code"] == "weighted_mean" and k["method"]["approximation"] is False
    assert k["method"]["weights_source"] == "POPW"
    assert k["provenance"]["method"] == "weighted_mean"
    assert k["provenance"]["verification"] == "weighted"
    assert k["provenance"]["outcome"] == "valid_total"
    assert k["change"]["value"] == 0.0 and k["change"]["status"] == "ok"


def test_weighted_years_without_weights_are_dropped(env):
    tmp, install = env
    w = {"parquet": "w.parquet", "source_code": "POPW", "join": ["RESIDENCE"]}
    spec = _spec(unit="‰", unit_kind="per_mille_rate", measure="non_additive",
                 weights=w, partitions=["RESIDENCE"])
    cols = ["RESIDENCE", "REF_AREA", "TIME_PERIOD", "UNIT_MEASURE", "OBS_VALUE"]
    rows = [(r, "Testland", str(y), "pm", 5.0) for y in (2010, 2011, 2012) for r in ("Urban", "Rural")]
    wrows = [("a", "F", r, "Testland", "2012", "p", 10.0) for r in ("Urban", "Rural")]
    _write(tmp / "w.parquet", ["AGE", "SEX", "RESIDENCE", "REF_AREA", "TIME_PERIOD", "UNIT_MEASURE", "OBS_VALUE"], wrows)
    k = _kpi(tmp, install, spec, cols, rows)["kpis"][0]
    assert [r["year"] for r in k["sparkline"]] == ["2012"]


def test_unweighted_approximation_is_named_in_response(env):
    tmp, install = env
    spec = _spec(unit="%", unit_kind="percent_rate", measure="non_additive",
                 allow_approximation=True, partitions=["SEX"])
    cols = ["SEX", "REF_AREA", "TIME_PERIOD", "UNIT_MEASURE", "OBS_VALUE"]
    rows = [("M", "Testland", "2024", "p", 2.1), ("F", "Testland", "2024", "p", 2.7),
            ("M", "Testland", "2023", "p", 1.1), ("F", "Testland", "2023", "p", 1.7)]
    k = _kpi(tmp, install, spec, cols, rows)["kpis"][0]
    assert k["value"] == 2.4
    m = k["method"]
    assert m["approximation"] is True and m["code"] == "unweighted_mean"
    assert "APROXIMARE" in m["note"] and "APPROXIMATION" in m["note_en"]
    assert k["provenance"]["approximation"] is True
    assert k["provenance"]["outcome"] == "approximation"
    # baselines carry the same disclosure
    b = ps.get_kpi_baselines("county", "testland", "k")
    assert b["national_meta"]["approximation"] is True


def test_non_additive_without_weights_or_permission_is_omitted(env):
    tmp, install = env
    spec = _spec(unit="%", unit_kind="percent_rate", measure="non_additive",
                 allow_approximation=False, partitions=["SEX"])
    cols = ["SEX", "REF_AREA", "TIME_PERIOD", "UNIT_MEASURE", "OBS_VALUE"]
    rows = [("M", "Testland", "2024", "p", 2.1), ("F", "Testland", "2024", "p", 2.7)]
    rep = _kpi(tmp, install, spec, cols, rows)
    assert rep["kpis"] == []
    assert rep["omitted"][0]["reason"] == "missing_weights"


def test_suppressed_kpi_is_reported_not_silently_dropped(env):
    tmp, install = env
    spec = _spec(suppress="no_all_activities_total")
    install(spec)
    rep = ps.get_place_kpi_report("county", "testland")
    assert rep["kpis"] == [] and rep["omitted"][0]["reason"] == "no_all_activities_total"


# ---- provenance contract ---------------------------------------------------------

def test_provenance_has_contract_keys(env):
    tmp, install = env
    spec = _spec(partitions=["SEX", "RESIDENCE"], source_code="POP105A")
    k = _kpi(tmp, install, spec, COUNT_COLS, _count_rows({2023: 100, 2024: 110}))["kpis"][0]
    keys = {"source_code", "period", "unit", "filters", "levels", "method", "verification",
            "approximation", "outcome", "reason", "comparison", "dimensions"}
    assert keys <= set(k["provenance"])
    assert k["provenance"]["source_code"] == "POP105A" and k["provenance"]["period"] == "2024"
    assert k["source"]["code"] == "POP105A" and k["unit"] == "pers."
    assert k["stale"] is False and k["source_latest_period"] == "2024"


def test_stale_flag_when_place_lags_source(env):
    tmp, install = env
    spec = _spec(partitions=["SEX", "RESIDENCE"])
    rows = _count_rows({2023: 100, 2024: 100}, areas=("Other",)) + _count_rows({2022: 90, 2023: 100})
    k = _kpi(tmp, install, spec, COUNT_COLS, rows)["kpis"][0]
    assert k["period"] == "2023" and k["source_latest_period"] == "2024" and k["stale"] is True


# ---- SOM103A identity and legacy alias ---------------------------------------------

def _config():
    return json.loads((ROOT / "app/static/data/place_kpi_config.json").read_text(encoding="utf-8"))


def test_som103a_never_labelled_bim_or_ilo_in_either_language():
    for level, specs in _config().items():
        if level.startswith("_"):
            continue
        for s in specs:
            if s.get("source_code") != "SOM103A":
                continue
            public = {k: v for k, v in s.items() if k != "aliases"}
            blob = json.dumps(public, ensure_ascii=False)
            assert "BIM" not in blob and "ILO" not in blob, (level, blob)
            assert s["label"] == "Rata șomajului înregistrat"
            assert s["label_en"] == "Registered unemployment rate"
            assert s["measure"] == "non_additive" and s.get("allow_approximation") is True


def test_old_label_still_resolves_and_baseline_route_accepts_it(env):
    tmp, install = env
    spec = _spec(key="registered_unemployment_rate", label="Rata șomajului înregistrat",
                 label_en="Registered unemployment rate", aliases=["Rata șomajului BIM"],
                 unit="%", unit_kind="percent_rate", measure="non_additive",
                 allow_approximation=True, partitions=["SEX"])
    cols = ["SEX", "REF_AREA", "TIME_PERIOD", "UNIT_MEASURE", "OBS_VALUE"]
    _write(tmp / spec["parquet"], cols, _rate_rows({2023: 2.0, 2024: 2.4}))
    install(spec)
    for ref in ("Rata șomajului BIM", "rata somajului bim", "Rata șomajului înregistrat",
                "Registered unemployment rate", "registered_unemployment_rate"):
        found, via_alias = ps.find_kpi_spec("county", ref)
        assert found is spec, ref
        assert via_alias == ("bim" in ref.lower())
    b = ps.get_kpi_baselines("county", "testland", "Rata șomajului BIM")
    assert b["kpi"]["matched_legacy_alias"] is True and b["national"]
    assert ps.find_kpi_spec("county", "nonexistent")[0] is None


def test_real_config_is_consistent():
    cfg = _config()
    for level in ("county", "region", "macroregion"):
        keys = [s["key"] for s in cfg[level]]
        assert len(keys) == len(set(keys))
        for s in cfg[level]:
            assert s["unit_kind"] in ("count", "percent_rate", "per_mille_rate", "currency")
            assert s.get("suppress") or (s["source_code"] and s["definition"] and s["definition_en"]
                                         and s["source_title"] and s["source_title_en"])
            if s["unit_kind"] in ("percent_rate", "per_mille_rate"):
                assert s["measure"] == "non_additive"
                assert s.get("weights") or s.get("allow_approximation")


def test_ui_does_not_label_change_with_the_value_unit():
    js = (ROOT / "app/static/js/place-page.js").read_text(encoding="utf-8")
    assert "change_yoy" not in js          # UI reads the explicit `change` object
    assert "kpi.unit)}\n                   </div>" not in js
    assert "'pers.'" not in js


# ---- corpus (read-only) --------------------------------------------------------------

@pytest.mark.corpus
def test_bihor_unemployment_uses_latest_source_period():
    ps._kpi_config = None
    rep = ps.get_place_kpi_report("county", "bihor")
    k = next(x for x in rep["kpis"] if x["key"] == "registered_unemployment_rate")
    assert k["period"] == k["source_latest_period"]       # not the old oldest-30 window (2020)
    assert int(k["period"]) >= 2024
    assert k["method"]["approximation"] is True
    assert "BIM" not in k["label"] and "BIM" not in k["label_en"]
    assert [r["year"] for r in k["sparkline"]] == sorted(r["year"] for r in k["sparkline"])
    # rates change in points, counts in relative percent
    for x in rep["kpis"]:
        assert x["change"]["unit"] == ("points" if x["unit_kind"].endswith("_rate") else "percent")
    assert {o["key"] for o in rep["omitted"]} == {"net_monthly_wage"}


@pytest.mark.corpus
def test_corpus_baseline_period_matches_place_period():
    rep = ps.get_place_kpi_report("county", "bihor")
    for k in rep["kpis"]:
        b = ps.get_kpi_baselines("county", "bihor", k["key"])
        assert b["national"], k["key"]
        assert b["national"][-1]["year"] == k["period"], k["key"]
