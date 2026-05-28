"""
Unit tests for state management classes.
"""

import pytest
from langchain_core.messages import AIMessage, HumanMessage

from brain_researcher.services.agent.states.base import (
    InteractiveSessionState,
    MetaAnalysisState,
    NeuroAgentState,
    ResearchState,
)


class TestNeuroAgentState:
    """Test minimal agent state functionality."""

    def test_state_creation_with_required_fields(self):
        """Test state can be created with all required fields."""
        state = NeuroAgentState(
            messages=[HumanMessage(content="Analyze motor task")],
            current_phase="planning",
            selected_tools=["glm_analysis"],
            tool_args=None,
            results=None,
            error=None,
        )

        assert len(state["messages"]) == 1
        assert state["messages"][0].content == "Analyze motor task"
        assert state["current_phase"] == "planning"
        assert "glm_analysis" in state["selected_tools"]
        assert state["error"] is None

    def test_state_creation_minimal(self):
        """Test state can be created with minimal fields."""
        state = NeuroAgentState(messages=[], current_phase="init", selected_tools=[])

        assert state["messages"] == []
        assert state["current_phase"] == "init"
        assert state["selected_tools"] == []

    def test_state_update(self):
        """Test state fields can be updated."""
        state = NeuroAgentState(messages=[], current_phase="init", selected_tools=[])

        # Update state
        state["current_phase"] = "execution"
        state["selected_tools"].append("neurokg_query")
        state["tool_args"] = {"neurokg_query": {"concept": "motor cortex"}}

        assert state["current_phase"] == "execution"
        assert len(state["selected_tools"]) == 1
        assert state["tool_args"]["neurokg_query"]["concept"] == "motor cortex"

    def test_message_list_behavior(self):
        """Test message list maintains conversation history."""
        messages = [HumanMessage(content="First message")]
        state = NeuroAgentState(
            messages=messages, current_phase="init", selected_tools=[]
        )

        # Add more messages
        state["messages"].append(AIMessage(content="Response"))
        state["messages"].append(HumanMessage(content="Follow-up"))

        assert len(state["messages"]) == 3
        assert isinstance(state["messages"][0], HumanMessage)
        assert isinstance(state["messages"][1], AIMessage)
        assert state["messages"][2].content == "Follow-up"

    def test_error_handling(self):
        """Test error field usage."""
        state = NeuroAgentState(
            messages=[],
            current_phase="execution",
            selected_tools=["glm_analysis"],
            error="Tool execution failed: GLM analysis error",
        )

        assert state["error"] is not None
        assert "GLM analysis error" in state["error"]


class TestResearchState:
    """Test extended research state for complex workflows."""

    def test_research_state_full_initialization(self):
        """Test research state with all fields."""
        state = ResearchState(
            # Base fields
            messages=[HumanMessage(content="Research query")],
            current_phase="planning",
            selected_tools=[],
            # fMRI fields
            dataset_id="ds000001",
            analysis_type="glm",
            analysis_results={"contrasts": {}},
            coordinates=[[-42, -22, 54]],
            # BR-KG fields
            concepts=["motor cortex"],
            concept_relationships={"motor cortex": ["movement", "primary motor area"]},
            literature_findings=[{"title": "Motor study", "pmid": "12345"}],
            # Integration fields
            synthesis={"summary": "Initial findings"},
            confidence_scores={"motor_activation": 0.95},
        )

        assert state["dataset_id"] == "ds000001"
        assert state["analysis_type"] == "glm"
        assert len(state["coordinates"]) == 1
        assert "motor cortex" in state["concepts"]
        assert len(state["concept_relationships"]["motor cortex"]) == 2
        assert state["confidence_scores"]["motor_activation"] == 0.95

    def test_research_state_optional_fields(self):
        """Test research state with optional fields as None."""
        state = ResearchState(
            messages=[],
            current_phase="init",
            selected_tools=[],
            dataset_id=None,
            analysis_results={},
            coordinates=[],
            concepts=[],
            concept_relationships={},
            literature_findings=[],
        )

        assert state["dataset_id"] is None
        assert state["analysis_results"] == {}
        assert state["coordinates"] == []
        assert state.get("synthesis") is None

    def test_coordinate_management(self):
        """Test brain coordinate list management."""
        state = ResearchState(
            messages=[],
            current_phase="analysis",
            selected_tools=["glm_analysis"],
            analysis_results={},
            coordinates=[],
            concepts=[],
            concept_relationships={},
            literature_findings=[],
        )

        # Add coordinates
        state["coordinates"].append([-42, -22, 54])  # Left motor
        state["coordinates"].append([42, -22, 54])  # Right motor

        assert len(state["coordinates"]) == 2
        assert state["coordinates"][0][0] == -42
        assert state["coordinates"][1][0] == 42

    def test_concept_relationship_building(self):
        """Test building concept relationship graph."""
        state = ResearchState(
            messages=[],
            current_phase="kg_enrichment",
            selected_tools=[],
            analysis_results={},
            coordinates=[],
            concepts=["motor cortex", "movement"],
            concept_relationships={},
            literature_findings=[],
        )

        # Build relationships
        state["concept_relationships"]["motor cortex"] = ["movement", "motor control"]
        state["concept_relationships"]["movement"] = ["motor cortex", "action"]

        assert len(state["concept_relationships"]) == 2
        assert "movement" in state["concept_relationships"]["motor cortex"]
        assert "action" in state["concept_relationships"]["movement"]


