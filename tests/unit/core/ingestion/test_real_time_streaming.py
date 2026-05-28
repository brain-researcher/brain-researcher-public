"""Comprehensive unit tests for INGEST-020 Real-time Data Streaming.

This test suite covers:
- Stream configuration and consumer management
- Message processing and transformation
- Backpressure handling and topic pausing
- Metrics collection and throughput monitoring
- Offset committing and result storage
- Processor registration and validation
- Error handling and recovery scenarios
"""

import asyncio
import json
import os
import sys
import time
from collections import defaultdict, deque
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Add project root to path
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../.."))
sys.path.insert(0, project_root)

from brain_researcher.core.ingestion.streaming.real_time_streaming import (
    ProcessingMode,
    ProcessingResult,
    RealTimeStreaming,
    StreamConfig,
    StreamMessage,
    StreamProcessor,
    StreamType,
    NeuroimagingProcessor,
    BehavioralProcessor,
)


class MockRedis:
    """Mock Redis client for testing."""
    
    def __init__(self):
        self.data = {}
        self.expiry_data = {}
        
    async def set(self, key, value):
        """Mock set method."""
        self.data[key] = value
        
    async def get(self, key):
        """Mock get method."""
        return self.data.get(key)
        
    async def setex(self, key, ttl, value):
        """Mock setex method."""
        self.data[key] = value
        self.expiry_data[key] = ttl


class TestProcessor(StreamProcessor):
    """Test processor for unit testing."""

    __test__ = False
    
    def __init__(self, should_fail=False, processing_time=0.01):
        self.should_fail = should_fail
        self.processing_time = processing_time
        self.processed_messages = []
        
    async def process(self, message: StreamMessage) -> ProcessingResult:
        """Process a test message."""
        await asyncio.sleep(self.processing_time)
        
        if self.should_fail:
            return ProcessingResult(
                message_id=message.message_id,
                success=False,
                error="Test processor failure"
            )
            
        self.processed_messages.append(message)
        
        return ProcessingResult(
            message_id=message.message_id,
            success=True,
            processing_time_ms=self.processing_time * 1000,
            output_data={"processed": True, "data": message.value}
        )


@pytest.fixture
def mock_redis():
    """Create a mock Redis client."""
    return MockRedis()


@pytest.fixture
def streaming_system(mock_redis):
    """Create a streaming system instance."""
    return RealTimeStreaming(redis_client=mock_redis)


@pytest.fixture
def test_processor():
    """Create a test processor."""
    return TestProcessor()


@pytest.fixture
def failing_processor():
    """Create a test processor that fails."""
    return TestProcessor(should_fail=True)


@pytest.fixture
def slow_processor():
    """Create a slow test processor."""
    return TestProcessor(processing_time=0.1)


@pytest.fixture 
async def started_system(streaming_system):
    """Create and start a streaming system."""
    await streaming_system.start()
    yield streaming_system
    await streaming_system.stop()


