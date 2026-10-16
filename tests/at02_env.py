"""Shared fixtures for the AT-02 tests: a synthetic generation with the real tools behind it
and a scripted provider. Only the model is fake; every number comes from the shared services."""
from types import SimpleNamespace

from at01_fixtures import GENERATION, add_dataset, add_search_columns, make_env
from fix08_helpers import FAKE_KEY  # noqa: F401 — re-exported for the tests
from test_at01_changes import area_dim, build_countx, time_dim, unit_dim
from test_at01_recipes_links import RECIPES, build_core, install_recipes
from app.services import agent
from app.services.llm_client import LLMResponse

POPC_ROWS = [("Cluj", "2020", "Numar persoane", 1000.0), ("Cluj", "2021", "Numar persoane", 1010.0),
             ("Iași", "2020", "Numar persoane", 900.0), ("Iași", "2021", "Numar persoane", 880.0),
             ("Bihor", "2020", "Numar persoane", 600.0), ("Bihor", "2021", "Numar persoane", 610.0)]


def build_all(corpus, extra=()):
    """COUNTX (A-D), the recipe fixtures, POPC (named counties), any `extra(corpus)` datasets,
    then the search columns (datasets can no longer be added after those)."""
    build_countx(corpus)
    build_core(corpus)
    add_dataset(corpus, "POPC", [area_dim(["Cluj", "Iași", "Bihor"]), time_dim(("2020", "2021")),
                                 unit_dim("Numar persoane")], POPC_ROWS, name="Populatie pe judete")
    for fn in extra:
        fn(corpus)
    add_search_columns(corpus)


def full_env(tmp_path, monkeypatch, extra=()):
    e = make_env(tmp_path, monkeypatch, build=lambda corpus: build_all(corpus, extra))
    install_recipes(tmp_path, monkeypatch, *RECIPES)
    monkeypatch.setattr(agent, "RETRY_PAUSE_SECONDS", 0.0)
    return e


def call_resp(tool, args, i=0, text=None):
    return LLMResponse(stop_reason="tool_use", text=text, finish="tool_use",
                       tool_calls=[{"id": f"c{i}", "name": tool, "input": args}])


def scripted(monkeypatch, responses):
    """Provider replaced by a script (a list, or fn(n, messages, kw)). Returns the call log."""
    calls = []
    it = iter(responses) if not callable(responses) else None

    def fake(messages, tools, **kw):
        calls.append(SimpleNamespace(messages=[m for m in messages], kw=kw))
        return responses(len(calls), messages, kw) if it is None else next(it)

    monkeypatch.setattr(agent, "complete_with_tools", fake)
    return calls


def run(monkeypatch, responses, question="Care este populatia?", **kw):
    calls = scripted(monkeypatch, responses)
    kw.setdefault("provider", "anthropic")
    kw.setdefault("api_key", "k")
    return agent.run_agent(question, **kw), calls
