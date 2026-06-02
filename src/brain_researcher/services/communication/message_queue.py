"""
Message Queue and Event-Driven Communication.

Provides unified message queuing with Redis and RabbitMQ backends,
event bus patterns, and pub/sub capabilities for service communication.
"""

import asyncio
import json
import logging
import time
import uuid
from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, AsyncIterator, Callable, Dict, List, Optional, Union

import aio_pika
import pika
import redis.asyncio as redis
from aio_pika import DeliveryMode, Message
from aio_pika.abc import AbstractChannel, AbstractQueue, AbstractRobustConnection

logger = logging.getLogger(__name__)


class QueueBackend(str, Enum):
    """Message queue backend types."""

    REDIS = "redis"
    RABBITMQ = "rabbitmq"
    IN_MEMORY = "in_memory"


class MessagePriority(int, Enum):
    """Message priority levels."""

    LOW = 1
    NORMAL = 5
    HIGH = 8
    CRITICAL = 10


@dataclass
class QueueConfig:
    """Message queue configuration."""

    backend: QueueBackend = QueueBackend.REDIS
    redis_url: str = "redis://localhost:6379/0"
    rabbitmq_url: str = "amqp://localhost/"
    default_queue: str = "brain_researcher"
    max_retries: int = 3
    retry_delay_seconds: float = 1.0
    message_ttl_seconds: int = 3600
    dead_letter_queue: str = "brain_researcher_dlq"
    enable_persistence: bool = True
    batch_size: int = 100
    consumer_timeout_seconds: float = 30.0


@dataclass
class Message:
    """Message wrapper."""

    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    topic: str = ""
    data: Dict[str, Any] = field(default_factory=dict)
    metadata: Dict[str, str] = field(default_factory=dict)
    priority: MessagePriority = MessagePriority.NORMAL
    timestamp: datetime = field(default_factory=datetime.utcnow)
    correlation_id: Optional[str] = None
    reply_to: Optional[str] = None
    headers: Dict[str, str] = field(default_factory=dict)
    retry_count: int = 0
    max_retries: int = 3
    delay_until: Optional[datetime] = None

    def to_json(self) -> str:
        """Serialize message to JSON."""
        data = asdict(self)
        # Convert datetime objects to ISO strings
        data["timestamp"] = self.timestamp.isoformat()
        if self.delay_until:
            data["delay_until"] = self.delay_until.isoformat()
        return json.dumps(data)

    @classmethod
    def from_json(cls, json_str: str) -> "Message":
        """Deserialize message from JSON."""
        data = json.loads(json_str)
        # Convert ISO strings back to datetime objects
        data["timestamp"] = datetime.fromisoformat(data["timestamp"])
        if data.get("delay_until"):
            data["delay_until"] = datetime.fromisoformat(data["delay_until"])
        return cls(**data)

    def should_retry(self) -> bool:
        """Check if message should be retried."""
        return self.retry_count < self.max_retries

    def is_delayed(self) -> bool:
        """Check if message is delayed."""
        return self.delay_until and self.delay_until > datetime.utcnow()


class MessageHandler(ABC):
    """Abstract message handler."""

    @abstractmethod
    async def handle(self, message: Message) -> bool:
        """Handle a message.

        Args:
            message: Message to handle

        Returns:
            True if message was handled successfully
        """
        pass


class QueueBackendBase(ABC):
    """Abstract queue backend."""

    @abstractmethod
    async def connect(self):
        """Connect to queue backend."""
        pass

    @abstractmethod
    async def disconnect(self):
        """Disconnect from queue backend."""
        pass

    @abstractmethod
    async def publish(self, queue: str, message: Message):
        """Publish message to queue."""
        pass

    @abstractmethod
    async def consume(
        self, queue: str, handler: MessageHandler
    ) -> AsyncIterator[Message]:
        """Consume messages from queue."""
        pass

    @abstractmethod
    async def subscribe(self, topic: str, handler: MessageHandler):
        """Subscribe to topic."""
        pass

    @abstractmethod
    async def unsubscribe(self, topic: str):
        """Unsubscribe from topic."""
        pass


