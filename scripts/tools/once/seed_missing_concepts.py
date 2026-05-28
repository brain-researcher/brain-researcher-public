#!/usr/bin/env python3
"""Seed placeholder Concept nodes for IDs referenced by taxonomy but missing in Neo4j."""
import json
from pathlib import Path
import os
from neo4j import GraphDatabase

NEO4J_URI = os.environ["NEO4J_URI"]
NEO4J_USER = os.environ["NEO4J_USER"]
NEO4J_PASSWORD = os.environ["NEO4J_PASSWORD"]
NEO4J_DATABASE = os.getenv("NEO4J_DATABASE", "neo4j")
ENTITIES = json.loads(Path("brain_researcher/semantics/taxonomy/entities.json").read_text())["entities"]

MISSING_IDS = [
    "trm_525331a9dc89f",
    "trm_4a3fd79d0a5c8",
    "trm_4d559bcd67c19",
    "trm_4c89912c79030",
    "concept:working_memory",
    "concept:reward_processing",
]

def resolve_label(concept_id: str) -> str:
    for payload in ENTITIES.values():
        links = payload.get("links") or {}
        cogat = links.get("cogat")
        if cogat and cogat.lower() == concept_id.lower():
            return payload.get("label") or concept_id
    return concept_id

def seed():
    rows = []
    for cid in MISSING_IDS:
        rows.append({"id": cid.upper(), "name": resolve_label(cid)})
    driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))
    with driver.session(database=NEO4J_DATABASE) as session:
        session.run(
            """
            UNWIND $rows AS row
            MERGE (c:Concept {id: row.id})
              ON CREATE SET c.name = row.name,
                            c.source = 'cognitive_atlas_seed',
                            c.created_at = datetime()
              ON MATCH  SET c.name = coalesce(c.name, row.name),
                            c.updated_at = datetime()
            """,
            rows=rows,
        ).consume()
    driver.close()
    print(f"Seeded/updated {len(rows)} placeholder concepts.")

if __name__ == "__main__":
    seed()
