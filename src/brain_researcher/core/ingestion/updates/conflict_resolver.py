"""Conflict resolution for incremental data updates."""

import hashlib
import json
import logging
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


class ConflictType(Enum):
    """Types of conflicts that can occur during updates."""

    VALUE_MISMATCH = "value_mismatch"
    TYPE_CHANGE = "type_change"
    SCHEMA_CHANGE = "schema_change"
    DELETION_CONFLICT = "deletion_conflict"
    DUPLICATE_KEY = "duplicate_key"
    VERSION_CONFLICT = "version_conflict"
    MERGE_CONFLICT = "merge_conflict"


class ResolutionStrategy(Enum):
    """Strategies for resolving conflicts."""

    KEEP_NEWEST = "keep_newest"
    KEEP_OLDEST = "keep_oldest"
    KEEP_LOCAL = "keep_local"
    KEEP_REMOTE = "keep_remote"
    MERGE_VALUES = "merge_values"
    MANUAL_REVIEW = "manual_review"
    USE_QUALITY_SCORE = "use_quality_score"
    VOTING_CONSENSUS = "voting_consensus"


class ConflictResolver:
    """Handles conflict resolution during data updates."""

    def __init__(
        self,
        default_strategy: ResolutionStrategy = ResolutionStrategy.KEEP_NEWEST,
        quality_threshold: float = 0.7,
    ):
        """Initialize conflict resolver.

        Args:
            default_strategy: Default resolution strategy
            quality_threshold: Minimum quality score for automatic resolution
        """
        self.default_strategy = default_strategy
        self.quality_threshold = quality_threshold
        self.conflict_history = []
        self.resolution_rules = self._initialize_rules()
        self.manual_review_queue = []

    def _initialize_rules(self) -> Dict[ConflictType, ResolutionStrategy]:
        """Initialize default resolution rules for different conflict types."""
        return {
            ConflictType.VALUE_MISMATCH: ResolutionStrategy.USE_QUALITY_SCORE,
            ConflictType.TYPE_CHANGE: ResolutionStrategy.MANUAL_REVIEW,
            ConflictType.SCHEMA_CHANGE: ResolutionStrategy.MANUAL_REVIEW,
            ConflictType.DELETION_CONFLICT: ResolutionStrategy.KEEP_LOCAL,
            ConflictType.DUPLICATE_KEY: ResolutionStrategy.KEEP_NEWEST,
            ConflictType.VERSION_CONFLICT: ResolutionStrategy.KEEP_NEWEST,
            ConflictType.MERGE_CONFLICT: ResolutionStrategy.MERGE_VALUES,
        }

    def detect_conflicts(
        self,
        local_data: Dict[str, Any],
        remote_data: Dict[str, Any],
        metadata: Optional[Dict[str, Any]] = None,
    ) -> List[Dict[str, Any]]:
        """Detect conflicts between local and remote data.

        Args:
            local_data: Current local data
            remote_data: Incoming remote data
            metadata: Additional metadata for conflict detection

        Returns:
            List of detected conflicts
        """
        conflicts = []

        # Check for value mismatches
        for key in set(local_data.keys()) & set(remote_data.keys()):
            local_value = local_data[key]
            remote_value = remote_data[key]

            if local_value != remote_value:
                conflict = self._analyze_conflict(
                    key, local_value, remote_value, metadata
                )
                if conflict:
                    conflicts.append(conflict)

        # Check for schema changes
        local_keys = set(local_data.keys())
        remote_keys = set(remote_data.keys())

        if local_keys != remote_keys:
            conflicts.append(
                {
                    "type": ConflictType.SCHEMA_CHANGE,
                    "local_keys": list(local_keys),
                    "remote_keys": list(remote_keys),
                    "added_keys": list(remote_keys - local_keys),
                    "removed_keys": list(local_keys - remote_keys),
                    "timestamp": datetime.now().isoformat(),
                }
            )

        # Check for version conflicts if metadata provided
        if metadata:
            version_conflict = self._check_version_conflict(metadata)
            if version_conflict:
                conflicts.append(version_conflict)

        logger.info(f"Detected {len(conflicts)} conflicts")
        return conflicts

    def resolve_conflicts(
        self,
        conflicts: List[Dict[str, Any]],
        strategy: Optional[ResolutionStrategy] = None,
    ) -> Dict[str, Any]:
        """Resolve detected conflicts.

        Args:
            conflicts: List of conflicts to resolve
            strategy: Resolution strategy to use (None = use rules)

        Returns:
            Resolution results
        """
        resolution_results = {
            "resolved": [],
            "manual_review": [],
            "failed": [],
            "statistics": {},
        }

        for conflict in conflicts:
            conflict_type = conflict.get("type", ConflictType.VALUE_MISMATCH)

            # Determine resolution strategy
            if strategy:
                resolution_strategy = strategy
            else:
                resolution_strategy = self.resolution_rules.get(
                    conflict_type, self.default_strategy
                )

            # Apply resolution
            try:
                resolution = self._apply_resolution(conflict, resolution_strategy)

                if resolution["status"] == "resolved":
                    resolution_results["resolved"].append(resolution)
                elif resolution["status"] == "manual_review":
                    resolution_results["manual_review"].append(resolution)
                    self.manual_review_queue.append(conflict)
                else:
                    resolution_results["failed"].append(resolution)

            except Exception as e:
                logger.error(f"Failed to resolve conflict: {e}")
                resolution_results["failed"].append(
                    {"conflict": conflict, "error": str(e)}
                )

        # Calculate statistics
        resolution_results["statistics"] = {
            "total_conflicts": len(conflicts),
            "resolved": len(resolution_results["resolved"]),
            "manual_review": len(resolution_results["manual_review"]),
            "failed": len(resolution_results["failed"]),
            "resolution_rate": (
                len(resolution_results["resolved"]) / len(conflicts) if conflicts else 0
            ),
        }

        # Store in history
        self.conflict_history.append(
            {"timestamp": datetime.now().isoformat(), "results": resolution_results}
        )

        logger.info(
            f"Resolved {resolution_results['statistics']['resolved']} of {len(conflicts)} conflicts"
        )
        return resolution_results

    def merge_data(
        self,
        local_data: Dict[str, Any],
        remote_data: Dict[str, Any],
        resolution_results: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Merge data based on conflict resolution results.

        Args:
            local_data: Current local data
            remote_data: Incoming remote data
            resolution_results: Results from conflict resolution

        Returns:
            Merged data
        """
        merged_data = local_data.copy()

        # Apply resolved conflicts
        for resolution in resolution_results.get("resolved", []):
            key = resolution.get("key")
            value = resolution.get("resolved_value")

            if key and value is not None:
                merged_data[key] = value

        # Add new keys from remote data
        for key in set(remote_data.keys()) - set(local_data.keys()):
            merged_data[key] = remote_data[key]

        # Add merge metadata
        merged_data["_merge_metadata"] = {
            "timestamp": datetime.now().isoformat(),
            "conflicts_resolved": resolution_results["statistics"]["resolved"],
            "conflicts_pending": resolution_results["statistics"]["manual_review"],
            "source": "incremental_update",
        }

        return merged_data

    def rollback_changes(self, data: Dict[str, Any], checkpoint: str) -> Dict[str, Any]:
        """Rollback changes to a previous checkpoint.

        Args:
            data: Current data
            checkpoint: Checkpoint identifier to rollback to

        Returns:
            Data at the specified checkpoint
        """
        # In a real implementation, this would restore from versioned storage
        logger.info(f"Rolling back to checkpoint: {checkpoint}")

        # For demo, return data with rollback metadata
        return {
            **data,
            "_rollback_metadata": {
                "checkpoint": checkpoint,
                "timestamp": datetime.now().isoformat(),
                "reason": "manual_rollback",
            },
        }

    def validate_resolution(
        self, original_data: Dict[str, Any], resolved_data: Dict[str, Any]
    ) -> bool:
        """Validate that resolution maintains data integrity.

        Args:
            original_data: Original data before resolution
            resolved_data: Data after resolution

        Returns:
            True if resolution is valid
        """
        # Check data integrity
        if not resolved_data:
            return False

        # Check for data loss
        original_keys = set(original_data.keys())
        resolved_keys = set(resolved_data.keys())

        if len(resolved_keys) < len(original_keys) * 0.9:
            logger.warning("Significant data loss detected in resolution")
            return False

        # Check for type consistency
        for key in original_keys & resolved_keys:
            if type(original_data[key]) != type(resolved_data[key]):
                if not self._is_compatible_type_change(
                    type(original_data[key]), type(resolved_data[key])
                ):
                    logger.warning(f"Incompatible type change for key {key}")
                    return False

        return True

    def get_manual_review_queue(self) -> List[Dict[str, Any]]:
        """Get conflicts requiring manual review.

        Returns:
            List of conflicts needing manual intervention
        """
        return self.manual_review_queue.copy()

    def resolve_manual_conflict(
        self, conflict_id: str, resolution: Dict[str, Any]
    ) -> bool:
        """Manually resolve a conflict.

        Args:
            conflict_id: Identifier of the conflict
            resolution: Manual resolution details

        Returns:
            True if resolution was successful
        """
        # Find and remove from queue
        for i, conflict in enumerate(self.manual_review_queue):
            if conflict.get("id") == conflict_id:
                self.manual_review_queue.pop(i)

                # Store resolution
                self.conflict_history.append(
                    {
                        "timestamp": datetime.now().isoformat(),
                        "conflict_id": conflict_id,
                        "resolution": resolution,
                        "type": "manual_resolution",
                    }
                )

                logger.info(f"Manually resolved conflict: {conflict_id}")
                return True

        return False

    def get_conflict_statistics(self) -> Dict[str, Any]:
        """Get statistics about conflict resolution.

        Returns:
            Conflict resolution statistics
        """
        stats = {
            "total_conflicts": 0,
            "resolved_automatically": 0,
            "resolved_manually": 0,
            "pending_review": len(self.manual_review_queue),
            "conflict_types": {},
            "resolution_strategies": {},
            "success_rate": 0.0,
        }

        # Aggregate from history
        for entry in self.conflict_history:
            if "results" in entry:
                results = entry["results"]
                stats["total_conflicts"] += results["statistics"]["total_conflicts"]
                stats["resolved_automatically"] += results["statistics"]["resolved"]
            elif entry.get("type") == "manual_resolution":
                stats["resolved_manually"] += 1

        # Calculate success rate
        total_resolved = stats["resolved_automatically"] + stats["resolved_manually"]
        if stats["total_conflicts"] > 0:
            stats["success_rate"] = total_resolved / stats["total_conflicts"]

        return stats

    # Private helper methods

    def _analyze_conflict(
        self,
        key: str,
        local_value: Any,
        remote_value: Any,
        metadata: Optional[Dict[str, Any]],
    ) -> Optional[Dict[str, Any]]:
        """Analyze a specific conflict."""
        # Skip if values are equivalent
        if self._values_equivalent(local_value, remote_value):
            return None

        conflict = {
            "id": self._generate_conflict_id(key, local_value, remote_value),
            "key": key,
            "local_value": local_value,
            "remote_value": remote_value,
            "timestamp": datetime.now().isoformat(),
        }

        # Determine conflict type
        if type(local_value) != type(remote_value):
            conflict["type"] = ConflictType.TYPE_CHANGE
        else:
            conflict["type"] = ConflictType.VALUE_MISMATCH

        # Add metadata if available
        if metadata:
            conflict["metadata"] = metadata

        return conflict

    def _check_version_conflict(
        self, metadata: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        """Check for version conflicts."""
        local_version = metadata.get("local_version")
        remote_version = metadata.get("remote_version")

        if local_version and remote_version:
            if local_version != remote_version:
                return {
                    "type": ConflictType.VERSION_CONFLICT,
                    "local_version": local_version,
                    "remote_version": remote_version,
                    "timestamp": datetime.now().isoformat(),
                }

        return None

    def _apply_resolution(
        self, conflict: Dict[str, Any], strategy: ResolutionStrategy
    ) -> Dict[str, Any]:
        """Apply resolution strategy to a conflict."""
        resolution = {
            "conflict_id": conflict.get("id"),
            "strategy": strategy,
            "timestamp": datetime.now().isoformat(),
        }

        if strategy == ResolutionStrategy.KEEP_NEWEST:
            # Use timestamp comparison if available
            resolution["resolved_value"] = self._get_newest_value(conflict)
            resolution["status"] = "resolved"

        elif strategy == ResolutionStrategy.KEEP_LOCAL:
            resolution["resolved_value"] = conflict.get("local_value")
            resolution["status"] = "resolved"

        elif strategy == ResolutionStrategy.KEEP_REMOTE:
            resolution["resolved_value"] = conflict.get("remote_value")
            resolution["status"] = "resolved"

        elif strategy == ResolutionStrategy.MERGE_VALUES:
            merged = self._merge_values(
                conflict.get("local_value"), conflict.get("remote_value")
            )
            if merged is not None:
                resolution["resolved_value"] = merged
                resolution["status"] = "resolved"
            else:
                resolution["status"] = "manual_review"

        elif strategy == ResolutionStrategy.USE_QUALITY_SCORE:
            best_value = self._select_by_quality(conflict)
            if best_value is not None:
                resolution["resolved_value"] = best_value
                resolution["status"] = "resolved"
            else:
                resolution["status"] = "manual_review"

        elif strategy == ResolutionStrategy.MANUAL_REVIEW:
            resolution["status"] = "manual_review"

        else:
            resolution["status"] = "failed"
            resolution["error"] = f"Unknown strategy: {strategy}"

        resolution["key"] = conflict.get("key")
        return resolution

    def _values_equivalent(self, value1: Any, value2: Any) -> bool:
        """Check if two values are equivalent."""
        # Handle None values
        if value1 is None or value2 is None:
            return value1 == value2

        # Handle numeric comparisons with tolerance
        if isinstance(value1, (int, float)) and isinstance(value2, (int, float)):
            return abs(value1 - value2) <= 1e-9

        # Handle pandas DataFrames
        if isinstance(value1, pd.DataFrame) and isinstance(value2, pd.DataFrame):
            return value1.equals(value2)

        # Handle numpy arrays
        if isinstance(value1, np.ndarray) and isinstance(value2, np.ndarray):
            return np.array_equal(value1, value2)

        # Default comparison
        return value1 == value2

    def _generate_conflict_id(
        self, key: str, local_value: Any, remote_value: Any
    ) -> str:
        """Generate unique conflict ID."""
        content = (
            f"{key}:{str(local_value)}:{str(remote_value)}:{datetime.now().isoformat()}"
        )
        return hashlib.md5(content.encode()).hexdigest()

    def _get_newest_value(self, conflict: Dict[str, Any]) -> Any:
        """Get the newest value based on timestamps."""
        metadata = conflict.get("metadata", {})

        local_timestamp = metadata.get("local_timestamp")
        remote_timestamp = metadata.get("remote_timestamp")

        if local_timestamp and remote_timestamp:
            if local_timestamp > remote_timestamp:
                return conflict.get("local_value")
            else:
                return conflict.get("remote_value")

        # Default to remote if no timestamps
        return conflict.get("remote_value")

    def _merge_values(self, local_value: Any, remote_value: Any) -> Optional[Any]:
        """Attempt to merge two values."""
        # Merge dictionaries
        if isinstance(local_value, dict) and isinstance(remote_value, dict):
            merged = local_value.copy()
            merged.update(remote_value)
            return merged

        # Merge lists (union)
        if isinstance(local_value, list) and isinstance(remote_value, list):
            return list(set(local_value + remote_value))

        # Cannot merge
        return None

    def _select_by_quality(self, conflict: Dict[str, Any]) -> Optional[Any]:
        """Select value based on quality scores."""
        metadata = conflict.get("metadata", {})

        local_quality = metadata.get("local_quality", 0.5)
        remote_quality = metadata.get("remote_quality", 0.5)

        diff = abs(local_quality - remote_quality)
        if diff < 0.05:
            return None

        # Auto-resolve when at least one value meets the quality threshold
        if max(local_quality, remote_quality) >= self.quality_threshold:
            if local_quality >= remote_quality:
                return conflict.get("local_value")
            return conflict.get("remote_value")

        # Cannot determine based on quality
        return None

    def _is_compatible_type_change(self, type1: type, type2: type) -> bool:
        """Check if type change is compatible."""
        compatible_changes = [
            (int, float),
            (float, int),
            (str, bytes),
            (bytes, str),
            (list, tuple),
            (tuple, list),
        ]

        return (type1, type2) in compatible_changes or (
            type2,
            type1,
        ) in compatible_changes
