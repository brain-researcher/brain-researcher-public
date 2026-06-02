"""Tests for NiCLIP evidence source and scorer."""

import asyncio
import os
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import numpy as np
import pytest

from brain_researcher.services.knowledge.evidence.base import (
    EvidenceBundle,
    EvidenceQuery,
    EvidenceResult,
    EvidenceSourceType,
)
from brain_researcher.services.knowledge.scoring.niclip_scorer import (
    NiCLIPConfig,
    NiCLIPEvidenceSource,
    NiCLIPScorer,
    ScoredConcept,
    create_niclip_source,
    search_niclip,
)


def _niclip_vocab_available() -> bool:
    data_path = os.environ.get("NICLIP_DATA_PATH") or NiCLIPConfig.DEFAULT_DATA_PATH
    if not data_path:
        return False
    path = Path(data_path)
    if not path.exists():
        return False
    if (path / "vocabulary-cogatlas_task.txt").exists():
        return True
    return any(path.glob("vocabulary*"))


def _run_niclip_unit_tests() -> bool:
    if os.getenv("BR_RUN_NICLIP_UNIT_TESTS", "").lower() in {"1", "true", "yes"}:
        return True
    return _niclip_vocab_available()


async def _direct_to_thread(func, *args, **kwargs):
    return func(*args, **kwargs)


@pytest.fixture(autouse=True)
def _disable_niclip_engine(monkeypatch):
    """Force NiCLIP scorer tests to use the embedding service mock."""
    try:
        from brain_researcher.services.br_kg.niclip import engine as niclip_engine
    except Exception:
        yield
        return
    monkeypatch.setattr(niclip_engine.NiclipEngine, "get", lambda *args, **kwargs: None)
    yield


class TestNiCLIPConfig:
    """Test NiCLIPConfig dataclass."""

    def test_default_config(self):
        """Test config with defaults."""
        config = NiCLIPConfig()
        assert config.vocabulary_type == "cogatlas_task-names"
        assert config.top_k == 10
        assert config.use_semantic is False
        assert config.default_confidence == 0.75

    def test_config_with_custom_values(self):
        """Test config with custom values."""
        config = NiCLIPConfig(
            data_path="/custom/path",
            vocabulary_type="cogatlasred_task-names",
            top_k=20,
            use_semantic=True,
        )
        assert config.data_path == "/custom/path"
        assert config.vocabulary_type == "cogatlasred_task-names"
        assert config.top_k == 20
        assert config.use_semantic is True

    @patch.dict("os.environ", {"NICLIP_DATA_PATH": "/env/niclip/path"})
    def test_config_uses_env_var(self):
        """Test config reads NICLIP_DATA_PATH from environment."""
        config = NiCLIPConfig()
        assert config.data_path == "/env/niclip/path"


class TestScoredConcept:
    """Test ScoredConcept dataclass."""

    def test_scored_concept_creation(self):
        """Test creating a scored concept."""
        concept = ScoredConcept(
            term="Motor Learning",
            score=0.85,
            vocabulary_index=42,
            prior_probability=0.15,
            vocabulary_type="cogatlas_task-names",
        )
        assert concept.term == "Motor Learning"
        assert concept.score == 0.85
        assert concept.vocabulary_index == 42
        assert concept.prior_probability == 0.15
        assert concept.vocabulary_type == "cogatlas_task-names"