class TestRealTimeStreaming:
    """Test cases for RealTimeStreaming class."""
    
    def test_initialization(self):
        """Test streaming system initialization."""
        system = RealTimeStreaming()
        
        assert system.kafka_config["bootstrap_servers"] == "localhost:9092"
        assert system.kafka_config["auto_offset_reset"] == "latest"
        assert len(system.stream_configs) == 0
        assert len(system.processors) == 0
        assert system.backpressure["enabled"] is True
        assert system.backpressure["threshold"] == 1000
        
    def test_initialization_with_config(self, mock_redis):
        """Test streaming system initialization with custom config."""
        kafka_config = {
            "bootstrap_servers": "custom:9092",
            "max_poll_records": 1000
        }
        
        system = RealTimeStreaming(
            kafka_config=kafka_config,
            redis_client=mock_redis
        )
        
        assert system.kafka_config["bootstrap_servers"] == "custom:9092"
        assert system.kafka_config["max_poll_records"] == 1000
        assert system.redis == mock_redis
        
    def test_configure_stream(self, streaming_system):
        """Test stream configuration."""
        config = streaming_system.configure_stream(
            topic="test_topic",
            stream_type=StreamType.NEUROIMAGING,
            consumer_group="test_group",
            batch_size=50,
            processing_mode=ProcessingMode.EXACTLY_ONCE
        )
        
        assert config.topic == "test_topic"
        assert config.stream_type == StreamType.NEUROIMAGING
        assert config.consumer_group == "test_group"
        assert config.batch_size == 50
        assert config.processing_mode == ProcessingMode.EXACTLY_ONCE
        
        # Verify config is stored
        assert "test_topic" in streaming_system.stream_configs
        assert streaming_system.stream_configs["test_topic"] == config
        
    def test_register_processor(self, streaming_system, test_processor):
        """Test processor registration."""
        streaming_system.register_processor(StreamType.NEUROIMAGING, test_processor)
        
        assert StreamType.NEUROIMAGING.value in streaming_system.processors
        assert streaming_system.processors[StreamType.NEUROIMAGING.value] == test_processor
        
    @pytest.mark.asyncio
    async def test_start_stop_system(self, streaming_system):
        """Test starting and stopping the streaming system."""
        # Configure a stream
        streaming_system.configure_stream(
            "test_topic", 
            StreamType.NEUROIMAGING, 
            "test_group"
        )
        
        await streaming_system.start()
        
        # Verify system state
        assert len(streaming_system.consumers) == 1
        assert "test_topic" in streaming_system.processing_state["active_streams"]
        assert len(streaming_system.processing_state["processing_tasks"]) == 4
        
        await streaming_system.stop()
        
        # Verify cleanup
        for task in streaming_system.processing_state["processing_tasks"]:
            assert task.cancelled() or task.done()
            
    @pytest.mark.asyncio
    async def test_create_consumer(self, streaming_system):
        """Test consumer creation."""
        config = StreamConfig(
            topic="test_topic",
            stream_type=StreamType.NEUROIMAGING,
            consumer_group="test_group"
        )
        
        consumer = await streaming_system._create_consumer(config)
        
        assert consumer["topic"] == "test_topic"
        assert consumer["group"] == "test_group"
        assert consumer["config"] == config
        assert consumer["position"] == 0
        assert consumer["committed"] == 0
        
    @pytest.mark.asyncio
    async def test_close_consumer(self, streaming_system):
        """Test consumer closure."""
        config = StreamConfig(
            topic="test_topic",
            stream_type=StreamType.NEUROIMAGING,
            consumer_group="test_group"
        )
        
        consumer = await streaming_system._create_consumer(config)
        await streaming_system._close_consumer(consumer)
        
        # Mock consumer just logs the closure, so we verify it doesn't error
        
    @pytest.mark.asyncio
    async def test_poll_messages(self, streaming_system):
        """Test message polling from consumer."""
        config = StreamConfig(
            topic="test_topic",
            stream_type=StreamType.NEUROIMAGING,
            consumer_group="test_group"
        )
        
        consumer = await streaming_system._create_consumer(config)
        
        # Poll messages multiple times to test randomization
        all_messages = []
        for _ in range(10):
            messages = await streaming_system._poll_messages(consumer)
            all_messages.extend(messages)
            
        # Should get some messages over 10 polls
        assert len(all_messages) > 0
        
        # Verify message structure
        if all_messages:
            message = all_messages[0]
            assert hasattr(message, 'message_id')
            assert hasattr(message, 'stream_type')
            assert hasattr(message, 'topic')
            assert message.topic == "test_topic"
            assert message.stream_type == StreamType.NEUROIMAGING
            
    @pytest.mark.asyncio
    async def test_process_single_message_success(self, streaming_system, test_processor):
        """Test successful single message processing."""
        streaming_system.register_processor(StreamType.NEUROIMAGING, test_processor)
        
        message = StreamMessage(
            message_id="test_msg_1",
            stream_type=StreamType.NEUROIMAGING,
            topic="test_topic",
            partition=0,
            offset=10,
            key="test_key",
            value={"data": "test_data"},
            timestamp=datetime.now()
        )
        
        result = await streaming_system._process_single_message(message)
        
        assert result.success is True
        assert result.message_id == "test_msg_1"
        assert result.output_data["processed"] is True
        assert message in test_processor.processed_messages
        
    @pytest.mark.asyncio
    async def test_process_single_message_no_processor(self, streaming_system):
        """Test message processing without registered processor."""
        message = StreamMessage(
            message_id="test_msg_1",
            stream_type=StreamType.NEUROIMAGING,
            topic="test_topic",
            partition=0,
            offset=10,
            key="test_key",
            value={"data": "test_data"},
            timestamp=datetime.now()
        )
        
        result = await streaming_system._process_single_message(message)
        
        assert result.success is False
        assert "No processor" in result.error
        
    @pytest.mark.asyncio
    async def test_process_single_message_failure(self, streaming_system, failing_processor):
        """Test message processing with failing processor."""
        streaming_system.register_processor(StreamType.NEUROIMAGING, failing_processor)
        
        message = StreamMessage(
            message_id="test_msg_1",
            stream_type=StreamType.NEUROIMAGING,
            topic="test_topic",
            partition=0,
            offset=10,
            key="test_key",
            value={"data": "test_data"},
            timestamp=datetime.now()
        )
        
        result = await streaming_system._process_single_message(message)
        
        assert result.success is False
        assert "Test processor failure" in result.error
        
    @pytest.mark.asyncio
    async def test_commit_offset(self, streaming_system, mock_redis):
        """Test offset committing."""
        config = StreamConfig(
            topic="test_topic",
            stream_type=StreamType.NEUROIMAGING,
            consumer_group="test_group"
        )
        
        consumer = await streaming_system._create_consumer(config)
        streaming_system.consumers["test_topic"] = consumer
        
        message = StreamMessage(
            message_id="test_msg_1",
            stream_type=StreamType.NEUROIMAGING,
            topic="test_topic",
            partition=0,
            offset=10,
            key="test_key",
            value={},
            timestamp=datetime.now()
        )
        
        await streaming_system._commit_offset(message)
        
        # Verify consumer offset updated
        assert consumer["committed"] == 10
        
        # Verify Redis key was set
        expected_key = "stream:offset:test_topic:0"
        assert expected_key in mock_redis.data
        assert mock_redis.data[expected_key] == 10
        
    @pytest.mark.asyncio
    async def test_store_result(self, streaming_system, mock_redis):
        """Test result storage."""
        message = StreamMessage(
            message_id="test_msg_1",
            stream_type=StreamType.NEUROIMAGING,
            topic="test_topic",
            partition=0,
            offset=10,
            key="test_key",
            value={},
            timestamp=datetime.now()
        )
        
        result = ProcessingResult(
            message_id="test_msg_1",
            success=True,
            output_data={"processed": True}
        )
        
        await streaming_system._store_result(message, result)
        
        # Verify result was stored in Redis
        expected_key = "stream:result:test_msg_1"
        assert expected_key in mock_redis.data
        
        stored_data = json.loads(mock_redis.data[expected_key])
        assert stored_data["message_id"] == "test_msg_1"
        assert stored_data["topic"] == "test_topic"
        assert stored_data["result"]["success"] is True
        
    def test_get_slowest_topics(self, streaming_system):
        """Test identification of slowest topics."""
        # Add processing times for different topics
        streaming_system.metrics["processing_times"]["topic_a"] = [10, 15, 20]
        streaming_system.metrics["processing_times"]["topic_b"] = [50, 60, 70]
        streaming_system.metrics["processing_times"]["topic_c"] = [5, 8, 12]
        
        slowest = streaming_system._get_slowest_topics()
        
        # Should be ordered by average processing time (descending)
        assert slowest[0] == "topic_b"  # Average: 60
        assert slowest[1] == "topic_a"  # Average: 15
        assert slowest[2] == "topic_c"  # Average: 8.33
        
    def test_get_statistics(self, streaming_system):
        """Test statistics collection."""
        # Set up test metrics
        streaming_system.metrics["messages_received"]["topic_a"] = 100
        streaming_system.metrics["messages_received"]["topic_b"] = 50
        streaming_system.metrics["messages_processed"]["topic_a"] = 95
        streaming_system.metrics["messages_processed"]["topic_b"] = 45
        streaming_system.metrics["messages_failed"]["topic_a"] = 5
        streaming_system.metrics["processing_times"]["topic_a"] = [10, 20, 30]
        streaming_system.metrics["lag_by_topic"]["topic_a"] = 5
        
        # Set queue size
        streaming_system.processing_state["message_queue"] = asyncio.Queue()
        for _ in range(10):
            streaming_system.processing_state["message_queue"].put_nowait("test")
            
        streaming_system.processing_state["active_streams"].add("topic_a")
        streaming_system.backpressure["paused_topics"].add("topic_b")
        
        stats = streaming_system.get_statistics()
        
        assert stats["total_received"] == 150
        assert stats["total_processed"] == 140
        assert stats["total_failed"] == 5
        assert stats["success_rate"] == 140 / 150
        assert stats["queue_size"] == 10
        assert "topic_a" in stats["active_streams"]
        assert "topic_b" in stats["paused_topics"]
        assert stats["lag_by_topic"]["topic_a"] == 5
        assert "topic_a" in stats["avg_processing_times"]
        
    @pytest.mark.asyncio
    async def test_backpressure_pause_resume(self, streaming_system, slow_processor):
        """Test backpressure management with topic pausing."""
        # Configure system with low threshold
        streaming_system.backpressure["threshold"] = 5
        
        # Set up slow processing times
        streaming_system.metrics["processing_times"]["slow_topic"] = [100, 120, 150]
        streaming_system.metrics["processing_times"]["fast_topic"] = [5, 8, 12]
        
        # Simulate high queue size
        for _ in range(10):
            streaming_system.processing_state["message_queue"].put_nowait("test")
            
        # Simulate backpressure monitoring
        queue_size = streaming_system.processing_state["message_queue"].qsize()
        
        if queue_size > streaming_system.backpressure["threshold"]:
            slowest_topics = streaming_system._get_slowest_topics()
            
            for topic in slowest_topics[:2]:
                if topic not in streaming_system.backpressure["paused_topics"]:
                    streaming_system.backpressure["paused_topics"].add(topic)
                    
        # Verify slowest topic was paused
        assert "slow_topic" in streaming_system.backpressure["paused_topics"]
        
        # Simulate queue draining
        while not streaming_system.processing_state["message_queue"].empty():
            streaming_system.processing_state["message_queue"].get_nowait()
            
        # Simulate resume condition
        queue_size = streaming_system.processing_state["message_queue"].qsize()
        if queue_size < streaming_system.backpressure["threshold"] * 0.5:
            streaming_system.backpressure["paused_topics"].clear()
            
        # Verify topics were resumed
        assert len(streaming_system.backpressure["paused_topics"]) == 0
        
    @pytest.mark.asyncio
    async def test_end_to_end_processing(self, started_system, test_processor, mock_redis):
        """Test end-to-end message processing flow."""
        # Configure and register processor
        started_system.configure_stream(
            "test_topic", 
            StreamType.NEUROIMAGING, 
            "test_group"
        )
        started_system.register_processor(StreamType.NEUROIMAGING, test_processor)
        
        # Create test message
        message = StreamMessage(
            message_id="e2e_test",
            stream_type=StreamType.NEUROIMAGING,
            topic="test_topic",
            partition=0,
            offset=100,
            key="test_key",
            value={"scan_type": "fMRI", "subject": "001"},
            timestamp=datetime.now()
        )
        
        # Add message to processing queue
        await started_system.processing_state["message_queue"].put(message)
        
        # Allow processing time
        await asyncio.sleep(0.1)
        
        # Verify message was processed
        assert len(test_processor.processed_messages) >= 1
        processed_msg = test_processor.processed_messages[-1]
        assert processed_msg.message_id == "e2e_test"
        
        # Verify metrics were updated
        assert started_system.metrics["messages_processed"]["test_topic"] >= 1
        
    @pytest.mark.asyncio
    async def test_concurrent_message_processing(self, started_system, test_processor):
        """Test concurrent processing of multiple messages."""
        started_system.register_processor(StreamType.NEUROIMAGING, test_processor)
        
        # Create multiple messages
        messages = []
        for i in range(5):
            message = StreamMessage(
                message_id=f"concurrent_test_{i}",
                stream_type=StreamType.NEUROIMAGING,
                topic="test_topic",
                partition=0,
                offset=i,
                key=f"key_{i}",
                value={"data": f"test_{i}"},
                timestamp=datetime.now()
            )
            messages.append(message)
            
        # Add all messages to queue
        for message in messages:
            await started_system.processing_state["message_queue"].put(message)
            
        # Allow processing time
        await asyncio.sleep(0.2)
        
        # Verify all messages were processed
        assert len(test_processor.processed_messages) >= 5
        
        # Verify message IDs
        processed_ids = [msg.message_id for msg in test_processor.processed_messages]
        for i in range(5):
            assert f"concurrent_test_{i}" in processed_ids


