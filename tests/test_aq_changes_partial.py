"""compare_periods and an unverified domain (owner decision 2026-10-17).

`compare_periods` mirrors `rank_entities`: `partial` / `unverified_total` (plus an `unverified_total`
warning) when the selection's `scope.domain_complete` is null, `partial` / `incomplete_domain` when it
is false, `ok` only when it is true and nothing was excluded. Exclusions alone stay `partial` with no
reason. Values, ranks, eligible counts and exclusions never depend on that verdict.

Synthetic corpora through the real shared services. The three scope verdicts come from the real
aggregation policy, not from a stub:

  UNV*   SEX is collapsed over a partition that only the metadata vouches for -> domain_complete null
  REST*  AGE holds 0 and 1 of a Total (0-999) domain -> false (ages 2 and over are not in the data)
  FULL*  nothing is collapsed -> true

`*X` also holds entity D with no 2020 row (one exclusion); `*C` is A, B, C only (no exclusion).

    entity   2010   2020   change
    A         100     60      -40
    B         200    150      -50
    C          50     80      +30
    D          70      -   (no_observation)
"""
import json
import zipfile
import io

import pytest

from at01_fixtures import add_dataset, call, make_env, said
from at02_env import call_resp, full_env, run
from at03_env import make_app, payload, started, session
from fix08_helpers import text_resp
from test_at01_changes import area_dim, iv, open_zip, real, recompute, time_dim, unit_dim  # noqa: F401
import test_aq05a_city_changes as t05a
from app import config
from app.services import agent, ask_present
from app.services.tools import registry as R

UNIT = "Numar persoane"
YEARS = ("2010", "2020")
TOTALS = {"A": (100.0, 60.0), "B": (200.0, 150.0), "C": (50.0, 80.0), "D": (70.0, None)}
CLEAN = {k: v for k, v in TOTALS.items() if k != "D"}
WANT_ASC = [("B", -50.0, 1), ("A", -40.0, 2), ("C", 30.0, 3)]


def _rows(table, parts):
    """One row per entity, part and year; every value is split evenly so each total is exact."""
    out = []
    for e, vals in table.items():
        for y, v in zip(YEARS, vals):
            if v is None:
                continue
            out += [(e, p, y, UNIT, v / len(parts)) if p else (e, y, UNIT, v) for p in parts]
    return out


def _add(corpus, code, table, extra_dim=None, parts=(None,)):
    dims = [area_dim(list(table))] + ([extra_dim] if extra_dim else []) + [time_dim(YEARS), unit_dim(UNIT)]
    add_dataset(corpus, code, dims, _rows(table, parts), name=code)


SEX = ("SEX", "Sexe", "gender", [("Masculin", dict(gender="M")), ("Feminin", dict(gender="F"))])
AGE = ("AGE", "Varsta", "age", [("Total", dict(age_min=0, age_max=999)),
                                 ("0 ani", dict(age_min=0, age_max=0)), ("1 ani", dict(age_min=1, age_max=1))])


def build(corpus):
    for suffix, table in (("X", TOTALS), ("C", CLEAN)):
        _add(corpus, "UNV" + suffix, table, SEX, ("Masculin", "Feminin"))
        _add(corpus, "REST" + suffix, table, AGE, ("0 ani", "1 ani"))
        _add(corpus, "FULL" + suffix, table)


@pytest.fixture
def env(tmp_path, monkeypatch):
    return make_env(tmp_path, monkeypatch, build=build)


def cp(code, **kw):
    kw.setdefault("entity_columns", ["REF_AREA"])
    kw.setdefault("intervals", [iv(*YEARS)])
    kw.setdefault("lang", "en")
    return call("compare_periods", dataset=code, **kw)


def rows_of(e):
    return [(r["entity"]["REF_AREA"], r["absolute"], r["rank"]) for r in e["data"]["intervals"][0]["rows"]]


