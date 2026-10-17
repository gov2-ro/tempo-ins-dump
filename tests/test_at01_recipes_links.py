"""AT-01f: `run_recipe`, `get_evidence_links` and the expected-generation
precondition of the evidence routes, on synthetic corpora through the real
shared services (recipes.run -> data_query.run_query -> aggregation policy and
grain gate). Recipes point at fixture datasets through a temporary recipes.json.

Recipe fixture (ratio recipe `fx_intensity` = STAYS1 / RESPOP):

            2023 stays/pop      2024 stays/pop
  Alfa      100 / 50  = 2       120 / 60  = 2
  Beta       40 / 80  = 0.5      50 / 100 = 0.5
  Gama       30 / 10  = 3        30 / 0   -> denominator_not_positive
  Delta      -                   10 / NULL -> denominator_missing
  Eps        -                    5 / -    -> not_in_denominator
  Zeta       -                   - / 70    -> numerator_missing
  (STAYS1 also has 2025 for Alfa; RESPOP does not: latest common year is 2024)

Published recipe `fx_published` (PSTAY / PPOP, INS cells in PUBM): Alfa
reconstructs as 99 / 10 = 9.9 while INS publishes 10.
"""
import csv
import io
import json
import zipfile
from urllib.parse import parse_qs, urlsplit

import duckdb
import pytest

from at01_fixtures import GENERATION, add_dataset, call, make_env, write_manifest
from app import config
from app.services import recipes as rc
from app.services.tools import contract as C
from app.services.tools import recipe as recipe_tool
from app.services.tools import registry as R

AREAS = ["Alfa", "Beta", "Gama", "Delta", "Eps", "Zeta"]


def geo(names):
    return ("REF_AREA", "Județe", "geo", [(n, {"geo_level": "county"}) for n in names])


def years(ys):
    return ("TIME_PERIOD", "Ani", "time", [(str(y), {"year": y}) for y in ys])


def unit(u):
    return ("UNIT_MEASURE", "Unitate", "unit", [(u, {})])


def series(corpus, code, name, um, data, names=AREAS, ys=(2023, 2024, 2025)):
    """data: {(area, year): value}; None is a NULL observation."""
    rows = [(a, str(y), um, v) for (a, y), v in data.items()]
    add_dataset(corpus, code, [geo(names), years(ys), unit(um)], rows, name=name)


STAYS = {("Alfa", 2023): 100.0, ("Beta", 2023): 40.0, ("Gama", 2023): 30.0,
         ("Alfa", 2024): 120.0, ("Beta", 2024): 50.0, ("Gama", 2024): 30.0,
         ("Delta", 2024): 10.0, ("Eps", 2024): 5.0, ("Alfa", 2025): 130.0}
POP = {("Alfa", 2023): 50.0, ("Beta", 2023): 80.0, ("Gama", 2023): 10.0,
       ("Alfa", 2024): 60.0, ("Beta", 2024): 100.0, ("Gama", 2024): 0.0,
       ("Delta", 2024): None, ("Zeta", 2024): 70.0}


def make_recipe(rid, num, den, **over):
    r = {
        "id": rid, "version": 3, "question": "QX",
        "status": {"ro": "verificat pe fixture", "en": "verified on the fixture"},
        "name": {"ro": "Intensitate (fixture)", "en": "Intensity (fixture)"},
        "unit": {"ro": "înnoptări pe locuitor", "en": "stays per resident"},
        "definition": {"ro": "Înnoptări împărțite la populație.", "en": "Stays divided by population."},
        "formula": "intensity(area, Y) = stays(area, Y) / population(area, Y)",
        "geo_level": "county", "universe": "denominator",
        "numerator": {"role": "stays", "dataset": num, "concept": "fx_stays",
                      "group_by": ["REF_AREA", "TIME_PERIOD"], "filters": {},
                      "reference": {"ro": "anul Y (flux)", "en": "calendar year Y (flow)"}},
        "denominator": {"role": "population", "dataset": den, "concept": "fx_population",
                        "group_by": ["REF_AREA", "TIME_PERIOD"], "filters": {},
                        "reference": {"ro": "1 ianuarie (stoc)", "en": "1 January (stock)"}},
        "unit_multipliers": {"Numar": 1, "Numar persoane": 1},
        "display_decimals": 2, "missing_policy": "excluded with its reason; no zero filling",
        "kind": "ratio",
        "columns": [{"key": "stays", "label": {"ro": "Înnoptări", "en": "Stays"}, "format": "int"},
                    {"key": "population", "label": {"ro": "Populație", "en": "Population"},
                     "format": "int"},
                    {"key": "value", "label": {"ro": "Valoare", "en": "Value"}, "format": "decimal"}],
    }
    r.update(over)
    return r


PUBLISHED = {
    "matrix": "PUBM", "cells": "Total x Total, every area",
    "formula": "value(area, Y) = INS's published cell (PUBM)",
    "reference": {"ro": "anul Y; totalul publicat de INS", "en": "year Y; the total INS publishes"},
    "status": {"ro": "valori publicate de INS", "en": "values published by INS"}}


def install_recipes(tmp_path, monkeypatch, *recipes):
    path = tmp_path / "recipes.json"
    path.write_text(json.dumps({"recipes": list(recipes)}))
    monkeypatch.setattr(rc, "RECIPES_PATH", path)


def published_table(corpus):
    db = duckdb.connect(str(corpus / "metadata.duckdb"))
    db.execute("CREATE TABLE published_totals (matrix_code VARCHAR, ref_area VARCHAR, "
               "time_period VARCHAR, value DOUBLE, unit VARCHAR, query_id VARCHAR, "
               "fetched_at VARCHAR, file_sha256 VARCHAR, meta_sha256 VARCHAR, ins_updated VARCHAR)")
    cells = [("Alfa", "2024", 10.0), ("Beta", "2024", 5.0), ("Gama", "2024", 5.0),
             ("Romania", "2024", 7.5), ("Alfa", "2022", 8.0), ("Beta", "2022", 4.0),
             ("Gama", "2022", 4.0)]
    for area, y, v in cells:
        db.execute("INSERT INTO published_totals VALUES ('PUBM', ?, ?, ?, 'Lei', 'PUBM-total', "
                   "'2026-10-12T00:00:00+00:00', 'f' || ?, 'm' || ?, '04-09-2025')",
                   [area, y, v, y, y])
    db.close()


def build_core(corpus):
    series(corpus, "STAYS1", "Stays fixture", "Numar", STAYS)
    series(corpus, "RESPOP", "Population fixture", "Numar persoane", POP)
    series(corpus, "PSTAY", "Published stays", "Numar", {("Alfa", 2024): 99.0, ("Beta", 2024): 50.0,
                                                          ("Gama", 2024): 50.0}, ys=(2024,))
    series(corpus, "PPOP", "Published population", "Numar persoane",
           {("Alfa", 2024): 10.0, ("Beta", 2024): 10.0, ("Gama", 2024): 10.0}, ys=(2024,))
    add_dataset(corpus, "PUBM", [], [], name="Published values", file=False)
    published_table(corpus)


RECIPES = [
    make_recipe("fx_intensity", "STAYS1", "RESPOP"),
    make_recipe("fx_published", "PSTAY", "PPOP", published=PUBLISHED, display_decimals=0),
    make_recipe("fx_badunit", "STAYS1", "RESPOP", unit_multipliers={"Numar": 1}),
]


@pytest.fixture
def env(tmp_path, monkeypatch):
    e = make_env(tmp_path, monkeypatch, build=build_core)
    install_recipes(tmp_path, monkeypatch, *RECIPES)
    return e


