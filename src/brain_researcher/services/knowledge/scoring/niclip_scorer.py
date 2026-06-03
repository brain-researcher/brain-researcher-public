"""NiCLIP-based evidence source for the Knowledge Layer.

This module provides:
- NiCLIPEvidenceSource: Evidence source adapter for NiCLIP embeddings
- Scoring utilities for cognitive concept similarity
- Integration with the unified evidence system

The scorer leverages pre-computed brain-text aligned embeddings from NiCLIP
to provide neuroimaging-aware relevance scoring against cognitive vocabularies.
"""

from __future__ import annotations

import asyncio
import logging
import os
from dataclasses import dataclass, field
from typing import List, Optional, Sequence, Tuple

import numpy as np

from brain_researcher.services.knowledge.evidence.base import (
    EvidenceBundle,
    EvidenceQuery,
    EvidenceResult,
    EvidenceSource,
    EvidenceSourceType,
)

logger = logging.getLogger(__name__)


@dataclass
class ScoredConcept:
    """A cognitive concept with similarity score from NiCLIP matching."""

    term: str
    score: float
    vocabulary_index: int
    prior_probability: float
    vocabulary_type: str


@dataclass
class NiCLIPConfig:
    """Configuration for NiCLIP scoring."""

    data_path: Optional[str] = None
    vocabulary_type: str = "cogatlas_task-names"
    top_k: int = 10
    use_semantic: bool = False  # If True, requires query embeddings
    default_confidence: float = 0.75  # NiCLIP confidence score

    # Default data path (can be overridden by NICLIP_DATA_PATH env var)
    DEFAULT_DATA_PATH: str = field(
        default="/app/data/niclip",
        repr=False,
    )

    def __post_init__(self):
        if self.data_path is None:
            self.data_path = (
                os.environ.get("NICLIP_DATA_PATH") or self.DEFAULT_DATA_PATH
            )


