"""FIX-02 phase 2 / FIX-08 item 7 (reworked by AT-02): the Ask agent keeps aggregation outcomes.

The agent now calls the seven shared tools, so these tests run the real tools against the
synthetic corpus (decisions are the real ones) and mock only the provider.
"""
import pytest

from at01_fixtures import add_search_columns, make_env
from fix08_helpers import text_resp
from app import config
from app.services import agent, answer_check
from app.services.llm_client import LLMResponse


@pytest.fixture
def env(tmp_path, monkeypatch):
    make_env(tmp_path, monkeypatch, build=add_search_columns)
    monkeypatch.setattr(agent, "RETRY_PAUSE_SECONDS", 0.0)
    return monkeypatch


def query_resp(code, group_by=None, filters=None, i=0, approximate=None):
    inp = {"dataset": code}
    if group_by:
        inp["group_by"] = group_by
    if filters:
        inp["filters"] = filters
    if approximate is not None:
        inp["approximate"] = approximate
    return LLMResponse(stop_reason="tool_use", text=None, finish="tool_use",
                       tool_calls=[{"id": f"q{i}", "name": "query_data", "input": inp}])


def run(env, responses, question="Care este populatia?"):
    seq = iter(responses)
    seen = []

    def fake(messages, tools, **kw):
        seen.append([m for m in messages])
        return next(seq)

    env.setattr(agent, "complete_with_tools", fake)
    return agent.run_agent(question, provider="anthropic", api_key="k"), seen


def tool(name, **args):
    from app.services.tools.registry import call_tool
    return call_tool(name, args)


# ------------------------------------------------------------ tool results

def test_unavailable_result_is_structured_and_has_no_rows(env):
    r = tool("query_data", dataset="POPX", group_by=["TIME_PERIOD"])
    assert r["status"] == "unavailable" and r["data"]["rows"] == []
    assert r["reason"] == "overlapping_levels"
    assert r["provenance"]["aggregation"]["outcome"] == "unavailable"
    assert r["provenance"]["aggregation"]["blocking_dimension"] == "AGE"


def test_approximation_is_opt_in(env):
    # PA-01a: same default as REST — no unweighted mean unless asked for.
    r = tool("query_data", dataset="RATEX", group_by=["TIME_PERIOD"])
    assert r["status"] == "unavailable" and r["data"]["rows"] == [] and r["reason"] == "missing_weights"


def test_approximation_result_is_labelled(env):
    r = tool("query_data", dataset="RATEX", group_by=["TIME_PERIOD"], approximate=True)
    assert r["status"] == "ok" and r["provenance"]["aggregation"]["approximation"] is True
    assert any(w["code"] == "approximation" for w in r["warnings"])
    assert {row[0]: row[1] for row in r["data"]["rows"]}["2023"] == pytest.approx(15.0)


def test_total_pin_is_reported_and_values_not_double_counted(env):
    r = tool("query_data", dataset="ADDX", group_by=["TIME_PERIOD"])
    assert r["status"] == "ok"
    assert {row[0]: row[1] for row in r["data"]["rows"]} == {"2022": 100.0, "2023": 120.0}
    assert r["provenance"]["effective_selection"]["filters"].get("CATEGORY")


# ------------------------------------------------- final-answer guarantees

def test_answer_without_valid_query_cannot_claim_values(env):
    # the model hits an unavailable total, then states a (double-counted) figure anyway
    res, seen = run(env, [
        query_resp("POPX", ["TIME_PERIOD"]),
        text_resp("In 2025 populatia a fost de 242 000 persoane (POPX)."),
    ])
    assert "242" not in res.answer
    assert res.verification["status"] == "values_withheld"
    assert res.verification["valid_query"] is False
    assert res.verification["unavailable"][0]["reason"] == "overlapping_levels"
    assert (res.outcome, res.reason) == ("refused", "no_valid_query")
    assert any("withheld" in w.lower() for w in res.warnings)
    # the model really was told why (structured tool result in its history)
    tool_msgs = [m for m in seen[-1] if isinstance(m.get("content"), list)]
    assert "overlapping_levels" in str(tool_msgs)


