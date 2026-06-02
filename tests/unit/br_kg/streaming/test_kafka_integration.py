"""Unit tests for Kafka integration streaming module.

This module tests the Kafka producer/consumer integration including:
- Message publishing and consumption
- Configuration handling
- Error handling and retry logic
- Dead letter queue functionality
- Integration with CDC processor
"""

import asyncio
import json
from datetime import datetime
from typing import Any, Dict, List
from unittest.mock import AsyncMock, MagicMock, Mock, patch

import pytest

# Import the modules to test
try:
    from brain_researcher.services.br_kg.streaming.cdc_processor import (
        ChangeType,
        GraphChangeEvent,
    )
    from brain_researcher.services.br_kg.streaming.kafka_integration import (
        KafkaConsumer,
        KafkaProducer,
        KafkaStreamingError,
        StreamConfig,
        create_cdc_kafka_integration,
        create_kafka_subscription_integration,
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
    from brain_researcher.services.br_kg.streaming.kafka_integration import (
        KafkaConsumer,
        KafkaProducer,
        KafkaStreamingError,
        StreamConfig,
        create_cdc_kafka_integration,
        create_kafka_subscription_integration,
    )


class TestStreamConfig:
    """Test StreamConfig configuration class."""

    def test_default_config(self):
        """Test default configuration values."""
        config = StreamConfig()

        assert config.bootstrap_servers == "localhost:9092"
        assert config.security_protocol == "PLAINTEXT"
        assert config.default_topic == "brain-researcher-graph-events"
        assert config.topic_partitions == 3
        assert config.topic_replication_factor == 1
        assert config.producer_batch_size == 16384
        assert config.consumer_group_id == "brain-researcher-consumers"
        assert config.max_poll_records == 500

    def test_custom_config(self):
        """Test custom configuration values."""
        config = StreamConfig(
            bootstrap_servers="kafka:9092",
            security_protocol="SASL_SSL",
            sasl_mechanism="PLAIN",
            sasl_plain_username="user",
            sasl_plain_password="pass",
            default_topic="custom-topic",
            producer_batch_size=32768,
            consumer_group_id="custom-group",
        )

        assert config.bootstrap_servers == "kafka:9092"
        assert config.security_protocol == "SASL_SSL"
        assert config.sasl_mechanism == "PLAIN"
        assert config.sasl_plain_username == "user"
        assert config.sasl_plain_password == "pass"
        assert config.default_topic == "custom-topic"
        assert config.producer_batch_size == 32768
        assert config.consumer_group_id == "custom-group"

    def test_producer_config(self):
        """Test producer configuration generation."""
        config = StreamConfig(
            bootstrap_servers="kafka:9092",
            security_protocol="SASL_SSL",
            sasl_mechanism="PLAIN",
            sasl_plain_username="user",
            sasl_plain_password="pass",
            producer_batch_size=32768,
        )

        producer_config = config.to_producer_config()

        assert producer_config["bootstrap_servers"] == "kafka:9092"
        assert producer_config["security_protocol"] == "SASL_SSL"
        assert producer_config["sasl_mechanism"] == "PLAIN"
        assert producer_config["sasl_plain_username"] == "user"
        assert producer_config["sasl_plain_password"] == "pass"
        assert producer_config["batch_size"] == 32768
        assert "value_serializer" in producer_config
        assert "key_serializer" in producer_config

    def test_consumer_config(self):
        """Test consumer configuration generation."""
        config = StreamConfig(
            bootstrap_servers="kafka:9092",
            consumer_group_id="test-group",
            max_poll_records=100,
        )

        consumer_config = config.to_consumer_config()

        assert consumer_config["bootstrap_servers"] == "kafka:9092"
        assert consumer_config["group_id"] == "test-group"
        assert consumer_config["max_poll_records"] == 100
        assert "value_deserializer" in consumer_config
        assert "key_deserializer" in consumer_config


class TestKafkaProducer:
    """Test KafkaProducer class."""

    @pytest.fixture
    def stream_config(self):
        """Create test stream configuration."""
        return StreamConfig(
            bootstrap_servers="localhost:9092", default_topic="test-topic"
        )

    @pytest.fixture
    def mock_aiokafka_producer(self):
        """Create mock AIOKafkaProducer."""
        producer = AsyncMock()
        producer.start = AsyncMock()
        producer.stop = AsyncMock()
        producer.send = AsyncMock()
        return producer

    @pytest.fixture
    def kafka_producer(self, stream_config):
        """Create KafkaProducer with mocked dependencies."""
        with patch(
            "brain_researcher.services.br_kg.streaming.kafka_integration.AIOKafkaProducer"
        ) as mock_producer_class:
            producer = KafkaProducer(stream_config)
            producer.producer = AsyncMock()  # Mock the actual producer
            return producer

    def test_producer_initialization(self, stream_config):
        """Test Kafka producer initialization."""
        with patch(
            "brain_researcher.services.br_kg.streaming.kafka_integration.AIOKafkaProducer"
        ) as mock_producer_class:
            producer = KafkaProducer(stream_config)

            assert producer.config == stream_config
            assert not producer.is_running
            assert producer.producer is None
            assert producer.stats["messages_sent"] == 0

    @pytest.mark.asyncio
    async def test_start_stop_producer(self, kafka_producer):
        """Test starting and stopping Kafka producer."""
        with patch.object(kafka_producer, "_ensure_topics", AsyncMock()):
            with patch(
                "brain_researcher.services.br_kg.streaming.kafka_integration.AIOKafkaProducer"
            ) as mock_producer_class:
                mock_producer = AsyncMock()
                mock_producer_class.return_value = mock_producer

                # Start producer
                await kafka_producer.start()

                assert kafka_producer.is_running
                mock_producer.start.assert_called_once()

                # Stop producer
                kafka_producer.producer = mock_producer
                await kafka_producer.stop()

                assert not kafka_producer.is_running
                mock_producer.stop.assert_called_once()

    @pytest.mark.asyncio
    async def test_send_event_success(self, kafka_producer):
        """Test successful event sending."""
        # Create test event
        event = GraphChangeEvent(
            event_id="test-123",
            change_type=ChangeType.NODE_CREATED,
            timestamp=datetime.now(),
            entity_id="node-456",
            entity_type="node",
            labels=["Person"],
            new_properties={"name": "John"},
        )

        # Mock producer
        mock_producer = AsyncMock()
        mock_producer.send.return_value = AsyncMock()
        kafka_producer.producer = mock_producer
        kafka_producer.is_running = True

        # Send event
        result = await kafka_producer.send_event(event)

        assert result is True
        mock_producer.send.assert_called_once()

        # Check call arguments
        call_args = mock_producer.send.call_args
        assert call_args[1]["topic"] == kafka_producer.config.default_topic
        assert call_args[1]["key"] == event.entity_id

        # Check message content
        message = call_args[1]["value"]
        assert message["event_id"] == event.event_id
        assert message["change_type"] == event.change_type.value
        assert "_kafka_metadata" in message

        # Check statistics
        assert kafka_producer.stats["messages_sent"] == 1
        assert kafka_producer.stats["last_send_time"] is not None

    @pytest.mark.asyncio
    async def test_send_event_failure_dlq(self, kafka_producer):
        """Test event sending failure and DLQ handling."""
        # Create test event
        event = GraphChangeEvent(
            event_id="test-123",
            change_type=ChangeType.NODE_CREATED,
            timestamp=datetime.now(),
            entity_id="node-456",
            entity_type="node",
        )

        # Mock producer that fails
        mock_producer = AsyncMock()
        mock_producer.send.side_effect = [
            Exception("Send failed"),  # First call fails
            AsyncMock(),  # DLQ send succeeds
        ]
        kafka_producer.producer = mock_producer
        kafka_producer.is_running = True

        # Send event
        result = await kafka_producer.send_event(event)

        assert result is False
        assert mock_producer.send.call_count == 2  # Original send + DLQ
        assert kafka_producer.stats["send_errors"] == 1

        # Check DLQ call
        dlq_call = mock_producer.send.call_args_list[1]
        assert dlq_call[1]["topic"] == f"{kafka_producer.config.default_topic}-dlq"

        dlq_message = dlq_call[1]["value"]
        assert "original_event" in dlq_message
        assert "error" in dlq_message
        assert "failed_at" in dlq_message

    @pytest.mark.asyncio
    async def test_send_batch(self, kafka_producer):
        """Test batch event sending."""
        # Create test events
        events = []
        for i in range(5):
            event = GraphChangeEvent(
                event_id=f"event-{i}",
                change_type=ChangeType.NODE_CREATED,
                timestamp=datetime.now(),
                entity_id=f"node-{i}",
                entity_type="node",
            )
            events.append(event)

        # Mock successful sends
        kafka_producer.send_event = AsyncMock(return_value=True)

        # Send batch
        sent_count = await kafka_producer.send_batch(events)

        assert sent_count == 5
        assert kafka_producer.send_event.call_count == 5

    @pytest.mark.asyncio
    async def test_send_with_custom_key_function(self, kafka_producer):
        """Test sending with custom key function."""
        # Create test events
        events = [
            GraphChangeEvent(
                event_id="event-1",
                change_type=ChangeType.NODE_CREATED,
                timestamp=datetime.now(),
                entity_id="node-1",
                entity_type="node",
                labels=["Person"],
            )
        ]

        # Custom key function
        def custom_key_func(event):
            return f"custom-{event.entity_id}"

        kafka_producer.send_event = AsyncMock(return_value=True)

        # Send with custom key function
        await kafka_producer.send_batch(events, key_func=custom_key_func)

        kafka_producer.send_event.assert_called_once()
        call_args = kafka_producer.send_event.call_args
        assert call_args[1]["key"] == "custom-node-1"

    def test_get_stats(self, kafka_producer):
        """Test getting producer statistics."""
        # Set some test stats
        kafka_producer.stats["messages_sent"] = 10
        kafka_producer.stats["bytes_sent"] = 1024
        kafka_producer.stats["last_send_time"] = datetime.now()

        stats = kafka_producer.get_stats()

        assert stats["is_running"] == False
        assert stats["messages_sent"] == 10
        assert stats["bytes_sent"] == 1024
        assert "last_send_time" in stats
        assert "config" in stats

    @pytest.mark.asyncio
    async def test_import_error_handling(self):
        """Test handling when aiokafka is not available."""
        with patch(
            "brain_researcher.services.br_kg.streaming.kafka_integration.AIOKafkaProducer",
            None,
        ):
            config = StreamConfig()

            with pytest.raises(ImportError, match="aiokafka is required"):
                KafkaProducer(config)


class TestKafkaConsumer:
    """Test KafkaConsumer class."""

    @pytest.fixture
    def stream_config(self):
        """Create test stream configuration."""
        return StreamConfig(
            bootstrap_servers="localhost:9092",
            default_topic="test-topic",
            consumer_group_id="test-group",
        )

    @pytest.fixture
    def kafka_consumer(self, stream_config):
        """Create KafkaConsumer with mocked dependencies."""
        with patch(
            "brain_researcher.services.br_kg.streaming.kafka_integration.AIOKafkaConsumer"
        ):
            consumer = KafkaConsumer(stream_config)
            consumer.consumer = AsyncMock()  # Mock the actual consumer
            return consumer

    def test_consumer_initialization(self, stream_config):
        """Test Kafka consumer initialization."""
        with patch(
            "brain_researcher.services.br_kg.streaming.kafka_integration.AIOKafkaConsumer"
        ):
            consumer = KafkaConsumer(stream_config, topics=["topic1", "topic2"])

            assert consumer.config == stream_config
            assert consumer.topics == ["topic1", "topic2"]
            assert not consumer.is_running
            assert consumer.consumer is None
            assert len(consumer.event_handlers) == 0
            assert len(consumer.batch_handlers) == 0
            assert consumer.stats["messages_consumed"] == 0

    @pytest.mark.asyncio
    async def test_start_stop_consumer(self, kafka_consumer):
        """Test starting and stopping Kafka consumer."""
        with patch(
            "brain_researcher.services.br_kg.streaming.kafka_integration.AIOKafkaConsumer"
        ) as mock_consumer_class:
            mock_consumer = AsyncMock()
            mock_consumer_class.return_value = mock_consumer

            # Start consumer
            await kafka_consumer.start()

            assert kafka_consumer.is_running
            mock_consumer.start.assert_called_once()

            # Stop consumer
            kafka_consumer.consumer = mock_consumer
            await kafka_consumer.stop()

            assert not kafka_consumer.is_running
            mock_consumer.stop.assert_called_once()

    @pytest.mark.asyncio
    async def test_event_handler_registration(self, kafka_consumer):
        """Test event handler registration."""

        def test_event_handler(event, record):
            pass

        def test_batch_handler(events, records):
            pass

        def test_error_handler(error, record):
            pass

        kafka_consumer.add_event_handler(test_event_handler)
        kafka_consumer.add_batch_handler(test_batch_handler)
        kafka_consumer.add_error_handler(test_error_handler)

        assert len(kafka_consumer.event_handlers) == 1
        assert len(kafka_consumer.batch_handlers) == 1
        assert len(kafka_consumer.error_handlers) == 1
        assert test_event_handler in kafka_consumer.event_handlers
        assert test_batch_handler in kafka_consumer.batch_handlers
        assert test_error_handler in kafka_consumer.error_handlers

    @pytest.mark.asyncio
    async def test_message_processing(self, kafka_consumer):
        """Test message processing from Kafka."""
        events_processed = []

        def test_handler(event, record):
            events_processed.append(event)

        kafka_consumer.add_event_handler(test_handler)

        # Mock consumer record
        mock_record = Mock()
        mock_record.topic = "test-topic"
        mock_record.partition = 0
        mock_record.offset = 123
        mock_record.value_size = 1024
        mock_record.value = {
            "event_id": "test-123",
            "change_type": "node_created",
            "timestamp": datetime.now().isoformat(),
            "entity_id": "node-456",
            "entity_type": "node",
            "_kafka_metadata": {"sent_at": datetime.now().isoformat()},
        }

        # Process single message (simulate what happens in consume loop)
        event_data = mock_record.value.copy()
        del event_data["_kafka_metadata"]  # This gets removed

        event = GraphChangeEvent.from_dict(event_data)

        # Call handler
        kafka_consumer.event_handlers[0](event, mock_record)

        assert len(events_processed) == 1
        assert events_processed[0].event_id == "test-123"

    @pytest.mark.asyncio
    async def test_batch_processing(self, kafka_consumer):
        """Test batch message processing."""
        batches_processed = []

        def test_batch_handler(events, records):
            batches_processed.append((events, records))

        kafka_consumer.add_batch_handler(test_batch_handler)

        # Create test events and records
        events = []
        records = []
        for i in range(3):
            event = GraphChangeEvent(
                event_id=f"event-{i}",
                change_type=ChangeType.NODE_CREATED,
                timestamp=datetime.now(),
                entity_id=f"node-{i}",
                entity_type="node",
            )
            events.append(event)

            record = Mock()
            record.topic = "test-topic"
            record.partition = 0
            record.offset = i
            records.append(record)

        # Process batch
        await kafka_consumer._process_batch(events, records)

        assert len(batches_processed) == 1
        batch_events, batch_records = batches_processed[0]
        assert len(batch_events) == 3
        assert len(batch_records) == 3
        assert batch_events[0].event_id == "event-0"

    @pytest.mark.asyncio
    async def test_error_handling(self, kafka_consumer):
        """Test error handling during message processing."""
        errors_handled = []

        def test_error_handler(error, record):
            errors_handled.append((error, record))

        kafka_consumer.add_error_handler(test_error_handler)

        # Mock error and record
        test_error = Exception("Processing failed")
        mock_record = Mock()

        # Handle error
        await kafka_consumer._handle_error(test_error, mock_record)

        assert len(errors_handled) == 1
        error, record = errors_handled[0]
        assert str(error) == "Processing failed"
        assert record == mock_record

    @pytest.mark.asyncio
    async def test_lag_info(self, kafka_consumer):
        """Test consumer lag information retrieval."""
        # Mock consumer with assignment and methods
        mock_consumer = AsyncMock()
        mock_partition = Mock()
        mock_partition.topic = "test-topic"
        mock_partition.partition = 0

        mock_consumer.assignment.return_value = [mock_partition]
        mock_consumer.end_offsets.return_value = {mock_partition: 1000}
        mock_consumer.position.return_value = 800

        kafka_consumer.consumer = mock_consumer

        # Get lag info
        lag_info = await kafka_consumer.get_lag_info()

        assert "test-topic-0" in lag_info
        partition_info = lag_info["test-topic-0"]
        assert partition_info["topic"] == "test-topic"
        assert partition_info["partition"] == 0
        assert partition_info["current_offset"] == 800
        assert partition_info["high_water_mark"] == 1000
        assert partition_info["lag"] == 200

    def test_get_stats(self, kafka_consumer):
        """Test getting consumer statistics."""
        # Set some test stats
        kafka_consumer.stats["messages_consumed"] = 50
        kafka_consumer.stats["bytes_consumed"] = 5120
        kafka_consumer.stats["last_consume_time"] = datetime.now()

        # Add handlers
        kafka_consumer.add_event_handler(lambda e, r: None)
        kafka_consumer.add_batch_handler(lambda es, rs: None)

        stats = kafka_consumer.get_stats()

        assert stats["is_running"] == False
        assert stats["topics"] == [kafka_consumer.config.default_topic]
        assert stats["messages_consumed"] == 50
        assert stats["bytes_consumed"] == 5120
        assert stats["event_handlers"] == 1
        assert stats["batch_handlers"] == 1
        assert "last_consume_time" in stats


class TestIntegrationHelpers:
    """Test integration helper functions."""

    @pytest.mark.asyncio
    async def test_cdc_kafka_integration(self):
        """Test CDC to Kafka integration helper."""
        # Mock CDC processor
        mock_cdc_processor = Mock()
        mock_cdc_processor.add_event_handler = Mock()

        # Mock Kafka producer
        mock_kafka_producer = Mock()
        mock_kafka_producer.send_event = AsyncMock()

        # Create integration
        handler = create_cdc_kafka_integration(mock_cdc_processor, mock_kafka_producer)

        # Verify handler was registered
        mock_cdc_processor.add_event_handler.assert_called_once()
        registered_handler = mock_cdc_processor.add_event_handler.call_args[0][0]

        # Test handler functionality
        test_event = GraphChangeEvent(
            event_id="test-123",
            change_type=ChangeType.NODE_CREATED,
            timestamp=datetime.now(),
            entity_id="node-456",
            entity_type="node",
        )

        with patch("asyncio.create_task") as mock_create_task:
            registered_handler(test_event)
            mock_create_task.assert_called_once()

    @pytest.mark.asyncio
    async def test_kafka_subscription_integration(self):
        """Test Kafka to subscription system integration."""
        # Mock Kafka consumer
        mock_kafka_consumer = Mock()
        mock_kafka_consumer.add_event_handler = Mock()

        # Mock subscription system
        mock_subscription_system = Mock()

        # Create integration
        handler = create_kafka_subscription_integration(
            mock_kafka_consumer, mock_subscription_system
        )

        # Verify handler was registered
        mock_kafka_consumer.add_event_handler.assert_called_once()
        registered_handler = mock_kafka_consumer.add_event_handler.call_args[0][0]

        # Test handler functionality
        test_event = GraphChangeEvent(
            event_id="test-123",
            change_type=ChangeType.NODE_CREATED,
            timestamp=datetime.now(),
            entity_id="node-456",
            entity_type="node",
            user_id="user-123",
        )

        mock_record = Mock()
        mock_record.topic = "test-topic"
        mock_record.partition = 0
        mock_record.offset = 123

        with patch("asyncio.create_task") as mock_create_task:
            registered_handler(test_event, mock_record)
            mock_create_task.assert_called_once()


@pytest.mark.asyncio
async def test_end_to_end_messaging():
    """Test end-to-end message flow."""
    with patch(
        "brain_researcher.services.br_kg.streaming.kafka_integration.AIOKafkaProducer"
    ):
        with patch(
            "brain_researcher.services.br_kg.streaming.kafka_integration.AIOKafkaConsumer"
        ):
            config = StreamConfig(default_topic="test-topic")

            # Create producer and consumer
            producer = KafkaProducer(config)
            consumer = KafkaConsumer(config)

            # Mock successful operations
            producer.send_event = AsyncMock(return_value=True)

            messages_received = []

            def message_handler(event, record):
                messages_received.append(event)

            consumer.add_event_handler(message_handler)

            # Create test event
            test_event = GraphChangeEvent(
                event_id="e2e-test",
                change_type=ChangeType.NODE_UPDATED,
                timestamp=datetime.now(),
                entity_id="node-123",
                entity_type="node",
                old_properties={"name": "Old"},
                new_properties={"name": "New"},
            )

            # Send event through producer
            result = await producer.send_event(test_event)
            assert result is True

            # Simulate consumer receiving the message
            message_handler(test_event, Mock())

            # Verify message was processed
            assert len(messages_received) == 1
            assert messages_received[0].event_id == "e2e-test"


@pytest.mark.asyncio
async def test_concurrent_operations():
    """Test concurrent producer/consumer operations."""
    with patch(
        "brain_researcher.services.br_kg.streaming.kafka_integration.AIOKafkaProducer"
    ):
        with patch(
            "brain_researcher.services.br_kg.streaming.kafka_integration.AIOKafkaConsumer"
        ):
            config = StreamConfig()
            producer = KafkaProducer(config)

            # Mock successful sends
            producer.send_event = AsyncMock(return_value=True)

            # Send many events concurrently
            events = []
            for i in range(100):
                event = GraphChangeEvent(
                    event_id=f"concurrent-{i}",
                    change_type=ChangeType.NODE_CREATED,
                    timestamp=datetime.now(),
                    entity_id=f"node-{i}",
                    entity_type="node",
                )
                events.append(event)

            # Send all events concurrently
            tasks = [producer.send_event(event) for event in events]
            results = await asyncio.gather(*tasks)

            # All should succeed
            assert all(results)
            assert producer.send_event.call_count == 100


if __name__ == "__main__":
    pytest.main([__file__])
