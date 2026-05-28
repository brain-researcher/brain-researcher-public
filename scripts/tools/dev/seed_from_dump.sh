#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEFAULT_DUMP_DIR="$SCRIPT_DIR/../../data/neo4j/mini_dump"
DUMP_DIR="${1:-$DEFAULT_DUMP_DIR}"
GRAPH_FILE="$DUMP_DIR/graph.json"

if [[ ! -f "$GRAPH_FILE" ]]; then
  echo "Mini dump not found at $GRAPH_FILE" >&2
  exit 1
fi

URI="${NEO4J_URI:-bolt://localhost:7687}"
USER="${NEO4J_USER:-neo4j}"
PASSWORD="${NEO4J_PASSWORD:-password}"
DATABASE="${NEO4J_DATABASE:-}"

python - "$GRAPH_FILE" "$URI" "$USER" "$PASSWORD" "$DATABASE" <<'PY'
import json
import pathlib
import sys

from neo4j import GraphDatabase

graph_path = pathlib.Path(sys.argv[1])
uri = sys.argv[2]
user = sys.argv[3]
password = sys.argv[4]
database = sys.argv[5] or None

data = json.loads(graph_path.read_text())
driver = GraphDatabase.driver(uri, auth=(user, password))


def _sanitize(value: str) -> str:
    return value.replace("`", "")


try:
    with driver.session(database=database) as session:
        session.run("MATCH (n) DETACH DELETE n")
        for statement in data.get("metadata", {}).get("constraint_cypher", []):
            session.run(statement)

        for node in data.get("nodes", []):
            labels = ":".join(f"`{_sanitize(label)}`" for label in node.get("labels", []))
            props = dict(node.get("properties", {}))
            node_id = node["id"]
            props.setdefault("id", node_id)
            if labels:
                cypher = f"MERGE (n:{labels} {{id:$id}}) SET n += $props"
            else:  # pragma: no cover
                cypher = "MERGE (n {id:$id}) SET n += $props"
            session.run(cypher, {"id": node_id, "props": props})

        for relationship in data.get("relationships", []):
            rel_type = _sanitize(relationship.get("type", "RELATED"))
            props = dict(relationship.get("properties", {}))
            session.run(
                f"""
                MATCH (s {{id:$start}}), (e {{id:$end}})
                MERGE (s)-[r:`{rel_type}`]->(e)
                SET r += $props
                """,
                {"start": relationship["start"], "end": relationship["end"], "props": props},
            )
finally:
    driver.close()
PY

INDEX_PLAN_SOURCE="$DUMP_DIR/index_plan.yaml"
if [[ -f "$INDEX_PLAN_SOURCE" ]]; then
  TARGET_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)/configs/neurokg"
  mkdir -p "$TARGET_DIR"
  cp "$INDEX_PLAN_SOURCE" "$TARGET_DIR/index_plan.yaml"
fi

echo "Seeded Neo4j at $URI using dump from $DUMP_DIR"
