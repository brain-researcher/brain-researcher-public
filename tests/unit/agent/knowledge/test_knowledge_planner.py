"""Unit tests for knowledge_planner.py."""

import json
from unittest.mock import MagicMock, patch

import pytest

from brain_researcher.services.agent.knowledge.knowledge_planner import (
    KnowledgePlanner,
    create_knowledge_planner,
)
from brain_researcher.services.agent.knowledge.evidence_models import (
    DecisionType,
    EvidenceBundle,
    EvidenceItem,
    EvidenceSourceType,
)


class MockLLMChatResult:
    """Mock for LLMChatResult."""

    def __init__(self, text: str):
        self.text = text


class MockLLMRouter:
    """Mock LLM router for testing."""

    def __init__(self, responses: dict = None):
        self.responses = responses or {}
        self.call_count = 0

    def route_chat(self, prompt: str, **kwargs):
        self.call_count += 1

        # Return appropriate mock response based on prompt content
        if "Classify the intent" in prompt:
            return MockLLMChatResult(json.dumps({
                "intent": self.responses.get("intent", "EXPLANATION"),
                "reasoning": "Test reasoning",
                "confidence": 0.9,
            }))
        elif "Generate a concise" in prompt:
            return MockLLMChatResult(json.dumps({
                "explanation": self.responses.get("explanation", "Test explanation with [1] citation."),
                "key_concepts": ["concept1", "concept2"],
                "confidence": 0.85,
            }))
        elif "Recommend datasets" in prompt:
            return MockLLMChatResult(json.dumps({
                "recommended_datasets": self.responses.get("datasets", ["ds001", "ds002"]),
                "dataset_scores": {"ds001": 0.9, "ds002": 0.8},
                "reasoning": "Test dataset reasoning",
                "confidence": 0.8,
            }))
        elif "Recommend analysis tools" in prompt:
            return MockLLMChatResult(json.dumps({
                "recommended_tools": self.responses.get("tools", ["fmriprep", "nilearn"]),
                "tool_sequence": ["fmriprep", "nilearn"],
                "reasoning": "Test tool reasoning",
                "confidence": 0.75,
            }))
        else:
            return MockLLMChatResult("{}")


def create_test_bundle(
    query: str = "test query",
    include_literature: bool = True,
    include_datasets: bool = True,
    include_tools: bool = True,
) -> EvidenceBundle:
    """Create a test evidence bundle."""
    bundle = EvidenceBundle(query=query)

    if include_literature:
        bundle.add_item(
            EvidenceItem(
                source_type=EvidenceSourceType.PUBMED,
                source_id="pmid:12345",
                label="Test Paper on Motor Cortex",
                relevance_score=0.9,
                url="https://pubmed.ncbi.nlm.nih.gov/12345",
                metadata={"year": "2023"},
            )
        )
        bundle.add_item(
            EvidenceItem(
                source_type=EvidenceSourceType.PUBMED,
                source_id="pmid:67890",
                label="fMRI Analysis Methods Review",
                relevance_score=0.85,
                url="https://pubmed.ncbi.nlm.nih.gov/67890",
            )
        )

    if include_datasets:
        bundle.add_item(
            EvidenceItem(
                source_type=EvidenceSourceType.DATASET_CATALOG,
                source_id="ds001234",
                label="Motor Task Dataset",
                relevance_score=0.88,
                url="https://openneuro.org/datasets/ds001234",
                metadata={
                    "tasks": ["motor"],
                    "modalities": ["fMRI"],
                    "n_subjects": 50,
                },
            )
        )

    if include_tools:
        bundle.add_item(
            EvidenceItem(
                source_type=EvidenceSourceType.TOOL_CATALOG,
                source_id="fmriprep",
                label="fMRIPrep",
                relevance_score=0.95,
                metadata={"description": "fMRI preprocessing pipeline"},
            )
        )

    bundle.compute_confidence()
    return bundle


