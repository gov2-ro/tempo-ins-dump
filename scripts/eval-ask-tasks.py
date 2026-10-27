#!/usr/bin/env python3
"""Offline task-level evaluation of Ask and the public MCP (AQ-02B).

Replays the versioned tasks in data/eval/ask_tasks.json against a synthetic generation (and,
when TEMPO_DATA_DIR points at a read-only copied generation, its pinned cases). The provider is
a SCRIPT: tool choice and the final answer are written in the task file, so a pass says the real
tools, Ask's budgets/context/claim verification and the MCP transport behave as specified. It is
never evidence of how a live model chooses tools or phrases caveats; every result and the report
say so ("tool_choice": "scripted", "live_model_quality": "not_measured").

  direct   Ask loop (agent.run_agent) dispatching the real tools in process
  mcp      the same scripted calls through the MCP Python SDK client over Streamable HTTP, with the
           default public gate; no model is involved, and a provider call there is a failure

    python scripts/eval-ask-tasks.py                       # all tasks, both languages and surfaces
    python scripts/eval-ask-tasks.py --task T06 --lang en --surface direct
    TEMPO_DATA_DIR=<copied generation>/data python scripts/eval-ask-tasks.py   # + pinned cases
    python scripts/eval-ask-tasks.py --list | --validate-only

Hard failures (never averaged away): an unsafe accepted claim, a leaked secret, a number that
deviates from the hand-checked expectation. Reports hold metadata and redacted summaries only;
prompt/answer/trace text needs --retain-content --consent-content-retention. Reports are written
outside the repository. Live-provider mode is AQ-02C and is not implemented here.
Exit: 0 pass, 1 failures, 2 usage/task-file errors, 3 only documented known limitations remain.
Needs the dev requirements (pytest): it reuses the test fixture builders in tests/.
"""
from __future__ import annotations

import argparse
import asyncio
import copy
import dataclasses
import json
import logging
import math
import os
import platform
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
for _p in (ROOT, ROOT / "tests"):          # fixtures and scripted-provider helpers live with the tests
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from aq02_tasks import (HARD, LANGS, MISSING, SURFACES, TASKS_PATH, clip, load_taskset, norm,  # noqa: E402
                        pattern_in, phrase_in, pointer, sha, states_number, stray_numbers, turns_of,
                        validate_taskset)

REPORT_SCHEMA = "ask-task-report/1"
RUNNER_VERSION = "1"
OFFLINE_NOTE = ("scripted provider responses: tool choice and answers are fixed by the task file; this run "
                "measures the deterministic system, not a model")


# ------------------------------------------------------------------ the scripted provider

class Script:
    """The provider as a script: the n-th model call returns the next step; a call made with
    tools disabled (the loop's final turn) and a script that has run out return the answer."""

    def __init__(self, steps, answer, *, prompt, lang, secrets=(), token=None, usage=None):
        self.steps, self.answer, self.prompt, self.lang = list(steps), answer, prompt, lang
        self.secrets, self.token, self.usage = list(secrets), token, usage
        self.i = self.n_calls = 0
        self.env_by_id: dict[str, dict] = {}
        self.envs: list[dict] = []

    def _absorb(self, messages):
        for m in messages:
            if isinstance(m.get("content"), list):
                for b in m["content"]:
                    if b.get("type") == "tool_result" and b["tool_use_id"] not in self.env_by_id:
                        try:
                            env = json.loads(b["content"])
                        except (TypeError, ValueError):
                            env = {}
                        self.env_by_id[b["tool_use_id"]] = env
                        self.envs.append(env)

    def _args(self, tool, args):
        from app.services.tools import registry
        args = copy.deepcopy(args)
        spec = registry.TOOLS.get(tool)

        def sub(v):
            if v == "$PROMPT":
                return self.prompt
            if isinstance(v, dict):
                return {k: sub(x) for k, x in v.items()}
            if isinstance(v, list):
                return [sub(x) for x in v]
            return v
        args = sub(args)
        if spec is not None and "lang" in spec.args.model_fields:
            args.setdefault("lang", self.lang)
        return args

    def _resp(self, **kw):
        from app.services.llm_client import LLMResponse
        return LLMResponse(usage=self.usage, **kw) if self.usage else LLMResponse(**kw)

    def text(self, text):
        return self._resp(stop_reason="end_turn", text=text, tool_calls=[], finish="complete")

    def __call__(self, n, messages, kw):
        self._absorb(messages)
        if kw.get("tool_choice") == "none" or self.i >= len(self.steps):
            return self.text(self.answer)
        step = self.steps[self.i]
        self.i += 1
        if "cancel" in step:
            if self.token is not None:
                self.token.cancel("client_disconnected")
            return self.text(self.answer)
        if "raise" in step:
            raise self._exception(step["raise"])
        if "provider" in step:
            return self._provider(step["provider"])
        tool, args = self.resolve(step)
        self.n_calls += 1
        return self._resp(stop_reason="tool_use", text=None, finish="tool_use",
                          tool_calls=[{"id": f"c{self.n_calls - 1}", "name": tool, "input": args}])

    def resolve(self, step, envs=None):
        """(tool, arguments) of a step; `follow` takes both from an earlier result."""
        envs = self.envs if envs is None else envs
        if "follow" in step:
            f = step["follow"]
            node = pointer(envs[f["call"]], f["path"]) if f["call"] < len(envs) else MISSING
            if not isinstance(node, dict) or "tool" not in node:
                return "describe_dataset", {"dataset": "NOT_FOUND_IN_RESULT"}   # the check on that call then fails
            args = {**node.get("arguments", {}), **(step.get("arguments") or {})}
            return node["tool"], self._args(node["tool"], args)
        return step["tool"], self._args(step["tool"], step.get("arguments", {}))

    def _provider(self, kind):
        if kind == "length_empty":
            return self._resp(stop_reason="max_tokens", text=None, tool_calls=[], finish="output_limit")
        if kind == "length_text":
            return self._resp(stop_reason="max_tokens", text="Partial answer", tool_calls=[], finish="output_limit")
        if kind == "empty":
            return self.text("")
        if kind == "incomplete":
            return self._resp(stop_reason="max_tokens", text=None, tool_calls=[], finish="incomplete")
        return self._resp(stop_reason="refusal", text=None, tool_calls=[], finish="content_filter")

    def _exception(self, kind):
        if kind == "key_echo":
            from app.services.llm_client import LLMError
            e = LLMError("provider_auth", "The provider rejected the API key", 401)
            key = self.secrets[0] if self.secrets else "KEY-MISSING"
            e.debug_detail = f"AuthenticationError: invalid api key '{key}' (Authorization: Bearer {key})"
            return e
        return type(kind, (Exception,), {})("provider said no")


# ------------------------------------------------------------------ observations

def call_record(tool, args, env, *, cached=False, executed=True, call_id=None):
    return {"id": call_id, "tool": tool, "input": args, "env": env, "cached": cached, "executed": executed}


