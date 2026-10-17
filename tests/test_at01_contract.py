"""AT-00/AT-01: the `tempo-tools/2` contract every tool shares.

Argument validation happens before any database work, every outcome is a valid
envelope, results fit a UTF-8 byte budget without cutting required provenance,
a generation change during a call invalidates it, and failures carry no
internals. Handlers are faked here; the tools' own tests use real services.
"""
import dataclasses
import json
import math

import jsonschema
import pytest

from app.services import generation
from app.services.tools import contract as C
from app.services.tools import registry as R
from at01_fixtures import make_env


@pytest.fixture
def env(tmp_path, monkeypatch):
    return make_env(tmp_path, monkeypatch)


@pytest.fixture
def no_db(monkeypatch):
    """Rejected arguments must never reach the database."""
    import app.db as appdb

    def boom():
        raise AssertionError("database opened for rejected arguments")
    monkeypatch.setattr(appdb, "get_conn", boom)


def fake(monkeypatch, name, handler, shrink=None):
    """Point one registered tool at a test handler (module:function refs)."""
    import sys
    mod = sys.modules[__name__]
    setattr(mod, "_handler_" + name, handler)
    if shrink:
        setattr(mod, "_shrink_" + name, shrink)
    spec = dataclasses.replace(R.TOOLS[name], handler=f"{__name__}:_handler_{name}",
                               shrink=f"{__name__}:_shrink_{name}" if shrink else None)
    monkeypatch.setitem(R.TOOLS, name, spec)


# ------------------------------------------------------------ schemas

def test_eight_tools_with_closed_valid_schemas():
    assert list(R.TOOLS) == ["discover_indicators", "describe_dataset", "find_dimension_values",
                             "query_data", "compare_periods", "rank_entities", "run_recipe", "get_evidence_links"]
    for name in R.TOOLS:
        s = R.input_schema(name)
        jsonschema.Draft202012Validator.check_schema(s)
        assert s["additionalProperties"] is False and s["type"] == "object"
        jsonschema.Draft202012Validator.check_schema(R.output_schema(name))


def _args_ok():
    sel = {"kind": "dataset", "dataset": "ADDX"}
    return {
        "discover_indicators": {"query": "populatie"},
        "describe_dataset": {"dataset": "ADDX"},
        "find_dimension_values": {"dataset": "ADDX", "column": "CATEGORY"},
        "query_data": {"dataset": "ADDX"},
        "compare_periods": {"dataset": "ADDX", "entity_columns": ["CATEGORY"],
                            "intervals": [{"from": "2022", "to": "2023"}]},
        "rank_entities": {"dataset": "ADDX", "entity_columns": ["CATEGORY"]},
        "run_recipe": {"recipe": "tourism_intensity"},
        "get_evidence_links": {"selection": sel, "generation_id": "g1"},
    }


