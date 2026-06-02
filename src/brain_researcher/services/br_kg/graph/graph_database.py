"""
Neo4j-only implementation for BR-KG.

The legacy NetworkX + SQLite mock backend has been removed. This shim keeps the
public name ``BRKGGraphDB`` but always connects to Neo4j using the configured
credentials, ignoring any SQLite paths that might be passed by older scripts.
"""

from __future__ import annotations

import logging
import os
from typing import Any, Dict, List, Tuple

from .neo4j_graph_database import Neo4jGraphDB

logger = logging.getLogger(__name__)


class BRKGGraphDB(Neo4jGraphDB):
    """Backward-compatible wrapper that now always uses Neo4j."""

    def __init__(
        self,
        db_path: str | None = None,
        *,
        uri: str | None = None,
        user: str | None = None,
        password: str | None = None,
        database: str | None = None,
        preload_cache: bool | None = None,
    ) -> None:
        if db_path:
            logger.warning(
                "SQLite fallback has been removed; ignoring db_path=%s and using Neo4j.",
                db_path,
            )

        uri = uri or os.getenv("NEO4J_URI")
        user = user or os.getenv("NEO4J_USER", "neo4j")
        password = password or os.getenv("NEO4J_PASSWORD")
        database = database or os.getenv("NEO4J_DATABASE")
        if preload_cache is None:
            preload_cache = os.getenv("NEO4J_PRELOAD_CACHE", "true").lower() not in (
                "0",
                "false",
                "no",
            )

        if not uri or not password:
            raise RuntimeError(
                "Neo4j connection details missing. Set NEO4J_URI and NEO4J_PASSWORD."
            )

        super().__init__(
            uri,
            user,
            password,
            database=database,
            preload_cache=preload_cache,
        )

    # ------------------------------------------------------------------
    # Compatibility helpers preserved from the legacy SQLite class
    # ------------------------------------------------------------------
    def get_relationship_count(self, rel_type: str | None = None) -> int:
        """Return the number of relationships, optionally filtered by type."""
        if rel_type:
            query = f"MATCH ()-[r:`{rel_type}`]->() RETURN count(r) AS cnt"
        else:
            query = "MATCH ()-[r]->() RETURN count(r) AS cnt"
        try:
            record = self._run(query).single()
            return int(record["cnt"] if record and record.get("cnt") is not None else 0)
        except Exception:  # pragma: no cover - defensive fallback
            return 0

    def match_and_link_nodes(
        self,
        candidate: Dict[str, Any],
        node_type: str,
        enable_matching: bool = True,
    ) -> Tuple[str, List[str]]:
        """Compatibility shim for legacy matching helper."""
        if not enable_matching:
            return candidate.get("id", ""), []

        try:
            from ..matching.node_matcher import UnifiedNodeMatcher

            existing_nodes = self.find_nodes(labels=node_type)
            existing_dicts = [{"id": nid, **data} for nid, data in existing_nodes]

            matcher = UnifiedNodeMatcher()
            matches = matcher.match_node(candidate, node_type, existing_dicts)

            node_id = candidate.get("id") or candidate.get("uid", "")
            edge_ids: List[str] = []

            if matches and node_id:
                edge_ids = matcher.create_same_as_edges(node_id, matches, self)

            return node_id, edge_ids

        except Exception as exc:  # pragma: no cover - best effort compatibility
            logger.warning("Matching failed for %s: %s", node_type, exc)
            return candidate.get("id", ""), []
