"""Discovery never drops a qualifier of the question: residence, a named locality, a currency.

Each is applied as an exact filter read from the candidate's own data file, offered as an exact value
lookup, or reported in `interpretation.unapplied_constraints` (with the `constraint_not_applied`
warning and no data call). A national question is never answered with regional rows when INS's
published national cell exists.

Part 1: the words (`intent`), no corpus. Part 2: the per-candidate logic on a synthetic corpus with the
production dataset codes. Part 3: the real corpus, pinned to generation f20fc32a (skipped otherwise).
"""
import pytest

from app.services import dataset_search
from app.services.tools import discovery
from app.services.tools import intent as I
from app.services.tools import registry as R
from at01_fixtures import add_dataset, add_search_columns, call, make_env
from test_aq04a_discovery_defaults import CTY, POP, YEARS, _series, area_dim, card, codes
from test_at01_changes import time_dim, unit_dim

PINNED = "f20fc32a"


def quals(query):
    return {q["kind"]: (q["value"], q["text"]) for q in I.interpret(query)["qualifiers"]}


# ============================================================ 1. the words

@pytest.mark.parametrize("query, value", [
    ("Rural resident population of Romania in 2023", "rural"),
    ("Populația rezidentă rurală a României în 2023", "rural"),
    ("urban population by county", "urban"),
    ("Populația din mediul urban", "urban"),
    ("population of rural areas", "rural"),
    ("populatia urbana 2020", "urban"),
])
def test_residence_is_read(query, value):
    assert quals(query)["residence"][0] == value


@pytest.mark.parametrize("query", [
    "urbanism permits in 2023", "Cluj county population", "autorizații de urbanism", "population of Romania",
])
def test_residence_has_no_false_positive(query):
    assert "residence" not in quals(query)


def test_rural_and_urban_together_is_not_one_value():
    assert quals("rural and urban population")["residence"][0] is None


@pytest.mark.parametrize("query, name", [
    ("Population by domicile of the city of Timișoara in 2023", "timisoara"),
    ("Populația după domiciliu a municipiului Timișoara în 2023", "timisoara"),
    ("population of the city of Cluj-Napoca in 2023", "cluj napoca"),
    ("populația orașului Târgu Mureș în 2022", "targu mures"),
    ("populația comunei Apahida", "apahida"),
    ("population of the town of Turda by sex", "turda"),
    ("population of the village of Rosia Montana, 2021", "rosia montana"),
    ("population of the municipality of Drobeta Turnu Severin", "drobeta turnu severin"),
    ("populația localității Florești din 2023", "floresti"),
])
def test_locality_is_read(query, name):
    assert quals(query)["locality"][0] == name


@pytest.mark.parametrize("query", [
    "Timiș county population in 2023", "populația județului Timiș", "population of Cluj", "population of Romania in 2023",
    "top 10 cities by population", "cele mai populate orașe", "the city was large",
])
def test_locality_has_no_false_positive(query):
    assert "locality" not in quals(query)


def test_a_singular_city_cue_does_not_start_the_city_ranking():
    assert not I.interpret("population of the city of Timișoara in 2023")["cities"]
    assert I.interpret("top 5 cities of Cluj by population")["cities"]
    assert "locality" not in quals("top 3 orase din orasul Cluj dupa populatie")      # the ranking handles its county


@pytest.mark.parametrize("query, value", [
    ("GDP per capita in euros in Romania in 2022", "eur"), ("PIB pe locuitor în euro în 2022", "eur"),
    ("GDP per capita in € 2022", "eur"), ("PIB pe locuitor în lei", "ron"), ("average wage in RON", "ron"),
])
def test_currency_is_read(query, value):
    assert quals(query)["currency"][0] == value


def test_both_currencies_are_not_one_value():
    assert quals("wage in lei and in euro")["currency"][0] is None


@pytest.mark.parametrize("query", ["European Union population", "population of Romania"])
def test_currency_has_no_false_positive(query):
    assert "currency" not in quals(query)


@pytest.mark.parametrize("unit, cur, ok", [("Lei", "ron", True), ("Milioane lei", "ron", True), ("Euro", "eur", True),
                                            ("Lei", "eur", False), ("Numar persoane", "ron", False)])
def test_unit_currency(unit, cur, ok):
    assert discovery._unit_is(unit, cur) is ok


class Ctx:
    conn = None


