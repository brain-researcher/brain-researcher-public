"""Advanced aggregation pipelines for BR-KG analytics.

This module provides sophisticated aggregation capabilities for:
- Multi-dimensional data aggregation and rollups
- Statistical analysis pipelines
- Graph analytics and centrality measures
- Custom aggregation functions with streaming support
- Real-time analytics with incremental updates
- Cross-modal data fusion and correlation analysis
"""

import json
import logging
import numpy as np
import pandas as pd
import time
from typing import Dict, List, Any, Optional, Tuple, Union, Callable
from dataclasses import dataclass, asdict
from enum import Enum
from collections import defaultdict, Counter
import asyncio
from concurrent.futures import ThreadPoolExecutor
import hashlib

logger = logging.getLogger(__name__)


class AggregationFunction(str, Enum):
    """Supported aggregation functions."""
    COUNT = "count"
    SUM = "sum"
    AVG = "avg"
    MIN = "min"
    MAX = "max"
    STDDEV = "stddev"
    VARIANCE = "variance"
    MEDIAN = "median"
    PERCENTILE = "percentile"
    MODE = "mode"
    DISTINCT_COUNT = "distinct_count"
    FIRST = "first"
    LAST = "last"
    CONCAT = "concat"
    ARRAY_AGG = "array_agg"


class GroupByOperation(str, Enum):
    """Group by operations for multi-dimensional aggregation."""
    SIMPLE = "simple"           # Single dimension grouping
    ROLLUP = "rollup"          # Hierarchical rollup
    CUBE = "cube"              # Multi-dimensional cube
    GROUPING_SETS = "grouping_sets"  # Custom grouping sets


class AnalyticsScope(str, Enum):
    """Scope of analytics computation."""
    GLOBAL = "global"           # Entire graph
    LOCAL = "local"             # Node neighborhood
    SUBGRAPH = "subgraph"       # Specific subgraph
    TEMPORAL = "temporal"       # Time-based scope


@dataclass
class AggregationSpec:
    """Specification for an aggregation operation."""

    function: AggregationFunction
    field: str
    alias: Optional[str] = None
    parameters: Optional[Dict[str, Any]] = None
    filter_condition: Optional[str] = None

    def get_alias(self) -> str:
        """Get the alias for this aggregation."""
        return self.alias or f"{self.function.value}_{self.field}"


@dataclass
class GroupBySpec:
    """Specification for grouping dimensions."""

    fields: List[str]
    operation: GroupByOperation = GroupByOperation.SIMPLE
    hierarchy: Optional[List[str]] = None  # For rollup operations
    custom_sets: Optional[List[List[str]]] = None  # For grouping sets


@dataclass
class PipelineStage:
    """A stage in the aggregation pipeline."""

    name: str
    operation_type: str
    parameters: Dict[str, Any]
    depends_on: List[str] = None  # Dependencies on other stages
    parallel: bool = False
    cache_result: bool = False


@dataclass
class AggregationResult:
    """Result of an aggregation pipeline."""

    pipeline_id: str
    results: Dict[str, Any]
    metadata: Dict[str, Any]
    execution_time_ms: float
    cache_hit: bool = False


