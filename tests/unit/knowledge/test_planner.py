"""Tests for knowledge planner."""

import pytest
from unittest.mock import MagicMock, patch, AsyncMock
from dataclasses import asdict

from brain_researcher.services.knowledge.evidence.base import (
    EvidenceBundle,
    EvidenceQuery,
    EvidenceResult,
    EvidenceSourceType,
)
from brain_researcher.services.knowledge.planner import (
    DecisionType,
    EvidenceAggregator,
    KnowledgePlan,
    KnowledgePlanner,
    create_aggregator,
    create_planner,
)


class TestDecisionType:
    """Test DecisionType enum."""

    def test_all_types_defined(self):
        """Test all expected decision types are defined."""
        assert DecisionType.EXPLANATION is not None
        assert DecisionType.DATASET_SELECTION is not None
        assert DecisionType.PIPELINE_RECOMMENDATION is not None
        assert DecisionType.CONCEPT_LOOKUP is not None
        assert DecisionType.UNKNOWN is not None

    def test_type_values(self):
        """Test enum string values."""
        assert DecisionType.EXPLANATION.value == "explanation"
        assert DecisionType.DATASET_SELECTION.value == "dataset_selection"
        assert DecisionType.PIPELINE_RECOMMENDATION.value == "pipeline_recommendation"


class TestKnowledgePlan:
    """Test KnowledgePlan dataclass."""

    def test_minimal_plan(self):
        """Test creating a minimal plan."""
        plan = KnowledgePlan(
            decision_type=DecisionType.EXPLANATION,
            query="What is the motor cortex?",
            reasoning="Test reasoning",
            confidence=0.85,
        )
        assert plan.decision_type == DecisionType.EXPLANATION
        assert plan.query == "What is the motor cortex?"
        assert plan.confidence == 0.85
        assert plan.explanation is None
        assert plan.recommended_datasets == []
        assert plan.citations == []

    def test_full_plan(self):
        """Test creating a plan with all fields."""
        plan = KnowledgePlan(
            decision_type=DecisionType.DATASET_SELECTION,
            query="Find motor task datasets",
            reasoning="Selected based on task type",
            confidence=0.9,
            recommended_datasets=["ds000001", "ds000002"],
            dataset_scores={"ds000001": 0.95, "ds000002": 0.85},
            citations=[{"ref": "[1]", "title": "Motor Task Paper"}],
        )
        assert plan.recommended_datasets == ["ds000001", "ds000002"]
        assert plan.dataset_scores["ds000001"] == 0.95

    def test_to_dict(self):
        """Test to_dict serialization."""
        plan = KnowledgePlan(
            decision_type=DecisionType.PIPELINE_RECOMMENDATION,
            query="How to preprocess fMRI?",
            reasoning="Standard fMRI pipeline",
            confidence=0.8,
            recommended_tools=["fmriprep", "nilearn"],
            tool_sequence=["fmriprep", "nilearn"],
        )
        d = plan.to_dict()
        assert d["decision_type"] == "pipeline_recommendation"
        assert d["recommended_tools"] == ["fmriprep", "nilearn"]


