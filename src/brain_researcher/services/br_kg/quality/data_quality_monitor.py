"""Data Quality Monitoring - completes KG-026.

This module provides automated data quality checks, anomaly detection,
and quality reports for the knowledge graph.
"""

import logging
from typing import Dict, List, Any, Optional, Set, Tuple
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
import statistics
import numpy as np
from collections import defaultdict
import json

logger = logging.getLogger(__name__)


class QualityMetric(Enum):
    """Types of quality metrics."""

    COMPLETENESS = "completeness"
    CONSISTENCY = "consistency"
    ACCURACY = "accuracy"
    UNIQUENESS = "uniqueness"
    TIMELINESS = "timeliness"
    VALIDITY = "validity"


class AnomalyType(Enum):
    """Types of anomalies."""

    MISSING_REQUIRED = "missing_required"
    DUPLICATE_ENTITY = "duplicate_entity"
    ORPHAN_NODE = "orphan_node"
    INVALID_REFERENCE = "invalid_reference"
    OUTLIER_VALUE = "outlier_value"
    SCHEMA_VIOLATION = "schema_violation"
    TEMPORAL_INCONSISTENCY = "temporal_inconsistency"


@dataclass
class QualityIssue:
    """Represents a data quality issue."""

    issue_type: AnomalyType
    severity: str  # "critical", "high", "medium", "low"
    entity_type: str
    entity_id: str
    field: Optional[str]
    description: str
    suggested_fix: Optional[str] = None
    detected_at: datetime = field(default_factory=datetime.now)


@dataclass
class QualityReport:
    """Comprehensive quality report."""

    report_id: str
    generated_at: datetime
    period_start: datetime
    period_end: datetime
    overall_score: float
    metrics: Dict[str, float]
    issues: List[QualityIssue]
    trends: Dict[str, List[float]]
    recommendations: List[str]


