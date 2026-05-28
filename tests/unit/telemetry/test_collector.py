"""
Comprehensive tests for TelemetryCollector - event collection with privacy controls.
"""

import asyncio
import pytest
import time
from datetime import datetime, timedelta
from unittest.mock import Mock, patch, AsyncMock
from typing import List, Dict, Any
import threading

from brain_researcher.services.telemetry.collector import (
    TelemetryCollector, EventBuffer, CollectorStats
)
from brain_researcher.services.telemetry.models import (
    TelemetryEvent, EventType, ServiceType, PrivacyLevel, TelemetryConfiguration
)


class TestEventBuffer:
    """Test the EventBuffer circular buffer implementation."""
    
    def test_buffer_initialization(self):
        """Test buffer initialization with default and custom sizes."""
        # Default size
        buffer = EventBuffer()
        assert buffer.max_size == 10000
        assert buffer.size() == 0
        assert buffer.dropped_count() == 0
        
        # Custom size
        buffer = EventBuffer(max_size=100)
        assert buffer.max_size == 100
    
    def test_append_and_size(self):
        """Test appending events and checking size."""
        buffer = EventBuffer(max_size=3)
        
        # Create test events
        events = [
            TelemetryEvent(id=f"evt_{i}", event_type=EventType.TOOL_INVOCATION, service=ServiceType.AGENT)
            for i in range(5)
        ]
        
        # Append events
        assert buffer.append(events[0]) is True
        assert buffer.size() == 1
        
        assert buffer.append(events[1]) is True
        assert buffer.size() == 2
        
        assert buffer.append(events[2]) is True
        assert buffer.size() == 3
        
        # Buffer is full, should drop events
        assert buffer.append(events[3]) is False
        assert buffer.size() == 3
        assert buffer.dropped_count() == 1
        
        assert buffer.append(events[4]) is False
        assert buffer.size() == 3
        assert buffer.dropped_count() == 2
    
    def test_flush_operations(self):
        """Test flushing events from buffer."""
        buffer = EventBuffer(max_size=5)
        
        # Add events
        events = [
            TelemetryEvent(id=f"evt_{i}", event_type=EventType.FEATURE_ACCESS, service=ServiceType.WEB_UI)
            for i in range(4)
        ]
        
        for event in events:
            buffer.append(event)
        
        # Flush partial
        flushed = buffer.flush(count=2)
        assert len(flushed) == 2
        assert buffer.size() == 2
        assert flushed[0].id == "evt_0"
        assert flushed[1].id == "evt_1"
        
        # Flush all remaining
        flushed = buffer.flush()
        assert len(flushed) == 2
        assert buffer.size() == 0
        assert flushed[0].id == "evt_2"
        assert flushed[1].id == "evt_3"
    
    def test_thread_safety(self):
        """Test thread-safe operations on buffer."""
        buffer = EventBuffer(max_size=1000)
        errors = []
        
        def writer_thread(thread_id: int):
            try:
                for i in range(100):
                    event = TelemetryEvent(
                        id=f"evt_{thread_id}_{i}",
                        event_type=EventType.PAGE_VIEW,
                        service=ServiceType.WEB_UI
                    )
                    buffer.append(event)
            except Exception as e:
                errors.append(e)
        
        def reader_thread():
            try:
                while buffer.size() > 0 or threading.active_count() > 2:  # Main + reader threads
                    if buffer.size() > 50:
                        buffer.flush(count=10)
                    time.sleep(0.001)
            except Exception as e:
                errors.append(e)
        
        # Start multiple writer threads and one reader thread
        threads = [
            threading.Thread(target=writer_thread, args=(i,))
            for i in range(3)
        ]
        threads.append(threading.Thread(target=reader_thread))
        
        for thread in threads:
            thread.start()
        
        for thread in threads:
            thread.join(timeout=5)
        
        assert not errors, f"Thread safety errors: {errors}"


class TestCollectorStats:
    """Test the CollectorStats data structure."""
    
    def test_stats_initialization(self):
        """Test stats initialization with default values."""
        stats = CollectorStats()
        
        assert stats.events_collected == 0
        assert stats.events_processed == 0
        assert stats.events_dropped == 0
        assert stats.events_anonymized == 0
        assert stats.last_flush_time is None
        assert stats.processing_errors == 0
        assert stats.avg_processing_time_ms == 0.0


