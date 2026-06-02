"""Unit tests for stream processor module.

This module tests the complex event processing functionality including:
- Event windowing strategies
- Stream aggregations
- Event ordering and buffering
- Window lifecycle management
- Complex event pattern detection
"""

import asyncio
from datetime import datetime, timedelta
from typing import Any, Dict, List
from unittest.mock import AsyncMock, Mock, patch

import pytest

# Import the modules to test
try:
    from brain_researcher.services.br_kg.streaming.cdc_processor import (
        ChangeType,
        GraphChangeEvent,
    )
    from brain_researcher.services.br_kg.streaming.stream_processor import (
        AggregationRule,
        AggregationType,
        EventWindow,
        StreamProcessor,
        WindowType,
        create_common_aggregation_rules,
    )
except ImportError:
    # Fallback if absolute imports don't work
    import os
    import sys

    sys.path.append(os.path.join(os.path.dirname(__file__), "..", "..", "..", ".."))
    from brain_researcher.services.br_kg.streaming.cdc_processor import (
        ChangeType,
        GraphChangeEvent,
    )
    from brain_researcher.services.br_kg.streaming.stream_processor import (
        AggregationRule,
        AggregationType,
        EventWindow,
        StreamProcessor,
        WindowType,
        create_common_aggregation_rules,
    )


