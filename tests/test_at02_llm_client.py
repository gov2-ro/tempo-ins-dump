"""AT-02: provider completion states, usage and call controls, offline.

Each backend's own terminal word (`length`, `max_tokens`, an incomplete Responses turn, an
empty `stop`) must reach the agent as one normalized `finish`; usage a provider omits stays
null; the final answer's `tool_choice="none"` and the SDK retry count reach the SDK.
"""
import sys
import types

import pytest

from app import config
from app.services import llm_client as lc
from app.services.llm_client import LLMError, complete_with_tools

TOOLS = [{"name": "t", "description": "d", "input_schema": {"type": "object", "properties": {}}}]
MSGS = [{"role": "user", "content": "q"}]
NS = types.SimpleNamespace


# ---------------------------------------------------------------- fakes

@pytest.fixture
def fake_anthropic(monkeypatch):
    seen = {"clients": [], "calls": [], "answers": []}

    class Anthropic:
        def __init__(self, **kw):
            seen["clients"].append(kw)
            self.messages = NS(create=self._create)

        def _create(self, **kw):
            seen["calls"].append(kw)
            return seen["answers"].pop(0)

    monkeypatch.setitem(sys.modules, "anthropic", NS(Anthropic=Anthropic))
    return seen


def ant(stop, blocks, usage=None):
    return NS(stop_reason=stop, content=blocks, usage=usage)


def txt(t):
    return NS(type="text", text=t)


def use(i, name="t", inp=None):
    return NS(type="tool_use", id=i, name=name, input={} if inp is None else inp)


@pytest.fixture
def fake_openai(monkeypatch):
    seen = {"clients": [], "chat": [], "responses": [], "chat_answers": [], "resp_answers": []}

    class OpenAI:
        def __init__(self, **kw):
            seen["clients"].append(kw)
            self.chat = NS(completions=NS(create=lambda **k: (seen["chat"].append(k),
                                                              seen["chat_answers"].pop(0))[1]))
            self.responses = NS(create=lambda **k: (seen["responses"].append(k),
                                                    seen["resp_answers"].pop(0))[1])

    monkeypatch.setitem(sys.modules, "openai", NS(OpenAI=OpenAI))
    for env in ("OPENAI_API_KEY", "DEEPSEEK_API_KEY", "MISTRAL_API_KEY"):
        monkeypatch.delenv(env, raising=False)
    return seen


def chat(finish, content=None, calls=None, usage=None):
    msg = NS(content=content, tool_calls=calls)
    return NS(choices=[NS(message=msg, finish_reason=finish)], usage=usage)


def fn(i, name, args):
    return NS(id=i, function=NS(name=name, arguments=args))


# ---------------------------------------------------------------- Anthropic

@pytest.mark.parametrize("stop,blocks,finish,text", [
    ("end_turn", [txt("gata")], "complete", "gata"),
    ("tool_use", [use("a")], "tool_use", None),
    ("max_tokens", [], "output_limit", None),                 # the logged empty answer
    ("max_tokens", [txt("part")], "output_limit", "part"),
    ("refusal", [], "content_filter", None),
    ("pause_turn", [txt("x")], "incomplete", "x"),
    ("something_new", [txt("x")], "other", "x"),
])
def test_anthropic_terminal_states(fake_anthropic, stop, blocks, finish, text):
    fake_anthropic["answers"].append(ant(stop, blocks))
    r = complete_with_tools(MSGS, TOOLS, provider="anthropic", model="m", api_key="k")
    assert (r.finish, r.text) == (finish, text)
    assert r.stop_reason == stop                                # the legacy word is kept


def test_anthropic_usage_and_missing_usage(fake_anthropic):
    u = NS(input_tokens=1200, output_tokens=80, cache_read_input_tokens=1000)
    fake_anthropic["answers"] += [ant("end_turn", [txt("a")], u), ant("end_turn", [txt("b")])]
    r = complete_with_tools(MSGS, TOOLS, provider="anthropic", model="m", api_key="k")
    assert r.usage == {"input_tokens": 1200, "output_tokens": 80, "reasoning_tokens": None,
                       "cached_tokens": 1000}
    assert complete_with_tools(MSGS, TOOLS, provider="anthropic", model="m", api_key="k").usage is None


