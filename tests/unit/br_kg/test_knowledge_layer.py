"""Unit tests for Track K+ Knowledge Layer.

Tests the KnowledgeAggregator, KnowledgePlanner, and evidence source adapters.
"""

import asyncio
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from brain_researcher.services.br_kg.knowledge import (
    AggregatedEvidence,
    AggregatorConfig,
    EvidenceConfidence,
    KnowledgeAggregator,
    KnowledgeItem,
    KnowledgePlan,
    KnowledgePlanner,
    PlanIntent,
    PlannerConfig,
)


class TestKnowledgeItem:
    """Tests for KnowledgeItem dataclass."""

    def test_create_item(self):
        item = KnowledgeItem(
            id="test:001",
            source_id="dataset_catalog",
            title="Test Dataset",
            description="A test dataset for fMRI analysis",
            score=0.85,
            metadata={"modalities": ["fMRI"], "subjects_count": 100},
        )
        assert item.id == "test:001"
        assert item.source_id == "dataset_catalog"
        assert item.score == 0.85
        assert item.metadata["subjects_count"] == 100

    def test_to_evidence_item(self):
        item = KnowledgeItem(
            id="test:001",
            source_id="br_kg",
            title="Amygdala",
            score=0.9,
        )
        evidence = item.to_evidence_item()
        assert evidence.id == "test:001"
        # Score is stored in metadata as knowledge_score
        assert evidence.metadata["knowledge_score"] == 0.9


class TestAggregatedEvidence:
    """Tests for AggregatedEvidence dataclass."""

    def test_create_evidence(self):
        evidence = AggregatedEvidence(
            query="find fMRI datasets",
            confidence=EvidenceConfidence.APPROXIMATE,
        )
        assert evidence.query == "find fMRI datasets"
        assert evidence.confidence == EvidenceConfidence.APPROXIMATE
        assert evidence.items == []

    def test_items_by_source(self):
        items = [
            KnowledgeItem(id="1", source_id="dataset_catalog", title="DS1", score=0.9),
            KnowledgeItem(id="2", source_id="dataset_catalog", title="DS2", score=0.8),
            KnowledgeItem(id="3", source_id="tool_registry", title="Tool1", score=0.7),
        ]
        evidence = AggregatedEvidence(
            query="test",
            items=items,
            confidence=EvidenceConfidence.COMPLETE,
        )
        by_source = evidence.items_by_source()
        assert len(by_source["dataset_catalog"]) == 2
        assert len(by_source["tool_registry"]) == 1

    def test_total_items_property(self):
        items = [
            KnowledgeItem(id=str(i), source_id="test", title=f"Item{i}", score=0.5)
            for i in range(5)
        ]
        evidence = AggregatedEvidence(
            query="test",
            items=items,
            confidence=EvidenceConfidence.COMPLETE,
        )
        assert evidence.total_items == 5


class TestKnowledgePlan:
    """Tests for KnowledgePlan dataclass."""

    def test_create_plan(self):
        plan = KnowledgePlan(
            intent=PlanIntent.PIPELINE_RECOMMENDATION,
            recommended_datasets=["ds000001", "ds000002"],
            recommended_tools=["fsl_bet", "fsl_feat"],
            justification="User wants to run fMRI analysis",
            confidence=0.85,
        )
        assert plan.intent == PlanIntent.PIPELINE_RECOMMENDATION
        assert len(plan.recommended_datasets) == 2
        assert len(plan.recommended_tools) == 2
        assert plan.confidence == 0.85

    def test_intent_enum(self):
        assert PlanIntent.EXPLANATION.value == "explanation"
        assert PlanIntent.DATASET_SELECTION.value == "dataset_selection"
        assert PlanIntent.PIPELINE_RECOMMENDATION.value == "pipeline_recommendation"


class TestAggregatorConfig:
    """Tests for AggregatorConfig."""

    def test_default_config(self):
        config = AggregatorConfig()
        assert config.enable_kg is True
        assert config.enable_datasets is True
        assert config.fast_timeout_ms == 200
        assert config.max_items_per_source == 10

    def test_custom_config(self):
        config = AggregatorConfig(
            enable_pubmed=False,
            fast_timeout_ms=500,
            max_total_items=100,
        )
        assert config.enable_pubmed is False
        assert config.fast_timeout_ms == 500
        assert config.max_total_items == 100


