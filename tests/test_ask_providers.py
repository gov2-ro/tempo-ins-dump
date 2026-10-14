"""Ask providers: routing, per-provider keys, OpenAI's Responses API, local Ollama.

Offline: the SDKs are replaced by fakes that record what would be sent.
"""
import json
import sys
import types

import pytest

from fix08_helpers import FAKE_KEY, install, make_client, text_resp
from app import config
from app.services import ask_guard
from app.services import llm_client as lc
from app.services.llm_client import LLMError, complete_with_tools

TOOLS = [{"name": "list_categories", "description": "d", "input_schema": {"type": "object", "properties": {}}}]


@pytest.fixture
def fake_openai(monkeypatch):
    """Records every OpenAI() client and request; answers with `answers` in turn."""
    seen = {"clients": [], "chat": [], "responses": [], "answers": []}

    def chat_create(**kw):
        seen["chat"].append(kw)
        msg = types.SimpleNamespace(content="ok", tool_calls=None)
        return types.SimpleNamespace(choices=[types.SimpleNamespace(message=msg, finish_reason="stop")])

    def responses_create(**kw):
        seen["responses"].append(kw)
        return seen["answers"].pop(0)

    class OpenAI:
        def __init__(self, **kw):
            seen["clients"].append(kw)
            self.chat = types.SimpleNamespace(completions=types.SimpleNamespace(create=chat_create))
            self.responses = types.SimpleNamespace(create=responses_create)

    monkeypatch.setitem(sys.modules, "openai", types.SimpleNamespace(OpenAI=OpenAI))
    for env in ("OPENAI_API_KEY", "MISTRAL_API_KEY", "DEEPSEEK_API_KEY", "XAI_API_KEY",
                "OPENROUTER_API_KEY", "GEMINI_API_KEY"):
        monkeypatch.delenv(env, raising=False)
    return seen


@pytest.mark.parametrize("provider", sorted(lc.OPENAI_COMPATIBLE))
def test_compatible_provider_gets_its_base_url_and_the_users_key(fake_openai, provider):
    complete_with_tools([{"role": "user", "content": "x"}], TOOLS, provider=provider, model="m", api_key="user-key")
    c = fake_openai["clients"][0]
    assert c["base_url"] == lc.OPENAI_COMPATIBLE[provider][0] and c["api_key"] == "user-key"
    assert fake_openai["chat"][0]["model"] == "m"


