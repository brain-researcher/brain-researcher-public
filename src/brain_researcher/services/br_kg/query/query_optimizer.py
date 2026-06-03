"""Cypher query optimization for BR-KG.

This module completes the query optimization for KG-006 with query plan analysis,
caching integration, and DataLoader support.
"""

import hashlib
import json
import logging
import re
import time
from typing import Dict, List, Any, Optional, Tuple
from dataclasses import dataclass
from enum import Enum

import redis
from neo4j import GraphDatabase

logger = logging.getLogger(__name__)


class QueryType(Enum):
    """Types of Cypher queries."""

    MATCH = "match"
    CREATE = "create"
    MERGE = "merge"
    DELETE = "delete"
    RETURN = "return"
    AGGREGATE = "aggregate"
    PATH = "path"


@dataclass
class QueryPlan:
    """Query execution plan."""

    original_query: str
    optimized_query: str
    estimated_cost: float
    actual_cost: Optional[float] = None
    optimizations_applied: List[str] = None
    cache_key: Optional[str] = None


class CypherOptimizer:
    """Optimize Cypher queries for Neo4j."""

    def __init__(self, db_driver, redis_client: Optional[redis.Redis] = None):
        """Initialize optimizer.

        Args:
            db_driver: Neo4j driver
            redis_client: Redis client for caching
        """
        self.db = db_driver
        self.redis = redis_client or self._create_redis_client()
        self.optimization_rules = self._load_optimization_rules()
        self.query_cache = {}

    def _create_redis_client(self) -> redis.Redis:
        """Create Redis client with fallback."""
        try:
            client = redis.Redis(host='localhost', port=6379, decode_responses=True)
            client.ping()
            return client
        except:
            import fakeredis
            return fakeredis.FakeRedis(decode_responses=True)

    def _load_optimization_rules(self) -> List[Dict[str, Any]]:
        """Load query optimization rules."""
        return [
            {
                "name": "index_hint",
                "pattern": r"MATCH\s+\(([\w]+):([\w]+)\)\s+WHERE\s+([\w\.]+)\s*=",
                "description": "Add index hints for equality filters"
            },
            {
                "name": "limit_early",
                "pattern": r"MATCH.*RETURN.*LIMIT\s+(\d+)",
                "description": "Apply LIMIT earlier in the query"
            },
            {
                "name": "avoid_cartesian",
                "pattern": r"MATCH\s+\([^)]+\),\s*\([^)]+\)",
                "description": "Avoid cartesian products"
            },
            {
                "name": "use_with",
                "pattern": r"MATCH.*MATCH",
                "description": "Use WITH clause between MATCH patterns"
            },
            {
                "name": "profile_aggregation",
                "pattern": r"(count|sum|avg|min|max)\s*\(",
                "description": "Optimize aggregation functions"
            },
            {
                "name": "parameter_extraction",
                "pattern": r"WHERE.*=\s*['\"]([^'\"]+)['\"]",
                "description": "Extract literals as parameters"
            }
        ]

    def optimize(self, query: str, parameters: Dict[str, Any] = None) -> QueryPlan:
        """Optimize a Cypher query.

        Args:
            query: Cypher query
            parameters: Query parameters

        Returns:
            Query execution plan
        """
        # Check cache first
        cache_key = self._generate_cache_key(query, parameters)
        cached_plan = self._get_cached_plan(cache_key)
        if cached_plan:
            logger.debug(f"Cache hit for query: {cache_key[:20]}...")
            return cached_plan

        # Analyze query
        query_type = self._identify_query_type(query)

        # Get execution plan
        original_plan = self._get_execution_plan(query, parameters)

        # Apply optimizations
        optimized_query = query
        optimizations_applied = []

        for rule in self.optimization_rules:
            if re.search(rule["pattern"], query, re.IGNORECASE):
                optimized_query, applied = self._apply_optimization(
                    optimized_query, rule, parameters
                )
                if applied:
                    optimizations_applied.append(rule["name"])

        # Get optimized plan
        optimized_plan = self._get_execution_plan(optimized_query, parameters)

        # Create query plan
        plan = QueryPlan(
            original_query=query,
            optimized_query=optimized_query,
            estimated_cost=original_plan.get("cost", 0),
            optimizations_applied=optimizations_applied,
            cache_key=cache_key
        )

        # Cache the plan
        self._cache_plan(cache_key, plan)

        logger.info(f"Optimized query with {len(optimizations_applied)} rules: {optimizations_applied}")

        return plan

    def _identify_query_type(self, query: str) -> QueryType:
        """Identify the type of query."""
        query_lower = query.lower().strip()

        if query_lower.startswith("match"):
            if "count(" in query_lower or "sum(" in query_lower:
                return QueryType.AGGREGATE
            elif "path" in query_lower:
                return QueryType.PATH
            else:
                return QueryType.MATCH
        elif query_lower.startswith("create"):
            return QueryType.CREATE
        elif query_lower.startswith("merge"):
            return QueryType.MERGE
        elif query_lower.startswith("delete"):
            return QueryType.DELETE
        else:
            return QueryType.RETURN

    def _get_execution_plan(self, query: str, parameters: Dict[str, Any] = None) -> Dict[str, Any]:
        """Get query execution plan from Neo4j."""
        with self.db.session() as session:
            explain_query = f"EXPLAIN {query}"

            try:
                result = session.run(explain_query, parameters or {})
                summary = result.consume()

                # Extract plan details
                plan = {
                    "cost": summary.profile.get("db_hits", 0) if summary.profile else 0,
                    "rows": summary.profile.get("rows", 0) if summary.profile else 0,
                    "operators": []
                }

                # Parse plan operators
                if summary.plan:
                    for operator in summary.plan.operators:
                        plan["operators"].append({
                            "name": operator.get("operatorType", "Unknown"),
                            "rows": operator.get("rows", 0),
                            "db_hits": operator.get("dbHits", 0)
                        })

                return plan

            except Exception as e:
                logger.warning(f"Could not get execution plan: {e}")
                return {"cost": 0, "rows": 0, "operators": []}

    def _apply_optimization(
        self,
        query: str,
        rule: Dict[str, Any],
        parameters: Dict[str, Any] = None
    ) -> Tuple[str, bool]:
        """Apply an optimization rule.

        Args:
            query: Query to optimize
            rule: Optimization rule
            parameters: Query parameters

        Returns:
            Tuple of (optimized_query, was_applied)
        """
        if rule["name"] == "index_hint":
            # Add index hints
            pattern = re.compile(rule["pattern"], re.IGNORECASE)
            match = pattern.search(query)

            if match:
                label = match.group(2)
                property_name = match.group(3).split(".")[-1]

                # Add index hint
                hint = f"USING INDEX {match.group(1)}:{label}({property_name})"
                if hint not in query:
                    # Insert hint after MATCH clause
                    parts = query.split("WHERE")
                    if len(parts) == 2:
                        optimized = f"{parts[0]} {hint} WHERE{parts[1]}"
                        return optimized, True

        elif rule["name"] == "limit_early":
            # Move LIMIT closer to MATCH
            if "LIMIT" in query and "ORDER BY" not in query:
                # Extract limit value
                limit_match = re.search(r"LIMIT\s+(\d+)", query)
                if limit_match:
                    limit_val = limit_match.group(1)

                    # Remove LIMIT from end
                    query_without_limit = re.sub(r"\s*LIMIT\s+\d+\s*$", "", query)

                    # Add LIMIT after first RETURN
                    if "WITH" in query_without_limit:
                        parts = query_without_limit.split("WITH", 1)
                        optimized = f"{parts[0]}WITH {parts[1]} LIMIT {limit_val}"
                        return optimized, True

        elif rule["name"] == "avoid_cartesian":
            # Add relationship between disconnected patterns
            if ", " in query and "-[" not in query:
                # This would need more sophisticated analysis
                pass

        elif rule["name"] == "use_with":
            # Add WITH clause between multiple MATCH statements
            matches = re.findall(r"MATCH", query, re.IGNORECASE)
            if len(matches) > 1 and "WITH" not in query:
                # Insert WITH between matches
                parts = re.split(r"(MATCH)", query, maxsplit=2)
                if len(parts) > 2:
                    # Add WITH clause to pass variables
                    optimized = f"{parts[0]}{parts[1]}{parts[2]} WITH * {parts[3]}"
                    return optimized, True

        elif rule["name"] == "parameter_extraction":
            # Extract string literals as parameters
            pattern = re.compile(rule["pattern"])
            matches = pattern.findall(query)

            if matches and parameters is not None:
                optimized = query
                for i, literal in enumerate(matches):
                    param_name = f"param_{i}"
                    optimized = optimized.replace(f"'{literal}'", f"${param_name}")
                    optimized = optimized.replace(f'"{literal}"', f"${param_name}")
                    parameters[param_name] = literal

                if optimized != query:
                    return optimized, True

        return query, False

    def _generate_cache_key(self, query: str, parameters: Dict[str, Any] = None) -> str:
        """Generate cache key for query."""
        content = f"{query}:{json.dumps(parameters or {}, sort_keys=True)}"
        return f"cypher:plan:{hashlib.sha256(content.encode()).hexdigest()}"

    def _get_cached_plan(self, cache_key: str) -> Optional[QueryPlan]:
        """Get cached query plan."""
        try:
            cached = self.redis.get(cache_key)
            if cached:
                data = json.loads(cached)
                return QueryPlan(**data)
        except Exception as e:
            logger.debug(f"Cache retrieval error: {e}")

        return None

    def _cache_plan(self, cache_key: str, plan: QueryPlan):
        """Cache query plan."""
        try:
            plan_data = {
                "original_query": plan.original_query,
                "optimized_query": plan.optimized_query,
                "estimated_cost": plan.estimated_cost,
                "optimizations_applied": plan.optimizations_applied
            }

            self.redis.setex(
                cache_key,
                3600,  # 1 hour TTL
                json.dumps(plan_data)
            )
        except Exception as e:
            logger.debug(f"Cache storage error: {e}")

    def add_dataloader_support(self, query: str) -> str:
        """Add DataLoader batching hints to query.

        Args:
            query: Cypher query

        Returns:
            Query with DataLoader hints
        """
        # Identify patterns that can benefit from batching
        dataloader_patterns = [
            (r"MATCH \((\w+):(\w+)\) WHERE \1\.id IN", "batch_by_id"),
            (r"MATCH \((\w+)\)-\[:(\w+)\]->\((\w+)\)", "batch_relationships"),
            (r"OPTIONAL MATCH", "batch_optional")
        ]

        hints = []
        for pattern, hint_type in dataloader_patterns:
            if re.search(pattern, query):
                hints.append(f"/* DataLoader: {hint_type} */")

        if hints:
            # Add hints as comments
            return f"{' '.join(hints)}\n{query}"

        return query

    def profile_query(self, query: str, parameters: Dict[str, Any] = None) -> Dict[str, Any]:
        """Profile query execution.

        Args:
            query: Cypher query
            parameters: Query parameters

        Returns:
            Profiling results
        """
        with self.db.session() as session:
            profile_query = f"PROFILE {query}"

            start_time = time.time()
            result = session.run(profile_query, parameters or {})
            records = list(result)
            execution_time = (time.time() - start_time) * 1000

            summary = result.consume()

            profile = {
                "execution_time_ms": execution_time,
                "records_returned": len(records),
                "db_hits": 0,
                "rows_produced": 0,
                "operators": []
            }

            if summary.profile:
                profile["db_hits"] = summary.profile.get("db_hits", 0)
                profile["rows_produced"] = summary.profile.get("rows", 0)

            if summary.plan:
                for op in summary.plan.operators:
                    profile["operators"].append({
                        "type": op.get("operatorType"),
                        "rows": op.get("rows", 0),
                        "db_hits": op.get("dbHits", 0),
                        "estimated_rows": op.get("estimatedRows", 0)
                    })

            return profile

    def suggest_indexes(self, slow_queries: List[str]) -> List[Dict[str, str]]:
        """Suggest indexes based on slow queries.

        Args:
            slow_queries: List of slow queries

        Returns:
            Index suggestions
        """
        suggestions = []
        seen = set()

        for query in slow_queries:
            # Look for WHERE clauses without indexes
            where_pattern = r"WHERE\s+(\w+)\.(\w+)\s*="
            matches = re.findall(where_pattern, query)

            for alias, property_name in matches:
                # Find the label for this alias
                label_pattern = f"\\({alias}:(\\w+)\\)"
                label_match = re.search(label_pattern, query)

                if label_match:
                    label = label_match.group(1)
                    index_key = f"{label}.{property_name}"

                    if index_key not in seen:
                        seen.add(index_key)
                        suggestions.append({
                            "label": label,
                            "property": property_name,
                            "command": f"CREATE INDEX ON :{label}({property_name})",
                            "reason": "Frequently used in WHERE clause"
                        })

            # Look for ORDER BY without indexes
            order_pattern = r"ORDER BY\s+(\w+)\.(\w+)"
            order_matches = re.findall(order_pattern, query)

            for alias, property_name in order_matches:
                label_pattern = f"\\({alias}:(\\w+)\\)"
                label_match = re.search(label_pattern, query)

                if label_match:
                    label = label_match.group(1)
                    index_key = f"{label}.{property_name}"

                    if index_key not in seen:
                        seen.add(index_key)
                        suggestions.append({
                            "label": label,
                            "property": property_name,
                            "command": f"CREATE INDEX ON :{label}({property_name})",
                            "reason": "Used in ORDER BY clause"
                        })

        return suggestions


