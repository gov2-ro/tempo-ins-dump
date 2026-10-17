"""AQ-04C in Ask: the page keeps what changes the meaning of the numbers whatever the model writes.

A scripted provider calls the real tools on the AQ-04A/04B/05A synthetic corpora and then answers
WITHOUT mentioning a single caveat. The qualifications still reach `warnings` (what the page lists)
from the tool results of the turn, once per (code, subject), in the question's language. Also here:
the captions of ranked and unranked tables, the language given to tools that were not told one, and
the two small corrections (`from` in the follow-up hint, the prompt's mention of `action`).
"""
import json

import pytest

import test_aq04a_discovery_defaults as t04a
import test_aq04b_follow_up_actions as t04b
import test_aq05a_city_changes as t05a
from at01_fixtures import call, make_env
from at02_env import call_resp, run
from fix08_helpers import text_resp
from test_at01_query import base_corpus, env  # noqa: F401 — the AT-01 query corpus (AGEC: single ages 0-2 only)
from app import config
from app.services import agent, ask_context, ask_present, dataset_search
from app.services.tools import registry as R


@pytest.fixture(autouse=True)
def _ask_on(monkeypatch):
    monkeypatch.setattr(config, "ASK_ENABLED", True)
    monkeypatch.setattr(config, "ASK_BYOK_ENABLED", True)
    monkeypatch.setattr(agent, "RETRY_PAUSE_SECONDS", 0.0)


@pytest.fixture
def e04a(tmp_path, monkeypatch):
    yield t04a.make(tmp_path, monkeypatch)
    monkeypatch.undo()
    dataset_search._reset_for_tests()


@pytest.fixture
def e04b(tmp_path, monkeypatch):
    yield t04b._setup(tmp_path, monkeypatch)
    monkeypatch.undo()
    dataset_search._reset_for_tests()


@pytest.fixture
def e05a(tmp_path, monkeypatch):
    return make_env(tmp_path, monkeypatch, build=t05a.build_chg)


def listed(res):
    return [w for w in res.warnings if not w.startswith("Guardrail")]


def trace_warnings(res, tool, code):
    return [w for t in res.tool_trace if t["tool"] == tool for w in t["output"]["warnings"] if w["code"] == code]


# ====================================================================== caveats the model omitted

QUESTIONS = [("Câți locuitori are Cluj în 2023?", "ro"), ("How many people live in Cluj in 2023?", "en")]


@pytest.mark.parametrize("question, lang", QUESTIONS)
def test_an_assumed_definition_stays_listed_when_the_model_does_not_mention_it(e04a, monkeypatch, question, lang):
    """The default (resident population) was assumed by discovery. The model queries it and answers
    with the figure alone; the page still lists the assumption, first, in the question's language."""
    prompt = "populatia Cluj 2023" if lang == "ro" else "population of Cluj 2023"
    res, _ = run(monkeypatch, [
        call_resp("discover_indicators", {"query": prompt}, 0),
        call_resp("query_data", {"dataset": "POP105A_judete_grupe", "group_by": ["REF_AREA", "TIME_PERIOD"],
                                 "filters": {"REF_AREA": ["Cluj"], "TIME_PERIOD": ["2023"]}}, 1),
        text_resp("Cluj avea 710 persoane în 2023." if lang == "ro" else "Cluj had 710 people in 2023."),
    ], question=question)
    assert res.data["rows"] == [["Cluj", "2023", 710.0]] and res.outcome == "answered"
    assumed = trace_warnings(res, "discover_indicators", "assumed_definition")
    assert [w["subject"] for w in assumed] == ["resident_population"]
    assert res.warnings[0] == assumed[0]["message"]                    # first: it changes what the figure is
    assert ("Definiție presupusă" in res.warnings[0]) == (lang == "ro")
    assert ("Definition assumed" in res.warnings[0]) == (lang == "en")
    assert "presupus" not in res.answer and "assumed" not in res.answer     # the model said nothing of it