def evidence_of(call) -> dict:
    """Source, definition, key, period, unit, scope and generation behind one tool result."""
    env = call["env"] if call else {}
    prov, data = env.get("provenance") or {}, env.get("data") or {}
    sel = prov.get("selection") or {}
    flt = (sel.get("filters") or {}).get("TIME_PERIOD") or []
    cols = data.get("columns") or []
    from_rows = sorted({str(r[cols.index("TIME_PERIOD")]) for r in data.get("rows") or []
                        if isinstance(r, list) and "TIME_PERIOD" in cols})
    periods = [str(x) for x in flt] or [str(v) for v in (data.get("year"),) if v] or \
        [str(x) for iv in sel.get("intervals") or [] for x in (iv.get("from"), iv.get("to"))] or from_rows
    recipe = data.get("recipe") if isinstance(data.get("recipe"), dict) else {}
    srcs = [{"dataset": s.get("dataset"), "unit": s.get("unit"), "definition": clip(s.get("definition"), 80)}
            for s in (prov.get("sources") or [])[:4]]
    return {"tool": call["tool"] if call else None, "status": env.get("status"), "reason": env.get("reason"),
            "sources": srcs, "selection_kind": sel.get("kind"), "dataset": sel.get("dataset") or data.get("dataset"),
            "keys": data.get("key_columns") or data.get("entity_columns") or sel.get("group_by")
            or sel.get("entity_columns") or [],
            "periods": periods, "unit": data.get("unit") or recipe.get("unit") or (srcs[0]["unit"] if srcs else None),
            "scope_complete": (prov.get("scope") or {}).get("domain_complete"),
            "generation": (prov.get("generation") or {}).get("id"),
            "warning_codes": [w.get("code") for w in env.get("warnings") or []]}


def primary_call(calls):
    data_tools = ("query_data", "compare_periods", "rank_entities", "run_recipe")
    good = [c for c in calls if c["tool"] in data_tools and c["env"].get("status") in ("ok", "partial")]
    return (good or [c for c in calls if c["tool"] in data_tools] or calls or [None])[-1]


def pairing_ok(messages) -> bool:
    """Every tool result in the model's context answers a tool request, and vice versa."""
    uses, results = set(), set()
    for m in messages:
        if isinstance(m.get("content"), list):
            for b in m["content"]:
                if b.get("type") == "tool_use":
                    uses.add(b["id"])
                elif b.get("type") == "tool_result":
                    results.add(b["tool_use_id"])
        for tc in m.get("tool_calls") or []:
            uses.add(tc["id"])
        if m.get("role") == "tool":
            results.add(m.get("tool_use_id"))
    return uses == results


class LogCapture(logging.Handler):
    """Every log record of a turn, as the root logger's only handler (so nothing is printed)."""

    def __init__(self):
        super().__init__(logging.DEBUG)
        self.lines: list[str] = []

    def emit(self, record):
        try:
            self.lines.append(record.getMessage())
        except Exception:  # noqa: BLE001
            pass

    def __enter__(self):
        root = logging.getLogger()
        self._saved = (root.handlers[:], root.level)
        root.handlers, root.level = [self], logging.DEBUG
        return self

    def __exit__(self, *a):
        root = logging.getLogger()
        root.handlers, root.level = self._saved[0], self._saved[1]


# ------------------------------------------------------------------ worlds (fixtures)

class World:
    """The environment a task runs in: a synthetic generation built from the existing fixture
    builders under a throw-away directory, or the copied generation read in place."""

    def __init__(self, kind):
        self.kind, self.mp, self.tmp, self.env = kind, None, None, None
        self.manifest_text = None

    def __enter__(self):
        import pytest
        self.mp = pytest.MonkeyPatch()
        from app.services import agent
        self.mp.setattr(agent, "RETRY_PAUSE_SECONDS", 0.0)
        if self.kind == "synthetic":
            import aq02_env
            self.tmp = tempfile.TemporaryDirectory(prefix="aq02-fixture-")
            self.env = aq02_env.synthetic_env(Path(self.tmp.name), self.mp)
        return self

    def __exit__(self, *a):
        self.mp.undo()
        if self.kind == "synthetic":
            from app.services import dataset_search
            dataset_search._reset_for_tests()
            self.tmp.cleanup()

    @property
    def generation(self) -> dict:
        from app.services import generation
        return generation.current()

    def advance_generation(self, new_id):
        """Another generation id in the manifest (restored by `restore`): a refresh between turns."""
        path = Path(self.env.corpus) / "generation-manifest.json"
        if self.manifest_text is None:
            self.manifest_text = path.read_text()
        path.write_text(json.dumps({**json.loads(self.manifest_text), "generation_id": new_id}))

    def restore(self):
        if self.manifest_text is not None:
            (Path(self.env.corpus) / "generation-manifest.json").write_text(self.manifest_text)
            self.manifest_text = None


def copied_prerequisite(fixture) -> str | None:
    """None when the copied generation is present and is the one the case was checked on."""
    from app import config
    if not (config.CORPUS_DIR / "metadata.duckdb").exists():
        return "prerequisite_missing: TEMPO_DATA_DIR does not hold a corpus (copied generation not provided)"
    try:
        gen = json.loads((config.CORPUS_DIR / "generation-manifest.json").read_text()).get("generation_id") or ""
    except (OSError, ValueError):
        return "prerequisite_missing: no readable generation manifest in the copied corpus"
    if not gen.startswith(fixture["generation_prefix"]):
        return f"prerequisite_mismatch: corpus generation {gen[:12]}… is not {fixture['generation_prefix']}…"
    return None


# ------------------------------------------------------------------ surfaces

def run_direct_turn(world, turn, lang, *, history, context, secrets, answer=None) -> dict:
    """One Ask turn: the real loop, tools, budgets, context handling and claim verification
    behind a scripted provider."""
    from fastapi import HTTPException
    from app import config
    from app.services import agent, ask_context, ask_guard
    from app.services.llm_client import LLMError
    prompt = turn["prompt"][lang]
    obs = {"surface": "direct", "raised": None, "answer": None, "scripted_answer": None, "calls": [], "events": [],
           "logs": [], "provider_calls": [], "verification": {}, "metrics": {}, "budget": {}, "context": [],
           "usage": None, "outcome": None, "reason": None, "stop_reason": None, "table": None, "warnings": []}
    for b in turn.get("before", []):
        if b["action"] == "advance_generation":
            world.advance_generation(b["generation"])
    try:                                         # follow-up context is untrusted input, validated as the router does
        validated = ask_context.validate(context, world.generation) if context else []
    except HTTPException as e:
        detail = e.detail if isinstance(e.detail, dict) else {"message": str(e.detail)}
        obs["raised"] = {"http_status": e.status_code, "reason": detail.get("reason"), "action": detail.get("action")}
        return obs
    token = ask_guard.CancelToken()
    answer_text = answer if answer is not None else turn["answer"][lang]
    script = Script(turn.get("steps", []), answer_text, prompt=prompt, lang=lang, secrets=secrets, token=token,
                    usage=turn.get("usage"))
    from at02_env import scripted
    calls = scripted(world.mp, script)
    t0 = time.perf_counter()
    with LogCapture() as logs:
        try:
            # the variant's language is the language of the site the (simulated) user is on: it decides a
            # prompt that shows none ("Acum pentru 2020."); a prompt that does show one is unaffected
            res = agent.run_agent(prompt, history, provider="anthropic", api_key=secrets[0] if secrets else "k",
                                  on_event=obs["events"].append, context=validated, cancel=token, site_lang=lang)
        except LLMError as e:
            obs["raised"] = {"type": "LLMError", "code": e.code, "status": e.status, "message": str(e)}
            res = None
        except Exception as e:  # noqa: BLE001 — an unexpected exception is a result, not a crash of the run
            obs["raised"] = {"type": type(e).__name__, "code": "unexpected_exception", "message": clip(e, 120)}
            res = None
    obs["logs"], obs["elapsed_ms"] = list(logs.lines), int((time.perf_counter() - t0) * 1000)
    obs["tool_ms"] = [e["took_ms"] for e in obs["events"] if e.get("event") == "tool_done"]
    obs["provider_calls"] = [{"tool_choice": c.kw.get("tool_choice"), "messages": c.messages,
                              "max_tokens": c.kw.get("max_tokens"),
                              "hint": "Earlier selections" in (c.kw.get("system") or "")} for c in calls]
    obs["scripted_answer"] = answer_text
    obs["slots_in_use"] = ask_guard.active_requests()
    if res is not None:
        obs.update(answer=res.answer, outcome=res.outcome, reason=res.reason, stop_reason=res.stop_reason,
                   verification=res.verification, metrics=res.metrics, budget=res.budget, context=res.context,
                   usage=res.usage, table=res.data, warnings=res.warnings,
                   calls=[call_record(t["tool"], t["input"], t["output"], cached=t["cached"],
                                      executed=t["executed"], call_id=t["id"]) for t in res.tool_trace])
        obs["limits"] = {"iterations": config.ASK_MAX_ITERATIONS, "tools": config.ASK_MAX_TOOL_CALLS,
                         "context_bytes": config.ASK_CONTEXT_BYTES}
    return obs


