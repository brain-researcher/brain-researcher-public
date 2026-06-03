"""Change detection for incremental updates.

Uses hashing and timestamps to detect changes in data sources.
"""

import hashlib
import json
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

try:
    import orjson

    HAS_ORJSON = True
except ImportError:
    HAS_ORJSON = False

logger = logging.getLogger(__name__)


def stable_hash(obj: dict[str, Any]) -> str:
    """Create a stable hash for a dictionary.

    Args:
        obj: Dictionary to hash

    Returns:
        Hex digest of SHA256 hash
    """
    if HAS_ORJSON:
        # orjson sorts keys by default
        serialized = orjson.dumps(obj, option=orjson.OPT_SORT_KEYS)
    else:
        serialized = json.dumps(obj, sort_keys=True, separators=(",", ":")).encode()

    return hashlib.sha256(serialized).hexdigest()


class ChangeDetector:
    """Detect changes in data sources for incremental updates."""

    def __init__(
        self,
        state_file: str | Path | None = "artifacts/change_state.json",
        ttl_days: int = 30,
    ):
        """Initialize change detector.

        Args:
            state_file: Path to store state between runs
            ttl_days: Time to live for hash entries
        """
        self.state_file = Path(state_file) if state_file else None
        self.ttl_days = ttl_days

        # State: source -> item_id -> (hash, timestamp)
        self.state: dict[str, dict[str, tuple[str, str]]] = {}

        # Load existing state
        if self.state_file:
            self.load_state()

    def load_state(self):
        """Load state from file."""
        if not self.state_file or not self.state_file.exists():
            return

        try:
            with open(self.state_file) as f:
                data = json.load(f)
                self.state = data.get("state", {})

            logger.info(f"Loaded change state with {len(self.state)} sources")

            # Clean old entries
            self.cleanup_old_entries()

        except Exception as e:
            logger.warning(f"Failed to load state: {e}")

    def save_state(self):
        """Save state to file."""
        if not self.state_file:
            return

        try:
            self.state_file.parent.mkdir(parents=True, exist_ok=True)

            with open(self.state_file, "w") as f:
                json.dump(
                    {
                        "state": self.state,
                        "updated": datetime.now().isoformat(),
                    },
                    f,
                    indent=2,
                )

            logger.debug(f"Saved change state for {len(self.state)} sources")

        except Exception as e:
            logger.error(f"Failed to save state: {e}")

    def cleanup_old_entries(self):
        """Remove entries older than TTL."""
        if self.ttl_days <= 0:
            return

        cutoff = datetime.now() - timedelta(days=self.ttl_days)
        cutoff_str = cutoff.isoformat()

        for source in self.state:
            old_items = [
                item_id
                for item_id, (_, timestamp) in self.state[source].items()
                if timestamp < cutoff_str
            ]

            for item_id in old_items:
                del self.state[source][item_id]

            if old_items:
                logger.debug(f"Cleaned {len(old_items)} old entries from {source}")

    def has_changed(self, source: str, item_id: str, content: dict[str, Any]) -> bool:
        """Check if an item has changed.

        Args:
            source: Data source name
            item_id: Unique item identifier
            content: Current item content

        Returns:
            True if changed or new
        """
        current_hash = stable_hash(content)

        # Check if we've seen this item
        if source in self.state and item_id in self.state[source]:
            stored_hash, _ = self.state[source][item_id]
            return current_hash != stored_hash

        # New item
        return True

    def update(self, source: str, item_id: str, content: dict[str, Any]):
        """Update the hash for an item.

        Args:
            source: Data source name
            item_id: Unique item identifier
            content: Current item content
        """
        if source not in self.state:
            self.state[source] = {}

        current_hash = stable_hash(content)
        timestamp = datetime.now().isoformat()

        self.state[source][item_id] = (current_hash, timestamp)

    def detect_changes(
        self, source: str, items: list[tuple[str, dict[str, Any]]]
    ) -> tuple[list[tuple[str, dict[str, Any]]], list[str], list[str]]:
        """Detect changes in a batch of items.

        Args:
            source: Data source name
            items: List of (item_id, content) tuples

        Returns:
            Tuple of (changed_items, new_ids, deleted_ids)
        """
        changed_items = []
        new_ids = []
        current_ids = set()

        for item_id, content in items:
            current_ids.add(item_id)

            if self.has_changed(source, item_id, content):
                changed_items.append((item_id, content))

                # Check if new
                if source not in self.state or item_id not in self.state[source]:
                    new_ids.append(item_id)

        # Find deleted items
        deleted_ids = []
        if source in self.state:
            stored_ids = set(self.state[source].keys())
            deleted_ids = list(stored_ids - current_ids)

        logger.info(
            f"{source}: {len(changed_items)} changed "
            f"({len(new_ids)} new, {len(deleted_ids)} deleted)"
        )

        return changed_items, new_ids, deleted_ids

    def update_batch(self, source: str, items: list[tuple[str, dict[str, Any]]]):
        """Update hashes for a batch of items.

        Args:
            source: Data source name
            items: List of (item_id, content) tuples
        """
        for item_id, content in items:
            self.update(source, item_id, content)

    def get_source_stats(self, source: str) -> dict[str, Any]:
        """Get statistics for a source.

        Args:
            source: Data source name

        Returns:
            Statistics dictionary
        """
        if source not in self.state:
            return {"items": 0, "oldest": None, "newest": None}

        items = self.state[source]

        if not items:
            return {"items": 0, "oldest": None, "newest": None}

        timestamps = [timestamp for _, timestamp in items.values()]

        return {
            "items": len(items),
            "oldest": min(timestamps),
            "newest": max(timestamps),
        }

    def get_all_stats(self) -> dict[str, Any]:
        """Get statistics for all sources.

        Returns:
            Statistics dictionary
        """
        stats = {}

        for source in self.state:
            stats[source] = self.get_source_stats(source)

        stats["total_items"] = sum(s["items"] for s in stats.values())
        stats["sources"] = list(self.state.keys())

        return stats


