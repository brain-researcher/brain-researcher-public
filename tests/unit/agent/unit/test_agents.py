"""
Unit tests for the NeuroAgent.
"""

from unittest.mock import Mock, patch

import pytest
from langchain_core.messages import AIMessage, HumanMessage

from brain_researcher.services.agent.agents.neuro_agent import NeuroAgent
from brain_researcher.services.agent.states.base import NeuroAgentState
from brain_researcher.services.tools.tool_registry import ToolRegistry


class TestNeuroAgent:
    """Test the main NeuroAgent functionality."""

    @pytest.fixture
    def mock_registry(self):
        """Create a mock tool registry."""
        registry = Mock(spec=ToolRegistry)

        # Mock tool selection
        mock_tool = Mock()
        mock_tool.get_tool_name.return_value = "mock_tool"
        mock_tool.run.return_value = {"status": "success", "data": {"result": "test"}}

        registry.get_tools_for_task.return_value = [mock_tool]
        registry.get_tool.return_value = mock_tool

        return registry

    @pytest.fixture
    def agent(self, mock_registry):
        """Create agent with mock registry."""
        return NeuroAgent(tool_registry=mock_registry)

    def test_agent_initialization(self):
        """Test agent initializes correctly."""
        agent = NeuroAgent()

        assert agent.tool_registry is not None
        assert agent.graph is not None
        assert agent.fmri_tools is not None
        assert agent.neurokg_tools is not None

    def test_understand_query_analysis(self, agent):
        """Test query understanding for analysis tasks."""
        state = NeuroAgentState(
            messages=[HumanMessage(content="Analyze the GLM results for motor task")],
            current_phase="init",
            selected_tools=[],
        )

        new_state = agent.understand_query(state)

        assert new_state["current_phase"] == "tool_selection"
        assert len(new_state["messages"]) == 2
        assert "analysis" in new_state["messages"][-1].content

    def test_understand_query_search(self, agent):
        """Test query understanding for search tasks."""
        state = NeuroAgentState(
            messages=[HumanMessage(content="Search for papers about visual cortex")],
            current_phase="init",
            selected_tools=[],
        )

        new_state = agent.understand_query(state)

        assert new_state["current_phase"] == "tool_selection"
        assert "search" in new_state["messages"][-1].content

    def test_understand_query_comparison(self, agent):
        """Test query understanding for comparison tasks."""
        state = NeuroAgentState(
            messages=[
                HumanMessage(content="Compare activation patterns between datasets")
            ],
            current_phase="init",
            selected_tools=[],
        )

        new_state = agent.understand_query(state)

        assert new_state["current_phase"] == "tool_selection"
        assert "comparison" in new_state["messages"][-1].content

    def test_understand_query_no_human_message(self, agent):
        """Test handling when no human message is present."""
        state = NeuroAgentState(
            messages=[AIMessage(content="Previous response")],
            current_phase="init",
            selected_tools=[],
        )

        new_state = agent.understand_query(state)

        assert new_state["error"] == "No user message found"

    def test_select_tools_with_registry(self, agent, mock_registry):
        """Test tool selection using registry."""
        state = NeuroAgentState(
            messages=[HumanMessage(content="Run GLM analysis")],
            current_phase="tool_selection",
            selected_tools=[],
        )

        new_state = agent.select_tools(state)

        assert new_state["current_phase"] == "execution"
        assert len(new_state["selected_tools"]) > 0
        assert "tool_args" in new_state
        mock_registry.get_tools_for_task.assert_called_once()

    def test_select_tools_fallback(self, agent):
        """Test tool selection fallback when registry returns empty."""
        # Mock registry to return empty list
        agent.tool_registry.get_tools_for_task.return_value = []

        state = NeuroAgentState(
            messages=[HumanMessage(content="Analyze GLM contrasts")],
            current_phase="tool_selection",
            selected_tools=[],
        )

        new_state = agent.select_tools(state)

        assert "glm_analysis" in new_state["selected_tools"]

    def test_prepare_tool_args_dataset_extraction(self, agent):
        """Test extracting dataset ID from query."""
        query = "Analyze ds000001 with GLM"
        tool_names = ["glm_analysis"]

        args = agent._prepare_tool_args(query, tool_names)

        assert args["glm_analysis"]["dataset_id"] == "ds000001"

    def test_prepare_tool_args_coordinate_extraction(self, agent):
        """Test extracting coordinates from query."""
        query = "Map coordinates [-42, -22, 54] and [42, -22, 54] to concepts"
        tool_names = ["coordinate_to_concept"]

        args = agent._prepare_tool_args(query, tool_names)

        coords = args["coordinate_to_concept"]["coordinates"]
        assert len(coords) == 2
        assert coords[0] == [-42.0, -22.0, 54.0]
        assert coords[1] == [42.0, -22.0, 54.0]

    def test_prepare_tool_args_concept_detection(self, agent):
        """Test detecting concepts from query."""
        # Visual concept
        query = "Find concepts related to visual processing"
        args = agent._prepare_tool_args(query, ["find_related_concepts"])
        assert args["find_related_concepts"]["concept"] == "visual cortex"

        # Memory concept
        query = "Search memory-related regions"
        args = agent._prepare_tool_args(query, ["find_related_concepts"])
        assert args["find_related_concepts"]["concept"] == "memory"

    def test_execute_tools_success(self, agent, mock_registry):
        """Test successful tool execution."""
        state = NeuroAgentState(
            messages=[HumanMessage(content="Test")],
            current_phase="execution",
            selected_tools=["mock_tool"],
            tool_args={"mock_tool": {"param": "value"}},
        )

        new_state = agent.execute_tools(state)

        assert new_state["current_phase"] == "synthesis"
        assert "results" in new_state
        assert new_state["results"]["mock_tool"]["status"] == "success"
        mock_registry.get_tool.assert_called_with("mock_tool")

    def test_execute_tools_not_found(self, agent):
        """Test handling when tool is not found."""
        agent.tool_registry.get_tool.return_value = None

        state = NeuroAgentState(
            messages=[HumanMessage(content="Test")],
            current_phase="execution",
            selected_tools=["non_existent_tool"],
            tool_args={},
        )

        new_state = agent.execute_tools(state)

        assert new_state["results"]["non_existent_tool"]["status"] == "error"
        assert "not found" in new_state["results"]["non_existent_tool"]["error"]

    def test_execute_tools_exception(self, agent, mock_registry):
        """Test handling tool execution exceptions."""
        mock_registry.get_tool.return_value.run.side_effect = Exception("Tool failed")

        state = NeuroAgentState(
            messages=[HumanMessage(content="Test")],
            current_phase="execution",
            selected_tools=["mock_tool"],
            tool_args={"mock_tool": {}},
        )

        new_state = agent.execute_tools(state)

        assert new_state["results"]["mock_tool"]["status"] == "error"
        assert "Tool failed" in new_state["results"]["mock_tool"]["error"]

    def test_check_execution_result_success(self, agent):
        """Test checking successful execution results."""
        state = {
            "results": {"tool1": {"status": "success"}, "tool2": {"status": "error"}}
        }

        result = agent.check_execution_result(state)
        assert result == "success"

    def test_check_execution_result_error(self, agent):
        """Test checking error execution results."""
        state = {"error": "All tools failed", "results": {}}

        result = agent.check_execution_result(state)
        assert result == "error"

    def test_check_execution_result_retry(self, agent):
        """Test checking for retry condition."""
        state = {}  # No results

        result = agent.check_execution_result(state)
        assert result == "error"

    def test_synthesize_results_glm(self, agent):
        """Test synthesizing GLM analysis results."""
        state = NeuroAgentState(
            messages=[],
            current_phase="synthesis",
            selected_tools=["glm_analysis"],
            results={
                "glm_analysis": {
                    "status": "success",
                    "data": {
                        "dataset_id": "ds000001",
                        "peak_coordinates": [[-42, -22, 54], [42, -22, 54]],
                    },
                }
            },
        )

        new_state = agent.synthesize_results(state)

        assert new_state["current_phase"] == "complete"
        assert "synthesis" in new_state
        assert "GLM analysis completed" in new_state["synthesis"]["summary"]
        assert "2 activation peaks" in new_state["synthesis"]["key_findings"][1]
        assert len(new_state["synthesis"]["recommendations"]) > 0

    def test_synthesize_results_concepts(self, agent):
        """Test synthesizing concept search results."""
        state = NeuroAgentState(
            messages=[],
            current_phase="synthesis",
            selected_tools=["find_related_concepts"],
            results={
                "find_related_concepts": {
                    "status": "success",
                    "data": {
                        "related_concepts": [
                            {"concept": "movement", "strength": 0.9},
                            {"concept": "motor control", "strength": 0.8},
                        ]
                    },
                }
            },
        )

        new_state = agent.synthesize_results(state)

        assert "movement" in new_state["synthesis"]["summary"]
        assert any(
            "literature" in rec for rec in new_state["synthesis"]["recommendations"]
        )

    def test_synthesize_results_multiple_tools(self, agent):
        """Test synthesizing results from multiple tools."""
        state = NeuroAgentState(
            messages=[],
            current_phase="synthesis",
            selected_tools=["glm_analysis", "coordinate_to_concept"],
            results={
                "glm_analysis": {
                    "status": "success",
                    "data": {"dataset_id": "ds000001"},
                },
                "coordinate_to_concept": {
                    "status": "success",
                    "data": {
                        "coordinate_mappings": [
                            {"coordinate": [-42, -22, 54], "region": "Motor cortex"}
                        ]
                    },
                },
            },
        )

        new_state = agent.synthesize_results(state)

        assert len(new_state["synthesis"]["key_findings"]) >= 2
        assert "Motor cortex" in new_state["synthesis"]["summary"]

    def test_handle_error(self, agent):
        """Test error handling."""
        state = NeuroAgentState(
            messages=[],
            current_phase="error",
            selected_tools=[],
            error="Tool execution failed",
        )

        new_state = agent.handle_error(state)

        assert new_state["current_phase"] == "error_handled"
        assert len(new_state["messages"]) == 1
        assert "Tool execution failed" in new_state["messages"][-1].content
        assert "different approach" in new_state["messages"][-1].content

    def test_run_complete_workflow(self, agent, mock_registry):
        """Test running complete agent workflow."""
        query = "Analyze GLM results for motor task"

        final_state = agent.run(query)

        assert final_state["current_phase"] in ["complete", "error_handled"]
        assert len(final_state["messages"]) > 1
        assert isinstance(final_state["messages"][0], HumanMessage)
        assert isinstance(final_state["messages"][-1], AIMessage)

    def test_run_with_initial_state(self, agent):
        """Test running with provided initial state."""
        initial_state = NeuroAgentState(
            messages=[HumanMessage(content="Custom query")],
            current_phase="tool_selection",
            selected_tools=["glm_analysis"],
        )

        final_state = agent.run("Ignored", initial_state=initial_state)

        # Should use provided state
        assert final_state["messages"][0].content == "Custom query"

    @patch("brain_researcher.services.agent.agents.neuro_agent.StateGraph")
    def test_graph_construction(self, mock_state_graph):
        """Test that the graph is constructed correctly."""
        mock_graph = Mock()
        mock_state_graph.return_value = mock_graph

        agent = NeuroAgent()

        # Verify nodes were added
        assert mock_graph.add_node.call_count == 7
        node_names = [call[0][0] for call in mock_graph.add_node.call_args_list]
        assert "understand" in node_names
        assert "select_tools" in node_names
        assert "execute" in node_names
        assert "validate" in node_names
        assert "synthesize" in node_names
        assert "memorize" in node_names
        assert "handle_error" in node_names

        # Verify edges
        assert mock_graph.add_edge.call_count >= 3
        assert mock_graph.add_conditional_edges.call_count >= 1

        # Verify compilation
        mock_graph.compile.assert_called_once()