def all_keys(obj):
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield k
            yield from all_keys(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from all_keys(v)


def by_label(out):
    return {r["label"]: r for r in out["data"]["rows"]}


# ============================================================ run_recipe: ratio

def test_ratio_recipe_ranks_stays_per_resident(env):
    out = call("run_recipe", recipe="fx_intensity", year="2023", lang="en")
    assert out["status"] == "ok" and out["reason"] is None
    rows = out["data"]["rows"]
    assert [(r["rank"], r["label"], r["value"]) for r in rows] == [
        (1, "Gama", 3.0), (2, "Alfa", 2.0), (3, "Beta", 0.5)]
    assert by_label(out)["Alfa"] == {"rank": 2, "geo_id": "alfa", "label": "Alfa", "value": 2.0,
                                     "stays": 100.0, "population": 50.0, "intensity": 2.0}
    assert out["data"]["year"] == "2023" and out["data"]["requested_year"] == "2023"
    assert out["data"]["exclusion_counts"] == {} and out["data"]["excluded"] == []
    assert out["data"]["universe"] == 3 and out["data"]["check"] is None
    assert out["limits"] == {"returned_rows": 3, "total_rows": 3, "preview_truncated": False,
                             "source_complete": True, "time_windowed": False,
                             "partial_period_dropped": None}
    assert out["provenance"]["scope"]["domain_complete"] is True
    assert out["provenance"]["generation"]["id"] == GENERATION
    info = out["data"]["recipe"]
    assert (info["id"], info["version"], info["value_source"]) == ("fx_intensity", 3, "reconstruction")
    assert info["name"] == "Intensity (fixture)" and info["unit"] == "stays per resident"
    assert info["formula"].startswith("intensity(area, Y)") and "missing_policy" in info


def test_stays_120_over_population_60_is_2_and_bad_denominators_are_excluded(env):
    out = call("run_recipe", recipe="fx_intensity", lang="en")      # latest common year: 2024
    assert out["data"]["year"] == "2024"
    assert [(r["label"], r["stays"], r["population"], r["intensity"], r["rank"])
            for r in out["data"]["rows"]] == [("Alfa", 120.0, 60.0, 2.0, 1),
                                              ("Beta", 50.0, 100.0, 0.5, 2)]
    ex = {e["label"]: e["reason"] for e in out["data"]["excluded"]}
    assert ex == {"Gama": "denominator_not_positive",      # zero population
                  "Delta": "denominator_missing",         # NULL population
                  "Zeta": "numerator_missing",
                  "Eps": "not_in_denominator"}
    assert out["data"]["exclusion_counts"] == {
        "denominator_missing": 1, "denominator_not_positive": 1, "not_in_denominator": 1,
        "numerator_missing": 1}
    assert out["data"]["exclusions_truncated"] is False
    # eligibility and exclusions are visible: this is not the whole country
    assert out["status"] == "partial" and out["reason"] == "incomplete_domain"
    assert "2 of 5 eligible" in out["message"] and "4 excluded" in out["message"]
    scope = out["provenance"]["scope"]
    assert scope["domain_complete"] is False
    assert "2 of 5 eligible areas ranked for 2024" in scope["description"]
    assert "denominator_not_positive: 1" in scope["description"]
    assert scope["limitations"][0]["code"] == "areas_excluded" and scope["limitations"][0]["count"] == 4
    assert out["limits"]["returned_rows"] == 2 and out["limits"]["total_rows"] == 2
    assert out["limits"]["source_complete"] is True


def test_latest_common_year_is_resolved_into_the_canonical_selection(env):
    out = call("run_recipe", recipe="fx_intensity")        # STAYS1 has 2025, RESPOP does not
    assert out["data"]["year"] == "2024" and out["data"]["requested_year"] is None
    prov = out["provenance"]
    assert prov["selection"] == {"kind": "recipe", "recipe": "fx_intensity", "year": "2024",
                                 "areas": None}
    assert prov["requested_selection"] == {"year": None, "areas": None}
    assert prov["effective_selection"]["source_queries"] == {
        "stays": {"dataset": "STAYS1", "filters": {}, "group_by": ["REF_AREA", "TIME_PERIOD"],
                  "approximate": False},
        "population": {"dataset": "RESPOP", "filters": {}, "group_by": ["REF_AREA", "TIME_PERIOD"],
                       "approximate": False}}
    assert data_years(out) == ["2023", "2024"]
    # the canonical selection is directly citable
    links = call("get_evidence_links", selection=prov["selection"], generation_id=GENERATION)
    assert links["status"] == "ok"
    assert "year=2024" in [l for l in links["data"]["links"] if l["kind"] == "evidence"][0]["url"]


def data_years(out):
    return out["data"]["years_available"]


def test_provenance_names_every_source_with_role_unit_and_reference(env):
    out = call("run_recipe", recipe="fx_intensity", year="2023", lang="en")
    prov = out["provenance"]
    stays, pop = prov["sources"]
    assert (stays["role"], stays["dataset"], stays["unit"], stays["metric"]) == (
        "stays", "STAYS1", "Numar", "Stays fixture")
    assert (pop["role"], pop["dataset"], pop["unit"]) == ("population", "RESPOP", "Numar persoane")
    assert stays["reference"] == "calendar year Y (flow)" and pop["reference"] == "1 January (stock)"
    assert stays["url"].endswith("/dataset-v2.html?code=STAYS1&lang=en")
    assert stays["source_updated"] == "2026-01-15" and stays["definition"] == "Stays fixture"
    assert set(prov["aggregation"]["sources"]) == {"stays", "population"}
    assert prov["aggregation"]["sources"]["stays"]["outcome"] == "valid_total"
    assert prov["quality"]["stays"]["grain"]["status"] == "unique"


def test_explicit_year_is_exact_and_an_unavailable_year_is_refused(env):
    out = call("run_recipe", recipe="fx_intensity", year="2025", lang="en")
    # STAYS1 has 2025, RESPOP has not: never the nearest year, never a mix
    assert out["status"] == "unavailable" and out["reason"] == "period_unavailable"
    assert out["data"]["requested_year"] == "2025"
    assert out["data"]["years_available"] == ["2023", "2024"]
    assert "rows" not in out["data"] and out["provenance"]["selection"] is None
    assert "2025" in out["message"] and "was not changed" in out["message"]
    nxt = out["recovery"][0]
    assert nxt["kind"] == "tool_call" and nxt["tool"] == "run_recipe"
    assert nxt["arguments"] == {"recipe": "fx_intensity", "year": "2024", "lang": "en"}
    # the suggestion is a candidate: following it works
    assert call("run_recipe", **nxt["arguments"])["data"]["year"] == "2024"


def test_unknown_recipe_is_an_error_with_a_discovery_recovery(env):
    out = call("run_recipe", recipe="no_such_recipe", lang="en")
    assert out["status"] == "error" and out["reason"] == "unknown_recipe"
    assert out["data"]["available_recipes"] == ["fx_badunit", "fx_intensity", "fx_published"]
    assert "fx_intensity" in out["message"]
    assert out["recovery"][0]["tool"] == "discover_indicators"
    assert out["recovery"][0]["arguments"]["query"] == "no such recipe"


def test_unknown_area_is_an_exclusion_never_a_fuzzy_match(env):
    out = call("run_recipe", recipe="fx_intensity", year="2023", areas=["Alfa", "Alpha"], lang="en")
    assert [r["label"] for r in out["data"]["rows"]] == ["Alfa"]
    assert out["data"]["excluded"] == [{"geo_id": "alpha", "label": "Alpha", "reason": "not_in_data"}]
    assert out["status"] == "partial"
    assert out["provenance"]["scope"]["domain_complete"] is False
    codes = [l["code"] for l in out["provenance"]["scope"]["limitations"]]
    assert codes == ["areas_excluded", "areas_subset"]
    assert "not a national ranking" in out["provenance"]["scope"]["description"]
    assert out["provenance"]["selection"]["areas"] == ["Alfa", "Alpha"]
    assert out["provenance"]["requested_selection"] == {"year": "2023", "areas": ["Alfa", "Alpha"]}


def test_area_subset_whose_areas_all_exist_is_complete_for_the_request(env):
    out = call("run_recipe", recipe="fx_intensity", year="2023", areas=["Beta", "Alfa"])
    assert out["status"] == "ok"
    assert [r["label"] for r in out["data"]["rows"]] == ["Alfa", "Beta"]      # ranked, not in input order
    assert out["provenance"]["scope"]["domain_complete"] is True
    assert [l["code"] for l in out["provenance"]["scope"]["limitations"]] == ["areas_subset"]


def test_exclusion_sample_is_bounded_but_counts_cover_everything(env):
    names = [f"Nowhere {i:02d}" for i in range(30)]
    out = call("run_recipe", recipe="fx_intensity", year="2023", areas=["Alfa", *names])
    d = out["data"]
    assert len(d["excluded"]) == 20 and d["exclusions_truncated"] is True
    assert d["exclusion_counts"] == {"not_in_data": 30}
    assert out["limits"]["returned_rows"] == 1 and out["status"] == "partial"
    # every reason stays represented when the sample is cut
    out = call("run_recipe", recipe="fx_intensity", areas=[*names, "Gama", "Delta", "Zeta", "Eps"])
    reasons = {e["reason"] for e in out["data"]["excluded"]}
    assert len(out["data"]["excluded"]) == 20
    assert reasons == {"not_in_data", "denominator_not_positive", "denominator_missing",
                       "numerator_missing", "not_in_denominator"}


def test_no_raw_inputs_or_reconstruction_tables_reach_the_envelope(env):
    for rid in ("fx_intensity", "fx_published"):
        for y in (None, "2023", "2024"):
            out = call("run_recipe", recipe=rid, year=y)
            keys = set(all_keys(out))
            assert "inputs" not in keys and "table" not in keys, (rid, y)
            assert C.size(out) <= C.MAX_RESULT_BYTES
    # input series of other years (Alfa's 2025 stays, 130) are not in a 2024 result
    assert "130.0" not in C.dumps(call("run_recipe", recipe="fx_intensity"))


def test_english_and_romanian_messages(env):
    ro = call("run_recipe", recipe="fx_intensity", year="2023")
    assert ro["message"] == "Rețeta fx_intensity, 2023: 3 zone clasate."
    assert ro["data"]["recipe"]["name"] == "Intensitate (fixture)"
    assert "Totalurile" not in ro["message"]
    en = call("run_recipe", recipe="fx_intensity", year="2023", lang="en")
    assert en["message"] == "Recipe fx_intensity, 2023: 3 areas ranked."


# ============================================================ run_recipe: published

def test_published_value_is_served_with_reconstruction_as_the_check(env):
    out = call("run_recipe", recipe="fx_published", lang="en")
    d = out["data"]
    assert d["year"] == "2024" and out["status"] == "ok"
    alfa = by_label(out)["Alfa"]
    assert alfa["value"] == 10.0 and alfa["reconstructed"] == pytest.approx(9.9)
    assert (alfa["stays"] if "stays" in alfa else None) is None      # components are the published cell's
    assert alfa["rank"] == 1
    assert d["recipe"]["value_source"] == "ins_published"
    assert d["recipe"]["reconstruction_formula"].startswith("intensity(area, Y)")
    assert d["recipe"]["formula"].startswith("value(area, Y) = INS's published cell")
    assert d["check"]["compared"] == 3
    assert d["check"]["max_abs_diff"] == pytest.approx(0.1)
    assert d["check"]["equal_when_rounded"] == 3 and d["check"]["decimals"] == 0
    assert d["aggregates"] == [{"geo_id": "romania", "label": "Romania", "value": 7.5}]
    assert d["universe"] == 3
    roles = {s["role"]: s for s in out["provenance"]["sources"]}
    assert list(roles) == ["published", "stays", "population"]
    assert roles["published"]["dataset"] == "PUBM" and roles["published"]["unit"] == "Lei"
    assert roles["published"]["source_updated"] == "04-09-2025"
    assert out["provenance"]["aggregation"]["sources"]["published"] == {
        "outcome": "valid_total", "method": "source_total"}
    assert out["provenance"]["effective_selection"]["source_queries"]["published"]["year"] == "2024"
    assert out["provenance"]["selection"]["year"] == "2024"
    assert not any(w["code"] == "published_totals_unavailable" for w in out["warnings"])


def test_published_year_without_a_reconstruction_has_no_check(env):
    out = call("run_recipe", recipe="fx_published", year="2022")
    assert out["status"] == "ok" and out["data"]["year"] == "2022"
    assert by_label(out)["Alfa"]["value"] == 8.0 and by_label(out)["Alfa"]["reconstructed"] is None
    assert out["data"]["check"] is None
    assert out["data"]["recipe"]["value_source"] == "ins_published"
    assert out["data"]["years_available"] == ["2022", "2024"]
    assert [w["code"] for w in out["warnings"]] == ["check_unavailable"]
    assert [s["role"] for s in out["provenance"]["sources"]] == ["published"]


def test_published_unavailable_year_lists_published_years(env):
    out = call("run_recipe", recipe="fx_published", year="2023")
    assert out["reason"] == "period_unavailable" and out["data"]["years_available"] == ["2022", "2024"]
    assert out["recovery"][0]["arguments"]["year"] == "2024"


def test_generation_without_published_totals_reconstructs_and_says_so(tmp_path, monkeypatch):
    def build(corpus):
        build_core(corpus)
        db = duckdb.connect(str(corpus / "metadata.duckdb"))
        db.execute("DROP TABLE published_totals")
        db.close()
    make_env(tmp_path, monkeypatch, build=build)
    install_recipes(tmp_path, monkeypatch, *RECIPES)
    out = call("run_recipe", recipe="fx_published")
    assert out["data"]["recipe"]["value_source"] == "reconstruction"
    assert by_label(out)["Alfa"]["value"] == pytest.approx(9.9)
    assert [w["code"] for w in out["warnings"]] == ["published_totals_unavailable"]


# ============================================================ run_recipe: refusals

def test_unsupported_unit_is_refused_with_the_native_reason(env):
    out = call("run_recipe", recipe="fx_badunit", lang="en")
    assert out["status"] == "unavailable" and out["reason"] == "unsupported_unit"
    assert out["data"]["unit"] == "Numar persoane" and out["data"]["source"] == "population"
    assert out["recovery"][0] == {
        "kind": "tool_call", "message": "Read this source's quality, grain status and notes.",
        "tool": "describe_dataset", "arguments": {"dataset": "RESPOP", "lang": "en"}}
    assert "rows" not in out["data"]


def test_capped_source_is_never_ranked(env, monkeypatch):
    monkeypatch.setattr(config, "MAX_DATA_ROWS", 3)       # recipes read their sources up to this cap
    out = call("run_recipe", recipe="fx_intensity", lang="en")
    assert out["status"] == "unavailable" and out["reason"] == "source_incomplete"
    assert "partial source is never ranked" in out["message"]
    assert out["data"]["source"] == "stays"
    assert out["recovery"][0]["arguments"]["dataset"] == "STAYS1"


def test_conflicting_source_is_refused_by_the_shared_policy(tmp_path, monkeypatch):
    def build(corpus):
        build_core(corpus)
        rows = [("Alfa", "2024", "Numar", 1.0), ("Alfa", "2024", "Numar", 2.0),
                ("Beta", "2024", "Numar", 3.0)]
        add_dataset(corpus, "STAYSD", [geo(AREAS), years([2024]), unit("Numar")], rows,
                    name="Duplicated stays")
    make_env(tmp_path, monkeypatch, build=build, conflicting=("STAYSD",))
    install_recipes(tmp_path, monkeypatch, make_recipe("fx_dup", "STAYSD", "RESPOP"))
    out = call("run_recipe", recipe="fx_dup", lang="en")
    assert out["status"] == "unavailable" and out["reason"] == "source_unavailable"
    assert out["data"]["source_reason"] and out["data"]["source_reason"] in out["message"]
    assert out["recovery"][0]["arguments"]["dataset"] == "STAYSD"
    assert "rows" not in out["data"]


def test_missing_generation_is_not_certified(tmp_path, monkeypatch):
    make_env(tmp_path, monkeypatch, build=build_core, generation_id=None)
    install_recipes(tmp_path, monkeypatch, *RECIPES)
    out = call("run_recipe", recipe="fx_intensity")
    assert out["status"] == "unavailable" and out["reason"] == "generation_unverified"
    assert out["provenance"]["generation"]["id"] is None and out["data"] == {}


def test_a_source_that_cannot_be_read_is_an_error_without_internals(env, monkeypatch):
    def boom(*a, **k):
        raise rc.RecipeError("source_failed", "STAYS1: /srv/data/x.parquet SELECT secret")
    monkeypatch.setattr(rc, "run", boom)
    out = call("run_recipe", recipe="fx_intensity", lang="en")
    assert out["status"] == "error" and out["reason"] == "execution_failed"
    text = json.dumps(out)
    assert "/srv" not in text and "SELECT" not in text and "reference" in out["message"]


def test_a_generation_swap_during_the_recipe_is_not_reported(env, monkeypatch):
    real = rc.run

    def swapping(*a, **k):
        res = real(*a, **k)
        write_manifest(env.corpus, "gen-swapped")
        return res
    monkeypatch.setattr(rc, "run", swapping)
    out = call("run_recipe", recipe="fx_intensity")
    assert out["status"] == "unavailable" and out["reason"] == "generation_changed"
    assert out["data"] == {} and "rows" not in out["data"]


def build_refusals(corpus):
    build_core(corpus)
    series(corpus, "DJ1", "Stays 2023 only", "Numar", {("Alfa", 2023): 1.0}, ys=(2023,))
    series(corpus, "DJ2", "Population 2025 only", "Numar persoane", {("Alfa", 2025): 1.0}, ys=(2025,))
    # two labels of one area (same id after normalization) in the same year
    series(corpus, "DUPL1", "Stays, one area twice", "Numar",
           {("Alfa", 2024): 1.0, ("ALFA", 2024): 2.0}, names=["Alfa", "ALFA"], ys=(2024,))
    db = duckdb.connect(str(corpus / "metadata.duckdb"))
    db.execute("INSERT INTO published_totals VALUES ('PUBN', 'Romania', '2024', 7.5, 'Lei', 'q', "
               "'2026-10-12T00:00:00+00:00', 'f', 'm', '04-09-2025')")
    db.close()


@pytest.fixture
def refusal_env(tmp_path, monkeypatch):
    e = make_env(tmp_path, monkeypatch, build=build_refusals)
    install_recipes(tmp_path, monkeypatch, *RECIPES,
                    make_recipe("fx_nocommon", "DJ1", "DJ2"),
                    make_recipe("fx_dupkey", "DUPL1", "RESPOP"),
                    make_recipe("fx_nopub", "PSTAY", "PPOP", published={**PUBLISHED, "matrix": "PUBN"}))
    return e


@pytest.mark.parametrize("rid,reason,source", [
    ("fx_nocommon", "no_common_year", None),
    ("fx_dupkey", "duplicate_key", "stays"),
    ("fx_nopub", "no_published_data", None)])
def test_native_refusals_keep_their_reason(refusal_env, rid, reason, source):
    out = call("run_recipe", recipe=rid, lang="en")
    assert out["status"] == "unavailable" and out["reason"] == reason
    assert out["data"].get("source") == source and "rows" not in out["data"]
    assert out["provenance"]["selection"] is None and out["limits"]["source_complete"] is None
    if reason == "no_common_year":
        assert out["data"]["years_numerator"] == ["2023"] and out["data"]["years_denominator"] == ["2025"]
    if reason == "duplicate_key":
        assert out["recovery"][0]["arguments"]["dataset"] == "DUPL1"


def test_nothing_ranked_is_unavailable_and_keeps_the_reasons(env):
    out = call("run_recipe", recipe="fx_intensity", year="2023", areas=["Atlantis", "Narnia"], lang="en")
    assert out["status"] == "unavailable" and out["reason"] == "incomplete_domain"
    d = out["data"]
    assert d["rows"] == [] and d["exclusion_counts"] == {"not_in_data": 2} and d["universe"] == 0
    assert [e["label"] for e in d["excluded"]] == ["Atlantis", "Narnia"]
    assert "no area could be ranked" in out["message"]
    assert out["provenance"]["scope"]["domain_complete"] is False
    assert out["limits"]["returned_rows"] == 0 and out["limits"]["total_rows"] == 0
    assert out["recovery"][0] == {
        "kind": "tool_call", "message": "Run the recipe for every area to see the names the data uses.",
        "tool": "run_recipe", "arguments": {"recipe": "fx_intensity", "year": "2023", "lang": "en"}}


# ============================================================ run_recipe: budget

def test_large_result_is_shortened_to_the_budget_without_losing_provenance(tmp_path, monkeypatch):
    names = [f"Zona {'x' * 40} {i:03d}" for i in range(220)]

    def build(corpus):
        s = {(n, 2024): 100.0 + i for i, n in enumerate(names)}
        p = {(n, 2024): 50.0 for n in names}
        series(corpus, "BIGS", "Big stays", "Numar", s, names=names, ys=(2024,))
        series(corpus, "BIGP", "Big population", "Numar persoane", p, names=names, ys=(2024,))
    make_env(tmp_path, monkeypatch, build=build)
    install_recipes(tmp_path, monkeypatch, make_recipe("fx_big", "BIGS", "BIGP"))
    out = call("run_recipe", recipe="fx_big")
    assert C.size(out) <= C.MAX_RESULT_BYTES
    n = len(out["data"]["rows"])
    assert 0 < n < 200
    assert out["limits"]["returned_rows"] == n and out["limits"]["total_rows"] == 220
    assert out["limits"]["preview_truncated"] is True
    assert [r["rank"] for r in out["data"]["rows"]] == list(range(1, n + 1))     # the top of the ranking
    assert [w["code"] for w in out["warnings"]].count("preview_shortened") == 1
    assert out["status"] == "ok" and out["provenance"]["selection"]["year"] == "2024"
    assert len(out["provenance"]["sources"]) == 2 and out["provenance"]["scope"]["domain_complete"] is True


def test_shrink_cuts_samples_before_rows_and_says_so_once(env):
    out = call("run_recipe", recipe="fx_published", areas=["Alfa", "Atlantis"])
    assert out["data"]["excluded"] and out["data"]["aggregates"] and out["data"]["rows"]
    counts = dict(out["data"]["exclusion_counts"])
    e = json.loads(json.dumps(out))
    assert recipe_tool.shrink(e) is True                        # 1: the exclusion sample
    assert e["data"]["excluded"] == [] and e["data"]["exclusions_truncated"] is True
    assert e["data"]["exclusion_counts"] == counts and e["data"]["rows"]
    assert recipe_tool.shrink(e) is True                        # 2: the published aggregate cells
    assert e["data"]["aggregates"] == [] and e["data"]["aggregates_truncated"] is True
    assert e["data"]["rows"] and e["limits"]["preview_truncated"] is False
    assert recipe_tool.shrink(e) is True                        # 3: the ranking rows
    assert e["data"]["rows"] == []
    assert e["limits"]["returned_rows"] == 0 and e["limits"]["preview_truncated"] is True
    assert [w["code"] for w in e["warnings"]] == ["preview_shortened"]
    assert recipe_tool.shrink(e) is False                       # nothing left to cut
    assert e["provenance"]["selection"] == out["provenance"]["selection"]
    assert e["data"]["check"] == out["data"]["check"]


# ============================================================ run_recipe: weighted mean

def test_weighted_mean_rows_carry_their_weights(tmp_path, monkeypatch):
    cols = [("SECT", "Sectiune", None, [("A  Agri", {}), ("B  Mine", {}), ("05 Div", {})]),
            geo(["X", "Y"]), years([2024]), unit("Lei")]
    wcols = [cols[0], cols[1], cols[2], unit("Numar")]

    def build(corpus):
        add_dataset(corpus, "EARN", cols,
                    [("A  Agri", "X", "2024", "Lei", 1000.0), ("B  Mine", "X", "2024", "Lei", 3000.0),
                     ("05 Div", "X", "2024", "Lei", 99999.0), ("A  Agri", "Y", "2024", "Lei", 500.0),
                     ("B  Mine", "Y", "2024", "Lei", 700.0)], name="Earnings")
        add_dataset(corpus, "EMPL", wcols,
                    [("A  Agri", "X", "2024", "Numar", 3.0), ("B  Mine", "X", "2024", "Numar", 1.0),
                     ("05 Div", "X", "2024", "Numar", 50.0), ("A  Agri", "Y", "2024", "Numar", 1.0),
                     ("B  Mine", "Y", "2024", "Numar", 1.0)], name="Employees")
    make_env(tmp_path, monkeypatch, build=build)
    rec = {
        "id": "fx_wm", "version": 1, "question": "Q", "kind": "weighted_mean",
        "status": {"ro": "s", "en": "s"}, "name": {"ro": "Câștig", "en": "Earnings"},
        "unit": {"ro": "lei", "en": "lei"}, "definition": {"ro": "d", "en": "d"},
        "formula": "earnings = sum(e x w) / sum(w)", "display_decimals": 0, "missing_policy": "m",
        "values": {"role": "earnings", "dataset": "EARN", "group_by": ["SECT", "REF_AREA", "TIME_PERIOD"],
                   "filters": {}, "reference": {"ro": "an", "en": "year"}},
        "weights": {"role": "employees", "dataset": "EMPL", "group_by": ["SECT", "REF_AREA", "TIME_PERIOD"],
                    "filters": {}, "reference": {"ro": "an", "en": "year"}},
        "cell_columns": ["SECT"], "keep": {"SECT": "^[A-S]  "},
        "columns": [{"key": "value", "label": {"ro": "v", "en": "v"}, "format": "int"}]}
    install_recipes(tmp_path, monkeypatch, rec)
    out = call("run_recipe", recipe="fx_wm")
    assert out["status"] == "ok" and out["data"]["year"] == "2024"
    rows = by_label(out)
    assert rows["X"]["value"] == pytest.approx(1500.0)        # (1000*3 + 3000*1) / 4, the division is outside `keep`
    assert (rows["X"]["weight_total"], rows["X"]["cells"]) == (4.0, 2)
    assert rows["Y"]["value"] == pytest.approx(600.0) and rows["Y"]["rank"] == 2
    assert [s["role"] for s in out["provenance"]["sources"]] == ["earnings", "employees"]
    assert "inputs" not in set(all_keys(out))


# ============================================================ get_evidence_links

GEN = GENERATION
FJ = "%7B%22CATEGORY%22%3A%5B%22A%22%5D%7D"           # {"CATEGORY":["A"]}
GJ = "%5B%22TIME_PERIOD%22%5D"                         # ["TIME_PERIOD"]


def dataset_selection(**kw):
    return {"kind": "dataset", "dataset": "ADDX", "filters": {"CATEGORY": ["A"]},
            "group_by": ["TIME_PERIOD"], "approximate": False, **kw}


def link_map(out):
    return {l["kind"]: l for l in out["data"]["links"]}


def query_of(url):
    return {k: v[0] for k, v in parse_qs(urlsplit(url).query, keep_blank_values=True).items()}


@pytest.fixture
def links_env(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "PUBLIC_BASE_URL", "")
    e = make_env(tmp_path, monkeypatch, build=build_core)
    install_recipes(tmp_path, monkeypatch, *RECIPES)
    return e


def test_dataset_links_have_exact_paths_and_params(links_env):
    out = call("get_evidence_links", selection=dataset_selection(), generation_id=GEN)
    assert out["status"] == "ok" and out["reason"] is None
    L = link_map(out)
    assert list(L) == ["dataset", "live_selection", "csv", "evidence"]
    assert L["dataset"]["url"] == f"/dataset-v2.html?code=ADDX&f={FJ}"
    assert L["live_selection"]["url"] == f"/api/datasets/ADDX/data?filters={FJ}&group_by={GJ}&approximate=0"
    assert L["csv"]["url"] == f"/api/datasets/ADDX/download?format=csv&filters={FJ}"
    assert L["evidence"]["url"] == (f"/api/datasets/ADDX/evidence?filters={FJ}&group_by={GJ}"
                                    f"&approximate=0&expected_generation={GEN}")
    assert [L[k]["generation_mode"] for k in L] == [
        "live_rerun", "live_rerun", "live_rerun", "expected_generation"]
    assert f"generația {GEN}" in L["evidence"]["description"] and "409" in L["evidence"]["description"]
    en = link_map(call("get_evidence_links", selection=dataset_selection(), generation_id=GEN, lang="en"))
    assert "raw observations" in en["csv"]["description"] and "Not the aggregated" in en["csv"]["description"]
    assert f"generation {GEN}" in en["evidence"]["description"] and "409" in en["evidence"]["description"]
    assert "Live re-run" in en["live_selection"]["description"]
    assert out["data"]["selection"] == dataset_selection() and out["data"]["generation_id"] == GEN
    # the JSON parameters decode back to the selection
    q = query_of(L["evidence"]["url"])
    assert json.loads(q["filters"]) == {"CATEGORY": ["A"]} and json.loads(q["group_by"]) == ["TIME_PERIOD"]


def test_english_links_add_lang_only_when_english(links_env):
    en = call("get_evidence_links", selection=dataset_selection(approximate=True), generation_id=GEN,
              lang="en")
    L = link_map(en)
    assert L["dataset"]["url"] == f"/dataset-v2.html?code=ADDX&f={FJ}&lang=en"
    assert L["live_selection"]["url"].endswith("&approximate=1") and "lang" not in L["live_selection"]["url"]
    assert L["csv"]["url"] == f"/api/datasets/ADDX/download?format=csv&filters={FJ}&lang=en"
    assert L["evidence"]["url"].endswith(f"&approximate=1&lang=en&expected_generation={GEN}")
    assert "Live re-run" in L["live_selection"]["description"]
    ro = call("get_evidence_links", selection=dataset_selection(), generation_id=GEN)
    assert not any("lang=" in l["url"] for l in ro["data"]["links"])
    assert "Reexecutare live" in link_map(
        call("get_evidence_links", selection=dataset_selection(), generation_id=GEN,
             lang="ro"))["live_selection"]["description"]


def test_links_use_the_configured_origin_or_stay_root_relative(links_env, monkeypatch):
    rel = call("get_evidence_links", selection=dataset_selection(), generation_id=GEN)
    assert all(l["url"].startswith("/") for l in rel["data"]["links"])
    monkeypatch.setattr(config, "PUBLIC_BASE_URL", "https://ins.example")
    out = call("get_evidence_links", selection=dataset_selection(), generation_id=GEN)
    assert all(l["url"].startswith("https://ins.example/") for l in out["data"]["links"])
    assert link_map(out)["live_selection"]["url"].startswith("https://ins.example/api/datasets/ADDX/data?")
    assert [l["url"].removeprefix("https://ins.example") for l in out["data"]["links"]] == \
           [l["url"] for l in rel["data"]["links"]]
    for src in out["provenance"]["sources"]:
        assert src["url"].startswith("https://ins.example/dataset-v2.html")


def test_dataset_without_filters_or_grouping(links_env):
    out = call("get_evidence_links", selection={"kind": "dataset", "dataset": "ADDX"}, generation_id=GEN)
    L = link_map(out)
    assert L["dataset"]["url"] == "/dataset-v2.html?code=ADDX"
    assert L["live_selection"]["url"] == "/api/datasets/ADDX/data?filters=%7B%7D&group_by=%5B%5D&approximate=0"
    assert out["data"]["selection"] == {"kind": "dataset", "dataset": "ADDX", "filters": {},
                                        "group_by": [], "approximate": False}


def test_empty_filter_lists_are_normalized_away_and_reported(links_env):
    sel = dataset_selection(filters={"CATEGORY": ["A"], "TIME_PERIOD": []})
    out = call("get_evidence_links", selection=sel, generation_id=GEN)
    assert out["data"]["selection"]["filters"] == {"CATEGORY": ["A"]}
    assert out["warnings"] == [{"code": "empty_filter_ignored", "subject": "TIME_PERIOD",
                                "message": out["warnings"][0]["message"]}]
    assert link_map(out)["evidence"]["url"].startswith(f"/api/datasets/ADDX/evidence?filters={FJ}&")
    assert out["provenance"]["selection"] == out["data"]["selection"]


def test_recipe_links(links_env):
    areas = ["Alfa", "Țara Bârsei"]
    sel = {"kind": "recipe", "recipe": "fx_intensity", "year": "2024", "areas": areas}
    out = call("get_evidence_links", selection=sel, generation_id=GEN)
    L = link_map(out)
    aj = "%5B%22Alfa%22%2C%22%C8%9Aara%20B%C3%A2rsei%22%5D"
    assert list(L) == ["dataset", "live_selection", "evidence"]
    assert L["dataset"]["url"] == f"/compare.html?recipe=fx_intensity&year=2024&areas={aj}"
    assert L["live_selection"]["url"] == f"/api/recipes/fx_intensity?year=2024&areas={aj}"
    assert L["evidence"]["url"] == (f"/api/recipes/fx_intensity/evidence?year=2024&areas={aj}"
                                    f"&expected_generation={GEN}")
    assert json.loads(query_of(L["evidence"]["url"])["areas"]) == areas
    assert [L[k]["generation_mode"] for k in L] == ["live_rerun", "live_rerun", "expected_generation"]
    assert out["data"]["selection"] == sel
    # same parameters the concept-search recipe card builds for the compare page
    from urllib.parse import urlencode
    card = query_of("/compare.html?" + urlencode(
        {"recipe": "fx_intensity", "areas": json.dumps(areas, ensure_ascii=False), "year": "2024"}))
    mine = query_of(L["dataset"]["url"])
    assert {k: v for k, v in mine.items() if k != "areas"} == {k: v for k, v in card.items() if k != "areas"}
    assert json.loads(mine["areas"]) == json.loads(card["areas"])          # the page JSON.parses it
    en = call("get_evidence_links", selection={**sel, "areas": None}, generation_id=GEN, lang="en")
    assert link_map(en)["evidence"]["url"] == (
        f"/api/recipes/fx_intensity/evidence?year=2024&lang=en&expected_generation={GEN}")
    assert link_map(en)["dataset"]["url"] == "/compare.html?recipe=fx_intensity&year=2024&lang=en"


def test_recipe_sources_are_the_recipes_datasets(links_env):
    out = call("get_evidence_links", selection={"kind": "recipe", "recipe": "fx_published", "year": "2024"},
               generation_id=GEN)
    assert [(s["role"], s["dataset"]) for s in out["provenance"]["sources"]] == [
        ("published", "PUBM"), ("stays", "PSTAY"), ("population", "PPOP")]
    assert out["provenance"]["selection"] == out["data"]["selection"]


def test_period_changes_links(links_env):
    sel = {"kind": "period_changes", "dataset": "ADDX", "entity_columns": ["CATEGORY"],
           "intervals": [{"from": "2022", "to": "2023"}], "filters": {"CATEGORY": ["A", "B"]},
           "metric": "percent", "order": "desc", "top_k": 5}
    out = call("get_evidence_links", selection=sel, generation_id=GEN, lang="en")
    L = link_map(out)
    assert list(L) == ["dataset", "live_selection", "evidence"]
    assert out["data"]["selection"] == sel
    base = ("dataset=ADDX&entity_columns=%5B%22CATEGORY%22%5D"
            "&intervals=%5B%7B%22from%22%3A%222022%22%2C%22to%22%3A%222023%22%7D%5D"
            "&filters=%7B%22CATEGORY%22%3A%5B%22A%22%2C%22B%22%5D%7D&metric=percent&order=desc"
            "&top_k=5&lang=en")
    assert L["live_selection"]["url"] == f"/api/period-changes?{base}"
    assert L["evidence"]["url"] == f"/api/period-changes/evidence?{base}&expected_generation={GEN}"
    assert L["dataset"]["url"].startswith("/dataset-v2.html?code=ADDX&f=")
    q = query_of(L["evidence"]["url"])
    assert json.loads(q["intervals"]) == [{"from": "2022", "to": "2023"}]
    assert json.loads(q["entity_columns"]) == ["CATEGORY"] and q["expected_generation"] == GEN
    assert [L[k]["generation_mode"] for k in L] == ["live_rerun", "live_rerun", "expected_generation"]
    ro = call("get_evidence_links", selection={k: v for k, v in sel.items() if k not in (
        "metric", "order", "top_k", "filters")}, generation_id=GEN)
    assert link_map(ro)["live_selection"]["url"] == (
        "/api/period-changes?dataset=ADDX&entity_columns=%5B%22CATEGORY%22%5D"
        "&intervals=%5B%7B%22from%22%3A%222022%22%2C%22to%22%3A%222023%22%7D%5D&filters=%7B%7D"
        "&metric=absolute&order=asc&top_k=20")


def test_links_are_built_without_running_any_query(links_env, monkeypatch):
    from app.services import data_query

    def boom(*a, **k):
        raise AssertionError("a query was executed to build links")
    monkeypatch.setattr(data_query, "run_query", boom)
    monkeypatch.setattr(rc, "run", boom)
    for sel in (dataset_selection(), {"kind": "recipe", "recipe": "fx_intensity", "year": "2024"}):
        assert call("get_evidence_links", selection=sel, generation_id=GEN)["status"] == "ok"


# ---- generation

def test_a_different_generation_yields_no_links(links_env):
    out = call("get_evidence_links", selection=dataset_selection(), generation_id="gen-older",
               lang="en")
    assert out["status"] == "unavailable" and out["reason"] == "generation_changed"
    assert out["data"] == {"expected_generation": "gen-older", "served_generation": GEN}
    assert "links" not in out["data"] and out["provenance"]["selection"] is None
    assert "gen-older" in out["message"] and GEN in out["message"]
    assert out["recovery"][0]["kind"] == "retry"
    assert not any("expected_generation" in json.dumps(r) for r in out["recovery"])
    # the same for every selection kind
    for sel in ({"kind": "recipe", "recipe": "fx_intensity", "year": "2024"},
                {"kind": "period_changes", "dataset": "ADDX", "entity_columns": ["CATEGORY"],
                 "intervals": [{"from": "2022", "to": "2023"}]}):
        assert call("get_evidence_links", selection=sel, generation_id="gen-older")["reason"] == "generation_changed"


def test_an_unverified_served_generation_yields_no_links(tmp_path, monkeypatch):
    make_env(tmp_path, monkeypatch, build=build_core, generation_id=None)
    out = call("get_evidence_links", selection=dataset_selection(), generation_id=GEN)
    assert out["status"] == "unavailable" and out["reason"] == "generation_unverified"
    assert out["data"] == {}


# ---- validation

def test_unknown_dataset_column_and_recipe_are_errors(links_env):
    out = call("get_evidence_links", selection={"kind": "dataset", "dataset": "NOPE"},
               generation_id=GEN)
    assert out["status"] == "error" and out["reason"] == "unknown_dataset"
    assert out["recovery"][0]["tool"] == "discover_indicators" and out["data"] == {}
    # a split parent: row but no data file
    out = call("get_evidence_links", selection={"kind": "dataset", "dataset": "PUBM"}, generation_id=GEN, lang="en")
    assert out["reason"] == "unknown_dataset" and "sub-datasets" in out["message"]
    assert out["recovery"][0] == {
        "kind": "tool_call", "message": "Read the dataset's columns, values and sub-datasets.",
        "tool": "describe_dataset", "arguments": {"dataset": "PUBM", "lang": "en"}}
    for sel in (dataset_selection(filters={"NOCOL": ["x"]}),
                dataset_selection(group_by=["NOCOL"]),
                {"kind": "period_changes", "dataset": "ADDX", "entity_columns": ["NOCOL"],
                 "intervals": [{"from": "2022", "to": "2023"}]},
                {"kind": "period_changes", "dataset": "ADDX", "entity_columns": ["CATEGORY"],
                 "intervals": [{"from": "2022", "to": "2023"}], "filters": {"NOCOL": ["x"]}}):
        out = call("get_evidence_links", selection=sel, generation_id=GEN)
        assert out["status"] == "error" and out["reason"] == "unknown_column", sel
        assert "NOCOL" in out["message"] and out["recovery"][0]["tool"] == "describe_dataset"
        assert out["data"] == {}
    out = call("get_evidence_links", selection={"kind": "recipe", "recipe": "no_such", "year": "2024"},
               generation_id=GEN)
    assert out["status"] == "error" and out["reason"] == "unknown_recipe"
    assert out["data"]["available_recipes"] == ["fx_badunit", "fx_intensity", "fx_published"]
    assert out["recovery"][0]["tool"] == "discover_indicators"


def test_period_changes_needs_a_time_column(tmp_path, monkeypatch):
    def build(corpus):
        add_dataset(corpus, "NOTIME", [("CATEGORY", "Categorie", None, [("A", {})])], [("A", 1.0)])
    make_env(tmp_path, monkeypatch, build=build)
    out = call("get_evidence_links", generation_id=GEN, selection={
        "kind": "period_changes", "dataset": "NOTIME", "entity_columns": ["CATEGORY"],
        "intervals": [{"from": "2022", "to": "2023"}]})
    assert out["status"] == "error" and out["reason"] == "unknown_column"
    assert "TIME_PERIOD" in out["message"]


def test_the_observation_value_is_not_a_dimension(links_env):
    out = R.call_tool("get_evidence_links", {"selection": dataset_selection(filters={"OBS_VALUE": [1]}),
                                             "generation_id": GEN})
    assert out["reason"] == "invalid_input"


# ---- 4 KiB

def test_an_overlong_link_is_refused_never_shortened(links_env):
    values = [f"{'v' * 40}{i:03d}" for i in range(100)]
    sel = dataset_selection(filters={"CATEGORY": values})
    out = call("get_evidence_links", selection=sel, generation_id=GEN, lang="en")
    assert out["status"] == "unavailable" and out["reason"] == "link_too_long"
    assert out["data"] == {} and "4096" in out["message"]
    assert out["recovery"][0]["kind"] == "narrow"
    assert "never shortened" in out["message"]
    # the same values in fewer numbers fit, and nothing was dropped
    fits = call("get_evidence_links", selection=dataset_selection(filters={"CATEGORY": values[:20]}),
                generation_id=GEN)
    assert fits["status"] == "ok"
    for l in fits["data"]["links"]:
        assert len(l["url"].encode()) <= 4096
    assert json.loads(query_of(link_map(fits)["evidence"]["url"])["filters"]) == {"CATEGORY": values[:20]}


def test_the_limit_is_on_the_encoded_url_bytes(links_env):
    # 45 values of 'ș' (2 UTF-8 bytes, 6 URL bytes each): short in characters, long once encoded
    sel = dataset_selection(filters={"CATEGORY": ["ș" * 60 + str(i) for i in range(45)]})
    out = call("get_evidence_links", selection=sel, generation_id=GEN)
    assert out["reason"] == "link_too_long"


def test_a_recipe_areas_list_the_routes_would_reject_is_link_too_long(links_env):
    areas = [f"{'a' * 85}{i:02d}" for i in range(24)]            # about 2,100 characters as JSON
    out = call("get_evidence_links", generation_id=GEN,
               selection={"kind": "recipe", "recipe": "fx_intensity", "year": "2024", "areas": areas})
    assert out["status"] == "unavailable" and out["reason"] == "link_too_long"
    assert "2000" in out["message"] and out["data"] == {}
    ok = call("get_evidence_links", generation_id=GEN,
              selection={"kind": "recipe", "recipe": "fx_intensity", "year": "2024", "areas": areas[:10]})
    assert ok["status"] == "ok"


def test_empty_areas_mean_all_areas(links_env):
    out = call("get_evidence_links", generation_id=GEN,
               selection={"kind": "recipe", "recipe": "fx_intensity", "year": "2024", "areas": []})
    assert out["data"]["selection"]["areas"] is None
    assert [w["code"] for w in out["warnings"]] == ["empty_filter_ignored"]
    assert "areas" not in query_of(link_map(out)["evidence"]["url"])


# ============================================================ evidence routes

def zip_manifest(content):
    z = zipfile.ZipFile(io.BytesIO(content))
    return z, json.loads(z.read("manifest.json"))


def test_dataset_evidence_link_round_trip_and_precondition(links_env):
    client = links_env.client
    out = call("get_evidence_links", generation_id=GEN, selection={
        "kind": "dataset", "dataset": "ADDX", "group_by": ["TIME_PERIOD"]})
    url = link_map(out)["evidence"]["url"]
    assert url.endswith(f"&expected_generation={GEN}")
    r = client.get(url)
    assert r.status_code == 200 and r.headers["content-type"] == "application/zip"
    z, m = zip_manifest(r.content)
    assert m["generation"]["id"] == GEN and m["dataset"] == "ADDX"
    assert {row["TIME_PERIOD"]: float(row["OBS_VALUE"]) for row in csv.DictReader(
        io.StringIO(z.read("result.csv").decode()))} == {"2022": 100.0, "2023": 120.0}
    # the old link, without the precondition, keeps its behaviour and its bytes' meaning
    old = url.split("&expected_generation=")[0]
    r_old = client.get(old)
    assert r_old.status_code == 200 and zip_manifest(r_old.content)[1]["generation"]["id"] == GEN
    assert zip_manifest(r_old.content)[0].namelist() == z.namelist()
    # the served generation moves on: the same link is now refused
    write_manifest(links_env.corpus, "gen-newer")
    r2 = client.get(url)
    assert r2.status_code == 409
    d = r2.json()["detail"]
    assert d["reason"] == "generation_changed" and d["expected_generation"] == GEN
    assert d["served_generation"] == "gen-newer" and d["served_status"] == "present"
    assert r2.headers["content-type"].startswith("application/json")
    # without the parameter the route still serves what is current
    r3 = client.get(old)
    assert r3.status_code == 200 and zip_manifest(r3.content)[1]["generation"]["id"] == "gen-newer"
    # and the tool refuses to link the old generation to the new data
    assert call("get_evidence_links", generation_id=GEN, selection={
        "kind": "dataset", "dataset": "ADDX"})["reason"] == "generation_changed"


def test_recipe_evidence_link_round_trip_and_precondition(links_env):
    client = links_env.client
    run = call("run_recipe", recipe="fx_intensity")                 # year resolved to 2024
    out = call("get_evidence_links", selection=run["provenance"]["selection"],
               generation_id=run["provenance"]["generation"]["id"])
    url = link_map(out)["evidence"]["url"]
    assert url == f"/api/recipes/fx_intensity/evidence?year=2024&expected_generation={GEN}"
    r = client.get(url)
    assert r.status_code == 200 and r.headers["content-type"] == "application/zip"
    z, m = zip_manifest(r.content)
    assert m["generation"]["id"] == GEN and m["recipe"] == "fx_intensity"
    result = list(csv.DictReader(io.StringIO(z.read("result.csv").decode())))
    assert [(x["label"], float(x["intensity"])) for x in result] == [("Alfa", 2.0), ("Beta", 0.5)]
    old = url.split("&expected_generation=")[0]
    assert client.get(old).status_code == 200
    write_manifest(links_env.corpus, "gen-newer")
    r2 = client.get(url)
    assert r2.status_code == 409
    assert r2.json()["detail"]["reason"] == "generation_changed"
    assert r2.json()["detail"]["expected_generation"] == GEN
    assert client.get(old).status_code == 200


def test_the_precondition_is_checked_again_before_the_bundle_is_sent(links_env, monkeypatch):
    import app.services.evidence as ev
    client = links_env.client
    real_dataset, real_recipe = ev.dataset_bundle, ev.recipe_bundle

    def swap_after(real):
        def wrapped(*a, **k):
            data = real(*a, **k)
            write_manifest(links_env.corpus, "gen-swapped-mid-build")
            return data
        return wrapped
    monkeypatch.setattr(ev, "dataset_bundle", swap_after(real_dataset))
    r = client.get(f"/api/datasets/ADDX/evidence?group_by=%5B%22TIME_PERIOD%22%5D&expected_generation={GEN}")
    assert r.status_code == 409 and r.json()["detail"]["served_generation"] == "gen-swapped-mid-build"
    assert r.headers["content-type"].startswith("application/json")           # no ZIP
    write_manifest(links_env.corpus, GEN)
    monkeypatch.setattr(ev, "recipe_bundle", swap_after(real_recipe))
    r = client.get(f"/api/recipes/fx_intensity/evidence?year=2024&expected_generation={GEN}")
    assert r.status_code == 409 and r.headers["content-type"].startswith("application/json")
    # without a precondition a swap changes nothing about the response
    write_manifest(links_env.corpus, GEN)
    assert client.get("/api/recipes/fx_intensity/evidence?year=2024").status_code == 200
    # the export slot was released by every refusal
    from app.services import export as ex
    slot = ex.try_acquire("csv")
    assert slot is not None
    slot()


def test_the_precondition_is_checked_before_anything_is_built(links_env, monkeypatch):
    import app.services.evidence as ev

    def boom(*a, **k):
        raise AssertionError("a bundle was built for a stale generation")
    monkeypatch.setattr(ev, "dataset_bundle", boom)
    monkeypatch.setattr(ev, "recipe_bundle", boom)
    client = links_env.client
    assert client.get("/api/datasets/ADDX/evidence?expected_generation=gen-older").status_code == 409
    assert client.get("/api/recipes/fx_intensity/evidence?expected_generation=gen-older").status_code == 409


def test_a_malformed_precondition_is_a_validation_error(links_env):
    client = links_env.client
    for bad in ("a b", "x/../y", "é", "a" * 129, ""):
        assert client.get("/api/datasets/ADDX/evidence", params={"expected_generation": bad}).status_code == 422, bad
        assert client.get("/api/recipes/fx_intensity/evidence",
                          params={"expected_generation": bad}).status_code == 422, bad


def test_other_evidence_outcomes_are_unchanged(links_env):
    client = links_env.client
    assert client.get("/api/datasets/ADDX/evidence", params={"filters": '{"BOGUS":["x"]}',
                                                              "expected_generation": GEN}).status_code == 400
    assert client.get("/api/datasets/NOPE/evidence", params={"expected_generation": GEN}).status_code == 404
    assert client.get("/api/recipes/nope/evidence", params={"expected_generation": GEN}).status_code == 404
    assert client.get("/api/recipes/fx_intensity/evidence",
                      params={"year": "2025", "expected_generation": GEN}).status_code == 422


def test_the_other_links_open_and_agree_with_the_tool_selection(links_env):
    client = links_env.client
    out = call("get_evidence_links", generation_id=GEN, selection=dataset_selection())
    L = link_map(out)
    live = client.get(L["live_selection"]["url"])
    assert live.status_code == 200
    body = live.json()
    assert body["columns"] == ["TIME_PERIOD", "OBS_VALUE"] and sorted(map(tuple, body["rows"])) == [
        ("2022", 40.0), ("2023", 50.0)]
    dl = client.get(L["csv"]["url"])
    assert dl.status_code == 200 and dl.headers["content-type"].startswith("text/csv")
    lines = dl.text.strip().splitlines()
    assert len(lines) == 3 and all(l.startswith("A,") for l in lines[1:])          # raw observations of CATEGORY=A
    page = client.get(L["dataset"]["url"])
    assert page.status_code == 200
    rec = call("get_evidence_links", generation_id=GEN, selection={
        "kind": "recipe", "recipe": "fx_intensity", "year": "2023"})
    live = client.get(link_map(rec)["live_selection"]["url"])
    assert live.status_code == 200 and live.json()["year"] == "2023"
    assert client.get(link_map(rec)["dataset"]["url"]).status_code == 200


# ============================================================ real corpus (read-only)

def _pinned_generation():
    from app.services import generation
    g = generation.current()
    if g["status"] != "present" or not str(g["id"]).startswith("9b3e065d"):
        pytest.skip("pinned to generation 9b3e065d (the PA-00 refresh)")
    return g["id"]


@pytest.mark.corpus
def test_real_tourism_intensity_and_net_earnings_through_the_tool():
    gid = _pinned_generation()
    out = R.call_tool("run_recipe", {"recipe": "tourism_intensity", "lang": "en"})
    R.validate_result("run_recipe", out)
    assert out["provenance"]["generation"]["id"] == gid
    assert out["status"] in ("ok", "partial") and out["data"]["rows"]
    assert C.size(out) <= C.MAX_RESULT_BYTES and "inputs" not in set(all_keys(out))
    assert out["provenance"]["selection"]["year"] == out["data"]["year"]
    links = R.call_tool("get_evidence_links", {"selection": out["provenance"]["selection"],
                                               "generation_id": gid})
    R.validate_result("get_evidence_links", links)
    assert links["status"] == "ok"
    pub = R.call_tool("run_recipe", {"recipe": "net_earnings_county"})
    R.validate_result("run_recipe", pub)
    assert pub["data"]["recipe"]["value_source"] in ("ins_published", "reconstruction")
    assert C.size(pub) <= C.MAX_RESULT_BYTES
    # the evidence link opens against the served generation and is refused for any other
    from fastapi.testclient import TestClient
    from app.main import app
    url = link_map(links)["evidence"]["url"]
    client = TestClient(app)
    r = client.get(url)
    assert r.status_code == 200 and zip_manifest(r.content)[1]["generation"]["id"] == gid
    stale = client.get(url.replace(gid, "not-the-served-generation"))
    assert stale.status_code == 409 and stale.json()["detail"]["served_generation"] == gid