def test_anthropic_forbids_tools_only_when_asked_and_owns_no_hidden_retries(fake_anthropic):
    fake_anthropic["answers"] += [ant("end_turn", [txt("a")]), ant("end_turn", [txt("b")])]
    complete_with_tools(MSGS, TOOLS, provider="anthropic", model="m", api_key="k", max_retries=0)
    complete_with_tools(MSGS, TOOLS, provider="anthropic", model="m", api_key="k",
                        tool_choice="none", max_retries=0)
    assert [c["tool_choice"] for c in fake_anthropic["calls"]] == [{"type": "auto"}, {"type": "none"}]
    assert all(c["max_retries"] == 0 for c in fake_anthropic["clients"])
    assert fake_anthropic["calls"][0]["tools"][0]["name"] == "t"   # tools stay: history may hold tool_use


def test_the_sdk_retry_default_is_the_configured_one_when_the_caller_does_not_say(fake_anthropic, monkeypatch):
    monkeypatch.setattr(config, "ASK_PROVIDER_MAX_RETRIES", 2)
    fake_anthropic["answers"].append(ant("end_turn", [txt("a")]))
    complete_with_tools(MSGS, TOOLS, provider="anthropic", model="m", api_key="k")
    assert fake_anthropic["clients"][0]["max_retries"] == 2


# ---------------------------------------------------------------- chat completions

@pytest.mark.parametrize("finish_reason,content,calls,finish", [
    ("stop", "gata", None, "complete"),
    ("length", None, None, "output_limit"),                   # reasoning spent the allowance
    ("length", "part", None, "output_limit"),
    ("content_filter", None, None, "content_filter"),
    ("tool_calls", None, [fn("c1", "t", "{}")], "tool_use"),
    ("stop", None, [fn("c1", "t", "{}")], "tool_use"),        # some providers say stop with calls
    ("weird", "x", None, "other"),
])
def test_chat_terminal_states(fake_openai, finish_reason, content, calls, finish):
    fake_openai["chat_answers"].append(chat(finish_reason, content, calls))
    r = complete_with_tools(MSGS, TOOLS, provider="deepseek", model="m", api_key="k")
    assert r.finish == finish and r.text == content


def test_chat_usage_with_reasoning_and_cache(fake_openai):
    u = NS(prompt_tokens=900, completion_tokens=2048,
           completion_tokens_details=NS(reasoning_tokens=2048),
           prompt_tokens_details=NS(cached_tokens=512))
    fake_openai["chat_answers"] += [chat("length", None, None, u), chat("stop", "a")]
    r = complete_with_tools(MSGS, TOOLS, provider="deepseek", model="m", api_key="k")
    assert r.usage == {"input_tokens": 900, "output_tokens": 2048, "reasoning_tokens": 2048,
                       "cached_tokens": 512}
    assert complete_with_tools(MSGS, TOOLS, provider="deepseek", model="m", api_key="k").usage is None


def test_a_truncated_tool_call_is_flagged_not_raised(fake_openai):
    calls = [fn("c1", "t", '{"query": "popul'), fn("c2", "t", '{"query": "ok"}')]
    fake_openai["chat_answers"].append(chat("length", None, calls))
    r = complete_with_tools(MSGS, TOOLS, provider="deepseek", model="m", api_key="k")
    assert r.finish == "output_limit"
    assert r.tool_calls[0] == {"id": "c1", "name": "t", "input": {}, "invalid": True}
    assert r.tool_calls[1] == {"id": "c2", "name": "t", "input": {"query": "ok"}}


def test_chat_tool_choice_none_and_retries(fake_openai):
    fake_openai["chat_answers"] += [chat("stop", "a"), chat("stop", "b")]
    complete_with_tools(MSGS, TOOLS, provider="mistral", model="m", api_key="k", max_retries=0)
    complete_with_tools(MSGS, TOOLS, provider="mistral", model="m", api_key="k",
                        tool_choice="none", max_retries=0)
    assert [c["tool_choice"] for c in fake_openai["chat"]] == ["auto", "none"]
    assert all(c["max_retries"] == 0 for c in fake_openai["clients"])


