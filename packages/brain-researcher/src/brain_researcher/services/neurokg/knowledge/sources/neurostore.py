"""NeuroStore evidence source backed by NeuroStoreConnector."""

from __future__ import annotations

import logging
from typing import Sequence, Optional

from brain_researcher.services.neurokg.evidence.connectors.neurostore import NeuroStoreConnector
from .base import BaseEvidenceSource, SourceCapabilities
from ..models import KnowledgeItem


logger = logging.getLogger(__name__)


class NeuroStoreEvidenceSource(BaseEvidenceSource):
    source_id = "neurostore"

    def __init__(self) -> None:
        self._connector = NeuroStoreConnector()
        self._capabilities = SourceCapabilities(
            supports_text_search=True,
            is_local=False,
            max_results_per_query=50,
            default_timeout_seconds=10.0,
            tags=["neurostore", "study"],
        )

    @property
    def capabilities(self) -> SourceCapabilities:
        return self._capabilities

    async def is_available(self) -> bool:
        try:
            await self._connector.search("brain", limit=1)
            return True
        except Exception as exc:  # pragma: no cover
            logger.debug("NeuroStore availability check failed: %s", exc)
            return False

    async def search(
        self,
        query: str,
        *,
        limit: int = 20,
        filters: Optional[dict] = None,
    ) -> Sequence["KnowledgeItem"]:
        studies = await self._connector.search(query, limit=limit, filters=filters or {})
        items: list[KnowledgeItem] = []
        for s in studies:
            items.append(
                KnowledgeItem(
                    id=s.id,
                    source_id=self.source_id,
                    title=s.title,
                    description=s.description,
                    score=s.score or 0.8,
                    confidence=1.0,
                    url=s.url,
                    doi=s.doi,
                    metadata=s.metadata or {},
                )
            )
        return items


__all__ = ["NeuroStoreEvidenceSource"]
