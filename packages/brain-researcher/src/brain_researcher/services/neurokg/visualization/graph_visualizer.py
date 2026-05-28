"""Knowledge Graph Visualization API - implements KG-017.

This module provides visualization capabilities for the knowledge graph,
including layout algorithms, filtering, and aggregation.
"""

import json
import logging
from typing import Dict, List, Any, Optional, Tuple, Set
from dataclasses import dataclass, field
from enum import Enum
import numpy as np
from collections import defaultdict
import math

logger = logging.getLogger(__name__)


class LayoutAlgorithm(Enum):
    """Available layout algorithms."""
    
    FORCE_DIRECTED = "force_directed"
    HIERARCHICAL = "hierarchical"
    CIRCULAR = "circular"
    RADIAL = "radial"
    SPECTRAL = "spectral"
    GEOGRAPHIC = "geographic"  # For brain regions
    

@dataclass
class NodeStyle:
    """Visual style for nodes."""
    
    color: str = "#4A90E2"
    size: float = 10.0
    shape: str = "circle"  # circle, square, triangle, diamond
    label_size: int = 12
    label_color: str = "#333333"
    opacity: float = 1.0
    border_width: float = 1.0
    border_color: str = "#FFFFFF"
    

@dataclass
class EdgeStyle:
    """Visual style for edges."""
    
    color: str = "#999999"
    width: float = 1.0
    style: str = "solid"  # solid, dashed, dotted
    opacity: float = 0.6
    arrow_size: float = 8.0
    curve_style: str = "straight"  # straight, curved, bezier
    

@dataclass
class GraphView:
    """Represents a view of the graph."""
    
    nodes: List[Dict[str, Any]]
    edges: List[Dict[str, Any]]
    layout: Dict[str, Tuple[float, float]]
    metadata: Dict[str, Any] = field(default_factory=dict)
    