def test_currency_outcome_filters_one_matching_unit_of_several(monkeypatch):
    def values(units):
        return lambda ctx, code, col, q=None, limit=500: {"values": units, "total": len(units)}
    q = {"kind": "currency", "value": "eur"}
    monkeypatch.setattr(discovery, "_values", values(["Lei", "Euro"]))
    assert discovery._currency_outcome(Ctx, "X", "Lei", q) == {"filter": ("UNIT_MEASURE", "Euro")}
    monkeypatch.setattr(discovery, "_values", values(["Lei"]))
    assert discovery._currency_outcome(Ctx, "X", "Lei", q) is None                  # no conversion
    assert discovery._currency_outcome(Ctx, "X", "Lei", {"kind": "currency", "value": "ron"}) == {}
    monkeypatch.setattr(discovery, "_values", values(["Lei", "Mii lei"]))
    assert discovery._currency_outcome(Ctx, "X", "Lei", {"kind": "currency", "value": "ron"}) is None   # two match
    monkeypatch.setattr(discovery, "_values", lambda *a, **k: None)                 # no unit column: the card's unit
    assert discovery._currency_outcome(Ctx, "X", "Euro", q) == {}
    assert discovery._currency_outcome(Ctx, "X", "Lei", q) is None


# ============================================================ 2. per candidate, synthetic corpus

RESIDENT = {"Cluj": (400.0, 300.0), "Iași": (350.0, 450.0), "Municipiul București": (0.0, 1900.0)}
LOCALITIES = [("Timiș", "155243 MUNICIPIUL TIMISOARA", 300000.0), ("Cluj", "54975 MUNICIPIUL CLUJ-NAPOCA", 320000.0),
              ("Cluj", "56001 COMUNA GURA ALFA", 1000.0), ("Cluj", "56002 COMUNA GURA BETA", 2000.0)]


def build(corpus):
    add_dataset(corpus, "POP105A_judete_grupe",
                [area_dim(CTY), ("RESIDENCE", "Mediu", "other", [("Total", {}), ("Rural", {}), ("Urban", {})]),
                 time_dim(list(YEARS)), unit_dim("Numar persoane")],
                [(a, r, y, "Numar persoane", (sum(v) if r == "Total" else v[("Rural", "Urban").index(r)])
                  + (20.0 if r == "Total" else 10.0) * (int(y) - 2022))
                 for a, v in RESIDENT.items() for r in ("Total", "Rural", "Urban") for y in YEARS],
                name="Populatia rezidenta")
    _series(corpus, "POP107A_judete_grupe", "Populatia dupa domiciliu", POP, shift=-20)
    add_dataset(corpus, "POP107D_grupe_localitate",
                [area_dim(["Timiș", "Cluj"]), area_dim([n for _, n, _ in LOCALITIES], "locality", "REF_AREA_2"),
                 time_dim(["2023", "2024"]), unit_dim("Numar persoane")],
                [(c, n, y, "Numar persoane", v + (5.0 if y == "2024" else 0.0)) for c, n, v in LOCALITIES
                 for y in ("2023", "2024")],
                name="Populatia dupa domiciliu pe localitati", updated="2026-06-01")
    add_search_columns(corpus)


@pytest.fixture
def env(tmp_path, monkeypatch):
    e = make_env(tmp_path, monkeypatch, build=build)
    monkeypatch.setattr(dataset_search, "SEARCH_DB_PATH", tmp_path / "no-fts.duckdb")
    dataset_search._reset_for_tests()
    yield e
    monkeypatch.undo()
    dataset_search._reset_for_tests()


def disc(query, lang="en"):
    return call("discover_indicators", query=query, lang=lang)


def unapplied(out):
    return out["data"]["interpretation"]["unapplied_constraints"]


def execute(nc):
    out = R.call_tool(nc["tool"], nc["arguments"])
    R.validate_result(nc["tool"], out)
    return out


@pytest.mark.parametrize("query, lang, value, total", [
    ("Rural resident population of Romania in 2023", "en", "Rural", 400 + 350 + 0 + 30),
    ("Populația rezidentă rurală în 2023", "ro", "Rural", 400 + 350 + 0 + 30),
    ("Urban resident population of Romania in 2023", "en", "Urban", 300 + 450 + 1900 + 30),
])
def test_residence_is_applied_from_the_data_file(env, query, lang, value, total):
    out = disc(query, lang)
    c = card(out, "resident_population")
    nc = c["next_call"]
    assert nc["tool"] == "query_data" and nc["arguments"]["filters"]["RESIDENCE"] == [value]
    assert unapplied(out) == [] and "constraint_not_applied" not in codes(out)
    assert any(w["code"] == "qualifier_applied" and w["subject"] == "RESIDENCE" for w in out["warnings"])
    pref = next(k for k in c["candidates"] if k["preferred"])
    assert any(n["code"] == "qualifier_applied" and "RESIDENCE" in n["message"] and value in n["message"]
               for n in pref["notes"])
    res = execute(nc)
    assert res["data"]["rows"] == [["2023", float(total)]]
    assert "unverified_total" in codes(res)          # query_data's own qualification stays