class TestNiCLIPEvidenceSource:
    """Test suite for NiCLIPEvidenceSource."""

    def setup_method(self):
        """Set up test fixtures."""
        self.source = NiCLIPEvidenceSource(
            data_path="/test/data",
            vocabulary_type="cogatlas_task-names",
            top_k=5,
        )

    def test_source_properties(self):
        """Test source type and id properties."""
        assert self.source.source_type == EvidenceSourceType.NICLIP
        assert self.source.source_id == "niclip:cogatlas_task-names"

    def test_source_with_config(self):
        """Test source creation with config object."""
        config = NiCLIPConfig(
            data_path="/config/path",
            vocabulary_type="cogatlasred_task-names",
            top_k=15,
        )
        source = NiCLIPEvidenceSource(config=config)
        assert source._config.data_path == "/config/path"
        assert source._config.vocabulary_type == "cogatlasred_task-names"
        assert source._config.top_k == 15

    @patch(
        "brain_researcher.services.br_kg.niclip.embedding_service.NICLIPEmbeddingService"
    )
    @pytest.mark.skipif(
        not _run_niclip_unit_tests(),
        reason="NiCLIP vocab/engine unavailable; set BR_RUN_NICLIP_UNIT_TESTS=1 or provide vocab files.",
    )
    def test_lazy_service_creation(self, mock_service_class):
        """Test embedding service is lazily created."""
        mock_service = MagicMock()
        mock_service_class.return_value = mock_service

        source = NiCLIPEvidenceSource(data_path="/test/path")
        service = source._get_service()

        mock_service_class.assert_called_once_with("/test/path")
        assert service is mock_service

    @patch(
        "brain_researcher.services.br_kg.niclip.embedding_service.NICLIPEmbeddingService"
    )
    @pytest.mark.skipif(
        not _run_niclip_unit_tests(),
        reason="NiCLIP vocab/engine unavailable; set BR_RUN_NICLIP_UNIT_TESTS=1 or provide vocab files.",
    )
    def test_service_reused(self, mock_service_class):
        """Test service is reused on subsequent calls."""
        mock_service = MagicMock()
        mock_service_class.return_value = mock_service

        source = NiCLIPEvidenceSource(data_path="/test/path")
        service1 = source._get_service()
        service2 = source._get_service()

        mock_service_class.assert_called_once()
        assert service1 is service2

    @patch(
        "brain_researcher.services.br_kg.niclip.embedding_service.NICLIPEmbeddingService"
    )
    @pytest.mark.skipif(
        not _run_niclip_unit_tests(),
        reason="NiCLIP vocab/engine unavailable; set BR_RUN_NICLIP_UNIT_TESTS=1 or provide vocab files.",
    )
    def test_vocabulary_loading(self, mock_service_class):
        """Test vocabulary is loaded from service."""
        # Setup mock
        mock_index = MagicMock()
        mock_index.ntotal = 3
        mock_index.reconstruct.side_effect = [
            np.array([0.1, 0.2, 0.3], dtype=np.float32),
            np.array([0.4, 0.5, 0.6], dtype=np.float32),
            np.array([0.7, 0.8, 0.9], dtype=np.float32),
        ]

        mock_service = MagicMock()
        mock_service.get_vocabulary_index.return_value = (
            ["Motor Learning", "Visual Perception", "Working Memory"],
            mock_index,
            np.array([0.1, 0.2, 0.3]),
        )
        mock_service_class.return_value = mock_service

        source = NiCLIPEvidenceSource(data_path="/test/path")
        vocab_data = source._get_vocabulary()

        assert vocab_data is not None
        vocab, embeddings, priors = vocab_data
        assert len(vocab) == 3
        assert vocab[0] == "Motor Learning"
        assert embeddings.shape == (3, 3)

    @patch(
        "brain_researcher.services.br_kg.niclip.embedding_service.NICLIPEmbeddingService"
    )
    @pytest.mark.skipif(
        not _run_niclip_unit_tests(),
        reason="NiCLIP vocab/engine unavailable; set BR_RUN_NICLIP_UNIT_TESTS=1 or provide vocab files.",
    )
    def test_keyword_scoring_exact_match(self, mock_service_class):
        """Test keyword scoring with exact match."""
        mock_index = MagicMock()
        mock_index.ntotal = 3
        mock_index.reconstruct.side_effect = [
            np.zeros(768, dtype=np.float32) for _ in range(3)
        ]

        mock_service = MagicMock()
        mock_service.get_vocabulary_index.return_value = (
            ["motor learning", "visual perception", "working memory"],
            mock_index,
            np.array([0.3, 0.4, 0.3]),
        )
        mock_service_class.return_value = mock_service

        source = NiCLIPEvidenceSource(data_path="/test/path", top_k=10)
        concepts = source._score_keyword("motor learning")

        assert len(concepts) > 0
        assert concepts[0].term == "motor learning"
        assert concepts[0].score >= 0.8  # Exact match should have high score

    @patch(
        "brain_researcher.services.br_kg.niclip.embedding_service.NICLIPEmbeddingService"
    )
    @pytest.mark.skipif(
        not _run_niclip_unit_tests(),
        reason="NiCLIP vocab/engine unavailable; set BR_RUN_NICLIP_UNIT_TESTS=1 or provide vocab files.",
    )
    def test_keyword_scoring_partial_match(self, mock_service_class):
        """Test keyword scoring with partial match."""
        mock_index = MagicMock()
        mock_index.ntotal = 3
        mock_index.reconstruct.side_effect = [
            np.zeros(768, dtype=np.float32) for _ in range(3)
        ]

        mock_service = MagicMock()
        mock_service.get_vocabulary_index.return_value = (
            ["motor learning", "motor cortex activation", "visual perception"],
            mock_index,
            np.array([0.3, 0.3, 0.4]),
        )
        mock_service_class.return_value = mock_service

        source = NiCLIPEvidenceSource(data_path="/test/path", top_k=10)
        concepts = source._score_keyword("motor")

        # Should match both motor-related terms
        assert len(concepts) >= 2
        terms = [c.term for c in concepts]
        assert "motor learning" in terms
        assert "motor cortex activation" in terms

    @patch(
        "brain_researcher.services.br_kg.niclip.embedding_service.NICLIPEmbeddingService"
    )
    def test_keyword_scoring_no_match(self, mock_service_class):
        """Test keyword scoring with no matches."""
        mock_index = MagicMock()
        mock_index.ntotal = 3
        mock_index.reconstruct.side_effect = [
            np.zeros(768, dtype=np.float32) for _ in range(3)
        ]

        mock_service = MagicMock()
        mock_service.get_vocabulary_index.return_value = (
            ["motor learning", "visual perception", "working memory"],
            mock_index,
            np.array([0.3, 0.4, 0.3]),
        )
        mock_service_class.return_value = mock_service

        source = NiCLIPEvidenceSource(data_path="/test/path", top_k=10)
        concepts = source._score_keyword("xyz123nonexistent")

        assert len(concepts) == 0

    @patch(
        "brain_researcher.services.br_kg.niclip.embedding_service.NICLIPEmbeddingService"
    )
    def test_query_sync_returns_evidence_results(self, mock_service_class):
        """Test query_sync returns EvidenceResult objects."""
        mock_index = MagicMock()
        mock_index.ntotal = 2
        mock_index.reconstruct.side_effect = [
            np.zeros(768, dtype=np.float32) for _ in range(2)
        ]

        mock_service = MagicMock()
        mock_service.get_vocabulary_index.return_value = (
            ["motor learning", "motor cortex"],
            mock_index,
            np.array([0.4, 0.6]),
        )
        mock_service_class.return_value = mock_service

        source = NiCLIPEvidenceSource(data_path="/test/path", top_k=10)
        query = EvidenceQuery(text="motor", limit=5)
        results = source.query_sync(query)

        assert len(results) > 0
        assert all(isinstance(r, EvidenceResult) for r in results)
        assert results[0].source == EvidenceSourceType.NICLIP
        assert "niclip:" in results[0].id
        assert results[0].payload.get("cognitive_atlas_concept") is True

    @patch(
        "brain_researcher.services.br_kg.niclip.embedding_service.NICLIPEmbeddingService"
    )
    def test_query_sync_respects_limit(self, mock_service_class):
        """Test query_sync respects limit parameter."""
        mock_index = MagicMock()
        mock_index.ntotal = 5
        mock_index.reconstruct.side_effect = [
            np.zeros(768, dtype=np.float32) for _ in range(5)
        ]

        mock_service = MagicMock()
        mock_service.get_vocabulary_index.return_value = (
            ["motor 1", "motor 2", "motor 3", "motor 4", "motor 5"],
            mock_index,
            np.array([0.2] * 5),
        )
        mock_service_class.return_value = mock_service

        source = NiCLIPEvidenceSource(data_path="/test/path", top_k=10)
        query = EvidenceQuery(text="motor", limit=2)
        results = source.query_sync(query)

        assert len(results) <= 2

    @patch.object(NiCLIPEvidenceSource, "_get_service", return_value=None)
    def test_query_sync_unavailable_service(self, mock_get_service):
        """Test query_sync handles unavailable service gracefully."""
        if _run_niclip_unit_tests():
            pytest.skip(
                "NiCLIP unit tests enabled; unavailable-service test not applicable"
            )
        source = NiCLIPEvidenceSource(data_path="/nonexistent/path")
        query = EvidenceQuery(text="test")
        results = source.query_sync(query)

        assert results == []

    @pytest.mark.asyncio
    @patch(
        "brain_researcher.services.br_kg.niclip.embedding_service.NICLIPEmbeddingService"
    )
    @pytest.mark.skipif(
        not _run_niclip_unit_tests(),
        reason="NiCLIP vocab/engine unavailable; set BR_RUN_NICLIP_UNIT_TESTS=1 or provide vocab files.",
    )
    async def test_async_query(self, mock_service_class, monkeypatch):
        """Test async query method."""
        monkeypatch.setattr(asyncio, "to_thread", _direct_to_thread)
        mock_index = MagicMock()
        mock_index.ntotal = 2
        mock_index.reconstruct.side_effect = [
            np.zeros(768, dtype=np.float32) for _ in range(2)
        ]

        mock_service = MagicMock()
        mock_service.get_vocabulary_index.return_value = (
            ["motor learning", "motor task"],
            mock_index,
            np.array([0.5, 0.5]),
        )
        mock_service_class.return_value = mock_service

        source = NiCLIPEvidenceSource(data_path="/test/path")
        query = EvidenceQuery(text="motor")
        results = await source.query(query)

        assert len(results) > 0
        assert results[0].source == EvidenceSourceType.NICLIP

    @pytest.mark.asyncio
    @patch(
        "brain_researcher.services.br_kg.niclip.embedding_service.NICLIPEmbeddingService"
    )
    @pytest.mark.skipif(
        not _run_niclip_unit_tests(),
        reason="NiCLIP vocab/engine unavailable; set BR_RUN_NICLIP_UNIT_TESTS=1 or provide vocab files.",
    )
    async def test_health_check_available(self, mock_service_class, monkeypatch):
        """Test health check when service is available."""
        monkeypatch.setattr(asyncio, "to_thread", _direct_to_thread)
        mock_index = MagicMock()
        mock_index.ntotal = 3
        mock_index.reconstruct.side_effect = [
            np.zeros(768, dtype=np.float32) for _ in range(3)
        ]

        mock_service = MagicMock()
        mock_service.get_vocabulary_index.return_value = (
            ["term1", "term2", "term3"],
            mock_index,
            np.array([0.3, 0.3, 0.4]),
        )
        mock_service_class.return_value = mock_service

        source = NiCLIPEvidenceSource(data_path="/test/path")
        result = await source.health_check()

        assert result is True

    @pytest.mark.asyncio
    @patch.object(NiCLIPEvidenceSource, "_get_service", return_value=None)
    async def test_health_check_unavailable(self, mock_get_service, monkeypatch):
        """Test health check when service is unavailable."""
        monkeypatch.setattr(asyncio, "to_thread", _direct_to_thread)
        if _run_niclip_unit_tests():
            pytest.skip(
                "NiCLIP unit tests enabled; unavailable-service test not applicable"
            )
        source = NiCLIPEvidenceSource(data_path="/nonexistent/path")
        result = await source.health_check()

        assert result is False


