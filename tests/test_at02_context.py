"""AT-02: follow-up selections (untrusted input, validated, re-run) and bounded model context."""
import json

import pytest

from at01_fixtures import write_manifest
from at02_env import call_resp, full_env, scripted
from fix08_helpers import make_client, text_resp
from app import config
from app.services import ask_context as X
from app.services import agent


@pytest.fixture(autouse=True)
def _ask_on(monkeypatch):
    monkeypatch.setattr(config, "ASK_ENABLED", True)
    monkeypatch.setattr(config, "ASK_BYOK_ENABLED", True)


GEN = {"id": "gen-at01-fixture", "status": "present"}


def sel(dataset="POPC", **kw):
    return {"kind": "dataset", "dataset": dataset, "filters": {}, "group_by": [], "approximate": False, **kw}


def entry(tool="query_data", selection=None, generation="gen-at01-fixture", **extra):
    return {"tool": tool, "generation": generation, "selection": selection or sel(), **extra}


def post(client, body, **extra):
    return client.post("/api/ask", json={"question": "Același lucru pentru Iași?", "provider": "anthropic",
                                         "model": "claude-sonnet-5-5", "api_key": "k-123456",
                                         "context": body, **extra})


# ---------------------------------------------------------------- validation

class TestValidate:
    def test_nothing_is_nothing(self):
        assert X.validate(None, GEN) == [] and X.validate([], GEN) == []

    def test_only_the_tool_generation_and_selection_survive(self):
        tampered = entry(summary={"rows": 99999, "verified": True}, sources=[{"dataset": "POPC", "unit": "x"}],
                         verification={"status": "verified"}, value=1e9)
        out = X.validate([tampered], GEN)
        assert out == [{"tool": "query_data", "generation": "gen-at01-fixture", "selection": sel()}]

    @pytest.mark.parametrize("bad,status", [
        ("nope", 400),
        ([entry()] * 5, 413),
        ([entry(selection=sel(filters={"REF_AREA": ["x" * 90] * 100}))], 413),   # > 8 KiB in total
        (["a string"], 400),
        ([{"tool": "describe_dataset", "generation": "g", "selection": sel()}], 400),
        ([entry(selection={"kind": "dataset", "dataset": "POPC", "filters": {}, "group_by": [],
                           "approximate": False, "extra": 1})], 400),
        ([entry(selection={"kind": "recipe", "recipe": "fx_intensity", "year": "2024", "areas": None})], 400),
        ([entry(selection=sel(group_by=["OBS_VALUE"]))], 400),
        ([{"tool": "query_data", "generation": "gen-at01-fixture", "selection": None}], 400),
        ([entry(generation="has spaces")], 400),
    ])
    def test_malformed_context_is_rejected_before_any_work(self, bad, status):
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as e:
            X.validate(bad, GEN)
        assert e.value.status_code == status

    def test_a_stale_generation_is_refused_with_a_refresh_action(self):
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as e:
            X.validate([entry(generation="gen-old")], GEN)
        assert e.value.status_code == 409
        assert e.value.detail["reason"] == "generation_changed" and e.value.detail["action"] == "refresh"

    def test_each_tool_accepts_its_own_selection_kind(self):
        ok = [entry("compare_periods", {"kind": "period_changes", "dataset": "COUNTX",
                                        "entity_columns": ["REF_AREA"], "intervals": [{"from": "1992", "to": "2002"}]}),
              entry("run_recipe", {"kind": "recipe", "recipe": "fx_intensity", "year": "2024", "areas": None})]
        assert [e["tool"] for e in X.validate(ok, GEN)] == ["compare_periods", "run_recipe"]


# ---------------------------------------------------------------- merge and prompt

def test_merge_keeps_four_newest_and_replaces_a_repeat():
    es = [entry(selection=sel(filters={"REF_AREA": [str(i)]})) for i in range(6)]
    out = X.merge(es[:3], es[3:])
    assert [e["selection"]["filters"]["REF_AREA"][0] for e in out] == ["2", "3", "4", "5"]
    again = X.merge(out, [es[3]])                                   # same canonical selection: moved, not duplicated
    assert [e["selection"]["filters"]["REF_AREA"][0] for e in again] == ["2", "4", "5", "3"]


def test_merge_drops_the_oldest_to_fit_8_kib():
    big = [entry(selection=sel(filters={"REF_AREA": [f"{k}-{i}" + "x" * 80 for i in range(40)]})) for k in range(4)]
    out = X.merge([], big)
    from app.services.tools.contract import size
    assert size(out) <= X.FOLLOWUP_MAX_BYTES and 1 <= len(out) < 4
    assert out[-1] == big[-1]                                       # the newest always survives


def test_the_prompt_section_calls_them_hints_not_results():
    text = X.prompt_section([entry()])
    assert "hints, not results" in text and "POPC" in text and "nothing here is a checked value" in text
    assert X.prompt_section([]) == ""


# ---------------------------------------------------------------- the follow-up flow

