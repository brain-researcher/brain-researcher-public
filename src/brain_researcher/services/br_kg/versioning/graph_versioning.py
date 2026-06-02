"""Graph versioning and snapshot system - implements KG-019.

This module provides Git-like versioning for the knowledge graph,
allowing tracking of changes, creating snapshots, and rollback.
"""

import gzip
import hashlib
import json
import logging
import pickle
from dataclasses import asdict, dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

logger = logging.getLogger(__name__)


class ChangeType(Enum):
    """Types of graph changes."""

    CREATE_NODE = "create_node"
    UPDATE_NODE = "update_node"
    DELETE_NODE = "delete_node"
    CREATE_EDGE = "create_edge"
    UPDATE_EDGE = "update_edge"
    DELETE_EDGE = "delete_edge"


@dataclass
class GraphChange:
    """Represents a single change to the graph."""

    change_type: ChangeType
    entity_type: str  # "node" or "edge"
    entity_id: str
    old_value: Optional[Dict[str, Any]] = None
    new_value: Optional[Dict[str, Any]] = None
    timestamp: datetime = field(default_factory=datetime.now)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "change_type": self.change_type.value,
            "entity_type": self.entity_type,
            "entity_id": self.entity_id,
            "old_value": self.old_value,
            "new_value": self.new_value,
            "timestamp": self.timestamp.isoformat(),
            "metadata": self.metadata,
        }


@dataclass
class GraphCommit:
    """Represents a commit in the graph history."""

    commit_id: str
    parent_id: Optional[str]
    changes: List[GraphChange]
    message: str
    author: str
    timestamp: datetime = field(default_factory=datetime.now)
    tags: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "commit_id": self.commit_id,
            "parent_id": self.parent_id,
            "changes": [c.to_dict() for c in self.changes],
            "message": self.message,
            "author": self.author,
            "timestamp": self.timestamp.isoformat(),
            "tags": self.tags,
            "metadata": self.metadata,
        }


@dataclass
class GraphSnapshot:
    """Represents a complete snapshot of the graph."""

    snapshot_id: str
    commit_id: str
    nodes: Dict[str, Dict[str, Any]]
    edges: Dict[str, Dict[str, Any]]
    timestamp: datetime = field(default_factory=datetime.now)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def get_hash(self) -> str:
        """Calculate hash of snapshot content."""
        content = json.dumps(
            {"nodes": sorted(self.nodes.items()), "edges": sorted(self.edges.items())},
            sort_keys=True,
        )
        return hashlib.sha256(content.encode()).hexdigest()


