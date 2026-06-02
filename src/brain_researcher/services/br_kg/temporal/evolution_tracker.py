"""Graph evolution tracker - completes KG-030 Temporal Graph.

This module provides real-time tracking and analysis of graph evolution,
detecting patterns, trends, and significant changes over time.
"""

import asyncio
import json
import logging
import statistics
from collections import defaultdict, deque
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

logger = logging.getLogger(__name__)


class EvolutionEventType(Enum):
    """Types of evolution events."""

    NODE_BIRTH = "node_birth"
    NODE_DEATH = "node_death"
    NODE_PROPERTY_CHANGE = "node_property_change"
    NODE_LABEL_CHANGE = "node_label_change"

    EDGE_BIRTH = "edge_birth"
    EDGE_DEATH = "edge_death"
    EDGE_PROPERTY_CHANGE = "edge_property_change"

    PATTERN_EMERGENCE = "pattern_emergence"
    PATTERN_DISAPPEARANCE = "pattern_disappearance"

    CLUSTER_FORMATION = "cluster_formation"
    CLUSTER_DISSOLUTION = "cluster_dissolution"

    TOPOLOGY_CHANGE = "topology_change"
    COMMUNITY_CHANGE = "community_change"


class PatternType(Enum):
    """Types of evolution patterns."""

    GROWTH = "growth"  # Steady increase in nodes/edges
    DECLINE = "decline"  # Steady decrease in nodes/edges
    BURST = "burst"  # Sudden spike in activity
    OSCILLATION = "oscillation"  # Periodic changes
    PHASE_TRANSITION = "phase_transition"  # Structural reorganization
    CASCADE = "cascade"  # Sequential propagation of changes


@dataclass
class EvolutionEvent:
    """Represents a single evolution event."""

    event_id: str
    event_type: EvolutionEventType
    timestamp: datetime

    # Affected entities
    entity_id: Optional[str] = None
    entity_type: str = "unknown"  # node, edge, pattern

    # Change details
    old_value: Optional[Any] = None
    new_value: Optional[Any] = None
    change_magnitude: float = 0.0

    # Context
    related_entities: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "event_id": self.event_id,
            "event_type": self.event_type.value,
            "timestamp": self.timestamp.isoformat(),
            "entity_id": self.entity_id,
            "entity_type": self.entity_type,
            "old_value": self.old_value,
            "new_value": self.new_value,
            "change_magnitude": self.change_magnitude,
            "related_entities": self.related_entities,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "EvolutionEvent":
        """Create from dictionary."""
        return cls(
            event_id=data["event_id"],
            event_type=EvolutionEventType(data["event_type"]),
            timestamp=datetime.fromisoformat(data["timestamp"]),
            entity_id=data.get("entity_id"),
            entity_type=data.get("entity_type", "unknown"),
            old_value=data.get("old_value"),
            new_value=data.get("new_value"),
            change_magnitude=data.get("change_magnitude", 0.0),
            related_entities=data.get("related_entities", []),
            metadata=data.get("metadata", {}),
        )