def test_a_definition_assumed_for_a_different_dataset_is_not_attached_to_another_table(e04a, monkeypatch):
    """The model went on to a dataset the assumption was not about: nothing to list."""
    res, _ = run(monkeypatch, [
        call_resp("discover_indicators", {"query": "populatia Cluj 2023"}, 0),
        call_resp("query_data", {"dataset": "POP107A_judete_grupe", "group_by": ["REF_AREA", "TIME_PERIOD"],
                                 "filters": {"REF_AREA": ["Cluj"], "TIME_PERIOD": ["2023"]}}, 1),
        text_resp("Cluj avea 690 persoane în 2023."),
    ], question="Câți locuitori după domiciliu are Cluj în 2023?")
    assert res.data["rows"] == [["Cluj", "2023", 690.0]]
    assert trace_warnings(res, "discover_indicators", "assumed_definition")
    assert not any("presupus" in w for w in res.warnings)


@pytest.mark.parametrize("question, lang", [("Cum s-a schimbat indicatorul SERK la Cluj?", "ro"),
                                            ("How did the SERK indicator change in Cluj?", "en")])
def test_a_series_break_stays_listed_when_the_model_does_not_mention_it(e04b, monkeypatch, question, lang):
    res, _ = run(monkeypatch, [
        call_resp("query_data", {"dataset": "SERK_judete", "filters": {"REF_AREA": ["Cluj"]},
                                 "group_by": ["REF_AREA", "TIME_PERIOD"]}, 0),
        text_resp("Cluj: 100 în 2018, 105 în 2023." if lang == "ro" else "Cluj: 100 in 2018, 105 in 2023."),
    ], question=question)
    text = ("Seria SERK se rupe între 2021 și 2022 (test)." if lang == "ro"
            else "SERK breaks between 2021 and 2022 (test).")
    assert text in res.warnings
    assert "rupe" not in res.answer and "breaks" not in res.answer
    assert res.data["status"] == "ok"


def test_the_same_qualification_is_listed_once_by_code_and_subject_even_in_two_languages(e04b, monkeypatch):
    base = {"dataset": "SERK_judete", "filters": {"REF_AREA": ["Cluj"]}, "group_by": ["REF_AREA", "TIME_PERIOD"]}
    res, _ = run(monkeypatch, [
        call_resp("query_data", {**base, "lang": "ro"}, 0),
        call_resp("query_data", {**base, "lang": "en", "limit": 150}, 1),     # another call, the other language
        call_resp("query_data", {**base, "filters": {"REF_AREA": ["Iași"]}, "lang": "en"}, 2),
        text_resp("Cluj: 105."),
    ], question="Cum s-a schimbat SERK?")
    breaks = [w for w in res.warnings if "SERK" in w and ("rupe" in w or "breaks" in w or "ruptură" in w)]
    # SERK-break once (the first language wins), SERK-iasi once; the Iasi-only break needs Iași
    assert [w for w in breaks if "2021" in w] == ["Seria SERK se rupe între 2021 și 2022 (test)."]
    assert sum("SERK-break" in json.dumps(t["output"]["warnings"]) for t in res.tool_trace) == 3
    assert len(res.warnings) == len(set(res.warnings))


@pytest.mark.parametrize("question, lang, scope, said", [
    ("Câte persoane sunt în AGEC în 2024?", "ro", "Vârste 0–2 ani (fără 3 ani și peste)",
     "Acest total acoperă doar o parte din domeniu (Vârste 0–2 ani (fără 3 ani și peste))"),
    ("How many people are in AGEC in 2024?", "en", "Ages 0–2 (3 and over not included)",
     "This total covers only part of the domain (Ages 0–2 (3 and over not included))")])
def test_a_partial_scope_stays_with_the_table_when_the_model_does_not_say_it(env, monkeypatch, question, lang, scope, said):
    res, _ = run(monkeypatch, [
        call_resp("query_data", {"dataset": "AGEC", "group_by": ["TIME_PERIOD"]}, 0),
        text_resp("În 2024: 90 de persoane." if lang == "ro" else "In 2024: 90 people.")], question=question)
    table = res.data
    assert table["status"] == "partial" and table["rows"] == [["2024", 90.0]]
    assert table["scope"]["domain_complete"] is False and table["scope"]["description"] == scope
    assert any(said in w for w in res.warnings)
    assert "0–2" not in res.answer and "parte" not in res.answer


# ====================================================================== language of tools called without one