# ---------------------------------------------------------------- OpenAI Responses

def resp(output, status="completed", reason=None, usage=None):
    return NS(output=output, status=status, usage=usage,
              incomplete_details=NS(reason=reason) if reason else None)


def call(i, args):
    return NS(type="function_call", call_id=i, name="t", arguments=args)


def test_responses_terminal_states(fake_openai):
    msg = NS(type="message", content=[NS(type="output_text", text="Răspuns")])
    fake_openai["resp_answers"] += [
        resp([msg]),
        resp([call("c1", "{}")]),
        resp([], "incomplete", "max_output_tokens"),
        resp([], "incomplete", "content_filter"),
        resp([], "incomplete", "other"),
    ]
    got = [complete_with_tools(MSGS, TOOLS, provider="openai", model="m", api_key="k")
           for _ in range(5)]
    assert [g.finish for g in got] == ["complete", "tool_use", "output_limit", "content_filter",
                                       "incomplete"]
    assert got[0].text == "Răspuns" and got[2].stop_reason == "max_tokens"


def test_responses_failed_turn_is_a_stable_provider_error(fake_openai):
    fake_openai["resp_answers"].append(resp([], "failed"))
    with pytest.raises(LLMError) as e:
        complete_with_tools(MSGS, TOOLS, provider="openai", model="m", api_key="k")
    assert e.value.code == "provider_error"


def test_responses_usage_and_controls(fake_openai):
    u = NS(input_tokens=700, output_tokens=8000, output_tokens_details=NS(reasoning_tokens=7900),
           input_tokens_details=NS(cached_tokens=0))
    fake_openai["resp_answers"] += [resp([], "incomplete", "max_output_tokens", u), resp([])]
    r = complete_with_tools(MSGS, TOOLS, provider="openai", model="m", api_key="k",
                            tool_choice="none", max_retries=0)
    assert r.usage == {"input_tokens": 700, "output_tokens": 8000, "reasoning_tokens": 7900,
                       "cached_tokens": 0}
    sent = fake_openai["responses"][0]
    assert sent["tool_choice"] == "none" and fake_openai["clients"][0]["max_retries"] == 0
    assert r.requested_tokens == sent["max_output_tokens"] == lc.RESPONSES_MIN_OUTPUT_TOKENS


# ---------------------------------------------------------------- output allowances

def test_allowances_are_configured_per_provider_and_model(monkeypatch):
    monkeypatch.setattr(config, "ASK_OUTPUT_TOKENS", 2048)
    monkeypatch.setattr(config, "ASK_REASONING_OUTPUT_TOKENS", 8000)
    monkeypatch.setattr(config, "ASK_REASONING_MODELS", ["deepseek:*", "xai:grok-4.7"])
    assert lc.output_allowance("anthropic", "claude-sonnet-5-5") == 2048
    assert lc.output_allowance("deepseek", "deepseek-v4-pro") == 8000
    assert lc.output_allowance("xai", "grok-4.7") == 8000 and lc.output_allowance("xai", "grok-4.3") == 2048


def test_the_charged_allowance_is_what_is_requested(fake_openai, fake_anthropic, monkeypatch):
    monkeypatch.setattr(config, "ASK_OUTPUT_TOKENS", 1500)
    monkeypatch.setattr(config, "ASK_REASONING_MODELS", [])
    assert lc.requested_output_tokens("anthropic", "m") == 1500
    assert lc.requested_output_tokens("anthropic", "m", 700) == 700
    assert lc.requested_output_tokens("openai", "m", 700) == lc.RESPONSES_MIN_OUTPUT_TOKENS   # floor
    fake_anthropic["answers"].append(ant("end_turn", [txt("a")]))
    r = complete_with_tools(MSGS, TOOLS, provider="anthropic", model="m", api_key="k")
    assert r.requested_tokens == 1500 == fake_anthropic["calls"][0]["max_tokens"]
