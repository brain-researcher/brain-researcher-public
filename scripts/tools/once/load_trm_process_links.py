#!/usr/bin/env python3
"""Upsert Process nodes and CLASSIFIED_UNDER edges for TRM concepts via Cognitive Atlas API."""
import os
import requests
from neo4j import GraphDatabase

API_URL = os.environ.get("COGAT_CONCEPT_API", "https://www.cognitiveatlas.org/api/v-alpha/concept")
NEO4J_URI = os.environ["NEO4J_URI"]
NEO4J_USER = os.environ["NEO4J_USER"]
NEO4J_PASSWORD = os.environ["NEO4J_PASSWORD"]
NEO4J_DATABASE = os.environ.get("NEO4J_DATABASE", "neo4j")

PROCESS_NAMES = {
    "ctp_C1": "Perception",
    "ctp_C2": "Attention",
    "ctp_C3": "Reasoning and Decision Making",
    "ctp_C4": "Executive/Cognitive Control",
    "ctp_C5": "Learning and Memory",
    "ctp_C6": "Language",
    "ctp_C7": "Action",
    "ctp_C8": "Emotion",
    "ctp_C9": "Social Cognition",
    "ctp_C10": "Motivation",
}

def fetch_concepts() -> list[dict]:
    resp = requests.get(API_URL, timeout=120)
    resp.raise_for_status()
    payload = resp.json()
    if isinstance(payload, dict) and "results" in payload:
        return payload["results"]
    return payload if isinstance(payload, list) else []

def main() -> None:
    concepts = fetch_concepts()
    links: list[dict] = []
    for rec in concepts:
        cid = rec.get("id")
        pid = rec.get("id_concept_class")
        if not cid or not pid:
            continue
        pname = PROCESS_NAMES.get(pid, rec.get("concept_class") or pid)
        links.append({"concept_id": cid, "process_id": pid, "process_name": pname})
    if not links:
        raise SystemExit("No concept→process rows found; aborting.")

    driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))
    with driver.session(database=NEO4J_DATABASE) as session:
        session.run(
            """
            UNWIND $rows AS row
            MERGE (p:Process {id: row.process_id})
              ON CREATE SET p.name = row.process_name,
                            p.source = 'cognitive_atlas',
                            p.created_at = datetime()
              ON MATCH  SET p.name = row.process_name,
                            p.updated_at = datetime()
            """,
            rows=links,
        ).consume()

        session.run(
            """
            UNWIND $rows AS row
            MATCH (c:Concept {id: row.concept_id})
            MATCH (p:Process {id: row.process_id})
            MERGE (c)-[r:CLASSIFIED_UNDER {source:'cognitive_atlas'}]->(p)
              ON CREATE SET r.created_at = datetime()
              ON MATCH  SET r.updated_at = datetime()
            """,
            rows=links,
        ).consume()

    driver.close()
    print(f"Linked {len(links)} concepts to processes via CLASSIFIED_UNDER.")

if __name__ == "__main__":
    main()
