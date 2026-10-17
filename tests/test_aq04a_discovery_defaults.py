"""AQ-04A: the reviewed discovery defaults are validated configuration, not code.

Part 1 validates `app/data/discovery_defaults.json` against the shipped concept catalogue and
recipes, and rejects invalid configurations (nothing needs a corpus).

Part 2 runs `discover_indicators` with the SHIPPED concepts.json, recipes' tourism concept and
policy on a synthetic corpus whose datasets carry the production dataset codes, so every
default is exercised exactly as configured. Known values (resident population 2022 + 10 per
year, domicile 20 below, July 5 above; stays = 3 / 4 / 5 times the resident population):

                      Cluj   Iași   Municipiul București
  POP105A (2023)       710    810    1910
  stays per resident   3.0    4.0    5.0

  POP107D_grupe_localitate 2025 (domicile, by locality; GOS102A lists the cities):
    Cluj-Napoca 324000, Iași 290000, Turda 55000, Hârlău 9500, and a COMMUNE (Apahida)
    of 999999 that a city ranking must exclude.
"""
import json

import pytest

from app.services import concept_search as cs
from app.services import dataset_search, recipes
from app.services.tools import discovery_policy as dp
from app.services.tools import registry as R
from app.services.tools import schemas as S
from at01_fixtures import add_dataset, add_search_columns, call, make_env, said
from test_at01_changes import time_dim, unit_dim
from test_at01_discovery import real  # noqa: F401 — the pinned-generation probe fixture
from test_at01_recipes_links import install_recipes, make_recipe

CTY = ["Cluj", "Iași", "Municipiul București"]
REGIONS = ["Nord-Vest", "Sud"]
YEARS = ("2022", "2023", "2024")
POP = {"Cluj": 700.0, "Iași": 800.0, "Municipiul București": 1900.0}
STAYS_PER_RESIDENT = {"Cluj": 3.0, "Iași": 4.0, "Municipiul București": 5.0}
LOCALITIES = [("Cluj", "54975 MUNICIPIUL CLUJ-NAPOCA", 320000.0, 324000.0),
              ("Iași", "95000 MUNICIPIUL IASI", 285000.0, 290000.0),
              ("Cluj", "55400 MUNICIPIUL TURDA", 53000.0, 55000.0),
              ("Iași", "96000 ORAS HARLAU", 9000.0, 9500.0),
              ("Cluj", "56000 COMUNA APAHIDA", 900000.0, 999999.0)]
CITIES = [name for _, name, *_ in LOCALITIES if "COMUNA" not in name]


def area_dim(names, level="county", col="REF_AREA"):
    """Geo dimension; counties carry the clean name the place parser reads."""
    clean = (lambda n: dict(geo_level=level, geo_name_clean=n)) if level != "locality" else (lambda n: dict(geo_level=level))
    return (col, "Entitati", "geo", [(n, clean(n)) for n in names])


def _series(corpus, code, name, base, *, names=CTY, level="county", unit="Numar persoane",
            shift=0.0, unit_type="count"):
    rows = [(a, y, unit, base[a] + shift + 10.0 * (int(y) - 2022)) for a in names for y in YEARS]
    add_dataset(corpus, code, [area_dim(names, level), time_dim(list(YEARS)), unit_dim(unit)], rows,
                name=name, unit_type=unit_type)


def build(corpus, omit=()):
    sets = {
        "POP105A_judete_grupe": lambda: _series(corpus, "POP105A_judete_grupe", "Populatia rezidenta", POP),
        "POP105A_regiuni_grupe": lambda: _series(corpus, "POP105A_regiuni_grupe", "Populatia rezidenta regiuni",
                                                 {"Nord-Vest": 2500.0, "Sud": 4000.0}, names=REGIONS, level="region"),
        "POP107A_judete_grupe": lambda: _series(corpus, "POP107A_judete_grupe", "Populatia dupa domiciliu", POP, shift=-20),
        "POP106A_judete_grupe": lambda: _series(corpus, "POP106A_judete_grupe", "Populatia la 1 iulie", POP, shift=5),
        "TUR105D_judete": lambda: add_dataset(
            corpus, "TUR105D_judete", [area_dim(CTY), time_dim(list(YEARS)), unit_dim("Numar")],
            [(a, y, "Numar", STAYS_PER_RESIDENT[a] * (POP[a] + 10.0 * (int(y) - 2022)))
             for a in CTY for y in YEARS], name="Innoptari turistice"),
        "SOM103A_judete": lambda: _series(corpus, "SOM103A_judete", "Somaj inregistrat", {a: 3.0 for a in CTY},
                                          unit="Procente", unit_type="percentage"),
        "AMG157A_anual": lambda: add_dataset(
            corpus, "AMG157A_anual", [area_dim(["Romania"], "national"), time_dim(list(YEARS)), unit_dim("Procente")],
            [("Romania", y, "Procente", 5.5) for y in YEARS], name="Somaj BIM", unit_type="percentage"),
        "POP107D_grupe_localitate": lambda: add_dataset(
            corpus, "POP107D_grupe_localitate",
            [area_dim(["Cluj", "Iași"]), area_dim([n for _, n, *_ in LOCALITIES], "locality", "REF_AREA_2"),
             time_dim(["2024", "2025"]), unit_dim("Numar persoane")],
            [(c, n, y, "Numar persoane", v) for c, n, a, b in LOCALITIES for y, v in (("2024", a), ("2025", b))],
            name="Populatia dupa domiciliu pe localitati"),
        "GOS102A": lambda: add_dataset(
            corpus, "GOS102A", [area_dim(CITIES, "locality", "REF_AREA_2"), time_dim(["2024"]), unit_dim("Hectare")],
            [(c, "2024", "Hectare", 10.0) for c in CITIES], name="Localitati"),
    }
    for code, make in sets.items():
        if code not in omit:
            make()
    add_search_columns(corpus)      # datasets cannot be added after these