class TestKnowledgePlanner:
    """Tests for KnowledgePlanner."""

    def test_initialization(self):
        """Test planner initialization."""
        planner = KnowledgePlanner(
            model_hint="test-model",
            max_citations=5,
        )
        assert planner._model_hint == "test-model"
        assert planner._max_citations == 5

    def test_parse_json_response_plain(self):
        """Test JSON parsing from plain response."""
        planner = KnowledgePlanner()
        result = planner._parse_json_response('{"key": "value"}')
        assert result == {"key": "value"}

    def test_parse_json_response_with_code_fence(self):
        """Test JSON parsing with markdown code fence."""
        planner = KnowledgePlanner()
        result = planner._parse_json_response('```json\n{"key": "value"}\n```')
        assert result == {"key": "value"}

    def test_parse_json_response_invalid(self):
        """Test JSON parsing with invalid JSON."""
        planner = KnowledgePlanner()
        result = planner._parse_json_response("not json")
        assert result == {}

    def test_format_evidence_summary(self):
        """Test evidence summary formatting."""
        planner = KnowledgePlanner()
        bundle = create_test_bundle()

        summary = planner._format_evidence_summary(bundle, max_items=5)

        assert "PUBMED" in summary
        assert "DATASET_CATALOG" in summary
        assert "TOOL_CATALOG" in summary

    def test_format_evidence_summary_empty(self):
        """Test evidence summary with empty bundle."""
        planner = KnowledgePlanner()
        bundle = EvidenceBundle(query="empty")

        summary = planner._format_evidence_summary(bundle)
        assert summary == "No evidence available."

    def test_format_citations(self):
        """Test citation formatting."""
        planner = KnowledgePlanner(max_citations=5)
        bundle = create_test_bundle()

        citations = planner._format_citations(bundle)

        assert "[1]" in citations
        assert "pubmed.ncbi.nlm.nih.gov" in citations

    def test_format_dataset_evidence(self):
        """Test dataset evidence formatting."""
        planner = KnowledgePlanner()
        bundle = create_test_bundle()

        formatted = planner._format_dataset_evidence(bundle)

        assert "ds001234" in formatted
        assert "motor" in formatted.lower()
        assert "fMRI" in formatted

    def test_format_dataset_evidence_empty(self):
        """Test dataset evidence formatting with no datasets."""
        planner = KnowledgePlanner()
        bundle = create_test_bundle(include_datasets=False)

        formatted = planner._format_dataset_evidence(bundle)
        assert "No datasets" in formatted

    def test_format_tool_evidence(self):
        """Test tool evidence formatting."""
        planner = KnowledgePlanner()
        bundle = create_test_bundle()

        formatted = planner._format_tool_evidence(bundle)

        assert "fmriprep" in formatted
        assert "preprocessing" in formatted.lower()

    @pytest.mark.asyncio
    async def test_classify_intent_explanation(self):
        """Test intent classification for explanation."""
        mock_router = MockLLMRouter(responses={"intent": "EXPLANATION"})

        planner = KnowledgePlanner()
        planner._router = mock_router

        bundle = create_test_bundle()
        intent = await planner.classify_intent("What is the motor cortex?", bundle)

        assert intent == DecisionType.EXPLANATION
        assert mock_router.call_count == 1

    @pytest.mark.asyncio
    async def test_classify_intent_dataset(self):
        """Test intent classification for dataset selection."""
        mock_router = MockLLMRouter(responses={"intent": "DATASET_SELECTION"})

        planner = KnowledgePlanner()
        planner._router = mock_router

        bundle = create_test_bundle()
        intent = await planner.classify_intent("Find motor task datasets", bundle)

        assert intent == DecisionType.DATASET_SELECTION

    @pytest.mark.asyncio
    async def test_classify_intent_pipeline(self):
        """Test intent classification for pipeline recommendation."""
        mock_router = MockLLMRouter(responses={"intent": "PIPELINE_RECOMMENDATION"})

        planner = KnowledgePlanner()
        planner._router = mock_router

        bundle = create_test_bundle()
        intent = await planner.classify_intent("How to preprocess fMRI data?", bundle)

        assert intent == DecisionType.PIPELINE_RECOMMENDATION

    @pytest.mark.asyncio
    async def test_classify_intent_fallback(self):
        """Test intent classification fallback on error."""
        mock_router = MagicMock()
        mock_router.route_chat.side_effect = Exception("LLM error")

        planner = KnowledgePlanner()
        planner._router = mock_router

        bundle = create_test_bundle()
        intent = await planner.classify_intent("test query", bundle)

        # Should default to EXPLANATION
        assert intent == DecisionType.EXPLANATION

    @pytest.mark.asyncio
    async def test_build_plan_explanation(self):
        """Test building an explanation plan."""
        mock_router = MockLLMRouter(responses={
            "intent": "EXPLANATION",
            "explanation": "The motor cortex is a brain region [1].",
        })

        planner = KnowledgePlanner()
        planner._router = mock_router

        bundle = create_test_bundle(query="What is the motor cortex?")
        plan = await planner.build_plan("What is the motor cortex?", bundle)

        assert plan.decision_type == DecisionType.EXPLANATION
        assert plan.explanation is not None
        assert len(plan.citations) > 0
        assert plan.confidence > 0

    @pytest.mark.asyncio
    async def test_build_plan_dataset_selection(self):
        """Test building a dataset selection plan."""
        mock_router = MockLLMRouter(responses={
            "intent": "DATASET_SELECTION",
            "datasets": ["ds001234", "ds005678"],
        })

        planner = KnowledgePlanner()
        planner._router = mock_router

        bundle = create_test_bundle(query="Find motor task datasets")
        plan = await planner.build_plan("Find motor task datasets", bundle)

        assert plan.decision_type == DecisionType.DATASET_SELECTION
        assert len(plan.recommended_datasets) > 0
        assert plan.dataset_scores

    @pytest.mark.asyncio
    async def test_build_plan_pipeline(self):
        """Test building a pipeline recommendation plan."""
        mock_router = MockLLMRouter(responses={
            "intent": "PIPELINE_RECOMMENDATION",
            "tools": ["fmriprep", "nilearn"],
        })

        planner = KnowledgePlanner()
        planner._router = mock_router

        bundle = create_test_bundle(query="How to preprocess fMRI?")
        plan = await planner.build_plan("How to preprocess fMRI?", bundle)

        assert plan.decision_type == DecisionType.PIPELINE_RECOMMENDATION
        assert len(plan.recommended_tools) > 0
        assert plan.tool_sequence

    @pytest.mark.asyncio
    async def test_build_plan_force_intent(self):
        """Test forcing a specific intent."""
        mock_router = MockLLMRouter(responses={
            "intent": "EXPLANATION",  # This would be the classified intent
            "datasets": ["ds001"],
        })

        planner = KnowledgePlanner()
        planner._router = mock_router

        bundle = create_test_bundle()

        # Force dataset selection even though query might classify as explanation
        plan = await planner.build_plan(
            "Some query",
            bundle,
            force_intent=DecisionType.DATASET_SELECTION,
        )

        assert plan.decision_type == DecisionType.DATASET_SELECTION


class TestCreateKnowledgePlanner:
    """Tests for factory function."""

    def test_create_with_defaults(self):
        """Test creating planner with defaults."""
        planner = create_knowledge_planner()
        assert planner._model_hint is None
        assert planner._max_citations == 10

    def test_create_with_custom_params(self):
        """Test creating planner with custom parameters."""
        planner = create_knowledge_planner(
            model_hint="custom-model",
            max_citations=5,
        )
        assert planner._model_hint == "custom-model"
        assert planner._max_citations == 5
