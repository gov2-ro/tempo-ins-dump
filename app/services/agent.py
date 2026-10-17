"""NL→Data agent for the INS TEMPO explorer (AT-02).

``run_agent(question, history)`` runs a bounded tool-calling loop over the eight shared
analytical tools (`tempo-tools/2`, ``app.services.tools.registry.call_tool``). The model
never generates SQL and the agent re-implements none of the tools' statistical rules: every
number comes from a tool result, and the deterministic checks here only decide what the
answer may claim.

Bounds, all counted together (every attempt, retry and the final answer):
  * model calls (default 8) — the last available call has tools disabled and writes the
    final answer from what was gathered, with the gaps stated;
  * tool dispatches (default 12) — every model request counts; an identical request in the
    same generation is answered from the turn's cache (counted as a cache hit, not an
    execution) and a repeated refusal returns its previous outcome with its recovery
    candidates instead of another scan;
  * wall clock (default 90 s) — remaining time is computed before every provider call and
    tool run, SDK retries are off, and a running query is interrupted at the deadline or
    when the request is abandoned;
  * requested output tokens per turn (default 64,000) — charged per call, final answer
    reserved; an insufficient allowance is reported as ``output_budget``, never truncated.

The model's context holds at most ``ASK_CONTEXT_BYTES`` of tool output: older bulky results
are replaced by compact summaries under the same call id (see ask_context).
"""
import json
import logging
import os
import time
import uuid
from collections import Counter
from dataclasses import dataclass, field

from app import config
from app.db import get_conn
from app.services import answer_check, ask_context, ask_guard, ask_present, generation
from app.services.ask_guard import Cancelled, CancelToken, RedactingFilter, bound, redact
from app.services.llm_client import (FINISH_COMPLETE, FINISH_CONTENT_FILTER, FINISH_OUTPUT_LIMIT,
                                     _server_key_env, classify_provider_error, complete_with_tools,
                                     requested_output_tokens)
from app.services.tools import contract as C
from app.services.tools import registry
from app.services.tools.registry import call_tool

log = logging.getLogger(__name__)
log.addFilter(RedactingFilter())  # credentials never reach agent logs (FIX-08)

MIN_CALL_SECONDS = 2.0            # do not start a provider call with less time than this
RETRY_PAUSE_SECONDS = 0.5         # pause before the one provider retry (bounded by the deadline)
RETRYABLE = ("provider_timeout", "provider_unavailable", "provider_rate_limited")
FAILURES_BEFORE_SYNTHESIS = 3     # consecutive refusals/errors before the loop stops exploring
BUDGET_STOPS = ("iterations", "tools", "deadline", "output_budget")
_BUDGET_NOTE = {"iterations": "Reached the model-call limit", "tools": "Reached the tool-call limit",
                "deadline": "Reached the time limit", "output_budget": "Reached the output allowance"}

# ---------------------------------------------------------------------------
# Tool definitions (JSON Schema, provider-agnostic): the registry's, inlined
# ---------------------------------------------------------------------------


def tool_definitions() -> list[dict]:
    return [{"name": name, "description": registry.TOOLS[name].description,
             "input_schema": registry.inline_schema(registry.input_schema(name))}
            for name in registry.tool_names()]


TOOLS = tool_definitions()
TOOL_NAMES = {t["name"] for t in TOOLS}
DATA_TOOLS = ask_present.DATA_TOOLS

# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """Assistant for the Romanian National Institute of Statistics (INS) TEMPO Online explorer. Access to ~3,600 datasets covering demographics, economy, labor, health, education, agriculture, geography, from the 1990s onward.

Reply in the user's language (RO or EN). Dataset names in the catalog are Romanian — search in Romanian first, translating key terms via the vocabulary below.

## Tools (read-only). Each returns an envelope: status, reason, message, data, provenance (sources, selection, scope), limits, warnings, recovery.
- discover_indicators: start here when the dataset is not known. Reviewed concepts with definition, unit, actual coverage and candidate datasets, or `needs_clarification` with choices.
- describe_dataset: columns, exact period bounds, sub-datasets, how to look up every value.
- find_dimension_values: the exact values a column has (search or page; time is newest first).
- query_data: one validated selection. Collapsed dimensions follow the aggregation policy.
- compare_periods: change between exact years, ranked over every eligible entity. Use it for "which grew/fell most" and "change from X to Y"; entity_class=cities (needs REF_AREA_2) ranks only municipalities and towns in the GOS102A catalogue, which does not prove historical city status or unchanged boundaries. Never subtract or rank numbers yourself.
- rank_entities: value rankings for one year over every eligible entity; entity_class=cities excludes communes. Use for top/bottom cities or counties. Never rank a query preview yourself.
- run_recipe: a reviewed cross-dataset recipe offered by discovery (e.g. tourism intensity).
- get_evidence_links: links for a selection. The page already links the main result: call it only to cite a different one.

## Workflow
1. discover_indicators with the full question, preserving the requested measure, denominator, geography, period and operation, unless the dataset is given or an earlier selection (below) applies. If it returns needs_clarification, ask the user that question with its choices; do not guess a definition, place or period.
2. describe_dataset before query_data. Use find_dimension_values for exact values (counties, ages, periods). Never guess columns or values.
3. A `recovery` entry or a candidate's `next_call` is a candidate, not an answer: call it and read its status.
4. Use group_by for aggregates (trends, comparisons). Do not pull raw rows when a grouped summary suffices.
5. Never ask "would you like me to fetch X?". Fetch it and caveat in the answer.
6. Never substitute county for city, counts for per-capita values, or domicile for explicitly requested resident population. If the requested definition/level/operation is unavailable, explain what is missing. Report any default assumption returned by discovery.