def make(tmp_path, monkeypatch, omit=(), drop_concepts=()):
    e = make_env(tmp_path, monkeypatch, build=lambda corpus: build(corpus, omit))
    install_recipes(tmp_path, monkeypatch, make_recipe("tourism_intensity", "TUR105D_judete", "POP105A_judete_grupe"))
    monkeypatch.setattr(dataset_search, "SEARCH_DB_PATH", tmp_path / "no-fts.duckdb")
    dataset_search._reset_for_tests()
    if drop_concepts:           # the shipped catalogue minus some concepts: their mappings become absent
        raw = json.loads(cs.CONCEPTS_PATH.read_text(encoding="utf-8"))
        raw["concepts"] = [c for c in raw["concepts"] if c["id"] not in drop_concepts]
        (tmp_path / "concepts.json").write_text(json.dumps(raw), encoding="utf-8")
        monkeypatch.setattr(cs, "CONCEPTS_PATH", tmp_path / "concepts.json")
    return e


@pytest.fixture
def build_env(tmp_path, monkeypatch):
    yield lambda **kw: make(tmp_path, monkeypatch, **kw)
    monkeypatch.undo()
    dataset_search._reset_for_tests()


@pytest.fixture
def env(build_env):
    return build_env()


def disc(query, lang="ro", **kw):
    return call("discover_indicators", query=query, lang=lang, **kw)


def card(out, cid):
    return next(c for c in out["data"]["concepts"] if c["id"] == cid)


def run(nc):
    """Execute a suggested call exactly as a model would, through the registry."""
    assert nc is not None
    out = R.call_tool(nc["tool"], nc["arguments"])
    R.validate_result(nc["tool"], out)
    return out


def codes(out):
    return [w["code"] for w in out["warnings"]]


# ============================================================ 1. the configuration

def shipped():
    return json.loads(dp.POLICY_PATH.read_text(encoding="utf-8"))


def catalogue():
    return json.loads(cs.CONCEPTS_PATH.read_text(encoding="utf-8"))["concepts"]


def test_shipped_policy_matches_catalogue_and_recipes():
    assert dp.validate(shipped(), catalogue(), recipe_ids=set(recipes.load_recipes())) == []
    pol = dp.load_policy()
    assert pol.data["version"] == 1 and set(pol.term_res) == {
        "resident_population", "domicile_population", "resident_population_july"}


def test_the_reviewed_table_is_pinned_in_the_configuration():
    p = shipped()
    assert p["population"]["default"] == {"concept": "resident_population", "phrase": "populatia rezidenta"}
    cities = p["population"]["cities"]
    assert cities["concept"] == "domicile_population" and cities["phrase"] == "populatia dupa domiciliu"
    # AQ-05A: a city may also be ranked by change, but only through the catalogue class below
    assert cities["variants"] == {"locality": "POP107D_grupe_localitate"} and cities["operations"] == ["rank", "change"]
    assert (cities["entity_columns"], cities["entity_class"]) == (["REF_AREA", "REF_AREA_2"], "cities")
    assert p["recipe_routes"] == [{"intent": "tourism_ratio", "concept": "tourism_intensity",
                                   "phrase": "innoptari pe locuitor"}]
    # owner decision 2026-10-17: unemployment is no longer clarify-only. It defaults by the level the question
    # points at; a region, a level that cannot be told and a question with no level still ask.
    assert "clarify_only" not in p and len(p["level_defaults"]) == 1
    entry = p["level_defaults"][0]
    assert entry["topic"] == "unemployment" and entry["no_level"] == "clarify"
    assert entry["levels"] == {"county": "registered_unemployment_rate", "national": "ilo_unemployment_rate"}
    assert set(entry["definitions"]) == {"registered_unemployment_rate", "ilo_unemployment_rate"}
    # owner decision 2026-10-17: one named county narrows a city ranking (Municipiul Bucuresti never does)
    assert cities["place_filter"] == {"level": "county", "column": "REF_AREA", "except": ["municipiul-bucuresti"]}
    targets = {p["population"]["default"]["concept"], cities["concept"], p["recipe_routes"][0]["concept"]}
    assert not targets & {"registered_unemployment_rate", "ilo_unemployment_rate"}    # one assumption per concept


def test_max_top_k_is_the_ranking_tools_own_limit():
    le = next(m.le for m in S.RankEntitiesArgs.model_fields["top_k"].metadata if hasattr(m, "le"))
    assert dp.MAX_TOP_K == le == 100


def _set(path, value):
    def edit(p):
        node = p
        for k in path[:-1]:
            node = node[k]
        if value is _DELETE:
            node.pop(path[-1])
        else:
            node[path[-1]] = value
    return edit


