"""Tests for tool registry evidence source adapter."""

import pytest
from unittest.mock import MagicMock, patch

from brain_researcher.services.knowledge.evidence.base import (
    EvidenceQuery,
    EvidenceSourceType,
)
from brain_researcher.services.knowledge.evidence.tool_source import (
    ToolEvidenceSource,
    search_tools,
)


class TestToolEvidenceSource:
    """Test suite for ToolEvidenceSource."""

    def setup_method(self):
        """Set up test fixtures."""
        self.mock_registry = MagicMock()
        self.source = ToolEvidenceSource(registry=self.mock_registry)

    def test_source_properties(self):
        """Test source type and id properties."""
        assert self.source.source_type == EvidenceSourceType.TOOL_REGISTRY
        assert self.source.source_id == "tool_registry"

    def test_source_without_registry(self):
        """Test source can be created without explicit registry."""
        source = ToolEvidenceSource()
        assert source._registry is None

    @patch("brain_researcher.services.tools.tool_registry.ToolRegistry")
    def test_lazy_registry_creation(self, mock_registry_class):
        """Test registry is lazily created on first use."""
        mock_registry = MagicMock()
        mock_registry.get_tools_for_task.return_value = []
        mock_registry_class.return_value = mock_registry

        source = ToolEvidenceSource()
        query = EvidenceQuery(text="skull stripping")
        source.query_sync(query)

        mock_registry_class.assert_called_once()

    def test_query_sync_basic(self):
        """Test basic query returns tool results."""
        # Setup mock tool
        mock_tool = MagicMock()
        mock_tool.get_tool_name.return_value = "fsl_bet"
        mock_tool.get_tool_description.return_value = "Brain extraction using FSL BET."
        mock_tool.TAGS = ["preprocessing", "skull-stripping"]
        mock_tool.__class__.__name__ = "FSLBETTool"

        self.mock_registry.get_tools_for_task.return_value = [mock_tool]

        query = EvidenceQuery(text="skull stripping", limit=5)
        results = self.source.query_sync(query)

        assert len(results) == 1
        assert results[0].source == EvidenceSourceType.TOOL_REGISTRY
        assert results[0].id == "fsl_bet"
        assert results[0].title == "fsl_bet"
        assert "FSL BET" in results[0].payload["description"]
        assert results[0].payload["tags"] == ["preprocessing", "skull-stripping"]
        assert results[0].payload["tool_class"] == "FSLBETTool"

    def test_query_sync_multiple_tools(self):
        """Test query returning multiple tools with decreasing relevance."""
        mock_tools = []
        for i, name in enumerate(["fsl_bet", "freesurfer_recon", "afni_3dSkullStrip"]):
            tool = MagicMock()
            tool.get_tool_name.return_value = name
            tool.get_tool_description.return_value = f"Description for {name}"
            tool.TAGS = ["preprocessing"]
            tool.__class__.__name__ = f"{name}Tool"
            mock_tools.append(tool)

        self.mock_registry.get_tools_for_task.return_value = mock_tools

        query = EvidenceQuery(text="brain extraction", limit=10)
        results = self.source.query_sync(query)

        assert len(results) == 3
        # First result should have highest relevance
        assert results[0].relevance_score > results[1].relevance_score
        assert results[1].relevance_score > results[2].relevance_score
        # All should have reasonable scores
        assert all(r.relevance_score >= 0.5 for r in results)

    def test_query_sync_respects_limit(self):
        """Test that query respects the limit parameter."""
        query = EvidenceQuery(text="preprocessing", limit=5)
        self.mock_registry.get_tools_for_task.return_value = []

        self.source.query_sync(query)

        # Check that k parameter was passed
        self.mock_registry.get_tools_for_task.assert_called_once_with(
            "preprocessing", k=5
        )

    def test_query_sync_empty_results(self):
        """Test query with no matching tools."""
        self.mock_registry.get_tools_for_task.return_value = []

        query = EvidenceQuery(text="nonexistent analysis xyz")
        results = self.source.query_sync(query)

        assert results == []

    def test_query_sync_handles_missing_tags(self):
        """Test query handles tools without TAGS attribute."""
        mock_tool = MagicMock(spec=["get_tool_name", "get_tool_description", "__class__"])
        mock_tool.get_tool_name.return_value = "custom_tool"
        mock_tool.get_tool_description.return_value = "A custom tool"
        mock_tool.__class__.__name__ = "CustomTool"
        # No TAGS attribute

        self.mock_registry.get_tools_for_task.return_value = [mock_tool]

        query = EvidenceQuery(text="custom analysis")
        results = self.source.query_sync(query)

        assert len(results) == 1
        assert results[0].payload["tags"] == []

    def test_query_sync_handles_exception(self):
        """Test query handles registry exceptions gracefully."""
        self.mock_registry.get_tools_for_task.side_effect = Exception("Registry error")

        query = EvidenceQuery(text="test query")
        results = self.source.query_sync(query)

        assert results == []

    def test_query_sync_truncates_description(self):
        """Test that long descriptions are truncated in summary."""
        mock_tool = MagicMock()
        mock_tool.get_tool_name.return_value = "long_desc_tool"
        long_desc = "A" * 500
        mock_tool.get_tool_description.return_value = long_desc
        mock_tool.TAGS = []
        mock_tool.__class__.__name__ = "LongDescTool"

        self.mock_registry.get_tools_for_task.return_value = [mock_tool]

        query = EvidenceQuery(text="test")
        results = self.source.query_sync(query)

        assert len(results) == 1
        # Summary should be truncated
        assert len(results[0].summary) <= 200

    def test_query_sync_confidence_score(self):
        """Test that results have appropriate confidence scores."""
        mock_tool = MagicMock()
        mock_tool.get_tool_name.return_value = "test_tool"
        mock_tool.get_tool_description.return_value = "Test tool"
        mock_tool.TAGS = []
        mock_tool.__class__.__name__ = "TestTool"

        self.mock_registry.get_tools_for_task.return_value = [mock_tool]

        query = EvidenceQuery(text="test")
        results = self.source.query_sync(query)

        assert results[0].confidence == 0.85

    def test_health_check_sync_registry_available(self):
        """Test health check when registry is available."""
        result = self.source.health_check_sync()
        assert result is True

    @patch("brain_researcher.services.tools.tool_registry.ToolRegistry")
    def test_health_check_sync_registry_unavailable(self, mock_registry_class):
        """Test health check when registry creation fails."""
        source = ToolEvidenceSource()  # No registry provided
        mock_registry_class.side_effect = Exception("Import failed")

        result = source.health_check_sync()
        assert result is False