@dataclass
class EvolutionPattern:
    """Represents a detected evolution pattern."""

    pattern_id: str
    pattern_type: PatternType
    start_time: datetime
    end_time: Optional[datetime] = None
    duration: Optional[timedelta] = None

    # Pattern characteristics
    entities_involved: Set[str] = field(default_factory=set)
    events: List[EvolutionEvent] = field(default_factory=list)
    metrics: Dict[str, float] = field(default_factory=dict)

    # Pattern metadata
    confidence_score: float = 0.0
    significance_score: float = 0.0
    description: str = ""

    def add_event(self, event: EvolutionEvent):
        """Add an event to this pattern."""
        self.events.append(event)
        if event.entity_id:
            self.entities_involved.add(event.entity_id)

        # Update end time and duration
        if not self.end_time or event.timestamp > self.end_time:
            self.end_time = event.timestamp

        if self.end_time:
            self.duration = self.end_time - self.start_time

    def calculate_metrics(self):
        """Calculate pattern metrics."""
        if not self.events:
            return

        # Basic metrics
        self.metrics["event_count"] = len(self.events)
        self.metrics["entity_count"] = len(self.entities_involved)
        self.metrics["duration_seconds"] = (
            self.duration.total_seconds() if self.duration else 0
        )

        # Rate metrics
        if self.duration and self.duration.total_seconds() > 0:
            self.metrics["event_rate"] = (
                len(self.events) / self.duration.total_seconds()
            )

        # Change magnitude metrics
        magnitudes = [e.change_magnitude for e in self.events if e.change_magnitude > 0]
        if magnitudes:
            self.metrics["avg_change_magnitude"] = statistics.mean(magnitudes)
            self.metrics["max_change_magnitude"] = max(magnitudes)
            self.metrics["total_change_magnitude"] = sum(magnitudes)

        # Event type distribution
        event_types = defaultdict(int)
        for event in self.events:
            event_types[event.event_type.value] += 1

        self.metrics["event_type_distribution"] = dict(event_types)
        self.metrics["primary_event_type"] = (
            max(event_types, key=event_types.get) if event_types else None
        )

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "pattern_id": self.pattern_id,
            "pattern_type": self.pattern_type.value,
            "start_time": self.start_time.isoformat(),
            "end_time": self.end_time.isoformat() if self.end_time else None,
            "duration_seconds": (
                self.duration.total_seconds() if self.duration else None
            ),
            "entities_involved": list(self.entities_involved),
            "events": [e.to_dict() for e in self.events],
            "metrics": self.metrics,
            "confidence_score": self.confidence_score,
            "significance_score": self.significance_score,
            "description": self.description,
        }