_DELETE = object()
POP_ = "population"
STRUCTURAL = [
    ("version", _set(["version"], 2), "version must be 1"),
    ("no population", _set([POP_], _DELETE), "population must be an object"),
    ("default concept not a definition", _set([POP_, "default", "concept"], "net_earnings"), "is not a definition"),
    ("empty terms", _set([POP_, "definitions", "resident_population", "terms"], []), "terms must be a non-empty"),
    ("unfolded term", _set([POP_, "definitions", "resident_population", "terms"], ["Rezident"]), "terms must be"),
    ("unfolded phrase", _set([POP_, "default", "phrase"], "Populația rezidentă"), "folded phrase"),
    ("no locality variant", _set([POP_, "cities", "variants"], {"county": "POP107A_judete_grupe"}), "locality level"),
    ("unknown level", _set([POP_, "cities", "variants"], {"locality": "X1", "district": "X2"}), "unknown level 'district'"),
    ("dataset code", _set([POP_, "cities", "variants", "locality"], "POP 107D; drop"), "is not a dataset code"),
    ("unknown operation", _set([POP_, "cities", "operations"], ["sum"]), "non-empty subset"),
    ("city change without the city class", lambda p: p[POP_]["cities"].update(operations=["rank", "change"], entity_class="all"),
     "only through entity_class 'cities'"),
    ("city lookup", _set([POP_, "cities", "operations"], ["lookup"]), "cannot be served at level 'locality'"),
    ("duplicate entity column", _set([POP_, "cities", "entity_columns"], ["REF_AREA", "REF_AREA"]), "unique non-time"),
    ("time entity column", _set([POP_, "cities", "entity_columns"], ["REF_AREA", "TIME_PERIOD"]), "unique non-time"),
    ("entity class", _set([POP_, "cities", "entity_class"], "villages"), "entity_class must be one of"),
    ("cities without locality key", _set([POP_, "cities", "entity_columns"], ["REF_AREA"]), "requires REF_AREA_2"),
    ("route intent", lambda p: p["recipe_routes"][0].update(intent="density"), "intent must be one of"),
    ("duplicate route", lambda p: p["recipe_routes"].append(dict(p["recipe_routes"][0])), "listed twice"),
    ("route phrase", lambda p: p["recipe_routes"][0].update(phrase="Stays Per Resident"), "folded phrase"),
    ("level_defaults with a population default",
     lambda p: p["level_defaults"][0]["definitions"].update(
         resident_population={"terms": ["rezident"], "phrase": "populatia rezidenta"}),
     "also has another default, route or level rule"),
    ("level_defaults without definitions", lambda p: p["level_defaults"][0].update(definitions={}),
     "definitions must name at least two concepts"),
]


@pytest.mark.parametrize("name,edit,expected", STRUCTURAL, ids=[s[0] for s in STRUCTURAL])
def test_invalid_structure_is_rejected_at_load(name, edit, expected, tmp_path, monkeypatch):
    bad = shipped()
    edit(bad)
    problems = dp.validate(bad)
    assert any(expected in p for p in problems), problems
    path = tmp_path / "defaults.json"
    path.write_text(json.dumps(bad), encoding="utf-8")
    monkeypatch.setattr(dp, "POLICY_PATH", path)
    with pytest.raises(dp.PolicyError, match="invalid"):
        dp.load_policy()


REFERENCES = [
    ("concept not in catalogue", lambda p: p[POP_]["default"].update(concept="resident_population"),
     lambda cs_: [c for c in cs_ if c["id"] != "resident_population"], "not in the concept catalogue"),
    ("phrase is not an alias", lambda p: p[POP_]["default"].update(phrase="populatia stabila de drept"),
     None, "is not a specific alias of resident_population"),
    ("a generic alias is not a phrase", lambda p: p[POP_]["default"].update(phrase="populatia"),
     None, "is not a specific alias of resident_population"),
    ("another concept's alias", lambda p: p[POP_]["cities"].update(phrase="populatia rezidenta"),
     None, "is not a specific alias of domicile_population"),
    ("alias of another concept", lambda p: p[POP_]["cities"].update(alias="rezidenta"),
     None, "is not an alias of domicile_population"),
    ("route to a plain concept", lambda p: p["recipe_routes"][0].update(concept="wage_like", phrase="salariul net"),
     lambda cs_: cs_ + [{"id": "wage_like", "aliases": {"ro": ["salariul net"]}, "variants": {"county": "X"}}],
     "is not a recipe concept"),
    ("route to a missing recipe", lambda p: None, None, "does not exist"),
    ("level_defaults concept unknown",
     lambda p: p["level_defaults"][0]["definitions"].update(
         no_such_concept={"terms": ["nimic"], "phrase": "nimic de gasit"}), None, "no_such_concept"),
]


@pytest.mark.parametrize("name,edit,catalogue_edit,expected", REFERENCES, ids=[r[0] for r in REFERENCES])
def test_references_are_checked_against_the_catalogue(name, edit, catalogue_edit, expected):
    bad, concepts = shipped(), catalogue()
    edit(bad)
    if catalogue_edit:
        concepts = catalogue_edit(concepts)
    recipe_ids = set(recipes.load_recipes()) - ({"tourism_intensity"} if name == "route to a missing recipe" else set())
    problems = dp.validate(bad, concepts, recipe_ids=recipe_ids)
    assert any(expected in p for p in problems), problems


