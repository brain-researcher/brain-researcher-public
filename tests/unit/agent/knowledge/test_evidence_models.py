"""Unit tests for evidence_models.py."""

import pytest

from brain_researcher.services.agent.knowledge.evidence_models import (
    DecisionType,
    EvidenceBundle,
    EvidenceItem,
    EvidenceSourceType,
    KnowledgePlan,
)


class TestEvidenceItem:
    """Tests for EvidenceItem dataclass."""

    def test_basic_creation(self):
        """Test creating an evidence item."""
        item = EvidenceItem(
            source_type=EvidenceSourceType.PUBMED,
            source_id="pmid:12345",
            label="Test Paper Title",
            relevance_score=0.85,
            url="https://pubmed.ncbi.nlm.nih.gov/12345",
        )
        assert item.source_type == EvidenceSourceType.PUBMED
        assert item.source_id == "pmid:12345"
        assert item.label == "Test Paper Title"
        assert item.relevance_score == 0.85
        assert item.url == "https://pubmed.ncbi.nlm.nih.gov/12345"

    def test_relevance_score_clamping(self):
        """Test that relevance scores are clamped to [0, 1]."""
        item_high = EvidenceItem(
            source_type=EvidenceSourceType.PUBMED,
            source_id="test",
            label="Test",
            relevance_score=1.5,
        )
        assert item_high.relevance_score == 1.0

        item_low = EvidenceItem(
            source_type=EvidenceSourceType.PUBMED,
            source_id="test",
            label="Test",
            relevance_score=-0.5,
        )
        assert item_low.relevance_score == 0.0

    def test_to_citation_with_url(self):
        """Test citation formatting with URL."""
        item = EvidenceItem(
            source_type=EvidenceSourceType.PUBMED,
            source_id="pmid:12345",
            label="Test",
            url="https://example.com",
        )
        assert item.to_citation(1) == "[1](https://example.com)"

    def test_to_citation_without_url(self):
        """Test citation formatting without URL."""
        item = EvidenceItem(
            source_type=EvidenceSourceType.DATASET_CATALOG,
            source_id="ds001",
            label="Test Dataset",
        )
        assert item.to_citation(3) == "[3]"

    def test_to_dict(self):
        """Test dictionary conversion."""
        item = EvidenceItem(
            source_type=EvidenceSourceType.PUBMED,
            source_id="pmid:12345",
            label="Test",
            relevance_score=0.9,
            metadata={"year": 2024},
        )
        d = item.to_dict()
        assert d["source_type"] == "pubmed"
        assert d["source_id"] == "pmid:12345"
        assert d["relevance_score"] == 0.9
        assert d["metadata"]["year"] == 2024