async def _mcp_turn(world, turn, lang) -> dict:
    import threading
    import at03_env as E
    from app.services import agent, public_mcp as P
    from app.services.tools import contract, registry
    prompt = turn["prompt"][lang]
    # A held call occupies the slot until the turn ends, so the next call can only wait out the queue:
    # a 1 s queue keeps that path (bounded wait, then `busy`) quick. Queued service is tested in
    # tests/test_at03_resources.py.
    held_turn = any(s.get("hold") for s in turn.get("steps", []))
    app, mcp = E.make_app(Path(world.tmp.name), world.mp, env=world.env,
                          environ={"TEMPO_MCP_QUEUE_SECONDS": "1"} if held_turn else None)
    # a model call from the MCP surface is a failure of the property under test
    model_calls = []
    world.mp.setattr(agent, "complete_with_tools", lambda *a, **k: model_calls.append(1))
    script = Script(turn.get("steps", []), "", prompt=prompt, lang=lang)
    obs = {"surface": "mcp", "raised": None, "calls": [], "model_calls": model_calls,
           "settings": dataclasses.asdict(mcp.settings)}
    real = registry.call_tool
    release = threading.Event()
    held = None                                    # (task, index) of a call kept running to occupy the slot
    t_all = time.perf_counter()
    try:
        async with E.started(app):
            if any(s.get("hold") for s in turn.get("steps", [])):
                entered = threading.Event()

                def blocked(name, arguments, *, conn=None):
                    entered.set()
                    release.wait(8)
                    return real(name, arguments, conn=conn)
                registry.call_tool = blocked      # restored in `finally`, not via the shared MonkeyPatch (its undo order would leak it)
            async with E.session(app) as s, E.session(app) as s2:
                envs = []
                for step in turn.get("steps", []):
                    if "tool" not in step and "follow" not in step:
                        continue
                    tool, args = script.resolve(step, envs)
                    if step.get("hold"):
                        held = (asyncio.ensure_future(s.call_tool(tool, args)), len(obs["calls"]))
                        while not entered.is_set():
                            await asyncio.sleep(0.01)
                        obs["calls"].append(call_record(tool, args, {}))
                        envs.append({})
                        continue
                    t0 = time.perf_counter()
                    res = await (s2 if held else s).call_tool(tool, args)
                    structured, text = E.payload(res)
                    obs["calls"].append({**call_record(tool, args, structured), "ms": int((time.perf_counter() - t0) * 1000),
                                         "is_error": bool(res.isError), "same_text": structured == text,
                                         "wire_bytes": P.wire_bytes(res)})
                    envs.append(structured)
                if held:
                    release.set()
                    res = await held[0]
                    structured, text = E.payload(res)
                    prev = obs["calls"][held[1]]
                    obs["calls"][held[1]] = {**call_record(prev["tool"], prev["input"], structured), "ms": None,
                                             "is_error": bool(res.isError), "same_text": structured == text,
                                             "wire_bytes": P.wire_bytes(res)}
                    registry.call_tool = real
                    deadline = time.monotonic() + 6
                    while mcp.gate.active and time.monotonic() < deadline:
                        await asyncio.sleep(0.02)
    finally:
        release.set()
        registry.call_tool = real
    obs["elapsed_ms"] = int((time.perf_counter() - t_all) * 1000)
    obs["slots_in_use"] = mcp.gate.active
    obs["limits"] = {"wire_bytes": P.MAX_WIRE_BYTES}
    obs["stats"] = dict(mcp.gate.stats)
    obs["metrics"] = {"tool_dispatches": len(obs["calls"]), "tool_executions": obs["stats"].get("calls", 0) - obs["stats"].get("cache_hits", 0),
                      "cache_hits": obs["stats"].get("cache_hits", 0),
                      "tool_result_bytes": sum(contract.size(c["env"]) for c in obs["calls"])}
    return obs


def run_mcp_turn(world, turn, lang) -> dict:
    return asyncio.run(_mcp_turn(world, turn, lang))


# ------------------------------------------------------------------ checks