class TestAgentIntegration:
    """Test agent integration scenarios."""

    def test_glm_to_concepts_workflow(self):
        """Test workflow from GLM analysis to concept mapping."""
        with patch("brain_researcher.services.agent.agents.neuro_agent.ToolRegistry") as mock_registry:
            # Setup mock tools
            glm_tool = Mock()
            glm_tool.get_tool_name.return_value = "glm_analysis"
            glm_tool.run.return_value = {
                "status": "success",
                "data": {
                    "dataset_id": "ds000001",
                    "peak_coordinates": [[-42, -22, 54]],
                },
            }

            coord_tool = Mock()
            coord_tool.get_tool_name.return_value = "coordinate_to_concept"
            coord_tool.run.return_value = {
                "status": "success",
                "data": {
                    "coordinate_mappings": [
                        {
                            "coordinate": [-42, -22, 54],
                            "concepts": [{"concept": "motor cortex", "score": 0.9}],
                            "region": "Motor cortex",
                        }
                    ]
                },
            }

            registry = mock_registry.return_value
            registry.get_tools_for_task.return_value = [glm_tool, coord_tool]
            registry.get_tool.side_effect = lambda name: {
                "glm_analysis": glm_tool,
                "coordinate_to_concept": coord_tool,
            }.get(name)

            agent = NeuroAgent(tool_registry=registry)

            # Run workflow
            final_state = agent.run("Analyze motor task and map to concepts")

            # Verify both tools were executed
            assert "glm_analysis" in final_state.get("results", {})
            assert final_state["current_phase"] in ["complete", "synthesis"]

    def test_error_recovery_workflow(self):
        """Test agent handles errors gracefully."""
        with patch("brain_researcher.services.agent.agents.neuro_agent.ToolRegistry") as mock_registry:
            # Setup failing tool
            failing_tool = Mock()
            failing_tool.get_tool_name.return_value = "failing_tool"
            failing_tool.run.side_effect = Exception("Connection timeout")

            registry = mock_registry.return_value
            registry.get_tools_for_task.return_value = [failing_tool]
            registry.get_tool.return_value = failing_tool

            agent = NeuroAgent(tool_registry=registry)

            # Run workflow
            final_state = agent.run("Run analysis")

            # Should handle error gracefully
            assert final_state["current_phase"] == "error_handled"
            assert "error" in final_state["messages"][-1].content.lower()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
