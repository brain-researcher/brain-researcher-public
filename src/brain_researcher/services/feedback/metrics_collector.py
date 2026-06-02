"""Metrics collection for A/B testing and RL feedback."""

import json
import logging
import time
from collections import defaultdict
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import redis

logger = logging.getLogger(__name__)


class EventType(Enum):
    IMPRESSION = "impression"
    CLICK = "click"
    CONVERSION = "conversion"
    ERROR = "error"
    CUSTOM = "custom"


@dataclass
class Event:
    user_id: str
    event_type: EventType
    experiment_id: Optional[str]
    variant: Optional[str]
    timestamp: datetime
    metadata: Dict[str, Any]
    value: Optional[float] = None
    session_id: Optional[str] = None


@dataclass
class MetricDefinition:
    name: str
    description: str
    event_types: List[EventType]
    aggregation: str  # sum, count, avg, conversion_rate, etc.
    conditions: Dict[str, Any]
    time_window_hours: int = 24


@dataclass
class ExperimentMetrics:
    experiment_id: str
    variant: str
    metrics: Dict[str, float]
    sample_size: int
    time_range: Tuple[datetime, datetime]
    last_updated: datetime


class MetricsAggregator:
    """Aggregates raw events into metrics."""

    @staticmethod
    def calculate_conversion_rate(events: List[Event]) -> float:
        """Calculate conversion rate from events."""
        impressions = sum(1 for e in events if e.event_type == EventType.IMPRESSION)
        conversions = sum(1 for e in events if e.event_type == EventType.CONVERSION)

        if impressions == 0:
            return 0.0

        return conversions / impressions

    @staticmethod
    def calculate_click_through_rate(events: List[Event]) -> float:
        """Calculate click-through rate."""
        impressions = sum(1 for e in events if e.event_type == EventType.IMPRESSION)
        clicks = sum(1 for e in events if e.event_type == EventType.CLICK)

        if impressions == 0:
            return 0.0

        return clicks / impressions

    @staticmethod
    def calculate_average_value(events: List[Event]) -> float:
        """Calculate average event value."""
        values = [e.value for e in events if e.value is not None]
        return np.mean(values) if values else 0.0

    @staticmethod
    def calculate_total_value(events: List[Event]) -> float:
        """Calculate total event value."""
        return sum(e.value for e in events if e.value is not None)

    @staticmethod
    def calculate_error_rate(events: List[Event]) -> float:
        """Calculate error rate."""
        total_events = len(events)
        error_events = sum(1 for e in events if e.event_type == EventType.ERROR)

        if total_events == 0:
            return 0.0

        return error_events / total_events

    @staticmethod
    def calculate_user_engagement(events: List[Event]) -> Dict[str, float]:
        """Calculate user engagement metrics."""
        if not events:
            return {"sessions": 0, "avg_session_length": 0, "events_per_session": 0}

        # Group by session
        sessions = defaultdict(list)
        for event in events:
            session_key = f"{event.user_id}:{event.session_id or 'default'}"
            sessions[session_key].append(event)

        session_lengths = []
        events_per_session = []

        for session_events in sessions.values():
            if len(session_events) < 2:
                continue

            session_events.sort(key=lambda e: e.timestamp)
            start_time = session_events[0].timestamp
            end_time = session_events[-1].timestamp

            session_length = (end_time - start_time).total_seconds() / 60  # minutes
            session_lengths.append(session_length)
            events_per_session.append(len(session_events))

        return {
            "sessions": len(sessions),
            "avg_session_length": np.mean(session_lengths) if session_lengths else 0,
            "events_per_session": (
                np.mean(events_per_session) if events_per_session else 0
            ),
        }