## Vocabulary
- șomaj / rata șomajului → unemployment / rate; pe județe → by county (REF_AREA, 42); pe regiuni → by region (8 NUTS-2)
- pe sexe → by gender (SEX); pe grupe de vârstă → by age (AGE); IPC → CPI, PIB → GDP, salarii → wages, natalitate → births, mortalitate → deaths

## Results
- ok: valid for the selection and scope stated in provenance. partial: usable only with the stated scope and uncertainty (an age range, excluded entities, or unverified total completeness) — say so.
- needs_clarification: ask the user. error: the request was invalid; fix it from the message.
- unavailable: no value exists for this request. Give no figure for it, never total or rank the raw rows yourself, never repeat the same call. Follow a recovery candidate that fits the question, or explain the limitation and the reason.
- Always pass on warnings and scope.description that change the meaning: approximations, age ranges (e.g. 0–84), truncated previews, excluded entities, series breaks.
- Only cite numbers that appear in an ok or partial result. Changes and rankings come from compare_periods, rank_entities or run_recipe.

## Limits
You have a limited number of tool calls and a short time. Your final turn has tools disabled: it must answer from what you gathered and state what you could not establish.

## Answer format
Plain-language summary in the user's language with the unit, period and place, and the cited dataset code(s) in parentheses (e.g. AMG159E). Don't invent codes. Decline questions unrelated to Romanian statistics.
"""

FINAL_NOTE = """
## This is your final turn: tools are disabled
Answer now, only from the tool results above. State plainly what you could not establish{gaps}. Do not invent or compute values. If nothing usable was obtained, say so, give the reason in plain words and suggest the next step from the results' recovery entries."""

REPAIR_NOTE = """
Your previous reply was empty. Reply now with a short answer written from the tool results above, or say plainly why you cannot."""

SHORT_NOTE = """
Your previous reply ran out of output space. Reply briefly: the answer first, then at most three short caveats."""

_NOTICE = {
    "ro": {
        "budget": "Nu am putut termina în limitele cererii. {partial}Reformulați mai precis întrebarea.",
        "partial_data": "Datele parțiale sunt atașate. ",
        "empty_output": "Modelul nu a returnat niciun răspuns. Încercați din nou sau reformulați întrebarea.",
        "output_limit": "Modelul a rămas fără spațiu de ieșire înainte să răspundă. Încercați o întrebare mai restrânsă.",
        "output_budget": "Cererea a depășit bugetul de ieșire al modelului. Încercați o întrebare mai restrânsă.",
        "content_filter": "Furnizorul modelului a oprit răspunsul (filtru de conținut).",
        "cut_note": "(Răspunsul a fost întrerupt de limita de ieșire a modelului.)",
        "no_result": "Nu am obținut o valoare verificată pentru această întrebare{why}.",
        "cancelled": "Cererea a fost oprită.",
        "provider": "Furnizorul modelului {why}. {partial}Încercați din nou sau alegeți alt model.",
    },
    "en": {
        "budget": "I could not finish within the request limits. {partial}Please ask a more specific question.",
        "partial_data": "Partial data is attached. ",
        "empty_output": "The model returned no answer. Please try again or rephrase the question.",
        "output_limit": "The model ran out of output space before answering. Try a narrower question.",
        "output_budget": "The request exceeded the model output budget. Try a narrower question.",
        "content_filter": "The model provider stopped the answer (content filter).",
        "cut_note": "(The answer was cut off by the model's output limit.)",
        "no_result": "I could not obtain a verified value for this question{why}.",
        "cancelled": "The request was stopped.",
        "provider": "The model provider {why}. {partial}Try again or choose another model.",
    },
}

# What stopped the turn when the provider failed after tools had run (stable codes only).
_PROVIDER_WHY = {
    "ro": {"provider_timeout": "nu a răspuns la timp", "provider_rate_limited": "a limitat cererile (rate limit)",
           "provider_unavailable": "nu a fost disponibil"},
    "en": {"provider_timeout": "did not answer in time", "provider_rate_limited": "rate-limited the request",
           "provider_unavailable": "was unavailable"},
}

# ---------------------------------------------------------------------------
# Agent result
# ---------------------------------------------------------------------------


@dataclass
class AgentResult:
    answer: str
    citations: list = field(default_factory=list)
    tool_trace: list = field(default_factory=list)
    data: dict | None = None
    chart_spec: dict | None = None
    warnings: list = field(default_factory=list)
    # "end_turn" normally; else why the turn ended early: "iterations" | "tools" | "deadline" |
    # "provider" | "output_limit" | "output_budget" | "empty_output" | "content_filter" | "cancelled"
    stop_reason: str = "end_turn"
    budget: dict = field(default_factory=dict)
    # Deterministic answer check: {status: verified|unverified_numbers|values_withheld|no_values,
    #  valid_query, uncited_numbers, unavailable, approximations, claims: [...], claim_summary,
    #  claim_reasons: {stable reason: count}}
    verification: dict = field(default_factory=dict)
    # Terminal state; HTTP 200 and end_turn do not mean a substantive answer.
    outcome: str = "answered"        # answered | clarification | refused | partial | failed
    reason: str | None = None
    context: list = field(default_factory=list)   # follow-up selections for the next turn
    usage: dict | None = None
    metrics: dict = field(default_factory=dict)   # content-free, for the operational log


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _synthetic(tool: str, status: str, reason: str, message: str, recovery=()) -> dict:
    """An envelope the agent itself produces (a call it did not execute)."""
    ctx = C.ToolContext(conn=None, lang="ro", generation=generation.current(), request_id="agent")
    return C.envelope(tool[:64], ctx, status=status, reason=reason, message=message,
                      recovery=list(recovery))


