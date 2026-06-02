"""Graph snapshot and versioning system."""

import hashlib
import json
import logging
import pickle
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import networkx as nx

logger = logging.getLogger(__name__)


class SnapshotType(str, Enum):
    """Types of snapshots."""

    FULL = "full"
    INCREMENTAL = "incremental"
    CHECKPOINT = "checkpoint"


class ChangeType(str, Enum):
    """Types of changes."""

    NODE_ADDED = "node_added"
    NODE_REMOVED = "node_removed"
    NODE_MODIFIED = "node_modified"
    EDGE_ADDED = "edge_added"
    EDGE_REMOVED = "edge_removed"
    EDGE_MODIFIED = "edge_modified"


class GraphSnapshot:
    """Represents a graph snapshot."""

    def __init__(
        self,
        snapshot_id: str,
        graph: nx.Graph,
        metadata: Optional[Dict[str, Any]] = None,
    ):
        """Initialize snapshot.

        Args:
            snapshot_id: Unique snapshot identifier
            graph: NetworkX graph
            metadata: Additional metadata
        """
        self.snapshot_id = snapshot_id
        self.graph = graph.copy()
        self.timestamp = datetime.utcnow()
        self.metadata = metadata or {}
        self.hash = self._calculate_hash()

    def _calculate_hash(self) -> str:
        """Calculate hash of graph state.

        Returns:
            SHA256 hash of graph
        """
        # Serialize graph deterministically
        nodes = sorted(self.graph.nodes(data=True))
        edges = sorted(self.graph.edges(data=True))

        graph_data = {"nodes": nodes, "edges": edges}

        serialized = json.dumps(graph_data, sort_keys=True)
        return hashlib.sha256(serialized.encode()).hexdigest()

    def to_dict(self) -> Dict[str, Any]:
        """Convert snapshot to dictionary.

        Returns:
            Snapshot as dict
        """
        return {
            "snapshot_id": self.snapshot_id,
            "timestamp": self.timestamp.isoformat(),
            "hash": self.hash,
            "metadata": self.metadata,
            "stats": {
                "nodes": self.graph.number_of_nodes(),
                "edges": self.graph.number_of_edges(),
            },
        }