class TestEvidenceBundle:
    """Tests for EvidenceBundle dataclass."""

    def test_basic_creation(self):
        """Test creating an empty bundle."""
        bundle = EvidenceBundle(query="motor cortex fMRI")
        assert bundle.query == "motor cortex fMRI"
        assert len(bundle.items) == 0
        assert bundle.total_literature_count == 0

    def test_add_item_literature(self):
        """Test adding literature items updates count."""
        bundle = EvidenceBundle(query="test")
        bundle.add_item(
            EvidenceItem(
                source_type=EvidenceSourceType.PUBMED,
                source_id="pmid:1",
                label="Paper 1",
            )
        )
        bundle.add_item(
            EvidenceItem(
                source_type=EvidenceSourceType.NEUROSTORE,
                source_id="ns:1",
                label="NeuroStore Study 1",
            )
        )
        assert bundle.total_literature_count == 2
        assert len(bundle.items) == 2

    def test_add_item_datasets(self):
        """Test adding dataset items updates count."""
        bundle = EvidenceBundle(query="test")
        bundle.add_item(
            EvidenceItem(
                source_type=EvidenceSourceType.DATASET_CATALOG,
                source_id="ds001",
                label="Dataset 1",
            )
        )
        assert bundle.total_dataset_count == 1
        assert bundle.total_literature_count == 0

    def test_add_item_tools(self):
        """Test adding tool items updates count."""
        bundle = EvidenceBundle(query="test")
        bundle.add_item(
            EvidenceItem(
                source_type=EvidenceSourceType.TOOL_CATALOG,
                source_id="fmriprep",
                label="fMRIPrep",
            )
        )
        assert bundle.total_tool_count == 1

    def test_get_items_by_source(self):
        """Test filtering items by source type."""
        bundle = EvidenceBundle(query="test")
        bundle.add_item(
            EvidenceItem(source_type=EvidenceSourceType.PUBMED, source_id="1", label="Paper")
        )
        bundle.add_item(
            EvidenceItem(source_type=EvidenceSourceType.DATASET_CATALOG, source_id="ds1", label="Dataset")
        )
        bundle.add_item(
            EvidenceItem(source_type=EvidenceSourceType.PUBMED, source_id="2", label="Paper 2")
        )

        papers = bundle.get_items_by_source(EvidenceSourceType.PUBMED)
        assert len(papers) == 2

        datasets = bundle.get_items_by_source(EvidenceSourceType.DATASET_CATALOG)
        assert len(datasets) == 1

    def test_get_top_items(self):
        """Test getting top items by relevance."""
        bundle = EvidenceBundle(query="test")
        bundle.add_item(
            EvidenceItem(source_type=EvidenceSourceType.PUBMED, source_id="1", label="Low", relevance_score=0.3)
        )
        bundle.add_item(
            EvidenceItem(source_type=EvidenceSourceType.PUBMED, source_id="2", label="High", relevance_score=0.9)
        )
        bundle.add_item(
            EvidenceItem(source_type=EvidenceSourceType.PUBMED, source_id="3", label="Medium", relevance_score=0.6)
        )

        top = bundle.get_top_items(2)
        assert len(top) == 2
        assert top[0].label == "High"
        assert top[1].label == "Medium"

    def test_compute_confidence(self):
        """Test confidence computation."""
        bundle = EvidenceBundle(query="test")
        # Add some literature
        for i in range(5):
            bundle.add_item(
                EvidenceItem(source_type=EvidenceSourceType.PUBMED, source_id=f"p{i}", label=f"Paper {i}")
            )
        # Add some datasets
        bundle.add_item(
            EvidenceItem(source_type=EvidenceSourceType.DATASET_CATALOG, source_id="ds1", label="Dataset")
        )
        bundle.aggregate_niclip_score = 0.7

        confidence = bundle.compute_confidence()
        assert 0.0 < confidence < 1.0
        assert bundle.confidence == confidence

    def test_format_citations(self):
        """Test citation formatting."""
        bundle = EvidenceBundle(query="test")
        bundle.add_item(
            EvidenceItem(
                source_type=EvidenceSourceType.PUBMED,
                source_id="pmid:1",
                label="Paper One",
                url="https://pubmed.ncbi.nlm.nih.gov/1",
                relevance_score=0.9,
            )
        )
        bundle.add_item(
            EvidenceItem(
                source_type=EvidenceSourceType.DATASET_CATALOG,
                source_id="ds001",
                label="Dataset One",
                url="https://openneuro.org/ds001",
                relevance_score=0.8,
            )
        )

        citations = bundle.format_citations(max_citations=5)
        assert len(citations) == 2
        assert citations[0]["ref"] == "[1]"
        assert citations[0]["label"] == "Paper One"
        assert citations[0]["url"] == "https://pubmed.ncbi.nlm.nih.gov/1"

    def test_summary(self):
        """Test bundle summary."""
        bundle = EvidenceBundle(query="motor cortex")
        bundle.add_item(
            EvidenceItem(source_type=EvidenceSourceType.PUBMED, source_id="1", label="Paper")
        )
        bundle.confidence = 0.75

        summary = bundle.summary()
        assert summary["query"] == "motor cortex"
        assert summary["total_items"] == 1
        assert summary["literature_count"] == 1
        assert summary["confidence"] == 0.75


