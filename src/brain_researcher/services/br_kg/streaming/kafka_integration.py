"""Kafka integration for distributed streaming - completes KG-034 streaming.

This module provides Kafka producer/consumer integration for distributed
event streaming, enabling scalable real-time processing across multiple
services and geographic regions.
"""

import logging
import asyncio
import json
from typing import Dict, List, Any, Optional, Callable, AsyncIterator
from dataclasses import dataclass, field, asdict
from datetime import datetime
from enum import Enum
import uuid
from collections import defaultdict

try:
    from aiokafka import AIOKafkaProducer, AIOKafkaConsumer, ConsumerRecord
    from aiokafka.errors import KafkaError
    from kafka.admin import KafkaAdminClient, NewTopic
    from kafka.errors import TopicAlreadyExistsError
except ImportError:
    AIOKafkaProducer = None
    AIOKafkaConsumer = None
    ConsumerRecord = None
    KafkaError = Exception
    KafkaAdminClient = None
    NewTopic = None
    TopicAlreadyExistsError = Exception

from .cdc_processor import GraphChangeEvent

logger = logging.getLogger(__name__)


@dataclass
class StreamConfig:
    """Configuration for Kafka streaming."""

    bootstrap_servers: str = "localhost:9092"
    security_protocol: str = "PLAINTEXT"
    sasl_mechanism: Optional[str] = None
    sasl_plain_username: Optional[str] = None
    sasl_plain_password: Optional[str] = None

    # Topic configuration
    default_topic: str = "brain-researcher-graph-events"
    topic_partitions: int = 3
    topic_replication_factor: int = 1

    # Producer settings
    producer_batch_size: int = 16384
    producer_linger_ms: int = 100
    producer_acks: str = "1"
    producer_retries: int = 3

    # Consumer settings
    consumer_group_id: str = "brain-researcher-consumers"
    consumer_auto_offset_reset: str = "latest"
    consumer_enable_auto_commit: bool = True
    consumer_auto_commit_interval_ms: int = 1000

    # Stream processing
    max_poll_records: int = 500
    session_timeout_ms: int = 30000
    heartbeat_interval_ms: int = 3000

    def to_producer_config(self) -> Dict[str, Any]:
        """Get producer configuration."""
        config = {
            "bootstrap_servers": self.bootstrap_servers,
            "security_protocol": self.security_protocol,
            "batch_size": self.producer_batch_size,
            "linger_ms": self.producer_linger_ms,
            "acks": self.producer_acks,
            "retries": self.producer_retries,
            "value_serializer": lambda v: json.dumps(v).encode(),
            "key_serializer": lambda v: str(v).encode() if v else None,
        }

        if self.sasl_mechanism:
            config.update({
                "sasl_mechanism": self.sasl_mechanism,
                "sasl_plain_username": self.sasl_plain_username,
                "sasl_plain_password": self.sasl_plain_password,
            })

        return config

    def to_consumer_config(self) -> Dict[str, Any]:
        """Get consumer configuration."""
        config = {
            "bootstrap_servers": self.bootstrap_servers,
            "security_protocol": self.security_protocol,
            "group_id": self.consumer_group_id,
            "auto_offset_reset": self.consumer_auto_offset_reset,
            "enable_auto_commit": self.consumer_enable_auto_commit,
            "auto_commit_interval_ms": self.consumer_auto_commit_interval_ms,
            "max_poll_records": self.max_poll_records,
            "session_timeout_ms": self.session_timeout_ms,
            "heartbeat_interval_ms": self.heartbeat_interval_ms,
            "value_deserializer": lambda m: json.loads(m.decode()) if m else None,
            "key_deserializer": lambda m: m.decode() if m else None,
        }

        if self.sasl_mechanism:
            config.update({
                "sasl_mechanism": self.sasl_mechanism,
                "sasl_plain_username": self.sasl_plain_username,
                "sasl_plain_password": self.sasl_plain_password,
            })

        return config


class KafkaStreamingError(Exception):
    """Kafka streaming related errors."""
    pass