def test_locality_datasets_and_entity_columns_are_checked_when_a_corpus_is_given():
    cols = {"POP107D_grupe_localitate": {"REF_AREA", "REF_AREA_2", "TIME_PERIOD", "AGE"}}
    assert dp.validate(shipped(), catalogue(), dataset_columns=cols.get) == []
    assert any("does not exist" in p for p in dp.validate(shipped(), catalogue(), dataset_columns=lambda c: None))
    cols["POP107D_grupe_localitate"] = {"REF_AREA", "TIME_PERIOD"}
    assert any("REF_AREA_2" in p and "not columns of" in p
               for p in dp.validate(shipped(), catalogue(), dataset_columns=cols.get))


def test_unreadable_or_malformed_policy_files_are_errors(tmp_path, monkeypatch):
    monkeypatch.setattr(dp, "POLICY_PATH", tmp_path / "missing.json")
    with pytest.raises(dp.PolicyError, match="unreadable"):
        dp.load_policy()
    (tmp_path / "bad.json").write_text("{not json", encoding="utf-8")
    monkeypatch.setattr(dp, "POLICY_PATH", tmp_path / "bad.json")
    with pytest.raises(dp.PolicyError, match="not valid JSON"):
        dp.load_policy()


@pytest.mark.corpus
def test_corpus_locality_dataset_and_entity_columns_exist(real):  # noqa: F811
    from app.db import get_conn
    from app.services import dataset_meta
    conn = get_conn()

    def columns(code):
        ctx = dataset_meta.get_aggregation_context(conn, code)
        return None if ctx is None else {d["dim_column_name"] for d in ctx["dimensions"]}

    assert dp.validate(shipped(), catalogue(), recipe_ids=set(recipes.load_recipes()),
                       dataset_columns=columns) == []


# ============================================================ interpretation vocabulary

@pytest.mark.parametrize("question,k,order,rank", [
    ("cele mai populate 30 de orașe", 30, "desc", True),
    ("top 5 cities by population", 5, "desc", True),
    ("largest 5 cities population", 5, "desc", True),
    ("5 largest cities by population", 5, "desc", True),
    ("primele 10 orașe după populație", 10, "desc", True),
    ("bottom 5 cities by population", 5, "asc", True),
    ("most populated cities", 30, "desc", True),
    ("populatia curenta a orasele", 30, "desc", False),
])
def test_city_ranking_paraphrases_read_the_same_intent(question, k, order, rank):
    from app.services.tools.intent import interpret
    i = interpret(question)
    assert i["cities"] and i["population"], question
    assert (i["top_k"], i["order"]) == (k, order)
    assert (i["operation"] == "rank") is rank


@pytest.mark.parametrize("question,kinds", [
    ("populatia feminina pe judete", {"sex"}),
    ("population of women aged 65 and over by county", {"sex", "age"}),
    ("populatia de peste 65 de ani Cluj 2023", {"age"}),
    ("populatia 20-24 ani", {"age"}),
    ("resident population of Cluj aged 20-24", {"age"}),
    ("rata somajului pe sexe", {"sex"}),
    ("population per capita", {"denominator"}),
    ("tourist arrivals per 1000 inhabitants in Cluj", {"denominator"}),
    # not constraints: a period range, a threshold without an age unit, a plain question
    ("populatia in ultimii 5 ani", set()),
    ("orasele cu peste 50000 locuitori", set()),
    ("evolutia populatiei in Cluj 2015 2024", set()),
    # the stays-per-resident denominator is handled by the reviewed recipe, not reported
    ("cate innoptari revin pe locuitor in Cluj", set()),
])
def test_constraint_vocabulary_is_bounded(question, kinds):
    from app.services.tools.intent import interpret
    assert {c["kind"] for c in interpret(question)["constraints"]} == kinds


# ============================================================ 2. generic population (county / region)

@pytest.mark.parametrize("question,lang", [
    ("populatia pe judete", "ro"), ("populație pe județe 2023", "ro"), ("populatie Cluj 2023", "ro"),
    ("population by county", "en"), ("population of Cluj in 2023", "en"), ("latest population by county", "en"),
])
def test_generic_population_is_resident_and_disclosed_with_alternatives(env, question, lang):
    out = disc(question, lang)
    assert out["status"] == "ok" and out["data"]["choices"] == []
    assert out["data"]["interpretation"]["assumed_definition"] == "resident_population"
    warn = next(w for w in out["warnings"] if w["code"] == "assumed_definition")
    assert warn["subject"] == "resident_population" and said(
        warn["message"], lang, "alternatives remain available", "alternativele rămân disponibile")
    c = card(out, "resident_population")
    assert c["assumed"] is True and not c["requires_choice"]
    assert {a["id"] for a in c["alternatives"]} >= {"domicile_population"}      # the others stay one call away
    assert c["next_call"]["tool"] == "query_data" and c["next_call"]["arguments"]["dataset"] == "POP105A_judete_grupe"


def test_the_default_answers_with_resident_values_for_the_named_place_and_year(env):
    nc = card(disc("population of Cluj in 2023", "en"), "resident_population")["next_call"]
    assert nc["arguments"]["filters"] == {"REF_AREA": ["Cluj"], "TIME_PERIOD": ["2023"]}
    rows = run(nc)["data"]["rows"]
    assert rows == [["Cluj", "2023", 710.0]]                           # resident, not 690 (domicile) or 715 (July)


