"""Tests for knowledge layer tools."""

import pytest
from unittest.mock import MagicMock, patch, AsyncMock

from brain_researcher.services.knowledge.evidence.base import (
    EvidenceBundle,
    EvidenceResult,
    EvidenceSourceType,
)
from brain_researcher.services.knowledge.planner import DecisionType, KnowledgePlan
from brain_researcher.services.knowledge.tools import (
    ToolResult,
    query_kg,
    search_datasets,
    search_tools,
    search_literature,
    query_niclip,
    gather_evidence,
    build_plan,
    explain,
    get_tool_definitions,
    get_tool_by_name,
    _parse_source_types,
    _parse_decision_type,
    _format_results,
)


class TestToolResult:
    """Test ToolResult type."""

    def test_success_result(self):
        """Test creating a success result."""
        result = ToolResult(
            status="success",
            data={"items": [1, 2, 3]},
            metadata={"time_ms": 100},
        )
        assert result.status == "success"
        assert result.data["items"] == [1, 2, 3]
        assert result.error is None

    def test_error_result(self):
        """Test creating an error result."""
        result = ToolResult(
            status="error",
            error="Something went wrong",
        )
        assert result.status == "error"
        assert result.error == "Something went wrong"
        assert result.data is None


class TestHelperFunctions:
    """Test helper functions."""

    def test_parse_source_types(self):
        """Test parsing source type strings."""
        result = _parse_source_types(["kg", "pubmed", "datasets"])
        assert EvidenceSourceType.KNOWLEDGE_GRAPH in result
        assert EvidenceSourceType.LITERATURE in result
        assert EvidenceSourceType.DATASET_CATALOG in result

    def test_parse_source_types_none(self):
        """Test parsing None source types."""
        assert _parse_source_types(None) is None
        assert _parse_source_types([]) is None

    def test_parse_source_types_invalid(self):
        """Test parsing invalid source types."""
        result = _parse_source_types(["invalid", "unknown"])
        assert result is None

    def test_parse_decision_type(self):
        """Test parsing decision type strings."""
        assert _parse_decision_type("explanation") == DecisionType.EXPLANATION
        assert _parse_decision_type("dataset_selection") == DecisionType.DATASET_SELECTION
        assert _parse_decision_type("pipeline_recommendation") == DecisionType.PIPELINE_RECOMMENDATION
        assert _parse_decision_type("EXPLANATION") == DecisionType.EXPLANATION  # Case insensitive

    def test_parse_decision_type_invalid(self):
        """Test parsing invalid decision type."""
        assert _parse_decision_type(None) is None
        assert _parse_decision_type("invalid") is None

    def test_format_results(self):
        """Test formatting evidence results."""
        results = [
            EvidenceResult(
                source=EvidenceSourceType.KNOWLEDGE_GRAPH,
                id="concept:motor",
                title="Motor Cortex",
                relevance_score=0.9,
                confidence=0.85,
                url="https://example.com",
                summary="Primary motor area",
                payload={"node_type": "BrainRegion"},
            )
        ]
        formatted = _format_results(results)
        assert len(formatted) == 1
        assert formatted[0]["id"] == "concept:motor"
        assert formatted[0]["title"] == "Motor Cortex"
        assert formatted[0]["source"] == "kg"


