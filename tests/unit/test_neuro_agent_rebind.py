"""Unit tests for NeuroAgentLLM._rebind_tools_for_query() method.

Tests the two-stage retrieval, complexity gating, and dynamic rebinding logic.
"""

import pytest
from unittest.mock import MagicMock, patch


def _attach_binding_helpers(agent):
    from brain_researcher.services.agent.agents.neuro_agent_llm import NeuroAgentLLM

    helper_names = [
        "_llm_provider_family",
        "_provider_requires_safe_tool_names",
        "_make_provider_safe_tool_name",
        "_prepare_provider_bound_tools",
        "_normalize_tool_choice_for_binding",
        "_bind_tools_to_llm",
    ]
    for helper_name in helper_names:
        setattr(
            agent,
            helper_name,
            getattr(NeuroAgentLLM, helper_name).__get__(agent, NeuroAgentLLM),
        )
    agent._runtime_to_bound_tool_name = {}
    agent._bound_to_runtime_tool_name = {}
    return agent


class TestFamilyToRegistryMapping:
    """Test FAMILY_TO_REGISTRY_TOOLS mapping completeness."""

    def test_always_tools_exist(self):
        """Verify _always tools are defined."""
        from brain_researcher.services.agent.agents.neuro_agent_llm import (
            FAMILY_TO_REGISTRY_TOOLS,
        )

        assert "_always" in FAMILY_TO_REGISTRY_TOOLS
        assert len(FAMILY_TO_REGISTRY_TOOLS["_always"]) > 0

    def test_unknown_fallback_exists(self):
        """Verify _unknown fallback is defined."""
        from brain_researcher.services.agent.agents.neuro_agent_llm import (
            FAMILY_TO_REGISTRY_TOOLS,
        )

        assert "_unknown" in FAMILY_TO_REGISTRY_TOOLS
        assert len(FAMILY_TO_REGISTRY_TOOLS["_unknown"]) > 0

    def test_core_families_have_mapping(self):
        """Verify core neuroimaging families have mappings."""
        from brain_researcher.services.agent.agents.neuro_agent_llm import (
            FAMILY_TO_REGISTRY_TOOLS,
        )

        core_families = ["fsl", "freesurfer", "ants", "afni", "mrtrix3", "bidsapps"]
        for family in core_families:
            assert family in FAMILY_TO_REGISTRY_TOOLS, (
                f"Core family '{family}' missing from FAMILY_TO_REGISTRY_TOOLS"
            )


class TestComplexityGating:
    """Test complexity gating in _rebind_tools_for_query."""

    @pytest.fixture
    def mock_agent(self):
        """Create a mock NeuroAgentLLM with minimal setup."""
        from brain_researcher.services.agent.agents.neuro_agent_llm import (
            FAMILY_TO_REGISTRY_TOOLS,
        )

        # Create mock tools
        mock_tools = []
        for name in [
            "niwrap_search",
            "niwrap_schema",
            "neurodesk_command",
            "neurokg_query",
            "pubmed_search",
            "dataset_resources",
        ]:
            tool = MagicMock()
            tool.name = name
            mock_tools.append(tool)

        agent = MagicMock()
        agent.tools = mock_tools
        agent.tool_choice = "required"
        agent.retriever_max_families = 5
        agent.retriever_top_k = 100
        agent.max_bound_tools = 100
        agent.llm = MagicMock()

        return _attach_binding_helpers(agent)

    def test_simple_complexity_skips_rebind(self, mock_agent):
        """Test that simple queries skip rebinding."""
        from brain_researcher.services.agent.agents.neuro_agent_llm import (
            NeuroAgentLLM,
        )

        mock_retriever = MagicMock()
        mock_agent.tool_retriever = mock_retriever

        result = NeuroAgentLLM._rebind_tools_for_query(
            mock_agent, "what is brain?", complexity="simple"
        )

        assert result is False
        assert not mock_retriever.select_families_by_query.called
        assert not mock_agent.llm.bind_tools.called

    def test_moderate_complexity_triggers_rebind(self, mock_agent):
        """Test that moderate queries trigger rebinding."""
        from brain_researcher.services.agent.agents.neuro_agent_llm import (
            NeuroAgentLLM,
        )

        mock_retriever = MagicMock()
        mock_retriever.select_families_by_query.return_value = ["fsl"]
        # Mock Stage 2 results
        mock_kg_tool = MagicMock()
        mock_kg_tool.id = "fsl.bet.run"
        mock_retriever.retrieve_tools.return_value = [mock_kg_tool]
        mock_agent.tool_retriever = mock_retriever

        result = NeuroAgentLLM._rebind_tools_for_query(
            mock_agent, "run FSL BET", complexity="moderate"
        )

        assert result is True
        mock_retriever.select_families_by_query.assert_called_once()
        mock_retriever.retrieve_tools.assert_called_once()
        assert mock_agent.llm.bind_tools.called

    def test_complex_complexity_triggers_rebind(self, mock_agent):
        """Test that complex queries trigger rebinding."""
        from brain_researcher.services.agent.agents.neuro_agent_llm import (
            NeuroAgentLLM,
        )

        mock_retriever = MagicMock()
        mock_retriever.select_families_by_query.return_value = ["fsl", "freesurfer"]
        mock_kg_tool = MagicMock()
        mock_kg_tool.id = "fsl.bet.run"
        mock_retriever.retrieve_tools.return_value = [mock_kg_tool]
        mock_agent.tool_retriever = mock_retriever

        result = NeuroAgentLLM._rebind_tools_for_query(
            mock_agent, "multi-step pipeline", complexity="complex"
        )

        assert result is True
        assert mock_agent.llm.bind_tools.called

    def test_none_complexity_skips_rebind(self, mock_agent):
        """Test that None complexity skips rebinding."""
        from brain_researcher.services.agent.agents.neuro_agent_llm import (
            NeuroAgentLLM,
        )

        mock_retriever = MagicMock()
        mock_agent.tool_retriever = mock_retriever

        result = NeuroAgentLLM._rebind_tools_for_query(
            mock_agent, "any query", complexity=None
        )

        assert result is False
        assert not mock_retriever.select_families_by_query.called