def test_the_default_also_follows_a_requested_region_level(env):
    nc = card(disc("populatia pe regiuni 2023"), "resident_population")["next_call"]
    assert nc["arguments"]["dataset"] == "POP105A_regiuni_grupe"
    assert nc["arguments"]["filters"] == {"TIME_PERIOD": ["2023"]}


def test_latest_resolves_to_a_real_period_and_an_exact_year_is_never_swapped(env):
    out = disc("latest population by county", "en")
    cand = card(out, "resident_population")["candidates"][0]
    assert cand["next_call"]["arguments"]["filters"] == {"TIME_PERIOD": ["2024"]}
    assert "latest_period" in [n["code"] for n in cand["notes"]]
    out = disc("populatia Cluj 2030")
    c = card(out, "resident_population")
    assert "period_unavailable" in [n["code"] for n in c["notes"]]
    assert c["next_call"]["tool"] == "find_dimension_values"
    assert "TIME_PERIOD" not in json.dumps(c["candidates"][0]["next_call"]["arguments"].get("filters", {}))
    assert out["data"]["interpretation"]["assumed_definition"] == "resident_population"


# ============================================================ explicit definitions are never overwritten

@pytest.mark.parametrize("question,lang,expected,dataset", [
    ("resident population by county", "en", "resident_population", "POP105A_judete_grupe"),
    ("populatia rezidenta pe judete 2023", "ro", "resident_population", "POP105A_judete_grupe"),
    ("populatia dupa domiciliu pe judete", "ro", "domicile_population", "POP107A_judete_grupe"),
    ("domicile population by county", "en", "domicile_population", "POP107A_judete_grupe"),
    ("registered population by county", "en", "domicile_population", "POP107A_judete_grupe"),
    ("populatia la 1 iulie pe judete", "ro", "resident_population_july", "POP106A_judete_grupe"),
    ("mid-year population by county", "en", "resident_population_july", "POP106A_judete_grupe"),
    ("population on 1 july by county", "en", "resident_population_july", "POP106A_judete_grupe"),
])
def test_a_definition_named_in_the_question_is_not_replaced_by_the_default(env, question, lang, expected, dataset):
    out = disc(question, lang)
    assert out["status"] == "ok"
    assert out["data"]["interpretation"]["assumed_definition"] is None and "assumed_definition" not in codes(out)
    assert out["data"]["concepts"][0]["id"] == expected
    assert not any(c.get("assumed") for c in out["data"]["concepts"])
    assert out["data"]["concepts"][0]["next_call"]["arguments"]["dataset"] == dataset
    if expected != "resident_population":      # no default phrase was put in front of the user's words
        assert "rezidenta" not in (out["data"]["interpretation"]["family_query"] or "")


# ============================================================ city ranking

CITY_RANKING = [
    ("top 30 orase dupa populatie", "ro", 30, "desc"), ("cele mai populate 30 de orașe", "ro", 30, "desc"),
    ("populația curentă a celor mai populate 30 de orașe", "ro", 30, "desc"),
    ("most populated cities", "en", 30, "desc"), ("top 10 cities by population", "en", 10, "desc"),
    ("largest 5 cities population", "en", 5, "desc"), ("bottom 5 cities by population", "en", 5, "asc"),
    ("primele 10 orase dupa populatie", "ro", 10, "desc"),
]


@pytest.mark.parametrize("question,lang,k,order", CITY_RANKING)
def test_generic_city_population_ranking_uses_domicile_and_says_what_it_counts(env, question, lang, k, order):
    out = disc(question, lang)
    assert out["status"] == "ok"
    assert out["data"]["interpretation"]["assumed_definition"] == "domicile_population"
    assert out["data"]["interpretation"]["level"] == "locality"
    warn = next(w for w in out["warnings"] if w["code"] == "assumed_definition")
    assert warn["subject"] == "domicile_population" and "legal" in warn["message"] \
        and said(warn["message"], lang, "not available for cities", "nu este disponibilă pentru orașe")   # the definition, disclosed
    nc = card(out, "domicile_population")["next_call"]
    assert nc == {"tool": "rank_entities", "arguments": {
        "dataset": "POP107D_grupe_localitate", "entity_columns": ["REF_AREA", "REF_AREA_2"], "year": None,
        "filters": {}, "entity_class": "cities", "top_k": k, "order": order, "lang": lang}}


def test_the_city_ranking_ranks_every_city_before_the_cut_and_excludes_communes(env):
    nc = card(disc("top 3 cities by population", "en"), "domicile_population")["next_call"]
    d = run(nc)["data"]
    assert d["year"] == "2025"                                   # latest actual period
    assert [(r["rank"], r["entity"]["REF_AREA_2"], r["value"]) for r in d["rows"]] == [
        (1, "54975 MUNICIPIUL CLUJ-NAPOCA", 324000.0), (2, "95000 MUNICIPIUL IASI", 290000.0),
        (3, "55400 MUNICIPIUL TURDA", 55000.0)]                  # the 999999 commune is not a city
    assert d["eligible_count"] == 4 and d["outside_class_count"] == 1
    d24 = run(card(disc("top 10 cities by population in 2024", "en"), "domicile_population")["next_call"])["data"]
    assert d24["year"] == "2024" and d24["rows"][0]["value"] == 320000.0 and d24["requested_year"] == "2024"