class KafkaProducer:
    """Kafka producer for publishing graph events."""

    def __init__(self, config: StreamConfig):
        """Initialize Kafka producer.

        Args:
            config: Stream configuration
        """
        if AIOKafkaProducer is None:
            raise ImportError("aiokafka is required for Kafka streaming")

        self.config = config
        self.producer: Optional[AIOKafkaProducer] = None
        self.is_running = False

        # Statistics
        self.stats = {
            "messages_sent": 0,
            "bytes_sent": 0,
            "send_errors": 0,
            "last_send_time": None,
            "messages_by_topic": defaultdict(int)
        }

    async def start(self):
        """Start the Kafka producer."""
        if self.is_running:
            logger.warning("Kafka producer is already running")
            return

        try:
            # Ensure topics exist
            await self._ensure_topics()

            # Initialize producer
            producer_config = self.config.to_producer_config()
            self.producer = AIOKafkaProducer(**producer_config)

            await self.producer.start()
            self.is_running = True

            logger.info("Kafka producer started")

        except Exception as e:
            logger.error(f"Failed to start Kafka producer: {e}", exc_info=True)
            raise KafkaStreamingError(f"Failed to start Kafka producer: {e}")

    async def stop(self):
        """Stop the Kafka producer."""
        if not self.is_running:
            return

        self.is_running = False

        if self.producer:
            await self.producer.stop()
            self.producer = None

        logger.info("Kafka producer stopped")

    async def _ensure_topics(self):
        """Ensure required topics exist."""
        if KafkaAdminClient is None:
            logger.warning("kafka-python not available, cannot create topics")
            return

        try:
            admin_client = KafkaAdminClient(
                bootstrap_servers=self.config.bootstrap_servers,
                security_protocol=self.config.security_protocol,
            )

            topics_to_create = [
                NewTopic(
                    name=self.config.default_topic,
                    num_partitions=self.config.topic_partitions,
                    replication_factor=self.config.topic_replication_factor
                ),
                NewTopic(
                    name=f"{self.config.default_topic}-dlq",
                    num_partitions=1,
                    replication_factor=self.config.topic_replication_factor
                )
            ]

            try:
                admin_client.create_topics(topics_to_create)
                logger.info("Created Kafka topics")
            except TopicAlreadyExistsError:
                logger.debug("Topics already exist")

            admin_client.close()

        except Exception as e:
            logger.warning(f"Could not ensure topics exist: {e}")

    async def send_event(
        self,
        event: GraphChangeEvent,
        topic: Optional[str] = None,
        key: Optional[str] = None,
        headers: Optional[Dict[str, str]] = None
    ) -> bool:
        """Send a graph change event to Kafka.

        Args:
            event: Graph change event to send
            topic: Target topic (defaults to configured topic)
            key: Message key for partitioning
            headers: Optional message headers

        Returns:
            True if sent successfully
        """
        if not self.is_running or not self.producer:
            logger.warning("Kafka producer not running")
            return False

        topic = topic or self.config.default_topic
        key = key or event.entity_id or event.event_id

        # Prepare message
        message = event.to_dict()
        message["_kafka_metadata"] = {
            "producer_id": str(uuid.uuid4()),
            "sent_at": datetime.now().isoformat(),
            "topic": topic,
            "key": key
        }

        # Prepare headers
        kafka_headers = {}
        if headers:
            kafka_headers.update(headers)
        kafka_headers.update({
            "event_type": event.change_type.value,
            "entity_type": event.entity_type,
            "timestamp": event.timestamp.isoformat()
        })

        try:
            # Send to Kafka
            future = await self.producer.send(
                topic=topic,
                value=message,
                key=key,
                headers=[(k, v.encode()) for k, v in kafka_headers.items()]
            )

            # Update statistics
            self.stats["messages_sent"] += 1
            self.stats["bytes_sent"] += len(json.dumps(message).encode())
            self.stats["last_send_time"] = datetime.now()
            self.stats["messages_by_topic"][topic] += 1

            logger.debug(f"Sent event {event.event_id} to topic {topic}")
            return True

        except Exception as e:
            logger.error(f"Failed to send event to Kafka: {e}", exc_info=True)
            self.stats["send_errors"] += 1

            # Try to send to dead letter queue
            await self._send_to_dlq(event, topic, str(e))
            return False

    async def _send_to_dlq(self, event: GraphChangeEvent, original_topic: str, error: str):
        """Send failed event to dead letter queue."""
        dlq_topic = f"{self.config.default_topic}-dlq"

        dlq_message = {
            "original_event": event.to_dict(),
            "original_topic": original_topic,
            "error": error,
            "failed_at": datetime.now().isoformat(),
            "producer_id": str(uuid.uuid4())
        }

        try:
            await self.producer.send(
                topic=dlq_topic,
                value=dlq_message,
                key=event.event_id
            )
            logger.info(f"Sent failed event {event.event_id} to DLQ")
        except Exception as e:
            logger.error(f"Failed to send to DLQ: {e}", exc_info=True)

    async def send_batch(
        self,
        events: List[GraphChangeEvent],
        topic: Optional[str] = None,
        key_func: Optional[Callable[[GraphChangeEvent], str]] = None
    ) -> int:
        """Send a batch of events to Kafka.

        Args:
            events: List of events to send
            topic: Target topic
            key_func: Function to generate keys from events

        Returns:
            Number of successfully sent events
        """
        if not events:
            return 0

        sent_count = 0

        for event in events:
            key = key_func(event) if key_func else None
            if await self.send_event(event, topic=topic, key=key):
                sent_count += 1

        logger.info(f"Sent {sent_count}/{len(events)} events in batch")
        return sent_count

    def get_stats(self) -> Dict[str, Any]:
        """Get producer statistics."""
        return {
            "is_running": self.is_running,
            "config": asdict(self.config),
            **self.stats,
            "last_send_time": self.stats["last_send_time"].isoformat() if self.stats["last_send_time"] else None
        }


