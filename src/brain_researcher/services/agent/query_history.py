"""
Query History Management for Brain Researcher Agent (AGENT-022)

This module implements query history tracking, pattern analysis, and user profile
management for the recommendation system.
"""

import json
import logging
import pickle
import time
from collections import defaultdict, deque
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Set, Tuple

import redis

logger = logging.getLogger(__name__)


@dataclass
class QueryExecution:
    """Represents a single query execution record."""

    query_id: str
    user_id: Optional[str]
    query: str
    timestamp: datetime
    execution_time: float
    success: bool
    error_message: Optional[str] = None
    tools_used: List[str] = field(default_factory=list)
    parameters: Dict[str, Any] = field(default_factory=dict)
    results_summary: Dict[str, Any] = field(default_factory=dict)
    session_id: Optional[str] = None
    domain: Optional[str] = None
    intent: Optional[str] = None
    complexity_score: float = 0.0


@dataclass
class QuerySession:
    """Represents a user session with multiple queries."""

    session_id: str
    user_id: Optional[str]
    start_time: datetime
    end_time: Optional[datetime] = None
    queries: List[str] = field(default_factory=list)
    total_execution_time: float = 0.0
    success_rate: float = 0.0
    domains_explored: Set[str] = field(default_factory=set)


class QueryHistoryStore:
    """
    Stores and retrieves query history using Redis backend.

    Features:
    - Store query history in Redis with TTL
    - Track query patterns and user sessions
    - Maintain user profiles
    - Provide fast query retrieval
    """

    def __init__(
        self,
        redis_client: Optional[redis.Redis] = None,
        ttl_days: int = 30,
        namespace: str = "query_history"
    ):
        """
        Initialize the query history store.

        Args:
            redis_client: Redis client instance
            ttl_days: Time to live for stored queries in days
            namespace: Namespace prefix for Redis keys
        """
        self.namespace = namespace
        self.ttl_seconds = ttl_days * 24 * 3600

        # Initialize Redis client
        if redis_client:
            self.redis = redis_client
        else:
            self.redis = self._create_redis_client()

        # In-memory cache for recent queries
        self.recent_cache: deque = deque(maxlen=100)
        self.session_cache: Dict[str, QuerySession] = {}

        logger.info("Query History Store initialized")

    def _create_redis_client(self) -> redis.Redis:
        """Create Redis client with fallback to fakeredis."""
        try:
            import os
            redis_url = os.getenv('REDIS_URL', 'redis://localhost:6379/1')
            client = redis.from_url(redis_url, decode_responses=False)

            # Test connection
            client.ping()
            logger.info(f"Connected to Redis for query history at {redis_url}")

            return client

        except Exception as e:
            logger.warning(f"Failed to connect to Redis: {e}, using fakeredis")

            try:
                import fakeredis
                return fakeredis.FakeRedis(decode_responses=False)
            except ImportError:
                raise Exception("Neither Redis nor fakeredis available")

    def store_query_execution(self, execution: QueryExecution):
        """
        Store a query execution record.

        Args:
            execution: Query execution to store
        """
        try:
            # Store in Redis with multiple keys for different access patterns

            # 1. Store full execution record
            exec_key = f"{self.namespace}:execution:{execution.query_id}"
            exec_data = pickle.dumps(execution)
            self.redis.setex(exec_key, self.ttl_seconds, exec_data)

            # 2. Add to user's query list
            if execution.user_id:
                user_key = f"{self.namespace}:user:{execution.user_id}"
                self.redis.lpush(user_key, execution.query_id)
                self.redis.expire(user_key, self.ttl_seconds)

            # 3. Add to global recent queries
            recent_key = f"{self.namespace}:recent"
            query_record = {
                "query_id": execution.query_id,
                "query": execution.query,
                "timestamp": execution.timestamp.isoformat(),
                "user_id": execution.user_id,
                "success": execution.success
            }
            self.redis.lpush(recent_key, json.dumps(query_record))
            self.redis.ltrim(recent_key, 0, 999)  # Keep last 1000

            # 4. Add to domain-specific queries
            if execution.domain:
                domain_key = f"{self.namespace}:domain:{execution.domain}"
                self.redis.lpush(domain_key, execution.query_id)
                self.redis.expire(domain_key, self.ttl_seconds)

            # 5. Add to time-based indexes
            date_key = f"{self.namespace}:date:{execution.timestamp.strftime('%Y-%m-%d')}"
            self.redis.lpush(date_key, execution.query_id)
            self.redis.expire(date_key, self.ttl_seconds)

            # 6. Update session tracking
            if execution.session_id:
                self._update_session(execution)

            # 7. Add to in-memory cache
            self.recent_cache.appendleft(execution)

            logger.debug(f"Stored query execution: {execution.query_id}")

        except Exception as e:
            logger.error(f"Failed to store query execution: {e}")

    def _update_session(self, execution: QueryExecution):
        """Update session information with new query execution."""
        if not execution.session_id:
            return

        session_key = f"{self.namespace}:session:{execution.session_id}"

        try:
            # Get existing session or create new one
            session_data = self.redis.get(session_key)
            if session_data:
                session = pickle.loads(session_data)
            else:
                session = QuerySession(
                    session_id=execution.session_id,
                    user_id=execution.user_id,
                    start_time=execution.timestamp
                )

            # Update session
            session.queries.append(execution.query_id)
            session.end_time = execution.timestamp
            session.total_execution_time += execution.execution_time

            if execution.domain:
                session.domains_explored.add(execution.domain)

            # Calculate success rate
            success_count = sum(1 for q_id in session.queries
                              if self._is_query_successful(q_id))
            session.success_rate = success_count / len(session.queries)

            # Store updated session
            session_data = pickle.dumps(session)
            self.redis.setex(session_key, self.ttl_seconds, session_data)

            # Cache in memory
            self.session_cache[execution.session_id] = session

        except Exception as e:
            logger.error(f"Failed to update session: {e}")

    def _is_query_successful(self, query_id: str) -> bool:
        """Check if a query was successful."""
        try:
            exec_key = f"{self.namespace}:execution:{query_id}"
            exec_data = self.redis.get(exec_key)
            if exec_data:
                execution = pickle.loads(exec_data)
                return execution.success
        except Exception:
            pass
        return False

    def get_query_execution(self, query_id: str) -> Optional[QueryExecution]:
        """
        Retrieve a specific query execution.

        Args:
            query_id: ID of the query execution

        Returns:
            Query execution record or None if not found
        """
        try:
            exec_key = f"{self.namespace}:execution:{query_id}"
            exec_data = self.redis.get(exec_key)

            if exec_data:
                return pickle.loads(exec_data)

        except Exception as e:
            logger.error(f"Failed to get query execution {query_id}: {e}")

        return None

    def get_user_queries(
        self,
        user_id: str,
        limit: int = 50,
        offset: int = 0
    ) -> List[QueryExecution]:
        """
        Get queries for a specific user.

        Args:
            user_id: User identifier
            limit: Maximum number of queries to return
            offset: Number of queries to skip

        Returns:
            List of query executions
        """
        try:
            user_key = f"{self.namespace}:user:{user_id}"
            query_ids = self.redis.lrange(user_key, offset, offset + limit - 1)

            executions = []
            for query_id_bytes in query_ids:
                query_id = query_id_bytes.decode('utf-8')
                execution = self.get_query_execution(query_id)
                if execution:
                    executions.append(execution)

            return executions

        except Exception as e:
            logger.error(f"Failed to get user queries for {user_id}: {e}")
            return []

    def get_recent_queries(
        self,
        limit: int = 50,
        domain: Optional[str] = None
    ) -> List[str]:
        """
        Get recent queries across all users.

        Args:
            limit: Maximum number of queries to return
            domain: Optional domain filter

        Returns:
            List of query strings
        """
        try:
            if domain:
                # Get from domain-specific list
                domain_key = f"{self.namespace}:domain:{domain}"
                query_ids = self.redis.lrange(domain_key, 0, limit - 1)

                queries = []
                for query_id_bytes in query_ids:
                    query_id = query_id_bytes.decode('utf-8')
                    execution = self.get_query_execution(query_id)
                    if execution:
                        queries.append(execution.query)

                return queries
            else:
                # Get from recent queries list
                recent_key = f"{self.namespace}:recent"
                recent_records = self.redis.lrange(recent_key, 0, limit - 1)

                queries = []
                for record_bytes in recent_records:
                    try:
                        record = json.loads(record_bytes.decode('utf-8'))
                        queries.append(record['query'])
                    except json.JSONDecodeError:
                        continue

                return queries

        except Exception as e:
            logger.error(f"Failed to get recent queries: {e}")
            return []

    def get_popular_queries(
        self,
        time_window_days: int = 7,
        limit: int = 10
    ) -> List[Tuple[str, int]]:
        """
        Get most popular queries in a time window.

        Args:
            time_window_days: Time window in days
            limit: Maximum number of queries to return

        Returns:
            List of (query, count) tuples
        """
        try:
            query_counts = defaultdict(int)

            # Get queries from the time window
            end_date = datetime.now()
            for i in range(time_window_days):
                date = end_date - timedelta(days=i)
                date_key = f"{self.namespace}:date:{date.strftime('%Y-%m-%d')}"

                query_ids = self.redis.lrange(date_key, 0, -1)
                for query_id_bytes in query_ids:
                    query_id = query_id_bytes.decode('utf-8')
                    execution = self.get_query_execution(query_id)
                    if execution:
                        # Normalize query for counting
                        normalized_query = self._normalize_query(execution.query)
                        query_counts[normalized_query] += 1

            # Sort by count and return top queries
            popular = sorted(query_counts.items(), key=lambda x: x[1], reverse=True)
            return popular[:limit]

        except Exception as e:
            logger.error(f"Failed to get popular queries: {e}")
            return []

    def _normalize_query(self, query: str) -> str:
        """Normalize query for counting similar queries."""
        # Simple normalization - could be more sophisticated
        normalized = query.lower().strip()

        # Remove common variations
        import re
        normalized = re.sub(r'\bds\d+\b', 'dataset', normalized)
        normalized = re.sub(r'\d+\.\d+', 'X.X', normalized)
        normalized = re.sub(r'\b\d+\b', 'N', normalized)

        return normalized

    def get_session_history(self, session_id: str) -> Optional[QuerySession]:
        """
        Get session history.

        Args:
            session_id: Session identifier

        Returns:
            Session object or None if not found
        """
        # Check memory cache first
        if session_id in self.session_cache:
            return self.session_cache[session_id]

        try:
            session_key = f"{self.namespace}:session:{session_id}"
            session_data = self.redis.get(session_key)

            if session_data:
                session = pickle.loads(session_data)
                self.session_cache[session_id] = session
                return session

        except Exception as e:
            logger.error(f"Failed to get session {session_id}: {e}")

        return None

    def get_query_patterns(
        self,
        user_id: Optional[str] = None,
        time_window_days: int = 30
    ) -> Dict[str, Any]:
        """
        Analyze query patterns for a user or globally.

        Args:
            user_id: Optional user ID to analyze
            time_window_days: Time window for analysis

        Returns:
            Dictionary with pattern analysis
        """
        try:
            patterns = {
                "common_domains": defaultdict(int),
                "common_tools": defaultdict(int),
                "avg_execution_time": 0.0,
                "success_rate": 0.0,
                "peak_hours": defaultdict(int),
                "query_complexity_dist": defaultdict(int),
                "total_queries": 0
            }

            # Get queries for analysis
            if user_id:
                executions = self.get_user_queries(user_id, limit=1000)
            else:
                executions = self._get_all_recent_executions(time_window_days)

            if not executions:
                return patterns

            # Analyze patterns
            total_time = 0.0
            successful_queries = 0

            for execution in executions:
                patterns["total_queries"] += 1

                # Domain distribution
                if execution.domain:
                    patterns["common_domains"][execution.domain] += 1

                # Tool usage
                for tool in execution.tools_used:
                    patterns["common_tools"][tool] += 1

                # Timing
                total_time += execution.execution_time
                hour = execution.timestamp.hour
                patterns["peak_hours"][hour] += 1

                # Success rate
                if execution.success:
                    successful_queries += 1

                # Complexity
                complexity_bucket = int(execution.complexity_score * 10) // 2  # 0-5 scale
                patterns["query_complexity_dist"][complexity_bucket] += 1

            # Calculate averages
            if patterns["total_queries"] > 0:
                patterns["avg_execution_time"] = total_time / patterns["total_queries"]
                patterns["success_rate"] = successful_queries / patterns["total_queries"]

            # Convert defaultdicts to regular dicts for JSON serialization
            patterns = {k: dict(v) if isinstance(v, defaultdict) else v
                       for k, v in patterns.items()}

            return patterns

        except Exception as e:
            logger.error(f"Failed to analyze query patterns: {e}")
            return {}

    def _get_all_recent_executions(self, time_window_days: int) -> List[QueryExecution]:
        """Get all recent executions within time window."""
        executions = []

        try:
            end_date = datetime.now()
            for i in range(time_window_days):
                date = end_date - timedelta(days=i)
                date_key = f"{self.namespace}:date:{date.strftime('%Y-%m-%d')}"

                query_ids = self.redis.lrange(date_key, 0, -1)
                for query_id_bytes in query_ids:
                    query_id = query_id_bytes.decode('utf-8')
                    execution = self.get_query_execution(query_id)
                    if execution:
                        executions.append(execution)

        except Exception as e:
            logger.error(f"Failed to get recent executions: {e}")

        return executions

    def cleanup_old_data(self, older_than_days: int = 90):
        """
        Clean up data older than specified days.

        Args:
            older_than_days: Remove data older than this many days
        """
        try:
            cutoff_date = datetime.now() - timedelta(days=older_than_days)
            cleanup_count = 0

            # Clean up date-based keys
            start_date = cutoff_date - timedelta(days=30)  # Look back 30 more days
            current_date = start_date

            while current_date <= cutoff_date:
                date_key = f"{self.namespace}:date:{current_date.strftime('%Y-%m-%d')}"

                # Get query IDs for this date
                query_ids = self.redis.lrange(date_key, 0, -1)
                for query_id_bytes in query_ids:
                    query_id = query_id_bytes.decode('utf-8')

                    # Check if execution is old enough to delete
                    execution = self.get_query_execution(query_id)
                    if execution and execution.timestamp < cutoff_date:
                        exec_key = f"{self.namespace}:execution:{query_id}"
                        self.redis.delete(exec_key)
                        cleanup_count += 1

                # Delete the date key
                self.redis.delete(date_key)
                current_date += timedelta(days=1)

            logger.info(f"Cleaned up {cleanup_count} old query records")

        except Exception as e:
            logger.error(f"Failed to cleanup old data: {e}")

    def get_stats(self) -> Dict[str, Any]:
        """Get query history statistics."""
        try:
            stats = {
                "total_queries": 0,
                "unique_users": 0,
                "avg_queries_per_user": 0.0,
                "success_rate": 0.0,
                "memory_cache_size": len(self.recent_cache),
                "active_sessions": len(self.session_cache)
            }

            # Get recent stats from Redis
            recent_key = f"{self.namespace}:recent"
            total_recent = self.redis.llen(recent_key)
            stats["total_queries"] = total_recent

            # Count unique users (approximate)
            user_pattern = f"{self.namespace}:user:*"
            user_keys = self.redis.keys(user_pattern)
            stats["unique_users"] = len(user_keys)

            if stats["unique_users"] > 0:
                stats["avg_queries_per_user"] = stats["total_queries"] / stats["unique_users"]

            # Calculate success rate from recent cache
            if self.recent_cache:
                successful = sum(1 for exec in self.recent_cache if exec.success)
                stats["success_rate"] = successful / len(self.recent_cache)

            return stats

        except Exception as e:
            logger.error(f"Failed to get query history stats: {e}")
            return {"error": str(e)}


# Factory function
def create_query_history_store(
    redis_client: Optional[redis.Redis] = None,
    ttl_days: int = 30
) -> QueryHistoryStore:
    """
    Create a query history store instance.

    Args:
        redis_client: Redis client instance
        ttl_days: Time to live for stored queries in days

    Returns:
        Configured query history store
    """
    return QueryHistoryStore(redis_client, ttl_days)