def test_without_the_word_there_is_no_residence_filter(env):
    out = disc("Resident population of Romania in 2023")
    assert "RESIDENCE" not in card(out, "resident_population")["next_call"]["arguments"]["filters"]
    assert "qualifier_applied" not in codes(out)


def test_a_candidate_without_the_column_gets_no_call_and_the_word_is_reported(env):
    out = disc("Rural domicile population of Romania in 2023")
    assert unapplied(out) == [{"kind": "residence", "text": "rural"}]
    assert "constraint_not_applied" in codes(out) and "qualifier_applied" not in codes(out)
    c = card(out, "domicile_population")
    assert c["next_call"]["tool"] == "describe_dataset"
    assert all((k["next_call"] or {}).get("tool") != "query_data" for k in c["candidates"])


def test_a_unique_locality_is_applied_and_its_row_is_the_answer(env):
    out = disc("Population by domicile of the city of Timișoara in 2023")
    nc = card(out, "domicile_population")["next_call"]
    assert nc["tool"] == "query_data"
    assert nc["arguments"]["filters"]["REF_AREA_2"] == ["155243 MUNICIPIUL TIMISOARA"]
    assert "REF_AREA_2" in nc["arguments"]["group_by"]
    assert unapplied(out) == []
    assert any(w["code"] == "qualifier_applied" and w["subject"] == "REF_AREA_2" for w in out["warnings"])
    rows = execute(nc)["data"]["rows"]
    assert len(rows) == 1 and rows[0][0] == "155243 MUNICIPIUL TIMISOARA"


def test_a_county_named_city_is_not_ambiguous_once_the_cue_names_it(env):
    out = disc("Population by domicile of the municipality of Cluj-Napoca in 2024")
    assert out["status"] == "ok" and out["data"]["interpretation"]["places"] == []
    nc = card(out, "domicile_population")["next_call"]
    assert nc["arguments"]["filters"]["REF_AREA_2"] == ["54975 MUNICIPIUL CLUJ-NAPOCA"]
    assert [r[-1] for r in execute(nc)["data"]["rows"]] == [320005.0]


def test_a_county_alone_keeps_its_behaviour(env):
    out = disc("Population by domicile of Cluj county in 2023")
    assert out["data"]["interpretation"]["unapplied_constraints"] == []
    assert "REF_AREA_2" not in str(card(out, "domicile_population")["next_call"])


def test_a_locality_matching_several_values_offers_the_lookup(env):
    out = disc("Population by domicile of the commune of Gura in 2024")
    c = card(out, "domicile_population")
    assert c["next_call"] == {"tool": "find_dimension_values", "arguments": {
        "dataset": "POP107D_grupe_localitate", "column": "REF_AREA_2", "query": "gura", "limit": 20}}
    assert any(w["code"] == "qualifier_lookup" for w in out["warnings"])
    vals = [v["value"] for v in execute(c["next_call"])["data"]["values"]]
    assert vals == ["56001 COMUNA GURA ALFA", "56002 COMUNA GURA BETA"]
    assert unapplied(out) == []


def test_a_locality_not_in_the_data_is_reported(env):
    out = disc("Population by domicile of the city of Narnia in 2024")
    assert unapplied(out) == [{"kind": "geography", "text": "narnia"}]
    assert "constraint_not_applied" in codes(out)
    assert card(out, "domicile_population")["next_call"]["tool"] == "describe_dataset"


def test_a_currency_no_candidate_is_in_is_reported_and_nothing_is_converted(env):
    out = disc("Resident population of Romania in euros in 2023")
    assert unapplied(out) == [{"kind": "currency", "text": "euros"}]
    assert card(out, "resident_population")["next_call"]["tool"] == "describe_dataset"


# ============================================================ 3. the real corpus (generation f20fc32a)

@pytest.fixture
def real():
    from app.services import generation
    gid = str(generation.current().get("id") or "")
    if not gid.startswith(PINNED):
        pytest.skip(f"pinned to generation {PINNED}…, corpus is {gid[:8] or 'unknown'}")
    return gid


def pref(out, cid):
    c = card(out, cid)
    return c, next((k for k in c["candidates"] if k["preferred"]), None)


