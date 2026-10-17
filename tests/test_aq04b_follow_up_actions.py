"""AQ-04B: follow-up actions are concrete, validated and never choose for the user.

Synthetic corpus, a test concept catalogue and test notes through the real shared services.
Known values (2023; every series moves +10 a year from 2020 for the populations):

                       Cluj   Iași   Mun. București
  POPK_judete           730    830    1930      resident, 1 January
  POPD_judete           710    810    1910      domicile
  STAYK_judete         2190   3320    9650      stays = 3 / 4 / 5 times the population
                                              (+ Arad 130: stays but no population)
  stays per resident    3.0    4.0     5.0      recipe tk_intensity = STAYK / POPK
  WAGEK_judete         5003   5103    5203     (+ Bihor 5303)
  SERK_judete (2018+)   105    115     125     in 2023: 100 + 10 * area + (year - 2018)

Test notes: SERK breaks between 2021 and 2022 (every area) and between 2019 and 2020 (Iași
only); a private break and a non-break note are never surfaced. WAGEK has no note at all: its
continuity is UNKNOWN, which is not reported as stable.
"""
import copy
import json

import pytest

from app.services import concept_search as cs
from app.services import dataset_notes, dataset_search, recipes
from app.services.tools import contract as C
from app.services.tools import discovery
from app.services.tools import recipe as recipe_tool
from app.services.tools import registry as R
from at01_fixtures import add_dataset, add_search_columns, call, make_env
from test_at01_changes import time_dim, unit_dim
from test_at01_discovery import concept, real  # noqa: F401 — real: the pinned-generation probe fixture
from test_at01_recipes_links import install_recipes, make_recipe

CTY = ["Cluj", "Iași", "Municipiul București"]
REGIONS = ["Nord-Vest", "Sud"]
YEARS = ("2020", "2021", "2022", "2023", "2024")
BASE = {"Cluj": 700.0, "Iași": 800.0, "Municipiul București": 1900.0}
RATIO = {"Cluj": 3.0, "Iași": 4.0, "Municipiul București": 5.0}
SEX = [("Masculin", dict(gender="M")), ("Feminin", dict(gender="F"))]


def area_dim(names, level="county", col="REF_AREA"):
    return (col, "Entitati", "geo", [(n, dict(geo_level=level, geo_name_clean=n)) for n in names])


def pop(a, y, shift=0.0):
    return BASE[a] + shift + 10.0 * (int(y) - 2020)


def _build(corpus):
    def counted(code, name, names, rows, unit="Numar persoane", ys=YEARS, **kw):
        add_dataset(corpus, code, [area_dim(names), time_dim(list(ys)), unit_dim(unit)], rows, name=name, **kw)

    counted("POPK_judete", "Populatia rezidenta test", CTY, [(a, y, "Numar persoane", pop(a, y)) for a in CTY for y in YEARS])
    add_dataset(corpus, "POPK_regiuni", [area_dim(REGIONS, "region"), time_dim(list(YEARS)), unit_dim("Numar persoane")],
                [(r, y, "Numar persoane", 2500.0 + 10 * i + (int(y) - 2020)) for i, r in enumerate(REGIONS) for y in YEARS],
                name="Populatia rezidenta test regiuni")
    counted("POPD_judete", "Populatia dupa domiciliu test", CTY, [(a, y, "Numar persoane", pop(a, y, -20)) for a in CTY for y in YEARS])
    stays = [(a, y, "Numar", RATIO[a] * pop(a, y)) for a in CTY for y in YEARS] \
        + [("Arad", y, "Numar", 100.0 + 10.0 * (int(y) - 2020)) for y in YEARS]       # Arad: no population
    counted("STAYK_judete", "Innoptari test", CTY + ["Arad"], stays, unit="Numar")
    counted("EARNK_judete", "Castig numaratoare test", CTY, [(a, y, "Numar", 10.0 * RATIO[a]) for a in CTY for y in YEARS], unit="Numar")
    for code, name, shift in (("ENETK_judete", "Castig net test", 0.0), ("EGROSSK_judete", "Castig brut test", 2.0),
                              ("REGK_judete", "Somaj inregistrat test", 1.0)):
        add_dataset(corpus, code, [area_dim(CTY), ("SEX", "Sexe", "gender", SEX), time_dim(list(YEARS))],
                    [(a, s, y, 5.0 + i + shift) for i, a in enumerate(CTY) for s, _ in SEX for y in YEARS],
                    unit_type="percentage", name=name)
    add_dataset(corpus, "ILOK_national", [area_dim(["Romania"], "national"), time_dim(list(YEARS))],
                [("Romania", y, 5.5) for y in YEARS], unit_type="percentage", name="Somaj BIM test")
    wage_areas = CTY + ["Bihor"]
    add_dataset(corpus, "WAGEK_judete", [area_dim(wage_areas), time_dim(list(YEARS))],
                [(a, y, 5000.0 + 100 * i + (int(y) - 2020)) for i, a in enumerate(wage_areas) for y in YEARS],
                name="Salariu test judete")
    ser_years = [str(y) for y in range(2018, 2025)]
    add_dataset(corpus, "SERK_judete", [area_dim(CTY), time_dim(ser_years)],
                [(a, y, 100.0 + 10 * i + (int(y) - 2018)) for i, a in enumerate(CTY) for y in ser_years],
                name="Indicator cu ruptura test")
    add_search_columns(corpus)      # datasets cannot be added after these