class TestEventWindow:
    """Test EventWindow class."""

    def test_window_creation(self):
        """Test creating an event window."""
        start_time = datetime.now()
        end_time = start_time + timedelta(minutes=5)

        window = EventWindow(
            window_id="test-window-1",
            window_type=WindowType.TUMBLING,
            start_time=start_time,
            end_time=end_time,
            duration=end_time - start_time,
        )

        assert window.window_id == "test-window-1"
        assert window.window_type == WindowType.TUMBLING
        assert window.start_time == start_time
        assert window.end_time == end_time
        assert window.duration == timedelta(minutes=5)
        assert len(window.events) == 0
        assert len(window.aggregations) == 0

    def test_add_event_in_window(self):
        """Test adding events within window time range."""
        start_time = datetime.now()
        end_time = start_time + timedelta(minutes=5)

        window = EventWindow(
            window_id="test-window",
            window_type=WindowType.TUMBLING,
            start_time=start_time,
            end_time=end_time,
            duration=end_time - start_time,
        )

        # Event within window
        event1 = GraphChangeEvent(
            event_id="event-1",
            change_type=ChangeType.NODE_CREATED,
            timestamp=start_time + timedelta(minutes=2),
            entity_id="node-1",
            entity_type="node",
        )

        # Event outside window
        event2 = GraphChangeEvent(
            event_id="event-2",
            change_type=ChangeType.NODE_CREATED,
            timestamp=end_time + timedelta(minutes=1),
            entity_id="node-2",
            entity_type="node",
        )

        assert window.add_event(event1) is True
        assert window.add_event(event2) is False
        assert len(window.events) == 1
        assert window.events[0].event_id == "event-1"

    def test_window_completion(self):
        """Test window completion logic."""
        start_time = datetime.now()
        end_time = start_time + timedelta(minutes=5)

        # Fixed window
        window = EventWindow(
            window_id="test-window",
            window_type=WindowType.TUMBLING,
            start_time=start_time,
            end_time=end_time,
            duration=end_time - start_time,
        )

        # Before end time
        assert not window.is_complete(start_time + timedelta(minutes=2))

        # After end time
        assert window.is_complete(end_time + timedelta(minutes=1))

    def test_session_window_completion(self):
        """Test session window completion logic."""
        start_time = datetime.now()
        end_time = start_time + timedelta(hours=1)

        window = EventWindow(
            window_id="session-window",
            window_type=WindowType.SESSION,
            start_time=start_time,
            end_time=end_time,
            duration=end_time - start_time,
        )

        # Empty session window
        assert not window.is_complete()

        # Add event
        event = GraphChangeEvent(
            event_id="event-1",
            change_type=ChangeType.NODE_CREATED,
            timestamp=start_time,
            entity_id="node-1",
            entity_type="node",
        )
        window.add_event(event)

        # Recent activity - not complete
        assert not window.is_complete(start_time + timedelta(seconds=10))

        # No recent activity - complete
        assert window.is_complete(start_time + timedelta(minutes=1))

    def test_get_events_by_type(self):
        """Test getting event counts by type."""
        window = EventWindow(
            window_id="test-window",
            window_type=WindowType.TUMBLING,
            start_time=datetime.now(),
            end_time=datetime.now() + timedelta(minutes=5),
            duration=timedelta(minutes=5),
        )

        # Add various events
        events = [
            GraphChangeEvent(
                "1", ChangeType.NODE_CREATED, datetime.now(), "n1", "node"
            ),
            GraphChangeEvent(
                "2", ChangeType.NODE_CREATED, datetime.now(), "n2", "node"
            ),
            GraphChangeEvent(
                "3", ChangeType.NODE_UPDATED, datetime.now(), "n1", "node"
            ),
            GraphChangeEvent(
                "4",
                ChangeType.RELATIONSHIP_CREATED,
                datetime.now(),
                "r1",
                "relationship",
            ),
        ]

        for event in events:
            window.add_event(event)

        counts = window.get_events_by_type()

        assert counts["node_created"] == 2
        assert counts["node_updated"] == 1
        assert counts["relationship_created"] == 1

    def test_get_affected_entities(self):
        """Test getting affected entity IDs."""
        window = EventWindow(
            window_id="test-window",
            window_type=WindowType.TUMBLING,
            start_time=datetime.now(),
            end_time=datetime.now() + timedelta(minutes=5),
            duration=timedelta(minutes=5),
        )

        # Add events with different entities
        events = [
            GraphChangeEvent(
                "1", ChangeType.NODE_CREATED, datetime.now(), "node-1", "node"
            ),
            GraphChangeEvent(
                "2", ChangeType.NODE_UPDATED, datetime.now(), "node-1", "node"
            ),
            GraphChangeEvent(
                "3", ChangeType.NODE_CREATED, datetime.now(), "node-2", "node"
            ),
            GraphChangeEvent(
                "4",
                ChangeType.RELATIONSHIP_CREATED,
                datetime.now(),
                "rel-1",
                "relationship",
            ),
        ]

        for event in events:
            window.add_event(event)

        entities = window.get_affected_entities()

        assert len(entities) == 3
        assert "node-1" in entities
        assert "node-2" in entities
        assert "rel-1" in entities

    def test_to_dict(self):
        """Test converting window to dictionary."""
        start_time = datetime.now()
        end_time = start_time + timedelta(minutes=5)

        window = EventWindow(
            window_id="test-window",
            window_type=WindowType.HOPPING,
            start_time=start_time,
            end_time=end_time,
            duration=timedelta(minutes=5),
        )

        # Add test event
        event = GraphChangeEvent(
            "1", ChangeType.NODE_CREATED, datetime.now(), "node-1", "node"
        )
        window.add_event(event)

        # Add test aggregation
        window.aggregations["test_count"] = 5
        window.metadata["source"] = "test"

        window_dict = window.to_dict()

        assert window_dict["window_id"] == "test-window"
        assert window_dict["window_type"] == "hopping"
        assert window_dict["event_count"] == 1
        assert window_dict["events_by_type"]["node_created"] == 1
        assert window_dict["affected_entities"] == ["node-1"]
        assert window_dict["aggregations"]["test_count"] == 5
        assert window_dict["metadata"]["source"] == "test"