class KafkaConsumer:
    """Kafka consumer for processing graph events."""

    def __init__(self, config: StreamConfig, topics: Optional[List[str]] = None):
        """Initialize Kafka consumer.

        Args:
            config: Stream configuration
            topics: Topics to subscribe to
        """
        if AIOKafkaConsumer is None:
            raise ImportError("aiokafka is required for Kafka streaming")

        self.config = config
        self.topics = topics or [config.default_topic]
        self.consumer: Optional[AIOKafkaConsumer] = None
        self.is_running = False

        # Event handlers
        self.event_handlers: List[Callable[[GraphChangeEvent, ConsumerRecord], None]] = []
        self.batch_handlers: List[Callable[[List[GraphChangeEvent], List[ConsumerRecord]], None]] = []
        self.error_handlers: List[Callable[[Exception, ConsumerRecord], None]] = []

        # Statistics
        self.stats = {
            "messages_consumed": 0,
            "bytes_consumed": 0,
            "consumption_errors": 0,
            "last_consume_time": None,
            "messages_by_topic": defaultdict(int),
            "lag_by_partition": {}
        }

        # Background tasks
        self.tasks: List[asyncio.Task] = []

    async def start(self):
        """Start the Kafka consumer."""
        if self.is_running:
            logger.warning("Kafka consumer is already running")
            return

        try:
            # Initialize consumer
            consumer_config = self.config.to_consumer_config()
            self.consumer = AIOKafkaConsumer(*self.topics, **consumer_config)

            await self.consumer.start()
            self.is_running = True

            # Start background tasks
            self.tasks.append(asyncio.create_task(self._consume_loop()))

            logger.info(f"Kafka consumer started for topics: {self.topics}")

        except Exception as e:
            logger.error(f"Failed to start Kafka consumer: {e}", exc_info=True)
            raise KafkaStreamingError(f"Failed to start Kafka consumer: {e}")

    async def stop(self):
        """Stop the Kafka consumer."""
        if not self.is_running:
            return

        self.is_running = False

        # Cancel background tasks
        for task in self.tasks:
            task.cancel()

        if self.consumer:
            await self.consumer.stop()
            self.consumer = None

        logger.info("Kafka consumer stopped")

    async def _consume_loop(self):
        """Main consumption loop."""
        batch = []
        records = []

        try:
            async for record in self.consumer:
                if not self.is_running:
                    break

                try:
                    # Parse event
                    event_data = record.value
                    if event_data and "_kafka_metadata" in event_data:
                        # Remove Kafka metadata
                        event_data = {k: v for k, v in event_data.items() if k != "_kafka_metadata"}

                    event = GraphChangeEvent.from_dict(event_data)

                    # Update statistics
                    self.stats["messages_consumed"] += 1
                    self.stats["bytes_consumed"] += len(record.value_size or 0)
                    self.stats["last_consume_time"] = datetime.now()
                    self.stats["messages_by_topic"][record.topic] += 1

                    # Process individual event handlers
                    for handler in self.event_handlers:
                        try:
                            handler(event, record)
                        except Exception as e:
                            logger.error(f"Error in event handler: {e}", exc_info=True)
                            await self._handle_error(e, record)

                    # Accumulate for batch processing
                    batch.append(event)
                    records.append(record)

                    # Process batch when full
                    if len(batch) >= self.config.max_poll_records:
                        await self._process_batch(batch, records)
                        batch.clear()
                        records.clear()

                except Exception as e:
                    logger.error(f"Error processing message: {e}", exc_info=True)
                    self.stats["consumption_errors"] += 1
                    await self._handle_error(e, record)

        except asyncio.CancelledError:
            # Process remaining batch
            if batch:
                await self._process_batch(batch, records)
        except Exception as e:
            logger.error(f"Error in consumption loop: {e}", exc_info=True)

    async def _process_batch(self, events: List[GraphChangeEvent], records: List[ConsumerRecord]):
        """Process a batch of events."""
        if not events:
            return

        for handler in self.batch_handlers:
            try:
                handler(events, records)
            except Exception as e:
                logger.error(f"Error in batch handler: {e}", exc_info=True)

        logger.debug(f"Processed batch of {len(events)} events")

    async def _handle_error(self, error: Exception, record: ConsumerRecord):
        """Handle processing errors."""
        for handler in self.error_handlers:
            try:
                handler(error, record)
            except Exception as e:
                logger.error(f"Error in error handler: {e}", exc_info=True)

    def add_event_handler(self, handler: Callable[[GraphChangeEvent, ConsumerRecord], None]):
        """Add an event handler for individual events.

        Args:
            handler: Function that processes individual events
        """
        self.event_handlers.append(handler)
        logger.info(f"Added event handler: {handler.__name__}")

    def add_batch_handler(self, handler: Callable[[List[GraphChangeEvent], List[ConsumerRecord]], None]):
        """Add a batch handler for processing event batches.

        Args:
            handler: Function that processes event batches
        """
        self.batch_handlers.append(handler)
        logger.info(f"Added batch handler: {handler.__name__}")

    def add_error_handler(self, handler: Callable[[Exception, ConsumerRecord], None]):
        """Add an error handler.

        Args:
            handler: Function that handles errors
        """
        self.error_handlers.append(handler)
        logger.info(f"Added error handler: {handler.__name__}")

    async def get_lag_info(self) -> Dict[str, Any]:
        """Get consumer lag information."""
        if not self.consumer:
            return {}

        try:
            lag_info = {}

            # Get assigned partitions
            assignment = self.consumer.assignment()

            for partition in assignment:
                # Get high water mark
                high_water_mark = await self.consumer.end_offsets([partition])

                # Get current position
                position = await self.consumer.position(partition)

                # Calculate lag
                lag = high_water_mark.get(partition, 0) - position

                lag_info[f"{partition.topic}-{partition.partition}"] = {
                    "topic": partition.topic,
                    "partition": partition.partition,
                    "current_offset": position,
                    "high_water_mark": high_water_mark.get(partition, 0),
                    "lag": lag
                }

            return lag_info

        except Exception as e:
            logger.error(f"Failed to get lag info: {e}", exc_info=True)
            return {}

    def get_stats(self) -> Dict[str, Any]:
        """Get consumer statistics."""
        return {
            "is_running": self.is_running,
            "topics": self.topics,
            "config": asdict(self.config),
            "event_handlers": len(self.event_handlers),
            "batch_handlers": len(self.batch_handlers),
            "error_handlers": len(self.error_handlers),
            **self.stats,
            "last_consume_time": self.stats["last_consume_time"].isoformat() if self.stats["last_consume_time"] else None
        }


