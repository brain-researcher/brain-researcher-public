"""Knowledge Aggregator for Track K+.

Aggregates evidence from multiple sources with progressive loading:
- Phase 1 (fast): Local sources (KG, datasets, tools, NiCLIP)
- Phase 2 (slow): External sources (PubMed, NeuroStore)
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass
from typing import (
    TYPE_CHECKING,
)

from .models import AggregatedEvidence, EvidenceConfidence, KnowledgeItem
from .sources.base import BaseEvidenceSource

if TYPE_CHECKING:
    from brain_researcher.services.shared.r2brkg_query_understanding_types import (
        QueryUnderstandingResult,
    )

logger = logging.getLogger(__name__)


@dataclass
class AggregatorConfig:
    """Configuration for the KnowledgeAggregator."""

    # Source enablement
    enable_kg: bool = True
    enable_datasets: bool = True
    enable_tools: bool = True
    enable_niclip: bool = True
    enable_pubmed: bool = True
    enable_neurostore: bool = True

    # Timeouts
    fast_timeout_ms: int = 200  # Phase 1 timeout
    slow_timeout_ms: int = 2000  # Phase 2 timeout
    total_timeout_ms: int = 5000  # Total aggregation timeout

    # Limits
    max_items_per_source: int = 10
    max_total_items: int = 50

    # Caching
    enable_cache: bool = True
    cache_ttl_seconds: int = 300  # 5 minutes


class KnowledgeAggregator:
    """Aggregates knowledge from multiple sources with progressive loading.

    Supports two-phase gathering:
    - Phase 1: Fast local sources (KG, datasets, tools, NiCLIP)
    - Phase 2: Slow external sources (PubMed, NeuroStore)

    Usage:
        aggregator = KnowledgeAggregator()

        # Simple gather (waits for all sources)
        evidence = await aggregator.gather(query, query_understanding)

        # Progressive gather (yields fast results first)
        async for evidence in aggregator.gather_progressive(query, query_understanding):
            print(evidence.confidence, len(evidence.items))
    """

    def __init__(self, config: AggregatorConfig | None = None):
        """Initialize the aggregator.

        Args:
            config: Optional configuration. Uses defaults if not provided.
        """
        self.config = config or AggregatorConfig()
        self._sources: dict[str, BaseEvidenceSource] = {}
        self._cache: dict[str, AggregatedEvidence] = {}  # L1 in-memory cache
        self._initialized = False

    def _init_sources(self) -> None:
        """Lazy-initialize evidence sources."""
        if self._initialized:
            return

        # Local sources (Phase 1 - fast)
        if self.config.enable_kg:
            try:
                from .sources.kg import KGEvidenceSource

                self._sources["br_kg"] = KGEvidenceSource()
            except Exception as e:
                logger.warning("Failed to init KG source: %s", e)

        if self.config.enable_datasets:
            try:
                from .sources.dataset import DatasetEvidenceSource

                self._sources["dataset_catalog"] = DatasetEvidenceSource()
            except Exception as e:
                logger.warning("Failed to init dataset source: %s", e)

        if self.config.enable_tools:
            try:
                from .sources.tool import ToolEvidenceSource

                self._sources["tool_registry"] = ToolEvidenceSource()
            except Exception as e:
                logger.warning("Failed to init tool source: %s", e)

        if self.config.enable_niclip:
            try:
                from .sources.niclip import NiCLIPEvidenceSource

                self._sources["niclip"] = NiCLIPEvidenceSource()
            except Exception as e:
                logger.warning("Failed to init NiCLIP source: %s", e)

        # External sources (Phase 2 - slow)
        if self.config.enable_pubmed:
            try:
                from .sources.pubmed import PubMedEvidenceSource

                self._sources["pubmed"] = PubMedEvidenceSource()
            except Exception as e:
                logger.warning("Failed to init PubMed source: %s", e)
                self.config.enable_pubmed = False

        if self.config.enable_neurostore:
            try:
                from .sources.neurostore import NeuroStoreEvidenceSource

                self._sources["neurostore"] = NeuroStoreEvidenceSource()
            except Exception as e:
                logger.warning("Failed to init NeuroStore source: %s", e)
                self.config.enable_neurostore = False

        self._initialized = True

    def _get_cache_key(
        self,
        query: str,
        entities: Sequence[str] | None = None,
        intent: str | None = None,
    ) -> str:
        """Generate cache key from normalized query + entities + intent."""
        norm_q = query.strip().lower()
        ent_part = "|".join(sorted(e.lower() for e in entities or []))
        intent_part = intent.lower() if intent else ""
        key = f"{intent_part}|{ent_part}|{norm_q}"
        return key[:200]

    def _check_cache(self, cache_key: str) -> AggregatedEvidence | None:
        """Check L1 cache for cached results."""
        if not self.config.enable_cache:
            return None

        cached = self._cache.get(cache_key)
        if cached is None:
            return None

        # Check TTL
        age_seconds = time.time() - cached.aggregated_at.timestamp()
        if age_seconds > self.config.cache_ttl_seconds:
            del self._cache[cache_key]
            return None

        return cached

    def _store_cache(self, cache_key: str, evidence: AggregatedEvidence) -> None:
        """Store results in L1 cache."""
        if not self.config.enable_cache:
            return

        # Simple LRU-like eviction: remove oldest if cache too large
        max_cache_size = 100
        if len(self._cache) >= max_cache_size:
            oldest_key = min(
                self._cache.keys(),
                key=lambda k: self._cache[k].aggregated_at.timestamp(),
            )
            del self._cache[oldest_key]

        self._cache[cache_key] = evidence

    async def _query_source(
        self,
        source_id: str,
        source: BaseEvidenceSource,
        query: str,
        limit: int,
        timeout_seconds: float,
    ) -> Sequence[KnowledgeItem]:
        """Query a single source with timeout."""
        try:
            # Check availability first
            available = await asyncio.wait_for(
                source.is_available(),
                timeout=timeout_seconds / 2,
            )
            if not available:
                logger.debug("Source %s not available", source_id)
                return []

            # Search
            items = await asyncio.wait_for(
                source.search(query, limit=limit),
                timeout=timeout_seconds,
            )
            return items

        except asyncio.TimeoutError:
            logger.warning("Source %s timed out", source_id)
            return []
        except Exception as e:
            logger.warning("Source %s failed: %s", source_id, e)
            return []

    async def gather(
        self,
        query: str,
        query_understanding: QueryUnderstandingResult | None = None,
        *,
        include_slow_sources: bool = True,
    ) -> AggregatedEvidence:
        """Gather evidence from all enabled sources.

        Args:
            query: User query string
            query_understanding: Optional pre-computed QU result
            include_slow_sources: Whether to include external sources

        Returns:
            AggregatedEvidence with all collected items
        """
        self._init_sources()
        start_time = time.time()

        # Check cache
        entities = []
        intent = None
        if query_understanding is not None:
            entities = [
                getattr(e, "text", "") or str(e)
                for e in getattr(query_understanding, "entities", [])
            ]
            intent = getattr(query_understanding, "intent", None)

        cache_key = self._get_cache_key(query, entities, intent)
        cached = self._check_cache(cache_key)
        if cached and cached.confidence == EvidenceConfidence.COMPLETE:
            return cached

        # Prepare result
        result = AggregatedEvidence(
            query=query,
            confidence=EvidenceConfidence.APPROXIMATE,
        )

        # Identify fast vs slow sources
        fast_sources = ["br_kg", "dataset_catalog", "tool_registry", "niclip"]
        slow_sources = ["pubmed", "neurostore"]

        # Query fast sources in parallel
        fast_tasks = []
        for source_id in fast_sources:
            source = self._sources.get(source_id)
            if source:
                result.sources_queried.append(source_id)
                fast_tasks.append(
                    self._query_source(
                        source_id,
                        source,
                        query,
                        self.config.max_items_per_source,
                        self.config.fast_timeout_ms / 1000,
                    )
                )

        if fast_tasks:
            fast_results = await asyncio.gather(*fast_tasks, return_exceptions=True)

            for source_id, items in zip(
                [s for s in fast_sources if s in self._sources],
                fast_results,
                strict=False,
            ):
                if isinstance(items, Exception):
                    result.sources_failed.append(source_id)
                    result.errors.append(f"{source_id}: {items}")
                elif items:
                    result.sources_succeeded.append(source_id)
                    result.items.extend(items)
                else:
                    result.sources_succeeded.append(source_id)

        # Query slow sources if requested
        if include_slow_sources:
            slow_tasks = []
            for source_id in slow_sources:
                source = self._sources.get(source_id)
                if source:
                    result.sources_queried.append(source_id)
                    slow_tasks.append(
                        self._query_source(
                            source_id,
                            source,
                            query,
                            self.config.max_items_per_source,
                            self.config.slow_timeout_ms / 1000,
                        )
                    )

            if slow_tasks:
                slow_results = await asyncio.gather(*slow_tasks, return_exceptions=True)

                for source_id, items in zip(
                    [s for s in slow_sources if s in self._sources],
                    slow_results,
                    strict=False,
                ):
                    if isinstance(items, Exception):
                        result.sources_failed.append(source_id)
                        result.errors.append(f"{source_id}: {items}")
                    elif items:
                        result.sources_succeeded.append(source_id)
                        result.items.extend(items)
                    else:
                        result.sources_succeeded.append(source_id)

            result.confidence = EvidenceConfidence.COMPLETE

        # Deduplicate across sources
        seen: set[str] = set()
        deduped: list[KnowledgeItem] = []
        for item in result.items:
            key = f"{item.source_id}:{item.id.strip().lower()}:{(item.title or '').strip().lower()}"
            if key in seen:
                continue
            seen.add(key)
            deduped.append(item)

        # Sort by score and limit total items
        deduped.sort(key=lambda x: x.score, reverse=True)
        result.items = deduped[: self.config.max_total_items]

        # Record timing
        result.duration_ms = (time.time() - start_time) * 1000

        # Cache complete results
        if result.confidence == EvidenceConfidence.COMPLETE:
            self._store_cache(cache_key, result)

        return result

    async def gather_progressive(
        self,
        query: str,
        query_understanding: QueryUnderstandingResult | None = None,
    ) -> AsyncIterator[AggregatedEvidence]:
        """Gather evidence progressively, yielding fast results first.

        Yields:
            AggregatedEvidence with approximate confidence (fast sources)
            AggregatedEvidence with complete confidence (all sources)
        """
        self._init_sources()
        start_time = time.time()

        # Phase 1: Fast sources only
        fast_result = await self.gather(
            query,
            query_understanding,
            include_slow_sources=False,
        )
        fast_result.confidence = EvidenceConfidence.APPROXIMATE
        yield fast_result

        # Phase 2: Include slow sources
        full_result = await self.gather(
            query,
            query_understanding,
            include_slow_sources=True,
        )
        full_result.duration_ms = (time.time() - start_time) * 1000
        yield full_result

    async def close(self) -> None:
        """Clean up all sources."""
        for source in self._sources.values():
            try:
                await source.close()
            except Exception as e:
                logger.warning("Failed to close source: %s", e)


# Convenience function
async def gather_knowledge(
    query: str,
    query_understanding: QueryUnderstandingResult | None = None,
) -> AggregatedEvidence:
    """Convenience function to gather knowledge for a query."""
    aggregator = KnowledgeAggregator()
    return await aggregator.gather(query, query_understanding)


__all__ = [
    "AggregatorConfig",
    "KnowledgeAggregator",
    "gather_knowledge",
]