CONCEPTS = {"about": "test", "version": 1, "reviewed": "test", "concepts": [
    concept("res_pop", "Populatia rezidenta test", ["populatia rezidenta"],
            variants={"county": "POPK_judete", "region": "POPK_regiuni"}, generic=["populatia", "populatie"],
            generic_en=["population"], alternatives=["dom_pop"]),
    concept("dom_pop", "Populatia dupa domiciliu test", ["populatia dupa domiciliu"],
            variants={"county": "POPD_judete"}, alternatives=["res_pop"]),
    concept("stays", "Innoptari test", ["innoptari testate"], variants={"county": "STAYK_judete"},
            generic=["turism"], alternatives=["intens"]),
    concept("intens", "Intensitate test", ["intensitate testata"], recipe="tk_intensity", alternatives=["stays"]),
    concept("earn_net", "Castig net test", ["castigul net"], variants={"county": "ENETK_judete"},
            generic=["castigul"], alternatives=["earn_gross"], total_recipe="earn_total"),
    concept("earn_gross", "Castig brut test", ["castigul brut"], variants={"county": "EGROSSK_judete"},
            alternatives=["earn_net"]),
    concept("unemp_reg", "Somaj inregistrat test", ["somaj inregistrat"], variants={"county": "REGK_judete"},
            generic=["somaj"], alternatives=["unemp_ilo"]),
    concept("unemp_ilo", "Somaj BIM test", ["somaj bim"], variants={"national": "ILOK_national"},
            alternatives=["unemp_reg"]),
    concept("wage", "Salariu test", ["salariul testat"], variants={"county": "WAGEK_judete"},
            generic=["salariul"], alternatives=["ser"]),
    concept("ser", "Indicator cu ruptura test", ["indicator cu ruptura"], variants={"county": "SERK_judete"},
            alternatives=["wage"]),
]}

NOTES = [
    {"id": "SERK-break", "codes": ["SERK"], "kind": "series_break", "public": True,
     "text": {"ro": "Seria SERK se rupe între 2021 și 2022 (test).", "en": "SERK breaks between 2021 and 2022 (test)."},
     "data": {"between": ["2021", "2022"]}},
    {"id": "SERK-iasi", "codes": ["SERK"], "kind": "series_break", "public": True,
     "text": {"ro": "Iași are o altă ruptură (test).", "en": "Iasi has its own break (test)."},
     "data": {"between": ["2019", "2020"], "areas": ["Iași"]}},
    {"id": "SERK-private", "codes": ["SERK"], "kind": "series_break", "public": False,
     "text": {"ro": "intern", "en": "internal"}, "data": {"between": ["2020", "2023"]}},
    {"id": "SERK-def", "codes": ["SERK"], "kind": "definition", "public": True,
     "text": {"ro": "o definiție", "en": "a definition"}},
]


def _setup(tmp_path, monkeypatch):
    env = make_env(tmp_path, monkeypatch, build=_build)
    (tmp_path / "concepts.json").write_text(json.dumps(CONCEPTS), encoding="utf-8")
    monkeypatch.setattr(cs, "CONCEPTS_PATH", tmp_path / "concepts.json")
    install_recipes(tmp_path, monkeypatch, make_recipe("tk_intensity", "STAYK_judete", "POPK_judete"),
                    make_recipe("earn_total", "EARNK_judete", "POPK_judete"))
    monkeypatch.setattr(dataset_search, "SEARCH_DB_PATH", tmp_path / "no-fts.duckdb")
    monkeypatch.setattr(dataset_notes, "load", lambda path=None: NOTES)
    dataset_search._reset_for_tests()
    return env


@pytest.fixture
def env(tmp_path, monkeypatch):
    yield _setup(tmp_path, monkeypatch)
    monkeypatch.undo()
    dataset_search._reset_for_tests()


def disc(query, lang="ro", **kw):
    return call("discover_indicators", query=query, lang=lang, **kw)


def card(out, cid):
    return next(c for c in out["data"]["concepts"] if c["id"] == cid)


def cand(c, key):
    return next(x for x in c["candidates"] if key in (x.get("dataset"), x.get("recipe")))


def choice(out, cid):
    return next(c for c in out["data"]["choices"] if c["id"] == cid)


def codes(items):
    return [i["code"] for i in items]


def run(nc):
    out = R.call_tool(nc["tool"], nc["arguments"])
    R.validate_result(nc["tool"], out)
    return out


def row(out, area, period=None):
    """The (area, period, value) row of a query result."""
    cols = out["data"]["columns"]
    return next(r for r in out["data"]["rows"] if r[cols.index("REF_AREA")] == area
                and (period is None or r[cols.index("TIME_PERIOD")] == period))


# ====================================================================== the walk

ERRORS = {"invalid_input", "unknown_tool", "unknown_dataset", "unknown_column", "execution_failed"}
OUTCOMES = {"ok", "partial", "needs_clarification", "unavailable"}
CALL_KEYS = ("next_call", "lookup", "area_lookup", "action")


