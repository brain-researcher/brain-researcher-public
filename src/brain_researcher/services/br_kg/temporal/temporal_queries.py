"""Temporal query support for time-based graph analysis.

This module provides sophisticated temporal query capabilities for:
- Time-series analysis of graph evolution
- Temporal pattern discovery and motif detection
- Change point detection in network structures
- Historical relationship analysis
- Time-bounded graph traversal and path analysis
- Temporal aggregation and windowing functions
"""

import json
import logging
import numpy as np
import time
from typing import Dict, List, Any, Optional, Tuple, Union, Set
from dataclasses import dataclass, asdict
from enum import Enum
from collections import defaultdict, deque
from datetime import datetime, timedelta
import pandas as pd

logger = logging.getLogger(__name__)


class TemporalGranularity(str, Enum):
    """Temporal granularity levels."""
    SECOND = "second"
    MINUTE = "minute"
    HOUR = "hour"
    DAY = "day"
    WEEK = "week"
    MONTH = "month"
    YEAR = "year"


class TemporalAggregation(str, Enum):
    """Temporal aggregation methods."""
    SUM = "sum"
    AVG = "avg"
    MIN = "min"
    MAX = "max"
    COUNT = "count"
    FIRST = "first"
    LAST = "last"
    STDDEV = "stddev"


class TemporalPattern(str, Enum):
    """Types of temporal patterns to detect."""
    TREND = "trend"                    # Increasing/decreasing trends
    SEASONALITY = "seasonality"        # Periodic patterns
    CHANGE_POINT = "change_point"      # Sudden changes
    ANOMALY = "anomaly"               # Outlier patterns
    CORRELATION = "correlation"        # Correlated changes
    CAUSALITY = "causality"           # Causal relationships


@dataclass
class TemporalWindow:
    """Defines a temporal analysis window."""

    start_time: datetime
    end_time: datetime
    granularity: TemporalGranularity
    overlap_ratio: float = 0.0  # 0.0 = no overlap, 0.5 = 50% overlap

    def get_window_duration(self) -> timedelta:
        """Get the duration of this window."""
        return self.end_time - self.start_time

    def get_time_buckets(self) -> List[Tuple[datetime, datetime]]:
        """Get time buckets within this window based on granularity."""
        buckets = []
        current_time = self.start_time

        # Define bucket size based on granularity
        bucket_sizes = {
            TemporalGranularity.SECOND: timedelta(seconds=1),
            TemporalGranularity.MINUTE: timedelta(minutes=1),
            TemporalGranularity.HOUR: timedelta(hours=1),
            TemporalGranularity.DAY: timedelta(days=1),
            TemporalGranularity.WEEK: timedelta(weeks=1),
            TemporalGranularity.MONTH: timedelta(days=30),  # Approximation
            TemporalGranularity.YEAR: timedelta(days=365)   # Approximation
        }

        bucket_size = bucket_sizes[self.granularity]
        overlap_size = timedelta(seconds=bucket_size.total_seconds() * self.overlap_ratio)
        step_size = bucket_size - overlap_size

        while current_time < self.end_time:
            bucket_end = min(current_time + bucket_size, self.end_time)
            buckets.append((current_time, bucket_end))
            current_time += step_size

        return buckets


@dataclass
class TemporalNode:
    """Node with temporal information."""

    node_id: str
    properties: Dict[str, Any]
    created_at: datetime
    updated_at: Optional[datetime] = None
    valid_from: Optional[datetime] = None
    valid_to: Optional[datetime] = None
    version: int = 1


@dataclass
class TemporalEdge:
    """Edge with temporal information."""

    edge_id: str
    source_id: str
    target_id: str
    relationship_type: str
    properties: Dict[str, Any]
    created_at: datetime
    updated_at: Optional[datetime] = None
    valid_from: Optional[datetime] = None
    valid_to: Optional[datetime] = None
    weight: float = 1.0
    version: int = 1


@dataclass
class TemporalSnapshot:
    """Graph snapshot at a specific time."""

    timestamp: datetime
    nodes: List[TemporalNode]
    edges: List[TemporalEdge]
    metadata: Dict[str, Any]

    def get_node_count_by_type(self) -> Dict[str, int]:
        """Get node counts by type."""
        counts = defaultdict(int)
        for node in self.nodes:
            node_type = node.properties.get('type', 'unknown')
            counts[node_type] += 1
        return dict(counts)

    def get_edge_count_by_type(self) -> Dict[str, int]:
        """Get edge counts by type."""
        counts = defaultdict(int)
        for edge in self.edges:
            counts[edge.relationship_type] += 1
        return dict(counts)


