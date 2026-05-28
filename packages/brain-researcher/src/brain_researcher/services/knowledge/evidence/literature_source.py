"""Literature evidence source adapter (PubMed).

Wraps the existing PubMedConnector to provide evidence via the EvidenceSource
protocol. Also provides a fallback sync implementation for environments without
httpx.
"""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Any, Dict, List, Optional

from brain_researcher.services.knowledge.evidence.base import (
    EvidenceQuery,
    EvidenceResult,
    EvidenceSource,
    EvidenceSourceType,
)

logger = logging.getLogger(__name__)


class LiteratureEvidenceSource:
    """Evidence source adapter for PubMed literature.

    Wraps the existing PubMedConnector to provide literature evidence
    matching the EvidenceSource protocol.
    """

    def __init__(self, api_key: Optional[str] = None):
        """Initialize the literature evidence source.

        Args:
            api_key: Optional NCBI API key for higher rate limits.
                    If not provided, uses NCBI_API_KEY env var.
        """
        self._api_key = api_key or os.getenv("NCBI_API_KEY")
        self._connector = None

    @property
    def source_type(self) -> EvidenceSourceType:
        return EvidenceSourceType.LITERATURE

    @property
    def source_id(self) -> str:
        return "pubmed"

    def _get_connector(self):
        """Lazy initialization of the PubMed connector."""
        if self._connector is None:
            try:
                from brain_researcher.services.neurokg.evidence.connectors.pubmed import (
                    PubMedConnector,
                )

                self._connector = PubMedConnector(api_key=self._api_key)
            except ImportError as exc:
                logger.warning("PubMedConnector import failed: %s", exc)
                return None
        return self._connector

    async def query(self, query: EvidenceQuery) -> List[EvidenceResult]:
        """Query PubMed for matching publications.

        Args:
            query: EvidenceQuery with text and optional year filters.

        Returns:
            List of EvidenceResult objects for matching publications.
        """
        connector = self._get_connector()
        if connector is None:
            logger.warning("PubMedConnector not available")
            return []

        try:
            # Build filters from query
            filters: Dict[str, Any] = {}
            if query.year_min:
                filters["year_from"] = query.year_min
            if query.year_max:
                filters["year_to"] = query.year_max

            # Use the connector's async search
            items = await connector.search(
                query.text,
                limit=query.limit,
                filters=filters if filters else None,
            )

            # Convert to EvidenceResult
            results: List[EvidenceResult] = []
            for item in items:
                results.append(
                    EvidenceResult(
                        source=EvidenceSourceType.LITERATURE,
                        id=item.id,
                        title=item.title,
                        relevance_score=item.score or 0.8,
                        confidence=0.9,  # PubMed results are authoritative
                        payload={
                            "authors": item.metadata.get("authors", []),
                            "journal": item.metadata.get("journal"),
                            "year": item.metadata.get("year"),
                            "doi": item.doi,
                            "item_type": str(item.item_type.value) if item.item_type else "publication",
                        },
                        url=item.url,
                        summary=item.description,
                    )
                )

            return results

        except Exception as exc:
            logger.warning("PubMed query failed: %s", exc)
            return []

    async def health_check(self) -> bool:
        """Check if PubMed is accessible."""
        try:
            connector = self._get_connector()
            return connector is not None and connector.is_available
        except Exception:
            return False


async def search_literature(
    query_text: str,
    year_min: Optional[int] = None,
    year_max: Optional[int] = None,
    limit: int = 10,
) -> List[EvidenceResult]:
    """Convenience function to search for literature evidence.

    Args:
        query_text: Free-text search query.
        year_min: Optional minimum publication year.
        year_max: Optional maximum publication year.
        limit: Maximum results to return.

    Returns:
        List of EvidenceResult for matching publications.
    """
    source = LiteratureEvidenceSource()
    query = EvidenceQuery(
        text=query_text,
        year_min=year_min,
        year_max=year_max,
        limit=limit,
    )
    return await source.query(query)


def search_literature_sync(
    query_text: str,
    year_min: Optional[int] = None,
    year_max: Optional[int] = None,
    limit: int = 10,
) -> List[EvidenceResult]:
    """Synchronous version of search_literature for non-async contexts.

    Args:
        query_text: Free-text search query.
        year_min: Optional minimum publication year.
        year_max: Optional maximum publication year.
        limit: Maximum results to return.

    Returns:
        List of EvidenceResult for matching publications.
    """
    return asyncio.run(
        search_literature(query_text, year_min, year_max, limit)
    )


__all__ = [
    "LiteratureEvidenceSource",
    "search_literature",
    "search_literature_sync",
]
