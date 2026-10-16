"""AT-02: the bounded Ask loop over the shared tools, with a scripted provider.

Provider outcomes (the logged empty `length` answer included), refusal loops and duplicate
requests, the final synthesis, token and context budgets, claim binding and the display
adapters. Statistics come from the real tools on a synthetic generation.
"""
import json

import pytest

from at02_env import call_resp, full_env, run, scripted
from fix08_helpers import fake_env, install, make_client, text_resp, tools_resp
from app import config
from app.services import agent
from app.services.llm_client import LLMError, LLMResponse


@pytest.fixture(autouse=True)
def _ask_on(monkeypatch):
    monkeypatch.setattr(config, "ASK_ENABLED", True)
    monkeypatch.setattr(config, "ASK_BYOK_ENABLED", True)


def length(text=None, tokens=2048, calls=()):
    return LLMResponse(stop_reason="max_tokens", text=text, tool_calls=list(calls),
                       finish="output_limit", requested_tokens=tokens)


# ---------------------------------------------------------------- provider outcomes

class TestProviderOutcomes:
    def test_the_logged_empty_length_answer_gets_one_bounded_retry(self, monkeypatch):
        """Old: HTTP 200, end_turn, `(no answer)`. New: a retry with more room and a short-answer
        instruction; if it answers, the answer is real."""
        calls = install(monkeypatch, lambda n, m, kw: length() if n == 1 else text_resp("Răspuns scurt."))
        res = agent.run_agent("Care este rata șomajului?", provider="deepseek", model="deepseek-v4-pro",
                              api_key="k")
        assert res.answer == "Răspuns scurt." and "(no answer)" not in res.answer
        assert len(calls) == 2 and res.metrics["retries"] == 1
        assert calls[1]["max_tokens"] > calls[0]["max_tokens"]               # a suitable allowance
        assert "ran out of output space" in calls[1]["system"]
        assert res.outcome == "answered"

    def test_a_second_empty_length_answer_is_an_explicit_failure(self, monkeypatch):
        calls = install(monkeypatch, lambda n, m, kw: length())
        res = agent.run_agent("Care este rata șomajului?", provider="deepseek", model="deepseek-v4-pro",
                              api_key="k")
        assert len(calls) == 2
        assert (res.outcome, res.reason, res.stop_reason) == ("failed", "output_limit", "output_limit")
        assert res.answer and "(no answer)" not in res.answer
        assert "spațiu" in res.answer                                          # RO question → RO notice

    def test_partial_text_is_marked_partial_and_not_retried(self, monkeypatch):
        calls = install(monkeypatch, lambda n, m, kw: length("Populația a crescut"))
        res = agent.run_agent("What is the population?", provider="deepseek", model="m", api_key="k")
        assert len(calls) == 1
        assert (res.outcome, res.reason) == ("partial", "output_limit")
        assert res.answer.startswith("Populația a crescut") and "cut off" in res.answer

    def test_whitespace_success_gets_one_repair_with_tools_off(self, monkeypatch):
        calls = install(monkeypatch, lambda n, m, kw: text_resp("   \n ") if n == 1 else text_resp("Gata."))
        res = agent.run_agent("Care este populatia?", provider="anthropic", api_key="k")
        assert res.answer == "Gata." and len(calls) == 2
        assert calls[1]["tool_choice"] == "none" and "previous reply was empty" in calls[1]["system"]

    def test_empty_twice_is_empty_output_never_no_answer(self, monkeypatch):
        install(monkeypatch, lambda n, m, kw: text_resp(""))
        res = agent.run_agent("What is the population?", provider="anthropic", api_key="k")
        assert (res.outcome, res.reason, res.stop_reason) == ("failed", "empty_output", "empty_output")
        assert "(no answer)" not in res.answer and "no answer" in res.answer.lower()

    def test_incomplete_responses_turn_with_no_text_is_repaired_once(self, monkeypatch):
        inc = LLMResponse(stop_reason="max_tokens", text=None, tool_calls=[], finish="incomplete")
        calls = install(monkeypatch, lambda n, m, kw: inc if n == 1 else text_resp("Acum da."))
        res = agent.run_agent("Care este populatia?", provider="openai", model="m", api_key="k")
        assert res.answer == "Acum da." and len(calls) == 2

    def test_content_filter_is_a_stable_failure(self, monkeypatch):
        cf = LLMResponse(stop_reason="refusal", text=None, tool_calls=[], finish="content_filter")
        install(monkeypatch, lambda n, m, kw: cf)
        res = agent.run_agent("What is the population?", provider="anthropic", api_key="k")
        assert (res.outcome, res.reason) == ("failed", "content_filter") and "content filter" in res.answer

    def test_auth_error_is_not_retried_and_never_switches_provider(self, monkeypatch):
        def deny(n, m, kw):
            raise LLMError("provider_auth", "The provider rejected the API key", 401)
        calls = install(monkeypatch, deny)
        r = make_client().post("/api/ask", json={"question": "x", "provider": "anthropic",
                                                 "model": "claude-sonnet-5-5", "api_key": "k-123456"})
        assert r.status_code == 401 and len(calls) == 1
        assert {c["provider"] for c in calls} == {"anthropic"}

    @pytest.mark.parametrize("error", ["RateLimitError", "APITimeoutError", "APIConnectionError"])
    def test_a_retryable_failure_is_retried_once_then_reported(self, monkeypatch, error):
        exc = type(error, (Exception,), {})

        def boom(n, m, kw):
            raise exc("provider said no")
        calls = install(monkeypatch, boom)
        r = make_client().post("/api/ask", json={"question": "x", "provider": "anthropic",
                                                 "model": "claude-sonnet-5-5", "api_key": "k-123456"})
        assert len(calls) == 2 and r.status_code in (429, 503)

    def test_provider_timeout_does_not_blame_the_key(self, monkeypatch):
        calls = install(monkeypatch, lambda n, m, kw: (_ for _ in ()).throw(TimeoutError("slow")))
        r = make_client().post("/api/ask", json={"question": "x", "provider": "anthropic",
                                                 "model": "claude-sonnet-5-5", "api_key": "k-123456"})
        assert r.status_code == 503 and "key" not in r.json()["detail"].lower()
        assert len(calls) == 2


