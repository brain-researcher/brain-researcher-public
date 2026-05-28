"""Complex event processing and stream analytics - completes KG-034 streaming.

This module provides windowed stream processing, event aggregation, and
complex event detection for real-time graph analytics and insights.
"""

import logging
import asyncio
import json
from typing import Dict, List, Any, Optional, Callable, Set, Tuple, Union, ClassVar
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta
from enum import Enum
import uuid
from collections import defaultdict, deque
import statistics
import heapq
import itertools

from .cdc_processor import GraphChangeEvent, ChangeType

logger = logging.getLogger(__name__)


class WindowType(Enum):
    """Types of event windows."""
    
    TUMBLING = "tumbling"  # Non-overlapping fixed-size windows
    HOPPING = "hopping"    # Overlapping fixed-size windows  
    SESSION = "session"    # Dynamic windows based on activity
    SLIDING = "sliding"    # Continuous windows with fixed size


class AggregationType(Enum):
    """Types of aggregations."""
    
    COUNT = "count"
    SUM = "sum"
    AVERAGE = "average"
    MIN = "min"
    MAX = "max"
    DISTINCT_COUNT = "distinct_count"
    TOP_K = "top_k"
    HISTOGRAM = "histogram"
    PERCENTILE = "percentile"


@dataclass
class EventWindow:
    """Represents a window of events for processing."""
    
    window_id: str
    window_type: WindowType
    start_time: datetime
    end_time: datetime
    duration: timedelta
    
    events: List[GraphChangeEvent] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    # Aggregated results
    aggregations: Dict[str, Any] = field(default_factory=dict)
    
    def add_event(self, event: GraphChangeEvent):
        """Add an event to this window."""
        if self.start_time <= event.timestamp <= self.end_time:
            self.events.append(event)
            return True
        return False
    
    def is_complete(self, current_time: Optional[datetime] = None) -> bool:
        """Check if window is complete."""
        current_time = current_time or datetime.now()
        
        if self.window_type == WindowType.SESSION:
            # Session window is complete after inactivity period
            if not self.events:
                return False
            last_event = max(self.events, key=lambda e: e.timestamp)
            return current_time - last_event.timestamp > timedelta(seconds=30)
        else:
            # Fixed windows are complete when end time is reached
            return current_time >= self.end_time
    
    def get_event_count(self) -> int:
        """Get total number of events."""
        return len(self.events)
    
    def get_events_by_type(self) -> Dict[str, int]:
        """Get event count by change type."""
        counts = defaultdict(int)
        for event in self.events:
            counts[event.change_type.value] += 1
        return dict(counts)
    
    def get_affected_entities(self) -> Set[str]:
        """Get set of affected entity IDs."""
        entities = set()
        for event in self.events:
            if event.entity_id:
                entities.add(event.entity_id)
        return entities
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "window_id": self.window_id,
            "window_type": self.window_type.value,
            "start_time": self.start_time.isoformat(),
            "end_time": self.end_time.isoformat(),
            "duration_seconds": self.duration.total_seconds(),
            "event_count": len(self.events),
            "events_by_type": self.get_events_by_type(),
            "affected_entities": list(self.get_affected_entities()),
            "aggregations": self.aggregations,
            "metadata": self.metadata
        }