class EvolutionAnalyzer:
    """Analyzes evolution events to detect patterns and trends."""

    def __init__(
        self,
        pattern_detection_window: timedelta = timedelta(hours=1),
        min_events_for_pattern: int = 3,
        significance_threshold: float = 0.5,
    ):
        """Initialize evolution analyzer.

        Args:
            pattern_detection_window: Time window for pattern detection
            min_events_for_pattern: Minimum events needed for pattern
            significance_threshold: Minimum significance score for patterns
        """
        self.pattern_window = pattern_detection_window
        self.min_events = min_events_for_pattern
        self.significance_threshold = significance_threshold

        # Pattern detection state
        self.active_patterns: Dict[str, EvolutionPattern] = {}
        self.completed_patterns: List[EvolutionPattern] = []

        # Statistics
        self.stats = {
            "events_analyzed": 0,
            "patterns_detected": 0,
            "patterns_by_type": defaultdict(int),
            "avg_pattern_duration": 0.0,
        }

    def analyze_events(self, events: List[EvolutionEvent]) -> List[EvolutionPattern]:
        """Analyze events to detect evolution patterns.

        Args:
            events: List of evolution events

        Returns:
            List of detected patterns
        """
        # Sort events by timestamp
        sorted_events = sorted(events, key=lambda e: e.timestamp)

        detected_patterns = []

        for event in sorted_events:
            self.stats["events_analyzed"] += 1

            # Check for growth patterns
            growth_pattern = self._detect_growth_pattern(event, sorted_events)
            if growth_pattern:
                detected_patterns.append(growth_pattern)

            # Check for burst patterns
            burst_pattern = self._detect_burst_pattern(event, sorted_events)
            if burst_pattern:
                detected_patterns.append(burst_pattern)

            # Check for cascade patterns
            cascade_pattern = self._detect_cascade_pattern(event, sorted_events)
            if cascade_pattern:
                detected_patterns.append(cascade_pattern)

            # Check for oscillation patterns
            oscillation_pattern = self._detect_oscillation_pattern(event, sorted_events)
            if oscillation_pattern:
                detected_patterns.append(oscillation_pattern)

        # Filter by significance
        significant_patterns = [
            p
            for p in detected_patterns
            if p.significance_score >= self.significance_threshold
        ]

        # Update statistics
        self.stats["patterns_detected"] += len(significant_patterns)
        for pattern in significant_patterns:
            self.stats["patterns_by_type"][pattern.pattern_type.value] += 1

        return significant_patterns

    def _detect_growth_pattern(
        self, current_event: EvolutionEvent, all_events: List[EvolutionEvent]
    ) -> Optional[EvolutionPattern]:
        """Detect growth patterns."""
        if current_event.event_type not in [
            EvolutionEventType.NODE_BIRTH,
            EvolutionEventType.EDGE_BIRTH,
        ]:
            return None

        # Look for similar events in recent time window
        window_start = current_event.timestamp - self.pattern_window

        similar_events = [
            e
            for e in all_events
            if e.event_type == current_event.event_type
            and window_start <= e.timestamp <= current_event.timestamp
        ]

        if len(similar_events) < self.min_events:
            return None

        # Check for consistent growth rate
        time_diffs = []
        for i in range(1, len(similar_events)):
            time_diff = (
                similar_events[i].timestamp - similar_events[i - 1].timestamp
            ).total_seconds()
            time_diffs.append(time_diff)

        if not time_diffs:
            return None

        # Check if growth rate is relatively consistent
        avg_interval = statistics.mean(time_diffs)
        std_interval = statistics.stdev(time_diffs) if len(time_diffs) > 1 else 0

        consistency = 1.0 - (std_interval / avg_interval) if avg_interval > 0 else 0

        if consistency < 0.5:  # Too irregular to be a growth pattern
            return None

        # Create growth pattern
        pattern = EvolutionPattern(
            pattern_id=f"growth_{current_event.timestamp.isoformat()}",
            pattern_type=PatternType.GROWTH,
            start_time=similar_events[0].timestamp,
            end_time=current_event.timestamp,
        )

        for event in similar_events:
            pattern.add_event(event)

        pattern.calculate_metrics()
        pattern.confidence_score = consistency
        pattern.significance_score = min(
            1.0, len(similar_events) / 10.0
        )  # More events = more significant
        pattern.description = f"Growth pattern with {len(similar_events)} {current_event.event_type.value} events"

        return pattern

    def _detect_burst_pattern(
        self, current_event: EvolutionEvent, all_events: List[EvolutionEvent]
    ) -> Optional[EvolutionPattern]:
        """Detect burst patterns (sudden spikes in activity)."""
        # Look at short time window around current event
        burst_window = timedelta(minutes=5)  # Short window for burst detection
        window_start = current_event.timestamp - burst_window
        window_end = current_event.timestamp + burst_window

        # Count events in burst window
        burst_events = [
            e for e in all_events if window_start <= e.timestamp <= window_end
        ]

        if len(burst_events) < self.min_events:
            return None

        # Compare with normal activity level
        # Look at longer historical window
        history_window = timedelta(hours=24)
        history_start = current_event.timestamp - history_window
        history_end = window_start

        historical_events = [
            e for e in all_events if history_start <= e.timestamp <= history_end
        ]

        # Calculate normal rate and burst rate
        history_duration_hours = (history_end - history_start).total_seconds() / 3600
        burst_duration_hours = (window_end - window_start).total_seconds() / 3600

        if history_duration_hours == 0 or burst_duration_hours == 0:
            return None

        normal_rate = len(historical_events) / history_duration_hours
        burst_rate = len(burst_events) / burst_duration_hours

        # Check if burst rate is significantly higher than normal
        burst_factor = burst_rate / normal_rate if normal_rate > 0 else float("inf")

        if burst_factor < 3.0:  # Must be at least 3x normal rate
            return None

        # Create burst pattern
        pattern = EvolutionPattern(
            pattern_id=f"burst_{current_event.timestamp.isoformat()}",
            pattern_type=PatternType.BURST,
            start_time=window_start,
            end_time=window_end,
        )

        for event in burst_events:
            pattern.add_event(event)

        pattern.calculate_metrics()
        pattern.metrics["burst_factor"] = burst_factor
        pattern.metrics["normal_rate"] = normal_rate
        pattern.metrics["burst_rate"] = burst_rate

        pattern.confidence_score = min(1.0, burst_factor / 10.0)
        pattern.significance_score = min(1.0, len(burst_events) / 20.0)
        pattern.description = f"Burst pattern with {burst_factor:.1f}x normal activity"

        return pattern

    def _detect_cascade_pattern(
        self, current_event: EvolutionEvent, all_events: List[EvolutionEvent]
    ) -> Optional[EvolutionPattern]:
        """Detect cascade patterns (sequential propagation of changes)."""
        if not current_event.related_entities:
            return None

        # Look for events that might be part of a cascade
        cascade_window = timedelta(minutes=30)
        window_start = current_event.timestamp - cascade_window

        # Find events that might be causally related
        potential_cascade = []

        # Start with current event
        cascade_entities = set(
            [current_event.entity_id] + current_event.related_entities
        )
        potential_cascade.append(current_event)

        # Look backwards for connected events
        for event in reversed(all_events):
            if event.timestamp < window_start:
                break

            if event == current_event:
                continue

            # Check if this event is connected to the cascade
            if event.entity_id in cascade_entities or any(
                entity in cascade_entities for entity in event.related_entities
            ):

                potential_cascade.insert(
                    0, event
                )  # Insert at beginning to maintain order
                cascade_entities.add(event.entity_id)
                cascade_entities.update(event.related_entities)

        if len(potential_cascade) < self.min_events:
            return None

        # Check for temporal ordering and connectivity
        cascade_score = self._calculate_cascade_score(potential_cascade)

        if cascade_score < 0.5:
            return None

        # Create cascade pattern
        pattern = EvolutionPattern(
            pattern_id=f"cascade_{current_event.timestamp.isoformat()}",
            pattern_type=PatternType.CASCADE,
            start_time=potential_cascade[0].timestamp,
            end_time=current_event.timestamp,
        )

        for event in potential_cascade:
            pattern.add_event(event)

        pattern.calculate_metrics()
        pattern.metrics["cascade_score"] = cascade_score
        pattern.metrics["cascade_depth"] = len(cascade_entities)

        pattern.confidence_score = cascade_score
        pattern.significance_score = min(1.0, len(potential_cascade) / 8.0)
        pattern.description = (
            f"Cascade pattern affecting {len(cascade_entities)} entities"
        )

        return pattern

    def _detect_oscillation_pattern(
        self, current_event: EvolutionEvent, all_events: List[EvolutionEvent]
    ) -> Optional[EvolutionPattern]:
        """Detect oscillation patterns (periodic changes)."""
        if not current_event.entity_id:
            return None

        # Look for events affecting the same entity
        entity_events = [
            e for e in all_events if e.entity_id == current_event.entity_id
        ]

        if len(entity_events) < self.min_events * 2:  # Need more events for oscillation
            return None

        # Group events by type
        event_groups = defaultdict(list)
        for event in entity_events:
            event_groups[event.event_type].append(event)

        # Look for alternating patterns
        for event_type, type_events in event_groups.items():
            if len(type_events) >= self.min_events:
                oscillation_score = self._calculate_oscillation_score(type_events)

                if oscillation_score > 0.6:
                    pattern = EvolutionPattern(
                        pattern_id=f"oscillation_{current_event.entity_id}_{event_type.value}",
                        pattern_type=PatternType.OSCILLATION,
                        start_time=type_events[0].timestamp,
                        end_time=type_events[-1].timestamp,
                    )

                    for event in type_events:
                        pattern.add_event(event)

                    pattern.calculate_metrics()
                    pattern.metrics["oscillation_score"] = oscillation_score
                    pattern.metrics["period_estimate"] = (
                        self._estimate_oscillation_period(type_events)
                    )

                    pattern.confidence_score = oscillation_score
                    pattern.significance_score = min(1.0, len(type_events) / 6.0)
                    pattern.description = f"Oscillation in {event_type.value} for entity {current_event.entity_id}"

                    return pattern

        return None

    def _calculate_cascade_score(self, events: List[EvolutionEvent]) -> float:
        """Calculate cascade score based on temporal and connectivity patterns."""
        if len(events) < 2:
            return 0.0

        # Check temporal progression
        temporal_score = 1.0
        for i in range(1, len(events)):
            time_diff = (events[i].timestamp - events[i - 1].timestamp).total_seconds()
            if time_diff <= 0:  # Events should progress forward in time
                temporal_score *= 0.5

        # Check connectivity
        connectivity_score = 0.0
        connected_pairs = 0
        total_pairs = len(events) - 1

        for i in range(len(events) - 1):
            curr_event = events[i]
            next_event = events[i + 1]

            # Check if events are connected through entities or related entities
            if next_event.entity_id in (
                [curr_event.entity_id] + curr_event.related_entities
            ) or curr_event.entity_id in (
                [next_event.entity_id] + next_event.related_entities
            ):
                connected_pairs += 1

        if total_pairs > 0:
            connectivity_score = connected_pairs / total_pairs

        return (temporal_score + connectivity_score) / 2.0

    def _calculate_oscillation_score(self, events: List[EvolutionEvent]) -> float:
        """Calculate oscillation score based on regularity of timing."""
        if len(events) < 3:
            return 0.0

        # Calculate intervals between events
        intervals = []
        for i in range(1, len(events)):
            interval = (events[i].timestamp - events[i - 1].timestamp).total_seconds()
            intervals.append(interval)

        if not intervals:
            return 0.0

        # Check regularity of intervals
        mean_interval = statistics.mean(intervals)
        if mean_interval == 0:
            return 0.0

        variance = statistics.variance(intervals) if len(intervals) > 1 else 0
        coefficient_of_variation = (variance**0.5) / mean_interval

        # Lower coefficient of variation = more regular = higher oscillation score
        regularity_score = max(0.0, 1.0 - coefficient_of_variation)

        return regularity_score

    def _estimate_oscillation_period(
        self, events: List[EvolutionEvent]
    ) -> Optional[float]:
        """Estimate the period of oscillation in seconds."""
        if len(events) < 2:
            return None

        intervals = []
        for i in range(1, len(events)):
            interval = (events[i].timestamp - events[i - 1].timestamp).total_seconds()
            intervals.append(interval)

        if intervals:
            return statistics.mean(intervals)

        return None

    def get_pattern_summary(self) -> Dict[str, Any]:
        """Get summary of detected patterns."""
        all_patterns = list(self.active_patterns.values()) + self.completed_patterns

        if not all_patterns:
            return {
                "total_patterns": 0,
                "patterns_by_type": {},
                "avg_duration": 0.0,
                "avg_confidence": 0.0,
                "avg_significance": 0.0,
            }

        # Calculate statistics
        pattern_types = defaultdict(int)
        durations = []
        confidences = []
        significances = []

        for pattern in all_patterns:
            pattern_types[pattern.pattern_type.value] += 1

            if pattern.duration:
                durations.append(pattern.duration.total_seconds())

            confidences.append(pattern.confidence_score)
            significances.append(pattern.significance_score)

        return {
            "total_patterns": len(all_patterns),
            "patterns_by_type": dict(pattern_types),
            "avg_duration": statistics.mean(durations) if durations else 0.0,
            "avg_confidence": statistics.mean(confidences),
            "avg_significance": statistics.mean(significances),
            "stats": dict(self.stats),
        }


