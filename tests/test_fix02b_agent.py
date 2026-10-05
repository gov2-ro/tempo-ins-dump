"""FIX-02 phase 2 / FIX-08 item 7: the Ask agent keeps aggregation outcomes.

Everything provider-facing is mocked; tool handlers run against the synthetic
corpus so decisions are the real ones.
"""
import pytest

from fix02b_corpus import make_client
from fix08_helpers import text_resp
from app.services import agent, answer_check
from app.services.llm_client import LLMResponse


@pytest.fixture
def env(tmp_path, monkeypatch):
    make_client(tmp_path, monkeypatch)
    from app.db import get_conn
    monkeypatch.setattr(agent, "get_conn", get_conn)
    return monkeypatch


def query_resp(code, group_by=None, filters=None, i=0):
    inp = {"matrix_code": code}
    if group_by:
        inp["group_by"] = group_by
    if filters:
        inp["filters"] = filters
    return LLMResponse(stop_reason="tool_use", text=None,
                       tool_calls=[{"id": f"q{i}", "name": "query_dataset_data", "input": inp}])


def run(env, responses, question="Care este populatia?"):
    seq = iter(responses)
    seen = []

    def fake(messages, tools, **kw):
        seen.append([m for m in messages])
        return next(seq)

    env.setattr(agent, "complete_with_tools", fake)
    return agent.run_agent(question, provider="anthropic", api_key="k"), seen


# ------------------------------------------------------------ tool results

def test_unavailable_result_is_structured_and_has_no_rows(env):
    from app.db import get_conn
    r = agent._handle_query_dataset_data(
        {"matrix_code": "POPX", "group_by": ["TIME_PERIOD"]}, get_conn())
    assert r["status"] == "unavailable" and r["rows"] == [] and "error" not in r
    assert r["reason"] == "overlapping_levels" and r["blocking_dimension"] == "AGE"
    assert r["aggregation"]["outcome"] == "unavailable"
    assert any("UNAVAILABLE" in w for w in r["warnings"])
    assert "AGE" in r["suggestion"]


def test_approximation_result_is_labelled(env):
    from app.db import get_conn
    r = agent._handle_query_dataset_data(
        {"matrix_code": "RATEX", "group_by": ["TIME_PERIOD"]}, get_conn())
    assert r["status"] == "approximation"
    assert r["aggregation"]["approximation"] is True
    assert any("APPROXIMATION" in w for w in r["warnings"])
    assert {row[0]: row[1] for row in r["rows"]}["2023"] == pytest.approx(15.0)


def test_total_pin_is_reported_and_values_not_double_counted(env):
    from app.db import get_conn
    r = agent._handle_query_dataset_data(
        {"matrix_code": "ADDX", "group_by": ["TIME_PERIOD"]}, get_conn())
    assert r["status"] == "ok"
    assert {row[0]: row[1] for row in r["rows"]} == {"2022": 100.0, "2023": 120.0}
    assert any("Auto-applied" in w for w in r["warnings"])


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
    assert any("withheld" in w.lower() for w in res.warnings)
    assert any("UNAVAILABLE" in w for w in res.warnings)
    # the model really was told why (structured tool result in its history)
    tool_msgs = [m for m in seen[-1] if isinstance(m.get("content"), list)]
    assert "overlapping_levels" in str(tool_msgs)


def test_answer_with_no_numbers_and_no_query_is_kept(env):
    res, _ = run(env, [text_resp("Nu pot raspunde la aceasta intrebare.")])
    assert res.answer.startswith("Nu pot")
    assert res.verification["status"] == "no_values"


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
    assert q0["approximation"] is False


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
        query_resp("RATEX", ["TIME_PERIOD"]),
        text_resp("Rata somajului la nivel national in 2023 a fost 15% (RATEX)."),
    ], question="Care este rata somajului?")
    assert res.verification["approximations"] == ["RATEX"]
    assert "medie neponderată" in res.answer and "aproximare" in res.answer
    assert any("APPROXIMATION" in w for w in res.warnings)
    cite = next(c for c in res.citations if c["matrix_code"] == "RATEX")
    assert cite["queries"][0]["approximation"] is True
    assert cite["queries"][0]["outcome"] == "approximation"


def test_model_that_qualifies_the_approximation_is_not_annotated_twice(env):
    res, _ = run(env, [
        query_resp("RATEX", ["TIME_PERIOD"]),
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
])
def test_number_matching(text, vals, expected):
    res = [{"rows": [[2023, v] for v in vals]}]
    assert answer_check.uncited_numbers(text, res) == expected


def test_numbers_from_the_question_are_not_claims():
    assert answer_check.find_numbers("Pentru 5000 de persoane", "ai 5000 de persoane?") == []
