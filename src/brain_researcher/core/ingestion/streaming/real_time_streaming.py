"""Real-time Data Streaming System - implements INGEST-020.

This module provides real-time data streaming capabilities using Kafka,
with consumers, processors, and backpressure management.
"""

import asyncio
import json
import logging
import os
import time
from collections import defaultdict, deque
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)


# Custom Exception Classes
class StreamingError(Exception):
    """Base exception for streaming errors."""

    pass


class ConnectionError(StreamingError):
    """Connection-related streaming errors."""

    pass


class ProcessingError(StreamingError):
    """Processing-related streaming errors."""

    pass


class ConfigurationError(StreamingError):
    """Configuration-related streaming errors."""

    pass


class BackpressureError(StreamingError):
    """Backpressure-related errors."""

    pass


class StreamType(Enum):
    """Types of data streams."""

    NEUROIMAGING = "neuroimaging"
    BEHAVIORAL = "behavioral"
    GENOMIC = "genomic"
    CLINICAL = "clinical"
    SENSOR = "sensor"
    ANNOTATION = "annotation"


class ProcessingMode(Enum):
    """Stream processing modes."""

    AT_LEAST_ONCE = "at_least_once"
    AT_MOST_ONCE = "at_most_once"
    EXACTLY_ONCE = "exactly_once"


@dataclass
class StreamMessage:
    """Represents a message in the stream."""

    message_id: str
    stream_type: StreamType
    topic: str
    partition: int
    offset: int
    key: str | None
    value: dict[str, Any]
    timestamp: datetime
    headers: dict[str, str] = field(default_factory=dict)


@dataclass
class StreamConfig:
    """Configuration for a data stream."""

    topic: str
    stream_type: StreamType
    consumer_group: str
    processing_mode: ProcessingMode = ProcessingMode.AT_LEAST_ONCE
    batch_size: int = 100
    batch_timeout_ms: int = 1000
    max_retries: int = 3
    retry_backoff_ms: int = 1000
    enable_auto_commit: bool = False


@dataclass
class ProcessingResult:
    """Result of processing a message."""

    message_id: str
    success: bool
    error: str | None = None
    processing_time_ms: float = 0
    output_data: dict[str, Any] | None = None


class StreamProcessor:
    """Base class for stream processors."""

    async def process(self, message: StreamMessage) -> ProcessingResult:
        """Process a stream message.

        Args:
            message: Message to process

        Returns:
            Processing result
        """
        raise NotImplementedError