def codes(e):
    return [w["code"] for w in e["warnings"]]


# ============================================================ the verdict -> status table

@pytest.mark.parametrize("code,complete,status,reason,excluded", [
    ("UNVC", None, "partial", "unverified_total", False),
    ("UNVX", None, "partial", "unverified_total", True),        # both apply: the domain reason wins, both warnings stay
    ("RESTC", False, "partial", "incomplete_domain", False),
    ("RESTX", False, "partial", "incomplete_domain", True),
    ("FULLC", True, "ok", None, False),
    ("FULLX", True, "partial", None, True),                     # exclusions alone: partial, no reason, as before
])
def test_status_and_reason_follow_the_domain_verdict(env, code, complete, status, reason, excluded):
    e = cp(code)
    assert e["provenance"]["scope"]["domain_complete"] is complete        # the real policy's verdict
    assert (e["status"], e["reason"]) == (status, reason)
    assert ("unverified_total" in codes(e)) is (complete is None)
    assert ("incomplete_domain" in codes(e)) is (complete is False)        # a proven gap is a warning too (2026-10-18)
    assert ("entities_excluded" in codes(e)) is excluded
    assert codes(e).count("unverified_total") <= 1
    # the numbers are the fixture's, whatever the verdict
    i = e["data"]["intervals"][0]
    assert rows_of(e) == WANT_ASC
    assert (i["eligible_count"], i["excluded_count"]) == (3, 1 if excluded else 0)
    assert e["limits"]["total_rows"] == 3 and e["limits"]["preview_truncated"] is False


def test_the_unverified_message_and_warning_say_what_is_unverified(env):
    e = cp("UNVC")
    w = next(x for x in e["warnings"] if x["code"] == "unverified_total")
    assert w["message"].startswith("The completeness of the collapsed domain behind these endpoint values is unverified")
    assert "official complete total" in w["message"]
    assert "Domain completeness is unverified, so these are not changes of an official complete total." in e["message"]
    assert e["provenance"]["scope"]["description"] == "Domain completeness cannot be verified"
    assert "Restricted domain" not in e["message"]                         # that sentence is for `false`
    ok, restricted = cp("FULLC"), cp("RESTC")
    assert "unverified" not in ok["message"] and "unverified" not in restricted["message"]
    assert "Restricted domain: Ages 0–1 (2 and over not included)" in restricted["message"]
    w = next(x for x in restricted["warnings"] if x["code"] == "incomplete_domain")
    assert "Ages 0–1 (2 and over not included)" in w["message"] and "Do not present it as one" in w["message"]


def test_the_texts_follow_the_language(env):
    e = cp("UNVC", lang="ro")
    w = next(x for x in e["warnings"] if x["code"] == "unverified_total")
    assert w["message"].startswith("Completitudinea domeniului colapsat din spatele valorilor de la capete nu este verificată")
    assert "Completitudinea domeniului nu este verificată" in e["message"]
    assert (e["status"], e["reason"]) == ("partial", "unverified_total")   # codes are language-neutral
    en = cp("UNVC")
    assert [x["code"] for x in e["warnings"]] == [x["code"] for x in en["warnings"]]
    assert said(e["message"], "ro", "unverified", "nu este verificată")


def test_no_ranked_entity_is_still_unavailable_not_unverified(env):
    e = cp("UNVX", filters={"REF_AREA": ["D"]})                            # D has no 2020 row
    assert (e["status"], e["reason"]) == ("unavailable", "no_eligible_entities")
    assert e["data"]["intervals"][0]["eligible_count"] == 0


# ============================================================ values do not depend on the verdict