class DataQualityMonitor:
    """Monitor and report on data quality."""

    def __init__(self, neo4j_driver, redis_client=None):
        """Initialize data quality monitor.

        Args:
            neo4j_driver: Neo4j driver instance
            redis_client: Optional Redis client for caching
        """
        self.driver = neo4j_driver
        self.redis = redis_client
        self.quality_rules = self._define_quality_rules()
        self.anomaly_detectors = self._initialize_detectors()
        self.metric_history = defaultdict(list)

    def _define_quality_rules(self) -> Dict[str, Any]:
        """Define quality rules for different entity types."""
        return {
            "Task": {
                "required_fields": ["id", "name", "description"],
                "unique_fields": ["id", "name"],
                "reference_fields": {"dataset_id": "Dataset"},
                "value_ranges": {
                    "difficulty": (1, 10),
                    "duration_seconds": (0, 3600)
                }
            },
            "Concept": {
                "required_fields": ["id", "name", "definition"],
                "unique_fields": ["id"],
                "reference_fields": {"parent_id": "Concept"},
                "value_ranges": {
                    "weight": (0, 1)
                }
            },
            "Region": {
                "required_fields": ["id", "name", "coordinates"],
                "unique_fields": ["id"],
                "reference_fields": {},
                "value_ranges": {
                    "x": (-100, 100),
                    "y": (-100, 100),
                    "z": (-100, 100),
                    "volume": (0, 10000)
                }
            },
            "Dataset": {
                "required_fields": ["id", "name", "source"],
                "unique_fields": ["id"],
                "reference_fields": {},
                "value_ranges": {
                    "size_gb": (0, 10000),
                    "num_subjects": (1, 100000)
                }
            },
            "Publication": {
                "required_fields": ["id", "title", "authors"],
                "unique_fields": ["id", "doi"],
                "reference_fields": {},
                "value_ranges": {
                    "year": (1900, 2030),
                    "citation_count": (0, 100000)
                }
            }
        }

    def _initialize_detectors(self) -> Dict[str, Any]:
        """Initialize anomaly detection algorithms."""
        return {
            "isolation_forest": {
                "contamination": 0.1,
                "n_estimators": 100
            },
            "zscore": {
                "threshold": 3.0
            },
            "iqr": {
                "factor": 1.5
            },
            "temporal": {
                "window_size": 7,
                "trend_threshold": 0.3
            }
        }

    def calculate_metrics(self, entity_type: Optional[str] = None) -> Dict[str, float]:
        """Calculate quality metrics.

        Args:
            entity_type: Optional entity type filter

        Returns:
            Dictionary of metrics
        """
        metrics = {}

        with self.driver.session() as session:
            # Completeness
            metrics["completeness"] = self._calculate_completeness(session, entity_type)

            # Consistency
            metrics["consistency"] = self._calculate_consistency(session, entity_type)

            # Uniqueness
            metrics["uniqueness"] = self._calculate_uniqueness(session, entity_type)

            # Validity
            metrics["validity"] = self._calculate_validity(session, entity_type)

            # Timeliness
            metrics["timeliness"] = self._calculate_timeliness(session, entity_type)

            # Overall score
            metrics["overall"] = np.mean(list(metrics.values()))

        # Store in history
        self.metric_history[entity_type or "all"].append({
            "timestamp": datetime.now().isoformat(),
            "metrics": metrics
        })

        return metrics

    def _calculate_completeness(self, session, entity_type: Optional[str]) -> float:
        """Calculate completeness metric."""
        if entity_type:
            types = [entity_type]
        else:
            types = list(self.quality_rules.keys())

        completeness_scores = []

        for etype in types:
            rules = self.quality_rules.get(etype, {})
            required_fields = rules.get("required_fields", [])

            if not required_fields:
                continue

            query = f"""
            MATCH (n:{etype})
            WITH n,
                 [{field} IN $required WHERE n[{field}] IS NOT NULL] as present_fields
            RETURN avg(size(present_fields) * 1.0 / $num_required) as completeness
            """

            result = session.run(query, {
                "required": required_fields,
                "num_required": len(required_fields)
            }).single()

            if result and result["completeness"] is not None:
                completeness_scores.append(result["completeness"])

        return np.mean(completeness_scores) if completeness_scores else 0.0

    def _calculate_consistency(self, session, entity_type: Optional[str]) -> float:
        """Calculate consistency metric."""
        consistency_checks = []

        # Check for referential integrity
        query = """
        MATCH (n)-[r]->(m)
        WHERE NOT exists(m.id)
        RETURN count(r) as invalid_refs
        """
        result = session.run(query).single()
        invalid_refs = result["invalid_refs"] if result else 0

        # Total relationships
        total_query = """
        MATCH ()-[r]->()
        RETURN count(r) as total
        """
        total_result = session.run(total_query).single()
        total_refs = total_result["total"] if total_result else 1

        ref_consistency = 1.0 - (invalid_refs / total_refs) if total_refs > 0 else 1.0
        consistency_checks.append(ref_consistency)

        # Check for schema consistency
        if entity_type:
            types = [entity_type]
        else:
            types = list(self.quality_rules.keys())

        for etype in types:
            query = f"""
            MATCH (n:{etype})
            WITH keys(n) as node_keys
            WITH collect(node_keys) as all_keys
            WITH reduce(common = head(all_keys), k IN tail(all_keys) |
                 [x IN common WHERE x IN k]) as common_keys,
                 all_keys
            RETURN size(common_keys) * 1.0 / avg([size(k) for k in all_keys]) as consistency
            """

            result = session.run(query).single()
            if result and result["consistency"] is not None:
                consistency_checks.append(result["consistency"])

        return np.mean(consistency_checks) if consistency_checks else 0.0

    def _calculate_uniqueness(self, session, entity_type: Optional[str]) -> float:
        """Calculate uniqueness metric."""
        uniqueness_scores = []

        if entity_type:
            types = [entity_type]
        else:
            types = list(self.quality_rules.keys())

        for etype in types:
            rules = self.quality_rules.get(etype, {})
            unique_fields = rules.get("unique_fields", [])

            for field in unique_fields:
                query = f"""
                MATCH (n:{etype})
                WHERE n.{field} IS NOT NULL
                WITH n.{field} as value, count(*) as cnt
                WITH sum(CASE WHEN cnt > 1 THEN cnt - 1 ELSE 0 END) as duplicates,
                     sum(cnt) as total
                RETURN 1.0 - (duplicates * 1.0 / total) as uniqueness
                """

                result = session.run(query).single()
                if result and result["uniqueness"] is not None:
                    uniqueness_scores.append(result["uniqueness"])

        return np.mean(uniqueness_scores) if uniqueness_scores else 1.0

    def _calculate_validity(self, session, entity_type: Optional[str]) -> float:
        """Calculate validity metric."""
        validity_scores = []

        if entity_type:
            types = [entity_type]
        else:
            types = list(self.quality_rules.keys())

        for etype in types:
            rules = self.quality_rules.get(etype, {})
            value_ranges = rules.get("value_ranges", {})

            for field, (min_val, max_val) in value_ranges.items():
                query = f"""
                MATCH (n:{etype})
                WHERE n.{field} IS NOT NULL
                WITH n.{field} as value
                WITH sum(CASE WHEN value >= $min AND value <= $max THEN 1 ELSE 0 END) as valid,
                     count(*) as total
                RETURN valid * 1.0 / total as validity
                """

                result = session.run(query, {"min": min_val, "max": max_val}).single()
                if result and result["validity"] is not None:
                    validity_scores.append(result["validity"])

        return np.mean(validity_scores) if validity_scores else 1.0

    def _calculate_timeliness(self, session, entity_type: Optional[str]) -> float:
        """Calculate timeliness metric."""
        # Check how recent the data is
        query = """
        MATCH (n)
        WHERE n.updated_at IS NOT NULL OR n.created_at IS NOT NULL
        WITH coalesce(n.updated_at, n.created_at) as timestamp
        WITH max(timestamp) as latest, min(timestamp) as earliest
        RETURN latest, earliest
        """

        result = session.run(query).single()

        if not result:
            return 0.5

        try:
            latest = datetime.fromisoformat(result["latest"])
            age_days = (datetime.now() - latest).days

            # Score based on age
            if age_days < 1:
                return 1.0
            elif age_days < 7:
                return 0.9
            elif age_days < 30:
                return 0.7
            elif age_days < 90:
                return 0.5
            else:
                return 0.3
        except:
            return 0.5

    def detect_anomalies(self) -> List[QualityIssue]:
        """Detect anomalies in the graph data.

        Returns:
            List of quality issues
        """
        issues = []

        with self.driver.session() as session:
            # Missing required fields
            issues.extend(self._detect_missing_required(session))

            # Duplicate entities
            issues.extend(self._detect_duplicates(session))

            # Orphan nodes
            issues.extend(self._detect_orphans(session))

            # Invalid references
            issues.extend(self._detect_invalid_references(session))

            # Statistical outliers
            issues.extend(self._detect_outliers(session))

            # Schema violations
            issues.extend(self._detect_schema_violations(session))

            # Temporal inconsistencies
            issues.extend(self._detect_temporal_inconsistencies(session))

        return issues

    def _detect_missing_required(self, session) -> List[QualityIssue]:
        """Detect missing required fields."""
        issues = []

        for entity_type, rules in self.quality_rules.items():
            required_fields = rules.get("required_fields", [])

            for field in required_fields:
                query = f"""
                MATCH (n:{entity_type})
                WHERE n.{field} IS NULL
                RETURN n.id as entity_id, '{field}' as missing_field
                LIMIT 100
                """

                result = session.run(query)

                for record in result:
                    issues.append(QualityIssue(
                        issue_type=AnomalyType.MISSING_REQUIRED,
                        severity="high",
                        entity_type=entity_type,
                        entity_id=record["entity_id"],
                        field=record["missing_field"],
                        description=f"Required field '{field}' is missing",
                        suggested_fix=f"Add value for '{field}' field"
                    ))

        return issues

    def _detect_duplicates(self, session) -> List[QualityIssue]:
        """Detect duplicate entities."""
        issues = []

        for entity_type, rules in self.quality_rules.items():
            unique_fields = rules.get("unique_fields", [])

            for field in unique_fields:
                query = f"""
                MATCH (n:{entity_type})
                WHERE n.{field} IS NOT NULL
                WITH n.{field} as value, collect(n.id) as ids
                WHERE size(ids) > 1
                RETURN value, ids
                LIMIT 50
                """

                result = session.run(query)

                for record in result:
                    for entity_id in record["ids"][1:]:  # Skip first, report others
                        issues.append(QualityIssue(
                            issue_type=AnomalyType.DUPLICATE_ENTITY,
                            severity="medium",
                            entity_type=entity_type,
                            entity_id=entity_id,
                            field=field,
                            description=f"Duplicate value '{record['value']}' for unique field '{field}'",
                            suggested_fix=f"Merge with entity {record['ids'][0]}"
                        ))

        return issues

    def _detect_orphans(self, session) -> List[QualityIssue]:
        """Detect orphan nodes."""
        issues = []

        query = """
        MATCH (n)
        WHERE NOT (n)--()
        RETURN labels(n)[0] as entity_type, n.id as entity_id
        LIMIT 100
        """

        result = session.run(query)

        for record in result:
            issues.append(QualityIssue(
                issue_type=AnomalyType.ORPHAN_NODE,
                severity="low",
                entity_type=record["entity_type"],
                entity_id=record["entity_id"],
                field=None,
                description="Node has no relationships",
                suggested_fix="Connect to related entities or remove"
            ))

        return issues

    def _detect_invalid_references(self, session) -> List[QualityIssue]:
        """Detect invalid references."""
        issues = []

        for entity_type, rules in self.quality_rules.items():
            reference_fields = rules.get("reference_fields", {})

            for field, target_type in reference_fields.items():
                query = f"""
                MATCH (n:{entity_type})
                WHERE n.{field} IS NOT NULL
                AND NOT exists((:{target_type} {{id: n.{field}}}))
                RETURN n.id as entity_id, n.{field} as invalid_ref
                LIMIT 50
                """

                result = session.run(query)

                for record in result:
                    issues.append(QualityIssue(
                        issue_type=AnomalyType.INVALID_REFERENCE,
                        severity="high",
                        entity_type=entity_type,
                        entity_id=record["entity_id"],
                        field=field,
                        description=f"Invalid reference '{record['invalid_ref']}' to {target_type}",
                        suggested_fix=f"Update reference or create missing {target_type}"
                    ))

        return issues

    def _detect_outliers(self, session) -> List[QualityIssue]:
        """Detect statistical outliers using Z-score method."""
        issues = []

        for entity_type, rules in self.quality_rules.items():
            value_ranges = rules.get("value_ranges", {})

            for field, _ in value_ranges.items():
                # Get field values
                query = f"""
                MATCH (n:{entity_type})
                WHERE n.{field} IS NOT NULL
                RETURN n.id as entity_id, n.{field} as value
                """

                result = session.run(query)
                data = [(r["entity_id"], r["value"]) for r in result]

                if len(data) < 10:  # Need minimum data for statistics
                    continue

                values = [v for _, v in data]
                mean = statistics.mean(values)
                stdev = statistics.stdev(values)

                if stdev == 0:
                    continue

                # Detect outliers using Z-score
                threshold = self.anomaly_detectors["zscore"]["threshold"]

                for entity_id, value in data:
                    z_score = abs((value - mean) / stdev)

                    if z_score > threshold:
                        issues.append(QualityIssue(
                            issue_type=AnomalyType.OUTLIER_VALUE,
                            severity="medium",
                            entity_type=entity_type,
                            entity_id=entity_id,
                            field=field,
                            description=f"Outlier value {value} (Z-score: {z_score:.2f})",
                            suggested_fix=f"Verify value is correct (expected range: {mean-2*stdev:.2f} to {mean+2*stdev:.2f})"
                        ))

        return issues

    def _detect_schema_violations(self, session) -> List[QualityIssue]:
        """Detect schema violations."""
        issues = []

        # Check for unexpected node labels
        query = """
        MATCH (n)
        WITH labels(n) as node_labels
        WHERE size(node_labels) > 1
        RETURN node_labels
        LIMIT 50
        """

        result = session.run(query)

        for record in result:
            issues.append(QualityIssue(
                issue_type=AnomalyType.SCHEMA_VIOLATION,
                severity="low",
                entity_type=str(record["node_labels"]),
                entity_id="multiple",
                field=None,
                description=f"Node has multiple labels: {record['node_labels']}",
                suggested_fix="Ensure single label per node"
            ))

        return issues

    def _detect_temporal_inconsistencies(self, session) -> List[QualityIssue]:
        """Detect temporal inconsistencies."""
        issues = []

        # Check for future dates
        query = """
        MATCH (n)
        WHERE n.created_at > datetime() OR n.updated_at > datetime()
        RETURN labels(n)[0] as entity_type, n.id as entity_id,
               n.created_at as created, n.updated_at as updated
        LIMIT 50
        """

        result = session.run(query)

        for record in result:
            issues.append(QualityIssue(
                issue_type=AnomalyType.TEMPORAL_INCONSISTENCY,
                severity="medium",
                entity_type=record["entity_type"],
                entity_id=record["entity_id"],
                field="timestamp",
                description="Timestamp is in the future",
                suggested_fix="Correct timestamp to valid past date"
            ))

        # Check for update before creation
        query2 = """
        MATCH (n)
        WHERE n.created_at IS NOT NULL AND n.updated_at IS NOT NULL
        AND n.updated_at < n.created_at
        RETURN labels(n)[0] as entity_type, n.id as entity_id
        LIMIT 50
        """

        result2 = session.run(query2)

        for record in result2:
            issues.append(QualityIssue(
                issue_type=AnomalyType.TEMPORAL_INCONSISTENCY,
                severity="medium",
                entity_type=record["entity_type"],
                entity_id=record["entity_id"],
                field="timestamp",
                description="Updated before created",
                suggested_fix="Correct timestamp order"
            ))

        return issues

    def generate_report(
        self,
        period_days: int = 7,
        include_trends: bool = True
    ) -> QualityReport:
        """Generate comprehensive quality report.

        Args:
            period_days: Period to analyze
            include_trends: Include trend analysis

        Returns:
            Quality report
        """
        report_id = f"QR-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
        period_end = datetime.now()
        period_start = period_end - timedelta(days=period_days)

        # Calculate current metrics
        metrics = self.calculate_metrics()

        # Detect anomalies
        issues = self.detect_anomalies()

        # Analyze trends
        trends = {}
        if include_trends:
            trends = self._analyze_trends(period_days)

        # Generate recommendations
        recommendations = self._generate_recommendations(metrics, issues, trends)

        # Calculate overall score
        overall_score = self._calculate_overall_score(metrics, len(issues))

        report = QualityReport(
            report_id=report_id,
            generated_at=datetime.now(),
            period_start=period_start,
            period_end=period_end,
            overall_score=overall_score,
            metrics=metrics,
            issues=issues[:100],  # Limit to top 100 issues
            trends=trends,
            recommendations=recommendations
        )

        # Save report
        self._save_report(report)

        return report

    def _analyze_trends(self, period_days: int) -> Dict[str, List[float]]:
        """Analyze quality trends over time."""
        trends = {}

        for entity_type in ["all"] + list(self.quality_rules.keys()):
            history = self.metric_history.get(entity_type, [])

            if not history:
                continue

            # Get recent history
            cutoff = datetime.now() - timedelta(days=period_days)
            recent = [
                h for h in history
                if datetime.fromisoformat(h["timestamp"]) >= cutoff
            ]

            if not recent:
                continue

            # Extract metric trends
            for metric in ["completeness", "consistency", "validity", "overall"]:
                values = [h["metrics"].get(metric, 0) for h in recent]
                if values:
                    trends[f"{entity_type}_{metric}"] = values

        return trends

    def _generate_recommendations(
        self,
        metrics: Dict[str, float],
        issues: List[QualityIssue],
        trends: Dict[str, List[float]]
    ) -> List[str]:
        """Generate recommendations based on analysis."""
        recommendations = []

        # Based on metrics
        if metrics.get("completeness", 1) < 0.8:
            recommendations.append("Improve data completeness by filling missing required fields")

        if metrics.get("consistency", 1) < 0.8:
            recommendations.append("Review and fix referential integrity issues")

        if metrics.get("uniqueness", 1) < 0.95:
            recommendations.append("Resolve duplicate entities to improve uniqueness")

        if metrics.get("validity", 1) < 0.9:
            recommendations.append("Validate field values against defined ranges")

        # Based on issues
        issue_counts = defaultdict(int)
        for issue in issues:
            issue_counts[issue.issue_type] += 1

        if issue_counts[AnomalyType.MISSING_REQUIRED] > 10:
            recommendations.append("Implement validation on data entry to prevent missing required fields")

        if issue_counts[AnomalyType.DUPLICATE_ENTITY] > 5:
            recommendations.append("Implement duplicate detection before entity creation")

        if issue_counts[AnomalyType.ORPHAN_NODE] > 20:
            recommendations.append("Review orphan nodes and establish proper relationships")

        # Based on trends
        for key, values in trends.items():
            if len(values) > 3:
                # Check for declining trend
                if values[-1] < values[0] * 0.9:
                    metric_name = key.split("_")[-1]
                    recommendations.append(f"Address declining {metric_name} trend in {key.split('_')[0]}")

        return recommendations[:10]  # Top 10 recommendations

    def _calculate_overall_score(self, metrics: Dict[str, float], issue_count: int) -> float:
        """Calculate overall quality score."""
        # Base score from metrics
        base_score = metrics.get("overall", 0.5)

        # Penalty for issues
        issue_penalty = min(0.3, issue_count * 0.01)

        return max(0, min(1, base_score - issue_penalty))

    def _save_report(self, report: QualityReport):
        """Save report to storage."""
        # Save to Redis if available
        if self.redis:
            key = f"quality:report:{report.report_id}"
            self.redis.setex(
                key,
                86400 * 30,  # 30 days TTL
                json.dumps({
                    "report_id": report.report_id,
                    "generated_at": report.generated_at.isoformat(),
                    "overall_score": report.overall_score,
                    "metrics": report.metrics,
                    "issue_count": len(report.issues),
                    "recommendations": report.recommendations
                })
            )

        # Log summary
        logger.info(
            f"Generated quality report {report.report_id}: "
            f"Score={report.overall_score:.2f}, Issues={len(report.issues)}"
        )

    def export_report(self, report: QualityReport, format: str = "json") -> str:
        """Export report in specified format.

        Args:
            report: Quality report
            format: Export format (json, html, markdown)

        Returns:
            Formatted report string
        """
        if format == "json":
            return json.dumps({
                "report_id": report.report_id,
                "generated_at": report.generated_at.isoformat(),
                "period": {
                    "start": report.period_start.isoformat(),
                    "end": report.period_end.isoformat()
                },
                "overall_score": report.overall_score,
                "metrics": report.metrics,
                "issues": [
                    {
                        "type": issue.issue_type.value,
                        "severity": issue.severity,
                        "entity_type": issue.entity_type,
                        "entity_id": issue.entity_id,
                        "description": issue.description,
                        "suggested_fix": issue.suggested_fix
                    }
                    for issue in report.issues
                ],
                "trends": report.trends,
                "recommendations": report.recommendations
            }, indent=2)

        elif format == "markdown":
            md = []
            md.append(f"# Data Quality Report {report.report_id}")
            md.append(f"\n**Generated:** {report.generated_at.isoformat()}")
            md.append(f"**Period:** {report.period_start.date()} to {report.period_end.date()}")
            md.append(f"\n## Overall Score: {report.overall_score:.1%}")

            md.append("\n## Metrics")
            for metric, value in report.metrics.items():
                md.append(f"- **{metric.title()}:** {value:.1%}")

            md.append(f"\n## Issues Found: {len(report.issues)}")

            # Group issues by type
            issues_by_type = defaultdict(list)
            for issue in report.issues[:20]:  # Show top 20
                issues_by_type[issue.issue_type.value].append(issue)

            for issue_type, type_issues in issues_by_type.items():
                md.append(f"\n### {issue_type.replace('_', ' ').title()} ({len(type_issues)})")
                for issue in type_issues[:5]:  # Show top 5 per type
                    md.append(f"- {issue.entity_type} {issue.entity_id}: {issue.description}")

            md.append("\n## Recommendations")
            for i, rec in enumerate(report.recommendations, 1):
                md.append(f"{i}. {rec}")

            return "\n".join(md)

        else:
            raise ValueError(f"Unsupported format: {format}")