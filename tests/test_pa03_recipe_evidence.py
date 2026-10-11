"""PA-03: tourism-intensity arithmetic and evidence bundles on fixtures.

The cases are the spec's required synthetic tests. The real Q4 numbers are
checked (corpus-marked) against the PA-00 answer record.
"""
import csv
import hashlib
import io
import json
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

from app.services import recipes as rc
from app.services.recipes import RecipeError, compute

M = {"Numar": 1, "Numar persoane": 1, "Mii": 1000}
ROOT = Path(__file__).resolve().parent.parent


def run(num, den, **kw):
    return compute(num, den, num_unit=kw.pop("nu", "Numar"), den_unit=kw.pop("du", "Numar persoane"),
                   multipliers=M, **kw)


def test_basic_ratio_and_ranking():
    r = run([("A", "2024", 120), ("B", "2024", 50)], [("A", "2024", 60), ("B", "2024", 100)])
    assert [(x["label"], x["intensity"], x["rank"]) for x in r["rows"]] == [("A", 2.0, 1), ("B", 0.5, 2)]
    assert r["year"] == "2024" and r["excluded"] == []


def test_unit_multiplier_applied_before_division():
    r = run([("A", "2024", 1.2)], [("A", "2024", 600)], nu="Mii")
    assert r["rows"][0]["intensity"] == pytest.approx(2.0)


def test_zero_stays_is_a_valid_zero():
    r = run([("A", "2024", 0)], [("A", "2024", 50)])
    assert r["rows"][0]["intensity"] == 0.0


def test_missing_and_invalid_inputs_have_distinct_reasons():
    r = run([("A", "2024", None), ("C", "2024", 5), ("D", "2024", 9), ("E", "2024", 7)],
            [("A", "2024", 10), ("B", "2024", 10), ("C", "2024", 0), ("D", "2024", None)])
    reasons = {e["label"]: e["reason"] for e in r["excluded"]}
    assert reasons == {"A": "numerator_missing", "B": "numerator_missing",
                       "C": "denominator_not_positive", "D": "denominator_missing",
                       "E": "not_in_denominator"}
    assert r["rows"] == []


def test_duplicate_key_refused_before_joining():
    with pytest.raises(RecipeError) as e:
        run([("Cluj", "2024", 1), ("Cluj ", "2024", 2)], [("Cluj", "2024", 10)])
    assert e.value.reason == "duplicate_key"
    with pytest.raises(RecipeError) as e:
        run([("Cluj", "2024", 1)], [("Cluj", "2024", 10), ("CLUJ", "2024", 11)])
    assert e.value.reason == "duplicate_key"


def test_latest_common_year_never_mixes_years():
    r = run([("A", "2023", 10), ("A", "2024", 20)], [("A", "2023", 5), ("A", "2025", 5)])
    assert r["year"] == "2023" and r["rows"][0]["intensity"] == 2.0
    with pytest.raises(RecipeError) as e:
        run([("A", "2024", 10)], [("A", "2025", 5)])
    assert e.value.reason == "no_common_year"
    with pytest.raises(RecipeError) as e:
        run([("A", "2023", 10)], [("A", "2023", 5)], year="2024")
    assert e.value.reason == "year_unavailable" and e.value.detail["years_available"] == ["2023"]


def test_names_join_exactly_not_fuzzily():
    # "Bucuresti" (locality-style label) must not join "Municipiul Bucuresti".
    r = run([("Bucuresti", "2024", 10)], [("Municipiul Bucuresti", "2024", 5)])
    assert r["rows"] == []
    assert {e["reason"] for e in r["excluded"]} == {"numerator_missing", "not_in_denominator"}


def test_unknown_unit_refused():
    with pytest.raises(RecipeError) as e:
        run([("A", "2024", 1)], [("A", "2024", 1)], nu="Procente")
    assert e.value.reason == "unsupported_unit"


def test_area_subset_reports_unknown_areas():
    r = run([("Cluj", "2024", 10), ("Iasi", "2024", 4)], [("Cluj", "2024", 5), ("Iasi", "2024", 4)],
            areas=["Cluj", "Atlantis"])
    assert [x["label"] for x in r["rows"]] == ["Cluj"]
    assert r["excluded"] == [{"geo_id": "atlantis", "label": "atlantis", "reason": "not_in_data"}]


@pytest.mark.parametrize("res,reason", [
    ({"unavailable": True, "aggregation": {"reason": "conflicting_grain"}}, "source_unavailable"),
    ({"truncated": True, "aggregation": {}}, "source_incomplete"),
    ({"time_windowed": True, "aggregation": {}}, "source_incomplete"),
    ({"aggregation": {"outcome": "approximation"}}, "source_approximation"),
])
def test_refused_or_capped_sources_stop_the_recipe(monkeypatch, res, reason):
    import app.services.data_query as dq
    monkeypatch.setattr(dq, "run_query", lambda *a, **k: {"columns": ["REF_AREA", "TIME_PERIOD", "OBS_VALUE"],
                                                         "rows": [], **res})
    with pytest.raises(RecipeError) as e:
        rc._source(None, {"role": "stays", "dataset": "X", "group_by": ["REF_AREA", "TIME_PERIOD"]}, "ro")
    assert e.value.reason == reason