class RedisQueueBackend(QueueBackendBase):
    """Redis-based queue backend."""

    def __init__(self, config: QueueConfig):
        """Initialize Redis backend.

        Args:
            config: Queue configuration
        """
        self.config = config
        self.redis_client = None
        self.pubsub = None
        self.subscribers = {}
        self.running = False

    async def connect(self):
        """Connect to Redis."""
        try:
            self.redis_client = redis.from_url(
                self.config.redis_url, decode_responses=False
            )
            self.pubsub = self.redis_client.pubsub()
            logger.info("Connected to Redis message queue")

        except Exception as e:
            logger.error(f"Failed to connect to Redis: {e}")
            raise

    async def disconnect(self):
        """Disconnect from Redis."""
        self.running = False

        if self.pubsub:
            await self.pubsub.close()

        if self.redis_client:
            await self.redis_client.close()

        logger.info("Disconnected from Redis message queue")

    async def publish(self, queue: str, message: Message):
        """Publish message to Redis queue."""
        try:
            # Add to queue with priority
            score = -message.priority.value  # Negative for high priority first
            await self.redis_client.zadd(f"queue:{queue}", {message.to_json(): score})

            # Notify consumers
            await self.redis_client.publish(f"queue:{queue}:notify", "1")

        except Exception as e:
            logger.error(f"Failed to publish message to Redis queue {queue}: {e}")
            raise

    async def consume(
        self, queue: str, handler: MessageHandler
    ) -> AsyncIterator[Message]:
        """Consume messages from Redis queue."""
        queue_key = f"queue:{queue}"
        notify_key = f"queue:{queue}:notify"

        # Subscribe to notifications
        await self.pubsub.subscribe(notify_key)

        try:
            self.running = True

            while self.running:
                # Check for delayed messages first
                await self._process_delayed_messages(queue)

                # Get highest priority message
                result = await self.redis_client.zpopmin(queue_key, 1)

                if result:
                    message_json, _ = result[0]
                    try:
                        message = Message.from_json(message_json.decode())

                        # Handle message
                        success = await handler.handle(message)

                        if not success and message.should_retry():
                            # Retry message
                            message.retry_count += 1
                            message.delay_until = datetime.utcnow() + timedelta(
                                seconds=self.config.retry_delay_seconds
                                * message.retry_count
                            )

                            # Add to delayed queue
                            await self._add_delayed_message(queue, message)
                        elif not success:
                            # Send to dead letter queue
                            await self._send_to_dlq(queue, message)

                        yield message

                    except Exception as e:
                        logger.error(f"Error processing message: {e}")

                else:
                    # Wait for notification
                    try:
                        await asyncio.wait_for(
                            self.pubsub.get_message(ignore_subscribe_messages=True),
                            timeout=self.config.consumer_timeout_seconds,
                        )
                    except asyncio.TimeoutError:
                        pass

        except Exception as e:
            logger.error(f"Error consuming from Redis queue {queue}: {e}")
        finally:
            await self.pubsub.unsubscribe(notify_key)

    async def subscribe(self, topic: str, handler: MessageHandler):
        """Subscribe to Redis pub/sub topic."""
        try:
            self.subscribers[topic] = handler
            await self.pubsub.subscribe(f"topic:{topic}")

            # Start message processor if not running
            if not hasattr(self, "_pubsub_task"):
                self._pubsub_task = asyncio.create_task(self._process_pubsub_messages())

        except Exception as e:
            logger.error(f"Failed to subscribe to Redis topic {topic}: {e}")
            raise

    async def unsubscribe(self, topic: str):
        """Unsubscribe from Redis pub/sub topic."""
        try:
            if topic in self.subscribers:
                del self.subscribers[topic]
                await self.pubsub.unsubscribe(f"topic:{topic}")

        except Exception as e:
            logger.error(f"Failed to unsubscribe from Redis topic {topic}: {e}")

    async def _process_pubsub_messages(self):
        """Process pub/sub messages."""
        try:
            async for message in self.pubsub.listen():
                if message["type"] == "message":
                    channel = message["channel"].decode()

                    if channel.startswith("topic:"):
                        topic = channel[6:]  # Remove 'topic:' prefix

                        if topic in self.subscribers:
                            try:
                                msg_data = json.loads(message["data"].decode())
                                msg = Message(**msg_data)
                                await self.subscribers[topic].handle(msg)

                            except Exception as e:
                                logger.error(f"Error handling pub/sub message: {e}")

        except Exception as e:
            logger.error(f"Error in pub/sub message processor: {e}")

    async def _process_delayed_messages(self, queue: str):
        """Process delayed messages that are ready."""
        delayed_key = f"queue:{queue}:delayed"
        now = datetime.utcnow().timestamp()

        # Get messages ready for processing
        ready_messages = await self.redis_client.zrangebyscore(
            delayed_key, 0, now, withscores=True
        )

        for message_json, score in ready_messages:
            try:
                message = Message.from_json(message_json.decode())

                # Move back to main queue
                await self.redis_client.zrem(delayed_key, message_json)
                await self.publish(queue, message)

            except Exception as e:
                logger.error(f"Error processing delayed message: {e}")

    async def _add_delayed_message(self, queue: str, message: Message):
        """Add message to delayed queue."""
        if message.delay_until:
            delayed_key = f"queue:{queue}:delayed"
            await self.redis_client.zadd(
                delayed_key, {message.to_json(): message.delay_until.timestamp()}
            )

    async def _send_to_dlq(self, queue: str, message: Message):
        """Send message to dead letter queue."""
        dlq_key = f"queue:{self.config.dead_letter_queue}"

        # Add metadata about original queue
        message.metadata["original_queue"] = queue
        message.metadata["failed_at"] = datetime.utcnow().isoformat()

        await self.redis_client.lpush(dlq_key, message.to_json())