class TestTelemetryCollector:
    """Test the main TelemetryCollector class."""
    
    @pytest.fixture
    def config(self):
        """Test configuration."""
        return TelemetryConfiguration(
            collection_enabled=True,
            sampling_rate=1.0,
            batch_size=10,
            flush_interval_seconds=1,
            anonymization_enabled=True,
            max_events_per_second=100,
            queue_max_size=1000
        )
    
    @pytest.fixture
    def collector(self, config):
        """Create test collector."""
        return TelemetryCollector(config)
    
    def test_collector_initialization(self, config):
        """Test collector initialization."""
        collector = TelemetryCollector(config)
        
        assert collector.config == config
        assert isinstance(collector.stats, CollectorStats)
        assert collector._event_buffer.max_size == config.queue_max_size
        assert len(collector._processing_handlers) == 0
        assert collector._flush_task is None
    
    def test_collect_basic_event(self, collector):
        """Test collecting a basic event."""
        event_id = collector.collect(
            event_type=EventType.TOOL_INVOCATION,
            service=ServiceType.AGENT,
            feature_name="test_tool",
            action="execute",
            user_id="test_user_123",
            duration_ms=500,
            success=True
        )
        
        assert event_id is not None
        assert event_id.startswith("evt_")
        assert collector.stats.events_collected == 1
        assert collector._event_buffer.size() == 1
    
    def test_collect_disabled(self):
        """Test collection when disabled."""
        config = TelemetryConfiguration(collection_enabled=False)
        collector = TelemetryCollector(config)
        
        event_id = collector.collect(
            event_type=EventType.FEATURE_ACCESS,
            service=ServiceType.WEB_UI
        )
        
        assert event_id is None
        assert collector.stats.events_collected == 0
        assert collector._event_buffer.size() == 0
    
    def test_sampling_rate(self):
        """Test sampling rate functionality."""
        config = TelemetryConfiguration(sampling_rate=0.0)  # No events should be collected
        collector = TelemetryCollector(config)
        
        # Try to collect multiple events
        collected_events = 0
        for i in range(100):
            event_id = collector.collect(
                event_type=EventType.PAGE_VIEW,
                service=ServiceType.WEB_UI
            )
            if event_id is not None:
                collected_events += 1
        
        assert collected_events == 0
        assert collector.stats.events_collected == 0
    
    def test_rate_limiting(self, collector):
        """Test rate limiting functionality."""
        # Collect events rapidly
        successful_collections = 0
        for i in range(150):  # More than max_events_per_second (100)
            event_id = collector.collect(
                event_type=EventType.TOOL_INVOCATION,
                service=ServiceType.AGENT
            )
            if event_id is not None:
                successful_collections += 1
        
        # Some events should be dropped due to rate limiting
        assert successful_collections <= 100
        assert collector.stats.events_dropped > 0
    
    def test_anonymization(self, collector):
        """Test event anonymization."""
        event_id = collector.collect(
            event_type=EventType.PAGE_VIEW,
            service=ServiceType.WEB_UI,
            user_id="real_user_id_123",
            metadata={"ip_address": "192.168.1.100", "user_agent": "Mozilla/5.0"}
        )
        
        assert event_id is not None
        assert collector.stats.events_anonymized == 1
        
        # Check that the event was anonymized
        events = collector._event_buffer.flush()
        assert len(events) == 1
        event = events[0]
        
        assert event.anonymized is True
        assert event.user_id != "real_user_id_123"
        assert len(event.user_id) == 32  # Hashed user ID length
        assert "ip_address" not in event.metadata
        assert event.ip_hash is not None
        assert event.user_agent_hash is not None
    
    def test_convenience_methods(self, collector):
        """Test convenience methods for common event types."""
        # Tool usage
        tool_event_id = collector.collect_tool_usage(
            tool_name="fmri_analysis",
            action="execute",
            duration_ms=2000,
            success=True
        )
        
        # Feature usage
        feature_event_id = collector.collect_feature_usage(
            feature_name="dataset_explorer",
            action="open",
            service=ServiceType.WEB_UI
        )
        
        # Page view
        page_event_id = collector.collect_page_view(
            page_path="/dashboard",
            referrer="https://example.com"
        )
        
        assert tool_event_id is not None
        assert feature_event_id is not None
        assert page_event_id is not None
        assert collector.stats.events_collected == 3
    
    def test_privacy_controls(self, collector):
        """Test privacy control features."""
        # Test PII detection and removal
        event_id = collector.collect(
            event_type=EventType.FEATURE_ACCESS,
            service=ServiceType.AGENT,
            parameters={
                "email": "user@example.com",
                "phone": "123-456-7890",
                "valid_param": "some_value"
            },
            privacy_level=PrivacyLevel.AGGREGATE_ONLY
        )
        
        assert event_id is not None
        
        events = collector._event_buffer.flush()
        event = events[0]
        
        # Check that PII was removed/hashed
        assert "email" not in event.parameters
        assert "phone" not in event.parameters
        assert "email_hash" in event.parameters
        assert "phone_hash" in event.parameters
        assert event.parameters["valid_param"] == "some_value"
    
    def test_session_tracking(self, collector):
        """Test session tracking functionality."""
        user_id = "test_user_123"
        
        # Collect multiple events for same user
        event_ids = []
        for i in range(5):
            event_id = collector.collect(
                event_type=EventType.FEATURE_ACCESS,
                service=ServiceType.WEB_UI,
                user_id=user_id,
                feature_name=f"feature_{i}"
            )
            event_ids.append(event_id)
        
        # All events should have the same session ID
        events = collector._event_buffer.flush()
        session_ids = [e.session_id for e in events]
        
        assert len(set(session_ids)) == 1  # All same session ID
        assert all(sid.startswith("user_") for sid in session_ids)
    
    def test_error_handling(self, collector):
        """Test error handling in event collection."""
        # Test with invalid parameters that might cause exceptions
        event_id = collector.collect(
            event_type=EventType.TOOL_ERROR,
            service=ServiceType.AGENT,
            error_message="Test error message",
            success=False,
            duration_ms=-100  # Invalid duration
        )
        
        # Should still collect event despite invalid duration
        assert event_id is not None or collector.stats.processing_errors > 0
    
    def test_processing_handlers(self, collector):
        """Test processing handler registration and execution."""
        processed_events = []
        
        def test_handler(events: List[TelemetryEvent]):
            processed_events.extend(events)
        
        # Add handler
        collector.add_processing_handler(test_handler)
        assert len(collector._processing_handlers) == 1
        
        # Collect events
        for i in range(5):
            collector.collect(
                event_type=EventType.PAGE_VIEW,
                service=ServiceType.WEB_UI,
                feature_name=f"page_{i}"
            )
        
        # Force flush
        collector._flush_events(force=True)
        
        # Check that handler was called
        assert len(processed_events) == 5
        assert all(isinstance(e, TelemetryEvent) for e in processed_events)
    
    @pytest.mark.asyncio
    async def test_async_handler(self, collector):
        """Test async processing handlers."""
        processed_events = []
        
        async def async_handler(events: List[TelemetryEvent]):
            await asyncio.sleep(0.01)  # Simulate async work
            processed_events.extend(events)
        
        collector.add_processing_handler(async_handler)
        
        # Collect events
        for i in range(3):
            collector.collect(
                event_type=EventType.ANALYSIS_COMPLETE,
                service=ServiceType.AGENT
            )
        
        # Force flush
        await collector._flush_events(force=True)
        
        assert len(processed_events) == 3
    
    def test_get_stats(self, collector):
        """Test statistics reporting."""
        # Collect some events
        for i in range(10):
            collector.collect(
                event_type=EventType.TOOL_INVOCATION,
                service=ServiceType.AGENT
            )
        
        stats = collector.get_stats()
        
        assert isinstance(stats, dict)
        assert stats["events_collected"] == 10
        assert stats["buffer_size"] == 10
        assert stats["processing_errors"] == 0
        assert "config" in stats
        assert stats["config"]["collection_enabled"] is True
    
    @pytest.mark.asyncio
    async def test_lifecycle_management(self, collector):
        """Test collector lifecycle (start/stop)."""
        # Start collector
        await collector.start()
        assert collector._flush_task is not None
        
        # Collect some events
        for i in range(5):
            collector.collect(
                event_type=EventType.SESSION_START,
                service=ServiceType.WEB_UI
            )
        
        # Stop collector
        await collector.stop()
        assert collector._flush_task.done() or collector._flush_task.cancelled()
    
    @pytest.mark.asyncio
    async def test_background_flushing(self, config):
        """Test background flushing functionality."""
        config.flush_interval_seconds = 0.1  # Very short interval for testing
        collector = TelemetryCollector(config)
        
        processed_events = []
        
        def handler(events: List[TelemetryEvent]):
            processed_events.extend(events)
        
        collector.add_processing_handler(handler)
        
        # Start background processing
        await collector.start()
        
        # Collect events
        for i in range(5):
            collector.collect(
                event_type=EventType.FEATURE_INTERACTION,
                service=ServiceType.WEB_UI
            )
        
        # Wait for background flush
        await asyncio.sleep(0.2)
        
        # Stop collector
        await collector.stop()
        
        # Events should have been processed by background flush
        assert len(processed_events) >= 5
    
    def test_memory_management(self, collector):
        """Test memory management with large numbers of events."""
        # Test with many events to check for memory leaks
        initial_buffer_size = collector._event_buffer.size()
        
        # Collect many events
        for i in range(2000):
            collector.collect(
                event_type=EventType.TOOL_INVOCATION,
                service=ServiceType.AGENT,
                feature_name=f"tool_{i % 10}"
            )
        
        # Should not exceed queue max size due to buffer management
        assert collector._event_buffer.size() <= collector.config.queue_max_size
        
        # Check that some events were dropped due to buffer limits
        if collector._event_buffer.size() == collector.config.queue_max_size:
            assert collector._event_buffer.dropped_count() > 0
    
    def test_concurrent_collection(self, collector):
        """Test concurrent event collection from multiple threads."""
        def collect_events(thread_id: int, count: int):
            for i in range(count):
                collector.collect(
                    event_type=EventType.FEATURE_ACCESS,
                    service=ServiceType.AGENT,
                    feature_name=f"thread_{thread_id}_feature_{i}",
                    user_id=f"user_{thread_id}"
                )
        
        # Start multiple threads
        threads = []
        events_per_thread = 50
        num_threads = 5
        
        for thread_id in range(num_threads):
            thread = threading.Thread(
                target=collect_events,
                args=(thread_id, events_per_thread)
            )
            threads.append(thread)
            thread.start()
        
        # Wait for all threads to complete
        for thread in threads:
            thread.join(timeout=10)
        
        # Check that all events were collected (within rate limits)
        total_expected = num_threads * events_per_thread
        total_collected = collector.stats.events_collected + collector.stats.events_dropped
        
        assert total_collected <= total_expected
        assert collector.stats.events_collected > 0


