"""PKG-TOOLS F1 on the served corpus (read-only), pinned to generation 062bd2b0."""
import pytest

from at01_fixtures import call
from test_audit_tools_corpus import real  # noqa: F401  (fixture)


def vintage(env_):
    return [w for w in env_["warnings"] if w["code"] == "newer_vintage"]


@pytest.mark.corpus
def test_births_2024_names_the_newer_table(real):
    q = call("query_data", dataset="POP201A_judete", filters={"TIME_PERIOD": ["2024"]}, group_by=["TIME_PERIOD"],
             lang="en")
    assert q["data"]["rows"][0][-1] == 148916.0
    w = vintage(q)[0]["message"]
    assert "POP201D" in w and "2025-10-14" in w and "2026-09-09" in w
    new = call("query_data", dataset="POP201D_localitate", filters={"TIME_PERIOD": ["2024"]},
               group_by=["TIME_PERIOD"], lang="en")
    assert new["data"]["rows"][0][-1] == 157270.0 and not vintage(new)


@pytest.mark.corpus
def test_domicile_population_2025_names_the_newer_table(real):
    q = call("query_data", dataset="POP107A_judete_grupe", filters={"TIME_PERIOD": ["2025"]},
             group_by=["TIME_PERIOD"], lang="ro")
    w = vintage(q)[0]["message"]
    assert "POP107D" in w and "2025-10-01" in w and "2026-10-02" in w
    assert not vintage(call("describe_dataset", dataset="POP107D"))
    assert vintage(call("describe_dataset", dataset="POP107A"))


@pytest.mark.corpus
def test_unrelated_dataset_has_no_vintage_warning(real):
    q = call("query_data", dataset="POP105A_judete_grupe", filters={"TIME_PERIOD": ["2025"]},
             group_by=["TIME_PERIOD"])
    assert not vintage(q)