def evaluate_turn(expect: dict, obs: dict, lang: str, *, canaries=()) -> tuple[list[dict], dict]:
    """Deterministic checks of one turn: [{id, kind, passed, category, detail}] and the
    app's verdict on the scripted answer ('withheld' | 'flagged' | 'accepted' | None)."""
    out: list[dict] = []
    surface = obs["surface"]

    def add(cid, kind, ok, category=None, detail=None):
        out.append({"id": cid, "kind": kind, "passed": bool(ok), "category": None if ok else category,
                    "detail": None if ok else detail})

    raised = obs.get("raised")
    want = expect.get("raises")
    if want:
        got = {k: raised.get(k) for k in want} if raised else None
        add("raises", "outcome", got == want, "outcome_mismatch", f"expected {want}, got {raised and {k: raised.get(k) for k in want}}")
    elif raised:
        add("no_exception", "outcome", False, "unexpected_exception",
            {k: raised.get(k) for k in ("type", "code", "status", "http_status", "reason")})
    calls, verification = obs.get("calls", []), obs.get("verification") or {}
    answer = obs.get("answer") or ""                 # what the user sees, after the app's own checks
    model_text = obs.get("scripted_answer") or ""    # what the (scripted) model wrote
    verdict = None
    if surface == "direct" and not raised:
        v = verification.get("status")
        if v in ("values_withheld", "claim_mismatch"):
            verdict = "withheld"
        elif v == "unverified_numbers":
            verdict = "flagged"
        elif obs.get("outcome") in ("failed", "refused", "partial", "clarification") and answer != obs.get("scripted_answer"):
            verdict = "withheld"
        else:
            verdict = "accepted"
        if "outcome" in expect:
            add("outcome", "outcome", obs["outcome"] in expect["outcome"], "outcome_mismatch",
                f"outcome {obs['outcome']!r}/{obs['reason']!r}, expected {expect['outcome']}")
        if "reasons" in expect:
            add("reason", "outcome", obs["reason"] in expect["reasons"], "reason_mismatch",
                f"reason {obs['reason']!r}, expected {expect['reasons']}")
        if "verification" in expect:
            add("verification", "verification", v in expect["verification"], "verification_mismatch",
                f"verification {v!r}, expected {expect['verification']}")
    # scripted tool choice: the expected tools, in order, with the expected argument subset
    if "tools" in expect and not raised:
        i, missing = 0, None
        for want_t in expect["tools"]:
            j = next((k for k in range(i, len(calls)) if calls[k]["tool"] == want_t["tool"]
                      and all(calls[k]["input"].get(a) == b for a, b in (want_t.get("args") or {}).items())), None)
            if j is None:
                missing = want_t
                break
            i = j + 1
        add("tools", "tool_choice_scripted", missing is None, "tool_choice_mismatch",
            f"expected call not found in order: {missing}")
    for ce in expect.get("calls", []):
        idx = ce["call"]
        c = calls[idx] if -len(calls) <= idx < len(calls) else None
        cid = f"call[{idx}]"
        if c is None:
            add(cid, "envelope", False, "envelope_mismatch", f"no tool call {idx} (made {len(calls)})")
            continue
        env = c["env"]
        if "tool" in ce:
            add(f"{cid}.tool", "envelope", c["tool"] == ce["tool"], "envelope_mismatch", f"tool {c['tool']!r}")
        if "status" in ce:
            add(f"{cid}.status", "envelope", env.get("status") in ce["status"], "envelope_mismatch",
                f"{c['tool']} status {env.get('status')!r}/{env.get('reason')!r}, expected {ce['status']}")
        if "reason" in ce:
            add(f"{cid}.reason", "envelope", env.get("reason") in ce["reason"], "envelope_mismatch",
                f"reason {env.get('reason')!r}, expected {ce['reason']}")
        codes = [w.get("code") for w in env.get("warnings") or []]
        for w in ce.get("warnings", []):
            add(f"{cid}.warning.{w}", "qualification", w in codes, "missing_qualification", f"warning codes {codes}")
        for w in ce.get("no_warnings", []):
            add(f"{cid}.no_warning.{w}", "envelope", w not in codes, "envelope_mismatch", f"unexpected warning {w}")
        for path in ce.get("absent", []):
            got = pointer(env, path)
            add(f"{cid}.absent{path}", "envelope", got is MISSING or got in (None, [], {}), "envelope_mismatch",
                f"{path} holds {got!r}")
        for path, val in (ce.get("equals") or {}).items():
            got = pointer(env, path)
            ok = got == val or (isinstance(got, (int, float)) and isinstance(val, (int, float))
                                and not isinstance(got, bool) and math.isclose(got, val, rel_tol=1e-9, abs_tol=1e-9))
            add(f"{cid}.equals{path}", "envelope", ok, "envelope_mismatch", f"{path} is {None if got is MISSING else got!r}")
    # hand-checked numbers: located in the real result, then stated in the answer, then bound to its cell
    expected_values = []
    for n in expect.get("numbers", []):
        idx = n["call"]
        c = calls[idx] if -len(calls) <= idx < len(calls) else None
        got = pointer(c["env"], n["path"]) if c else MISSING
        expected_values.append(float(n["value"]))
        if got is MISSING or isinstance(got, (dict, list, str, bool)) or got is None:
            add(f"number.{n['id']}", "numerical", False, "envelope_mismatch",
                f"{n['path']} of call {idx} holds no number")
            continue
        tol = float(n.get("tol", 0))
        ok = math.isclose(float(got), float(n["value"]), rel_tol=1e-9, abs_tol=tol + 1e-9)
        add(f"number.{n['id']}", "numerical", ok, "numerical_deviation", f"tool gave {got!r}, hand-checked {n['value']}")
        if surface == "direct" and n.get("stated", True) and not raised:
            add(f"stated.{n['id']}", "numerical", states_number(answer, float(n["value"])), "number_not_stated",
                f"the answer does not state {n['value']}")
            if n.get("bind") and verification.get("claims") is not None:
                matched = [cl for cl in verification["claims"] if cl.get("check") == "matched"
                           and cl.get("tool_call_id") == (c.get("id") if c else None)
                           and (not n.get("entity") or norm(n["entity"]) in norm(cl.get("entity")))
                           and (not n.get("period") or str(cl.get("period")) == str(n["period"]))]
                add(f"bound.{n['id']}", "verification", bool(matched), "claim_not_bound",
                    f"no matched claim for call {idx} entity={n.get('entity')} period={n.get('period')}")
    if surface == "direct" and not raised:
        ans = expect.get("answer") or {}
        allowed = [float(x) for x in ans.get("allowed_numbers", [])]
        if ans.get("check_numbers", bool(expect.get("numbers")) or ans.get("no_numbers")):
            stray = stray_numbers(model_text, expected_values, allowed)
            if stray:
                # a stated figure that is not hand-checked: contained when the app flagged or withheld it
                cat = "numerical_deviation" if verdict == "accepted" else "unexpected_number"
                add("answer_numbers", "numerical", False, cat, f"figures outside the hand-checked set: {stray[:5]}")
            else:
                add("answer_numbers", "numerical", True)
        for q in expect.get("qualifications", []):
            if q.get("answer_any"):
                hit = phrase_in(answer, q["answer_any"][lang])
                add(f"qualification.{q['id']}", "qualification", hit is not None, "missing_qualification",
                    "none of the required statements appears in the answer")
        for f in expect.get("forbidden", []):
            def hit(text):
                return bool(pattern_in(text, (f.get("answer_pattern") or {}).get(lang, []))
                            or [v for v in f.get("numbers", []) if states_number(text, float(v))])
            written = hit(answer) if f.get("on") == "visible" else hit(model_text) or hit(answer)
            if written:
                add(f"forbidden.{f['id']}", "forbidden", False, "forbidden_claim", "a forbidden claim is in the answer")
                if verdict == "accepted" and hit(answer):
                    add(f"accepted.{f['id']}", "safety", False, "unsafe_claim_accepted",
                        "the forbidden claim reached the user in an answer the app does not flag")
            else:
                add(f"forbidden.{f['id']}", "forbidden", True)
        lim = expect.get("limits") or {}
        m = obs.get("metrics") or {}
        for key, mkey, op in (("max_dispatches", "tool_dispatches", "le"), ("max_executions", "tool_executions", "le"),
                              ("min_executions", "tool_executions", "ge"),
                              ("min_cache_hits", "cache_hits", "ge"), ("max_model_attempts", "model_attempts", "le"),
                              ("retries", "retries", "eq")):
            if key in lim:
                v = m.get(mkey)
                ok = v is not None and ((op == "le" and v <= lim[key]) or (op == "ge" and v >= lim[key])
                                        or (op == "eq" and v == lim[key]))
                add(f"limit.{key}", "budget", ok, "budget_exceeded", f"{mkey}={v}, {key}={lim[key]}")
        if "min_compacted_results" in lim and obs.get("provider_calls"):
            n_compact = sum(1 for msg in obs["provider_calls"][-1]["messages"] if isinstance(msg.get("content"), list)
                            for b in msg["content"] if b.get("type") == "tool_result" and '"compacted"' in str(b.get("content")))
            add("limit.min_compacted_results", "budget", n_compact >= lim["min_compacted_results"], "budget_exceeded",
                f"{n_compact} compacted result(s) in the model's context")
        tb = expect.get("table")
        if tb is not None:
            table, kinds = obs.get("table") or {}, {l.get("kind") for l in (obs.get("table") or {}).get("links", [])}
            if "max_rows" in tb:
                add("table.max_rows", "budget", 0 < len(table.get("rows") or []) <= tb["max_rows"], "budget_exceeded",
                    f"{len(table.get('rows') or [])} rows shown")
            if "link_kinds_any" in tb:
                add("table.links", "evidence", bool(kinds & set(tb["link_kinds_any"])), "evidence_mismatch",
                    f"link kinds {sorted(kinds)}")
        cx = expect.get("context")
        if cx is not None:
            hints = [c["hint"] for c in obs.get("provider_calls", [])]
            if "hint" in cx:
                add("context.hint", "context", bool(hints) and hints[0] == cx["hint"], "context_mismatch",
                    f"earlier-selection hint {hints[:1]}, expected {cx['hint']}")
            if "entries" in cx:
                add("context.entries", "context", len(obs.get("context") or []) == cx["entries"], "context_mismatch",
                    f"{len(obs.get('context') or [])} follow-up entries, expected {cx['entries']}")
        # invariants of every Ask turn
        b = obs.get("budget") or {}
        add("invariant.within_budget", "budget",
            b.get("iterations", 0) <= b.get("max_iterations", 99) and b.get("tools", 0) <= b.get("max_tools", 99),
            "budget_exceeded", f"budget {b}")
        add("invariant.context_bytes", "budget",
            b.get("context_bytes", 0) <= b.get("max_context_bytes", 10 ** 9) or (obs.get("metrics") or {}).get("tool_dispatches", 0) <= 1,
            "budget_exceeded", f"context {b.get('context_bytes')} bytes")
        add("invariant.answer_present", "outcome", bool(answer.strip()) and "(no answer)" not in answer,
            "false_success", "empty answer")
        if obs.get("provider_calls"):
            add("invariant.context_pairing", "budget", pairing_ok(obs["provider_calls"][-1]["messages"]),
                "context_pairing", "tool results and tool requests do not pair up")
        add("invariant.slot_released", "budget", obs.get("slots_in_use", 0) == 0, "leaked_slot", f"{obs.get('slots_in_use')} in use")
    if surface == "mcp":
        mx = expect.get("mcp") or {}
        add("invariant.no_model_call", "transport", not obs.get("model_calls"), "model_call_on_mcp",
            "the MCP surface made a provider call")
        for i, c in enumerate(calls):
            if "same_text" in c:
                add(f"invariant.call[{i}].structured_equals_text", "transport", c["same_text"], "transport_mismatch",
                    "structuredContent and the text fallback differ")
                add(f"invariant.call[{i}].wire", "transport", c["wire_bytes"] <= obs["limits"]["wire_bytes"],
                    "transport_mismatch", f"{c['wire_bytes']} wire bytes")
        if "max_wire_bytes" in mx:
            top = max([c.get("wire_bytes", 0) for c in calls] or [0])
            add("mcp.max_wire_bytes", "transport", top <= mx["max_wire_bytes"], "transport_mismatch", f"{top} bytes")
        add("invariant.slot_released", "transport", obs.get("slots_in_use", 0) == 0, "leaked_slot",
            f"{obs.get('slots_in_use')} in use")
    ev = expect.get("evidence")
    if ev:
        c = calls[ev["call"]] if "call" in ev and -len(calls) <= ev["call"] < len(calls) else primary_call(calls)
        have = evidence_of(c)
        problems = []
        if "datasets" in ev and not (set(ev["datasets"]) <= {s["dataset"] for s in have["sources"]} | {have["dataset"]}):
            problems.append(f"datasets {ev['datasets']} not in {[s['dataset'] for s in have['sources']]}")
        for k in ("unit", "generation", "scope_complete", "selection_kind"):
            want_v = ev[k].get(lang) if isinstance(ev.get(k), dict) else ev.get(k)
            if k in ev and have[k] != want_v:
                problems.append(f"{k} is {have[k]!r}, expected {want_v!r}")
        if "periods" in ev and not set(map(str, ev["periods"])) <= set(have["periods"]):
            problems.append(f"periods {have['periods']}, expected {ev['periods']}")
        if "keys" in ev and not set(ev["keys"]) <= set(have["keys"] or []):
            problems.append(f"keys {have['keys']}, expected {ev['keys']}")
        for text in ev.get("definition_contains", []):
            if not any(norm(text) in norm(s["definition"]) for s in have["sources"]):
                problems.append(f"no source definition contains {text!r}")
        add("evidence", "evidence", not problems, "evidence_mismatch", "; ".join(problems))
    for q in expect.get("qualifications", []):
        t = q.get("tool")
        if t:
            idx = t["call"]
            c = calls[idx] if -len(calls) <= idx < len(calls) else None
            codes = [w.get("code") for w in (c["env"].get("warnings") or [])] if c else []
            ok = c is not None and (not t.get("warning") or t["warning"] in codes)
            for path, val in (t.get("equals") or {}).items():
                ok = ok and pointer(c["env"], path) == val
            add(f"qualification.{q['id']}.evidence", "qualification", ok, "missing_qualification",
                f"the result lacks {t}")
    allowed_secrets = [s for s in canaries if s]
    blob = json.dumps({k: obs.get(k) for k in ("answer", "raised", "events", "logs")}, ensure_ascii=False, default=str) \
        + json.dumps([c["env"] for c in calls], ensure_ascii=False, default=str)
    leaked = [i for i, s in enumerate(allowed_secrets) if s in blob]
    add("secrets", "safety", not leaked, "secret_leak", f"{len(leaked)} canary string(s) in the response, events, logs or trace")
    return out, {"verdict": verdict}


