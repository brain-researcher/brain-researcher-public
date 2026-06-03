"""
Performance monitoring system for BR-KG.
Implements KG-015: Query profiling, slow query logging, and index recommendations.
"""

import hashlib
import json
import logging
import sqlite3
import threading
import time
from collections import defaultdict
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from functools import wraps
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class QueryProfile:
    """Profile information for a single query execution."""

    query_id: str
    query_text: str
    query_type: str  # 'graphql', 'cypher', 'persisted', 'search'
    start_time: float
    end_time: float
    execution_time_ms: float
    rows_returned: int
    rows_examined: int
    index_used: bool
    cache_hit: bool
    user_id: str | None = None
    ip_address: str | None = None
    error: str | None = None
    slow_threshold_ms: float = 1000  # Default threshold

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for storage."""
        data = asdict(self)
        # Remove threshold from storage
        data.pop("slow_threshold_ms", None)
        return data

    @property
    def is_slow(self) -> bool:
        """Check if query is considered slow."""
        return self.execution_time_ms > self.slow_threshold_ms


@dataclass
class IndexRecommendation:
    """Recommendation for a database index."""

    table: str
    columns: list[str]
    reason: str
    estimated_improvement: float  # Percentage improvement
    query_patterns: list[str]
    frequency: int

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return asdict(self)


class PerformanceMonitor:
    """
    Main performance monitoring class for BR-KG.

    Features:
    - Query profiling with detailed metrics
    - Slow query logging with threshold configuration
    - Performance metrics aggregation
    - Index recommendation based on query patterns
    - Query plan analysis
    """

    def __init__(
        self,
        db_path: str = "br_kg_performance.db",
        slow_query_threshold_ms: float = 1000,
        enable_profiling: bool = True,
        max_history_days: int = 30,
    ):
        """
        Initialize performance monitor.

        Args:
            db_path: Path to performance database
            slow_query_threshold_ms: Threshold for slow queries
            enable_profiling: Whether to enable profiling
            max_history_days: Days to keep history
        """
        self.db_path = db_path
        self.slow_query_threshold = slow_query_threshold_ms
        self.enabled = enable_profiling
        self.max_history_days = max_history_days

        # In-memory caches
        self.query_cache: dict[str, QueryProfile] = {}
        self.slow_queries: list[QueryProfile] = []
        self.query_patterns: dict[str, int] = defaultdict(int)

        # Thread safety
        self._lock = threading.Lock()

        # Initialize database
        self._init_database()

        # Start background cleanup
        self._start_cleanup_thread()

    def _init_database(self):
        """Initialize performance database tables."""
        conn = sqlite3.connect(self.db_path)
        try:
            # Query profiles table
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS query_profiles (
                    query_id TEXT PRIMARY KEY,
                    query_text TEXT NOT NULL,
                    query_type TEXT NOT NULL,
                    start_time REAL NOT NULL,
                    end_time REAL NOT NULL,
                    execution_time_ms REAL NOT NULL,
                    rows_returned INTEGER,
                    rows_examined INTEGER,
                    index_used BOOLEAN,
                    cache_hit BOOLEAN,
                    user_id TEXT,
                    ip_address TEXT,
                    error TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """
            )

            # Slow query log
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS slow_queries (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    query_id TEXT NOT NULL,
                    query_text TEXT NOT NULL,
                    execution_time_ms REAL NOT NULL,
                    query_type TEXT NOT NULL,
                    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (query_id) REFERENCES query_profiles(query_id)
                )
            """
            )

            # Performance metrics table
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS performance_metrics (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    metric_name TEXT NOT NULL,
                    metric_value REAL NOT NULL,
                    metric_type TEXT NOT NULL,  -- 'counter', 'gauge', 'histogram'
                    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """
            )

            # Index recommendations table
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS index_recommendations (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    table_name TEXT NOT NULL,
                    columns TEXT NOT NULL,  -- JSON array
                    reason TEXT NOT NULL,
                    estimated_improvement REAL,
                    query_patterns TEXT,  -- JSON array
                    frequency INTEGER,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    applied BOOLEAN DEFAULT FALSE
                )
            """
            )

            # Query patterns table for analysis
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS query_patterns (
                    pattern_hash TEXT PRIMARY KEY,
                    pattern TEXT NOT NULL,
                    count INTEGER DEFAULT 1,
                    avg_execution_time_ms REAL,
                    last_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """
            )

            # Create indexes for performance
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_profiles_time
                ON query_profiles(start_time DESC)
            """
            )

            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_profiles_type
                ON query_profiles(query_type)
            """
            )

            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_slow_queries_time
                ON slow_queries(timestamp DESC)
            """
            )

            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_metrics_name_time
                ON performance_metrics(metric_name, timestamp DESC)
            """
            )

            conn.commit()
        finally:
            conn.close()

    def profile_query(
        self,
        query_text: str,
        query_type: str = "unknown",
        user_id: str | None = None,
        ip_address: str | None = None,
    ):
        """
        Context manager for profiling a query.

        Usage:
            with monitor.profile_query(query, "graphql") as profile:
                # Execute query
                results = execute_query(query)
                profile.rows_returned = len(results)
        """
        if not self.enabled:
            return NullProfiler()

        return QueryProfiler(
            monitor=self,
            query_text=query_text,
            query_type=query_type,
            user_id=user_id,
            ip_address=ip_address,
        )

    def record_profile(self, profile: QueryProfile):
        """Record a query profile."""
        with self._lock:
            # Store in memory
            self.query_cache[profile.query_id] = profile

            # Check if slow query
            if profile.is_slow:
                self.slow_queries.append(profile)
                self._log_slow_query(profile)

            # Update query patterns
            pattern = self._extract_pattern(profile.query_text)
            self.query_patterns[pattern] += 1

            # Store in database
            self._store_profile(profile)

            # Update metrics
            self._update_metrics(profile)

    def _log_slow_query(self, profile: QueryProfile):
        """Log a slow query."""
        logger.warning(
            f"Slow query detected: {profile.execution_time_ms:.2f}ms\n"
            f"Type: {profile.query_type}\n"
            f"Query: {profile.query_text[:200]}..."
        )

        # Store in slow query log
        conn = sqlite3.connect(self.db_path)
        try:
            conn.execute(
                """
                INSERT INTO slow_queries
                (query_id, query_text, execution_time_ms, query_type)
                VALUES (?, ?, ?, ?)
            """,
                (
                    profile.query_id,
                    profile.query_text,
                    profile.execution_time_ms,
                    profile.query_type,
                ),
            )
            conn.commit()
        finally:
            conn.close()

    def _store_profile(self, profile: QueryProfile):
        """Store profile in database."""
        conn = sqlite3.connect(self.db_path)
        try:
            conn.execute(
                """
                INSERT OR REPLACE INTO query_profiles
                (query_id, query_text, query_type, start_time, end_time,
                 execution_time_ms, rows_returned, rows_examined,
                 index_used, cache_hit, user_id, ip_address, error)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
                (
                    profile.query_id,
                    profile.query_text,
                    profile.query_type,
                    profile.start_time,
                    profile.end_time,
                    profile.execution_time_ms,
                    profile.rows_returned,
                    profile.rows_examined,
                    profile.index_used,
                    profile.cache_hit,
                    profile.user_id,
                    profile.ip_address,
                    profile.error,
                ),
            )

            # Update query patterns
            pattern = self._extract_pattern(profile.query_text)
            pattern_hash = hashlib.md5(pattern.encode()).hexdigest()

            conn.execute(
                """
                INSERT INTO query_patterns (pattern_hash, pattern, count, avg_execution_time_ms)
                VALUES (?, ?, 1, ?)
                ON CONFLICT(pattern_hash) DO UPDATE SET
                    count = count + 1,
                    avg_execution_time_ms =
                        (avg_execution_time_ms * count + ?) / (count + 1),
                    last_seen = CURRENT_TIMESTAMP
            """,
                (
                    pattern_hash,
                    pattern,
                    profile.execution_time_ms,
                    profile.execution_time_ms,
                ),
            )

            conn.commit()
        finally:
            conn.close()

    def _update_metrics(self, profile: QueryProfile):
        """Update performance metrics."""
        conn = sqlite3.connect(self.db_path)
        try:
            # Record execution time
            conn.execute(
                """
                INSERT INTO performance_metrics
                (metric_name, metric_value, metric_type)
                VALUES (?, ?, ?)
            """,
                (
                    f"query_execution_time_{profile.query_type}",
                    profile.execution_time_ms,
                    "histogram",
                ),
            )

            # Record cache hit rate
            if profile.cache_hit is not None:
                conn.execute(
                    """
                    INSERT INTO performance_metrics
                    (metric_name, metric_value, metric_type)
                    VALUES (?, ?, ?)
                """,
                    ("cache_hit_rate", 1.0 if profile.cache_hit else 0.0, "gauge"),
                )

            conn.commit()
        finally:
            conn.close()

    def _extract_pattern(self, query: str) -> str:
        """
        Extract pattern from query by removing literals.
        This helps identify similar queries.
        """
        import re

        # Remove string literals
        pattern = re.sub(r'"[^"]*"', '"?"', query)
        pattern = re.sub(r"'[^']*'", "'?'", pattern)

        # Remove numbers
        pattern = re.sub(r"\b\d+\b", "?", pattern)

        # Normalize whitespace
        pattern = " ".join(pattern.split())

        return pattern

    def get_slow_queries(
        self, limit: int = 100, since: datetime | None = None
    ) -> list[dict[str, Any]]:
        """Get recent slow queries."""
        conn = sqlite3.connect(self.db_path)
        try:
            query = """
                SELECT query_id, query_text, execution_time_ms,
                       query_type, timestamp
                FROM slow_queries
            """
            params = []

            if since:
                query += " WHERE timestamp >= ?"
                params.append(since.isoformat())

            query += " ORDER BY timestamp DESC LIMIT ?"
            params.append(limit)

            cursor = conn.execute(query, params)

            return [
                {
                    "query_id": row[0],
                    "query_text": row[1],
                    "execution_time_ms": row[2],
                    "query_type": row[3],
                    "timestamp": row[4],
                }
                for row in cursor.fetchall()
            ]
        finally:
            conn.close()

    def get_performance_metrics(
        self,
        metric_names: list[str] | None = None,
        since: datetime | None = None,
        aggregation: str = "avg",  # 'avg', 'sum', 'count', 'p50', 'p95', 'p99'
    ) -> dict[str, float]:
        """Get aggregated performance metrics."""
        conn = sqlite3.connect(self.db_path)
        try:
            base_query = """
                SELECT metric_name, metric_value
                FROM performance_metrics
            """
            conditions = []
            params = []

            if metric_names:
                placeholders = ",".join("?" * len(metric_names))
                conditions.append(f"metric_name IN ({placeholders})")
                params.extend(metric_names)

            if since:
                conditions.append("timestamp >= ?")
                params.append(since.isoformat())

            if conditions:
                base_query += " WHERE " + " AND ".join(conditions)

            cursor = conn.execute(base_query, params)

            # Group metrics by name
            metrics_data = defaultdict(list)
            for row in cursor.fetchall():
                metrics_data[row[0]].append(row[1])

            # Aggregate
            results = {}
            for name, values in metrics_data.items():
                if not values:
                    continue

                if aggregation == "avg":
                    results[name] = sum(values) / len(values)
                elif aggregation == "sum":
                    results[name] = sum(values)
                elif aggregation == "count":
                    results[name] = len(values)
                elif aggregation == "p50":
                    values.sort()
                    results[name] = values[len(values) // 2]
                elif aggregation == "p95":
                    values.sort()
                    idx = int(len(values) * 0.95)
                    results[name] = values[min(idx, len(values) - 1)]
                elif aggregation == "p99":
                    values.sort()
                    idx = int(len(values) * 0.99)
                    results[name] = values[min(idx, len(values) - 1)]

            return results
        finally:
            conn.close()

    def analyze_query_patterns(self, min_frequency: int = 5) -> list[dict[str, Any]]:
        """Analyze query patterns to find optimization opportunities."""
        conn = sqlite3.connect(self.db_path)
        try:
            cursor = conn.execute(
                """
                SELECT pattern, count, avg_execution_time_ms
                FROM query_patterns
                WHERE count >= ?
                ORDER BY count DESC, avg_execution_time_ms DESC
            """,
                (min_frequency,),
            )

            patterns = []
            for row in cursor.fetchall():
                patterns.append(
                    {
                        "pattern": row[0],
                        "frequency": row[1],
                        "avg_execution_time_ms": row[2],
                        "total_time_ms": row[1] * row[2],
                    }
                )

            return patterns
        finally:
            conn.close()

    def recommend_indexes(self) -> list[IndexRecommendation]:
        """
        Analyze query patterns and recommend indexes.

        Returns:
            List of index recommendations
        """
        recommendations = []

        # Analyze slow queries without indexes
        conn = sqlite3.connect(self.db_path)
        try:
            # Find queries that don't use indexes
            cursor = conn.execute(
                """
                SELECT query_text, query_type, COUNT(*) as freq,
                       AVG(execution_time_ms) as avg_time
                FROM query_profiles
                WHERE index_used = 0
                  AND execution_time_ms > ?
                GROUP BY query_text
                HAVING freq >= 3
                ORDER BY freq * avg_time DESC
            """,
                (self.slow_query_threshold / 2,),
            )

            for row in cursor.fetchall():
                query_text = row[0]
                query_type = row[1]
                frequency = row[2]
                avg_time = row[3]

                # Extract potential index columns from query
                index_cols = self._extract_index_candidates(query_text, query_type)

                if index_cols:
                    for table, columns in index_cols.items():
                        rec = IndexRecommendation(
                            table=table,
                            columns=columns,
                            reason="Frequent slow query without index usage",
                            estimated_improvement=min(
                                80, avg_time / 10
                            ),  # Rough estimate
                            query_patterns=[self._extract_pattern(query_text)],
                            frequency=frequency,
                        )
                        recommendations.append(rec)

            # Store recommendations
            for rec in recommendations:
                conn.execute(
                    """
                    INSERT INTO index_recommendations
                    (table_name, columns, reason, estimated_improvement,
                     query_patterns, frequency)
                    VALUES (?, ?, ?, ?, ?, ?)
                """,
                    (
                        rec.table,
                        json.dumps(rec.columns),
                        rec.reason,
                        rec.estimated_improvement,
                        json.dumps(rec.query_patterns),
                        rec.frequency,
                    ),
                )

            conn.commit()

        finally:
            conn.close()

        return recommendations

    def _extract_index_candidates(
        self, query: str, query_type: str
    ) -> dict[str, list[str]]:
        """Extract potential index columns from query."""
        import re

        candidates = defaultdict(list)

        if query_type == "graphql":
            # Look for filter conditions in GraphQL
            # Example: concepts(filter: {name: "motor"})
            filter_pattern = r"filter:\s*{([^}]+)}"
            matches = re.findall(filter_pattern, query)
            for match in matches:
                # Extract field names
                fields = re.findall(r"(\w+):", match)
                if fields:
                    # Assume concepts table for now
                    candidates["concepts"].extend(fields)

        elif query_type == "cypher":
            # Look for WHERE clauses in Cypher
            # Example: WHERE n.name = 'motor'
            where_pattern = r"WHERE\s+(\w+)\.(\w+)\s*="
            matches = re.findall(where_pattern, query, re.IGNORECASE)
            for alias, field in matches:
                # Map alias to table (simplified)
                table = self._cypher_alias_to_table(alias)
                if table:
                    candidates[table].append(field)

        elif query_type == "search":
            # Search queries typically benefit from full-text indexes
            candidates["nodes"].append("_text_index_")

        # Remove duplicates
        for table in candidates:
            candidates[table] = list(set(candidates[table]))

        return dict(candidates)

    def _cypher_alias_to_table(self, alias: str) -> str | None:
        """Map Cypher alias to table name (simplified)."""
        # This is a simple heuristic
        if alias.lower() in ["n", "node"]:
            return "nodes"
        elif alias.lower() in ["r", "rel", "e", "edge"]:
            return "relationships"
        return None

    def export_report(
        self,
        output_path: str | None = None,
        include_slow_queries: bool = True,
        include_metrics: bool = True,
        include_recommendations: bool = True,
    ) -> dict[str, Any]:
        """
        Export comprehensive performance report.

        Args:
            output_path: Optional path to save JSON report
            include_slow_queries: Include slow query analysis
            include_metrics: Include performance metrics
            include_recommendations: Include index recommendations

        Returns:
            Performance report dictionary
        """
        report = {
            "generated_at": datetime.now().isoformat(),
            "monitoring_period_days": self.max_history_days,
            "slow_query_threshold_ms": self.slow_query_threshold,
        }

        if include_slow_queries:
            report["slow_queries"] = {
                "recent": self.get_slow_queries(limit=50),
                "patterns": self.analyze_query_patterns(),
            }

        if include_metrics:
            # Get metrics for last 24 hours
            since = datetime.now() - timedelta(hours=24)
            report["metrics"] = {
                "p50": self.get_performance_metrics(since=since, aggregation="p50"),
                "p95": self.get_performance_metrics(since=since, aggregation="p95"),
                "p99": self.get_performance_metrics(since=since, aggregation="p99"),
                "avg": self.get_performance_metrics(since=since, aggregation="avg"),
            }

        if include_recommendations:
            recommendations = self.recommend_indexes()
            report["index_recommendations"] = [rec.to_dict() for rec in recommendations]

        # Add summary statistics
        conn = sqlite3.connect(self.db_path)
        try:
            # Total queries
            cursor = conn.execute("SELECT COUNT(*) FROM query_profiles")
            report["total_queries"] = cursor.fetchone()[0]

            # Slow query percentage
            cursor = conn.execute(
                "SELECT COUNT(*) FROM query_profiles WHERE execution_time_ms > ?",
                (self.slow_query_threshold,),
            )
            slow_count = cursor.fetchone()[0]
            report["slow_query_percentage"] = (
                (slow_count / report["total_queries"] * 100)
                if report["total_queries"] > 0
                else 0
            )

            # Cache hit rate
            cursor = conn.execute(
                """
                SELECT AVG(CASE WHEN cache_hit THEN 1.0 ELSE 0.0 END)
                FROM query_profiles
                WHERE cache_hit IS NOT NULL
            """
            )
            cache_hit_rate = cursor.fetchone()[0]
            report["cache_hit_rate"] = cache_hit_rate or 0.0

        finally:
            conn.close()

        if output_path:
            with open(output_path, "w") as f:
                json.dump(report, f, indent=2, default=str)

        return report

    def _start_cleanup_thread(self):
        """Start background thread for cleanup."""

        def cleanup():
            while True:
                time.sleep(86400)  # Daily cleanup
                self._cleanup_old_data()

        thread = threading.Thread(target=cleanup, daemon=True)
        thread.start()

    def _cleanup_old_data(self):
        """Clean up old performance data."""
        cutoff = datetime.now() - timedelta(days=self.max_history_days)

        conn = sqlite3.connect(self.db_path)
        try:
            # Clean up old profiles
            conn.execute(
                "DELETE FROM query_profiles WHERE created_at < ?", (cutoff.isoformat(),)
            )

            # Clean up old metrics
            conn.execute(
                "DELETE FROM performance_metrics WHERE timestamp < ?",
                (cutoff.isoformat(),),
            )

            # Clean up old slow queries
            conn.execute(
                "DELETE FROM slow_queries WHERE timestamp < ?", (cutoff.isoformat(),)
            )

            conn.commit()

            # Vacuum to reclaim space
            conn.execute("VACUUM")

        finally:
            conn.close()


class QueryProfiler:
    """Context manager for profiling a single query."""

    def __init__(
        self,
        monitor: PerformanceMonitor,
        query_text: str,
        query_type: str,
        user_id: str | None = None,
        ip_address: str | None = None,
    ):
        self.monitor = monitor
        self.query_text = query_text
        self.query_type = query_type
        self.user_id = user_id
        self.ip_address = ip_address
        self.profile: QueryProfile | None = None

    def __enter__(self):
        """Start profiling."""
        self.start_time = time.time()

        # Generate query ID
        query_hash = hashlib.md5(
            f"{self.query_text}{self.start_time}".encode()
        ).hexdigest()[:16]

        self.profile = QueryProfile(
            query_id=query_hash,
            query_text=self.query_text,
            query_type=self.query_type,
            start_time=self.start_time,
            end_time=0,
            execution_time_ms=0,
            rows_returned=0,
            rows_examined=0,
            index_used=False,
            cache_hit=False,
            user_id=self.user_id,
            ip_address=self.ip_address,
            error=None,
            slow_threshold_ms=self.monitor.slow_query_threshold,
        )

        return self.profile

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Complete profiling."""
        if self.profile:
            self.profile.end_time = time.time()
            self.profile.execution_time_ms = (
                self.profile.end_time - self.profile.start_time
            ) * 1000

            if exc_val:
                self.profile.error = str(exc_val)

            # Record the profile
            self.monitor.record_profile(self.profile)


class NullProfiler:
    """Null profiler when monitoring is disabled."""

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        pass

    def __setattr__(self, name, value):
        pass


def profile_query(monitor: PerformanceMonitor):
    """
    Decorator for profiling functions that execute queries.

    Usage:
        @profile_query(monitor)
        def execute_graphql(query: str):
            # Execute query
            return results
    """

    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            # Try to extract query from args
            query = args[0] if args else kwargs.get("query", "unknown")
            query_type = kwargs.get("query_type", func.__name__)

            with monitor.profile_query(query, query_type) as profile:
                try:
                    result = func(*args, **kwargs)

                    # Try to extract result count
                    if hasattr(result, "__len__"):
                        profile.rows_returned = len(result)

                    return result
                except Exception as e:
                    profile.error = str(e)
                    raise

        return wrapper

    return decorator


# Example usage
if __name__ == "__main__":
    # Create monitor
    monitor = PerformanceMonitor(slow_query_threshold_ms=500, enable_profiling=True)

    # Example profiling
    with monitor.profile_query(
        "query { concepts(filter: {name: 'motor'}) { id name } }", "graphql"
    ) as profile:
        # Simulate query execution
        time.sleep(0.1)
        profile.rows_returned = 10
        profile.index_used = True

    # Get slow queries
    slow_queries = monitor.get_slow_queries(limit=10)
    print(f"Slow queries: {len(slow_queries)}")

    # Get performance metrics
    metrics = monitor.get_performance_metrics(aggregation="p95")
    print(f"P95 metrics: {metrics}")

    # Get recommendations
    recommendations = monitor.recommend_indexes()
    for rec in recommendations:
        print(f"Recommend index on {rec.table}({', '.join(rec.columns)})")

    # Export report
    report = monitor.export_report("performance_report.json")
    print(f"Report exported with {report['total_queries']} queries analyzed")