class TestLowLevelTools:
    """Test low-level tool implementations."""

    @patch("brain_researcher.services.knowledge.evidence.kg_source.KGEvidenceSource")
    def test_query_kg_success(self, mock_source_class):
        """Test query_kg success."""
        mock_source = MagicMock()
        mock_source.query_sync.return_value = [
            EvidenceResult(
                source=EvidenceSourceType.KNOWLEDGE_GRAPH,
                id="concept:motor",
                title="Motor Cortex",
                relevance_score=0.9,
                confidence=0.85,
                payload={"is_brain_region": True},
            )
        ]
        mock_source_class.return_value = mock_source

        result = query_kg("motor cortex", limit=5)

        assert result.status == "success"
        assert result.data["total"] == 1
        assert len(result.data["brain_regions"]) == 1

    @patch("brain_researcher.services.knowledge.evidence.kg_source.KGEvidenceSource")
    def test_query_kg_error(self, mock_source_class):
        """Test query_kg error handling."""
        mock_source_class.side_effect = Exception("DB error")

        result = query_kg("test")

        assert result.status == "error"
        assert "KG query failed" in result.error

    @patch("brain_researcher.services.knowledge.evidence.dataset_source.DatasetEvidenceSource")
    def test_search_datasets_success(self, mock_source_class):
        """Test search_datasets success."""
        mock_source = MagicMock()
        mock_source.query_sync.return_value = [
            EvidenceResult(
                source=EvidenceSourceType.DATASET_CATALOG,
                id="ds000001",
                title="Motor Task Dataset",
                relevance_score=0.85,
                confidence=0.8,
            )
        ]
        mock_source_class.return_value = mock_source

        result = search_datasets("motor", modality="fmri", limit=5)

        assert result.status == "success"
        assert result.data["total"] == 1
        assert result.metadata["modality_filter"] == "fmri"

    @patch("brain_researcher.services.knowledge.evidence.tool_source.ToolEvidenceSource")
    def test_search_tools_success(self, mock_source_class):
        """Test search_tools success."""
        mock_source = MagicMock()
        mock_source.query_sync.return_value = [
            EvidenceResult(
                source=EvidenceSourceType.TOOL_REGISTRY,
                id="fmriprep",
                title="fMRIPrep",
                relevance_score=0.9,
                confidence=0.85,
            )
        ]
        mock_source_class.return_value = mock_source

        result = search_tools("preprocessing", limit=5)

        assert result.status == "success"
        assert result.data["total"] == 1

    @patch("brain_researcher.services.knowledge.evidence.literature_source.LiteratureEvidenceSource")
    def test_search_literature_success(self, mock_source_class):
        """Test search_literature success."""
        mock_source = MagicMock()
        mock_source.query = AsyncMock(
            return_value=[
                EvidenceResult(
                    source=EvidenceSourceType.LITERATURE,
                    id="pmid:12345",
                    title="Brain Paper",
                    relevance_score=0.88,
                    confidence=0.9,
                )
            ]
        )
        mock_source_class.return_value = mock_source

        result = search_literature("fmri", year_min=2020, limit=5)

        assert result.status == "success"
        assert result.data["total"] == 1
        assert result.metadata["year_min_filter"] == 2020

    @patch("brain_researcher.services.knowledge.scoring.niclip_scorer.NiCLIPEvidenceSource")
    def test_query_niclip_success(self, mock_source_class):
        """Test query_niclip success."""
        mock_source = MagicMock()
        mock_source.query_sync.return_value = [
            EvidenceResult(
                source=EvidenceSourceType.NICLIP,
                id="niclip:0",
                title="Motor Learning",
                relevance_score=0.85,
                confidence=0.75,
            )
        ]
        mock_source_class.return_value = mock_source

        result = query_niclip("motor", limit=5)

        assert result.status == "success"
        assert result.data["total"] == 1
        assert result.data["vocabulary_type"] == "cogatlas_task-names"


