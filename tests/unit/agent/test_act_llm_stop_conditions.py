from __future__ import annotations

from langchain_core.messages import AIMessage
from langchain_core.tools import StructuredTool
from pydantic import BaseModel

from brain_researcher.services.agent.agents.neuro_agent_llm import NeuroAgentLLM


class _ListArgs(BaseModel):
    values: list[str]


class _NoArgs(BaseModel):
    pass


class _LoopingLLM:
    __module__ = "langchain_openai.chat_models.base"

    def __init__(self, *, tool_name: str, tool_args: dict):
        self.tool_name = tool_name
        self.tool_args = tool_args
        self.invoke_count = 0
        self.bound_tools = []
        self.bound_kwargs = {}

    def bind_tools(self, tools, **kwargs):
        self.bound_tools = list(tools)
        self.bound_kwargs = dict(kwargs)
        return self

    def invoke(self, messages, config=None):
        self.invoke_count += 1
        return AIMessage(
            content="",
            tool_calls=[
                {
                    "id": f"call_{self.invoke_count}",
                    "name": self.tool_name,
                    "args": dict(self.tool_args),
                }
            ],
        )


def _make_agent(fake_llm: _LoopingLLM, tool: StructuredTool) -> NeuroAgentLLM:
    agent = NeuroAgentLLM.__new__(NeuroAgentLLM)
    agent.llm = fake_llm
    agent.system_prompt = "test"
    agent.tools = [tool]
    agent.tool_choice = "required"
    agent.tool_retriever = None
    agent.retriever_top_k = 100
    agent.retriever_max_families = 5
    agent.max_bound_tools = 100
    agent.timeout_seconds = 5
    agent._runtime_to_bound_tool_name = {}
    agent._bound_to_runtime_tool_name = {}
    agent._bind_tools_to_llm(agent.tools, tool_choice="required")
    agent.graph = agent._build_graph()
    return agent


def test_run_halts_after_repeated_validation_failures():
    tool = StructuredTool(
        name="tool_search",
        description="test tool",
        func=lambda values: {"values": values},
        args_schema=_ListArgs,
    )
    fake_llm = _LoopingLLM(tool_name="tool_search", tool_args={"values": ""})
    agent = _make_agent(fake_llm, tool)

    final_state = agent.run("test query")
    final_message = agent.get_last_ai_message(final_state)

    assert fake_llm.invoke_count == 2
    assert "validation errors" in final_message


def test_run_halts_after_repeated_identical_error_results():
    tool = StructuredTool(
        name="dataset_lookup",
        description="test tool",
        func=lambda: {
            "status": "error",
            "error": "dataset catalog missing",
            "metadata": {"error_category": "data"},
        },
        args_schema=_NoArgs,
    )
    fake_llm = _LoopingLLM(tool_name="dataset_lookup", tool_args={})
    agent = _make_agent(fake_llm, tool)

    final_state = agent.run("test query")
    final_message = agent.get_last_ai_message(final_state)

    assert fake_llm.invoke_count == 2
    assert "failed 2 times with the same arguments" in final_message


def test_get_last_ai_message_accepts_empty_tool_call_lists():
    agent = NeuroAgentLLM.__new__(NeuroAgentLLM)
    state = {"messages": [AIMessage(content="final answer", tool_calls=[])]}
    assert agent.get_last_ai_message(state) == "final answer"


def test_record_tool_failure_halts_after_total_failure_cap(monkeypatch):
    monkeypatch.setenv("BR_ACT_LLM_MAX_TOTAL_TOOL_FAILURES", "3")
    agent = NeuroAgentLLM.__new__(NeuroAgentLLM)

    context = {}
    for idx, tool_name in enumerate(["tool_one", "tool_two", "tool_three"], start=1):
        context, should_halt, halt_reason = agent._record_tool_failure(
            context,
            {"name": tool_name, "args": {"attempt": idx}},
            error_message="boom",
        )

    assert should_halt is True
    assert "failed 3 times in this run" in halt_reason
