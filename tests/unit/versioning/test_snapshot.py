"""Unit tests for graph snapshot and versioning system."""

import tempfile
from datetime import datetime, timedelta
from pathlib import Path

import networkx as nx
import pytest

from brain_researcher.services.br_kg.versioning.snapshot import (
    ChangeType,
    GraphSnapshot,
    GraphVersioning,
    SnapshotType,
)


class TestGraphSnapshot:
    """Test suite for GraphSnapshot."""

    def test_snapshot_creation(self):
        """Test creating a graph snapshot."""
        graph = nx.Graph()
        graph.add_node("A", weight=1)
        graph.add_node("B", weight=2)
        graph.add_edge("A", "B", weight=0.5)

        snapshot = GraphSnapshot("test_snapshot", graph)

        assert snapshot.snapshot_id == "test_snapshot"
        assert snapshot.graph.number_of_nodes() == 2
        assert snapshot.graph.number_of_edges() == 1
        assert snapshot.hash is not None
        assert len(snapshot.hash) == 64  # SHA256 hash

    def test_snapshot_hash_consistency(self):
        """Test that identical graphs produce same hash."""
        graph1 = nx.Graph()
        graph1.add_edge("A", "B", weight=1)

        graph2 = nx.Graph()
        graph2.add_edge("A", "B", weight=1)

        snapshot1 = GraphSnapshot("snap1", graph1)
        snapshot2 = GraphSnapshot("snap2", graph2)

        assert snapshot1.hash == snapshot2.hash

    def test_snapshot_hash_difference(self):
        """Test that different graphs produce different hashes."""
        graph1 = nx.Graph()
        graph1.add_edge("A", "B", weight=1)

        graph2 = nx.Graph()
        graph2.add_edge("A", "B", weight=2)  # Different weight

        snapshot1 = GraphSnapshot("snap1", graph1)
        snapshot2 = GraphSnapshot("snap2", graph2)

        assert snapshot1.hash != snapshot2.hash

    def test_snapshot_to_dict(self):
        """Test snapshot dictionary conversion."""
        graph = nx.Graph()
        graph.add_nodes_from([1, 2, 3])
        graph.add_edges_from([(1, 2), (2, 3)])

        metadata = {"description": "Test snapshot"}
        snapshot = GraphSnapshot("test", graph, metadata)

        data = snapshot.to_dict()

        assert data["snapshot_id"] == "test"
        assert "timestamp" in data
        assert data["hash"] == snapshot.hash
        assert data["metadata"] == metadata
        assert data["stats"]["nodes"] == 3
        assert data["stats"]["edges"] == 2


