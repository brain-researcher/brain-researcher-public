"""Unit tests for knowledge layer tools."""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from brain_researcher.services.agent.knowledge.tools import (
    BuildKnowledgePlanTool,
    ExplainTool,
    GatherEvidenceTool,
    RecommendDatasetsTool,
    get_knowledge_tools,
    _source_str_to_enum,
)
from brain_researcher.services.agent.knowledge.evidence_models import (
    DecisionType,
    EvidenceBundle,
    EvidenceItem,
    EvidenceSourceType,
    KnowledgePlan,
)


def create_mock_bundle(query: str = "test query") -> EvidenceBundle:
    """Create a mock evidence bundle for testing."""
    bundle = EvidenceBundle(query=query)
    bundle.add_item(
        EvidenceItem(
            source_type=EvidenceSourceType.PUBMED,
            source_id="pmid:12345",
            label="Test Paper",
            relevance_score=0.9,
            url="https://pubmed.ncbi.nlm.nih.gov/12345",
        )
    )
    bundle.add_item(
        EvidenceItem(
            source_type=EvidenceSourceType.DATASET_CATALOG,
            source_id="ds001234",
            label="Test Dataset",
            relevance_score=0.85,
            url="https://openneuro.org/datasets/ds001234",
            metadata={
                "tasks": ["motor"],
                "modalities": ["fMRI"],
                "n_subjects": 50,
            },
        )
    )
    bundle.add_item(
        EvidenceItem(
            source_type=EvidenceSourceType.TOOL_CATALOG,
            source_id="fmriprep",
            label="fMRIPrep",
            relevance_score=0.88,
            metadata={"description": "fMRI preprocessing"},
        )
    )
    bundle.compute_confidence()
    return bundle


def create_mock_plan(query: str = "test query") -> KnowledgePlan:
    """Create a minimal KnowledgePlan used in planner mocks."""
    return KnowledgePlan(
        decision_type=DecisionType.DATASET_SELECTION,
        query=query,
        reasoning="mock reasoning",
        recommended_datasets=[],
        dataset_scores={},
        confidence=0.9,
    )


class TestSourceStrToEnum:
    """Tests for _source_str_to_enum helper."""

    def test_valid_sources(self):
        """Test valid source string conversion."""
        assert _source_str_to_enum("pubmed") == EvidenceSourceType.PUBMED
        assert _source_str_to_enum("PUBMED") == EvidenceSourceType.PUBMED
        assert _source_str_to_enum("dataset_catalog") == EvidenceSourceType.DATASET_CATALOG
        assert _source_str_to_enum("tool_catalog") == EvidenceSourceType.TOOL_CATALOG
        assert _source_str_to_enum("kg_graph") == EvidenceSourceType.KG_GRAPH
        assert _source_str_to_enum("niclip") == EvidenceSourceType.NICLIP

    def test_invalid_source(self):
        """Test invalid source string returns None."""
        assert _source_str_to_enum("invalid") is None
        assert _source_str_to_enum("unknown_source") is None


class TestGatherEvidenceTool:
    """Tests for GatherEvidenceTool."""

    def test_tool_properties(self):
        """Test tool properties."""
        tool = GatherEvidenceTool()
        assert tool.get_tool_name() == "neuroassistant.gather_evidence"
        assert "evidence" in tool.get_tool_description().lower()
        assert tool.get_args_schema() is not None

    def test_run_success(self):
        """Test successful evidence gathering."""
        mock_bundle = create_mock_bundle()

        with patch(
            "brain_researcher.services.agent.knowledge.evidence_connector.EvidenceAggregator"
        ) as MockAggregator, patch(
            "brain_researcher.services.agent.knowledge.niclip_scorer.NiCLIPScorer"
        ) as MockScorer:
            mock_aggregator = MagicMock()
            mock_aggregator.gather_evidence = AsyncMock(return_value=mock_bundle)
            MockAggregator.return_value = mock_aggregator

            mock_scorer = MagicMock()
            mock_scorer.enrich_bundle = AsyncMock(return_value=mock_bundle)
            MockScorer.return_value = mock_scorer

            tool = GatherEvidenceTool()
            result = tool._run(query="motor cortex", limit=10)

            assert result.status == "success"
            assert result.data["query"] == "test query"
            assert result.data["total_items"] == 3

    def test_run_with_source_filter(self):
        """Test evidence gathering with source filter."""
        mock_bundle = create_mock_bundle()

        with patch(
            "brain_researcher.services.agent.knowledge.evidence_connector.EvidenceAggregator"
        ) as MockAggregator, patch(
            "brain_researcher.services.agent.knowledge.niclip_scorer.NiCLIPScorer"
        ) as MockScorer:
            mock_aggregator = MagicMock()
            mock_aggregator.gather_evidence = AsyncMock(return_value=mock_bundle)
            MockAggregator.return_value = mock_aggregator

            mock_scorer = MagicMock()
            mock_scorer.enrich_bundle = AsyncMock(return_value=mock_bundle)
            MockScorer.return_value = mock_scorer

            tool = GatherEvidenceTool()
            result = tool._run(
                query="motor cortex",
                sources=["pubmed", "dataset_catalog"],
                limit=10,
            )

            assert result.status == "success"

    def test_as_langchain_tool(self):
        """Test conversion to LangChain tool."""
        tool = GatherEvidenceTool()
        lc_tool = tool.as_langchain_tool()

        assert lc_tool.name == "neuroassistant.gather_evidence"
        assert lc_tool.description is not None