def _compact_outcome(env: dict, note: str) -> dict:
    """A previous refusal handed back instead of a second scan: its status, reason, message
    and recovery candidates, labelled as a repeat."""
    return {**env, "data": {}, "warnings": [*env.get("warnings", []),
            C.warning("repeated_request", note)]}


def _assistant_turn(resp, provider: str | None = None) -> dict:
    """Build an assistant message from an LLMResponse."""
    prov = provider or config.LLM_PROVIDER
    if prov == "anthropic":
        content = []
        if resp.text:
            content.append({"type": "text", "text": resp.text})
        for tc in resp.tool_calls:
            content.append({"type": "tool_use", "id": tc["id"], "name": tc["name"], "input": tc["input"]})
        return {"role": "assistant", "content": content}
    return {
        "role": "assistant",
        "content": resp.text,
        "tool_calls": [
            {"id": tc["id"], "type": "function",
             "function": {"name": tc["name"], "arguments": json.dumps(tc["input"])}}
            for tc in resp.tool_calls
        ] if resp.tool_calls else None,
    }


def _guess_lang(question: str) -> str:
    return answer_check.guess_lang(question)


# ---------------------------------------------------------------------------
# The loop
# ---------------------------------------------------------------------------


class _Stop(Exception):
    """Ends the loop with a result (carries it)."""

    def __init__(self, result: "AgentResult"):
        self.result = result


