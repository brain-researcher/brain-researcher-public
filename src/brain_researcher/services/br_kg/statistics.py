"""
Graph statistics API for BR-KG.
Implements KG-013: Graph Statistics API
"""

import logging
from collections import Counter, defaultdict
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


@dataclass
class NodeStatistics:
    """Statistics for a node type."""
    count: int
    avg_degree: float
    max_degree: int
    min_degree: int
    properties: Dict[str, int]  # Property name -> count


@dataclass
class EdgeStatistics:
    """Statistics for an edge type."""
    count: int
    avg_confidence: float
    confidence_distribution: Dict[str, int]  # Range -> count
    source_distribution: Dict[str, int]  # Source -> count


@dataclass
class GraphStatistics:
    """Overall graph statistics."""
    total_nodes: int
    total_edges: int
    node_types: Dict[str, NodeStatistics]
    edge_types: Dict[str, EdgeStatistics]
    density: float
    avg_clustering_coefficient: float
    connected_components: int
    largest_component_size: int
    diameter: Optional[int]


class GraphAnalyzer:
    """Analyzer for graph statistics and metrics."""

    def __init__(self, db):
        """Initialize analyzer with database."""
        self.db = db
        self._cache = {}

    def get_statistics(self, use_cache: bool = True) -> GraphStatistics:
        """
        Get comprehensive graph statistics.

        Args:
            use_cache: Whether to use cached results

        Returns:
            GraphStatistics object with all metrics
        """
        if use_cache and "stats" in self._cache:
            return self._cache["stats"]

        # Collect basic counts
        node_stats = self._get_node_statistics()
        edge_stats = self._get_edge_statistics()

        total_nodes = sum(ns.count for ns in node_stats.values())
        total_edges = sum(es.count for es in edge_stats.values())

        # Calculate graph metrics
        density = self._calculate_density(total_nodes, total_edges)
        clustering = self._calculate_clustering_coefficient()
        components = self._find_connected_components()

        stats = GraphStatistics(
            total_nodes=total_nodes,
            total_edges=total_edges,
            node_types=node_stats,
            edge_types=edge_stats,
            density=density,
            avg_clustering_coefficient=clustering,
            connected_components=len(components),
            largest_component_size=max(len(c) for c in components) if components else 0,
            diameter=None  # Expensive to calculate for large graphs
        )

        if use_cache:
            self._cache["stats"] = stats

        return stats

    def _get_node_statistics(self) -> Dict[str, NodeStatistics]:
        """Get statistics for each node type."""
        node_stats = {}

        node_types = ["Concept", "Task", "Region", "Dataset", "Publication"]

        for node_type in node_types:
            nodes = list(self.db.find_nodes(node_type, None))

            if not nodes:
                continue

            # Count properties
            property_counts = defaultdict(int)
            degrees = []

            for node_id, props in nodes:
                # Count non-null properties
                for key, value in props.items():
                    if value is not None:
                        property_counts[key] += 1

                # Calculate degree
                degree = self._get_node_degree(node_id)
                degrees.append(degree)

            node_stats[node_type] = NodeStatistics(
                count=len(nodes),
                avg_degree=sum(degrees) / len(degrees) if degrees else 0,
                max_degree=max(degrees) if degrees else 0,
                min_degree=min(degrees) if degrees else 0,
                properties=dict(property_counts)
            )

        return node_stats

    def _get_edge_statistics(self) -> Dict[str, EdgeStatistics]:
        """Get statistics for each edge type."""
        edge_stats = defaultdict(lambda: {
            "count": 0,
            "confidences": [],
            "sources": []
        })

        # Collect all edges
        for source, target, props in self.db.find_relationships(None, None, None):
            edge_type = props.get("type", "UNKNOWN")

            edge_stats[edge_type]["count"] += 1

            if "confidence" in props:
                edge_stats[edge_type]["confidences"].append(props["confidence"])

            if "source" in props:
                edge_stats[edge_type]["sources"].append(props["source"])

        # Process statistics
        result = {}
        for edge_type, data in edge_stats.items():
            # Calculate confidence distribution
            confidence_dist = {}
            if data["confidences"]:
                for conf in data["confidences"]:
                    bucket = f"{int(conf * 10) / 10:.1f}-{min(1.0, int(conf * 10 + 1) / 10):.1f}"
                    confidence_dist[bucket] = confidence_dist.get(bucket, 0) + 1

            # Calculate source distribution
            source_dist = dict(Counter(data["sources"]))

            result[edge_type] = EdgeStatistics(
                count=data["count"],
                avg_confidence=sum(data["confidences"]) / len(data["confidences"]) if data["confidences"] else 0,
                confidence_distribution=confidence_dist,
                source_distribution=source_dist
            )

        return result

    def _get_node_degree(self, node_id: str) -> int:
        """Get degree of a node (in + out)."""
        degree = 0

        # Outgoing edges
        for _ in self.db.find_relationships(node_id, None, None):
            degree += 1

        # Incoming edges
        for _ in self.db.find_relationships(None, node_id, None):
            degree += 1

        return degree

    def _calculate_density(self, nodes: int, edges: int) -> float:
        """Calculate graph density."""
        if nodes <= 1:
            return 0.0

        # For directed graph
        max_edges = nodes * (nodes - 1)
        return edges / max_edges if max_edges > 0 else 0.0

    def _calculate_clustering_coefficient(self) -> float:
        """Calculate average clustering coefficient."""
        # Simplified version - would need full implementation for accuracy
        # This is a placeholder that returns a reasonable estimate
        return 0.0  # Would require triangle counting

    def _find_connected_components(self) -> List[List[str]]:
        """Find connected components in the graph."""
        visited = set()
        components = []

        # Get all nodes
        all_nodes = set()
        for node_type in ["Concept", "Task", "Region", "Dataset", "Publication"]:
            for node_id, _ in self.db.find_nodes(node_type, None):
                all_nodes.add(node_id)

        # DFS to find components
        for node in all_nodes:
            if node not in visited:
                component = []
                stack = [node]

                while stack:
                    current = stack.pop()
                    if current not in visited:
                        visited.add(current)
                        component.append(current)

                        # Add neighbors
                        for _, target, _ in self.db.find_relationships(current, None, None):
                            if target not in visited:
                                stack.append(target)

                        for source, _, _ in self.db.find_relationships(None, current, None):
                            if source not in visited:
                                stack.append(source)

                components.append(component)

        return components

    def get_degree_distribution(self) -> Dict[int, int]:
        """Get degree distribution of the graph."""
        degree_counts = defaultdict(int)

        # Get all nodes
        all_nodes = set()
        for node_type in ["Concept", "Task", "Region", "Dataset", "Publication"]:
            for node_id, _ in self.db.find_nodes(node_type, None):
                degree = self._get_node_degree(node_id)
                degree_counts[degree] += 1

        return dict(degree_counts)

    def get_top_nodes(self, n: int = 10, metric: str = "degree") -> List[Tuple[str, float]]:
        """
        Get top N nodes by specified metric.

        Args:
            n: Number of top nodes to return
            metric: Metric to use (degree, betweenness, closeness)

        Returns:
            List of (node_id, metric_value) tuples
        """
        node_scores = []

        # Get all nodes
        for node_type in ["Concept", "Task", "Region", "Dataset", "Publication"]:
            for node_id, props in self.db.find_nodes(node_type, None):
                if metric == "degree":
                    score = self._get_node_degree(node_id)
                else:
                    # Other metrics would require more complex calculations
                    score = 0

                node_scores.append((node_id, score))

        # Sort and return top N
        node_scores.sort(key=lambda x: x[1], reverse=True)
        return node_scores[:n]

    def get_path_statistics(self) -> Dict[str, Any]:
        """Get statistics about paths in the graph."""
        # This would require path algorithms
        return {
            "avg_path_length": None,  # Would require all-pairs shortest paths
            "diameter": None,  # Longest shortest path
            "radius": None  # Minimum eccentricity
        }

    def get_type_connectivity(self) -> Dict[str, Dict[str, int]]:
        """Get connectivity matrix between node types."""
        connectivity = defaultdict(lambda: defaultdict(int))

        # Count edges between different node types
        for source, target, _ in self.db.find_relationships(None, None, None):
            source_type = self._get_node_type(source)
            target_type = self._get_node_type(target)

            if source_type and target_type:
                connectivity[source_type][target_type] += 1

        # Convert to regular dict
        return {k: dict(v) for k, v in connectivity.items()}

    def _get_node_type(self, node_id: str) -> Optional[str]:
        """Get the type of a node."""
        for node_type in ["Concept", "Task", "Region", "Dataset", "Publication"]:
            nodes = list(self.db.find_nodes(node_type, {"id": node_id}))
            if nodes:
                return node_type
        return None

    def clear_cache(self):
        """Clear the statistics cache."""
        self._cache.clear()