@dataclass
class AggregationRule:
    """Defines how to aggregate events in a window."""
    
    name: str
    aggregation_type: AggregationType
    field_path: Optional[str] = None  # Path to field for aggregation
    group_by: Optional[List[str]] = None  # Fields to group by
    filter_condition: Optional[Callable[[GraphChangeEvent], bool]] = None
    parameters: Dict[str, Any] = field(default_factory=dict)

    DISTINCT_COUNT: ClassVar[AggregationType] = AggregationType.DISTINCT_COUNT
    
    def apply(self, events: List[GraphChangeEvent]) -> Any:
        """Apply aggregation to events."""
        # Filter events if condition is provided
        if self.filter_condition:
            events = [e for e in events if self.filter_condition(e)]
        
        if not events:
            return None
        
        # Group events if needed
        if self.group_by:
            groups = self._group_events(events)
            return {str(key): self._aggregate_group(group) for key, group in groups.items()}
        else:
            return self._aggregate_group(events)
    
    def _group_events(self, events: List[GraphChangeEvent]) -> Dict[Tuple, List[GraphChangeEvent]]:
        """Group events by specified fields."""
        groups = defaultdict(list)
        
        for event in events:
            key_values = []
            for field in self.group_by:
                if field == "change_type":
                    key_values.append(event.change_type.value)
                elif field == "entity_type":
                    key_values.append(event.entity_type)
                elif field == "entity_id":
                    key_values.append(event.entity_id)
                elif field == "user_id":
                    key_values.append(event.user_id)
                elif field.startswith("labels."):
                    # Handle label-specific grouping
                    label_index = int(field.split(".")[1]) if len(field.split(".")) > 1 else 0
                    if label_index < len(event.labels):
                        key_values.append(event.labels[label_index])
                    else:
                        key_values.append(None)
                else:
                    # Try to get from properties or metadata
                    value = event.new_properties.get(field) or event.metadata.get(field)
                    key_values.append(value)
            
            groups[tuple(key_values)].append(event)
        
        return groups
    
    def _aggregate_group(self, events: List[GraphChangeEvent]) -> Any:
        """Aggregate a group of events."""
        if self.aggregation_type == AggregationType.COUNT:
            return len(events)
        
        elif self.aggregation_type == AggregationType.DISTINCT_COUNT:
            if self.field_path:
                values = set()
                for event in events:
                    value = self._get_field_value(event, self.field_path)
                    if value is not None:
                        values.add(str(value))
                return len(values)
            else:
                return len(set(e.entity_id for e in events if e.entity_id))
        
        elif self.aggregation_type in [AggregationType.SUM, AggregationType.AVERAGE, 
                                       AggregationType.MIN, AggregationType.MAX]:
            if not self.field_path:
                return None
                
            values = []
            for event in events:
                value = self._get_field_value(event, self.field_path)
                if isinstance(value, (int, float)):
                    values.append(value)
            
            if not values:
                return None
            
            if self.aggregation_type == AggregationType.SUM:
                return sum(values)
            elif self.aggregation_type == AggregationType.AVERAGE:
                return statistics.mean(values)
            elif self.aggregation_type == AggregationType.MIN:
                return min(values)
            elif self.aggregation_type == AggregationType.MAX:
                return max(values)
        
        elif self.aggregation_type == AggregationType.TOP_K:
            k = self.parameters.get("k", 5)
            if self.field_path:
                value_counts = defaultdict(int)
                for event in events:
                    value = self._get_field_value(event, self.field_path)
                    if value is not None:
                        value_counts[str(value)] += 1
                return dict(sorted(value_counts.items(), key=lambda x: x[1], reverse=True)[:k])
            else:
                # Top K entity types
                type_counts = defaultdict(int)
                for event in events:
                    type_counts[event.change_type.value] += 1
                return dict(sorted(type_counts.items(), key=lambda x: x[1], reverse=True)[:k])
        
        elif self.aggregation_type == AggregationType.HISTOGRAM:
            if not self.field_path:
                return None
                
            bins = self.parameters.get("bins", 10)
            values = []
            for event in events:
                value = self._get_field_value(event, self.field_path)
                if isinstance(value, (int, float)):
                    values.append(value)
            
            if not values:
                return None
            
            # Simple histogram implementation
            min_val, max_val = min(values), max(values)
            if min_val == max_val:
                return {str(min_val): len(values)}
            
            bin_size = (max_val - min_val) / bins
            histogram = defaultdict(int)
            
            for value in values:
                bin_index = min(int((value - min_val) / bin_size), bins - 1)
                bin_start = min_val + bin_index * bin_size
                bin_end = min_val + (bin_index + 1) * bin_size
                bin_key = f"{bin_start:.2f}-{bin_end:.2f}"
                histogram[bin_key] += 1
            
            return dict(histogram)
        
        elif self.aggregation_type == AggregationType.PERCENTILE:
            if not self.field_path:
                return None
                
            percentile = self.parameters.get("percentile", 50)
            values = []
            for event in events:
                value = self._get_field_value(event, self.field_path)
                if isinstance(value, (int, float)):
                    values.append(value)
            
            if not values:
                return None
            
            values.sort()
            index = (percentile / 100) * (len(values) - 1)
            if index.is_integer():
                return values[int(index)]
            else:
                lower = values[int(index)]
                upper = values[int(index) + 1]
                return lower + (upper - lower) * (index - int(index))
        
        return None
    
    def _get_field_value(self, event: GraphChangeEvent, field_path: str) -> Any:
        """Get field value from event using dot notation."""
        if "." not in field_path:
            # Simple field access
            if hasattr(event, field_path):
                return getattr(event, field_path)
            elif field_path in event.new_properties:
                return event.new_properties[field_path]
            elif field_path in event.metadata:
                return event.metadata[field_path]
            return None
        
        # Nested field access
        parts = field_path.split(".")
        if parts[0] == "new_properties":
            return event.new_properties.get(parts[1]) if len(parts) > 1 else None
        elif parts[0] == "old_properties":
            return event.old_properties.get(parts[1]) if len(parts) > 1 else None
        elif parts[0] == "metadata":
            return event.metadata.get(parts[1]) if len(parts) > 1 else None
        elif parts[0] == "property_changes":
            if len(parts) > 2:
                change = event.property_changes.get(parts[1])
                if change and isinstance(change, dict):
                    return change.get(parts[2])
            return None
        
        return None