# ---------------------------------------------------------------- loops and duplicates

class TestRefusalLoopsAndDuplicates:
    def test_repeated_refusals_stop_early_without_new_scans(self, tmp_path, monkeypatch):
        full_env(tmp_path, monkeypatch)
        executed = []
        real = agent.call_tool

        def spy(name, arguments, **kw):
            executed.append((name, json.dumps(arguments, sort_keys=True)))
            return real(name, arguments, **kw)
        monkeypatch.setattr(agent, "call_tool", spy)
        refused = {"dataset": "POPX", "group_by": ["TIME_PERIOD"]}
        res, calls = run(monkeypatch, [
            call_resp("query_data", refused, 0),
            call_resp("query_data", refused, 1),
            call_resp("query_data", refused, 2),
            text_resp("Nu există un total sigur pentru această selecție (POPX)."),
        ])
        data_runs = [e for e in executed if e[0] == "query_data"]
        assert len(data_runs) == 1                                   # one real scan
        assert res.budget["tools"] == 3 and res.budget["executions"] == 1 and res.budget["cache_hits"] == 2
        assert [c.kw["tool_choice"] for c in calls] == ["auto", "auto", "auto", "none"]   # then synthesis
        repeat = [t for t in res.tool_trace if t["cached"]][-1]["output"]
        assert repeat["status"] == "unavailable" and repeat["reason"] == "overlapping_levels"
        assert any(w["code"] == "repeated_request" for w in repeat["warnings"])
        assert repeat["recovery"]                                      # candidates, not another scan
        assert (res.outcome, res.reason) == ("refused", "overlapping_levels")
        assert res.metrics["refusal_codes"]["overlapping_levels"] == 3

    def test_no_raw_row_total_appears_after_a_refusal(self, tmp_path, monkeypatch):
        full_env(tmp_path, monkeypatch)
        res, _ = run(monkeypatch, [
            call_resp("query_data", {"dataset": "POPX", "group_by": ["TIME_PERIOD"]}, 0),
            text_resp("Totalul este 242 000 (POPX)."),
        ])
        assert "242" not in res.answer and res.verification["status"] == "values_withheld"
        assert res.data is None                                          # no table: nothing valid ran

    def test_an_exact_repeat_of_a_success_is_served_from_the_turn_cache(self, tmp_path, monkeypatch):
        full_env(tmp_path, monkeypatch)
        executed = []
        real = agent.call_tool
        monkeypatch.setattr(agent, "call_tool",
                            lambda name, args, **kw: executed.append(name) or real(name, args, **kw))
        args = {"dataset": "POPC", "group_by": ["REF_AREA", "TIME_PERIOD"]}
        res, _ = run(monkeypatch, [call_resp("query_data", args, 0), call_resp("query_data", args, 1),
                                   text_resp("Cluj: 1000 în 2020.")])
        assert executed.count("query_data") == 1
        assert res.budget["tools"] == 2 and res.budget["cache_hits"] == 1   # still counted as dispatches
        second = res.tool_trace[1]
        assert second["cached"] and second["output"]["status"] == "ok"

    def test_a_transient_failure_may_be_retried_once_then_it_is_cached(self, monkeypatch):
        outcomes = iter([fake_env("query_data", "unavailable", "busy", "busy"),
                         fake_env("query_data", "unavailable", "busy", "busy"),
                         fake_env("query_data", "ok")])
        executed = []

        def handler(name, args):
            executed.append(name)
            return next(outcomes)
        same = {"dataset": "COUNTX"}
        calls = install(monkeypatch, lambda n, m, kw: call_resp("query_data", same, n) if n <= 3
                        else text_resp("Nu pot acum."), handler=handler)
        res = agent.run_agent("Care este populatia?", provider="anthropic", api_key="k")
        assert len(executed) == 2                                   # the original and exactly one retry
        assert res.budget["cache_hits"] == 1 and res.budget["tools"] == 3
        assert len(calls) == 4

    def test_a_model_that_keeps_asking_on_its_last_call_is_answered_from_what_exists(
            self, tmp_path, monkeypatch):
        full_env(tmp_path, monkeypatch)
        monkeypatch.setattr(config, "ASK_MAX_ITERATIONS", 3)
        args = {"dataset": "POPC", "group_by": ["REF_AREA", "TIME_PERIOD"], "limit": 100}
        res, calls = run(monkeypatch, lambda n, m, kw: call_resp("query_data", {**args, "limit": 100 - n}, n)
                         if kw["tool_choice"] == "auto" else
                         LLMResponse(stop_reason="end_turn", text="Cluj: 1010 în 2021.", tool_calls=[],
                                     finish="complete"))
        assert [c.kw["tool_choice"] for c in calls] == ["auto", "auto", "none"]
        assert (res.outcome, res.reason) == ("partial", "iterations")
        assert "known gaps" in calls[2].kw["system"] or "final turn" in calls[2].kw["system"]
        assert res.verification["status"] == "verified"