# ------------------------------------------------------------------ results

def result_skeleton(task, lang, surface, obs, checks, extra, *, kind="positive", negative=None, fixture=None) -> dict:
    calls = obs.get("calls", [])
    prim = primary_call(calls)
    m = obs.get("metrics") or {}
    usage = obs.get("usage")
    failures = [c for c in checks if not c["passed"]]
    cats = sorted({c["category"] for c in failures})
    return {
        "task_id": task["id"], "variant": lang, "surface": surface, "kind": kind, "negative_id": negative,
        "fixture": fixture or task["fixture"], "scripted": True,
        "tool_choice": "scripted", "live_model_quality": "not_measured",
        "status": "fail" if failures else "pass", "failure_categories": cats,
        "hard_failures": [c for c in cats if c in HARD],
        "outcome": {"outcome": obs.get("outcome"), "reason": obs.get("reason"), "stop_reason": obs.get("stop_reason"),
                    "raised": {k: v for k, v in (obs.get("raised") or {}).items() if k != "message"} or None,
                    "final_tool_status": [prim["env"].get("status"), prim["env"].get("reason")] if prim else None,
                    "app_verdict": extra.get("verdict")},
        "evidence": evidence_of(prim) if prim else None,
        "verification": {"status": (obs.get("verification") or {}).get("status"),
                         "claims": (obs.get("verification") or {}).get("claim_summary")},
        "checks": checks,
        "generation": (evidence_of(prim) or {}).get("generation") if prim else None,
        "counts": {"model_attempts": m.get("model_attempts"), "retries": m.get("retries"),
                   "dispatches": m.get("tool_dispatches", len(calls) if obs["surface"] == "mcp" else None),
                   "executions": m.get("tool_executions"), "cache_hits": m.get("cache_hits"),
                   "provider_calls": len(obs.get("provider_calls") or []) if obs["surface"] == "direct" else len(obs.get("model_calls") or [])},
        "bytes": {"tool_results": m.get("tool_result_bytes"), "answer_chars": len(obs.get("answer") or ""),
                  "wire_max": max([c.get("wire_bytes", 0) for c in calls] or [0]) or None},
        "latency_ms": {"total": obs.get("elapsed_ms"),
                       "tool_calls": obs.get("tool_ms") or [c.get("ms") for c in calls if c.get("ms") is not None] or None},
        "tokens": {"known": usage is not None, "usage": usage, "requested_output_tokens": m.get("requested_output_tokens")},
        "cost": {"usd": None, "status": "unknown: no price schedule and offline replay makes no paid call"},
        "skipped": None,
    }