class TestKnowledgePlan:
    """Tests for KnowledgePlan dataclass."""

    def test_explanation_plan(self):
        """Test creating an explanation plan."""
        plan = KnowledgePlan(
            decision_type=DecisionType.EXPLANATION,
            query="What is the motor cortex?",
            reasoning="User is asking a conceptual question",
            explanation="The motor cortex is a region of the brain...",
            confidence=0.9,
        )
        assert plan.is_explanation()
        assert not plan.is_dataset_selection()
        assert plan.explanation is not None

    def test_dataset_selection_plan(self):
        """Test creating a dataset selection plan."""
        plan = KnowledgePlan(
            decision_type=DecisionType.DATASET_SELECTION,
            query="Find fMRI datasets with motor tasks",
            reasoning="User wants to find datasets",
            recommended_datasets=["ds001", "ds002", "ds003"],
            dataset_scores={"ds001": 0.95, "ds002": 0.8, "ds003": 0.7},
            confidence=0.85,
        )
        assert plan.is_dataset_selection()
        assert len(plan.recommended_datasets) == 3

    def test_pipeline_recommendation_plan(self):
        """Test creating a pipeline recommendation plan."""
        plan = KnowledgePlan(
            decision_type=DecisionType.PIPELINE_RECOMMENDATION,
            query="How do I preprocess fMRI data?",
            reasoning="User needs analysis guidance",
            recommended_tools=["fmriprep", "nilearn"],
            tool_sequence=["fmriprep", "nilearn.glm"],
            confidence=0.8,
        )
        assert plan.is_pipeline_recommendation()
        assert "fmriprep" in plan.recommended_tools

    def test_get_top_datasets(self):
        """Test getting top datasets by score."""
        plan = KnowledgePlan(
            decision_type=DecisionType.DATASET_SELECTION,
            query="test",
            dataset_scores={"ds001": 0.9, "ds002": 0.95, "ds003": 0.7},
        )
        top = plan.get_top_datasets(2)
        assert len(top) == 2
        assert top[0] == "ds002"  # Highest score
        assert top[1] == "ds001"

    def test_confidence_clamping(self):
        """Test that confidence is clamped to [0, 1]."""
        plan = KnowledgePlan(
            decision_type=DecisionType.EXPLANATION,
            query="test",
            confidence=1.5,
        )
        assert plan.confidence == 1.0

    def test_to_dict(self):
        """Test dictionary conversion."""
        plan = KnowledgePlan(
            decision_type=DecisionType.EXPLANATION,
            query="test",
            explanation="Test explanation",
            citations=[{"ref": "[1]", "label": "Paper", "url": "http://example.com"}],
        )
        d = plan.to_dict()
        assert d["decision_type"] == "explanation"
        assert d["explanation"] == "Test explanation"
        assert len(d["citations"]) == 1


class TestDecisionType:
    """Tests for DecisionType enum."""

    def test_enum_values(self):
        """Test enum string values."""
        assert DecisionType.EXPLANATION.value == "explanation"
        assert DecisionType.DATASET_SELECTION.value == "dataset_selection"
        assert DecisionType.PIPELINE_RECOMMENDATION.value == "pipeline_recommendation"


class TestEvidenceSourceType:
    """Tests for EvidenceSourceType enum."""

    def test_enum_values(self):
        """Test enum string values."""
        assert EvidenceSourceType.PUBMED.value == "pubmed"
        assert EvidenceSourceType.NEUROSTORE.value == "neurostore"
        assert EvidenceSourceType.DATASET_CATALOG.value == "dataset_catalog"
        assert EvidenceSourceType.TOOL_CATALOG.value == "tool_catalog"
        assert EvidenceSourceType.KG_GRAPH.value == "kg_graph"
        assert EvidenceSourceType.NICLIP.value == "niclip"
