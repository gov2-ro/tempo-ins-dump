"""Ask language: the site's language (the switcher's) as a signal for a question that shows none.

Owner decision 2026-10-17: tool prose stays Romanian by default; in addition the Ask page sends the
site's language, and the server uses it only when the question has no language of its own.

  question shows a language (diacritics, or more Romanian than English hint words, or the reverse) -> that
  ambiguous question (a tie: "PIB Cluj 2023")                                                         -> the request's `lang`
  neither                                                                                             -> 'ro'

Covered: the resolver as a table; the request field (accepted values, 422 for others, nothing reaches a
provider on a 422); the loop (tool calls without `lang`, the agent's own warnings, the response's `lang`,
the model's system prompt); the content-free metrics and the debug start event; the AQ-02 runner, which
sends each task variant's language as the site language. A real browser run is in test_aqlang_browser.py.
"""
import importlib.util
import json
import logging
import sys
from pathlib import Path

import pytest

from at02_env import call_resp, run, scripted
from fix08_helpers import install, make_client, text_resp
from test_at01_query import base_corpus, env  # noqa: F401 — the AT-01 query corpus (AGEC: single ages 0-2 only)
from app import config
from app.services import agent, answer_check, ask_guard

ROOT = Path(__file__).resolve().parent.parent
BODY = {"provider": "anthropic", "model": "claude-sonnet-5-5", "api_key": "k-123456"}


@pytest.fixture(autouse=True)
def _ask_on(monkeypatch):
    monkeypatch.setattr(config, "ASK_ENABLED", True)
    monkeypatch.setattr(config, "ASK_BYOK_ENABLED", True)
    monkeypatch.setattr(agent, "RETRY_PAUSE_SECONDS", 0.0)


# ====================================================================== the resolver

AMBIGUOUS = "PIB Cluj 2023"           # no diacritic and no hint word in either language

RESOLVER = [
    # (question, site, language, source)
    ("Câți locuitori are Cluj în 2023?", None, "ro", "question"),          # diacritics
    ("Câți locuitori are Cluj în 2023?", "en", "ro", "question"),          # ... beat an English site
    ("CÂȚI LOCUITORI ARE CLUJ?", "en", "ro", "question"),                  # upper-case diacritics count too
    ("Câți locuitori are Iaşi?", None, "ro", "question"),                  # cedilla forms (ş ţ), not only the comma ones
    ("Care este rata somajului pe judete?", "en", "ro", "question"),       # a Romanian hint majority without diacritics
    ("What is the unemployment rate by county?", None, "en", "question"),   # English words
    ("What is the unemployment rate by county?", "ro", "en", "question"),   # an English question on a Romanian site stays English
    ("How many people live in Cluj?", "ro", "en", "question"),
    (AMBIGUOUS, "en", "en", "site"),                                        # a tie follows the site ...
    (AMBIGUOUS, "ro", "ro", "site"),
    (AMBIGUOUS, None, "ro", "default"),                                     # ... with neither it is Romanian
    ("", "en", "en", "site"),
    ("in", "en", "en", "site"),                                             # 'in' is a hint word of both languages: a tie
    (AMBIGUOUS, "fr", "ro", "default"),                                     # only ro and en are languages here
    (AMBIGUOUS, "EN", "ro", "default"),
]


@pytest.mark.parametrize("question, site, lang, source", RESOLVER)
def test_the_language_resolver_table(question, site, lang, source):
    assert answer_check.resolve_lang(question, site) == (lang, source)


def test_guess_lang_answers_as_it_always_did_unless_a_default_is_passed():
    assert answer_check.guess_lang(AMBIGUOUS) == "en"                      # a tie used to read English: callers keep that
    assert answer_check.guess_lang(AMBIGUOUS, default="ro") == "ro"
    assert answer_check.guess_lang(AMBIGUOUS, default="en") == "en"
    assert answer_check.guess_lang("Care este populația?", default="en") == "ro"    # a signal is never overridden
    assert answer_check.guess_lang("What is the population?", default="ro") == "en"
    assert answer_check.lang_signal(AMBIGUOUS) is None and answer_check.lang_signal(None) is None