class TestSearchToolsFunction:
    """Test search_tools convenience function."""

    @patch("brain_researcher.services.knowledge.evidence.tool_source.ToolEvidenceSource")
    def test_search_tools_basic(self, mock_source_class):
        """Test basic search_tools call."""
        mock_source = MagicMock()
        mock_source.query_sync.return_value = []
        mock_source_class.return_value = mock_source

        results = search_tools("fmri preprocessing", limit=5)

        mock_source.query_sync.assert_called_once()
        query = mock_source.query_sync.call_args[0][0]
        assert query.text == "fmri preprocessing"
        assert query.limit == 5

    @patch("brain_researcher.services.knowledge.evidence.tool_source.ToolEvidenceSource")
    def test_search_tools_default_limit(self, mock_source_class):
        """Test search_tools uses default limit."""
        mock_source = MagicMock()
        mock_source.query_sync.return_value = []
        mock_source_class.return_value = mock_source

        results = search_tools("brain extraction")

        query = mock_source.query_sync.call_args[0][0]
        assert query.limit == 10  # Default

    @patch("brain_researcher.services.knowledge.evidence.tool_source.ToolEvidenceSource")
    def test_search_tools_returns_results(self, mock_source_class):
        """Test search_tools returns results from source."""
        mock_result = MagicMock()
        mock_result.id = "fsl_bet"

        mock_source = MagicMock()
        mock_source.query_sync.return_value = [mock_result]
        mock_source_class.return_value = mock_source

        results = search_tools("skull stripping")

        assert len(results) == 1
        assert results[0].id == "fsl_bet"
