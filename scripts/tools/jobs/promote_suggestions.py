#!/usr/bin/env python3
"""Promote high-confidence SUGGESTS_MEASURES edges to MEASURES."""
from __future__ import annotations

import argparse
import os
from neo4j import GraphDatabase


def promote(threshold: float, batch: int, dry_run: bool, protect_ca: bool) -> None:
    uri = os.environ["NEO4J_URI"]
    user = os.environ["NEO4J_USER"]
    password = os.environ["NEO4J_PASSWORD"]
    database = os.getenv("NEO4J_DATABASE", "neo4j")
    driver = GraphDatabase.driver(uri, auth=(user, password))

    promote_clause = """
    CALL {
        WITH t, c, s
        MERGE (t)-[e:MEASURES]->(c)
        SET e.source = coalesce(e.source, s.source),
            e.method = coalesce(e.method, s.method),
            e.confidence = CASE WHEN e.confidence IS NULL OR e.confidence < s.confidence THEN s.confidence ELSE e.confidence END,
            e.evidence_json = coalesce(e.evidence_json, s.evidence_json),
            e.updated_at = datetime()
        DELETE s
    }
    RETURN count(*) AS promoted
    """

    ca_clause = "AND NOT ( (t)-[:MEASURES {source:'cognitive_atlas', method:'assertion'}]->(c) )" if protect_ca else ""
    query = f"""
    MATCH (t:Task)-[s:SUGGESTS_MEASURES]->(c:Concept)
    WHERE s.confidence >= $threshold
      AND coalesce(s.promotable, true)
      AND (c.is_placeholder IS NULL OR c.is_placeholder = false)
      {ca_clause}
    WITH t, c, s
    LIMIT $batch
    {"RETURN count(*) AS to_promote" if dry_run else promote_clause}
    """
    with driver.session(database=database) as session:
        result = session.run(query, threshold=threshold, batch=batch).data()
        print(result)

    driver.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Promote taxonomy suggestions to MEASURES")
    parser.add_argument("--threshold", type=float, default=0.9)
    parser.add_argument("--batch", type=int, default=1000)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--protect-ca", action="store_true")
    args = parser.parse_args()
    promote(args.threshold, args.batch, args.dry_run, args.protect_ca)


if __name__ == "__main__":
    main()