@pytest.mark.performance
class TestCollectorPerformance:
    """Performance tests for TelemetryCollector."""
    
    def test_collection_throughput(self):
        """Test event collection throughput."""
        config = TelemetryConfiguration(
            sampling_rate=1.0,
            max_events_per_second=10000,
            anonymization_enabled=False  # Disable for pure throughput test
        )
        collector = TelemetryCollector(config)
        
        start_time = time.time()
        num_events = 1000
        
        for i in range(num_events):
            collector.collect(
                event_type=EventType.TOOL_INVOCATION,
                service=ServiceType.AGENT,
                feature_name="performance_test"
            )
        
        end_time = time.time()
        duration = end_time - start_time
        throughput = num_events / duration
        
        # Should be able to collect at least 1000 events/second
        assert throughput > 1000, f"Low throughput: {throughput:.2f} events/sec"
        assert collector.stats.events_collected == num_events
    
    def test_anonymization_performance(self):
        """Test performance impact of anonymization."""
        config = TelemetryConfiguration(anonymization_enabled=True)
        collector = TelemetryCollector(config)
        
        start_time = time.time()
        
        for i in range(500):
            collector.collect(
                event_type=EventType.PAGE_VIEW,
                service=ServiceType.WEB_UI,
                user_id=f"user_{i}",
                metadata={
                    "ip_address": f"192.168.1.{i % 255}",
                    "user_agent": "Mozilla/5.0 (Test Browser)"
                },
                parameters={
                    "page": f"/test/page/{i}",
                    "referrer": f"https://example.com/page/{i-1}"
                }
            )
        
        end_time = time.time()
        duration = end_time - start_time
        
        # Anonymization should not severely impact performance
        assert duration < 2.0, f"Anonymization too slow: {duration:.2f}s for 500 events"
        assert collector.stats.events_anonymized == 500
    
    def test_memory_usage_stability(self):
        """Test memory usage remains stable over time."""
        config = TelemetryConfiguration(queue_max_size=1000)
        collector = TelemetryCollector(config)
        
        # Handler to consume events
        def consuming_handler(events):
            pass  # Just consume the events
        
        collector.add_processing_handler(consuming_handler)
        
        # Collect many events with periodic flushing
        for batch in range(10):
            for i in range(100):
                collector.collect(
                    event_type=EventType.TOOL_INVOCATION,
                    service=ServiceType.AGENT
                )
            
            # Force flush to prevent buffer overflow
            collector._flush_events(force=True)
        
        # Buffer should be manageable size
        assert collector._event_buffer.size() <= 1000
        assert collector.stats.events_processed >= 900  # Most events processed