def test_the_same_values_under_every_verdict_differ_only_in_status_reason_warnings_and_scope(env, monkeypatch):
    import app.services.data_query as dq
    real = dq.run_query
    out = {}
    for verdict in (True, None, False):
        def with_scope(*a, _v=verdict, **k):
            res = real(*a, **k)
            res["scope"] = {"domain_complete": _v, "restrictions": []}
            return res
        monkeypatch.setattr(dq, "run_query", with_scope)
        out[verdict] = cp("FULLX", top_k=2)                                # cut to two rows: still ranked over 3
    assert [(out[v]["status"], out[v]["reason"]) for v in (True, None, False)] == [
        ("partial", None), ("partial", "unverified_total"), ("partial", "incomplete_domain")]

    def stripped(e):
        e = json.loads(json.dumps(e))
        for k in ("status", "reason", "message", "warnings"):
            e.pop(k)
        e["provenance"].pop("scope")
        e["recovery"] = [r for r in e["recovery"]]
        return json.dumps(e, sort_keys=True)
    assert stripped(out[None]) == stripped(out[True]) == stripped(out[False])        # byte-identical
    assert out[None]["limits"]["total_rows"] == 3 and out[None]["limits"]["preview_truncated"] is True
    base = {c for c in codes(out[True])}
    assert set(codes(out[None])) - base == {"unverified_total"}
    assert set(codes(out[False])) - base == {"incomplete_domain"}         # mirrors rank_entities (2026-10-18)


def test_the_fixture_values_are_the_same_across_the_three_datasets(env):
    got = [rows_of(cp(c)) for c in ("UNVC", "RESTC", "FULLC")]
    assert got[0] == got[1] == got[2] == WANT_ASC
    pct = [[r["percent"] for r in cp(c, metric="percent")["data"]["intervals"][0]["rows"]]
           for c in ("UNVC", "RESTC", "FULLC")]
    assert pct[0] == pct[1] == pct[2] == [-40.0, -25.0, 60.0]      # A -40/100, B -50/200, C +30/50


def test_the_default_for_a_verified_domain_is_untouched(env):
    e = cp("FULLC")
    assert (e["status"], e["reason"]) == ("ok", None)
    assert codes(e) == ["boundary_continuity_unverified"]
    assert e["provenance"]["scope"] == {"description": "Complete domain", "domain_complete": True, "limitations": []}


# ============================================================ city class

def test_the_city_class_carries_the_verdict_and_ranks_the_same_cities(tmp_path, monkeypatch):
    import app.services.data_query as dq
    make_env(tmp_path, monkeypatch, build=t05a.build_chg)
    real = dq.run_query
    out = {}
    for verdict in (True, None):
        def with_scope(*a, _v=verdict, **k):
            res = real(*a, **k)
            res["scope"] = {"domain_complete": _v, "restrictions": []}
            return res
        monkeypatch.setattr(dq, "run_query", with_scope)
        out[verdict] = t05a.cities(top_k=3)
    t, n = out[True], out[None]
    assert (t["status"], t["reason"]) == ("partial", None)                 # GONE and NULLED are excluded
    assert (n["status"], n["reason"]) == ("partial", "unverified_total")
    assert set(codes(n)) - set(codes(t)) == {"unverified_total"}
    assert {"classification_reference", "entities_excluded", "unverified_total"} <= set(codes(n))
    assert n["data"] == t["data"] and n["limits"] == t["limits"]
    iv0 = n["data"]["intervals"][0]
    assert iv0["eligible_count"] == 233 and n["data"]["outside_class_count"] == 2
    assert [(t05a.loc_of(r), r["absolute"]) for r in iv0["rows"]] == [
        (t05a.city(229), -229.0), (t05a.city(228), -228.0), (t05a.city(227), -227.0)]
    assert "classification" in n["provenance"] and n["provenance"]["classification"] == t["provenance"]["classification"]
    assert "Domain completeness is unverified" in n["message"] and "Domain completeness is unverified" not in t["message"]


# ============================================================ REST, evidence bundle, links and replay

def params(code, **kw):
    p = {"dataset": code, "entity_columns": json.dumps(["REF_AREA"]), "intervals": json.dumps([iv(*YEARS)]),
         "lang": "en"}
    p.update({k: v if isinstance(v, str) else json.dumps(v) for k, v in kw.items()})
    return p