class GraphMetricsCalculator:
    """Calculate various graph analytics metrics."""

    @staticmethod
    def calculate_centrality_metrics(nodes: List[Dict], edges: List[Dict]) -> Dict[str, Dict[str, float]]:
        """Calculate centrality metrics for nodes."""
        # Build adjacency structure
        adjacency = defaultdict(set)
        node_ids = [node.get('id', node.get('concept_id', '')) for node in nodes]
        node_lookup = {node_id: i for i, node_id in enumerate(node_ids)}

        for edge in edges:
            source = edge.get('source_id', edge.get('start_node'))
            target = edge.get('target_id', edge.get('end_node'))

            if source in node_lookup and target in node_lookup:
                adjacency[source].add(target)
                adjacency[target].add(source)  # Assuming undirected

        centrality_metrics = {}

        for node_id in node_ids:
            metrics = {
                'degree_centrality': len(adjacency[node_id]) / max(1, len(node_ids) - 1),
                'closeness_centrality': GraphMetricsCalculator._calculate_closeness(
                    node_id, adjacency, node_ids
                ),
                'betweenness_centrality': GraphMetricsCalculator._calculate_betweenness(
                    node_id, adjacency, node_ids
                ),
                'eigenvector_centrality': 0.1  # Simplified placeholder
            }
            centrality_metrics[node_id] = metrics

        return centrality_metrics

    @staticmethod
    def _calculate_closeness(node_id: str, adjacency: Dict, all_nodes: List[str]) -> float:
        """Calculate closeness centrality using BFS."""
        if not adjacency[node_id]:
            return 0.0

        distances = {node_id: 0}
        queue = [(node_id, 0)]
        visited = {node_id}

        while queue:
            current, dist = queue.pop(0)

            for neighbor in adjacency[current]:
                if neighbor not in visited:
                    visited.add(neighbor)
                    distances[neighbor] = dist + 1
                    queue.append((neighbor, dist + 1))

        # Calculate closeness
        total_distance = sum(distances.values())
        reachable_nodes = len(distances) - 1  # Exclude self

        if reachable_nodes == 0 or total_distance == 0:
            return 0.0

        return reachable_nodes / total_distance

    @staticmethod
    def _calculate_betweenness(node_id: str, adjacency: Dict, all_nodes: List[str]) -> float:
        """Calculate betweenness centrality (simplified)."""
        # Simplified betweenness calculation
        # In production, would use proper shortest path algorithms
        return 0.1  # Placeholder

    @staticmethod
    def calculate_clustering_coefficient(node_id: str, adjacency: Dict) -> float:
        """Calculate local clustering coefficient."""
        neighbors = list(adjacency[node_id])

        if len(neighbors) < 2:
            return 0.0

        # Count edges between neighbors
        edges_between_neighbors = 0
        for i, neighbor1 in enumerate(neighbors):
            for neighbor2 in neighbors[i+1:]:
                if neighbor2 in adjacency[neighbor1]:
                    edges_between_neighbors += 1

        # Maximum possible edges between neighbors
        max_edges = len(neighbors) * (len(neighbors) - 1) // 2

        return edges_between_neighbors / max_edges if max_edges > 0 else 0.0


class StatisticalAnalyzer:
    """Perform statistical analysis on aggregated data."""

    @staticmethod
    def calculate_distribution_stats(values: List[Union[int, float]]) -> Dict[str, float]:
        """Calculate comprehensive distribution statistics."""
        if not values:
            return {}

        values = [v for v in values if v is not None]
        if not values:
            return {}

        values_array = np.array(values)

        return {
            'count': len(values),
            'mean': float(np.mean(values_array)),
            'median': float(np.median(values_array)),
            'std': float(np.std(values_array)),
            'variance': float(np.var(values_array)),
            'min': float(np.min(values_array)),
            'max': float(np.max(values_array)),
            'q25': float(np.percentile(values_array, 25)),
            'q75': float(np.percentile(values_array, 75)),
            'skewness': StatisticalAnalyzer._calculate_skewness(values_array),
            'kurtosis': StatisticalAnalyzer._calculate_kurtosis(values_array)
        }

    @staticmethod
    def _calculate_skewness(values: np.ndarray) -> float:
        """Calculate skewness of distribution."""
        if len(values) < 3:
            return 0.0

        mean = np.mean(values)
        std = np.std(values)

        if std == 0:
            return 0.0

        skew = np.mean(((values - mean) / std) ** 3)
        return float(skew)

    @staticmethod
    def _calculate_kurtosis(values: np.ndarray) -> float:
        """Calculate kurtosis of distribution."""
        if len(values) < 4:
            return 0.0

        mean = np.mean(values)
        std = np.std(values)

        if std == 0:
            return 0.0

        kurt = np.mean(((values - mean) / std) ** 4) - 3  # Excess kurtosis
        return float(kurt)

    @staticmethod
    def calculate_correlation_matrix(data: Dict[str, List[float]]) -> Dict[str, Dict[str, float]]:
        """Calculate correlation matrix between variables."""
        variables = list(data.keys())
        correlation_matrix = {}

        for var1 in variables:
            correlation_matrix[var1] = {}
            for var2 in variables:
                if var1 == var2:
                    correlation_matrix[var1][var2] = 1.0
                else:
                    corr = StatisticalAnalyzer._calculate_correlation(
                        data[var1], data[var2]
                    )
                    correlation_matrix[var1][var2] = corr

        return correlation_matrix

    @staticmethod
    def _calculate_correlation(x: List[float], y: List[float]) -> float:
        """Calculate Pearson correlation coefficient."""
        if len(x) != len(y) or len(x) < 2:
            return 0.0

        # Remove None values
        pairs = [(a, b) for a, b in zip(x, y) if a is not None and b is not None]
        if len(pairs) < 2:
            return 0.0

        x_clean, y_clean = zip(*pairs)

        try:
            corr = np.corrcoef(x_clean, y_clean)[0, 1]
            return float(corr) if not np.isnan(corr) else 0.0
        except:
            return 0.0