class StreamProcessor:
    """Processes streams of graph events with windowing and aggregation."""
    
    def __init__(
        self,
        window_size: timedelta = timedelta(minutes=5),
        window_type: WindowType = WindowType.TUMBLING,
        hop_size: Optional[timedelta] = None,
        max_windows: int = 100,
        late_arrival_grace: timedelta = timedelta(minutes=1),
        buffer_size: int = 1000,
    ):
        """Initialize stream processor.
        
        Args:
            window_size: Size of processing windows
            window_type: Type of windowing strategy
            hop_size: Hop size for hopping windows
            max_windows: Maximum number of active windows
            late_arrival_grace: Grace period for late-arriving events
        """
        self.window_size = window_size
        self.window_type = window_type
        self.hop_size = hop_size or window_size
        self.max_windows = max_windows
        self.late_arrival_grace = late_arrival_grace
        
        # Active windows
        self.windows: Dict[str, EventWindow] = {}
        self.completed_windows: deque = deque(maxlen=max_windows)
        
        # Aggregation rules
        self.aggregation_rules: List[AggregationRule] = []
        
        # Event handlers
        self.window_handlers: List[Callable[[EventWindow], None]] = []
        self.aggregation_handlers: List[Callable[[str, Any, EventWindow], None]] = []
        
        # Background processing
        self.is_running = False
        self.tasks: List[asyncio.Task] = []
        
        # Statistics
        self.stats = {
            "events_processed": 0,
            "windows_created": 0,
            "windows_completed": 0,
            "aggregations_computed": 0,
            "late_events": 0,
            "dropped_events": 0
        }
        
        # Event buffer for ordering
        self.event_buffer: List[Tuple[datetime, int, GraphChangeEvent]] = []
        self.buffer_size = buffer_size
        self._event_counter = itertools.count()
    
    async def start(self):
        """Start the stream processor."""
        if self.is_running:
            logger.warning("Stream processor is already running")
            return
        
        self.is_running = True
        
        # Start background tasks
        self.tasks.append(asyncio.create_task(self._window_manager()))
        self.tasks.append(asyncio.create_task(self._event_processor()))
        
        logger.info("Stream processor started")
    
    async def stop(self):
        """Stop the stream processor."""
        if not self.is_running:
            return
        
        self.is_running = False
        
        # Cancel background tasks
        for task in self.tasks:
            task.cancel()
        
        # Process remaining events
        await self._process_pending_events()
        
        # Complete remaining windows
        await self._complete_all_windows()
        
        logger.info("Stream processor stopped")
    
    async def process_event(self, event: GraphChangeEvent):
        """Process a single event."""
        if not self.is_running:
            logger.warning("Stream processor not running")
            return
        
        # Add to buffer for ordering
        heapq.heappush(self.event_buffer, (event.timestamp, next(self._event_counter), event))
        
        # Keep buffer size manageable
        if len(self.event_buffer) > self.buffer_size:
            self.stats["dropped_events"] += 1
            heapq.heappop(self.event_buffer)  # Drop oldest
        
        self.stats["events_processed"] += 1
    
    async def process_events(self, events: List[GraphChangeEvent]):
        """Process a batch of events."""
        for event in events:
            await self.process_event(event)
    
    async def _event_processor(self):
        """Process buffered events in order."""
        while self.is_running:
            try:
                await asyncio.sleep(0.1)  # Process every 100ms
                await self._process_pending_events()
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in event processor: {e}", exc_info=True)
    
    async def _process_pending_events(self):
        """Process events from buffer."""
        current_time = datetime.now()
        processed_events = []
        
        # Process events that are not too late
        while self.event_buffer:
            event_time, _, event = self.event_buffer[0]
            
            # Check if event is too late
            if current_time - event_time > self.late_arrival_grace:
                heapq.heappop(self.event_buffer)
                self.stats["late_events"] += 1
                continue
            
            # Allow processing of near-future events within grace window
            if event_time > current_time + self.late_arrival_grace:
                break
            
            # Process the event
            heapq.heappop(self.event_buffer)
            processed_events.append(event)
        
        # Assign events to windows
        for event in processed_events:
            await self._assign_to_windows(event)
    
    async def _assign_to_windows(self, event: GraphChangeEvent):
        """Assign an event to appropriate windows."""
        event_time = event.timestamp
        
        if self.window_type == WindowType.TUMBLING:
            # Create window if needed
            window_start = self._get_window_start_time(event_time)
            window_id = f"tumbling_{window_start.isoformat()}"
            
            if window_id not in self.windows:
                await self._create_window(window_id, window_start, window_start + self.window_size)
            
            self.windows[window_id].add_event(event)
        
        elif self.window_type == WindowType.HOPPING:
            # Event can belong to multiple hopping windows
            current_time = event_time
            
            # Find all windows this event should belong to
            while current_time >= event_time - self.window_size:
                window_start = self._get_window_start_time(current_time)
                window_id = f"hopping_{window_start.isoformat()}"
                
                if window_id not in self.windows:
                    await self._create_window(window_id, window_start, window_start + self.window_size)
                
                window = self.windows[window_id]
                window.add_event(event)
                
                current_time -= self.hop_size
        
        elif self.window_type == WindowType.SESSION:
            # Find or create session window
            session_window = None
            
            for window in self.windows.values():
                if window.window_type == WindowType.SESSION:
                    # Check if event belongs to this session (within 30 seconds of last event)
                    if window.events:
                        last_event = max(window.events, key=lambda e: e.timestamp)
                        if abs((event_time - last_event.timestamp).total_seconds()) <= 30:
                            session_window = window
                            break
            
            if not session_window:
                # Create new session window
                window_id = f"session_{event_time.isoformat()}_{uuid.uuid4().hex[:8]}"
                session_window = await self._create_window(window_id, event_time, event_time + timedelta(hours=1))
            
            session_window.add_event(event)
            # Update session window end time
            session_window.end_time = max(session_window.end_time, event_time + timedelta(minutes=30))
        
        elif self.window_type == WindowType.SLIDING:
            # Sliding window - create a new window for each event
            window_id = f"sliding_{event_time.isoformat()}_{uuid.uuid4().hex[:8]}"
            window_start = event_time - self.window_size
            window_end = event_time
            
            window = await self._create_window(window_id, window_start, window_end)
            
            # Add all events in the time range
            for existing_window in self.windows.values():
                for existing_event in existing_window.events:
                    if window_start <= existing_event.timestamp <= window_end:
                        window.add_event(existing_event)
            
            window.add_event(event)
    
    def _get_window_start_time(self, event_time: datetime) -> datetime:
        """Get window start time for tumbling/hopping windows."""
        # Align to window boundaries
        epoch = datetime(1970, 1, 1)
        seconds_since_epoch = (event_time - epoch).total_seconds()
        window_seconds = self.window_size.total_seconds()
        
        window_number = int(seconds_since_epoch // window_seconds)
        return epoch + timedelta(seconds=window_number * window_seconds)
    
    async def _create_window(self, window_id: str, start_time: datetime, end_time: datetime) -> EventWindow:
        """Create a new event window."""
        window = EventWindow(
            window_id=window_id,
            window_type=self.window_type,
            start_time=start_time,
            end_time=end_time,
            duration=end_time - start_time
        )
        
        self.windows[window_id] = window
        self.stats["windows_created"] += 1
        
        logger.debug(f"Created window {window_id}: {start_time} - {end_time}")
        return window
    
    async def _window_manager(self):
        """Manage window lifecycle."""
        while self.is_running:
            try:
                await asyncio.sleep(1.0)  # Check every second
                await self._check_completed_windows()
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in window manager: {e}", exc_info=True)
    
    async def _check_completed_windows(self):
        """Check for completed windows and process them."""
        current_time = datetime.now()
        completed_window_ids = []
        
        for window_id, window in self.windows.items():
            if window.is_complete(current_time):
                completed_window_ids.append(window_id)
        
        # Process completed windows
        for window_id in completed_window_ids:
            window = self.windows.pop(window_id)
            await self._complete_window(window)
    
    async def _complete_window(self, window: EventWindow):
        """Complete and process a window."""
        logger.debug(f"Completing window {window.window_id} with {len(window.events)} events")
        
        # Apply aggregation rules
        for rule in self.aggregation_rules:
            try:
                result = rule.apply(window.events)
                window.aggregations[rule.name] = result
                self.stats["aggregations_computed"] += 1
                
                # Notify aggregation handlers
                for handler in self.aggregation_handlers:
                    try:
                        handler(rule.name, result, window)
                    except Exception as e:
                        logger.error(f"Error in aggregation handler: {e}", exc_info=True)
                        
            except Exception as e:
                logger.error(f"Error applying aggregation rule {rule.name}: {e}", exc_info=True)
        
        # Notify window handlers
        for handler in self.window_handlers:
            try:
                handler(window)
            except Exception as e:
                logger.error(f"Error in window handler: {e}", exc_info=True)
        
        # Archive completed window
        self.completed_windows.append(window)
        self.stats["windows_completed"] += 1
    
    async def _complete_all_windows(self):
        """Complete all remaining windows."""
        for window in list(self.windows.values()):
            await self._complete_window(window)
        self.windows.clear()
    
    def add_aggregation_rule(self, rule: AggregationRule):
        """Add an aggregation rule."""
        self.aggregation_rules.append(rule)
        logger.info(f"Added aggregation rule: {rule.name}")
    
    def remove_aggregation_rule(self, rule_name: str):
        """Remove an aggregation rule."""
        self.aggregation_rules = [r for r in self.aggregation_rules if r.name != rule_name]
        logger.info(f"Removed aggregation rule: {rule_name}")
    
    def add_window_handler(self, handler: Callable[[EventWindow], None]):
        """Add a window completion handler."""
        self.window_handlers.append(handler)
        logger.info(f"Added window handler: {handler.__name__}")
    
    def add_aggregation_handler(self, handler: Callable[[str, Any, EventWindow], None]):
        """Add an aggregation result handler."""
        self.aggregation_handlers.append(handler)
        logger.info(f"Added aggregation handler: {handler.__name__}")
    
    def get_active_windows(self) -> List[Dict[str, Any]]:
        """Get information about active windows."""
        return [window.to_dict() for window in self.windows.values()]
    
    def get_completed_windows(self, limit: int = 10) -> List[Dict[str, Any]]:
        """Get recent completed windows."""
        return [window.to_dict() for window in list(self.completed_windows)[-limit:]]
    
    def get_stats(self) -> Dict[str, Any]:
        """Get stream processor statistics."""
        return {
            "is_running": self.is_running,
            "window_type": self.window_type.value,
            "window_size_seconds": self.window_size.total_seconds(),
            "active_windows": len(self.windows),
            "completed_windows": len(self.completed_windows),
            "aggregation_rules": len(self.aggregation_rules),
            "window_handlers": len(self.window_handlers),
            "aggregation_handlers": len(self.aggregation_handlers),
            "buffer_size": len(self.event_buffer),
            **self.stats
        }


# Predefined aggregation rules for common use cases
def create_common_aggregation_rules() -> List[AggregationRule]:
    """Create commonly used aggregation rules."""
    return [
        # Event counts by type
        AggregationRule(
            name="event_count_by_type",
            aggregation_type=AggregationType.COUNT,
            group_by=["change_type"]
        ),
        
        # Distinct entities affected
        AggregationRule(
            name="distinct_entities_affected",
            aggregation_type=AggregationType.DISTINCT_COUNT,
            field_path="entity_id"
        ),
        
        # Top 5 most active users
        AggregationRule(
            name="top_users",
            aggregation_type=AggregationType.TOP_K,
            field_path="user_id",
            parameters={"k": 5}
        ),
        
        # Node creation rate
        AggregationRule(
            name="node_creation_rate",
            aggregation_type=AggregationType.COUNT,
            filter_condition=lambda e: e.change_type == ChangeType.NODE_CREATED
        ),
        
        # Relationship creation rate  
        AggregationRule(
            name="relationship_creation_rate",
            aggregation_type=AggregationType.COUNT,
            filter_condition=lambda e: e.change_type in [ChangeType.RELATIONSHIP_CREATED]
        ),
        
        # Entity types being modified
        AggregationRule(
            name="entity_types_modified",
            aggregation_type=AggregationType.TOP_K,
            field_path="entity_type",
            parameters={"k": 10}
        )
    ]