def test_an_english_question_that_names_a_place_with_diacritics_reads_as_romanian():
    """Known limitation, pinned so that a change is deliberate: the Romanian letters are checked first
    (the hint lists are too crude to outvote them: 'are' is an English hint and the commonest Romanian
    verb). The site language does not rescue it, because the question 'shows' a language."""
    assert answer_check.resolve_lang("How many people live in Iași?", "en") == ("ro", "question")


# ====================================================================== the request field

def post(client, question, **extra):
    return client.post("/api/ask", json={"question": question, **BODY, **extra})


@pytest.mark.parametrize("value", ["fr", "EN", "", "ro-RO", 1, ["en"], True])
def test_any_other_lang_is_a_422_and_nothing_reaches_the_provider(monkeypatch, value):
    calls = install(monkeypatch, lambda n, m, kw: text_resp("ok"))
    r = post(make_client(), AMBIGUOUS, lang=value)
    assert r.status_code == 422, r.text
    assert calls == []


@pytest.mark.parametrize("extra, expected", [({}, "ro"), ({"lang": None}, "ro"), ({"lang": "ro"}, "ro"),
                                             ({"lang": "en"}, "en")])
def test_lang_is_optional_and_the_response_says_which_language_the_turn_used(monkeypatch, extra, expected):
    install(monkeypatch, lambda n, m, kw: text_resp("ok"))
    r = post(make_client(), AMBIGUOUS, **extra)
    assert r.status_code == 200 and r.json()["lang"] == expected


def test_a_question_that_shows_its_language_is_not_overridden_by_the_request(monkeypatch):
    install(monkeypatch, lambda n, m, kw: text_resp("ok"))
    client = make_client()
    assert post(client, "Câți locuitori are Cluj?", lang="en").json()["lang"] == "ro"
    assert post(client, "How many people live in Cluj?", lang="ro").json()["lang"] == "en"


def test_the_stream_endpoint_takes_the_same_field(monkeypatch):
    monkeypatch.setattr(config, "ASK_DEBUG", True)
    install(monkeypatch, lambda n, m, kw: text_resp("ok"))
    client = make_client()
    r = client.post("/api/ask/stream", json={"question": AMBIGUOUS, **BODY, "lang": "en"})
    lines = [json.loads(x) for x in r.text.splitlines()]
    start = next(e for e in lines if e.get("event") == "start")
    assert (start["lang"], start["lang_source"]) == ("en", "site")
    assert lines[-1]["event"] == "result" and lines[-1]["result"]["lang"] == "en"
    assert client.post("/api/ask/stream", json={"question": AMBIGUOUS, **BODY, "lang": "fr"}).status_code == 422


# ====================================================================== the loop

NOWHERE = {"dataset": "AGEC", "filters": {"TIME_PERIOD": ["1850"]}, "group_by": ["TIME_PERIOD"]}   # a period the data lacks


def refusal(res):
    return res.tool_trace[0]["output"]["message"]


@pytest.mark.parametrize("question, site, language, source, said", [
    ("Nowhere AGEC 2024", "en", "en", "site", "No rows match"),
    ("Nowhere AGEC 2024", "ro", "ro", "site", "Niciun rând nu corespunde"),
    ("Nowhere AGEC 2024", None, "ro", "default", "Niciun rând nu corespunde"),
    ("Câte persoane sunt în AGEC în 2024?", "en", "ro", "question", "Niciun rând nu corespunde"),
    ("How many people are in AGEC in 2024?", "ro", "en", "question", "No rows match"),
])
def test_a_tool_called_without_lang_gets_the_resolved_language(env, monkeypatch, question, site, language, source, said):
    res, _ = run(monkeypatch, [call_resp("query_data", NOWHERE, 0), text_resp("Nu am găsit.")],
                 question=question, site_lang=site)
    assert refusal(res).startswith(said)
    assert res.tool_trace[0]["input"] == NOWHERE                          # the model's arguments are kept as sent
    assert (res.lang, res.metrics["lang"], res.metrics["lang_source"]) == (language, language, source)


def test_a_language_the_model_chose_is_still_respected_over_the_site(env, monkeypatch):
    res, _ = run(monkeypatch, [call_resp("query_data", {**NOWHERE, "lang": "ro"}, 0), text_resp("x")],
                 question="Nowhere AGEC 2024", site_lang="en")
    assert refusal(res).startswith("Niciun rând nu corespunde")


