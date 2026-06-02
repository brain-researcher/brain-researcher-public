#!/usr/bin/env python3
"""
Export BR-KG Graph Database to JSON for Railway deployment.

This script exports all nodes and relationships from the SQLite database
to a JSON file that can be used in cloud deployments.
"""

import json
import sys
from pathlib import Path

# Add br_kg directory to path
sys.path.insert(0, str(Path(__file__).parent))

from graph.graph_database import BRKGGraphDB


def export_database_to_json(db_path: str, output_path: str):
    """Export database to JSON format."""
    print(f"Loading database from: {db_path}")
    db = BRKGGraphDB(db_path)

    # Get statistics
    stats = db.get_stats()
    print(
        f"Database contains: {stats['total_nodes']} nodes, {stats['total_relationships']} relationships"
    )

    # Export data
    export_data = {
        "metadata": {
            "source": db_path,
            "export_date": str(Path(db_path).stat().st_mtime),
            "statistics": stats,
        },
        "nodes": {},
        "relationships": [],
    }

    # Export nodes by type
    for label in stats.get("node_labels", {}):
        print(f"Exporting {label} nodes...")
        nodes = db.find_nodes(labels=label)
        export_data["nodes"][label] = []

        for node_id, properties in nodes:
            node_data = {"id": node_id}
            node_data.update(properties)
            export_data["nodes"][label].append(node_data)

    # Export relationships
    print("Exporting relationships...")

    # Get all relationships
    relationships = db.find_relationships()  # Get all relationships

    for start_node, end_node, edge_data in relationships:
        rel_type = edge_data.get("type", "RELATED_TO")
        export_data["relationships"].append(
            {
                "source": start_node,
                "target": end_node,
                "type": rel_type,
                "properties": {k: v for k, v in edge_data.items() if k != "type"},
            }
        )

    # Save to JSON
    print(f"Saving to: {output_path}")
    with open(output_path, "w") as f:
        json.dump(export_data, f, indent=2)

    print(
        f"Export complete! Exported {len(export_data['relationships'])} relationships"
    )

    # Close database
    db.close()


if __name__ == "__main__":
    # Use the database with all our loaded data
    db_path = "../../data/br-kg/db/br_kg_full.db"
    output_path = "br_kg_graph_export.json"

    export_database_to_json(db_path, output_path)