@pytest.mark.parametrize("question,lang", [
    ("top 10 cities by domicile population", "en"), ("populatia dupa domiciliu a celor mai populate 10 orase", "ro"),
    ("top 10 cities by registered population", "en"),
])
def test_explicit_domicile_city_population_is_respected(env, question, lang):
    out = disc(question, lang)
    assert out["status"] == "ok" and "assumed_definition" not in codes(out)
    assert out["data"]["interpretation"]["assumed_definition"] is None
    assert card(out, "domicile_population")["next_call"]["arguments"]["dataset"] == "POP107D_grupe_localitate"
    assert card(out, "domicile_population")["next_call"]["arguments"]["top_k"] == 10


@pytest.mark.parametrize("question,lang", [
    ("top 10 cities by resident population", "en"), ("populatia rezidenta a celor mai populate 10 orase", "ro"),
    ("top 10 cities by population on 1 july", "en"), ("populatia la 1 iulie a primelor 10 orase", "ro"),
    ("top 10 cities resident population by domicile", "en"),         # two definitions: not both satisfiable
])
def test_explicit_resident_or_july_city_population_is_unavailable_never_substituted(env, question, lang):
    out = disc(question, lang)
    assert out["status"] == "unavailable" and out["reason"] == "level_unavailable"
    assert said(out["message"], lang, "County data was not substituted", "Datele pe județ nu au fost înlocuite") \
        and said(out["message"], lang, "domicile", "domiciliu")
    assert out["data"] == {} and not out["warnings"]


@pytest.mark.parametrize("question,reason,fragment", [
    ("top 10 cities by net salary", "level_unavailable", "only one is the annual population"),
    ("innoptari pe locuitor in orasele mari", "level_unavailable", "only one is the annual population"),
    ("cities population change 2020 2024", "unsupported_operation", "change rankings"),
    ("orasele care au pierdut populatie", "unsupported_operation", "change rankings"),
    ("population and population density of the top 30 cities", "unsupported_operation", "density"),
])
def test_unsupported_city_questions_are_stated_not_answered_with_county_data(env, question, reason, fragment):
    out = disc(question, "en")
    assert out["status"] == "unavailable" and out["reason"] == reason and fragment in out["message"]
    assert out["data"] == {}


def test_top_k_out_of_range_is_an_explicit_error(env):
    for q, fragment in (("top 200 cities by population", "At most 100"), ("top 0 cities by population", "at least 1"),
                        ("top 101 counties by population", "At most 100")):
        out = disc(q, "en")
        assert out["status"] == "error" and out["reason"] == "invalid_input" and fragment in out["message"], q
    out = disc("top 100 cities by population", "en")
    assert out["status"] == "ok" and card(out, "domicile_population")["next_call"]["arguments"]["top_k"] == 100


# ============================================================ stays per resident

@pytest.mark.parametrize("question,lang", [
    ("Câte înnoptări revin la un locuitor în Cluj, în 2023?", "ro"),
    ("Câte înnoptări turistice revin pe locuitor în Cluj, în 2023?", "ro"),
    ("innoptari per locuitor Cluj 2023", "ro"),
    ("How many overnight stays were there per resident in Cluj in 2023?", "en"),
    ("stays per resident in Cluj 2023", "en"),
])
def test_stays_per_resident_reaches_the_reviewed_recipe_with_the_exact_year(env, question, lang):
    out = disc(question, lang)
    assert out["status"] == "ok"
    assert [c["id"] for c in out["data"]["concepts"]] == ["tourism_intensity"]
    nc = out["data"]["concepts"][0]["next_call"]
    assert nc == {"tool": "run_recipe", "arguments": {"recipe": "tourism_intensity", "lang": lang,
                                                      "year": "2023", "areas": ["Cluj"]}}
    res = run(nc)
    assert res["status"] == "ok" and res["data"]["year"] == "2023"
    row = res["data"]["rows"][0]
    assert (row["label"], row["stays"], row["population"], row["value"]) == ("Cluj", 2130.0, 710.0, 3.0)


def test_stays_per_resident_without_a_year_leaves_the_year_to_the_recipe_and_never_swaps_one(env):
    out = disc("overnight stays per resident in Cluj latest", "en")
    nc = card(out, "tourism_intensity")["next_call"]
    assert nc["tool"] == "run_recipe" and "year" not in nc["arguments"]
    assert run(nc)["data"]["year"] == "2024"                       # the latest year both sources share
    out = disc("overnight stays per resident in Cluj 2030", "en")
    c = card(out, "tourism_intensity")
    assert "period_unavailable" in [n["code"] for n in c["candidates"][0]["notes"]]
    assert c["next_call"]["tool"] == "find_dimension_values"


@pytest.mark.parametrize("question", ["înnoptări la mia de locuitori Cluj", "turisti pe locuitor Cluj",
                                      "tourists per resident in Cluj"])
def test_other_denominators_are_unsupported_not_turned_into_counts(env, question):
    out = disc(question)
    assert out["status"] == "unavailable" and out["reason"] == "unsupported_operation" and out["data"] == {}