class GraphVersioning:
    """Manage graph versioning and snapshots."""

    def __init__(self, storage_path: str = "./graph_versions"):
        """Initialize versioning system.

        Args:
            storage_path: Path to store version data
        """
        self.storage_path = Path(storage_path)
        self.storage_path.mkdir(parents=True, exist_ok=True)

        self.commits_path = self.storage_path / "commits"
        self.snapshots_path = self.storage_path / "snapshots"
        self.branches_path = self.storage_path / "branches"

        self.commits_path.mkdir(exist_ok=True)
        self.snapshots_path.mkdir(exist_ok=True)
        self.branches_path.mkdir(exist_ok=True)

        self.current_branch = "main"
        self.current_commit = None
        self.uncommitted_changes = []

        self._load_state()

    def _load_state(self):
        """Load current state from storage."""
        # Load current branch
        branch_file = self.branches_path / "HEAD"
        if branch_file.exists():
            self.current_branch = branch_file.read_text().strip()

        # Load current commit
        branch_commit_file = self.branches_path / f"{self.current_branch}.txt"
        if branch_commit_file.exists():
            self.current_commit = branch_commit_file.read_text().strip()

    def _save_state(self):
        """Save current state to storage."""
        # Save current branch
        branch_file = self.branches_path / "HEAD"
        branch_file.write_text(self.current_branch)

        # Save current commit
        if self.current_commit:
            branch_commit_file = self.branches_path / f"{self.current_branch}.txt"
            branch_commit_file.write_text(self.current_commit)

    def track_change(
        self,
        change_type: ChangeType,
        entity_type: str,
        entity_id: str,
        old_value: Optional[Dict[str, Any]] = None,
        new_value: Optional[Dict[str, Any]] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ):
        """Track a change to the graph.

        Args:
            change_type: Type of change
            entity_type: "node" or "edge"
            entity_id: ID of the entity
            old_value: Previous value
            new_value: New value
            metadata: Additional metadata
        """
        change = GraphChange(
            change_type=change_type,
            entity_type=entity_type,
            entity_id=entity_id,
            old_value=old_value,
            new_value=new_value,
            metadata=metadata or {},
        )

        self.uncommitted_changes.append(change)
        logger.info(f"Tracked change: {change_type.value} on {entity_type} {entity_id}")

    def commit(
        self, message: str, author: str, tags: Optional[List[str]] = None
    ) -> str:
        """Commit tracked changes.

        Args:
            message: Commit message
            author: Author name
            tags: Optional tags

        Returns:
            Commit ID
        """
        if not self.uncommitted_changes:
            logger.warning("No changes to commit")
            return None

        # Generate commit ID
        commit_content = json.dumps(
            {
                "parent": self.current_commit,
                "changes": [c.to_dict() for c in self.uncommitted_changes],
                "message": message,
                "author": author,
                "timestamp": datetime.now().isoformat(),
            },
            sort_keys=True,
        )
        commit_id = hashlib.sha256(commit_content.encode()).hexdigest()[:12]

        # Create commit
        commit = GraphCommit(
            commit_id=commit_id,
            parent_id=self.current_commit,
            changes=self.uncommitted_changes.copy(),
            message=message,
            author=author,
            tags=tags or [],
        )

        # Save commit
        commit_file = self.commits_path / f"{commit_id}.json"
        with open(commit_file, "w") as f:
            json.dump(commit.to_dict(), f, indent=2)

        # Update state
        self.current_commit = commit_id
        self.uncommitted_changes.clear()
        self._save_state()

        logger.info(f"Created commit {commit_id}: {message}")
        return commit_id

    def create_snapshot(
        self,
        nodes: Dict[str, Dict[str, Any]],
        edges: Dict[str, Dict[str, Any]],
        message: str = None,
    ) -> str:
        """Create a snapshot of the current graph state.

        Args:
            nodes: Current nodes
            edges: Current edges
            message: Optional message

        Returns:
            Snapshot ID
        """
        # Generate snapshot ID
        snapshot_id = hashlib.sha256(
            f"{self.current_commit}_{datetime.now().isoformat()}".encode()
        ).hexdigest()[:12]

        # Create snapshot
        snapshot = GraphSnapshot(
            snapshot_id=snapshot_id,
            commit_id=self.current_commit or "initial",
            nodes=nodes.copy(),
            edges=edges.copy(),
            metadata={"message": message} if message else {},
        )

        # Compress and save
        snapshot_file = self.snapshots_path / f"{snapshot_id}.pkl.gz"
        with gzip.open(snapshot_file, "wb") as f:
            pickle.dump(snapshot, f)

        logger.info(f"Created snapshot {snapshot_id}")
        return snapshot_id

    def load_snapshot(self, snapshot_id: str) -> Optional[GraphSnapshot]:
        """Load a snapshot.

        Args:
            snapshot_id: Snapshot ID

        Returns:
            GraphSnapshot or None
        """
        snapshot_file = self.snapshots_path / f"{snapshot_id}.pkl.gz"

        if not snapshot_file.exists():
            logger.error(f"Snapshot {snapshot_id} not found")
            return None

        with gzip.open(snapshot_file, "rb") as f:
            snapshot = pickle.load(f)

        logger.info(f"Loaded snapshot {snapshot_id}")
        return snapshot

    def get_commit(self, commit_id: str) -> Optional[GraphCommit]:
        """Get a specific commit.

        Args:
            commit_id: Commit ID

        Returns:
            GraphCommit or None
        """
        commit_file = self.commits_path / f"{commit_id}.json"

        if not commit_file.exists():
            logger.error(f"Commit {commit_id} not found")
            return None

        with open(commit_file, "r") as f:
            commit_data = json.load(f)

        # Reconstruct commit
        commit = GraphCommit(
            commit_id=commit_data["commit_id"],
            parent_id=commit_data["parent_id"],
            changes=[
                GraphChange(
                    change_type=ChangeType(c["change_type"]),
                    entity_type=c["entity_type"],
                    entity_id=c["entity_id"],
                    old_value=c["old_value"],
                    new_value=c["new_value"],
                    timestamp=datetime.fromisoformat(c["timestamp"]),
                    metadata=c["metadata"],
                )
                for c in commit_data["changes"]
            ],
            message=commit_data["message"],
            author=commit_data["author"],
            timestamp=datetime.fromisoformat(commit_data["timestamp"]),
            tags=commit_data.get("tags", []),
            metadata=commit_data.get("metadata", {}),
        )

        return commit

    def get_history(self, limit: int = 10) -> List[GraphCommit]:
        """Get commit history.

        Args:
            limit: Maximum number of commits

        Returns:
            List of commits
        """
        history = []
        current = self.current_commit

        while current and len(history) < limit:
            commit = self.get_commit(current)
            if commit:
                history.append(commit)
                current = commit.parent_id
            else:
                break

        return history

    def diff(self, commit_id1: str, commit_id2: str) -> List[GraphChange]:
        """Get differences between two commits.

        Args:
            commit_id1: First commit
            commit_id2: Second commit

        Returns:
            List of changes
        """
        # Get all changes between commits
        changes = []

        # Find common ancestor
        ancestors1 = self._get_ancestors(commit_id1)
        ancestors2 = self._get_ancestors(commit_id2)
        common_ancestor = None

        for ancestor in ancestors1:
            if ancestor in ancestors2:
                common_ancestor = ancestor
                break

        if not common_ancestor:
            logger.warning("No common ancestor found")
            return changes

        # Get changes from common ancestor to commit2
        current = commit_id2
        while current and current != common_ancestor:
            commit = self.get_commit(current)
            if commit:
                changes.extend(commit.changes)
                current = commit.parent_id
            else:
                break

        return changes

    def _get_ancestors(self, commit_id: str) -> List[str]:
        """Get all ancestors of a commit.

        Args:
            commit_id: Commit ID

        Returns:
            List of ancestor commit IDs
        """
        ancestors = []
        current = commit_id

        while current:
            ancestors.append(current)
            commit = self.get_commit(current)
            if commit:
                current = commit.parent_id
            else:
                break

        return ancestors

    def rollback(self, commit_id: str) -> bool:
        """Rollback to a specific commit.

        Args:
            commit_id: Target commit ID

        Returns:
            Success status
        """
        # Verify commit exists
        commit = self.get_commit(commit_id)
        if not commit:
            logger.error(f"Commit {commit_id} not found")
            return False

        # Clear uncommitted changes
        if self.uncommitted_changes:
            logger.warning("Discarding uncommitted changes")
            self.uncommitted_changes.clear()

        # Update current commit
        self.current_commit = commit_id
        self._save_state()

        logger.info(f"Rolled back to commit {commit_id}")
        return True

    def create_branch(self, branch_name: str) -> bool:
        """Create a new branch.

        Args:
            branch_name: Name of the new branch

        Returns:
            Success status
        """
        branch_file = self.branches_path / f"{branch_name}.txt"

        if branch_file.exists():
            logger.error(f"Branch {branch_name} already exists")
            return False

        # Create branch pointing to current commit
        branch_file.write_text(self.current_commit or "")

        logger.info(f"Created branch {branch_name}")
        return True

    def switch_branch(self, branch_name: str) -> bool:
        """Switch to a different branch.

        Args:
            branch_name: Target branch name

        Returns:
            Success status
        """
        branch_file = self.branches_path / f"{branch_name}.txt"

        if not branch_file.exists():
            logger.error(f"Branch {branch_name} not found")
            return False

        # Check for uncommitted changes
        if self.uncommitted_changes:
            logger.warning("Please commit or discard changes before switching branches")
            return False

        # Switch branch
        self.current_branch = branch_name
        self.current_commit = branch_file.read_text().strip() or None
        self._save_state()

        logger.info(f"Switched to branch {branch_name}")
        return True

    def merge(self, source_branch: str, message: str, author: str) -> Optional[str]:
        """Merge another branch into current branch.

        Args:
            source_branch: Branch to merge from
            message: Merge commit message
            author: Author name

        Returns:
            Merge commit ID or None
        """
        source_file = self.branches_path / f"{source_branch}.txt"

        if not source_file.exists():
            logger.error(f"Branch {source_branch} not found")
            return None

        source_commit = source_file.read_text().strip()

        if not source_commit:
            logger.error(f"Branch {source_branch} has no commits")
            return None

        # Get changes to merge
        changes_to_merge = self.diff(self.current_commit, source_commit)

        if not changes_to_merge:
            logger.info("Nothing to merge")
            return None

        # Apply changes
        self.uncommitted_changes.extend(changes_to_merge)

        # Create merge commit
        commit_id = self.commit(
            message=f"Merge branch '{source_branch}': {message}",
            author=author,
            tags=["merge"],
        )

        return commit_id

    def get_stats(self) -> Dict[str, Any]:
        """Get versioning statistics.

        Returns:
            Statistics dictionary
        """
        # Count commits
        commit_files = list(self.commits_path.glob("*.json"))

        # Count snapshots
        snapshot_files = list(self.snapshots_path.glob("*.pkl.gz"))

        # Count branches
        branch_files = list(self.branches_path.glob("*.txt"))

        # Calculate storage size
        total_size = 0
        for path in [self.commits_path, self.snapshots_path]:
            for file in path.iterdir():
                if file.is_file():
                    total_size += file.stat().st_size

        return {
            "current_branch": self.current_branch,
            "current_commit": self.current_commit,
            "uncommitted_changes": len(self.uncommitted_changes),
            "total_commits": len(commit_files),
            "total_snapshots": len(snapshot_files),
            "total_branches": len(branch_files),
            "storage_size_mb": total_size / (1024 * 1024),
            "recent_commits": [
                {
                    "commit_id": c.commit_id,
                    "message": c.message,
                    "author": c.author,
                    "timestamp": c.timestamp.isoformat(),
                    "changes": len(c.changes),
                }
                for c in self.get_history(5)
            ],
        }

    def export_patch(self, commit_id: str, output_file: str):
        """Export a commit as a patch file.

        Args:
            commit_id: Commit to export
            output_file: Output file path
        """
        commit = self.get_commit(commit_id)

        if not commit:
            logger.error(f"Commit {commit_id} not found")
            return

        patch = {
            "commit": commit.to_dict(),
            "format_version": "1.0",
            "exported_at": datetime.now().isoformat(),
        }

        with open(output_file, "w") as f:
            json.dump(patch, f, indent=2)

        logger.info(f"Exported commit {commit_id} to {output_file}")

    def import_patch(self, patch_file: str) -> Optional[str]:
        """Import a patch file.

        Args:
            patch_file: Path to patch file

        Returns:
            Imported commit ID or None
        """
        with open(patch_file, "r") as f:
            patch = json.load(f)

        commit_data = patch["commit"]

        # Apply changes
        for change_data in commit_data["changes"]:
            self.track_change(
                change_type=ChangeType(change_data["change_type"]),
                entity_type=change_data["entity_type"],
                entity_id=change_data["entity_id"],
                old_value=change_data["old_value"],
                new_value=change_data["new_value"],
                metadata=change_data["metadata"],
            )

        # Commit with original message
        commit_id = self.commit(
            message=f"[IMPORTED] {commit_data['message']}",
            author=commit_data["author"],
            tags=commit_data.get("tags", []) + ["imported"],
        )

        logger.info(f"Imported patch as commit {commit_id}")
        return commit_id
