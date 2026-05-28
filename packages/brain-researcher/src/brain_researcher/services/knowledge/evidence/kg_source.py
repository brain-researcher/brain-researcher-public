"""Knowledge Graph evidence source adapter.

Wraps the BR-KG query_service to provide evidence via the EvidenceSource protocol.
"""

from __future__ import annotations

import logging
from typing import List, Optional

from brain_researcher.services.knowledge.evidence.base import (
    EvidenceQuery,
    EvidenceResult,
    EvidenceSourceType,
    SyncEvidenceSourceAdapter,
)

logger = logging.getLogger(__name__)


class KGEvidenceSource(SyncEvidenceSourceAdapter):
    """Evidence source adapter for the BR-KG Knowledge Graph.

    Wraps query_service.search_nodes() to provide concept and brain region
    evidence matching the EvidenceSource protocol.
    """

    def __init__(self, db=None):
        """Initialize the KG evidence source.

        Args:
            db: Optional Neo4jGraphDB instance for testing. If None, uses
                the default cached connection from query_service.
        """
        self._db = db

    @property
    def source_type(self) -> EvidenceSourceType:
        return EvidenceSourceType.KNOWLEDGE_GRAPH

    @property
    def source_id(self) -> str:
        return "neurokg"

    def query_sync(self, query: EvidenceQuery) -> List[EvidenceResult]:
        """Query the Knowledge Graph for matching nodes.

        Args:
            query: EvidenceQuery with text and optional node_types filter.

        Returns:
            List of EvidenceResult objects for matching KG nodes.
        """
        from brain_researcher.services.neurokg import query_service

        results: List[EvidenceResult] = []

        try:
            # Use node_types from query, or default to concepts + regions
            node_types = query.node_types
            if not node_types:
                node_types = ["CognitiveConcept", "Concept", "BrainRegion", "Region"]

            nodes = query_service.search_nodes(
                query.text,
                node_types=node_types,
                limit=query.limit,
                db=self._db,
            )

            for node in nodes:
                # Determine if this is a concept or region
                node_type_lower = (node.node_type or "").lower()
                is_region = "region" in node_type_lower or "parcel" in node_type_lower

                results.append(
                    EvidenceResult(
                        source=EvidenceSourceType.KNOWLEDGE_GRAPH,
                        id=node.kg_id,
                        title=node.label,
                        relevance_score=min(1.0, max(0.0, node.score)),
                        confidence=0.8,  # KG matches are generally reliable
                        payload={
                            "node_type": node.node_type,
                            "properties": node.properties or {},
                            "is_brain_region": is_region,
                        },
                        summary=f"{node.node_type}: {node.label}",
                    )
                )
        except Exception as exc:
            logger.warning("KG query failed: %s", exc)
            # Return empty list on error - don't propagate exceptions

        return results

    def health_check_sync(self) -> bool:
        """Check if the KG service is available."""
        try:
            from brain_researcher.services.neurokg import query_service

            # Try a simple query to verify connectivity
            db = self._db or query_service.get_default_db()
            return db is not None
        except Exception:
            return False


def get_concepts(
    query_text: str,
    limit: int = 10,
    db=None,
) -> List[EvidenceResult]:
    """Convenience function to get concept evidence from KG.

    Args:
        query_text: Free-text search query.
        limit: Maximum results to return.
        db: Optional database connection for testing.

    Returns:
        List of EvidenceResult for matching concepts.
    """
    source = KGEvidenceSource(db=db)
    query = EvidenceQuery(
        text=query_text,
        node_types=["CognitiveConcept", "Concept", "Term"],
        limit=limit,
    )
    # Use sync method directly for convenience functions
    return source.query_sync(query)


def get_brain_regions(
    query_text: str,
    limit: int = 10,
    db=None,
) -> List[EvidenceResult]:
    """Convenience function to get brain region evidence from KG.

    Args:
        query_text: Free-text search query.
        limit: Maximum results to return.
        db: Optional database connection for testing.

    Returns:
        List of EvidenceResult for matching brain regions.
    """
    source = KGEvidenceSource(db=db)
    query = EvidenceQuery(
        text=query_text,
        node_types=["BrainRegion", "Region", "Parcel"],
        limit=limit,
    )
    return source.query_sync(query)


__all__ = [
    "KGEvidenceSource",
    "get_brain_regions",
    "get_concepts",
]
