"""Provider-agnostic LLM client for tool-calling.

Anthropic (default) uses its own SDK, OpenAI the Responses API (its current
models call tools only there), and every other provider an OpenAI-compatible
chat-completions endpoint (OPENAI_COMPATIBLE). All return the same LLMResponse
shape so the agent loop is provider-agnostic.

Usage:
    from app.services.llm_client import complete_with_tools, LLMResponse
    resp = complete_with_tools(messages, tools, system=SYSTEM_PROMPT)
"""
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


@dataclass
class LLMResponse:
    stop_reason: str           # "end_turn" | "tool_use" | "max_tokens"
    text: str | None           # assistant text (may be None on tool-use turns)
    tool_calls: list[dict]     # [{id, name, input}]


def complete_with_tools(
    messages: list[dict],
    tools: list[dict],
    *,
    provider: str | None = None,
    model: str | None = None,
    system: str = "",
    max_tokens: int = 2048,
    api_key: str | None = None,
    timeout: float | None = None,
) -> LLMResponse:
    """Call an LLM with tool definitions, return a normalised LLMResponse.

    Args:
        messages:   Conversation history in the provider-agnostic format:
                    [{"role": "user"|"assistant"|"tool", "content": ...}]
        tools:      JSON-Schema tool definitions (provider-agnostic format).
        provider:   one of PROVIDERS. Defaults to config.LLM_PROVIDER.
        model:      Model ID. Defaults to config.LLM_MODEL.
        system:     System prompt text.
        max_tokens: Maximum output tokens.
        api_key:    Optional BYOK API key. None → reads from env (default behaviour).
        timeout:    Per-call timeout in seconds (default config.ASK_PROVIDER_TIMEOUT).

    Raises LLMError (stable message, no provider text or secrets) on any failure.
    Unknown providers raise UnsupportedProvider; they never fall through.
    """
    prov = provider or config.LLM_PROVIDER
    mdl = model or config.LLM_MODEL
    kw = dict(model=mdl, system=system, max_tokens=max_tokens,
              timeout=timeout or config.ASK_PROVIDER_TIMEOUT)

    try:
        if prov == "anthropic":
            return _anthropic(messages, tools, api_key=api_key, **kw)
        if prov == "openai":
            return _openai_responses(messages, tools, api_key=_key(api_key, "OPENAI_API_KEY"), **kw)
        if prov in OPENAI_COMPATIBLE:
            base_url, env = OPENAI_COMPATIBLE[prov]
            return _openai(messages, tools, api_key=_key(api_key, env), base_url=base_url, **kw)
        if prov == "ollama" and provider_available(prov):
            return _openai(messages, tools, api_key="ollama", base_url=config.OLLAMA_BASE_URL, **kw)
    except Exception as e:  # noqa: BLE001 — classified, original text dropped
        raise classify_provider_error(e) from None
    raise UnsupportedProvider()


# ---------------------------------------------------------------------------
# Anthropic backend
# ---------------------------------------------------------------------------

def _anthropic(messages, tools, *, model, system, max_tokens, api_key=None, timeout=30.0) -> LLMResponse:
    import anthropic

    client = anthropic.Anthropic(api_key=api_key, timeout=timeout,
                                 max_retries=config.ASK_PROVIDER_MAX_RETRIES)  # None → reads ANTHROPIC_API_KEY from env

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
        tool_choice={"type": "auto"},
    )

    text = next((b.text for b in resp.content if b.type == "text"), None)
    tool_calls = [
        {"id": b.id, "name": b.name, "input": b.input}
        for b in resp.content
        if b.type == "tool_use"
    ]
    return LLMResponse(stop_reason=resp.stop_reason, text=text, tool_calls=tool_calls)


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
RESPONSES_MIN_OUTPUT_TOKENS = 8000


def _openai_responses(messages, tools, *, model, system, max_tokens, api_key, timeout=30.0) -> LLMResponse:
    """OpenAI's own models via the Responses API (stateless: store=False, full input each turn)."""
    import openai

    client = openai.OpenAI(api_key=api_key, timeout=timeout, max_retries=config.ASK_PROVIDER_MAX_RETRIES)
    resp = client.responses.create(
        model=model,
        instructions=system or None,
        input=[item for m in messages for item in _to_responses_items(m)],
        tools=[{"type": "function", "name": t["name"], "description": t.get("description", ""),
                "parameters": t.get("input_schema", {"type": "object", "properties": {}})}
               for t in tools],
        tool_choice="auto",
        max_output_tokens=max(max_tokens, RESPONSES_MIN_OUTPUT_TOKENS),
        store=False,
    )
    texts, tool_calls = [], []
    for item in resp.output or []:
        if item.type == "message":
            texts += [c.text for c in item.content or [] if getattr(c, "type", "") == "output_text"]
        elif item.type == "function_call":
            tool_calls.append({"id": item.call_id, "name": item.name,
                               "input": json.loads(item.arguments or "{}")})
    if tool_calls:
        stop = "tool_use"
    elif resp.status == "incomplete":
        stop = "max_tokens"
    else:
        stop = "end_turn"
    return LLMResponse(stop_reason=stop, text="\n".join(texts) or None, tool_calls=tool_calls)


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
            timeout=30.0) -> LLMResponse:
    import openai

    client = openai.OpenAI(api_key=api_key, base_url=base_url, timeout=timeout,
                           max_retries=config.ASK_PROVIDER_MAX_RETRIES)  # None → reads OPENAI_API_KEY / default base URL

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
        tool_choice="auto",
    )

    choice = resp.choices[0]
    msg = choice.message
    text = msg.content  # may be None
    tool_calls = []
    if msg.tool_calls:
        import json
        tool_calls = [
            {"id": tc.id, "name": tc.function.name, "input": json.loads(tc.function.arguments)}
            for tc in msg.tool_calls
        ]

    stop_reason = "tool_use" if tool_calls else (
        "end_turn" if choice.finish_reason in ("stop", "end_turn") else choice.finish_reason
    )
    return LLMResponse(stop_reason=stop_reason, text=text, tool_calls=tool_calls)


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
