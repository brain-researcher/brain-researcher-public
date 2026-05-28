"""Tests for evidence base types."""

import pytest
from dataclasses import asdict

from brain_researcher.services.knowledge.evidence.base import (
    EvidenceBundle,
    EvidenceQuery,
    EvidenceResult,
    EvidenceSourceType,
    SyncEvidenceSourceAdapter,
)


class TestEvidenceSourceType:
    """Test EvidenceSourceType enum."""

    def test_all_types_defined(self):
        """Test all expected source types are defined."""
        assert EvidenceSourceType.KNOWLEDGE_GRAPH is not None
        assert EvidenceSourceType.LITERATURE is not None
        assert EvidenceSourceType.DATASET_CATALOG is not None
        assert EvidenceSourceType.TOOL_REGISTRY is not None
        assert EvidenceSourceType.NICLIP is not None
        assert EvidenceSourceType.NEUROSTORE is not None

    def test_type_values(self):
        """Test enum string values."""
        assert EvidenceSourceType.KNOWLEDGE_GRAPH.value == "kg"
        assert EvidenceSourceType.LITERATURE.value == "pubmed"
        assert EvidenceSourceType.DATASET_CATALOG.value == "datasets"
        assert EvidenceSourceType.TOOL_REGISTRY.value == "tools"
        assert EvidenceSourceType.NICLIP.value == "niclip"

    def test_enum_is_str(self):
        """Test that enum values are strings."""
        assert isinstance(EvidenceSourceType.KNOWLEDGE_GRAPH.value, str)
        # str(Enum) returns full name, but .value gives the string value
        assert EvidenceSourceType.KNOWLEDGE_GRAPH.value == "kg"


class TestEvidenceResult:
    """Test EvidenceResult dataclass."""

    def test_minimal_construction(self):
        """Test creating EvidenceResult with minimal fields."""
        result = EvidenceResult(
            source=EvidenceSourceType.KNOWLEDGE_GRAPH,
            id="test-123",
            title="Test Result",
            relevance_score=0.85,
            confidence=0.9,
        )
        assert result.source == EvidenceSourceType.KNOWLEDGE_GRAPH
        assert result.id == "test-123"
        assert result.title == "Test Result"
        assert result.relevance_score == 0.85
        assert result.confidence == 0.9
        assert result.payload == {}
        assert result.url is None
        assert result.summary is None

    def test_full_construction(self):
        """Test creating EvidenceResult with all fields."""
        result = EvidenceResult(
            source=EvidenceSourceType.LITERATURE,
            id="pmid:12345",
            title="A Research Paper",
            relevance_score=0.95,
            confidence=0.88,
            payload={"authors": ["Smith J", "Doe A"], "year": 2023},
            url="https://pubmed.ncbi.nlm.nih.gov/12345/",
            summary="This paper discusses brain imaging techniques.",
        )
        assert result.payload["authors"] == ["Smith J", "Doe A"]
        assert result.payload["year"] == 2023
        assert result.url == "https://pubmed.ncbi.nlm.nih.gov/12345/"
        assert "brain imaging" in result.summary

    def test_is_dataclass(self):
        """Test that EvidenceResult is a proper dataclass."""
        result = EvidenceResult(
            source=EvidenceSourceType.DATASET_CATALOG,
            id="ds001",
            title="Dataset 1",
            relevance_score=0.7,
            confidence=0.8,
        )
        d = asdict(result)
        assert isinstance(d, dict)
        assert d["id"] == "ds001"

    def test_relevance_score_bounds(self):
        """Test that relevance scores work within expected range."""
        # Valid scores
        for score in [0.0, 0.5, 1.0]:
            result = EvidenceResult(
                source=EvidenceSourceType.TOOL_REGISTRY,
                id="tool1",
                title="Tool",
                relevance_score=score,
                confidence=0.5,
            )
            assert result.relevance_score == score

    def test_to_dict(self):
        """Test to_dict method serializes correctly."""
        result = EvidenceResult(
            source=EvidenceSourceType.KNOWLEDGE_GRAPH,
            id="concept:123",
            title="Motor Cortex",
            relevance_score=0.9,
            confidence=0.85,
            payload={"node_type": "BrainRegion"},
            url="https://example.com/concept/123",
            summary="Primary motor cortex region",
        )
        d = result.to_dict()
        assert d["source"] == "kg"  # Uses enum value
        assert d["id"] == "concept:123"
        assert d["relevance_score"] == 0.9
        assert d["payload"]["node_type"] == "BrainRegion"


