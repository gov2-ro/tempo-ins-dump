"""AT-01c: discover_indicators, describe_dataset, find_dimension_values.

Synthetic corpus through the real shared services (concept_search, dataset_meta,
data_query, grain_guard, scope). A temporary concepts.json and recipes.json point
at fixture datasets; the FTS sidecar is absent so family results use the shared
name fallback. Corpus-marked probes at the end run on the pinned real generation.

Fixture datasets (all values are known, nothing is mocked):
  POPK_judete / POPK_regiuni   resident population test concept (county, region)
  POPD_judete                  domicile definition (alternative of the generic alias)
  WAGEK_judete                 plain annual series; Cluj 2023 = 5002
  MONK_judete                  monthly series (a year is not one period)
  RATEK_judete                 percentage by sex, no Total: a rate cannot be summed
  CONFK_judete / CONFK_regiuni county file has conflicting keys (manifest), region is clean
  STAYK_judete                 numerator of the fixture recipe (denominator POPK_judete)
  AGEP (split parent, no file) AGEP_judete_varste (ages 0-2 of a 0+ domain), AGEP_judete_grupe
  FAMX (+ children)            full-text family without a concept
  WIDEX, TOTX, BIGX, LOCX, OLDT, LEGX   describe/values cases
"""
import copy
import json
import re

import duckdb
import pytest

from app.services.tools import contract as C
from app.services.tools import registry as R
from app.services.tools import schemas as S
from at01_fixtures import add_dataset, add_split, call, make_env
from fix02b_corpus import _write

CTY = ["Cluj", "Iași", "Municipiul București"]
REGIONS = ["Nord-Vest", "Sud"]
SEX = [("Masculin", dict(gender="M")), ("Feminin", dict(gender="F"))]


def geo(names, level="county"):
    return [(n, dict(geo_level=level, geo_name_clean=n)) for n in names]


def years(ys):
    return [(str(y), dict(year=y)) for y in ys]


def concept(cid, name, ro, *, variants=None, generic=None, alternatives=(), recipe=None,
            total_recipe=None, en=(), generic_en=()):
    c = {"id": cid, "question": "T", "name": {"ro": name, "en": name + " (en)"},
         "note": {"ro": f"nota {name}", "en": f"note {name}"},
         "aliases": {"ro": ro, "en": list(en)}, "alternatives": list(alternatives)}
    if generic:
        c["generic"] = {"ro": generic, "en": list(generic_en)}
    if variants:
        c["variants"] = variants
        c["family"] = next(iter(variants.values()))
    if recipe:
        c["recipe"] = recipe
    if total_recipe:
        c["total_recipe"] = total_recipe
    return c


CONCEPTS = {"about": "test", "version": 1, "reviewed": "test", "concepts": [
    concept("res_pop", "Populatia rezidenta test", ["populatia rezidenta", "locuitori rezidenti"],
            variants={"county": "POPK_judete", "region": "POPK_regiuni"},
            generic=["populatia", "populatie"], generic_en=["population"], alternatives=["dom_pop"]),
    concept("dom_pop", "Populatia dupa domiciliu test", ["populatia dupa domiciliu"],
            variants={"county": "POPD_judete"}, alternatives=["res_pop"]),
    concept("wage", "Castig test", ["castigul testat"], variants={"county": "WAGEK_judete"}),
    concept("monthly", "Indicator lunar test", ["indicator lunar"], variants={"county": "MONK_judete"}),
    concept("conf", "Indicator conflictual test", ["indicator conflictual"],
            variants={"county": "CONFK_judete", "region": "CONFK_regiuni"}),
    concept("agecon", "Populatie pe varste test", ["populatia pe varste"],
            variants={"county": "AGEP_judete_varste"}),
    concept("ratek", "Rata test", ["rata testata"], variants={"county": "RATEK_judete"},
            total_recipe="rk_total"),
    concept("intensity", "Intensitate test", ["intensitate testata"], recipe="tk_intensity"),
]}


def recipe(rid, num, den):
    return {"id": rid, "version": 1, "question": "T", "kind": "ratio", "geo_level": "county",
            "status": {"ro": "verificat test", "en": "verified test"},
            "name": {"ro": f"Retetă {rid}", "en": f"Recipe {rid}"},
            "unit": {"ro": "buc", "en": "pcs"}, "definition": {"ro": f"def {rid}", "en": f"def {rid}"},
            "formula": "a / b", "numerator": {"dataset": num}, "denominator": {"dataset": den}}


RECIPES = {"about": "test", "recipes": [recipe("tk_intensity", "STAYK_judete", "POPK_judete"),
                                        recipe("rk_total", "RATEK_judete", "POPK_judete")]}


# ------------------------------------------------------------------ the synthetic corpus

