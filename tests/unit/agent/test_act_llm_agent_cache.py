import importlib
from types import SimpleNamespace

import pytest
from langchain_core.messages import AIMessage

from brain_researcher.services.agent import agent_factory


@pytest.fixture(autouse=True)
def _reset_agent_factory_cache():
    agent_factory.reset_llm_agent_cache()
    yield
    agent_factory.reset_llm_agent_cache()


def _reload_web_service():
    module = importlib.import_module("brain_researcher.services.agent.web_service")
    importlib.reload(module)
    return module


def test_get_llm_agent_caches_custom_registry_by_surface_key(monkeypatch):
    monkeypatch.setenv("BR_USE_TOOL_RETRIEVER", "true")

    retriever_inits = []
    agent_inits = []

    class FakeRetriever:
        def __init__(self):
            retriever_inits.append("init")

    class FakeAgent:
        def __init__(
            self,
            llm_model,
            tool_choice,
            tool_retriever=None,
            tool_registry=None,
        ):
            agent_inits.append(
                {
                    "model": llm_model,
                    "tool_choice": tool_choice,
                    "tool_retriever": tool_retriever,
                    "tool_registry": tool_registry,
                }
            )
            self.tools = []
            self.llm = SimpleNamespace(bind_tools=lambda *args, **kwargs: None)

    monkeypatch.setattr(agent_factory, "ToolRetriever", FakeRetriever)
    neuro_agent_llm = importlib.import_module(
        "brain_researcher.services.agent.agents.neuro_agent_llm"
    )
    monkeypatch.setattr(neuro_agent_llm, "NeuroAgentLLM", FakeAgent)

    registry = object()
    agent_a = agent_factory.get_llm_agent(
        tool_mode="required",
        tool_registry=registry,
        tool_registry_cache_key="surface:2:abc",
    )
    agent_b = agent_factory.get_llm_agent(
        tool_mode="required",
        tool_registry=registry,
        tool_registry_cache_key="surface:2:abc",
    )
    agent_c = agent_factory.get_llm_agent(
        tool_mode="required",
        coding_bias=True,
        tool_registry=registry,
        tool_registry_cache_key="surface:2:abc",
    )

    assert agent_a is agent_b
    assert agent_c is not agent_a
    assert len(agent_inits) == 2
    assert len(retriever_inits) == 2


def test_get_llm_agent_auto_caches_filtered_registry_surface(monkeypatch):
    monkeypatch.setenv("BR_USE_TOOL_RETRIEVER", "true")

    retriever_inits = []
    agent_inits = []

    class FakeRetriever:
        def __init__(self):
            retriever_inits.append("init")

    class FakeAgent:
        def __init__(
            self,
            llm_model,
            tool_choice,
            tool_retriever=None,
            tool_registry=None,
        ):
            agent_inits.append(
                {
                    "model": llm_model,
                    "tool_choice": tool_choice,
                    "tool_retriever": tool_retriever,
                    "tool_registry": tool_registry,
                }
            )
            self.tools = []
            self.llm = SimpleNamespace(bind_tools=lambda *args, **kwargs: None)

    class FakeRegistry:
        def __init__(self):
            self.tools = {"kg_search_nodes": object(), "datasets.describe_resources": object()}

    monkeypatch.setattr(agent_factory, "ToolRetriever", FakeRetriever)
    neuro_agent_llm = importlib.import_module(
        "brain_researcher.services.agent.agents.neuro_agent_llm"
    )
    monkeypatch.setattr(neuro_agent_llm, "NeuroAgentLLM", FakeAgent)

    registry = FakeRegistry()
    agent_a = agent_factory.get_llm_agent(
        tool_mode="required",
        tool_registry=registry,
    )
    agent_b = agent_factory.get_llm_agent(
        tool_mode="required",
        tool_registry=registry,
    )

    assert agent_a is agent_b
    assert len(agent_inits) == 1
    assert len(retriever_inits) == 1


def test_get_cached_act_llm_agent_reuses_filtered_registry_snapshot(monkeypatch):
    web_service = _reload_web_service()

    class FakeTool:
        def __init__(self, name):
            self.name = name

        def get_tool_description(self):
            return f"description:{self.name}"

    class FakeRegistry:
        def __init__(self):
            self.use_capabilities = False
            self.light_mode = True
            self.source_backend = "adapter"
            self.tools = {
                "tool.query": FakeTool("tool.query"),
                "tool.safe": FakeTool("tool.safe"),
                "tool.exec": FakeTool("tool.exec"),
            }
            self.tool_descriptions = {
                name: tool.get_tool_description() for name, tool in self.tools.items()
            }

        def get_tool(self, name):
            return self.tools.get(name)

    base_registry = FakeRegistry()
    calls = []

    monkeypatch.setattr(
        web_service,
        "get_agent",
        lambda: SimpleNamespace(tool_registry=base_registry),
    )
    monkeypatch.setattr(
        web_service,
        "_effective_tool_allowset",
        lambda: {"tool.query", "tool.safe"},
    )

    def fake_get_llm_agent(**kwargs):
        calls.append(kwargs)
        return f"agent:{len(calls)}"

    monkeypatch.setattr(web_service, "get_llm_agent", fake_get_llm_agent)
    web_service.reset_act_llm_cache()

    first = web_service._get_cached_act_llm_agent(
        tool_mode="required",
        coding_bias=False,
    )
    second = web_service._get_cached_act_llm_agent(
        tool_mode="required",
        coding_bias=False,
    )

    assert first == "agent:1"
    assert second == "agent:2"
    assert calls[0]["tool_registry"] is calls[1]["tool_registry"]
    assert calls[0]["tool_registry_cache_key"] == calls[1]["tool_registry_cache_key"]
    assert sorted(calls[0]["tool_registry"].tools.keys()) == [
        "tool.query",
        "tool.safe",
    ]
    assert sorted(base_registry.tools.keys()) == ["tool.exec", "tool.query", "tool.safe"]


