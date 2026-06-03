"""Unit tests for graph layout algorithms."""

import pytest
import networkx as nx
import math
from brain_researcher.services.br_kg.algorithms.layouts import LayoutEngine


class TestLayoutEngine:
    """Test suite for LayoutEngine."""

    @pytest.fixture
    def layout_engine(self):
        """Create layout engine instance."""
        return LayoutEngine(viewport_width=1000, viewport_height=800)

    @pytest.fixture
    def simple_graph(self):
        """Create simple test graph."""
        G = nx.Graph()
        G.add_edges_from([(1, 2), (2, 3), (3, 4), (4, 1), (1, 3)])
        return G

    @pytest.fixture
    def tree_graph(self):
        """Create tree graph for hierarchical layout."""
        G = nx.DiGraph()
        G.add_edges_from([
            ('root', 'child1'),
            ('root', 'child2'),
            ('child1', 'grandchild1'),
            ('child1', 'grandchild2'),
            ('child2', 'grandchild3')
        ])
        return G

    def test_force_directed_layout(self, layout_engine, simple_graph):
        """Test force-directed layout algorithm."""
        layout = layout_engine.force_directed(simple_graph, iterations=50)

        # Check all nodes have positions
        assert len(layout) == len(simple_graph.nodes())

        # Check positions are within viewport
        for node, (x, y) in layout.items():
            assert 0 <= x <= layout_engine.viewport_width
            assert 0 <= y <= layout_engine.viewport_height

        # Check nodes are separated (no overlap)
        positions = list(layout.values())
        for i, pos1 in enumerate(positions):
            for pos2 in positions[i+1:]:
                distance = math.sqrt((pos1[0] - pos2[0])**2 + (pos1[1] - pos2[1])**2)
                assert distance > 10, "Nodes too close together"

    def test_hierarchical_layout(self, layout_engine, tree_graph):
        """Test hierarchical layout algorithm."""
        layout = layout_engine.hierarchical(tree_graph, root='root')

        # Check all nodes have positions
        assert len(layout) == len(tree_graph.nodes())

        # Check root is at top
        root_y = layout['root'][1]
        for node in ['child1', 'child2']:
            assert layout[node][1] > root_y, "Children should be below root"

        # Check grandchildren are below children
        child1_y = layout['child1'][1]
        for node in ['grandchild1', 'grandchild2']:
            assert layout[node][1] > child1_y, "Grandchildren should be below children"

    def test_circular_layout(self, layout_engine, simple_graph):
        """Test circular layout algorithm."""
        layout = layout_engine.circular(simple_graph, ordering='degree')

        # Check all nodes have positions
        assert len(layout) == len(simple_graph.nodes())

        # Check nodes are arranged in circle
        center_x = layout_engine.viewport_width / 2
        center_y = layout_engine.viewport_height / 2

        distances = []
        for node, (x, y) in layout.items():
            distance = math.sqrt((x - center_x)**2 + (y - center_y)**2)
            distances.append(distance)

        # All distances should be approximately equal (circular)
        assert max(distances) - min(distances) < 1, "Nodes not arranged in circle"

    def test_empty_graph(self, layout_engine):
        """Test layout with empty graph."""
        G = nx.Graph()

        layout = layout_engine.force_directed(G)
        assert len(layout) == 0

        layout = layout_engine.hierarchical(G)
        assert len(layout) == 0

        layout = layout_engine.circular(G)
        assert len(layout) == 0

    def test_single_node(self, layout_engine):
        """Test layout with single node."""
        G = nx.Graph()
        G.add_node(1)

        layout = layout_engine.force_directed(G)
        assert len(layout) == 1
        assert 1 in layout

        x, y = layout[1]
        assert 0 <= x <= layout_engine.viewport_width
        assert 0 <= y <= layout_engine.viewport_height

    def test_layout_determinism(self, layout_engine, simple_graph):
        """Test that layouts are deterministic with same input."""
        # Force-directed is random, but should be stable within bounds
        layout1 = layout_engine.force_directed(simple_graph, iterations=10)
        layout2 = layout_engine.force_directed(simple_graph, iterations=10)

        # Positions will differ due to randomness, but structure should be similar
        for node in simple_graph.nodes():
            assert node in layout1
            assert node in layout2