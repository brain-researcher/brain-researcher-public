"""Unit tests for path finding algorithms."""

import pytest
import networkx as nx
from brain_researcher.services.br_kg.algorithms.paths import PathFinder


class TestPathFinder:
    """Test suite for PathFinder algorithms."""

    @pytest.fixture
    def weighted_graph(self):
        """Create weighted graph for testing."""
        G = nx.Graph()
        G.add_weighted_edges_from([
            ('A', 'B', 1),
            ('B', 'C', 2),
            ('A', 'C', 4),
            ('C', 'D', 1),
            ('B', 'D', 5),
            ('D', 'E', 1)
        ])
        return G

    @pytest.fixture
    def disconnected_graph(self):
        """Create disconnected graph."""
        G = nx.Graph()
        G.add_edges_from([('A', 'B'), ('C', 'D')])
        return G

    def test_dijkstra_shortest_path(self, weighted_graph):
        """Test Dijkstra's algorithm."""
        path, weight = PathFinder.dijkstra(weighted_graph, 'A', 'E')

        # Shortest path should be A -> B -> C -> D -> E
        assert path == ['A', 'B', 'C', 'D', 'E']
        assert weight == 5  # 1 + 2 + 1 + 1

    def test_dijkstra_no_path(self, disconnected_graph):
        """Test Dijkstra when no path exists."""
        path, weight = PathFinder.dijkstra(disconnected_graph, 'A', 'D')

        assert path == []
        assert weight == float('inf')

    def test_dijkstra_same_node(self, weighted_graph):
        """Test path from node to itself."""
        path, weight = PathFinder.dijkstra(weighted_graph, 'A', 'A')

        assert path == ['A']
        assert weight == 0

    def test_a_star_with_heuristic(self, weighted_graph):
        """Test A* algorithm with heuristic."""
        # Simple heuristic: underestimate distance
        heuristic = {
            'A': 4,
            'B': 3,
            'C': 2,
            'D': 1,
            'E': 0
        }

        path, weight = PathFinder.a_star(weighted_graph, 'A', 'E', heuristic)

        assert path == ['A', 'B', 'C', 'D', 'E']
        assert weight == 5

    def test_a_star_without_heuristic(self, weighted_graph):
        """Test A* without heuristic (reduces to Dijkstra)."""
        path, weight = PathFinder.a_star(weighted_graph, 'A', 'E')

        assert path == ['A', 'B', 'C', 'D', 'E']
        assert weight == 5

    def test_all_shortest_paths(self, weighted_graph):
        """Test finding all shortest paths."""
        # Add alternative path with same weight
        weighted_graph.add_edge('A', 'D', 3)

        paths = PathFinder.all_shortest_paths(weighted_graph, 'A', 'D')

        # Should find both paths
        assert len(paths) >= 1
        # Direct path A -> D (weight 3)
        assert ['A', 'D'] in paths or ['A', 'B', 'C', 'D'] in paths

    def test_find_paths_with_length(self, weighted_graph):
        """Test finding paths within length range."""
        paths = PathFinder.find_paths_with_length(
            weighted_graph, 'A', 'E',
            min_length=2, max_length=4
        )

        # Should find paths of length 2-4
        assert len(paths) > 0
        for path in paths:
            path_length = len(path) - 1
            assert 2 <= path_length <= 4

    def test_paths_avoid_cycles(self, weighted_graph):
        """Test that paths don't contain cycles."""
        # Add cycle
        weighted_graph.add_edge('E', 'A', 1)

        paths = PathFinder.find_paths_with_length(
            weighted_graph, 'A', 'E',
            min_length=1, max_length=10
        )

        for path in paths:
            # Check no repeated nodes (no cycles)
            assert len(path) == len(set(path)), f"Cycle detected in path: {path}"

    def test_invalid_nodes(self, weighted_graph):
        """Test with invalid node IDs."""
        path, weight = PathFinder.dijkstra(weighted_graph, 'A', 'Z')
        assert path == []
        assert weight == float('inf')

        path, weight = PathFinder.dijkstra(weighted_graph, 'Z', 'A')
        assert path == []
        assert weight == float('inf')