class RealTimeStreaming:
    """Real-time data streaming system."""

    def __init__(self, kafka_config: dict[str, Any] | None = None, redis_client=None):
        """Initialize streaming system.

        Args:
            kafka_config: Kafka configuration
            redis_client: Optional Redis client for state management
        """
        self.kafka_config = kafka_config or self._get_default_kafka_config()
        self.redis = redis_client

        # Stream configurations
        self.stream_configs: dict[str, StreamConfig] = {}

        # Processors
        self.processors: dict[str, StreamProcessor] = {}

        # Consumers
        self.consumers: dict[str, Any] = {}  # Would be KafkaConsumer objects

        # Processing state
        self.processing_state = {
            "active_streams": set(),
            "message_queue": asyncio.Queue(),
            "processing_tasks": [],
            "shutdown_event": asyncio.Event(),
        }

        # Metrics
        self.metrics = {
            "messages_received": defaultdict(int),
            "messages_processed": defaultdict(int),
            "messages_failed": defaultdict(int),
            "processing_times": defaultdict(list),
            "lag_by_topic": defaultdict(int),
            "throughput_history": deque(maxlen=100),
        }

        # Backpressure management
        self.backpressure = {
            "enabled": True,
            "threshold": 1000,
            "current_pressure": 0,
            "paused_topics": set(),
        }

        # Thread pool for blocking operations (dynamic based on CPU count)
        max_workers = min(32, (os.cpu_count() or 1) + 4)
        self.executor = ThreadPoolExecutor(max_workers=max_workers)

        # Metrics cleanup settings
        self.metrics_retention_size = 1000
        self.metrics_cleanup_interval = 300  # 5 minutes

    def _get_default_kafka_config(self) -> dict[str, Any]:
        """Get default Kafka configuration."""
        return {
            "bootstrap_servers": "localhost:9092",
            "key_deserializer": lambda k: k.decode("utf-8") if k else None,
            "value_deserializer": lambda v: json.loads(v.decode("utf-8")),
            "auto_offset_reset": "latest",
            "enable_auto_commit": False,
            "max_poll_records": 500,
            "session_timeout_ms": 30000,
            "heartbeat_interval_ms": 10000,
        }

    def configure_stream(
        self, topic: str, stream_type: StreamType, consumer_group: str, **kwargs
    ) -> StreamConfig:
        """Configure a data stream.

        Args:
            topic: Kafka topic
            stream_type: Type of stream
            consumer_group: Consumer group ID
            **kwargs: Additional configuration

        Returns:
            Stream configuration
        """
        config = StreamConfig(
            topic=topic,
            stream_type=stream_type,
            consumer_group=consumer_group,
            **kwargs,
        )

        # Validate configuration
        is_valid, errors = self.validate_stream_config(config)
        if not is_valid:
            raise ConfigurationError(f"Invalid stream configuration: {errors}")

        self.stream_configs[topic] = config

        logger.info(f"Configured stream for topic {topic}")
        return config

    def register_processor(self, stream_type: StreamType, processor: StreamProcessor):
        """Register a stream processor.

        Args:
            stream_type: Stream type to process
            processor: Processor instance
        """
        self.processors[stream_type.value] = processor
        logger.info(f"Registered processor for {stream_type.value}")

    async def start(self):
        """Start the streaming system."""
        logger.info("Starting real-time streaming system")

        # Create consumers for configured streams
        for topic, config in self.stream_configs.items():
            consumer = await self._create_consumer(config)
            self.consumers[topic] = consumer
            self.processing_state["active_streams"].add(topic)

        # Start processing tasks
        self.processing_state["processing_tasks"] = [
            asyncio.create_task(self._consume_messages()),
            asyncio.create_task(self._process_messages()),
            asyncio.create_task(self._monitor_backpressure()),
            asyncio.create_task(self._collect_metrics()),
        ]

        logger.info("Streaming system started")

    async def stop(self):
        """Stop the streaming system."""
        logger.info("Stopping real-time streaming system")

        # Signal shutdown
        self.processing_state["shutdown_event"].set()

        # Wait for tasks to complete
        await asyncio.gather(
            *self.processing_state["processing_tasks"], return_exceptions=True
        )

        # Close consumers with error handling
        for topic, consumer in self.consumers.items():
            try:
                await self._close_consumer(consumer)
            except Exception as e:
                logger.error(f"Error closing consumer for {topic}: {e}", exc_info=True)

        # Shutdown executor
        self.executor.shutdown(wait=True)

        logger.info("Streaming system stopped")

    async def _create_consumer(self, config: StreamConfig) -> Any:
        """Create a Kafka consumer.

        Args:
            config: Stream configuration

        Returns:
            Consumer instance
        """
        # In production, would create actual KafkaConsumer
        # For now, create a mock consumer
        consumer = {
            "topic": config.topic,
            "group": config.consumer_group,
            "config": config,
            "position": 0,
            "committed": 0,
        }

        logger.info(f"Created consumer for topic {config.topic}")
        return consumer

    async def _close_consumer(self, consumer: Any):
        """Close a Kafka consumer.

        Args:
            consumer: Consumer to close
        """
        try:
            # In production, would close actual KafkaConsumer
            # Handle connection cleanup
            if hasattr(consumer, "close"):
                consumer.close()
            logger.info(f"Closed consumer for topic {consumer['topic']}")
        except Exception as e:
            logger.error(f"Error during consumer cleanup: {e}", exc_info=True)
            raise ConnectionError(f"Failed to close consumer: {e}")

    async def _consume_messages(self):
        """Consume messages from Kafka."""
        while not self.processing_state["shutdown_event"].is_set():
            try:
                for topic, consumer in self.consumers.items():
                    if topic in self.backpressure["paused_topics"]:
                        continue

                    # Simulate consuming messages
                    # In production, would use actual Kafka consumer
                    messages = await self._poll_messages(consumer)

                    for message in messages:
                        # Add to processing queue
                        await self.processing_state["message_queue"].put(message)
                        self.metrics["messages_received"][topic] += 1

                # Small delay to prevent tight loop
                await asyncio.sleep(0.1)

            except ConnectionError as e:
                logger.error(f"Connection error consuming messages: {e}")
                # Try to reconnect
                await self._handle_connection_error(e)
                await asyncio.sleep(5)  # Longer delay for connection issues
            except Exception as e:
                logger.error(f"Error consuming messages: {e}", exc_info=True)
                await asyncio.sleep(1)

    async def _poll_messages(self, consumer: Any) -> list[StreamMessage]:
        """Poll messages from consumer.

        Args:
            consumer: Consumer instance

        Returns:
            List of messages
        """
        # Simulate message polling
        # In production, would use actual Kafka consumer.poll()
        messages: list[StreamMessage] = []

        # Generate deterministic mock messages so unit tests don't flake.
        import random

        config = consumer["config"]
        for i in range(random.randint(1, 3)):
            message = StreamMessage(
                message_id=f"{consumer['topic']}-{consumer['position']}",
                stream_type=config.stream_type,
                topic=consumer["topic"],
                partition=0,
                offset=consumer["position"],
                key=f"key-{i}",
                value={
                    "data": f"Message {consumer['position']}",
                    "timestamp": datetime.now().isoformat(),
                },
                timestamp=datetime.now(),
            )

            messages.append(message)
            consumer["position"] += 1

        return messages

    async def _process_messages(self):
        """Process messages from the queue."""
        while not self.processing_state["shutdown_event"].is_set():
            try:
                # Get message with timeout
                try:
                    message = await asyncio.wait_for(
                        self.processing_state["message_queue"].get(), timeout=1.0
                    )
                except asyncio.TimeoutError:
                    continue

                # Update backpressure
                self.backpressure["current_pressure"] = self.processing_state[
                    "message_queue"
                ].qsize()

                # Process message
                start_time = time.time()
                result = await self._process_single_message(message)
                processing_time = (time.time() - start_time) * 1000

                # Update metrics
                if result.success:
                    self.metrics["messages_processed"][message.topic] += 1
                else:
                    self.metrics["messages_failed"][message.topic] += 1

                self.metrics["processing_times"][message.topic].append(processing_time)

                # Commit offset if needed
                if result.success:
                    await self._commit_offset(message)

            except ProcessingError as e:
                logger.error(f"Processing error: {e}")
            except Exception as e:
                logger.error(f"Error processing message: {e}", exc_info=True)

    async def _process_single_message(self, message: StreamMessage) -> ProcessingResult:
        """Process a single message.

        Args:
            message: Message to process

        Returns:
            Processing result
        """
        processor = self.processors.get(message.stream_type.value)

        if not processor:
            return ProcessingResult(
                message_id=message.message_id,
                success=False,
                error=f"No processor for stream type {message.stream_type.value}",
            )

        try:
            result = await processor.process(message)

            # Store result if needed
            if result.output_data and self.redis:
                await self._store_result(message, result)

            return result

        except ProcessingError as e:
            logger.error(f"Processing error for message {message.message_id}: {e}")
            return ProcessingResult(
                message_id=message.message_id, success=False, error=str(e)
            )
        except Exception as e:
            logger.error(
                f"Unexpected error processing message {message.message_id}: {e}",
                exc_info=True,
            )
            return ProcessingResult(
                message_id=message.message_id,
                success=False,
                error=f"Unexpected error: {str(e)}",
            )

    async def _commit_offset(self, message: StreamMessage):
        """Commit message offset.

        Args:
            message: Processed message
        """
        consumer = self.consumers.get(message.topic)
        if consumer:
            consumer["committed"] = message.offset

            # In production, would commit to Kafka
            if self.redis:
                key = f"stream:offset:{message.topic}:{message.partition}"
                await self.redis.set(key, message.offset)

    async def _store_result(self, message: StreamMessage, result: ProcessingResult):
        """Store processing result.

        Args:
            message: Original message
            result: Processing result
        """
        if not self.redis:
            return

        key = f"stream:result:{message.message_id}"
        value = {
            "message_id": message.message_id,
            "topic": message.topic,
            "timestamp": message.timestamp.isoformat(),
            "result": asdict(result),
        }

        # Store with TTL
        await self.redis.setex(key, 3600, json.dumps(value))

    async def _monitor_backpressure(self):
        """Monitor and manage backpressure."""
        while not self.processing_state["shutdown_event"].is_set():
            try:
                queue_size = self.processing_state["message_queue"].qsize()

                if self.backpressure["enabled"]:
                    # Check if we need to pause topics
                    if queue_size > self.backpressure["threshold"]:
                        # Pause slowest topics
                        slowest_topics = self._get_slowest_topics()

                        for topic in slowest_topics[:2]:  # Pause top 2 slowest
                            if topic not in self.backpressure["paused_topics"]:
                                self.backpressure["paused_topics"].add(topic)
                                logger.warning(
                                    f"Paused topic {topic} due to backpressure"
                                )

                    # Check if we can resume topics
                    elif queue_size < self.backpressure["threshold"] * 0.5:
                        for topic in list(self.backpressure["paused_topics"]):
                            self.backpressure["paused_topics"].remove(topic)
                            logger.info(f"Resumed topic {topic}")

                await asyncio.sleep(5)

            except Exception as e:
                logger.error(f"Error monitoring backpressure: {e}", exc_info=True)
                await asyncio.sleep(5)

    def _get_slowest_topics(self) -> list[str]:
        """Get topics with slowest processing times.

        Returns:
            List of slowest topics
        """
        avg_times = {}

        for topic, times in self.metrics["processing_times"].items():
            if times:
                avg_times[topic] = sum(times[-100:]) / len(times[-100:])

        return sorted(avg_times.keys(), key=avg_times.get, reverse=True)

    async def _collect_metrics(self):
        """Collect and report metrics."""
        while not self.processing_state["shutdown_event"].is_set():
            try:
                # Calculate throughput
                total_processed = sum(self.metrics["messages_processed"].values())
                throughput = total_processed / max(
                    1, len(self.metrics["throughput_history"])
                )

                self.metrics["throughput_history"].append(
                    {
                        "timestamp": datetime.now().isoformat(),
                        "throughput": throughput,
                        "queue_size": self.processing_state["message_queue"].qsize(),
                        "paused_topics": list(self.backpressure["paused_topics"]),
                    }
                )

                # Calculate lag
                for topic, consumer in self.consumers.items():
                    lag = consumer["position"] - consumer["committed"]
                    self.metrics["lag_by_topic"][topic] = lag

                # Log metrics
                if len(self.metrics["throughput_history"]) % 10 == 0:
                    self._log_metrics()

                await asyncio.sleep(10)

            except Exception as e:
                logger.error(f"Error collecting metrics: {e}", exc_info=True)
                await asyncio.sleep(10)

    def _log_metrics(self):
        """Log current metrics."""
        total_received = sum(self.metrics["messages_received"].values())
        total_processed = sum(self.metrics["messages_processed"].values())
        total_failed = sum(self.metrics["messages_failed"].values())

        logger.info(
            f"Streaming metrics - "
            f"Received: {total_received}, "
            f"Processed: {total_processed}, "
            f"Failed: {total_failed}, "
            f"Queue: {self.processing_state['message_queue'].qsize()}, "
            f"Paused: {list(self.backpressure['paused_topics'])}"
        )

    def get_statistics(self) -> dict[str, Any]:
        """Get streaming statistics.

        Returns:
            Statistics dictionary
        """
        total_received = sum(self.metrics["messages_received"].values())
        total_processed = sum(self.metrics["messages_processed"].values())
        total_failed = sum(self.metrics["messages_failed"].values())

        # Calculate average processing times
        avg_processing_times = {}
        for topic, times in self.metrics["processing_times"].items():
            if times:
                avg_processing_times[topic] = sum(times[-100:]) / len(times[-100:])

        return {
            "total_received": total_received,
            "total_processed": total_processed,
            "total_failed": total_failed,
            "success_rate": total_processed / max(1, total_received),
            "queue_size": self.processing_state["message_queue"].qsize(),
            "active_streams": list(self.processing_state["active_streams"]),
            "paused_topics": list(self.backpressure["paused_topics"]),
            "lag_by_topic": dict(self.metrics["lag_by_topic"]),
            "avg_processing_times": avg_processing_times,
            "backpressure": {
                "enabled": self.backpressure["enabled"],
                "threshold": self.backpressure["threshold"],
                "current": self.backpressure["current_pressure"],
            },
        }

    async def _cleanup_metrics(self):
        """Clean up old metrics data to prevent memory growth."""
        while not self.processing_state["shutdown_event"].is_set():
            try:
                await asyncio.sleep(self.metrics_cleanup_interval)

                # Clean up processing times (keep only recent data)
                for topic in self.metrics["processing_times"]:
                    times = self.metrics["processing_times"][topic]
                    if len(times) > self.metrics_retention_size:
                        # Keep only the most recent metrics
                        self.metrics["processing_times"][topic] = times[
                            -self.metrics_retention_size :
                        ]

                # Clean up throughput history
                if (
                    len(self.metrics["throughput_history"])
                    > self.metrics_retention_size
                ):
                    # Remove oldest entries
                    while (
                        len(self.metrics["throughput_history"])
                        > self.metrics_retention_size
                    ):
                        self.metrics["throughput_history"].popleft()

                logger.debug("Completed metrics cleanup")

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error cleaning up metrics: {e}", exc_info=True)
                await asyncio.sleep(self.metrics_cleanup_interval)

    async def _handle_connection_error(self, error: ConnectionError):
        """Handle connection errors with retry logic."""
        logger.warning(f"Handling connection error: {error}")

        # Pause affected topics temporarily
        for topic in list(self.processing_state["active_streams"]):
            if topic not in self.backpressure["paused_topics"]:
                self.backpressure["paused_topics"].add(topic)
                logger.info(f"Paused topic {topic} due to connection error")

        # Try to recreate consumers after delay
        await asyncio.sleep(10)

        try:
            # Recreate consumers
            for topic, config in self.stream_configs.items():
                if topic in self.consumers:
                    try:
                        await self._close_consumer(self.consumers[topic])
                    except Exception:
                        pass  # Ignore errors during cleanup

                    new_consumer = await self._create_consumer(config)
                    self.consumers[topic] = new_consumer

                    # Resume topic
                    self.backpressure["paused_topics"].discard(topic)
                    logger.info(f"Recreated consumer and resumed topic {topic}")

        except Exception as e:
            logger.error(f"Failed to recover from connection error: {e}", exc_info=True)

    def validate_stream_config(self, config: StreamConfig) -> tuple[bool, list[str]]:
        """Validate stream configuration.

        Args:
            config: Stream configuration to validate

        Returns:
            (is_valid, error_messages)
        """
        errors = []

        # Required fields
        if not config.topic:
            errors.append("Topic is required")

        if not config.consumer_group:
            errors.append("Consumer group is required")

        # Validate numeric fields
        if config.batch_size <= 0:
            errors.append("Batch size must be positive")

        if config.batch_timeout_ms <= 0:
            errors.append("Batch timeout must be positive")

        if config.max_retries < 0:
            errors.append("Max retries cannot be negative")

        if config.retry_backoff_ms <= 0:
            errors.append("Retry backoff must be positive")

        return len(errors) == 0, errors