def test_get_cached_act_llm_agent_changes_cache_key_when_surface_changes(monkeypatch):
    web_service = _reload_web_service()

    class FakeTool:
        def __init__(self, name):
            self.name = name

        def get_tool_description(self):
            return self.name

    class FakeRegistry:
        def __init__(self):
            self.use_capabilities = False
            self.light_mode = True
            self.source_backend = "adapter"
            self.tools = {
                "tool.query": FakeTool("tool.query"),
                "tool.safe": FakeTool("tool.safe"),
            }
            self.tool_descriptions = {
                name: tool.get_tool_description() for name, tool in self.tools.items()
            }

        def get_tool(self, name):
            return self.tools.get(name)

    allowed_tools = {"tool.query", "tool.safe"}
    calls = []

    monkeypatch.setattr(
        web_service,
        "get_agent",
        lambda: SimpleNamespace(tool_registry=FakeRegistry()),
    )
    monkeypatch.setattr(
        web_service,
        "_effective_tool_allowset",
        lambda: set(allowed_tools),
    )

    def fake_get_llm_agent(**kwargs):
        calls.append(kwargs)
        return kwargs["tool_registry_cache_key"]

    monkeypatch.setattr(web_service, "get_llm_agent", fake_get_llm_agent)
    web_service.reset_act_llm_cache()

    first_key = web_service._get_cached_act_llm_agent(
        tool_mode="required",
        coding_bias=False,
    )
    allowed_tools.remove("tool.query")
    second_key = web_service._get_cached_act_llm_agent(
        tool_mode="required",
        coding_bias=False,
    )

    assert first_key != second_key
    assert sorted(calls[0]["tool_registry"].tools.keys()) == ["tool.query", "tool.safe"]
    assert sorted(calls[1]["tool_registry"].tools.keys()) == ["tool.safe"]


def test_act_llm_route_reuses_agent_factory_cache_for_stable_surface(monkeypatch):
    web_service = _reload_web_service()
    web_service.reset_act_llm_cache()

    class FakeTool:
        def __init__(self, name):
            self.name = name

        def get_tool_description(self):
            return self.name

    class FakeRegistry:
        def __init__(self):
            self.use_capabilities = False
            self.light_mode = True
            self.source_backend = "adapter"
            self.tools = {
                "tool.query": FakeTool("tool.query"),
                "tool.safe": FakeTool("tool.safe"),
            }
            self.tool_descriptions = {
                name: tool.get_tool_description() for name, tool in self.tools.items()
            }

        def get_tool(self, name):
            return self.tools.get(name)

    class FakeActAgent:
        def __init__(self):
            self.llm = SimpleNamespace(model="models/gemini-2.5-pro")

        def _llm_provider_family(self):
            return "gemini"

        def run(self, query, complexity=None, context=None):
            del query, complexity, context
            return {"messages": [AIMessage(content="ok", tool_calls=[])]}

        def get_last_ai_message(self, state):
            del state
            return "ok"

    build_calls = []

    def fake_build_llm_agent(*, model, tool_mode, coding_bias, tool_registry=None):
        build_calls.append(
            {
                "model": model,
                "tool_mode": tool_mode,
                "coding_bias": coding_bias,
                "tool_registry": tool_registry,
            }
        )
        return FakeActAgent()

    monkeypatch.setattr(
        web_service,
        "get_agent",
        lambda: SimpleNamespace(tool_registry=FakeRegistry()),
    )
    monkeypatch.setattr(
        web_service,
        "_effective_tool_allowset",
        lambda: {"tool.query", "tool.safe"},
    )
    monkeypatch.setattr(agent_factory, "_build_llm_agent", fake_build_llm_agent)
    monkeypatch.setenv("BR_USE_TOOL_RETRIEVER", "false")

    client = web_service.app.test_client()
    first = client.post("/act_llm", json={"query": "hello", "tool_mode": "auto"})
    second = client.post("/act_llm", json={"query": "hello", "tool_mode": "auto"})

    assert first.status_code == 200
    assert second.status_code == 200
    assert len(build_calls) == 1
