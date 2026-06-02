"""Tests for KG evidence source adapter."""

from unittest.mock import MagicMock, patch

import pytest

from brain_researcher.services.knowledge.evidence.base import (
    EvidenceQuery,
    EvidenceSourceType,
)
from brain_researcher.services.knowledge.evidence.kg_source import (
    KGEvidenceSource,
    get_brain_regions,
    get_concepts,
)


class TestKGEvidenceSource:
    """Test suite for KGEvidenceSource."""

    def setup_method(self):
        """Set up test fixtures."""
        self.mock_db = MagicMock()
        self.source = KGEvidenceSource(db=self.mock_db)

    def test_source_properties(self):
        """Test source type and id properties."""
        assert self.source.source_type == EvidenceSourceType.KNOWLEDGE_GRAPH
        assert self.source.source_id == "br_kg"

    def test_source_without_db(self):
        """Test source can be created without explicit db."""
        source = KGEvidenceSource()
        assert source._db is None

    @patch("brain_researcher.services.br_kg.query_service.search_nodes")
    def test_query_sync_basic(self, mock_search_nodes):
        """Test basic query returns results."""
        # Setup mock
        mock_node = MagicMock()
        mock_node.kg_id = "concept:motor_cortex"
        mock_node.label = "Motor Cortex"
        mock_node.node_type = "BrainRegion"
        mock_node.properties = {}
        mock_node.score = 0.92

        mock_search_nodes.return_value = [mock_node]

        # Execute query
        query = EvidenceQuery(text="motor cortex", limit=5)
        results = self.source.query_sync(query)

        # Verify
        assert len(results) == 1
        assert results[0].source == EvidenceSourceType.KNOWLEDGE_GRAPH
        assert results[0].id == "concept:motor_cortex"
        assert results[0].title == "Motor Cortex"
        assert results[0].relevance_score == 0.92
        assert results[0].payload["node_type"] == "BrainRegion"

        mock_search_nodes.assert_called_once()

    @patch("brain_researcher.services.br_kg.query_service.search_nodes")
    def test_query_sync_empty_results(self, mock_search_nodes):
        """Test query with no results."""
        mock_search_nodes.return_value = []

        query = EvidenceQuery(text="nonexistent concept xyz123")
        results = self.source.query_sync(query)

        assert results == []

    @patch("brain_researcher.services.br_kg.query_service.search_nodes")
    def test_query_sync_handles_exception(self, mock_search_nodes):
        """Test query handles exceptions gracefully."""
        mock_search_nodes.side_effect = Exception("DB connection failed")

        query = EvidenceQuery(text="test query")
        results = self.source.query_sync(query)

        assert results == []

    @patch("brain_researcher.services.br_kg.query_service.search_nodes")
    def test_query_sync_multiple_results(self, mock_search_nodes):
        """Test query with multiple results."""
        mock_nodes = []
        for i in range(3):
            node = MagicMock()
            node.kg_id = f"concept:node_{i}"
            node.label = f"Node {i}"
            node.node_type = "Concept"
            node.properties = {}
            node.score = 0.9 - i * 0.1
            mock_nodes.append(node)

        mock_search_nodes.return_value = mock_nodes

        query = EvidenceQuery(text="test", limit=10)
        results = self.source.query_sync(query)

        assert len(results) == 3
        # Check relevance scores are preserved
        assert results[0].relevance_score == 0.9
        assert results[1].relevance_score == 0.8
        assert abs(results[2].relevance_score - 0.7) < 0.01

    @patch("brain_researcher.services.br_kg.query_service.search_nodes")
    def test_query_sync_with_node_types_filter(self, mock_search_nodes):
        """Test query with node_types filter."""
        mock_node = MagicMock()
        mock_node.kg_id = "region:v1"
        mock_node.label = "Visual Cortex V1"
        mock_node.node_type = "BrainRegion"
        mock_node.properties = {}
        mock_node.score = 0.88

        mock_search_nodes.return_value = [mock_node]

        query = EvidenceQuery(text="visual cortex", node_types=["BrainRegion"])
        results = self.source.query_sync(query)

        mock_search_nodes.assert_called_once()
        call_kwargs = mock_search_nodes.call_args[1]
        assert call_kwargs.get("node_types") == ["BrainRegion"]

    @patch("brain_researcher.services.br_kg.query_service.search_nodes")
    def test_query_sync_passes_limit(self, mock_search_nodes):
        """Test that limit is passed to the query service."""
        mock_search_nodes.return_value = []

        query = EvidenceQuery(text="test", limit=25)
        self.source.query_sync(query)

        call_kwargs = mock_search_nodes.call_args[1]
        assert call_kwargs.get("limit") == 25

    @patch("brain_researcher.services.br_kg.query_service.search_nodes")
    def test_query_sync_brain_region_detection(self, mock_search_nodes):
        """Test that brain regions are correctly identified."""
        mock_region = MagicMock()
        mock_region.kg_id = "region:motor"
        mock_region.label = "Motor Cortex"
        mock_region.node_type = "BrainRegion"
        mock_region.properties = {}
        mock_region.score = 0.9

        mock_concept = MagicMock()
        mock_concept.kg_id = "concept:motor_task"
        mock_concept.label = "Motor Task"
        mock_concept.node_type = "Concept"
        mock_concept.properties = {}
        mock_concept.score = 0.85

        mock_search_nodes.return_value = [mock_region, mock_concept]

        query = EvidenceQuery(text="motor")
        results = self.source.query_sync(query)

        assert len(results) == 2
        # First is brain region
        assert results[0].payload["is_brain_region"] is True
        assert isinstance(results[0].payload, dict)
        assert results[0].relevance_score == 0.9
        # Second is not
        assert results[1].payload["is_brain_region"] is False
        assert isinstance(results[1].payload, dict)
        assert results[1].relevance_score == 0.85

    @patch("brain_researcher.services.br_kg.query_service.get_default_db")
    def test_health_check_sync_with_db(self, mock_get_default_db):
        """Test health check with database."""
        mock_get_default_db.return_value = MagicMock()

        result = self.source.health_check_sync()
        assert result is True

    @patch("brain_researcher.services.br_kg.query_service.get_default_db")
    def test_health_check_sync_no_db(self, mock_get_default_db):
        """Test health check when db is not available."""
        source = KGEvidenceSource()  # No db passed
        mock_get_default_db.return_value = None

        result = source.health_check_sync()
        assert result is False