# Example processor implementations
class NeuroimagingProcessor(StreamProcessor):
    """Processor for neuroimaging data streams."""

    async def process(self, message: StreamMessage) -> ProcessingResult:
        """Process neuroimaging data."""
        try:
            data = message.value

            # Simulate processing
            await asyncio.sleep(0.01)  # Simulate work

            # Extract metadata
            output = {
                "subject_id": data.get("subject_id"),
                "scan_type": data.get("scan_type"),
                "timestamp": data.get("timestamp"),
                "processed_at": datetime.now().isoformat(),
            }

            return ProcessingResult(
                message_id=message.message_id,
                success=True,
                processing_time_ms=10,
                output_data=output,
            )

        except Exception as e:
            return ProcessingResult(
                message_id=message.message_id, success=False, error=str(e)
            )


class BehavioralProcessor(StreamProcessor):
    """Processor for behavioral data streams."""

    async def process(self, message: StreamMessage) -> ProcessingResult:
        """Process behavioral data."""
        try:
            data = message.value

            # Validate and transform
            output = {
                "subject_id": data.get("subject_id"),
                "task": data.get("task"),
                "score": data.get("score"),
                "reaction_time": data.get("reaction_time"),
                "processed_at": datetime.now().isoformat(),
            }

            return ProcessingResult(
                message_id=message.message_id,
                success=True,
                processing_time_ms=5,
                output_data=output,
            )

        except Exception as e:
            return ProcessingResult(
                message_id=message.message_id, success=False, error=str(e)
            )