def test_server_key_is_read_per_provider_never_openais(fake_openai, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-openai-server")
    with pytest.raises(LLMError) as e:
        complete_with_tools([{"role": "user", "content": "x"}], TOOLS, provider="mistral", model="m")
    assert e.value.code == "provider_auth" and fake_openai["clients"] == []
    monkeypatch.setenv("MISTRAL_API_KEY", "mistral-server")
    complete_with_tools([{"role": "user", "content": "x"}], TOOLS, provider="mistral", model="m")
    assert fake_openai["clients"][0]["api_key"] == "mistral-server"


def _resp(output, status="completed"):
    return types.SimpleNamespace(output=output, status=status)


def test_openai_uses_the_responses_api_with_history_as_items(fake_openai):
    call = types.SimpleNamespace(type="function_call", call_id="c2", name="list_categories", arguments='{"a": 1}')
    fake_openai["answers"].append(_resp([types.SimpleNamespace(type="reasoning"), call]))
    history = [
        {"role": "user", "content": "q"},
        {"role": "assistant", "content": "looking", "tool_calls": [
            {"id": "c1", "type": "function", "function": {"name": "list_categories", "arguments": "{}"}}]},
        {"role": "tool", "tool_use_id": "c1", "content": "[]"},
    ]
    r = complete_with_tools(history, TOOLS, provider="openai", model="gpt-6.1-sol", system="S", api_key="k")
    assert (r.stop_reason, r.tool_calls) == ("tool_use", [{"id": "c2", "name": "list_categories", "input": {"a": 1}}])
    sent = fake_openai["responses"][0]
    assert fake_openai["chat"] == [] and sent["instructions"] == "S" and sent["store"] is False
    assert sent["input"] == [
        {"role": "user", "content": "q"},
        {"role": "assistant", "content": "looking"},
        {"type": "function_call", "call_id": "c1", "name": "list_categories", "arguments": "{}"},
        {"type": "function_call_output", "call_id": "c1", "output": "[]"},
    ]
    assert sent["tools"][0] == {"type": "function", "name": "list_categories", "description": "d",
                                "parameters": {"type": "object", "properties": {}}}
    assert sent["max_output_tokens"] >= lc.RESPONSES_MIN_OUTPUT_TOKENS


def test_openai_text_answer_and_incomplete_turn(fake_openai):
    text = types.SimpleNamespace(type="message", content=[types.SimpleNamespace(type="output_text", text="Răspuns")])
    fake_openai["answers"] += [_resp([text]), _resp([], status="incomplete")]
    r = complete_with_tools([{"role": "user", "content": "q"}], TOOLS, provider="openai", model="m", api_key="k")
    assert (r.stop_reason, r.text, r.tool_calls) == ("end_turn", "Răspuns", [])
    r = complete_with_tools([{"role": "user", "content": "q"}], TOOLS, provider="openai", model="m", api_key="k")
    assert (r.stop_reason, r.text) == ("max_tokens", None)


# --- Ollama: local, keyless, off unless configured --------------------------

@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(config, "ASK_ENABLED", False)
    monkeypatch.setattr(config, "ASK_BYOK_ENABLED", True)
    return make_client()


def test_ollama_is_absent_unless_the_server_configures_it(client, monkeypatch):
    calls = install(monkeypatch, lambda n, m, kw: text_resp())
    monkeypatch.setattr(config, "OLLAMA_BASE_URL", "")
    assert "ollama" not in client.get("/api/ask/config").json()["byok_models"]
    assert client.post("/api/ask", json={"question": "x", "provider": "ollama"}).status_code == 400
    with pytest.raises(LLMError):
        complete_with_tools([], [], provider="ollama", model="qwen3:8b")
    assert calls == []


def test_configured_ollama_needs_no_key_but_the_own_key_switch(client, monkeypatch, fake_openai):
    calls = install(monkeypatch, lambda n, m, kw: text_resp())
    monkeypatch.setattr(config, "OLLAMA_BASE_URL", "http://localhost:11434/v1")
    assert client.get("/api/ask/config").json()["byok_models"]["ollama"][0] == "qwen3:8b"
    r = client.post("/api/ask", json={"question": "x", "provider": "ollama"})
    assert r.status_code == 200 and (calls[0]["provider"], calls[0]["api_key"]) == ("ollama", None)
    complete_with_tools([{"role": "user", "content": "x"}], TOOLS, provider="ollama", model="qwen3:8b")
    assert fake_openai["clients"][0]["base_url"] == "http://localhost:11434/v1"
    monkeypatch.setattr(config, "ASK_BYOK_ENABLED", False)
    assert client.post("/api/ask", json={"question": "x", "provider": "ollama"}).status_code == 404


def test_every_listed_provider_is_known_and_has_models():
    listed = json.loads(config.ASK_MODELS_FILE.read_text())
    assert set(listed) == set(lc.PROVIDERS)
    assert all(listed[p] for p in listed)
    assert set(ask_guard.byok_allowlist()) <= set(lc.PROVIDERS)


def test_byok_call_reaches_a_new_provider(client, monkeypatch):
    calls = install(monkeypatch, lambda n, m, kw: text_resp())
    r = client.post("/api/ask", json={"question": "x", "provider": "deepseek", "api_key": FAKE_KEY})
    assert r.status_code == 200 and (calls[0]["provider"], calls[0]["model"]) == ("deepseek", "deepseek-v4-pro")
