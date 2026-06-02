"""Thread-safe history management for user queries and feedback."""

import json
import logging
import os
import threading
import uuid
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class QueryHistory:
    """Thread-safe manager for user query history and feedback."""

    def __init__(self, history_dir: str | None = None):
        """Initialize history manager.

        Args:
            history_dir: Directory to store history files.
                        Defaults to HISTORY_DIR env var or data/history
        """
        self.history_dir = Path(
            history_dir or os.environ.get("HISTORY_DIR", "data/history")
        )
        self.history_dir.mkdir(parents=True, exist_ok=True)

        # Thread lock for file operations
        self._lock = threading.Lock()

        # In-memory cache for current session
        self._session_cache: dict[str, list[dict[str, Any]]] = defaultdict(list)

        logger.info(f"History manager initialized with directory: {self.history_dir}")

    def _get_user_file(self, user_id: str) -> Path:
        """Get the history file path for a user."""
        return self.history_dir / f"user_{user_id}_history.json"

    def _load_user_history_unlocked(self, user_id: str) -> list[dict[str, Any]]:
        """Load history for a user from disk without locking.

        Internal method - assumes caller holds the lock.

        Returns:
            List of query records, newest first
        """
        file_path = self._get_user_file(user_id)

        if not file_path.exists():
            return []

        try:
            with open(file_path) as f:
                data = json.load(f)
                # Ensure it's a list
                if isinstance(data, list):
                    return data
                else:
                    logger.warning(f"Invalid history format for user {user_id}")
                    return []
        except (OSError, json.JSONDecodeError) as e:
            logger.error(f"Error loading history for user {user_id}: {e}")
            # Backup corrupted file
            backup_path = file_path.with_suffix(".json.corrupted")
            try:
                file_path.rename(backup_path)
                logger.info(f"Backed up corrupted history to {backup_path}")
            except Exception:
                pass
            return []

    def _load_user_history(self, user_id: str) -> list[dict[str, Any]]:
        """Load history for a user from disk.

        Returns:
            List of query records, newest first
        """
        with self._lock:
            return self._load_user_history_unlocked(user_id)

    def _save_user_history_unlocked(
        self, user_id: str, history: list[dict[str, Any]]
    ) -> bool:
        """Save history for a user to disk without locking.

        Internal method - assumes caller holds the lock.

        Args:
            user_id: User identifier
            history: List of query records

        Returns:
            True if successful, False otherwise
        """
        file_path = self._get_user_file(user_id)

        try:
            # Write to temp file first
            temp_path = file_path.with_suffix(".json.tmp")
            with open(temp_path, "w") as f:
                json.dump(history, f, indent=2, default=str)
                # Ensure data is written to disk
                f.flush()
                os.fsync(f.fileno())

            # Atomic rename
            temp_path.replace(file_path)

            return True
        except Exception as e:
            logger.error(f"Error saving history for user {user_id}: {e}")
            return False

    def _save_user_history(self, user_id: str, history: list[dict[str, Any]]) -> bool:
        """Save history for a user to disk.

        Args:
            user_id: User identifier
            history: List of query records

        Returns:
            True if successful, False otherwise
        """
        with self._lock:
            return self._save_user_history_unlocked(user_id, history)

    def add_query(
        self,
        user_id: str,
        query_text: str,
        query_params: dict[str, Any],
        results: list[dict[str, Any]],
        metadata: dict[str, Any] | None = None,
    ) -> str:
        """Add a new query to user history.

        Args:
            user_id: User identifier
            query_text: The query text
            query_params: Parameters used for the query
            results: Query results
            metadata: Additional metadata

        Returns:
            Query ID for future reference
        """
        query_id = str(uuid.uuid4())
        timestamp = datetime.utcnow().isoformat()

        query_record = {
            "query_id": query_id,
            "timestamp": timestamp,
            "query_text": query_text,
            "query_params": query_params,
            "results_count": len(results),
            "results_summary": self._summarize_results(results),
            "metadata": metadata or {},
            "feedback": None,
            "feedback_timestamp": None,
        }

        # Perform the entire read-modify-write operation under lock
        with self._lock:
            # Load existing history
            history = self._load_user_history_unlocked(user_id)

            # Limit history size (keep most recent 1000 queries)
            if len(history) >= 1000:
                history = history[:999]

            # Add new query at the beginning (newest first)
            history.insert(0, query_record)

            # Save to disk
            if self._save_user_history_unlocked(user_id, history):
                # Update session cache
                self._session_cache[user_id].insert(0, query_record)
                logger.info(f"Added query {query_id} for user {user_id}")
                return query_id
            else:
                return ""

    def add_feedback(
        self, user_id: str, query_id: str, rating: int, comment: str | None = None
    ) -> bool:
        """Add feedback to a query.

        Args:
            user_id: User identifier
            query_id: Query ID to add feedback to
            rating: Rating (1-5)
            comment: Optional feedback comment

        Returns:
            True if successful, False otherwise
        """
        if not 1 <= rating <= 5:
            logger.warning(f"Invalid rating {rating} for query {query_id}")
            return False

        history = self._load_user_history(user_id)

        # Find the query
        for record in history:
            if record.get("query_id") == query_id:
                # Update feedback
                record["feedback"] = {"rating": rating, "comment": comment}
                record["feedback_timestamp"] = datetime.utcnow().isoformat()

                # Save updated history
                if self._save_user_history(user_id, history):
                    # Update cache
                    for cached in self._session_cache[user_id]:
                        if cached.get("query_id") == query_id:
                            cached["feedback"] = record["feedback"]
                            cached["feedback_timestamp"] = record["feedback_timestamp"]
                            break

                    logger.info(
                        f"Added feedback to query {query_id} for user {user_id}"
                    )
                    return True
                break

        logger.warning(f"Query {query_id} not found for user {user_id}")
        return False

    def get_user_history(
        self, user_id: str, limit: int = 50, offset: int = 0
    ) -> list[dict[str, Any]]:
        """Get query history for a user.

        Args:
            user_id: User identifier
            limit: Maximum number of queries to return
            offset: Number of queries to skip

        Returns:
            List of query records, newest first
        """
        history = self._load_user_history(user_id)
        return history[offset : offset + limit]

    def get_user_statistics(self, user_id: str) -> dict[str, Any]:
        """Get statistics for a user's query history.

        Args:
            user_id: User identifier

        Returns:
            Dictionary with user statistics
        """
        history = self._load_user_history(user_id)

        if not history:
            return {
                "total_queries": 0,
                "queries_with_feedback": 0,
                "average_rating": None,
                "queries_by_type": {},
                "recent_activity": [],
            }

        # Calculate statistics
        total_queries = len(history)
        queries_with_feedback = sum(1 for q in history if q.get("feedback"))

        # Average rating
        ratings = [
            q["feedback"]["rating"]
            for q in history
            if q.get("feedback") and q["feedback"].get("rating")
        ]
        avg_rating = sum(ratings) / len(ratings) if ratings else None

        # Queries by type (based on query_params)
        queries_by_type = defaultdict(int)
        for q in history:
            query_type = q.get("query_params", {}).get("retrieval_mode", "unknown")
            queries_by_type[query_type] += 1

        # Recent activity (last 10 queries)
        recent_activity = [
            {
                "query_id": q["query_id"],
                "timestamp": q["timestamp"],
                "query_text": (
                    q["query_text"][:100] + "..."
                    if len(q["query_text"]) > 100
                    else q["query_text"]
                ),
                "has_feedback": bool(q.get("feedback")),
            }
            for q in history[:10]
        ]

        return {
            "total_queries": total_queries,
            "queries_with_feedback": queries_with_feedback,
            "average_rating": round(avg_rating, 2) if avg_rating else None,
            "feedback_rate": (
                round(queries_with_feedback / total_queries * 100, 1)
                if total_queries > 0
                else 0
            ),
            "queries_by_type": dict(queries_by_type),
            "recent_activity": recent_activity,
        }

    def get_global_statistics(self) -> dict[str, Any]:
        """Get global statistics across all users.

        Returns:
            Dictionary with global statistics
        """
        all_users = []
        total_queries = 0
        total_feedback = 0
        all_ratings = []

        # Scan history directory
        try:
            for file_path in self.history_dir.glob("user_*_history.json"):
                # Extract user ID from filename
                # file_path.stem gives us "user_0_history", we need just "0"
                filename = file_path.stem  # e.g., "user_0_history"
                if filename.startswith("user_") and filename.endswith("_history"):
                    user_id = filename[5:-8]  # Extract the ID part
                    all_users.append(user_id)
                else:
                    # Fallback for simpler pattern
                    parts = filename.split("_")
                    if len(parts) >= 2 and parts[0] == "user":
                        user_id = "_".join(
                            parts[1:-1]
                        )  # Handle user IDs with underscores
                        all_users.append(user_id)

                # Get user stats
                stats = self.get_user_statistics(user_id)
                total_queries += stats["total_queries"]
                total_feedback += stats["queries_with_feedback"]

                # Collect ratings
                history = self._load_user_history(user_id)
                for q in history:
                    if q.get("feedback") and q["feedback"].get("rating"):
                        all_ratings.append(q["feedback"]["rating"])

        except Exception as e:
            logger.error(f"Error calculating global statistics: {e}")

        return {
            "total_users": len(all_users),
            "total_queries": total_queries,
            "total_feedback": total_feedback,
            "average_rating": (
                round(sum(all_ratings) / len(all_ratings), 2) if all_ratings else None
            ),
            "feedback_rate": (
                round(total_feedback / total_queries * 100, 1)
                if total_queries > 0
                else 0
            ),
        }

    def _summarize_results(self, results: list[dict[str, Any]]) -> dict[str, Any]:
        """Create a summary of query results.

        Args:
            results: List of result documents

        Returns:
            Summary dictionary
        """
        if not results:
            return {"count": 0, "sources": []}

        # Count by source
        sources = defaultdict(int)
        for r in results:
            source = r.get("source", "unknown")
            sources[source] += 1

        # Get top papers (first 3)
        top_papers = []
        for r in results[:3]:
            top_papers.append(
                {
                    "id": r.get("id"),
                    "title": (
                        r.get("title", "")[:100] + "..."
                        if len(r.get("title", "")) > 100
                        else r.get("title", "")
                    ),
                }
            )

        return {
            "count": len(results),
            "sources": dict(sources),
            "top_papers": top_papers,
        }

    def clear_user_history(self, user_id: str) -> bool:
        """Clear all history for a user.

        Args:
            user_id: User identifier

        Returns:
            True if successful, False otherwise
        """
        file_path = self._get_user_file(user_id)

        try:
            with self._lock:
                if file_path.exists():
                    # Backup before deletion
                    backup_path = file_path.with_suffix(
                        f'.json.backup_{datetime.utcnow().strftime("%Y%m%d_%H%M%S")}'
                    )
                    file_path.rename(backup_path)
                    logger.info(f"Backed up and cleared history for user {user_id}")

                # Clear cache
                self._session_cache.pop(user_id, None)

            return True
        except Exception as e:
            logger.error(f"Error clearing history for user {user_id}: {e}")
            return False


# Global instance
_history_manager: QueryHistory | None = None


def get_history_manager() -> QueryHistory:
    """Get the global history manager instance."""
    global _history_manager
    if _history_manager is None:
        _history_manager = QueryHistory()
    return _history_manager
