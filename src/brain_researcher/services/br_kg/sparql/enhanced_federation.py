"""Enhanced SPARQL federation for external knowledge graph integration.

This module provides advanced SPARQL federation capabilities for:
- Multi-endpoint query federation with intelligent routing
- Query optimization across federated sources
- Result merging and deduplication
- Caching strategies for external endpoint results
- Error handling and fallback mechanisms
- Performance monitoring and adaptive query planning
"""

import hashlib
import json
import logging
import time
import xml.etree.ElementTree as ET
from collections import defaultdict
from dataclasses import dataclass
from enum import Enum
from typing import Any

import redis
from SPARQLWrapper import GET, JSON, POST, XML, SPARQLWrapper

logger = logging.getLogger(__name__)


class EndpointType(str, Enum):
    """Types of SPARQL endpoints."""

    WIKIDATA = "wikidata"
    DBPEDIA = "dbpedia"
    PUBMED = "pubmed"
    BIOPORTAL = "bioportal"
    NEUROLEX = "neurolex"
    CUSTOM = "custom"


class QueryDistributionStrategy(str, Enum):
    """Strategies for distributing queries across endpoints."""

    PARALLEL = "parallel"  # Send to all endpoints in parallel
    SEQUENTIAL = "sequential"  # Send to endpoints sequentially
    PRIORITY = "priority"  # Send based on endpoint priority
    ADAPTIVE = "adaptive"  # Adapt based on endpoint performance


class ResultMergeStrategy(str, Enum):
    """Strategies for merging results from multiple endpoints."""

    UNION = "union"  # Union of all results
    INTERSECTION = "intersection"  # Intersection of results
    RANKED = "ranked"  # Ranked by relevance score
    WEIGHTED = "weighted"  # Weighted by endpoint reliability


@dataclass
class FederatedEndpoint:
    """Configuration for a federated SPARQL endpoint."""

    name: str
    endpoint_url: str
    endpoint_type: EndpointType
    priority: int = 1  # Higher priority = preferred endpoint
    timeout_seconds: int = 30
    max_retries: int = 3
    rate_limit_per_second: float = 1.0
    authentication: dict[str, str] | None = None
    custom_headers: dict[str, str] | None = None
    result_format: str = "json"  # json, xml, turtle

    # Performance tracking
    avg_response_time_ms: float = 0.0
    success_rate: float = 1.0
    last_error: str | None = None
    query_count: int = 0


@dataclass
class FederatedQuery:
    """A federated SPARQL query with endpoint routing."""

    query_id: str
    original_query: str
    endpoint_queries: dict[str, str]  # endpoint_name -> query
    distribution_strategy: QueryDistributionStrategy
    merge_strategy: ResultMergeStrategy
    timeout_seconds: int = 60
    max_results: int | None = None


@dataclass
class EndpointResult:
    """Result from a single endpoint."""

    endpoint_name: str
    query: str
    results: list[dict[str, Any]]
    execution_time_ms: float
    success: bool
    error_message: str | None = None
    result_count: int = 0
    cached: bool = False


@dataclass
class FederatedResult:
    """Combined result from federated query."""

    query_id: str
    endpoint_results: list[EndpointResult]
    merged_results: list[dict[str, Any]]
    total_execution_time_ms: float
    successful_endpoints: int
    total_endpoints: int
    merge_strategy: ResultMergeStrategy
    metadata: dict[str, Any]