def _build(corpus):
    ys = (2022, 2023, 2024)
    geo_dims = lambda names, lv="county": ("REF_AREA", "Judete", "geo", geo(names, lv))
    t_dim = lambda yrs: ("TIME_PERIOD", "Ani", "time", years(yrs))

    add_dataset(corpus, "POPK_judete", [geo_dims(CTY), ("SEX", "Sexe", "gender", SEX), t_dim(ys)],
                [(c, s, str(y), 100.0 * (i + 1) + (10 if s == "Masculin" else 0) + (y - 2022))
                 for i, c in enumerate(CTY) for s, _ in SEX for y in ys],
                name="Populatia rezidenta test judete",
                definition="Populatia rezidenta: persoanele cu resedinta obisnuita in zona.")
    add_dataset(corpus, "POPK_regiuni", [geo_dims(REGIONS, "region"),
                                         ("SEX", "Sexe", "gender", SEX), t_dim(ys)],
                [(r, s, str(y), 1000.0 * (i + 1) + (y - 2022)) for i, r in enumerate(REGIONS)
                 for s, _ in SEX for y in ys], name="Populatia rezidenta test regiuni")
    add_dataset(corpus, "POPD_judete", [geo_dims(CTY), ("SEX", "Sexe", "gender", SEX), t_dim(ys)],
                [(c, s, str(y), 90.0 + i) for i, c in enumerate(CTY) for s, _ in SEX for y in ys],
                name="Populatia dupa domiciliu test judete")
    add_dataset(corpus, "WAGEK_judete", [geo_dims(CTY), t_dim(range(2021, 2025))],
                [(c, str(y), 5000.0 + 100 * i + (y - 2021)) for i, c in enumerate(CTY)
                 for y in range(2021, 2025)], name="Castig test judete")
    add_dataset(corpus, "MONK_judete", [geo_dims(CTY), ("TIME_PERIOD", "Luni", "time", [
        (f"2024-0{m}", dict(year=2024, month=m)) for m in (1, 2, 3)])],
                [(c, f"2024-0{m}", float(m)) for c in CTY for m in (1, 2, 3)],
                name="Indicator lunar test judete")
    add_dataset(corpus, "RATEK_judete", [geo_dims(CTY), ("SEX", "Sexe", "gender", SEX), t_dim(ys)],
                [(c, s, str(y), 5.0 + i) for i, c in enumerate(CTY) for s, _ in SEX for y in ys],
                unit_type="percentage", name="Rata test judete")
    add_dataset(corpus, "CONFK_judete", [geo_dims(CTY), t_dim(ys)],
                [(c, str(y), 1.0 + i) for i, c in enumerate(CTY) for y in ys],
                name="Indicator conflictual test judete")
    add_dataset(corpus, "CONFK_regiuni", [geo_dims(REGIONS, "region"), t_dim(ys)],
                [(r, str(y), 10.0 + i) for i, r in enumerate(REGIONS) for y in ys],
                name="Indicator conflictual test regiuni")
    add_dataset(corpus, "STAYK_judete", [geo_dims(CTY), t_dim(range(2021, 2025))],
                [(c, str(y), 50.0 + i) for i, c in enumerate(CTY) for y in range(2021, 2025)],
                name="Innoptari test judete")

    # split parent without a file and two children; the single-age child stops at 2 of a 0+ domain
    age_one = [("Total", dict(age_min=0, age_max=999))] + [
        (f"{a} ani", dict(age_min=a, age_max=a)) for a in range(3)]
    age_grp = [("Total", dict(age_min=0, age_max=999)), ("0-2 ani", dict(age_min=0, age_max=2)),
               ("3 ani si peste", dict(age_min=3, age_max=999))]
    agep_dims = lambda ages: [geo_dims(CTY[:2]), ("AGE", "Varste", "age", ages), t_dim((2023, 2024))]
    add_dataset(corpus, "AGEP", agep_dims(age_one), [], file=False, name="Populatia pe varste test")
    add_dataset(corpus, "AGEP_judete_varste", agep_dims(age_one),
                [(c, f"{a} ani", str(y), 10.0 + a) for c in CTY[:2] for a in range(3) for y in (2023, 2024)],
                name="Populatia pe varste test [judete x varste]", parent="AGEP")
    add_dataset(corpus, "AGEP_judete_grupe", agep_dims(age_grp),
                [(c, b, str(y), v) for c in CTY[:2] for b, v in (("0-2 ani", 30.0), ("3 ani si peste", 5.0))
                 for y in (2023, 2024)],
                name="Populatia pe varste test [judete x grupe]", parent="AGEP")
    add_split(corpus, "AGEP", "AGEP_judete_varste", "judete x varste", {"REF_AREA": "judete", "AGE": "varste"})
    add_split(corpus, "AGEP", "AGEP_judete_grupe", "judete x grupe", {"REF_AREA": "judete", "AGE": "grupe"})

    # a full-text family (no concept): parent without a file + two children
    fam_dims = [geo_dims(CTY), t_dim((2023, 2024))]
    add_dataset(corpus, "FAMX", fam_dims, [], file=False, name="Locuinte construite pe tipuri")
    for ch, lv in (("FAMX_judete", "judete"), ("FAMX_regiuni", "regiuni")):
        add_dataset(corpus, ch, fam_dims, [(c, str(y), 1.0) for c in CTY for y in (2023, 2024)],
                    name=f"Locuinte construite pe tipuri [{lv}]", parent="FAMX")
        add_split(corpus, "FAMX", ch, lv, {"REF_AREA": lv})

    # actual period bounds narrower than the metadata's
    add_dataset(corpus, "WIDEX", [("CAT", "Categorie", None, [("A", {}), ("B", {})]),
                                  t_dim(range(2000, 2025))],
                [(c, str(y), 1.0) for c in ("A", "B") for y in (2018, 2019, 2020)],
                name="Serie cu metadate mai largi")
    # metadata lists a Total for both dims; the data keeps it only for SEX
    add_dataset(corpus, "TOTX", [("CATEGORY", "Categorie", None, [("Total", {}), ("A", {}), ("B", {})]),
                                 ("SEX", "Sexe", "gender", [("Total", dict(gender="T"))] + SEX),
                                 t_dim((2023, 2024))],
                [(c, s, str(y), 1.0) for c in ("A", "B") for s in ("Total", "Masculin", "Feminin")
                 for y in (2023, 2024)], name="Total in metadate")
    # one large dimension
    cats = [f"Categoria {i:02d}" for i in range(60)]
    add_dataset(corpus, "BIGX", [("CAT", "Categorie", None, [(c, {}) for c in cats]), t_dim((2023, 2024))],
                [(c, str(y), 1.0) for c in cats for y in (2023, 2024)], name="Dimensiune mare")
    # localities nest in counties
    add_dataset(corpus, "LOCX", [geo_dims(CTY[:2]), ("REF_AREA_2", "Localitati", "geo", geo(
        ["1001 CLUJ-NAPOCA", "1002 TURDA", "2001 IASI"], "locality")), t_dim((2023, 2024))],
                [(c, l, str(y), 1.0) for c, l in (("Cluj", "1001 CLUJ-NAPOCA"), ("Cluj", "1002 TURDA"),
                                                  ("Iași", "2001 IASI")) for y in (2023, 2024)],
                name="Localitati")
    # a long time axis and an accented place
    add_dataset(corpus, "OLDT", [geo_dims(["București", "Cluj"]), t_dim(range(1960, 2026))],
                [(c, str(y), 1.0) for c in ("București", "Cluj") for y in range(1960, 2026)],
                name="Serie lunga")
    # legacy-shaped file: *_nom_id columns, label-string values with padding
    _write(corpus / "parquet" / "LEGX.parquet", "SEX_nom_id VARCHAR, TIME_nom_id VARCHAR, value DOUBLE",
           [(" Masculin", "Anul 2023", 1.0), (" Feminin", "Anul 2023", 2.0),
            (" Masculin", "Anul 2024", 3.0), (" Feminin", "Anul 2024", 4.0)])
    add_dataset(corpus, "LEGX", [("SEX_nom_id", "Sexe", "gender", SEX),
                                 ("TIME_nom_id", "Ani", "time", [("Anul 2023", dict(year=2023)),
                                                                 ("Anul 2024", dict(year=2024))])],
                [], file=False, name="Serie in format vechi")

    db = duckdb.connect(str(corpus / "metadata.duckdb"))
    db.execute("UPDATE matrices SET row_count = 4 WHERE matrix_code = 'LEGX'")
    db.execute("INSERT INTO sdmx_column_map VALUES ('LEGX', 'SEX', 'SEX_nom_id'), "
               "('LEGX', 'TIME_PERIOD', 'TIME_nom_id')")
    db.execute("""CREATE TABLE dimension_structure (matrix_code VARCHAR, dim_column VARCHAR,
                  levels VARCHAR, default_level VARCHAR, n_levels INTEGER, aggregate_value VARCHAR,
                  aggregate_verified BOOLEAN, additive BOOLEAN, nests_in VARCHAR,
                  discrimination DOUBLE, dominance DOUBLE, confidence VARCHAR, source VARCHAR)""")
    db.execute("INSERT INTO dimension_structure VALUES ('LOCX', 'REF_AREA_2', '[]', NULL, 0, NULL, FALSE, "
               "NULL, 'REF_AREA', 1.0, 1.0, 'verified', 'test')")
    lv = json.dumps([{"level_id": "top", "name": "primele 30", "verified": True, "members": cats[:30]},
                     {"level_id": "all", "name": "toate", "verified": True, "members": cats}])
    db.execute("INSERT INTO dimension_structure VALUES ('BIGX', 'CAT', ?, 'top', 2, NULL, FALSE, "
               "NULL, NULL, 1.0, 1.0, 'verified', 'test')", [lv])
    # search_datasets filters on columns the minimal fixture schema lacks
    db.execute("ALTER TABLE matrices ADD COLUMN is_canonical BOOLEAN DEFAULT TRUE")
    for ddl in ("has_time BOOLEAN", "has_geo BOOLEAN", "time_granularity VARCHAR",
                "has_gender BOOLEAN", "has_age BOOLEAN", "has_residence BOOLEAN"):
        db.execute(f"ALTER TABLE matrix_profiles ADD COLUMN {ddl}")
    db.close()