class GraphVersioning:
    """Manages graph versions with time-travel queries."""

    def __init__(self, storage_dir: str = "/tmp/graph_snapshots"):
        """Initialize versioning system.

        Args:
            storage_dir: Directory for snapshot storage
        """
        self.storage_dir = Path(storage_dir)
        self.storage_dir.mkdir(parents=True, exist_ok=True)

        self.snapshots: Dict[str, GraphSnapshot] = {}
        self.version_chain: List[str] = []
        self.current_version: Optional[str] = None
        self.change_log: List[Dict[str, Any]] = []

    def create_snapshot(
        self,
        graph: nx.Graph,
        snapshot_type: SnapshotType = SnapshotType.FULL,
        description: str = "",
    ) -> str:
        """Create a new snapshot.

        Args:
            graph: Graph to snapshot
            snapshot_type: Type of snapshot
            description: Snapshot description

        Returns:
            Snapshot ID
        """
        # Generate snapshot ID
        timestamp = datetime.utcnow()
        snapshot_id = (
            f"snapshot_{timestamp.strftime('%Y%m%d_%H%M%S')}_{len(self.snapshots)}"
        )

        # Create snapshot
        metadata = {
            "type": snapshot_type.value,
            "description": description,
            "parent": self.current_version,
        }

        snapshot = GraphSnapshot(snapshot_id, graph, metadata)

        # Store snapshot
        self.snapshots[snapshot_id] = snapshot
        self.version_chain.append(snapshot_id)
        self.current_version = snapshot_id

        # Save to disk
        self._save_snapshot(snapshot)

        logger.info(f"Created snapshot {snapshot_id}")
        return snapshot_id

    def _save_snapshot(self, snapshot: GraphSnapshot):
        """Save snapshot to disk.

        Args:
            snapshot: Snapshot to save
        """
        snapshot_file = self.storage_dir / f"{snapshot.snapshot_id}.pkl"

        with open(snapshot_file, "wb") as f:
            pickle.dump(snapshot, f)

    def load_snapshot(self, snapshot_id: str) -> Optional[GraphSnapshot]:
        """Load snapshot from storage.

        Args:
            snapshot_id: Snapshot identifier

        Returns:
            GraphSnapshot or None
        """
        # Check memory cache first
        if snapshot_id in self.snapshots:
            return self.snapshots[snapshot_id]

        # Load from disk
        snapshot_file = self.storage_dir / f"{snapshot_id}.pkl"

        if snapshot_file.exists():
            with open(snapshot_file, "rb") as f:
                snapshot = pickle.load(f)
                self.snapshots[snapshot_id] = snapshot
                return snapshot

        return None

    def time_travel_query(self, timestamp: datetime, query_func: callable) -> Any:
        """Execute query on graph at specific time.

        Args:
            timestamp: Point in time
            query_func: Function to execute on graph

        Returns:
            Query result
        """
        # Find snapshot closest to timestamp
        closest_snapshot = None
        min_diff = float("inf")

        for snapshot_id in self.version_chain:
            snapshot = self.load_snapshot(snapshot_id)
            if snapshot:
                diff = abs((snapshot.timestamp - timestamp).total_seconds())
                if diff < min_diff:
                    min_diff = diff
                    closest_snapshot = snapshot

        if closest_snapshot:
            return query_func(closest_snapshot.graph)

        return None

    def compare_versions(self, version1: str, version2: str) -> Dict[str, Any]:
        """Compare two graph versions.

        Args:
            version1: First version ID
            version2: Second version ID

        Returns:
            Comparison results
        """
        snap1 = self.load_snapshot(version1)
        snap2 = self.load_snapshot(version2)

        if not snap1 or not snap2:
            raise ValueError("Invalid snapshot IDs")

        g1 = snap1.graph
        g2 = snap2.graph

        # Calculate differences
        nodes_added = set(g2.nodes()) - set(g1.nodes())
        nodes_removed = set(g1.nodes()) - set(g2.nodes())
        edges_added = set(g2.edges()) - set(g1.edges())
        edges_removed = set(g1.edges()) - set(g2.edges())

        # Check for modified nodes
        nodes_modified = []
        common_nodes = set(g1.nodes()) & set(g2.nodes())
        for node in common_nodes:
            if g1.nodes[node] != g2.nodes[node]:
                nodes_modified.append(node)

        # Check for modified edges
        edges_modified = []
        common_edges = set(g1.edges()) & set(g2.edges())
        for edge in common_edges:
            if g1.edges[edge] != g2.edges[edge]:
                edges_modified.append(edge)

        return {
            "version1": version1,
            "version2": version2,
            "nodes": {
                "added": list(nodes_added),
                "removed": list(nodes_removed),
                "modified": nodes_modified,
            },
            "edges": {
                "added": list(edges_added),
                "removed": list(edges_removed),
                "modified": edges_modified,
            },
            "summary": {
                "total_changes": (
                    len(nodes_added)
                    + len(nodes_removed)
                    + len(nodes_modified)
                    + len(edges_added)
                    + len(edges_removed)
                    + len(edges_modified)
                )
            },
        }

    def rollback(self, target_version: str) -> bool:
        """Rollback to specific version.

        Args:
            target_version: Version to rollback to

        Returns:
            Success status
        """
        if target_version not in self.version_chain:
            logger.error(f"Version {target_version} not found")
            return False

        # Find index of target version
        target_index = self.version_chain.index(target_version)

        # Remove newer versions from chain
        removed_versions = self.version_chain[target_index + 1 :]
        self.version_chain = self.version_chain[: target_index + 1]

        # Update current version
        self.current_version = target_version

        # Log rollback
        self.change_log.append(
            {
                "timestamp": datetime.utcnow().isoformat(),
                "action": "rollback",
                "target_version": target_version,
                "removed_versions": removed_versions,
            }
        )

        logger.info(f"Rolled back to version {target_version}")
        return True

    def create_branch(self, branch_name: str) -> str:
        """Create a new branch from current version.

        Args:
            branch_name: Name for the branch

        Returns:
            Branch ID
        """
        if not self.current_version:
            raise ValueError("No current version to branch from")

        current_snapshot = self.load_snapshot(self.current_version)
        if not current_snapshot:
            raise ValueError("Current snapshot not found")

        # Create branch snapshot
        branch_id = (
            f"branch_{branch_name}_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}"
        )

        metadata = {
            "type": "branch",
            "branch_name": branch_name,
            "branched_from": self.current_version,
        }

        branch_snapshot = GraphSnapshot(branch_id, current_snapshot.graph, metadata)

        # Store branch
        self.snapshots[branch_id] = branch_snapshot
        self._save_snapshot(branch_snapshot)

        logger.info(f"Created branch {branch_name} as {branch_id}")
        return branch_id

    def merge_branches(
        self,
        source_branch: str,
        target_branch: str,
        conflict_resolution: str = "source",
    ) -> str:
        """Merge two branches.

        Args:
            source_branch: Source branch ID
            target_branch: Target branch ID
            conflict_resolution: How to resolve conflicts ('source' or 'target')

        Returns:
            Merged snapshot ID
        """
        source = self.load_snapshot(source_branch)
        target = self.load_snapshot(target_branch)

        if not source or not target:
            raise ValueError("Invalid branch IDs")

        # Create merged graph
        merged_graph = nx.Graph()

        # Add all nodes from both graphs
        for node, data in source.graph.nodes(data=True):
            merged_graph.add_node(node, **data)

        for node, data in target.graph.nodes(data=True):
            if node not in merged_graph:
                merged_graph.add_node(node, **data)
            elif conflict_resolution == "target":
                # Overwrite with target data
                merged_graph.nodes[node].update(data)

        # Add all edges from both graphs
        for u, v, data in source.graph.edges(data=True):
            merged_graph.add_edge(u, v, **data)

        for u, v, data in target.graph.edges(data=True):
            if not merged_graph.has_edge(u, v):
                merged_graph.add_edge(u, v, **data)
            elif conflict_resolution == "target":
                # Overwrite with target data
                merged_graph.edges[u, v].update(data)

        # Create merged snapshot
        merge_id = self.create_snapshot(
            merged_graph,
            SnapshotType.FULL,
            f"Merge of {source_branch} into {target_branch}",
        )

        return merge_id

    def get_version_history(self) -> List[Dict[str, Any]]:
        """Get version history.

        Returns:
            List of version summaries
        """
        history = []

        for snapshot_id in self.version_chain:
            snapshot = self.load_snapshot(snapshot_id)
            if snapshot:
                history.append(snapshot.to_dict())

        return history

    def calculate_diff(
        self, from_version: str, to_version: str
    ) -> List[Dict[str, Any]]:
        """Calculate detailed diff between versions.

        Args:
            from_version: Starting version
            to_version: Ending version

        Returns:
            List of changes
        """
        comparison = self.compare_versions(from_version, to_version)
        changes = []

        # Node changes
        for node in comparison["nodes"]["added"]:
            changes.append(
                {
                    "type": ChangeType.NODE_ADDED.value,
                    "node": node,
                    "timestamp": datetime.utcnow().isoformat(),
                }
            )

        for node in comparison["nodes"]["removed"]:
            changes.append(
                {
                    "type": ChangeType.NODE_REMOVED.value,
                    "node": node,
                    "timestamp": datetime.utcnow().isoformat(),
                }
            )

        for node in comparison["nodes"]["modified"]:
            changes.append(
                {
                    "type": ChangeType.NODE_MODIFIED.value,
                    "node": node,
                    "timestamp": datetime.utcnow().isoformat(),
                }
            )

        # Edge changes
        for edge in comparison["edges"]["added"]:
            changes.append(
                {
                    "type": ChangeType.EDGE_ADDED.value,
                    "edge": edge,
                    "timestamp": datetime.utcnow().isoformat(),
                }
            )

        for edge in comparison["edges"]["removed"]:
            changes.append(
                {
                    "type": ChangeType.EDGE_REMOVED.value,
                    "edge": edge,
                    "timestamp": datetime.utcnow().isoformat(),
                }
            )

        for edge in comparison["edges"]["modified"]:
            changes.append(
                {
                    "type": ChangeType.EDGE_MODIFIED.value,
                    "edge": edge,
                    "timestamp": datetime.utcnow().isoformat(),
                }
            )

        return changes