class TestNeuroimagingProcessor:
    """Test cases for NeuroimagingProcessor."""
    
    @pytest.mark.asyncio
    async def test_process_neuroimaging_message(self):
        """Test processing of neuroimaging data."""
        processor = NeuroimagingProcessor()
        
        message = StreamMessage(
            message_id="neuro_test",
            stream_type=StreamType.NEUROIMAGING,
            topic="neuroimaging_topic",
            partition=0,
            offset=1,
            key="scan_key",
            value={
                "subject_id": "sub-001",
                "scan_type": "fMRI",
                "timestamp": "2025-01-01T12:00:00Z"
            },
            timestamp=datetime.now()
        )
        
        result = await processor.process(message)
        
        assert result.success is True
        assert result.message_id == "neuro_test"
        assert result.output_data["subject_id"] == "sub-001"
        assert result.output_data["scan_type"] == "fMRI"
        assert "processed_at" in result.output_data
        
    @pytest.mark.asyncio
    async def test_process_neuroimaging_error(self):
        """Test error handling in neuroimaging processor."""
        processor = NeuroimagingProcessor()
        
        # Create message with invalid data that might cause processing error
        message = StreamMessage(
            message_id="neuro_error_test",
            stream_type=StreamType.NEUROIMAGING,
            topic="neuroimaging_topic",
            partition=0,
            offset=1,
            key="scan_key",
            value=None,  # This should cause an error
            timestamp=datetime.now()
        )
        
        result = await processor.process(message)
        
        # The processor should handle the error gracefully
        assert result.success is False
        assert result.message_id == "neuro_error_test"
        assert result.error is not None