def test_a_stays_question_without_a_denominator_stays_a_plain_count(env):
    out = disc("innoptari turistice Cluj 2023")
    assert [c["id"] for c in out["data"]["concepts"]] == ["tourist_overnight_stays"]
    assert out["data"]["concepts"][0]["recipe"] is None


# ============================================================ unemployment

@pytest.mark.parametrize("question,lang", [("somaj", "ro"), ("rata somajului", "ro"), ("unemployment", "en"),
                                           ("unemployment rate", "en")])
def test_generic_unemployment_asks_registered_versus_ilo_and_assumes_nothing(env, question, lang):
    out = disc(question, lang)
    assert out["status"] == "needs_clarification" and out["reason"] == "ambiguous_definition"
    assert {c["id"] for c in out["data"]["choices"]} == {"registered_unemployment_rate", "ilo_unemployment_rate"}
    assert out["data"]["interpretation"]["assumed_definition"] is None and "assumed_definition" not in codes(out)
    assert all(c["next_call"] is None and c["requires_choice"] for c in out["data"]["concepts"])
    for choice in out["data"]["choices"]:                        # choosing is a separate, specific call
        picked = run(choice["next_call"])
        assert picked["status"] == "ok" and picked["data"]["concepts"][0]["id"] == choice["id"]


# ============================================================ constraints are reported, never dropped

UNAPPLIED = [
    ("populatia feminina pe judete", "ro", {"sex"}), ("population of women aged 65 and over by county", "en", {"sex", "age"}),
    ("populatia de peste 65 de ani Cluj 2023", "ro", {"age"}), ("resident population of Cluj aged 20-24", "en", {"age"}),
    ("top 10 judete dupa populatia rezidenta feminina", "ro", {"sex"}), ("population per capita", "en", {"denominator"}),
    ("populatia pe sexe 2023", "ro", {"sex"}),
]


@pytest.mark.parametrize("question,lang,kinds", UNAPPLIED)
def test_unsupported_age_sex_and_denominator_are_reported_and_no_call_ignores_them(env, question, lang, kinds):
    out = disc(question, lang)
    assert out["status"] == "ok"
    assert {c["kind"] for c in out["data"]["interpretation"]["unapplied_constraints"]} == kinds
    subjects = [w["subject"] for w in out["warnings"] if w["code"] == "constraint_not_applied"]
    assert sorted(subjects) == sorted(kinds)                       # one warning per kind
    assert said(out["message"], lang, "Not applied from the question", "Neaplicat din întrebare")
    c = out["data"]["concepts"][0]
    assert c["next_call"]["tool"] == "describe_dataset"                # explicit values are chosen there
    assert all(cd["next_call"] is None or cd["next_call"]["tool"] in ("describe_dataset", "find_dimension_values")
               for cd in c["candidates"])
    assert "constraint_not_applied" in [n["code"] for n in c["candidates"][0]["notes"]]
    R.validate_result("describe_dataset", run(c["next_call"]))


def test_the_same_question_without_the_constraint_still_gets_its_data_call(env):
    out = disc("populatia pe judete 2023")
    assert out["data"]["interpretation"]["unapplied_constraints"] == []
    assert card(out, "resident_population")["next_call"]["tool"] == "query_data"
    assert "constraint_not_applied" not in codes(out)


def test_without_a_place_filter_a_county_around_a_city_ranking_is_reported_not_silently_dropped(
        env, monkeypatch, tmp_path):
    """The AQ-04A behaviour, now the rollback of the 2026-10-17 decision: with `place_filter` removed
    from the configuration a county around a city ranking is reported and the data call withheld."""
    raw = shipped()
    del raw["population"]["cities"]["place_filter"]
    (tmp_path / "no-place-filter.json").write_text(json.dumps(raw), encoding="utf-8")
    monkeypatch.setattr(dp, "POLICY_PATH", tmp_path / "no-place-filter.json")
    out = disc("top 10 orase din Cluj dupa populatie")
    assert out["data"]["interpretation"]["unapplied_constraints"] == [{"kind": "geography", "text": "Cluj"}]
    assert out["data"]["interpretation"]["ambiguities"] == []
    nc = card(out, "domicile_population")["next_call"]
    assert nc["tool"] == "describe_dataset" and nc["arguments"]["dataset"] == "POP107D_grupe_localitate"
    assert "geography" in [w["subject"] for w in out["warnings"] if w["code"] == "constraint_not_applied"]


def test_a_recipe_cannot_take_a_sex_constraint_so_it_offers_no_call(env):
    out = disc("overnight stays per resident of women in Cluj 2023", "en")
    c = card(out, "tourism_intensity")
    assert c["next_call"] is None and c["candidates"][0]["next_call"] is None
    assert [x["kind"] for x in out["data"]["interpretation"]["unapplied_constraints"]] == ["sex"]
    assert "constraint_not_applied" in [n["code"] for n in c["candidates"][0]["notes"]]


def test_a_constraint_inside_the_matched_concepts_own_alias_is_the_concept_not_a_dropped_filter(env, tmp_path, monkeypatch):
    raw = json.loads(cs.CONCEPTS_PATH.read_text(encoding="utf-8"))
    next(c for c in raw["concepts"] if c["id"] == "resident_population")["aliases"]["ro"].append(
        "populatia feminina rezidenta")
    (tmp_path / "concepts.json").write_text(json.dumps(raw), encoding="utf-8")
    monkeypatch.setattr(cs, "CONCEPTS_PATH", tmp_path / "concepts.json")
    out = disc("populatia feminina rezidenta pe judete")
    assert out["data"]["interpretation"]["unapplied_constraints"] == []
    assert card(out, "resident_population")["next_call"]["tool"] == "query_data"