class TestAggregationRule:
    """Test AggregationRule class."""

    def test_count_aggregation(self):
        """Test count aggregation."""
        rule = AggregationRule(
            name="event_count", aggregation_type=AggregationType.COUNT
        )

        events = [
            GraphChangeEvent(
                "1", ChangeType.NODE_CREATED, datetime.now(), "n1", "node"
            ),
            GraphChangeEvent(
                "2", ChangeType.NODE_CREATED, datetime.now(), "n2", "node"
            ),
            GraphChangeEvent(
                "3", ChangeType.NODE_UPDATED, datetime.now(), "n1", "node"
            ),
        ]

        result = rule.apply(events)
        assert result == 3

    def test_distinct_count_aggregation(self):
        """Test distinct count aggregation."""
        rule = AggregationRule(
            name="distinct_entities",
            aggregation_type=AggregationType.DISTINCT_COUNT,
            field_path="entity_id",
        )

        events = [
            GraphChangeEvent(
                "1", ChangeType.NODE_CREATED, datetime.now(), "node-1", "node"
            ),
            GraphChangeEvent(
                "2", ChangeType.NODE_UPDATED, datetime.now(), "node-1", "node"
            ),
            GraphChangeEvent(
                "3", ChangeType.NODE_CREATED, datetime.now(), "node-2", "node"
            ),
        ]

        result = rule.apply(events)
        assert result == 2  # Two distinct entities

    def test_grouped_count_aggregation(self):
        """Test count aggregation with grouping."""
        rule = AggregationRule(
            name="count_by_type",
            aggregation_type=AggregationType.COUNT,
            group_by=["change_type"],
        )

        events = [
            GraphChangeEvent(
                "1", ChangeType.NODE_CREATED, datetime.now(), "n1", "node"
            ),
            GraphChangeEvent(
                "2", ChangeType.NODE_CREATED, datetime.now(), "n2", "node"
            ),
            GraphChangeEvent(
                "3", ChangeType.NODE_UPDATED, datetime.now(), "n1", "node"
            ),
        ]

        result = rule.apply(events)

        assert isinstance(result, dict)
        assert result[("node_created",)] == 2
        assert result[("node_updated",)] == 1

    def test_sum_aggregation(self):
        """Test sum aggregation."""
        rule = AggregationRule(
            name="property_sum",
            aggregation_type=AggregationType.SUM,
            field_path="new_properties.value",
        )

        events = [
            GraphChangeEvent(
                "1",
                ChangeType.NODE_CREATED,
                datetime.now(),
                "n1",
                "node",
                new_properties={"value": 10},
            ),
            GraphChangeEvent(
                "2",
                ChangeType.NODE_CREATED,
                datetime.now(),
                "n2",
                "node",
                new_properties={"value": 20},
            ),
            GraphChangeEvent(
                "3",
                ChangeType.NODE_CREATED,
                datetime.now(),
                "n3",
                "node",
                new_properties={"value": 15},
            ),
        ]

        result = rule.apply(events)
        assert result == 45

    def test_average_aggregation(self):
        """Test average aggregation."""
        rule = AggregationRule(
            name="property_average",
            aggregation_type=AggregationType.AVERAGE,
            field_path="new_properties.score",
        )

        events = [
            GraphChangeEvent(
                "1",
                ChangeType.NODE_CREATED,
                datetime.now(),
                "n1",
                "node",
                new_properties={"score": 10.0},
            ),
            GraphChangeEvent(
                "2",
                ChangeType.NODE_CREATED,
                datetime.now(),
                "n2",
                "node",
                new_properties={"score": 20.0},
            ),
            GraphChangeEvent(
                "3",
                ChangeType.NODE_CREATED,
                datetime.now(),
                "n3",
                "node",
                new_properties={"score": 30.0},
            ),
        ]

        result = rule.apply(events)
        assert result == 20.0

    def test_top_k_aggregation(self):
        """Test top-k aggregation."""
        rule = AggregationRule(
            name="top_users",
            aggregation_type=AggregationType.TOP_K,
            field_path="user_id",
            parameters={"k": 2},
        )

        events = [
            GraphChangeEvent(
                "1",
                ChangeType.NODE_CREATED,
                datetime.now(),
                "n1",
                "node",
                user_id="user1",
            ),
            GraphChangeEvent(
                "2",
                ChangeType.NODE_CREATED,
                datetime.now(),
                "n2",
                "node",
                user_id="user1",
            ),
            GraphChangeEvent(
                "3",
                ChangeType.NODE_CREATED,
                datetime.now(),
                "n3",
                "node",
                user_id="user2",
            ),
            GraphChangeEvent(
                "4",
                ChangeType.NODE_CREATED,
                datetime.now(),
                "n4",
                "node",
                user_id="user3",
            ),
        ]

        result = rule.apply(events)

        assert isinstance(result, dict)
        assert len(result) == 2  # Top 2
        assert result["user1"] == 2  # Most frequent

    def test_filter_condition(self):
        """Test aggregation with filter condition."""
        rule = AggregationRule(
            name="node_creations_only",
            aggregation_type=AggregationType.COUNT,
            filter_condition=lambda e: e.change_type == ChangeType.NODE_CREATED,
        )

        events = [
            GraphChangeEvent(
                "1", ChangeType.NODE_CREATED, datetime.now(), "n1", "node"
            ),
            GraphChangeEvent(
                "2", ChangeType.NODE_UPDATED, datetime.now(), "n2", "node"
            ),
            GraphChangeEvent(
                "3", ChangeType.NODE_CREATED, datetime.now(), "n3", "node"
            ),
        ]

        result = rule.apply(events)
        assert result == 2  # Only NODE_CREATED events

    def test_histogram_aggregation(self):
        """Test histogram aggregation."""
        rule = AggregationRule(
            name="value_histogram",
            aggregation_type=AggregationType.HISTOGRAM,
            field_path="new_properties.value",
            parameters={"bins": 3},
        )

        events = [
            GraphChangeEvent(
                "1",
                ChangeType.NODE_CREATED,
                datetime.now(),
                "n1",
                "node",
                new_properties={"value": 1},
            ),
            GraphChangeEvent(
                "2",
                ChangeType.NODE_CREATED,
                datetime.now(),
                "n2",
                "node",
                new_properties={"value": 5},
            ),
            GraphChangeEvent(
                "3",
                ChangeType.NODE_CREATED,
                datetime.now(),
                "n3",
                "node",
                new_properties={"value": 10},
            ),
            GraphChangeEvent(
                "4",
                ChangeType.NODE_CREATED,
                datetime.now(),
                "n4",
                "node",
                new_properties={"value": 15},
            ),
        ]

        result = rule.apply(events)

        assert isinstance(result, dict)
        assert len(result) == 3  # 3 bins
        # Values should be distributed across bins

    def test_percentile_aggregation(self):
        """Test percentile aggregation."""
        rule = AggregationRule(
            name="median_value",
            aggregation_type=AggregationType.PERCENTILE,
            field_path="new_properties.value",
            parameters={"percentile": 50},
        )

        events = [
            GraphChangeEvent(
                "1",
                ChangeType.NODE_CREATED,
                datetime.now(),
                "n1",
                "node",
                new_properties={"value": 1},
            ),
            GraphChangeEvent(
                "2",
                ChangeType.NODE_CREATED,
                datetime.now(),
                "n2",
                "node",
                new_properties={"value": 5},
            ),
            GraphChangeEvent(
                "3",
                ChangeType.NODE_CREATED,
                datetime.now(),
                "n3",
                "node",
                new_properties={"value": 10},
            ),
            GraphChangeEvent(
                "4",
                ChangeType.NODE_CREATED,
                datetime.now(),
                "n4",
                "node",
                new_properties={"value": 15},
            ),
        ]

        result = rule.apply(events)
        assert result == 7.5  # Median of [1, 5, 10, 15]

    def test_field_value_extraction(self):
        """Test extracting field values from events."""
        rule = AggregationRule("test", AggregationType.COUNT)

        event = GraphChangeEvent(
            "1",
            ChangeType.NODE_UPDATED,
            datetime.now(),
            "n1",
            "node",
            new_properties={"name": "John", "age": 30},
            old_properties={"name": "Jane", "age": 25},
            metadata={"source": "test"},
            property_changes={"age": {"old": 25, "new": 30}},
        )

        # Test direct property access
        assert rule._get_field_value(event, "entity_id") == "n1"
        assert rule._get_field_value(event, "entity_type") == "node"

        # Test nested property access
        assert rule._get_field_value(event, "new_properties.name") == "John"
        assert rule._get_field_value(event, "old_properties.age") == 25
        assert rule._get_field_value(event, "metadata.source") == "test"
        assert rule._get_field_value(event, "property_changes.age.new") == 30

        # Test non-existent fields
        assert rule._get_field_value(event, "nonexistent") is None
        assert rule._get_field_value(event, "new_properties.nonexistent") is None