class TestBehavioralProcessor:
    """Test cases for BehavioralProcessor."""
    
    @pytest.mark.asyncio
    async def test_process_behavioral_message(self):
        """Test processing of behavioral data."""
        processor = BehavioralProcessor()
        
        message = StreamMessage(
            message_id="behavioral_test",
            stream_type=StreamType.BEHAVIORAL,
            topic="behavioral_topic",
            partition=0,
            offset=1,
            key="behavior_key",
            value={
                "subject_id": "sub-001",
                "task": "n-back",
                "score": 85,
                "reaction_time": 450
            },
            timestamp=datetime.now()
        )
        
        result = await processor.process(message)
        
        assert result.success is True
        assert result.message_id == "behavioral_test"
        assert result.output_data["subject_id"] == "sub-001"
        assert result.output_data["task"] == "n-back"
        assert result.output_data["score"] == 85
        assert result.output_data["reaction_time"] == 450
        assert "processed_at" in result.output_data
        
    @pytest.mark.asyncio
    async def test_process_behavioral_error(self):
        """Test error handling in behavioral processor."""
        processor = BehavioralProcessor()
        
        # Create message that might cause processing error
        message = StreamMessage(
            message_id="behavioral_error_test",
            stream_type=StreamType.BEHAVIORAL,
            topic="behavioral_topic",
            partition=0,
            offset=1,
            key="behavior_key",
            value={"invalid": "data"},  # Missing expected fields
            timestamp=datetime.now()
        )
        
        result = await processor.process(message)
        
        # Processor should handle missing fields gracefully
        assert result.success is True
        assert result.message_id == "behavioral_error_test"
        assert result.output_data["subject_id"] is None  # Missing field should be None


