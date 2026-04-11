"""Provider-agnostic LLM client for tool-calling.

Supports Anthropic (default) and OpenAI. Both return the same LLMResponse shape
so the agent loop is provider-agnostic.

Usage:
    from app.services.llm_client import complete_with_tools, LLMResponse
    resp = complete_with_tools(messages, tools, system=SYSTEM_PROMPT)
"""
from dataclasses import dataclass, field
from typing import Any

from app import config


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
) -> LLMResponse:
    """Call an LLM with tool definitions, return a normalised LLMResponse.

    Args:
        messages:   Conversation history in the provider-agnostic format:
                    [{"role": "user"|"assistant"|"tool", "content": ...}]
        tools:      JSON-Schema tool definitions (provider-agnostic format).
        provider:   "anthropic" or "openai". Defaults to config.LLM_PROVIDER.
        model:      Model ID. Defaults to config.LLM_MODEL.
        system:     System prompt text.
        max_tokens: Maximum output tokens.
        api_key:    Optional BYOK API key. None → reads from env (default behaviour).
    """
    prov = provider or config.LLM_PROVIDER
    mdl = model or config.LLM_MODEL

    if prov == "openai":
        return _openai(messages, tools, model=mdl, system=system, max_tokens=max_tokens, api_key=api_key)
    if prov == "gemini":
        # Gemini via OpenAI-compatible endpoint — no extra dependency needed
        key = api_key or config.GEMINI_API_KEY or None
        return _openai(
            messages, tools, model=mdl, system=system, max_tokens=max_tokens,
            api_key=key,
            base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
        )
    return _anthropic(messages, tools, model=mdl, system=system, max_tokens=max_tokens, api_key=api_key)


# ---------------------------------------------------------------------------
# Anthropic backend
# ---------------------------------------------------------------------------

def _anthropic(messages, tools, *, model, system, max_tokens, api_key=None) -> LLMResponse:
    import anthropic

    client = anthropic.Anthropic(api_key=api_key)  # None → reads ANTHROPIC_API_KEY from env

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

def _openai(messages, tools, *, model, system, max_tokens, api_key=None, base_url=None) -> LLMResponse:
    import openai

    client = openai.OpenAI(api_key=api_key, base_url=base_url)  # None → reads OPENAI_API_KEY / default base URL

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