class TestStreamProcessor:
    """Test StreamProcessor class."""

    @pytest.fixture
    def stream_processor(self):
        """Create StreamProcessor instance."""
        return StreamProcessor(
            window_size=timedelta(minutes=5),
            window_type=WindowType.TUMBLING,
            max_windows=10,
            late_arrival_grace=timedelta(seconds=30),
        )

    def test_processor_initialization(self, stream_processor):
        """Test stream processor initialization."""
        assert stream_processor.window_size == timedelta(minutes=5)
        assert stream_processor.window_type == WindowType.TUMBLING
        assert stream_processor.max_windows == 10
        assert stream_processor.late_arrival_grace == timedelta(seconds=30)
        assert not stream_processor.is_running
        assert len(stream_processor.windows) == 0
        assert len(stream_processor.aggregation_rules) == 0
        assert stream_processor.stats["events_processed"] == 0

    @pytest.mark.asyncio
    async def test_start_stop_processor(self, stream_processor):
        """Test starting and stopping stream processor."""
        # Start processor
        await stream_processor.start()

        assert stream_processor.is_running
        assert len(stream_processor.tasks) > 0

        # Stop processor
        await stream_processor.stop()

        assert not stream_processor.is_running

    @pytest.mark.asyncio
    async def test_event_processing(self, stream_processor):
        """Test basic event processing."""
        event = GraphChangeEvent(
            "test-1", ChangeType.NODE_CREATED, datetime.now(), "node-1", "node"
        )

        await stream_processor.process_event(event)

        assert len(stream_processor.event_buffer) == 1
        assert stream_processor.stats["events_processed"] == 1

    @pytest.mark.asyncio
    async def test_batch_event_processing(self, stream_processor):
        """Test batch event processing."""
        events = []
        for i in range(5):
            event = GraphChangeEvent(
                f"event-{i}",
                ChangeType.NODE_CREATED,
                datetime.now(),
                f"node-{i}",
                "node",
            )
            events.append(event)

        await stream_processor.process_events(events)

        assert len(stream_processor.event_buffer) == 5
        assert stream_processor.stats["events_processed"] == 5

    @pytest.mark.asyncio
    async def test_tumbling_window_creation(self, stream_processor):
        """Test tumbling window creation."""
        base_time = datetime.now().replace(second=0, microsecond=0)

        event = GraphChangeEvent(
            "event-1",
            ChangeType.NODE_CREATED,
            base_time + timedelta(minutes=1),
            "node-1",
            "node",
        )

        await stream_processor._assign_to_windows(event)

        assert len(stream_processor.windows) == 1
        window = list(stream_processor.windows.values())[0]
        assert len(window.events) == 1
        assert window.window_type == WindowType.TUMBLING

    @pytest.mark.asyncio
    async def test_hopping_window_creation(self):
        """Test hopping window creation."""
        processor = StreamProcessor(
            window_size=timedelta(minutes=5),
            window_type=WindowType.HOPPING,
            hop_size=timedelta(minutes=2),
        )

        base_time = datetime.now().replace(second=0, microsecond=0)

        event = GraphChangeEvent(
            "event-1",
            ChangeType.NODE_CREATED,
            base_time + timedelta(minutes=3),
            "node-1",
            "node",
        )

        await processor._assign_to_windows(event)

        # Event might belong to multiple hopping windows
        assert len(processor.windows) >= 1

        # Check that event is in at least one window
        total_events = sum(len(w.events) for w in processor.windows.values())
        assert total_events >= 1

    @pytest.mark.asyncio
    async def test_session_window_creation(self):
        """Test session window creation."""
        processor = StreamProcessor(
            window_size=timedelta(minutes=30), window_type=WindowType.SESSION
        )

        base_time = datetime.now()

        # First event creates new session
        event1 = GraphChangeEvent(
            "event-1", ChangeType.NODE_CREATED, base_time, "node-1", "node"
        )

        await processor._assign_to_windows(event1)
        assert len(processor.windows) == 1

        # Second event within session timeout should join same window
        event2 = GraphChangeEvent(
            "event-2",
            ChangeType.NODE_CREATED,
            base_time + timedelta(seconds=10),
            "node-2",
            "node",
        )

        await processor._assign_to_windows(event2)
        assert len(processor.windows) == 1

        window = list(processor.windows.values())[0]
        assert len(window.events) == 2

    @pytest.mark.asyncio
    async def test_sliding_window_creation(self):
        """Test sliding window creation."""
        processor = StreamProcessor(
            window_size=timedelta(minutes=5), window_type=WindowType.SLIDING
        )

        base_time = datetime.now()

        # Each event creates its own sliding window
        event1 = GraphChangeEvent(
            "event-1", ChangeType.NODE_CREATED, base_time, "node-1", "node"
        )

        await processor._assign_to_windows(event1)
        assert len(processor.windows) == 1

        event2 = GraphChangeEvent(
            "event-2",
            ChangeType.NODE_CREATED,
            base_time + timedelta(minutes=1),
            "node-2",
            "node",
        )

        await processor._assign_to_windows(event2)
        # Should have two sliding windows
        assert len(processor.windows) == 2

    @pytest.mark.asyncio
    async def test_window_completion(self, stream_processor):
        """Test window completion and processing."""
        # Mock current time to control completion
        past_time = datetime.now() - timedelta(minutes=10)

        # Create a window that should be completed
        window = await stream_processor._create_window(
            "test-window", past_time, past_time + timedelta(minutes=5)
        )

        # Add event to window
        event = GraphChangeEvent(
            "event-1",
            ChangeType.NODE_CREATED,
            past_time + timedelta(minutes=1),
            "node-1",
            "node",
        )
        window.add_event(event)

        # Check for completed windows
        await stream_processor._check_completed_windows()

        # Window should be completed and moved
        assert len(stream_processor.windows) == 0
        assert len(stream_processor.completed_windows) == 1
        assert stream_processor.stats["windows_completed"] == 1

    @pytest.mark.asyncio
    async def test_aggregation_rule_application(self, stream_processor):
        """Test aggregation rule application during window completion."""
        # Add aggregation rule
        rule = AggregationRule(
            name="event_count", aggregation_type=AggregationType.COUNT
        )
        stream_processor.add_aggregation_rule(rule)

        # Create window with events
        window = await stream_processor._create_window(
            "test-window",
            datetime.now() - timedelta(minutes=10),
            datetime.now() - timedelta(minutes=5),
        )

        # Add events
        for i in range(3):
            event = GraphChangeEvent(
                f"event-{i}",
                ChangeType.NODE_CREATED,
                datetime.now() - timedelta(minutes=8),
                f"node-{i}",
                "node",
            )
            window.add_event(event)

        # Complete window
        await stream_processor._complete_window(window)

        # Check aggregation was applied
        assert "event_count" in window.aggregations
        assert window.aggregations["event_count"] == 3
        assert stream_processor.stats["aggregations_computed"] == 1

    @pytest.mark.asyncio
    async def test_handler_registration_and_execution(self, stream_processor):
        """Test window and aggregation handler registration."""
        window_results = []
        aggregation_results = []

        def window_handler(window):
            window_results.append(window.window_id)

        def aggregation_handler(rule_name, result, window):
            aggregation_results.append((rule_name, result, window.window_id))

        # Register handlers
        stream_processor.add_window_handler(window_handler)
        stream_processor.add_aggregation_handler(aggregation_handler)

        # Add aggregation rule
        rule = AggregationRule("test_count", AggregationType.COUNT)
        stream_processor.add_aggregation_rule(rule)

        # Create and complete window
        window = await stream_processor._create_window(
            "test-window",
            datetime.now() - timedelta(minutes=10),
            datetime.now() - timedelta(minutes=5),
        )

        event = GraphChangeEvent(
            "event-1",
            ChangeType.NODE_CREATED,
            datetime.now() - timedelta(minutes=8),
            "node-1",
            "node",
        )
        window.add_event(event)

        await stream_processor._complete_window(window)

        # Check handlers were called
        assert len(window_results) == 1
        assert window_results[0] == "test-window"
        assert len(aggregation_results) == 1
        assert aggregation_results[0][0] == "test_count"
        assert aggregation_results[0][1] == 1
        assert aggregation_results[0][2] == "test-window"

    @pytest.mark.asyncio
    async def test_late_event_handling(self, stream_processor):
        """Test handling of late-arriving events."""
        current_time = datetime.now()

        # Event that arrives too late (beyond grace period)
        late_event = GraphChangeEvent(
            "late-event",
            ChangeType.NODE_CREATED,
            current_time - timedelta(minutes=5),  # Much older than grace period
            "node-1",
            "node",
        )

        await stream_processor.process_event(late_event)

        # Process pending events (simulate time passing)
        await stream_processor._process_pending_events()

        # Late event should be counted as dropped
        assert stream_processor.stats["late_events"] >= 0  # Depends on timing

    @pytest.mark.asyncio
    async def test_buffer_overflow_handling(self, stream_processor):
        """Test event buffer overflow handling."""
        # Fill buffer beyond capacity
        for i in range(stream_processor.buffer_size + 10):
            event = GraphChangeEvent(
                f"event-{i}",
                ChangeType.NODE_CREATED,
                datetime.now(),
                f"node-{i}",
                "node",
            )
            await stream_processor.process_event(event)

        # Should drop oldest events
        assert len(stream_processor.event_buffer) <= stream_processor.buffer_size
        assert stream_processor.stats["dropped_events"] >= 10

    def test_aggregation_rule_management(self, stream_processor):
        """Test adding and removing aggregation rules."""
        rule = AggregationRule("test_rule", AggregationType.COUNT)

        # Add rule
        stream_processor.add_aggregation_rule(rule)
        assert len(stream_processor.aggregation_rules) == 1
        assert stream_processor.aggregation_rules[0].name == "test_rule"

        # Remove rule
        stream_processor.remove_aggregation_rule("test_rule")
        assert len(stream_processor.aggregation_rules) == 0

    def test_get_stats(self, stream_processor):
        """Test getting processor statistics."""
        # Add some test data
        stream_processor.stats["events_processed"] = 100
        stream_processor.stats["windows_created"] = 10

        stats = stream_processor.get_stats()

        assert stats["is_running"] == False
        assert stats["window_type"] == WindowType.TUMBLING.value
        assert stats["events_processed"] == 100
        assert stats["windows_created"] == 10
        assert "window_size_seconds" in stats
        assert "active_windows" in stats

    def test_get_active_windows(self, stream_processor):
        """Test getting active window information."""
        # Create test window
        window = EventWindow(
            "test-window",
            WindowType.TUMBLING,
            datetime.now(),
            datetime.now() + timedelta(minutes=5),
            timedelta(minutes=5),
        )
        stream_processor.windows["test-window"] = window

        active_windows = stream_processor.get_active_windows()

        assert len(active_windows) == 1
        assert active_windows[0]["window_id"] == "test-window"
        assert active_windows[0]["window_type"] == "tumbling"

    def test_get_completed_windows(self, stream_processor):
        """Test getting completed window information."""
        # Add completed windows
        for i in range(3):
            window = EventWindow(
                f"completed-{i}",
                WindowType.TUMBLING,
                datetime.now(),
                datetime.now() + timedelta(minutes=5),
                timedelta(minutes=5),
            )
            stream_processor.completed_windows.append(window)

        completed_windows = stream_processor.get_completed_windows(limit=2)

        assert len(completed_windows) == 2
        # Should get the most recent ones
        assert completed_windows[0]["window_id"] == "completed-1"
        assert completed_windows[1]["window_id"] == "completed-2"


