"""
UsageMetricsAggregator - Advanced data aggregation and analysis engine.
"""

import logging
import statistics
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from .models import (
    EventType,
    FeatureUsage,
    MetricType,
    PrivacyLevel,
    ServiceType,
    TelemetryEvent,
    UsageMetric,
    UserJourney,
)

logger = logging.getLogger(__name__)


@dataclass
class AggregationWindow:
    """Time window for metric aggregation."""

    start: datetime
    end: datetime
    granularity: str  # 'hour', 'day', 'week', 'month'

    @property
    def duration(self) -> timedelta:
        return self.end - self.start

    @property
    def duration_seconds(self) -> float:
        return self.duration.total_seconds()


@dataclass
class AggregationConfig:
    """Configuration for metrics aggregation."""

    # Time windows
    default_window_hours: int = 24
    max_window_days: int = 90
    real_time_window_minutes: int = 15

    # Granularity settings
    auto_granularity: bool = True
    min_data_points: int = 10
    max_data_points: int = 1000

    # Feature analysis
    min_feature_uses: int = 5
    percentile_thresholds: list[float] = None

    # Journey analysis
    max_journey_steps: int = 50
    journey_timeout_minutes: int = 120
    common_path_threshold: float = 0.1  # 10% of users

    # Performance
    batch_size: int = 1000
    parallel_processing: bool = True
    cache_results: bool = True
    cache_ttl_minutes: int = 30

    def __post_init__(self):
        if self.percentile_thresholds is None:
            self.percentile_thresholds = [50.0, 75.0, 90.0, 95.0, 99.0]


