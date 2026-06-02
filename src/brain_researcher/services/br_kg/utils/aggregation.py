"""Graph aggregation utilities for dense subgraph handling."""

from collections import defaultdict
from typing import Any, Dict, List, Set, Tuple

import networkx as nx


class GraphAggregator:
    """Aggregator for simplifying dense graph regions."""

    def __init__(self):
        self.aggregated_nodes = {}
        self.aggregation_metadata = {}

    def cluster_dense_regions(
        self, graph: nx.Graph, density_threshold: float = 0.7
    ) -> nx.Graph:
        """Cluster dense regions of the graph.

        Args:
            graph: Input graph
            density_threshold: Minimum density for clustering (0-1)

        Returns:
            Aggregated graph with dense regions collapsed
        """
        # Find dense subgraphs using community detection
        communities = list(nx.community.greedy_modularity_communities(graph))

        # Create new aggregated graph
        agg_graph = nx.Graph()
        node_to_cluster = {}

        for i, community in enumerate(communities):
            # Calculate subgraph density
            subgraph = graph.subgraph(community)
            n = len(community)
            if n <= 1:
                # Single node, add as-is
                for node in community:
                    agg_graph.add_node(node, **graph.nodes[node])
                continue

            m = subgraph.number_of_edges()
            max_edges = n * (n - 1) / 2
            density = m / max_edges if max_edges > 0 else 0

            if density >= density_threshold:
                # Create cluster node
                cluster_id = f"cluster_{i}"
                agg_graph.add_node(
                    cluster_id,
                    type="cluster",
                    size=n,
                    density=density,
                    members=list(community),
                )

                # Track mapping
                for node in community:
                    node_to_cluster[node] = cluster_id

                self.aggregation_metadata[cluster_id] = {
                    "members": list(community),
                    "internal_edges": m,
                    "density": density,
                }
            else:
                # Add individual nodes
                for node in community:
                    agg_graph.add_node(node, **graph.nodes[node])

        # Add edges between clusters and remaining nodes
        for u, v in graph.edges():
            u_cluster = node_to_cluster.get(u, u)
            v_cluster = node_to_cluster.get(v, v)

            if u_cluster != v_cluster:
                if agg_graph.has_edge(u_cluster, v_cluster):
                    # Increment edge weight
                    agg_graph[u_cluster][v_cluster]["weight"] += 1
                else:
                    agg_graph.add_edge(u_cluster, v_cluster, weight=1)

        return agg_graph

    def collapse_chains(self, graph: nx.Graph) -> nx.Graph:
        """Collapse linear chains of nodes.

        Args:
            graph: Input graph

        Returns:
            Graph with chains collapsed
        """
        agg_graph = graph.copy()
        chains_found = []
        visited = set()

        for node in graph.nodes():
            if node in visited:
                continue

            # Check if this starts a chain (degree 2 nodes)
            if graph.degree(node) == 2:
                chain = [node]
                visited.add(node)

                # Follow the chain
                neighbors = list(graph.neighbors(node))
                current = node

                for next_node in neighbors:
                    if next_node in visited:
                        continue

                    # Follow chain while nodes have degree 2
                    while graph.degree(next_node) == 2 and next_node not in visited:
                        chain.append(next_node)
                        visited.add(next_node)

                        # Get next node in chain
                        next_neighbors = [
                            n
                            for n in graph.neighbors(next_node)
                            if n != current and n not in chain
                        ]
                        if not next_neighbors:
                            break

                        current = next_node
                        next_node = next_neighbors[0]

                if len(chain) > 2:
                    chains_found.append(chain)

        # Replace chains with single nodes
        for i, chain in enumerate(chains_found):
            chain_id = f"chain_{i}"

            # Get endpoints
            endpoints = []
            for node in [chain[0], chain[-1]]:
                for neighbor in graph.neighbors(node):
                    if neighbor not in chain:
                        endpoints.append(neighbor)

            # Remove chain nodes
            agg_graph.remove_nodes_from(chain)

            # Add chain node
            agg_graph.add_node(chain_id, type="chain", length=len(chain), members=chain)

            # Connect to endpoints
            for endpoint in endpoints:
                if endpoint in agg_graph:
                    agg_graph.add_edge(chain_id, endpoint)

            self.aggregation_metadata[chain_id] = {
                "members": chain,
                "length": len(chain),
            }

        return agg_graph

    def summarize_neighborhoods(
        self, graph: nx.Graph, max_neighbors: int = 10
    ) -> Dict[str, Any]:
        """Summarize neighborhoods for nodes with many neighbors.

        Args:
            graph: Input graph
            max_neighbors: Maximum neighbors to show individually

        Returns:
            Summary statistics for dense neighborhoods
        """
        summaries = {}

        for node in graph.nodes():
            neighbors = list(graph.neighbors(node))
            degree = len(neighbors)

            if degree > max_neighbors:
                # Compute summary statistics
                neighbor_types = defaultdict(int)
                edge_weights = []

                for neighbor in neighbors:
                    # Count node types
                    node_type = graph.nodes[neighbor].get("type", "unknown")
                    neighbor_types[node_type] += 1

                    # Collect edge weights
                    edge_data = graph[node][neighbor]
                    if "weight" in edge_data:
                        edge_weights.append(edge_data["weight"])

                summaries[node] = {
                    "total_neighbors": degree,
                    "shown_neighbors": neighbors[:max_neighbors],
                    "hidden_count": degree - max_neighbors,
                    "neighbor_types": dict(neighbor_types),
                    "avg_edge_weight": (
                        sum(edge_weights) / len(edge_weights) if edge_weights else 1.0
                    ),
                }

        return summaries

    def get_aggregation_info(self, node_id: str) -> Dict[str, Any]:
        """Get aggregation information for a node.

        Args:
            node_id: Node identifier

        Returns:
            Aggregation metadata if node is aggregated
        """
        return self.aggregation_metadata.get(node_id, {})
