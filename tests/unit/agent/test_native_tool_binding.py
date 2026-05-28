from __future__ import annotations

from types import SimpleNamespace

from langchain_core.messages import AIMessage
from langchain_core.tools import StructuredTool
from pydantic import BaseModel

from brain_researcher.services.agent.agents.neuro_agent_llm import NeuroAgentLLM


class _Args(BaseModel):
    query: str


class _FakeOpenAILLM:
    __module__ = "langchain_openai.chat_models.base"

    def __init__(self):
        self.calls: list[tuple[list[StructuredTool], dict]] = []

    def bind_tools(self, tools, **kwargs):
        self.calls.append((list(tools), dict(kwargs)))
        return SimpleNamespace(invoke=lambda *_args, **_kwargs: AIMessage(content="ok"))


class _FakeGeminiLLM:
    __module__ = "langchain_google_genai.chat_models"

    def __init__(self):
        self.calls: list[tuple[list[StructuredTool], dict]] = []

    def bind_tools(self, tools, **kwargs):
        self.calls.append((list(tools), dict(kwargs)))
        return SimpleNamespace(invoke=lambda *_args, **_kwargs: AIMessage(content="ok"))


def _make_agent(fake_llm) -> NeuroAgentLLM:
    agent = NeuroAgentLLM.__new__(NeuroAgentLLM)
    agent.llm = fake_llm
    agent.llm_with_tools = None
    agent._runtime_to_bound_tool_name = {}
    agent._bound_to_runtime_tool_name = {}
    return agent


def _make_tool(name: str) -> StructuredTool:
    return StructuredTool(
        name=name,
        description=f"tool:{name}",
        func=lambda **kwargs: kwargs,
        args_schema=_Args,
    )


def test_openai_binding_sanitizes_dotted_tool_names_and_restores_runtime_names():
    agent = _make_agent(_FakeOpenAILLM())
    tool = _make_tool("mcp.server_info")

    agent._bind_tools_to_llm([tool], tool_choice="required")

    bound_tools, bind_kwargs = agent.llm.calls[-1]
    assert bind_kwargs["tool_choice"] == "required"
    assert bound_tools[0].name != "mcp.server_info"
    assert agent._runtime_to_bound_tool_name["mcp.server_info"] == bound_tools[0].name

    message = AIMessage(
        content="",
        tool_calls=[{"id": "call_1", "name": bound_tools[0].name, "args": {}}],
        additional_kwargs={
            "tool_calls": [
                {
                    "id": "call_1",
                    "type": "function",
                    "function": {"name": bound_tools[0].name, "arguments": "{}"},
                }
            ]
        },
    )

    restored = agent._restore_tool_call_names(message)

    assert restored.tool_calls[0]["name"] == "mcp.server_info"
    assert (
        restored.additional_kwargs["tool_calls"][0]["function"]["name"]
        == "mcp.server_info"
    )


def test_gemini_binding_normalizes_required_tool_choice():
    agent = _make_agent(_FakeGeminiLLM())
    tool = _make_tool("kg_search_nodes")

    agent._bind_tools_to_llm([tool], tool_choice="required")

    bound_tools, bind_kwargs = agent.llm.calls[-1]
    assert bound_tools[0].name == "kg_search_nodes"
    assert bind_kwargs["tool_choice"] is True
