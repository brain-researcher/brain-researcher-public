"""Visualization API for graph data preparation."""

import time
from typing import Any, Dict, List, Optional, Tuple

import networkx as nx
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from ..algorithms.layouts import LayoutEngine
from ..utils.aggregation import GraphAggregator

router = APIRouter(prefix="/visualization", tags=["visualization"])


class GraphFilter(BaseModel):
    """Filter criteria for graph visualization."""

    node_properties: Optional[Dict[str, Any]] = Field(default=None)
    edge_types: Optional[List[str]] = Field(default=None)
    min_degree: Optional[int] = Field(default=None)
    max_degree: Optional[int] = Field(default=None)


class VisualizationRequest(BaseModel):
    """Request for graph visualization."""

    subgraph_query: Optional[str] = Field(
        default=None, description="Cypher query for subgraph"
    )
    node_ids: Optional[List[str]] = Field(
        default=None, description="Specific nodes to visualize"
    )
    max_nodes: int = Field(default=1000, description="Maximum nodes to return")
    layout_algorithm: str = Field(
        default="force_directed", description="Layout algorithm"
    )
    filters: Optional[GraphFilter] = Field(default=None)
    aggregate_dense: bool = Field(default=True, description="Aggregate dense regions")
    density_threshold: float = Field(
        default=0.7, description="Density threshold for aggregation"
    )


class VisualizationResponse(BaseModel):
    """Response with visualization data."""

    nodes: List[Dict[str, Any]]
    edges: List[Dict[str, Any]]
    layout: Dict[str, Tuple[float, float]]
    aggregation_info: Optional[Dict[str, Any]] = None
    performance_ms: float


class GraphFilterEngine:
    """Engine for filtering graph elements."""

    @staticmethod
    def by_node_property(
        graph: nx.Graph, property_name: str, value: Any, operator: str = "eq"
    ) -> nx.Graph:
        """Filter nodes by property value.

        Args:
            graph: Input graph
            property_name: Property to filter on
            value: Value to compare
            operator: Comparison operator (eq, ne, gt, lt, gte, lte, contains)

        Returns:
            Filtered graph
        """
        filtered_nodes = []

        for node, data in graph.nodes(data=True):
            prop_value = data.get(property_name)

            if operator == "eq" and prop_value == value:
                filtered_nodes.append(node)
            elif operator == "ne" and prop_value != value:
                filtered_nodes.append(node)
            elif operator == "gt" and prop_value > value:
                filtered_nodes.append(node)
            elif operator == "lt" and prop_value < value:
                filtered_nodes.append(node)
            elif operator == "gte" and prop_value >= value:
                filtered_nodes.append(node)
            elif operator == "lte" and prop_value <= value:
                filtered_nodes.append(node)
            elif operator == "contains" and value in str(prop_value):
                filtered_nodes.append(node)

        return graph.subgraph(filtered_nodes)

    @staticmethod
    def by_edge_type(graph: nx.Graph, edge_types: List[str]) -> nx.Graph:
        """Filter edges by type.

        Args:
            graph: Input graph
            edge_types: List of edge types to keep

        Returns:
            Filtered graph
        """
        filtered_edges = []

        for u, v, data in graph.edges(data=True):
            if data.get("type") in edge_types:
                filtered_edges.append((u, v))

        # Create subgraph with filtered edges
        filtered_graph = nx.Graph()
        filtered_graph.add_nodes_from(graph.nodes(data=True))
        filtered_graph.add_edges_from([(u, v, graph[u][v]) for u, v in filtered_edges])

        return filtered_graph

    @staticmethod
    def by_degree_range(
        graph: nx.Graph,
        min_degree: Optional[int] = None,
        max_degree: Optional[int] = None,
    ) -> nx.Graph:
        """Filter nodes by degree range.

        Args:
            graph: Input graph
            min_degree: Minimum degree
            max_degree: Maximum degree

        Returns:
            Filtered graph
        """
        filtered_nodes = []

        for node in graph.nodes():
            degree = graph.degree(node)

            if min_degree is not None and degree < min_degree:
                continue
            if max_degree is not None and degree > max_degree:
                continue

            filtered_nodes.append(node)

        return graph.subgraph(filtered_nodes)


@router.post("/prepare", response_model=VisualizationResponse)
async def prepare_visualization(request: VisualizationRequest):
    """Prepare graph data for visualization.

    Args:
        request: Visualization request parameters

    Returns:
        Prepared visualization data with layout
    """
    start_time = time.time()

    try:
        # TODO: Execute subgraph query or load nodes
        # For now, create a sample graph
        graph = nx.karate_club_graph()

        # Apply filters if specified
        if request.filters:
            filter_engine = GraphFilterEngine()

            if request.filters.node_properties:
                for prop, value in request.filters.node_properties.items():
                    graph = filter_engine.by_node_property(graph, prop, value)

            if request.filters.edge_types:
                graph = filter_engine.by_edge_type(graph, request.filters.edge_types)

            if (
                request.filters.min_degree is not None
                or request.filters.max_degree is not None
            ):
                graph = filter_engine.by_degree_range(
                    graph, request.filters.min_degree, request.filters.max_degree
                )

        # Limit number of nodes
        if len(graph) > request.max_nodes:
            # Take highest degree nodes
            nodes_by_degree = sorted(
                graph.nodes(), key=lambda x: graph.degree(x), reverse=True
            )
            graph = graph.subgraph(nodes_by_degree[: request.max_nodes])

        # Apply aggregation if requested
        aggregation_info = None
        if request.aggregate_dense and len(graph) > 50:
            aggregator = GraphAggregator()
            graph = aggregator.cluster_dense_regions(graph, request.density_threshold)
            aggregation_info = {
                "aggregated_clusters": len(aggregator.aggregation_metadata),
                "original_nodes": sum(
                    len(v["members"]) for v in aggregator.aggregation_metadata.values()
                ),
            }

        # Compute layout
        layout_engine = LayoutEngine()

        if request.layout_algorithm == "hierarchical":
            layout = layout_engine.hierarchical(graph)
        elif request.layout_algorithm == "circular":
            layout = layout_engine.circular(graph)
        else:  # force_directed
            layout = layout_engine.force_directed(graph)

        # Prepare response
        nodes = []
        for node, data in graph.nodes(data=True):
            node_data = {"id": str(node), **data}
            if node in layout:
                node_data["x"], node_data["y"] = layout[node]
            nodes.append(node_data)

        edges = []
        for u, v, data in graph.edges(data=True):
            edges.append({"source": str(u), "target": str(v), **data})

        elapsed = (time.time() - start_time) * 1000

        return VisualizationResponse(
            nodes=nodes,
            edges=edges,
            layout={str(k): v for k, v in layout.items()},
            aggregation_info=aggregation_info,
            performance_ms=elapsed,
        )

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Visualization error: {str(e)}")


@router.get("/layouts")
async def get_available_layouts():
    """Get list of available layout algorithms."""
    return {
        "layouts": [
            {
                "name": "force_directed",
                "description": "Force-directed layout using Fruchterman-Reingold",
                "best_for": "General graphs",
            },
            {
                "name": "hierarchical",
                "description": "Hierarchical layout for tree-like structures",
                "best_for": "Trees and DAGs",
            },
            {
                "name": "circular",
                "description": "Nodes arranged in a circle",
                "best_for": "Small to medium graphs",
            },
        ]
    }