@pytest.mark.parametrize("site, language", [("en", "en"), ("ro", "ro")])
def test_the_page_lists_caveats_and_scope_in_the_resolved_language(env, monkeypatch, site, language):
    """An ambiguous question on a site shown in `site`: the warnings and the table's scope text follow it
    whatever the model's own wording is."""
    res, _ = run(monkeypatch, [call_resp("query_data", {"dataset": "AGEC", "group_by": ["TIME_PERIOD"]}, 0),
                               text_resp("90.")], question="AGEC 2024", site_lang=site)
    scope = {"en": "Ages 0–2 (3 and over not included)", "ro": "Vârste 0–2 ani (fără 3 ani și peste)"}[language]
    said = {"en": "This total covers only part of the domain", "ro": "Acest total acoperă doar o parte din domeniu"}[language]
    assert res.data["scope"]["description"] == scope and res.lang == language
    assert any(said in w for w in res.warnings), res.warnings


def test_the_agents_own_notices_follow_the_resolved_language(env, monkeypatch):
    monkeypatch.setattr(config, "ASK_MAX_TOOL_CALLS", 1)
    for site, text in (("en", "Reached the tool-call limit"), ("ro", "S-a atins limita de apeluri către instrumente")):
        res, _ = run(monkeypatch, [
            call_resp("describe_dataset", {"dataset": "AGEC"}, 0),
            call_resp("describe_dataset", {"dataset": "AGEC", "lang": "en"}, 1),
            text_resp("done")], question="AGEC 2024", site_lang=site)
        assert any(w.startswith(text) for w in res.warnings), (site, res.warnings)


def test_a_follow_up_is_resolved_per_turn(env, monkeypatch):
    """The language is decided for each question from that question and the site at that moment: an
    ambiguous follow-up in an English conversation follows the site, not the earlier turn."""
    first, _ = run(monkeypatch, [call_resp("query_data", NOWHERE, 0), text_resp("none")],
                   question="How many people are in AGEC in 2024?", site_lang="ro")
    assert first.lang == "en"
    history = [{"role": "user", "content": "How many people are in AGEC in 2024?"},
               {"role": "assistant", "content": first.answer}]
    second, _ = run(monkeypatch, [call_resp("query_data", NOWHERE, 0), text_resp("none")],
                    question="2023", history=history, site_lang="ro")
    assert (second.lang, second.metrics["lang_source"]) == ("ro", "site")


# ---------------------------------------------------------------- what the model is told

def systems(calls):
    return [c.kw["system"] for c in calls]


@pytest.mark.parametrize("site, name, code", [("en", "English", "en"), ("ro", "Romanian", "ro")])
def test_the_model_is_told_the_language_only_when_the_site_decided_it(env, monkeypatch, site, name, code):
    _, calls = run(monkeypatch, [call_resp("describe_dataset", {"dataset": "AGEC"}, 0), text_resp("ok")],
                   question="AGEC 2024", site_lang=site)
    assert len(calls) == 2
    for system in systems(calls):
        assert system.startswith(agent.SYSTEM_PROMPT)
        assert f"the user reads the site in {name}. Answer in {name} and pass `lang` \"{code}\"" in system


def test_the_model_is_told_nothing_when_the_question_or_the_default_decided_it(env, monkeypatch):
    for question, site in (("How many people are in AGEC in 2024?", "ro"),    # the question decided
                           ("Câte persoane sunt în AGEC?", "en"),
                           ("AGEC 2024", None)):                               # nothing decided: the default
        _, calls = run(monkeypatch, [text_resp("ok")], question=question, site_lang=site)
        assert systems(calls) == [agent.SYSTEM_PROMPT], (question, site)


def test_the_note_also_reaches_the_final_turn_and_a_repair(env, monkeypatch):
    monkeypatch.setattr(config, "ASK_MAX_TOOL_CALLS", 1)
    _, calls = run(monkeypatch, [call_resp("describe_dataset", {"dataset": "AGEC"}, 0),
                                 call_resp("describe_dataset", {"dataset": "AGEC", "lang": "en"}, 1),
                                 text_resp("done")], question="AGEC 2024", site_lang="en")
    final = [c for c in calls if c.kw.get("tool_choice") == "none"]
    assert final and all("the user reads the site in English" in c.kw["system"] for c in final)


# ====================================================================== metrics and debug

def metrics_line(caplog):
    lines = [r.getMessage() for r in caplog.records if "ASK_METRICS" in r.getMessage()]
    assert len(lines) == 1, lines
    return lines[0], json.loads(lines[0].split("ASK_METRICS ", 1)[1])