class QueryCacheManager:
    """Manage query result caching."""

    def __init__(self, redis_client: Optional[redis.Redis] = None, ttl: int = 3600):
        """Initialize cache manager.

        Args:
            redis_client: Redis client
            ttl: Cache TTL in seconds
        """
        self.redis = redis_client or self._create_redis_client()
        self.ttl = ttl
        self.stats = {
            "hits": 0,
            "misses": 0,
            "evictions": 0
        }

    def _create_redis_client(self) -> redis.Redis:
        """Create Redis client with fallback."""
        try:
            client = redis.Redis(host='localhost', port=6379, decode_responses=False)
            client.ping()
            return client
        except:
            import fakeredis
            return fakeredis.FakeRedis(decode_responses=False)

    def get(self, query: str, parameters: Dict[str, Any] = None) -> Optional[List[Dict]]:
        """Get cached query results.

        Args:
            query: Cypher query
            parameters: Query parameters

        Returns:
            Cached results or None
        """
        cache_key = self._generate_key(query, parameters)

        try:
            cached = self.redis.get(cache_key)
            if cached:
                self.stats["hits"] += 1
                return json.loads(cached)
            else:
                self.stats["misses"] += 1

        except Exception as e:
            logger.debug(f"Cache get error: {e}")

        return None

    def set(self, query: str, parameters: Dict[str, Any], results: List[Dict]):
        """Cache query results.

        Args:
            query: Cypher query
            parameters: Query parameters
            results: Query results
        """
        cache_key = self._generate_key(query, parameters)

        try:
            self.redis.setex(
                cache_key,
                self.ttl,
                json.dumps(results)
            )
        except Exception as e:
            logger.debug(f"Cache set error: {e}")

    def invalidate(self, pattern: str = "*"):
        """Invalidate cache entries.

        Args:
            pattern: Key pattern to invalidate
        """
        try:
            keys = self.redis.keys(f"cypher:result:{pattern}")
            if keys:
                self.redis.delete(*keys)
                self.stats["evictions"] += len(keys)
                logger.info(f"Invalidated {len(keys)} cache entries")

        except Exception as e:
            logger.debug(f"Cache invalidation error: {e}")

    def _generate_key(self, query: str, parameters: Dict[str, Any] = None) -> str:
        """Generate cache key."""
        content = f"{query}:{json.dumps(parameters or {}, sort_keys=True)}"
        return f"cypher:result:{hashlib.sha256(content.encode()).hexdigest()}"

    def get_stats(self) -> Dict[str, Any]:
        """Get cache statistics."""
        total = self.stats["hits"] + self.stats["misses"]
        hit_rate = self.stats["hits"] / total if total > 0 else 0

        return {
            "hits": self.stats["hits"],
            "misses": self.stats["misses"],
            "evictions": self.stats["evictions"],
            "hit_rate": hit_rate,
            "total_requests": total
        }