class NiCLIPEvidenceSource(EvidenceSource):
    """Evidence source adapter for NiCLIP brain-text embeddings.

    This adapter provides evidence items from the NiCLIP vocabulary,
    which contains cognitive concepts aligned with brain activation patterns.
    Supports both keyword-based and semantic (embedding-based) matching.

    Implements the EvidenceSource protocol for integration with the
    Knowledge Layer aggregator.
    """

    def __init__(
        self,
        config: Optional[NiCLIPConfig] = None,
        data_path: Optional[str] = None,
        vocabulary_type: str = "cogatlas_task-names",
        top_k: int = 10,
    ):
        """Initialize the NiCLIP evidence source.

        Args:
            config: Full configuration object (overrides other params)
            data_path: Path to NiCLIP data directory
            vocabulary_type: Which vocabulary to use:
                - "cogatlas_task-names": Task names (recommended)
                - "cogatlasred_task-names": Reduced 88 tasks
                - "cogatlas_task-definitions": Task definitions
            top_k: Number of top matches to return
        """
        if config:
            self._config = config
        else:
            self._config = NiCLIPConfig(
                data_path=data_path,
                vocabulary_type=vocabulary_type,
                top_k=top_k,
            )

        # Lazy-loaded service and caches
        self._service = None
        self._available: Optional[bool] = None
        self._engine = None
        self._vocab_cache: Optional[Tuple[List[str], np.ndarray, np.ndarray]] = None

    @property
    def source_type(self) -> EvidenceSourceType:
        """Return the evidence source type."""
        return EvidenceSourceType.NICLIP

    @property
    def source_id(self) -> str:
        """Return unique identifier for this source."""
        return f"niclip:{self._config.vocabulary_type}"

    def _get_service(self):
        """Lazy-load the NiCLIP embedding service."""
        if self._service is None:
            try:
                if self._engine is None:
                    from brain_researcher.services.br_kg.niclip.engine import (
                        NiclipEngine,
                        NiclipEngineConfig,
                    )

                    cfg = NiclipEngineConfig(data_path=self._config.data_path)
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

                    self._service = NICLIPEmbeddingService(self._config.data_path)
                except Exception as e:
                    logger.warning("Failed to load NiCLIP service: %s", e)
                    self._service = None
        return self._service

    def _get_vocabulary(self) -> Optional[Tuple[List[str], np.ndarray, np.ndarray]]:
        """Get cached vocabulary, embeddings, and priors.

        Returns:
            Tuple of (vocabulary list, embeddings array, priors array)
            or None if unavailable
        """
        if self._vocab_cache is not None:
            return self._vocab_cache

        service = self._get_service()
        if service is None:
            return None

        try:
            vocab, index, priors = service.get_vocabulary_index(
                self._config.vocabulary_type
            )
            # Extract embeddings from FAISS index for local scoring
            n_vectors = index.ntotal
            embeddings = np.array(
                [index.reconstruct(i) for i in range(n_vectors)], dtype=np.float32
            )
            self._vocab_cache = (vocab, embeddings, priors)
            return self._vocab_cache
        except Exception as e:
            logger.warning("Failed to load vocabulary: %s", e)
            return None

    def _score_keyword(self, text: str) -> List[ScoredConcept]:
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
                    vocabulary_type=self._config.vocabulary_type,
                )
            )

        # Sort by score and return top_k
        scored.sort(key=lambda x: x.score, reverse=True)
        return scored[: self._config.top_k]

    def _score_semantic(self, query_embedding: np.ndarray) -> List[ScoredConcept]:
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
            _, index, _ = service.get_vocabulary_index(self._config.vocabulary_type)
            distances, indices = service.search_similar(
                query_embedding, index, k=self._config.top_k
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
                        vocabulary_type=self._config.vocabulary_type,
                    )
                )

            return scored

        except Exception as e:
            logger.warning("Semantic scoring failed: %s", e)
            return []

    def _concepts_to_results(
        self, concepts: List[ScoredConcept]
    ) -> List[EvidenceResult]:
        """Convert scored concepts to evidence results."""
        return [
            EvidenceResult(
                source=self.source_type,
                id=f"niclip:{concept.vocabulary_type}:{concept.vocabulary_index}",
                title=concept.term,
                relevance_score=concept.score,
                confidence=self._config.default_confidence,
                payload={
                    "vocabulary_type": concept.vocabulary_type,
                    "vocabulary_index": concept.vocabulary_index,
                    "prior_probability": concept.prior_probability,
                    "cognitive_atlas_concept": True,
                },
                url=self._get_cognitive_atlas_url(concept.term),
                summary=f"Cognitive concept: {concept.term} (prior: {concept.prior_probability:.3f})",
            )
            for concept in concepts
        ]

    def _get_cognitive_atlas_url(self, term: str) -> Optional[str]:
        """Generate Cognitive Atlas URL for a concept if applicable."""
        # Simple URL generation - could be enhanced with actual ID lookup
        slug = term.lower().replace(" ", "-").replace("_", "-")
        return f"https://www.cognitiveatlas.org/concept/id/{slug}"

    def query_sync(self, query: EvidenceQuery) -> List[EvidenceResult]:
        """Synchronous query implementation.

        Args:
            query: The evidence query with text and optional embedding

        Returns:
            List of evidence results from NiCLIP vocabulary
        """
        if not self._get_vocabulary():
            logger.debug("NiCLIP vocabulary not available")
            return []

        # Determine scoring method based on query
        if self._config.use_semantic and hasattr(query, "embedding") and query.embedding is not None:
            concepts = self._score_semantic(query.embedding)
        else:
            concepts = self._score_keyword(query.text)

        # Apply limit
        limit = query.limit or self._config.top_k
        concepts = concepts[:limit]

        return self._concepts_to_results(concepts)

    async def query(self, query: EvidenceQuery) -> List[EvidenceResult]:
        """Async query for NiCLIP matches.

        Args:
            query: The evidence query

        Returns:
            List of evidence results
        """
        # Run sync method in thread pool to avoid blocking
        return await asyncio.to_thread(self.query_sync, query)

    def health_check_sync(self) -> bool:
        """Synchronous health check."""
        vocab_data = self._get_vocabulary()
        return vocab_data is not None and len(vocab_data[0]) > 0

    async def health_check(self) -> bool:
        """Check if NiCLIP is available.

        Returns:
            True if the service is available and vocabulary is loaded
        """
        if self._available is not None:
            return self._available

        self._available = await asyncio.to_thread(self.health_check_sync)
        return self._available