def test_rest_returns_the_same_partial_envelope(env):
    r = env.client.get("/api/period-changes", params=params("UNVX"))
    assert r.status_code == 200
    body = r.json()
    assert (body["status"], body["reason"]) == ("partial", "unverified_total")
    assert body == cp("UNVX")
    assert {"entities_excluded", "unverified_total"} <= set(codes(body))
    ok = env.client.get("/api/period-changes", params=params("FULLC")).json()
    assert (ok["status"], ok["reason"]) == ("ok", None)


def test_the_evidence_bundle_of_an_unverified_domain_is_certified_and_records_the_verdict(env, tmp_path):
    r = env.client.get("/api/period-changes/evidence", params=params("UNVX"))
    assert r.status_code == 200                                              # partial is certifiable, not a 422
    z, m = open_zip(r.content)
    method = json.loads(z.read("method.json"))
    assert method["scope"]["domain_complete"] is None
    assert {"entities_excluded", "unverified_total"} <= {w["code"] for w in method["warnings"]}
    z.extractall(tmp_path)
    assert recompute(tmp_path).returncode == 0                               # same numbers, offline
    res = [line.split(",") for line in z.read("result.csv").decode().strip().splitlines()[1:]]
    assert [(x[3], x[6], x[2]) for x in res] == [("B", "-50.0", "1"), ("A", "-40.0", "2"), ("C", "30.0", "3")]
    exc = z.read("exclusions.csv").decode().strip().splitlines()[1:]
    assert len(exc) == 1 and ",D,no_observation," in exc[0]


def test_the_evidence_links_replay_to_the_same_partial_result(env):
    e = cp("UNVX", lang="ro")
    links = call("get_evidence_links", selection=e["provenance"]["selection"],
                 generation_id=e["provenance"]["generation"]["id"], lang="ro")
    assert links["status"] == "ok"
    live = next(link["url"] for link in links["data"]["links"] if link["kind"] == "live_selection")
    rep = env.client.get(live).json()
    assert (rep["status"], rep["reason"]) == ("partial", "unverified_total")
    assert rep["data"] == e["data"] and rep["warnings"] == e["warnings"]       # same values, same disclosure
    ev = next(link["url"] for link in links["data"]["links"] if link["kind"] == "evidence")
    assert env.client.get(ev).status_code == 200


# ============================================================ MCP and Ask

def test_mcp_returns_the_same_partial_envelope(tmp_path, monkeypatch):
    import asyncio
    app, mcp = make_app(tmp_path, monkeypatch, env=full_env(tmp_path, monkeypatch, extra=(build,)))
    args = {"dataset": "UNVX", "entity_columns": ["REF_AREA"], "intervals": [iv(*YEARS)]}
    direct = R.call_tool("compare_periods", args)

    async def go():
        async with started(app), session(app) as s:
            return await s.call_tool("compare_periods", args)
    res = asyncio.run(go())
    structured, text = payload(res)
    assert structured == text == direct
    assert (structured["status"], structured["reason"]) == ("partial", "unverified_total")
    assert res.isError is False                                               # partial is a usable result
    R.validate_result("compare_periods", structured)


@pytest.fixture
def ask_on(monkeypatch):
    monkeypatch.setattr(config, "ASK_ENABLED", True)
    monkeypatch.setattr(config, "ASK_BYOK_ENABLED", True)
    monkeypatch.setattr(agent, "RETRY_PAUSE_SECONDS", 0.0)