class UsageMetricsAggregator:
    """
    Advanced metrics aggregation engine with real-time capabilities.
    """

    def __init__(self, config: AggregationConfig | None = None):
        self.config = config or AggregationConfig()

        # Event storage (in production, this would be a database)
        self._events: list[TelemetryEvent] = []
        self._event_index: dict[str, int] = {}

        # Caching
        self._metric_cache: dict[str, tuple[datetime, Any]] = {}
        self._feature_cache: dict[str, tuple[datetime, FeatureUsage]] = {}

        # Real-time aggregation state
        self._real_time_counters: dict[str, dict[str, int]] = defaultdict(
            lambda: defaultdict(int)
        )
        self._real_time_timers: dict[str, list[float]] = defaultdict(list)

        # Journey tracking
        self._active_journeys: dict[str, list[TelemetryEvent]] = {}
        self._completed_journeys: list[UserJourney] = []

        logger.info(f"UsageMetricsAggregator initialized with config: {self.config}")

    async def add_events(self, events: list[TelemetryEvent]):
        """Add events for processing and aggregation."""
        self._ingest_events(events)

    def add_events_sync(self, events: list[TelemetryEvent]) -> None:
        """Synchronous variant for test harnesses."""
        self._ingest_events(events)

    def _ingest_events(self, events: list[TelemetryEvent]) -> None:
        for event in events:
            self._events.append(event)
            self._event_index[event.id] = len(self._events) - 1

            # Update real-time counters
            self._update_real_time_metrics(event)

            # Track user journeys
            self._update_journey_tracking(event)

        logger.debug(f"Added {len(events)} events for aggregation")

    def seed_events(self, events: list[TelemetryEvent]):
        """Load historical events into internal structures without async context."""
        if not events:
            return
        for event in events:
            self._events.append(event)
            self._event_index[event.id] = len(self._events) - 1
            self._update_real_time_metrics(event)
            self._update_journey_tracking(event)
        logger.info("Seeded %s telemetry events from persistent storage", len(events))

    async def calculate_usage_metrics(
        self,
        window: AggregationWindow | None = None,
        services: list[ServiceType] | None = None,
        features: list[str] | None = None,
    ) -> list[UsageMetric]:
        """Calculate comprehensive usage metrics for the specified window."""
        if window is None:
            end_time = datetime.utcnow()
            start_time = end_time - timedelta(hours=self.config.default_window_hours)
            window = AggregationWindow(start_time, end_time, "hour")

        # Check cache first
        cache_key = self._get_cache_key("usage_metrics", window, services, features)
        cached_result = self._get_cached_result(cache_key)
        if cached_result:
            return cached_result

        # Filter events
        filtered_events = self._filter_events(
            window=window, services=services, features=features
        )

        if not filtered_events:
            return []

        metrics = []

        # Basic usage counts
        metrics.extend(await self._calculate_usage_counts(filtered_events, window))

        # Feature adoption metrics
        metrics.extend(await self._calculate_adoption_metrics(filtered_events, window))

        # Performance metrics
        metrics.extend(
            await self._calculate_performance_metrics(filtered_events, window)
        )

        # Error rate metrics
        metrics.extend(await self._calculate_error_metrics(filtered_events, window))

        # Temporal pattern metrics
        metrics.extend(await self._calculate_temporal_metrics(filtered_events, window))

        # Cache results
        self._cache_result(cache_key, metrics)

        logger.info(
            f"Calculated {len(metrics)} usage metrics for window {window.start} - {window.end}"
        )
        return metrics

    async def analyze_feature_usage(
        self,
        feature_name: str | None = None,
        service: ServiceType | None = None,
        window: AggregationWindow | None = None,
    ) -> list[FeatureUsage]:
        """Analyze detailed feature usage patterns."""
        if window is None:
            if self._events:
                start_time = min(e.timestamp for e in self._events)
                end_time = max(e.timestamp for e in self._events)
            else:
                end_time = datetime.utcnow()
                start_time = end_time - timedelta(
                    hours=self.config.default_window_hours
                )
            window = AggregationWindow(start_time, end_time, "day")

        # Filter events for feature analysis
        filtered_events = self._filter_events(
            window=window,
            services=[service] if service else None,
            features=[feature_name] if feature_name else None,
        )

        # Group by feature and service
        feature_groups = defaultdict(list)
        for event in filtered_events:
            if event.feature_name:
                key = (event.feature_name, event.service)
                feature_groups[key].append(event)

        feature_analyses = []

        for (fname, fservice), events in feature_groups.items():
            if len(events) < self.config.min_feature_uses:
                continue

            analysis = await self._analyze_feature_events(
                fname, fservice, events, window
            )
            feature_analyses.append(analysis)

        # Sort by usage count
        feature_analyses.sort(key=lambda x: x.total_uses, reverse=True)

        logger.info(f"Analyzed {len(feature_analyses)} features")
        return feature_analyses

    async def extract_user_journeys(
        self,
        user_hash: str | None = None,
        window: AggregationWindow | None = None,
        min_steps: int = 2,
    ) -> list[UserJourney]:
        """Extract and analyze user journeys from events."""
        if window is None:
            if self._events:
                start_time = min(e.timestamp for e in self._events)
                end_time = max(e.timestamp for e in self._events)
            else:
                end_time = datetime.utcnow()
                start_time = end_time - timedelta(hours=24)
            window = AggregationWindow(start_time, end_time, "hour")

        # Get session-grouped events
        session_events = self._group_events_by_session(
            self._filter_events(window=window), user_hash=user_hash
        )

        journeys = []

        for session_id, events in session_events.items():
            if len(events) < min_steps:
                continue

            # Sort by timestamp
            events.sort(key=lambda e: e.timestamp)

            journey = self._build_user_journey(session_id, events)
            if journey:
                journeys.append(journey)

        # Analyze journey patterns
        journeys = self._analyze_journey_patterns(journeys)

        logger.info(f"Extracted {len(journeys)} user journeys")
        return journeys

    async def get_real_time_metrics(self) -> dict[str, Any]:
        """Get real-time metrics from current aggregation state."""
        now = datetime.utcnow()
        window_start = now - timedelta(minutes=self.config.real_time_window_minutes)

        # Get recent events
        recent_events = [e for e in self._events if e.timestamp >= window_start]

        metrics = {
            "timestamp": now.isoformat(),
            "window_minutes": self.config.real_time_window_minutes,
            "total_events": len(recent_events),
            "events_per_minute": len(recent_events)
            / self.config.real_time_window_minutes,
            "services": {},
            "features": {},
            "errors": {},
        }

        # Service breakdown
        service_counts = Counter(e.service for e in recent_events)
        for service, count in service_counts.items():
            metrics["services"][service.value] = {
                "event_count": count,
                "events_per_minute": count / self.config.real_time_window_minutes,
            }

        # Feature usage
        feature_counts = Counter(
            e.feature_name for e in recent_events if e.feature_name
        )
        for feature, count in feature_counts.most_common(10):
            metrics["features"][feature] = count

        # Error analysis
        error_events = [e for e in recent_events if not e.success]
        if error_events:
            error_rate = len(error_events) / len(recent_events)
            metrics["errors"] = {
                "total_errors": len(error_events),
                "error_rate": error_rate,
                "error_types": Counter(
                    e.error_message for e in error_events if e.error_message
                ),
            }

        return metrics

    def get_aggregator_stats(self) -> dict[str, Any]:
        """Get aggregator statistics and health info."""
        return {
            "total_events": len(self._events),
            "active_journeys": len(self._active_journeys),
            "completed_journeys": len(self._completed_journeys),
            "cache_size": len(self._metric_cache),
            "real_time_counters": len(self._real_time_counters),
            "config": {
                "default_window_hours": self.config.default_window_hours,
                "batch_size": self.config.batch_size,
                "cache_ttl_minutes": self.config.cache_ttl_minutes,
                "parallel_processing": self.config.parallel_processing,
            },
        }

    # Private helper methods

    async def _calculate_usage_counts(
        self, events: list[TelemetryEvent], window: AggregationWindow
    ) -> list[UsageMetric]:
        """Calculate basic usage count metrics."""
        metrics = []

        # Total events
        metrics.append(
            UsageMetric(
                id=f"usage_count_{window.granularity}_{int(window.start.timestamp())}",
                metric_type=MetricType.USAGE_COUNT,
                name="Total Events",
                value=float(len(events)),
                unit="events",
                period_start=window.start,
                period_end=window.end,
                granularity=window.granularity,
                sample_size=len(events),
                privacy_level=PrivacyLevel.AGGREGATE_ONLY,
            )
        )

        # Events by service
        service_counts = Counter(e.service for e in events)
        for service, count in service_counts.items():
            metrics.append(
                UsageMetric(
                    id=f"service_usage_{service.value}_{int(window.start.timestamp())}",
                    metric_type=MetricType.USAGE_COUNT,
                    name=f"{service.value} Usage",
                    value=float(count),
                    unit="events",
                    period_start=window.start,
                    period_end=window.end,
                    granularity=window.granularity,
                    dimensions={"service": service.value},
                    sample_size=count,
                    privacy_level=PrivacyLevel.AGGREGATE_ONLY,
                )
            )

        # Unique users
        unique_users = len({e.user_id for e in events if e.user_id})
        if unique_users > 0:
            metrics.append(
                UsageMetric(
                    id=f"unique_users_{int(window.start.timestamp())}",
                    metric_type=MetricType.USAGE_COUNT,
                    name="Unique Users",
                    value=float(unique_users),
                    unit="users",
                    period_start=window.start,
                    period_end=window.end,
                    granularity=window.granularity,
                    sample_size=unique_users,
                    privacy_level=PrivacyLevel.AGGREGATE_ONLY,
                )
            )

        return metrics

    async def _calculate_adoption_metrics(
        self, events: list[TelemetryEvent], window: AggregationWindow
    ) -> list[UsageMetric]:
        """Calculate feature adoption metrics."""
        metrics = []

        # Total unique users
        total_users = len({e.user_id for e in events if e.user_id})
        if total_users == 0:
            return metrics

        # Feature adoption rates
        feature_users = defaultdict(set)
        for event in events:
            if event.feature_name and event.user_id:
                feature_users[event.feature_name].add(event.user_id)

        for feature, users in feature_users.items():
            adoption_rate = len(users) / total_users
            metrics.append(
                UsageMetric(
                    id=f"adoption_{feature}_{int(window.start.timestamp())}",
                    metric_type=MetricType.ADOPTION_RATE,
                    name=f"{feature} Adoption Rate",
                    value=adoption_rate,
                    unit="percentage",
                    period_start=window.start,
                    period_end=window.end,
                    granularity=window.granularity,
                    dimensions={"feature": feature},
                    sample_size=len(users),
                    privacy_level=PrivacyLevel.AGGREGATE_ONLY,
                )
            )

        return metrics

    async def _calculate_performance_metrics(
        self, events: list[TelemetryEvent], window: AggregationWindow
    ) -> list[UsageMetric]:
        """Calculate performance-related metrics."""
        metrics = []

        # Events with duration data
        duration_events = [
            e for e in events if e.duration_ms is not None and e.duration_ms > 0
        ]

        if not duration_events:
            return metrics

        durations = [e.duration_ms for e in duration_events]

        # Overall performance metrics
        metrics.append(
            UsageMetric(
                id=f"avg_response_time_{int(window.start.timestamp())}",
                metric_type=MetricType.PERFORMANCE_METRICS,
                name="Average Response Time",
                value=statistics.mean(durations),
                unit="milliseconds",
                period_start=window.start,
                period_end=window.end,
                granularity=window.granularity,
                sample_size=len(durations),
                privacy_level=PrivacyLevel.AGGREGATE_ONLY,
            )
        )

        metrics.append(
            UsageMetric(
                id=f"median_response_time_{int(window.start.timestamp())}",
                metric_type=MetricType.PERFORMANCE_METRICS,
                name="Median Response Time",
                value=statistics.median(durations),
                unit="milliseconds",
                period_start=window.start,
                period_end=window.end,
                granularity=window.granularity,
                sample_size=len(durations),
                privacy_level=PrivacyLevel.AGGREGATE_ONLY,
            )
        )

        # Percentile metrics
        for percentile in self.config.percentile_thresholds:
            value = self._calculate_percentile(durations, percentile)
            metrics.append(
                UsageMetric(
                    id=f"p{int(percentile)}_response_time_{int(window.start.timestamp())}",
                    metric_type=MetricType.PERFORMANCE_METRICS,
                    name=f"P{int(percentile)} Response Time",
                    value=value,
                    unit="milliseconds",
                    period_start=window.start,
                    period_end=window.end,
                    granularity=window.granularity,
                    dimensions={"percentile": str(int(percentile))},
                    sample_size=len(durations),
                    privacy_level=PrivacyLevel.AGGREGATE_ONLY,
                )
            )

        return metrics

    async def _calculate_error_metrics(
        self, events: list[TelemetryEvent], window: AggregationWindow
    ) -> list[UsageMetric]:
        """Calculate error rate metrics."""
        metrics = []

        total_events = len(events)
        if total_events == 0:
            return metrics

        error_events = [e for e in events if not e.success]
        error_rate = len(error_events) / total_events

        metrics.append(
            UsageMetric(
                id=f"error_rate_{int(window.start.timestamp())}",
                metric_type=MetricType.ERROR_RATE,
                name="Overall Error Rate",
                value=error_rate,
                unit="percentage",
                period_start=window.start,
                period_end=window.end,
                granularity=window.granularity,
                sample_size=total_events,
                privacy_level=PrivacyLevel.AGGREGATE_ONLY,
            )
        )

        # Error rates by service
        service_events = defaultdict(list)
        for event in events:
            service_events[event.service].append(event)

        for service, service_event_list in service_events.items():
            service_errors = [e for e in service_event_list if not e.success]
            service_error_rate = len(service_errors) / len(service_event_list)

            metrics.append(
                UsageMetric(
                    id=f"error_rate_{service.value}_{int(window.start.timestamp())}",
                    metric_type=MetricType.ERROR_RATE,
                    name=f"{service.value} Error Rate",
                    value=service_error_rate,
                    unit="percentage",
                    period_start=window.start,
                    period_end=window.end,
                    granularity=window.granularity,
                    dimensions={"service": service.value},
                    sample_size=len(service_event_list),
                    privacy_level=PrivacyLevel.AGGREGATE_ONLY,
                )
            )

        return metrics

    async def _calculate_temporal_metrics(
        self, events: list[TelemetryEvent], window: AggregationWindow
    ) -> list[UsageMetric]:
        """Calculate temporal pattern metrics."""
        metrics = []

        if not events:
            return metrics

        # Events by hour of day
        hourly_counts = defaultdict(int)
        for event in events:
            hour = event.timestamp.hour
            hourly_counts[hour] += 1

        # Find peak usage hour
        peak_hour = max(hourly_counts.keys(), key=lambda h: hourly_counts[h])
        peak_count = hourly_counts[peak_hour]

        metrics.append(
            UsageMetric(
                id=f"peak_usage_hour_{int(window.start.timestamp())}",
                metric_type=MetricType.TEMPORAL_PATTERNS,
                name="Peak Usage Hour",
                value=float(peak_hour),
                unit="hour",
                period_start=window.start,
                period_end=window.end,
                granularity=window.granularity,
                breakdown={str(hour): count for hour, count in hourly_counts.items()},
                sample_size=len(events),
                privacy_level=PrivacyLevel.AGGREGATE_ONLY,
            )
        )

        metrics.append(
            UsageMetric(
                id=f"peak_usage_count_{int(window.start.timestamp())}",
                metric_type=MetricType.TEMPORAL_PATTERNS,
                name="Peak Hour Event Count",
                value=float(peak_count),
                unit="events",
                period_start=window.start,
                period_end=window.end,
                granularity=window.granularity,
                dimensions={"peak_hour": str(peak_hour)},
                sample_size=peak_count,
                privacy_level=PrivacyLevel.AGGREGATE_ONLY,
            )
        )

        return metrics

    async def _analyze_feature_events(
        self,
        feature_name: str,
        service: ServiceType,
        events: list[TelemetryEvent],
        window: AggregationWindow,
    ) -> FeatureUsage:
        """Analyze events for a specific feature."""
        total_uses = len(events)
        unique_users = len({e.user_id for e in events if e.user_id})
        successful_events = [e for e in events if e.success]
        success_rate = len(successful_events) / total_uses if total_uses > 0 else 0

        # Duration analysis
        durations = [e.duration_ms for e in events if e.duration_ms is not None]
        avg_duration = statistics.mean(durations) if durations else None

        # User frequency analysis
        user_counts = Counter(e.user_id for e in events if e.user_id)
        frequency = statistics.mean(user_counts.values()) if user_counts else 0

        # Trend analysis (simplified)
        mid_point = window.start + (window.end - window.start) / 2
        first_half = [e for e in events if e.timestamp < mid_point]
        second_half = [e for e in events if e.timestamp >= mid_point]

        first_half_rate = (
            len(first_half) / (len(first_half) + len(second_half)) if events else 0
        )
        second_half_rate = (
            len(second_half) / (len(first_half) + len(second_half)) if events else 0
        )

        trend = "stable"
        period_change = 0.0
        if first_half_rate > 0:
            period_change = (second_half_rate - first_half_rate) / first_half_rate * 100
            if period_change > 10:
                trend = "increasing"
            elif period_change < -10:
                trend = "decreasing"

        # Error rate
        error_events = [e for e in events if not e.success]
        error_rate = len(error_events) / total_uses if total_uses > 0 else 0

        # Response time analysis
        response_times = [
            e.duration_ms for e in successful_events if e.duration_ms is not None
        ]
        avg_response_time = statistics.mean(response_times) if response_times else None

        # Peak usage analysis
        hourly_usage = defaultdict(int)
        for event in events:
            hourly_usage[event.timestamp.hour] += 1

        peak_hour = (
            max(hourly_usage.keys(), key=lambda h: hourly_usage[h])
            if hourly_usage
            else None
        )

        return FeatureUsage(
            feature_name=feature_name,
            service=service,
            total_uses=total_uses,
            unique_users=unique_users,
            success_rate=success_rate,
            avg_duration_ms=avg_duration,
            adoption_rate=0.0,  # Would need total user base to calculate
            retention_rate=0.0,  # Would need historical data to calculate
            frequency=frequency,
            trend=trend,
            period_over_period_change=period_change,
            peak_usage_hour=peak_hour,
            error_rate=error_rate,
            avg_response_time_ms=avg_response_time,
            period_start=window.start,
            period_end=window.end,
        )

    def _filter_events(
        self,
        window: AggregationWindow | None = None,
        services: list[ServiceType] | None = None,
        features: list[str] | None = None,
        event_types: list[EventType] | None = None,
    ) -> list[TelemetryEvent]:
        """Filter events based on various criteria."""
        filtered = self._events

        if window:
            filtered = [
                e for e in filtered if window.start <= e.timestamp <= window.end
            ]

        if services:
            filtered = [e for e in filtered if e.service in services]

        if features:
            filtered = [
                e for e in filtered if e.feature_name and e.feature_name in features
            ]

        if event_types:
            filtered = [e for e in filtered if e.event_type in event_types]

        return filtered

    def _group_events_by_session(
        self, events: list[TelemetryEvent], user_hash: str | None = None
    ) -> dict[str, list[TelemetryEvent]]:
        """Group events by session ID."""
        session_groups = defaultdict(list)

        for event in events:
            if event.session_id:
                if user_hash is None or (event.user_id and event.user_id == user_hash):
                    session_groups[event.session_id].append(event)

        return dict(session_groups)

    def _build_user_journey(
        self, session_id: str, events: list[TelemetryEvent]
    ) -> UserJourney | None:
        """Build a user journey from session events."""
        if len(events) < 2:
            return None

        # Sort events by timestamp
        events.sort(key=lambda e: e.timestamp)

        # Build journey steps
        steps = []
        for i, event in enumerate(events):
            step = {
                "step_number": i + 1,
                "timestamp": event.timestamp.isoformat(),
                "event_type": event.event_type.value,
                "feature_name": event.feature_name,
                "action": event.action,
                "success": event.success,
                "duration_ms": event.duration_ms,
            }
            steps.append(step)

        # Determine success and conversion
        successful = all(e.success for e in events)
        conversion_event = None

        # Look for conversion events (simplified logic)
        for event in reversed(events):
            if event.event_type in [
                EventType.ANALYSIS_COMPLETE,
                EventType.EXPORT_REQUEST,
            ]:
                conversion_event = event.event_type.value
                break

        # Calculate completion rate
        successful_steps = len([e for e in events if e.success])
        completion_rate = successful_steps / len(events)

        # Find drop-off point
        drop_off_step = None
        for i, event in enumerate(events):
            if not event.success:
                drop_off_step = i + 1
                break

        user_hash = (
            events[0].user_id
            if events and events[0].user_id
            else f"session_{session_id}"
        )

        return UserJourney(
            journey_id=f"journey_{session_id}_{int(events[0].timestamp.timestamp())}",
            user_hash=user_hash,
            start_time=events[0].timestamp,
            end_time=events[-1].timestamp,
            total_duration_minutes=(
                events[-1].timestamp - events[0].timestamp
            ).total_seconds()
            / 60,
            steps=steps,
            completed_steps=successful_steps,
            total_steps=len(events),
            completion_rate=completion_rate,
            successful=successful,
            conversion_event=conversion_event,
            drop_off_step=drop_off_step,
            common_path=False,  # Would need pattern analysis to determine
            anomaly_score=None,  # Would need ML model to calculate
        )

    def _analyze_journey_patterns(
        self, journeys: list[UserJourney]
    ) -> list[UserJourney]:
        """Analyze patterns in user journeys to identify common paths."""
        if len(journeys) < 10:  # Not enough data for pattern analysis
            return journeys

        # Create path signatures for pattern matching
        path_signatures = defaultdict(list)

        for journey in journeys:
            # Create a signature based on the sequence of features/actions
            signature = []
            for step in journey.steps:
                if step.get("feature_name") and step.get("action"):
                    signature.append(f"{step['feature_name']}:{step['action']}")

            path_key = "->".join(signature)
            path_signatures[path_key].append(journey)

        # Identify common paths
        total_journeys = len(journeys)
        common_threshold = max(
            2, int(total_journeys * self.config.common_path_threshold)
        )

        for path_key, path_journeys in path_signatures.items():
            if len(path_journeys) >= common_threshold:
                for journey in path_journeys:
                    journey.common_path = True

        return journeys

    def _update_real_time_metrics(self, event: TelemetryEvent):
        """Update real-time metric counters."""
        datetime.utcnow()

        # Service counters
        service_key = f"service_{event.service.value}"
        self._real_time_counters["services"][service_key] += 1

        # Feature counters
        if event.feature_name:
            feature_key = f"feature_{event.feature_name}"
            self._real_time_counters["features"][feature_key] += 1

        # Error counters
        if not event.success:
            self._real_time_counters["errors"]["total"] += 1

        # Performance tracking
        if event.duration_ms is not None:
            self._real_time_timers["response_times"].append(event.duration_ms)

            # Keep only recent measurements
            if len(self._real_time_timers["response_times"]) > 1000:
                self._real_time_timers["response_times"] = self._real_time_timers[
                    "response_times"
                ][-500:]

    def _update_journey_tracking(self, event: TelemetryEvent):
        """Update journey tracking with new event."""
        if not event.session_id:
            return

        # Add to active journey
        if event.session_id not in self._active_journeys:
            self._active_journeys[event.session_id] = []

        self._active_journeys[event.session_id].append(event)

        # Check for journey completion or timeout
        session_events = self._active_journeys[event.session_id]

        # Journey completion conditions (simplified)
        if (
            len(session_events) > self.config.max_journey_steps
            or event.event_type == EventType.SESSION_END
            or (
                session_events
                and (event.timestamp - session_events[0].timestamp).total_seconds()
                > self.config.journey_timeout_minutes * 60
            )
        ):

            # Complete the journey
            journey = self._build_user_journey(event.session_id, session_events)
            if journey:
                self._completed_journeys.append(journey)

            # Clean up active journey
            del self._active_journeys[event.session_id]

    def _calculate_percentile(self, values: list[float], percentile: float) -> float:
        """Calculate percentile value."""
        if not values:
            return 0.0

        sorted_values = sorted(values)
        n = len(sorted_values)
        if n == 1:
            return sorted_values[0]

        # Use a hybrid percentile strategy:
        # - middle percentiles use "exclusive" interpolation (n + 1)
        # - extreme tails use "inclusive" interpolation (n - 1)
        pct = max(0.0, min(100.0, percentile))
        if pct <= 10.0 or pct >= 90.0:
            index = (pct / 100) * (n - 1)
        else:
            index = (pct / 100) * (n + 1) - 1

        # Clamp index to valid range
        if index <= 0:
            return sorted_values[0]
        if index >= n - 1:
            return sorted_values[-1]

        lower_idx = int(index)
        upper_idx = lower_idx + 1
        lower = sorted_values[lower_idx]
        upper = sorted_values[upper_idx]
        result = lower + (upper - lower) * (index - lower_idx)
        return round(result, 10)

    def _get_cache_key(self, operation: str, *args) -> str:
        """Generate cache key for results."""
        key_parts = [operation]
        for arg in args:
            if hasattr(arg, "__dict__"):
                key_parts.append(str(hash(frozenset(arg.__dict__.items()))))
            else:
                key_parts.append(str(hash(str(arg))))
        return "_".join(key_parts)

    def _get_cached_result(self, cache_key: str) -> Any | None:
        """Get cached result if still valid."""
        if not self.config.cache_results:
            return None

        if cache_key in self._metric_cache:
            timestamp, result = self._metric_cache[cache_key]
            if (
                datetime.utcnow() - timestamp
            ).total_seconds() < self.config.cache_ttl_minutes * 60:
                return result
            else:
                del self._metric_cache[cache_key]

        return None

    def _cache_result(self, cache_key: str, result: Any):
        """Cache result with timestamp."""
        if self.config.cache_results:
            self._metric_cache[cache_key] = (datetime.utcnow(), result)