class TestConvenienceFunctions:
    """Test convenience functions for KG queries."""

    @patch("brain_researcher.services.br_kg.query_service.search_nodes")
    def test_get_concepts(self, mock_search_nodes):
        """Test get_concepts convenience function."""
        mock_node = MagicMock()
        mock_node.kg_id = "concept:test"
        mock_node.label = "Test Concept"
        mock_node.node_type = "Concept"
        mock_node.properties = {}
        mock_node.score = 0.9

        mock_search_nodes.return_value = [mock_node]

        results = get_concepts("test query", limit=5)

        mock_search_nodes.assert_called_once()
        call_kwargs = mock_search_nodes.call_args[1]
        # Should filter by concept types (include Concept/Term aliases)
        node_types = call_kwargs.get("node_types", [])
        assert "Concept" in node_types
        assert call_kwargs.get("limit") == 5

    @patch("brain_researcher.services.br_kg.query_service.search_nodes")
    def test_get_brain_regions(self, mock_search_nodes):
        """Test get_brain_regions convenience function."""
        mock_node = MagicMock()
        mock_node.kg_id = "region:motor"
        mock_node.label = "Motor Cortex"
        mock_node.node_type = "BrainRegion"
        mock_node.properties = {}
        mock_node.score = 0.88

        mock_search_nodes.return_value = [mock_node]

        results = get_brain_regions("motor cortex", limit=10)

        mock_search_nodes.assert_called_once()
        call_kwargs = mock_search_nodes.call_args[1]
        # Should filter by BrainRegion type
        node_types = call_kwargs.get("node_types", [])
        assert "BrainRegion" in node_types
        assert call_kwargs.get("limit") == 10
