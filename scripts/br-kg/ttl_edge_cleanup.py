#!/usr/bin/env python3
"""Purge expired on-demand IN_REGION edges from Neo4j.

Designed for cron/CI usage. Removes edges where `edge_source` identifies an
on-demand pipeline (e.g., neurosynth term decodes) and `expires_at_epoch` is
older than the current UNIX timestamp.
"""

from __future__ import annotations

import argparse
import logging
from typing import Iterable

from neo4j import GraphDatabase

CLEANUP_QUERY = """
MATCH ()-[e:IN_REGION {atlas: $atlas}]->()
WHERE e.edge_source = $edge_source
  AND e.expires_at_epoch IS NOT NULL
  AND e.expires_at_epoch < toInteger(timestamp()/1000)
WITH e LIMIT $batch_size
DELETE e
RETURN count(*) AS deleted
"""

COUNT_QUERY = """
MATCH ()-[e:IN_REGION {atlas: $atlas}]->()
WHERE e.edge_source = $edge_source
  AND e.expires_at_epoch IS NOT NULL
  AND e.expires_at_epoch < toInteger(timestamp()/1000)
RETURN count(e) AS pending
"""


def cleanup_edges(
    *,
    uri: str,
    user: str,
    password: str,
    database: str,
    atlas: str,
    edge_source: str,
    batch_size: int,
    dry_run: bool,
) -> int:
    """Delete expired edges in batches. Returns total deletions (0 in dry-run)."""

    driver = GraphDatabase.driver(uri, auth=(user, password))
    total_deleted = 0

    try:
        with driver.session(database=database) as session:
            pending = session.run(
                COUNT_QUERY,
                atlas=atlas,
                edge_source=edge_source,
            ).single()["pending"]
            logging.info("%d expired edges detected", pending)

            if dry_run or pending == 0:
                return 0

            while True:
                result = session.run(
                    CLEANUP_QUERY,
                    atlas=atlas,
                    edge_source=edge_source,
                    batch_size=batch_size,
                ).single()["deleted"]
                if result == 0:
                    break
                total_deleted += result
                logging.info("Deleted %d edges (running total %d)", result, total_deleted)
    finally:
        driver.close()

    return total_deleted


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--neo4j-uri", default="bolt://localhost:7687")
    parser.add_argument("--neo4j-user", default="neo4j")
    parser.add_argument("--neo4j-password", default="password")
    parser.add_argument("--neo4j-database", default="neo4j")
    parser.add_argument("--atlas", default="yeo17")
    parser.add_argument("--edge-source", default="neurosynth")
    parser.add_argument("--batch-size", type=int, default=5000)
    parser.add_argument("--dry-run", action="store_true")
    return parser


def main(argv: Iterable[str] | None = None) -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    args = build_parser().parse_args(argv)

    deleted = cleanup_edges(
        uri=args.neo4j_uri,
        user=args.neo4j_user,
        password=args.neo4j_password,
        database=args.neo4j_database,
        atlas=args.atlas,
        edge_source=args.edge_source,
        batch_size=args.batch_size,
        dry_run=args.dry_run,
    )

    if args.dry_run:
        logging.info("Dry run complete")
    else:
        logging.info("Deleted %d edges", deleted)


if __name__ == "__main__":
    main()