def test_a_tool_called_without_lang_answers_in_the_question_language(e04b, monkeypatch):
    for question, expected, forbidden in (
            ("Câte persoane sunt în POPK_judete?", "nu există în date", "does not exist in the data"),
            ("How many people are there in POPK_judete?", "does not exist in the data", "nu există în date")):
        res, _ = run(monkeypatch, [
            call_resp("query_data", {"dataset": "POPK_judete", "filters": {"REF_AREA": ["Nowhere"]},
                                     "group_by": ["REF_AREA"]}, 0),
            text_resp("Nu există date."),
        ], question=question)
        out = res.tool_trace[0]["output"]
        assert out["reason"] == "slice_value_missing"
        assert res.tool_trace[0]["input"] == {"dataset": "POPK_judete", "filters": {"REF_AREA": ["Nowhere"]},
                                              "group_by": ["REF_AREA"]}        # the model's arguments are kept as sent
        assert out["recovery"][0]["tool"] == "find_dimension_values"
        assert out["recovery"][0]["message"] == ("Caută valorile exacte ale REF_AREA din date." if question.startswith("Câte")
                                                else "Look up the exact REF_AREA values the data has.")
        assert out["message"].startswith("Niciun rând nu corespunde" if question.startswith("Câte") else "No rows match")
        assert (expected in out["message"]) and (forbidden not in out["message"])


def test_a_language_the_model_chose_is_respected(e04b, monkeypatch):
    res, _ = run(monkeypatch, [
        call_resp("query_data", {"dataset": "POPK_judete", "filters": {"REF_AREA": ["Nowhere"]},
                                 "group_by": ["REF_AREA"], "lang": "ro"}, 0),
        text_resp("There is no such county."),
    ], question="How many people live in Nowhere?")
    assert res.tool_trace[0]["output"]["message"].startswith("Niciun rând nu corespunde")


def test_find_dimension_values_takes_a_language_and_the_loop_supplies_it(e04b, monkeypatch):
    out = call("find_dimension_values", dataset="POPK_judete", column="REF_AREA", query="zzz", lang="en")
    assert out["message"].startswith("No value of REF_AREA contains")
    res, _ = run(monkeypatch, [
        call_resp("find_dimension_values", {"dataset": "POPK_judete", "column": "REF_AREA", "query": "zzz"}, 0),
        text_resp("No such county."),
    ], question="Which counties exist?")
    assert res.tool_trace[0]["output"]["message"].startswith("No value of REF_AREA contains")


# ====================================================================== ranked and unranked captions

def test_a_cut_period_change_ranking_is_a_ranking_not_a_preview(e05a, monkeypatch):
    """compare_periods ranks every eligible entity before its top K: a list cut to K rows is the
    ranking, and says how many entities were ranked, excluded and outside the class."""
    res, _ = run(monkeypatch, [
        call_resp("compare_periods", {"dataset": "CHG", "entity_columns": ["REF_AREA", "REF_AREA_2"],
                                      "intervals": [{"from": "2015", "to": "2020"}], "entity_class": "cities",
                                      "top_k": 3}, 0),
        text_resp("Cele mai mari scăderi sunt la CITY229, CITY228 și CITY227."),
    ], question="Care sunt orașele cu cea mai mare scădere între 2015 și 2020?")
    table = res.data
    assert table["tool"] == "compare_periods" and len(table["rows"]) == 3
    assert table["truncated"] is True                                   # the list was cut ...
    assert table["ranked"] is True and table["eligible_count"] == 233   # ... of a ranking over 233 cities
    assert (table["interval_count"], table["excluded_count"], table["outside_class_count"]) == (1, 2, 2)
    assert "preview" not in table or not table["preview"]
    # the ranking's own qualifications, from the tool and not from the model
    assert any("nu dovedește statutul istoric de oraș" in w for w in res.warnings)
    assert any("perechi entitate–interval nu au fost clasate" in w for w in res.warnings)     # the tool's own
    assert any("perechi entitate–interval au fost excluse din clasament" in w for w in table["warnings"])