class TestFollowUp:
    def turn_one(self, monkeypatch, client):
        calls = scripted(monkeypatch, [
            call_resp("query_data", {"dataset": "POPC", "filters": {"REF_AREA": ["Cluj"]},
                                     "group_by": ["REF_AREA", "TIME_PERIOD"]}),
            text_resp("Cluj avea 1010 persoane în 2021 (POPC)."),
        ])
        r = client.post("/api/ask", json={"question": "Câți locuitori are Cluj?", "provider": "anthropic",
                                          "model": "claude-sonnet-5-5", "api_key": "k-123456"})
        assert r.status_code == 200, r.text
        return r.json(), calls

    def test_same_for_iasi_reuses_the_source_and_revalidates(self, tmp_path, monkeypatch):
        full_env(tmp_path, monkeypatch)
        client = make_client()
        one, _ = self.turn_one(monkeypatch, client)
        ctx = one["context"]
        assert len(ctx) == 1 and ctx[0]["selection"]["filters"] == {"REF_AREA": ["Cluj"]}
        assert ctx[0]["sources"][0]["dataset"] == "POPC" and ctx[0]["generation"] == "gen-at01-fixture"

        calls = scripted(monkeypatch, [
            call_resp("query_data", {"dataset": "POPC", "filters": {"REF_AREA": ["Iași"]},
                                     "group_by": ["REF_AREA", "TIME_PERIOD"]}, 5),
            text_resp("Iași avea 880 de persoane în 2021 (POPC)."),
        ])
        r = post(client, ctx)
        two = r.json()
        assert r.status_code == 200
        system = calls[0].kw["system"]
        assert "Earlier selections" in system and '"Cluj"' in system        # a hint to reuse
        assert two["verification"]["status"] == "verified"                  # re-run, not trusted
        assert [t["tool"] for t in two["tool_trace"]] == ["query_data"]
        assert len(two["context"]) == 2 and two["context"][-1]["selection"]["filters"] == {"REF_AREA": ["Iași"]}

    def test_context_cannot_certify_a_number_or_enable_an_approximation(self, tmp_path, monkeypatch):
        full_env(tmp_path, monkeypatch)
        client = make_client()
        approx = entry(selection=sel(approximate=True), summary={"rows": 1})
        scripted(monkeypatch, [text_resp("Cluj avea 1010 persoane în 2021.")])      # no tool run this turn
        two = post(client, [approx]).json()
        assert two["verification"]["status"] == "values_withheld" and "1010" not in two["answer"]
        assert two["tool_trace"] == [] and two["outcome"] == "refused"

    def test_client_claims_never_reach_the_model(self, tmp_path, monkeypatch):
        full_env(tmp_path, monkeypatch)
        calls = scripted(monkeypatch, [text_resp("Nu știu.")])
        post(make_client(), [entry(summary={"claim": "Cluj has 99999999 people"},
                                   sources=[{"dataset": "POPC", "definition": "SECRET-CLAIM"}])])
        system = calls[0].kw["system"]
        assert "99999999" not in system and "SECRET-CLAIM" not in system

    def test_a_stale_generation_stops_before_any_provider_call(self, tmp_path, monkeypatch):
        e = full_env(tmp_path, monkeypatch)
        client = make_client()
        one, _ = self.turn_one(monkeypatch, client)
        write_manifest(e.corpus, "gen-next")
        calls = scripted(monkeypatch, [text_resp("x")])
        r = post(client, one["context"])
        assert r.status_code == 409 and r.json()["detail"]["action"] == "refresh"
        assert calls == []

    def test_malformed_context_is_a_400_and_takes_no_slot(self, tmp_path, monkeypatch):
        full_env(tmp_path, monkeypatch)
        calls = scripted(monkeypatch, [text_resp("x")])
        r = post(make_client(), [entry(selection={"kind": "dataset"})])
        assert r.status_code == 400 and calls == []
        from app.services import ask_guard
        assert ask_guard.active_requests() == 0

    def test_the_context_stays_within_four_entries_over_many_turns(self, tmp_path, monkeypatch):
        full_env(tmp_path, monkeypatch)
        client = make_client()
        ctx = []
        picks = [(c, y) for c in ("Cluj", "Iași", "Bihor") for y in ("2020", "2021")]     # six distinct selections
        for i, (county, year) in enumerate(picks):
            scripted(monkeypatch, [call_resp("query_data", {"dataset": "POPC",
                                                            "filters": {"REF_AREA": [county], "TIME_PERIOD": [year]},
                                                            "group_by": ["REF_AREA", "TIME_PERIOD"]}, i),
                                   text_resp("Gata (POPC).")])
            r = post(client, ctx)
            assert r.status_code == 200, r.text
            ctx = r.json()["context"]
            assert len(ctx) <= X.FOLLOWUP_MAX_ENTRIES and len(json.dumps(ctx).encode()) <= X.FOLLOWUP_MAX_BYTES
        assert len(ctx) == 4

    def test_config_advertises_the_bounds(self):
        limits = make_client().get("/api/ask/config").json()["limits"]
        assert limits["max_context_entries"] == 4 and limits["max_context_bytes"] == 8192
