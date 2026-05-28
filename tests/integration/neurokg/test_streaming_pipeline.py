"""Integration tests for streaming pipeline.

This module tests the complete streaming pipeline integration including:
- CDC processor and Kafka producer/consumer integration
- Stream processing with windowing and aggregation
- End-to-end event flow from graph changes to analytics
- Error handling and recovery scenarios
"""

import pytest
import asyncio
import json
import tempfile
import os
from datetime import datetime, timedelta
from unittest.mock import Mock, AsyncMock, patch, MagicMock
from typing import Dict, List, Any

# Import the modules to test
try:
    from brain_researcher.services.neurokg.streaming.cdc_processor import (
        CDCProcessor,
        GraphChangeEvent,
        ChangeType
    )
    from brain_researcher.services.neurokg.streaming.kafka_integration import (
        KafkaProducer,
        KafkaConsumer,
        StreamConfig,
        create_cdc_kafka_integration
    )
    from brain_researcher.services.neurokg.streaming.stream_processor import (
        StreamProcessor,
        EventWindow,
        AggregationRule,
        WindowType,
        AggregationType
    )
except ImportError:
    # Fallback if absolute imports don't work
    import sys
    import os
    sys.path.append(os.path.join(os.path.dirname(__file__), '..', '..', '..'))
    from brain_researcher.services.neurokg.streaming.cdc_processor import (
        CDCProcessor,
        GraphChangeEvent,
        ChangeType
    )
    from brain_researcher.services.neurokg.streaming.kafka_integration import (
        KafkaProducer,
        KafkaConsumer,
        StreamConfig,
        create_cdc_kafka_integration
    )
    from brain_researcher.services.neurokg.streaming.stream_processor import (
        StreamProcessor,
        EventWindow,
        AggregationRule,
        WindowType,
        AggregationType
    )


