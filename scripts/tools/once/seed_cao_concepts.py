#!/usr/bin/env python3
"""Seed minimal CAO Concept nodes from taxonomy entities."""
import json
from pathlib import Path

from neo4j import GraphDatabase

import os
NEO4J_URI = os.environ["NEO4J_URI"]
NEO4J_USER = os.environ["NEO4J_USER"]
NEO4J_PASSWORD = os.environ["NEO4J_PASSWORD"]
NEO4J_DATABASE = os.getenv("NEO4J_DATABASE", "neo4j")

ENTITIES = Path("brain_researcher/semantics/taxonomy/entities.json")

def main():
    data = json.loads(ENTITIES.read_text())
    entities = data.get("entities", {})
    rows = []
    for payload in entities.values():
        links = payload.get("links") or {}
        cao_id = links.get("cogat")
        if isinstance(cao_id, str) and cao_id.upper().startswith("CAO_"):
            rows.append({
                "id": cao_id.upper(),
                "name": payload.get("label") or cao_id,
                "type": payload.get("type"),
                "source": "cognitive_atlas_taxonomy",
            })
    if not rows:
        print("No CAO IDs found.")
        return

    driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))
    with driver.session(database=NEO4J_DATABASE) as session:
        session.run(
            """
            UNWIND $rows AS row
            MERGE (c:Concept {id: row.id})
              ON CREATE SET c.name = row.name,
                            c.source = row.source,
                            c.concept_type = row.type,
                            c.created_at = datetime()
              ON MATCH  SET c.name = coalesce(c.name, row.name),
                            c.updated_at = datetime()
            """,
            rows=rows,
        ).consume()
    driver.close()
    print(f"Seeded {len(rows)} CAO concept placeholders.")

if __name__ == "__main__":
    main()