# ---------------------------------------------------------------- budgets

class TestBudgets:
    def test_output_tokens_are_charged_per_call_and_the_final_answer_is_reserved(self, monkeypatch):
        monkeypatch.setattr(config, "ASK_OUTPUT_TOKENS", 2048)
        monkeypatch.setattr(config, "ASK_REASONING_MODELS", [])
        monkeypatch.setattr(config, "ASK_TURN_OUTPUT_TOKENS", 7000)
        calls = install(monkeypatch, lambda n, m, kw: tools_resp(1) if kw["tool_choice"] == "auto"
                        else text_resp("din ce am"))
        res = agent.run_agent("Care este populatia?", provider="anthropic", api_key="k")
        # 7000: call 1 (2048) leaves 4952; a second tool call would leave less than a final answer's
        # allowance after it, so call 2 is already the final one
        assert [c["tool_choice"] for c in calls] == ["auto", "none"] or len(calls) == 3
        assert res.budget["output_tokens_requested"] <= 7000
        assert res.answer == "din ce am"

    def test_an_insufficient_allowance_is_output_budget_not_a_silent_cut(self, monkeypatch):
        monkeypatch.setattr(config, "ASK_OUTPUT_TOKENS", 2048)
        monkeypatch.setattr(config, "ASK_REASONING_MODELS", [])
        monkeypatch.setattr(config, "ASK_TURN_OUTPUT_TOKENS", 1000)
        calls = install(monkeypatch, lambda n, m, kw: text_resp("x"))
        res = agent.run_agent("Care este populatia?", provider="anthropic", api_key="k")
        assert calls == []
        assert (res.outcome, res.reason, res.stop_reason) == ("failed", "output_budget", "output_budget")
        assert "buget" in res.answer

    def test_usage_totals_accumulate_where_the_provider_reports_them(self, monkeypatch):
        u = {"input_tokens": 100, "output_tokens": 20, "reasoning_tokens": None, "cached_tokens": 10}
        install(monkeypatch, lambda n, m, kw: None)
        seq = iter([LLMResponse("tool_use", None, tools_resp(1).tool_calls, finish="tool_use", usage=u),
                    LLMResponse("end_turn", "gata", [], finish="complete", usage=u)])
        monkeypatch.setattr(agent, "complete_with_tools", lambda msgs, tools, **kw: next(seq))
        res = agent.run_agent("Care este populatia?", provider="anthropic", api_key="k")
        assert res.usage == {"input_tokens": 200, "output_tokens": 40, "reasoning_tokens": None,
                             "cached_tokens": 20}
        assert res.metrics["usage"] == res.usage

    def test_the_context_budget_compacts_older_results_and_keeps_pairing(self, monkeypatch):
        big = [[f"Județ {i}", 1.0 * i] for i in range(300)]

        def handler(name, args):
            return fake_env(name, status="ok", rows=big, selection={"kind": "dataset", "dataset": "BIGX",
                            "filters": {}, "group_by": ["REF_AREA"], "approximate": False},
                            warnings=[{"code": "approximation", "message": "APPROXIMATION: unweighted mean"}],
                            sources=[{"dataset": "BIGX", "unit": "Numar", "definition": "d"}])
        monkeypatch.setattr(config, "ASK_CONTEXT_BYTES", 12_000)
        calls = install(monkeypatch, lambda n, m, kw: tools_resp(1, name="query_data", args={"dataset": f"D{n}"})
                        if n <= 4 else text_resp("gata"), handler=handler)
        res = agent.run_agent("Care este populatia?", provider="anthropic", api_key="k")
        last = calls[-1]["messages"]
        blocks = [b for m in last if isinstance(m.get("content"), list) for b in m["content"]
                  if b.get("type") == "tool_result"]
        uses = [b for m in last if isinstance(m.get("content"), list) for b in m["content"]
                if b.get("type") == "tool_use"]
        assert {b["tool_use_id"] for b in blocks} == {b["id"] for b in uses}      # no orphan ids
        bodies = [json.loads(b["content"]) for b in blocks]
        assert [b.get("compacted", False) for b in bodies] == [True, True, True, False]
        old = bodies[0]
        assert old["result"]["rows_omitted"] == 295 and len(old["result"]["rows"]) == 5
        assert old["warnings"][0]["code"] == "approximation"                    # safety notes survive
        assert old["selection"]["dataset"] == "BIGX" and "NOT re-checked" in old["compaction_note"]
        assert res.budget["context_bytes"] <= 12_000 or len(blocks) == 1
        # the page still gets the complete last table, independent of what the model kept
        assert res.data["row_count"] == 300 or len(res.data["rows"]) == 300

    def test_a_large_real_result_stays_within_the_logical_budget(self, tmp_path, monkeypatch):
        from at01_fixtures import add_dataset
        from test_at01_changes import area_dim, time_dim, unit_dim
        rows = [(f"Localitatea {i:04d}", "2020", "Numar persoane", float(i)) for i in range(2732)]

        def big(corpus):
            add_dataset(corpus, "BIGL", [area_dim([r[0] for r in rows], level="locality"),
                                         time_dim(("2020",)), unit_dim("Numar persoane")], rows,
                        name="Localitati")
        full_env(tmp_path, monkeypatch, extra=(big,))
        res, calls = run(monkeypatch, [call_resp("query_data", {"dataset": "BIGL", "limit": 200}, 0),
                                       text_resp("Sunt multe localități (BIGL).")])
        sent = [b for m in calls[1].messages if isinstance(m.get("content"), list) for b in m["content"]
                if b.get("type") == "tool_result"]
        assert len(sent[0]["content"].encode()) <= 32 * 1024
        assert len(res.data["rows"]) <= 200
        kinds = {link["kind"] for link in res.data["links"]}
        assert kinds & {"csv", "evidence", "live_selection"}                 # the complete data is a link away