class TestNiCLIPScorer:
    """Test suite for NiCLIPScorer."""

    def _create_mock_service(self):
        """Create a mock NiCLIP service with vocabulary."""
        mock_index = MagicMock()
        mock_index.ntotal = 5
        mock_index.reconstruct.side_effect = [
            np.zeros(768, dtype=np.float32) for _ in range(5)
        ]

        mock_service = MagicMock()
        mock_service.get_vocabulary_index.return_value = (
            [
                "motor learning",
                "visual perception",
                "working memory",
                "attention",
                "motor cortex",
            ],
            mock_index,
            np.array([0.2, 0.25, 0.2, 0.15, 0.2]),
        )
        return mock_service

    @patch(
        "brain_researcher.services.br_kg.niclip.embedding_service.NICLIPEmbeddingService"
    )
    def test_scorer_initialization(self, mock_service_class):
        """Test scorer initialization."""
        scorer = NiCLIPScorer(data_path="/test/path", top_k=15)
        assert scorer._config.data_path == "/test/path"
        assert scorer._config.top_k == 15

    @patch(
        "brain_researcher.services.br_kg.niclip.embedding_service.NICLIPEmbeddingService"
    )
    @pytest.mark.skipif(
        not _run_niclip_unit_tests(),
        reason="NiCLIP vocab/engine unavailable; set BR_RUN_NICLIP_UNIT_TESTS=1 or provide vocab files.",
    )
    def test_score_text(self, mock_service_class):
        """Test score_text method."""
        mock_service_class.return_value = self._create_mock_service()

        scorer = NiCLIPScorer(data_path="/test/path")
        concepts = scorer.score_text("motor")

        assert len(concepts) > 0
        # Should match motor-related terms
        terms = [c.term for c in concepts]
        assert "motor learning" in terms or "motor cortex" in terms

    @patch(
        "brain_researcher.services.br_kg.niclip.embedding_service.NICLIPEmbeddingService"
    )
    @pytest.mark.skipif(
        not _run_niclip_unit_tests(),
        reason="NiCLIP vocab/engine unavailable; set BR_RUN_NICLIP_UNIT_TESTS=1 or provide vocab files.",
    )
    def test_compute_aggregate_score(self, mock_service_class):
        """Test aggregate score computation."""
        mock_service_class.return_value = self._create_mock_service()

        scorer = NiCLIPScorer(data_path="/test/path")
        score = scorer.compute_aggregate_score("motor learning")

        assert 0.0 <= score <= 1.0
        assert score > 0.5  # Exact match should have high aggregate score

    @patch(
        "brain_researcher.services.br_kg.niclip.embedding_service.NICLIPEmbeddingService"
    )
    def test_compute_aggregate_score_no_match(self, mock_service_class):
        """Test aggregate score with no matches."""
        mock_service_class.return_value = self._create_mock_service()

        scorer = NiCLIPScorer(data_path="/test/path")
        score = scorer.compute_aggregate_score("xyz123nonexistent")

        assert score == 0.0

    @patch(
        "brain_researcher.services.br_kg.niclip.embedding_service.NICLIPEmbeddingService"
    )
    def test_get_top_concepts(self, mock_service_class):
        """Test get_top_concepts returns concept names."""
        mock_service_class.return_value = self._create_mock_service()

        scorer = NiCLIPScorer(data_path="/test/path")
        concepts = scorer.get_top_concepts("motor", limit=3)

        assert isinstance(concepts, list)
        assert all(isinstance(c, str) for c in concepts)
        assert len(concepts) <= 3

    @pytest.mark.asyncio
    @patch(
        "brain_researcher.services.br_kg.niclip.embedding_service.NICLIPEmbeddingService"
    )
    async def test_is_available(self, mock_service_class):
        """Test is_available async method."""
        mock_service_class.return_value = self._create_mock_service()

        scorer = NiCLIPScorer(data_path="/test/path")
        available = await scorer.is_available()

        assert available is True

    @pytest.mark.asyncio
    @patch(
        "brain_researcher.services.br_kg.niclip.embedding_service.NICLIPEmbeddingService"
    )
    async def test_enrich_bundle(self, mock_service_class):
        """Test bundle enrichment with NiCLIP results."""
        mock_service_class.return_value = self._create_mock_service()

        scorer = NiCLIPScorer(data_path="/test/path")

        bundle = EvidenceBundle(
            query_interpretation={"original_query": "motor learning fmri"},
            metadata={},
        )

        enriched = await scorer.enrich_bundle(bundle, limit=3)

        # Should have added NiCLIP concepts
        niclip_concepts = [
            c for c in enriched.concepts if c.source == EvidenceSourceType.NICLIP
        ]
        assert len(niclip_concepts) > 0
        assert "niclip_aggregate_score" in enriched.metadata

    @pytest.mark.asyncio
    @patch(
        "brain_researcher.services.br_kg.niclip.embedding_service.NICLIPEmbeddingService"
    )
    async def test_enrich_bundle_avoids_duplicates(self, mock_service_class):
        """Test bundle enrichment doesn't duplicate concepts."""
        mock_service_class.return_value = self._create_mock_service()

        scorer = NiCLIPScorer(data_path="/test/path")

        # Pre-populate with a NiCLIP concept
        existing = EvidenceResult(
            source=EvidenceSourceType.NICLIP,
            id="niclip:cogatlas_task-names:0",
            title="motor learning",
            relevance_score=0.9,
            confidence=0.75,
        )

        bundle = EvidenceBundle(
            concepts=[existing],
            query_interpretation={"original_query": "motor learning"},
            metadata={},
        )

        enriched = await scorer.enrich_bundle(bundle, limit=5)

        # Should not have duplicates
        ids = [c.id for c in enriched.concepts]
        assert len(ids) == len(set(ids))


