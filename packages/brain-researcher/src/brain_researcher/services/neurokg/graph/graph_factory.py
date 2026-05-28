"""Runtime factory for BR-KG graph database clients."""

from __future__ import annotations

import logging

from brain_researcher.core.ingestion.graph_factory import GraphDatabaseProtocol
from brain_researcher.services.neurokg.graph.neo4j_utils import require_neo4j_db

logger = logging.getLogger(__name__)


def create_graph_client(
    *,
    db_path: str | None = None,
    allow_sqlite_mock: bool | None = None,
) -> GraphDatabaseProtocol:
    """
    Create a Neo4j graph database client from environment configuration.

    Deprecated SQLite/mock parameters are accepted so older service callers can
    migrate without changing behavior.
    """
    if db_path:
        logger.warning("Ignoring db_path=%s; Neo4j is required.", db_path)
    if allow_sqlite_mock is not None:
        logger.warning(
            "Ignoring allow_sqlite_mock=%s; Neo4j is required.", allow_sqlite_mock
        )

    return require_neo4j_db()


__all__ = ["create_graph_client"]