def skipped_result(task, lang, surface, reason, fixture=None):
    return {"task_id": task["id"], "variant": lang, "surface": surface, "kind": "positive", "negative_id": None,
            "fixture": fixture or task["fixture"], "scripted": True, "status": "skipped", "skipped": reason,
            "failure_categories": [], "hard_failures": [], "checks": []}


def run_task(world, task, lang, surface, *, canaries, answer_override=None, steps_override=None, fixture=None,
             negative=None) -> dict:
    """All turns of one task variant on one surface; failures of any turn fail the variant."""
    turns = copy.deepcopy(turns_of(task))
    if steps_override is not None:
        turns[-1]["steps"] = steps_override
    history, context, merged_checks, last_obs, last_extra = [], [], [], None, {}
    secrets = list(task.get("secrets", []))
    try:
        for i, turn in enumerate(turns):
            if surface == "direct":
                ans = answer_override if (answer_override is not None and i == len(turns) - 1) else None
                obs = run_direct_turn(world, turn, lang, history=history, context=context, secrets=secrets, answer=ans)
                if obs.get("answer"):
                    history += [{"role": "user", "content": turn["prompt"][lang]},
                                {"role": "assistant", "content": obs["answer"]}]
                context = obs.get("context") or context
            else:
                obs = run_mcp_turn(world, turn, lang)
            checks, extra = evaluate_turn(turn.get("expect", {}), obs, lang, canaries=canaries + secrets)
            for c in checks:
                c["turn"] = i
            merged_checks += checks
            last_obs, last_extra = obs, extra
    finally:
        world.restore()
    res = result_skeleton(task, lang, surface, last_obs, merged_checks, last_extra, fixture=fixture,
                          kind="negative_control" if negative else "positive", negative=negative)
    res["turns"] = len(turns)
    res["_obs"] = last_obs
    return res


def guarded(fn, world, task, lang, surface, **kw) -> dict:
    """A task that crashes the runner is a failed result with its exception type, not a lost run."""
    try:
        return fn(world, task, lang, surface, **kw)
    except Exception as e:  # noqa: BLE001
        world.restore()
        res = skipped_result(task, lang, surface, None, fixture=kw.get("fixture"))
        res.update(status="fail", skipped=None, kind="negative_control" if kw.get("negative") else "positive",
                   negative_id=kw.get("negative"), failure_categories=["runner_error"],
                   error={"type": type(e).__name__, "detail": clip(e, 160)})
        return res


def apply_known_failure(task, res):
    """A documented current limitation: the failure is real and listed, but in its own bucket."""
    kf = task.get("known_failure")
    if not kf or res["kind"] != "positive":
        return
    if kf.get("surfaces") and res["surface"] not in kf["surfaces"]:
        return
    if kf.get("variants") and res["variant"] not in kf["variants"]:
        return
    if res["status"] == "fail" and set(res["failure_categories"]) <= set(kf["categories"]):
        res["status"], res["known_failure"] = "known_failure", {k: kf[k] for k in ("package", "note")}
    elif res["status"] == "pass":
        res["known_failure_resolved"] = {k: kf[k] for k in ("package", "note")}


def judge_control(task, neg, res):
    """Did the runner flag the intentionally wrong answer for the declared reason, and did the
    app contain it as declared? Controls never count toward the task pass rate. A declared known
    limitation that the app now contains is an improvement ("resolved"), not a failure."""
    det = neg["detect"]
    failed_ids = {c["id"] for c in res["checks"] if not c["passed"]}
    verdict = res["outcome"]["app_verdict"]
    problems = []
    for need in det["fails"]:
        if not any(f == need or f.startswith(need + ".") for f in failed_ids):
            problems.append(f"expected check {need!r} to fail; failed: {sorted(failed_ids)[:6]}")
    hard = set(res["hard_failures"])
    resolved = (det["app"] == "accepted" and verdict in ("withheld", "flagged") and not problems)
    if res["surface"] == "direct" and verdict != det["app"] and not resolved:
        problems.append(f"app verdict {verdict!r}, declared {det['app']!r}")
    if not resolved:
        if det.get("hard") and not set(det["hard"]) <= hard:
            problems.append(f"expected hard failure {det['hard']}, got {sorted(hard)}")
        if not det.get("hard") and hard:
            problems.append(f"unexpected hard failure {sorted(hard)}")
    if problems:
        res["control"], res["control_problems"] = "mismatch", problems
    elif resolved:
        res["control"] = "resolved"
        res["known_limitation_resolved"] = neg.get("known_limitation")
        res["hard_failures"] = []
    else:
        res["control"] = "known_limitation" if neg.get("known_limitation") else "detected"
        if neg.get("known_limitation"):
            res["known_limitation"] = neg["known_limitation"]
    res["status"] = {"detected": "pass", "resolved": "pass", "known_limitation": "known_failure", "mismatch": "fail"}[res["control"]]
    res["control_declared"] = {"app": det["app"], "fails": det["fails"], "hard": det.get("hard", [])}


# ------------------------------------------------------------------ the run

