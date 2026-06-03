"""Optimized GraphQL API for BR-KG with caching and query optimization.

This module provides an optimized GraphQL interface with query caching,
DataLoader pattern, and performance monitoring.
"""

import hashlib
import json
import logging
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional, Union

import redis
from graphql import (
    GraphQLSchema,
    GraphQLObjectType,
    GraphQLField,
    GraphQLString,
    GraphQLList,
    GraphQLInt,
    GraphQLFloat,
    GraphQLBoolean,
    GraphQLArgument,
    graphql_sync,
)
from promise import Promise
from promise.dataloader import DataLoader

logger = logging.getLogger(__name__)


@dataclass
class QueryMetrics:
    """Query performance metrics."""

    query_hash: str
    execution_time_ms: float
    cache_hit: bool
    result_size: int
    timestamp: datetime


class QueryCache:
    """Redis-based query result cache."""

    def __init__(self, redis_client: Optional[redis.Redis] = None, ttl_seconds: int = 3600):
        """Initialize query cache.

        Args:
            redis_client: Redis client instance
            ttl_seconds: Cache TTL in seconds
        """
        self.redis = redis_client or self._create_redis_client()
        self.ttl = ttl_seconds
        self.metrics = []

    def _create_redis_client(self) -> redis.Redis:
        """Create Redis client with fallback."""
        try:
            client = redis.Redis(
                host='localhost',
                port=6379,
                decode_responses=True
            )
            client.ping()
            return client
        except:
            # Use fakeredis for testing
            import fakeredis
            return fakeredis.FakeRedis(decode_responses=True)

    def get(self, query: str, variables: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Get cached query result.

        Args:
            query: GraphQL query string
            variables: Query variables

        Returns:
            Cached result or None
        """
        cache_key = self._generate_key(query, variables)

        try:
            cached = self.redis.get(cache_key)
            if cached:
                logger.debug(f"Cache hit for query: {cache_key[:20]}...")
                return json.loads(cached)
        except Exception as e:
            logger.warning(f"Cache get error: {e}")

        return None

    def set(self, query: str, variables: Dict[str, Any], result: Dict[str, Any]):
        """Cache query result.

        Args:
            query: GraphQL query string
            variables: Query variables
            result: Query result
        """
        cache_key = self._generate_key(query, variables)

        try:
            self.redis.setex(
                cache_key,
                self.ttl,
                json.dumps(result)
            )
            logger.debug(f"Cached query result: {cache_key[:20]}...")
        except Exception as e:
            logger.warning(f"Cache set error: {e}")

    def invalidate(self, pattern: str):
        """Invalidate cache entries matching pattern.

        Args:
            pattern: Cache key pattern
        """
        try:
            keys = self.redis.keys(pattern)
            if keys:
                self.redis.delete(*keys)
                logger.info(f"Invalidated {len(keys)} cache entries")
        except Exception as e:
            logger.warning(f"Cache invalidation error: {e}")

    def _generate_key(self, query: str, variables: Dict[str, Any]) -> str:
        """Generate cache key from query and variables.

        Args:
            query: GraphQL query
            variables: Query variables

        Returns:
            Cache key
        """
        content = f"{query}:{json.dumps(variables, sort_keys=True)}"
        hash_obj = hashlib.sha256(content.encode())
        return f"graphql:query:{hash_obj.hexdigest()}"

    def record_metric(self, metric: QueryMetrics):
        """Record query performance metric.

        Args:
            metric: Query metric
        """
        self.metrics.append(metric)

        # Store in Redis for analysis
        metric_key = f"graphql:metrics:{metric.timestamp.isoformat()}"
        self.redis.setex(
            metric_key,
            86400,  # Keep metrics for 24 hours
            json.dumps({
                "query_hash": metric.query_hash,
                "execution_time_ms": metric.execution_time_ms,
                "cache_hit": metric.cache_hit,
                "result_size": metric.result_size,
                "timestamp": metric.timestamp.isoformat()
            })
        )


class ConceptLoader(DataLoader):
    """DataLoader for batching Concept queries."""

    def __init__(self, db_connection):
        """Initialize concept loader.

        Args:
            db_connection: Database connection
        """
        super().__init__()
        self.db = db_connection

    def batch_load_fn(self, concept_ids: List[str]) -> Promise:
        """Batch load concepts by IDs.

        Args:
            concept_ids: List of concept IDs

        Returns:
            Promise resolving to concepts
        """
        # Batch query to database
        query = """
            MATCH (c:Concept)
            WHERE coalesce(c.concept_id, c.id) IN $ids
            RETURN c
        """

        with self.db.session() as session:
            result = session.run(query, ids=concept_ids)
            concepts_dict = {
                (
                    (props := dict(record["c"])).get("concept_id") or props.get("id")
                ): props
                for record in result
            }

        # Return in same order as requested
        concepts = [concepts_dict.get(cid) for cid in concept_ids]
        return Promise.resolve(concepts)


class TaskLoader(DataLoader):
    """DataLoader for batching Task queries."""

    def __init__(self, db_connection):
        """Initialize task loader.

        Args:
            db_connection: Database connection
        """
        super().__init__()
        self.db = db_connection

    def batch_load_fn(self, task_ids: List[str]) -> Promise:
        """Batch load tasks by IDs.

        Args:
            task_ids: List of task IDs

        Returns:
            Promise resolving to tasks
        """
        query = """
            MATCH (t:Task)
            WHERE coalesce(t.task_id, t.id) IN $ids
            RETURN t
        """

        with self.db.session() as session:
            result = session.run(query, ids=task_ids)
            tasks_dict = {
                (
                    (props := dict(record["t"])).get("task_id") or props.get("id")
                ): props
                for record in result
            }

        tasks = [tasks_dict.get(tid) for tid in task_ids]
        return Promise.resolve(tasks)


class RegionLoader(DataLoader):
    """DataLoader for batching Region queries."""

    def __init__(self, db_connection):
        """Initialize region loader.

        Args:
            db_connection: Database connection
        """
        super().__init__()
        self.db = db_connection

    def batch_load_fn(self, region_ids: List[str]) -> Promise:
        """Batch load regions by IDs.

        Args:
            region_ids: List of region IDs

        Returns:
            Promise resolving to regions
        """
        query = """
            MATCH (r:Region)
            WHERE coalesce(r.region_id, r.id) IN $ids
            RETURN r
        """

        with self.db.session() as session:
            result = session.run(query, ids=region_ids)
            regions_dict = {
                (
                    (props := dict(record["r"])).get("region_id") or props.get("id")
                ): props
                for record in result
            }

        regions = [regions_dict.get(rid) for rid in region_ids]
        return Promise.resolve(regions)


class OptimizedGraphQLAPI:
    """Optimized GraphQL API with caching and DataLoader."""

    def __init__(self, db_connection, cache_ttl: int = 3600):
        """Initialize GraphQL API.

        Args:
            db_connection: Database connection
            cache_ttl: Cache TTL in seconds
        """
        self.db = db_connection
        self.cache = QueryCache(ttl_seconds=cache_ttl)

        # Initialize DataLoaders
        self.concept_loader = ConceptLoader(db_connection)
        self.task_loader = TaskLoader(db_connection)
        self.region_loader = RegionLoader(db_connection)

        # Build schema
        self.schema = self._build_schema()

    def _build_schema(self) -> GraphQLSchema:
        """Build GraphQL schema.

        Returns:
            GraphQL schema
        """
        # Define types
        concept_type = GraphQLObjectType(
            'Concept',
            lambda: {
                'id': GraphQLField(GraphQLString),
                'name': GraphQLField(GraphQLString),
                'definition': GraphQLField(GraphQLString),
                'ontology_id': GraphQLField(GraphQLString),
                'confidence_score': GraphQLField(GraphQLFloat),
                'tasks': GraphQLField(
                    GraphQLList(task_type),
                    resolve=self._resolve_concept_tasks
                ),
                'regions': GraphQLField(
                    GraphQLList(region_type),
                    resolve=self._resolve_concept_regions
                )
            }
        )

        task_type = GraphQLObjectType(
            'Task',
            lambda: {
                'id': GraphQLField(GraphQLString),
                'name': GraphQLField(GraphQLString),
                'dataset_id': GraphQLField(GraphQLString),
                'description': GraphQLField(GraphQLString),
                'concepts': GraphQLField(
                    GraphQLList(concept_type),
                    resolve=self._resolve_task_concepts
                )
            }
        )

        region_type = GraphQLObjectType(
            'Region',
            lambda: {
                'id': GraphQLField(GraphQLString),
                'name': GraphQLField(GraphQLString),
                'mni_coordinates': GraphQLField(GraphQLString),
                'atlas': GraphQLField(GraphQLString),
                'concepts': GraphQLField(
                    GraphQLList(concept_type),
                    resolve=self._resolve_region_concepts
                )
            }
        )

        publication_type = GraphQLObjectType(
            'Publication',
            fields={
                'pmid': GraphQLField(GraphQLString),
                'title': GraphQLField(GraphQLString),
                'authors': GraphQLField(GraphQLList(GraphQLString)),
                'year': GraphQLField(GraphQLInt),
                'journal': GraphQLField(GraphQLString),
                'doi': GraphQLField(GraphQLString)
            }
        )

        # Define queries
        query_type = GraphQLObjectType(
            'Query',
            fields={
                'concept': GraphQLField(
                    concept_type,
                    args={
                        'id': GraphQLArgument(GraphQLString),
                        'name': GraphQLArgument(GraphQLString)
                    },
                    resolve=self._resolve_concept
                ),
                'concepts': GraphQLField(
                    GraphQLList(concept_type),
                    args={
                        'limit': GraphQLArgument(GraphQLInt),
                        'offset': GraphQLArgument(GraphQLInt),
                        'ontology_id': GraphQLArgument(GraphQLString)
                    },
                    resolve=self._resolve_concepts
                ),
                'task': GraphQLField(
                    task_type,
                    args={
                        'id': GraphQLArgument(GraphQLString),
                        'name': GraphQLArgument(GraphQLString)
                    },
                    resolve=self._resolve_task
                ),
                'tasks': GraphQLField(
                    GraphQLList(task_type),
                    args={
                        'dataset_id': GraphQLArgument(GraphQLString),
                        'limit': GraphQLArgument(GraphQLInt)
                    },
                    resolve=self._resolve_tasks
                ),
                'region': GraphQLField(
                    region_type,
                    args={
                        'id': GraphQLArgument(GraphQLString),
                        'name': GraphQLArgument(GraphQLString)
                    },
                    resolve=self._resolve_region
                ),
                'searchPublications': GraphQLField(
                    GraphQLList(publication_type),
                    args={
                        'keyword': GraphQLArgument(GraphQLString),
                        'year': GraphQLArgument(GraphQLInt),
                        'limit': GraphQLArgument(GraphQLInt)
                    },
                    resolve=self._resolve_search_publications
                )
            }
        )

        return GraphQLSchema(query=query_type)

    def _resolve_concept(self, obj, info, **kwargs):
        """Resolve single concept.

        Args:
            obj: Parent object
            info: GraphQL info
            **kwargs: Query arguments

        Returns:
            Concept data
        """
        concept_id = kwargs.get('id')
        if concept_id:
            return self.concept_loader.load(concept_id).get()

        name = kwargs.get('name')
        if name:
            query = "MATCH (c:Concept {name: $name}) RETURN c LIMIT 1"
            with self.db.session() as session:
                result = session.run(query, name=name)
                record = result.single()
                return record["c"] if record else None

        return None

    def _resolve_concepts(self, obj, info, **kwargs):
        """Resolve multiple concepts.

        Args:
            obj: Parent object
            info: GraphQL info
            **kwargs: Query arguments

        Returns:
            List of concepts
        """
        limit = kwargs.get('limit', 100)
        offset = kwargs.get('offset', 0)
        ontology_id = kwargs.get('ontology_id')

        query = "MATCH (c:Concept)"
        if ontology_id:
            query += " WHERE c.ontology_id = $ontology_id"
        query += f" RETURN c SKIP {offset} LIMIT {limit}"

        with self.db.session() as session:
            params = {'ontology_id': ontology_id} if ontology_id else {}
            result = session.run(query, **params)
            return [record["c"] for record in result]

    def _resolve_task(self, obj, info, **kwargs):
        """Resolve single task.

        Args:
            obj: Parent object
            info: GraphQL info
            **kwargs: Query arguments

        Returns:
            Task data
        """
        task_id = kwargs.get('id')
        if task_id:
            return self.task_loader.load(task_id).get()

        name = kwargs.get('name')
        if name:
            query = "MATCH (t:Task {name: $name}) RETURN t LIMIT 1"
            with self.db.session() as session:
                result = session.run(query, name=name)
                record = result.single()
                return record["t"] if record else None

        return None

    def _resolve_tasks(self, obj, info, **kwargs):
        """Resolve multiple tasks.

        Args:
            obj: Parent object
            info: GraphQL info
            **kwargs: Query arguments

        Returns:
            List of tasks
        """
        dataset_id = kwargs.get('dataset_id')
        limit = kwargs.get('limit', 100)

        query = "MATCH (t:Task)"
        if dataset_id:
            query += " WHERE t.dataset_id = $dataset_id"
        query += f" RETURN t LIMIT {limit}"

        with self.db.session() as session:
            params = {'dataset_id': dataset_id} if dataset_id else {}
            result = session.run(query, **params)
            return [record["t"] for record in result]

    def _resolve_region(self, obj, info, **kwargs):
        """Resolve single region.

        Args:
            obj: Parent object
            info: GraphQL info
            **kwargs: Query arguments

        Returns:
            Region data
        """
        region_id = kwargs.get('id')
        if region_id:
            return self.region_loader.load(region_id).get()

        name = kwargs.get('name')
        if name:
            query = "MATCH (r:Region {name: $name}) RETURN r LIMIT 1"
            with self.db.session() as session:
                result = session.run(query, name=name)
                record = result.single()
                return record["r"] if record else None

        return None

    def _resolve_search_publications(self, obj, info, **kwargs):
        """Search publications.

        Args:
            obj: Parent object
            info: GraphQL info
            **kwargs: Query arguments

        Returns:
            List of publications
        """
        keyword = kwargs.get('keyword', '')
        year = kwargs.get('year')
        limit = kwargs.get('limit', 50)

        query = "MATCH (p:Publication)"
        conditions = []

        if keyword:
            conditions.append("(p.title CONTAINS $keyword OR p.abstract CONTAINS $keyword)")
        if year:
            conditions.append("p.year = $year")

        if conditions:
            query += " WHERE " + " AND ".join(conditions)
        query += f" RETURN p LIMIT {limit}"

        with self.db.session() as session:
            params = {}
            if keyword:
                params['keyword'] = keyword
            if year:
                params['year'] = year

            result = session.run(query, **params)
            return [record["p"] for record in result]

    def _resolve_concept_tasks(self, concept, info):
        """Resolve tasks for a concept.

        Args:
            concept: Concept object
            info: GraphQL info

        Returns:
            List of tasks
        """
        query = """
            MATCH (c:Concept {concept_id: $concept_id})<-[:MEASURES]-(t:Task)
            RETURN t
        """

        with self.db.session() as session:
            result = session.run(query, concept_id=concept['id'])
            return [record["t"] for record in result]

    def _resolve_concept_regions(self, concept, info):
        """Resolve regions for a concept.

        Args:
            concept: Concept object
            info: GraphQL info

        Returns:
            List of regions
        """
        query = """
            MATCH (c:Concept {concept_id: $concept_id})-[:ACTIVATES]->(r:Region)
            RETURN r
        """

        with self.db.session() as session:
            result = session.run(query, concept_id=concept['id'])
            return [record["r"] for record in result]

    def _resolve_task_concepts(self, task, info):
        """Resolve concepts for a task.

        Args:
            task: Task object
            info: GraphQL info

        Returns:
            List of concepts
        """
        query = """
            MATCH (t:Task {task_id: $task_id})-[:MEASURES]->(c:Concept)
            RETURN c
        """

        with self.db.session() as session:
            result = session.run(query, task_id=task['id'])
            return [record["c"] for record in result]

    def _resolve_region_concepts(self, region, info):
        """Resolve concepts for a region.

        Args:
            region: Region object
            info: GraphQL info

        Returns:
            List of concepts
        """
        query = """
            MATCH (r:Region {region_id: $region_id})<-[:ACTIVATES]-(c:Concept)
            RETURN c
        """

        with self.db.session() as session:
            result = session.run(query, region_id=region['id'])
            return [record["c"] for record in result]

    def execute_query(self, query: str, variables: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Execute GraphQL query with caching.

        Args:
            query: GraphQL query string
            variables: Query variables

        Returns:
            Query result
        """
        variables = variables or {}

        # Check cache
        cached_result = self.cache.get(query, variables)
        if cached_result:
            # Record cache hit metric
            metric = QueryMetrics(
                query_hash=hashlib.sha256(query.encode()).hexdigest()[:8],
                execution_time_ms=0,
                cache_hit=True,
                result_size=len(json.dumps(cached_result)),
                timestamp=datetime.utcnow()
            )
            self.cache.record_metric(metric)
            return cached_result

        # Execute query
        start_time = time.time()
        result = graphql_sync(
            self.schema,
            query,
            variable_values=variables,
            context_value={
                'concept_loader': self.concept_loader,
                'task_loader': self.task_loader,
                'region_loader': self.region_loader
            }
        )

        execution_time = (time.time() - start_time) * 1000

        # Convert result to dict
        result_dict = {
            'data': result.data,
            'errors': [str(e) for e in result.errors] if result.errors else None
        }

        # Cache successful results
        if not result.errors:
            self.cache.set(query, variables, result_dict)

        # Record metric
        metric = QueryMetrics(
            query_hash=hashlib.sha256(query.encode()).hexdigest()[:8],
            execution_time_ms=execution_time,
            cache_hit=False,
            result_size=len(json.dumps(result_dict)),
            timestamp=datetime.utcnow()
        )
        self.cache.record_metric(metric)

        return result_dict

    def invalidate_cache(self, entity_type: Optional[str] = None):
        """Invalidate cache entries.

        Args:
            entity_type: Type of entity to invalidate (e.g., 'Concept', 'Task')
        """
        if entity_type:
            pattern = f"graphql:query:*{entity_type}*"
        else:
            pattern = "graphql:query:*"

        self.cache.invalidate(pattern)

    def get_performance_stats(self) -> Dict[str, Any]:
        """Get performance statistics.

        Returns:
            Performance stats
        """
        # Get recent metrics from Redis
        metric_keys = self.cache.redis.keys("graphql:metrics:*")
        recent_metrics = []

        for key in metric_keys[-100:]:  # Last 100 queries
            metric_data = self.cache.redis.get(key)
            if metric_data:
                recent_metrics.append(json.loads(metric_data))

        if not recent_metrics:
            return {
                "total_queries": 0,
                "cache_hit_rate": 0,
                "avg_execution_time_ms": 0,
                "p95_execution_time_ms": 0
            }

        # Calculate statistics
        total_queries = len(recent_metrics)
        cache_hits = sum(1 for m in recent_metrics if m['cache_hit'])
        cache_hit_rate = cache_hits / total_queries if total_queries > 0 else 0

        execution_times = [m['execution_time_ms'] for m in recent_metrics if not m['cache_hit']]
        if execution_times:
            avg_execution_time = sum(execution_times) / len(execution_times)
            execution_times.sort()
            p95_index = int(len(execution_times) * 0.95)
            p95_execution_time = execution_times[p95_index] if p95_index < len(execution_times) else execution_times[-1]
        else:
            avg_execution_time = 0
            p95_execution_time = 0

        return {
            "total_queries": total_queries,
            "cache_hit_rate": cache_hit_rate,
            "avg_execution_time_ms": avg_execution_time,
            "p95_execution_time_ms": p95_execution_time,
            "recent_queries": recent_metrics[-10:]  # Last 10 queries
        }