@pytest.mark.parametrize("question, site, expected", [
    (AMBIGUOUS, "en", {"site_lang": "en", "lang": "en", "lang_source": "site"}),
    (AMBIGUOUS, "ro", {"site_lang": "ro", "lang": "ro", "lang_source": "site"}),
    (AMBIGUOUS, None, {"lang": "ro", "lang_source": "default"}),
    ("Care este populația?", "en", {"site_lang": "en", "lang": "ro", "lang_source": "question"}),
])
def test_the_resolved_language_and_its_source_are_in_the_content_free_metrics(monkeypatch, caplog, question, site, expected):
    install(monkeypatch, lambda n, m, kw: text_resp("RĂSPUNS-PRIVAT"))
    caplog.set_level(logging.DEBUG)
    r = post(make_client(), question, **({"lang": site} if site else {}))
    assert r.status_code == 200
    raw, payload = metrics_line(caplog)
    assert {k: payload.get(k) for k in ("site_lang", "lang", "lang_source")} == {"site_lang": None, **expected}
    assert "RĂSPUNS-PRIVAT" not in raw and question not in raw
    assert set(payload) <= set(ask_guard.METRIC_SCALARS) | {"usage", "refusal_codes", "claim_codes"}


def test_a_failed_turn_still_logs_the_site_language_the_client_sent(monkeypatch, caplog):
    from app.services.llm_client import LLMError

    def boom(n, m, kw):
        raise LLMError("provider_unavailable", "down", 503)

    install(monkeypatch, boom)
    caplog.set_level(logging.DEBUG)
    r = post(make_client(), AMBIGUOUS, lang="en")
    assert r.status_code == 503
    _, payload = metrics_line(caplog)
    assert payload["site_lang"] == "en" and payload["status"] == 503 and "lang_source" not in payload


def test_the_metric_fields_are_strings_of_stable_codes_only():
    out = ask_guard.sanitize_metrics({"site_lang": "en", "lang": "ro", "lang_source": "x" * 200, "question": "secret"})
    assert out["site_lang"] == "en" and out["lang"] == "ro" and len(out["lang_source"]) == 80 and "question" not in out


def test_the_debug_start_event_names_the_language_and_where_it_came_from(monkeypatch):
    install(monkeypatch, lambda n, m, kw: text_resp("ok"))
    events = []
    agent.run_agent(AMBIGUOUS, provider="anthropic", api_key="k", on_event=events.append, site_lang="en")
    start = next(e for e in events if e["event"] == "start")
    assert (start["lang"], start["lang_source"]) == ("en", "site")


# ====================================================================== the AQ-02 runner

def _runner():
    spec = importlib.util.spec_from_file_location("eval_ask_tasks_lang", ROOT / "scripts" / "eval-ask-tasks.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["eval_ask_tasks_lang"] = mod
    spec.loader.exec_module(mod)
    return mod


def test_the_runner_sends_each_variants_language_as_the_site_language(monkeypatch):
    """T13 en ('List every value in BIGLONG.') and T16 ro ('Acum pentru 2020.') show no language of their
    own: the (simulated) user's site decides them, as it would in a browser."""
    R = _runner()
    from aq02_tasks import load_taskset
    tasks = {t["id"]: t for t in load_taskset()["tasks"]}
    seen = []
    real = agent.run_agent
    monkeypatch.setattr(agent, "run_agent", lambda *a, **kw: (seen.append((a[0], kw.get("site_lang"))), real(*a, **kw))[1])
    with R.World("synthetic") as world:
        for tid, lang in (("T13", "en"), ("T13", "ro"), ("T16", "ro"), ("T16", "en")):
            res = R.run_task(world, tasks[tid], lang, "direct", canaries=[])
            assert res["status"] == "pass", (tid, lang, res["failure_categories"])
    assert seen and all(site in ("ro", "en") for _, site in seen)
    by_prompt = {(p, s) for p, s in seen}
    assert ("List every value in BIGLONG.", "en") in by_prompt and ("Acum pentru 2020.", "ro") in by_prompt
    assert answer_check.resolve_lang("List every value in BIGLONG.", "en") == ("en", "site")
    assert answer_check.resolve_lang("Acum pentru 2020.", "ro") == ("ro", "site")
