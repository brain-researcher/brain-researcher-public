"""Query pattern analyzer for performance monitoring - completes KG-011.

This module analyzes query patterns to identify performance bottlenecks and optimization opportunities.
"""

import logging
import re
import statistics
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class QueryPattern:
    """Represents a query pattern."""

    pattern_type: str
    pattern_value: str
    frequency: int = 0
    avg_execution_time: float = 0
    max_execution_time: float = 0
    min_execution_time: float = float("inf")
    examples: list[str] = field(default_factory=list)


@dataclass
class SlowQueryReport:
    """Report for slow queries."""

    query: str
    execution_time_ms: float
    timestamp: datetime
    pattern_matches: list[str]
    suggested_optimizations: list[str]


class PatternAnalyzer:
    """Analyze query patterns for performance optimization."""

    def __init__(self):
        """Initialize pattern analyzer."""
        self.patterns = self._define_patterns()
        self.slow_query_threshold_ms = 500
        self.query_history = []
        self.pattern_stats = defaultdict(lambda: QueryPattern("", ""))

    def _define_patterns(self) -> dict[str, re.Pattern]:
        """Define query patterns to detect."""
        return {
            # Problematic patterns
            "cartesian_product": re.compile(
                r"MATCH\s+\([^)]+\)\s*,\s*\([^)]+\)", re.IGNORECASE
            ),
            "missing_where": re.compile(r"MATCH\s+[^W]+RETURN", re.IGNORECASE),
            "unbounded_path": re.compile(r"\[\*\]|\[\*\.\.\]", re.IGNORECASE),
            "no_limit": re.compile(r"RETURN(?!.*LIMIT)", re.IGNORECASE),
            "large_collect": re.compile(
                r"collect\([^)]+\)(?!.*\[\.\.\d+\])", re.IGNORECASE
            ),
            # Optimization opportunities
            "missing_index_hint": re.compile(
                r"WHERE\s+\w+\.\w+\s*=(?!.*USING INDEX)", re.IGNORECASE
            ),
            "multiple_match": re.compile(r"(MATCH.*){3,}", re.IGNORECASE),
            "expensive_aggregation": re.compile(
                r"(count|sum|avg|collect)\s*\(\s*\*\s*\)", re.IGNORECASE
            ),
            "redundant_distinct": re.compile(r"DISTINCT.*DISTINCT", re.IGNORECASE),
            "nested_optional": re.compile(
                r"OPTIONAL MATCH.*OPTIONAL MATCH", re.IGNORECASE
            ),
            # Query types
            "simple_lookup": re.compile(
                r"^MATCH\s+\([^:]+:[^)]+\{[^}]+\}\)\s+RETURN", re.IGNORECASE
            ),
            "traversal": re.compile(r"MATCH.*-\[.*\]-.*RETURN", re.IGNORECASE),
            "aggregation": re.compile(
                r"(count|sum|avg|min|max|collect)\s*\(", re.IGNORECASE
            ),
            "path_query": re.compile(
                r"(shortestPath|allShortestPaths|path\s*=)", re.IGNORECASE
            ),
            "write_query": re.compile(r"(CREATE|MERGE|DELETE|SET)", re.IGNORECASE),
        }

    def analyze_query(self, query: str, execution_time_ms: float) -> dict[str, Any]:
        """Analyze a single query.

        Args:
            query: Cypher query
            execution_time_ms: Execution time in milliseconds

        Returns:
            Analysis results
        """
        analysis = {
            "query": query,
            "execution_time_ms": execution_time_ms,
            "patterns_detected": [],
            "query_type": None,
            "is_slow": execution_time_ms > self.slow_query_threshold_ms,
            "optimizations": [],
        }

        # Detect patterns
        for pattern_name, pattern_regex in self.patterns.items():
            if pattern_regex.search(query):
                analysis["patterns_detected"].append(pattern_name)

                # Update pattern statistics
                self._update_pattern_stats(pattern_name, query, execution_time_ms)

                # Determine query type
                if pattern_name in [
                    "simple_lookup",
                    "traversal",
                    "aggregation",
                    "path_query",
                    "write_query",
                ]:
                    analysis["query_type"] = pattern_name

        # Suggest optimizations
        analysis["optimizations"] = self._suggest_optimizations(
            analysis["patterns_detected"]
        )

        # Add to history
        self.query_history.append(
            {
                "query": query,
                "execution_time_ms": execution_time_ms,
                "timestamp": datetime.now(),
                "patterns": analysis["patterns_detected"],
            }
        )

        return analysis

    def _update_pattern_stats(
        self, pattern_name: str, query: str, execution_time_ms: float
    ):
        """Update statistics for a pattern.

        Args:
            pattern_name: Name of the pattern
            query: Example query
            execution_time_ms: Execution time
        """
        stats = self.pattern_stats[pattern_name]
        stats.pattern_type = pattern_name
        stats.frequency += 1

        # Update execution times
        if stats.avg_execution_time == 0:
            stats.avg_execution_time = execution_time_ms
        else:
            stats.avg_execution_time = (
                stats.avg_execution_time * (stats.frequency - 1) + execution_time_ms
            ) / stats.frequency

        stats.max_execution_time = max(stats.max_execution_time, execution_time_ms)
        stats.min_execution_time = min(stats.min_execution_time, execution_time_ms)

        # Keep up to 5 examples
        if len(stats.examples) < 5 and query not in stats.examples:
            stats.examples.append(query[:200])  # Truncate long queries

    def _suggest_optimizations(self, patterns: list[str]) -> list[str]:
        """Suggest optimizations based on detected patterns.

        Args:
            patterns: Detected patterns

        Returns:
            List of optimization suggestions
        """
        suggestions = []

        if "cartesian_product" in patterns:
            suggestions.append(
                "Add relationships between disconnected patterns to avoid cartesian product"
            )

        if "missing_where" in patterns:
            suggestions.append("Add WHERE clause to filter results early")

        if "unbounded_path" in patterns:
            suggestions.append(
                "Add upper bound to variable-length paths (e.g., [*1..5])"
            )

        if "no_limit" in patterns:
            suggestions.append("Add LIMIT clause to restrict result size")

        if "large_collect" in patterns:
            suggestions.append(
                "Limit collected items with slice notation (e.g., collect(n)[..100])"
            )

        if "missing_index_hint" in patterns:
            suggestions.append("Consider adding index hints for equality filters")

        if "multiple_match" in patterns:
            suggestions.append("Use WITH clause to separate MATCH patterns")

        if "expensive_aggregation" in patterns:
            suggestions.append("Avoid count(*) - count specific properties instead")

        if "redundant_distinct" in patterns:
            suggestions.append("Remove redundant DISTINCT keywords")

        if "nested_optional" in patterns:
            suggestions.append("Combine nested OPTIONAL MATCH clauses")

        return suggestions

    def analyze_patterns(self, time_window: timedelta | None = None) -> dict[str, Any]:
        """Analyze patterns in query history.

        Args:
            time_window: Time window to analyze (default: all history)

        Returns:
            Pattern analysis report
        """
        # Filter by time window if specified
        queries = self.query_history
        if time_window:
            cutoff = datetime.now() - time_window
            queries = [q for q in queries if q["timestamp"] >= cutoff]

        if not queries:
            return {"message": "No queries to analyze"}

        # Overall statistics
        execution_times = [q["execution_time_ms"] for q in queries]

        report = {
            "time_period": {
                "start": min(q["timestamp"] for q in queries),
                "end": max(q["timestamp"] for q in queries),
                "total_queries": len(queries),
            },
            "performance": {
                "avg_execution_time_ms": statistics.mean(execution_times),
                "median_execution_time_ms": statistics.median(execution_times),
                "p95_execution_time_ms": (
                    statistics.quantiles(execution_times, n=20)[18]
                    if len(execution_times) > 20
                    else max(execution_times)
                ),
                "max_execution_time_ms": max(execution_times),
                "min_execution_time_ms": min(execution_times),
            },
            "slow_queries": [],
            "pattern_frequency": {},
            "problematic_patterns": [],
            "optimization_opportunities": [],
        }

        # Identify slow queries
        slow_queries = [
            q for q in queries if q["execution_time_ms"] > self.slow_query_threshold_ms
        ]
        report["slow_queries"] = [
            {
                "query": q["query"][:200],
                "execution_time_ms": q["execution_time_ms"],
                "timestamp": q["timestamp"].isoformat(),
                "patterns": q["patterns"],
            }
            for q in sorted(
                slow_queries, key=lambda x: x["execution_time_ms"], reverse=True
            )[:10]
        ]

        # Pattern frequency analysis
        pattern_counter = Counter()
        for q in queries:
            pattern_counter.update(q["patterns"])

        report["pattern_frequency"] = dict(pattern_counter.most_common())

        # Identify problematic patterns
        problematic = [
            "cartesian_product",
            "unbounded_path",
            "missing_where",
            "no_limit",
        ]
        for pattern in problematic:
            if pattern in self.pattern_stats:
                stats = self.pattern_stats[pattern]
                if stats.frequency > 0:
                    report["problematic_patterns"].append(
                        {
                            "pattern": pattern,
                            "frequency": stats.frequency,
                            "avg_execution_time_ms": stats.avg_execution_time,
                            "impact": (
                                "HIGH" if stats.avg_execution_time > 1000 else "MEDIUM"
                            ),
                        }
                    )

        # Optimization opportunities
        optimization_patterns = [
            "missing_index_hint",
            "multiple_match",
            "expensive_aggregation",
        ]
        for pattern in optimization_patterns:
            if pattern in self.pattern_stats:
                stats = self.pattern_stats[pattern]
                if stats.frequency > 5:  # Only suggest if pattern is frequent
                    report["optimization_opportunities"].append(
                        {
                            "pattern": pattern,
                            "frequency": stats.frequency,
                            "potential_improvement_ms": stats.avg_execution_time
                            * 0.3,  # Estimate 30% improvement
                            "examples": stats.examples[:2],
                        }
                    )

        return report

    def detect_anomalies(self) -> list[dict[str, Any]]:
        """Detect anomalous query patterns.

        Returns:
            List of anomalies
        """
        anomalies = []

        # Check for sudden performance degradation
        if len(self.query_history) > 100:
            recent = self.query_history[-20:]
            older = self.query_history[-100:-20]

            recent_avg = statistics.mean([q["execution_time_ms"] for q in recent])
            older_avg = statistics.mean([q["execution_time_ms"] for q in older])

            if recent_avg > older_avg * 2:
                anomalies.append(
                    {
                        "type": "performance_degradation",
                        "description": f"Recent queries 2x slower: {recent_avg:.0f}ms vs {older_avg:.0f}ms",
                        "severity": "HIGH",
                    }
                )

        # Check for unusual patterns
        for pattern_name, stats in self.pattern_stats.items():
            if pattern_name in ["cartesian_product", "unbounded_path"]:
                if stats.frequency > 10:
                    anomalies.append(
                        {
                            "type": "problematic_pattern",
                            "pattern": pattern_name,
                            "frequency": stats.frequency,
                            "description": f"Problematic pattern '{pattern_name}' detected {stats.frequency} times",
                            "severity": "MEDIUM",
                        }
                    )

        # Check for missing optimizations
        total_queries = len(self.query_history)
        if total_queries > 0:
            no_limit_ratio = (
                self.pattern_stats.get("no_limit", QueryPattern("", "")).frequency
                / total_queries
            )
            if no_limit_ratio > 0.3:
                anomalies.append(
                    {
                        "type": "missing_optimization",
                        "description": f"{no_limit_ratio*100:.0f}% of queries missing LIMIT clause",
                        "severity": "LOW",
                    }
                )

        return anomalies

    def recommend_indexes(self) -> list[dict[str, str]]:
        """Recommend indexes based on query patterns.

        Returns:
            Index recommendations
        """
        recommendations = []
        seen_indexes = set()

        # Analyze WHERE clauses in slow queries
        slow_queries = [
            q
            for q in self.query_history
            if q["execution_time_ms"] > self.slow_query_threshold_ms
        ]

        for query_info in slow_queries:
            query = query_info["query"]

            # Look for WHERE clauses
            where_pattern = re.compile(r"WHERE\s+(\w+)\.(\w+)\s*=", re.IGNORECASE)
            matches = where_pattern.findall(query)

            for alias, property_name in matches:
                # Try to find the label for this alias
                label_pattern = re.compile(f"\\({alias}:(\\w+)\\)", re.IGNORECASE)
                label_match = label_pattern.search(query)

                if label_match:
                    label = label_match.group(1)
                    index_key = f"{label}.{property_name}"

                    if index_key not in seen_indexes:
                        seen_indexes.add(index_key)
                        recommendations.append(
                            {
                                "label": label,
                                "property": property_name,
                                "command": f"CREATE INDEX ON :{label}({property_name})",
                                "reason": f"Used in WHERE clause of slow query ({query_info['execution_time_ms']:.0f}ms)",
                                "expected_improvement": "30-50%",
                            }
                        )

        return recommendations[:10]  # Limit to top 10 recommendations

    def generate_report(self) -> str:
        """Generate comprehensive analysis report.

        Returns:
            Formatted report
        """
        analysis = self.analyze_patterns()
        anomalies = self.detect_anomalies()
        index_recommendations = self.recommend_indexes()

        report = []
        report.append("=" * 60)
        report.append("BR_KG QUERY PATTERN ANALYSIS REPORT")
        report.append("=" * 60)

        # Time period
        if "time_period" in analysis:
            period = analysis["time_period"]
            report.append(f"\nAnalysis Period: {period['start']} to {period['end']}")
            report.append(f"Total Queries Analyzed: {period['total_queries']}")

        # Performance summary
        if "performance" in analysis:
            perf = analysis["performance"]
            report.append("\nPerformance Summary:")
            report.append(f"  Average: {perf['avg_execution_time_ms']:.0f}ms")
            report.append(f"  Median: {perf['median_execution_time_ms']:.0f}ms")
            report.append(f"  P95: {perf['p95_execution_time_ms']:.0f}ms")
            report.append(f"  Max: {perf['max_execution_time_ms']:.0f}ms")

        # Anomalies
        if anomalies:
            report.append("\n⚠️ Anomalies Detected:")
            for anomaly in anomalies:
                report.append(f"  [{anomaly['severity']}] {anomaly['description']}")

        # Problematic patterns
        if analysis.get("problematic_patterns"):
            report.append("\n❌ Problematic Patterns:")
            for pattern in analysis["problematic_patterns"]:
                report.append(
                    f"  {pattern['pattern']}: {pattern['frequency']} occurrences, avg {pattern['avg_execution_time_ms']:.0f}ms"
                )

        # Optimization opportunities
        if analysis.get("optimization_opportunities"):
            report.append("\n💡 Optimization Opportunities:")
            for opp in analysis["optimization_opportunities"]:
                report.append(
                    f"  {opp['pattern']}: {opp['frequency']} queries could save ~{opp['potential_improvement_ms']:.0f}ms"
                )

        # Index recommendations
        if index_recommendations:
            report.append("\n🔧 Recommended Indexes:")
            for rec in index_recommendations[:5]:
                report.append(f"  {rec['command']}")
                report.append(f"    Reason: {rec['reason']}")

        # Slow queries
        if analysis.get("slow_queries"):
            report.append("\n🐌 Slowest Queries:")
            for sq in analysis["slow_queries"][:3]:
                report.append(
                    f"  {sq['execution_time_ms']:.0f}ms: {sq['query'][:100]}..."
                )

        report.append("\n" + "=" * 60)

        return "\n".join(report)