class GraphEvolutionTracker:
    """Tracks and analyzes graph evolution in real-time."""

    def __init__(
        self,
        history_size: int = 10000,
        analysis_interval: timedelta = timedelta(minutes=5),
        auto_analyze: bool = True,
    ):
        """Initialize graph evolution tracker.

        Args:
            history_size: Maximum events to keep in history
            analysis_interval: How often to run analysis
            auto_analyze: Whether to automatically analyze patterns
        """
        self.history_size = history_size
        self.analysis_interval = analysis_interval
        self.auto_analyze = auto_analyze

        # Event storage
        self.event_history: deque = deque(maxlen=history_size)
        self.events_by_entity: Dict[str, List[EvolutionEvent]] = defaultdict(list)

        # Analysis components
        self.analyzer = EvolutionAnalyzer()

        # Pattern tracking
        self.detected_patterns: List[EvolutionPattern] = []
        self.pattern_handlers: List[Callable[[EvolutionPattern], None]] = []

        # Background processing
        self.is_running = False
        self.analysis_task: Optional[asyncio.Task] = None

        # Statistics
        self.stats = {
            "total_events": 0,
            "events_by_type": defaultdict(int),
            "entities_tracked": 0,
            "patterns_detected": 0,
            "last_analysis_time": None,
        }

    def add_event(self, event: EvolutionEvent):
        """Add an evolution event to track.

        Args:
            event: Evolution event to add
        """
        # Add to history
        self.event_history.append(event)

        # Add to entity tracking
        if event.entity_id:
            self.events_by_entity[event.entity_id].append(event)

            # Trim entity history if too long
            if len(self.events_by_entity[event.entity_id]) > 1000:
                self.events_by_entity[event.entity_id] = self.events_by_entity[
                    event.entity_id
                ][-500:]

        # Update statistics
        self.stats["total_events"] += 1
        self.stats["events_by_type"][event.event_type.value] += 1
        self.stats["entities_tracked"] = len(self.events_by_entity)

        logger.debug(
            f"Added evolution event: {event.event_type.value} for {event.entity_id}"
        )

    def add_events(self, events: List[EvolutionEvent]):
        """Add multiple evolution events.

        Args:
            events: List of evolution events
        """
        for event in events:
            self.add_event(event)

    async def start_tracking(self):
        """Start background evolution tracking."""
        if self.is_running:
            logger.warning("Evolution tracker is already running")
            return

        self.is_running = True

        if self.auto_analyze:
            self.analysis_task = asyncio.create_task(self._analysis_loop())

        logger.info("Started graph evolution tracking")

    async def stop_tracking(self):
        """Stop background evolution tracking."""
        if not self.is_running:
            return

        self.is_running = False

        if self.analysis_task:
            self.analysis_task.cancel()
            self.analysis_task = None

        # Run final analysis
        await self.analyze_patterns()

        logger.info("Stopped graph evolution tracking")

    async def _analysis_loop(self):
        """Background analysis loop."""
        while self.is_running:
            try:
                await asyncio.sleep(self.analysis_interval.total_seconds())
                await self.analyze_patterns()

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in evolution analysis loop: {e}", exc_info=True)

    async def analyze_patterns(self) -> List[EvolutionPattern]:
        """Analyze recent events for evolution patterns.

        Returns:
            List of newly detected patterns
        """
        # Get recent events for analysis
        recent_events = list(self.event_history)

        if not recent_events:
            return []

        # Run pattern analysis
        new_patterns = self.analyzer.analyze_events(recent_events)

        # Filter out patterns we've already detected
        existing_pattern_ids = {p.pattern_id for p in self.detected_patterns}
        truly_new_patterns = [
            p for p in new_patterns if p.pattern_id not in existing_pattern_ids
        ]

        # Add new patterns
        self.detected_patterns.extend(truly_new_patterns)

        # Update statistics
        self.stats["patterns_detected"] = len(self.detected_patterns)
        self.stats["last_analysis_time"] = datetime.now()

        # Notify pattern handlers
        for pattern in truly_new_patterns:
            for handler in self.pattern_handlers:
                try:
                    handler(pattern)
                except Exception as e:
                    logger.error(f"Error in pattern handler: {e}", exc_info=True)

        if truly_new_patterns:
            logger.info(f"Detected {len(truly_new_patterns)} new evolution patterns")

        return truly_new_patterns

    def get_entity_evolution(self, entity_id: str) -> List[EvolutionEvent]:
        """Get evolution history for specific entity.

        Args:
            entity_id: Entity ID to get history for

        Returns:
            List of evolution events for the entity
        """
        return self.events_by_entity.get(entity_id, []).copy()

    def get_recent_events(self, time_window: timedelta) -> List[EvolutionEvent]:
        """Get events from recent time window.

        Args:
            time_window: Time window to look back

        Returns:
            List of recent events
        """
        cutoff_time = datetime.now() - time_window

        return [event for event in self.event_history if event.timestamp >= cutoff_time]

    def get_patterns_by_type(self, pattern_type: PatternType) -> List[EvolutionPattern]:
        """Get patterns of specific type.

        Args:
            pattern_type: Pattern type to filter by

        Returns:
            List of patterns of the specified type
        """
        return [p for p in self.detected_patterns if p.pattern_type == pattern_type]

    def add_pattern_handler(self, handler: Callable[[EvolutionPattern], None]):
        """Add a pattern detection handler.

        Args:
            handler: Function to call when patterns are detected
        """
        self.pattern_handlers.append(handler)
        logger.info(f"Added pattern handler: {handler.__name__}")

    def remove_pattern_handler(self, handler: Callable[[EvolutionPattern], None]):
        """Remove a pattern detection handler.

        Args:
            handler: Handler function to remove
        """
        if handler in self.pattern_handlers:
            self.pattern_handlers.remove(handler)
            logger.info(f"Removed pattern handler: {handler.__name__}")

    def get_evolution_summary(self) -> Dict[str, Any]:
        """Get summary of tracked evolution.

        Returns:
            Summary statistics and information
        """
        # Calculate time ranges
        if self.event_history:
            earliest_event = min(self.event_history, key=lambda e: e.timestamp)
            latest_event = max(self.event_history, key=lambda e: e.timestamp)
            tracking_duration = latest_event.timestamp - earliest_event.timestamp
        else:
            earliest_event = None
            latest_event = None
            tracking_duration = timedelta(0)

        # Pattern summary
        pattern_summary = self.analyzer.get_pattern_summary()

        # Most active entities
        entity_activity = {
            entity_id: len(events)
            for entity_id, events in self.events_by_entity.items()
        }
        most_active = sorted(entity_activity.items(), key=lambda x: x[1], reverse=True)[
            :10
        ]

        return {
            "tracking_duration_seconds": tracking_duration.total_seconds(),
            "earliest_event": (
                earliest_event.timestamp.isoformat() if earliest_event else None
            ),
            "latest_event": (
                latest_event.timestamp.isoformat() if latest_event else None
            ),
            "event_history_size": len(self.event_history),
            "most_active_entities": most_active,
            "pattern_summary": pattern_summary,
            "stats": dict(self.stats),
            "last_analysis_time": (
                self.stats["last_analysis_time"].isoformat()
                if self.stats["last_analysis_time"]
                else None
            ),
        }

    def export_evolution_data(self) -> Dict[str, Any]:
        """Export all evolution data.

        Returns:
            Complete evolution data including events and patterns
        """
        return {
            "events": [event.to_dict() for event in self.event_history],
            "patterns": [pattern.to_dict() for pattern in self.detected_patterns],
            "entity_events": {
                entity_id: [event.to_dict() for event in events]
                for entity_id, events in self.events_by_entity.items()
            },
            "summary": self.get_evolution_summary(),
        }

    def clear_history(self):
        """Clear evolution history (for testing or reset)."""
        self.event_history.clear()
        self.events_by_entity.clear()
        self.detected_patterns.clear()

        # Reset stats
        self.stats = {
            "total_events": 0,
            "events_by_type": defaultdict(int),
            "entities_tracked": 0,
            "patterns_detected": 0,
            "last_analysis_time": None,
        }

        logger.info("Cleared evolution history")


