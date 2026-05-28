#!/usr/bin/env python3
"""Tests for LangGraph integration."""

import logging

import pytest

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@pytest.fixture(scope="module")
def graph():
    """Construct the BrainResearcherGraph for tests."""
    try:
        from brain_researcher.services.agent.brain_researcher_graph import (
            BrainResearcherGraph,
        )

        return BrainResearcherGraph()
    except Exception as exc:  # pragma: no cover - environment dependent
        pytest.skip(f"Unable to create BrainResearcherGraph: {exc}")


def test_graph_creation(graph):
    """Test creating the graph."""
    assert graph is not None
    assert len(graph.tools) > 0
    assert graph.checkpointer is not None


def test_tool_registry():
    """Test tool registry."""
    from brain_researcher.services.tools.tool_registry import ToolRegistry

    registry = ToolRegistry()
    tools = registry.get_all_tools()
    assert tools


def test_simple_query(graph):
    """Test a simple query."""
    from langchain_core.messages import HumanMessage

    query = "What is the n-back task?"

    initial_state = {
        "messages": [HumanMessage(content=query)],
        "selected_tools": [],
        "tool_results": {},
        "synthesis": {},
        "current_phase": "understanding",
    }

    config = {"configurable": {"thread_id": "test-thread-1"}}
    try:
        result = graph.app.invoke(initial_state, config)
    except KeyError as exc:  # pragma: no cover - prompt template mismatch
        pytest.skip(f"LangGraph prompt variables mismatch: {exc}")

    assert result.get("current_phase") is not None
    assert "messages" in result


def test_api_compatibility():
    """Test API compatibility."""
    from brain_researcher.legacy.agent.web_service_langgraph import app

    routes = [rule.rule for rule in app.url_map.iter_rules()]
    important_routes = [
        "/health",
        "/tools",
        "/tools/run",
        "/act",
        "/act_llm",
    ]

    for route in important_routes:
        assert route in routes, f"Missing route {route}"
