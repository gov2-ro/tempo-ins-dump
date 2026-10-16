"""Provider-agnostic LLM client for tool-calling.

Anthropic (default) uses its own SDK, OpenAI the Responses API (its current
models call tools only there), and every other provider an OpenAI-compatible
chat-completions endpoint (OPENAI_COMPATIBLE). All return the same LLMResponse
shape so the agent loop is provider-agnostic.

Usage:
    from app.services.llm_client import complete_with_tools, LLMResponse
    resp = complete_with_tools(messages, tools, system=SYSTEM_PROMPT)
"""
import fnmatch
import json
import os
from dataclasses import dataclass, field
from typing import Any

from app import config

# provider -> (base URL, env var holding a server-funded key)
OPENAI_COMPATIBLE = {
    "gemini": ("https://generativelanguage.googleapis.com/v1beta/openai/", "GEMINI_API_KEY"),
    "mistral": ("https://api.mistral.ai/v1", "MISTRAL_API_KEY"),
    "deepseek": ("https://api.deepseek.com", "DEEPSEEK_API_KEY"),
    "xai": ("https://api.x.ai/v1", "XAI_API_KEY"),
    "openrouter": ("https://openrouter.ai/api/v1", "OPENROUTER_API_KEY"),
}
# Ollama runs on the operator's machine and needs no key. It exists only when
# TEMPO_OLLAMA_BASE_URL is set, so a public server never calls a local port by default.
KEYLESS = ("ollama",)
PROVIDERS = ("anthropic", "openai", *OPENAI_COMPATIBLE, *KEYLESS)


def provider_available(provider: str) -> bool:
    return provider in PROVIDERS and (provider != "ollama" or bool(config.OLLAMA_BASE_URL))


class LLMError(Exception):
    """Stable, secret-free provider failure. ``str(e)`` is safe to show to clients."""

    def __init__(self, code: str, message: str, status: int = 502, retry_after: int | None = None):
        super().__init__(message)
        self.code, self.message, self.status, self.retry_after = code, message, status, retry_after
        self.debug_detail: str | None = None   # the provider's own error, for TEMPO_ASK_DEBUG only


class UnsupportedProvider(LLMError):
    def __init__(self):
        super().__init__("unsupported_provider", "Unsupported provider", status=400)


def classify_provider_error(e: BaseException) -> LLMError:
    """Map any provider/SDK exception to a stable LLMError. Never embeds str(e)."""
    if isinstance(e, LLMError):
        return e
    name = type(e).__name__.lower()
    status = getattr(e, "status_code", None)
    if status in (401, 403):
        return LLMError("provider_auth", "The provider rejected the API key", 401)
    if status == 404:
        return LLMError("provider_model", "The provider does not know this model", 400)
    if status == 429 or "ratelimit" in name:
        return LLMError("provider_rate_limited", "The provider rate-limited the request", 429, 30)
    if "timeout" in name or isinstance(e, TimeoutError):
        return LLMError("provider_timeout", "The provider did not answer in time", 503, 10)
    if "connection" in name or (isinstance(status, int) and status >= 500):
        return LLMError("provider_unavailable", "The provider is unavailable", 503, 10)
    return LLMError("provider_error", "The provider request failed", 502)


def _key(api_key: str | None, env: str) -> str:
    """The user's key, else the server's own for this provider. Never another provider's:
    the OpenAI SDK would otherwise fall back to OPENAI_API_KEY and send it elsewhere."""
    key = api_key or os.environ.get(env, "")
    if not key:
        raise LLMError("provider_auth", "No API key for this provider", 401)
    return key


# Normalized terminal states (AT-02). The agent decides what to do from `finish`, never from
# a provider's own word: "length", "max_tokens", an incomplete Responses turn and an empty
# "stop" all arrive here as something the loop can reason about.
FINISH_COMPLETE = "complete"          # the model ended its turn
FINISH_TOOL_USE = "tool_use"          # it asked for tools
FINISH_OUTPUT_LIMIT = "output_limit"  # cut off by the output allowance (length, max_tokens)
FINISH_CONTENT_FILTER = "content_filter"
FINISH_INCOMPLETE = "incomplete"      # paused/incomplete for another reason
FINISH_OTHER = "other"