class TestKnowledgeAggregator:
    """Tests for KnowledgeAggregator."""

    @pytest.fixture
    def aggregator(self):
        """Create aggregator with disabled external sources for testing."""
        config = AggregatorConfig(
            enable_kg=False,  # Disable to avoid Neo4j dependency
            enable_datasets=False,  # Disable to avoid catalog dependency
            enable_tools=False,  # Disable to avoid registry dependency
            enable_niclip=False,  # Disable to avoid NiCLIP dependency
            enable_pubmed=False,
            enable_neurostore=False,
        )
        return KnowledgeAggregator(config)

    @pytest.mark.asyncio
    async def test_gather_empty_sources(self, aggregator):
        """Test gathering with all sources disabled."""
        evidence = await aggregator.gather("test query", include_slow_sources=False)
        assert evidence.query == "test query"
        assert evidence.items == []
        # With include_slow_sources=False, confidence is APPROXIMATE
        assert evidence.confidence == EvidenceConfidence.APPROXIMATE

    @pytest.mark.asyncio
    async def test_gather_with_mock_source(self):
        """Test gathering with a mocked source via direct _query_source call."""
        config = AggregatorConfig(
            enable_kg=False,
            enable_datasets=False,
            enable_tools=False,
            enable_niclip=False,
        )
        aggregator = KnowledgeAggregator(config)

        # Create mock source
        mock_source = AsyncMock()
        mock_source.source_id = "mock_source"
        mock_source.is_available = AsyncMock(return_value=True)
        mock_source.search = AsyncMock(
            return_value=[
                KnowledgeItem(
                    id="mock:1", source_id="mock_source", title="Mock Result", score=0.9
                )
            ]
        )

        # Test _query_source directly since gather() only queries predefined source lists
        items = await aggregator._query_source(
            "mock_source", mock_source, "test query", 10, 0.5
        )

        mock_source.search.assert_called_once()
        assert len(items) == 1
        assert items[0].id == "mock:1"

    def test_cache_key_generation(self):
        aggregator = KnowledgeAggregator()
        key1 = aggregator._get_cache_key("Find fMRI datasets")
        key2 = aggregator._get_cache_key("find fmri datasets")
        # Basic normalization: lowercase and strip
        assert key1 == key2

        # Verify truncation to 200 chars
        long_query = "x" * 300
        long_key = aggregator._get_cache_key(long_query)
        assert len(long_key) <= 200


class TestPlannerConfig:
    """Tests for PlannerConfig."""

    def test_default_config(self):
        config = PlannerConfig()
        assert config.model_name == "gpt-4o-mini"
        assert config.temperature == 0.3
        assert config.enable_cache is True
        assert config.use_heuristics_first is True


class TestKnowledgePlanner:
    """Tests for KnowledgePlanner."""

    @pytest.fixture
    def planner(self):
        config = PlannerConfig(
            use_heuristics_first=True,
            enable_cache=False,  # Disable cache for testing
        )
        return KnowledgePlanner(config)

    @pytest.fixture
    def sample_evidence(self):
        """Create sample evidence for testing."""
        return AggregatedEvidence(
            query="what is the amygdala?",
            items=[
                KnowledgeItem(
                    id="kg:amygdala",
                    source_id="br_kg",
                    title="Amygdala",
                    description="Brain region involved in emotion processing",
                    score=0.95,
                ),
            ],
            confidence=EvidenceConfidence.COMPLETE,
        )

    @pytest.mark.asyncio
    async def test_heuristic_explanation(self, planner, sample_evidence):
        """Test heuristic planning for explanation queries."""
        plan = await planner.plan(None, sample_evidence)

        assert plan.intent == PlanIntent.EXPLANATION
        assert plan.confidence >= 0.8

    @pytest.mark.asyncio
    async def test_heuristic_dataset_selection(self, planner):
        """Test heuristic planning for dataset queries."""
        evidence = AggregatedEvidence(
            query="find datasets for working memory",
            items=[
                KnowledgeItem(
                    id="ds:001",
                    source_id="dataset_catalog",
                    title="Working Memory Dataset",
                    score=0.9,
                    metadata={"dataset_id": "ds000001"},
                ),
            ],
            confidence=EvidenceConfidence.COMPLETE,
        )
        plan = await planner.plan(None, evidence)

        assert plan.intent == PlanIntent.DATASET_SELECTION
        assert "ds000001" in plan.recommended_datasets

    @pytest.mark.asyncio
    async def test_heuristic_pipeline_recommendation(self, planner):
        """Test heuristic planning for analysis queries."""
        evidence = AggregatedEvidence(
            query="run GLM analysis on ds000001",
            items=[
                KnowledgeItem(
                    id="ds:001",
                    source_id="dataset_catalog",
                    title="DS000001",
                    score=0.9,
                    metadata={"dataset_id": "ds000001"},
                ),
                KnowledgeItem(
                    id="tool:glm",
                    source_id="tool_registry",
                    title="GLM Analysis Tool",
                    score=0.85,
                    metadata={"tool_name": "nilearn_glm"},
                ),
            ],
            confidence=EvidenceConfidence.COMPLETE,
        )
        plan = await planner.plan(None, evidence)

        assert plan.intent == PlanIntent.PIPELINE_RECOMMENDATION
        assert "ds000001" in plan.recommended_datasets


