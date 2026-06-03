"""Tests for evidence models."""

import pytest

from brain_researcher.services.br_kg.evidence.models import (
    EvidenceBundle,
    EvidenceItem,
    EvidenceSource,
    EvidenceType,
)


class TestEvidenceItem:
    """Tests for EvidenceItem model."""

    def test_create_basic_item(self):
        """Test creating a basic evidence item."""
        item = EvidenceItem(
            id="test-1",
            source=EvidenceSource.BR_KG,
            item_type=EvidenceType.CONCEPT,
            title="Test Concept",
        )
        assert item.id == "test-1"
        assert item.source == EvidenceSource.BR_KG
        assert item.item_type == EvidenceType.CONCEPT
        assert item.title == "Test Concept"
        assert item.score == 1.0  # default
        assert item.metadata == {}  # default

    def test_create_full_item(self, sample_evidence_item):
        """Test creating a fully specified evidence item."""
        item = sample_evidence_item
        assert item.id == "test-123"
        assert item.description is not None
        assert item.score == 0.95
        assert "node_type" in item.metadata

    def test_item_is_immutable(self, sample_evidence_item):
        """Test that evidence items are immutable (frozen)."""
        with pytest.raises(Exception):  # ValidationError or similar
            sample_evidence_item.title = "New Title"

    def test_to_dict(self, sample_evidence_item):
        """Test serialization to dictionary."""
        data = sample_evidence_item.to_dict()
        assert data["id"] == "test-123"
        assert data["source"] == "br_kg"
        assert data["item_type"] == "concept"
        assert isinstance(data["fetched_at"], str)  # ISO format

    def test_score_validation(self):
        """Test score must be between 0 and 1."""
        with pytest.raises(ValueError):
            EvidenceItem(
                id="test",
                source=EvidenceSource.BR_KG,
                item_type=EvidenceType.CONCEPT,
                title="Test",
                score=1.5,  # Invalid
            )

        with pytest.raises(ValueError):
            EvidenceItem(
                id="test",
                source=EvidenceSource.BR_KG,
                item_type=EvidenceType.CONCEPT,
                title="Test",
                score=-0.1,  # Invalid
            )


class TestEvidenceBundle:
    """Tests for EvidenceBundle model."""

    def test_create_empty_bundle(self):
        """Test creating an empty bundle."""
        bundle = EvidenceBundle(query="test query")
        assert bundle.query == "test query"
        assert bundle.items == []
        assert bundle.sources_queried == []
        assert bundle.errors == {}
        assert bundle.total_count == 0

    def test_create_bundle_with_items(self, sample_evidence_items):
        """Test creating a bundle with items."""
        bundle = EvidenceBundle(
            query="working memory",
            items=sample_evidence_items,
            sources_queried=[
                EvidenceSource.BR_KG,
                EvidenceSource.DATASET_CATALOG,
                EvidenceSource.PUBMED,
            ],
        )
        assert bundle.total_count == 3
        assert len(bundle.sources_queried) == 3

    def test_by_source(self, sample_evidence_items):
        """Test grouping items by source."""
        bundle = EvidenceBundle(query="test", items=sample_evidence_items)
        by_source = bundle.by_source

        assert EvidenceSource.BR_KG in by_source
        assert EvidenceSource.DATASET_CATALOG in by_source
        assert EvidenceSource.PUBMED in by_source
        assert len(by_source[EvidenceSource.BR_KG]) == 1

    def test_by_type(self, sample_evidence_items):
        """Test grouping items by type."""
        bundle = EvidenceBundle(query="test", items=sample_evidence_items)
        by_type = bundle.by_type

        assert EvidenceType.CONCEPT in by_type
        assert EvidenceType.DATASET in by_type
        assert EvidenceType.PUBLICATION in by_type

    def test_top_items(self, sample_evidence_items):
        """Test getting top items by score."""
        bundle = EvidenceBundle(query="test", items=sample_evidence_items)
        top = bundle.top_items(2)

        assert len(top) == 2
        assert top[0].score >= top[1].score  # Sorted by score descending

    def test_filter_by_source(self, sample_evidence_items):
        """Test filtering items by source."""
        bundle = EvidenceBundle(query="test", items=sample_evidence_items)
        filtered = bundle.filter_by_source(EvidenceSource.BR_KG)

        assert len(filtered) == 1
        assert all(i.source == EvidenceSource.BR_KG for i in filtered)

    def test_filter_by_type(self, sample_evidence_items):
        """Test filtering items by type."""
        bundle = EvidenceBundle(query="test", items=sample_evidence_items)
        filtered = bundle.filter_by_type(EvidenceType.DATASET)

        assert len(filtered) == 1
        assert all(i.item_type == EvidenceType.DATASET for i in filtered)

    def test_has_errors(self):
        """Test error detection."""
        bundle_ok = EvidenceBundle(query="test")
        assert not bundle_ok.has_errors

        bundle_err = EvidenceBundle(query="test", errors={"pubmed": "API down"})
        assert bundle_err.has_errors

    def test_summary(self, sample_evidence_items):
        """Test summary generation."""
        bundle = EvidenceBundle(
            query="test",
            items=sample_evidence_items,
            sources_queried=[EvidenceSource.BR_KG, EvidenceSource.DATASET_CATALOG],
            query_time_ms=150.5,
        )
        summary = bundle.summary()

        assert summary["query"] == "test"
        assert summary["total_items"] == 3
        assert "br_kg" in summary["sources_queried"]
        assert summary["query_time_ms"] == 150.5


class TestEvidenceSource:
    """Tests for EvidenceSource enum."""

    def test_all_sources(self):
        """Test all expected sources are defined."""
        sources = list(EvidenceSource)
        assert EvidenceSource.PUBMED in sources
        assert EvidenceSource.NEUROSTORE in sources
        assert EvidenceSource.DATASET_CATALOG in sources
        assert EvidenceSource.TOOL_CATALOG in sources
        assert EvidenceSource.BR_KG in sources

    def test_source_values(self):
        """Test source string values."""
        assert EvidenceSource.PUBMED.value == "pubmed"
        assert EvidenceSource.BR_KG.value == "br_kg"


class TestEvidenceType:
    """Tests for EvidenceType enum."""

    def test_all_types(self):
        """Test all expected types are defined."""
        types = list(EvidenceType)
        assert EvidenceType.PUBLICATION in types
        assert EvidenceType.DATASET in types
        assert EvidenceType.TOOL in types
        assert EvidenceType.CONCEPT in types
        assert EvidenceType.BRAIN_REGION in types
        assert EvidenceType.STATISTICAL_MAP in types
