"""PKG-TOOLS probes on the served corpus (read-only), pinned to generation 062bd2b0.

Golden discovery phrases for the births and consumer-price concepts (F2, F5), the national
registered-unemployment route (F3) and the index unit type (F5).
"""
import pytest

from at01_fixtures import call

PINNED = "062bd2b0"


@pytest.fixture
def real():
    from app.services import generation
    gid = str(generation.current().get("id") or "")
    if not gid.startswith(PINNED):
        pytest.skip(f"probe is pinned to generation {PINNED}…, corpus is {gid[:8] or 'unknown'}")
    return gid


def disc(q, lang):
    return call("discover_indicators", query=q, lang=lang)


def card_ids(out):
    return [c["id"] for c in out["data"]["concepts"]]


@pytest.mark.corpus
@pytest.mark.parametrize("q,lang", [
    ("nașteri", "ro"), ("născuți vii", "ro"), ("numărul nașterilor în România", "ro"),
    ("nascuti vii pe ani din 2015", "ro"), ("births", "en"), ("live births", "en"),
])
def test_births_phrases_ask_domicile_or_usual_residence(real, q, lang):
    out = disc(q, lang)
    assert out["status"] == "needs_clarification" and out["reason"] == "ambiguous_definition"
    assert {c["id"] for c in out["data"]["choices"]} == {"live_births_domicile", "live_births_residence"}
    assert set(card_ids(out)) <= {"live_births_domicile", "live_births_residence"}
    datasets = {c["dataset"] for c in out["data"]["choices"]}
    assert datasets <= {"POP201A_judete", "POP201H_judete", "POP201A", "POP201H"}


@pytest.mark.corpus
def test_births_definition_choice_is_runnable(real):
    out = disc("births", "en")
    by_id = {c["id"]: c for c in out["data"]["choices"]}
    assert by_id["live_births_domicile"]["action"]["arguments"]["dataset"] == "POP201A_judete"
    assert by_id["live_births_residence"]["action"]["arguments"]["dataset"] == "POP201H_judete"
    assert all(c["action_status"] == "ready" for c in by_id.values())


@pytest.mark.corpus
@pytest.mark.parametrize("q,lang", [
    ("inflație", "ro"), ("inflatia lunara", "ro"), ("indicele prețurilor de consum", "ro"),
    ("latest monthly inflation rate", "en"), ("inflation", "en"), ("CPI", "en"),
])
def test_inflation_phrases_lead_to_the_monthly_cpi_tables(real, q, lang):
    out = disc(q, lang)
    assert card_ids(out)[0] in ("cpi_previous_month", "cpi_since_december")
    first = out["data"]["concepts"][0]
    assert first["candidates"][0]["dataset"] in ("IPC102A", "IPC102B")
    assert first["unit_type"] == "index"
    if out["reason"] == "ambiguous_definition":
        assert {c["id"] for c in out["data"]["choices"]} == {"cpi_previous_month", "cpi_since_december"}


@pytest.mark.corpus
def test_ipc_tables_report_an_index_not_a_percentage(real):
    for code in ("IPC102A", "IPC102B"):
        d = call("describe_dataset", dataset=code)
        assert d["data"]["unit_type"] == "index" and d["provenance"]["sources"][0]["unit_type"] == "index"
    q = call("query_data", dataset="IPC102A", filters={"TIME_PERIOD": ["2026-05"]}, limit=5)
    assert all(s["unit_type"] == "index" for s in q["provenance"]["sources"])
    # the annual average inflation RATE (IPC101A) stays a percentage
    assert call("describe_dataset", dataset="IPC101A")["data"]["unit_type"] == "percentage"


@pytest.mark.corpus
def test_national_registered_unemployment_is_a_runnable_choice(real):
    out = disc("How did the unemployment rate evolve in Romania in recent years?", "en")
    by_id = {c["id"]: c for c in out["data"]["choices"]}
    reg = by_id["registered_unemployment_rate"]
    assert reg["action_status"] == "ready"
    assert reg["action"] == {"tool": "run_recipe", "arguments": {
        "recipe": "registered_unemployment_county", "lang": "en", "areas": ["TOTAL"]}}
    run = call("run_recipe", **reg["action"]["arguments"])
    assert run["status"] == "ok"
    series = {r["year"]: r["value"] for r in run["data"]["rows"]}
    assert [series[str(y)] for y in range(2018, 2026)] == [3.3, 2.9, 3.4, 3.0, 3.0, 2.9, 3.3, 3.3]
    assert run["provenance"]["sources"][0]["dataset"] == "SOM103A"


@pytest.mark.corpus
def test_total_area_is_not_an_exclusion_any_more(real):
    run = call("run_recipe", recipe="registered_unemployment_county", areas=["TOTAL"], year="2025")
    assert run["status"] == "ok" and run["data"]["exclusion_counts"] == {}
    # counties are unchanged
    cj = call("run_recipe", recipe="registered_unemployment_county", areas=["Cluj"], year="2025")
    assert cj["data"]["rows"][0]["value"] == 1.5