# ============================================================ county / city ambiguity stays with the default

def test_a_city_named_place_keeps_the_county_choice_and_the_disclosed_default(env):
    out = disc("Cluj-Napoca populatie 2023")
    assert out["status"] == "needs_clarification" and out["reason"] == "ambiguous_place"
    assert out["data"]["interpretation"]["assumed_definition"] == "resident_population"
    assert "assumed_definition" in codes(out)
    assert {c["id"] for c in out["data"]["choices"]} == {"county", "all_counties"}
    assert card(out, "resident_population")["next_call"] is None           # no headline before the choice
    picked = run(next(c for c in out["data"]["choices"] if c["id"] == "county")["next_call"])
    assert picked["status"] == "ok"
    nc = card(picked, "resident_population")["next_call"]
    assert nc["arguments"]["filters"] == {"REF_AREA": ["Cluj"], "TIME_PERIOD": ["2023"]}
    assert run(nc)["data"]["rows"] == [["Cluj", "2023", 710.0]]


def test_a_city_ranking_is_not_a_county_city_ambiguity(env):
    out = disc("top 10 cities by population", "en")
    assert out["status"] == "ok" and out["data"]["choices"] == []
    assert out["data"]["interpretation"]["ambiguities"] == []


# ============================================================ absent mappings are inert

def test_a_default_whose_concept_is_absent_assumes_nothing(build_env):
    build_env(drop_concepts=("resident_population",))
    out = disc("populatie pe judete")
    assert out["data"]["interpretation"]["assumed_definition"] is None and "assumed_definition" not in codes(out)
    assert "rezidenta" not in (out["data"]["interpretation"]["family_query"] or "")    # no phrase was put in front
    assert out["data"]["concepts"] == [] and "no_match" in codes(out)


def test_a_default_whose_dataset_is_absent_does_not_warn_about_a_source_nobody_saw(build_env):
    build_env(omit=("POP105A_judete_grupe", "POP105A_regiuni_grupe"))
    out = disc("populatie pe judete")
    assert "resident_population" not in [c["id"] for c in out["data"]["concepts"]]
    assert out["data"]["interpretation"]["assumed_definition"] is None
    assert "assumed_definition" not in codes(out)


def test_a_city_ranking_without_its_configured_concept_is_unavailable_not_a_county_answer(build_env):
    build_env(drop_concepts=("domicile_population",))
    out = disc("top 10 cities by population", "en")
    assert out["status"] == "unavailable" and out["reason"] == "level_unavailable"
    assert "No reviewed city population series is configured" in out["message"] and out["data"] == {}


def test_a_city_ranking_whose_locality_dataset_is_absent_says_so(build_env):
    build_env(omit=("POP107D_grupe_localitate",))
    out = disc("top 10 cities by population", "en")
    assert out["status"] == "unavailable" and out["reason"] == "level_unavailable"
    assert "not in this data generation" in out["message"] and out["data"] == {}


@pytest.mark.parametrize("absent", [{"drop_concepts": ("tourism_intensity",)}, {"omit": ("TUR105D_judete",)}])
def test_a_recipe_route_without_its_concept_or_source_is_unavailable_not_a_raw_count(build_env, absent):
    build_env(**absent)
    out = disc("overnight stays per resident in Cluj 2023", "en")
    assert out["status"] == "unavailable" and out["reason"] == "recipe_unavailable"
    assert "no raw count was substituted" in out["message"] and out["data"] == {}


# ============================================================ the policy stays out of the catalogue

def test_catalogue_search_ignores_the_discovery_policy(env, monkeypatch, tmp_path):
    """Raw concept search (catalogue, UI, static site) never reads the policy: it is unchanged
    whether the policy file is valid, invalid or absent."""
    def search(q):
        r = env.client.get("/api/search", params={"q": q, "limit": 5})
        assert r.status_code == 200
        return r.json()

    before = {q: search(q) for q in ("populatie", "top 10 cities by population", "somaj")}
    monkeypatch.setattr(dp, "POLICY_PATH", tmp_path / "nothing.json")
    after = {q: search(q) for q in before}
    assert before == after
    pop = before["populatie"]["concepts"][0]
    assert pop["id"] == "resident_population" and pop["ambiguous"] is True and "assumed" not in pop
    assert not hasattr(cs, "dpol") and "discovery_policy" not in open(cs.__file__, encoding="utf-8").read()


def test_an_invalid_policy_fails_closed_instead_of_guessing(env, monkeypatch, tmp_path):
    bad = shipped()
    bad["population"]["cities"]["operations"] = ["rank", "lookup"]
    (tmp_path / "bad.json").write_text(json.dumps(bad), encoding="utf-8")
    monkeypatch.setattr(dp, "POLICY_PATH", tmp_path / "bad.json")
    out = R.call_tool("discover_indicators", {"query": "populatie pe judete"})
    assert out["status"] == "error" and out["reason"] == "execution_failed" and out["data"] == {}
