"""Unit tests for niclip_scorer.py."""

from unittest.mock import patch

import numpy as np
import pytest

from brain_researcher.services.agent.knowledge.evidence_models import (
    EvidenceBundle,
    EvidenceSourceType,
)
from brain_researcher.services.agent.knowledge.niclip_scorer import (
    NiCLIPConnector,
    NiCLIPScorer,
    ScoredConcept,
    create_niclip_scorer,
)


class MockFaissIndex:
    """Mock FAISS index."""

    def __init__(self, n_vectors: int, dim: int = 768):
        self.ntotal = n_vectors
        self._vectors = np.random.randn(n_vectors, dim).astype(np.float32)

    def reconstruct(self, i: int) -> np.ndarray:
        return self._vectors[i]


class MockEmbeddingService:
    """Mock for NICLIPEmbeddingService."""

    def __init__(self, vocab_size: int = 10):
        self.vocab = [
            "working memory",
            "motor control",
            "visual attention",
            "language processing",
            "decision making",
            "emotional regulation",
            "spatial navigation",
            "face recognition",
            "motor imagery",
            "cognitive control",
        ][:vocab_size]
        self.priors = np.ones(vocab_size) / vocab_size
        self._index = MockFaissIndex(vocab_size)

    def get_vocabulary_index(self, vocab_type: str):
        return self.vocab, self._index, self.priors

    def search_similar(self, embedding, index, k: int = 10):
        # Return mock distances and indices
        k = min(k, len(self.vocab))
        distances = np.linspace(0.95, 0.5, k).astype(np.float32)
        indices = np.arange(k, dtype=np.int64)
        return distances, indices


class TestScoredConcept:
    """Tests for ScoredConcept dataclass."""

    def test_creation(self):
        """Test creating a scored concept."""
        concept = ScoredConcept(
            term="working memory",
            score=0.85,
            vocabulary_index=0,
            prior_probability=0.1,
            vocabulary_type="cogatlas_task-names",
        )
        assert concept.term == "working memory"
        assert concept.score == 0.85
        assert concept.vocabulary_index == 0


class TestNiCLIPScorer:
    """Tests for NiCLIPScorer."""

    def test_initialization(self):
        """Test scorer initialization."""
        scorer = NiCLIPScorer(
            niclip_data_path="/test/path",
            vocabulary_type="cogatlasred_task-names",
            top_k=5,
        )
        assert scorer._data_path == "/test/path"
        assert scorer._vocabulary_type == "cogatlasred_task-names"
        assert scorer._top_k == 5

    def test_score_text_keyword_exact_match(self):
        """Test keyword scoring with exact match."""
        mock_service = MockEmbeddingService()

        with patch(
            "brain_researcher.services.br_kg.niclip.embedding_service.NICLIPEmbeddingService",
            return_value=mock_service,
        ):
            scorer = NiCLIPScorer()
            scorer._service = mock_service
            scorer._vocab_cache = (
                mock_service.vocab,
                np.random.randn(10, 768).astype(np.float32),
                mock_service.priors,
            )

            results = scorer.score_text_keyword("working memory")

            assert len(results) > 0
            # Exact match should have highest score
            assert results[0].term == "working memory"
            # Score is combined: 0.7 * base + 0.3 * prior. With low priors, expect ~0.7+
            assert results[0].score >= 0.7

    def test_score_text_keyword_partial_match(self):
        """Test keyword scoring with partial match."""
        mock_service = MockEmbeddingService()

        with patch(
            "brain_researcher.services.br_kg.niclip.embedding_service.NICLIPEmbeddingService",
            return_value=mock_service,
        ):
            scorer = NiCLIPScorer()
            scorer._service = mock_service
            scorer._vocab_cache = (
                mock_service.vocab,
                np.random.randn(10, 768).astype(np.float32),
                mock_service.priors,
            )

            # "motor" should match "motor control" and "motor imagery"
            results = scorer.score_text_keyword("motor")

            motor_terms = [r.term for r in results if "motor" in r.term.lower()]
            assert len(motor_terms) >= 1

    def test_score_text_keyword_no_match(self):
        """Test keyword scoring with no match."""
        mock_service = MockEmbeddingService()

        scorer = NiCLIPScorer()
        scorer._service = mock_service
        scorer._vocab_cache = (
            mock_service.vocab,
            np.random.randn(10, 768).astype(np.float32),
            mock_service.priors,
        )

        results = scorer.score_text_keyword("xyz_nonexistent_term_abc")
        assert len(results) == 0

    def test_compute_aggregate_score(self):
        """Test aggregate score computation."""
        mock_service = MockEmbeddingService()

        scorer = NiCLIPScorer()
        scorer._service = mock_service
        scorer._vocab_cache = (
            mock_service.vocab,
            np.random.randn(10, 768).astype(np.float32),
            mock_service.priors,
        )

        score = scorer.compute_aggregate_score("working memory")
        assert 0.0 < score <= 1.0

    def test_compute_aggregate_score_no_match(self):
        """Test aggregate score with no matches."""
        mock_service = MockEmbeddingService()

        scorer = NiCLIPScorer()
        scorer._service = mock_service
        scorer._vocab_cache = (
            mock_service.vocab,
            np.random.randn(10, 768).astype(np.float32),
            mock_service.priors,
        )

        score = scorer.compute_aggregate_score("xyz_nonexistent")
        assert score == 0.0

    def test_get_evidence_items(self):
        """Test getting evidence items."""
        mock_service = MockEmbeddingService()

        scorer = NiCLIPScorer()
        scorer._service = mock_service
        scorer._vocab_cache = (
            mock_service.vocab,
            np.random.randn(10, 768).astype(np.float32),
            mock_service.priors,
        )

        items = scorer.get_evidence_items("motor", limit=3)

        assert len(items) <= 3
        for item in items:
            assert item.source_type == EvidenceSourceType.NICLIP
            assert item.source_id.startswith("niclip:")

    @pytest.mark.asyncio
    async def test_is_available_when_service_works(self):
        """Test availability check when service works."""
        mock_service = MockEmbeddingService()

        scorer = NiCLIPScorer()
        scorer._service = mock_service
        scorer._vocab_cache = (
            mock_service.vocab,
            np.random.randn(10, 768).astype(np.float32),
            mock_service.priors,
        )

        result = await scorer.is_available()
        assert result is True

    @pytest.mark.asyncio
    async def test_is_available_when_service_fails(self):
        """Test availability check when service fails."""
        scorer = NiCLIPScorer()
        scorer._service = None
        scorer._available = None

        # Mock _get_vocabulary to return None
        with patch.object(scorer, "_get_vocabulary", return_value=None):
            result = await scorer.is_available()
            assert result is False

    @pytest.mark.asyncio
    async def test_enrich_bundle(self):
        """Test bundle enrichment."""
        mock_service = MockEmbeddingService()

        scorer = NiCLIPScorer()
        scorer._service = mock_service
        scorer._vocab_cache = (
            mock_service.vocab,
            np.random.randn(10, 768).astype(np.float32),
            mock_service.priors,
        )
        scorer._available = True

        bundle = EvidenceBundle(query="motor control")
        enriched = await scorer.enrich_bundle(bundle, limit=3)

        # Should have added NiCLIP items
        niclip_items = [
            i for i in enriched.items if i.source_type == EvidenceSourceType.NICLIP
        ]
        assert len(niclip_items) <= 3
        assert enriched.aggregate_niclip_score > 0.0