class TestEvidenceAggregator:
    """Test EvidenceAggregator class."""

    def setup_method(self):
        """Set up test fixtures."""
        self.aggregator = EvidenceAggregator(timeout=10.0, limit_per_source=5)

    @pytest.mark.asyncio
    async def test_gather_no_sources(self):
        """Test gather with no available sources."""
        aggregator = EvidenceAggregator(sources=[])
        bundle = await aggregator.gather("test query")

        assert bundle is not None
        assert "error" in bundle.metadata or "sources_queried" in bundle.metadata

    @pytest.mark.asyncio
    async def test_gather_with_mock_source(self):
        """Test gather with a mock source."""
        # Create mock source
        mock_source = MagicMock()
        mock_source.source_type = EvidenceSourceType.KNOWLEDGE_GRAPH
        mock_source.health_check = AsyncMock(return_value=True)
        mock_source.query = AsyncMock(
            return_value=[
                EvidenceResult(
                    source=EvidenceSourceType.KNOWLEDGE_GRAPH,
                    id="concept:motor",
                    title="Motor Cortex",
                    relevance_score=0.9,
                    confidence=0.85,
                )
            ]
        )

        aggregator = EvidenceAggregator(sources=[mock_source])
        bundle = await aggregator.gather("motor cortex")

        assert bundle is not None
        assert len(bundle.concepts) + len(bundle.brain_regions) > 0

    @pytest.mark.asyncio
    async def test_gather_handles_source_error(self):
        """Test gather handles source errors gracefully."""
        mock_source = MagicMock()
        mock_source.source_type = EvidenceSourceType.LITERATURE
        mock_source.health_check = AsyncMock(return_value=True)
        mock_source.query = AsyncMock(side_effect=Exception("API error"))

        aggregator = EvidenceAggregator(sources=[mock_source])
        bundle = await aggregator.gather("test query")

        # Should not raise, should return bundle with error info
        assert bundle is not None
        assert "pubmed" in bundle.metadata.get("errors", {})

    @pytest.mark.asyncio
    async def test_gather_filters_by_source_type(self):
        """Test gather filters by source type."""
        mock_kg = MagicMock()
        mock_kg.source_type = EvidenceSourceType.KNOWLEDGE_GRAPH
        mock_kg.health_check = AsyncMock(return_value=True)
        mock_kg.query = AsyncMock(return_value=[])

        mock_lit = MagicMock()
        mock_lit.source_type = EvidenceSourceType.LITERATURE
        mock_lit.health_check = AsyncMock(return_value=True)
        mock_lit.query = AsyncMock(return_value=[])

        aggregator = EvidenceAggregator(sources=[mock_kg, mock_lit])
        bundle = await aggregator.gather(
            "test",
            source_types=[EvidenceSourceType.KNOWLEDGE_GRAPH],
        )

        # Should only query KG
        mock_kg.query.assert_called_once()
        mock_lit.query.assert_not_called()

    @pytest.mark.asyncio
    async def test_gather_deduplicates_results(self):
        """Test that gather deduplicates by ID."""
        mock_source1 = MagicMock()
        mock_source1.source_type = EvidenceSourceType.KNOWLEDGE_GRAPH
        mock_source1.health_check = AsyncMock(return_value=True)
        mock_source1.query = AsyncMock(
            return_value=[
                EvidenceResult(
                    source=EvidenceSourceType.KNOWLEDGE_GRAPH,
                    id="concept:motor",
                    title="Motor Cortex",
                    relevance_score=0.9,
                    confidence=0.85,
                )
            ]
        )

        mock_source2 = MagicMock()
        mock_source2.source_type = EvidenceSourceType.NICLIP
        mock_source2.health_check = AsyncMock(return_value=True)
        mock_source2.query = AsyncMock(
            return_value=[
                EvidenceResult(
                    source=EvidenceSourceType.NICLIP,
                    id="concept:motor",  # Same ID
                    title="Motor Cortex",
                    relevance_score=0.85,
                    confidence=0.75,
                )
            ]
        )

        aggregator = EvidenceAggregator(sources=[mock_source1, mock_source2])
        bundle = await aggregator.gather("motor")

        # Should only have one item with this ID
        all_ids = (
            [c.id for c in bundle.concepts]
            + [r.id for r in bundle.brain_regions]
        )
        assert all_ids.count("concept:motor") == 1

    def test_add_to_bundle_categorization(self):
        """Test that results are added to correct bundle categories."""
        aggregator = EvidenceAggregator()
        bundle = EvidenceBundle()

        # Brain region
        region = EvidenceResult(
            source=EvidenceSourceType.KNOWLEDGE_GRAPH,
            id="region:m1",
            title="Primary Motor Cortex",
            relevance_score=0.9,
            confidence=0.85,
            payload={"is_brain_region": True},
        )
        aggregator._add_to_bundle(bundle, region)
        assert len(bundle.brain_regions) == 1

        # Concept
        concept = EvidenceResult(
            source=EvidenceSourceType.KNOWLEDGE_GRAPH,
            id="concept:learning",
            title="Motor Learning",
            relevance_score=0.85,
            confidence=0.8,
            payload={},
        )
        aggregator._add_to_bundle(bundle, concept)
        assert len(bundle.concepts) == 1

        # Dataset
        dataset = EvidenceResult(
            source=EvidenceSourceType.DATASET_CATALOG,
            id="ds000001",
            title="Motor Task Dataset",
            relevance_score=0.8,
            confidence=0.75,
        )
        aggregator._add_to_bundle(bundle, dataset)
        assert len(bundle.datasets) == 1

        # Tool
        tool = EvidenceResult(
            source=EvidenceSourceType.TOOL_REGISTRY,
            id="fsl_bet",
            title="FSL BET",
            relevance_score=0.9,
            confidence=0.85,
        )
        aggregator._add_to_bundle(bundle, tool)
        assert len(bundle.tools) == 1

        # Paper
        paper = EvidenceResult(
            source=EvidenceSourceType.LITERATURE,
            id="pmid:12345",
            title="Motor Cortex Paper",
            relevance_score=0.88,
            confidence=0.9,
        )
        aggregator._add_to_bundle(bundle, paper)
        assert len(bundle.papers) == 1