class QueryOptimizer:
    """Optimizes SPARQL queries for federation."""

    def __init__(self):
        """Initialize query optimizer."""
        # Common prefixes for different knowledge graphs
        self.endpoint_prefixes = {
            EndpointType.WIKIDATA: {
                "wd": "http://www.wikidata.org/entity/",
                "wdt": "http://www.wikidata.org/prop/direct/",
                "wikibase": "http://wikiba.se/ontology#",
            },
            EndpointType.DBPEDIA: {
                "dbo": "http://dbpedia.org/ontology/",
                "dbr": "http://dbpedia.org/resource/",
                "dbp": "http://dbpedia.org/property/",
            },
            EndpointType.NEUROLEX: {
                "neurolex": "http://neurolex.org/wiki/",
                "nlx": "http://ontology.neuinfo.org/NIF/Backend/nlx_",
            },
        }

    def optimize_query_for_endpoint(
        self, query: str, endpoint: FederatedEndpoint
    ) -> str:
        """Optimize query for specific endpoint.

        Args:
            query: Original SPARQL query
            endpoint: Target endpoint

        Returns:
            Optimized query for the endpoint
        """
        optimized_query = query

        # Add endpoint-specific prefixes
        prefixes = self.endpoint_prefixes.get(endpoint.endpoint_type, {})
        prefix_lines = []

        for prefix, uri in prefixes.items():
            if f"{prefix}:" in query and f"PREFIX {prefix}:" not in query:
                prefix_lines.append(f"PREFIX {prefix}: <{uri}>")

        if prefix_lines:
            optimized_query = "\n".join(prefix_lines) + "\n" + query

        # Add endpoint-specific optimizations
        if endpoint.endpoint_type == EndpointType.WIKIDATA:
            optimized_query = self._optimize_for_wikidata(optimized_query)
        elif endpoint.endpoint_type == EndpointType.DBPEDIA:
            optimized_query = self._optimize_for_dbpedia(optimized_query)

        # Add LIMIT if not present and endpoint has limitations
        if "LIMIT" not in optimized_query.upper():
            if endpoint.endpoint_type in [EndpointType.WIKIDATA, EndpointType.DBPEDIA]:
                optimized_query += "\nLIMIT 1000"

        return optimized_query

    def _optimize_for_wikidata(self, query: str) -> str:
        """Apply Wikidata-specific optimizations."""
        # Use SERVICE hint for better performance
        if "SERVICE" not in query:
            # Add service hint for better query planning
            optimized = query.replace(
                "SELECT", "SELECT"  # Would add wikidata-specific hints in production
            )
            return optimized
        return query

    def _optimize_for_dbpedia(self, query: str) -> str:
        """Apply DBpedia-specific optimizations."""
        # Add language filters for better performance
        if "FILTER" not in query and "rdfs:label" in query:
            # Would add language filters in production
            pass
        return query

    def detect_federated_queries(self, query: str) -> list[str]:
        """Detect which endpoints a query should be sent to.

        Args:
            query: SPARQL query

        Returns:
            List of endpoint types the query should target
        """
        relevant_endpoints = []
        query_lower = query.lower()

        # Wikidata patterns
        if any(
            pattern in query_lower for pattern in ["wikidata", "wd:", "wdt:", "p31"]
        ):
            relevant_endpoints.append(EndpointType.WIKIDATA)

        # DBpedia patterns
        if any(pattern in query_lower for pattern in ["dbpedia", "dbo:", "dbr:"]):
            relevant_endpoints.append(EndpointType.DBPEDIA)

        # NeuroLex patterns
        if any(
            pattern in query_lower
            for pattern in ["neurolex", "nlx:", "brain", "neuron"]
        ):
            relevant_endpoints.append(EndpointType.NEUROLEX)

        # Default to Wikidata and DBpedia if no specific patterns found
        if not relevant_endpoints:
            relevant_endpoints = [EndpointType.WIKIDATA, EndpointType.DBPEDIA]

        return relevant_endpoints


