"""Helpers for Neo4j-only scripts and CLI usage."""

from __future__ import annotations

import logging
import os
from typing import Optional

from .neo4j_graph_database import Neo4jGraphDB

logger = logging.getLogger(__name__)


def require_neo4j_db(
    db_path: Optional[str] = None,
    *,
    database: Optional[str] = None,
    preload_cache: Optional[bool] = None,
) -> Neo4jGraphDB:
    """Return a Neo4jGraphDB, erroring if Neo4j is not configured."""
    if db_path:
        logger.warning("Ignoring db_path=%s; Neo4j is required.", db_path)

    uri = os.getenv("NEO4J_URI")
    user = os.getenv("NEO4J_USER", "neo4j")
    password = os.getenv("NEO4J_PASSWORD")
    if database is None:
        database = os.getenv("NEO4J_DATABASE")
    if preload_cache is None:
        preload_cache = os.getenv("NEO4J_PRELOAD_CACHE", "true").lower() not in (
            "0",
            "false",
            "no",
        )

    if not uri or not password:
        raise RuntimeError(
            "Neo4j connection details missing. Set NEO4J_URI/NEO4J_PASSWORD."
        )

    return Neo4jGraphDB(
        uri,
        user,
        password,
        database=database,
        preload_cache=preload_cache,
    )