class TestEvidenceQuery:
    """Test EvidenceQuery dataclass."""

    def test_minimal_query(self):
        """Test creating query with just text."""
        query = EvidenceQuery(text="fMRI analysis")
        assert query.text == "fMRI analysis"
        assert query.limit == 10
        assert query.modality is None
        assert query.year_min is None
        assert query.year_max is None
        assert query.min_subjects is None
        assert query.entities == []
        assert query.coordinates is None
        assert query.filters == {}
        assert query.node_types is None

    def test_full_query(self):
        """Test creating query with all fields."""
        query = EvidenceQuery(
            text="resting state connectivity",
            limit=20,
            modality="fmri",
            year_min=2018,
            year_max=2023,
            min_subjects=50,
            node_types=["Concept", "BrainRegion"],
            entities=[{"type": "concept", "name": "resting state"}],
            filters={"species": "human"},
        )
        assert query.limit == 20
        assert query.modality == "fmri"
        assert query.year_min == 2018
        assert query.year_max == 2023
        assert query.min_subjects == 50
        assert query.node_types == ["Concept", "BrainRegion"]
        assert len(query.entities) == 1

    def test_query_with_coordinates(self):
        """Test query with spatial coordinates."""
        query = EvidenceQuery(
            text="motor area",
            coordinates=[(-38, -26, 56), (38, -26, 56)],
        )
        assert query.coordinates == [(-38, -26, 56), (38, -26, 56)]


class TestEvidenceBundle:
    """Test EvidenceBundle dataclass."""

    def test_empty_bundle(self):
        """Test creating empty bundle."""
        bundle = EvidenceBundle()
        assert bundle.concepts == []
        assert bundle.brain_regions == []
        assert bundle.datasets == []
        assert bundle.tools == []
        assert bundle.papers == []
        assert bundle.query_interpretation == {}
        assert bundle.metadata == {}

    def test_bundle_total_count(self):
        """Test total_count property."""
        bundle = EvidenceBundle(
            concepts=[
                EvidenceResult(
                    source=EvidenceSourceType.KNOWLEDGE_GRAPH,
                    id="c1",
                    title="Concept 1",
                    relevance_score=0.9,
                    confidence=0.8,
                )
            ],
            datasets=[
                EvidenceResult(
                    source=EvidenceSourceType.DATASET_CATALOG,
                    id="ds1",
                    title="Dataset 1",
                    relevance_score=0.85,
                    confidence=0.8,
                ),
                EvidenceResult(
                    source=EvidenceSourceType.DATASET_CATALOG,
                    id="ds2",
                    title="Dataset 2",
                    relevance_score=0.75,
                    confidence=0.7,
                ),
            ],
        )
        assert bundle.total_count == 3

    def test_bundle_is_empty(self):
        """Test is_empty method."""
        empty_bundle = EvidenceBundle()
        assert empty_bundle.is_empty() is True

        non_empty_bundle = EvidenceBundle(
            tools=[
                EvidenceResult(
                    source=EvidenceSourceType.TOOL_REGISTRY,
                    id="tool1",
                    title="Tool",
                    relevance_score=0.8,
                    confidence=0.9,
                )
            ]
        )
        assert non_empty_bundle.is_empty() is False

    def test_bundle_with_all_categories(self):
        """Test bundle with evidence in all categories."""
        bundle = EvidenceBundle(
            concepts=[
                EvidenceResult(
                    source=EvidenceSourceType.KNOWLEDGE_GRAPH,
                    id="concept:motor",
                    title="Motor Cortex",
                    relevance_score=0.95,
                    confidence=0.9,
                )
            ],
            brain_regions=[
                EvidenceResult(
                    source=EvidenceSourceType.KNOWLEDGE_GRAPH,
                    id="region:m1",
                    title="Primary Motor Cortex M1",
                    relevance_score=0.92,
                    confidence=0.88,
                )
            ],
            datasets=[
                EvidenceResult(
                    source=EvidenceSourceType.DATASET_CATALOG,
                    id="ds000001",
                    title="Motor Task Dataset",
                    relevance_score=0.85,
                    confidence=0.8,
                )
            ],
            tools=[
                EvidenceResult(
                    source=EvidenceSourceType.TOOL_REGISTRY,
                    id="fsl_feat",
                    title="FSL FEAT",
                    relevance_score=0.8,
                    confidence=0.85,
                )
            ],
            papers=[
                EvidenceResult(
                    source=EvidenceSourceType.LITERATURE,
                    id="pmid:12345",
                    title="Motor Control Paper",
                    relevance_score=0.88,
                    confidence=0.9,
                )
            ],
            query_interpretation={"intent": "analysis", "entities": ["motor"]},
            metadata={"search_time_ms": 150},
        )
        assert bundle.total_count == 5
        assert bundle.query_interpretation["intent"] == "analysis"
        assert bundle.metadata["search_time_ms"] == 150

    def test_bundle_to_dict(self):
        """Test to_dict serialization."""
        bundle = EvidenceBundle(
            concepts=[
                EvidenceResult(
                    source=EvidenceSourceType.KNOWLEDGE_GRAPH,
                    id="c1",
                    title="Concept",
                    relevance_score=0.9,
                    confidence=0.8,
                )
            ],
            metadata={"version": "1.0"},
        )
        d = bundle.to_dict()
        assert isinstance(d, dict)
        assert len(d["concepts"]) == 1
        assert d["concepts"][0]["source"] == "kg"
        assert d["metadata"]["version"] == "1.0"


