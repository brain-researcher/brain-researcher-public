"""
BR-KG evidence connector.

Wraps the query_service.search_nodes() function to search for
concepts, brain regions, and other entities in the knowledge graph.
"""

from __future__ import annotations

from typing import Any

from ..models import EvidenceItem, EvidenceSource, EvidenceType
from ..protocols import ConnectorError
from .base import SyncWrapperConnector


class BRKGConnector(SyncWrapperConnector):
    """
    Connector for searching BR-KG knowledge graph nodes.

    Searches for cognitive concepts, brain regions, and other entities
    using the Neo4j-backed query service.
    """

    @property
    def source(self) -> EvidenceSource:
        return EvidenceSource.BR_KG

    @property
    def is_available(self) -> bool:
        """Check if Neo4j is available."""
        try:
            from brain_researcher.services.br_kg.query_service import get_default_db

            db = get_default_db()
            return db is not None
        except Exception:
            return False

    async def search(
        self,
        query: str,
        *,
        limit: int = 20,
        filters: dict[str, Any] | None = None,
    ) -> list[EvidenceItem]:
        """
        Search BR-KG for matching nodes.

        Args:
            query: Search query
            limit: Maximum results
            filters: Optional filters:
                - node_types: List of node types to search (e.g., ["CognitiveConcept", "BrainRegion"])

        Returns:
            List of evidence items
        """
        try:
            from brain_researcher.services.br_kg.query_service import search_nodes
        except ImportError as e:
            raise ConnectorError(self.source, "query_service not available", e)

        node_types = filters.get("node_types") if filters else None

        try:
            results = await self._run_sync(
                search_nodes,
                query,
                node_types=node_types,
                limit=limit,
            )
        except Exception as e:
            raise ConnectorError(self.source, f"Search failed: {e}", e)

        return [self._to_evidence_item(r) for r in results]

    async def get_by_id(self, item_id: str) -> EvidenceItem | None:
        """Get a specific node by KG ID."""
        try:
            from brain_researcher.services.br_kg.query_service import node_details
        except ImportError:
            return None

        try:
            result = await self._run_sync(node_details, item_id)
            if result:
                return self._to_evidence_item(result)
        except Exception:
            pass
        return None

    def _to_evidence_item(self, node) -> EvidenceItem:
        """Convert KGNodeSummary to EvidenceItem."""
        return EvidenceItem(
            id=str(node.kg_id),  # Ensure string
            source=self.source,
            item_type=self._map_node_type(node.node_type),
            title=node.label,
            description=f"{node.node_type}: {node.label}",
            score=node.score,
            metadata={
                "node_type": node.node_type,
                "properties": node.properties,
            },
        )

    def _map_node_type(self, node_type: str) -> EvidenceType:
        """Map KG node type to EvidenceType."""
        mapping = {
            "CognitiveConcept": EvidenceType.CONCEPT,
            "Concept": EvidenceType.CONCEPT,
            "Term": EvidenceType.CONCEPT,
            "BrainRegion": EvidenceType.BRAIN_REGION,
            "Region": EvidenceType.BRAIN_REGION,
            "Parcel": EvidenceType.BRAIN_REGION,
            "Dataset": EvidenceType.DATASET,
            "Publication": EvidenceType.PUBLICATION,
            "Coordinate": EvidenceType.COORDINATE,
        }
        return mapping.get(node_type, EvidenceType.CONCEPT)