class TestBuildKnowledgePlanTool:
    """Tests for BuildKnowledgePlanTool."""

    def test_tool_properties(self):
        """Test tool properties."""
        tool = BuildKnowledgePlanTool()
        assert tool.get_tool_name() == "neuroassistant.build_knowledge_plan"
        assert "plan" in tool.get_tool_description().lower()

    def test_run_explanation_plan(self):
        """Test building an explanation plan."""
        mock_bundle = create_mock_bundle()

        from brain_researcher.services.agent.knowledge.evidence_models import KnowledgePlan

        mock_plan = KnowledgePlan(
            decision_type=DecisionType.EXPLANATION,
            query="What is motor cortex?",
            reasoning="User asking conceptual question",
            explanation="The motor cortex is...",
            citations=[{"ref": "[1]", "label": "Test", "url": "http://test.com"}],
            confidence=0.85,
        )

        with patch(
            "brain_researcher.services.agent.knowledge.evidence_connector.EvidenceAggregator"
        ) as MockAggregator, patch(
            "brain_researcher.services.agent.knowledge.niclip_scorer.NiCLIPScorer"
        ) as MockScorer, patch(
            "brain_researcher.services.agent.knowledge.knowledge_planner.KnowledgePlanner"
        ) as MockPlanner:
            mock_aggregator = MagicMock()
            mock_aggregator.gather_evidence = AsyncMock(return_value=mock_bundle)
            MockAggregator.return_value = mock_aggregator

            mock_scorer = MagicMock()
            mock_scorer.enrich_bundle = AsyncMock(return_value=mock_bundle)
            MockScorer.return_value = mock_scorer

            mock_planner = MagicMock()
            mock_planner.build_plan = AsyncMock(return_value=mock_plan)
            MockPlanner.return_value = mock_planner

            tool = BuildKnowledgePlanTool()
            result = tool._run(query="What is motor cortex?")

            assert result.status == "success"
            assert result.data["decision_type"] == "explanation"
            assert result.data["explanation"] is not None

    def test_run_with_forced_intent(self):
        """Test building plan with forced intent."""
        mock_bundle = create_mock_bundle()

        from brain_researcher.services.agent.knowledge.evidence_models import KnowledgePlan

        mock_plan = KnowledgePlan(
            decision_type=DecisionType.DATASET_SELECTION,
            query="Find motor datasets",
            reasoning="Forced to dataset selection",
            recommended_datasets=["ds001"],
            dataset_scores={"ds001": 0.9},
            confidence=0.8,
        )

        with patch(
            "brain_researcher.services.agent.knowledge.evidence_connector.EvidenceAggregator"
        ) as MockAggregator, patch(
            "brain_researcher.services.agent.knowledge.niclip_scorer.NiCLIPScorer"
        ) as MockScorer, patch(
            "brain_researcher.services.agent.knowledge.knowledge_planner.KnowledgePlanner"
        ) as MockPlanner:
            mock_aggregator = MagicMock()
            mock_aggregator.gather_evidence = AsyncMock(return_value=mock_bundle)
            MockAggregator.return_value = mock_aggregator

            mock_scorer = MagicMock()
            mock_scorer.enrich_bundle = AsyncMock(return_value=mock_bundle)
            MockScorer.return_value = mock_scorer

            mock_planner = MagicMock()
            mock_planner.build_plan = AsyncMock(return_value=mock_plan)
            MockPlanner.return_value = mock_planner

            tool = BuildKnowledgePlanTool()
            result = tool._run(query="Find motor datasets", force_intent="dataset_selection")

            assert result.status == "success"
            assert result.data["decision_type"] == "dataset_selection"