# Integration helpers
def create_cdc_kafka_integration(cdc_processor, kafka_producer: KafkaProducer) -> Callable:
    """Create integration between CDC processor and Kafka producer.

    Args:
        cdc_processor: CDC processor instance
        kafka_producer: Kafka producer instance

    Returns:
        Handler function for CDC events
    """
    def cdc_to_kafka_handler(event: GraphChangeEvent):
        """Handle CDC events and send to Kafka."""
        asyncio.create_task(kafka_producer.send_event(event))

    cdc_processor.add_event_handler(cdc_to_kafka_handler)
    logger.info("Integrated CDC processor with Kafka producer")

    return cdc_to_kafka_handler


def create_kafka_subscription_integration(kafka_consumer: KafkaConsumer, subscription_system) -> Callable:
    """Create integration between Kafka consumer and subscription system.

    Args:
        kafka_consumer: Kafka consumer instance
        subscription_system: Subscription system instance

    Returns:
        Handler function for Kafka events
    """
    from ..subscriptions.subscription_system import Event, EventType

    def kafka_to_subscription_handler(event: GraphChangeEvent, record: ConsumerRecord):
        """Handle Kafka events and publish to subscription system."""
        # Convert to subscription event
        type_mapping = {
            "node_created": EventType.NODE_CREATED,
            "node_updated": EventType.NODE_UPDATED,
            "node_deleted": EventType.NODE_DELETED,
            "relationship_created": EventType.EDGE_CREATED,
            "relationship_updated": EventType.EDGE_UPDATED,
            "relationship_deleted": EventType.EDGE_DELETED,
        }

        event_type = type_mapping.get(event.change_type.value, EventType.GRAPH_CHANGED)

        subscription_event = Event(
            event_id=event.event_id,
            event_type=event_type,
            entity_type=event.entity_type,
            entity_id=event.entity_id or "",
            data=event.to_dict(),
            user_id=event.user_id,
            timestamp=event.timestamp,
            metadata={
                **event.metadata,
                "kafka_topic": record.topic,
                "kafka_partition": record.partition,
                "kafka_offset": record.offset
            }
        )

        asyncio.create_task(subscription_system.publish_event(subscription_event))

    kafka_consumer.add_event_handler(kafka_to_subscription_handler)
    logger.info("Integrated Kafka consumer with subscription system")

    return kafka_to_subscription_handler