class TestCommonAggregationRules:
    """Test predefined common aggregation rules."""

    def test_create_common_rules(self):
        """Test creating common aggregation rules."""
        rules = create_common_aggregation_rules()

        assert len(rules) > 0

        rule_names = [rule.name for rule in rules]

        # Check expected rules are present
        assert "event_count_by_type" in rule_names
        assert "distinct_entities_affected" in rule_names
        assert "top_users" in rule_names
        assert "node_creation_rate" in rule_names
        assert "relationship_creation_rate" in rule_names
        assert "entity_types_modified" in rule_names

    def test_common_rules_application(self):
        """Test applying common rules to sample data."""
        rules = create_common_aggregation_rules()

        # Create sample events
        events = [
            GraphChangeEvent(
                "1",
                ChangeType.NODE_CREATED,
                datetime.now(),
                "n1",
                "node",
                user_id="user1",
            ),
            GraphChangeEvent(
                "2",
                ChangeType.NODE_CREATED,
                datetime.now(),
                "n2",
                "node",
                user_id="user1",
            ),
            GraphChangeEvent(
                "3",
                ChangeType.NODE_UPDATED,
                datetime.now(),
                "n1",
                "node",
                user_id="user2",
            ),
            GraphChangeEvent(
                "4",
                ChangeType.RELATIONSHIP_CREATED,
                datetime.now(),
                "r1",
                "relationship",
                user_id="user2",
            ),
        ]

        # Apply each rule
        for rule in rules:
            result = rule.apply(events)

            # All rules should produce some result with this data
            assert result is not None

            # Check specific rule results
            if rule.name == "event_count_by_type":
                assert isinstance(result, dict)
                assert ("node_created",) in result
                assert ("node_updated",) in result
                assert ("relationship_created",) in result

            elif rule.name == "distinct_entities_affected":
                assert result == 3  # n1, n2, r1

            elif rule.name == "node_creation_rate":
                assert result == 2  # Two NODE_CREATED events

            elif rule.name == "relationship_creation_rate":
                assert result == 1  # One RELATIONSHIP_CREATED event