class RabbitMQQueueBackend(QueueBackendBase):
    """RabbitMQ-based queue backend."""

    def __init__(self, config: QueueConfig):
        """Initialize RabbitMQ backend.

        Args:
            config: Queue configuration
        """
        self.config = config
        self.connection = None
        self.channel = None
        self.exchanges = {}
        self.queues = {}
        self.consumers = {}

    async def connect(self):
        """Connect to RabbitMQ."""
        try:
            self.connection = await aio_pika.connect_robust(self.config.rabbitmq_url)
            self.channel = await self.connection.channel()
            await self.channel.set_qos(prefetch_count=self.config.batch_size)

            logger.info("Connected to RabbitMQ message queue")

        except Exception as e:
            logger.error(f"Failed to connect to RabbitMQ: {e}")
            raise

    async def disconnect(self):
        """Disconnect from RabbitMQ."""
        try:
            if self.connection:
                await self.connection.close()

            logger.info("Disconnected from RabbitMQ message queue")

        except Exception as e:
            logger.error(f"Error disconnecting from RabbitMQ: {e}")

    async def publish(self, queue: str, message: Message):
        """Publish message to RabbitMQ queue."""
        try:
            # Ensure queue exists
            await self._ensure_queue(queue)

            # Create AMQP message
            amqp_message = aio_pika.Message(
                message.to_json().encode(),
                priority=message.priority.value,
                correlation_id=message.correlation_id,
                reply_to=message.reply_to,
                headers=message.headers,
                delivery_mode=(
                    DeliveryMode.PERSISTENT
                    if self.config.enable_persistence
                    else DeliveryMode.NOT_PERSISTENT
                ),
            )

            # Publish message
            await self.channel.default_exchange.publish(amqp_message, routing_key=queue)

        except Exception as e:
            logger.error(f"Failed to publish message to RabbitMQ queue {queue}: {e}")
            raise

    async def consume(
        self, queue: str, handler: MessageHandler
    ) -> AsyncIterator[Message]:
        """Consume messages from RabbitMQ queue."""
        try:
            # Ensure queue exists
            rabbit_queue = await self._ensure_queue(queue)

            async with rabbit_queue.iterator() as queue_iter:
                async for amqp_message in queue_iter:
                    try:
                        # Parse message
                        message_data = json.loads(amqp_message.body.decode())
                        message = Message(**message_data)

                        # Handle message
                        success = await handler.handle(message)

                        if success:
                            amqp_message.ack()
                        else:
                            # Reject and possibly retry
                            if message.should_retry():
                                amqp_message.reject(requeue=True)
                            else:
                                amqp_message.reject(requeue=False)

                        yield message

                    except Exception as e:
                        logger.error(f"Error processing RabbitMQ message: {e}")
                        amqp_message.reject(requeue=False)

        except Exception as e:
            logger.error(f"Error consuming from RabbitMQ queue {queue}: {e}")

    async def subscribe(self, topic: str, handler: MessageHandler):
        """Subscribe to RabbitMQ topic."""
        try:
            # Create topic exchange
            exchange = await self._ensure_topic_exchange(topic)

            # Create temporary queue for subscriber
            queue_name = f"{topic}_subscriber_{uuid.uuid4().hex[:8]}"
            queue = await self.channel.declare_queue(queue_name, auto_delete=True)

            # Bind queue to topic
            await queue.bind(exchange, topic)

            # Store consumer reference
            self.consumers[topic] = handler

            # Start consuming
            asyncio.create_task(self._consume_topic_messages(queue, handler))

        except Exception as e:
            logger.error(f"Failed to subscribe to RabbitMQ topic {topic}: {e}")
            raise

    async def unsubscribe(self, topic: str):
        """Unsubscribe from RabbitMQ topic."""
        try:
            if topic in self.consumers:
                del self.consumers[topic]

        except Exception as e:
            logger.error(f"Failed to unsubscribe from RabbitMQ topic {topic}: {e}")

    async def _ensure_queue(self, queue_name: str) -> AbstractQueue:
        """Ensure queue exists."""
        if queue_name not in self.queues:
            queue = await self.channel.declare_queue(
                queue_name,
                durable=self.config.enable_persistence,
                arguments={
                    "x-message-ttl": self.config.message_ttl_seconds * 1000,
                    "x-dead-letter-exchange": "",
                    "x-dead-letter-routing-key": self.config.dead_letter_queue,
                },
            )
            self.queues[queue_name] = queue

        return self.queues[queue_name]

    async def _ensure_topic_exchange(self, topic: str):
        """Ensure topic exchange exists."""
        if topic not in self.exchanges:
            exchange = await self.channel.declare_exchange(
                f"topic_{topic}",
                aio_pika.ExchangeType.TOPIC,
                durable=self.config.enable_persistence,
            )
            self.exchanges[topic] = exchange

        return self.exchanges[topic]

    async def _consume_topic_messages(
        self, queue: AbstractQueue, handler: MessageHandler
    ):
        """Consume messages from topic queue."""
        try:
            async with queue.iterator() as queue_iter:
                async for amqp_message in queue_iter:
                    try:
                        message_data = json.loads(amqp_message.body.decode())
                        message = Message(**message_data)

                        await handler.handle(message)
                        amqp_message.ack()

                    except Exception as e:
                        logger.error(f"Error handling topic message: {e}")
                        amqp_message.reject(requeue=False)

        except Exception as e:
            logger.error(f"Error consuming topic messages: {e}")