class TestHighLevelTools:
    """Test high-level tool implementations."""

    @patch("brain_researcher.services.knowledge.tools.EvidenceAggregator")
    def test_gather_evidence_success(self, mock_aggregator_class):
        """Test gather_evidence success."""
        mock_aggregator = MagicMock()
        mock_aggregator.gather = AsyncMock(
            return_value=EvidenceBundle(
                concepts=[
                    EvidenceResult(
                        source=EvidenceSourceType.KNOWLEDGE_GRAPH,
                        id="c1",
                        title="Concept 1",
                        relevance_score=0.9,
                        confidence=0.85,
                    )
                ],
                datasets=[
                    EvidenceResult(
                        source=EvidenceSourceType.DATASET_CATALOG,
                        id="ds1",
                        title="Dataset 1",
                        relevance_score=0.8,
                        confidence=0.75,
                    )
                ],
                metadata={"sources_queried": ["kg", "datasets"], "query_time_ms": 100},
            )
        )
        mock_aggregator_class.return_value = mock_aggregator

        result = gather_evidence("motor cortex")

        assert result.status == "success"
        assert result.data["concepts_count"] == 1
        assert result.data["datasets_count"] == 1

    @patch("brain_researcher.services.knowledge.tools.EvidenceAggregator")
    def test_gather_evidence_with_source_filter(self, mock_aggregator_class):
        """Test gather_evidence with source type filter."""
        mock_aggregator = MagicMock()
        mock_aggregator.gather = AsyncMock(return_value=EvidenceBundle())
        mock_aggregator_class.return_value = mock_aggregator

        result = gather_evidence("test", source_types=["kg", "pubmed"])

        assert result.status == "success"
        mock_aggregator.gather.assert_called_once()
        call_kwargs = mock_aggregator.gather.call_args[1]
        assert EvidenceSourceType.KNOWLEDGE_GRAPH in call_kwargs.get("source_types", [])

    @patch("brain_researcher.services.knowledge.tools.KnowledgePlanner")
    def test_build_plan_success(self, mock_planner_class):
        """Test build_plan success."""
        mock_planner = MagicMock()
        mock_planner.build_plan = AsyncMock(
            return_value=KnowledgePlan(
                decision_type=DecisionType.EXPLANATION,
                query="What is motor cortex?",
                reasoning="Explanation based on evidence",
                confidence=0.85,
                explanation="The motor cortex is...",
                concepts=["motor", "cortex"],
                citations=[{"ref": "[1]", "title": "Paper"}],
            )
        )
        mock_planner_class.return_value = mock_planner

        result = build_plan("What is motor cortex?")

        assert result.status == "success"
        assert result.data["decision_type"] == "explanation"
        assert result.data["explanation"] is not None

    @patch("brain_researcher.services.knowledge.tools.KnowledgePlanner")
    def test_build_plan_forced_intent(self, mock_planner_class):
        """Test build_plan with forced intent."""
        mock_planner = MagicMock()
        mock_planner.build_plan = AsyncMock(
            return_value=KnowledgePlan(
                decision_type=DecisionType.DATASET_SELECTION,
                query="test",
                reasoning="Forced to dataset selection",
                confidence=0.8,
                recommended_datasets=["ds1", "ds2"],
                dataset_scores={"ds1": 0.9, "ds2": 0.8},
            )
        )
        mock_planner_class.return_value = mock_planner

        result = build_plan("test", force_intent="dataset_selection")

        assert result.status == "success"
        assert result.data["decision_type"] == "dataset_selection"
        assert "recommended_datasets" in result.data

    @patch("brain_researcher.services.knowledge.tools.KnowledgePlanner")
    @patch("brain_researcher.services.knowledge.tools.EvidenceAggregator")
    def test_explain_success(self, mock_aggregator_class, mock_planner_class):
        """Test explain success."""
        # Setup aggregator mock
        mock_aggregator = MagicMock()
        mock_aggregator.gather = AsyncMock(
            return_value=EvidenceBundle(
                concepts=[
                    EvidenceResult(
                        source=EvidenceSourceType.NICLIP,
                        id="niclip:0",
                        title="Motor Learning",
                        relevance_score=0.85,
                        confidence=0.75,
                    )
                ]
            )
        )
        mock_aggregator_class.return_value = mock_aggregator

        # Setup planner mock
        mock_planner = MagicMock()
        mock_planner._generate_explanation_plan = AsyncMock(
            return_value=KnowledgePlan(
                decision_type=DecisionType.EXPLANATION,
                query="What is motor learning?",
                reasoning="Generated explanation",
                confidence=0.85,
                explanation="Motor learning is the process...",
                concepts=["motor", "learning"],
                citations=[{"ref": "[1]", "title": "Paper"}],
                evidence_bundle=EvidenceBundle(
                    concepts=[
                        EvidenceResult(
                            source=EvidenceSourceType.NICLIP,
                            id="niclip:0",
                            title="Motor Learning",
                            relevance_score=0.85,
                            confidence=0.75,
                        )
                    ]
                ),
            )
        )
        mock_planner_class.return_value = mock_planner

        result = explain("What is motor learning?", max_citations=5)

        assert result.status == "success"
        assert result.data["explanation"] is not None
        assert "niclip_concepts" in result.data


class TestToolRegistry:
    """Test tool registry functions."""

    def test_get_tool_definitions(self):
        """Test get_tool_definitions returns all tools."""
        definitions = get_tool_definitions()

        assert len(definitions) == 8
        names = [d["name"] for d in definitions]

        # Low-level tools
        assert "knowledge.query_kg" in names
        assert "knowledge.search_datasets" in names
        assert "knowledge.search_tools" in names
        assert "knowledge.search_literature" in names
        assert "knowledge.query_niclip" in names

        # High-level tools
        assert "knowledge.gather_evidence" in names
        assert "knowledge.build_plan" in names
        assert "knowledge.explain" in names

    def test_get_tool_by_name(self):
        """Test get_tool_by_name returns correct tool."""
        tool = get_tool_by_name("knowledge.query_kg")

        assert tool is not None
        assert tool["name"] == "knowledge.query_kg"
        assert callable(tool["function"])
        assert tool["input_schema"] is not None

    def test_get_tool_by_name_not_found(self):
        """Test get_tool_by_name returns None for unknown tool."""
        tool = get_tool_by_name("unknown.tool")
        assert tool is None

    def test_tool_definitions_have_required_fields(self):
        """Test all tool definitions have required fields."""
        definitions = get_tool_definitions()

        for tool in definitions:
            assert "name" in tool
            assert "description" in tool
            assert "function" in tool
            assert "input_schema" in tool
            assert "tags" in tool
            assert callable(tool["function"])