class TestStreamConfig:
    """Test cases for StreamConfig dataclass."""
    
    def test_stream_config_creation(self):
        """Test StreamConfig creation with defaults."""
        config = StreamConfig(
            topic="test_topic",
            stream_type=StreamType.NEUROIMAGING,
            consumer_group="test_group"
        )
        
        assert config.topic == "test_topic"
        assert config.stream_type == StreamType.NEUROIMAGING
        assert config.consumer_group == "test_group"
        assert config.processing_mode == ProcessingMode.AT_LEAST_ONCE
        assert config.batch_size == 100
        assert config.batch_timeout_ms == 1000
        assert config.max_retries == 3
        assert config.enable_auto_commit is False
        
    def test_stream_config_custom_values(self):
        """Test StreamConfig creation with custom values."""
        config = StreamConfig(
            topic="custom_topic",
            stream_type=StreamType.CLINICAL,
            consumer_group="custom_group",
            processing_mode=ProcessingMode.EXACTLY_ONCE,
            batch_size=200,
            batch_timeout_ms=2000,
            max_retries=5,
            retry_backoff_ms=2000,
            enable_auto_commit=True
        )
        
        assert config.processing_mode == ProcessingMode.EXACTLY_ONCE
        assert config.batch_size == 200
        assert config.batch_timeout_ms == 2000
        assert config.max_retries == 5
        assert config.retry_backoff_ms == 2000
        assert config.enable_auto_commit is True


