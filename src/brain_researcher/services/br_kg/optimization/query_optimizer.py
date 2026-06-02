"""Query optimization engine for Neo4j knowledge graph.

Provides query planning, caching, and optimization for complex graph queries
to ensure <500ms response times for common patterns.
"""

import hashlib
import json
import logging
import re
import time
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

import networkx as nx

logger = logging.getLogger(__name__)


class QueryType(str, Enum):
    """Types of graph queries."""

    MATCH = "match"
    TRAVERSE = "traverse"
    AGGREGATE = "aggregate"
    PATH = "path"
    SUBGRAPH = "subgraph"
    ANALYTICAL = "analytical"


class OptimizationStrategy(str, Enum):
    """Query optimization strategies."""

    INDEX_SCAN = "index_scan"
    LABEL_SCAN = "label_scan"
    NODE_BY_ID = "node_by_id"
    RELATIONSHIP_SCAN = "relationship_scan"
    EXPAND = "expand"
    HASH_JOIN = "hash_join"
    MERGE_JOIN = "merge_join"
    FILTER_PUSH_DOWN = "filter_push_down"


@dataclass
class QueryPlan:
    """Execution plan for a query."""

    query_id: str
    original_query: str
    optimized_query: str
    estimated_cost: float
    strategies: List[OptimizationStrategy]
    index_hints: List[str]
    cache_key: Optional[str] = None
    execution_time: Optional[float] = None
    rows_returned: Optional[int] = None


@dataclass
class QueryStatistics:
    """Statistics for query execution."""

    query_pattern: str
    execution_count: int = 0
    total_time: float = 0.0
    avg_time: float = 0.0
    min_time: float = float("inf")
    max_time: float = 0.0
    avg_rows: float = 0.0
    last_executed: Optional[datetime] = None


class QueryCache:
    """LRU cache for query results."""

    def __init__(self, max_size: int = 1000, ttl_seconds: int = 300):
        """Initialize cache.

        Args:
            max_size: Maximum cache entries
            ttl_seconds: Time to live for entries
        """
        self.max_size = max_size
        self.ttl_seconds = ttl_seconds
        self.cache: Dict[str, Tuple[Any, datetime]] = {}
        self.access_order: List[str] = []
        self.hit_count = 0
        self.miss_count = 0

    def get(self, key: str) -> Optional[Any]:
        """Get value from cache.

        Args:
            key: Cache key

        Returns:
            Cached value or None
        """
        if key in self.cache:
            value, timestamp = self.cache[key]

            # Check TTL
            if (datetime.utcnow() - timestamp).seconds > self.ttl_seconds:
                del self.cache[key]
                self.miss_count += 1
                return None

            # Update access order
            self.access_order.remove(key)
            self.access_order.append(key)
            self.hit_count += 1
            return value

        self.miss_count += 1
        return None

    def put(self, key: str, value: Any):
        """Put value in cache.

        Args:
            key: Cache key
            value: Value to cache
        """
        # Evict if at capacity
        if len(self.cache) >= self.max_size and key not in self.cache:
            oldest = self.access_order.pop(0)
            del self.cache[oldest]

        self.cache[key] = (value, datetime.utcnow())

        if key in self.access_order:
            self.access_order.remove(key)
        self.access_order.append(key)

    def get_hit_rate(self) -> float:
        """Get cache hit rate.

        Returns:
            Hit rate (0-1)
        """
        total = self.hit_count + self.miss_count
        return self.hit_count / total if total > 0 else 0.0