USAGE_FIELDS = ("input_tokens", "output_tokens", "reasoning_tokens", "cached_tokens")


@dataclass
class LLMResponse:
    stop_reason: str           # "end_turn" | "tool_use" | "max_tokens" | provider-specific
    text: str | None           # assistant text (may be None on tool-use turns)
    tool_calls: list[dict]     # [{id, name, input}] (+ "invalid": True when the arguments were not JSON)
    finish: str = FINISH_COMPLETE      # one of the FINISH_* states above
    usage: dict | None = None          # USAGE_FIELDS; a field the provider did not report is None
    requested_tokens: int | None = None  # the output allowance this call asked for


def requested_output_tokens(provider: str | None, model: str | None, max_tokens: int | None = None) -> int:
    """The output allowance a call actually requests: the caller's (or the configured default
    for this provider/model) and, on OpenAI's Responses API, at least its configured floor.
    The agent charges exactly this against its per-turn allowance."""
    prov, mdl = provider or config.LLM_PROVIDER, model or config.LLM_MODEL
    n = int(max_tokens) if max_tokens else output_allowance(prov, mdl)
    if prov == "openai":
        n = max(n, config.ASK_RESPONSES_MIN_OUTPUT_TOKENS)
    return n


def output_allowance(provider: str, model: str) -> int:
    """Default output tokens for one call. Reasoning tokens count against the limit, so
    models configured as reasoning-capable (TEMPO_ASK_REASONING_MODELS) get more."""
    pair = f"{provider}:{model}"
    if any(fnmatch.fnmatchcase(pair, pat) for pat in config.ASK_REASONING_MODELS):
        return max(config.ASK_OUTPUT_TOKENS, config.ASK_REASONING_OUTPUT_TOKENS)
    return config.ASK_OUTPUT_TOKENS