# ---------------------------------------------------------------- final synthesis wording

class TestFinalSynthesis:
    def test_the_final_call_lists_the_gaps_and_disables_tools(self, tmp_path, monkeypatch):
        full_env(tmp_path, monkeypatch)
        monkeypatch.setattr(config, "ASK_MAX_ITERATIONS", 2)
        res, calls = run(monkeypatch, lambda n, m, kw:
                         call_resp("query_data", {"dataset": "POPX", "group_by": ["TIME_PERIOD"]}, n)
                         if n == 1 else text_resp("Nu pot da un total sigur."))
        assert calls[1].kw["tool_choice"] == "none"
        assert "final turn" in calls[1].kw["system"] and "query_data → overlapping_levels" in calls[1].kw["system"]
        assert res.outcome in ("refused", "partial")


# ---------------------------------------------------------------- claims and display

class TestClaimsAndDisplay:
    def test_a_claim_is_bound_to_its_cell_entity_period_and_unit(self, tmp_path, monkeypatch):
        full_env(tmp_path, monkeypatch)
        res, _ = run(monkeypatch, [
            call_resp("query_data", {"dataset": "POPC", "group_by": ["REF_AREA", "TIME_PERIOD"]}, 7),
            text_resp("Cluj avea 1010 persoane în 2021. Iași avea 1010 persoane în 2020."),
        ])
        claims = res.verification["claims"]
        assert [c["check"] for c in claims] == ["matched", "unverified"]      # 1010 belongs to Cluj, not Iași
        c = claims[0]
        assert c["tool_call_id"] == "c7" and c["entity"] == "Cluj" and c["period"] == "2021"
        assert c["unit"] == "Numar persoane"
        env = next(t["output"] for t in res.tool_trace if t["id"] == "c7")
        node = env
        for part in c["path"].strip("/").split("/"):                           # JSON Pointer into the result
            node = node[int(part)] if isinstance(node, list) else node[part]
        assert node == 1010.0
        assert claims[1]["tool_call_id"] is None and claims[1]["path"] is None
        assert res.verification["claim_summary"] == {"matched": 1, "unverified": 1}

    def test_a_number_that_exists_in_no_result_has_no_binding(self, tmp_path, monkeypatch):
        full_env(tmp_path, monkeypatch)
        res, _ = run(monkeypatch, [
            call_resp("query_data", {"dataset": "POPC", "group_by": ["REF_AREA", "TIME_PERIOD"]}),
            text_resp("Cluj avea 7777 persoane."),
        ])
        assert res.verification["status"] == "unverified_numbers"
        assert [c["check"] for c in res.verification["claims"]] == ["unverified"]

    def test_change_ranking_is_rendered_as_its_own_table_without_a_chart(self, tmp_path, monkeypatch):
        full_env(tmp_path, monkeypatch)
        res, _ = run(monkeypatch, [
            call_resp("compare_periods", {"dataset": "COUNTX", "entity_columns": ["REF_AREA"],
                                          "intervals": [{"from": "1992", "to": "2002"}]}),
            text_resp("Cea mai mare scădere: B, cu 50 de persoane (COUNTX)."),
        ])
        d = res.data
        assert d["columns"] == ["REF_AREA", "INTERVAL", "FROM_VALUE", "TO_VALUE", "ABSOLUTE", "PERCENT", "RANK"]
        assert d["rows"][0] == ["B", "1992→2002", 200.0, 150.0, -50.0, -25.0, 1]
        assert d["status"] == "partial" and any("excluded" in w for w in d["warnings"])
        assert res.chart_spec is None
        assert res.verification["status"] == "verified"                        # "50" matches a change of -50
        assert res.verification["claims"][0]["check"] == "matched"
        assert res.verification["claims"][0]["path"].endswith("/absolute")

    def test_a_recipe_result_is_a_bounded_table_with_links(self, tmp_path, monkeypatch):
        full_env(tmp_path, monkeypatch)
        res, _ = run(monkeypatch, [
            call_resp("run_recipe", {"recipe": "fx_intensity", "year": "2024"}),
            text_resp("Alfa: 2 (fx_intensity)."),
        ])
        assert res.data["columns"] == ["LABEL", "VALUE"] and res.data["recipe"] == "fx_intensity"
        assert {r[0]: r[1] for r in res.data["rows"]}["Alfa"] == 2.0 and res.chart_spec is None
        assert res.data["links"], "a recipe table links to its evidence"
        assert res.verification["valid_query"] is True                         # recipes count as retrieval

    def test_a_query_table_keeps_every_series_identity_for_the_page(self, tmp_path, monkeypatch):
        full_env(tmp_path, monkeypatch)
        res, _ = run(monkeypatch, [
            call_resp("query_data", {"dataset": "POPC", "group_by": ["REF_AREA", "TIME_PERIOD"]}),
            text_resp("Vezi tabelul (POPC)."),
        ])
        assert res.data["columns"] == ["REF_AREA", "TIME_PERIOD", "OBS_VALUE"]
        assert len(res.data["rows"]) == 6                                       # three counties × two years
        assert {r[0] for r in res.data["rows"]} == {"Cluj", "Iași", "Bihor"}

    def test_clarification_is_an_outcome_of_its_own(self, monkeypatch):
        choice = fake_env("discover_indicators", "needs_clarification", "ambiguous_definition",
                          "Registered or ILO unemployment?",
                          data={"choices": [{"label": "înregistrat"}, {"label": "ILO"}]})
        install(monkeypatch, lambda n, m, kw: tools_resp(1) if n == 1
                else text_resp("Vă referiți la șomajul înregistrat sau la cel ILO?"),
                handler=lambda name, args: choice)
        res = agent.run_agent("Cât este șomajul?", provider="anthropic", api_key="k")
        assert (res.outcome, res.reason) == ("clarification", "ambiguous_definition")
        assert res.data is None and res.verification["status"] == "no_values"