def advertised(obj):
    """Every call a result advertises, wherever it sits."""
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k in CALL_KEYS and isinstance(v, dict) and "tool" in v:
                yield v
            else:
                yield from advertised(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from advertised(v)


def walk(out, depth=2, seen=None):
    """Validate every advertised call under the registry schema and execute it: it must run or
    end in an intentional refusal/clarification, never a schema or system error. Follows
    discover_indicators calls `depth` levels down. Returns [(tool, status, reason)]."""
    seen = set() if seen is None else seen
    calls = list(advertised(out["data"])) + [{"tool": r["tool"], "arguments": r["arguments"]}
                                             for r in out["recovery"] if r["kind"] == "tool_call"]
    done = []
    for c in calls:
        key = json.dumps(c, sort_keys=True)
        if key in seen:
            continue
        seen.add(key)
        assert R.precheck(c["tool"], c["arguments"]) is None, c       # the registry's own validator
        res = run(c)
        assert res["status"] in OUTCOMES and res["reason"] not in ERRORS, (c, res["status"], res["reason"], res["message"])
        assert res["tool"] == c["tool"]
        done.append((c["tool"], res["status"], res["reason"]))
        if c["tool"] == "discover_indicators" and depth:
            done += walk(res, depth - 1, seen)
    return done


QUESTIONS = [
    ("populatie", "ro"), ("population", "en"), ("population of Cluj in 2023", "en"), ("populatie Cluj 2019", "ro"),
    ("populatie Cluj-Napoca", "ro"), ("Cluj-Napoca populatia rezidenta 2023", "ro"),
    ("top 3 judete dupa populatia rezidenta", "ro"), ("turism", "ro"), ("turism Cluj 2023", "ro"),
    ("turism 2030", "ro"), ("turism feminin Cluj 2023", "ro"), ("castigul Cluj 2023", "ro"),
    ("castigul feminin Cluj 2023", "ro"),
    ("earnings", "en"), ("somaj", "ro"), ("somaj Cluj 2023", "ro"), ("salariul Cluj", "ro"),
    ("salariul Cluj 2030", "ro"), ("intensitate testata Cluj 2023", "ro"), ("intensitate testata Bihor 2023", "ro"),
    ("intensitate testata 2030", "ro"), ("indicator cu ruptura Iasi", "ro"), ("indicator cu ruptura 2030", "ro"),
    ("salariul testat Bihor 2023", "ro"),
]


def test_every_advertised_call_validates_and_executes(env):
    """The acceptance walk: choices, restatements, actions, lookups, candidates and recoveries
    of RO and EN questions across every branch (ambiguity, place, period, recipe, partial)."""
    tools, branches = set(), set()
    for q, lang in QUESTIONS:
        out = disc(q, lang)
        done = walk(out)
        tools |= {t for t, _, _ in done}
        for ch in out["data"]["choices"]:
            branches.add((out["reason"], ch["action_status"]))
        assert C.size(out) <= C.MAX_RESULT_BYTES, q
    # not vacuous: every action tool was executed and every action state was met
    assert {"discover_indicators", "describe_dataset", "find_dimension_values", "query_data", "run_recipe",
            "rank_entities"} <= tools
    assert {"ready", "needs_clarification", "unavailable"} == {s for _, s in branches}


# ====================================================================== choices: actions

def test_a_definition_choice_carries_the_validated_call_that_card_would_make(env):
    out = disc("population of Cluj in 2023", "en")
    assert out["status"] == "needs_clarification" and out["reason"] == "ambiguous_definition"
    assert [c["id"] for c in out["data"]["choices"]] == ["res_pop", "dom_pop"]
    for ch in out["data"]["choices"]:
        # the restatement stays a plain discover call (unchanged contract) ...
        assert ch["next_call"]["tool"] == "discover_indicators"
        # ... and the action is what that restated question's own card calls next
        picked = run(ch["next_call"])
        assert picked["status"] == "ok" and ch["action_status"] == "ready"
        assert card(picked, ch["id"])["next_call"] == ch["action"]
        assert ch["action"]["tool"] == "query_data"
        assert ch["action"]["arguments"]["filters"] == {"REF_AREA": ["Cluj"], "TIME_PERIOD": ["2023"]}
        assert ch["action_notes"] == [] and ch["recipe"] is None
    # the actions are the two definitions' own sources, executed to their known values
    res, dom = (run(choice(out, i)["action"]) for i in ("res_pop", "dom_pop"))
    assert (row(res, "Cluj", "2023")[-1], row(dom, "Cluj", "2023")[-1]) == (730.0, 710.0)
    assert choice(out, "res_pop")["dataset"] == "POPK_judete" and choice(out, "dom_pop")["dataset"] == "POPD_judete"


def test_a_choice_never_runs_before_the_user_picks(env):
    """The clarification itself has no headline: cards and candidates carry no call, the message
    says to ask first, and the actions live only on the choices."""
    out = disc("population of Cluj in 2023", "en")
    assert all(c["next_call"] is None and c["requires_choice"] for c in out["data"]["concepts"])
    assert all(cd["next_call"] is None and not cd["preferred"] for c in out["data"]["concepts"] for cd in c["candidates"])
    assert "ask the user to pick" in out["message"] and "Only after they have picked" in out["message"]
    # recovery still restates (a discover call), it does not run a definition for the user
    assert out["recovery"] and all(r["tool"] == "discover_indicators" for r in out["recovery"])


def test_choice_recipe_agrees_with_the_selected_concepts_total_route(env):
    """earn_net has no recipe of its own but a reviewed total route: its choice used to say
    recipe None while the card (and its call) used the route."""
    out = disc("castigul Cluj 2023")
    net, gross = choice(out, "earn_net"), choice(out, "earn_gross")
    assert net["recipe"] == "earn_total" and net["action"] == {"tool": "run_recipe", "arguments": {
        "recipe": "earn_total", "lang": "ro", "year": "2023", "areas": ["Cluj"]}}
    assert net["action"]["arguments"]["recipe"] == net["recipe"]
    picked = run(net["next_call"])
    assert card(picked, "earn_net")["recipe"] == net["recipe"] == "earn_total"
    # the other definition has no route: no recipe is invented for it, and its rate is not summed
    assert gross["recipe"] is None and gross["action"]["tool"] == "describe_dataset"
    assert gross["action"]["arguments"]["dataset"] == "EGROSSK_judete"
    # the alternatives listed on a card use the same rule
    alt = next(a for a in card(disc("castigul brut Cluj 2023"), "earn_gross")["alternatives"] if a["id"] == "earn_net")
    assert alt["recipe"] == "earn_total"
    # the recipe call runs: 10 * 3 / 730 per area is not what it is, the fixture ratio is 30 / 730
    res = run(net["action"])
    assert res["status"] == "ok" and res["data"]["rows"][0]["label"] == "Cluj"
    assert res["data"]["rows"][0]["value"] == pytest.approx(30.0 / 730.0)


def test_a_recipe_concept_choice_runs_the_recipe(env):
    out = disc("turism Cluj 2023")
    intens, stays = choice(out, "intens"), choice(out, "stays")
    assert intens["recipe"] == "tk_intensity" and intens["dataset"] is None
    assert intens["action"] == {"tool": "run_recipe", "arguments": {
        "recipe": "tk_intensity", "lang": "ro", "year": "2023", "areas": ["Cluj"]}}
    assert stays["recipe"] is None and stays["action"]["tool"] == "query_data"
    res = run(intens["action"])
    assert res["status"] == "ok" and res["data"]["rows"][0]["value"] == pytest.approx(3.0)       # 2190 / 730
    assert row(run(stays["action"]), "Cluj", "2023")[-1] == 2190.0


def test_an_unavailable_place_stays_a_clarification_and_is_not_widened(env):
    """The ILO series has no county data: its action must not silently become the national
    figure for a question about Cluj."""
    out = disc("somaj Cluj 2023")
    reg, ilo = choice(out, "unemp_reg"), choice(out, "unemp_ilo")
    assert ilo["action"] is None and ilo["action_status"] == "needs_clarification"
    assert [n["code"] for n in ilo["action_notes"]] == ["place_level_unavailable", "level_differs"]
    assert ilo["next_call"]["tool"] == "discover_indicators"                  # the restatement remains
    assert reg["action_status"] == "ready" and reg["action"]["tool"] == "describe_dataset"   # a rate is not summed
    assert reg["action"]["arguments"]["dataset"] == "REGK_judete"
    # without a place the national series is the answer and the action is concrete
    nat = choice(disc("somaj"), "unemp_ilo")
    assert nat["action_status"] == "ready" and nat["action"]["tool"] == "query_data"
    assert nat["action"]["arguments"]["dataset"] == "ILOK_national" and nat["action_notes"] == []
    series = run(nat["action"])["data"]
    assert series["columns"] == ["TIME_PERIOD", "OBS_VALUE"] and ["2023", 5.5] in series["rows"]


def test_a_second_ambiguity_keeps_the_restatement_as_the_only_call(env):
    """Generic word AND a city: choosing the definition still needs the county/city question."""
    out = disc("populatie Cluj-Napoca")
    assert out["reason"] == "ambiguous_definition"
    for ch in out["data"]["choices"]:
        assert ch["action"] is None and ch["action_status"] == "needs_clarification"
        assert [n["code"] for n in ch["action_notes"]] == ["ambiguous_place"]
        picked = run(ch["next_call"])
        assert picked["status"] == "needs_clarification" and picked["reason"] == "ambiguous_place"


def test_place_choices_are_concrete_after_the_place_is_chosen(env):
    out = disc("Cluj-Napoca populatia rezidenta 2023")
    assert out["reason"] == "ambiguous_place" and card(out, "res_pop")["next_call"] is None
    county, every = choice(out, "county"), choice(out, "all_counties")
    assert county["action_status"] == every["action_status"] == "ready"
    assert county["action"]["arguments"]["filters"] == {"REF_AREA": ["Cluj"], "TIME_PERIOD": ["2023"]}
    assert every["action"]["arguments"]["filters"] == {"TIME_PERIOD": ["2023"]}
    assert every["action"]["arguments"]["group_by"] == ["REF_AREA", "TIME_PERIOD"]
    assert row(run(county["action"]), "Cluj", "2023")[-1] == 730.0
    assert {r[0]: r[-1] for r in run(every["action"])["data"]["rows"]} == {"Cluj": 730.0, "Iași": 830.0,
                                                                          "Municipiul București": 1930.0}
    assert county["next_call"]["tool"] == every["next_call"]["tool"] == "discover_indicators"
    # a recipe concept: the county choice runs the recipe for the county, not for the city
    rec = disc("intensitate testata Cluj-Napoca 2023")
    assert rec["reason"] == "ambiguous_place"
    cc = choice(rec, "county")
    assert cc["recipe"] == "tk_intensity" and cc["action"]["arguments"] == {
        "recipe": "tk_intensity", "lang": "ro", "year": "2023", "areas": ["Cluj"]}


def test_ranking_questions_get_the_ranking_call_as_the_action(env):
    out = disc("top 2 judete dupa populatia rezidenta")
    nc = card(out, "res_pop")["next_call"]
    assert nc["tool"] == "rank_entities" and nc["arguments"]["top_k"] == 2
    res = run(nc)
    assert [r["entity"]["REF_AREA"] for r in res["data"]["rows"]] == ["Municipiul București", "Iași"]
    gen = disc("top 2 judete dupa populatia")                  # generic word: the choices carry it
    assert gen["reason"] == "ambiguous_definition"
    assert {c["action"]["tool"] for c in gen["data"]["choices"]} == {"rank_entities"}


def test_an_unapplied_constraint_withholds_the_data_call_from_the_action_too(env):
    """AQ-04A: a constraint discovery cannot apply never hides behind a data call. The action
    is describe_dataset (explicit values can be filtered there) or nothing, never the recipe."""
    out = disc("castigul feminin Cluj 2023")
    assert out["data"]["interpretation"]["unapplied_constraints"][0]["kind"] == "sex"
    for cid, dataset in (("earn_net", "ENETK_judete"), ("earn_gross", "EGROSSK_judete")):
        ch = choice(out, cid)
        assert ch["action"] == {"tool": "describe_dataset", "arguments": {"dataset": dataset, "lang": "ro"}}
        assert ch["action_status"] == "ready" and [n["code"] for n in ch["action_notes"]] == ["constraint_not_applied"]
    assert choice(out, "earn_net")["recipe"] == "earn_total"          # the route exists but cannot take the filter
    out = disc("turism feminin Cluj 2023")
    stays, intens = choice(out, "stays"), choice(out, "intens")
    assert stays["action"]["tool"] == "describe_dataset" and stays["action_status"] == "ready"
    assert intens["action"] is None and intens["action_status"] == "unavailable"
    assert [n["code"] for n in intens["action_notes"]] == ["constraint_not_applied", "no_call"]
    for ch in out["data"]["choices"]:
        assert not ch["action"] or ch["action"]["tool"] not in ("query_data", "rank_entities", "run_recipe")


def test_choices_without_a_specific_wording_offer_no_call(env, monkeypatch):
    monkeypatch.setattr(discovery, "_specific_query", lambda *a, **k: None)
    out = disc("castigul Cluj 2023")
    for ch in out["data"]["choices"]:
        assert ch["next_call"] is None and ch["action"] is None
        assert [n["code"] for n in ch["action_notes"]] == ["no_specific_wording"]


def test_choice_resolution_is_one_level_deep(env, monkeypatch):
    """A choice restates the question once; the restated question's own choices are not
    resolved again (that would multiply the work of every clarification)."""
    seen, orig = [], discovery.discover_indicators

    def spy(args, ctx):
        seen.append(args.query)
        return orig(args, ctx)
    monkeypatch.setattr(discovery, "discover_indicators", spy)
    out = disc("populatie Cluj-Napoca")                  # definition choices, each leading to place choices
    assert len(out["data"]["choices"]) == 2 and len(seen) == 3          # the call itself + one per choice
    seen.clear()
    out = disc("Cluj-Napoca populatia rezidenta 2023")
    assert len(seen) == 3                                # + county and all counties


def test_choices_stay_within_the_byte_budget_and_do_not_list_options(env):
    for q in ("castigul Cluj 2023", "turism", "somaj Cluj 2023", "populatie Cluj-Napoca"):
        out = disc(q, limit=10)
        assert C.size(out) <= discovery.FIT_BYTES, q
        for ch in out["data"]["choices"]:
            assert len(ch["action_notes"]) <= discovery.MAX_ACTION_NOTES
            assert all(len(n["message"]) <= discovery.ACTION_NOTE_CHARS + 2 for n in ch["action_notes"])
            assert set(ch) <= {"id", "label", "description", "dataset", "coverage", "recipe", "next_call",
                               "action", "action_status", "action_notes"}


def test_trimming_cuts_choice_prose_not_codes_and_terminates(env, monkeypatch):
    monkeypatch.setattr(discovery, "FIT_BYTES", 200)             # nothing fits: every cut is taken
    out = disc("castigul feminin Cluj 2023")
    assert out["status"] == "needs_clarification" and "response_shortened" in codes(out["warnings"])
    for ch in out["data"]["choices"]:
        assert ch["action_notes"] and all(n["code"] and len(n["message"]) <= 90 for n in ch["action_notes"])
        assert ch["action_status"] in ("unavailable", "ready")


# ====================================================================== recipe areas

def test_recipe_candidates_carry_an_actionable_area_lookup_on_exact_source_labels(env):
    out = disc("intensitate testata Cluj 2023")
    c = card(out, "intens")
    cd = cand(c, "tk_intensity")
    # ratio recipe: areas are matched against the denominator's labels
    assert recipe_tool.area_dataset("tk_intensity") == "POPK_judete"
    assert cd["area_lookup"] == {"tool": "find_dimension_values", "arguments": {
        "dataset": "POPK_judete", "column": "REF_AREA", "limit": 20, "query": "Cluj"}}
    assert [v["value"] for v in run(cd["area_lookup"])["data"]["values"]] == ["Cluj"]
    assert c["next_call"]["arguments"]["areas"] == ["Cluj"]               # the exact label, run as such
    no_place = cand(card(disc("intensitate testata"), "intens"), "tk_intensity")
    assert "query" not in no_place["area_lookup"]["arguments"]            # lists the labels
    assert {v["value"] for v in run(no_place["area_lookup"])["data"]["values"]} == set(CTY)


def test_a_place_the_recipe_source_lacks_gets_a_lookup_not_a_doomed_run(env):
    out = disc("intensitate testata Bihor 2023")          # Bihor is a county, but not in POPK_judete
    c = card(out, "intens")
    cd = cand(c, "tk_intensity")
    assert "place_not_in_dataset" in codes(cd["notes"]) and out["status"] == "ok"
    assert c["next_call"] == cd["area_lookup"] == {"tool": "find_dimension_values", "arguments": {
        "dataset": "POPK_judete", "column": "REF_AREA", "limit": 20, "query": "Bihor"}}
    res = run(c["next_call"])
    assert res["data"]["total"] == 0 and "Nicio valoare din REF_AREA nu conține 'Bihor'" in res["message"]
    # nothing similar was substituted: the recipe itself, asked for Bihor, excludes it with its reason
    ran = call("run_recipe", recipe="tk_intensity", areas=["Bihor"], year="2023")
    assert ran["status"] == "unavailable" and ran["data"]["rows"] == []
    assert ran["data"]["exclusion_counts"] == {"not_in_data": 1}
    assert [r["tool"] for r in ran["recovery"]] == ["run_recipe", "find_dimension_values"]    # the old step first
    # one place found and one not: the run goes ahead for the one it has, the other is reported
    two = disc("intensitate testata Cluj Bihor 2023")
    nc = card(two, "intens")["next_call"]
    assert nc["tool"] == "run_recipe" and nc["arguments"]["areas"] == ["Cluj", "Bihor"]
    assert "place_not_in_dataset" in codes(cand(card(two, "intens"), "tk_intensity")["notes"])
    part = run(nc)
    assert part["status"] == "partial" and [r["label"] for r in part["data"]["rows"]] == ["Cluj"]
    assert part["data"]["exclusion_counts"] == {"not_in_data": 1}


@pytest.mark.parametrize("lang,fragment", [("en", "Look up the exact label"), ("ro", "Caută eticheta exactă")])
def test_run_recipe_offers_the_label_lookup_for_a_missing_area_alias(env, lang, fragment):
    res = call("run_recipe", recipe="tk_intensity", areas=["Cluj-Napoca", "Cluj"], year="2023", lang=lang)
    assert res["status"] == "partial" and [r["label"] for r in res["data"]["rows"]] == ["Cluj"]
    assert res["data"]["rows"][0]["value"] == pytest.approx(3.0)
    assert [e["label"] for e in res["data"]["excluded"]] == ["Cluj-Napoca"]      # as the caller wrote it
    rec = res["recovery"]
    assert len(rec) == 1 and fragment in rec[0]["message"]
    assert rec[0]["arguments"] == {"dataset": "POPK_judete", "column": "REF_AREA", "query": "Cluj", "limit": 20}
    assert [v["value"] for v in run({"tool": rec[0]["tool"], "arguments": rec[0]["arguments"]})["data"]["values"]] == ["Cluj"]


def test_missing_area_lookups_are_bounded_and_keep_the_run_all_areas_step(env):
    res = call("run_recipe", recipe="tk_intensity", areas=["Alfa", "Beta", "Gama"], year="2023")
    assert res["status"] == "unavailable" and res["data"]["exclusion_counts"] == {"not_in_data": 3}
    tools = [r["tool"] for r in res["recovery"]]
    assert tools == ["run_recipe", "find_dimension_values", "find_dimension_values"]       # at most 3
    assert res["recovery"][0]["arguments"] == {"recipe": "tk_intensity", "year": "2023", "lang": "ro"}
    assert [r["arguments"]["query"] for r in res["recovery"][1:]] == ["Alfa", "Beta"]


def test_a_partial_source_is_reported_without_a_label_lookup(env):
    """Arad has stays but no population: excluded with its reason, nothing divided by zero."""
    res = call("run_recipe", recipe="tk_intensity", year="2023")
    assert res["status"] == "partial" and res["reason"] == "incomplete_domain"
    assert {r["label"]: r["value"] for r in res["data"]["rows"]} == {
        "Cluj": pytest.approx(3.0), "Iași": pytest.approx(4.0), "Municipiul București": pytest.approx(5.0)}
    assert res["data"]["exclusion_counts"] == {"not_in_denominator": 1}
    assert [e["label"] for e in res["data"]["excluded"]] == ["Arad"]
    assert res["recovery"] == []                  # the label exists in the numerator: a lookup would not help
    only = call("run_recipe", recipe="tk_intensity", areas=["Arad"], year="2023")
    assert only["status"] == "unavailable" and only["data"]["exclusion_counts"] == {"not_in_denominator": 1}


def test_recipe_year_outside_the_sources_is_looked_up_never_swapped(env):
    out = disc("intensitate testata Cluj 2030")
    c = card(out, "intens")
    assert "period_unavailable" in codes(c["notes"])
    assert c["next_call"]["tool"] == "find_dimension_values" and c["next_call"]["arguments"]["column"] == "TIME_PERIOD"
    assert c["next_call"]["arguments"]["dataset"] == "STAYK_judete"
    assert "2030" not in json.dumps(c["next_call"])
    assert run(c["next_call"])["data"]["period_bounds"]["last"] == "2024"
    refused = call("run_recipe", recipe="tk_intensity", areas=["Cluj"], year="2030")
    assert refused["reason"] == "period_unavailable" and refused["data"]["years_available"][-1] == "2024"
    assert refused["recovery"][0]["arguments"]["year"] == "2024"


def test_area_dataset_follows_how_each_recipe_kind_builds_its_universe(monkeypatch):
    fake = {"r": {"kind": "ratio", "numerator": {"dataset": "N"}, "denominator": {"dataset": "D"}},
            "p": {"kind": "ratio", "numerator": {"dataset": "N"}, "denominator": {"dataset": "D"},
                  "published": {"matrix": "M"}},
            "w": {"kind": "weighted_mean", "values": {"dataset": "V"}, "weights": {"dataset": "W"}},
            "c": {"kind": "rate_from_counts", "rates": {"dataset": "R"}, "counts": {"dataset": "K"}}}
    monkeypatch.setattr(recipes, "load_recipes", lambda: fake)
    assert [recipe_tool.area_dataset(k) for k in ("r", "p", "w", "c", "none")] == ["D", "N", "V", "R", None]


def test_lookup_query_only_chooses_what_to_search_for():
    labels = ["Cluj", "Iași", "Municipiul București"]
    q = recipe_tool.lookup_query
    assert q("Cluj-Napoca", labels) == "Cluj" and q("Județul Cluj", labels) == "Cluj"
    assert q("Mun. Bucuresti", labels) == "Bucuresti"                    # accent-insensitive, like the lookup
    assert q("Bihor", labels) == "Bihor" and q("Cluj-Napoca") == "Cluj-Napoca"      # nothing contains it / no labels
    assert q("  Satu   Mare ") == "Satu Mare" and len(q("x" * 500)) == 200


# ====================================================================== series breaks

def spanning(**selection):
    return call("query_data", dataset="SERK_judete", group_by=["REF_AREA", "TIME_PERIOD"], **selection)


def breaks(out):
    return [(w["subject"], w["message"]) for w in out["warnings"] if w["code"] == "series_break"]


def test_query_warns_when_the_selected_periods_straddle_a_recorded_break(env):
    out = spanning(filters={"REF_AREA": ["Cluj"], "TIME_PERIOD": ["2020", "2021", "2022", "2023"]})
    assert breaks(out) == [("SERK-break", "Seria SERK se rupe între 2021 și 2022 (test).")]
    assert out["provenance"]["series_breaks"] == [{"id": "SERK-break", "dataset": "SERK_judete",
                                                   "between": ["2021", "2022"]}]
    assert row(out, "Cluj", "2023")[-1] == 105.0
    # the break is not hidden in the source notes only: they still list the public notes of the dataset
    assert {n["id"] for n in out["provenance"]["sources"][0]["notes"]} == {"SERK-break", "SERK-iasi", "SERK-def"}
    # only one side of the boundary, or exactly on it: nothing is claimed
    for ys in (["2022", "2023"], ["2018", "2021"], ["2021"], ["2023"]):
        o = spanning(filters={"REF_AREA": ["Cluj"], "TIME_PERIOD": ys})
        assert breaks(o) == [] and "series_breaks" not in o["provenance"], ys
    # no period filter: the whole series is selected
    assert [s for s, _ in breaks(spanning(filters={"REF_AREA": ["Cluj"]}))] == ["SERK-break"]


def test_an_area_specific_break_only_affects_that_area(env):
    both = {"TIME_PERIOD": ["2019", "2020", "2021"]}
    assert breaks(spanning(filters={"REF_AREA": ["Cluj"], **both})) == []
    assert [s for s, _ in breaks(spanning(filters={"REF_AREA": ["Iași"], **both}))] == ["SERK-iasi"]
    assert [s for s, _ in breaks(spanning(filters={**both}))] == ["SERK-iasi"]          # every area
    allp = [s for s, _ in breaks(spanning(filters={"REF_AREA": ["Iași", "Cluj"]}))]
    assert allp == ["SERK-break", "SERK-iasi"]        # file order, once each; private and non-break notes never


def test_unknown_continuity_is_not_reported_as_stable(env):
    out = call("query_data", dataset="WAGEK_judete", group_by=["REF_AREA", "TIME_PERIOD"], filters={"REF_AREA": ["Cluj"]})
    assert out["status"] == "ok" and row(out, "Cluj", "2023")[-1] == 5003.0
    assert breaks(out) == [] and "series_breaks" not in out["provenance"]
    text = json.dumps(out, ensure_ascii=False).lower()
    assert "stable" not in text and "continuous" not in text
    d = call("describe_dataset", dataset="WAGEK_judete")
    assert d["data"]["series_breaks"] == [] and breaks(d) == []                # "none recorded", nothing more


def test_the_break_text_follows_the_language(env):
    out = spanning(filters={"REF_AREA": ["Cluj"]}, lang="en")
    assert breaks(out) == [("SERK-break", "SERK breaks between 2021 and 2022 (test).")]


def test_other_tools_keep_their_own_single_period_and_interval_handling(env):
    ranked = call("rank_entities", dataset="SERK_judete", entity_columns=["REF_AREA"], year="2023")
    assert breaks(ranked) == [] and "series_breaks" not in ranked["provenance"]            # one period
    cmp_ = call("compare_periods", dataset="SERK_judete", entity_columns=["REF_AREA"],
                intervals=[{"from": "2020", "to": "2023"}], lang="en")
    own = [(w["subject"], w["message"]) for w in cmp_["warnings"] if w["code"] == "series_break"]
    assert [s for s, _ in own].count("SERK-break") == 1                       # raised once, by that tool
    assert own[0][1].startswith("Inside the compared interval 2020→2023") and "series_breaks" not in cmp_["provenance"]


def test_describe_lists_breaks_inside_the_data_it_holds(env):
    d = call("describe_dataset", dataset="SERK_judete")
    assert [b["id"] for b in d["data"]["series_breaks"]] == ["SERK-break", "SERK-iasi"]
    assert d["data"]["series_breaks"][1] == {"id": "SERK-iasi", "dataset": "SERK_judete",
                                             "between": ["2019", "2020"], "areas": ["Iași"]}
    assert [s for s, _ in breaks(d)] == ["SERK-break", "SERK-iasi"]
    assert "private" not in json.dumps(d).lower().replace("serk-private", "")


def test_discovery_puts_the_breaks_of_the_selection_on_the_candidate_and_the_headline(env):
    out = disc("indicator cu ruptura Cluj")
    c = card(out, "ser")
    cd = cand(c, "SERK_judete")
    assert [b["id"] for b in cd["series_breaks"]] == ["SERK-break"]            # Iași's own break is not Cluj's
    assert [(n["code"], n["subject"]) for n in cd["notes"] if n["code"] == "series_break"] == [("series_break", "SERK-break")]
    assert [s for s, _ in breaks(out)] == ["SERK-break"]
    assert c["next_call"]["arguments"]["filters"] == {"REF_AREA": ["Cluj"]}
    iasi = card(disc("indicator cu ruptura Iasi"), "ser")
    assert [b["id"] for b in cand(iasi, "SERK_judete")["series_breaks"]] == ["SERK-break", "SERK-iasi"]
    # a pinned year is one period; an absent year selects nothing yet
    for q in ("indicator cu ruptura Cluj 2023", "indicator cu ruptura Cluj 2030"):
        o = disc(q)
        assert cand(card(o, "ser"), "SERK_judete")["series_breaks"] == [] and breaks(o) == [], q
    # a ranking is one year, whatever the data holds
    rk = disc("top 2 judete indicator cu ruptura")
    assert card(rk, "ser")["next_call"]["tool"] == "rank_entities"
    assert cand(card(rk, "ser"), "SERK_judete")["series_breaks"] == [] and breaks(rk) == []


def test_a_choice_carries_the_break_of_its_action_and_unknown_stays_unlabelled(env):
    out = disc("salariul Cluj")
    ser, wage = choice(out, "ser"), choice(out, "wage")
    assert ser["action"]["tool"] == "query_data" and ser["action"]["arguments"]["dataset"] == "SERK_judete"
    assert [(n["code"], n["subject"]) for n in ser["action_notes"]] == [("series_break", "SERK-break")]
    assert wage["action_notes"] == [] and wage["action"]["arguments"]["dataset"] == "WAGEK_judete"
    # the action runs and its own result carries the same break as a warning on that selection
    assert [s for s, _ in breaks(run(ser["action"]))] == ["SERK-break"]
    # a year that is not there: the action is the period lookup and the note says so
    gone = choice(disc("salariul Cluj 2030"), "ser")
    assert gone["action"]["tool"] == "find_dimension_values" and gone["action"]["arguments"]["column"] == "TIME_PERIOD"
    assert [n["code"] for n in gone["action_notes"]] == ["period_unavailable"]
    assert run(gone["action"])["data"]["period_bounds"] == {"first": "2018", "last": "2024", "periods_with_data": 7}


def test_series_breaks_helper_selection_rules():
    sb = dataset_notes.series_breaks
    notes = NOTES
    ids = lambda **kw: [b["id"] for b in sb("SERK_judete", notes=notes, **kw)]
    assert ids(periods=["2021", "2022"]) == ["SERK-break"]                 # both sides, edges included
    assert ids(periods=["2021-12", "2022-01"]) == ["SERK-break"]           # any period text with a year
    assert ids(periods=["Anul 2020", "Anul 2023"]) == ["SERK-break"]
    assert ids(periods=["2022", "2023"]) == [] and ids(periods=["2018", "2019"]) == []
    assert ids(periods=["2018", "2021"]) == ["SERK-iasi"]                  # across 2019/2020 only
    assert ids(span=("2018", "2024")) == ["SERK-break", "SERK-iasi"]
    assert ids(span=("2022", "2024")) == []
    assert ids() == ["SERK-break", "SERK-iasi"]                            # selection unknown: not ruled out
    assert ids(periods=["2019", "2023"], areas=["Cluj"]) == ["SERK-break"]
    assert ids(periods=["2019", "2023"], areas=["IASI"]) == ["SERK-break", "SERK-iasi"]   # accents and case
    assert ids(periods=["2019", "2023"], areas=[]) == ["SERK-break", "SERK-iasi"]
    assert sb("OTHER", notes=notes, span=("2018", "2024")) == [] and sb("SERK", notes=notes)[0]["dataset"] == "SERK"
    en = sb("SERK_judete", "en", notes=notes, span=("2018", "2024"))[1]
    assert en["text"] == "Iasi has its own break (test)." and en["areas"] == ["Iași"]
    bad = [{"id": "x", "codes": ["Z"], "kind": "series_break", "public": True, "text": {"ro": "t"}, "data": {}}]
    assert [b["between"] for b in sb("Z", notes=bad, span=("2000", "2001"))] == [None]       # unplaced: kept


# ====================================================================== the real generation

PINNED = "9b3e065d"


@pytest.mark.corpus
def test_corpus_choices_agree_with_their_cards_and_the_census_break_is_flagged(real):
    out = disc("salariu mediu Cluj 2023")
    net = choice(out, "net_earnings")
    assert net["recipe"] == "net_earnings_county" and net["action"] == {"tool": "run_recipe", "arguments": {
        "recipe": "net_earnings_county", "lang": "ro", "year": "2023", "areas": ["Cluj"]}}
    assert choice(out, "gross_earnings")["recipe"] is None
    assert card(run(net["next_call"]), "net_earnings")["next_call"] == net["action"]
    ilo = choice(disc("somaj Cluj 2019"), "ilo_unemployment_rate")
    assert ilo["action"] is None and ilo["action_notes"][0]["code"] == "place_level_unavailable"
    reg = choice(disc("somaj Cluj 2019"), "registered_unemployment_rate")
    assert reg["recipe"] == "registered_unemployment_county" == reg["action"]["arguments"]["recipe"]
    span = call("query_data", dataset="POP105A_judete_grupe", group_by=["REF_AREA", "TIME_PERIOD"],
                filters={"REF_AREA": ["Cluj"], "TIME_PERIOD": ["2020", "2021", "2022", "2023"]})
    assert [s for s, _ in breaks(span)] == ["POP105A-census-break"]
    assert span["provenance"]["series_breaks"][0]["between"] == ["2021", "2022"]
    after = call("query_data", dataset="POP105A_judete_grupe", group_by=["REF_AREA", "TIME_PERIOD"],
                 filters={"REF_AREA": ["Cluj"], "TIME_PERIOD": ["2022", "2023"]})
    assert breaks(after) == []


@pytest.mark.corpus
@pytest.mark.parametrize("q", ["somaj", "turism", "salariu mediu Cluj 2023", "populatie Cluj-Napoca",
                               "innoptari pe locuitor Cluj 2023", "rata somajului inregistrat Cluj 2019"])
def test_corpus_every_advertised_call_validates_and_executes(real, q):
    done = walk(disc(q), depth=1)
    assert done and all(s in OUTCOMES for _, s, _ in done)