class TestTwoStageRetrieval:
    """Test two-stage retrieval (family selection + embedding search)."""

    @pytest.fixture
    def mock_agent(self):
        """Create a mock NeuroAgentLLM with minimal setup."""
        mock_tools = []
        for name in [
            "niwrap_search",
            "niwrap_schema",
            "neurodesk_command",
            "neurokg_query",
            "pubmed_search",
            "dataset_resources",
        ]:
            tool = MagicMock()
            tool.name = name
            mock_tools.append(tool)

        agent = MagicMock()
        agent.tools = mock_tools
        agent.tool_choice = "required"
        agent.retriever_max_families = 5
        agent.retriever_top_k = 100
        agent.max_bound_tools = 100
        agent.llm = MagicMock()

        return _attach_binding_helpers(agent)

    def test_stage2_retrieve_tools_called_with_families(self, mock_agent):
        """Test that Stage 2 is called with Stage 1 family results."""
        from brain_researcher.services.agent.agents.neuro_agent_llm import (
            NeuroAgentLLM,
        )

        mock_retriever = MagicMock()
        mock_retriever.select_families_by_query.return_value = ["fsl", "ants"]
        mock_kg_tool = MagicMock()
        mock_kg_tool.id = "fsl.bet.run"
        mock_retriever.retrieve_tools.return_value = [mock_kg_tool]
        mock_agent.tool_retriever = mock_retriever

        NeuroAgentLLM._rebind_tools_for_query(
            mock_agent, "brain extraction", complexity="moderate"
        )

        mock_retriever.retrieve_tools.assert_called_once_with(
            query="brain extraction",
            family_ids=["fsl", "ants"],
            top_k=100,
        )

    def test_empty_families_returns_false(self, mock_agent):
        """Test that empty family selection returns False."""
        from brain_researcher.services.agent.agents.neuro_agent_llm import (
            NeuroAgentLLM,
        )

        mock_retriever = MagicMock()
        mock_retriever.select_families_by_query.return_value = []
        mock_agent.tool_retriever = mock_retriever

        result = NeuroAgentLLM._rebind_tools_for_query(
            mock_agent, "unknown query", complexity="moderate"
        )

        assert result is False
        assert not mock_retriever.retrieve_tools.called

    def test_empty_tools_returns_false(self, mock_agent):
        """Test that empty tool retrieval returns False."""
        from brain_researcher.services.agent.agents.neuro_agent_llm import (
            NeuroAgentLLM,
        )

        mock_retriever = MagicMock()
        mock_retriever.select_families_by_query.return_value = ["fsl"]
        mock_retriever.retrieve_tools.return_value = []
        mock_agent.tool_retriever = mock_retriever

        result = NeuroAgentLLM._rebind_tools_for_query(
            mock_agent, "find tools", complexity="moderate"
        )

        assert result is False
        assert not mock_agent.llm.bind_tools.called