@pytest.mark.corpus
@pytest.mark.parametrize("query, lang, value, total", [
    ("Rural resident population of Romania in 2023", "en", "Rural", 9114421.0),
    ("Populația rezidentă rurală a României în 2023", "ro", "Rural", 9114421.0),
    ("Urban resident population of Romania in 2023", "en", "Urban", 9940807.0),
])
def test_real_residence(real, query, lang, value, total):
    out = disc(query, lang)
    c, p = pref(out, "resident_population")
    assert p["dataset"] == "POP105A_judete_grupe" and unapplied(out) == []
    nc = c["next_call"]
    assert nc["arguments"]["filters"] == {"TIME_PERIOD": ["2023"], "RESIDENCE": [value]}
    res = execute(nc)
    assert res["data"]["rows"] == [["2023", total]]
    assert "unverified_total" in codes(res)


@pytest.mark.corpus
@pytest.mark.parametrize("query, lang, code, label, last", [
    ("Population by domicile of the city of Timișoara in 2023", "en", "155243", "MUNICIPIUL TIMISOARA", None),
    ("Populația după domiciliu a municipiului Timișoara în 2023", "ro", "155243", "MUNICIPIUL TIMISOARA", None),
    ("Population by domicile of the city of Cluj-Napoca in 2023", "en", "54975", "MUNICIPIUL CLUJ-NAPOCA", None),
])
def test_real_locality(real, query, lang, code, label, last):
    out = disc(query, lang)
    assert out["status"] == "ok" and unapplied(out) == []
    c, p = pref(out, "domicile_population")
    assert p["dataset"] == "POP107D_grupe_localitate"
    nc = c["next_call"]
    assert nc["arguments"]["filters"]["REF_AREA_2"] == [f"{code} {label}"]
    others = [k for k in c["candidates"] if not k["preferred"]]
    assert all((k["next_call"] or {}).get("tool") != "query_data" for k in others)       # level variants withheld
    rows = execute(nc)["data"]["rows"]
    assert len(rows) == 1 and f"{code} {label}" in rows[0] and "2023" in rows[0]


@pytest.mark.corpus
@pytest.mark.parametrize("query, label", [
    ("Populația după domiciliu a comunei Apahida în 2023", "55687 APAHIDA"),
    ("Populația după domiciliu a municipiului Oradea în 2023", "26564 MUNICIPIUL ORADEA"),
])
def test_real_romanian_cues_resolve_one_locality(real, query, label):
    c, _ = pref(disc(query, "ro"), "domicile_population")
    assert c["next_call"]["arguments"]["filters"]["REF_AREA_2"] == [label]
    assert len(execute(c["next_call"])["data"]["rows"]) == 1


@pytest.mark.corpus
def test_real_locality_name_matching_several_values_is_looked_up(real):
    out = disc("Populația după domiciliu a orașului Turda în 2023", "ro")
    c, _ = pref(out, "domicile_population")
    assert c["next_call"]["tool"] == "find_dimension_values" and c["next_call"]["arguments"]["query"] == "turda"
    assert [v["value"] for v in execute(c["next_call"])["data"]["values"]] == ["55259 MUNICIPIUL TURDA", "91688 TURDAS"]


@pytest.mark.corpus
@pytest.mark.parametrize("query, lang", [
    ("GDP per capita in euros in Romania in 2022", "en"), ("PIB pe locuitor în euro în România în 2022", "ro"),
])
def test_real_euro_is_not_answered_with_lei_or_regions(real, query, lang):
    out = disc(query, lang)
    assert {c["kind"] for c in unapplied(out)} >= {"currency"}
    assert "constraint_not_applied" in codes(out)
    c = card(out, "gdp_per_inhabitant")
    assert c["next_call"] is None or c["next_call"]["tool"] != "query_data"
    assert all((k["next_call"] or {}).get("tool") != "query_data" for k in c["candidates"])


@pytest.mark.corpus
@pytest.mark.parametrize("query", ["GDP per capita in Romania in 2022", "GDP per capita in lei in Romania in 2022",
                                   "PIB pe locuitor în lei în România în 2022"])
def test_real_national_published_cell_is_preferred(real, query):
    out = disc(query, "ro" if "PIB" in query else "en")
    c, p = pref(out, "gdp_per_inhabitant")
    assert unapplied(out) == [] and p["dataset"] == "CON103H_judete"
    assert c["next_call"]["arguments"] == {"dataset": "CON103H_judete", "filters": {"TIME_PERIOD": ["2022"]},
                                           "group_by": ["TIME_PERIOD"], "lang": c["next_call"]["arguments"]["lang"]}
    assert any(n["code"] == "national_published" for n in p["notes"])
    res = execute(c["next_call"])
    assert res["data"]["rows"] == [["TOTAL", "2022", "Lei", 72669.5]]
    assert res["data"]["value_source"] == "ins_published"
