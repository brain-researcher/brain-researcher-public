"""
Graph API routes as a Blueprint for integration into app.py
"""

import logging

from flask import Blueprint, jsonify, request

logger = logging.getLogger(__name__)

# Create blueprint
graph_routes_bp = Blueprint("graph_routes", __name__)


def init_graph_routes(db):
    """Initialize graph routes with database connection."""

    def _sanitize_value(val):
        """Convert Neo4j temporal/spatial values to JSON-safe representations."""
        try:
            if hasattr(val, "isoformat"):
                return val.isoformat()
            if isinstance(val, list | tuple):
                return [_sanitize_value(v) for v in val]
            if isinstance(val, dict):
                return {k: _sanitize_value(v) for k, v in val.items()}
        except Exception:
            pass
        return val

    @graph_routes_bp.route("/subgraph", methods=["GET"])
    def get_subgraph():
        """
        Get a subgraph starting from a specific node

        Query parameters:
        - node_id: Direct node id/elementId to start from (preferred)
        - label: Node label (e.g., 'Concept', 'BrainRegion', 'Study')
        - name: Node name to search for
        - depth: Traversal depth (default: 2, max: 3)
        """
        try:
            # Get query parameters
            node_id = request.args.get("node_id")
            node_label = request.args.get("label")
            node_name = request.args.get("name")
            depth = int(request.args.get("depth", 2))

            # Validate parameters
            if not node_id and (not node_label or not node_name):
                return (
                    jsonify(
                        {
                            "error": "Missing required parameters: node_id or (label and name)"
                        }
                    ),
                    400,
                )

            if depth < 1 or depth > 3:
                return jsonify({"error": "Depth must be between 1 and 3"}), 400

            # Resolve start node
            if node_id:
                start_node_id = node_id
            else:
                nodes = db.find_nodes(labels=node_label, properties={"name": node_name})
                if not nodes:
                    return (
                        jsonify(
                            {"error": f"No {node_label} found with name: {node_name}"}
                        ),
                        404,
                    )
                start_node_id = nodes[0][0]

            # Get subgraph based on database type
            if hasattr(db, "get_subgraph"):  # JSON database
                subgraph_data = db.get_subgraph(start_node_id, depth)
                if not subgraph_data:
                    return jsonify({"error": "Failed to get subgraph"}), 500

                # Format response for visualization
                response = {
                    "nodes": [{"data": node} for node in subgraph_data["nodes"]],
                    "edges": [{"data": edge} for edge in subgraph_data["edges"]],
                }
            else:  # SQLite database or Neo4j adapter with graph_bfs
                # Perform BFS traversal to get subgraph
                nodes_result, edges_result = db.graph_bfs(start_node_id, depth)

                # Format response for visualization
                response = {"nodes": [], "edges": []}

                # Add nodes
                for node in nodes_result:
                    props = _sanitize_value(node.get("properties", {}))
                    node_data = {
                        "data": {
                            "id": str(node["id"]),
                            "label": node.get("name", f'Node {node["id"]}'),
                            "labels": node.get("labels", []),
                            **props,
                        }
                    }
                    response["nodes"].append(node_data)

                # Add edges
                for edge in edges_result:
                    source = (
                        edge.get("source_id") or edge.get("start") or edge.get("from")
                    )
                    target = edge.get("target_id") or edge.get("end") or edge.get("to")
                    if not source or not target:
                        logger.warning("Skipping edge without source/target: %s", edge)
                        continue

                    edge_props = _sanitize_value(edge.get("properties", {}))
                    edge_data = {
                        "data": {
                            "id": f"{source}-{target}",
                            "source": str(source),
                            "target": str(target),
                            "relationship": edge.get("type")
                            or edge.get("relationship", "RELATED_TO"),
                            **edge_props,
                        }
                    }
                    response["edges"].append(edge_data)

            return jsonify(response)

        except ValueError as e:
            logger.error(f"Invalid parameters: {str(e)}")
            return jsonify({"error": f"Invalid parameters: {str(e)}"}), 400
        except Exception as e:
            logger.error(f"Error getting subgraph: {str(e)}")
            return jsonify({"error": f"Internal server error: {str(e)}"}), 500

    return graph_routes_bp