def test_answer_with_no_numbers_and_no_query_is_kept(env):
    res, _ = run(env, [text_resp("Nu pot raspunde la aceasta intrebare.")])
    assert res.answer.startswith("Nu pot")
    assert res.verification["status"] == "no_values"
    assert (res.outcome, res.reason) == ("answered", None)


def test_valid_query_verified_numbers_pass(env):
    res, _ = run(env, [
        query_resp("ADDX", ["TIME_PERIOD"]),
        text_resp("Productia a fost 120 in 2023, fata de 100 in 2022 (ADDX)."),
    ])
    assert res.verification["status"] == "verified"
    assert res.verification["uncited_numbers"] == []
    assert res.answer.startswith("Productia")
    cite = next(c for c in res.citations if c["matrix_code"] == "ADDX")
    q0 = cite["queries"][0]
    assert q0["outcome"] == "valid_total" and q0["method"] == "aggregate_row"
    assert q0["approximation"] is False and q0["tool"] == "query_data"
    assert (res.outcome, res.reason) == ("answered", None)
    # the displayed table is the tool's, byte for byte, with the dataset it came from
    assert res.data["matrix_code"] == "ADDX" and res.data["columns"] == ["TIME_PERIOD", "OBS_VALUE"]
    assert sorted(res.data["rows"]) == [["2022", 100.0], ["2023", 120.0]]


def test_uncited_number_is_flagged(env):
    res, _ = run(env, [
        query_resp("ADDX", ["TIME_PERIOD"]),
        text_resp("Productia a fost 120 in 2023 si 987 654 in total cumulat (ADDX)."),
    ])
    assert res.verification["status"] == "unverified_numbers"
    assert any("987" in n for n in res.verification["uncited_numbers"])
    assert any("987" in w for w in res.warnings)
    assert res.answer.startswith("Productia")        # flagged, not rewritten


def test_approximation_is_never_relabelled_as_official(env):
    res, _ = run(env, [
        query_resp("RATEX", ["TIME_PERIOD"], approximate=True),
        text_resp("Rata somajului la nivel national in 2023 a fost 15% (RATEX)."),
    ], question="Care este rata somajului?")
    assert res.verification["approximations"] == ["RATEX"]
    assert "medie neponderată" in res.answer and "aproximare" in res.answer
    assert any("APPROXIMATION" in w for w in res.warnings)
    cite = next(c for c in res.citations if c["matrix_code"] == "RATEX")
    assert cite["queries"][0]["approximation"] is True
    assert cite["queries"][0]["outcome"] == "approximation"
    assert cite["queries"][0]["status"] == "approximation"


def test_model_that_qualifies_the_approximation_is_not_annotated_twice(env):
    res, _ = run(env, [
        query_resp("RATEX", ["TIME_PERIOD"], approximate=True),
        text_resp("Aproximativ 15% (medie neponderată, aproximare) (RATEX)."),
    ], question="Care este rata somajului?")
    assert "Notă:" not in res.answer


def test_explicit_slice_after_unavailable_recovers(env):
    res, _ = run(env, [
        query_resp("POPX", ["TIME_PERIOD"], i=0),
        query_resp("POPX", ["TIME_PERIOD"], {"AGE": ["0-4 ani"]}, i=1),
        text_resp("Pentru grupa 0-4 ani: 110 in 2025 (POPX)."),
    ])
    assert res.verification["valid_query"] is True
    assert res.verification["status"] == "verified"
    assert len(res.verification["unavailable"]) == 1


# --------------------------------------------------------- pure checker

@pytest.mark.parametrize("text,vals,expected", [
    ("19,0 milioane de locuitori", [19012345.0], []),
    ("19.012.345 persoane", [19012345.0], []),
    ("19,012,345 people", [19012345.0], []),
    ("rata de 5,2%", [5.2], []),
    ("rata de 7,9%", [5.2], ["7,9 %"]),
    ("in 2023 (AMG159E) au fost 3 regiuni", [100.0], []),
    ("o scădere de 50 de persoane", [-50.0], []),          # a decline matches a change of -50
])
def test_number_matching(text, vals, expected):
    res = [{"rows": [[2023, v] for v in vals]}]
    assert answer_check.uncited_numbers(text, res) == expected


def test_numbers_from_the_question_are_not_claims():
    assert answer_check.find_numbers("Pentru 5000 de persoane", "ai 5000 de persoane?") == []