class TestPlanCache:
    """Tests for plan caching."""

    def test_cache_key_normalization(self):
        from brain_researcher.services.br_kg.knowledge.planner import PlanCache

        cache = PlanCache(ttl_seconds=3600)

        # Test that dataset IDs get normalized to placeholder
        # This allows caching of similar query patterns
        key1_normalized = cache._normalize_query("analyze ds000001", [])
        key2_normalized = cache._normalize_query("analyze ds000002", [])

        # Both should normalize dataset IDs to {dataset}
        assert key1_normalized == key2_normalized
        assert "{dataset}" in key1_normalized

        # Entity replacement
        key3_normalized = cache._normalize_query("find amygdala data", ["amygdala"])
        assert "{entity}" in key3_normalized

        # Different query structure should produce different normalized forms
        key_different = cache._normalize_query("completely different query", [])
        assert key_different != key1_normalized

    def test_cache_ttl(self):
        import time

        from brain_researcher.services.br_kg.knowledge.planner import PlanCache

        cache = PlanCache(ttl_seconds=1)  # 1 second TTL

        plan = KnowledgePlan(
            intent=PlanIntent.EXPLANATION,
            justification="test",
            confidence=0.9,
        )

        cache.set("test_key", plan)
        assert cache.get("test_key") is not None

        # Wait for TTL to expire
        time.sleep(1.1)
        assert cache.get("test_key") is None


class TestToolRouterKnowledgeIntegration:
    """Tests for knowledge-aware tool routing."""

    def test_rank_with_knowledge_evidence(self):
        """Test that tool ranking boosts tools matching evidence."""
        from brain_researcher.services.agent.tool_router import (
            RoutingToolView,
            ToolRouter,
        )
        from brain_researcher.services.tools.tool_registry import ToolRegistry

        # Create minimal registry for testing
        registry = ToolRegistry(auto_discover=False)
        router = ToolRouter(core_registry=registry, chat_whitelist=set())

        # Create mock tool specs
        specs = [
            RoutingToolView(
                runtime_id="glm_tool",
                name="glm_tool",
                description="Run GLM analysis",
                tags=["fmri", "analysis"],
            ),
            RoutingToolView(
                runtime_id="dataset_search",
                name="dataset_search",
                description="Search datasets",
                tags=["dataset_catalog"],
            ),
            RoutingToolView(
                runtime_id="br_kg_query",
                name="br_kg_query",
                description="Query knowledge graph",
                tags=["br_kg"],
            ),
        ]

        # Create mock evidence
        evidence = AggregatedEvidence(
            query="run GLM",
            items=[
                KnowledgeItem(
                    id="tool:glm",
                    source_id="tool_registry",
                    title="glm_tool",
                    score=0.9,
                    metadata={"tool_name": "glm_tool", "tags": ["fmri"]},
                ),
            ],
            confidence=EvidenceConfidence.COMPLETE,
        )

        # Rank with evidence
        ctx = {"knowledge_evidence": evidence}
        ranked = router._rank("run GLM analysis", specs, ctx)

        # GLM tool should be ranked first due to evidence boost
        assert ranked[0].runtime_id == "glm_tool"


class TestChatOrchestratorKnowledgeIntegration:
    """Tests for knowledge gathering in chat orchestrator."""

    def test_knowledge_layer_can_be_disabled(self):
        """Test that knowledge layer can be disabled."""
        from unittest.mock import MagicMock

        from brain_researcher.services.agent.chat_orchestrator import ChatOrchestrator

        mock_router = MagicMock()
        mock_router.route_chat = MagicMock(return_value=MagicMock(text="test response"))

        orchestrator = ChatOrchestrator(
            router=mock_router,
            enable_knowledge_layer=False,
            error_recovery=False,
        )

        # _gather_knowledge_evidence should return None when disabled
        evidence = orchestrator._gather_knowledge_evidence("test query", {})
        assert evidence is None

    def test_structured_context_includes_evidence(self):
        """Test that structured context includes knowledge evidence."""
        from unittest.mock import MagicMock

        from brain_researcher.services.agent.chat_orchestrator import ChatOrchestrator

        mock_router = MagicMock()
        orchestrator = ChatOrchestrator(
            router=mock_router,
            enable_knowledge_layer=False,
            error_recovery=False,
        )

        # Create mock evidence
        evidence = AggregatedEvidence(
            query="test",
            items=[
                KnowledgeItem(
                    id="test:1",
                    source_id="dataset_catalog",
                    title="Test Dataset",
                    score=0.9,
                ),
            ],
            confidence=EvidenceConfidence.COMPLETE,
            sources_succeeded=["dataset_catalog"],
        )

        ctx = {"knowledge_evidence": evidence}
        structured = orchestrator._build_structured_context("test", [], ctx, "thread1")

        assert "Knowledge evidence" in structured
        assert "dataset_catalog" in structured


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