class TestGraphVersioning:
    """Test suite for GraphVersioning."""

    @pytest.fixture
    def versioning(self):
        """Create versioning instance with temp directory."""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield GraphVersioning(storage_dir=tmpdir)

    @pytest.fixture
    def sample_graph(self):
        """Create sample graph."""
        graph = nx.Graph()
        graph.add_nodes_from(["A", "B", "C"], type="concept")
        graph.add_edges_from([("A", "B"), ("B", "C")], weight=1.0)
        return graph

    def test_create_snapshot(self, versioning, sample_graph):
        """Test creating snapshots."""
        snapshot_id = versioning.create_snapshot(
            sample_graph, SnapshotType.FULL, "Initial snapshot"
        )

        assert snapshot_id in versioning.snapshots
        assert versioning.current_version == snapshot_id
        assert len(versioning.version_chain) == 1

        # Verify snapshot file was saved
        snapshot_file = Path(versioning.storage_dir) / f"{snapshot_id}.pkl"
        assert snapshot_file.exists()

    def test_load_snapshot(self, versioning, sample_graph):
        """Test loading snapshots."""
        snapshot_id = versioning.create_snapshot(sample_graph)

        # Clear memory cache
        versioning.snapshots.clear()

        # Load from disk
        loaded = versioning.load_snapshot(snapshot_id)

        assert loaded is not None
        assert loaded.snapshot_id == snapshot_id
        assert loaded.graph.number_of_nodes() == 3
        assert loaded.graph.number_of_edges() == 2

    def test_time_travel_query(self, versioning, sample_graph):
        """Test time-travel queries."""
        # Create snapshots at different times
        snapshot1_id = versioning.create_snapshot(sample_graph)

        # Modify graph
        sample_graph.add_node("D")
        versioning.create_snapshot(sample_graph)

        # Query at first snapshot time
        snapshot1 = versioning.snapshots[snapshot1_id]
        result = versioning.time_travel_query(
            snapshot1.timestamp, lambda g: g.number_of_nodes()
        )

        assert result == 3  # Original node count

    def test_compare_versions(self, versioning):
        """Test version comparison."""
        # Create initial graph
        graph1 = nx.Graph()
        graph1.add_nodes_from(["A", "B"], weight=1)
        graph1.add_edge("A", "B", weight=0.5)

        v1 = versioning.create_snapshot(graph1, description="Version 1")

        # Modify graph
        graph2 = nx.Graph()
        graph2.add_nodes_from(["A", "B", "C"], weight=1)
        graph2.add_edge("A", "B", weight=0.5)
        graph2.add_edge("B", "C", weight=0.8)
        graph2.nodes["A"]["weight"] = 2  # Modified node

        v2 = versioning.create_snapshot(graph2, description="Version 2")

        # Compare versions
        diff = versioning.compare_versions(v1, v2)

        assert "C" in diff["nodes"]["added"]
        assert len(diff["nodes"]["removed"]) == 0
        assert "A" in diff["nodes"]["modified"]
        assert ("B", "C") in diff["edges"]["added"] or ("C", "B") in diff["edges"][
            "added"
        ]
        assert (
            diff["summary"]["total_changes"] == 3
        )  # 1 node added, 1 modified, 1 edge added

    def test_rollback(self, versioning, sample_graph):
        """Test rollback functionality."""
        v1 = versioning.create_snapshot(sample_graph, description="V1")

        sample_graph.add_node("D")
        v2 = versioning.create_snapshot(sample_graph, description="V2")

        sample_graph.add_node("E")
        v3 = versioning.create_snapshot(sample_graph, description="V3")

        assert len(versioning.version_chain) == 3
        assert versioning.current_version == v3

        # Rollback to v1
        success = versioning.rollback(v1)

        assert success
        assert versioning.current_version == v1
        assert len(versioning.version_chain) == 1
        assert v2 not in versioning.version_chain
        assert v3 not in versioning.version_chain

    def test_create_branch(self, versioning, sample_graph):
        """Test branch creation."""
        v1 = versioning.create_snapshot(sample_graph)

        branch_id = versioning.create_branch("feature_branch")

        assert branch_id in versioning.snapshots
        branch = versioning.snapshots[branch_id]
        assert branch.metadata["branch_name"] == "feature_branch"
        assert branch.metadata["branched_from"] == v1
        assert branch.graph.number_of_nodes() == sample_graph.number_of_nodes()

    def test_merge_branches(self, versioning):
        """Test branch merging."""
        # Create base graph
        base_graph = nx.Graph()
        base_graph.add_nodes_from(["A", "B"])
        base_graph.add_edge("A", "B")

        versioning.create_snapshot(base_graph)

        # Create branch 1
        branch1_graph = base_graph.copy()
        branch1_graph.add_node("C")
        branch1 = versioning.create_snapshot(branch1_graph, description="Branch 1")

        # Create branch 2
        branch2_graph = base_graph.copy()
        branch2_graph.add_node("D")
        branch2 = versioning.create_snapshot(branch2_graph, description="Branch 2")

        # Merge branches
        merged_id = versioning.merge_branches(
            branch1, branch2, conflict_resolution="source"
        )

        merged = versioning.snapshots[merged_id]

        # Check merged graph has all nodes
        assert "A" in merged.graph.nodes()
        assert "B" in merged.graph.nodes()
        assert "C" in merged.graph.nodes()
        assert "D" in merged.graph.nodes()
        assert merged.graph.number_of_edges() == 1

    def test_calculate_diff(self, versioning):
        """Test detailed diff calculation."""
        graph1 = nx.Graph()
        graph1.add_node("A")
        v1 = versioning.create_snapshot(graph1)

        graph2 = nx.Graph()
        graph2.add_nodes_from(["A", "B"])
        graph2.add_edge("A", "B")
        graph2.nodes["A"]["modified"] = True
        v2 = versioning.create_snapshot(graph2)

        changes = versioning.calculate_diff(v1, v2)

        # Check change types
        change_types = [c["type"] for c in changes]
        assert ChangeType.NODE_ADDED.value in change_types
        assert ChangeType.NODE_MODIFIED.value in change_types
        assert ChangeType.EDGE_ADDED.value in change_types

        # Verify specific changes
        node_added = next(
            c for c in changes if c["type"] == ChangeType.NODE_ADDED.value
        )
        assert node_added["node"] == "B"

    def test_version_history(self, versioning, sample_graph):
        """Test version history retrieval."""
        # Create multiple versions
        for i in range(3):
            sample_graph.add_node(f"Node_{i}")
            versioning.create_snapshot(sample_graph, description=f"Version {i+1}")

        history = versioning.get_version_history()

        assert len(history) == 3
        for i, version in enumerate(history):
            assert "snapshot_id" in version
            assert "timestamp" in version
            assert "hash" in version
            assert version["stats"]["nodes"] == 3 + i + 1  # Original 3 + added nodes


class TestSnapshotPerformance:
    """Performance tests for snapshot system."""

    @pytest.mark.slow
    def test_large_graph_snapshot(self):
        """Test snapshot performance with large graph."""
        # Create large graph (1000 nodes, 5000 edges)
        graph = nx.erdos_renyi_graph(1000, 0.01)

        # Add attributes
        for node in graph.nodes():
            graph.nodes[node]["weight"] = node
        for edge in graph.edges():
            graph.edges[edge]["weight"] = 1.0

        start = datetime.now()
        snapshot = GraphSnapshot("large_graph", graph)
        duration = (datetime.now() - start).total_seconds()

        assert duration < 1.0  # Should complete within 1 second
        assert snapshot.hash is not None

    @pytest.mark.slow
    def test_version_chain_performance(self):
        """Test performance with long version chain."""
        with tempfile.TemporaryDirectory() as tmpdir:
            versioning = GraphVersioning(storage_dir=tmpdir)
            graph = nx.Graph()

            # Create 100 versions
            for i in range(100):
                graph.add_node(f"node_{i}")
                if i > 0:
                    graph.add_edge(f"node_{i-1}", f"node_{i}")
                versioning.create_snapshot(graph)

            assert len(versioning.version_chain) == 100

            # Test time-travel query performance
            start = datetime.now()
            result = versioning.time_travel_query(
                datetime.now() - timedelta(minutes=5), lambda g: g.number_of_nodes()
            )
            duration = (datetime.now() - start).total_seconds()

            assert duration < 0.5  # Should be fast
            assert result is not None