class TestRecommendDatasetsTool:
    """Tests for RecommendDatasetsTool."""

    def test_tool_properties(self):
        """Test tool properties."""
        tool = RecommendDatasetsTool()
        assert tool.get_tool_name() == "neuroassistant.recommend_datasets"
        assert "dataset" in tool.get_tool_description().lower()

    def test_run_success(self):
        """Test successful dataset recommendation."""
        mock_bundle = create_mock_bundle()

        with patch(
            "brain_researcher.services.agent.knowledge.evidence_connector.EvidenceAggregator"
        ) as MockAggregator, patch(
            "brain_researcher.services.agent.knowledge.knowledge_planner.KnowledgePlanner"
        ) as MockPlanner:
            mock_aggregator = MagicMock()
            mock_aggregator.gather_evidence = AsyncMock(return_value=mock_bundle)
            MockAggregator.return_value = mock_aggregator

            tool = RecommendDatasetsTool()
            result = tool._run(query="motor task datasets", max_datasets=5)

            assert result.status == "success"
            assert "datasets" in result.data
            assert result.data["total_found"] >= 0

    def test_run_with_modality_filter(self):
        """Test dataset recommendation with modality filter."""
        mock_bundle = create_mock_bundle()

        with patch(
            "brain_researcher.services.agent.knowledge.evidence_connector.EvidenceAggregator"
        ) as MockAggregator, patch(
            "brain_researcher.services.agent.knowledge.knowledge_planner.KnowledgePlanner"
        ) as MockPlanner:
            mock_aggregator = MagicMock()
            mock_aggregator.gather_evidence = AsyncMock(return_value=mock_bundle)
            MockAggregator.return_value = mock_aggregator

            mock_planner = MagicMock()
            mock_planner._generate_dataset_plan = AsyncMock(
                return_value=create_mock_plan()
            )
            MockPlanner.return_value = mock_planner

            tool = RecommendDatasetsTool()
            result = tool._run(
                query="motor task",
                max_datasets=5,
                required_modalities=["fMRI"],
            )

            assert result.status == "success"
            # Check filter was applied in metadata
            assert result.metadata["filters_applied"]["modalities"] == ["fMRI"]


class TestExplainTool:
    """Tests for ExplainTool."""

    def test_tool_properties(self):
        """Test tool properties."""
        tool = ExplainTool()
        assert tool.get_tool_name() == "neuroassistant.explain"
        assert "explanation" in tool.get_tool_description().lower()

    def test_run_success(self):
        """Test successful explanation generation."""
        mock_bundle = create_mock_bundle()

        from brain_researcher.services.agent.knowledge.evidence_models import KnowledgePlan

        mock_plan = KnowledgePlan(
            decision_type=DecisionType.EXPLANATION,
            query="What is fMRI?",
            explanation="fMRI (functional MRI) is a neuroimaging technique...",
            citations=[{"ref": "[1]", "label": "Test", "url": "http://test.com"}],
            confidence=0.9,
            metadata={"key_concepts": ["BOLD", "hemodynamic response"]},
        )

        with patch(
            "brain_researcher.services.agent.knowledge.evidence_connector.EvidenceAggregator"
        ) as MockAggregator, patch(
            "brain_researcher.services.agent.knowledge.niclip_scorer.NiCLIPScorer"
        ) as MockScorer, patch(
            "brain_researcher.services.agent.knowledge.knowledge_planner.KnowledgePlanner"
        ) as MockPlanner:
            mock_aggregator = MagicMock()
            mock_aggregator.gather_evidence = AsyncMock(return_value=mock_bundle)
            MockAggregator.return_value = mock_aggregator

            mock_scorer = MagicMock()
            mock_scorer.enrich_bundle = AsyncMock(return_value=mock_bundle)
            MockScorer.return_value = mock_scorer

            mock_planner = MagicMock()
            mock_planner._generate_explanation_plan = AsyncMock(return_value=mock_plan)
            MockPlanner.return_value = mock_planner

            tool = ExplainTool()
            result = tool._run(query="What is fMRI?", max_citations=5)

            assert result.status == "success"
            assert result.data["explanation"] is not None
            assert result.data["confidence"] > 0


class TestGetKnowledgeTools:
    """Tests for get_knowledge_tools function."""

    def test_returns_all_tools(self):
        """Test that all tools are returned."""
        tools = get_knowledge_tools()

        assert len(tools) == 4

        tool_names = [t.get_tool_name() for t in tools]
        assert "neuroassistant.gather_evidence" in tool_names
        assert "neuroassistant.build_knowledge_plan" in tool_names
        assert "neuroassistant.recommend_datasets" in tool_names
        assert "neuroassistant.explain" in tool_names

    def test_tools_are_valid(self):
        """Test that all tools have valid properties."""
        tools = get_knowledge_tools()

        for tool in tools:
            assert tool.get_tool_name() is not None
            assert tool.get_tool_description() is not None
            assert tool.get_args_schema() is not None

            # Should be convertible to LangChain tool
            lc_tool = tool.as_langchain_tool()
            assert lc_tool is not None