class TestConvenienceFunctions:
    """Test convenience functions."""

    @patch(
        "brain_researcher.services.br_kg.niclip.embedding_service.NICLIPEmbeddingService"
    )
    def test_search_niclip(self, mock_service_class):
        """Test search_niclip convenience function."""
        mock_index = MagicMock()
        mock_index.ntotal = 3
        mock_index.reconstruct.side_effect = [
            np.zeros(768, dtype=np.float32) for _ in range(3)
        ]

        mock_service = MagicMock()
        mock_service.get_vocabulary_index.return_value = (
            ["motor learning", "motor cortex", "motor task"],
            mock_index,
            np.array([0.3, 0.4, 0.3]),
        )
        mock_service_class.return_value = mock_service

        results = search_niclip("motor", limit=5)

        assert len(results) > 0
        assert all(isinstance(r, EvidenceResult) for r in results)
        assert results[0].source == EvidenceSourceType.NICLIP

    @patch(
        "brain_researcher.services.br_kg.niclip.embedding_service.NICLIPEmbeddingService"
    )
    def test_create_niclip_source(self, mock_service_class):
        """Test create_niclip_source factory function."""
        source = create_niclip_source(
            data_path="/test/path",
            vocabulary_type="cogatlasred_task-names",
            top_k=20,
        )

        assert isinstance(source, NiCLIPEvidenceSource)
        assert source._config.data_path == "/test/path"
        assert source._config.vocabulary_type == "cogatlasred_task-names"
        assert source._config.top_k == 20
