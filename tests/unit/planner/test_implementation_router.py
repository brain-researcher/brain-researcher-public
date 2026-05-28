"""Tests for implementation_router KG retriever integration."""

from dataclasses import dataclass

from brain_researcher.services.agent.planner.implementation_router import (
    EnvContext,
    choose_tool_for_operation_debug,
)
from brain_researcher.services.agent.planner.intents import Intent, Operation


@dataclass(frozen=True)
class DummyTool:
    id: str
    name: str
    description: str
    runtime_kind: str
    package: str = ""
    entrypoint: str = ""
    capabilities: tuple = ()


@dataclass(frozen=True)
class DummyMatch:
    id: str
    score: float


class DummyRetriever:
    def retrieve_tools(self, query: str, family_ids=None, top_k: int = 10, filters=None):
        return [DummyMatch(id="tool.keep", score=0.9)]


def test_kg_retriever_boosts_selection(monkeypatch):
    tool_drop = DummyTool(
        id="tool.drop",
        name="Drop Tool",
        description="drop",
        runtime_kind="python",
    )
    tool_keep = DummyTool(
        id="tool.keep",
        name="Keep Tool",
        description="keep",
        runtime_kind="python",
    )

    monkeypatch.setattr(
        "brain_researcher.services.agent.planner.implementation_router.search_by_intent",
        lambda _: [tool_drop, tool_keep],
    )

    intent = Intent(id="test_intent", name="Test Intent", description="Test Desc")
    op = Operation(op_id=intent.id, intent=intent)

    env = EnvContext(
        preferences={"use_kg_retriever": True, "kg_retriever_weight": 0.2},
        tool_retriever=DummyRetriever(),
    )

    best, debug_rows = choose_tool_for_operation_debug(op, env)
    assert best is not None
    assert best.id == "tool.keep"
    assert any("kg_retriever" in ",".join(row[2]) for row in debug_rows)