def _num(v) -> int | None:
    return int(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def _usage(input_t=None, output_t=None, reasoning_t=None, cached_t=None) -> dict | None:
    u = dict(zip(USAGE_FIELDS, (_num(input_t), _num(output_t), _num(reasoning_t), _num(cached_t))))
    return u if any(v is not None for v in u.values()) else None


def _attr(obj, *path):
    """obj.a.b.c, or None if any step is missing (providers differ in what they report)."""
    for name in path:
        obj = getattr(obj, name, None) if not isinstance(obj, dict) else obj.get(name)
        if obj is None:
            return None
    return obj


def _loads_args(raw) -> tuple[dict, bool]:
    """(arguments, ok). A truncated or malformed argument string is not an exception: the
    agent answers that call with an error the model can correct."""
    try:
        v = json.loads(raw or "{}")
    except (TypeError, ValueError):
        return {}, False
    return (v, True) if isinstance(v, dict) else ({}, False)


def _finish_from_stop(stop: str | None, has_tool_calls: bool) -> str:
    stop = (stop or "").lower()
    if stop in ("max_tokens", "length", "model_context_window_exceeded"):
        return FINISH_OUTPUT_LIMIT
    if stop in ("refusal", "content_filter", "safety"):
        return FINISH_CONTENT_FILTER
    if has_tool_calls or stop in ("tool_use", "tool_calls"):
        return FINISH_TOOL_USE
    if stop in ("end_turn", "stop", "stop_sequence", ""):
        return FINISH_COMPLETE
    if stop in ("pause_turn",):
        return FINISH_INCOMPLETE
    return FINISH_OTHER


def complete_with_tools(
    messages: list[dict],
    tools: list[dict],
    *,
    provider: str | None = None,
    model: str | None = None,
    system: str = "",
    max_tokens: int | None = None,
    api_key: str | None = None,
    timeout: float | None = None,
    tool_choice: str = "auto",
    max_retries: int | None = None,
) -> LLMResponse:
    """Call an LLM with tool definitions, return a normalised LLMResponse.

    Args:
        messages:   Conversation history in the provider-agnostic format:
                    [{"role": "user"|"assistant"|"tool", "content": ...}]
        tools:      JSON-Schema tool definitions (provider-agnostic format).
        provider:   one of PROVIDERS. Defaults to config.LLM_PROVIDER.
        model:      Model ID. Defaults to config.LLM_MODEL.
        system:     System prompt text.
        max_tokens: Output tokens to request. None → the configured allowance for this
                    provider/model (see requested_output_tokens).
        api_key:    Optional BYOK API key. None → reads from env (default behaviour).
        timeout:    Per-call timeout in seconds (default config.ASK_PROVIDER_TIMEOUT).
        tool_choice: "auto", or "none" to forbid tool use with the provider's own control
                    (the final answer of an Ask turn).
        max_retries: SDK-level retries. None → config.ASK_PROVIDER_MAX_RETRIES. The Ask loop
                    passes 0 because it owns the retry policy and the deadline.

    Raises LLMError (stable message, no provider text or secrets) on any failure.
    Unknown providers raise UnsupportedProvider; they never fall through.
    """
    prov = provider or config.LLM_PROVIDER
    mdl = model or config.LLM_MODEL
    requested = requested_output_tokens(prov, mdl, max_tokens)
    kw = dict(model=mdl, system=system, max_tokens=requested,
              timeout=timeout or config.ASK_PROVIDER_TIMEOUT, tool_choice=tool_choice,
              max_retries=config.ASK_PROVIDER_MAX_RETRIES if max_retries is None else max_retries)

    try:
        if prov == "anthropic":
            resp = _anthropic(messages, tools, api_key=api_key, **kw)
        elif prov == "openai":
            resp = _openai_responses(messages, tools, api_key=_key(api_key, "OPENAI_API_KEY"), **kw)
        elif prov in OPENAI_COMPATIBLE:
            base_url, env = OPENAI_COMPATIBLE[prov]
            resp = _openai(messages, tools, api_key=_key(api_key, env), base_url=base_url, **kw)
        elif prov == "ollama" and provider_available(prov):
            resp = _openai(messages, tools, api_key="ollama", base_url=config.OLLAMA_BASE_URL, **kw)
        else:
            raise UnsupportedProvider()
    except Exception as e:  # noqa: BLE001 — classified, original text dropped
        err = classify_provider_error(e)
        if err is not e:
            err.debug_detail = f"{type(e).__name__}: {str(e)[:500]}"
        raise err from None
    resp.requested_tokens = requested
    return resp


# ---------------------------------------------------------------------------
# Anthropic backend
# ---------------------------------------------------------------------------

def _anthropic(messages, tools, *, model, system, max_tokens, api_key=None, timeout=30.0,
               tool_choice="auto", max_retries=0) -> LLMResponse:
    import anthropic

    client = anthropic.Anthropic(api_key=api_key, timeout=timeout,
                                 max_retries=max_retries)  # api_key None → reads ANTHROPIC_API_KEY from env

    # Convert generic messages to Anthropic format (handles tool results)
    ant_messages = [_to_anthropic_message(m) for m in messages]

    # Convert generic tool defs to Anthropic format
    ant_tools = [
        {
            "name": t["name"],
            "description": t.get("description", ""),
            "input_schema": t.get("input_schema", {"type": "object", "properties": {}}),
        }
        for t in tools
    ]

    resp = client.messages.create(
        model=model,
        max_tokens=max_tokens,
        system=system,
        messages=ant_messages,
        tools=ant_tools,
        tool_choice={"type": "none" if tool_choice == "none" else "auto"},
    )

    text = "".join(b.text for b in resp.content if b.type == "text") or None
    tool_calls = [
        {"id": b.id, "name": b.name, "input": b.input if isinstance(b.input, dict) else {}}
        for b in resp.content
        if b.type == "tool_use"
    ]
    usage = _usage(_attr(resp, "usage", "input_tokens"), _attr(resp, "usage", "output_tokens"),
                   None, _attr(resp, "usage", "cache_read_input_tokens"))
    return LLMResponse(stop_reason=resp.stop_reason, text=text, tool_calls=tool_calls,
                       finish=_finish_from_stop(resp.stop_reason, bool(tool_calls)), usage=usage)


def _to_anthropic_message(msg: dict) -> dict:
    """Convert a generic message dict to Anthropic API format."""
    role = msg["role"]
    content = msg["content"]

    if role == "tool":
        # Tool result message — Anthropic expects role="user" with tool_result blocks
        return {
            "role": "user",
            "content": [
                {
                    "type": "tool_result",
                    "tool_use_id": msg["tool_use_id"],
                    "content": content if isinstance(content, str) else str(content),
                }
            ],
        }

    if role == "assistant" and isinstance(content, list):
        # Already in Anthropic block format (e.g. from previous turn)
        return msg

    return {"role": role, "content": content}


# ---------------------------------------------------------------------------
# OpenAI backend
# ---------------------------------------------------------------------------

# Reasoning tokens count against max_output_tokens: a budget sized for the answer
# alone can end a turn before any text or tool call.
RESPONSES_MIN_OUTPUT_TOKENS = config.ASK_RESPONSES_MIN_OUTPUT_TOKENS


def _openai_responses(messages, tools, *, model, system, max_tokens, api_key, timeout=30.0,
                      tool_choice="auto", max_retries=0) -> LLMResponse:
    """OpenAI's own models via the Responses API (stateless: store=False, full input each turn)."""
    import openai

    client = openai.OpenAI(api_key=api_key, timeout=timeout, max_retries=max_retries)
    resp = client.responses.create(
        model=model,
        instructions=system or None,
        input=[item for m in messages for item in _to_responses_items(m)],
        tools=[{"type": "function", "name": t["name"], "description": t.get("description", ""),
                "parameters": t.get("input_schema", {"type": "object", "properties": {}})}
               for t in tools],
        tool_choice="none" if tool_choice == "none" else "auto",
        max_output_tokens=max_tokens,
        store=False,
    )
    texts, tool_calls = [], []
    for item in resp.output or []:
        if item.type == "message":
            texts += [c.text for c in item.content or [] if getattr(c, "type", "") == "output_text"]
        elif item.type == "function_call":
            args, ok = _loads_args(item.arguments)
            call = {"id": item.call_id, "name": item.name, "input": args}
            if not ok:
                call["invalid"] = True
            tool_calls.append(call)
    status = getattr(resp, "status", None)
    reason = _attr(resp, "incomplete_details", "reason")
    if status == "failed":
        raise LLMError("provider_error", "The provider request failed", 502)
    if status == "incomplete":
        finish = {"max_output_tokens": FINISH_OUTPUT_LIMIT,
                  "content_filter": FINISH_CONTENT_FILTER}.get(reason, FINISH_INCOMPLETE)
    elif tool_calls:
        finish = FINISH_TOOL_USE
    else:
        finish = FINISH_COMPLETE if status in (None, "completed") else FINISH_INCOMPLETE
    stop = "tool_use" if tool_calls and finish == FINISH_TOOL_USE else (
        "max_tokens" if status == "incomplete" else "end_turn")
    usage = _usage(_attr(resp, "usage", "input_tokens"), _attr(resp, "usage", "output_tokens"),
                   _attr(resp, "usage", "output_tokens_details", "reasoning_tokens"),
                   _attr(resp, "usage", "input_tokens_details", "cached_tokens"))
    return LLMResponse(stop_reason=stop, text="\n".join(texts) or None, tool_calls=tool_calls,
                       finish=finish, usage=usage)


def _to_responses_items(msg: dict) -> list[dict]:
    """A generic (OpenAI chat-format) message as Responses API input items."""
    role, content = msg["role"], msg.get("content")
    if role == "tool":
        return [{"type": "function_call_output", "call_id": msg["tool_use_id"],
                 "output": content if isinstance(content, str) else str(content)}]
    if role == "assistant":
        chat = _to_openai_message(msg)          # Anthropic blocks -> chat tool_calls
        items = [{"role": "assistant", "content": chat["content"]}] if chat.get("content") else []
        for tc in chat.get("tool_calls") or []:
            items.append({"type": "function_call", "call_id": tc["id"],
                          "name": tc["function"]["name"], "arguments": tc["function"]["arguments"]})
        return items
    return [{"role": role, "content": content}]


def _openai(messages, tools, *, model, system, max_tokens, api_key=None, base_url=None,
            timeout=30.0, tool_choice="auto", max_retries=0) -> LLMResponse:
    import openai

    client = openai.OpenAI(api_key=api_key, base_url=base_url, timeout=timeout,
                           max_retries=max_retries)

    oai_messages = [{"role": "system", "content": system}] if system else []
    oai_messages += [_to_openai_message(m) for m in messages]

    # Convert generic tool defs to OpenAI format
    oai_tools = [
        {
            "type": "function",
            "function": {
                "name": t["name"],
                "description": t.get("description", ""),
                "parameters": t.get("input_schema", {"type": "object", "properties": {}}),
            },
        }
        for t in tools
    ]

    resp = client.chat.completions.create(
        model=model,
        max_tokens=max_tokens,
        messages=oai_messages,
        tools=oai_tools,
        tool_choice="none" if tool_choice == "none" else "auto",
    )

    choice = resp.choices[0]
    msg = choice.message
    text = msg.content  # may be None
    tool_calls = []
    for tc in msg.tool_calls or []:
        args, ok = _loads_args(tc.function.arguments)
        call = {"id": tc.id, "name": tc.function.name, "input": args}
        if not ok:
            call["invalid"] = True
        tool_calls.append(call)

    stop_reason = "tool_use" if tool_calls else (
        "end_turn" if choice.finish_reason in ("stop", "end_turn") else choice.finish_reason
    )
    finish = _finish_from_stop(choice.finish_reason, bool(tool_calls))
    usage = _usage(_attr(resp, "usage", "prompt_tokens"), _attr(resp, "usage", "completion_tokens"),
                   _attr(resp, "usage", "completion_tokens_details", "reasoning_tokens"),
                   _attr(resp, "usage", "prompt_tokens_details", "cached_tokens"))
    return LLMResponse(stop_reason=stop_reason, text=text, tool_calls=tool_calls,
                       finish=finish, usage=usage)


def _to_openai_message(msg: dict) -> dict:
    """Convert a generic message dict to OpenAI API format."""
    import json as _json
    role = msg["role"]

    if role == "tool":
        return {
            "role": "tool",
            "tool_call_id": msg["tool_use_id"],
            "content": msg["content"] if isinstance(msg["content"], str) else str(msg["content"]),
        }

    if role == "assistant":
        # Already in OpenAI format (has tool_calls field)
        if msg.get("tool_calls"):
            return {
                "role": "assistant",
                "content": msg.get("content"),
                "tool_calls": msg["tool_calls"],
            }

        # Convert from Anthropic format (content list with tool_use blocks)
        content = msg.get("content")
        if isinstance(content, list):
            tool_uses = [b for b in content if isinstance(b, dict) and b.get("type") == "tool_use"]
            if tool_uses:
                # Extract text and tool calls
                text_blocks = [b for b in content if b.get("type") == "text"]
                text = text_blocks[0]["text"] if text_blocks else None
                tool_calls = [
                    {
                        "id": t["id"],
                        "type": "function",
                        "function": {
                            "name": t["name"],
                            "arguments": _json.dumps(t["input"]),
                        },
                    }
                    for t in tool_uses
                ]
                return {
                    "role": "assistant",
                    "content": text,
                    "tool_calls": tool_calls,
                }

        # Plain text message
        return {"role": role, "content": content}

    return {"role": role, "content": msg["content"]}