class TestRebindFallbacks:
    """Test fallback behavior in rebinding."""

    @pytest.fixture
    def mock_agent(self):
        """Create a mock NeuroAgentLLM with minimal setup."""
        mock_tools = []
        for name in [
            "niwrap_search",
            "niwrap_schema",
            "neurodesk_command",
            "neurokg_query",
            "pubmed_search",
            "dataset_resources",
        ]:
            tool = MagicMock()
            tool.name = name
            mock_tools.append(tool)

        agent = MagicMock()
        agent.tools = mock_tools
        agent.tool_choice = "required"
        agent.retriever_max_families = 5
        agent.retriever_top_k = 100
        agent.max_bound_tools = 100
        agent.llm = MagicMock()

        return _attach_binding_helpers(agent)

    def test_rebind_returns_false_when_no_retriever(self, mock_agent):
        """Test that method returns False when no retriever is configured."""
        from brain_researcher.services.agent.agents.neuro_agent_llm import (
            NeuroAgentLLM,
        )

        mock_agent.tool_retriever = None

        result = NeuroAgentLLM._rebind_tools_for_query(
            mock_agent, "any query", complexity="moderate"
        )

        assert result is False
        assert not mock_agent.llm.bind_tools.called

    def test_rebind_handles_provider_not_supporting_tool_choice(self, mock_agent):
        """Test fallback when provider doesn't support tool_choice."""
        from brain_researcher.services.agent.agents.neuro_agent_llm import (
            NeuroAgentLLM,
        )

        mock_retriever = MagicMock()
        mock_retriever.select_families_by_query.return_value = ["fsl"]
        mock_kg_tool = MagicMock()
        mock_kg_tool.id = "fsl.bet.run"
        mock_retriever.retrieve_tools.return_value = [mock_kg_tool]
        mock_agent.tool_retriever = mock_retriever

        # First call raises TypeError (tool_choice not supported)
        # Second call succeeds (without tool_choice)
        mock_agent.llm.bind_tools.side_effect = [TypeError("bad kwarg"), None]

        result = NeuroAgentLLM._rebind_tools_for_query(
            mock_agent, "run FSL BET", complexity="moderate"
        )

        assert result is True
        assert mock_agent.llm.bind_tools.call_count == 2

    def test_rebind_returns_false_when_no_registry_tools_match(self, mock_agent):
        """Test that method returns False when no registry tools match at all."""
        from brain_researcher.services.agent.agents.neuro_agent_llm import (
            NeuroAgentLLM,
        )

        # Empty tools list means neither direct ID match nor family mapping will find tools
        mock_agent.tools = []

        mock_retriever = MagicMock()
        # Use an unknown family that won't have mapping
        mock_retriever.select_families_by_query.return_value = ["unknown_family_xyz"]
        mock_kg_tool = MagicMock()
        mock_kg_tool.id = "unknown_tool"
        mock_retriever.retrieve_tools.return_value = [mock_kg_tool]
        mock_agent.tool_retriever = mock_retriever

        # Explicitly mock _convert_kg_tools_to_registry_tools to return empty
        # (since mock_agent is a MagicMock, method calls return MagicMock by default)
        mock_agent._convert_kg_tools_to_registry_tools.return_value = []

        result = NeuroAgentLLM._rebind_tools_for_query(
            mock_agent, "unknown task", complexity="moderate"
        )

        # With empty tools list and unknown family, no tools can be bound
        assert result is False
        assert not mock_agent.llm.bind_tools.called

    def test_family_fallback_filters_executor_style_tools(self, mock_agent):
        """Family fallback must not reintroduce remote execution tools."""
        from brain_researcher.services.agent.agents.neuro_agent_llm import (
            NeuroAgentLLM,
        )

        method = NeuroAgentLLM._convert_planner_tool_ids_to_registry_tools.__get__(
            mock_agent, NeuroAgentLLM
        )

        bound_tools = method([], ["fsl"])
        bound_names = [tool.name for tool in bound_tools]

        assert "niwrap_execute" not in bound_names
        assert "neurodesk_command" not in bound_names
        assert "niwrap_search" in bound_names
        assert "niwrap_schema" in bound_names


class TestBRToolChoiceMode:
    """Test BR_TOOL_CHOICE_MODE environment variable."""

    def test_default_tool_choice_is_required(self):
        """Test that default tool_choice is 'required'."""
        import os

        env_backup = os.environ.pop("BR_TOOL_CHOICE_MODE", None)
        try:
            tool_choice = os.environ.get("BR_TOOL_CHOICE_MODE", "required")
            assert tool_choice == "required"
        finally:
            if env_backup:
                os.environ["BR_TOOL_CHOICE_MODE"] = env_backup

    def test_env_var_overrides_default(self):
        """Test that BR_TOOL_CHOICE_MODE can override default."""
        import os

        env_backup = os.environ.get("BR_TOOL_CHOICE_MODE")
        try:
            os.environ["BR_TOOL_CHOICE_MODE"] = "auto"
            tool_choice = os.environ.get("BR_TOOL_CHOICE_MODE", "required")
            assert tool_choice == "auto"
        finally:
            if env_backup:
                os.environ["BR_TOOL_CHOICE_MODE"] = env_backup
            else:
                os.environ.pop("BR_TOOL_CHOICE_MODE", None)
