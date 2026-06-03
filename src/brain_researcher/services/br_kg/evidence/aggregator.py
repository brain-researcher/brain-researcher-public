"""
Evidence aggregator - main entry point for evidence gathering.

Provides the gather_evidence() function that queries multiple sources
in parallel and aggregates results.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from .models import EvidenceBundle, EvidenceItem, EvidenceSource
from .protocols import ConnectorError, EvidenceConnector

logger = logging.getLogger(__name__)


def _get_default_connectors() -> list[EvidenceConnector]:
    """Create default connector instances."""
    from .connectors import (
        BRKGConnector,
        DatasetConnector,
        NeuroStoreConnector,
        PubMedConnector,
        ToolConnector,
    )

    return [
        BRKGConnector(),
        DatasetConnector(),
        ToolConnector(),
        PubMedConnector(),
        NeuroStoreConnector(),
    ]


async def gather_evidence(
    query: str,
    *,
    sources: list[EvidenceSource] | None = None,
    limit_per_source: int = 10,
    connectors: list[EvidenceConnector] | None = None,
    timeout: float | None = None,
) -> EvidenceBundle:
    """
    Gather evidence from multiple knowledge sources in parallel.

    This is the primary public API for the evidence layer.

    Args:
        query: Natural language search query
        sources: Specific sources to query (None = all available)
        limit_per_source: Maximum results per source
        connectors: Custom connectors (for testing/dependency injection)
        timeout: Optional timeout for all queries combined

    Returns:
        EvidenceBundle with aggregated items and metadata

    Example:
        >>> bundle = await gather_evidence("working memory fMRI")
        >>> print(f"Found {bundle.total_count} items from {len(bundle.sources_queried)} sources")

        >>> # Query specific sources
        >>> bundle = await gather_evidence(
        ...     "motor task dataset",
        ...     sources=[EvidenceSource.DATASET_CATALOG, EvidenceSource.BR_KG],
        ...     limit_per_source=5,
        ... )
    """
    start_time = time.time()

    # Get connectors (use default only if connectors is None, not empty list)
    all_connectors = connectors if connectors is not None else _get_default_connectors()

    # Filter by requested sources
    if sources:
        all_connectors = [c for c in all_connectors if c.source in sources]

    # Filter to available connectors
    active_connectors = [c for c in all_connectors if c.is_available]

    if not active_connectors:
        logger.warning("No available connectors for evidence gathering")
        return EvidenceBundle(
            query=query,
            items=[],
            sources_queried=[],
            errors={"all": "No connectors available"},
            query_time_ms=0,
        )

    async def _search_one(
        connector: EvidenceConnector,
    ) -> tuple[EvidenceSource, list[EvidenceItem], str | None]:
        """Search a single connector with error handling."""
        try:
            items = await connector.search(query, limit=limit_per_source)
            logger.debug(f"[{connector.source.value}] Found {len(items)} items")
            return connector.source, items, None
        except ConnectorError as e:
            logger.warning(f"[{connector.source.value}] Error: {e.message}")
            return connector.source, [], e.message
        except Exception as e:
            logger.warning(f"[{connector.source.value}] Unexpected error: {e}")
            return connector.source, [], str(e)

    # Run all connectors in parallel
    tasks = [_search_one(c) for c in active_connectors]

    if timeout:
        try:
            results = await asyncio.wait_for(
                asyncio.gather(*tasks, return_exceptions=True),
                timeout=timeout,
            )
        except asyncio.TimeoutError:
            logger.warning(f"Evidence gathering timed out after {timeout}s")
            results = []
    else:
        results = await asyncio.gather(*tasks, return_exceptions=True)

    # Aggregate results
    bundle = EvidenceBundle(query=query)

    seen: set[str] = set()

    def _canon_key(item: EvidenceItem) -> str:
        base = f"{item.source.value}:{item.id.strip().lower()}"
        title = (item.title or "").strip().lower()
        return f"{base}:{title}" if title else base

    def _clamp_score(val: float | None) -> float:
        if val is None:
            return 0.0
        try:
            return max(0.0, min(1.0, float(val)))
        except Exception:
            return 0.0

    for result in results:
        if isinstance(result, Exception):
            # Handle exceptions from gather
            logger.warning(f"Task failed: {result}")
            continue

        source, items, error = result
        bundle.sources_queried.append(source)

        if error:
            bundle.errors[source.value] = error
        else:
            for item in items:
                item = item.model_copy(
                    update={"score": _clamp_score(getattr(item, "score", None))}
                )
                key = _canon_key(item)
                if key in seen:
                    continue
                seen.add(key)
                bundle.items.append(item)

    bundle.query_time_ms = (time.time() - start_time) * 1000

    logger.info(
        f"Evidence gathered: {bundle.total_count} items from "
        f"{len(bundle.sources_queried)} sources in {bundle.query_time_ms:.1f}ms"
    )

    return bundle


async def gather_evidence_for_qur(
    qur: Any,  # QueryUnderstandingResult
    *,
    limit_per_source: int = 10,
    connectors: list[EvidenceConnector] | None = None,
) -> EvidenceBundle:
    """
    Gather evidence based on QueryUnderstandingResult.

    Automatically infers which sources to query based on the QUR content.

    Args:
        qur: QueryUnderstandingResult from kg_resolution
        limit_per_source: Maximum results per source
        connectors: Custom connectors (for testing)

    Returns:
        EvidenceBundle with aggregated items
    """
    sources = _infer_sources_from_qur(qur)
    return await gather_evidence(
        qur.original_query,
        sources=sources,
        limit_per_source=limit_per_source,
        connectors=connectors,
    )


def _infer_sources_from_qur(qur: Any) -> list[EvidenceSource]:
    """
    Infer which sources to query based on QUR content.

    Rules:
    1. Always query BR-KG (comprehensive)
    2. If dataset entities present -> DatasetConnector
    3. If literature keywords -> PubMed
    4. If tool keywords -> ToolConnector
    5. If activation/coordinate keywords -> NeuroStore
    """
    sources = [EvidenceSource.BR_KG]  # Always query KG

    # Extract entity types
    entity_types = set()
    if hasattr(qur, "entities"):
        entity_types = {
            e.get("entity_type") for e in qur.entities if isinstance(e, dict)
        }

    query_lower = qur.original_query.lower()

    # Dataset entities or resolved datasets
    if "DATASET" in entity_types or (
        hasattr(qur, "resolved_datasets") and qur.resolved_datasets
    ):
        sources.append(EvidenceSource.DATASET_CATALOG)

    # Literature keywords
    pub_keywords = ["paper", "study", "publication", "literature", "review", "research"]
    if any(kw in query_lower for kw in pub_keywords):
        sources.append(EvidenceSource.PUBMED)

    # Tool keywords
    tool_keywords = [
        "tool",
        "pipeline",
        "software",
        "method",
        "analysis",
        "fsl",
        "spm",
        "fmriprep",
    ]
    if any(kw in query_lower for kw in tool_keywords):
        sources.append(EvidenceSource.TOOL_CATALOG)

    # NeuroStore keywords
    neurostore_keywords = [
        "activation",
        "statmap",
        "coordinate",
        "mni",
        "meta-analysis",
        "peak",
    ]
    if any(kw in query_lower for kw in neurostore_keywords):
        sources.append(EvidenceSource.NEUROSTORE)

    return list(set(sources))


# Convenience sync wrapper
def gather_evidence_sync(
    query: str,
    *,
    sources: list[EvidenceSource] | None = None,
    limit_per_source: int = 10,
) -> EvidenceBundle:
    """
    Synchronous wrapper for gather_evidence.

    Useful for non-async contexts. Creates a new event loop if needed.
    """
    try:
        asyncio.get_running_loop()
        # Already in async context - can't use run
        import concurrent.futures

        with concurrent.futures.ThreadPoolExecutor() as executor:
            future = executor.submit(
                asyncio.run,
                gather_evidence(
                    query, sources=sources, limit_per_source=limit_per_source
                ),
            )
            return future.result()
    except RuntimeError:
        # No running event loop - create one
        return asyncio.run(
            gather_evidence(query, sources=sources, limit_per_source=limit_per_source)
        )