class NiCLIPScorer:
    """High-level scorer for NiCLIP-based relevance scoring.

    This class provides convenient methods for:
    - Scoring individual queries against cognitive concepts
    - Computing aggregate scores for text
    - Enriching evidence bundles with NiCLIP results

    Unlike NiCLIPEvidenceSource, this class focuses on scoring utilities
    rather than just evidence generation.
    """

    def __init__(
        self,
        config: Optional[NiCLIPConfig] = None,
        data_path: Optional[str] = None,
        vocabulary_type: str = "cogatlas_task-names",
        top_k: int = 10,
    ):
        """Initialize the scorer.

        Args:
            config: Full configuration object
            data_path: Path to NiCLIP data directory
            vocabulary_type: Which vocabulary to use
            top_k: Number of top matches for scoring
        """
        self._source = NiCLIPEvidenceSource(
            config=config,
            data_path=data_path,
            vocabulary_type=vocabulary_type,
            top_k=top_k,
        )
        self._config = self._source._config

    async def is_available(self) -> bool:
        """Check if NiCLIP scoring is available."""
        return await self._source.health_check()

    def score_text(self, text: str) -> List[ScoredConcept]:
        """Score text against vocabulary.

        Args:
            text: Query text to score

        Returns:
            List of scored concepts sorted by score (descending)
        """
        return self._source._score_keyword(text)

    def score_embedding(self, embedding: np.ndarray) -> List[ScoredConcept]:
        """Score using a pre-computed embedding.

        Args:
            embedding: Pre-computed query embedding

        Returns:
            List of scored concepts sorted by similarity
        """
        return self._source._score_semantic(embedding)

    def compute_aggregate_score(self, text: str) -> float:
        """Compute aggregate NiCLIP score for a query.

        Returns the weighted average similarity of top-k matches.

        Args:
            text: Text query

        Returns:
            Aggregate score in [0.0, 1.0]
        """
        scored = self.score_text(text)
        if not scored:
            return 0.0

        # Average of top-k scores, weighted toward top matches
        weights = [1.0 / (i + 1) for i in range(len(scored))]
        weighted_sum = sum(s.score * w for s, w in zip(scored, weights))
        total_weight = sum(weights)

        return weighted_sum / total_weight if total_weight > 0 else 0.0

    def get_top_concepts(self, text: str, limit: int = 5) -> List[str]:
        """Get top matching concept names for a query.

        Args:
            text: Query text
            limit: Maximum concepts to return

        Returns:
            List of concept term strings
        """
        scored = self.score_text(text)[:limit]
        return [s.term for s in scored]

    async def enrich_bundle(
        self, bundle: EvidenceBundle, limit: int = 5
    ) -> EvidenceBundle:
        """Enrich an evidence bundle with NiCLIP-derived evidence.

        Adds NiCLIP matches to the bundle's concepts list.

        Args:
            bundle: The evidence bundle to enrich
            limit: Maximum NiCLIP items to add

        Returns:
            The enriched bundle (mutated in place)
        """
        if not await self.is_available():
            logger.debug("NiCLIP not available, skipping enrichment")
            return bundle

        # Get query text from bundle metadata or first concept
        query_text = bundle.query_interpretation.get("original_query", "")
        if not query_text and bundle.concepts:
            query_text = bundle.concepts[0].title

        if not query_text:
            return bundle

        # Query for NiCLIP results
        query = EvidenceQuery(text=query_text, limit=limit)
        results = await self._source.query(query)

        # Add to bundle's concepts (NiCLIP concepts are cognitive concepts)
        for result in results:
            # Avoid duplicates based on ID
            if not any(c.id == result.id for c in bundle.concepts):
                bundle.concepts.append(result)

        # Add aggregate score to metadata
        bundle.metadata["niclip_aggregate_score"] = self.compute_aggregate_score(
            query_text
        )

        return bundle


def search_niclip(
    text: str,
    limit: int = 10,
    vocabulary_type: str = "cogatlas_task-names",
) -> List[EvidenceResult]:
    """Search NiCLIP vocabulary for matching concepts.

    Convenience function for simple queries without creating instances.

    Args:
        text: Query text
        limit: Maximum results
        vocabulary_type: Which vocabulary to search

    Returns:
        List of evidence results
    """
    source = NiCLIPEvidenceSource(vocabulary_type=vocabulary_type, top_k=limit)
    query = EvidenceQuery(text=text, limit=limit)
    return source.query_sync(query)


def create_niclip_source(
    data_path: Optional[str] = None,
    vocabulary_type: str = "cogatlas_task-names",
    top_k: int = 10,
) -> NiCLIPEvidenceSource:
    """Factory function to create a NiCLIP evidence source.

    Args:
        data_path: Optional override for data path
        vocabulary_type: Which vocabulary to use
        top_k: Number of top matches to return

    Returns:
        Configured NiCLIPEvidenceSource instance
    """
    return NiCLIPEvidenceSource(
        data_path=data_path,
        vocabulary_type=vocabulary_type,
        top_k=top_k,
    )


__all__ = [
    "NiCLIPConfig",
    "NiCLIPEvidenceSource",
    "NiCLIPScorer",
    "ScoredConcept",
    "create_niclip_source",
    "search_niclip",
]