class ETagTracker:
    """Track ETags for HTTP resources."""

    def __init__(self, cache_file: str | Path | None = "artifacts/etags.json"):
        """Initialize ETag tracker.

        Args:
            cache_file: Path to store ETags
        """
        self.cache_file = Path(cache_file) if cache_file else None
        self.etags: dict[str, str] = {}

        if self.cache_file:
            self.load_etags()

    def load_etags(self):
        """Load ETags from file."""
        if not self.cache_file or not self.cache_file.exists():
            return

        try:
            with open(self.cache_file) as f:
                self.etags = json.load(f)
            logger.debug(f"Loaded {len(self.etags)} ETags")
        except Exception as e:
            logger.warning(f"Failed to load ETags: {e}")

    def save_etags(self):
        """Save ETags to file."""
        if not self.cache_file:
            return

        try:
            self.cache_file.parent.mkdir(parents=True, exist_ok=True)
            with open(self.cache_file, "w") as f:
                json.dump(self.etags, f, indent=2)
        except Exception as e:
            logger.error(f"Failed to save ETags: {e}")

    def get_etag(self, url: str) -> str | None:
        """Get stored ETag for URL.

        Args:
            url: Resource URL

        Returns:
            ETag string or None
        """
        return self.etags.get(url)

    def update_etag(self, url: str, etag: str):
        """Update ETag for URL.

        Args:
            url: Resource URL
            etag: New ETag value
        """
        self.etags[url] = etag

    def has_changed(self, url: str, new_etag: str) -> bool:
        """Check if resource has changed based on ETag.

        Args:
            url: Resource URL
            new_etag: Current ETag from server

        Returns:
            True if changed or new
        """
        old_etag = self.etags.get(url)
        return old_etag != new_etag