class MetricsCollector:
    """Main metrics collection system."""

    def __init__(self, redis_client: Optional[redis.Redis] = None):
        self.redis_client = redis_client or redis.Redis(decode_responses=True)
        self.metric_definitions: Dict[str, MetricDefinition] = {}
        self.aggregator = MetricsAggregator()

        # Initialize default metrics
        self._setup_default_metrics()

    def track_event(
        self,
        user_id: str,
        event_type: str,
        experiment_id: Optional[str] = None,
        variant: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        value: Optional[float] = None,
        session_id: Optional[str] = None,
    ) -> None:
        """Track a user event."""
        try:
            event_type_enum = EventType(event_type.lower())
        except ValueError:
            event_type_enum = EventType.CUSTOM

        event = Event(
            user_id=user_id,
            event_type=event_type_enum,
            experiment_id=experiment_id,
            variant=variant,
            timestamp=datetime.utcnow(),
            metadata=metadata or {},
            value=value,
            session_id=session_id,
        )

        self._store_event(event)
        self._update_real_time_metrics(event)

        logger.debug(f"Tracked event: {event_type} for user {user_id}")

    def track_experiment_event(
        self,
        user_id: str,
        experiment_id: str,
        variant: str,
        event_type: str,
        metadata: Optional[Dict[str, Any]] = None,
        value: Optional[float] = None,
    ) -> None:
        """Track an event for a specific experiment."""
        self.track_event(
            user_id=user_id,
            event_type=event_type,
            experiment_id=experiment_id,
            variant=variant,
            metadata=metadata,
            value=value,
        )

        # Also update experiment-specific counters
        self._update_experiment_counters(experiment_id, variant, event_type, value)

    def get_experiment_metrics(
        self,
        experiment_id: str,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
    ) -> Dict[str, ExperimentMetrics]:
        """Get metrics for all variants of an experiment."""
        end_time = end_time or datetime.utcnow()
        start_time = start_time or (end_time - timedelta(days=7))

        # Get all variants for this experiment
        variants = self._get_experiment_variants(experiment_id)

        metrics = {}
        for variant in variants:
            variant_metrics = self._calculate_variant_metrics(
                experiment_id, variant, start_time, end_time
            )
            metrics[variant] = variant_metrics

        return metrics

    def get_real_time_metrics(
        self, experiment_id: str, time_window_minutes: int = 60
    ) -> Dict[str, Dict[str, float]]:
        """Get real-time metrics for an experiment."""
        cutoff_time = datetime.utcnow() - timedelta(minutes=time_window_minutes)

        metrics = {}
        variants = self._get_experiment_variants(experiment_id)

        for variant in variants:
            variant_metrics = {}

            # Get recent events for this variant
            events = self._get_events(
                experiment_id=experiment_id, variant=variant, start_time=cutoff_time
            )

            # Calculate metrics
            variant_metrics["impressions"] = sum(
                1 for e in events if e.event_type == EventType.IMPRESSION
            )
            variant_metrics["clicks"] = sum(
                1 for e in events if e.event_type == EventType.CLICK
            )
            variant_metrics["conversions"] = sum(
                1 for e in events if e.event_type == EventType.CONVERSION
            )
            variant_metrics["errors"] = sum(
                1 for e in events if e.event_type == EventType.ERROR
            )

            # Rates
            if variant_metrics["impressions"] > 0:
                variant_metrics["ctr"] = (
                    variant_metrics["clicks"] / variant_metrics["impressions"]
                )
                variant_metrics["conversion_rate"] = (
                    variant_metrics["conversions"] / variant_metrics["impressions"]
                )
                variant_metrics["error_rate"] = (
                    variant_metrics["errors"] / variant_metrics["impressions"]
                )
            else:
                variant_metrics["ctr"] = 0.0
                variant_metrics["conversion_rate"] = 0.0
                variant_metrics["error_rate"] = 0.0

            # Revenue/value metrics
            variant_metrics["total_revenue"] = sum(
                e.value for e in events if e.value is not None
            )
            variant_metrics["avg_order_value"] = variant_metrics["total_revenue"] / max(
                variant_metrics["conversions"], 1
            )

            metrics[variant] = variant_metrics

        return metrics

    def create_custom_metric(
        self,
        name: str,
        description: str,
        event_types: List[str],
        aggregation: str,
        conditions: Optional[Dict[str, Any]] = None,
        time_window_hours: int = 24,
    ) -> None:
        """Create a custom metric definition."""
        try:
            event_type_enums = [EventType(et.lower()) for et in event_types]
        except ValueError as e:
            raise ValueError(f"Invalid event type: {e}")

        if aggregation not in [
            "sum",
            "count",
            "avg",
            "conversion_rate",
            "click_through_rate",
        ]:
            raise ValueError(f"Invalid aggregation: {aggregation}")

        metric_def = MetricDefinition(
            name=name,
            description=description,
            event_types=event_type_enums,
            aggregation=aggregation,
            conditions=conditions or {},
            time_window_hours=time_window_hours,
        )

        self.metric_definitions[name] = metric_def
        self._save_metric_definition(metric_def)

        logger.info(f"Created custom metric: {name}")

    def get_custom_metric_value(
        self,
        metric_name: str,
        experiment_id: str,
        variant: str,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
    ) -> float:
        """Get value for a custom metric."""
        if metric_name not in self.metric_definitions:
            raise ValueError(f"Metric {metric_name} not defined")

        metric_def = self.metric_definitions[metric_name]

        end_time = end_time or datetime.utcnow()
        start_time = start_time or (
            end_time - timedelta(hours=metric_def.time_window_hours)
        )

        # Get relevant events
        events = self._get_events(
            experiment_id=experiment_id,
            variant=variant,
            start_time=start_time,
            end_time=end_time,
            event_types=metric_def.event_types,
            conditions=metric_def.conditions,
        )

        # Apply aggregation
        if metric_def.aggregation == "count":
            return float(len(events))
        elif metric_def.aggregation == "sum":
            return sum(e.value for e in events if e.value is not None)
        elif metric_def.aggregation == "avg":
            values = [e.value for e in events if e.value is not None]
            return np.mean(values) if values else 0.0
        elif metric_def.aggregation == "conversion_rate":
            return self.aggregator.calculate_conversion_rate(events)
        elif metric_def.aggregation == "click_through_rate":
            return self.aggregator.calculate_click_through_rate(events)
        else:
            return 0.0

    def get_metrics_dashboard_data(self, experiment_id: str) -> Dict:
        """Get comprehensive dashboard data for an experiment."""
        current_time = datetime.utcnow()

        # Real-time metrics (last hour)
        real_time = self.get_real_time_metrics(experiment_id, time_window_minutes=60)

        # Daily metrics (last 7 days)
        daily_metrics = {}
        for days_back in range(7):
            day_start = current_time.replace(
                hour=0, minute=0, second=0, microsecond=0
            ) - timedelta(days=days_back)
            day_end = day_start + timedelta(days=1)

            day_key = day_start.strftime("%Y-%m-%d")
            daily_metrics[day_key] = {}

            variants = self._get_experiment_variants(experiment_id)
            for variant in variants:
                events = self._get_events(
                    experiment_id=experiment_id,
                    variant=variant,
                    start_time=day_start,
                    end_time=day_end,
                )

                daily_metrics[day_key][variant] = {
                    "impressions": sum(
                        1 for e in events if e.event_type == EventType.IMPRESSION
                    ),
                    "conversions": sum(
                        1 for e in events if e.event_type == EventType.CONVERSION
                    ),
                    "revenue": sum(e.value for e in events if e.value is not None),
                }

        return {
            "real_time": real_time,
            "daily": daily_metrics,
            "last_updated": current_time.isoformat(),
        }

    # Private Methods

    def _setup_default_metrics(self) -> None:
        """Setup default metric definitions."""
        default_metrics = [
            {
                "name": "conversion_rate",
                "description": "Percentage of impressions that convert",
                "event_types": ["impression", "conversion"],
                "aggregation": "conversion_rate",
            },
            {
                "name": "click_through_rate",
                "description": "Percentage of impressions that get clicked",
                "event_types": ["impression", "click"],
                "aggregation": "click_through_rate",
            },
            {
                "name": "revenue_per_visitor",
                "description": "Average revenue per visitor",
                "event_types": ["conversion"],
                "aggregation": "avg",
            },
            {
                "name": "error_rate",
                "description": "Percentage of events that are errors",
                "event_types": ["impression", "error"],
                "aggregation": "conversion_rate",
            },
        ]

        for metric_config in default_metrics:
            if metric_config["name"] not in self.metric_definitions:
                self.create_custom_metric(**metric_config)

    def _store_event(self, event: Event) -> None:
        """Store event in Redis."""
        # Store in time-series format for efficient querying
        timestamp_key = int(event.timestamp.timestamp())

        # Main event storage
        event_key = f"events:{event.experiment_id}:{event.variant}:{timestamp_key}:{event.user_id}"
        event_data = asdict(event)
        event_data["timestamp"] = event.timestamp.isoformat()
        event_data["event_type"] = event.event_type.value

        self.redis_client.hset(
            event_key,
            mapping={
                k: json.dumps(v) if isinstance(v, dict) else str(v)
                for k, v in event_data.items()
            },
        )

        # Set expiration (30 days)
        self.redis_client.expire(event_key, 30 * 24 * 3600)

        # Add to sorted set for time-based queries
        if event.experiment_id and event.variant:
            timeline_key = f"timeline:{event.experiment_id}:{event.variant}"
            self.redis_client.zadd(timeline_key, {event_key: timestamp_key})
            self.redis_client.expire(timeline_key, 30 * 24 * 3600)

    def _update_real_time_metrics(self, event: Event) -> None:
        """Update real-time metrics counters."""
        if not event.experiment_id or not event.variant:
            return

        # Update hourly counters
        hour_key = event.timestamp.strftime("%Y%m%d%H")
        counter_key = f"metrics:{event.experiment_id}:{event.variant}:{hour_key}"

        self.redis_client.hincrby(counter_key, f"{event.event_type.value}_count", 1)

        if event.value is not None:
            self.redis_client.hincrbyfloat(
                counter_key, f"{event.event_type.value}_value", event.value
            )

        # Set expiration
        self.redis_client.expire(counter_key, 7 * 24 * 3600)

    def _update_experiment_counters(
        self, experiment_id: str, variant: str, event_type: str, value: Optional[float]
    ) -> None:
        """Update experiment-level counters for A/B testing framework."""
        counter_key = f"metrics:{experiment_id}:{variant}"

        # Update event type counters
        if event_type.lower() == "impression":
            self.redis_client.hincrby(counter_key, "impressions", 1)
        elif event_type.lower() == "conversion":
            self.redis_client.hincrby(counter_key, "conversions", 1)
        elif event_type.lower() == "click":
            self.redis_client.hincrby(counter_key, "clicks", 1)

        # Update value counters
        if value is not None:
            self.redis_client.hincrbyfloat(counter_key, "revenue", value)

    def _get_experiment_variants(self, experiment_id: str) -> List[str]:
        """Get all variants for an experiment."""
        pattern = f"timeline:{experiment_id}:*"
        variants = set()

        for key in self.redis_client.scan_iter(match=pattern):
            variant = key.split(":")[-1]
            variants.add(variant)

        return list(variants)

    def _get_events(
        self,
        experiment_id: str,
        variant: str,
        start_time: datetime,
        end_time: Optional[datetime] = None,
        event_types: Optional[List[EventType]] = None,
        conditions: Optional[Dict[str, Any]] = None,
    ) -> List[Event]:
        """Get events for a specific experiment variant and time range."""
        end_time = end_time or datetime.utcnow()

        start_timestamp = int(start_time.timestamp())
        end_timestamp = int(end_time.timestamp())

        timeline_key = f"timeline:{experiment_id}:{variant}"

        # Get event keys in time range
        event_keys = self.redis_client.zrangebyscore(
            timeline_key, start_timestamp, end_timestamp
        )

        events = []
        for event_key in event_keys:
            try:
                event_data = self.redis_client.hgetall(event_key)
                if not event_data:
                    continue

                # Parse event data
                event_data["timestamp"] = datetime.fromisoformat(
                    event_data["timestamp"]
                )
                event_data["event_type"] = EventType(event_data["event_type"])
                event_data["metadata"] = json.loads(event_data["metadata"])

                if event_data.get("value") and event_data["value"] != "None":
                    event_data["value"] = float(event_data["value"])
                else:
                    event_data["value"] = None

                event = Event(**event_data)

                # Apply filters
                if event_types and event.event_type not in event_types:
                    continue

                if conditions:
                    if not self._event_matches_conditions(event, conditions):
                        continue

                events.append(event)

            except Exception as e:
                logger.warning(f"Failed to parse event {event_key}: {e}")

        return events

    def _event_matches_conditions(
        self, event: Event, conditions: Dict[str, Any]
    ) -> bool:
        """Check if an event matches the given conditions."""
        for condition_key, condition_value in conditions.items():
            if condition_key == "metadata":
                for meta_key, meta_value in condition_value.items():
                    if event.metadata.get(meta_key) != meta_value:
                        return False
            elif condition_key == "user_id":
                if event.user_id != condition_value:
                    return False
            elif condition_key == "min_value":
                if not event.value or event.value < condition_value:
                    return False

        return True

    def _calculate_variant_metrics(
        self, experiment_id: str, variant: str, start_time: datetime, end_time: datetime
    ) -> ExperimentMetrics:
        """Calculate comprehensive metrics for a variant."""
        events = self._get_events(experiment_id, variant, start_time, end_time)

        # Basic metrics
        metrics = {
            "impressions": sum(
                1 for e in events if e.event_type == EventType.IMPRESSION
            ),
            "clicks": sum(1 for e in events if e.event_type == EventType.CLICK),
            "conversions": sum(
                1 for e in events if e.event_type == EventType.CONVERSION
            ),
            "errors": sum(1 for e in events if e.event_type == EventType.ERROR),
            "total_revenue": sum(e.value for e in events if e.value is not None),
        }

        # Calculated metrics
        if metrics["impressions"] > 0:
            metrics["conversion_rate"] = metrics["conversions"] / metrics["impressions"]
            metrics["click_through_rate"] = metrics["clicks"] / metrics["impressions"]
            metrics["error_rate"] = metrics["errors"] / metrics["impressions"]
        else:
            metrics["conversion_rate"] = 0.0
            metrics["click_through_rate"] = 0.0
            metrics["error_rate"] = 0.0

        if metrics["conversions"] > 0:
            metrics["average_order_value"] = (
                metrics["total_revenue"] / metrics["conversions"]
            )
        else:
            metrics["average_order_value"] = 0.0

        # User engagement metrics
        engagement = self.aggregator.calculate_user_engagement(events)
        metrics.update(engagement)

        # Unique users
        unique_users = len(set(e.user_id for e in events))
        metrics["unique_users"] = unique_users

        return ExperimentMetrics(
            experiment_id=experiment_id,
            variant=variant,
            metrics=metrics,
            sample_size=unique_users,
            time_range=(start_time, end_time),
            last_updated=datetime.utcnow(),
        )

    def _save_metric_definition(self, metric_def: MetricDefinition) -> None:
        """Save metric definition to Redis."""
        key = f"metric_def:{metric_def.name}"
        data = asdict(metric_def)
        data["event_types"] = [et.value for et in metric_def.event_types]

        self.redis_client.hset(
            key,
            mapping={
                k: json.dumps(v) if isinstance(v, (dict, list)) else str(v)
                for k, v in data.items()
            },
        )
