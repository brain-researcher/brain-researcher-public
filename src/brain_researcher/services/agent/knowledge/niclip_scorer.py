"""NiCLIP-based scoring for knowledge layer evidence.

This module wraps NICLIPEmbeddingService to provide:
- Semantic similarity scoring for text queries against cognitive concepts
- Aggregate scoring for evidence bundles
- NiCLIP-derived evidence items

The scorer operates on pre-computed brain-text aligned embeddings
to provide neuroimaging-aware relevance scoring.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Sequence, Tuple

import numpy as np

from brain_researcher.services.agent.knowledge.evidence_models import (
    EvidenceBundle,
    EvidenceItem,
    EvidenceSourceType,
)

logger = logging.getLogger(__name__)


@dataclass
class ScoredConcept:
    """A cognitive concept with similarity score."""

    term: str
    score: float
    vocabulary_index: int
    prior_probability: float
    vocabulary_type: str


class NiCLIPScorer:
    """Scorer using NiCLIP brain-text embeddings.

    This class provides semantic scoring capabilities by leveraging
    the NiCLIP embedding service which contains pre-computed embeddings
    for cognitive concepts aligned with brain activation patterns.

    Environment Variables:
        NICLIP_DATA_PATH: Override the default NiCLIP data directory path.
                          If not set, defaults to <project_root>/data/niclip.
    """

    # Default data path computed relative to project root
    # Can be overridden by NICLIP_DATA_PATH environment variable
    # Path(__file__).resolve().parents[5] -> <repo>/brain_researcher
    _PROJECT_ROOT = Path(__file__).resolve().parents[5]
    DEFAULT_DATA_PATH = str(_PROJECT_ROOT / "data" / "niclip")

    def __init__(
        self,
        niclip_data_path: Optional[str] = None,
        vocabulary_type: str = "cogatlas_task-names",
        top_k: int = 10,
    ):
        """Initialize the NiCLIP scorer.

        Args:
            niclip_data_path: Path to NiCLIP data directory.
                             Falls back to NICLIP_DATA_PATH env or default.
            vocabulary_type: Which vocabulary to use for scoring:
                - "cogatlas_task-names": Task names (recommended)
                - "cogatlasred_task-names": Reduced 88 tasks
                - "cogatlas_task-definitions": Task definitions
            top_k: Number of top matches to consider for scoring
        """
        self._data_path = (
            niclip_data_path
            or os.environ.get("NICLIP_DATA_PATH")
            or self.DEFAULT_DATA_PATH
        )
        self._vocabulary_type = vocabulary_type
        self._top_k = top_k

        # Lazy-loaded service and cache
        self._service = None
        self._available: Optional[bool] = None
        self._engine = None

        # Cached vocabulary data
        self._vocab_cache: Optional[Tuple[List[str], np.ndarray, np.ndarray]] = None

    def _get_service(self):
        """Lazy-load the NiCLIP embedding service."""
        if self._service is None:
            try:
                if self._engine is None:
                    from brain_researcher.services.br_kg.niclip.engine import (
                        NiclipEngine,
                        NiclipEngineConfig,
                    )

                    cfg = NiclipEngineConfig(data_path=self._data_path)
                    self._engine = NiclipEngine.get(cfg)
                if self._engine is not None:
                    self._service = self._engine.get_embedding_service()
            except Exception as e:
                logger.warning("Failed to load NiCLIP engine: %s", e)
                self._engine = None

            if self._service is None:
                try:
                    from brain_researcher.services.br_kg.niclip.embedding_service import (
                        NICLIPEmbeddingService,
                    )

                    self._service = NICLIPEmbeddingService(self._data_path)
                except Exception as e:
                    logger.warning("Failed to load NiCLIP service: %s", e)
                    self._service = None
        return self._service

    def _get_vocabulary(self) -> Optional[Tuple[List[str], np.ndarray, np.ndarray]]:
        """Get cached vocabulary, embeddings, and priors."""
        if self._vocab_cache is not None:
            return self._vocab_cache

        service = self._get_service()
        if service is None:
            return None

        try:
            vocab, index, priors = service.get_vocabulary_index(self._vocabulary_type)
            # Extract embeddings from index for local scoring
            n_vectors = index.ntotal
            embeddings = np.array(
                [index.reconstruct(i) for i in range(n_vectors)], dtype=np.float32
            )
            self._vocab_cache = (vocab, embeddings, priors)
            return self._vocab_cache
        except Exception as e:
            logger.warning("Failed to load vocabulary: %s", e)
            return None

    async def is_available(self) -> bool:
        """Check if NiCLIP scoring is available.

        Returns:
            True if the service is available and vocabulary is loaded
        """
        if self._available is not None:
            return self._available

        vocab_data = self._get_vocabulary()
        self._available = vocab_data is not None and len(vocab_data[0]) > 0
        return self._available

    def score_text_keyword(self, text: str) -> List[ScoredConcept]:
        """Score text against vocabulary using keyword matching.

        This is a fast scoring method that doesn't require embeddings.

        Args:
            text: Query text to score

        Returns:
            List of scored concepts sorted by score (descending)
        """
        vocab_data = self._get_vocabulary()
        if vocab_data is None:
            return []

        vocab, _, priors = vocab_data
        text_lower = text.lower()
        scored = []

        for i, term in enumerate(vocab):
            term_lower = term.lower()

            # Compute keyword-based score
            if text_lower == term_lower:
                base_score = 1.0
            elif text_lower in term_lower:
                base_score = 0.8
            elif term_lower in text_lower:
                base_score = 0.7
            else:
                # Word overlap
                query_words = set(text_lower.split())
                term_words = set(term_lower.split())
                overlap = query_words.intersection(term_words)
                if overlap:
                    base_score = 0.4 * len(overlap) / max(
                        len(query_words), len(term_words)
                    )
                else:
                    continue  # Skip if no overlap

            # Weight by prior probability
            prior = float(priors[i]) if i < len(priors) else 0.5
            combined_score = 0.7 * base_score + 0.3 * min(prior * 2, 1.0)

            scored.append(
                ScoredConcept(
                    term=term,
                    score=min(combined_score, 1.0),
                    vocabulary_index=i,
                    prior_probability=prior,
                    vocabulary_type=self._vocabulary_type,
                )
            )

        # Sort by score and return top_k
        scored.sort(key=lambda x: x.score, reverse=True)
        return scored[: self._top_k]

    def score_text_semantic(
        self, query_embedding: np.ndarray
    ) -> List[ScoredConcept]:
        """Score using a pre-computed embedding vector.

        This provides full semantic similarity using FAISS.

        Args:
            query_embedding: Pre-computed query embedding (768-dim for NiCLIP)

        Returns:
            List of scored concepts sorted by similarity (descending)
        """
        service = self._get_service()
        if service is None:
            return []

        vocab_data = self._get_vocabulary()
        if vocab_data is None:
            return []

        vocab, _, priors = vocab_data

        try:
            _, index, _ = service.get_vocabulary_index(self._vocabulary_type)
            distances, indices = service.search_similar(
                query_embedding, index, k=self._top_k
            )

            scored = []
            for dist, idx in zip(distances, indices):
                if idx < 0 or idx >= len(vocab):
                    continue

                scored.append(
                    ScoredConcept(
                        term=vocab[idx],
                        score=float(dist),  # Cosine similarity
                        vocabulary_index=int(idx),
                        prior_probability=float(priors[idx])
                        if idx < len(priors)
                        else 0.5,
                        vocabulary_type=self._vocabulary_type,
                    )
                )

            return scored

        except Exception as e:
            logger.warning("Semantic scoring failed: %s", e)
            return []

    def compute_aggregate_score(self, query: str) -> float:
        """Compute aggregate NiCLIP score for a query.

        Returns the average similarity of top-k matches.

        Args:
            query: Text query

        Returns:
            Aggregate score in [0.0, 1.0]
        """
        scored = self.score_text_keyword(query)
        if not scored:
            return 0.0

        # Average of top-k scores, weighted toward top matches
        weights = [1.0 / (i + 1) for i in range(len(scored))]
        weighted_sum = sum(s.score * w for s, w in zip(scored, weights))
        total_weight = sum(weights)

        return weighted_sum / total_weight if total_weight > 0 else 0.0

    def get_evidence_items(self, query: str, limit: int = 5) -> List[EvidenceItem]:
        """Get evidence items from NiCLIP matches.

        Args:
            query: Text query
            limit: Maximum number of items

        Returns:
            List of EvidenceItem objects
        """
        scored = self.score_text_keyword(query)[:limit]

        return [
            EvidenceItem(
                source_type=EvidenceSourceType.NICLIP,
                source_id=f"niclip:{concept.vocabulary_type}:{concept.vocabulary_index}",
                label=concept.term,
                relevance_score=concept.score,
                metadata={
                    "vocabulary_type": concept.vocabulary_type,
                    "vocabulary_index": concept.vocabulary_index,
                    "prior_probability": concept.prior_probability,
                },
            )
            for concept in scored
        ]

    async def enrich_bundle(
        self, bundle: EvidenceBundle, limit: int = 5
    ) -> EvidenceBundle:
        """Enrich an evidence bundle with NiCLIP-derived evidence.

        Adds NiCLIP matches as evidence items and sets the aggregate score.

        Args:
            bundle: The evidence bundle to enrich
            limit: Maximum NiCLIP items to add

        Returns:
            The enriched bundle (mutated in place)
        """
        if not await self.is_available():
            logger.debug("NiCLIP not available, skipping enrichment")
            return bundle

        # Add NiCLIP evidence items
        items = self.get_evidence_items(bundle.query, limit=limit)
        for item in items:
            bundle.add_item(item)

        # Set aggregate score
        bundle.aggregate_niclip_score = self.compute_aggregate_score(bundle.query)

        # Recompute confidence with new NiCLIP score
        bundle.compute_confidence()

        return bundle


class NiCLIPConnector:
    """Evidence connector for NiCLIP that integrates with EvidenceAggregator.

    This connector implements the EvidenceConnector protocol to provide
    NiCLIP evidence items through the standard aggregation interface.
    """

    def __init__(
        self,
        niclip_data_path: Optional[str] = None,
        vocabulary_type: str = "cogatlas_task-names",
    ):
        """Initialize the NiCLIP connector.

        Args:
            niclip_data_path: Path to NiCLIP data directory
            vocabulary_type: Which vocabulary to use
        """
        self._scorer = NiCLIPScorer(
            niclip_data_path=niclip_data_path,
            vocabulary_type=vocabulary_type,
        )

    @property
    def source_name(self) -> str:
        return "niclip"

    @property
    def source_type(self) -> EvidenceSourceType:
        return EvidenceSourceType.NICLIP

    async def search(self, query: str, limit: int = 10) -> List[EvidenceItem]:
        """Search for NiCLIP matches.

        Args:
            query: Text query
            limit: Maximum results

        Returns:
            List of evidence items
        """
        if not await self._scorer.is_available():
            return []

        return self._scorer.get_evidence_items(query, limit=limit)

    async def health_check(self) -> bool:
        """Check if NiCLIP is available."""
        return await self._scorer.is_available()


# Factory function for easy creation
def create_niclip_scorer(
    data_path: Optional[str] = None,
    vocabulary_type: str = "cogatlas_task-names",
) -> NiCLIPScorer:
    """Create a NiCLIP scorer with sensible defaults.

    Args:
        data_path: Optional override for data path
        vocabulary_type: Which vocabulary to use

    Returns:
        Configured NiCLIPScorer instance
    """
    return NiCLIPScorer(
        niclip_data_path=data_path,
        vocabulary_type=vocabulary_type,
    )


__all__ = [
    "NiCLIPConnector",
    "NiCLIPScorer",
    "ScoredConcept",
    "create_niclip_scorer",
]
