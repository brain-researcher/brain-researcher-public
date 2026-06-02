"""
JSON Graph Loader for Railway deployment.

This module provides a lightweight graph database that loads from JSON
instead of SQLite, suitable for cloud deployments.
"""

import json
import logging
from typing import Any

logger = logging.getLogger(__name__)


class JSONGraphDB:
    """JSON-based graph database for deployment."""

    def __init__(self, json_path: str):
        """Initialize from JSON file."""
        self.json_path = json_path
        self.nodes = {}
        self.relationships = []
        self.node_labels = {}
        self.relationship_types = {}

        self._load_from_json()

    def _load_from_json(self):
        """Load graph data from JSON file."""
        logger.info(f"Loading graph data from: {self.json_path}")

        with open(self.json_path) as f:
            data = json.load(f)

        # Load nodes
        for label, nodes in data.get("nodes", {}).items():
            self.node_labels[label] = len(nodes)
            for node in nodes:
                node_id = node["id"]
                self.nodes[node_id] = {
                    "labels": label,
                    "properties": {k: v for k, v in node.items() if k != "id"},
                }

        # Load relationships
        rel_type_count = {}
        for rel in data.get("relationships", []):
            self.relationships.append(rel)
            rel_type = rel.get("type", "RELATED_TO")
            rel_type_count[rel_type] = rel_type_count.get(rel_type, 0) + 1

        self.relationship_types = rel_type_count

        logger.info(
            f"Loaded {len(self.nodes)} nodes and {len(self.relationships)} relationships"
        )

    def get_stats(self) -> dict[str, Any]:
        """Get database statistics."""
        return {
            "total_nodes": len(self.nodes),
            "total_relationships": len(self.relationships),
            "node_labels": self.node_labels.copy(),
            "relationship_types": self.relationship_types.copy(),
            "constraints": 0,  # No constraints in JSON
            "indexes": 0,  # No indexes in JSON
        }

    def find_nodes(
        self, labels: str = None, properties: dict[str, Any] = None
    ) -> list[tuple[str, dict[str, Any]]]:
        """Find nodes matching criteria."""
        results = []

        for node_id, node_data in self.nodes.items():
            # Check label match
            if labels and node_data["labels"] != labels:
                continue

            # Check property match
            if properties:
                node_props = node_data["properties"]
                match = all(node_props.get(k) == v for k, v in properties.items())
                if not match:
                    continue

            results.append((node_id, node_data["properties"]))

        return results

    def get_subgraph(self, start_node_id: str, depth: int = 2) -> dict[str, Any]:
        """Get subgraph starting from a node using BFS."""
        if start_node_id not in self.nodes:
            return None

        visited = set()
        to_visit = [(start_node_id, 0)]
        subgraph_nodes = {}
        subgraph_edges = []

        while to_visit:
            current_id, current_depth = to_visit.pop(0)

            if current_id in visited or current_depth > depth:
                continue

            visited.add(current_id)

            # Add node to subgraph
            node_data = self.nodes[current_id]
            subgraph_nodes[current_id] = {
                "id": current_id,
                "labels": [node_data["labels"]],
                **node_data["properties"],
            }

            # Find relationships
            if current_depth < depth:
                for rel in self.relationships:
                    if rel["source"] == current_id:
                        target_id = rel["target"]
                        if target_id in self.nodes:
                            subgraph_edges.append(
                                {
                                    "id": f"{rel['source']}-{rel['target']}-{rel['type']}",
                                    "source": rel["source"],
                                    "target": rel["target"],
                                    "label": rel["type"],
                                    **rel.get("properties", {}),
                                }
                            )
                            to_visit.append((target_id, current_depth + 1))

                    elif rel["target"] == current_id:
                        source_id = rel["source"]
                        if source_id in self.nodes:
                            subgraph_edges.append(
                                {
                                    "id": f"{rel['source']}-{rel['target']}-{rel['type']}",
                                    "source": rel["source"],
                                    "target": rel["target"],
                                    "label": rel["type"],
                                    **rel.get("properties", {}),
                                }
                            )
                            to_visit.append((source_id, current_depth + 1))

        # Ensure all edge nodes are included
        for edge in subgraph_edges:
            for node_id in [edge["source"], edge["target"]]:
                if node_id not in subgraph_nodes and node_id in self.nodes:
                    node_data = self.nodes[node_id]
                    subgraph_nodes[node_id] = {
                        "id": node_id,
                        "labels": [node_data["labels"]],
                        **node_data["properties"],
                    }

        return {"nodes": list(subgraph_nodes.values()), "edges": subgraph_edges}

    def close(self):
        """Close database connection (no-op for JSON)."""
        pass