class QueryOptimizer:
    """Main query optimization engine."""

    def __init__(
        self,
        enable_cache: bool = True,
        cache_size: int = 1000,
        collect_statistics: bool = True,
    ):
        """Initialize optimizer.

        Args:
            enable_cache: Enable query caching
            cache_size: Cache size
            collect_statistics: Collect query statistics
        """
        self.enable_cache = enable_cache
        self.cache = QueryCache(max_size=cache_size) if enable_cache else None
        self.collect_statistics = collect_statistics
        self.statistics: Dict[str, QueryStatistics] = {}

        # Index metadata (would be loaded from Neo4j)
        self.available_indexes = {
            "Task": ["id", "name", "contrast"],
            "Concept": ["id", "name", "domain"],
            "Region": ["id", "name", "coordinates"],
            "Publication": ["pmid", "doi", "year"],
        }

        # Query patterns for optimization
        self.optimization_rules = self._initialize_rules()

    def _initialize_rules(self) -> List[Tuple[re.Pattern, Callable]]:
        """Initialize optimization rules.

        Returns:
            List of (pattern, optimizer) tuples
        """
        return [
            # Index usage for node properties
            (
                re.compile(r'MATCH \((\w+):(\w+)\s*\{(\w+):\s*["\']([^"\']*)'),
                self._optimize_index_lookup,
            ),
            # Filter push-down
            (re.compile(r"MATCH .+ WHERE .+ AND"), self._optimize_filter_pushdown),
            # Path optimization
            (re.compile(r"MATCH .+\*\d+\.\.\.?\d*"), self._optimize_path_query),
            # Aggregation optimization
            (re.compile(r"WITH .+ AS .+, collect\("), self._optimize_aggregation),
            # Join optimization
            (re.compile(r"MATCH \(.+\).+MATCH \(.+\)"), self._optimize_joins),
        ]

    def optimize_query(self, query: str, params: Optional[Dict] = None) -> QueryPlan:
        """Optimize a Cypher query.

        Args:
            query: Original Cypher query
            params: Query parameters

        Returns:
            Optimized query plan
        """
        query_id = self._generate_query_id(query, params)

        # Check cache if enabled
        if self.enable_cache:
            cache_key = self._get_cache_key(query, params)
            if cached_plan := self.cache.get(f"plan_{cache_key}"):
                logger.debug(f"Using cached plan for query {query_id}")
                return cached_plan

        # Analyze query
        query_type = self._identify_query_type(query)
        estimated_cost = self._estimate_cost(query)

        # Apply optimization rules
        optimized_query = query
        strategies = []
        index_hints = []

        for pattern, optimizer in self.optimization_rules:
            if pattern.search(query):
                result = optimizer(query)
                if result:
                    optimized_query = result.get("query", optimized_query)
                    strategies.extend(result.get("strategies", []))
                    index_hints.extend(result.get("hints", []))

        # Add index hints
        if index_hints:
            optimized_query = self._add_index_hints(optimized_query, index_hints)

        # Create plan
        plan = QueryPlan(
            query_id=query_id,
            original_query=query,
            optimized_query=optimized_query,
            estimated_cost=estimated_cost,
            strategies=strategies,
            index_hints=index_hints,
            cache_key=cache_key if self.enable_cache else None,
        )

        # Cache plan
        if self.enable_cache:
            self.cache.put(f"plan_{cache_key}", plan)

        return plan

    def _generate_query_id(self, query: str, params: Optional[Dict]) -> str:
        """Generate unique query ID.

        Args:
            query: Query string
            params: Parameters

        Returns:
            Query ID
        """
        content = query + str(params) if params else query
        return hashlib.md5(content.encode()).hexdigest()[:8]

    def _get_cache_key(self, query: str, params: Optional[Dict]) -> str:
        """Generate cache key for query.

        Args:
            query: Query string
            params: Parameters

        Returns:
            Cache key
        """
        # Normalize query (remove whitespace, lowercase)
        normalized = re.sub(r"\s+", " ", query.lower().strip())
        content = (
            normalized + json.dumps(params, sort_keys=True) if params else normalized
        )
        return hashlib.sha256(content.encode()).hexdigest()

    def _identify_query_type(self, query: str) -> QueryType:
        """Identify query type.

        Args:
            query: Cypher query

        Returns:
            Query type
        """
        query_lower = query.lower()

        if "shortest" in query_lower or "allshortestpaths" in query_lower:
            return QueryType.PATH
        elif "*" in query and ".." in query:
            return QueryType.TRAVERSE
        elif "collect(" in query_lower or "count(" in query_lower:
            return QueryType.AGGREGATE
        elif "algo." in query_lower or "gds." in query_lower:
            return QueryType.ANALYTICAL
        elif "match" in query_lower and "return" in query_lower:
            return QueryType.MATCH
        else:
            return QueryType.SUBGRAPH

    def _estimate_cost(self, query: str) -> float:
        """Estimate query execution cost.

        Args:
            query: Cypher query

        Returns:
            Estimated cost (arbitrary units)
        """
        cost = 1.0

        # Penalize unbounded traversals
        if re.search(r"\*\d*\.\.(?!\d)", query):
            cost *= 10.0

        # Penalize missing WHERE clauses
        if "match" in query.lower() and "where" not in query.lower():
            cost *= 2.0

        # Reward index usage
        for label, props in self.available_indexes.items():
            if label in query:
                for prop in props:
                    if prop in query:
                        cost *= 0.5

        # Penalize cartesian products
        match_count = query.lower().count("match")
        if match_count > 1 and "with" not in query.lower():
            cost *= match_count * 2

        return cost

    def _optimize_index_lookup(self, query: str) -> Dict[str, Any]:
        """Optimize index lookups.

        Args:
            query: Cypher query

        Returns:
            Optimization result
        """
        result = {
            "query": query,
            "strategies": [OptimizationStrategy.INDEX_SCAN],
            "hints": [],
        }

        # Find property lookups
        pattern = re.compile(r'MATCH \((\w+):(\w+)\s*\{(\w+):\s*["\']?([^"\'}]*)')
        matches = pattern.findall(query)

        for var, label, prop, value in matches:
            if label in self.available_indexes:
                if prop in self.available_indexes[label]:
                    hint = f"USING INDEX {var}:{label}({prop})"
                    result["hints"].append(hint)

        return result

    def _optimize_filter_pushdown(self, query: str) -> Dict[str, Any]:
        """Push filters down in query.

        Args:
            query: Cypher query

        Returns:
            Optimization result
        """
        # Move WHERE conditions closer to MATCH
        optimized = query

        # Find WHERE clause filters
        where_match = re.search(r"WHERE (.+?)(?:RETURN|WITH|ORDER)", query)
        if where_match:
            filters = where_match.group(1)

            # Try to convert to inline filters
            prop_filters = re.findall(r'(\w+)\.(\w+)\s*=\s*["\']?([^"\' ]+)', filters)

            for var, prop, value in prop_filters:
                # Find corresponding MATCH
                match_pattern = rf"MATCH \(({var}):(\w+)\)"
                if re.search(match_pattern, optimized):
                    # Convert to inline filter
                    inline = f"MATCH ({var}:$2 {{{prop}: {value}}}"
                    optimized = re.sub(match_pattern, inline, optimized, count=1)

        return {
            "query": optimized,
            "strategies": [OptimizationStrategy.FILTER_PUSH_DOWN],
            "hints": [],
        }

    def _optimize_path_query(self, query: str) -> Dict[str, Any]:
        """Optimize path queries.

        Args:
            query: Cypher query

        Returns:
            Optimization result
        """
        result = {
            "query": query,
            "strategies": [OptimizationStrategy.EXPAND],
            "hints": [],
        }

        # Limit unbounded traversals
        unbounded = re.compile(r"\*(\.\.(?!\d))")
        if unbounded.search(query):
            # Add reasonable upper bound
            result["query"] = unbounded.sub(r"*1..5", query)
            result["hints"].append("Limited unbounded traversal to depth 5")

        return result

    def _optimize_aggregation(self, query: str) -> Dict[str, Any]:
        """Optimize aggregation queries.

        Args:
            query: Cypher query

        Returns:
            Optimization result
        """
        # Use DISTINCT before collect() when appropriate
        optimized = re.sub(r"collect\(([^)]+)\)", r"collect(DISTINCT \1)", query)

        return {
            "query": optimized,
            "strategies": [OptimizationStrategy.HASH_JOIN],
            "hints": ["Added DISTINCT to collect()"],
        }

    def _optimize_joins(self, query: str) -> Dict[str, Any]:
        """Optimize join operations.

        Args:
            query: Cypher query

        Returns:
            Optimization result
        """
        # Reorder joins based on selectivity
        # This is simplified - real implementation would analyze cardinality

        return {
            "query": query,
            "strategies": [OptimizationStrategy.MERGE_JOIN],
            "hints": ["Consider join order based on selectivity"],
        }

    def _add_index_hints(self, query: str, hints: List[str]) -> str:
        """Add index hints to query.

        Args:
            query: Cypher query
            hints: Index hints

        Returns:
            Query with hints
        """
        if not hints:
            return query

        # Add hints after MATCH clause
        hint_str = " ".join(hints)
        return re.sub(
            r"(MATCH .+?)\s+(WHERE|RETURN|WITH)", f"\\1 {hint_str} \\2", query, count=1
        )

    def execute_with_optimization(
        self,
        query: str,
        params: Optional[Dict] = None,
        executor: Optional[Callable] = None,
    ) -> Tuple[Any, QueryPlan]:
        """Execute query with optimization.

        Args:
            query: Cypher query
            params: Query parameters
            executor: Query executor function

        Returns:
            (results, plan) tuple
        """
        # Check cache
        if self.enable_cache:
            cache_key = self._get_cache_key(query, params)
            if cached_result := self.cache.get(f"result_{cache_key}"):
                logger.debug("Returning cached result")
                # Still need to get plan
                plan = self.optimize_query(query, params)
                return cached_result, plan

        # Optimize query
        plan = self.optimize_query(query, params)

        # Execute
        start_time = time.time()

        if executor:
            results = executor(plan.optimized_query, params)
        else:
            # Simulate execution
            results = {"simulated": True, "query": plan.optimized_query}

        execution_time = time.time() - start_time
        plan.execution_time = execution_time

        # Update statistics
        if self.collect_statistics:
            self._update_statistics(
                query, execution_time, len(results) if isinstance(results, list) else 1
            )

        # Cache result
        if self.enable_cache:
            self.cache.put(f"result_{cache_key}", results)

        return results, plan

    def _update_statistics(self, query: str, execution_time: float, row_count: int):
        """Update query statistics.

        Args:
            query: Query pattern
            execution_time: Execution time
            row_count: Rows returned
        """
        # Normalize query to pattern
        pattern = re.sub(r'["\'][^"^\']*["\']', "<value>", query)
        pattern = re.sub(r"\d+", "<number>", pattern)

        if pattern not in self.statistics:
            self.statistics[pattern] = QueryStatistics(query_pattern=pattern)

        stats = self.statistics[pattern]
        stats.execution_count += 1
        stats.total_time += execution_time
        stats.avg_time = stats.total_time / stats.execution_count
        stats.min_time = min(stats.min_time, execution_time)
        stats.max_time = max(stats.max_time, execution_time)
        stats.avg_rows = (
            stats.avg_rows * (stats.execution_count - 1) + row_count
        ) / stats.execution_count
        stats.last_executed = datetime.utcnow()

    def get_statistics_report(self) -> Dict[str, Any]:
        """Get optimization statistics report.

        Returns:
            Statistics report
        """
        report = {
            "cache_hit_rate": self.cache.get_hit_rate() if self.cache else 0,
            "total_queries": sum(s.execution_count for s in self.statistics.values()),
            "unique_patterns": len(self.statistics),
            "top_queries": [],
            "slowest_queries": [],
        }

        # Top queries by frequency
        sorted_by_count = sorted(
            self.statistics.values(), key=lambda s: s.execution_count, reverse=True
        )[:10]

        report["top_queries"] = [
            {
                "pattern": s.query_pattern[:100],
                "count": s.execution_count,
                "avg_time": s.avg_time,
            }
            for s in sorted_by_count
        ]

        # Slowest queries
        sorted_by_time = sorted(
            self.statistics.values(), key=lambda s: s.avg_time, reverse=True
        )[:10]

        report["slowest_queries"] = [
            {
                "pattern": s.query_pattern[:100],
                "avg_time": s.avg_time,
                "count": s.execution_count,
            }
            for s in sorted_by_time
        ]

        return report
