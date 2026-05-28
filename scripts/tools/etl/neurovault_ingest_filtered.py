#!/usr/bin/env python3
"""
Ingest filtered NeuroVault metadata into Neo4j (no NIfTI downloads).

Inputs:
  - Filtered metadata JSON from scripts/tools/etl/neurovault_filter.py
    default: data/neurovault/cache/neurovault_images_filtered.json

Behavior:
  - Uses EnhancedNeuroVaultLoader to create StatMap and Collection nodes
  - Stores file/thumbnail URLs only (no image downloads)
  - Optional --limit for sanity; optional --dry-run to show counts only
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from brain_researcher.services.neurokg.etl.loaders.enhanced_neurovault_loader import (
    EnhancedNeuroVaultLoader,
)
from brain_researcher.services.neurokg.graph.neo4j_graph_database import (
    Neo4jGraphDB,
)

DEFAULT_JSON = Path("data/neurovault/cache/neurovault_images_filtered.json")


def load_maps(path: Path) -> list[dict]:
    with path.open() as f:
        data = json.load(f)
    if isinstance(data, dict):
        return data.get("statistical_maps", [])
    return data


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Ingest filtered NeuroVault metadata into Neo4j")
    p.add_argument("--json", type=Path, default=DEFAULT_JSON, help="Filtered NeuroVault JSON file")
    p.add_argument("--limit", type=int, default=0, help="Optional cap on maps to ingest (0 = all)")
    p.add_argument("--offset", type=int, default=0, help="Skip this many maps from the start before ingesting")
    p.add_argument("--min-id", type=int, default=None, help="Require numeric id >= this value")
    p.add_argument("--max-id", type=int, default=None, help="Require numeric id <= this value")
    p.add_argument("--confidence", type=float, default=0.7, help="Contrast matching confidence threshold")
    p.add_argument("--dry-run", action="store_true", help="Run filters and report counts without DB writes")
    p.add_argument("--neo4j-uri", default=os.getenv("NEO4J_URI", "bolt://localhost:7687"))
    p.add_argument("--neo4j-user", default=os.getenv("NEO4J_USER", "neo4j"))
    p.add_argument("--neo4j-password", default=os.getenv("NEO4J_PASSWORD", "password"))
    p.add_argument("--neo4j-database", default=os.getenv("NEO4J_DATABASE", None))
    return p.parse_args()


class _StubDB:
    """Minimal stub to let EnhancedNeuroVaultLoader run filters without Neo4j."""

    def __init__(self):
        self.graph = None

    def find_nodes(self, *args, **kwargs):
        return []

    def close(self):
        return None

    def create_node(self, *args, **kwargs):
        return "stub"

    def create_relationship(self, *args, **kwargs):
        return None


def main() -> None:
    args = parse_args()

    maps = load_maps(args.json)

    # Filter by id bounds if provided
    def _id_ok(m: dict) -> bool:
        try:
            mid = int(m.get("id"))
        except Exception:
            return False
        if args.min_id is not None and mid < args.min_id:
            return False
        if args.max_id is not None and mid > args.max_id:
            return False
        return True

    if args.min_id is not None or args.max_id is not None:
        maps = [m for m in maps if _id_ok(m)]

    if args.offset:
        maps = maps[args.offset :]
    if args.limit and args.limit > 0:
        maps = maps[: args.limit]

    print(f"Loaded {len(maps)} maps from {args.json}")
    if maps:
        print(f"First id: {maps[0].get('id')}, last id: {maps[-1].get('id')}")

    if args.dry_run:
        stub = _StubDB()
        loader = EnhancedNeuroVaultLoader(stub)
        filtered = loader._filter_and_cap_maps(maps)  # type: ignore[attr-defined]
        print(f"[DRY RUN] Would ingest {len(filtered)} maps after loader filters/caps")
        stub.close()
        return

    db = Neo4jGraphDB(
        uri=args.neo4j_uri,
        user=args.neo4j_user,
        password=args.neo4j_password,
        database=args.neo4j_database,
        preload_cache=False,
    )

    loader = EnhancedNeuroVaultLoader(db)

    stats = loader.ingest_maps(maps, confidence_threshold=args.confidence)
    print("Ingestion complete:")
    for k, v in stats.items():
        print(f"  {k}: {v}")

    db.close()


if __name__ == "__main__":
    main()