class InMemoryQueueBackend(QueueBackendBase):
    """In-memory queue backend for testing."""

    def __init__(self, config: QueueConfig):
        """Initialize in-memory backend.

        Args:
            config: Queue configuration
        """
        self.config = config
        self.queues = {}
        self.topics = {}
        self.running = False

    async def connect(self):
        """Connect (no-op for in-memory)."""
        self.running = True
        logger.info("Connected to in-memory message queue")

    async def disconnect(self):
        """Disconnect (no-op for in-memory)."""
        self.running = False
        logger.info("Disconnected from in-memory message queue")

    async def publish(self, queue: str, message: Message):
        """Publish message to in-memory queue."""
        if queue not in self.queues:
            self.queues[queue] = asyncio.Queue()

        await self.queues[queue].put(message)

    async def consume(
        self, queue: str, handler: MessageHandler
    ) -> AsyncIterator[Message]:
        """Consume messages from in-memory queue."""
        if queue not in self.queues:
            self.queues[queue] = asyncio.Queue()

        queue_obj = self.queues[queue]

        while self.running:
            try:
                message = await asyncio.wait_for(
                    queue_obj.get(), timeout=self.config.consumer_timeout_seconds
                )

                success = await handler.handle(message)

                if not success and message.should_retry():
                    message.retry_count += 1
                    await asyncio.sleep(self.config.retry_delay_seconds)
                    await self.publish(queue, message)

                yield message

            except asyncio.TimeoutError:
                continue

    async def subscribe(self, topic: str, handler: MessageHandler):
        """Subscribe to in-memory topic."""
        if topic not in self.topics:
            self.topics[topic] = []

        self.topics[topic].append(handler)

    async def unsubscribe(self, topic: str):
        """Unsubscribe from in-memory topic."""
        if topic in self.topics:
            del self.topics[topic]


