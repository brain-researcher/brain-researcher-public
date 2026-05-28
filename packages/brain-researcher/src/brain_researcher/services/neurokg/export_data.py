#!/usr/bin/env python3
"""
Export GLM FitLins database data to JSON for cloud deployment
"""

import json
import sqlite3
from pathlib import Path


def export_database():
    """Export database to JSON format"""
    db_path = Path("data/neurokg/db/neurokg_glmfitlins.db")

    if not db_path.exists():
        print(f"Database not found: {db_path}")
        return

    # Connect to database
    conn = sqlite3.connect(str(db_path))
    cursor = conn.cursor()

    # Export nodes
    cursor.execute("SELECT * FROM nodes")
    nodes = cursor.fetchall()

    # Get column names
    cursor.execute("PRAGMA table_info(nodes)")
    node_columns = [row[1] for row in cursor.fetchall()]

    # Export relationships
    cursor.execute("SELECT * FROM relationships")
    relationships = cursor.fetchall()

    cursor.execute("PRAGMA table_info(relationships)")
    rel_columns = [row[1] for row in cursor.fetchall()]

    # Convert to dictionaries
    nodes_data = []
    for row in nodes:
        node_dict = dict(zip(node_columns, row, strict=False))
        # Parse JSON fields
        if "labels" in node_dict and node_dict["labels"]:
            node_dict["labels"] = json.loads(node_dict["labels"])
        if "properties" in node_dict and node_dict["properties"]:
            node_dict["properties"] = json.loads(node_dict["properties"])
        nodes_data.append(node_dict)

    relationships_data = []
    for row in relationships:
        rel_dict = dict(zip(rel_columns, row, strict=False))
        # Parse JSON fields
        if "properties" in rel_dict and rel_dict["properties"]:
            rel_dict["properties"] = json.loads(rel_dict["properties"])
        relationships_data.append(rel_dict)

    # Export to JSON
    data = {
        "nodes": nodes_data,
        "relationships": relationships_data,
        "metadata": {
            "total_nodes": len(nodes_data),
            "total_relationships": len(relationships_data),
            "export_version": "1.0",
        },
    }

    # Save to file
    output_path = Path("neurokg_glmfitlins_export.json")
    with open(output_path, "w") as f:
        json.dump(data, f, indent=2)

    print(f"Database exported to {output_path}")
    print(f"- Nodes: {len(nodes_data)}")
    print(f"- Relationships: {len(relationships_data)}")

    conn.close()


if __name__ == "__main__":
    export_database()