def git_state() -> dict:
    def git(*a):
        return subprocess.run(["git", *a], cwd=ROOT, capture_output=True, text=True, timeout=30).stdout
    try:
        head = git("rev-parse", "HEAD").strip()
        status = git("status", "--porcelain", "--", "app", "scripts", "tests", "data/eval")
        diff = git("diff", "HEAD", "--", "app", "scripts", "tests", "data/eval")
        untracked = [l[3:] for l in status.splitlines() if l.startswith("??")]
        parts = [diff] + [f"{u}:{sha((ROOT / u).read_bytes(), 32)}" for u in sorted(untracked) if (ROOT / u).is_file()]
        return {"head": head, "dirty": bool(status.strip()), "dirty_hash": sha("\n".join(parts), 16) if status.strip() else None}
    except Exception:  # noqa: BLE001
        return {"head": None, "dirty": None, "dirty_hash": None}


def run_config(mcp_settings=None) -> dict:
    from app import config
    cfg = {k: getattr(config, k) for k in ("ASK_MAX_ITERATIONS", "ASK_MAX_TOOL_CALLS", "ASK_MAX_SECONDS",
                                           "ASK_TURN_OUTPUT_TOKENS", "ASK_CONTEXT_BYTES", "MAX_DATA_ROWS") if hasattr(config, k)}
    return {"ask": cfg, "mcp_public_gate": mcp_settings}


def run_taskset(doc, *, ids=(), langs=LANGS, surfaces=SURFACES, controls=True, progress=None) -> dict:
    """Run the selected tasks; returns the results and run metadata (not yet written)."""
    from app.services import agent
    from app.services.tools import contract
    started = datetime.now(timezone.utc)
    ids = set(ids)
    tasks = [t for t in doc["tasks"] if not ids or t["id"] in ids]
    results: list[dict] = []
    canaries = list(doc.get("canaries", []))
    mcp_settings = None

    def go(world, task, fixture_id, view):
        nonlocal mcp_settings
        for lang in langs:
            for surface in [s for s in view["surfaces"] if s in surfaces]:
                if progress:
                    progress(f"{task['id']} {lang} {surface}")
                res = guarded(run_task, world, view, lang, surface, canaries=canaries, fixture=fixture_id)
                res["_review"] = task.get("review")
                mcp_settings = (res["_obs"].get("settings") or mcp_settings) if surface == "mcp" else mcp_settings
                apply_known_failure(task, res)
                results.append(res)
                if not controls or view.get("pinned_run"):
                    continue
                for neg in task.get("negatives", []):
                    nsurf = [s for s in neg.get("surfaces", ["direct"]) if s == surface]
                    if not nsurf:
                        continue
                    r = guarded(run_task, world, view, lang, surface, canaries=canaries, answer_override=neg["answer"][lang],
                                steps_override=neg.get("steps"), fixture=fixture_id, negative=neg["id"])
                    if r["status"] != "fail" or r["failure_categories"] != ["runner_error"]:
                        judge_control(task, neg, r)
                    results.append(r)

    synthetic = [t for t in tasks if doc["fixtures"][t["fixture"]]["kind"] == "synthetic"]
    if synthetic:
        with World("synthetic") as world:
            for t in synthetic:
                go(world, t, t["fixture"], t)
    copied = []                                   # (task, fixture id, what to run): own copied-generation tasks and pinned variants
    for t in tasks:
        if doc["fixtures"][t["fixture"]]["kind"] == "copied":
            copied.append((t, t["fixture"], {**t, "pinned_run": True}))
        elif t.get("pinned"):
            view = {**{k: v for k, v in t.items() if k != "known_failure"},
                    **{k: v for k, v in t["pinned"].items() if k != "fixture"}, "pinned_run": True}
            view.pop("pinned", None)
            view["surfaces"] = t["pinned"].get("surfaces", ["direct"])
            copied.append((t, t["pinned"]["fixture"], view))
    if copied:
        with World("copied") as world:
            for t, fid, view in copied:
                reason = copied_prerequisite(doc["fixtures"][fid])
                if reason:
                    for lang in langs:
                        for surface in [s for s in view["surfaces"] if s in surfaces]:
                            results.append(skipped_result(t, lang, surface, reason, fixture=fid))
                    continue
                go(world, t, fid, view)
    prompt_hash = sha(agent.SYSTEM_PROMPT)
    meta = {
        "report_schema": REPORT_SCHEMA, "runner_version": RUNNER_VERSION,
        "started_at": started.isoformat(timespec="seconds"),
        "finished_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "mode": "offline_replay", "tool_choice": "scripted", "live_model_quality": "not_measured", "note": OFFLINE_NOTE,
        "versions": {"task_schema": doc["schema"], "task_set": doc["version"],
                     "task_file_sha256": doc.get("_sha256"), "system_prompt_sha256": prompt_hash,
                     "tool_contract": contract.CONTRACT},
        "code": git_state(), "config": run_config(mcp_settings),
        "environment": {"python": platform.python_version(), "platform": platform.system()},
    }
    return {"meta": meta, "results": results}


def summarize(results: list[dict]) -> dict:
    pos = [r for r in results if r["kind"] == "positive"]
    ctl = [r for r in results if r["kind"] == "negative_control"]
    ran = [r for r in pos if r["status"] != "skipped"]
    by = lambda rs, s: [r for r in rs if r["status"] == s]
    hard = [{"task_id": r["task_id"], "variant": r["variant"], "surface": r["surface"], "kind": r["kind"],
             "negative_id": r["negative_id"], "categories": r["hard_failures"],
             "known": r["status"] == "known_failure"}
            for r in results if r["hard_failures"] and not (r["kind"] == "negative_control" and r.get("control") in ("detected", "resolved"))]
    refusal_ok = [r for r in pos if r["status"] == "pass" and (r["outcome"] or {}).get("outcome") in ("refused", "clarification")]
    summary = {
        "executed": len(ran), "passed": len(by(ran, "pass")), "failed": len(by(ran, "fail")),
        "known_failures": len(by(ran, "known_failure")), "skipped": len(by(pos, "skipped")),
        "pass_rate_of_executed": round(len(by(ran, "pass")) / len(ran), 4) if ran else None,
        "denominator_note": "executed = passed + failed + known_failures; skips and negative controls are excluded",
        "legitimate_refusals_or_clarifications": len(refusal_ok),
        "hard_failures": hard,
        "unsafe_accepted_claims": sum("unsafe_claim_accepted" in h["categories"] for h in hard),
        "secret_leaks": sum("secret_leak" in h["categories"] for h in hard),
        "numerical_deviations": sum("numerical_deviation" in h["categories"] for h in hard),
        "known_failure_tasks": sorted({(r["task_id"], r["variant"], r["surface"], r.get("negative_id") or "")
                                       for r in results if r["status"] == "known_failure"}),
        "known_failures_resolved": sorted({r["task_id"] for r in results if r.get("known_failure_resolved")}),
        "known_limitations_resolved": sorted({(r["task_id"], r["negative_id"]) for r in ctl if r.get("control") == "resolved"}),
        "negative_controls": {"total": len(ctl), "detected": len([r for r in ctl if r.get("control") == "detected"]),
                              "known_limitation": len([r for r in ctl if r.get("control") == "known_limitation"]),
                              "resolved": len([r for r in ctl if r.get("control") == "resolved"]),
                              "mismatch": len([r for r in ctl if r.get("control") == "mismatch"])},
        "by_surface": {s: {"executed": len([r for r in ran if r["surface"] == s]),
                           "passed": len([r for r in ran if r["surface"] == s and r["status"] == "pass"])}
                       for s in SURFACES},
        "skip_reasons": sorted({r["skipped"] for r in pos if r["status"] == "skipped"}),
    }
    real_fail = summary["failed"] + summary["negative_controls"]["mismatch"]
    only_known = summary["known_failures"] + summary["negative_controls"]["known_limitation"]
    summary["verdict"] = "fail" if real_fail or any(not h["known"] for h in hard) else \
        "blocked_by_known_limitations" if only_known else "pass"
    return summary


