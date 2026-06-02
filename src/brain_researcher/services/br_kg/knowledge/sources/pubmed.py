"""PubMed evidence source backed by the PubMedConnector."""

from __future__ import annotations

import logging
from typing import Optional, Sequence

from brain_researcher.services.br_kg.evidence.connectors.pubmed import PubMedConnector

from ..models import KnowledgeItem
from .base import BaseEvidenceSource, SourceCapabilities

logger = logging.getLogger(__name__)


class PubMedEvidenceSource(BaseEvidenceSource):
    source_id = "pubmed"

    def __init__(self, api_key: Optional[str] = None) -> None:
        self._connector = PubMedConnector(api_key=api_key)
        self._capabilities = SourceCapabilities(
            supports_text_search=True,
            is_local=False,
            max_results_per_query=50,
            default_timeout_seconds=10.0,
            tags=["literature", "pubmed"],
        )

    @property
    def capabilities(self) -> SourceCapabilities:
        return self._capabilities

    async def is_available(self) -> bool:
        # Simple availability: try a lightweight query
        try:
            await self._connector.search("brain", limit=1)
            return True
        except Exception as exc:  # pragma: no cover - best effort
            logger.debug("PubMed availability check failed: %s", exc)
            return False

    async def search(
        self,
        query: str,
        *,
        limit: int = 20,
        filters: Optional[dict] = None,
    ) -> Sequence[KnowledgeItem]:
        pubs = await self._connector.search(query, limit=limit, filters=filters or {})
        items: list[KnowledgeItem] = []
        for pub in pubs:
            items.append(
                KnowledgeItem(
                    id=pub.id,
                    source_id=self.source_id,
                    title=pub.title,
                    description=pub.description,
                    score=pub.score or 0.8,
                    confidence=1.0,
                    url=pub.url,
                    doi=pub.doi,
                    metadata=pub.metadata or {},
                )
            )
        return items


__all__ = ["PubMedEvidenceSource"]