BAD = [
    ("discover_indicators", {"query": ""}),
    ("discover_indicators", {"query": "x" * 201}),
    ("discover_indicators", {"query": "a", "limit": True}),           # bool is not an int
    ("discover_indicators", {"query": "a", "limit": 11}),
    ("discover_indicators", {"query": "a", "lang": "fr"}),
    ("describe_dataset", {"dataset": "../etc/passwd"}),
    ("describe_dataset", {"dataset": "ADDX\x00"}),
    ("describe_dataset", {"dataset": "A" * 129}),
    ("describe_dataset", {"dataset": "ADDX", "extra": 1}),            # unknown key
    ("find_dimension_values", {"dataset": "ADDX", "column": "CATEGORY", "limit": 101}),
    ("find_dimension_values", {"dataset": "ADDX", "column": "CATEGORY", "offset": -1}),
    ("query_data", {"dataset": "ADDX", "limit": 0}),
    ("query_data", {"dataset": "ADDX", "limit": 201}),
    ("query_data", {"dataset": "ADDX", "limit": 5.0}),
    ("query_data", {"dataset": "ADDX", "filters": "{\"CATEGORY\": [\"A\"]}"}),   # JSON string
    ("query_data", {"dataset": "ADDX", "filters": {"CATEGORY": "A"}}),
    ("query_data", {"dataset": "ADDX", "filters": {"CATEGORY": [None]}}),
    ("query_data", {"dataset": "ADDX", "filters": {"CATEGORY": [True]}}),
    ("query_data", {"dataset": "ADDX", "filters": {"OBS_VALUE": [1]}}),
    ("query_data", {"dataset": "ADDX", "filters": {f"C{i}": ["a"] for i in range(17)}}),
    ("query_data", {"dataset": "ADDX", "filters": {"CATEGORY": ["a"] * 101}}),
    ("query_data", {"dataset": "ADDX", "filters": {f"C{i}": ["a"] * 100 for i in range(11)}}),
    ("query_data", {"dataset": "ADDX", "group_by": ["CATEGORY", "CATEGORY"]}),
    ("query_data", {"dataset": "ADDX", "group_by": [f"C{i}" for i in range(9)]}),
    ("query_data", {"dataset": "ADDX", "approximate": 1}),
    ("compare_periods", {"dataset": "ADDX", "entity_columns": [], "intervals": [{"from": "1", "to": "2"}]}),
    ("compare_periods", {"dataset": "ADDX", "entity_columns": ["CATEGORY"],
                         "intervals": [{"from": "2023", "to": "2022"}]}),
    ("compare_periods", {"dataset": "ADDX", "entity_columns": ["CATEGORY"],
                         "intervals": [{"from": 2022, "to": 2023}]}),
    ("compare_periods", {"dataset": "ADDX", "entity_columns": ["CATEGORY"],
                         "intervals": [{"from": "2022", "to": "2023"}] * 2}),
    ("compare_periods", {"dataset": "ADDX", "entity_columns": ["CATEGORY"], "intervals":
                         [{"from": str(1990 + i), "to": str(2000 + i)} for i in range(5)]}),
    ("compare_periods", {"dataset": "ADDX", "entity_columns": ["CATEGORY"],
                         "intervals": [{"from": "2022", "to": "2023"}],
                         "filters": {"TIME_PERIOD": ["2022"]}}),
    ("compare_periods", {"dataset": "ADDX", "entity_columns": ["TIME_PERIOD"],
                         "intervals": [{"from": "2022", "to": "2023"}]}),
    ("compare_periods", {"dataset": "ADDX", "entity_columns": ["CATEGORY"],
                         "intervals": [{"from": "2022", "to": "2023"}], "top_k": 0}),
    ("run_recipe", {"recipe": "tourism_intensity", "year": "24"}),
    ("run_recipe", {"recipe": "tourism_intensity", "year": 2024}),
    ("run_recipe", {"recipe": "tourism_intensity", "areas": ["Cluj"] * 61}),
    ("run_recipe", {"recipe": "../x"}),
    ("get_evidence_links", {"selection": {"kind": "recipe", "recipe": "tourism_intensity"},
                            "generation_id": "g1"}),               # citation needs a year
    ("get_evidence_links", {"selection": {"kind": "url", "url": "http://x"}, "generation_id": "g"}),
    ("get_evidence_links", {"selection": {"kind": "dataset", "dataset": "ADDX"},
                            "generation_id": "g/../1"}),
    ("query_data", {"dataset": "ADDX", "filters": {"CATEGORY": ["é" * 500] * 20}}),  # > 16 KiB in bytes
]


@pytest.mark.parametrize("name,args", BAD)
def test_bad_arguments_are_errors_before_any_db_work(no_db, name, args):
    env = R.call_tool(name, args)
    R.validate_result(name, env)
    assert env["status"] == "error" and env["reason"] == "invalid_input", env["message"]
    assert env["data"] == {} and env["provenance"]["selection"] is None


def test_good_arguments_pass_validation():
    for name, args in _args_ok().items():
        R.TOOLS[name].args.model_validate(args)


def test_non_object_and_unknown_tool(no_db):
    assert R.call_tool("query_data", ["ADDX"])["reason"] == "invalid_input"
    assert R.call_tool("query_data", {"dataset": "ADDX", "x": float("nan")})["reason"] == "invalid_input"
    env = R.call_tool("run_sql", {"sql": "select 1"})
    assert env["status"] == "error" and env["reason"] == "unknown_tool"
    S = R.S.Envelope
    S.model_validate(env)