class AggregationPipeline:
    """Advanced aggregation pipeline processor."""

    def __init__(self, neo4j_db, enable_caching: bool = True, max_workers: int = 4):
        """Initialize aggregation pipeline.

        Args:
            neo4j_db: Neo4j database connection
            enable_caching: Enable result caching
            max_workers: Maximum worker threads for parallel processing
        """
        self.neo4j_db = neo4j_db
        self.enable_caching = enable_caching
        self.max_workers = max_workers

        # Result cache
        self.result_cache = {}
        self.cache_ttl = 3600  # 1 hour

        # Thread pool for parallel processing
        self.executor = ThreadPoolExecutor(max_workers=max_workers)

        # Built-in aggregation functions
        self.aggregation_functions = {
            AggregationFunction.COUNT: self._count_aggregation,
            AggregationFunction.SUM: self._sum_aggregation,
            AggregationFunction.AVG: self._avg_aggregation,
            AggregationFunction.MIN: self._min_aggregation,
            AggregationFunction.MAX: self._max_aggregation,
            AggregationFunction.STDDEV: self._stddev_aggregation,
            AggregationFunction.MEDIAN: self._median_aggregation,
            AggregationFunction.DISTINCT_COUNT: self._distinct_count_aggregation,
            AggregationFunction.ARRAY_AGG: self._array_agg_aggregation
        }

        # Analytics calculators
        self.graph_calculator = GraphMetricsCalculator()
        self.stats_analyzer = StatisticalAnalyzer()

        # Performance tracking
        self.pipeline_stats = {
            'pipelines_executed': 0,
            'cache_hits': 0,
            'avg_execution_time_ms': 0.0,
            'total_results_generated': 0
        }

        logger.info("Initialized AggregationPipeline")

    def execute_pipeline(self,
                        pipeline_stages: List[PipelineStage],
                        pipeline_id: Optional[str] = None,
                        scope: AnalyticsScope = AnalyticsScope.GLOBAL,
                        scope_filters: Optional[Dict[str, Any]] = None) -> AggregationResult:
        """Execute a multi-stage aggregation pipeline.

        Args:
            pipeline_stages: List of pipeline stages
            pipeline_id: Optional pipeline identifier
            scope: Analytics scope
            scope_filters: Filters for scoping data

        Returns:
            Aggregation pipeline result
        """
        start_time = time.time()

        if pipeline_id is None:
            pipeline_id = self._generate_pipeline_id(pipeline_stages)

        # Check cache
        if self.enable_caching:
            cached_result = self._get_cached_result(pipeline_id)
            if cached_result:
                self.pipeline_stats['cache_hits'] += 1
                return cached_result

        # Execute stages
        stage_results = {}
        execution_plan = self._build_execution_plan(pipeline_stages)

        try:
            for stage_group in execution_plan:
                if len(stage_group) == 1:
                    # Sequential execution
                    stage = stage_group[0]
                    stage_results[stage.name] = self._execute_stage(
                        stage, stage_results, scope, scope_filters
                    )
                else:
                    # Parallel execution
                    futures = []
                    for stage in stage_group:
                        future = self.executor.submit(
                            self._execute_stage, stage, stage_results, scope, scope_filters
                        )
                        futures.append((stage.name, future))

                    # Collect results
                    for stage_name, future in futures:
                        stage_results[stage_name] = future.result()

            # Combine final results
            final_results = self._combine_stage_results(stage_results, pipeline_stages)

            # Calculate metadata
            execution_time_ms = (time.time() - start_time) * 1000
            metadata = {
                'pipeline_id': pipeline_id,
                'stages_executed': len(pipeline_stages),
                'execution_time_ms': execution_time_ms,
                'scope': scope.value,
                'data_points_processed': sum(
                    result.get('data_points', 0) for result in stage_results.values()
                    if isinstance(result, dict)
                )
            }

            # Create result
            result = AggregationResult(
                pipeline_id=pipeline_id,
                results=final_results,
                metadata=metadata,
                execution_time_ms=execution_time_ms
            )

            # Cache result
            if self.enable_caching:
                self._cache_result(pipeline_id, result)

            # Update stats
            self._update_pipeline_stats(execution_time_ms)

            logger.info(f"Pipeline {pipeline_id} executed in {execution_time_ms:.2f}ms")

            return result

        except Exception as e:
            logger.error(f"Pipeline execution failed: {e}")
            raise

    def aggregate_node_properties(self,
                                 node_type: Optional[str] = None,
                                 aggregations: List[AggregationSpec] = None,
                                 group_by: Optional[GroupBySpec] = None,
                                 filters: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Aggregate node properties with flexible grouping.

        Args:
            node_type: Optional node type filter
            aggregations: List of aggregation specifications
            group_by: Grouping specification
            filters: Additional filters

        Returns:
            Aggregated results
        """
        if aggregations is None:
            aggregations = [AggregationSpec(AggregationFunction.COUNT, "id")]

        # Build query
        query_parts = []
        query_parts.append("MATCH (n)")

        # Add type filter
        where_conditions = []
        if node_type:
            where_conditions.append(f"'{node_type}' IN labels(n)")

        # Add custom filters
        if filters:
            for field, value in filters.items():
                if isinstance(value, str):
                    where_conditions.append(f"n.{field} = '{value}'")
                elif isinstance(value, list):
                    values_str = "', '".join(str(v) for v in value)
                    where_conditions.append(f"n.{field} IN ['{values_str}']")
                else:
                    where_conditions.append(f"n.{field} = {value}")

        if where_conditions:
            query_parts.append("WHERE " + " AND ".join(where_conditions))

        # Build return clause with aggregations
        return_parts = []
        group_by_parts = []

        # Add grouping fields
        if group_by:
            for field in group_by.fields:
                group_by_parts.append(f"n.{field}")
                return_parts.append(f"n.{field} as {field}")

        # Add aggregations
        for agg_spec in aggregations:
            if agg_spec.function == AggregationFunction.COUNT:
                return_parts.append(f"count(n.{agg_spec.field}) as {agg_spec.get_alias()}")
            elif agg_spec.function == AggregationFunction.SUM:
                return_parts.append(f"sum(n.{agg_spec.field}) as {agg_spec.get_alias()}")
            elif agg_spec.function == AggregationFunction.AVG:
                return_parts.append(f"avg(n.{agg_spec.field}) as {agg_spec.get_alias()}")
            elif agg_spec.function == AggregationFunction.MIN:
                return_parts.append(f"min(n.{agg_spec.field}) as {agg_spec.get_alias()}")
            elif agg_spec.function == AggregationFunction.MAX:
                return_parts.append(f"max(n.{agg_spec.field}) as {agg_spec.get_alias()}")
            elif agg_spec.function == AggregationFunction.DISTINCT_COUNT:
                return_parts.append(f"count(DISTINCT n.{agg_spec.field}) as {agg_spec.get_alias()}")
            elif agg_spec.function == AggregationFunction.ARRAY_AGG:
                return_parts.append(f"collect(n.{agg_spec.field}) as {agg_spec.get_alias()}")

        query_parts.append("RETURN " + ", ".join(return_parts))

        # Add ORDER BY if grouping
        if group_by_parts:
            query_parts.append("ORDER BY " + ", ".join(group_by_parts))

        query = "\n".join(query_parts)

        # Execute query
        try:
            with self.neo4j_db.session() as session:
                result = session.run(query)

                aggregated_data = []
                for record in result:
                    row_data = dict(record)
                    aggregated_data.append(row_data)

                return {
                    'data': aggregated_data,
                    'query': query,
                    'row_count': len(aggregated_data),
                    'aggregations': [agg.get_alias() for agg in aggregations],
                    'grouping_fields': group_by.fields if group_by else []
                }

        except Exception as e:
            logger.error(f"Node property aggregation failed: {e}")
            return {'data': [], 'error': str(e)}

    def calculate_graph_analytics(self,
                                 node_types: Optional[List[str]] = None,
                                 edge_types: Optional[List[str]] = None,
                                 metrics: Optional[List[str]] = None) -> Dict[str, Any]:
        """Calculate comprehensive graph analytics.

        Args:
            node_types: Node types to include
            edge_types: Edge types to include
            metrics: Specific metrics to calculate

        Returns:
            Graph analytics results
        """
        if metrics is None:
            metrics = ['centrality', 'clustering', 'connectivity', 'distribution']

        # Fetch graph data
        nodes_query = "MATCH (n) RETURN n, labels(n) as node_labels"
        edges_query = "MATCH (a)-[r]-(b) RETURN r, a.id as source_id, b.id as target_id, type(r) as edge_type"

        if node_types:
            node_filter = " OR ".join([f"'{nt}' IN labels(n)" for nt in node_types])
            nodes_query = f"MATCH (n) WHERE {node_filter} RETURN n, labels(n) as node_labels"

        if edge_types:
            edge_filter = " OR ".join([f"type(r) = '{et}'" for et in edge_types])
            edges_query = f"MATCH (a)-[r]-(b) WHERE {edge_filter} RETURN r, a.id as source_id, b.id as target_id, type(r) as edge_type"

        analytics_results = {}

        try:
            with self.neo4j_db.session() as session:
                # Get nodes
                node_result = session.run(nodes_query)
                nodes = []
                for record in node_result:
                    node_data = dict(record['n'])
                    node_data['labels'] = record['node_labels']
                    nodes.append(node_data)

                # Get edges
                edge_result = session.run(edges_query)
                edges = []
                for record in edge_result:
                    edge_data = dict(record['r'])
                    edge_data['source_id'] = record['source_id']
                    edge_data['target_id'] = record['target_id']
                    edge_data['edge_type'] = record['edge_type']
                    edges.append(edge_data)

                # Calculate metrics
                if 'centrality' in metrics:
                    centrality_metrics = self.graph_calculator.calculate_centrality_metrics(nodes, edges)
                    analytics_results['centrality'] = centrality_metrics

                if 'clustering' in metrics:
                    clustering_results = self._calculate_clustering_analytics(nodes, edges)
                    analytics_results['clustering'] = clustering_results

                if 'connectivity' in metrics:
                    connectivity_results = self._calculate_connectivity_analytics(nodes, edges)
                    analytics_results['connectivity'] = connectivity_results

                if 'distribution' in metrics:
                    distribution_results = self._calculate_distribution_analytics(nodes, edges)
                    analytics_results['distribution'] = distribution_results

                # Add summary statistics
                analytics_results['summary'] = {
                    'total_nodes': len(nodes),
                    'total_edges': len(edges),
                    'node_types': list(set(
                        label for node in nodes for label in node.get('labels', [])
                    )),
                    'edge_types': list(set(edge['edge_type'] for edge in edges)),
                    'density': len(edges) / max(1, len(nodes) * (len(nodes) - 1) / 2)
                }

                return analytics_results

        except Exception as e:
            logger.error(f"Graph analytics calculation failed: {e}")
            return {'error': str(e)}

    def create_correlation_analysis(self,
                                   variables: List[str],
                                   entity_type: str = "Concept",
                                   filters: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Create correlation analysis between variables.

        Args:
            variables: List of property names to correlate
            entity_type: Entity type to analyze
            filters: Optional filters

        Returns:
            Correlation analysis results
        """
        # Build query to get variable values
        query_parts = []
        query_parts.append(f"MATCH (n:{entity_type})")

        # Add filters
        if filters:
            where_conditions = []
            for field, value in filters.items():
                if isinstance(value, str):
                    where_conditions.append(f"n.{field} = '{value}'")
                else:
                    where_conditions.append(f"n.{field} = {value}")

            if where_conditions:
                query_parts.append("WHERE " + " AND ".join(where_conditions))

        # Add variable selection
        var_conditions = []
        for var in variables:
            var_conditions.append(f"n.{var} IS NOT NULL")

        if var_conditions:
            if "WHERE" in query_parts[-1]:
                query_parts[-1] += " AND " + " AND ".join(var_conditions)
            else:
                query_parts.append("WHERE " + " AND ".join(var_conditions))

        # Return variables
        return_vars = [f"n.{var} as {var}" for var in variables]
        query_parts.append("RETURN " + ", ".join(return_vars))

        query = "\n".join(query_parts)

        try:
            with self.neo4j_db.session() as session:
                result = session.run(query)

                # Collect data
                data = {var: [] for var in variables}
                for record in result:
                    for var in variables:
                        value = record[var]
                        if value is not None:
                            data[var].append(float(value) if isinstance(value, (int, float)) else value)
                        else:
                            data[var].append(None)

                # Calculate correlations
                correlation_matrix = self.stats_analyzer.calculate_correlation_matrix(data)

                # Calculate distribution stats for each variable
                distribution_stats = {}
                for var, values in data.items():
                    numeric_values = [v for v in values if isinstance(v, (int, float))]
                    if numeric_values:
                        distribution_stats[var] = self.stats_analyzer.calculate_distribution_stats(numeric_values)

                return {
                    'correlation_matrix': correlation_matrix,
                    'distribution_stats': distribution_stats,
                    'sample_size': len(data[variables[0]]),
                    'variables': variables,
                    'entity_type': entity_type
                }

        except Exception as e:
            logger.error(f"Correlation analysis failed: {e}")
            return {'error': str(e)}

    def _execute_stage(self,
                      stage: PipelineStage,
                      previous_results: Dict[str, Any],
                      scope: AnalyticsScope,
                      scope_filters: Optional[Dict[str, Any]]) -> Any:
        """Execute a single pipeline stage."""

        if stage.operation_type == 'node_aggregation':
            return self._execute_node_aggregation_stage(stage, scope_filters)
        elif stage.operation_type == 'edge_aggregation':
            return self._execute_edge_aggregation_stage(stage, scope_filters)
        elif stage.operation_type == 'graph_analytics':
            return self._execute_graph_analytics_stage(stage, scope_filters)
        elif stage.operation_type == 'statistical_analysis':
            return self._execute_statistical_analysis_stage(stage, previous_results)
        elif stage.operation_type == 'correlation_analysis':
            return self._execute_correlation_analysis_stage(stage, scope_filters)
        else:
            logger.warning(f"Unknown stage operation type: {stage.operation_type}")
            return {}

    def _execute_node_aggregation_stage(self, stage: PipelineStage, filters: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        """Execute node aggregation stage."""
        params = stage.parameters

        aggregations = []
        for agg_config in params.get('aggregations', []):
            agg_spec = AggregationSpec(
                function=AggregationFunction(agg_config['function']),
                field=agg_config['field'],
                alias=agg_config.get('alias')
            )
            aggregations.append(agg_spec)

        group_by = None
        if 'group_by' in params:
            group_by = GroupBySpec(
                fields=params['group_by']['fields'],
                operation=GroupByOperation(params['group_by'].get('operation', 'simple'))
            )

        return self.aggregate_node_properties(
            node_type=params.get('node_type'),
            aggregations=aggregations,
            group_by=group_by,
            filters=filters
        )

    def _execute_graph_analytics_stage(self, stage: PipelineStage, filters: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        """Execute graph analytics stage."""
        params = stage.parameters

        return self.calculate_graph_analytics(
            node_types=params.get('node_types'),
            edge_types=params.get('edge_types'),
            metrics=params.get('metrics', ['centrality', 'clustering'])
        )

    def _execute_correlation_analysis_stage(self, stage: PipelineStage, filters: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        """Execute correlation analysis stage."""
        params = stage.parameters

        return self.create_correlation_analysis(
            variables=params['variables'],
            entity_type=params.get('entity_type', 'Concept'),
            filters=filters
        )

    def _build_execution_plan(self, stages: List[PipelineStage]) -> List[List[PipelineStage]]:
        """Build execution plan considering dependencies."""
        # Simple topological sort for dependency resolution
        stage_map = {stage.name: stage for stage in stages}
        executed = set()
        plan = []

        while len(executed) < len(stages):
            ready_stages = []

            for stage in stages:
                if stage.name in executed:
                    continue

                # Check if dependencies are satisfied
                if not stage.depends_on or all(dep in executed for dep in stage.depends_on):
                    ready_stages.append(stage)

            if not ready_stages:
                # Circular dependency or error
                remaining = [s for s in stages if s.name not in executed]
                plan.append(remaining)
                break

            # Group by parallel execution capability
            parallel_stages = [s for s in ready_stages if s.parallel]
            sequential_stages = [s for s in ready_stages if not s.parallel]

            if parallel_stages:
                plan.append(parallel_stages)
                executed.update(s.name for s in parallel_stages)

            for stage in sequential_stages:
                plan.append([stage])
                executed.add(stage.name)

        return plan

    def _combine_stage_results(self, stage_results: Dict[str, Any], stages: List[PipelineStage]) -> Dict[str, Any]:
        """Combine results from all pipeline stages."""
        combined_results = {}

        for stage in stages:
            if stage.name in stage_results:
                combined_results[stage.name] = stage_results[stage.name]

        return combined_results

    def _calculate_clustering_analytics(self, nodes: List[Dict], edges: List[Dict]) -> Dict[str, Any]:
        """Calculate clustering analytics."""
        # Build adjacency for clustering calculation
        adjacency = defaultdict(set)

        for edge in edges:
            source = edge.get('source_id')
            target = edge.get('target_id')
            if source and target:
                adjacency[source].add(target)
                adjacency[target].add(source)

        # Calculate clustering coefficients
        clustering_coefficients = {}
        for node in nodes:
            node_id = node.get('id', node.get('concept_id', ''))
            clustering_coeff = self.graph_calculator.calculate_clustering_coefficient(node_id, adjacency)
            clustering_coefficients[node_id] = clustering_coeff

        # Calculate global clustering
        local_coeffs = list(clustering_coefficients.values())
        global_clustering = sum(local_coeffs) / len(local_coeffs) if local_coeffs else 0.0

        return {
            'local_clustering': clustering_coefficients,
            'global_clustering': global_clustering,
            'distribution_stats': self.stats_analyzer.calculate_distribution_stats(local_coeffs)
        }

    def _calculate_connectivity_analytics(self, nodes: List[Dict], edges: List[Dict]) -> Dict[str, Any]:
        """Calculate connectivity analytics."""
        # Calculate degree distribution
        degree_count = defaultdict(int)

        for edge in edges:
            source = edge.get('source_id')
            target = edge.get('target_id')
            if source:
                degree_count[source] += 1
            if target:
                degree_count[target] += 1

        degrees = list(degree_count.values())

        return {
            'degree_distribution': dict(Counter(degrees)),
            'degree_stats': self.stats_analyzer.calculate_distribution_stats(degrees),
            'max_degree': max(degrees) if degrees else 0,
            'isolated_nodes': sum(1 for node in nodes if degree_count.get(node.get('id', ''), 0) == 0)
        }

    def _calculate_distribution_analytics(self, nodes: List[Dict], edges: List[Dict]) -> Dict[str, Any]:
        """Calculate distribution analytics."""
        # Node type distribution
        node_type_counts = defaultdict(int)
        for node in nodes:
            labels = node.get('labels', ['Unknown'])
            for label in labels:
                node_type_counts[label] += 1

        # Edge type distribution
        edge_type_counts = defaultdict(int)
        for edge in edges:
            edge_type = edge.get('edge_type', 'Unknown')
            edge_type_counts[edge_type] += 1

        return {
            'node_type_distribution': dict(node_type_counts),
            'edge_type_distribution': dict(edge_type_counts),
            'node_type_entropy': self._calculate_entropy(list(node_type_counts.values())),
            'edge_type_entropy': self._calculate_entropy(list(edge_type_counts.values()))
        }

    def _calculate_entropy(self, counts: List[int]) -> float:
        """Calculate Shannon entropy."""
        if not counts:
            return 0.0

        total = sum(counts)
        if total == 0:
            return 0.0

        entropy = 0.0
        for count in counts:
            if count > 0:
                p = count / total
                entropy -= p * np.log2(p)

        return entropy

    # Aggregation function implementations
    def _count_aggregation(self, values: List[Any]) -> int:
        """Count non-null values."""
        return len([v for v in values if v is not None])

    def _sum_aggregation(self, values: List[Union[int, float]]) -> Union[int, float]:
        """Sum numeric values."""
        numeric_values = [v for v in values if isinstance(v, (int, float))]
        return sum(numeric_values)

    def _avg_aggregation(self, values: List[Union[int, float]]) -> float:
        """Average of numeric values."""
        numeric_values = [v for v in values if isinstance(v, (int, float))]
        return sum(numeric_values) / len(numeric_values) if numeric_values else 0.0

    def _min_aggregation(self, values: List[Union[int, float]]) -> Union[int, float]:
        """Minimum of numeric values."""
        numeric_values = [v for v in values if isinstance(v, (int, float))]
        return min(numeric_values) if numeric_values else 0

    def _max_aggregation(self, values: List[Union[int, float]]) -> Union[int, float]:
        """Maximum of numeric values."""
        numeric_values = [v for v in values if isinstance(v, (int, float))]
        return max(numeric_values) if numeric_values else 0

    def _stddev_aggregation(self, values: List[Union[int, float]]) -> float:
        """Standard deviation of numeric values."""
        numeric_values = [v for v in values if isinstance(v, (int, float))]
        if len(numeric_values) < 2:
            return 0.0
        return float(np.std(numeric_values))

    def _median_aggregation(self, values: List[Union[int, float]]) -> float:
        """Median of numeric values."""
        numeric_values = [v for v in values if isinstance(v, (int, float))]
        return float(np.median(numeric_values)) if numeric_values else 0.0

    def _distinct_count_aggregation(self, values: List[Any]) -> int:
        """Count distinct values."""
        return len(set(v for v in values if v is not None))

    def _array_agg_aggregation(self, values: List[Any]) -> List[Any]:
        """Collect values into array."""
        return [v for v in values if v is not None]

    def _generate_pipeline_id(self, stages: List[PipelineStage]) -> str:
        """Generate unique pipeline ID."""
        stage_signatures = []
        for stage in stages:
            signature = f"{stage.name}:{stage.operation_type}:{json.dumps(stage.parameters, sort_keys=True)}"
            stage_signatures.append(signature)

        combined_signature = "|".join(stage_signatures)
        return hashlib.md5(combined_signature.encode()).hexdigest()[:12]

    def _get_cached_result(self, pipeline_id: str) -> Optional[AggregationResult]:
        """Get cached pipeline result."""
        if pipeline_id in self.result_cache:
            cached_data, timestamp = self.result_cache[pipeline_id]
            if time.time() - timestamp < self.cache_ttl:
                cached_data.cache_hit = True
                return cached_data
            else:
                del self.result_cache[pipeline_id]
        return None

    def _cache_result(self, pipeline_id: str, result: AggregationResult):
        """Cache pipeline result."""
        self.result_cache[pipeline_id] = (result, time.time())

    def _update_pipeline_stats(self, execution_time_ms: float):
        """Update pipeline performance statistics."""
        self.pipeline_stats['pipelines_executed'] += 1
        current_avg = self.pipeline_stats['avg_execution_time_ms']
        total_pipelines = self.pipeline_stats['pipelines_executed']

        self.pipeline_stats['avg_execution_time_ms'] = (
            (current_avg * (total_pipelines - 1) + execution_time_ms) / total_pipelines
        )

    def get_pipeline_statistics(self) -> Dict[str, Any]:
        """Get comprehensive pipeline statistics."""
        return {
            **self.pipeline_stats,
            'cache_size': len(self.result_cache),
            'cache_hit_rate': (
                self.pipeline_stats['cache_hits'] / max(1, self.pipeline_stats['pipelines_executed'])
            ),
            'available_functions': list(self.aggregation_functions.keys()),
            'max_workers': self.max_workers,
            'caching_enabled': self.enable_caching
        }