class MessageQueue:
    """Main message queue interface."""

    def __init__(self, config: Optional[QueueConfig] = None):
        """Initialize message queue.

        Args:
            config: Queue configuration
        """
        self.config = config or QueueConfig()
        self.backend = self._create_backend()
        self.connected = False

    def _create_backend(self) -> QueueBackendBase:
        """Create queue backend based on configuration."""
        if self.config.backend == QueueBackend.REDIS:
            return RedisQueueBackend(self.config)
        elif self.config.backend == QueueBackend.RABBITMQ:
            return RabbitMQQueueBackend(self.config)
        elif self.config.backend == QueueBackend.IN_MEMORY:
            return InMemoryQueueBackend(self.config)
        else:
            raise ValueError(f"Unsupported queue backend: {self.config.backend}")

    async def connect(self):
        """Connect to message queue."""
        if not self.connected:
            await self.backend.connect()
            self.connected = True

    async def disconnect(self):
        """Disconnect from message queue."""
        if self.connected:
            await self.backend.disconnect()
            self.connected = False

    async def publish(self, queue: str, message: Message):
        """Publish message to queue."""
        await self.backend.publish(queue, message)

    async def consume(
        self, queue: str, handler: MessageHandler
    ) -> AsyncIterator[Message]:
        """Consume messages from queue."""
        async for message in self.backend.consume(queue, handler):
            yield message

    async def subscribe(self, topic: str, handler: MessageHandler):
        """Subscribe to topic."""
        await self.backend.subscribe(topic, handler)

    async def unsubscribe(self, topic: str):
        """Unsubscribe from topic."""
        await self.backend.unsubscribe(topic)


class EventBus:
    """Event-driven message bus."""

    def __init__(self, message_queue: MessageQueue):
        """Initialize event bus.

        Args:
            message_queue: Underlying message queue
        """
        self.message_queue = message_queue
        self.event_handlers = {}
        self.middleware = []

    async def publish_event(self, event_type: str, data: Dict[str, Any], **kwargs):
        """Publish an event.

        Args:
            event_type: Type of event
            data: Event data
            **kwargs: Additional message parameters
        """
        message = Message(topic=event_type, data=data, **kwargs)

        # Apply middleware
        for middleware_func in self.middleware:
            message = await middleware_func(message)

        await self.message_queue.publish(f"events.{event_type}", message)

    async def subscribe_to_event(self, event_type: str, handler: Callable):
        """Subscribe to an event type.

        Args:
            event_type: Event type to subscribe to
            handler: Event handler function
        """

        # Wrap handler in MessageHandler
        class EventMessageHandler(MessageHandler):
            def __init__(self, event_handler):
                self.event_handler = event_handler

            async def handle(self, message: Message) -> bool:
                try:
                    await self.event_handler(message.data, message.metadata)
                    return True
                except Exception as e:
                    logger.error(f"Error handling event {event_type}: {e}")
                    return False

        handler_wrapper = EventMessageHandler(handler)
        await self.message_queue.subscribe(f"events.{event_type}", handler_wrapper)

    def add_middleware(self, middleware_func: Callable):
        """Add middleware to event processing.

        Args:
            middleware_func: Middleware function
        """
        self.middleware.append(middleware_func)


# Export components
__all__ = [
    "MessageQueue",
    "EventBus",
    "Message",
    "MessageHandler",
    "QueueConfig",
    "QueueBackend",
    "MessagePriority",
]