def test_a_ranking_over_several_intervals_counts_pairs_and_a_default_class_has_no_outside_count(e05a):
    out = call("compare_periods", dataset="CHG", entity_columns=["REF_AREA", "REF_AREA_2"],
               intervals=[{"from": "2010", "to": "2015"}, {"from": "2015", "to": "2020"}], top_k=2, lang="en")
    table = ask_present.display_table([{"id": "c", "tool": "compare_periods", "input": {}, "output": out}], "en")
    assert table["ranked"] is True and table["interval_count"] == 2 and len(table["rows"]) == 4
    assert table["eligible_count"] == sum(iv["eligible_count"] for iv in out["data"]["intervals"])
    assert table["outside_class_count"] is None
    assert any("entity-interval pair(s) were excluded from the ranking" in w for w in table["warnings"])
    ro = ask_present.display_table([{"id": "c", "tool": "compare_periods", "input": {}, "output": out}], "ro")
    assert any("perechi entitate–interval au fost excluse din clasament" in w for w in ro["warnings"])


def test_an_unranked_query_preview_is_still_a_preview(e04b):
    out = call("query_data", dataset="STAYK_judete", limit=2, lang="en")
    table = ask_present.display_table([{"id": "q", "tool": "query_data", "input": {}, "output": out}])
    assert table["truncated"] is True and table["preview"] is True
    assert not table.get("ranked") and "eligible_count" not in table


def test_a_city_ranking_lists_what_it_does_not_rank_and_what_is_unverified(e05a, monkeypatch):
    res, _ = run(monkeypatch, [
        call_resp("rank_entities", {"dataset": "CHG", "entity_columns": ["REF_AREA", "REF_AREA_2"],
                                    "entity_class": "cities", "year": "2020", "top_k": 3}, 0),
        text_resp("CITY001 are 5019 locuitori."),
    ], question="Care sunt cele mai mari 3 orașe în 2020?")
    table = res.data
    assert table["ranked"] is True and table["status"] == "partial"
    assert table["outside_class_count"] == 2 and table["excluded_count"] == 2
    assert any("schimbările istorice ale clasei UAT nu sunt urmărite" in w for w in res.warnings)
    assert any("entități nu au o observație finită" in w for w in res.warnings)


# ====================================================================== the agent's own warnings

def test_the_budget_notice_is_in_the_question_language(e04b, monkeypatch):
    monkeypatch.setattr(config, "ASK_MAX_TOOL_CALLS", 1)
    for question, text in (("Câte persoane sunt în Cluj?", "S-a atins limita de apeluri către instrumente"),
                           ("How many people are in Cluj?", "Reached the tool-call limit")):
        res, _ = run(monkeypatch, [
            call_resp("describe_dataset", {"dataset": "POPK_judete"}, 0),
            call_resp("describe_dataset", {"dataset": "STAYK_judete"}, 1),
            text_resp("Nu am terminat." if question.startswith("Câte") else "I did not finish."),
        ], question=question)
        assert any(w.startswith(text) for w in res.warnings), res.warnings


# ====================================================================== the two small corrections

def test_the_follow_up_hint_names_a_period_selection_with_its_public_field(e05a):
    out = call("compare_periods", dataset="CHG", entity_columns=["REF_AREA", "REF_AREA_2"],
               intervals=[{"from": "2015", "to": "2020"}], top_k=2)
    entry = ask_context.entry_from_envelope("compare_periods", out)
    assert entry["selection"]["intervals"] == [{"from": "2015", "to": "2020"}]
    gen = entry["generation"]
    clean = ask_context.validate([{"tool": "compare_periods", "generation": gen, "selection": entry["selection"]}],
                                 current={"status": "present", "id": gen})
    assert clean[0]["selection"]["intervals"] == [{"from": "2015", "to": "2020"}]
    hint = ask_context.prompt_section(clean)
    assert '"from":"2015"' in hint and "from_" not in hint
    # a validated entry can be sent again: the public name is the one the schema takes
    assert R.precheck("get_evidence_links", {"selection": clean[0]["selection"], "generation_id": gen}) is None


def test_the_prompt_and_the_tool_description_name_the_choice_actions():
    assert "`action`" in agent.SYSTEM_PROMPT and "`action_status`" in agent.SYSTEM_PROMPT
    assert "never run an action before they pick" in agent.SYSTEM_PROMPT
    assert "`lang`" in agent.SYSTEM_PROMPT
    desc = R.TOOLS["discover_indicators"].description
    assert "`action`" in desc and "once `action_status` is ready" in desc
    assert "only after the user has picked that choice" in desc
    for name in R.tool_names():
        assert "lang" in R.input_schema(name)["properties"], name