class _Run:
    def __init__(self, question, history, *, provider, model, api_key, on_event, context, cancel,
                 request_id):
        self.question = question
        self.provider, self.model, self.api_key = provider, model, api_key
        self.prov_name = provider or config.LLM_PROVIDER
        self.model_name = model or config.LLM_MODEL
        self.on_event = on_event
        self.cancel = cancel or CancelToken()
        self.request_id = request_id or uuid.uuid4().hex[:12]
        self.prior_context = list(context or [])
        self.lang = _guess_lang(question)

        self.messages = list(history or [])
        self.messages.append({"role": "user", "content": question})
        self.conn = None                      # the cursor this run owns (closed in close())

        self.started = time.monotonic()
        self.deadline = self.started + config.ASK_MAX_SECONDS

        self.iterations = 0                   # model calls, retries and the final answer included
        self.tools_used = 0                   # model-requested dispatches (executed or cached)
        self.executions = 0                   # tools actually run
        self.cache_hits = 0
        self.retries = 0                      # provider retries (at most one) + output/empty repairs
        self.requested_tokens = 0             # output tokens requested so far
        self.last_requested = 0               # ... by the latest call
        self.usage = {k: None for k in ("input_tokens", "output_tokens", "reasoning_tokens", "cached_tokens")}
        self.tool_result_bytes = 0
        self.refusal_codes: dict[str, int] = {}

        self.trace: list[dict] = []           # [{id, tool, input, output, executed, cached}]
        self.retained: list[dict] = []        # tool results still in the model's context
        self.cache: dict[tuple, dict] = {}    # (tool, args, generation) -> {env, executions}
        self.warnings: list[str] = []
        self.consecutive_failures = 0
        self.force_final: str | None = None   # why the next model call is the final one
        self.provider_retry_used = False
        self.provider_code: str | None = None  # the stable code of the failure that ended the turn
        self.output_retry_used = False
        self.repair_used = False
        self.guardrail_fired = False
        self.no_tools_next = False            # the next call is a repair: tools stay disabled
        self.exploring = False                # the last non-final model turn asked for tools
        self.dropped_events = 0
        self.events_kept = 0

    # ------------------------------------------------------------ plumbing

    def remaining(self) -> float:
        return self.deadline - time.monotonic()

    def emit(self, kind: str, **fields) -> None:
        """A debug step (only when a sink is attached). Credentials and bulk are removed
        before the event is logged or delivered, and the count of stored events is capped."""
        if self.on_event is None:
            return
        if self.events_kept >= config.ASK_DEBUG_MAX_EVENTS:
            self.dropped_events += 1
            return
        self.events_kept += 1
        ev = {"event": kind, "ms": int((time.monotonic() - self.started) * 1000), **fields}
        ev = bound(redact(ev, ask_guard.active_secrets()))
        log.info("ASK_DEBUG %s", json.dumps(ev, ensure_ascii=False, default=str))
        try:
            self.on_event(ev)
        except Exception:  # noqa: BLE001 — a debug sink must never break the answer
            pass

    def budget(self) -> dict:
        return {
            "iterations": self.iterations, "max_iterations": config.ASK_MAX_ITERATIONS,
            "tools": self.tools_used, "max_tools": config.ASK_MAX_TOOL_CALLS,
            "executions": self.executions, "cache_hits": self.cache_hits,
            "elapsed_s": round(time.monotonic() - self.started, 3), "max_seconds": config.ASK_MAX_SECONDS,
            "output_tokens_requested": self.requested_tokens,
            "max_output_tokens": config.ASK_TURN_OUTPUT_TOKENS,
            "context_bytes": ask_context.retained_bytes(self.retained),
            "max_context_bytes": config.ASK_CONTEXT_BYTES,
        }

    def close(self) -> None:
        if self.conn is not None:
            try:
                self.conn.close()
            except Exception:  # noqa: BLE001
                pass

    # ------------------------------------------------------------ planning

    def plan(self) -> bool:
        """Decide the next model call: True when it must be the final (no tools) call.
        Raises _Stop when no call can be made."""
        if self.cancel.cancelled:
            raise _Stop(self.finish_without_model("cancelled"))
        if self.remaining() < MIN_CALL_SECONDS:
            raise _Stop(self.finish_without_model("deadline"))
        calls_left = config.ASK_MAX_ITERATIONS - self.iterations
        if calls_left <= 0:
            raise _Stop(self.finish_without_model("iterations"))
        allowance = requested_output_tokens(self.prov_name, self.model_name)
        tokens_left = config.ASK_TURN_OUTPUT_TOKENS - self.requested_tokens
        if tokens_left < allowance:
            raise _Stop(self.finish_without_model("output_budget"))
        final = bool(self.force_final) or self.no_tools_next
        if not final:
            if calls_left <= 1:
                final, self.force_final = True, "iterations"
            elif config.ASK_MAX_TOOL_CALLS - self.tools_used <= 0:
                final, self.force_final = True, "tools"
            elif tokens_left - allowance < allowance:       # keep the final answer's allowance
                final, self.force_final = True, "output_budget"
            elif self.remaining() < 2 * MIN_CALL_SECONDS:
                final, self.force_final = True, "deadline"
        return final

    # ------------------------------------------------------------ model call

    def call_model(self, final: bool, *, system_extra: str = "", allowance: int | None = None):
        """One provider call, fully counted. Returns the LLMResponse, or None when a
        retryable provider failure was absorbed (the caller loops and re-plans)."""
        self.iterations += 1
        tokens = requested_output_tokens(self.prov_name, self.model_name, allowance)
        self.requested_tokens += tokens
        self.last_requested = tokens
        system = SYSTEM_PROMPT + ("\n" + ask_context.prompt_section(self.prior_context)
                                  if self.prior_context else "")
        if final:
            system += FINAL_NOTE.format(gaps=self._gaps())
        system += system_extra
        self.emit("model_call", iteration=self.iterations, messages=len(self.messages),
                  final=final, max_tokens=tokens)
        t_call = time.monotonic()
        try:
            resp = complete_with_tools(
                self.messages, TOOLS, system=system, provider=self.provider, model=self.model,
                api_key=self.api_key, max_tokens=tokens, max_retries=0,
                tool_choice="none" if final else "auto",
                timeout=max(1.0, min(config.ASK_PROVIDER_TIMEOUT, self.remaining())))
        except Exception as e:  # noqa: BLE001
            err = classify_provider_error(e)
            self.emit("model_error", iteration=self.iterations,
                      took_ms=int((time.monotonic() - t_call) * 1000), code=err.code,
                      detail=getattr(err, "debug_detail", None) or type(e).__name__)
            if self.cancel.cancelled:
                raise _Stop(self.finish_without_model("cancelled")) from None
            if (err.code in RETRYABLE and not self.provider_retry_used
                    and self.iterations < config.ASK_MAX_ITERATIONS and self.remaining() > 3 * MIN_CALL_SECONDS):
                self.provider_retry_used = True
                self.retries += 1
                self.emit("retry", code=err.code)
                time.sleep(min(RETRY_PAUSE_SECONDS, self.remaining() / 10))
                return None
            if err.code in RETRYABLE and any(t.get("executed", True) for t in self.trace):
                log.warning("Provider error after %d tools: %s", len(self.trace), err.code)
                self.provider_code = err.code
                raise _Stop(self.finish_without_model("provider")) from None
            raise err from None
        self.emit("model_done", iteration=self.iterations, took_ms=int((time.monotonic() - t_call) * 1000),
                  stop_reason=resp.stop_reason, finish=resp.finish,
                  tool_calls=[tc["name"] for tc in resp.tool_calls], text_chars=len(resp.text or ""),
                  usage=resp.usage)
        for k, v in (resp.usage or {}).items():
            if v is not None:
                self.usage[k] = (self.usage.get(k) or 0) + v
        if self.cancel.cancelled:
            raise _Stop(self.finish_without_model("cancelled"))
        return resp

    def _gaps(self) -> str:
        """Server-side list of what the turn could not establish, for the final turn."""
        gaps = []
        for t in self.trace:
            env = t.get("output") or {}
            if t.get("tool") in DATA_TOOLS and env.get("status") in ("unavailable", "error"):
                gaps.append(f"{t['tool']} → {env.get('reason')}")
        if self.force_final in BUDGET_STOPS:
            gaps.append(f"the {self.force_final} limit was reached")
        gaps = list(dict.fromkeys(gaps))[:6]
        return f" (known gaps: {'; '.join(gaps)})" if gaps else ""

    # ------------------------------------------------------------ tools

    def dispatch(self, tc: dict) -> dict:
        """The envelope for one model-requested tool call (executed, cached or synthetic)."""
        name, args = tc["name"], tc.get("input") or {}
        self.emit("tool", name=name, input=args)
        t0 = time.monotonic()
        executed, cached = False, False
        skipped = False        # answered for the provider's call/result pairing, never traced
        if self.tools_used >= config.ASK_MAX_TOOL_CALLS:
            env = _synthetic(name, "unavailable", "tool_budget",
                             "Not executed: the tool-call limit was reached. Answer from the results you have.")
            self.force_final, skipped = self.force_final or "tools", True
        elif self.remaining() <= 0 or self.cancel.cancelled:
            env = _synthetic(name, "unavailable", "deadline",
                             "Not executed: the time limit was reached. Answer from the results you have.")
            self.force_final, skipped = self.force_final or "deadline", True
        else:
            self.tools_used += 1
            if name not in TOOL_NAMES:
                env = _synthetic(name, "error", "unknown_tool",
                                 f"Unknown tool {name[:64]!r}; available: {', '.join(sorted(TOOL_NAMES))}.")
            elif tc.get("invalid"):
                env = _synthetic(name, "error", "invalid_input",
                                 "The tool arguments were cut off or were not a JSON object; call the tool "
                                 "again with complete arguments.")
            else:
                env, executed, cached = self._run_tool(name, args)
        if skipped:
            return env
        self.tool_result_bytes += C.size(env)
        status = env.get("status")
        if status in ("unavailable", "error", "needs_clarification") and env.get("reason") \
                and (executed or cached):
            self.refusal_codes[env["reason"]] = self.refusal_codes.get(env["reason"], 0) + 1
        self._track_failures(status, env, executed or cached)
        self.emit("tool_done", name=name, took_ms=int((time.monotonic() - t0) * 1000), status=status,
                  reason=env.get("reason"), cached=cached,
                  rows=len(((env.get("data") or {}).get("rows") or [])) or None,
                  result_bytes=C.size(env))
        self.trace.append({"id": tc["id"], "tool": name, "input": args, "output": env,
                           "executed": executed or cached, "cached": cached})
        for w in env.get("warnings") or []:
            msg = w.get("message") if isinstance(w, dict) else str(w)
            if msg and msg not in self.warnings and name in DATA_TOOLS:
                self.warnings.append(msg)
        return env

    def _run_tool(self, name: str, args: dict):
        key = (name, C.dumps(args), generation.current().get("id"))
        prev = self.cache.get(key)
        if prev:
            env = prev["env"]
            transient = env.get("reason") in ("busy", "query_timeout", "execution_failed")
            if prev["executions"] >= 2 or not (transient and env.get("status") != "ok"):
                self.cache_hits += 1
                if env.get("status") in ("ok", "partial"):
                    return env, False, True
                return _compact_outcome(env, "This exact request was already made this turn and refused; "
                                             "its outcome and recovery candidates are repeated, not re-run. "
                                             "Narrow or change the request."), False, True
        try:
            with self.cancel.running(self.conn, deadline_in=max(0.0, self.remaining())):
                env = call_tool(name, args, conn=self.conn)
        except Cancelled:
            env = _synthetic(name, "unavailable", "cancelled", "Not executed: the request was stopped.")
            return env, False, False
        except Exception:  # noqa: BLE001 — the registry does not raise; this is the last resort
            log.exception("tool dispatch failed tool=%s", name)
            env = _synthetic(name, "error", "execution_failed", "The tool failed; nothing was computed.")
        self.executions += 1
        slot = self.cache.setdefault(key, {"env": env, "executions": 0})
        slot["env"], slot["executions"] = env, slot["executions"] + 1
        return env, True, False

    def _track_failures(self, status, env, counted: bool) -> None:
        if status in ("ok", "partial"):
            self.consecutive_failures = 0
        elif counted and status in ("unavailable", "error"):
            self.consecutive_failures += 1
            if self.consecutive_failures >= FAILURES_BEFORE_SYNTHESIS and not self.force_final:
                # no justified next action is left: answer with the known reason and sources
                self.force_final = "no_progress"

    def append_tool_turn(self, resp, envs: list[tuple[dict, dict]]) -> None:
        self.messages.append(_assistant_turn(resp, provider=self.prov_name))
        holders = []
        if self.prov_name == "anthropic":
            blocks = [{"type": "tool_result", "tool_use_id": tc["id"], "content": C.dumps(env)}
                      for tc, env in envs]
            self.messages.append({"role": "user", "content": blocks})
            holders = blocks
        else:
            for tc, env in envs:
                m = {"role": "tool", "tool_use_id": tc["id"], "content": C.dumps(env)}
                self.messages.append(m)
                holders.append(m)
        for h, (tc, env) in zip(holders, envs):
            self.retained.append({"holder": h, "id": tc["id"], "envelope": env})
        n = ask_context.compact_to_budget(self.retained, config.ASK_CONTEXT_BYTES)
        if n:
            self.emit("compact", results=n, context_bytes=ask_context.retained_bytes(self.retained))

    # ------------------------------------------------------------ guardrail

    def should_nudge(self) -> bool:
        """The model answered without data although discovery found candidates (one-shot)."""
        if self.guardrail_fired or any(t["tool"] in DATA_TOOLS for t in self.trace):
            return False
        if config.ASK_MAX_ITERATIONS - self.iterations < 3:
            return False
        for t in self.trace:
            env = t["output"]
            d = env.get("data") or {}
            if t["tool"] == "discover_indicators" and env.get("status") == "ok" \
                    and (d.get("concepts") or d.get("families")):
                return True
        return False

    # ------------------------------------------------------------ results

    def execute(self) -> AgentResult:
        self.emit("start", provider=self.prov_name, model=self.model_name,
                  history_turns=len(self.messages) - 1, context_entries=len(self.prior_context))
        self.conn = get_conn()
        try:
            return self._loop()
        except _Stop as stop:
            return stop.result

    def _loop(self) -> AgentResult:
        retry_note, retry_allowance = "", None
        while True:
            final = self.plan()
            resp = self.call_model(final, system_extra=retry_note, allowance=retry_allowance)
            if resp is None:                      # a retryable provider failure was absorbed
                continue
            retry_note, retry_allowance, self.no_tools_next = "", None, False
            usable_calls = [tc for tc in resp.tool_calls] if resp.finish != FINISH_OUTPUT_LIMIT \
                else [tc for tc in resp.tool_calls if not tc.get("invalid")]
            text = (resp.text or "").strip()

            if resp.finish == FINISH_CONTENT_FILTER:
                return self.conclude(None, failed="content_filter")

            if usable_calls and not final:
                self.exploring = True
                # (a cut-off reply's complete calls run; its cut-off ones get an error to correct)
                envs = [(tc, self.dispatch(tc)) for tc in resp.tool_calls]
                self.append_tool_turn(resp, envs)
                continue

            # no tool will run: this reply is the answer (or a failure to give one)
            if resp.finish == FINISH_OUTPUT_LIMIT and not text:
                if not self.output_retry_used and self._can_retry(extra_calls=1):
                    self.output_retry_used = True
                    self.retries += 1
                    ask_context.compact_to_budget(self.retained, 0, keep_latest=1)
                    self.emit("retry", code="output_limit")
                    retry_note = SHORT_NOTE
                    retry_allowance = self._larger_allowance(resp)
                    self.no_tools_next = final
                    continue
                return self.conclude(None, failed="output_limit")
            if not text and resp.tool_calls:
                # tools were requested on a turn where none may run (the provider ignored the
                # disabled tool_choice): there is no answer, only what was gathered
                stop = self.force_final if self.force_final in BUDGET_STOPS else "tools"
                return self.conclude(None, stopped=stop)
            if not text:
                if not self.repair_used and self._can_retry(extra_calls=1):
                    self.repair_used = True
                    self.retries += 1
                    self.emit("retry", code="empty_output")
                    retry_note = REPAIR_NOTE
                    self.no_tools_next = True
                    continue
                return self.conclude(None, failed="empty_output")

            if not final and not usable_calls and resp.finish == FINISH_COMPLETE and self.should_nudge():
                self.guardrail_fired = True
                self.messages.append(_assistant_turn(resp, provider=self.prov_name))
                self.messages.append({"role": "user", "content": (
                    "You found relevant datasets but did not query any data. Call describe_dataset on the "
                    "most relevant candidate, then query_data (or compare_periods) to get actual numbers "
                    "before answering.")})
                self.warnings.append("Guardrail: model skipped data query — injected follow-up turn.")
                self.emit("guardrail", note="discovery found candidates but no data was queried; nudging the model")
                continue

            forced = self.force_final if (final and self.exploring and self.force_final in BUDGET_STOPS) else None
            return self.conclude(resp.text, forced=forced, cut=resp.finish == FINISH_OUTPUT_LIMIT)

    def _can_retry(self, *, extra_calls: int) -> bool:
        return (config.ASK_MAX_ITERATIONS - self.iterations >= extra_calls
                and self.remaining() > 2 * MIN_CALL_SECONDS
                and config.ASK_TURN_OUTPUT_TOKENS - self.requested_tokens
                >= requested_output_tokens(self.prov_name, self.model_name))

    def _larger_allowance(self, resp) -> int:
        """A suitable allowance for the one bounded retry: bigger than the call that ran out,
        never more than the turn has left."""
        left = config.ASK_TURN_OUTPUT_TOKENS - self.requested_tokens
        want = max(2 * self.last_requested, config.ASK_REASONING_OUTPUT_TOKENS)
        return max(1, min(want, left))

    # ------------------------------------------------------------ conclusion

    def finish_without_model(self, stop: str) -> AgentResult:
        """The loop cannot make another model call: end with what exists."""
        self.emit("stopped", reason=stop)
        if stop == "provider":
            self.warnings.append(f"The model provider failed ({self.provider_code or 'provider_error'}) "
                                 "before a final answer; the result is partial.")
        return self.conclude(None, failed="cancelled" if stop == "cancelled" else None,
                             stopped=None if stop == "cancelled" else stop)

    def conclude(self, text, *, failed: str | None = None, forced: str | None = None,
                 cut: bool = False, stopped: str | None = None) -> AgentResult:
        """Build the terminal result: the answer (or a stable notice), its verification,
        outcome, display table, links and the next turn's context."""
        notices = _NOTICE[self.lang]
        usable = any(ask_present._usable(t) for t in self.trace)
        stop_reason = failed or stopped or forced or ("output_limit" if cut else "end_turn")
        if (forced or stopped) in _BUDGET_NOTE:
            self.warnings.append(_BUDGET_NOTE[forced or stopped]
                                 + (" before a final answer; the result is partial." if stopped
                                    else " before the exploration finished; the answer is partial."))

        if text is None or not str(text).strip():
            key = failed or stopped
            partial = notices["partial_data"] if usable else ""
            if key == "provider":
                whys = _PROVIDER_WHY[self.lang]
                why = whys.get(self.provider_code or "", whys["provider_unavailable"])
                text = notices["provider"].format(why=why, partial=partial)
            else:
                text = notices[key] if key in notices else notices["budget"].format(partial=partial)
        elif cut:
            text = text.rstrip() + "\n\n" + notices["cut_note"]

        answer, verification = self._check_answer(text)
        outcome, reason = self._outcome(answer, failed, stopped, forced, cut, usable, verification)
        table = ask_present.display_table(self.trace)
        from app.services.tools.intent import interpret
        if table is not None and interpret(self.question)["operation"] == "rank" and table.get("tool") == "query_data":
            table = None
            outcome, reason = "partial", "ranking_unverified"
            answer = ("Nu am obținut un clasament verificat pentru întreaga selecție. "
                      "Rezultatul disponibil este doar o interogare fără clasare." if self.lang == "ro" else
                      "I could not obtain a verified ranking over the full selection. "
                      "The available result is an unranked query.")
            self.warnings.append("An unranked query preview was hidden: it does not answer the requested ranking.")
        if table is not None:
            table["links"] = self._links()
        ctx_entries = ask_context.merge(
            self.prior_context,
            [e for t in self.trace if t.get("executed", True) and
             (e := ask_context.entry_from_envelope(t["tool"], t["output"])) is not None])
        usage = self.usage if any(v is not None for v in self.usage.values()) else None
        metrics = {
            "request_id": self.request_id, "outcome": outcome, "reason": reason,
            "stop_reason": stop_reason, "model_attempts": self.iterations, "retries": self.retries,
            "tool_dispatches": self.tools_used, "tool_executions": self.executions,
            "cache_hits": self.cache_hits, "duration_ms": int((time.monotonic() - self.started) * 1000),
            "tool_result_bytes": self.tool_result_bytes, "usage": usage,
            "refusal_codes": dict(self.refusal_codes), "cancelled": self.cancel.cancelled,
            "timed_out": self.cancel.timed_out or stop_reason == "deadline",
            "requested_output_tokens": self.requested_tokens,
            "dropped_debug_events": self.dropped_events, "context_entries": len(ctx_entries),
            "claim_codes": {**{k: n for k, n in (verification.get("claim_summary") or {}).items() if n},
                            **(verification.get("claim_reasons") or {})},
        }
        self.emit("answer", text_chars=len(answer), outcome=outcome, reason=reason)
        budget = self.budget()
        if self.dropped_events:
            budget["dropped_debug_events"] = self.dropped_events
        return AgentResult(
            answer=answer, citations=ask_present.citations(answer, self.trace),
            tool_trace=self.trace, data=table, chart_spec=self._chart_spec() if table is not None else None, warnings=self.warnings,
            stop_reason=stop_reason, budget=budget, verification=verification,
            outcome=outcome, reason=reason, context=ctx_entries, usage=usage, metrics=metrics)

    def _outcome(self, answer, failed, stopped, forced, cut, usable, verification) -> tuple[str, str | None]:
        """answered | clarification | refused | partial | failed, with a stable reason."""
        if failed:
            return "failed", failed
        real = [t for t in self.trace if t.get("executed", True)]
        refusals = [t["output"] for t in real
                    if t["output"].get("status") in ("unavailable", "error") and t["tool"] in DATA_TOOLS]
        if stopped or forced:
            if usable:
                return "partial", stopped or forced
            if refusals:
                return "refused", refusals[-1].get("reason")
            # nothing usable and nothing refused: an answer written at the limit is partial,
            # no answer at all is a failure
            return ("failed", stopped) if stopped else ("partial", forced)
        if cut:
            return "partial", "output_limit"
        if verification["status"] == "claim_mismatch":
            return "partial", "claim_mismatch"
        if verification["status"] == "unverified_numbers":
            return "partial", "unverified_numbers"
        if verification["status"] == "values_withheld":
            return "refused", "no_valid_query"
        if not usable:
            last = real[-1]["output"] if real else None
            if last is not None and last.get("status") == "needs_clarification":
                return "clarification", last.get("reason")
            if refusals:
                return "refused", refusals[-1].get("reason")
            if not real and answer.rstrip().endswith("?"):
                return "clarification", "question"
        return "answered", None

    # ------------------------------------------------------------ verification

    def _check_answer(self, answer: str) -> tuple[str, dict]:
        """Deterministic and outside the prompt: keep aggregation warnings on the answer, flag
        numbers no valid result contains, bind each claim to its cell, withhold an answer that
        claims values without any valid result."""
        lang, valid = self.lang, answer_check.valid_queries(self.trace)
        unavailable = [
            {"matrix_code": ((t["output"].get("provenance") or {}).get("selection") or {}).get("dataset"),
             "reason": t["output"].get("reason")}
            for t in self.trace
            if t["tool"] in DATA_TOOLS and t.get("executed", True)
            and t["output"].get("status") == "unavailable"]
        approx = sorted({((v.get("provenance") or {}).get("selection") or {}).get("dataset")
                         for v in valid
                         if (v.get("provenance") or {}).get("aggregation", {}).get("approximation")} - {None})
        ver = {"valid_query": bool(valid), "uncited_numbers": [], "unavailable": unavailable,
               "approximations": approx, "status": "no_values", "claims": [],
               "claim_summary": {"matched": 0, "unverified": 0}}
        warns: list[str] = []
        if not valid:
            if answer_check.has_value_claims(answer, self.question):
                ver["status"] = "values_withheld"
                ver["uncited_numbers"] = [c["raw"] for c in answer_check.find_numbers(answer, self.question)]
                warns.append("Answer withheld: it stated figures but no data query succeeded.")
                answer = answer_check.NOTICES[lang]["withheld"]
                if unavailable:
                    answer += f" ({', '.join(sorted({u['reason'] or '?' for u in unavailable}))})"
        else:
            unc = answer_check.uncited_numbers(answer, valid, self.question)
            if unc:
                ver["status"] = "unverified_numbers"
                ver["uncited_numbers"] = unc
                warns.append("Numbers not found in any query result (derived or unverified): "
                             + ", ".join(unc[:8]))
            else:
                ver["status"] = "verified"
            ver["claims"] = answer_check.bind_claims(answer, self.question, self.trace)
            ver["claim_summary"] = {
                "matched": sum(c["check"] == "matched" for c in ver["claims"]),
                "unverified": sum(c["check"] == "unverified" for c in ver["claims"])}
            # stable reason -> count, never the claim text (debug event and content-free metrics)
            ver["claim_reasons"] = dict(sorted(Counter(
                c["reason"] for c in ver["claims"] if c.get("reason")).items()))
            self.emit("claims", **ver["claim_summary"], reasons=ver["claim_reasons"],
                      complete=sum(bool((c.get("anchors") or {}).get("complete")) for c in ver["claims"]))
            if ver["claim_summary"]["unverified"]:
                ver["status"] = "unverified_numbers"
            contradictions = [c for c in ver["claims"] if c.get("reason") in answer_check.CONTRADICTIONS]
            if contradictions:
                ver["status"] = "claim_mismatch"
                answer = ("Am retras explicația deoarece unitatea sau perioada nu corespund datelor. "
                          "Consultați tabelul și sursele pentru selecția verificată." if lang == "ro" else
                          "I withheld the explanation because its unit or period contradicts the data. "
                          "See the table and sources for the validated selection.")
                warns.append("Answer withheld: explicit unit or period contradicts the cited result.")
            notes = answer_check.approximation_notes(answer, self.trace, lang)
            if notes:
                answer = answer.rstrip() + "\n\n" + "\n".join(notes)
        for w in warns:
            if w not in self.warnings:
                self.warnings.append(w)
        return answer, ver

    # ------------------------------------------------------------ display

    def _links(self) -> list[dict]:
        sel = ask_present.selection_of(self.trace)
        if sel is None:
            return []
        try:
            env = call_tool("get_evidence_links", {"selection": sel[0], "generation_id": sel[1],
                                                   "lang": self.lang}, conn=self.conn)
        except Exception:  # noqa: BLE001
            return []
        if env.get("status") != "ok":
            return []
        return [{k: l.get(k) for k in ("kind", "url", "description", "generation_mode")}
                for l in (env.get("data") or {}).get("links") or []]

    def _chart_spec(self) -> dict | None:
        code = ask_present.chart_dataset(self.trace)
        if not code:
            return None
        try:
            from app.services.dataset_meta import get_dataset_meta
            meta = get_dataset_meta(code, conn=self.conn)
            return meta.get("chart_config") if meta else None
        except Exception:  # noqa: BLE001
            return None


