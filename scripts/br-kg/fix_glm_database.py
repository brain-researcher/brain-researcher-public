#!/usr/bin/env python3
"""Fix the GLM FitLins database by ensuring proper loading"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from brain_researcher.services.br_kg.graph.neo4j_utils import require_neo4j_db


def fix_database():
    """Run a Neo4j-backed GLM FitLins sanity check."""
    print("Checking GLM FitLins Neo4j backend...")

    db = require_neo4j_db(preload_cache=False)

    # Check stats
    stats = db.get_stats()
    print("\nDatabase stats after reload:")
    print(f"  Total nodes: {stats['total_nodes']}")
    print(f"  Total relationships: {stats['total_relationships']}")

    # Check relationship types
    try:
        rows = db.execute_query("MATCH ()-[r]->() RETURN type(r) AS type, count(r) AS cnt")
    except Exception:
        rows = []
    if rows:
        print("\nRelationship types:")
        for row in rows:
            rel_type = row.get("type")
            count = row.get("cnt")
            print(f"  {rel_type}: {count}")

    # Test INVOLVES_CONSTRUCT relationships
    involves_rels = db.find_relationships(rel_type="INVOLVES_CONSTRUCT")
    print(f"\nINVOLVES_CONSTRUCT relationships: {len(involves_rels)}")

    if involves_rels:
        # Check a sample
        _, _, edge_data = involves_rels[0]
        print(f"Sample relationship properties: {list(edge_data.keys())}")

    db.close()
    print("\nDatabase check complete!")


if __name__ == "__main__":
    fix_database()