class TestNiCLIPConnector:
    """Tests for NiCLIPConnector."""

    def test_source_properties(self):
        """Test connector properties."""
        connector = NiCLIPConnector()
        assert connector.source_name == "niclip"
        assert connector.source_type == EvidenceSourceType.NICLIP

    @pytest.mark.asyncio
    async def test_search_when_available(self):
        """Test search when service is available."""
        mock_service = MockEmbeddingService()

        connector = NiCLIPConnector()
        connector._scorer._service = mock_service
        connector._scorer._vocab_cache = (
            mock_service.vocab,
            np.random.randn(10, 768).astype(np.float32),
            mock_service.priors,
        )
        connector._scorer._available = True

        items = await connector.search("motor", limit=5)

        assert len(items) <= 5
        for item in items:
            assert item.source_type == EvidenceSourceType.NICLIP

    @pytest.mark.asyncio
    async def test_search_when_unavailable(self):
        """Test search when service is unavailable."""
        connector = NiCLIPConnector()
        connector._scorer._available = False

        items = await connector.search("motor")
        assert items == []

    @pytest.mark.asyncio
    async def test_health_check(self):
        """Test health check."""
        mock_service = MockEmbeddingService()

        connector = NiCLIPConnector()
        connector._scorer._service = mock_service
        connector._scorer._vocab_cache = (
            mock_service.vocab,
            np.random.randn(10, 768).astype(np.float32),
            mock_service.priors,
        )
        connector._scorer._available = True

        result = await connector.health_check()
        assert result is True


class TestCreateNiCLIPScorer:
    """Tests for factory function."""

    def test_create_with_defaults(self):
        """Test creating scorer with defaults."""
        scorer = create_niclip_scorer()
        assert scorer._vocabulary_type == "cogatlas_task-names"

    def test_create_with_custom_params(self):
        """Test creating scorer with custom parameters."""
        scorer = create_niclip_scorer(
            data_path="/custom/path",
            vocabulary_type="cogatlasred_task-names",
        )
        assert scorer._data_path == "/custom/path"
        assert scorer._vocabulary_type == "cogatlasred_task-names"