class TestMetaAnalysisState:
    """Test meta-analysis specific state."""

    def test_meta_analysis_state_creation(self):
        """Test creating meta-analysis state."""
        state = MetaAnalysisState(
            messages=[HumanMessage(content="Run meta-analysis")],
            current_phase="study_selection",
            selected_tools=["dataset_search"],
            dataset_ids=["ds000001", "ds000002", "ds000003"],
            inclusion_criteria={
                "task_type": "motor",
                "min_subjects": 20,
                "has_contrasts": True,
            },
            included_studies=[],
            excluded_studies=[],
        )

        assert len(state["dataset_ids"]) == 3
        assert state["inclusion_criteria"]["task_type"] == "motor"
        assert state["inclusion_criteria"]["min_subjects"] == 20
        assert state["included_studies"] == []

    def test_study_filtering(self):
        """Test adding studies to included/excluded lists."""
        state = MetaAnalysisState(
            messages=[],
            current_phase="filtering",
            selected_tools=[],
            dataset_ids=["ds000001", "ds000002"],
            inclusion_criteria={},
            included_studies=[],
            excluded_studies=[],
        )

        # Add included study
        state["included_studies"].append(
            {"dataset_id": "ds000001", "n_subjects": 30, "task": "motor"}
        )

        # Add excluded study
        state["excluded_studies"].append(
            {"dataset_id": "ds000002", "n_subjects": 15, "reason": "Too few subjects"}
        )

        assert len(state["included_studies"]) == 1
        assert len(state["excluded_studies"]) == 1
        assert state["excluded_studies"][0]["reason"] == "Too few subjects"

    def test_pooled_results_storage(self):
        """Test storing meta-analysis results."""
        state = MetaAnalysisState(
            messages=[],
            current_phase="analysis",
            selected_tools=[],
            dataset_ids=[],
            inclusion_criteria={},
            included_studies=[],
            excluded_studies=[],
            pooled_results={
                "effect_size": 0.65,
                "ci_lower": 0.45,
                "ci_upper": 0.85,
                "p_value": 0.001,
            },
            heterogeneity_stats={"i_squared": 45.2, "tau_squared": 0.08},
        )

        assert state["pooled_results"]["effect_size"] == 0.65
        assert state["heterogeneity_stats"]["i_squared"] == 45.2


class TestInteractiveSessionState:
    """Test interactive session state with memory."""

    def test_session_state_creation(self):
        """Test creating interactive session state."""
        state = InteractiveSessionState(
            messages=[HumanMessage(content="Start session")],
            current_phase="init",
            selected_tools=[],
            session_id="session_123",
            session_history=[],
            context_window=[],
            accumulated_findings={},
        )

        assert state["session_id"] == "session_123"
        assert state["session_history"] == []
        assert state["accumulated_findings"] == {}

    def test_session_history_accumulation(self):
        """Test building session history over time."""
        state = InteractiveSessionState(
            messages=[],
            current_phase="active",
            selected_tools=[],
            session_id="session_123",
            session_history=[],
            context_window=[],
            accumulated_findings={},
        )

        # Add to history
        state["session_history"].append(
            {
                "query": "Analyze motor cortex",
                "timestamp": "2024-01-01T10:00:00",
                "tools_used": ["glm_analysis"],
                "key_findings": ["Bilateral activation"],
            }
        )

        state["session_history"].append(
            {
                "query": "Find related papers",
                "timestamp": "2024-01-01T10:05:00",
                "tools_used": ["literature_search"],
                "key_findings": ["10 relevant papers found"],
            }
        )

        assert len(state["session_history"]) == 2
        assert state["session_history"][0]["tools_used"] == ["glm_analysis"]
        assert state["session_history"][1]["query"] == "Find related papers"

    def test_context_window_management(self):
        """Test maintaining context window for recent messages."""
        state = InteractiveSessionState(
            messages=[],
            current_phase="active",
            selected_tools=[],
            session_id="session_123",
            session_history=[],
            context_window=[],
            accumulated_findings={},
        )

        # Add messages to context window
        for i in range(5):
            state["context_window"].append(HumanMessage(content=f"Message {i}"))

        # Simulate sliding window (keep last 3)
        if len(state["context_window"]) > 3:
            state["context_window"] = state["context_window"][-3:]

        assert len(state["context_window"]) == 3
        assert state["context_window"][0].content == "Message 2"
        assert state["context_window"][-1].content == "Message 4"

    def test_accumulated_findings(self):
        """Test accumulating findings across queries."""
        state = InteractiveSessionState(
            messages=[],
            current_phase="active",
            selected_tools=[],
            session_id="session_123",
            session_history=[],
            context_window=[],
            accumulated_findings={},
        )

        # Add findings from different analyses
        state["accumulated_findings"]["motor_regions"] = [
            "Primary motor cortex",
            "Supplementary motor area",
        ]

        state["accumulated_findings"]["peak_coordinates"] = [
            [-42, -22, 54],
            [0, -4, 58],
        ]

        state["accumulated_findings"]["related_concepts"] = {
            "motor cortex": ["movement", "motor control"],
            "SMA": ["motor planning", "sequence learning"],
        }

        assert len(state["accumulated_findings"]) == 3
        assert len(state["accumulated_findings"]["motor_regions"]) == 2
        assert state["accumulated_findings"]["peak_coordinates"][0][0] == -42


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