def test_messages_name_the_argument_not_its_value(no_db):
    env = R.call_tool("query_data", {"dataset": "ADDX", "filters": {"CATEGORY": "secret-ish"}})
    assert "filters.CATEGORY" in env["message"] and "secret-ish" not in env["message"]
    env = R.call_tool("describe_dataset", {"dataset": "ADDX", "nope": 1, "lang": "en"})
    assert "nope: unknown argument" in env["message"]
    env = R.call_tool("describe_dataset", {"dataset": "ADDX", "nope": 1})
    assert "nope: argument necunoscut" in env["message"]            # Romanian by default


# ------------------------------------------------------------ envelope, errors

def test_execution_failure_reveals_no_internals(env, monkeypatch, caplog):
    def handler(args, ctx):
        raise RuntimeError("SELECT * FROM read_parquet('/srv/data/corpus/x.parquet') key=sk-abc")
    fake(monkeypatch, "query_data", handler)
    out = R.call_tool("query_data", {"dataset": "ADDX", "lang": "en"})
    R.validate_result("query_data", out)
    assert out["status"] == "error" and out["reason"] == "execution_failed"
    text = json.dumps(out)
    assert "SELECT" not in text and "/srv" not in text and "sk-abc" not in text
    assert "reference" in out["message"]


def test_generation_change_during_a_call_invalidates_it(env, monkeypatch):
    from at01_fixtures import write_manifest

    def handler(args, ctx):
        assert ctx.generation["id"] == "gen-at01-fixture"
        write_manifest(env.corpus, "gen-next")          # a swap mid-call
        return C.envelope("query_data", ctx, data={"columns": ["OBS_VALUE"], "rows": [[1]],
                                                    "column_labels": {}, "selection": None})
    fake(monkeypatch, "query_data", handler)
    out = R.call_tool("query_data", {"dataset": "ADDX"})
    R.validate_result("query_data", out)
    assert out["status"] == "unavailable" and out["reason"] == "generation_changed"
    assert out["data"] == {} and out["recovery"][0]["kind"] == "retry"


def test_the_call_owns_and_closes_its_cursor(env, monkeypatch):
    import app.db as appdb
    seen = {}
    real = appdb.get_conn

    def tracking():
        c = real()
        seen["conn"] = c
        return c
    monkeypatch.setattr(appdb, "get_conn", tracking)

    def handler(args, ctx):
        assert ctx.conn is seen["conn"]
        raise C.ToolFailure("unavailable", "query_budget", "too big")
    fake(monkeypatch, "query_data", handler)
    out = R.call_tool("query_data", {"dataset": "ADDX"})
    assert out["reason"] == "query_budget"
    with pytest.raises(Exception):
        seen["conn"].execute("SELECT 1")             # closed in finally


def test_invalid_recovery_suggestions_are_dropped(env, monkeypatch):
    def handler(args, ctx):
        raise C.ToolFailure("unavailable", "slice_value_missing", "no such value", recovery=[
            C.recovery("tool_call", "bad", "find_dimension_values", {"dataset": "ADDX"}),
            C.recovery("tool_call", "unknown tool", "run_sql", {"sql": "x"}),
            C.recovery("tool_call", "good", "find_dimension_values",
                       {"dataset": "ADDX", "column": "CATEGORY", "query": "tot"}),
            C.recovery("narrow", "Filter one period.")])
    fake(monkeypatch, "query_data", handler)
    out = R.call_tool("query_data", {"dataset": "ADDX"})
    R.validate_result("query_data", out)
    assert [r["message"] for r in out["recovery"]] == ["good", "Filter one period."]


def test_missing_generation_is_reported_not_invented(tmp_path, monkeypatch):
    make_env(tmp_path, monkeypatch, generation_id=None)

    def handler(args, ctx):
        ctx.require_present_generation("query_data")
    fake(monkeypatch, "query_data", handler)
    out = R.call_tool("query_data", {"dataset": "ADDX"})
    R.validate_result("query_data", out)
    assert out["reason"] == "generation_unverified"
    assert out["provenance"]["generation"] == {"id": None, "status": "missing", "built_at": None}


# ------------------------------------------------------------ budgets

def _rows_handler(n, text):
    def handler(args, ctx):
        rows = [[f"{text} {i}", float(i)] for i in range(n)]
        return C.envelope("query_data", ctx, data={"columns": ["REF_AREA", "OBS_VALUE"], "rows": rows,
                                                    "column_labels": {}, "selection": None},
                          limits={"returned_rows": n, "total_rows": n, "source_complete": True},
                          warnings=[C.warning("approximation", "Labelled approximation.")])
    return handler


