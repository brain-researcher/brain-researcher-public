"""Advanced graph traversal queries - implements KG-020.

This module provides advanced traversal algorithms including path finding,
centrality metrics, and graph analytics.
"""

import heapq
import logging
from collections import defaultdict, deque
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Set, Tuple

import numpy as np

logger = logging.getLogger(__name__)


class CentralityType(Enum):
    """Types of centrality metrics."""

    DEGREE = "degree"
    BETWEENNESS = "betweenness"
    CLOSENESS = "closeness"
    EIGENVECTOR = "eigenvector"
    PAGERANK = "pagerank"


class PathAlgorithm(Enum):
    """Path finding algorithms."""

    SHORTEST_PATH = "shortest_path"
    ALL_SHORTEST_PATHS = "all_shortest_paths"
    K_SHORTEST_PATHS = "k_shortest_paths"
    ALL_SIMPLE_PATHS = "all_simple_paths"


@dataclass
class TraversalResult:
    """Result of a traversal query."""

    query_type: str
    results: Any
    execution_time_ms: float
    nodes_visited: int
    edges_traversed: int
    metadata: Dict[str, Any] = field(default_factory=dict)


class AdvancedTraversal:
    """Advanced graph traversal algorithms."""

    def __init__(self, neo4j_driver):
        """Initialize advanced traversal.

        Args:
            neo4j_driver: Neo4j driver instance
        """
        self.driver = neo4j_driver

    def find_shortest_path(
        self,
        start_node_id: str,
        end_node_id: str,
        relationship_types: Optional[List[str]] = None,
        max_hops: int = 10,
        weight_property: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """Find shortest path between two nodes.

        Args:
            start_node_id: Starting node ID
            end_node_id: Target node ID
            relationship_types: Allowed relationship types
            max_hops: Maximum path length
            weight_property: Property to use as edge weight

        Returns:
            Path information or None
        """
        with self.driver.session() as session:
            # Build relationship pattern
            if relationship_types:
                rel_pattern = (
                    f"[r:{relationship_types[0]}|{relationship_types[1:]}*..{max_hops}]"
                )
            else:
                rel_pattern = f"[r*..{max_hops}]"

            # Build query
            if weight_property:
                # Weighted shortest path using APOC
                query = """
                MATCH (start {id: $start_id}), (end {id: $end_id})
                CALL apoc.algo.dijkstra(start, end, $rel_types, $weight_prop)
                YIELD path, weight
                RETURN path, weight
                """
                params = {
                    "start_id": start_node_id,
                    "end_id": end_node_id,
                    "rel_types": (
                        "|".join(relationship_types) if relationship_types else ""
                    ),
                    "weight_prop": weight_property,
                }
            else:
                # Unweighted shortest path
                query = f"""
                MATCH (start {{id: $start_id}}), (end {{id: $end_id}})
                MATCH p = shortestPath((start)-{rel_pattern}-(end))
                RETURN p as path, length(p) as weight
                """
                params = {"start_id": start_node_id, "end_id": end_node_id}

            result = session.run(query, params)
            record = result.single()

            if record:
                path = record["path"]
                return {
                    "nodes": [node["id"] for node in path.nodes],
                    "edges": [
                        {
                            "source": rel.start_node["id"],
                            "target": rel.end_node["id"],
                            "type": rel.type,
                            "properties": dict(rel),
                        }
                        for rel in path.relationships
                    ],
                    "length": len(path.relationships),
                    "weight": record["weight"],
                }

        return None

    def find_all_shortest_paths(
        self,
        start_node_id: str,
        end_node_id: str,
        relationship_types: Optional[List[str]] = None,
        max_hops: int = 10,
    ) -> List[Dict[str, Any]]:
        """Find all shortest paths between two nodes.

        Args:
            start_node_id: Starting node ID
            end_node_id: Target node ID
            relationship_types: Allowed relationship types
            max_hops: Maximum path length

        Returns:
            List of paths
        """
        with self.driver.session() as session:
            # Build relationship pattern
            if relationship_types:
                rel_pattern = (
                    f"[:{relationship_types[0]}|{relationship_types[1:]}*..{max_hops}]"
                )
            else:
                rel_pattern = f"[*..{max_hops}]"

            query = f"""
            MATCH (start {{id: $start_id}}), (end {{id: $end_id}})
            MATCH p = allShortestPaths((start)-{rel_pattern}-(end))
            RETURN p as path
            """

            result = session.run(
                query, {"start_id": start_node_id, "end_id": end_node_id}
            )

            paths = []
            for record in result:
                path = record["path"]
                paths.append(
                    {
                        "nodes": [node["id"] for node in path.nodes],
                        "edges": [
                            {
                                "source": rel.start_node["id"],
                                "target": rel.end_node["id"],
                                "type": rel.type,
                            }
                            for rel in path.relationships
                        ],
                        "length": len(path.relationships),
                    }
                )

            return paths

    def find_k_shortest_paths(
        self,
        start_node_id: str,
        end_node_id: str,
        k: int = 5,
        relationship_types: Optional[List[str]] = None,
        max_hops: int = 10,
    ) -> List[Dict[str, Any]]:
        """Find K shortest paths using Yen's algorithm.

        Args:
            start_node_id: Starting node ID
            end_node_id: Target node ID
            k: Number of paths to find
            relationship_types: Allowed relationship types
            max_hops: Maximum path length

        Returns:
            List of K shortest paths
        """
        with self.driver.session() as session:
            # Use APOC for K shortest paths if available
            query = """
            MATCH (start {id: $start_id}), (end {id: $end_id})
            CALL apoc.algo.kShortestPaths(start, end, $k, $rel_types)
            YIELD path
            RETURN path
            LIMIT $k
            """

            result = session.run(
                query,
                {
                    "start_id": start_node_id,
                    "end_id": end_node_id,
                    "k": k,
                    "rel_types": (
                        "|".join(relationship_types) if relationship_types else ""
                    ),
                },
            )

            paths = []
            for record in result:
                path = record["path"]
                paths.append(
                    {
                        "nodes": [node["id"] for node in path.nodes],
                        "edges": [
                            {
                                "source": rel.start_node["id"],
                                "target": rel.end_node["id"],
                                "type": rel.type,
                            }
                            for rel in path.relationships
                        ],
                        "length": len(path.relationships),
                    }
                )

            return paths[:k]

    def calculate_centrality(
        self,
        centrality_type: CentralityType,
        node_type: Optional[str] = None,
        relationship_types: Optional[List[str]] = None,
        top_k: int = 10,
    ) -> List[Dict[str, Any]]:
        """Calculate centrality metrics for nodes.

        Args:
            centrality_type: Type of centrality to calculate
            node_type: Filter by node type
            relationship_types: Consider only these relationships
            top_k: Return top K central nodes

        Returns:
            List of nodes with centrality scores
        """
        with self.driver.session() as session:
            if centrality_type == CentralityType.DEGREE:
                return self._degree_centrality(
                    session, node_type, relationship_types, top_k
                )
            elif centrality_type == CentralityType.BETWEENNESS:
                return self._betweenness_centrality(
                    session, node_type, relationship_types, top_k
                )
            elif centrality_type == CentralityType.CLOSENESS:
                return self._closeness_centrality(
                    session, node_type, relationship_types, top_k
                )
            elif centrality_type == CentralityType.EIGENVECTOR:
                return self._eigenvector_centrality(
                    session, node_type, relationship_types, top_k
                )
            elif centrality_type == CentralityType.PAGERANK:
                return self._pagerank(session, node_type, relationship_types, top_k)
            else:
                raise ValueError(f"Unknown centrality type: {centrality_type}")

    def _degree_centrality(
        self,
        session,
        node_type: Optional[str],
        relationship_types: Optional[List[str]],
        top_k: int,
    ) -> List[Dict[str, Any]]:
        """Calculate degree centrality."""
        node_pattern = f":{node_type}" if node_type else ""
        rel_pattern = (
            f"[:{relationship_types[0]}|{relationship_types[1:]}]"
            if relationship_types
            else ""
        )

        query = f"""
        MATCH (n{node_pattern})
        OPTIONAL MATCH (n)-{rel_pattern if rel_pattern else '[r]'}-(m)
        WITH n, count(DISTINCT m) as degree
        ORDER BY degree DESC
        LIMIT $top_k
        RETURN n.id as node_id,
               n.label as label,
               degree,
               degree * 1.0 / (SELECT count(*) FROM Node) as normalized_degree
        """

        result = session.run(query, {"top_k": top_k})

        return [
            {
                "node_id": record["node_id"],
                "label": record["label"],
                "centrality": record["degree"],
                "normalized": record["normalized_degree"],
            }
            for record in result
        ]

    def _betweenness_centrality(
        self,
        session,
        node_type: Optional[str],
        relationship_types: Optional[List[str]],
        top_k: int,
    ) -> List[Dict[str, Any]]:
        """Calculate betweenness centrality."""
        # Use APOC if available
        query = """
        CALL apoc.algo.betweenness($rel_types, $node_label, 'BOTH')
        YIELD node, score
        RETURN node.id as node_id,
               node.label as label,
               score as centrality
        ORDER BY centrality DESC
        LIMIT $top_k
        """

        result = session.run(
            query,
            {
                "rel_types": "|".join(relationship_types) if relationship_types else "",
                "node_label": node_type or "",
                "top_k": top_k,
            },
        )

        return [
            {
                "node_id": record["node_id"],
                "label": record["label"],
                "centrality": record["centrality"],
            }
            for record in result
        ]

    def _closeness_centrality(
        self,
        session,
        node_type: Optional[str],
        relationship_types: Optional[List[str]],
        top_k: int,
    ) -> List[Dict[str, Any]]:
        """Calculate closeness centrality."""
        query = """
        CALL apoc.algo.closeness($rel_types, $node_label, 'BOTH')
        YIELD node, score
        RETURN node.id as node_id,
               node.label as label,
               score as centrality
        ORDER BY centrality DESC
        LIMIT $top_k
        """

        result = session.run(
            query,
            {
                "rel_types": "|".join(relationship_types) if relationship_types else "",
                "node_label": node_type or "",
                "top_k": top_k,
            },
        )

        return [
            {
                "node_id": record["node_id"],
                "label": record["label"],
                "centrality": record["centrality"],
            }
            for record in result
        ]

    def _eigenvector_centrality(
        self,
        session,
        node_type: Optional[str],
        relationship_types: Optional[List[str]],
        top_k: int,
    ) -> List[Dict[str, Any]]:
        """Calculate eigenvector centrality."""
        # Simplified eigenvector centrality using iterative approach
        node_pattern = f":{node_type}" if node_type else ""

        query = f"""
        MATCH (n{node_pattern})
        WITH collect(n) as nodes
        UNWIND nodes as n
        OPTIONAL MATCH (n)-[r]-(m)
        WHERE m IN nodes
        WITH n, collect(DISTINCT m) as neighbors
        RETURN n.id as node_id,
               n.label as label,
               size(neighbors) as degree
        """

        result = session.run(query)

        # Build adjacency list
        adjacency = defaultdict(list)
        nodes = []

        for record in result:
            node_id = record["node_id"]
            nodes.append({"node_id": node_id, "label": record["label"]})

        # Power iteration for eigenvector centrality
        scores = {node["node_id"]: 1.0 for node in nodes}

        for _ in range(100):  # iterations
            new_scores = {}
            for node in nodes:
                node_id = node["node_id"]

                # Get neighbors
                neighbor_query = f"""
                MATCH (n {{id: $node_id}})-[r]-(m)
                RETURN m.id as neighbor_id
                """
                neighbors = session.run(neighbor_query, {"node_id": node_id})

                score = 0
                for neighbor in neighbors:
                    score += scores.get(neighbor["neighbor_id"], 0)

                new_scores[node_id] = score

            # Normalize
            max_score = max(new_scores.values()) if new_scores else 1
            scores = {k: v / max_score for k, v in new_scores.items()}

        # Return top K
        sorted_nodes = sorted(nodes, key=lambda n: scores[n["node_id"]], reverse=True)

        return [
            {
                "node_id": node["node_id"],
                "label": node["label"],
                "centrality": scores[node["node_id"]],
            }
            for node in sorted_nodes[:top_k]
        ]

    def _pagerank(
        self,
        session,
        node_type: Optional[str],
        relationship_types: Optional[List[str]],
        top_k: int,
    ) -> List[Dict[str, Any]]:
        """Calculate PageRank."""
        query = """
        CALL apoc.algo.pageRank($rel_types, $node_label)
        YIELD node, score
        RETURN node.id as node_id,
               node.label as label,
               score as centrality
        ORDER BY centrality DESC
        LIMIT $top_k
        """

        result = session.run(
            query,
            {
                "rel_types": "|".join(relationship_types) if relationship_types else "",
                "node_label": node_type or "",
                "top_k": top_k,
            },
        )

        return [
            {
                "node_id": record["node_id"],
                "label": record["label"],
                "centrality": record["centrality"],
            }
            for record in result
        ]

    def find_communities(
        self, algorithm: str = "louvain", min_community_size: int = 3
    ) -> List[Dict[str, Any]]:
        """Detect communities in the graph.

        Args:
            algorithm: Community detection algorithm
            min_community_size: Minimum community size

        Returns:
            List of communities
        """
        with self.driver.session() as session:
            if algorithm == "louvain":
                query = """
                CALL apoc.algo.community.louvain()
                YIELD nodes, community, modularity
                WHERE size(nodes) >= $min_size
                RETURN community,
                       [n IN nodes | {id: n.id, label: n.label}] as members,
                       size(nodes) as size,
                       modularity
                ORDER BY size DESC
                """
            elif algorithm == "label_propagation":
                query = """
                CALL apoc.algo.labelPropagation()
                YIELD nodes, labels
                WITH labels as community, collect(nodes) as members
                WHERE size(members) >= $min_size
                RETURN community,
                       [n IN members | {id: n.id, label: n.label}] as members,
                       size(members) as size
                ORDER BY size DESC
                """
            else:
                raise ValueError(f"Unknown algorithm: {algorithm}")

            result = session.run(query, {"min_size": min_community_size})

            communities = []
            for record in result:
                communities.append(
                    {
                        "community_id": record["community"],
                        "members": record["members"],
                        "size": record["size"],
                        "modularity": record.get("modularity"),
                    }
                )

            return communities

    def find_bridges(self) -> List[Dict[str, Any]]:
        """Find bridge edges (edges whose removal increases components).

        Returns:
            List of bridge edges
        """
        with self.driver.session() as session:
            query = """
            MATCH (n)-[r]-(m)
            WHERE n.id < m.id  // Avoid duplicates
            WITH r, n, m
            // Check if removing this edge would disconnect the graph
            MATCH p = (n)-[*]-(m)
            WHERE NONE(rel IN relationships(p) WHERE rel = r)
            WITH r, n, m, count(p) as alternative_paths
            WHERE alternative_paths = 0
            RETURN n.id as source,
                   m.id as target,
                   type(r) as relationship_type,
                   r as relationship
            """

            result = session.run(query)

            bridges = []
            for record in result:
                bridges.append(
                    {
                        "source": record["source"],
                        "target": record["target"],
                        "type": record["relationship_type"],
                        "properties": dict(record["relationship"]),
                    }
                )

            return bridges

    def find_cliques(self, min_size: int = 3) -> List[List[str]]:
        """Find cliques (fully connected subgraphs).

        Args:
            min_size: Minimum clique size

        Returns:
            List of cliques
        """
        with self.driver.session() as session:
            # Use APOC if available
            query = """
            CALL apoc.algo.cliques($min_size)
            YIELD clique
            RETURN [n IN clique | n.id] as members
            """

            try:
                result = session.run(query, {"min_size": min_size})
                return [record["members"] for record in result]
            except:
                # Fallback to manual detection for small graphs
                return self._find_cliques_manual(session, min_size)

    def _find_cliques_manual(self, session, min_size: int) -> List[List[str]]:
        """Manual clique detection using Bron-Kerbosch algorithm."""
        # Get all nodes and edges
        nodes_query = "MATCH (n) RETURN n.id as id"
        edges_query = (
            "MATCH (n)-[r]-(m) WHERE n.id < m.id RETURN n.id as source, m.id as target"
        )

        nodes = {record["id"] for record in session.run(nodes_query)}

        # Build adjacency list
        adjacency = defaultdict(set)
        for record in session.run(edges_query):
            adjacency[record["source"]].add(record["target"])
            adjacency[record["target"]].add(record["source"])

        # Bron-Kerbosch algorithm
        cliques = []

        def bron_kerbosch(r: Set[str], p: Set[str], x: Set[str]):
            if not p and not x:
                if len(r) >= min_size:
                    cliques.append(list(r))
                return

            for node in list(p):
                neighbors = adjacency[node]
                bron_kerbosch(r | {node}, p & neighbors, x & neighbors)
                p.remove(node)
                x.add(node)

        bron_kerbosch(set(), nodes, set())

        return cliques

    def find_influence_paths(
        self, source_node_id: str, max_hops: int = 3, min_influence: float = 0.1
    ) -> Dict[str, Any]:
        """Find influence paths from a source node.

        Args:
            source_node_id: Source node ID
            max_hops: Maximum path length
            min_influence: Minimum influence threshold

        Returns:
            Influence tree
        """
        with self.driver.session() as session:
            query = f"""
            MATCH (source {{id: $source_id}})
            CALL apoc.path.spanningTree(source, {{
                maxLevel: $max_hops,
                relationshipFilter: '>'
            }})
            YIELD path
            WITH path,
                 reduce(influence = 1.0, r IN relationships(path) |
                        influence * coalesce(r.weight, 0.5)) as path_influence
            WHERE path_influence >= $min_influence
            RETURN nodes(path) as nodes,
                   relationships(path) as edges,
                   path_influence as influence
            ORDER BY influence DESC
            """

            result = session.run(
                query,
                {
                    "source_id": source_node_id,
                    "max_hops": max_hops,
                    "min_influence": min_influence,
                },
            )

            influence_tree = {
                "source": source_node_id,
                "influenced_nodes": [],
                "paths": [],
            }

            influenced = set()

            for record in result:
                path_nodes = [n["id"] for n in record["nodes"]]
                influenced.update(path_nodes[1:])  # Exclude source

                influence_tree["paths"].append(
                    {
                        "nodes": path_nodes,
                        "influence": record["influence"],
                        "length": len(path_nodes) - 1,
                    }
                )

            influence_tree["influenced_nodes"] = list(influenced)
            influence_tree["total_influence"] = len(influenced)

            return influence_tree

    def find_motifs(
        self, motif_size: int = 3, min_frequency: int = 5
    ) -> List[Dict[str, Any]]:
        """Find recurring motifs (subgraph patterns).

        Args:
            motif_size: Size of motifs to find (3 or 4)
            min_frequency: Minimum occurrence frequency

        Returns:
            List of motifs with frequencies
        """
        with self.driver.session() as session:
            if motif_size == 3:
                # Find triangle motifs
                query = """
                MATCH (a)-[r1]-(b)-[r2]-(c)-[r3]-(a)
                WHERE id(a) < id(b) < id(c)
                WITH type(r1) + '-' + type(r2) + '-' + type(r3) as pattern,
                     collect({a: labels(a)[0], b: labels(b)[0], c: labels(c)[0]}) as instances
                WHERE size(instances) >= $min_freq
                RETURN pattern,
                       size(instances) as frequency,
                       instances[0..5] as examples
                ORDER BY frequency DESC
                """
            elif motif_size == 4:
                # Find square motifs
                query = """
                MATCH (a)-[r1]-(b)-[r2]-(c)-[r3]-(d)-[r4]-(a)
                WHERE id(a) < id(b) < id(c) < id(d)
                AND NOT (b)-[]-(d)
                WITH type(r1) + '-' + type(r2) + '-' + type(r3) + '-' + type(r4) as pattern,
                     collect({
                         a: labels(a)[0],
                         b: labels(b)[0],
                         c: labels(c)[0],
                         d: labels(d)[0]
                     }) as instances
                WHERE size(instances) >= $min_freq
                RETURN pattern,
                       size(instances) as frequency,
                       instances[0..5] as examples
                ORDER BY frequency DESC
                """
            else:
                raise ValueError(f"Motif size {motif_size} not supported")

            result = session.run(query, {"min_freq": min_frequency})

            motifs = []
            for record in result:
                motifs.append(
                    {
                        "pattern": record["pattern"],
                        "frequency": record["frequency"],
                        "examples": record["examples"],
                    }
                )

            return motifs

    def calculate_graph_metrics(self) -> Dict[str, Any]:
        """Calculate overall graph metrics.

        Returns:
            Dictionary of graph metrics
        """
        with self.driver.session() as session:
            metrics = {}

            # Basic counts
            counts_query = """
            MATCH (n)
            WITH count(n) as node_count
            MATCH ()-[r]->()
            WITH node_count, count(r) as edge_count
            RETURN node_count, edge_count
            """
            result = session.run(counts_query).single()
            metrics["node_count"] = result["node_count"]
            metrics["edge_count"] = result["edge_count"]

            # Density
            n = metrics["node_count"]
            if n > 1:
                max_edges = n * (n - 1)
                metrics["density"] = metrics["edge_count"] / max_edges
            else:
                metrics["density"] = 0

            # Average degree
            metrics["avg_degree"] = 2 * metrics["edge_count"] / n if n > 0 else 0

            # Clustering coefficient
            clustering_query = """
            MATCH (n)-[r1]-(m)-[r2]-(o)-[r3]-(n)
            WHERE id(n) < id(m) < id(o)
            WITH count(*) as triangles
            MATCH (n)-[r]-(m)
            WHERE id(n) < id(m)
            WITH triangles, count(*) as edges
            RETURN triangles * 3.0 / edges as clustering_coefficient
            """
            result = session.run(clustering_query).single()
            metrics["clustering_coefficient"] = (
                result["clustering_coefficient"] if result else 0
            )

            # Connected components
            components_query = """
            CALL apoc.algo.unionFind()
            YIELD sets
            RETURN size(sets) as num_components,
                   [s IN sets | size(s)] as component_sizes
            """
            try:
                result = session.run(components_query).single()
                metrics["num_components"] = result["num_components"]
                metrics["largest_component"] = max(result["component_sizes"])
            except:
                metrics["num_components"] = 1
                metrics["largest_component"] = n

            # Diameter (longest shortest path)
            diameter_query = """
            MATCH (n), (m)
            WHERE id(n) < id(m)
            WITH n, m
            LIMIT 100  // Sample for performance
            MATCH p = shortestPath((n)-[*]-(m))
            RETURN max(length(p)) as diameter
            """
            result = session.run(diameter_query).single()
            metrics["diameter_estimate"] = result["diameter"] if result else 0

            return metrics
