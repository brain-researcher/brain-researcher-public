#!/usr/bin/env python3
"""
Create a trimmed Neo4j export suitable for local testing and CI seeding.

The script captures a small slice of the graph (10–20 Task nodes plus their
immediate neighbourhood) and writes it to ``graph.json`` along with the current
constraint statements.  The output directory defaults to
``data/neo4j/mini_dump`` and also receives a copy of ``configs/br-kg/index_plan.yaml``
for convenience.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Iterable, Tuple

try:
    from neo4j import GraphDatabase, Node, Relationship
except Exception as exc:  # pragma: no cover
    raise SystemExit(
        "neo4j driver is required. Install it with `pip install neo4j`."
    ) from exc


@dataclass
class ExportConfig:
    task_limit: int
    output_dir: Path
    index_plan_source: Path
    uri: str
    user: str
    password: str
    database: str | None


def parse_args() -> ExportConfig:
    parser = argparse.ArgumentParser(description="Create a mini Neo4j dump.")
    parser.add_argument(
        "--output",
        default="data/neo4j/mini_dump",
        help="Directory to store the dump (default: %(default)s)",
    )
    parser.add_argument(
        "--task-limit",
        type=int,
        default=12,
        help="Maximum number of Task nodes to capture (default: %(default)s)",
    )
    parser.add_argument(
        "--index-plan",
        default="configs/br-kg/index_plan.yaml",
        help="Path to index_plan.yaml to copy alongside the dump",
    )
    parser.add_argument(
        "--uri",
        default=os.environ.get("NEO4J_URI", "bolt://localhost:7687"),
        help="Neo4j connection URI (default: %(default)s or $NEO4J_URI)",
    )
    parser.add_argument(
        "--user",
        default=os.environ.get("NEO4J_USER", "neo4j"),
        help="Neo4j username (default: %(default)s or $NEO4J_USER)",
    )
    parser.add_argument(
        "--password",
        default=os.environ.get("NEO4J_PASSWORD", "password"),
        help="Neo4j password (default: %(default)s or $NEO4J_PASSWORD)",
    )
    parser.add_argument(
        "--database",
        default=os.environ.get("NEO4J_DATABASE"),
        help="Neo4j database name (default: %(default)s or $NEO4J_DATABASE)",
    )

    args = parser.parse_args()
    output_dir = Path(args.output).expanduser().resolve()
    index_plan_source = Path(args.index_plan).expanduser().resolve()

    return ExportConfig(
        task_limit=args.task_limit,
        output_dir=output_dir,
        index_plan_source=index_plan_source,
        uri=args.uri,
        user=args.user,
        password=args.password,
        database=args.database or None,
    )


def node_key(node: Node) -> str:
    return getattr(node, "element_id", None) or str(getattr(node, "id"))


def serialise_node(node: Node) -> Tuple[str, Dict]:
    props = dict(node)
    ext_id = props.get("id") or node_key(node)
    payload = {
        "id": str(ext_id),
        "labels": sorted(node.labels),
        "properties": props,
    }
    payload["properties"].setdefault("id", payload["id"])
    return payload["id"], payload


def serialise_relationship(
    relationship: Relationship,
    id_map: Dict[str, str],
) -> Dict:
    start_internal = node_key(relationship.start_node)
    end_internal = node_key(relationship.end_node)
    try:
        start_external = id_map[start_internal]
        end_external = id_map[end_internal]
    except KeyError as exc:  # pragma: no cover
        raise RuntimeError(
            "Encountered relationship referencing node not present in dump"
        ) from exc

    rel_props = dict(relationship)
    return {
        "start": start_external,
        "end": end_external,
        "type": relationship.type,
        "properties": rel_props,
    }


def unique_key(rel_payload: Dict) -> Tuple:
    props_items = tuple(sorted(rel_payload.get("properties", {}).items()))
    return (rel_payload["start"], rel_payload["end"], rel_payload["type"], props_items)


def export_graph(cfg: ExportConfig) -> Dict:
    driver = GraphDatabase.driver(cfg.uri, auth=(cfg.user, cfg.password))
    node_store: Dict[str, Dict] = {}
    id_map: Dict[str, str] = {}
    relationships = []
    seen_relationships = set()
    task_ids: set[str] = set()

    try:
        with driver.session(database=cfg.database) as session:
            result = session.run(
                """
                MATCH (t:Task)
                RETURN t
                ORDER BY coalesce(t.priority, t.name, t.id)
                LIMIT $limit
                """,
                limit=cfg.task_limit,
            )
            tasks = [record["t"] for record in result]
            if not tasks:
                raise RuntimeError("No Task nodes found; cannot build dump.")

            for task in tasks:
                node_id, payload = serialise_node(task)
                node_store[node_id] = payload
                id_map[node_key(task)] = node_id
                task_ids.add(node_id)

            result = session.run(
                """
                MATCH (t:Task)-[r]-(n)
                WHERE t.id IN $task_ids
                RETURN t, r, n
                """,
                task_ids=list(task_ids),
            )
            for record in result:
                for node in (record["t"], record["n"], record["r"].start_node, record["r"].end_node):
                    node_id, payload = serialise_node(node)
                    node_store[node_id] = payload
                    id_map[node_key(node)] = node_id

                rel_payload = serialise_relationship(record["r"], id_map)
                rel_key = unique_key(rel_payload)
                if rel_key not in seen_relationships:
                    seen_relationships.add(rel_key)
                    relationships.append(rel_payload)

            # Capture relationships among already selected nodes (depth-two neighbourhood)
            result = session.run(
                """
                MATCH (a)-[r]-(b)
                WHERE a.id IN $ids AND b.id IN $ids
                RETURN a, r, b
                """,
                ids=list(node_store.keys()),
            )
            for record in result:
                for node in (record["a"], record["b"], record["r"].start_node, record["r"].end_node):
                    node_id, payload = serialise_node(node)
                    node_store[node_id] = payload
                    id_map[node_key(node)] = node_id

                rel_payload = serialise_relationship(record["r"], id_map)
                rel_key = unique_key(rel_payload)
                if rel_key not in seen_relationships:
                    seen_relationships.add(rel_key)
                    relationships.append(rel_payload)

            constraint_statements = []
            constraint_result = session.run(
                "SHOW CONSTRAINTS YIELD createStatement RETURN createStatement"
            )
            for record in constraint_result:
                stmt = record["createStatement"]
                if stmt not in constraint_statements:
                    constraint_statements.append(stmt)
    finally:
        driver.close()

    metadata = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "task_ids": sorted(task_ids),
        "node_count": len(node_store),
        "relationship_count": len(relationships),
        "constraint_cypher": constraint_statements,
    }

    dump = {
        "metadata": metadata,
        "nodes": sorted(node_store.values(), key=lambda item: item["id"]),
        "relationships": relationships,
    }
    return dump


def copy_index_plan(source: Path, destination_dir: Path) -> None:
    if not source.exists():
        print(f"warning: index plan not found at {source}", file=sys.stderr)
        return
    destination_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy(source, destination_dir / "index_plan.yaml")


def main() -> None:
    cfg = parse_args()
    cfg.output_dir.mkdir(parents=True, exist_ok=True)
    dump = export_graph(cfg)
    output_path = cfg.output_dir / "graph.json"
    output_path.write_text(json.dumps(dump, indent=2, sort_keys=True))
    copy_index_plan(cfg.index_plan_source, cfg.output_dir)
    print(f"Wrote mini dump to {output_path}")


if __name__ == "__main__":
    main()