def test_budget_counts_utf8_bytes_and_keeps_safety_notes(env, monkeypatch):
    # 200 rows of 2-byte characters: under 32 KiB in characters, over it in bytes
    text = "ș" * 90
    assert len(C.dumps([[text, 1.0]] * 200)) < 32 * 1024 < C.size([[text, 1.0]] * 200)
    fake(monkeypatch, "query_data", _rows_handler(200, text))
    out = R.call_tool("query_data", {"dataset": "ADDX"})
    R.validate_result("query_data", out)
    assert C.size(out) <= C.MAX_RESULT_BYTES
    assert out["status"] == "ok" and 0 < len(out["data"]["rows"]) < 200
    assert out["limits"]["returned_rows"] == len(out["data"]["rows"])
    assert out["limits"]["preview_truncated"] is True and out["limits"]["total_rows"] == 200
    codes = [w["code"] for w in out["warnings"]]
    assert "approximation" in codes and "preview_shortened" in codes
    # rows are whole: never cut mid-string or mid-row
    assert all(len(r) == 2 and r[0].startswith(text) for r in out["data"]["rows"])


def test_required_provenance_that_cannot_fit_is_a_response_budget(env, monkeypatch):
    def handler(args, ctx):
        prov = {"sources": [{"dataset": f"D{i}", "metric": "ă" * 200, "unit": None,
                             "definition": None, "source_updated": None, "url": None,
                             "notes": []} for i in range(200)],
                "selection": {"kind": "dataset", "dataset": "ADDX"}}
        return C.envelope("query_data", ctx, provenance=prov, data={
            "columns": ["OBS_VALUE"], "rows": [[1.0]], "column_labels": {}, "selection": None})
    fake(monkeypatch, "query_data", handler)
    out = R.call_tool("query_data", {"dataset": "ADDX"})
    R.validate_result("query_data", out)
    assert out["status"] == "unavailable" and out["reason"] == "response_budget"
    assert out["provenance"]["selection"] is None and "rows" not in out["data"]
    assert len(out["data"]["request"]["sha256"]) == 64
    assert out["recovery"][0]["kind"] == "narrow"


def test_json_safety():
    v = C.json_safe({"a": float("nan"), "b": [float("inf"), 1.5], "c": {1, 2}})
    assert v == {"a": None, "b": [None, 1.5], "c": [1, 2]}
    with pytest.raises(ValueError):
        C.dumps({"x": math.nan})


# ------------------------------------------------------------ helpers

def test_scope_text_states_the_restriction():
    s = C.scope_block({"domain_complete": False, "restrictions": [
        {"column": "AGE", "kind": "age_range", "covered": [[0, 84]], "domain": [0, None],
         "requested": False}]}, "ro")
    assert s["domain_complete"] is False
    assert s["description"] == "Vârste 0–84 ani (fără 85 ani și peste)"
    assert s["limitations"][0]["missing"] == [[85, None]]
    en = C.scope_block({"domain_complete": None, "restrictions": []}, "en")
    assert en == {"description": "Domain completeness cannot be verified", "domain_complete": None,
                  "limitations": []}
    assert C.scope_block(None, "en", raw=True)["description"] == "Raw observations, not aggregated"


def test_public_links_use_the_configured_origin_only(monkeypatch):
    from app import config
    monkeypatch.setattr(config, "PUBLIC_BASE_URL", "")
    assert C.dataset_page("ADDX", "ro") == "/dataset-v2.html?code=ADDX"
    monkeypatch.setattr(config, "PUBLIC_BASE_URL", "https://ins.example/")
    url = C.dataset_page("ADDX", "en", {"CATEGORY": ["Țară"]})
    assert url.startswith("https://ins.example/dataset-v2.html?code=ADDX&f=") and url.endswith("&lang=en")


def test_generation_precondition(env):
    assert generation.precondition(None) is None
    assert generation.precondition("gen-at01-fixture") is None
    d = generation.precondition("gen-old")
    assert d["reason"] == "generation_changed" and d["served_generation"] == "gen-at01-fixture"
