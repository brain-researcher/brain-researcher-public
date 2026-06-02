"""
JSON-based Graph Database for Cloud Deployment

This module provides a JSON-based graph database implementation
for cloud deployment where SQLite might not be suitable.
"""

import json
import logging
from pathlib import Path
from typing import Any

import networkx as nx

logger = logging.getLogger(__name__)


class JSONGraphDatabase:
    """JSON-based graph database for cloud deployment"""

    def __init__(self, json_path: str):
        self.json_path = Path(json_path)
        self.graph = nx.MultiDiGraph()
        self.nodes_data = {}
        self.relationships_data = {}
        self._load_data()

    def _load_data(self):
        """Load data from JSON file"""
        try:
            with open(self.json_path) as f:
                data = json.load(f)

            # Load nodes
            for node in data.get("nodes", []):
                node_id = node["id"]
                labels = node.get("labels", [])
                properties = node.get("properties", {})

                # Store full node data
                self.nodes_data[node_id] = {"labels": labels, "properties": properties}

                # Add to NetworkX graph
                self.graph.add_node(node_id, labels=labels, **properties)

            # Load relationships
            for rel in data.get("relationships", []):
                start_node = rel["start_node"]
                end_node = rel["end_node"]
                rel_type = rel["type"]
                properties = rel.get("properties", {})

                # Store relationship data
                rel_id = f"{start_node}_{rel_type}_{end_node}"
                self.relationships_data[rel_id] = {
                    "start_node": start_node,
                    "end_node": end_node,
                    "type": rel_type,
                    "properties": properties,
                }

                # Add to NetworkX graph
                self.graph.add_edge(start_node, end_node, type=rel_type, **properties)

            logger.info(
                f"Loaded {len(self.nodes_data)} nodes and "
                f"{len(self.relationships_data)} relationships from JSON"
            )

        except Exception as e:
            logger.error(f"Error loading JSON data: {e}")
            raise

    def find_nodes(
        self, labels: str | None = None, properties: dict[str, Any] | None = None
    ) -> list[tuple[str, dict]]:
        """Find nodes by labels and/or properties"""
        results = []

        for node_id, node_data in self.nodes_data.items():
            # Check labels
            if labels and labels not in node_data.get("labels", []):
                continue

            # Check properties
            if properties:
                node_props = node_data.get("properties", {})
                if not all(node_props.get(k) == v for k, v in properties.items()):
                    continue

            # Return node data in expected format
            combined_data = {
                "labels": node_data.get("labels", []),
                **node_data.get("properties", {}),
            }
            results.append((node_id, combined_data))

        return results

    def find_relationships(
        self,
        start_node: str | None = None,
        end_node: str | None = None,
        rel_type: str | None = None,
    ) -> list[tuple[str, str, dict]]:
        """Find relationships by start_node, end_node, and/or type"""
        results = []

        for rel_id, rel_data in self.relationships_data.items():
            # Check start node
            if start_node and rel_data["start_node"] != start_node:
                continue

            # Check end node
            if end_node and rel_data["end_node"] != end_node:
                continue

            # Check relationship type
            if rel_type and rel_data["type"] != rel_type:
                continue

            results.append(
                (
                    rel_data["start_node"],
                    rel_data["end_node"],
                    rel_data.get("properties", {}),
                )
            )

        return results

    def get_stats(self) -> dict[str, Any]:
        """Get database statistics"""
        # Count nodes by label
        label_counts = {}
        for node_data in self.nodes_data.values():
            for label in node_data.get("labels", []):
                label_counts[label] = label_counts.get(label, 0) + 1

        # Count relationships by type
        type_counts = {}
        for rel_data in self.relationships_data.values():
            rel_type = rel_data["type"]
            type_counts[rel_type] = type_counts.get(rel_type, 0) + 1

        return {
            "total_nodes": len(self.nodes_data),
            "total_relationships": len(self.relationships_data),
            "node_labels": label_counts,
            "relationship_types": type_counts,
        }

    def close(self):
        """Close database connection (no-op for JSON)"""
        pass
