"""Unit tests for evidence_connector.py."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from brain_researcher.services.agent.knowledge.evidence_connector import (
    DatasetCatalogConnector,
    EvidenceAggregator,
    EvidenceConnector,
    KGNodeConnector,
    LiteratureConnector,
    NeuroStoreConnector,
    ToolCatalogConnector,
)
from brain_researcher.services.agent.knowledge.evidence_models import (
    EvidenceItem,
    EvidenceSourceType,
)


class MockKGNodeSummary:
    """Mock for KGNodeSummary from query_service."""

    def __init__(
        self, kg_id: str, label: str, node_type: str = "Publication", score: float = 1.0
    ):
        self.kg_id = kg_id
        self.label = label
        self.node_type = node_type
        self.score = score
        self.properties = {}


class MockDatasetSummary:
    """Mock for DatasetSummary from query_service."""

    def __init__(
        self,
        dataset_id: str,
        title: str,
        tasks: list = None,
        modalities: list = None,
    ):
        self.dataset_id = dataset_id
        self.title = title
        self.tasks = tasks or []
        self.modalities = modalities or []
        self.n_subjects = 20
        self.species = "human"
        self.kg_id = f"kg:{dataset_id}"


class TestLiteratureConnector:
    """Tests for LiteratureConnector."""

    @pytest.mark.asyncio
    async def test_search_neo4j_success(self):
        """Test successful Neo4j search."""
        mock_nodes = [
            MockKGNodeSummary(
                "pmid:12345", "Motor cortex activation study", "Publication", 0.9
            ),
            MockKGNodeSummary(
                "pmid:67890", "fMRI motor task analysis", "Publication", 0.8
            ),
        ]

        with patch(
            "brain_researcher.services.br_kg.query_service.search_nodes",
            return_value=mock_nodes,
        ):
            connector = LiteratureConnector(use_edirect_fallback=False)
            items = await connector.search("motor cortex", limit=10)

            assert len(items) == 2
            assert items[0].source_type == EvidenceSourceType.PUBMED
            assert items[0].source_id == "pmid:12345"
            assert items[0].relevance_score == 0.9
            assert "pubmed.ncbi.nlm.nih.gov/12345" in items[0].url

    @pytest.mark.asyncio
    async def test_search_neo4j_failure_returns_empty(self):
        """Test that Neo4j failure returns empty list."""
        with patch(
            "brain_researcher.services.br_kg.query_service.search_nodes",
            side_effect=Exception("DB connection failed"),
        ):
            connector = LiteratureConnector(use_edirect_fallback=False)
            items = await connector.search("test query")

            assert items == []

    def test_source_properties(self):
        """Test connector properties."""
        connector = LiteratureConnector()
        assert connector.source_name == "literature"
        assert connector.source_type == EvidenceSourceType.PUBMED

    def test_build_pubmed_url(self):
        """Test PubMed URL building."""
        connector = LiteratureConnector()
        assert (
            connector._build_pubmed_url("pmid:12345")
            == "https://pubmed.ncbi.nlm.nih.gov/12345"
        )
        assert connector._build_pubmed_url("other:id") is None


class TestNeuroStoreConnector:
    """Tests for NeuroStoreConnector."""

    @pytest.mark.asyncio
    async def test_search_success(self):
        """Test successful NeuroStore search."""
        mock_nodes = [
            MockKGNodeSummary(
                "neurostore:abc123", "Motor meta-analysis", "Study", 0.85
            ),
        ]

        with patch(
            "brain_researcher.services.br_kg.query_service.search_nodes",
            return_value=mock_nodes,
        ):
            connector = NeuroStoreConnector()
            items = await connector.search("motor", limit=10)

            assert len(items) == 1
            assert items[0].source_type == EvidenceSourceType.NEUROSTORE
            assert items[0].source_id == "neurostore:abc123"

    def test_source_properties(self):
        """Test connector properties."""
        connector = NeuroStoreConnector()
        assert connector.source_name == "neurostore"
        assert connector.source_type == EvidenceSourceType.NEUROSTORE


class TestDatasetCatalogConnector:
    """Tests for DatasetCatalogConnector."""

    @pytest.mark.asyncio
    async def test_search_success(self):
        """Test successful dataset search."""
        mock_datasets = [
            MockDatasetSummary(
                "ds001234", "Motor Task fMRI Dataset", ["motor"], ["fMRI"]
            ),
            MockDatasetSummary("ds005678", "Visual Task Dataset", ["visual"], ["fMRI"]),
        ]

        with patch(
            "brain_researcher.services.br_kg.query_service.search_datasets",
            return_value=mock_datasets,
        ):
            connector = DatasetCatalogConnector()
            items = await connector.search("motor task", limit=10)

            assert len(items) == 2
            assert items[0].source_type == EvidenceSourceType.DATASET_CATALOG
            assert items[0].source_id == "ds001234"
            assert items[0].metadata["tasks"] == ["motor"]
            assert "openneuro.org" in items[0].url

    @pytest.mark.asyncio
    async def test_search_failure_returns_empty(self):
        """Test that search failure returns empty list."""
        with patch(
            "brain_researcher.services.br_kg.query_service.search_datasets",
            side_effect=Exception("Search failed"),
        ):
            connector = DatasetCatalogConnector()
            items = await connector.search("test")

            assert items == []

    def test_source_properties(self):
        """Test connector properties."""
        connector = DatasetCatalogConnector()
        assert connector.source_name == "dataset_catalog"
        assert connector.source_type == EvidenceSourceType.DATASET_CATALOG


class TestKGNodeConnector:
    """Tests for KGNodeConnector."""

    @pytest.mark.asyncio
    async def test_search_success(self):
        """Test successful KG node search."""
        mock_nodes = [
            MockKGNodeSummary(
                "concept:motor_cortex", "Motor Cortex", "CognitiveConcept", 0.95
            ),
        ]

        with patch(
            "brain_researcher.services.br_kg.query_service.search_nodes",
            return_value=mock_nodes,
        ):
            connector = KGNodeConnector()
            items = await connector.search("motor cortex", limit=10)

            assert len(items) == 1
            assert items[0].source_type == EvidenceSourceType.KG_GRAPH
            assert items[0].source_id == "concept:motor_cortex"

    @pytest.mark.asyncio
    async def test_search_with_node_type_filter(self):
        """Test search with node type filtering."""
        mock_nodes = [
            MockKGNodeSummary("region:m1", "Primary Motor Cortex", "BrainRegion", 0.9),
        ]

        with patch(
            "brain_researcher.services.br_kg.query_service.search_nodes",
            return_value=mock_nodes,
        ) as mock_search:
            connector = KGNodeConnector(node_types=["BrainRegion"])
            await connector.search("motor", limit=10)

            # Verify node_types was passed
            call_args = mock_search.call_args
            assert call_args[1]["node_types"] == ["BrainRegion"]

    def test_source_properties(self):
        """Test connector properties."""
        connector = KGNodeConnector()
        assert connector.source_name == "kg_graph"
        assert connector.source_type == EvidenceSourceType.KG_GRAPH


class TestToolCatalogConnector:
    """Tests for ToolCatalogConnector."""

    @pytest.mark.asyncio
    async def test_search_success(self):
        """Test successful tool search."""
        mock_tool = MagicMock()
        mock_tool.get_tool_name.return_value = "fmriprep"
        mock_tool.get_tool_description.return_value = "fMRI preprocessing pipeline"

        mock_registry = MagicMock()
        mock_registry.all_tools.return_value = [mock_tool]

        with patch(
            "brain_researcher.services.tools.tool_registry.ToolRegistry",
            return_value=mock_registry,
        ):
            connector = ToolCatalogConnector()
            connector._registry = mock_registry
            items = await connector.search("fmri preprocessing", limit=10)

            assert len(items) == 1
            assert items[0].source_type == EvidenceSourceType.TOOL_CATALOG
            assert items[0].source_id == "fmriprep"

    def test_source_properties(self):
        """Test connector properties."""
        connector = ToolCatalogConnector()
        assert connector.source_name == "tool_catalog"
        assert connector.source_type == EvidenceSourceType.TOOL_CATALOG


class TestEvidenceAggregator:
    """Tests for EvidenceAggregator."""

    @pytest.mark.asyncio
    async def test_gather_evidence_combines_sources(self):
        """Test that aggregator combines results from multiple sources."""
        # Create mock connectors
        mock_lit_connector = MagicMock()
        mock_lit_connector.source_type = EvidenceSourceType.PUBMED
        mock_lit_connector.source_name = "literature"
        mock_lit_connector.search = AsyncMock(
            return_value=[
                EvidenceItem(
                    source_type=EvidenceSourceType.PUBMED,
                    source_id="pmid:1",
                    label="Paper 1",
                )
            ]
        )

        mock_ds_connector = MagicMock()
        mock_ds_connector.source_type = EvidenceSourceType.DATASET_CATALOG
        mock_ds_connector.source_name = "dataset"
        mock_ds_connector.search = AsyncMock(
            return_value=[
                EvidenceItem(
                    source_type=EvidenceSourceType.DATASET_CATALOG,
                    source_id="ds001",
                    label="Dataset 1",
                )
            ]
        )

        aggregator = EvidenceAggregator(
            connectors=[mock_lit_connector, mock_ds_connector],
            source_timeout=1.0,
            total_timeout=2.0,
        )

        bundle = await aggregator.gather_evidence("motor cortex", limit=10)

        assert len(bundle.items) == 2
        assert bundle.total_literature_count == 1
        assert bundle.total_dataset_count == 1

    @pytest.mark.asyncio
    async def test_gather_evidence_filters_by_source_type(self):
        """Test filtering by source type."""
        mock_lit_connector = MagicMock()
        mock_lit_connector.source_type = EvidenceSourceType.PUBMED
        mock_lit_connector.source_name = "literature"
        mock_lit_connector.search = AsyncMock(
            return_value=[
                EvidenceItem(
                    source_type=EvidenceSourceType.PUBMED,
                    source_id="pmid:1",
                    label="Paper 1",
                )
            ]
        )

        mock_ds_connector = MagicMock()
        mock_ds_connector.source_type = EvidenceSourceType.DATASET_CATALOG
        mock_ds_connector.source_name = "dataset"
        mock_ds_connector.search = AsyncMock(
            return_value=[
                EvidenceItem(
                    source_type=EvidenceSourceType.DATASET_CATALOG,
                    source_id="ds001",
                    label="Dataset 1",
                )
            ]
        )

        aggregator = EvidenceAggregator(
            connectors=[mock_lit_connector, mock_ds_connector]
        )

        # Only request PUBMED
        bundle = await aggregator.gather_evidence(
            "motor cortex",
            sources=[EvidenceSourceType.PUBMED],
            limit=10,
        )

        assert len(bundle.items) == 1
        assert bundle.total_literature_count == 1
        assert bundle.total_dataset_count == 0
        mock_ds_connector.search.assert_not_called()

    @pytest.mark.asyncio
    async def test_gather_evidence_handles_connector_failure(self):
        """Test graceful handling of connector failures."""
        mock_failing_connector = MagicMock()
        mock_failing_connector.source_type = EvidenceSourceType.PUBMED
        mock_failing_connector.source_name = "failing"
        mock_failing_connector.search = AsyncMock(
            side_effect=Exception("Connection failed")
        )

        mock_success_connector = MagicMock()
        mock_success_connector.source_type = EvidenceSourceType.DATASET_CATALOG
        mock_success_connector.source_name = "success"
        mock_success_connector.search = AsyncMock(
            return_value=[
                EvidenceItem(
                    source_type=EvidenceSourceType.DATASET_CATALOG,
                    source_id="ds001",
                    label="Dataset 1",
                )
            ]
        )

        aggregator = EvidenceAggregator(
            connectors=[mock_failing_connector, mock_success_connector]
        )

        bundle = await aggregator.gather_evidence("test", limit=10)

        # Should still get results from successful connector
        assert len(bundle.items) == 1
        assert bundle.total_dataset_count == 1

    @pytest.mark.asyncio
    async def test_gather_evidence_respects_timeout(self):
        """Test that slow connectors are handled via timeout."""

        async def slow_search(query, limit):
            await asyncio.sleep(5.0)  # Very slow
            return []

        mock_slow_connector = MagicMock()
        mock_slow_connector.source_type = EvidenceSourceType.PUBMED
        mock_slow_connector.source_name = "slow"
        mock_slow_connector.search = slow_search

        aggregator = EvidenceAggregator(
            connectors=[mock_slow_connector],
            source_timeout=0.1,  # Very short timeout
            total_timeout=0.2,
        )

        bundle = await aggregator.gather_evidence("test", limit=10)

        # Should return empty bundle without crashing
        assert len(bundle.items) == 0

    @pytest.mark.asyncio
    async def test_gather_evidence_computes_confidence(self):
        """Test that confidence is computed after gathering."""
        mock_connector = MagicMock()
        mock_connector.source_type = EvidenceSourceType.PUBMED
        mock_connector.source_name = "lit"
        mock_connector.search = AsyncMock(
            return_value=[
                EvidenceItem(
                    source_type=EvidenceSourceType.PUBMED,
                    source_id=f"pmid:{i}",
                    label=f"Paper {i}",
                )
                for i in range(5)
            ]
        )

        aggregator = EvidenceAggregator(connectors=[mock_connector])
        bundle = await aggregator.gather_evidence("test", limit=10)

        # Confidence should be computed (not default 0.5)
        assert bundle.confidence > 0.0
        assert bundle.confidence < 1.0


class TestEvidenceConnectorProtocol:
    """Tests for EvidenceConnector protocol compliance."""

    def test_literature_connector_implements_protocol(self):
        """Test LiteratureConnector implements protocol."""
        connector = LiteratureConnector()
        assert isinstance(connector, EvidenceConnector)

    def test_neurostore_connector_implements_protocol(self):
        """Test NeuroStoreConnector implements protocol."""
        connector = NeuroStoreConnector()
        assert isinstance(connector, EvidenceConnector)

    def test_dataset_connector_implements_protocol(self):
        """Test DatasetCatalogConnector implements protocol."""
        connector = DatasetCatalogConnector()
        assert isinstance(connector, EvidenceConnector)

    def test_kg_connector_implements_protocol(self):
        """Test KGNodeConnector implements protocol."""
        connector = KGNodeConnector()
        assert isinstance(connector, EvidenceConnector)

    def test_tool_connector_implements_protocol(self):
        """Test ToolCatalogConnector implements protocol."""
        connector = ToolCatalogConnector()
        assert isinstance(connector, EvidenceConnector)
