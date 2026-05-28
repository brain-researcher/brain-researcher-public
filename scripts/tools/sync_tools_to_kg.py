"""Sync current ToolSpec set into BR-KG (Neo4j) and optionally purge stale tools.

Usage examples:
  python scripts/tools/sync_tools_to_kg.py \
      --uri bolt://localhost:7687 --user neo4j --password *** \
      --purge-stale

  # Sync pipelines too
  python scripts/tools/sync_tools_to_kg.py --include-pipelines

  # Dry-run (prints what would be sent)
  python scripts/tools/sync_tools_to_kg.py --dry-run
"""

from __future__ import annotations

import argparse
import json
import os
from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any, Dict, List

import yaml
from neo4j import GraphDatabase

from brain_researcher.services.tools.catalog_loader import load_tool_specs

CONFIGS_DIR = Path(__file__).resolve().parents[2] / "configs"


def _to_tool_payload(spec) -> Dict[str, Any]:
    """Convert ToolSpec to a JSON-serializable dict for Cypher parameters."""
    if is_dataclass(spec):
        d = asdict(spec)
    elif hasattr(spec, "model_dump"):
        d = spec.model_dump()
    elif hasattr(spec, "dict"):
        d = spec.dict()
    else:
        # Last resort: use __dict__
        d = dict(spec.__dict__)
    # Ensure lists, not tuples
    d["intents"] = list(d.get("intents", []) or [])
    d["modalities"] = list(d.get("modalities", []) or [])
    # Normalize id: ToolSpec uses `name` as identifier
    d["id"] = d.get("id") or d.get("name")
    # Trim fields we don't store on Tool node
    d.pop("json_schema", None)
    d.pop("description_json", None)
    return d


def upsert_tools(tx, tools: List[Dict[str, Any]]):
    """Upsert Tool + Intent/Modality relationships."""
    cypher = """
    UNWIND $tools AS tool
      MERGE (t:Tool {id: tool.id})
        ON CREATE SET t.created_at = timestamp()
      SET t.name        = coalesce(tool.name, tool.id),
          t.description = coalesce(tool.description, ""),
          t.backend     = coalesce(tool.backend, "python"),
          t.kind        = tool.kind,
          t.updated_at  = timestamp()

      FOREACH (intent IN tool.intents |
        MERGE (i:Intent {id:intent})
        MERGE (t)-[:SUPPORTS_INTENT]->(i)
      )

      FOREACH (mod IN tool.modalities |
        MERGE (m:Modality {id:mod})
        MERGE (t)-[:WORKS_ON_MODALITY]->(m)
      )
    """
    tx.run(cypher, tools=tools)


def purge_stale(tx, keep_ids: List[str]) -> int:
    """Remove Tool nodes not present in keep_ids. Returns count deleted."""
    cypher = """
    MATCH (t:Tool)
    WHERE NOT t.id IN $keep_ids
    WITH t LIMIT 1000  // batch to avoid huge transactions
    DETACH DELETE t
    RETURN count(*) AS deleted
    """
    result = tx.run(cypher, keep_ids=keep_ids)
    record = result.single()
    return record["deleted"] if record else 0


def load_pipelines() -> List[Dict[str, Any]]:
    """Load pipeline templates from configs/catalog/pipelines.yaml."""
    pipelines_path = CONFIGS_DIR / "catalog" / "pipelines.yaml"
    if not pipelines_path.exists():
        return []
    with open(pipelines_path) as f:
        data = yaml.safe_load(f) or {}
    return data.get("pipelines", [])


def upsert_pipelines(tx, pipelines: List[Dict[str, Any]]):
    """Upsert Pipeline nodes and STEP relationships to Tools."""
    # First, create/update Pipeline nodes
    pipeline_cypher = """
    UNWIND $pipelines AS pipe
      MERGE (p:Pipeline {id: pipe.id})
        ON CREATE SET p.created_at = timestamp()
      SET p.name        = coalesce(pipe.name, pipe.id),
          p.description = coalesce(pipe.description, ""),
          p.modalities  = coalesce(pipe.modalities, []),
          p.updated_at  = timestamp()
    """
    tx.run(pipeline_cypher, pipelines=pipelines)

    # Then, create STEP relationships with order property
    # First delete existing STEP relationships to refresh
    for pipe in pipelines:
        delete_cypher = """
        MATCH (p:Pipeline {id: $pipe_id})-[r:STEP]->()
        DELETE r
        """
        tx.run(delete_cypher, pipe_id=pipe["id"])

        # Create new STEP relationships
        for step in pipe.get("steps", []):
            step_cypher = """
            MATCH (p:Pipeline {id: $pipe_id})
            MATCH (t:Tool {id: $tool_id})
            MERGE (p)-[r:STEP {order: $order}]->(t)
            SET r.description = $description
            """
            tx.run(
                step_cypher,
                pipe_id=pipe["id"],
                tool_id=step["tool"],
                order=step["order"],
                description=step.get("description", ""),
            )


def main():
    parser = argparse.ArgumentParser(description="Sync ToolSpec to BR-KG (Neo4j).")
    parser.add_argument("--uri", default=os.getenv("NEO4J_URI", "bolt://localhost:7687"))
    parser.add_argument("--user", default=os.getenv("NEO4J_USER", "neo4j"))
    parser.add_argument("--password", default=os.getenv("NEO4J_PASSWORD"))
    parser.add_argument("--purge-stale", action="store_true", help="Delete Tool nodes not in the current ToolSpec set.")
    parser.add_argument("--include-pipelines", action="store_true", help="Also sync pipeline templates from configs/catalog/pipelines.yaml.")
    parser.add_argument("--dry-run", action="store_true", help="Print payloads instead of writing to Neo4j.")
    args = parser.parse_args()

    specs = load_tool_specs(force_reload=True)
    tools_payload = [_to_tool_payload(s) for s in specs]
    keep_ids = [t["id"] for t in tools_payload]

    pipelines = []
    if args.include_pipelines:
        pipelines = load_pipelines()

    if args.dry_run:
        print(f"[dry-run] Would upsert {len(tools_payload)} tools")
        print(json.dumps({"tools": tools_payload[:5]}, indent=2))  # preview first 5
        if args.purge_stale:
            print("[dry-run] Would purge tools NOT in keep_ids (len=%d)" % len(keep_ids))
        if pipelines:
            print(f"\n[dry-run] Would upsert {len(pipelines)} pipelines:")
            for p in pipelines:
                steps = [s["tool"] for s in p.get("steps", [])]
                print(f"  - {p['id']}: {' -> '.join(steps)}")
        return

    if not args.password:
        raise SystemExit("Neo4j password is required (set NEO4J_PASSWORD or use --password).")

    driver = GraphDatabase.driver(args.uri, auth=(args.user, args.password))
    with driver.session() as session:
        # Upsert tools + relationships
        session.execute_write(upsert_tools, tools_payload)

        deleted_total = 0
        if args.purge_stale:
            # Batch delete to avoid transaction blow-up
            while True:
                deleted = session.execute_write(purge_stale, keep_ids)
                deleted_total += deleted
                if deleted == 0:
                    break
            print(f"Purged stale tools: {deleted_total}")

        # Upsert pipelines if requested
        if pipelines:
            session.execute_write(upsert_pipelines, pipelines)
            print(f"Synced {len(pipelines)} pipelines to Neo4j")

    print(f"Synced {len(tools_payload)} tools to Neo4j at {args.uri}")


if __name__ == "__main__":
    main()
