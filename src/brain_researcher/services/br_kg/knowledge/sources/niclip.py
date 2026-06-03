"""NiCLIP brain embedding evidence source adapter.

Wraps the NiCLIP embedding service to provide semantic matches
as KnowledgeItem objects.
"""

from __future__ import annotations

import logging
import os
from typing import Optional, Sequence

from brain_researcher.config.paths import get_data_root
from brain_researcher.services.shared.brkg_atlas_paths import default_atlas_output_root

from ..models import KnowledgeItem
from .base import BaseEvidenceSource, SourceCapabilities

logger = logging.getLogger(__name__)


def _default_niclip_data_path() -> str:
    shared_root = default_atlas_output_root() / "niclip"
    if shared_root.exists():
        return str(shared_root)
    return str((get_data_root() / "niclip").resolve())


class NiCLIPEvidenceSource(BaseEvidenceSource):
    """Evidence source adapter for NiCLIP brain embeddings.

    Provides semantic search over cognitive concepts using pre-computed
    brain-text aligned embeddings.
    """

    def __init__(self, niclip_data_path: Optional[str] = None):
        """Initialize the NiCLIP source.

        Args:
            niclip_data_path: Path to NiCLIP data directory.
                             Defaults to NICLIP_DATA_PATH env var.
        """
        self._data_path = niclip_data_path or os.environ.get(
            "NICLIP_DATA_PATH",
            _default_niclip_data_path(),
        )
        self._service = None
        self._engine = None
        self._available: Optional[bool] = None

    @property
    def source_id(self) -> str:
        return "niclip"

    @property
    def capabilities(self) -> SourceCapabilities:
        return SourceCapabilities(
            supports_text_search=True,
            supports_semantic_search=True,  # Has embedding-based search
            supports_coordinate_lookup=True,  # Can map coordinates to concepts
            supports_entity_resolution=False,
            supports_streaming=False,
            max_results_per_query=50,
            default_timeout_seconds=5.0,
            is_local=True,  # Pre-computed embeddings are local
            tags=["niclip", "embeddings", "brain", "cognitive"],
        )

    def _get_service(self):
        """Lazy-load the NiCLIP service."""
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
                logger.warning("Failed to load NiCLIP service: %s", e)
                self._service = None
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

    async def is_available(self) -> bool:
        """Check if the NiCLIP service is available."""
        if self._available is not None:
            return self._available

        try:
            service = self._get_service()
            if service is None:
                self._available = False
            else:
                # Try to load vocabulary to verify availability
                vocab, _ = service.load_vocabulary_embeddings("cogatlas_task-names")
                self._available = len(vocab) > 0
        except Exception as e:
            logger.debug("NiCLIP service unavailable: %s", e)
            self._available = False

        return self._available

    async def search(
        self,
        query: str,
        *,
        limit: int = 10,
        filters: Optional[dict] = None,
    ) -> Sequence[KnowledgeItem]:
        """Search NiCLIP vocabulary for matching concepts.

        Uses keyword matching against the cognitive task vocabulary.
        For full semantic search, use the embedding-based methods directly.

        Args:
            query: Search text
            limit: Maximum results
            filters: Optional filters like {"vocabulary_type": "cogatlasred_task-names"}

        Returns:
            Sequence of KnowledgeItem objects
        """
        try:
            service = self._get_service()
            if service is None:
                return []

            # Get vocabulary type from filters or default
            vocab_type = "cogatlas_task-names"
            if filters:
                vocab_type = filters.get("vocabulary_type", vocab_type)

            # Load vocabulary and priors
            vocab, index, priors = service.get_vocabulary_index(vocab_type)

            # Simple keyword matching (for now)
            # TODO: Add text encoder for full semantic search
            query_lower = query.lower()
            scored_items = []

            for i, term in enumerate(vocab):
                score = 0.0

                # Exact match
                if query_lower == term.lower():
                    score = 1.0
                # Contains query
                elif query_lower in term.lower():
                    score = 0.8
                # Query contains term
                elif term.lower() in query_lower:
                    score = 0.6
                # Word overlap
                else:
                    query_words = set(query_lower.split())
                    term_words = set(term.lower().split())
                    overlap = query_words.intersection(term_words)
                    if overlap:
                        score = (
                            0.3 * len(overlap) / max(len(query_words), len(term_words))
                        )

                if score > 0:
                    # Boost score by prior probability
                    prior_score = priors[i] if i < len(priors) else 0.5
                    combined_score = 0.7 * score + 0.3 * prior_score
                    scored_items.append((i, term, combined_score))

            # Sort by score and limit
            scored_items.sort(key=lambda x: x[2], reverse=True)
            top_items = scored_items[:limit]

            # Convert to KnowledgeItem
            items = []
            for idx, term, score in top_items:
                items.append(
                    KnowledgeItem(
                        id=f"niclip:{vocab_type}:{idx}",
                        source_id=self.source_id,
                        title=term,
                        description=f"Cognitive task: {term}",
                        score=min(score, 1.0),
                        confidence=0.8,  # Keyword matching is less confident
                        metadata={
                            "vocabulary_type": vocab_type,
                            "vocabulary_index": idx,
                            "prior_probability": float(priors[idx])
                            if idx < len(priors)
                            else 0.5,
                        },
                    )
                )

            return items

        except Exception as e:
            logger.warning("NiCLIP search failed: %s", e)
            return []

    async def search_semantic(
        self,
        query_embedding,
        *,
        limit: int = 10,
        vocabulary_type: str = "cogatlas_task-names",
    ) -> Sequence[KnowledgeItem]:
        """Search using a pre-computed query embedding.

        This is the full semantic search using FAISS.

        Args:
            query_embedding: Pre-computed embedding vector (numpy array)
            limit: Maximum results
            vocabulary_type: Which vocabulary to search

        Returns:
            Sequence of KnowledgeItem objects
        """
        try:
            service = self._get_service()
            if service is None:
                return []

            vocab, index, priors = service.get_vocabulary_index(vocabulary_type)

            # Search using FAISS
            distances, indices = service.search_similar(query_embedding, index, k=limit)

            # Convert to KnowledgeItem
            items = []
            for i, (dist, idx) in enumerate(zip(distances, indices)):
                if idx < 0 or idx >= len(vocab):
                    continue

                term = vocab[idx]
                score = float(dist)  # Cosine similarity (0-1)

                items.append(
                    KnowledgeItem(
                        id=f"niclip:{vocabulary_type}:{idx}",
                        source_id=self.source_id,
                        title=term,
                        description=f"Cognitive task: {term}",
                        score=score,
                        confidence=0.95,  # Semantic search is more confident
                        metadata={
                            "vocabulary_type": vocabulary_type,
                            "vocabulary_index": int(idx),
                            "cosine_similarity": score,
                            "prior_probability": float(priors[idx])
                            if idx < len(priors)
                            else 0.5,
                        },
                    )
                )

            return items

        except Exception as e:
            logger.warning("NiCLIP semantic search failed: %s", e)
            return []


__all__ = ["NiCLIPEvidenceSource"]