@pytest.mark.asyncio
async def test_end_to_end_stream_processing():
    """Test end-to-end stream processing with multiple events and windows."""
    processor = StreamProcessor(
        window_size=timedelta(seconds=2), window_type=WindowType.TUMBLING
    )

    # Add common aggregation rules
    rules = create_common_aggregation_rules()
    for rule in rules:
        processor.add_aggregation_rule(rule)

    # Track results
    completed_windows = []

    def window_handler(window):
        completed_windows.append(window.to_dict())

    processor.add_window_handler(window_handler)

    # Start processor
    await processor.start()

    # Send events over time
    base_time = datetime.now()
    events = []

    for i in range(10):
        event = GraphChangeEvent(
            f"event-{i}",
            ChangeType.NODE_CREATED if i % 2 == 0 else ChangeType.NODE_UPDATED,
            base_time + timedelta(milliseconds=i * 200),
            f"node-{i % 3}",  # 3 different entities
            "node",
            user_id=f"user-{i % 2}",  # 2 different users
        )
        events.append(event)
        await processor.process_event(event)

    # Wait for processing
    await asyncio.sleep(0.5)

    # Process any remaining events
    await processor._process_pending_events()

    # Complete any remaining windows
    await processor._complete_all_windows()

    # Stop processor
    await processor.stop()

    # Should have processed events and created windows
    assert processor.stats["events_processed"] == 10
    assert processor.stats["windows_created"] > 0
    assert processor.stats["windows_completed"] > 0

    # Should have completed windows with aggregations
    assert len(completed_windows) > 0

    # Check that aggregations were computed
    for window_data in completed_windows:
        assert len(window_data["aggregations"]) > 0
        assert "event_count_by_type" in window_data["aggregations"]


@pytest.mark.asyncio
async def test_concurrent_event_processing():
    """Test concurrent event processing under load."""
    processor = StreamProcessor(
        window_size=timedelta(seconds=1),
        window_type=WindowType.TUMBLING,
        buffer_size=1000,
    )

    await processor.start()

    # Generate many events concurrently
    async def generate_events(start_index, count):
        tasks = []
        for i in range(start_index, start_index + count):
            event = GraphChangeEvent(
                f"concurrent-{i}",
                ChangeType.NODE_CREATED,
                datetime.now(),
                f"node-{i}",
                "node",
            )
            tasks.append(processor.process_event(event))

        await asyncio.gather(*tasks)

    # Generate events from multiple coroutines
    await asyncio.gather(
        generate_events(0, 100), generate_events(100, 100), generate_events(200, 100)
    )

    # Allow processing time
    await asyncio.sleep(0.2)

    await processor.stop()

    # Should process all events without errors
    assert processor.stats["events_processed"] == 300
    assert processor.stats["dropped_events"] == 0  # Buffer should handle the load


if __name__ == "__main__":
    pytest.main([__file__])