# REST API endpoints
def create_statistics_endpoints(app):
    """Add statistics endpoints to Flask app."""
    from flask import jsonify

    from brain_researcher.services.br_kg.db.bootstrap import get_db

    @app.route("/api/statistics", methods=["GET"])
    def get_graph_statistics():
        """Get comprehensive graph statistics."""
        # Keep this endpoint fast: UI uses it for a quick overview and should not
        # block on expensive graph-wide traversals.
        db = get_db()

        # Neo4j 5.x provides fast graph counts via db.stats (used by Neo4j Browser).
        if hasattr(db, "execute_query"):
            try:
                rows = db.execute_query(
                    "CALL db.stats.retrieve('GRAPH COUNTS') YIELD data RETURN data AS data LIMIT 1"
                )
                payload = rows[0]["data"] if rows else {}

                node_types: Dict[str, int] = {}
                total_nodes = 0
                for entry in (payload.get("nodes") or []):
                    if not isinstance(entry, dict):
                        continue
                    if "label" in entry:
                        label = str(entry.get("label") or "").strip()
                        if label:
                            node_types[label] = int(entry.get("count") or 0)
                    elif "count" in entry:
                        total_nodes = int(entry.get("count") or 0)

                edge_types: Dict[str, int] = {}
                total_edges = 0
                for entry in (payload.get("relationships") or []):
                    if not isinstance(entry, dict):
                        continue
                    rel_type = entry.get("relationshipType")
                    if rel_type and "startLabel" not in entry and "endLabel" not in entry:
                        edge_types[str(rel_type)] = int(entry.get("count") or 0)
                    elif "count" in entry and not rel_type:
                        total_edges = int(entry.get("count") or 0)

                if not total_nodes:
                    total_nodes = int(sum(node_types.values()))
                if not total_edges:
                    total_edges = int(sum(edge_types.values()))

                return jsonify(
                    {
                        "total_nodes": total_nodes,
                        "total_edges": total_edges,
                        "node_types": node_types,
                        "edge_types": edge_types,
                        "source": "neo4j_db_stats",
                    }
                )
            except Exception:
                # Fall back to the slower analyzer below.
                pass

        analyzer = GraphAnalyzer(db)
        stats = analyzer.get_statistics()

        return jsonify(
            {
                "total_nodes": stats.total_nodes,
                "total_edges": stats.total_edges,
                "node_types": {k: v.count for k, v in stats.node_types.items()},
                "edge_types": {k: v.count for k, v in stats.edge_types.items()},
                "source": "computed",
            }
        )

    @app.route("/api/statistics/degrees", methods=["GET"])
    def get_degree_distribution():
        """Get degree distribution."""
        db = get_db()
        analyzer = GraphAnalyzer(db)
        distribution = analyzer.get_degree_distribution()

        return jsonify(distribution)

    @app.route("/api/statistics/top-nodes", methods=["GET"])
    def get_top_nodes():
        """Get top nodes by degree."""
        db = get_db()
        analyzer = GraphAnalyzer(db)
        top_nodes = analyzer.get_top_nodes(n=20)

        return jsonify([
            {"node_id": node_id, "degree": degree}
            for node_id, degree in top_nodes
        ])

    @app.route("/api/statistics/connectivity", methods=["GET"])
    def get_type_connectivity():
        """Get connectivity between node types."""
        db = get_db()
        analyzer = GraphAnalyzer(db)
        connectivity = analyzer.get_type_connectivity()

        return jsonify(connectivity)
