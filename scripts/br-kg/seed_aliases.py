#!/usr/bin/env python3
"""
Seed alias entries for common missing terms (DVARS, scrubbing, OpenNeuro).
"""

from __future__ import annotations

import argparse
import logging
import os

from neo4j import GraphDatabase

logger = logging.getLogger(__name__)


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed alias entries in Neo4j")
    parser.add_argument("--neo4j-uri", default=os.getenv("NEO4J_URI", "bolt://localhost:7687"))
    parser.add_argument("--neo4j-user", default=os.getenv("NEO4J_USER", "neo4j"))
    parser.add_argument("--neo4j-password", default=os.getenv("NEO4J_PASSWORD", "password"))
    parser.add_argument("--neo4j-database", default=os.getenv("NEO4J_DATABASE"))
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    driver = GraphDatabase.driver(args.neo4j_uri, auth=(args.neo4j_user, args.neo4j_password))
    with driver.session(database=args.neo4j_database) as session:
        # Seed Concept nodes for DVARS and Scrubbing (if missing).
        session.run(
            """
            MERGE (n:Concept {id: 'concept:dvars'})
            ON CREATE SET n.name = 'DVARS', n.label = 'DVARS', n.aliases = ['dvars', 'dvar']
            WITH n, coalesce(n.aliases, []) AS aliases
            SET n.aliases = CASE
                WHEN any(a IN aliases WHERE toLower(a) = 'dvars') THEN aliases
                ELSE aliases + ['dvars']
            END
            """
        )

        session.run(
            """
            MERGE (n:Concept {id: 'concept:scrubbing'})
            ON CREATE SET n.name = 'Scrubbing', n.label = 'Scrubbing',
                n.aliases = ['scrubbing', 'motion scrubbing', 'volume censoring', 'outlier censoring']
            WITH n, coalesce(n.aliases, []) AS aliases
            SET n.aliases = CASE
                WHEN any(a IN aliases WHERE toLower(a) = 'scrubbing') THEN aliases
                ELSE aliases + ['scrubbing']
            END
            """
        )

        session.run(
            """
            MERGE (n:Concept {id: 'concept:framewise_displacement'})
            ON CREATE SET n.name = 'Framewise Displacement', n.label = 'Framewise Displacement',
                n.aliases = ['framewise displacement', 'fd']
            WITH n, coalesce(n.aliases, []) AS aliases
            SET n.aliases = CASE
                WHEN any(a IN aliases WHERE toLower(a) = 'framewise displacement') THEN aliases
                ELSE aliases + ['framewise displacement', 'fd']
            END
            """
        )

        session.run(
            """
            MERGE (n:Concept {id: 'concept:compcor'})
            ON CREATE SET n.name = 'CompCor', n.label = 'CompCor',
                n.aliases = ['compcor', 'acompcor', 'tcompcor', 'aCompCor', 'tCompCor']
            WITH n, coalesce(n.aliases, []) AS aliases
            SET n.aliases = CASE
                WHEN any(a IN aliases WHERE toLower(a) = 'compcor') THEN aliases
                ELSE aliases + ['compcor', 'acompcor', 'tcompcor', 'aCompCor', 'tCompCor']
            END
            """
        )

        session.run(
            """
            MERGE (n:Concept {id: 'concept:ica_aroma'})
            ON CREATE SET n.name = 'ICA-AROMA', n.label = 'ICA-AROMA',
                n.aliases = ['ica-aroma', 'ica aroma', 'aroma', 'ICA-AROMA']
            WITH n, coalesce(n.aliases, []) AS aliases
            SET n.aliases = CASE
                WHEN any(a IN aliases WHERE toLower(a) = 'ica-aroma') THEN aliases
                ELSE aliases + ['ica-aroma', 'ica aroma', 'aroma', 'ICA-AROMA']
            END
            """
        )

        # Add OpenNeuro alias to OpenNeuro datasets.
        session.run(
            """
            MATCH (d:Dataset)
            WHERE toLower(coalesce(d.source_repo, '')) CONTAINS 'openneuro'
               OR toLower(coalesce(d.source, '')) CONTAINS 'openneuro'
               OR coalesce(d.is_openneuro, false) = true
               OR d.openneuro_id IS NOT NULL
               OR (d.dataset_id IS NOT NULL AND toLower(d.dataset_id) STARTS WITH 'ds')
            WITH d, coalesce(d.aliases, []) AS aliases
            SET d.aliases = CASE
                WHEN any(a IN aliases WHERE toLower(a) = 'openneuro') THEN aliases
                ELSE aliases + ['openneuro']
            END
            """
        )

    driver.close()
    logger.info("Alias seeding complete.")


if __name__ == "__main__":
    main()