def _setup(tmp_path, monkeypatch, **kw):
    from app.services import concept_search as cs
    from app.services import dataset_search, recipes
    kw.setdefault("conflicting", ["CONFK_judete"])
    env = make_env(tmp_path, monkeypatch, build=_build, **kw)
    (tmp_path / "concepts.json").write_text(json.dumps(CONCEPTS), encoding="utf-8")
    (tmp_path / "recipes.json").write_text(json.dumps(RECIPES), encoding="utf-8")
    monkeypatch.setattr(cs, "CONCEPTS_PATH", tmp_path / "concepts.json")
    monkeypatch.setattr(recipes, "RECIPES_PATH", tmp_path / "recipes.json")
    monkeypatch.setattr(dataset_search, "SEARCH_DB_PATH", tmp_path / "no-fts.duckdb")
    dataset_search._reset_for_tests()
    return env


@pytest.fixture
def env(tmp_path, monkeypatch):
    yield _setup(tmp_path, monkeypatch)
    from app.services import dataset_search
    monkeypatch.undo()
    dataset_search._reset_for_tests()


def disc(query, **kw):
    return call("discover_indicators", query=query, **kw)


def next_calls(obj):
    """Every non-null next_call in a result, wherever it is."""
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k in ("next_call", "lookup") and v:
                yield v
            else:
                yield from next_calls(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from next_calls(v)


def assert_calls_valid(env_):
    n = 0
    for nc in next_calls(env_["data"]):
        R.TOOLS[nc["tool"]].args.model_validate(nc["arguments"])
        n += 1
    return n


def card(env_, cid):
    return next(c for c in env_["data"]["concepts"] if c["id"] == cid)


def cand(card_, dataset):
    return next(c for c in card_["candidates"] if c["dataset"] == dataset)


def codes(items):
    return [i["code"] for i in items]


def run_next(env_card):
    """Execute a card's next_call through the registry (the model's next step)."""
    nc = env_card["next_call"]
    return R.call_tool(nc["tool"], nc["arguments"])


def no_internals(env_, tmp_path):
    text = json.dumps(env_, ensure_ascii=False)
    assert str(tmp_path) not in text and "SELECT" not in text and "read_parquet" not in text
    assert "Traceback" not in text and C.size(env_) <= C.MAX_RESULT_BYTES


# ------------------------------------------------------------------ discover: ok paths

def test_specific_concept_gives_a_valid_query_call_that_runs(env, tmp_path):
    out = disc("castigul testat Cluj 2023")
    assert out["status"] == "ok" and out["reason"] is None
    c = card(out, "wage")
    assert c["generic_match"] is False and c["unit_type"] == "count"
    assert c["coverage"]["first"] == "2021" and c["coverage"]["last"] == "2024"
    assert [lv["level"] for lv in c["levels"]] == ["county"]
    assert c["preferred"] == "WAGEK_judete"
    nc = c["next_call"]
    assert nc == {"tool": "query_data", "arguments": {
        "dataset": "WAGEK_judete", "filters": {"REF_AREA": ["Cluj"], "TIME_PERIOD": ["2023"]},
        "group_by": ["REF_AREA", "TIME_PERIOD"], "lang": "ro"}}
    S.QueryDataArgs.model_validate(nc["arguments"])
    assert out["data"]["interpretation"]["places"] == [{"slug": "cluj", "name": "Cluj", "type": "county"}]
    assert out["data"]["interpretation"]["period"] == 2023
    # the suggested call is not doomed: the shared query answers it
    from app.db import get_conn
    from app.services.data_query import run_query
    res = run_query(get_conn(), "WAGEK_judete", nc["arguments"]["filters"], nc["arguments"]["group_by"])
    assert not res.get("unavailable") and res["rows"] == [["Cluj", "2023", 5002.0]]
    cd = cand(c, "WAGEK_judete")
    assert cd["quality"] == "unique" and cd["level"] == "county" and cd["preferred"] and cd["queryable"]
    assert cd["domain"]["complete"] is None            # no age dimension: nothing is claimed
    assert assert_calls_valid(out) > 0
    assert out["limits"] == C.metadata_limits() and out["provenance"]["generation"]["status"] == "present"
    no_internals(out, tmp_path)


def test_without_place_or_year_the_call_groups_by_period_only(env):
    out = disc("castigul testat")
    nc = card(out, "wage")["next_call"]
    assert nc["arguments"]["filters"] == {} and nc["arguments"]["group_by"] == ["TIME_PERIOD"]


def test_requested_level_adds_the_breakdown_and_latest_is_a_real_period(env):
    out = disc("indicator conflictual regiuni cel mai recent")      # level region, latest
    cd = cand(card(out, "conf"), "CONFK_regiuni")
    assert cd["next_call"]["arguments"]["filters"] == {"TIME_PERIOD": ["2024"]}
    assert cd["next_call"]["arguments"]["group_by"] == ["REF_AREA", "TIME_PERIOD"]
    assert any(n["code"] == "latest_period" for n in cd["notes"])


def test_year_outside_the_data_is_reported_never_pinned(env):
    out = disc("castigul testat Cluj 2030")
    assert out["status"] == "ok"
    c = card(out, "wage")
    assert "period_unavailable" in [n["code"] for n in c["notes"]]
    nc = c["next_call"]
    # the model first sees the actual periods; no query for another year is offered
    assert nc["tool"] == "find_dimension_values"
    assert nc["arguments"] == {"dataset": "WAGEK_judete", "column": "TIME_PERIOD", "limit": 20}
    assert "2030" not in json.dumps(cand(c, "WAGEK_judete")["next_call"]["arguments"].get("filters", {}))
    kinds = [(a["kind"], a.get("reason")) for a in out["data"]["interpretation"]["ambiguities"]]
    assert ("period", "period_unavailable") in kinds
    assert [w["code"] for w in out["warnings"] if w.get("subject") == "wage"] == ["period_unavailable"]
    assert out["data"]["interpretation"]["period"] == 2030


def test_a_year_on_monthly_data_is_not_one_period(env):
    out = disc("indicator lunar Cluj 2024")
    c = card(out, "monthly")
    assert "period_not_single" in [n["code"] for n in c["notes"]]
    assert c["next_call"]["arguments"] == {"dataset": "MONK_judete", "column": "TIME_PERIOD",
                                           "limit": 20, "query": "2024"}
    res = R.call_tool(c["next_call"]["tool"], c["next_call"]["arguments"])
    assert [v["value"] for v in res["data"]["values"]] == ["2024-03", "2024-02", "2024-01"]


@pytest.mark.parametrize("q,expected", [
    ("între 2015 și 2024", {"from": 2015, "to": 2024}), ("between 2015 and 2024", {"from": 2015, "to": 2024}),
    ("din 2015 până în 2020", {"from": 2015, "to": 2020}), ("from 2015 to 2020", {"from": 2015, "to": 2020}),
    ("perioada 2015-2024", {"from": 2015, "to": 2024}), ("2015–2024", {"from": 2015, "to": 2024}),
    ("2015, 2024", None), ("2015 și 2024", None), ("2024-2015", None), ("2024", None)])
def test_a_span_of_years_is_read_only_where_the_words_say_so(q, expected):
    from app.services.tools.intent import period_range
    assert period_range(q) == expected


def test_a_year_range_asks_for_every_year_the_data_has_and_names_the_rest(env):
    # P2 (06C): "between 2015 and 2024" got a call for 2024 alone
    out = disc("castigul testat Cluj intre 2019 si 2023")
    interp = out["data"]["interpretation"]
    assert interp["period_range"] == {"from": 2019, "to": 2023} and interp["periods"] == list(range(2019, 2024))
    c = card(out, "wage")
    nc = c["next_call"]
    assert nc["arguments"]["filters"] == {"REF_AREA": ["Cluj"], "TIME_PERIOD": ["2021", "2022", "2023"]}
    assert nc["arguments"]["group_by"] == ["REF_AREA", "TIME_PERIOD"]
    note = next(n for n in c["notes"] if n["code"] == "period_range_partial")
    assert "2019–2020" in note["message"]
    assert [w["code"] for w in out["warnings"] if w.get("subject") == "wage"] == ["period_range_partial"]
    assert interp["ambiguities"] == []
    res = R.call_tool(nc["tool"], nc["arguments"])
    assert sorted(r[1:] for r in res["data"]["rows"]) == [["2021", 5000.0], ["2022", 5001.0], ["2023", 5002.0]]


def test_listed_years_are_all_asked_for(env):
    nc = card(disc("castigul testat Cluj 2021 si 2024"), "wage")["next_call"]
    assert nc["arguments"]["filters"]["TIME_PERIOD"] == ["2021", "2024"]


def test_a_year_range_outside_the_data_is_reported_never_pinned(env):
    c = card(disc("castigul testat Cluj 2010-2015"), "wage")
    assert "period_unavailable" in codes(c["notes"])
    assert c["next_call"] == {"tool": "find_dimension_values", "arguments": {
        "dataset": "WAGEK_judete", "column": "TIME_PERIOD", "limit": 20}}


def test_a_recipe_asked_for_a_range_says_it_answers_one_year(env):
    c = card(disc("intensitate testata Cluj 2022-2024"), "intensity")
    assert c["next_call"]["arguments"]["year"] == "2024"
    assert "period_range_single" in codes(c["notes"])


def test_recipe_concept_gets_a_run_recipe_call_with_year_and_areas(env):
    out = disc("intensitate testata Cluj 2023")
    assert out["status"] == "ok"
    c = card(out, "intensity")
    assert c["kind"] == "recipe" and c["recipe"] == "tk_intensity"
    assert c["coverage"] == {"first": "2022", "last": "2024", "frequency": "annual"}
    cd = c["candidates"][0]
    assert cd["kind"] == "recipe" and cd["sources"] == ["STAYK_judete", "POPK_judete"] and cd["preferred"]
    assert cd["dataset"] is None and cd["recipe"] == "tk_intensity"
    assert c["next_call"] == {"tool": "run_recipe", "arguments": {
        "recipe": "tk_intensity", "lang": "ro", "year": "2023", "areas": ["Cluj"]}}
    assert_calls_valid(out)


def test_recipe_year_outside_common_coverage_is_not_swapped(env):
    out = disc("intensitate testata 2030")
    c = card(out, "intensity")
    assert "period_unavailable" in [n["code"] for n in c["notes"]]
    assert c["next_call"]["tool"] == "find_dimension_values"
    assert c["next_call"]["arguments"]["dataset"] == "STAYK_judete"


def test_conflicting_county_file_is_not_the_preferred_call(env):
    out = disc("indicator conflictual judete")
    c = card(out, "conf")
    county, region = cand(c, "CONFK_judete"), cand(c, "CONFK_regiuni")
    assert county["quality"] == "conflicting" and county["queryable"] is False
    assert county["next_call"]["tool"] == "describe_dataset" and not county["preferred"]
    assert "grain_conflicting" in [n["code"] for n in county["notes"]]
    assert region["quality"] == "unique" and region["preferred"] and c["preferred"] == "CONFK_regiuni"
    assert region["next_call"]["tool"] == "query_data"
    # the level difference is stated: a region series cannot answer a county question
    assert "level_differs" in [n["code"] for n in region["notes"]]
    assert c["candidates"][0]["dataset"] == "CONFK_regiuni"


def test_single_age_child_is_restricted_and_a_complete_sibling_is_preferred(env):
    out = disc("populatia pe varste 2023")
    c = card(out, "agecon")
    child = cand(c, "AGEP_judete_varste")
    assert child["domain"]["complete"] is False and child["domain"]["restrictions"] == [
        {"column": "AGE", "kind": "age_range", "covered": [[0, 2]], "domain": [0, None]}]
    assert "3 ani" in child["domain"]["description"] or "3 and over" in child["domain"]["description"]
    assert child["queryable"] is False and child["preferred"] is False
    assert child["next_call"]["tool"] == "describe_dataset"
    assert "domain_incomplete" in [n["code"] for n in child["notes"]]
    sib = cand(c, "AGEP_judete_grupe")
    assert sib["relation"] == "sibling" and sib["domain"]["complete"] is True
    assert sib["preferred"] and c["preferred"] == "AGEP_judete_grupe"
    assert c["next_call"]["tool"] == "query_data" and c["next_call"]["arguments"]["dataset"] == "AGEP_judete_grupe"
    assert assert_calls_valid(out)


def test_a_rate_that_cannot_be_summed_points_at_the_reviewed_recipe(env):
    out = disc("rata testata Cluj 2023")
    c = card(out, "ratek")
    ds = cand(c, "RATEK_judete")
    assert ds["queryable"] is False and ds["next_call"]["tool"] == "describe_dataset"
    assert "aggregation_unavailable" in [n["code"] for n in ds["notes"]]
    assert c["recipe"] == "rk_total" and c["preferred"] == "rk_total"
    assert c["next_call"] == {"tool": "run_recipe", "arguments": {
        "recipe": "rk_total", "lang": "ro", "year": "2023", "areas": ["Cluj"]}}


# ------------------------------------------------------------------ discover: clarification

def test_generic_word_asks_which_definition(env, tmp_path):
    out = disc("populatie")
    assert out["status"] == "needs_clarification" and out["reason"] == "ambiguous_definition"
    ch = out["data"]["choices"]
    assert [c["id"] for c in ch] == ["res_pop", "dom_pop"] and len(ch) <= 5
    assert all(c["label"] and c["description"] and c["next_call"] for c in ch)
    # cards are shown, but no headline: no call is suggested until a definition is chosen
    c = card(out, "res_pop")
    assert c["generic_match"] and c["requires_choice"] and c["next_call"] is None
    assert all(cd["next_call"] is None and not cd["preferred"] for cd in c["candidates"])
    assert [a["id"] for a in c["alternatives"]] == ["dom_pop"]
    assert out["data"]["interpretation"]["ambiguities"][0]["kind"] == "definition"
    assert len(out["recovery"]) == 2 and all(r["kind"] == "tool_call" for r in out["recovery"])
    assert_calls_valid(out)
    no_internals(out, tmp_path)
    # selecting a definition is a separate call, and it is specific
    for choice in ch:
        picked = R.call_tool(choice["next_call"]["tool"], choice["next_call"]["arguments"])
        R.validate_result("discover_indicators", picked)
        assert picked["status"] == "ok" and picked["data"]["concepts"][0]["id"] == choice["id"]
        assert picked["data"]["concepts"][0]["generic_match"] is False


def test_specific_phrase_is_not_asked_about(env):
    out = disc("populatia rezidenta Cluj")
    assert out["status"] == "ok" and out["data"]["choices"] == []
    c = card(out, "res_pop")
    assert [a["id"] for a in c["alternatives"]] == ["dom_pop"]    # shown, not imposed
    assert c["next_call"]["tool"] == "query_data"


def test_city_named_place_asks_county_or_all_counties(env):
    out = disc("Cluj-Napoca populatia rezidenta 2023")
    assert out["status"] == "needs_clarification" and out["reason"] == "ambiguous_place"
    amb = out["data"]["interpretation"]["ambiguities"]
    assert amb[0]["kind"] == "place" and amb[0]["reason"] == "city_not_county"
    place = out["data"]["interpretation"]["places"][0]
    assert place["ambiguous"] is True and place["note"] == "city_not_county"
    ch = {c["id"]: c for c in out["data"]["choices"]}
    assert set(ch) == {"county", "all_counties"}
    assert card(out, "res_pop")["next_call"] is None
    picked = R.call_tool(ch["county"]["next_call"]["tool"], ch["county"]["next_call"]["arguments"])
    R.validate_result("discover_indicators", picked)
    assert picked["status"] == "ok"
    nc = card(picked, "res_pop")["next_call"]
    assert nc["arguments"]["filters"] == {"REF_AREA": ["Cluj"], "TIME_PERIOD": ["2023"]}
    allc = R.call_tool(ch["all_counties"]["next_call"]["tool"], ch["all_counties"]["next_call"]["arguments"])
    assert allc["status"] == "ok" and allc["data"]["interpretation"]["places"] == []
    assert allc["data"]["interpretation"]["level"] == "county"


def test_generic_word_and_city_clarify_the_definition_first_and_keep_the_city(env):
    out = disc("Cluj-Napoca populatie")
    assert out["status"] == "needs_clarification" and out["reason"] == "ambiguous_definition"
    kinds = {a["kind"] for a in out["data"]["interpretation"]["ambiguities"]}
    assert kinds == {"definition", "place"}
    picked = R.call_tool(out["data"]["choices"][0]["next_call"]["tool"],
                         out["data"]["choices"][0]["next_call"]["arguments"])
    assert picked["status"] == "needs_clarification" and picked["reason"] == "ambiguous_place"


# ------------------------------------------------------------------ discover: families, edges

def test_families_group_split_children_and_are_not_verified_answers(env):
    out = disc("locuinte construite", lang="en")
    assert out["status"] == "ok" and out["data"]["concepts"] == []
    fam = out["data"]["families"]
    assert [f["family"] for f in fam] == ["FAMX"]
    f = fam[0]
    assert f["verified"] is False and f["members_truncated"] is False
    assert set(codes(f["members"])) == {"FAMX", "FAMX_judete", "FAMX_regiuni"}
    labels = {m["code"]: m["label"] for m in f["members"]}
    assert labels["FAMX_judete"] == "judete" and labels["FAMX"] is None
    assert all(m["next_call"]["tool"] == "describe_dataset" for m in f["members"])
    assert f["next_call"]["arguments"]["dataset"] == "FAMX"
    info = out["data"]["families_info"]
    assert info["verified"] is False and "not verified" in info["note"] and info["total"] == 1
    assert "search_degraded" in [w["code"] for w in out["warnings"]]       # no FTS sidecar here
    assert_calls_valid(out)


def test_limit_bounds_concept_and_family_cards(env):
    out = disc("populatia rezidenta", limit=1)
    assert len(out["data"]["concepts"]) == 1 and out["data"]["families"] == []
    out = disc("locuinte construite", limit=1)
    assert len(out["data"]["families"]) == 1


def test_nothing_found_is_ok_with_empty_lists_and_a_way_forward(env):
    out = disc("xyzzy qwerty")
    assert out["status"] == "ok" and out["reason"] is None
    assert out["data"]["concepts"] == [] and out["data"]["families"] == [] and out["data"]["choices"] == []
    assert "no_match" in [w["code"] for w in out["warnings"]]
    assert out["recovery"][0]["kind"] == "clarify" and out["recovery"][0]["tool"] is None


def test_english_query_and_language_follow_lang(env):
    out = disc("population", lang="en")
    assert out["status"] == "needs_clarification"      # the generic English word, same concepts
    assert [c["label"] for c in out["data"]["choices"]] == [
        "Populatia rezidenta test (en)", "Populatia dupa domiciliu test (en)"]
    assert all(c["next_call"]["arguments"]["lang"] == "en" for c in out["data"]["choices"])
    out = disc("castigul testat", lang="en")
    assert card(out, "wage")["name"] == "Castig test (en)"
    assert card(out, "wage")["next_call"]["arguments"]["lang"] == "en"


def test_missing_generation_is_warned_and_reported(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch, generation_id=None)
    out = disc("castigul testat")
    assert out["provenance"]["generation"] == {"id": None, "status": "missing", "built_at": None}
    assert "generation_unverified" in [w["code"] for w in out["warnings"]]
    assert out["status"] == "ok"
    assert cand(card(out, "wage"), "WAGEK_judete")["quality"] == "unverified"
    d = call("describe_dataset", dataset="WAGEK_judete")
    assert "generation_unverified" in [w["code"] for w in d["warnings"]]
    v = call("find_dimension_values", dataset="WAGEK_judete", column="REF_AREA")
    assert v["provenance"]["generation"]["status"] == "missing"
    assert "generation_unverified" in [w["code"] for w in v["warnings"]]


def test_envelope_stays_within_budget_for_the_widest_request(env, tmp_path):
    out = disc("populatie", limit=10)
    assert C.size(out) <= C.MAX_RESULT_BYTES
    no_internals(out, tmp_path)


def test_oversized_output_is_trimmed_by_the_tool_not_dropped(env, monkeypatch):
    from app.services.tools import discovery
    full = disc("populatia rezidenta", limit=10)
    monkeypatch.setattr(discovery, "FIT_BYTES", C.size(full) - 600)
    out = disc("populatia rezidenta", limit=10)
    assert C.size(out) < C.size(full) and out["status"] == "ok"
    assert "response_shortened" in [w["code"] for w in out["warnings"]]
    assert out["data"]["concepts"][0]["id"] == "res_pop" and out["data"]["concepts"][0]["next_call"]
    monkeypatch.setattr(discovery, "FIT_BYTES", 1500)       # cuts optional detail, never the safety notes
    tiny = disc("populatie", limit=10)
    assert tiny["status"] == "needs_clarification" and tiny["data"]["choices"]
    assert tiny["data"]["interpretation"]["ambiguities"]


def test_describe_trims_examples_before_dropping_anything_required(env, monkeypatch):
    from app.services.tools import discovery
    monkeypatch.setattr(discovery, "FIT_BYTES", C.size(call("describe_dataset", dataset="BIGX")) - 100)
    d = call("describe_dataset", dataset="BIGX")
    assert len(dim(d, "CAT")["examples"]) == 3 and dim(d, "CAT")["values_truncated"] is True
    assert d["data"]["time"]["first"] == "2023" and d["data"]["dimensions"][0]["lookup"]


# ------------------------------------------------------------------ describe_dataset

def dim(d, col):
    return next(x for x in d["data"]["dimensions"] if x["column"] == col)


def test_actual_period_bounds_beat_metadata(env):
    d = call("describe_dataset", dataset="WIDEX")
    t = d["data"]["time"]
    assert (t["column"], t["first"], t["last"], t["frequency"], t["periods_with_data"]) == (
        "TIME_PERIOD", "2018", "2020", "annual", 3)
    assert t["metadata_range"] == {"first": "2000", "last": "2024", "options": 25}
    assert "metadata_period_range_differs" in [n["id"] for n in d["data"]["notes"]]
    td = dim(d, "TIME_PERIOD")
    assert td["option_count"] == 3 and td["metadata_option_count"] == 25
    assert td["examples"] == ["2020", "2019", "2018"]            # newest first
    assert d["data"]["has_data"] is True and d["limits"] == C.metadata_limits()
    assert d["provenance"]["sources"][0]["dataset"] == "WIDEX"


def test_total_listed_by_metadata_but_absent_from_data_is_explained(env):
    d = call("describe_dataset", dataset="TOTX", lang="en")
    cat, sex = dim(d, "CATEGORY"), dim(d, "SEX")
    assert cat["total_in_data"] is False and cat["total_metadata_values"] == ["Total"]
    assert "no such value" in cat["total_note"] and "Do not filter" in cat["total_note"]
    assert cat["examples"] == ["A", "B"] and cat["option_count"] == 2 and cat["metadata_option_count"] == 3
    assert sex["total_in_data"] is True and sex["total_values"] == ["Total"] and "total_note" not in sex
    assert dim(d, "TIME_PERIOD")["total_in_data"] is None       # not a category dimension


def test_examples_are_a_bounded_sample_with_a_working_lookup(env):
    d = call("describe_dataset", dataset="BIGX", lang="en")
    cat = dim(d, "CAT")
    assert len(cat["examples"]) == 5 and cat["values_truncated"] is True and cat["option_count"] == 60
    assert cat["lookup"] == {"tool": "find_dimension_values", "arguments": {"dataset": "BIGX", "column": "CAT"}}
    assert "not an exhaustive allowlist" in d["data"]["examples_note"]
    # the examples are exactly the first page of the lookup
    page = call("find_dimension_values", **cat["lookup"]["arguments"], limit=5)
    assert [v["value"] for v in page["data"]["values"]] == cat["examples"]
    small = dim(call("describe_dataset", dataset="WIDEX"), "CAT")
    assert small["values_truncated"] is False and small["examples"] == ["A", "B"]
    assert assert_calls_valid(d) > 0


def test_verified_structure_levels_are_reported(env):
    cat = dim(call("describe_dataset", dataset="BIGX"), "CAT")
    assert cat["levels"] == [{"level_id": "top", "name": "primele 30", "members": 30, "default": True},
                             {"level_id": "all", "name": "toate", "members": 60, "default": False}]
    assert dim(call("describe_dataset", dataset="WIDEX"), "CAT")["levels"] == []


def test_geographic_entity_keys_follow_nesting(env):
    d = call("describe_dataset", dataset="LOCX")
    assert d["data"]["geo"]["columns"] == ["REF_AREA", "REF_AREA_2"]
    assert d["data"]["geo"]["nesting"] == {"REF_AREA_2": "REF_AREA"}
    assert d["data"]["geo"]["entity_keys"] == [["REF_AREA", "REF_AREA_2"]]
    assert d["data"]["geo"]["levels"] == {"REF_AREA": "county", "REF_AREA_2": "locality"}
    assert dim(d, "REF_AREA_2")["nests_in"] == "REF_AREA"
    flat = call("describe_dataset", dataset="WAGEK_judete")["data"]["geo"]
    assert flat["entity_keys"] == [["REF_AREA"]] and flat["nesting"] == {}


def test_split_parent_without_a_file_is_described_from_metadata(env):
    d = call("describe_dataset", dataset="AGEP")
    assert d["status"] == "ok" and d["data"]["has_data"] is False
    t = d["data"]["time"]
    assert t["column"] == "TIME_PERIOD" and t["first"] is None and t["last"] is None
    assert all(x["examples"] == [] and x["option_count"] is None and x["metadata_option_count"] > 0
               for x in d["data"]["dimensions"])
    assert [s["dataset"] for s in d["data"]["splits"]] == ["AGEP_judete_grupe", "AGEP_judete_varste"]
    assert all(s["next_call"]["tool"] == "describe_dataset" for s in d["data"]["splits"])
    assert "no_data_file" in [n["id"] for n in d["data"]["notes"]]
    assert d["data"]["domain"]["complete"] is None
    assert d["data"]["grain"]["status"] == "unique"
    child = call("describe_dataset", dataset="AGEP_judete_varste")
    assert child["data"]["parent"]["dataset"] == "AGEP"
    assert child["data"]["parent"]["next_call"]["arguments"]["dataset"] == "AGEP"


def test_restricted_child_discloses_its_domain_and_the_complete_sibling(env):
    d = call("describe_dataset", dataset="AGEP_judete_varste")
    dom = d["data"]["domain"]
    assert dom["complete"] is False and dom["restrictions"][0]["covered"] == [[0, 2]]
    assert dom["complete_alternatives"][0]["dataset"] == "AGEP_judete_grupe"
    assert d["provenance"]["scope"]["domain_complete"] is False
    assert d["provenance"]["scope"]["limitations"][0]["missing"] == [[3, None]]
    assert "domain_incomplete" in [w["code"] for w in d["warnings"]]
    age = dim(d, "AGE")
    assert age["total_in_data"] is False and age["examples"] == ["0 ani", "1 ani", "2 ani"]
    grp = call("describe_dataset", dataset="AGEP_judete_grupe")
    assert grp["data"]["domain"]["complete"] is True and grp["provenance"]["scope"]["domain_complete"] is True
    assert "domain_incomplete" not in [w["code"] for w in grp["warnings"]]
    # a dataset with no age dimension claims nothing either way
    assert call("describe_dataset", dataset="WAGEK_judete")["data"]["domain"]["complete"] is None


def test_conflicting_grain_is_visible_in_describe(env):
    d = call("describe_dataset", dataset="CONFK_judete")
    assert d["data"]["grain"]["status"] == "conflicting"
    assert "grain_conflicting" in [w["code"] for w in d["warnings"]]
    assert call("describe_dataset", dataset="CONFK_regiuni")["data"]["grain"]["status"] == "unique"


def test_definition_unit_and_links(env):
    d = call("describe_dataset", dataset="POPK_judete")
    data = d["data"]
    assert data["definition"].startswith("Populatia rezidenta") and len(data["definition"]) <= 402
    assert data["measure"] == "additive" and data["unit_type"] == "count"
    assert data["source_updated"] == "2026-01-15" and data["url"] == "/dataset-v2.html?code=POPK_judete"
    assert data["name"] == "Populatia rezidenta test judete" and data["row_count"] == 18
    assert [x["column"] for x in data["dimensions"]] == ["REF_AREA", "SEX", "TIME_PERIOD"]
    assert dim(d, "SEX")["type"] == "gender" and dim(d, "REF_AREA")["examples"] == [
        "Cluj", "Iași", "Municipiul București"]
    en = call("describe_dataset", dataset="POPK_judete", lang="en")
    assert en["data"]["dataset"] == "POPK_judete" and en["data"]["url"].endswith("&lang=en")


def test_legacy_shaped_file_uses_canonical_column_names(env):
    d = call("describe_dataset", dataset="LEGX")
    assert [x["column"] for x in d["data"]["dimensions"]] == ["SEX", "TIME_PERIOD"]
    assert "nom_id" not in json.dumps(d["data"])
    assert d["data"]["time"]["first"] == "Anul 2023" and d["data"]["time"]["last"] == "Anul 2024"
    assert d["data"]["time"]["frequency"] == "annual"
    assert dim(d, "SEX")["examples"] == [" Feminin", " Masculin"]         # the exact data values
    v = call("find_dimension_values", dataset="LEGX", column="SEX")
    assert v["data"]["column"] == "SEX"
    assert [(i["value"], i["label"]) for i in v["data"]["values"]] == [
        (" Feminin", "Feminin"), (" Masculin", "Masculin")]
    t = call("find_dimension_values", dataset="LEGX", column="TIME_PERIOD")
    assert [i["value"] for i in t["data"]["values"]] == ["Anul 2024", "Anul 2023"]
    assert t["data"]["period_bounds"]["first"] == "Anul 2023"


def test_describe_does_not_mutate_cached_metadata(env):
    from app.db import get_conn
    from app.services import dataset_meta as dm
    rest = lambda: {x["dim_column_name"]: len(x["options"]) for x in
                    env.client.get("/api/datasets/BIGX").json()["dimensions"]}
    before_rest = rest()
    conn = get_conn()
    before_ctx = copy.deepcopy(dm.get_aggregation_context(conn, "BIGX"))
    before_ctx.pop("ts")
    d = call("describe_dataset", dataset="BIGX")
    assert len(dim(d, "CAT")["examples"]) == 5
    after_ctx = copy.deepcopy(dm.get_aggregation_context(conn, "BIGX"))
    after_ctx.pop("ts")
    assert after_ctx == before_ctx
    assert rest() == before_rest and before_rest["CAT"] == 60
    # the shared cache still hands out every option and every data value
    ctx = dm.get_aggregation_context(conn, "BIGX")
    assert len(ctx["actual_values"]["CAT"]) == 60
    assert len([x for x in ctx["dimensions"] if x["dim_column_name"] == "CAT"][0]["options"]) == 60
    # discovery reads the same caches and leaves them alone too
    disc("populatia rezidenta")
    disc("populatia pe varste")
    assert rest() == before_rest


def test_unknown_dataset_is_an_error_with_a_way_to_find_it(env):
    d = call("describe_dataset", dataset="NOPE123")
    assert d["status"] == "error" and d["reason"] == "unknown_dataset" and d["data"] == {}
    assert d["recovery"][0]["tool"] == "discover_indicators" and d["recovery"][0]["kind"] == "tool_call"
    assert d["provenance"]["sources"] == [] and "NOPE123" in d["message"]
    assert d["limits"] == C.metadata_limits()


# ------------------------------------------------------------------ find_dimension_values

def test_paging_next_offset_total_and_newest_first_time(env):
    first = call("find_dimension_values", dataset="OLDT", column="TIME_PERIOD", limit=20)
    d = first["data"]
    assert [v["value"] for v in d["values"]][:3] == ["2025", "2024", "2023"] and len(d["values"]) == 20
    assert (d["total"], d["offset"], d["next_offset"], d["values_truncated"]) == (66, 0, 20, True)
    assert d["period_bounds"] == {"first": "1960", "last": "2025", "periods_with_data": 66}
    assert d["order"] == "newest first"
    got, off = [], 0
    while off is not None:
        page = call("find_dimension_values", dataset="OLDT", column="TIME_PERIOD", limit=20, offset=off)
        got += [v["value"] for v in page["data"]["values"]]
        off = page["data"]["next_offset"]
        assert page["data"]["values_truncated"] is (off is not None)
    assert got == [str(y) for y in range(2025, 1959, -1)]
    assert first["limits"] == C.metadata_limits()


def test_an_old_exact_period_is_found_by_query_without_paging(env):
    d = call("find_dimension_values", dataset="OLDT", column="TIME_PERIOD", query="1992")["data"]
    assert [v["value"] for v in d["values"]] == ["1992"] and d["total"] == 1 and d["next_offset"] is None
    assert d["period_bounds"]["first"] == "1960"           # bounds describe the data, not the match


def test_search_is_accent_and_case_insensitive_and_returns_exact_values(env):
    for q in ("bucuresti", "BUCUREȘTI", "București", "ucur"):
        d = call("find_dimension_values", dataset="OLDT", column="REF_AREA", query=q)["data"]
        assert [(v["value"], v["label"]) for v in d["values"]] == [("București", "București")], q
        assert d["period_bounds"] is None and d["order"].startswith("alphabetical")
    d = call("find_dimension_values", dataset="POPK_judete", column="REF_AREA", query="iasi")["data"]
    assert d["values"][0]["value"] == "Iași"
    d = call("find_dimension_values", dataset="POPK_judete", column="REF_AREA")["data"]
    assert [v["value"] for v in d["values"]] == ["Cluj", "Iași", "Municipiul București"] and d["total"] == 3


def test_a_query_without_a_match_is_an_empty_page_with_a_hint(env):
    out = call("find_dimension_values", dataset="OLDT", column="TIME_PERIOD", query="1850", lang="en")
    assert out["status"] == "ok" and out["reason"] is None
    d = out["data"]
    assert d["values"] == [] and d["total"] == 0 and d["next_offset"] is None
    assert "1850" in d["hint"] and "1960" in d["hint"]
    assert out["recovery"][0]["tool"] == "find_dimension_values"
    assert out["recovery"][0]["arguments"] == {"dataset": "OLDT", "column": "TIME_PERIOD"}
    past = call("find_dimension_values", dataset="OLDT", column="TIME_PERIOD", offset=500, lang="en")["data"]
    assert past["values"] == [] and past["total"] == 66 and "past the last" in past["hint"]


def test_unknown_column_and_unknown_dataset_and_value_column(env):
    out = call("find_dimension_values", dataset="POPK_judete", column="BOGUS")
    assert out["status"] == "error" and out["reason"] == "unknown_column" and out["data"] == {}
    assert "REF_AREA, SEX, TIME_PERIOD" in out["message"] and "BOGUS" in out["message"]
    assert out["recovery"][0]["tool"] == "describe_dataset"
    assert call("find_dimension_values", dataset="POPK_judete", column="OBS_VALUE")["reason"] == "unknown_column"
    out = call("find_dimension_values", dataset="NOPE123", column="REF_AREA")
    assert out["status"] == "error" and out["reason"] == "unknown_dataset"


def test_values_of_a_split_parent_point_at_its_sub_datasets(env, tmp_path):
    out = call("find_dimension_values", dataset="AGEP", column="AGE", lang="en")
    assert out["status"] == "error" and out["reason"] == "unknown_dataset"
    assert "sub-datasets" in out["message"] and out["recovery"][0]["tool"] == "describe_dataset"
    no_internals(out, tmp_path)


def test_value_lookup_carries_the_source_for_citation(env):
    out = call("find_dimension_values", dataset="POPK_judete", column="SEX")
    src = out["provenance"]["sources"][0]
    assert src["dataset"] == "POPK_judete" and src["url"] == "/dataset-v2.html?code=POPK_judete"
    assert src["source_updated"] == "2026-01-15"


# ------------------------------------------------------------------ pinned real generation

PINNED = "9b3e065d"


@pytest.fixture
def real():
    from app.services import generation
    gid = str(generation.current().get("id") or "")
    if not gid.startswith(PINNED):
        pytest.skip(f"probe is pinned to generation {PINNED}…, corpus is {gid[:8] or 'unknown'}")
    return gid


@pytest.mark.corpus
def test_corpus_long_time_axis_is_reachable(real):
    d = call("describe_dataset", dataset="AMG157G")["data"]
    t = d["time"]
    assert t["frequency"] == "monthly" and (t["first"], t["last"]) == ("2004-01", "2026-06")
    assert t["periods_with_data"] == 270 and t["periods_with_data"] > 20
    assert t["metadata_range"]["last"] != t["last"]            # metadata is narrower here
    got, off = [], 0
    while off is not None:
        page = call("find_dimension_values", dataset="AMG157G", column="TIME_PERIOD", limit=100, offset=off)
        got += [v["value"] for v in page["data"]["values"]]
        off = page["data"]["next_offset"]
    assert len(got) == 270 and got[0] == "2026-06" and got[-1] == "2004-01"
    old = call("find_dimension_values", dataset="AMG157G", column="TIME_PERIOD", query="2004-01")["data"]
    assert [v["value"] for v in old["values"]] == ["2004-01"]
    cur = call("find_dimension_values", dataset="AMG157G", column="TIME_PERIOD", limit=20)["data"]
    assert cur["values"][0]["value"] == "2026-06" and cur["next_offset"] == 20


@pytest.mark.corpus
def test_corpus_describe_total_absence_levels_and_nesting(real):
    d = call("describe_dataset", dataset="POP107D")
    sex = dim(d, "SEX")
    assert sex["total_in_data"] is False and sex["option_count"] == 2 and sex["metadata_option_count"] == 3
    assert [lv["level_id"] for lv in dim(d, "AGE")["levels"]] == ["age_w1", "age_w5"]
    assert d["data"]["geo"]["entity_keys"] == [["REF_AREA", "REF_AREA_2"]]
    assert len(d["data"]["splits"]) == 4 and d["data"]["has_data"] is True


@pytest.mark.corpus
def test_corpus_single_age_children_are_restricted(real):
    for code in ("POP105A_judete_varste", "POP201G"):
        d = call("describe_dataset", dataset=code)
        assert d["data"]["domain"]["complete"] is False, code
        assert "domain_incomplete" in [w["code"] for w in d["warnings"]]
    d = call("describe_dataset", dataset="POP105A_judete_varste")
    assert d["data"]["domain"]["restrictions"][0]["covered"] == [[0, 84]]
    assert d["data"]["domain"]["complete_alternatives"][0]["dataset"] == "POP105A_judete_grupe"
    assert call("describe_dataset", dataset="POP105A_judete_grupe")["data"]["domain"]["complete"] is True


@pytest.mark.corpus
def test_corpus_tourism_intensity_returns_the_recipe(real):
    out = disc("intensitate turistica Cluj 2023")
    c = card(out, "tourism_intensity")
    assert out["status"] == "ok" and c["recipe"] == "tourism_intensity"
    assert c["next_call"] == {"tool": "run_recipe", "arguments": {
        "recipe": "tourism_intensity", "lang": "ro", "year": "2023", "areas": ["Cluj"]}}
    assert c["candidates"][0]["sources"] == ["TUR105D_judete", "POP105A_judete_grupe"]


@pytest.mark.corpus
@pytest.mark.parametrize("q,reason,ids", [
    ("somaj", "ambiguous_definition", {"registered_unemployment_rate", "ilo_unemployment_rate"}),
    ("turism", "ambiguous_definition", {"tourist_overnight_stays", "tourism_intensity"}),
])
def test_corpus_generic_words_ask_for_a_definition(real, q, reason, ids):
    out = disc(q)
    assert out["status"] == "needs_clarification" and out["reason"] == reason
    assert {c["id"] for c in out["data"]["choices"]} == ids
    assert all(c["next_call"] for c in out["data"]["choices"])
    assert all(c["next_call"] is None for c in out["data"]["concepts"])
    assert assert_calls_valid(out) > 0


@pytest.mark.corpus
def test_corpus_city_and_specific_resident_population(real):
    out = disc("Cluj-Napoca populatia rezidenta")
    assert out["status"] == "needs_clarification" and out["reason"] == "ambiguous_place"
    out = disc("populatia rezidenta Cluj 2024")
    assert out["status"] == "ok"
    nc = card(out, "resident_population")["next_call"]
    assert nc["arguments"]["dataset"] == "POP105A_judete_grupe"
    assert nc["arguments"]["filters"] == {"REF_AREA": ["Cluj"], "TIME_PERIOD": ["2024"]}
    from app.db import get_conn
    from app.services.data_query import run_query
    res = run_query(get_conn(), nc["arguments"]["dataset"], nc["arguments"]["filters"],
                    nc["arguments"]["group_by"])
    assert not res.get("unavailable") and len(res["rows"]) == 1


@pytest.mark.corpus
def test_corpus_year_beyond_the_data_and_rates_are_not_papered_over(real):
    out = disc("salariul net Cluj 2030")
    c = card(out, "net_earnings")
    assert "period_unavailable" in [n["code"] for n in c["notes"]]
    assert c["next_call"]["tool"] == "find_dimension_values"
    out = disc("rata somajului inregistrat Cluj 2019")
    c = card(out, "registered_unemployment_rate")
    assert c["next_call"]["tool"] == "run_recipe" and c["next_call"]["arguments"]["year"] == "2019"
    ds = cand(c, "SOM103A_judete")
    assert ds["queryable"] is False and ds["next_call"]["tool"] == "describe_dataset"


@pytest.mark.corpus
def test_corpus_every_reviewed_concept_is_discoverable_within_budget(real):
    from app.services import concept_search as cs
    for c in cs.load_concepts():
        for lang in ("ro", "en"):
            alias = (c["aliases"].get(lang) or c["aliases"]["ro"])[0]
            out = disc(alias, lang=lang)
            assert out["status"] in ("ok", "needs_clarification"), (c["id"], lang)
            assert C.size(out) <= C.MAX_RESULT_BYTES
            assert out["data"]["concepts"] and out["data"]["concepts"][0]["id"] == c["id"], (c["id"], lang)
            assert_calls_valid(out)


@pytest.mark.corpus
def test_corpus_generic_population_uses_disclosed_resident_default(real):
    out = disc('populatie')
    assert out['status'] == 'ok'
    assert out['data']['interpretation']['assumed_definition'] == 'resident_population'
    assert any(w['code'] == 'assumed_definition' for w in out['warnings'])
    assert card(out, 'resident_population')['next_call']