class TestStreamMessage:
    """Test cases for StreamMessage dataclass."""
    
    def test_stream_message_creation(self):
        """Test StreamMessage creation."""
        timestamp = datetime.now()
        
        message = StreamMessage(
            message_id="test_msg",
            stream_type=StreamType.GENOMIC,
            topic="genomic_data",
            partition=2,
            offset=150,
            key="gene_key",
            value={"gene": "APOE", "variant": "e4"},
            timestamp=timestamp,
            headers={"source": "lab_a", "version": "1.0"}
        )
        
        assert message.message_id == "test_msg"
        assert message.stream_type == StreamType.GENOMIC
        assert message.topic == "genomic_data"
        assert message.partition == 2
        assert message.offset == 150
        assert message.key == "gene_key"
        assert message.value == {"gene": "APOE", "variant": "e4"}
        assert message.timestamp == timestamp
        assert message.headers["source"] == "lab_a"
        assert message.headers["version"] == "1.0"


class TestProcessingResult:
    """Test cases for ProcessingResult dataclass."""
    
    def test_processing_result_success(self):
        """Test successful ProcessingResult creation."""
        result = ProcessingResult(
            message_id="test_msg",
            success=True,
            processing_time_ms=15.5,
            output_data={"processed": True, "result": "success"}
        )
        
        assert result.message_id == "test_msg"
        assert result.success is True
        assert result.error is None
        assert result.processing_time_ms == 15.5
        assert result.output_data["processed"] is True
        assert result.output_data["result"] == "success"
        
    def test_processing_result_failure(self):
        """Test failed ProcessingResult creation."""
        result = ProcessingResult(
            message_id="test_msg",
            success=False,
            error="Processing failed due to invalid data",
            processing_time_ms=5.0
        )
        
        assert result.message_id == "test_msg"
        assert result.success is False
        assert result.error == "Processing failed due to invalid data"
        assert result.processing_time_ms == 5.0
        assert result.output_data is None