class ResultMerger:
    """Merges results from multiple federated endpoints."""

    def merge_results(
        self,
        endpoint_results: list[EndpointResult],
        strategy: ResultMergeStrategy,
        max_results: int | None = None,
    ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        """Merge results from multiple endpoints.

        Args:
            endpoint_results: Results from endpoints
            strategy: Merge strategy
            max_results: Maximum results to return

        Returns:
            Tuple of (merged_results, merge_metadata)
        """
        successful_results = [r for r in endpoint_results if r.success]

        if not successful_results:
            return [], {"error": "No successful endpoint results"}

        if strategy == ResultMergeStrategy.UNION:
            return self._merge_union(successful_results, max_results)
        elif strategy == ResultMergeStrategy.INTERSECTION:
            return self._merge_intersection(successful_results, max_results)
        elif strategy == ResultMergeStrategy.RANKED:
            return self._merge_ranked(successful_results, max_results)
        elif strategy == ResultMergeStrategy.WEIGHTED:
            return self._merge_weighted(successful_results, max_results)
        else:
            return self._merge_union(successful_results, max_results)

    def _merge_union(
        self, results: list[EndpointResult], max_results: int | None
    ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        """Merge results using union strategy."""
        all_results = []
        seen_results = set()

        for endpoint_result in results:
            for result in endpoint_result.results:
                # Create a hash for deduplication
                result_hash = self._hash_result(result)

                if result_hash not in seen_results:
                    seen_results.add(result_hash)
                    # Add source endpoint info
                    result_with_source = result.copy()
                    result_with_source["_source_endpoint"] = (
                        endpoint_result.endpoint_name
                    )
                    all_results.append(result_with_source)

        # Limit results if specified
        if max_results:
            all_results = all_results[:max_results]

        metadata = {
            "strategy": "union",
            "total_unique_results": len(all_results),
            "duplicates_removed": sum(len(r.results) for r in results)
            - len(all_results),
            "contributing_endpoints": len(results),
        }

        return all_results, metadata

    def _merge_intersection(
        self, results: list[EndpointResult], max_results: int | None
    ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        """Merge results using intersection strategy."""
        if len(results) < 2:
            return self._merge_union(results, max_results)

        # Find results that appear in all endpoints
        result_counts = defaultdict(list)

        for endpoint_result in results:
            for result in endpoint_result.results:
                result_hash = self._hash_result(result)
                result_counts[result_hash].append(
                    (endpoint_result.endpoint_name, result)
                )

        # Keep only results that appear in all endpoints
        intersection_results = []
        required_count = len(results)

        for result_hash, endpoint_results in result_counts.items():
            if len(endpoint_results) == required_count:
                # Use result from first endpoint, but add source info
                result = endpoint_results[0][1].copy()
                result["_source_endpoints"] = [er[0] for er in endpoint_results]
                intersection_results.append(result)

        if max_results:
            intersection_results = intersection_results[:max_results]

        metadata = {
            "strategy": "intersection",
            "intersection_count": len(intersection_results),
            "total_unique_results": len(result_counts),
            "agreement_endpoints": required_count,
        }

        return intersection_results, metadata

    def _merge_ranked(
        self, results: list[EndpointResult], max_results: int | None
    ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        """Merge results using ranking strategy."""
        all_results_with_scores = []

        for endpoint_result in results:
            # Calculate endpoint reliability score
            endpoint_score = (
                endpoint_result.execution_time_ms / 10000.0
            )  # Lower is better

            for i, result in enumerate(endpoint_result.results):
                # Calculate position score (earlier results ranked higher)
                position_score = 1.0 / (i + 1)

                # Combined score
                combined_score = position_score - endpoint_score

                result_with_score = result.copy()
                result_with_score["_source_endpoint"] = endpoint_result.endpoint_name
                result_with_score["_relevance_score"] = combined_score

                all_results_with_scores.append(result_with_score)

        # Sort by relevance score
        all_results_with_scores.sort(key=lambda x: x["_relevance_score"], reverse=True)

        # Remove duplicates while preserving ranking
        seen_results = set()
        ranked_results = []

        for result in all_results_with_scores:
            result_hash = self._hash_result(result)
            if result_hash not in seen_results:
                seen_results.add(result_hash)
                ranked_results.append(result)

        if max_results:
            ranked_results = ranked_results[:max_results]

        metadata = {
            "strategy": "ranked",
            "ranked_count": len(ranked_results),
            "score_range": [
                (
                    min(r["_relevance_score"] for r in ranked_results)
                    if ranked_results
                    else 0
                ),
                (
                    max(r["_relevance_score"] for r in ranked_results)
                    if ranked_results
                    else 0
                ),
            ],
        }

        return ranked_results, metadata

    def _merge_weighted(
        self, results: list[EndpointResult], max_results: int | None
    ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        """Merge results using weighted strategy."""
        # Calculate weights based on endpoint performance
        total_response_time = sum(r.execution_time_ms for r in results)

        weighted_results = []

        for endpoint_result in results:
            # Weight based on inverse of response time (faster = higher weight)
            if total_response_time > 0:
                weight = (
                    total_response_time - endpoint_result.execution_time_ms
                ) / total_response_time
            else:
                weight = 1.0 / len(results)

            for result in endpoint_result.results:
                result_with_weight = result.copy()
                result_with_weight["_source_endpoint"] = endpoint_result.endpoint_name
                result_with_weight["_endpoint_weight"] = weight
                weighted_results.append(result_with_weight)

        # Sort by weight
        weighted_results.sort(key=lambda x: x["_endpoint_weight"], reverse=True)

        # Remove duplicates
        seen_results = set()
        final_results = []

        for result in weighted_results:
            result_hash = self._hash_result(result)
            if result_hash not in seen_results:
                seen_results.add(result_hash)
                final_results.append(result)

        if max_results:
            final_results = final_results[:max_results]

        metadata = {
            "strategy": "weighted",
            "weighted_count": len(final_results),
            "endpoint_weights": {
                result["_source_endpoint"]: result["_endpoint_weight"]
                for result in final_results[:10]  # Sample weights
            },
        }

        return final_results, metadata

    def _hash_result(self, result: dict[str, Any]) -> str:
        """Create hash for result deduplication."""
        # Remove source-specific fields for comparison
        clean_result = {k: v for k, v in result.items() if not k.startswith("_")}

        # Sort keys for consistent hashing
        result_str = json.dumps(clean_result, sort_keys=True)
        return hashlib.md5(result_str.encode()).hexdigest()


class FederatedSPARQLEngine:
    """Advanced federated SPARQL query engine."""

    def __init__(self, redis_client: redis.Redis | None = None):
        """Initialize federated SPARQL engine.

        Args:
            redis_client: Redis client for caching
        """
        self.endpoints: dict[str, FederatedEndpoint] = {}
        self.query_optimizer = QueryOptimizer()
        self.result_merger = ResultMerger()

        # Initialize Redis for caching
        if redis_client:
            self.redis = redis_client
        else:
            try:
                self.redis = redis.Redis(
                    host="localhost", port=6379, decode_responses=True
                )
                self.redis.ping()
            except:
                import fakeredis

                self.redis = fakeredis.FakeRedis(decode_responses=True)

        # Performance tracking
        self.federation_stats = {
            "queries_executed": 0,
            "successful_queries": 0,
            "cache_hits": 0,
            "avg_federation_time_ms": 0.0,
            "endpoint_success_rates": defaultdict(float),
        }

        # Initialize default endpoints
        self._initialize_default_endpoints()

        logger.info("Initialized FederatedSPARQLEngine")

    def _initialize_default_endpoints(self):
        """Initialize default external SPARQL endpoints."""
        default_endpoints = [
            FederatedEndpoint(
                name="wikidata",
                endpoint_url="https://query.wikidata.org/sparql",
                endpoint_type=EndpointType.WIKIDATA,
                priority=3,
                timeout_seconds=30,
                rate_limit_per_second=0.5,  # Respect Wikidata limits
            ),
            FederatedEndpoint(
                name="dbpedia",
                endpoint_url="https://dbpedia.org/sparql",
                endpoint_type=EndpointType.DBPEDIA,
                priority=2,
                timeout_seconds=25,
                rate_limit_per_second=1.0,
            ),
            # Add more endpoints as needed
        ]

        for endpoint in default_endpoints:
            self.register_endpoint(endpoint)

    def register_endpoint(self, endpoint: FederatedEndpoint):
        """Register a new federated endpoint.

        Args:
            endpoint: Endpoint configuration
        """
        self.endpoints[endpoint.name] = endpoint
        logger.info(f"Registered federated endpoint: {endpoint.name}")

    def execute_federated_query(
        self,
        query: str,
        distribution_strategy: QueryDistributionStrategy = QueryDistributionStrategy.PARALLEL,
        merge_strategy: ResultMergeStrategy = ResultMergeStrategy.UNION,
        max_results: int | None = None,
        timeout_seconds: int = 60,
    ) -> FederatedResult:
        """Execute a federated SPARQL query.

        Args:
            query: SPARQL query
            distribution_strategy: How to distribute query
            merge_strategy: How to merge results
            max_results: Maximum results to return
            timeout_seconds: Query timeout

        Returns:
            Federated query result
        """
        start_time = time.time()
        query_id = hashlib.md5(query.encode()).hexdigest()[:12]

        self.federation_stats["queries_executed"] += 1

        # Determine relevant endpoints
        relevant_endpoint_types = self.query_optimizer.detect_federated_queries(query)
        relevant_endpoints = [
            endpoint
            for endpoint in self.endpoints.values()
            if endpoint.endpoint_type in relevant_endpoint_types
        ]

        if not relevant_endpoints:
            relevant_endpoints = list(self.endpoints.values())

        # Create optimized queries for each endpoint
        endpoint_queries = {}
        for endpoint in relevant_endpoints:
            optimized_query = self.query_optimizer.optimize_query_for_endpoint(
                query, endpoint
            )
            endpoint_queries[endpoint.name] = optimized_query

        # Execute queries based on distribution strategy
        if distribution_strategy == QueryDistributionStrategy.PARALLEL:
            endpoint_results = self._execute_parallel(
                endpoint_queries, relevant_endpoints, timeout_seconds
            )
        elif distribution_strategy == QueryDistributionStrategy.SEQUENTIAL:
            endpoint_results = self._execute_sequential(
                endpoint_queries, relevant_endpoints, timeout_seconds
            )
        else:
            endpoint_results = self._execute_parallel(
                endpoint_queries, relevant_endpoints, timeout_seconds
            )

        # Merge results
        merged_results, merge_metadata = self.result_merger.merge_results(
            endpoint_results, merge_strategy, max_results
        )

        # Calculate execution time
        total_execution_time_ms = (time.time() - start_time) * 1000

        # Update endpoint performance stats
        self._update_endpoint_stats(endpoint_results)

        # Create federated result
        successful_endpoints = sum(1 for r in endpoint_results if r.success)

        result = FederatedResult(
            query_id=query_id,
            endpoint_results=endpoint_results,
            merged_results=merged_results,
            total_execution_time_ms=total_execution_time_ms,
            successful_endpoints=successful_endpoints,
            total_endpoints=len(endpoint_results),
            merge_strategy=merge_strategy,
            metadata={
                "distribution_strategy": distribution_strategy.value,
                "merge_metadata": merge_metadata,
                "cache_hits": sum(1 for r in endpoint_results if r.cached),
                "original_query": query,
            },
        )

        # Update federation stats
        if successful_endpoints > 0:
            self.federation_stats["successful_queries"] += 1

        self._update_federation_stats(total_execution_time_ms)

        logger.info(
            f"Federated query {query_id} completed: {successful_endpoints}/{len(endpoint_results)} endpoints successful"
        )

        return result

    def _execute_parallel(
        self,
        endpoint_queries: dict[str, str],
        endpoints: list[FederatedEndpoint],
        timeout_seconds: int,
    ) -> list[EndpointResult]:
        """Execute queries in parallel across endpoints."""
        import concurrent.futures

        endpoint_results = []

        with concurrent.futures.ThreadPoolExecutor(
            max_workers=len(endpoints)
        ) as executor:
            # Submit all queries
            future_to_endpoint = {}

            for endpoint in endpoints:
                if endpoint.name in endpoint_queries:
                    future = executor.submit(
                        self._execute_single_endpoint,
                        endpoint,
                        endpoint_queries[endpoint.name],
                        timeout_seconds,
                    )
                    future_to_endpoint[future] = endpoint

            # Collect results
            for future in concurrent.futures.as_completed(
                future_to_endpoint, timeout=timeout_seconds
            ):
                try:
                    result = future.result()
                    endpoint_results.append(result)
                except concurrent.futures.TimeoutError:
                    endpoint = future_to_endpoint[future]
                    error_result = EndpointResult(
                        endpoint_name=endpoint.name,
                        query=endpoint_queries.get(endpoint.name, ""),
                        results=[],
                        execution_time_ms=timeout_seconds * 1000,
                        success=False,
                        error_message="Query timeout",
                    )
                    endpoint_results.append(error_result)
                except Exception as e:
                    endpoint = future_to_endpoint[future]
                    error_result = EndpointResult(
                        endpoint_name=endpoint.name,
                        query=endpoint_queries.get(endpoint.name, ""),
                        results=[],
                        execution_time_ms=0,
                        success=False,
                        error_message=str(e),
                    )
                    endpoint_results.append(error_result)

        return endpoint_results

    def _execute_sequential(
        self,
        endpoint_queries: dict[str, str],
        endpoints: list[FederatedEndpoint],
        timeout_seconds: int,
    ) -> list[EndpointResult]:
        """Execute queries sequentially across endpoints."""
        endpoint_results = []

        # Sort endpoints by priority
        sorted_endpoints = sorted(endpoints, key=lambda x: x.priority, reverse=True)

        for endpoint in sorted_endpoints:
            if endpoint.name in endpoint_queries:
                result = self._execute_single_endpoint(
                    endpoint, endpoint_queries[endpoint.name], timeout_seconds
                )
                endpoint_results.append(result)

                # Early termination if we got enough results
                if result.success and len(result.results) >= 100:
                    logger.info(
                        f"Early termination after {endpoint.name} returned {len(result.results)} results"
                    )
                    break

        return endpoint_results

    def _execute_single_endpoint(
        self, endpoint: FederatedEndpoint, query: str, timeout_seconds: int
    ) -> EndpointResult:
        """Execute query on a single endpoint.

        Args:
            endpoint: Endpoint to query
            query: SPARQL query
            timeout_seconds: Query timeout

        Returns:
            Endpoint result
        """
        start_time = time.time()

        # Check cache first
        cache_key = f"sparql:{endpoint.name}:{hashlib.md5(query.encode()).hexdigest()}"
        cached_result = self._get_cached_result(cache_key)

        if cached_result:
            cached_result.cached = True
            self.federation_stats["cache_hits"] += 1
            return cached_result

        try:
            # Create SPARQL wrapper
            sparql = SPARQLWrapper(endpoint.endpoint_url)
            sparql.setQuery(query)
            sparql.setReturnFormat(JSON if endpoint.result_format == "json" else XML)
            sparql.setTimeout(min(timeout_seconds, endpoint.timeout_seconds))

            # Set HTTP method
            sparql.method = POST if len(query) > 2000 else GET

            # Add custom headers
            if endpoint.custom_headers:
                for header, value in endpoint.custom_headers.items():
                    sparql.addCustomHttpHeader(header, value)

            # Execute query with retries
            results = []
            last_error = None

            for attempt in range(endpoint.max_retries + 1):
                try:
                    if attempt > 0:
                        time.sleep(2**attempt)  # Exponential backoff

                    response = sparql.query()

                    if endpoint.result_format == "json":
                        json_result = response.convert()
                        if (
                            "results" in json_result
                            and "bindings" in json_result["results"]
                        ):
                            results = self._convert_sparql_json_results(
                                json_result["results"]["bindings"]
                            )
                    else:
                        # Handle XML results
                        results = self._convert_sparql_xml_results(
                            response.response.read()
                        )

                    break  # Successful execution

                except Exception as e:
                    last_error = str(e)
                    logger.warning(
                        f"Attempt {attempt + 1} failed for {endpoint.name}: {e}"
                    )

            execution_time_ms = (time.time() - start_time) * 1000

            # Create result
            endpoint_result = EndpointResult(
                endpoint_name=endpoint.name,
                query=query,
                results=results,
                execution_time_ms=execution_time_ms,
                success=len(results) > 0 or last_error is None,
                error_message=last_error,
                result_count=len(results),
            )

            # Cache successful results
            if endpoint_result.success and results:
                self._cache_result(cache_key, endpoint_result)

            # Update endpoint stats
            endpoint.query_count += 1
            endpoint.avg_response_time_ms = (
                endpoint.avg_response_time_ms * (endpoint.query_count - 1)
                + execution_time_ms
            ) / endpoint.query_count

            if endpoint_result.success:
                endpoint.success_rate = (
                    endpoint.success_rate * (endpoint.query_count - 1) + 1.0
                ) / endpoint.query_count
            else:
                endpoint.success_rate = (
                    endpoint.success_rate * (endpoint.query_count - 1) + 0.0
                ) / endpoint.query_count
                endpoint.last_error = last_error

            return endpoint_result

        except Exception as e:
            execution_time_ms = (time.time() - start_time) * 1000

            logger.error(f"Endpoint {endpoint.name} query failed: {e}")

            return EndpointResult(
                endpoint_name=endpoint.name,
                query=query,
                results=[],
                execution_time_ms=execution_time_ms,
                success=False,
                error_message=str(e),
            )

    def _convert_sparql_json_results(
        self, bindings: list[dict]
    ) -> list[dict[str, Any]]:
        """Convert SPARQL JSON results to standard format."""
        converted_results = []

        for binding in bindings:
            result = {}
            for var, value_info in binding.items():
                if "value" in value_info:
                    result[var] = value_info["value"]
                else:
                    result[var] = str(value_info)
            converted_results.append(result)

        return converted_results

    def _convert_sparql_xml_results(self, xml_data: bytes) -> list[dict[str, Any]]:
        """Convert SPARQL XML results to standard format."""
        try:
            root = ET.fromstring(xml_data)

            # Find results
            results = []
            for result_elem in root.findall(
                ".//{http://www.w3.org/2005/sparql-results#}result"
            ):
                result = {}
                for binding_elem in result_elem.findall(
                    ".//{http://www.w3.org/2005/sparql-results#}binding"
                ):
                    var_name = binding_elem.get("name")

                    # Get value
                    value_elem = binding_elem.find(
                        ".//{http://www.w3.org/2005/sparql-results#}uri"
                    ) or binding_elem.find(
                        ".//{http://www.w3.org/2005/sparql-results#}literal"
                    )

                    if value_elem is not None:
                        result[var_name] = value_elem.text

                if result:
                    results.append(result)

            return results

        except Exception as e:
            logger.error(f"Failed to parse XML results: {e}")
            return []

    def _get_cached_result(self, cache_key: str) -> EndpointResult | None:
        """Get cached endpoint result."""
        try:
            cached_data = self.redis.get(cache_key)
            if cached_data:
                result_dict = json.loads(cached_data)
                return EndpointResult(
                    endpoint_name=result_dict["endpoint_name"],
                    query=result_dict["query"],
                    results=result_dict["results"],
                    execution_time_ms=result_dict["execution_time_ms"],
                    success=result_dict["success"],
                    error_message=result_dict.get("error_message"),
                    result_count=result_dict["result_count"],
                    cached=True,
                )
        except Exception as e:
            logger.warning(f"Cache retrieval failed: {e}")

        return None

    def _cache_result(self, cache_key: str, result: EndpointResult, ttl: int = 3600):
        """Cache endpoint result."""
        try:
            result_dict = {
                "endpoint_name": result.endpoint_name,
                "query": result.query,
                "results": result.results,
                "execution_time_ms": result.execution_time_ms,
                "success": result.success,
                "error_message": result.error_message,
                "result_count": result.result_count,
            }

            self.redis.setex(cache_key, ttl, json.dumps(result_dict))
        except Exception as e:
            logger.warning(f"Cache storage failed: {e}")

    def _update_endpoint_stats(self, endpoint_results: list[EndpointResult]):
        """Update endpoint performance statistics."""
        for result in endpoint_results:
            endpoint_name = result.endpoint_name
            if result.success:
                self.federation_stats["endpoint_success_rates"][endpoint_name] = (
                    self.federation_stats["endpoint_success_rates"][endpoint_name] + 1.0
                ) / 2.0
            else:
                self.federation_stats["endpoint_success_rates"][endpoint_name] = (
                    self.federation_stats["endpoint_success_rates"][endpoint_name] / 2.0
                )

    def _update_federation_stats(self, execution_time_ms: float):
        """Update federation performance statistics."""
        current_avg = self.federation_stats["avg_federation_time_ms"]
        total_queries = self.federation_stats["queries_executed"]

        self.federation_stats["avg_federation_time_ms"] = (
            current_avg * (total_queries - 1) + execution_time_ms
        ) / total_queries

    def get_federation_statistics(self) -> dict[str, Any]:
        """Get comprehensive federation statistics."""
        endpoint_stats = {}
        for name, endpoint in self.endpoints.items():
            endpoint_stats[name] = {
                "endpoint_type": endpoint.endpoint_type.value,
                "priority": endpoint.priority,
                "query_count": endpoint.query_count,
                "avg_response_time_ms": endpoint.avg_response_time_ms,
                "success_rate": endpoint.success_rate,
                "last_error": endpoint.last_error,
            }

        return {
            **self.federation_stats,
            "registered_endpoints": len(self.endpoints),
            "endpoint_statistics": endpoint_stats,
            "cache_size": (
                len(self.redis.keys("sparql:*")) if hasattr(self.redis, "keys") else 0
            ),
        }

    def clear_cache(self, endpoint_name: str | None = None):
        """Clear federation cache.

        Args:
            endpoint_name: Clear cache for specific endpoint, or all if None
        """
        try:
            if endpoint_name:
                pattern = f"sparql:{endpoint_name}:*"
            else:
                pattern = "sparql:*"

            keys = self.redis.keys(pattern)
            if keys:
                self.redis.delete(*keys)
                logger.info(f"Cleared {len(keys)} cache entries")
        except Exception as e:
            logger.warning(f"Cache clearing failed: {e}")
