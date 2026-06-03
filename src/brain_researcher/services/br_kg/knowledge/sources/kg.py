"""Knowledge Graph evidence source adapter.

Wraps the BR-KG query_service to provide KG node search results
as KnowledgeItem objects.
"""

from __future__ import annotations

import logging
from typing import Optional, Sequence

from .base import BaseEvidenceSource, SourceCapabilities
from ..models import KnowledgeItem

logger = logging.getLogger(__name__)


class KGEvidenceSource(BaseEvidenceSource):
    """Evidence source adapter for BR-KG (Knowledge Graph)."""

    def __init__(self):
        self._available: Optional[bool] = None

    @property
    def source_id(self) -> str:
        return "br_kg"

    @property
    def capabilities(self) -> SourceCapabilities:
        return SourceCapabilities(
            supports_text_search=True,
            supports_semantic_search=False,  # KG uses label matching
            supports_coordinate_lookup=False,
            supports_entity_resolution=True,
            supports_streaming=False,
            max_results_per_query=50,
            default_timeout_seconds=5.0,
            is_local=True,  # Neo4j is local
            tags=["kg", "concepts", "regions", "datasets"],
        )

    async def is_available(self) -> bool:
        """Check if the KG query service is available."""
        if self._available is not None:
            return self._available

        try:
            from brain_researcher.services.br_kg import query_service

            # Try a quick search
            results = query_service.search_nodes("test", limit=1)
            self._available = True
        except Exception as e:
            logger.debug("KG service unavailable: %s", e)
            self._available = False

        return self._available

    async def search(
        self,
        query: str,
        *,
        limit: int = 20,
        filters: Optional[dict] = None,
    ) -> Sequence[KnowledgeItem]:
        """Search KG for nodes matching the query.

        Args:
            query: Search text
            limit: Maximum results
            filters: Optional filters like {"node_types": ["Concept", "Region"]}

        Returns:
            Sequence of KnowledgeItem objects
        """
        try:
            from brain_researcher.services.br_kg import query_service

            # Extract filters
            node_types = None
            if filters:
                node_types = filters.get("node_types")

            # Search KG
            results = query_service.search_nodes(
                query,
                node_types=node_types,
                limit=limit,
            )

            # Convert to KnowledgeItem
            items = []
            for node in results:
                items.append(
                    KnowledgeItem(
                        id=f"kg:{node.kg_id}",
                        source_id=self.source_id,
                        title=node.label,
                        description=f"{node.node_type}: {node.label}",
                        score=node.score,
                        confidence=1.0,
                        metadata={
                            "kg_id": node.kg_id,
                            "node_type": node.node_type,
                            "properties": node.properties or {},
                        },
                    )
                )

            return items

        except Exception as e:
            logger.warning("KG search failed: %s", e)
            return []

    async def get_by_id(self, item_id: str) -> Optional[KnowledgeItem]:
        """Get a KG node by its ID."""
        try:
            from brain_researcher.services.br_kg import query_service

            # Strip prefix if present
            kg_id = item_id
            if kg_id.startswith("kg:"):
                kg_id = kg_id[3:]

            # Get node details
            result = query_service.node_details(kg_id)
            if not result:
                return None

            return KnowledgeItem(
                id=f"kg:{kg_id}",
                source_id=self.source_id,
                title=result.get("label", kg_id),
                description=f"{result.get('type', 'Unknown')}: {result.get('label', kg_id)}",
                score=1.0,
                confidence=1.0,
                metadata=result,
            )

        except Exception as e:
            logger.warning("KG get_by_id failed for %s: %s", item_id, e)
            return None


__all__ = ["KGEvidenceSource"]
