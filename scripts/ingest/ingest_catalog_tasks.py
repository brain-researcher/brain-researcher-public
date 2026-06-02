import json, os
from pathlib import Path
from neo4j import GraphDatabase

NEO4J_URI = os.environ.get("NEO4J_URI")
NEO4J_USER = os.environ.get("NEO4J_USER")
NEO4J_PASSWORD = os.environ.get("NEO4J_PASSWORD")
NEO4J_DB = os.environ.get("NEO4J_DATABASE") or None
if not (NEO4J_URI and NEO4J_USER and NEO4J_PASSWORD):
    raise SystemExit("Missing NEO4J env vars")

CATALOG = Path("configs/datasets/catalog.v1.jsonl")
if not CATALOG.exists():
    raise SystemExit(f"Catalog not found: {CATALOG}")

def iter_rows(path):
    with path.open() as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            yield json.loads(line)

with GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD)) as driver:
    with driver.session(database=NEO4J_DB) as session:
        linked = 0
        missing = 0
        for row in iter_rows(CATALOG):
            ds_id = row.get("dataset_id")
            tasks = row.get("tasks") or []
            if not ds_id or not tasks:
                continue
            exists = session.run("MATCH (d:Dataset {id:$id}) RETURN d LIMIT 1", {"id": ds_id}).single()
            if not exists:
                missing += 1
                continue
            for tname in tasks:
                if not tname:
                    continue
                session.run(
                    """
                    MERGE (t:Task {name:$tname})
                    ON CREATE SET t.source = coalesce(t.source,"catalog")
                    WITH t
                    MATCH (d:Dataset {id:$ds})
                    MERGE (d)-[:HAS_TASK]->(t)
                    """,
                    {"tname": tname, "ds": ds_id},
                )
                linked += 1
        print(f"Linked tasks created: {linked}; datasets missing: {missing}")