# ---------------------------------------------------------------- debug bounds

def test_debug_events_are_capped_and_the_drop_is_reported(monkeypatch):
    monkeypatch.setattr(config, "ASK_DEBUG", True)
    monkeypatch.setattr(config, "ASK_DEBUG_MAX_EVENTS", 4)
    install(monkeypatch, lambda n, m, kw: tools_resp(3, args={"query": "x" * 5000}) if n == 1
            else text_resp("gata"))
    r = make_client().post("/api/ask", json={"question": "x", "debug": True, "provider": "anthropic",
                                             "model": "claude-sonnet-5-5", "api_key": "k-123456"})
    d = r.json()
    assert len(d["debug"]["events"]) == 4 and d["debug"]["dropped_events"] > 0
    assert d["budget"]["dropped_debug_events"] == d["debug"]["dropped_events"]
    tool_events = [e for e in d["debug"]["events"] if e["event"] == "tool"]
    assert all(len(json.dumps(e)) < 2000 for e in tool_events)          # 5,000-char input was bounded
    call = next(e for e in d["debug"]["events"] if e["event"] == "model_call")
    assert isinstance(call["max_tokens"], int)                          # a count is not mistaken for a secret


def test_the_response_carries_outcome_reason_and_context_next_to_the_legacy_fields(monkeypatch):
    install(monkeypatch, lambda n, m, kw: text_resp("Bună!"))
    d = make_client().post("/api/ask", json={"question": "x", "provider": "anthropic",
                                             "model": "claude-sonnet-5-5", "api_key": "k-123456"}).json()
    for k in ("answer", "citations", "tool_trace", "data", "chart_spec", "warnings", "verification",
              "stop_reason", "budget", "outcome", "reason", "context"):
        assert k in d
    assert d["outcome"] == "answered" and d["reason"] is None and d["context"] == []