class GraphVisualizer:
    """Visualize knowledge graph data."""
    
    def __init__(self):
        """Initialize graph visualizer."""
        self.default_node_styles = self._get_default_node_styles()
        self.default_edge_styles = self._get_default_edge_styles()
        
    def _get_default_node_styles(self) -> Dict[str, NodeStyle]:
        """Get default styles for different node types."""
        return {
            "Task": NodeStyle(color="#FF6B6B", shape="circle", size=12),
            "Concept": NodeStyle(color="#4ECDC4", shape="diamond", size=10),
            "Region": NodeStyle(color="#45B7D1", shape="square", size=14),
            "Dataset": NodeStyle(color="#96CEB4", shape="triangle", size=11),
            "Publication": NodeStyle(color="#DDA0DD", shape="circle", size=8),
            "default": NodeStyle()
        }
        
    def _get_default_edge_styles(self) -> Dict[str, EdgeStyle]:
        """Get default styles for different edge types."""
        return {
            "INVOLVES": EdgeStyle(color="#FF6B6B", width=2.0),
            "RELATES_TO": EdgeStyle(color="#4ECDC4", style="dashed"),
            "LOCATED_IN": EdgeStyle(color="#45B7D1", width=1.5),
            "HAS_ACTIVATION": EdgeStyle(color="#96CEB4", curve_style="curved"),
            "CITES": EdgeStyle(color="#DDA0DD", style="dotted"),
            "default": EdgeStyle()
        }
        
    def create_view(
        self,
        graph_data: Dict[str, Any],
        layout_algorithm: LayoutAlgorithm = LayoutAlgorithm.FORCE_DIRECTED,
        filters: Optional[Dict[str, Any]] = None,
        aggregation: Optional[Dict[str, Any]] = None
    ) -> GraphView:
        """Create a visualization view of the graph.
        
        Args:
            graph_data: Graph data with nodes and edges
            layout_algorithm: Layout algorithm to use
            filters: Filtering criteria
            aggregation: Aggregation settings
            
        Returns:
            GraphView object
        """
        # Apply filters
        filtered_data = self._apply_filters(graph_data, filters)
        
        # Apply aggregation
        if aggregation:
            filtered_data = self._apply_aggregation(filtered_data, aggregation)
            
        # Calculate layout
        layout = self._calculate_layout(filtered_data, layout_algorithm)
        
        # Style nodes and edges
        styled_nodes = self._style_nodes(filtered_data["nodes"])
        styled_edges = self._style_edges(filtered_data["edges"])
        
        return GraphView(
            nodes=styled_nodes,
            edges=styled_edges,
            layout=layout,
            metadata={
                "algorithm": layout_algorithm.value,
                "node_count": len(styled_nodes),
                "edge_count": len(styled_edges),
                "filters": filters,
                "aggregation": aggregation
            }
        )
        
    def _apply_filters(
        self,
        graph_data: Dict[str, Any],
        filters: Optional[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """Apply filters to graph data.
        
        Args:
            graph_data: Original graph data
            filters: Filtering criteria
            
        Returns:
            Filtered graph data
        """
        if not filters:
            return graph_data
            
        filtered_nodes = []
        filtered_edges = []
        node_ids = set()
        
        # Filter nodes
        for node in graph_data.get("nodes", []):
            include = True
            
            # Node type filter
            if "node_types" in filters:
                if node.get("type") not in filters["node_types"]:
                    include = False
                    
            # Property filters
            if "node_properties" in filters:
                for prop, value in filters["node_properties"].items():
                    if node.get(prop) != value:
                        include = False
                        break
                        
            # Degree filter
            if "min_degree" in filters:
                degree = self._calculate_degree(node["id"], graph_data["edges"])
                if degree < filters["min_degree"]:
                    include = False
                    
            if include:
                filtered_nodes.append(node)
                node_ids.add(node["id"])
                
        # Filter edges (only keep edges between filtered nodes)
        for edge in graph_data.get("edges", []):
            if edge["source"] in node_ids and edge["target"] in node_ids:
                # Edge type filter
                if "edge_types" in filters:
                    if edge.get("type") not in filters["edge_types"]:
                        continue
                        
                # Weight filter
                if "min_weight" in filters:
                    if edge.get("weight", 1.0) < filters["min_weight"]:
                        continue
                        
                filtered_edges.append(edge)
                
        return {"nodes": filtered_nodes, "edges": filtered_edges}
        
    def _apply_aggregation(
        self,
        graph_data: Dict[str, Any],
        aggregation: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Apply aggregation to graph data.
        
        Args:
            graph_data: Filtered graph data
            aggregation: Aggregation settings
            
        Returns:
            Aggregated graph data
        """
        if aggregation.get("group_by"):
            return self._group_nodes(graph_data, aggregation["group_by"])
            
        if aggregation.get("collapse_chains"):
            return self._collapse_chains(graph_data)
            
        if aggregation.get("cluster_by_community"):
            return self._detect_communities(graph_data)
            
        return graph_data
        
    def _group_nodes(
        self,
        graph_data: Dict[str, Any],
        group_by: str
    ) -> Dict[str, Any]:
        """Group nodes by a property.
        
        Args:
            graph_data: Graph data
            group_by: Property to group by
            
        Returns:
            Grouped graph data
        """
        groups = defaultdict(list)
        group_edges = defaultdict(lambda: defaultdict(float))
        
        # Group nodes
        for node in graph_data["nodes"]:
            group_key = node.get(group_by, "unknown")
            groups[group_key].append(node)
            
        # Aggregate edges between groups
        for edge in graph_data["edges"]:
            source_group = None
            target_group = None
            
            for group_key, nodes in groups.items():
                node_ids = {n["id"] for n in nodes}
                if edge["source"] in node_ids:
                    source_group = group_key
                if edge["target"] in node_ids:
                    target_group = group_key
                    
            if source_group and target_group:
                weight = edge.get("weight", 1.0)
                group_edges[source_group][target_group] += weight
                
        # Create aggregated nodes and edges
        agg_nodes = []
        for group_key, nodes in groups.items():
            agg_nodes.append({
                "id": f"group_{group_key}",
                "label": str(group_key),
                "type": "group",
                "size": len(nodes),
                "members": [n["id"] for n in nodes]
            })
            
        agg_edges = []
        for source, targets in group_edges.items():
            for target, weight in targets.items():
                if source != target:  # Skip self-loops for now
                    agg_edges.append({
                        "source": f"group_{source}",
                        "target": f"group_{target}",
                        "weight": weight,
                        "type": "aggregated"
                    })
                    
        return {"nodes": agg_nodes, "edges": agg_edges}
        
    def _collapse_chains(self, graph_data: Dict[str, Any]) -> Dict[str, Any]:
        """Collapse linear chains of nodes.
        
        Args:
            graph_data: Graph data
            
        Returns:
            Graph with collapsed chains
        """
        # Find nodes with degree 2 (chain nodes)
        degrees = {}
        for node in graph_data["nodes"]:
            degrees[node["id"]] = self._calculate_degree(node["id"], graph_data["edges"])
            
        chains = []
        visited = set()
        
        for node in graph_data["nodes"]:
            if node["id"] not in visited and degrees[node["id"]] == 2:
                chain = self._find_chain(node["id"], graph_data, degrees, visited)
                if len(chain) > 2:
                    chains.append(chain)
                    
        # Create collapsed representation
        collapsed_nodes = []
        collapsed_edges = []
        chain_map = {}
        
        for chain in chains:
            chain_id = f"chain_{chain[0]}_{chain[-1]}"
            collapsed_nodes.append({
                "id": chain_id,
                "type": "chain",
                "label": f"Chain ({len(chain)} nodes)",
                "members": chain
            })
            for node_id in chain:
                chain_map[node_id] = chain_id
                
        # Add non-chain nodes
        for node in graph_data["nodes"]:
            if node["id"] not in chain_map:
                collapsed_nodes.append(node)
                
        # Update edges
        for edge in graph_data["edges"]:
            source = chain_map.get(edge["source"], edge["source"])
            target = chain_map.get(edge["target"], edge["target"])
            
            if source != target:  # Skip internal chain edges
                collapsed_edges.append({
                    **edge,
                    "source": source,
                    "target": target
                })
                
        return {"nodes": collapsed_nodes, "edges": collapsed_edges}
        
    def _detect_communities(self, graph_data: Dict[str, Any]) -> Dict[str, Any]:
        """Detect communities using Louvain algorithm.
        
        Args:
            graph_data: Graph data
            
        Returns:
            Graph with community information
        """
        # Simple community detection (modularity-based)
        communities = self._louvain_communities(graph_data)
        
        # Add community information to nodes
        for node in graph_data["nodes"]:
            node["community"] = communities.get(node["id"], 0)
            
        return graph_data
        
    def _calculate_layout(
        self,
        graph_data: Dict[str, Any],
        algorithm: LayoutAlgorithm
    ) -> Dict[str, Tuple[float, float]]:
        """Calculate node positions using specified algorithm.
        
        Args:
            graph_data: Graph data
            algorithm: Layout algorithm
            
        Returns:
            Node positions
        """
        if algorithm == LayoutAlgorithm.FORCE_DIRECTED:
            return self._force_directed_layout(graph_data)
        elif algorithm == LayoutAlgorithm.HIERARCHICAL:
            return self._hierarchical_layout(graph_data)
        elif algorithm == LayoutAlgorithm.CIRCULAR:
            return self._circular_layout(graph_data)
        elif algorithm == LayoutAlgorithm.RADIAL:
            return self._radial_layout(graph_data)
        elif algorithm == LayoutAlgorithm.SPECTRAL:
            return self._spectral_layout(graph_data)
        elif algorithm == LayoutAlgorithm.GEOGRAPHIC:
            return self._geographic_layout(graph_data)
        else:
            return self._force_directed_layout(graph_data)
            
    def _force_directed_layout(self, graph_data: Dict[str, Any]) -> Dict[str, Tuple[float, float]]:
        """Force-directed layout using Fruchterman-Reingold algorithm."""
        nodes = graph_data["nodes"]
        edges = graph_data["edges"]
        
        if not nodes:
            return {}
            
        # Initialize positions randomly
        positions = {}
        for node in nodes:
            positions[node["id"]] = (
                np.random.uniform(-100, 100),
                np.random.uniform(-100, 100)
            )
            
        # Parameters
        k = math.sqrt(10000 / len(nodes))  # Optimal distance
        iterations = 50
        temperature = 100
        
        for iteration in range(iterations):
            # Calculate repulsive forces
            forces = defaultdict(lambda: [0.0, 0.0])
            
            for i, node1 in enumerate(nodes):
                for node2 in nodes[i+1:]:
                    dx = positions[node2["id"]][0] - positions[node1["id"]][0]
                    dy = positions[node2["id"]][1] - positions[node1["id"]][1]
                    distance = max(math.sqrt(dx*dx + dy*dy), 0.01)
                    
                    repulsion = k * k / distance
                    fx = repulsion * dx / distance
                    fy = repulsion * dy / distance
                    
                    forces[node1["id"]][0] -= fx
                    forces[node1["id"]][1] -= fy
                    forces[node2["id"]][0] += fx
                    forces[node2["id"]][1] += fy
                    
            # Calculate attractive forces
            for edge in edges:
                source = edge["source"]
                target = edge["target"]
                
                if source in positions and target in positions:
                    dx = positions[target][0] - positions[source][0]
                    dy = positions[target][1] - positions[source][1]
                    distance = max(math.sqrt(dx*dx + dy*dy), 0.01)
                    
                    attraction = distance * distance / k
                    fx = attraction * dx / distance
                    fy = attraction * dy / distance
                    
                    forces[source][0] += fx
                    forces[source][1] += fy
                    forces[target][0] -= fx
                    forces[target][1] -= fy
                    
            # Update positions
            for node in nodes:
                node_id = node["id"]
                fx, fy = forces[node_id]
                
                # Limit displacement by temperature
                displacement = math.sqrt(fx*fx + fy*fy)
                if displacement > 0:
                    limited = min(displacement, temperature)
                    fx = fx / displacement * limited
                    fy = fy / displacement * limited
                    
                positions[node_id] = (
                    positions[node_id][0] + fx,
                    positions[node_id][1] + fy
                )
                
            # Cool down
            temperature *= 0.95
            
        return positions
        
    def _hierarchical_layout(self, graph_data: Dict[str, Any]) -> Dict[str, Tuple[float, float]]:
        """Hierarchical layout for directed graphs."""
        # Assign layers using topological sort
        layers = self._assign_layers(graph_data)
        
        positions = {}
        layer_widths = {}
        
        # Count nodes in each layer
        for node_id, layer in layers.items():
            if layer not in layer_widths:
                layer_widths[layer] = 0
            layer_widths[layer] += 1
            
        # Position nodes
        layer_counters = defaultdict(int)
        for node in graph_data["nodes"]:
            node_id = node["id"]
            layer = layers.get(node_id, 0)
            
            # Horizontal position within layer
            x = (layer_counters[layer] - layer_widths[layer] / 2) * 50
            # Vertical position by layer
            y = layer * 100
            
            positions[node_id] = (x, y)
            layer_counters[layer] += 1
            
        return positions
        
    def _circular_layout(self, graph_data: Dict[str, Any]) -> Dict[str, Tuple[float, float]]:
        """Circular layout."""
        nodes = graph_data["nodes"]
        n = len(nodes)
        
        if n == 0:
            return {}
            
        positions = {}
        radius = 100
        
        for i, node in enumerate(nodes):
            angle = 2 * math.pi * i / n
            x = radius * math.cos(angle)
            y = radius * math.sin(angle)
            positions[node["id"]] = (x, y)
            
        return positions
        
    def _radial_layout(self, graph_data: Dict[str, Any]) -> Dict[str, Tuple[float, float]]:
        """Radial layout with central node."""
        # Find most connected node as center
        degrees = {}
        for node in graph_data["nodes"]:
            degrees[node["id"]] = self._calculate_degree(node["id"], graph_data["edges"])
            
        if not degrees:
            return {}
            
        center_id = max(degrees, key=degrees.get)
        
        # BFS from center
        positions = {center_id: (0, 0)}
        visited = {center_id}
        queue = [(center_id, 0)]
        
        while queue:
            node_id, level = queue.pop(0)
            
            # Find neighbors
            neighbors = []
            for edge in graph_data["edges"]:
                if edge["source"] == node_id and edge["target"] not in visited:
                    neighbors.append(edge["target"])
                elif edge["target"] == node_id and edge["source"] not in visited:
                    neighbors.append(edge["source"])
                    
            # Position neighbors in a circle around current level
            if neighbors:
                radius = (level + 1) * 50
                n = len(neighbors)
                for i, neighbor_id in enumerate(neighbors):
                    angle = 2 * math.pi * i / n
                    x = radius * math.cos(angle)
                    y = radius * math.sin(angle)
                    positions[neighbor_id] = (x, y)
                    visited.add(neighbor_id)
                    queue.append((neighbor_id, level + 1))
                    
        # Add any disconnected nodes
        for node in graph_data["nodes"]:
            if node["id"] not in positions:
                positions[node["id"]] = (
                    np.random.uniform(-100, 100),
                    np.random.uniform(-100, 100)
                )
                
        return positions
        
    def _spectral_layout(self, graph_data: Dict[str, Any]) -> Dict[str, Tuple[float, float]]:
        """Spectral layout using graph Laplacian."""
        nodes = graph_data["nodes"]
        n = len(nodes)
        
        if n == 0:
            return {}
            
        # Create adjacency matrix
        node_index = {node["id"]: i for i, node in enumerate(nodes)}
        adj_matrix = np.zeros((n, n))
        
        for edge in graph_data["edges"]:
            if edge["source"] in node_index and edge["target"] in node_index:
                i = node_index[edge["source"]]
                j = node_index[edge["target"]]
                weight = edge.get("weight", 1.0)
                adj_matrix[i, j] = weight
                adj_matrix[j, i] = weight  # Undirected
                
        # Calculate Laplacian
        degree_matrix = np.diag(np.sum(adj_matrix, axis=1))
        laplacian = degree_matrix - adj_matrix
        
        # Compute eigenvectors
        try:
            eigenvalues, eigenvectors = np.linalg.eigh(laplacian)
            
            # Use 2nd and 3rd smallest eigenvectors for 2D layout
            positions = {}
            for i, node in enumerate(nodes):
                x = eigenvectors[i, 1] * 100 if n > 1 else 0
                y = eigenvectors[i, 2] * 100 if n > 2 else 0
                positions[node["id"]] = (x, y)
                
        except np.linalg.LinAlgError:
            # Fallback to circular layout
            return self._circular_layout(graph_data)
            
        return positions
        
    def _geographic_layout(self, graph_data: Dict[str, Any]) -> Dict[str, Tuple[float, float]]:
        """Geographic layout for brain regions."""
        positions = {}
        
        # Predefined positions for common brain regions
        brain_positions = {
            "frontal": (-20, 30),
            "parietal": (0, 20),
            "temporal": (-30, 0),
            "occipital": (0, -30),
            "cerebellum": (0, -50),
            "brainstem": (0, -40),
            "hippocampus": (-15, -10),
            "amygdala": (-20, -5),
            "thalamus": (0, 0),
            "default": (0, 0)
        }
        
        for node in graph_data["nodes"]:
            node_id = node["id"]
            
            # Try to extract region from node properties
            region = node.get("region", "").lower()
            position = None
            
            for key, pos in brain_positions.items():
                if key in region:
                    position = pos
                    break
                    
            if not position:
                # Add some randomness for unique positions
                position = (
                    brain_positions["default"][0] + np.random.uniform(-10, 10),
                    brain_positions["default"][1] + np.random.uniform(-10, 10)
                )
                
            positions[node_id] = position
            
        return positions
        
    def _style_nodes(self, nodes: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Apply visual styles to nodes."""
        styled_nodes = []
        
        for node in nodes:
            node_type = node.get("type", "default")
            style = self.default_node_styles.get(node_type, self.default_node_styles["default"])
            
            styled_node = {
                **node,
                "style": {
                    "color": style.color,
                    "size": style.size * (1 + node.get("importance", 0) * 0.5),
                    "shape": style.shape,
                    "label_size": style.label_size,
                    "label_color": style.label_color,
                    "opacity": style.opacity,
                    "border_width": style.border_width,
                    "border_color": style.border_color
                }
            }
            styled_nodes.append(styled_node)
            
        return styled_nodes
        
    def _style_edges(self, edges: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Apply visual styles to edges."""
        styled_edges = []
        
        for edge in edges:
            edge_type = edge.get("type", "default")
            style = self.default_edge_styles.get(edge_type, self.default_edge_styles["default"])
            
            styled_edge = {
                **edge,
                "style": {
                    "color": style.color,
                    "width": style.width * (1 + edge.get("weight", 1) * 0.2),
                    "style": style.style,
                    "opacity": style.opacity,
                    "arrow_size": style.arrow_size,
                    "curve_style": style.curve_style
                }
            }
            styled_edges.append(styled_edge)
            
        return styled_edges
        
    def _calculate_degree(self, node_id: str, edges: List[Dict[str, Any]]) -> int:
        """Calculate degree of a node."""
        degree = 0
        for edge in edges:
            if edge["source"] == node_id or edge["target"] == node_id:
                degree += 1
        return degree
        
    def _find_chain(
        self,
        start_id: str,
        graph_data: Dict[str, Any],
        degrees: Dict[str, int],
        visited: Set[str]
    ) -> List[str]:
        """Find a linear chain starting from a node."""
        chain = [start_id]
        visited.add(start_id)
        
        current = start_id
        while True:
            # Find next node in chain
            next_node = None
            for edge in graph_data["edges"]:
                neighbor = None
                if edge["source"] == current and edge["target"] not in visited:
                    neighbor = edge["target"]
                elif edge["target"] == current and edge["source"] not in visited:
                    neighbor = edge["source"]
                    
                if neighbor and degrees.get(neighbor, 0) <= 2:
                    next_node = neighbor
                    break
                    
            if next_node:
                chain.append(next_node)
                visited.add(next_node)
                current = next_node
            else:
                break
                
        return chain
        
    def _assign_layers(self, graph_data: Dict[str, Any]) -> Dict[str, int]:
        """Assign layers to nodes for hierarchical layout."""
        layers = {}
        
        # Find nodes with no incoming edges (roots)
        incoming = defaultdict(int)
        for edge in graph_data["edges"]:
            incoming[edge["target"]] += 1
            
        roots = []
        for node in graph_data["nodes"]:
            if incoming[node["id"]] == 0:
                roots.append(node["id"])
                layers[node["id"]] = 0
                
        if not roots and graph_data["nodes"]:
            # If no roots, pick node with minimum incoming edges
            roots = [min(graph_data["nodes"], key=lambda n: incoming[n["id"]])["id"]]
            layers[roots[0]] = 0
            
        # BFS to assign layers
        queue = [(root, 0) for root in roots]
        
        while queue:
            node_id, layer = queue.pop(0)
            
            for edge in graph_data["edges"]:
                if edge["source"] == node_id:
                    target = edge["target"]
                    if target not in layers or layers[target] < layer + 1:
                        layers[target] = layer + 1
                        queue.append((target, layer + 1))
                        
        # Assign default layer to disconnected nodes
        for node in graph_data["nodes"]:
            if node["id"] not in layers:
                layers[node["id"]] = 0
                
        return layers
        
    def _louvain_communities(self, graph_data: Dict[str, Any]) -> Dict[str, int]:
        """Simple Louvain community detection."""
        # Initialize each node in its own community
        communities = {}
        for i, node in enumerate(graph_data["nodes"]):
            communities[node["id"]] = i
            
        # Iteratively merge communities (simplified)
        improved = True
        while improved:
            improved = False
            
            for node in graph_data["nodes"]:
                node_id = node["id"]
                current_community = communities[node_id]
                
                # Find neighbor communities
                neighbor_communities = defaultdict(float)
                for edge in graph_data["edges"]:
                    if edge["source"] == node_id:
                        neighbor_communities[communities[edge["target"]]] += edge.get("weight", 1.0)
                    elif edge["target"] == node_id:
                        neighbor_communities[communities[edge["source"]]] += edge.get("weight", 1.0)
                        
                # Move to best community
                if neighbor_communities:
                    best_community = max(neighbor_communities, key=neighbor_communities.get)
                    if best_community != current_community and neighbor_communities[best_community] > neighbor_communities.get(current_community, 0):
                        communities[node_id] = best_community
                        improved = True
                        
        # Renumber communities
        unique_communities = list(set(communities.values()))
        community_map = {old: new for new, old in enumerate(unique_communities)}
        
        return {node_id: community_map[comm] for node_id, comm in communities.items()}
        
    def export_to_d3(self, view: GraphView) -> str:
        """Export view to D3.js format.
        
        Args:
            view: GraphView object
            
        Returns:
            JSON string for D3.js
        """
        d3_data = {
            "nodes": [
                {
                    "id": node["id"],
                    "label": node.get("label", node["id"]),
                    "x": view.layout[node["id"]][0],
                    "y": view.layout[node["id"]][1],
                    **node.get("style", {})
                }
                for node in view.nodes
            ],
            "links": [
                {
                    "source": edge["source"],
                    "target": edge["target"],
                    "value": edge.get("weight", 1.0),
                    **edge.get("style", {})
                }
                for edge in view.edges
            ]
        }
        
        return json.dumps(d3_data, indent=2)
        
    def export_to_cytoscape(self, view: GraphView) -> str:
        """Export view to Cytoscape format.
        
        Args:
            view: GraphView object
            
        Returns:
            JSON string for Cytoscape
        """
        elements = []
        
        # Add nodes
        for node in view.nodes:
            elements.append({
                "data": {
                    "id": node["id"],
                    "label": node.get("label", node["id"]),
                    **{k: v for k, v in node.items() if k not in ["id", "label", "style"]}
                },
                "position": {
                    "x": view.layout[node["id"]][0],
                    "y": view.layout[node["id"]][1]
                },
                "style": node.get("style", {})
            })
            
        # Add edges
        for edge in view.edges:
            elements.append({
                "data": {
                    "id": f"{edge['source']}-{edge['target']}",
                    "source": edge["source"],
                    "target": edge["target"],
                    **{k: v for k, v in edge.items() if k not in ["source", "target", "style"]}
                },
                "style": edge.get("style", {})
            })
            
        cytoscape_data = {
            "elements": elements,
            "style": self._get_cytoscape_stylesheet(),
            "layout": {"name": "preset"}
        }
        
        return json.dumps(cytoscape_data, indent=2)
        
    def _get_cytoscape_stylesheet(self) -> List[Dict[str, Any]]:
        """Get Cytoscape stylesheet."""
        return [
            {
                "selector": "node",
                "style": {
                    "label": "data(label)",
                    "text-valign": "center",
                    "text-halign": "center",
                    "background-color": "data(color)",
                    "width": "data(size)",
                    "height": "data(size)"
                }
            },
            {
                "selector": "edge",
                "style": {
                    "width": "data(width)",
                    "line-color": "data(color)",
                    "target-arrow-color": "data(color)",
                    "target-arrow-shape": "triangle",
                    "curve-style": "bezier"
                }
            }
        ]