class TestSyncEvidenceSourceAdapter:
    """Test SyncEvidenceSourceAdapter base class."""

    def test_adapter_requires_implementation(self):
        """Test that adapter methods must be implemented."""

        class IncompleteAdapter(SyncEvidenceSourceAdapter):
            @property
            def source_type(self):
                return EvidenceSourceType.TOOL_REGISTRY

            @property
            def source_id(self):
                return "test"

        adapter = IncompleteAdapter()

        # query_sync should raise NotImplementedError
        with pytest.raises(NotImplementedError):
            adapter.query_sync(EvidenceQuery(text="test"))

    def test_adapter_sync_wrapper(self):
        """Test that sync query implementation works."""

        class TestAdapter(SyncEvidenceSourceAdapter):
            @property
            def source_type(self):
                return EvidenceSourceType.TOOL_REGISTRY

            @property
            def source_id(self):
                return "test"

            def query_sync(self, query):
                return [
                    EvidenceResult(
                        source=self.source_type,
                        id="test-1",
                        title="Test Result",
                        relevance_score=0.9,
                        confidence=0.85,
                    )
                ]

        adapter = TestAdapter()

        # Sync method works directly
        results = adapter.query_sync(EvidenceQuery(text="test"))
        assert len(results) == 1
        assert results[0].id == "test-1"

    @pytest.mark.asyncio
    async def test_adapter_async_query(self):
        """Test async query method of adapter."""

        class TestAdapter(SyncEvidenceSourceAdapter):
            @property
            def source_type(self):
                return EvidenceSourceType.TOOL_REGISTRY

            @property
            def source_id(self):
                return "test"

            def query_sync(self, query):
                return [
                    EvidenceResult(
                        source=self.source_type,
                        id="async-test",
                        title="Async Test Result",
                        relevance_score=0.88,
                        confidence=0.9,
                    )
                ]

        adapter = TestAdapter()
        results = await adapter.query(EvidenceQuery(text="test"))
        assert len(results) == 1
        assert results[0].id == "async-test"

    @pytest.mark.asyncio
    async def test_adapter_async_health_check(self):
        """Test async health check method of adapter."""

        class TestAdapter(SyncEvidenceSourceAdapter):
            @property
            def source_type(self):
                return EvidenceSourceType.TOOL_REGISTRY

            @property
            def source_id(self):
                return "test"

            def health_check_sync(self):
                return True

        adapter = TestAdapter()
        result = await adapter.health_check()
        assert result is True

    def test_default_health_check_sync(self):
        """Test that default health_check_sync returns True."""

        class MinimalAdapter(SyncEvidenceSourceAdapter):
            @property
            def source_type(self):
                return EvidenceSourceType.TOOL_REGISTRY

            @property
            def source_id(self):
                return "test"

        adapter = MinimalAdapter()
        assert adapter.health_check_sync() is True
