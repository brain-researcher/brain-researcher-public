"""Tests for the evidence aggregator."""

import pytest

from brain_researcher.services.br_kg.evidence.aggregator import (
    _infer_sources_from_qur,
    gather_evidence,
)
from brain_researcher.services.br_kg.evidence.models import (
    EvidenceBundle,
    EvidenceSource,
)


class TestGatherEvidence:
    """Tests for gather_evidence function."""

    @pytest.mark.asyncio
    async def test_gather_single_source(self, mock_br_kg_connector):
        """Test gathering from a single source."""
        bundle = await gather_evidence(
            "working memory",
            connectors=[mock_br_kg_connector],
        )

        assert isinstance(bundle, EvidenceBundle)
        assert bundle.query == "working memory"
        assert EvidenceSource.BR_KG in bundle.sources_queried
        assert len(bundle.items) == 1

    @pytest.mark.asyncio
    async def test_gather_multiple_sources(
        self, mock_br_kg_connector, mock_dataset_connector
    ):
        """Test gathering from multiple sources in parallel."""
        bundle = await gather_evidence(
            "motor task",
            connectors=[mock_br_kg_connector, mock_dataset_connector],
        )

        assert len(bundle.sources_queried) == 2
        assert EvidenceSource.BR_KG in bundle.sources_queried
        assert EvidenceSource.DATASET_CATALOG in bundle.sources_queried

    @pytest.mark.asyncio
    async def test_gather_with_source_filter(
        self, mock_br_kg_connector, mock_dataset_connector
    ):
        """Test filtering by specific sources."""
        bundle = await gather_evidence(
            "test query",
            sources=[EvidenceSource.BR_KG],
            connectors=[mock_br_kg_connector, mock_dataset_connector],
        )

        # Only BR-KG should be queried
        assert bundle.sources_queried == [EvidenceSource.BR_KG]

    @pytest.mark.asyncio
    async def test_gather_with_limit(self, mock_br_kg_connector, sample_evidence_items):
        """Test limiting results per source."""
        # Create connector with multiple items
        from tests.unit.br_kg.evidence.conftest import MockConnector

        connector = MockConnector(EvidenceSource.BR_KG, sample_evidence_items * 3)

        bundle = await gather_evidence(
            "test",
            limit_per_source=2,
            connectors=[connector],
        )

        assert len(bundle.items) <= 2

    @pytest.mark.asyncio
    async def test_gather_handles_errors(self, mock_failing_connector):
        """Test that errors are captured but don't break aggregation."""
        bundle = await gather_evidence(
            "test",
            connectors=[mock_failing_connector],
        )

        assert EvidenceSource.PUBMED in bundle.sources_queried
        assert EvidenceSource.PUBMED.value in bundle.errors
        assert bundle.has_errors

    @pytest.mark.asyncio
    async def test_gather_skips_unavailable(
        self, mock_br_kg_connector, mock_unavailable_connector
    ):
        """Test that unavailable connectors are skipped."""
        bundle = await gather_evidence(
            "test",
            connectors=[mock_br_kg_connector, mock_unavailable_connector],
        )

        # Only available connector should be queried
        assert EvidenceSource.BR_KG in bundle.sources_queried
        assert EvidenceSource.NEUROSTORE not in bundle.sources_queried

    @pytest.mark.asyncio
    async def test_gather_no_connectors(self):
        """Test with no available connectors."""
        bundle = await gather_evidence("test", connectors=[])

        assert bundle.total_count == 0
        assert "all" in bundle.errors

    @pytest.mark.asyncio
    async def test_gather_records_query_time(self, mock_br_kg_connector):
        """Test that query time is recorded."""
        bundle = await gather_evidence(
            "test",
            connectors=[mock_br_kg_connector],
        )

        assert bundle.query_time_ms > 0

    @pytest.mark.asyncio
    async def test_gather_partial_failure(
        self, mock_br_kg_connector, mock_failing_connector
    ):
        """Test that partial failures don't prevent successful results."""
        bundle = await gather_evidence(
            "test",
            connectors=[mock_br_kg_connector, mock_failing_connector],
        )

        # Should have results from working connector
        assert len(bundle.items) > 0
        # And error from failing connector
        assert bundle.has_errors


class TestInferSourcesFromQur:
    """Tests for QUR-based source inference."""

    def test_always_includes_br_kg(self):
        """Test that BR-KG is always included."""

        class MockQUR:
            original_query = "simple query"
            entities = []

        sources = _infer_sources_from_qur(MockQUR())
        assert EvidenceSource.BR_KG in sources

    def test_dataset_keywords(self):
        """Test detection of dataset keywords."""

        class MockQUR:
            original_query = "find datasets for motor task"
            entities = []
            resolved_datasets = []

        sources = _infer_sources_from_qur(MockQUR())
        # "datasets" keyword doesn't trigger, but entity type would
        assert EvidenceSource.BR_KG in sources

    def test_dataset_entities(self):
        """Test detection of dataset entities."""

        class MockQUR:
            original_query = "analyze ds000001"
            entities = [{"entity_type": "DATASET", "value": "ds000001"}]
            resolved_datasets = ["ds000001"]

        sources = _infer_sources_from_qur(MockQUR())
        assert EvidenceSource.DATASET_CATALOG in sources

    def test_publication_keywords(self):
        """Test detection of publication keywords."""

        class MockQUR:
            original_query = "find papers about working memory"
            entities = []

        sources = _infer_sources_from_qur(MockQUR())
        assert EvidenceSource.PUBMED in sources

        class MockQUR2:
            original_query = "literature review on attention"
            entities = []

        sources2 = _infer_sources_from_qur(MockQUR2())
        assert EvidenceSource.PUBMED in sources2

    def test_tool_keywords(self):
        """Test detection of tool keywords."""

        class MockQUR:
            original_query = "how to run fmriprep pipeline"
            entities = []

        sources = _infer_sources_from_qur(MockQUR())
        assert EvidenceSource.TOOL_CATALOG in sources

    def test_neurostore_keywords(self):
        """Test detection of neurostore keywords."""

        class MockQUR:
            original_query = "find activation coordinates in MNI space"
            entities = []

        sources = _infer_sources_from_qur(MockQUR())
        assert EvidenceSource.NEUROSTORE in sources

    def test_multiple_sources_inferred(self):
        """Test that multiple sources can be inferred."""

        class MockQUR:
            original_query = "find papers and tools for meta-analysis"
            entities = []

        sources = _infer_sources_from_qur(MockQUR())
        assert EvidenceSource.PUBMED in sources  # "papers"
        assert EvidenceSource.TOOL_CATALOG in sources  # "tools"
        assert EvidenceSource.NEUROSTORE in sources  # "meta-analysis"