def public_result(r: dict) -> dict:
    """The metadata a report keeps: no prompt, answer or trace text."""
    return {k: v for k, v in r.items() if not k.startswith("_")}


def write_report(run: dict, report_dir: Path, *, retain_content=False, canaries=()) -> Path:
    report_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    summary = summarize(run["results"])
    review = {}
    for r in run["results"]:
        if r.get("_review") and r["kind"] == "positive":
            item = review.setdefault(r["task_id"], {"task_id": r["task_id"], "why": r["_review"], "variants": []})
            item["variants"].append(f"{r['variant']}/{r['surface']}")
    review = list(review.values())
    body = {**run["meta"], "content_retention": "consented" if retain_content else "none",
            "summary": summary, "human_review": review,
            "results": [public_result(r) for r in run["results"]]}
    text = json.dumps(body, ensure_ascii=False, indent=1, default=str)
    leaked = [c for c in canaries if c and c in text]
    if leaked:                                    # the report itself must not leak: redact, then fail loudly
        for c in leaked:
            text = text.replace(c, "[REDACTED]")
        body = json.loads(text)
        body["summary"]["secret_leaks"] += len(leaked)
        body["summary"]["hard_failures"].append({"task_id": "*", "variant": None, "surface": None, "kind": "report",
                                                 "negative_id": None, "categories": ["secret_leak"], "known": False})
        body["summary"]["verdict"] = "fail"
        text = json.dumps(body, ensure_ascii=False, indent=1, default=str)
    path = report_dir / f"ask-task-report-{stamp}.json"
    path.write_text(text, encoding="utf-8")
    if retain_content:
        from app.services import ask_guard
        lines = []
        for r in run["results"]:
            o = r.get("_obs")
            if not o:
                continue
            row = {"task_id": r["task_id"], "variant": r["variant"], "surface": r["surface"],
                   "negative_id": r["negative_id"], "answer": o.get("answer"), "scripted_answer": o.get("scripted_answer"),
                   "calls": [{"tool": c["tool"], "input": c["input"], "status": c["env"].get("status"),
                              "reason": c["env"].get("reason")} for c in o.get("calls", [])]}
            lines.append(json.dumps(ask_guard.redact(row, tuple(c for c in canaries if c)), ensure_ascii=False, default=str))
        (report_dir / f"ask-task-contents-{stamp}.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def default_report_dir() -> Path:
    return Path(os.environ.get("TEMPO_EVAL_REPORT_DIR") or Path(tempfile.gettempdir()) / "tempo-ask-task-eval")


def table(results: list[dict]) -> str:
    rows = [f"{'task':6} {'var':3} {'surface':7} {'kind':16} {'status':14} categories"]
    for r in results:
        if r["status"] == "skipped":
            rows.append(f"{r['task_id']:6} {r['variant']:3} {r['surface']:7} {r['kind'][:16]:16} {'skipped':14} {r['skipped'][:60]}")
            continue
        kind = r["kind"] if r["kind"] == "positive" else f"ctl:{r['negative_id']}"
        rows.append(f"{r['task_id']:6} {r['variant']:3} {r['surface']:7} {kind[:16]:16} {r['status']:14} "
                    f"{','.join(r['failure_categories'])}")
    return "\n".join(rows)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--tasks", type=Path, default=TASKS_PATH)
    ap.add_argument("--task", action="append", default=[], help="task id (repeatable); default all")
    ap.add_argument("--lang", choices=("ro", "en", "both"), default="both")
    ap.add_argument("--surface", choices=("direct", "mcp", "both"), default="both")
    ap.add_argument("--mode", choices=("offline",), default="offline",
                    help="offline replay only; the budgeted live mode is AQ-02C and not implemented")
    ap.add_argument("--no-controls", action="store_true", help="skip the intentionally wrong answers")
    ap.add_argument("--report-dir", type=Path, default=None, help="outside the repository (default: system temp)")
    ap.add_argument("--retain-content", action="store_true", help="also write redacted answers and tool calls")
    ap.add_argument("--consent-content-retention", action="store_true",
                    help="required with --retain-content: the owner agreed to keep content")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--validate-only", action="store_true")
    ap.add_argument("--quiet", action="store_true")
    a = ap.parse_args(argv)
    if a.retain_content and not a.consent_content_retention:
        print("--retain-content needs --consent-content-retention: reports are metadata-only by default", file=sys.stderr)
        return 2
    report_dir = (a.report_dir or default_report_dir()).resolve()
    if ROOT in (report_dir, *report_dir.parents):
        print(f"refusing to write reports inside the repository ({report_dir}); use --report-dir elsewhere", file=sys.stderr)
        return 2
    doc = load_taskset(a.tasks)
    doc["_sha256"] = sha(Path(a.tasks).read_bytes(), 16)
    problems = validate_taskset(doc)
    if problems:
        print("task file is invalid:\n  " + "\n  ".join(problems), file=sys.stderr)
        return 2
    if a.list:
        for t in doc["tasks"]:
            print(f"{t['id']:5} {','.join(t['surfaces']):11} {t['fixture']:14} {t['title']}")
        return 0
    if a.validate_only:
        print(f"{len(doc['tasks'])} tasks valid (task set {doc['version']})")
        return 0
    unknown = set(a.task) - {t["id"] for t in doc["tasks"]}
    if unknown:
        print(f"unknown task ids: {sorted(unknown)}", file=sys.stderr)
        return 2
    langs = LANGS if a.lang == "both" else (a.lang,)
    surfaces = SURFACES if a.surface == "both" else (a.surface,)
    run = run_taskset(doc, ids=a.task, langs=langs, surfaces=surfaces, controls=not a.no_controls,
                      progress=None if a.quiet else lambda s: print(f"  {s}", file=sys.stderr))
    canaries = list(doc.get("canaries", [])) + [s for t in doc["tasks"] for s in t.get("secrets", [])]
    path = write_report(run, report_dir, retain_content=a.retain_content, canaries=canaries)
    summary = json.loads(path.read_text())["summary"]
    print(table(run["results"]))
    print(f"\n{summary['executed']} executed: {summary['passed']} passed, {summary['failed']} failed, "
          f"{summary['known_failures']} known failures; {summary['skipped']} skipped. Negative controls: "
          f"{summary['negative_controls']}. Hard failures: {len(summary['hard_failures'])}. Verdict: {summary['verdict']}")
    print(f"tool choice is scripted; live model quality is not measured. Report: {path}")
    return {"pass": 0, "fail": 1, "blocked_by_known_limitations": 3}[summary["verdict"]]


if __name__ == "__main__":
    sys.exit(main())
