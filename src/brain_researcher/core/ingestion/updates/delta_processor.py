"""Process only changed data for efficient updates.

Handles insertions, updates, and deletions based on change detection.
"""

import logging
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


class ChangeType(Enum):
    """Type of change detected."""

    INSERT = "insert"
    UPDATE = "update"
    DELETE = "delete"
    UNCHANGED = "unchanged"


class DeltaProcessor:
    """Process delta changes efficiently."""

    def __init__(self, merge_strategy: str = "overwrite", track_deletes: bool = True):
        """Initialize delta processor.

        Args:
            merge_strategy: How to handle updates ("overwrite", "merge", "custom")
            track_deletes: Whether to track and process deletions
        """
        self.merge_strategy = merge_strategy
        self.track_deletes = track_deletes

        # Statistics
        self.stats = {
            "inserts": 0,
            "updates": 0,
            "deletes": 0,
            "unchanged": 0,
            "conflicts": 0,
            "errors": [],
        }

    def categorize_changes(
        self,
        current: List[Tuple[str, Dict[str, Any]]],
        previous: List[Tuple[str, Dict[str, Any]]],
    ) -> Dict[ChangeType, List[Tuple[str, Dict[str, Any]]]]:
        """Categorize changes between current and previous data.

        Args:
            current: Current data as (id, content) tuples
            previous: Previous data as (id, content) tuples

        Returns:
            Dictionary mapping change types to affected items
        """
        current_dict = {item_id: content for item_id, content in current}
        previous_dict = {item_id: content for item_id, content in previous}

        current_ids = set(current_dict.keys())
        previous_ids = set(previous_dict.keys())

        changes = {
            ChangeType.INSERT: [],
            ChangeType.UPDATE: [],
            ChangeType.DELETE: [],
            ChangeType.UNCHANGED: [],
        }

        # Find inserts (new items)
        for item_id in current_ids - previous_ids:
            changes[ChangeType.INSERT].append((item_id, current_dict[item_id]))
            self.stats["inserts"] += 1

        # Find updates and unchanged
        for item_id in current_ids & previous_ids:
            if current_dict[item_id] != previous_dict[item_id]:
                changes[ChangeType.UPDATE].append((item_id, current_dict[item_id]))
                self.stats["updates"] += 1
            else:
                changes[ChangeType.UNCHANGED].append((item_id, current_dict[item_id]))
                self.stats["unchanged"] += 1

        # Find deletes
        if self.track_deletes:
            for item_id in previous_ids - current_ids:
                changes[ChangeType.DELETE].append((item_id, previous_dict[item_id]))
                self.stats["deletes"] += 1

        return changes

    def merge_updates(
        self,
        old_content: Dict[str, Any],
        new_content: Dict[str, Any],
        custom_merger: Optional[Callable] = None,
    ) -> Dict[str, Any]:
        """Merge old and new content based on strategy.

        Args:
            old_content: Existing content
            new_content: New content
            custom_merger: Optional custom merge function

        Returns:
            Merged content
        """
        if self.merge_strategy == "overwrite":
            return new_content

        elif self.merge_strategy == "merge":
            # Deep merge: new values override old, but keep old keys not in new
            merged = old_content.copy()
            merged.update(new_content)
            return merged

        elif self.merge_strategy == "custom" and custom_merger:
            return custom_merger(old_content, new_content)

        else:
            # Default to overwrite
            return new_content

    def process_delta(
        self,
        changes: Dict[ChangeType, List[Tuple[str, Dict[str, Any]]]],
        insert_handler: Optional[Callable] = None,
        update_handler: Optional[Callable] = None,
        delete_handler: Optional[Callable] = None,
    ) -> Dict[str, Any]:
        """Process delta changes with appropriate handlers.

        Args:
            changes: Categorized changes
            insert_handler: Function to handle inserts
            update_handler: Function to handle updates
            delete_handler: Function to handle deletes

        Returns:
            Processing results
        """
        results = {
            "processed": {
                "inserts": 0,
                "updates": 0,
                "deletes": 0,
            },
            "failed": {
                "inserts": [],
                "updates": [],
                "deletes": [],
            },
        }

        # Process inserts
        if insert_handler and ChangeType.INSERT in changes:
            for item_id, content in changes[ChangeType.INSERT]:
                try:
                    insert_handler(item_id, content)
                    results["processed"]["inserts"] += 1
                except Exception as e:
                    logger.error(f"Failed to insert {item_id}: {e}")
                    results["failed"]["inserts"].append((item_id, str(e)))
                    self.stats["errors"].append(f"Insert {item_id}: {e}")

        # Process updates
        if update_handler and ChangeType.UPDATE in changes:
            for item_id, content in changes[ChangeType.UPDATE]:
                try:
                    update_handler(item_id, content)
                    results["processed"]["updates"] += 1
                except Exception as e:
                    logger.error(f"Failed to update {item_id}: {e}")
                    results["failed"]["updates"].append((item_id, str(e)))
                    self.stats["errors"].append(f"Update {item_id}: {e}")

        # Process deletes
        if delete_handler and self.track_deletes and ChangeType.DELETE in changes:
            for item_id, content in changes[ChangeType.DELETE]:
                try:
                    delete_handler(item_id, content)
                    results["processed"]["deletes"] += 1
                except Exception as e:
                    logger.error(f"Failed to delete {item_id}: {e}")
                    results["failed"]["deletes"].append((item_id, str(e)))
                    self.stats["errors"].append(f"Delete {item_id}: {e}")

        return results

    def process_batch_delta(
        self,
        source: str,
        current_items: List[Tuple[str, Dict[str, Any]]],
        get_previous: Callable[[str], List[Tuple[str, Dict[str, Any]]]],
        handlers: Dict[str, Callable],
    ) -> Dict[str, Any]:
        """Process a batch of items with delta detection.

        Args:
            source: Data source name
            current_items: Current items
            get_previous: Function to get previous items
            handlers: Dictionary of handlers for each change type

        Returns:
            Processing results
        """
        logger.info(f"Processing delta for {source} ({len(current_items)} items)")

        # Get previous state
        previous_items = get_previous(source)

        # Categorize changes
        changes = self.categorize_changes(current_items, previous_items)

        # Log summary
        logger.info(
            f"{source} changes: "
            f"{len(changes[ChangeType.INSERT])} inserts, "
            f"{len(changes[ChangeType.UPDATE])} updates, "
            f"{len(changes[ChangeType.DELETE])} deletes"
        )

        # Process changes
        results = self.process_delta(
            changes,
            handlers.get("insert"),
            handlers.get("update"),
            handlers.get("delete"),
        )

        return {
            "source": source,
            "total_items": len(current_items),
            "changes": {
                "inserts": len(changes[ChangeType.INSERT]),
                "updates": len(changes[ChangeType.UPDATE]),
                "deletes": len(changes[ChangeType.DELETE]),
                "unchanged": len(changes[ChangeType.UNCHANGED]),
            },
            "results": results,
            "stats": self.get_statistics(),
        }

    def resolve_conflicts(
        self, conflicts: List[Dict[str, Any]], resolution_strategy: str = "newest"
    ) -> List[Dict[str, Any]]:
        """Resolve conflicts between concurrent updates.

        Args:
            conflicts: List of conflicting updates
            resolution_strategy: How to resolve ("newest", "merge", "manual")

        Returns:
            Resolved updates
        """
        resolved = []

        for conflict in conflicts:
            if resolution_strategy == "newest":
                # Take the most recent update
                resolved.append(
                    max(conflict["versions"], key=lambda x: x.get("timestamp", ""))
                )

            elif resolution_strategy == "merge":
                # Merge all versions
                merged = {}
                for version in conflict["versions"]:
                    merged.update(version)
                resolved.append(merged)

            else:
                # Manual resolution needed
                logger.warning(f"Conflict requires manual resolution: {conflict['id']}")
                self.stats["conflicts"] += 1

        return resolved

    def get_statistics(self) -> Dict[str, Any]:
        """Get processing statistics.

        Returns:
            Statistics dictionary
        """
        stats = dict(self.stats)

        # Calculate rates
        total = sum(
            [stats["inserts"], stats["updates"], stats["deletes"], stats["unchanged"]]
        )

        if total > 0:
            stats["change_rate"] = (
                stats["inserts"] + stats["updates"] + stats["deletes"]
            ) / total
        else:
            stats["change_rate"] = 0

        return stats

    def reset_statistics(self):
        """Reset processing statistics."""
        self.stats = {
            "inserts": 0,
            "updates": 0,
            "deletes": 0,
            "unchanged": 0,
            "conflicts": 0,
            "errors": [],
        }