def test_an_ask_turn_treats_the_period_change_like_the_ranking(tmp_path, monkeypatch, ask_on):
    """Same unverified domain, same page: the table is partial with the scope note and the warning,
    and the turn's outcome is the one a rank_entities turn gets (the tool status does not change it)."""
    full_env(tmp_path, monkeypatch, extra=(build,))
    change = {"dataset": "UNVC", "entity_columns": ["REF_AREA"], "intervals": [iv(*YEARS)], "lang": "ro"}
    rank = {"dataset": "UNVC", "entity_columns": ["REF_AREA"], "year": "2020", "lang": "ro"}
    res_c, _ = run(monkeypatch, [call_resp("compare_periods", change, 0), text_resp("B scade cel mai mult.")],
                   question="Care județ a scăzut cel mai mult între 2010 și 2020?")
    res_r, _ = run(monkeypatch, [call_resp("rank_entities", rank, 0), text_resp("B este cel mai mare.")],
                   question="Care județ este cel mai mare în 2020?")
    t_c, t_r = res_c.data, res_r.data
    assert (t_c["tool"], t_c["status"]) == ("compare_periods", "partial")
    assert (t_r["tool"], t_r["status"]) == ("rank_entities", "partial")
    assert t_c["scope"]["domain_complete"] is None and t_r["scope"]["domain_complete"] is None
    assert t_c["ranked"] is True and t_c["eligible_count"] == 3
    assert any("Completitudinea domeniului colapsat" in w for w in t_c["warnings"])
    assert any("Completitudinea domeniului colapsat" in w for w in res_c.warnings)    # what the page lists
    assert any("Nu se poate verifica dacă domeniul este complet" in w for w in res_r.warnings)   # the ranking's own words
    assert (res_c.outcome, res_c.reason) == (res_r.outcome, res_r.reason)
    # the display table is built from the tool's envelope alone
    env_ = res_c.tool_trace[0]["output"]
    table = ask_present.display_table([{"id": "c", "tool": "compare_periods", "input": {}, "output": env_}], "ro")
    assert table["status"] == "partial" and table["rows"][0][:2] == ["B", "2010→2020"]


# ============================================================ real corpus (read-only, generation-pinned)

@pytest.mark.corpus
def test_real_city_decline_and_a_county_change_are_partial_with_the_numbers_they_always_had(real):
    """POP107D_grupe_localitate (AGE and SEX collapsed, domain unverified) and POP105A (SEX and RESIDENCE):
    `ok` before the decision, now partial/unverified_total; every value, rank and count is the one the
    AQ-05A and AT-01e records published."""
    city = R.call_tool("compare_periods", {
        "dataset": "POP107D_grupe_localitate", "entity_columns": ["REF_AREA", "REF_AREA_2"],
        "intervals": [iv("2015", "2020")], "entity_class": "cities", "top_k": 3, "lang": "en"})
    assert (city["status"], city["reason"]) == ("partial", "unverified_total")
    assert city["provenance"]["scope"]["domain_complete"] is None
    assert {"classification_reference", "unverified_total"} <= set(codes(city))
    i = city["data"]["intervals"][0]
    assert (i["eligible_count"], i["excluded_count"], city["data"]["outside_class_count"]) == (319, 0, 2862)
    assert [(r["entity"]["REF_AREA_2"], r["from_value"], r["to_value"], r["absolute"]) for r in i["rows"]] == [
        ("42682 MUNICIPIUL BRAILA", 213169.0, 200342.0, -12827.0),
        ("130534 MUNICIPIUL PLOIESTI", 235114.0, 225171.0, -9943.0),
        ("155243 MUNICIPIUL TIMISOARA", 333998.0, 325583.0, -8415.0)]
    county = R.call_tool("compare_periods", {"dataset": "POP105A", "entity_columns": ["REF_AREA"],
                                             "intervals": [iv("2012", "2021")], "top_k": 3, "lang": "en"})
    assert (county["status"], county["reason"]) == ("partial", "unverified_total")
    assert county["data"]["intervals"][0]["eligible_count"] == 42
    assert [r["absolute"] for r in county["data"]["intervals"][0]["rows"]] == [-58119.0, -58085.0, -53623.0]