class TestKnowledgePlanner:
    """Test KnowledgePlanner class."""

    def setup_method(self):
        """Set up test fixtures."""
        # Create mock aggregator
        self.mock_aggregator = MagicMock()
        self.mock_aggregator.gather = AsyncMock(
            return_value=EvidenceBundle(
                concepts=[
                    EvidenceResult(
                        source=EvidenceSourceType.KNOWLEDGE_GRAPH,
                        id="concept:motor",
                        title="Motor Cortex",
                        relevance_score=0.9,
                        confidence=0.85,
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
                        id="fmriprep",
                        title="fMRIPrep",
                        relevance_score=0.9,
                        confidence=0.85,
                    )
                ],
            )
        )
        self.planner = KnowledgePlanner(aggregator=self.mock_aggregator)

    def test_planner_initialization(self):
        """Test planner initialization."""
        planner = KnowledgePlanner()
        assert planner._aggregator is not None
        assert planner._max_citations == 10

    def test_planner_with_custom_config(self):
        """Test planner with custom configuration."""
        planner = KnowledgePlanner(
            model_hint="gpt-4",
            max_citations=20,
        )
        assert planner._model_hint == "gpt-4"
        assert planner._max_citations == 20

    def test_classify_intent_heuristic_dataset(self):
        """Test heuristic intent classification for datasets."""
        result = self.planner._classify_intent_heuristic("Find motor task dataset")
        assert result == DecisionType.DATASET_SELECTION

    def test_classify_intent_heuristic_pipeline(self):
        """Test heuristic intent classification for pipelines."""
        result = self.planner._classify_intent_heuristic("How to run fMRI analysis pipeline?")
        assert result == DecisionType.PIPELINE_RECOMMENDATION

    def test_classify_intent_heuristic_concept(self):
        """Test heuristic intent classification for concepts."""
        result = self.planner._classify_intent_heuristic("What is the motor cortex?")
        assert result == DecisionType.CONCEPT_LOOKUP

    def test_classify_intent_heuristic_explanation(self):
        """Test heuristic defaults to explanation."""
        result = self.planner._classify_intent_heuristic("Tell me about brain imaging")
        assert result == DecisionType.EXPLANATION

    def test_format_evidence_summary(self):
        """Test evidence summary formatting."""
        bundle = EvidenceBundle(
            concepts=[
                EvidenceResult(
                    source=EvidenceSourceType.KNOWLEDGE_GRAPH,
                    id="c1",
                    title="Motor Cortex",
                    relevance_score=0.9,
                    confidence=0.85,
                    summary="Primary motor area",
                )
            ]
        )
        summary = self.planner._format_evidence_summary(bundle, max_items=5)
        assert "Motor Cortex" in summary
        assert "[KG]" in summary

    def test_format_citations(self):
        """Test citations formatting."""
        bundle = EvidenceBundle(
            papers=[
                EvidenceResult(
                    source=EvidenceSourceType.LITERATURE,
                    id="pmid:12345",
                    title="Motor Learning Paper",
                    relevance_score=0.9,
                    confidence=0.9,
                    url="https://pubmed.ncbi.nlm.nih.gov/12345/",
                )
            ]
        )
        citations = self.planner._format_citations(bundle)
        assert "[1]" in citations
        assert "Motor Learning Paper" in citations

    def test_build_citations(self):
        """Test building citation list."""
        bundle = EvidenceBundle(
            papers=[
                EvidenceResult(
                    source=EvidenceSourceType.LITERATURE,
                    id="pmid:12345",
                    title="Test Paper",
                    relevance_score=0.9,
                    confidence=0.9,
                )
            ]
        )
        citations = self.planner._build_citations(bundle)
        assert len(citations) == 1
        assert citations[0]["ref"] == "[1]"
        assert citations[0]["title"] == "Test Paper"

    @pytest.mark.asyncio
    async def test_build_plan_with_bundle(self):
        """Test build_plan with pre-gathered bundle."""
        bundle = EvidenceBundle(
            concepts=[
                EvidenceResult(
                    source=EvidenceSourceType.KNOWLEDGE_GRAPH,
                    id="c1",
                    title="Motor Cortex",
                    relevance_score=0.9,
                    confidence=0.85,
                )
            ]
        )

        plan = await self.planner.build_plan(
            "What is motor cortex?",
            bundle=bundle,
            use_llm=False,  # Use heuristic
        )

        assert plan is not None
        assert plan.query == "What is motor cortex?"
        assert plan.decision_type == DecisionType.CONCEPT_LOOKUP

    @pytest.mark.asyncio
    async def test_build_plan_gathers_evidence(self):
        """Test build_plan gathers evidence when not provided."""
        plan = await self.planner.build_plan(
            "Find datasets",
            use_llm=False,
        )

        # Should have called gather
        self.mock_aggregator.gather.assert_called_once()

    @pytest.mark.asyncio
    async def test_build_plan_force_intent(self):
        """Test build_plan with forced intent."""
        plan = await self.planner.build_plan(
            "Any query",
            force_intent=DecisionType.PIPELINE_RECOMMENDATION,
            use_llm=False,
        )

        assert plan.decision_type == DecisionType.PIPELINE_RECOMMENDATION

    @pytest.mark.asyncio
    async def test_generate_dataset_plan(self):
        """Test dataset plan generation."""
        bundle = EvidenceBundle(
            datasets=[
                EvidenceResult(
                    source=EvidenceSourceType.DATASET_CATALOG,
                    id="ds000001",
                    title="Motor Task Dataset",
                    relevance_score=0.9,
                    confidence=0.85,
                    payload={"tasks": ["motor"], "modalities": ["fmri"]},
                ),
                EvidenceResult(
                    source=EvidenceSourceType.DATASET_CATALOG,
                    id="ds000002",
                    title="Visual Task Dataset",
                    relevance_score=0.7,
                    confidence=0.75,
                    payload={"tasks": ["visual"], "modalities": ["fmri"]},
                ),
            ]
        )

        plan = await self.planner._generate_dataset_plan(
            "Find motor datasets", bundle
        )

        # Should be a fallback plan without LLM
        assert plan.decision_type == DecisionType.DATASET_SELECTION
        assert len(plan.recommended_datasets) > 0

    @pytest.mark.asyncio
    async def test_generate_pipeline_plan(self):
        """Test pipeline plan generation."""
        bundle = EvidenceBundle(
            tools=[
                EvidenceResult(
                    source=EvidenceSourceType.TOOL_REGISTRY,
                    id="fmriprep",
                    title="fMRIPrep",
                    relevance_score=0.9,
                    confidence=0.85,
                    summary="Preprocessing pipeline",
                ),
            ]
        )

        plan = await self.planner._generate_pipeline_plan(
            "How to preprocess fMRI?", bundle
        )

        assert plan.decision_type == DecisionType.PIPELINE_RECOMMENDATION
        assert len(plan.recommended_tools) > 0

    @pytest.mark.asyncio
    async def test_generate_concept_plan(self):
        """Test concept lookup plan generation."""
        bundle = EvidenceBundle(
            concepts=[
                EvidenceResult(
                    source=EvidenceSourceType.KNOWLEDGE_GRAPH,
                    id="c1",
                    title="Motor Learning",
                    relevance_score=0.9,
                    confidence=0.85,
                )
            ],
            brain_regions=[
                EvidenceResult(
                    source=EvidenceSourceType.KNOWLEDGE_GRAPH,
                    id="r1",
                    title="Primary Motor Cortex",
                    relevance_score=0.85,
                    confidence=0.8,
                )
            ],
        )

        plan = await self.planner._generate_concept_plan(
            "What is motor cortex?", bundle
        )

        assert plan.decision_type == DecisionType.CONCEPT_LOOKUP
        assert "Motor Learning" in plan.concepts or "Primary Motor Cortex" in plan.concepts

    @pytest.mark.asyncio
    async def test_quick_gather(self):
        """Test quick_gather convenience method."""
        bundle = await self.planner.quick_gather("motor cortex")

        self.mock_aggregator.gather.assert_called()
        assert bundle is not None


class TestFactoryFunctions:
    """Test factory functions."""

    def test_create_planner(self):
        """Test create_planner factory."""
        planner = create_planner(
            model_hint="gpt-4",
            max_citations=15,
            timeout=20.0,
        )
        assert isinstance(planner, KnowledgePlanner)
        assert planner._model_hint == "gpt-4"
        assert planner._max_citations == 15

    def test_create_aggregator(self):
        """Test create_aggregator factory."""
        aggregator = create_aggregator(
            timeout=15.0,
            limit_per_source=20,
        )
        assert isinstance(aggregator, EvidenceAggregator)
        assert aggregator._timeout == 15.0
        assert aggregator._limit_per_source == 20