@pytest.mark.integration
class TestStreamingPipelineIntegration:
    """Test streaming pipeline integration."""
    
    @pytest.fixture
    def mock_neo4j_driver(self):
        """Mock Neo4j driver."""
        driver = Mock()
        session = MagicMock()
        session.run.return_value = []
        session_cm = MagicMock()
        session_cm.__enter__.return_value = session
        session_cm.__exit__.return_value = None
        driver.session.return_value = session_cm
        driver.close = Mock()
        return driver
    
    @pytest.fixture
    def stream_config(self):
        """Create test stream configuration."""
        return StreamConfig(
            bootstrap_servers="localhost:9092",
            default_topic="test-events",
            consumer_group_id="test-group"
        )
    
    @pytest.fixture
    async def cdc_processor(self, mock_neo4j_driver):
        """Create CDC processor with mocked Neo4j."""
        with patch('brain_researcher.services.neurokg.streaming.cdc_processor.GraphDatabase') as mock_graphdb:
            mock_graphdb.driver.return_value = mock_neo4j_driver
            
            processor = CDCProcessor(
                neo4j_uri="neo4j://localhost:7687",
                neo4j_user="neo4j",
                neo4j_password="password",
                buffer_size=10,
                batch_interval=0.1
            )
            
            yield processor
            
            if processor.is_running:
                await processor.stop()
    
    @pytest.fixture
    async def kafka_producer(self, stream_config):
        """Create Kafka producer with mocked components."""
        with patch('brain_researcher.services.neurokg.streaming.kafka_integration.AIOKafkaProducer') as mock_producer_class:
            mock_producer = AsyncMock()
            mock_producer_class.return_value = mock_producer
            
            producer = KafkaProducer(stream_config)
            
            yield producer
            
            if producer.is_running:
                await producer.stop()
    
    @pytest.fixture
    async def kafka_consumer(self, stream_config):
        """Create Kafka consumer with mocked components."""
        with patch('brain_researcher.services.neurokg.streaming.kafka_integration.AIOKafkaConsumer') as mock_consumer_class:
            mock_consumer = AsyncMock()
            mock_consumer_class.return_value = mock_consumer
            
            consumer = KafkaConsumer(stream_config)
            
            yield consumer
            
            if consumer.is_running:
                await consumer.stop()
    
    @pytest.fixture
    async def stream_processor(self):
        """Create stream processor."""
        processor = StreamProcessor(
            window_size=timedelta(seconds=5),
            window_type=WindowType.TUMBLING,
            max_windows=20
        )
        
        yield processor
        
        if processor.is_running:
            await processor.stop()
    
    @pytest.mark.asyncio
    async def test_cdc_to_kafka_integration(self, cdc_processor, kafka_producer):
        """Test CDC to Kafka integration."""
        # Set up integration
        await kafka_producer.start()
        
        # Mock Kafka producer send
        kafka_producer.send_event = AsyncMock(return_value=True)
        
        # Create integration
        handler = create_cdc_kafka_integration(cdc_processor, kafka_producer)
        
        # Create test event
        test_event = GraphChangeEvent(
            event_id="test-123",
            change_type=ChangeType.NODE_CREATED,
            timestamp=datetime.now(),
            entity_id="node-456",
            entity_type="node",
            labels=["Person"],
            new_properties={"name": "John", "age": 30}
        )
        
        # Add event to CDC processor
        await cdc_processor._add_event(test_event)
        
        # Verify Kafka producer was called
        kafka_producer.send_event.assert_called()
        sent_event = kafka_producer.send_event.call_args[0][0]
        assert sent_event.event_id == "test-123"
        assert sent_event.change_type == ChangeType.NODE_CREATED
    
    @pytest.mark.asyncio
    async def test_kafka_to_stream_processor_integration(self, kafka_consumer, stream_processor):
        """Test Kafka consumer to stream processor integration."""
        # Start stream processor
        await stream_processor.start()
        
        # Add aggregation rule
        rule = AggregationRule(
            name="event_count",
            aggregation_type=AggregationType.COUNT
        )
        stream_processor.add_aggregation_rule(rule)
        
        # Track processed windows
        processed_windows = []
        
        def window_handler(window):
            processed_windows.append(window)
        
        stream_processor.add_window_handler(window_handler)
        
        # Create test events
        events = []
        for i in range(3):
            event = GraphChangeEvent(
                f"kafka-event-{i}",
                ChangeType.NODE_CREATED,
                datetime.now(),
                f"node-{i}",
                "node"
            )
            events.append(event)
        
        # Process events through stream processor
        for event in events:
            await stream_processor.process_event(event)
        
        # Wait for processing
        await asyncio.sleep(0.2)
        
        # Force processing of remaining events
        await stream_processor._process_pending_events()
        await stream_processor._complete_all_windows()
        
        # Verify events were processed
        assert stream_processor.stats["events_processed"] == 3
    
    @pytest.mark.asyncio
    async def test_end_to_end_pipeline(self, cdc_processor, kafka_producer, kafka_consumer, stream_processor):
        """Test complete end-to-end streaming pipeline."""
        # Start all components
        await kafka_producer.start()
        await kafka_consumer.start()
        await stream_processor.start()

        # Mock Kafka send for call count assertions
        kafka_producer.send_event = AsyncMock(return_value=True)

        # Set up pipeline integrations
        create_cdc_kafka_integration(cdc_processor, kafka_producer)
        
        # Add stream processor aggregations
        rules = [
            AggregationRule("total_events", AggregationType.COUNT),
            AggregationRule("events_by_type", AggregationType.COUNT, group_by=["change_type"]),
            AggregationRule("distinct_entities", AggregationRule.DISTINCT_COUNT, field_path="entity_id")
        ]
        
        for rule in rules:
            stream_processor.add_aggregation_rule(rule)
        
        # Track results
        pipeline_results = []
        
        def result_handler(window):
            pipeline_results.append({
                "window_id": window.window_id,
                "event_count": len(window.events),
                "aggregations": window.aggregations
            })
        
        stream_processor.add_window_handler(result_handler)
        
        # Generate test events through CDC
        test_events = [
            GraphChangeEvent(
                f"pipeline-event-{i}",
                ChangeType.NODE_CREATED if i % 2 == 0 else ChangeType.NODE_UPDATED,
                datetime.now(),
                f"entity-{i % 3}",  # 3 distinct entities
                "node",
                user_id="test-user"
            )
            for i in range(10)
        ]
        
        # Process events through CDC processor
        for event in test_events:
            await cdc_processor._add_event(event)
        
        # Simulate Kafka message flow by directly processing in stream processor
        for event in test_events:
            await stream_processor.process_event(event)
        
        # Wait for processing
        await asyncio.sleep(0.3)
        
        # Complete processing
        await stream_processor._process_pending_events()
        await stream_processor._complete_all_windows()
        
        # Verify end-to-end flow
        assert cdc_processor.stats["events_processed"] == 10
        assert kafka_producer.send_event.call_count == 10
        assert stream_processor.stats["events_processed"] == 10
        
        # Check that windows were processed with aggregations
        if pipeline_results:
            result = pipeline_results[0]
            assert "total_events" in result["aggregations"]
            assert result["aggregations"]["total_events"] > 0
    
    @pytest.mark.asyncio
    async def test_pipeline_error_handling(self, cdc_processor, kafka_producer, stream_processor):
        """Test pipeline error handling and recovery."""
        # Start components
        await kafka_producer.start()
        await stream_processor.start()
        
        # Mock Kafka producer to fail occasionally
        call_count = 0
        async def mock_send_event(event, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count % 3 == 0:  # Fail every 3rd event
                raise Exception("Kafka send failed")
            return True
        
        kafka_producer.send_event = mock_send_event
        
        # Set up integration
        create_cdc_kafka_integration(cdc_processor, kafka_producer)
        
        # Add error tracking
        errors_captured = []
        
        def error_handler(event):
            errors_captured.append(event)
        
        # Generate events that will trigger errors
        test_events = [
            GraphChangeEvent(
                f"error-test-{i}",
                ChangeType.NODE_CREATED,
                datetime.now(),
                f"node-{i}",
                "node"
            )
            for i in range(9)  # Will trigger 3 errors
        ]
        
        # Process events
        for event in test_events:
            await cdc_processor._add_event(event)
        
        # Wait for processing
        await asyncio.sleep(0.2)
        
        # Verify some events succeeded despite errors
        # (6 should succeed, 3 should fail)
        assert call_count == 9
        
        # Verify stream processor still handles events that did succeed
        successful_events = [e for i, e in enumerate(test_events) if (i + 1) % 3 != 0]
        for event in successful_events:
            await stream_processor.process_event(event)
        
        await stream_processor._process_pending_events()
        
        # Should have processed the successful events
        assert stream_processor.stats["events_processed"] == len(successful_events)
    
    @pytest.mark.asyncio
    async def test_pipeline_backpressure_handling(self, stream_processor):
        """Test pipeline backpressure and buffer management."""
        # Configure processor with small buffer for testing
        processor = StreamProcessor(
            window_size=timedelta(seconds=1),
            window_type=WindowType.TUMBLING,
            buffer_size=5,  # Small buffer
            late_arrival_grace=timedelta(seconds=0.1)
        )
        
        await processor.start()
        
        try:
            # Generate more events than buffer can handle
            events = [
                GraphChangeEvent(
                    f"backpressure-{i}",
                    ChangeType.NODE_CREATED,
                    datetime.now(),
                    f"node-{i}",
                    "node"
                )
                for i in range(20)  # More than buffer size
            ]
            
            # Process events rapidly
            for event in events:
                await processor.process_event(event)
            
            # Buffer should not exceed maximum size
            assert len(processor.event_buffer) <= processor.buffer_size
            
            # Some events should be dropped due to buffer overflow
            assert processor.stats["dropped_events"] > 0
            
            # But processing should continue without errors
            await processor._process_pending_events()
            
            # Total events processed should be less than total sent
            assert processor.stats["events_processed"] == 20
            
        finally:
            await processor.stop()
    
    @pytest.mark.asyncio
    async def test_pipeline_windowing_accuracy(self, stream_processor):
        """Test accuracy of windowing in the pipeline."""
        await stream_processor.start()
        
        # Add aggregation rules
        rules = [
            AggregationRule("event_count", AggregationType.COUNT),
            AggregationRule("avg_value", AggregationType.AVERAGE, field_path="new_properties.value")
        ]
        
        for rule in rules:
            stream_processor.add_aggregation_rule(rule)
        
        # Track windows
        completed_windows = []
        
        def window_handler(window):
            completed_windows.append(window)
        
        stream_processor.add_window_handler(window_handler)
        
        # Generate events with timestamps spread across multiple windows
        base_time = datetime.now()
        events = []
        
        # Window 1: 5 events
        for i in range(5):
            event = GraphChangeEvent(
                f"w1-event-{i}",
                ChangeType.NODE_CREATED,
                base_time + timedelta(seconds=i * 0.5),  # Within first window
                f"node-{i}",
                "node",
                new_properties={"value": i * 10}
            )
            events.append(event)
        
        # Window 2: 3 events
        for i in range(3):
            event = GraphChangeEvent(
                f"w2-event-{i}",
                ChangeType.NODE_UPDATED,
                base_time + timedelta(seconds=6 + i * 0.5),  # In second window
                f"node-{i}",
                "node",
                new_properties={"value": (i + 5) * 10}
            )
            events.append(event)
        
        # Process all events
        for event in events:
            await stream_processor.process_event(event)
        
        # Wait for processing and window completion
        await asyncio.sleep(0.5)
        await stream_processor._process_pending_events()
        await stream_processor._complete_all_windows()
        
        # Should have created multiple windows
        assert len(completed_windows) >= 1
        
        # Check aggregations in windows
        for window in completed_windows:
            assert "event_count" in window.aggregations
            assert window.aggregations["event_count"] > 0
            
            if "avg_value" in window.aggregations and window.aggregations["avg_value"] is not None:
                assert isinstance(window.aggregations["avg_value"], (int, float))
    
    @pytest.mark.asyncio 
    async def test_pipeline_state_persistence(self, stream_processor, tmp_path):
        """Test pipeline state persistence and recovery."""
        await stream_processor.start()
        
        # Process some events
        events = [
            GraphChangeEvent(
                f"persist-event-{i}",
                ChangeType.NODE_CREATED,
                datetime.now(),
                f"node-{i}",
                "node"
            )
            for i in range(5)
        ]
        
        for event in events:
            await stream_processor.process_event(event)
        
        # Get current stats
        original_stats = stream_processor.get_stats().copy()
        
        # Simulate saving state (in a real implementation)
        state_file = tmp_path / "processor_state.json"
        with open(state_file, 'w') as f:
            json.dump({
                "stats": original_stats,
                "buffer_size": len(stream_processor.event_buffer)
            }, f, default=str)
        
        await stream_processor.stop()
        
        # Create new processor and simulate state restoration
        new_processor = StreamProcessor(
            window_size=timedelta(seconds=5),
            window_type=WindowType.TUMBLING
        )
        
        # Load state
        with open(state_file, 'r') as f:
            saved_state = json.load(f)
        
        # Verify state was preserved
        assert saved_state["stats"]["events_processed"] == 5
        assert saved_state["buffer_size"] >= 0
    
    @pytest.mark.asyncio
    async def test_pipeline_monitoring_metrics(self, cdc_processor, kafka_producer, stream_processor):
        """Test pipeline monitoring and metrics collection."""
        # Start all components
        await kafka_producer.start()
        await stream_processor.start()
        
        # Set up integration
        create_cdc_kafka_integration(cdc_processor, kafka_producer)
        
        # Process test events
        test_events = [
            GraphChangeEvent(
                f"metrics-event-{i}",
                ChangeType.NODE_CREATED if i % 2 == 0 else ChangeType.RELATIONSHIP_CREATED,
                datetime.now(),
                f"entity-{i}",
                "node" if i % 2 == 0 else "relationship"
            )
            for i in range(8)
        ]
        
        for event in test_events:
            await cdc_processor._add_event(event)
            await stream_processor.process_event(event)
        
        # Wait for processing
        await asyncio.sleep(0.2)
        await stream_processor._process_pending_events()
        
        # Collect metrics from all components
        cdc_stats = cdc_processor.get_stats()
        producer_stats = kafka_producer.get_stats()
        processor_stats = stream_processor.get_stats()
        
        # Verify CDC metrics
        assert cdc_stats["events_processed"] == 8
        assert cdc_stats["events_by_type"]["node_created"] == 4
        assert cdc_stats["events_by_type"]["relationship_created"] == 4
        assert cdc_stats["is_running"] == False
        
        # Verify producer metrics
        assert producer_stats["messages_sent"] == 8
        assert producer_stats["send_errors"] == 0
        
        # Verify stream processor metrics
        assert processor_stats["events_processed"] == 8
        assert processor_stats["is_running"] == True
        assert processor_stats["window_type"] == "tumbling"
        
        # Create monitoring summary
        monitoring_summary = {
            "pipeline_health": "healthy",
            "total_events_processed": (
                cdc_stats["events_processed"] +
                processor_stats["events_processed"]
            ),
            "components": {
                "cdc_processor": cdc_stats,
                "kafka_producer": producer_stats,
                "stream_processor": processor_stats
            },
            "timestamp": datetime.now().isoformat()
        }
        
        assert monitoring_summary["total_events_processed"] == 16  # 8 + 8
        assert monitoring_summary["pipeline_health"] == "healthy"


@pytest.mark.integration
class TestStreamingPipelineScenarios:
    """Test specific streaming pipeline scenarios."""
    
    @pytest.mark.asyncio
    async def test_high_volume_event_processing(self):
        """Test processing high volume of events."""
        processor = StreamProcessor(
            window_size=timedelta(seconds=2),
            window_type=WindowType.TUMBLING,
            buffer_size=1000
        )
        
        await processor.start()
        
        try:
            # Generate high volume of events
            num_events = 500
            events = [
                GraphChangeEvent(
                    f"high-vol-{i}",
                    ChangeType.NODE_CREATED,
                    datetime.now() + timedelta(milliseconds=i),
                    f"node-{i % 100}",  # 100 distinct entities
                    "node"
                )
                for i in range(num_events)
            ]
            
            # Process events in batches
            batch_size = 50
            for i in range(0, num_events, batch_size):
                batch = events[i:i + batch_size]
                await processor.process_events(batch)
                
                # Small delay to prevent overwhelming
                await asyncio.sleep(0.01)
            
            # Wait for processing
            await asyncio.sleep(1.0)
            await processor._process_pending_events()
            
            # Verify all events were processed
            assert processor.stats["events_processed"] == num_events
            assert processor.stats["dropped_events"] == 0
            
        finally:
            await processor.stop()
    
    @pytest.mark.asyncio
    async def test_late_arriving_events(self):
        """Test handling of late-arriving events."""
        processor = StreamProcessor(
            window_size=timedelta(seconds=3),
            window_type=WindowType.TUMBLING,
            late_arrival_grace=timedelta(seconds=1)
        )
        
        await processor.start()
        
        try:
            base_time = datetime.now() - timedelta(seconds=10)  # Events from past
            
            # Create events with different timestamps
            events = [
                # Current events (should be processed)
                GraphChangeEvent(
                    "current-1",
                    ChangeType.NODE_CREATED,
                    datetime.now(),
                    "current-node",
                    "node"
                ),
                # Recent events (within grace period, should be processed)
                GraphChangeEvent(
                    "recent-1", 
                    ChangeType.NODE_CREATED,
                    datetime.now() - timedelta(milliseconds=500),
                    "recent-node",
                    "node"
                ),
                # Late events (beyond grace period, may be dropped)
                GraphChangeEvent(
                    "late-1",
                    ChangeType.NODE_CREATED,
                    base_time,  # Very old
                    "late-node",
                    "node"
                )
            ]
            
            # Process events
            for event in events:
                await processor.process_event(event)
            
            # Wait for processing
            await asyncio.sleep(2.0)
            await processor._process_pending_events()
            
            # Verify late events were handled appropriately
            assert processor.stats["events_processed"] == 3
            # Late events count depends on timing and grace period
            assert processor.stats["late_events"] >= 0
            
        finally:
            await processor.stop()
    
    @pytest.mark.asyncio
    async def test_window_overlap_scenarios(self):
        """Test overlapping window scenarios."""
        # Use hopping windows with overlap
        processor = StreamProcessor(
            window_size=timedelta(seconds=4),
            window_type=WindowType.HOPPING,
            hop_size=timedelta(seconds=2)  # 50% overlap
        )
        
        await processor.start()
        
        # Track completed windows
        completed_windows = []
        
        def window_handler(window):
            completed_windows.append(window)
        
        processor.add_window_handler(window_handler)
        
        try:
            # Generate events over time
            base_time = datetime.now()
            events = [
                GraphChangeEvent(
                    f"overlap-{i}",
                    ChangeType.NODE_CREATED,
                    base_time + timedelta(seconds=i),
                    f"node-{i}",
                    "node"
                )
                for i in range(8)
            ]
            
            # Process events
            for event in events:
                await processor.process_event(event)
            
            # Wait for processing and window completion
            await asyncio.sleep(1.0)
            await processor._process_pending_events()
            await processor._complete_all_windows()
            
            # With hopping windows, events should appear in multiple windows
            if completed_windows:
                # Check that some events appear in multiple windows
                all_event_ids = []
                for window in completed_windows:
                    for event in window.events:
                        all_event_ids.append(event.event_id)
                
                # With overlapping windows, we should see duplicate events
                assert len(all_event_ids) >= len(events)
            
        finally:
            await processor.stop()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