# Integration with CDC processor
def integrate_evolution_tracker_with_cdc(
    evolution_tracker: GraphEvolutionTracker, cdc_processor
):
    """Integrate evolution tracker with CDC processor.

    Args:
        evolution_tracker: Evolution tracker instance
        cdc_processor: CDC processor instance
    """
    from ..streaming.cdc_processor import ChangeType, GraphChangeEvent

    def convert_cdc_to_evolution_event(cdc_event: GraphChangeEvent) -> EvolutionEvent:
        """Convert CDC event to evolution event."""
        # Map CDC change types to evolution event types
        type_mapping = {
            ChangeType.NODE_CREATED: EvolutionEventType.NODE_BIRTH,
            ChangeType.NODE_DELETED: EvolutionEventType.NODE_DEATH,
            ChangeType.NODE_UPDATED: EvolutionEventType.NODE_PROPERTY_CHANGE,
            ChangeType.LABEL_ADDED: EvolutionEventType.NODE_LABEL_CHANGE,
            ChangeType.LABEL_REMOVED: EvolutionEventType.NODE_LABEL_CHANGE,
            ChangeType.RELATIONSHIP_CREATED: EvolutionEventType.EDGE_BIRTH,
            ChangeType.RELATIONSHIP_DELETED: EvolutionEventType.EDGE_DEATH,
            ChangeType.RELATIONSHIP_UPDATED: EvolutionEventType.EDGE_PROPERTY_CHANGE,
        }

        evolution_type = type_mapping.get(
            cdc_event.change_type, EvolutionEventType.NODE_PROPERTY_CHANGE
        )

        # Calculate change magnitude
        change_magnitude = 0.0
        if cdc_event.property_changes:
            change_magnitude = len(cdc_event.property_changes)
        elif cdc_event.old_properties and cdc_event.new_properties:
            # Simple measure of property differences
            old_keys = set(cdc_event.old_properties.keys())
            new_keys = set(cdc_event.new_properties.keys())
            change_magnitude = len(old_keys.symmetric_difference(new_keys))

        # Related entities (for relationships, include start and end nodes)
        related_entities = []
        if cdc_event.start_node_id:
            related_entities.append(cdc_event.start_node_id)
        if cdc_event.end_node_id:
            related_entities.append(cdc_event.end_node_id)

        return EvolutionEvent(
            event_id=cdc_event.event_id,
            event_type=evolution_type,
            timestamp=cdc_event.timestamp,
            entity_id=cdc_event.entity_id,
            entity_type=cdc_event.entity_type,
            old_value=cdc_event.old_properties,
            new_value=cdc_event.new_properties,
            change_magnitude=change_magnitude,
            related_entities=related_entities,
            metadata={
                "transaction_id": cdc_event.transaction_id,
                "user_id": cdc_event.user_id,
                "session_id": cdc_event.session_id,
                **cdc_event.metadata,
            },
        )

    def cdc_event_handler(cdc_event: GraphChangeEvent):
        """Handle CDC events and convert to evolution events."""
        evolution_event = convert_cdc_to_evolution_event(cdc_event)
        evolution_tracker.add_event(evolution_event)

    # Register handler with CDC processor
    cdc_processor.add_event_handler(cdc_event_handler)
    logger.info("Integrated evolution tracker with CDC processor")

    return cdc_event_handler