@dataclass
class DetectedTemporalPattern:
    """Detected temporal pattern."""

    pattern_type: TemporalPattern
    entity_id: str
    entity_type: str
    start_time: datetime
    end_time: datetime
    confidence: float
    parameters: Dict[str, Any]
    description: str


class TemporalQueryEngine:
    """Advanced temporal query engine for graph analysis."""

    def __init__(self, neo4j_db, enable_versioning: bool = True):
        """Initialize temporal query engine.

        Args:
            neo4j_db: Neo4j database connection
            enable_versioning: Enable node/edge versioning
        """
        self.neo4j_db = neo4j_db
        self.enable_versioning = enable_versioning

        # Temporal index cache
        self.temporal_cache = {}
        self.cache_ttl = 1800  # 30 minutes

        # Pattern detection models (simplified)
        self.pattern_detectors = {
            TemporalPattern.TREND: self._detect_trend,
            TemporalPattern.SEASONALITY: self._detect_seasonality,
            TemporalPattern.CHANGE_POINT: self._detect_change_point,
            TemporalPattern.ANOMALY: self._detect_anomaly
        }

        # Performance tracking
        self.query_stats = {
            'temporal_queries': 0,
            'snapshots_generated': 0,
            'patterns_detected': 0,
            'avg_query_time_ms': 0.0
        }

        logger.info("Initialized TemporalQueryEngine")

        # Create temporal indexes if not exists
        self._create_temporal_indexes()

    def _create_temporal_indexes(self):
        """Create temporal indexes for efficient querying."""
        temporal_indexes = [
            "CREATE INDEX temporal_node_created IF NOT EXISTS FOR (n:TemporalNode) ON (n.created_at)",
            "CREATE INDEX temporal_node_valid_from IF NOT EXISTS FOR (n:TemporalNode) ON (n.valid_from)",
            "CREATE INDEX temporal_node_valid_to IF NOT EXISTS FOR (n:TemporalNode) ON (n.valid_to)",
            "CREATE INDEX temporal_edge_created IF NOT EXISTS FOR ()-[r:TEMPORAL_REL]-() ON (r.created_at)",
            "CREATE INDEX temporal_edge_valid_from IF NOT EXISTS FOR ()-[r:TEMPORAL_REL]-() ON (r.valid_from)",
            "CREATE INDEX temporal_edge_valid_to IF NOT EXISTS FOR ()-[r:TEMPORAL_REL]-() ON (r.valid_to)"
        ]

        try:
            with self.neo4j_db.session() as session:
                for index_query in temporal_indexes:
                    session.run(index_query)
                logger.info("Created temporal indexes")
        except Exception as e:
            logger.warning(f"Failed to create temporal indexes: {e}")

    def create_temporal_snapshot(self,
                                timestamp: datetime,
                                node_filters: Optional[Dict[str, Any]] = None,
                                edge_filters: Optional[Dict[str, Any]] = None) -> TemporalSnapshot:
        """Create a graph snapshot at a specific timestamp.

        Args:
            timestamp: Target timestamp
            node_filters: Optional filters for nodes
            edge_filters: Optional filters for edges

        Returns:
            Graph snapshot at the specified time
        """
        start_time = time.time()

        # Query nodes valid at the timestamp
        node_query = """
        MATCH (n)
        WHERE (n.created_at IS NULL OR n.created_at <= $timestamp)
        AND (n.valid_from IS NULL OR n.valid_from <= $timestamp)
        AND (n.valid_to IS NULL OR n.valid_to > $timestamp)
        %s
        RETURN n, labels(n) as node_labels
        ORDER BY n.created_at
        """ % self._build_node_filters(node_filters)

        # Query edges valid at the timestamp
        edge_query = """
        MATCH (a)-[r]-(b)
        WHERE (r.created_at IS NULL OR r.created_at <= $timestamp)
        AND (r.valid_from IS NULL OR r.valid_from <= $timestamp)
        AND (r.valid_to IS NULL OR r.valid_to > $timestamp)
        %s
        RETURN r, a.id as source_id, b.id as target_id, type(r) as rel_type
        ORDER BY r.created_at
        """ % self._build_edge_filters(edge_filters)

        try:
            with self.neo4j_db.session() as session:
                # Get nodes
                node_result = session.run(node_query, timestamp=timestamp)
                temporal_nodes = []

                for record in node_result:
                    node_data = dict(record['n'])
                    node_labels = record['node_labels']

                    temporal_node = TemporalNode(
                        node_id=node_data.get('id', str(node_data.get('concept_id', ''))),
                        properties={**node_data, 'labels': node_labels},
                        created_at=node_data.get('created_at', timestamp),
                        updated_at=node_data.get('updated_at'),
                        valid_from=node_data.get('valid_from'),
                        valid_to=node_data.get('valid_to'),
                        version=node_data.get('version', 1)
                    )
                    temporal_nodes.append(temporal_node)

                # Get edges
                edge_result = session.run(edge_query, timestamp=timestamp)
                temporal_edges = []

                for record in edge_result:
                    edge_data = dict(record['r'])

                    temporal_edge = TemporalEdge(
                        edge_id=edge_data.get('id', f"{record['source_id']}-{record['target_id']}"),
                        source_id=record['source_id'],
                        target_id=record['target_id'],
                        relationship_type=record['rel_type'],
                        properties=edge_data,
                        created_at=edge_data.get('created_at', timestamp),
                        updated_at=edge_data.get('updated_at'),
                        valid_from=edge_data.get('valid_from'),
                        valid_to=edge_data.get('valid_to'),
                        weight=edge_data.get('weight', 1.0),
                        version=edge_data.get('version', 1)
                    )
                    temporal_edges.append(temporal_edge)

                # Create snapshot
                snapshot = TemporalSnapshot(
                    timestamp=timestamp,
                    nodes=temporal_nodes,
                    edges=temporal_edges,
                    metadata={
                        'node_count': len(temporal_nodes),
                        'edge_count': len(temporal_edges),
                        'generation_time_ms': (time.time() - start_time) * 1000
                    }
                )

                self.query_stats['snapshots_generated'] += 1

                logger.info(f"Created temporal snapshot with {len(temporal_nodes)} nodes and {len(temporal_edges)} edges")

                return snapshot

        except Exception as e:
            logger.error(f"Failed to create temporal snapshot: {e}")
            return TemporalSnapshot(timestamp=timestamp, nodes=[], edges=[], metadata={})

    def analyze_temporal_evolution(self,
                                  entity_ids: List[str],
                                  start_time: datetime,
                                  end_time: datetime,
                                  granularity: TemporalGranularity = TemporalGranularity.DAY,
                                  metrics: Optional[List[str]] = None) -> Dict[str, Any]:
        """Analyze how entities evolve over time.

        Args:
            entity_ids: IDs of entities to analyze
            start_time: Analysis start time
            end_time: Analysis end time
            granularity: Temporal granularity
            metrics: Metrics to compute

        Returns:
            Evolution analysis results
        """
        start_query_time = time.time()

        if metrics is None:
            metrics = ['degree', 'betweenness', 'clustering']

        window = TemporalWindow(start_time, end_time, granularity)
        time_buckets = window.get_time_buckets()

        evolution_data = {}

        for entity_id in entity_ids:
            entity_evolution = {
                'timestamps': [],
                'metrics': {metric: [] for metric in metrics},
                'properties': []
            }

            for bucket_start, bucket_end in time_buckets:
                # Create snapshot for this time bucket
                snapshot = self.create_temporal_snapshot(bucket_end)

                # Find entity in snapshot
                entity_node = None
                for node in snapshot.nodes:
                    if node.node_id == entity_id:
                        entity_node = node
                        break

                if entity_node:
                    entity_evolution['timestamps'].append(bucket_end)
                    entity_evolution['properties'].append(entity_node.properties)

                    # Calculate metrics
                    for metric in metrics:
                        metric_value = self._calculate_temporal_metric(
                            metric, entity_node, snapshot
                        )
                        entity_evolution['metrics'][metric].append(metric_value)
                else:
                    # Entity doesn't exist at this time
                    entity_evolution['timestamps'].append(bucket_end)
                    entity_evolution['properties'].append({})

                    for metric in metrics:
                        entity_evolution['metrics'][metric].append(0.0)

            evolution_data[entity_id] = entity_evolution

        # Detect patterns in evolution
        patterns = []
        for entity_id, evolution in evolution_data.items():
            for metric in metrics:
                metric_values = evolution['metrics'][metric]
                if len(metric_values) > 3:  # Need minimum data points
                    detected_patterns = self._detect_temporal_patterns(
                        entity_id, metric, metric_values, evolution['timestamps']
                    )
                    patterns.extend(detected_patterns)

        query_time_ms = (time.time() - start_query_time) * 1000
        self.query_stats['temporal_queries'] += 1
        self._update_query_stats(query_time_ms)

        return {
            'entity_evolution': evolution_data,
            'detected_patterns': [asdict(p) for p in patterns],
            'time_buckets': len(time_buckets),
            'analysis_window': {
                'start': start_time.isoformat(),
                'end': end_time.isoformat(),
                'granularity': granularity.value
            },
            'query_time_ms': query_time_ms
        }

    def find_temporal_communities(self,
                                 start_time: datetime,
                                 end_time: datetime,
                                 granularity: TemporalGranularity = TemporalGranularity.DAY,
                                 min_community_size: int = 3) -> Dict[str, Any]:
        """Find communities that form and dissolve over time.

        Args:
            start_time: Analysis start time
            end_time: Analysis end time
            granularity: Temporal granularity
            min_community_size: Minimum community size

        Returns:
            Temporal community analysis
        """
        window = TemporalWindow(start_time, end_time, granularity)
        time_buckets = window.get_time_buckets()

        community_evolution = []

        for bucket_start, bucket_end in time_buckets:
            # Create snapshot
            snapshot = self.create_temporal_snapshot(bucket_end)

            # Detect communities in this snapshot (simplified implementation)
            communities = self._detect_communities_in_snapshot(snapshot, min_community_size)

            community_evolution.append({
                'timestamp': bucket_end,
                'communities': communities,
                'community_count': len(communities)
            })

        # Analyze community stability and evolution
        stable_communities = self._analyze_community_stability(community_evolution)

        return {
            'community_evolution': community_evolution,
            'stable_communities': stable_communities,
            'analysis_summary': {
                'time_buckets': len(time_buckets),
                'max_communities': max(len(ce['communities']) for ce in community_evolution),
                'avg_communities': sum(len(ce['communities']) for ce in community_evolution) / len(community_evolution)
            }
        }

    def query_temporal_paths(self,
                           source_id: str,
                           target_id: str,
                           time_window: TemporalWindow,
                           path_constraints: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        """Find temporal paths between nodes within a time window.

        Args:
            source_id: Source node ID
            target_id: Target node ID
            time_window: Time window for path search
            path_constraints: Additional path constraints

        Returns:
            List of temporal paths
        """
        query = """
        MATCH path = (source)-[r*1..5]-(target)
        WHERE source.id = $source_id AND target.id = $target_id
        AND ALL(rel in relationships(path) WHERE
            (rel.created_at IS NULL OR rel.created_at >= $start_time)
            AND (rel.created_at IS NULL OR rel.created_at <= $end_time)
            AND (rel.valid_from IS NULL OR rel.valid_from <= $end_time)
            AND (rel.valid_to IS NULL OR rel.valid_to >= $start_time)
        )
        WITH path, relationships(path) as path_rels,
             [rel in relationships(path) | rel.created_at] as creation_times
        RETURN nodes(path) as path_nodes, path_rels,
               length(path) as path_length,
               apoc.coll.min(creation_times) as earliest_edge,
               apoc.coll.max(creation_times) as latest_edge
        ORDER BY path_length ASC, earliest_edge ASC
        LIMIT 50
        """

        try:
            with self.neo4j_db.session() as session:
                result = session.run(
                    query,
                    source_id=source_id,
                    target_id=target_id,
                    start_time=time_window.start_time,
                    end_time=time_window.end_time
                )

                temporal_paths = []
                for record in result:
                    path_data = {
                        'nodes': [dict(node) for node in record['path_nodes']],
                        'edges': [dict(rel) for rel in record['path_rels']],
                        'length': record['path_length'],
                        'earliest_edge': record['earliest_edge'],
                        'latest_edge': record['latest_edge'],
                        'temporal_span_seconds': (
                            (record['latest_edge'] - record['earliest_edge']).total_seconds()
                            if record['latest_edge'] and record['earliest_edge'] else 0
                        )
                    }
                    temporal_paths.append(path_data)

                return temporal_paths

        except Exception as e:
            logger.error(f"Temporal path query failed: {e}")
            return []

    def aggregate_temporal_data(self,
                               entity_ids: List[str],
                               property_name: str,
                               time_window: TemporalWindow,
                               aggregation: TemporalAggregation = TemporalAggregation.AVG) -> Dict[str, Any]:
        """Aggregate property values over time.

        Args:
            entity_ids: Entity IDs to aggregate
            property_name: Property to aggregate
            time_window: Time window for aggregation
            aggregation: Aggregation method

        Returns:
            Aggregated temporal data
        """
        time_buckets = time_window.get_time_buckets()

        aggregated_data = {
            'entity_id': entity_ids,
            'property_name': property_name,
            'aggregation_method': aggregation.value,
            'time_series': [],
            'summary_stats': {}
        }

        all_values = []

        for bucket_start, bucket_end in time_buckets:
            bucket_values = []

            # Query property values in this time bucket
            query = """
            MATCH (n)
            WHERE n.id IN $entity_ids
            AND (n.created_at IS NULL OR n.created_at <= $bucket_end)
            AND (n.valid_from IS NULL OR n.valid_from <= $bucket_end)
            AND (n.valid_to IS NULL OR n.valid_to > $bucket_start)
            AND n.%s IS NOT NULL
            RETURN n.id as entity_id, n.%s as property_value, n.updated_at
            """ % (property_name, property_name)

            try:
                with self.neo4j_db.session() as session:
                    result = session.run(
                        query,
                        entity_ids=entity_ids,
                        bucket_start=bucket_start,
                        bucket_end=bucket_end
                    )

                    for record in result:
                        bucket_values.append(record['property_value'])

            except Exception as e:
                logger.warning(f"Aggregation query failed: {e}")

            # Apply aggregation
            if bucket_values:
                if aggregation == TemporalAggregation.SUM:
                    agg_value = sum(bucket_values)
                elif aggregation == TemporalAggregation.AVG:
                    agg_value = sum(bucket_values) / len(bucket_values)
                elif aggregation == TemporalAggregation.MIN:
                    agg_value = min(bucket_values)
                elif aggregation == TemporalAggregation.MAX:
                    agg_value = max(bucket_values)
                elif aggregation == TemporalAggregation.COUNT:
                    agg_value = len(bucket_values)
                elif aggregation == TemporalAggregation.STDDEV:
                    mean = sum(bucket_values) / len(bucket_values)
                    variance = sum((x - mean) ** 2 for x in bucket_values) / len(bucket_values)
                    agg_value = variance ** 0.5
                else:
                    agg_value = bucket_values[0]  # FIRST/LAST

                all_values.append(agg_value)
            else:
                agg_value = None

            aggregated_data['time_series'].append({
                'timestamp': bucket_end,
                'value': agg_value,
                'sample_count': len(bucket_values)
            })

        # Calculate summary statistics
        if all_values:
            aggregated_data['summary_stats'] = {
                'total_buckets': len(time_buckets),
                'non_null_buckets': len(all_values),
                'min_value': min(all_values),
                'max_value': max(all_values),
                'avg_value': sum(all_values) / len(all_values),
                'total_sum': sum(all_values)
            }

        return aggregated_data

    def _calculate_temporal_metric(self, metric: str, node: TemporalNode, snapshot: TemporalSnapshot) -> float:
        """Calculate temporal metric for a node in a snapshot."""
        if metric == 'degree':
            # Count edges connected to this node
            degree = 0
            for edge in snapshot.edges:
                if edge.source_id == node.node_id or edge.target_id == node.node_id:
                    degree += 1
            return float(degree)

        elif metric == 'betweenness':
            # Simplified betweenness centrality (would use proper algorithm in production)
            return 0.5  # Placeholder

        elif metric == 'clustering':
            # Local clustering coefficient
            return 0.3  # Placeholder

        else:
            # Property-based metric
            return float(node.properties.get(metric, 0.0))

    def _detect_temporal_patterns(self,
                                 entity_id: str,
                                 metric: str,
                                 values: List[float],
                                 timestamps: List[datetime]) -> List[DetectedTemporalPattern]:
        """Detect temporal patterns in metric values."""
        patterns = []

        if len(values) < 3:
            return patterns

        # Convert to numpy for analysis
        y = np.array(values)
        x = np.arange(len(values))

        # Detect trend
        trend_pattern = self._detect_trend(entity_id, metric, x, y, timestamps)
        if trend_pattern:
            patterns.append(trend_pattern)

        # Detect seasonality
        seasonality_pattern = self._detect_seasonality(entity_id, metric, x, y, timestamps)
        if seasonality_pattern:
            patterns.append(seasonality_pattern)

        # Detect change points
        change_point_pattern = self._detect_change_point(entity_id, metric, x, y, timestamps)
        if change_point_pattern:
            patterns.append(change_point_pattern)

        # Detect anomalies
        anomaly_pattern = self._detect_anomaly(entity_id, metric, x, y, timestamps)
        if anomaly_pattern:
            patterns.append(anomaly_pattern)

        return patterns

    def _detect_trend(self, entity_id: str, metric: str, x: np.ndarray, y: np.ndarray, timestamps: List[datetime]) -> Optional[DetectedTemporalPattern]:
        """Detect trend patterns."""
        if len(y) < 3:
            return None

        # Simple linear regression
        slope = np.corrcoef(x, y)[0, 1] * (np.std(y) / np.std(x))

        if abs(slope) > 0.1:  # Threshold for significant trend
            trend_type = "increasing" if slope > 0 else "decreasing"
            confidence = min(abs(slope), 1.0)

            return DetectedTemporalPattern(
                pattern_type=TemporalPattern.TREND,
                entity_id=entity_id,
                entity_type=metric,
                start_time=timestamps[0],
                end_time=timestamps[-1],
                confidence=confidence,
                parameters={'slope': slope, 'trend_type': trend_type},
                description=f"{trend_type.capitalize()} trend detected in {metric}"
            )

        return None

    def _detect_seasonality(self, entity_id: str, metric: str, x: np.ndarray, y: np.ndarray, timestamps: List[datetime]) -> Optional[DetectedTemporalPattern]:
        """Detect simple seasonality using autocorrelation peaks."""
        if len(y) < 6:
            return None

        y_demeaned = y - np.mean(y)
        autocorr = np.correlate(y_demeaned, y_demeaned, mode='full')
        mid = len(autocorr) // 2
        base = autocorr[mid]
        if base == 0:
            return None

        normalized = autocorr[mid + 1 :] / base
        peak_idx = int(np.argmax(normalized))
        peak_strength = float(normalized[peak_idx])

        if peak_strength < 0.5:
            return None

        period = peak_idx + 1
        end_idx = min(len(timestamps) - 1, period)

        return DetectedTemporalPattern(
            pattern_type=TemporalPattern.SEASONALITY,
            entity_id=entity_id,
            entity_type=metric,
            start_time=timestamps[0],
            end_time=timestamps[end_idx],
            confidence=min(peak_strength, 1.0),
            parameters={'period': period, 'autocorrelation': peak_strength},
            description=f"Seasonal pattern detected in {metric} with period {period}"
        )

    def _detect_change_point(self, entity_id: str, metric: str, x: np.ndarray, y: np.ndarray, timestamps: List[datetime]) -> Optional[DetectedTemporalPattern]:
        """Detect change point patterns."""
        if len(y) < 5:
            return None

        # Simple change point detection using variance
        max_variance_ratio = 0
        change_point_idx = -1

        for i in range(2, len(y) - 2):
            before = y[:i]
            after = y[i:]

            if len(before) > 1 and len(after) > 1:
                var_before = np.var(before)
                var_after = np.var(after)

                if var_before > 0:
                    variance_ratio = abs(var_after - var_before) / var_before
                    if variance_ratio > max_variance_ratio:
                        max_variance_ratio = variance_ratio
                        change_point_idx = i

        if max_variance_ratio > 0.5:  # Threshold for significant change
            return DetectedTemporalPattern(
                pattern_type=TemporalPattern.CHANGE_POINT,
                entity_id=entity_id,
                entity_type=metric,
                start_time=timestamps[max(0, change_point_idx - 1)],
                end_time=timestamps[min(len(timestamps) - 1, change_point_idx + 1)],
                confidence=min(max_variance_ratio, 1.0),
                parameters={'change_point_index': change_point_idx, 'variance_ratio': max_variance_ratio},
                description=f"Change point detected in {metric} at index {change_point_idx}"
            )

        return None

    def _detect_anomaly(self, entity_id: str, metric: str, x: np.ndarray, y: np.ndarray, timestamps: List[datetime]) -> Optional[DetectedTemporalPattern]:
        """Detect anomaly patterns."""
        if len(y) < 3:
            return None

        # Simple outlier detection using IQR
        q25 = np.percentile(y, 25)
        q75 = np.percentile(y, 75)
        iqr = q75 - q25

        lower_bound = q25 - 1.5 * iqr
        upper_bound = q75 + 1.5 * iqr

        outliers = []
        for i, value in enumerate(y):
            if value < lower_bound or value > upper_bound:
                outliers.append(i)

        if len(outliers) > 0:
            return DetectedTemporalPattern(
                pattern_type=TemporalPattern.ANOMALY,
                entity_id=entity_id,
                entity_type=metric,
                start_time=timestamps[outliers[0]],
                end_time=timestamps[outliers[-1]],
                confidence=len(outliers) / len(y),
                parameters={'outlier_indices': outliers, 'bounds': [lower_bound, upper_bound]},
                description=f"{len(outliers)} anomalies detected in {metric}"
            )

        return None

    def _detect_communities_in_snapshot(self, snapshot: TemporalSnapshot, min_size: int) -> List[Dict[str, Any]]:
        """Detect communities in a temporal snapshot."""
        # Simplified community detection (would use proper algorithms in production)
        communities = []

        # Group nodes by type as a simple community detection
        node_groups = defaultdict(list)
        for node in snapshot.nodes:
            node_type = node.properties.get('type', 'unknown')
            node_groups[node_type].append(node.node_id)

        for community_type, members in node_groups.items():
            if len(members) >= min_size:
                communities.append({
                    'id': f"{community_type}_{len(communities)}",
                    'type': community_type,
                    'members': members,
                    'size': len(members)
                })

        return communities

    def _analyze_community_stability(self, community_evolution: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Analyze stability of communities over time."""
        stable_communities = []

        # Track communities across time
        community_tracker = defaultdict(list)

        for timestamp_data in community_evolution:
            for community in timestamp_data['communities']:
                community_id = community['id']
                community_tracker[community_id].append({
                    'timestamp': timestamp_data['timestamp'],
                    'size': community['size'],
                    'members': set(community['members'])
                })

        # Identify stable communities
        for community_id, timeline in community_tracker.items():
            if len(timeline) >= 3:  # Appears in at least 3 snapshots
                stability_score = len(timeline) / len(community_evolution)

                stable_communities.append({
                    'community_id': community_id,
                    'stability_score': stability_score,
                    'appearances': len(timeline),
                    'avg_size': sum(t['size'] for t in timeline) / len(timeline),
                    'first_appearance': timeline[0]['timestamp'],
                    'last_appearance': timeline[-1]['timestamp']
                })

        return sorted(stable_communities, key=lambda x: x['stability_score'], reverse=True)

    def _build_node_filters(self, filters: Optional[Dict[str, Any]]) -> str:
        """Build node filtering conditions."""
        if not filters:
            return ""

        conditions = []
        for key, value in filters.items():
            if isinstance(value, str):
                conditions.append(f"n.{key} = '{value}'")
            else:
                conditions.append(f"n.{key} = {value}")

        return "AND " + " AND ".join(conditions) if conditions else ""

    def _build_edge_filters(self, filters: Optional[Dict[str, Any]]) -> str:
        """Build edge filtering conditions."""
        if not filters:
            return ""

        conditions = []
        for key, value in filters.items():
            if isinstance(value, str):
                conditions.append(f"r.{key} = '{value}'")
            else:
                conditions.append(f"r.{key} = {value}")

        return "AND " + " AND ".join(conditions) if conditions else ""

    def _update_query_stats(self, query_time_ms: float):
        """Update query performance statistics."""
        total_queries = self.query_stats['temporal_queries']
        current_avg = self.query_stats['avg_query_time_ms']

        self.query_stats['avg_query_time_ms'] = (
            (current_avg * (total_queries - 1) + query_time_ms) / total_queries
        )

    def get_temporal_statistics(self) -> Dict[str, Any]:
        """Get comprehensive temporal query statistics."""
        return {
            **self.query_stats,
            'cache_size': len(self.temporal_cache),
            'pattern_detectors_available': list(self.pattern_detectors.keys()),
            'versioning_enabled': self.enable_versioning
        }