def run_agent(
    question: str,
    history: list[dict] | None = None,
    *,
    provider: str | None = None,
    model: str | None = None,
    api_key: str | None = None,
    on_event=None,
    context: list[dict] | None = None,
    cancel: CancelToken | None = None,
    request_id: str | None = None,
) -> AgentResult:
    """Run the NL→Data agent loop.

    Args:
        question: User's natural language question.
        history:  Prior conversation turns in the format [{role, content}, ...].
        provider: LLM provider override. None → env default.
        model:    Model ID override. None → env default.
        api_key:  BYOK API key. None → reads from env (default behaviour). It is removed from
                  every log record and debug event while the request runs.
        on_event: Debug hook (TEMPO_ASK_DEBUG): called with one bounded, redacted dict per
                  step, each stamped with ms since start.
        context:  Validated follow-up selections from earlier turns (ask_context.validate).
        cancel:   CancelToken; cancelling it stops the loop and interrupts the running query.

    Returns an AgentResult. It raises LLMError (stable text) for a provider failure with
    nothing gathered yet; a failure after tools ran returns a partial result instead.
    """
    prov = provider or config.LLM_PROVIDER
    run = _Run(question, history, provider=provider, model=model, api_key=api_key,
               on_event=on_event, context=context, cancel=cancel, request_id=request_id)
    with ask_guard.secrets_scope(api_key, os.environ.get(_server_key_env(prov), "")):
        try:
            return run.execute()
        finally:
            run.close()