# ------------------------------------------------------------ bundles

def _fake_result(gen_id="g1"):
    num = [("A", "2024", 120.0), ("B", "2024", 50.0), ("A", "2023", 1.0)]
    den = [("A", "2024", 60.0), ("B", "2024", 100.0)]
    out = compute(num, den, num_unit="Numar", den_unit="Numar persoane", multipliers=M)
    r = rc.load_recipes()["tourism_intensity"]
    src = lambda role, ds, unit: {"role": role, "dataset": ds, "unit": unit, "title": ds, "reference": "x",
                                 "source_updated": "01-01-2025", "query": {"dataset": ds},
                                 "aggregation": {"method": "sum_partition"}, "quality": {}, "contract": "tempo-query/1"}
    return {"recipe": {"id": r["id"], "version": r["version"], "name": "T", "unit": "u", "definition": "d",
                       "formula": r["formula"], "status": "s", "missing_policy": "m",
                       "display_decimals": 3, "unit_multipliers": M},
            "request": {"year": None, "areas": None, "lang": "ro"}, **out,
            "sources": [src("stays", "N", "Numar"), src("population", "D", "Numar persoane")],
            "inputs": {"stays": num, "population": den},
            "generation": {"id": gen_id, "status": "present", "built_at": None}}


def _open(data):
    z = zipfile.ZipFile(io.BytesIO(data))
    m = json.loads(z.read("manifest.json"))
    for name, h in m["files"].items():
        assert hashlib.sha256(z.read(name)).hexdigest() == h, name
    return z, m


def test_recipe_bundle_recomputes_offline(tmp_path):
    from app.services.evidence import recipe_bundle
    z, m = _open(recipe_bundle(_fake_result(), "http://x/compare.html?recipe=tourism_intensity"))
    assert m["schema"] == "tempo-evidence/1" and m["generation"]["id"] == "g1"
    rows = list(csv.DictReader(io.StringIO(z.read("result.csv").decode())))
    assert [(r["label"], float(r["intensity"])) for r in rows] == [("A", 2.0), ("B", 0.5)]
    z.extractall(tmp_path)
    p = subprocess.run([sys.executable, "-I", "recompute.py"], cwd=tmp_path,
                       capture_output=True, text=True, timeout=60)
    assert p.returncode == 0, p.stderr
    assert "recomputed 2 rows; 0 differ" in p.stderr
    for forbidden in ("/Users/", "api_key", "Traceback"):
        assert not any(forbidden in z.read(n).decode() for n in z.namelist())


def test_old_bundle_keeps_its_generation():
    from app.services.evidence import recipe_bundle
    old = recipe_bundle(_fake_result("g1"), "l")
    new = recipe_bundle(_fake_result("g2"), "l")
    assert _open(old)[1]["generation"]["id"] == "g1"
    assert _open(new)[1]["generation"]["id"] == "g2"


@pytest.fixture
def client(tmp_path, monkeypatch):
    from fix02b_corpus import make_client
    return make_client(tmp_path, monkeypatch)


def test_dataset_bundle_carries_aggregation_inputs(client):
    r = client.get("/api/datasets/ADDX/evidence", params={"group_by": '["TIME_PERIOD"]'})
    assert r.status_code == 200 and r.headers["content-type"] == "application/zip"
    z, m = _open(r.content)
    assert m["kind"] == "dataset" and m["dataset"] == "ADDX"
    result = {row["TIME_PERIOD"]: float(row["OBS_VALUE"])
              for row in csv.DictReader(io.StringIO(z.read("result.csv").decode()))}
    obs = list(csv.DictReader(io.StringIO(z.read("inputs/observations.csv").decode())))
    for year, value in result.items():         # every result recomputes from the inputs
        assert sum(float(o["OBS_VALUE"]) for o in obs if o["TIME_PERIOD"] == year) == value
    method = json.loads(z.read("method.json"))
    assert method["decision"]["filters"] == {"CATEGORY": ["Total"]}


def test_dataset_bundle_refuses_rather_than_cuts(client, monkeypatch):
    import app.services.evidence as ev
    monkeypatch.setattr(ev, "MAX_INPUT_ROWS", 1)
    r = client.get("/api/datasets/ADDX/evidence", params={"group_by": '["TIME_PERIOD"]'})
    assert r.status_code == 413
    assert client.get("/api/datasets/ADDX/evidence", params={"filters": '{"BOGUS":["x"]}'}).status_code == 400


@pytest.mark.corpus
def test_real_tourism_intensity_matches_answer_record():
    from fastapi.testclient import TestClient
    from app.main import app
    d = TestClient(app).get("/api/recipes/tourism_intensity").json()
    rec = json.loads((ROOT / "docs/plans/public-alpha/pa-00/answers.json").read_text())["records"]["Q4"]
    want = {x["geo"]: x["stays_per_resident"] for x in rec["values_2024"]}
    assert d["year"] == "2024" and len(d["rows"]) == len(want) == 42
    assert all(round(x["intensity"], 3) == want[x["label"]] for x in d["rows"])
