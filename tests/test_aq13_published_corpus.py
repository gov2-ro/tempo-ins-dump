"""AQ-13 on the copied generation that holds the published cells (skipped without it)."""
import pytest
from at01_fixtures import call

from app.services import recipes


@pytest.fixture
def real():
    from app.db import get_conn
    from app.services import generation
    if not str(generation.current().get("id") or ""):
        pytest.skip("no served corpus generation")
    for m in ("TCP0341", "POP209B", "IPC102A", "FOM107E", "SOM103A", "CON103H", "AMG157A"):
        if not recipes._pt_query(get_conn(), "matrix_code = ? LIMIT 1", [m]):
            pytest.skip("the generation holds no published cells for " + m)


def values(e):
    return {tuple(r[:-2]): r[-1] for r in e["data"]["rows"]}


@pytest.mark.corpus
def test_corpus_the_indicators_return_the_values_checked_against_ins(real):
    # each value was re-requested from INS's pivot service as a single cell (aq-13-record.md)
    le = call("query_data", dataset="TCP0341_judete", filters={"TIME_PERIOD": ["2023"]},
              group_by=["TIME_PERIOD", "SEX"])
    assert le["status"] == "ok" and values(le)[("TOTAL", "2023", "Feminin")] == 79.15
    both = call("query_data", dataset="TCP0341_judete", filters={"TIME_PERIOD": ["2023"]}, group_by=["TIME_PERIOD"])
    assert values(both) == {("TOTAL", "2023"): 75.5}
    inf = call("query_data", dataset="POP209B_judete", filters={"REF_AREA": ["Cluj"], "TIME_PERIOD": ["2024"]},
               group_by=["TIME_PERIOD"])
    assert values(inf) == {("Cluj", "2024"): 6.4}
    cpi = call("query_data", dataset="IPC102A", filters={"CATEGORY": ["Total"], "TIME_PERIOD": ["2024-01"]})
    assert cpi["status"] == "ok" and values(cpi) == {("TOTAL", "2024-01"): 101.1}
    gross = call("query_data", dataset="FOM107E_judete", filters={"REF_AREA": ["Cluj"], "TIME_PERIOD": ["2024"]},
                 group_by=["TIME_PERIOD"])
    assert values(gross) == {("Cluj", "2024"): 9636.0}
    unemp = call("query_data", dataset="SOM103A_judete", filters={"SEX": ["Feminin"], "TIME_PERIOD": ["2025"]},
                 group_by=["TIME_PERIOD"])
    assert values(unemp) == {("TOTAL", "2025", "Feminin"): 3.5}
    ilo = call("query_data", dataset="AMG157A_anual", filters={"SEX": ["Masculin"], "TIME_PERIOD": ["2024"]},
               group_by=["TIME_PERIOD"])
    assert values(ilo) == {("TOTAL", "2024", "Masculin"): 5.7}
    gdp = call("query_data", dataset="CON103H_judete", filters={"TIME_PERIOD": ["2022"]}, group_by=["TIME_PERIOD"])
    assert values(gdp) == {("TOTAL", "2022"): 72669.5}


@pytest.mark.corpus
def test_corpus_a_county_ranking_of_a_dropped_total_ranks_ins_cells_and_the_country_sits_beside(real):
    r = call("rank_entities", dataset="FOM107E_judete", entity_columns=["REF_AREA"], year="2024", top_k=3)
    assert r["data"]["value_source"] == "ins_published"
    assert r["data"]["rows"][0]["entity"]["REF_AREA"] == "Municipiul Bucuresti" and r["data"]["rows"][0]["value"] == 11002.0
    assert r["data"]["aggregates"][0]["entity"] == {"REF_AREA": "TOTAL"}
    assert len(r["data"]["rows"]) == 3 and r["data"]["eligible_count"] == 42
    # a ranking from the file keeps its own rows, with the country beside them
    g = call("rank_entities", dataset="CON103H_judete", entity_columns=["REF_AREA"], year="2022", top_k=2)
    assert "value_source" not in g["data"] and g["data"]["aggregates"][0]["value"] == 72669.5
