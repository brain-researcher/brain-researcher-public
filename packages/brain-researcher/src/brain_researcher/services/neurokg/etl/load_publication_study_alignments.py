#!/usr/bin/env python3
"""Backfill explicit Publication -> Study alignments into BR-KG."""

from __future__ import annotations

import argparse
import logging

from brain_researcher.core.ingestion.loaders.publication_study_alignment import (
    link_publication_study_alignments,
)
from brain_researcher.services.neurokg.graph.neo4j_graph_database import Neo4jGraphDB

logger = logging.getLogger(__name__)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Backfill explicit Publication->Study alignments into BR-KG"
    )
    parser.add_argument("--neo4j-uri", required=True)
    parser.add_argument("--neo4j-user", required=True)
    parser.add_argument("--neo4j-password", required=True)
    parser.add_argument("--neo4j-database", default=None)
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Optional publication limit for smoke tests",
    )
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO)

    db = Neo4jGraphDB(
        args.neo4j_uri,
        args.neo4j_user,
        args.neo4j_password,
        database=args.neo4j_database,
    )
    stats = link_publication_study_alignments(db, limit=args.limit)
    logger.info("Applied Publication->Study alignment stats: %s", stats)


if __name__ == "__main__":
    main()
