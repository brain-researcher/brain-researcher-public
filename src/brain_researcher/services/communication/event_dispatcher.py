"""
Event Dispatcher for Service Communication.

Provides event-driven communication patterns with support for
event routing, filtering, transformation, and delivery guarantees.
"""

import asyncio
import logging
import time
import uuid
from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)


class EventPriority(int, Enum):
    """Event priority levels."""

    LOW = 1
    NORMAL = 5
    HIGH = 8
    CRITICAL = 10


class DeliveryMode(str, Enum):
    """Event delivery modes."""

    AT_MOST_ONCE = "at_most_once"  # Fire and forget
    AT_LEAST_ONCE = "at_least_once"  # Retry until success
    EXACTLY_ONCE = "exactly_once"  # Idempotent delivery


@dataclass
class Event:
    """Event data structure."""

    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    type: str = ""
    source: str = ""
    data: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, str] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=datetime.utcnow)
    correlation_id: str | None = None
    causation_id: str | None = None
    version: str = "1.0"
    priority: EventPriority = EventPriority.NORMAL
    ttl_seconds: int | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert event to dictionary."""
        return {
            "id": self.id,
            "type": self.type,
            "source": self.source,
            "data": self.data,
            "metadata": self.metadata,
            "timestamp": self.timestamp.isoformat(),
            "correlation_id": self.correlation_id,
            "causation_id": self.causation_id,
            "version": self.version,
            "priority": self.priority.value,
            "ttl_seconds": self.ttl_seconds,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Event":
        """Create event from dictionary."""
        event_data = data.copy()

        # Convert timestamp
        if "timestamp" in event_data and isinstance(event_data["timestamp"], str):
            event_data["timestamp"] = datetime.fromisoformat(event_data["timestamp"])

        # Convert priority
        if "priority" in event_data and isinstance(event_data["priority"], int):
            event_data["priority"] = EventPriority(event_data["priority"])

        return cls(**event_data)

    def is_expired(self) -> bool:
        """Check if event has expired."""
        if not self.ttl_seconds:
            return False

        age_seconds = (datetime.utcnow() - self.timestamp).total_seconds()
        return age_seconds > self.ttl_seconds


@dataclass
class EventHandlerConfig:
    """Configuration for event handler."""

    event_types: list[str] = field(default_factory=list)
    source_patterns: list[str] = field(default_factory=list)
    priority_filter: EventPriority | None = None
    async_processing: bool = True
    max_retries: int = 3
    retry_delay_seconds: float = 1.0
    timeout_seconds: float = 30.0
    delivery_mode: DeliveryMode = DeliveryMode.AT_LEAST_ONCE
    dead_letter_queue: bool = True


class EventFilter(ABC):
    """Abstract event filter."""

    @abstractmethod
    async def should_process(self, event: Event) -> bool:
        """Check if event should be processed.

        Args:
            event: Event to check

        Returns:
            True if event should be processed
        """
        pass


class TypeFilter(EventFilter):
    """Filter events by type."""

    def __init__(self, event_types: list[str]):
        """Initialize type filter.

        Args:
            event_types: List of event types to match
        """
        self.event_types = set(event_types)

    async def should_process(self, event: Event) -> bool:
        """Check if event type matches."""
        return event.type in self.event_types


class SourceFilter(EventFilter):
    """Filter events by source pattern."""

    def __init__(self, source_patterns: list[str]):
        """Initialize source filter.

        Args:
            source_patterns: List of source patterns to match
        """
        self.source_patterns = source_patterns

    async def should_process(self, event: Event) -> bool:
        """Check if event source matches patterns."""
        import re

        for pattern in self.source_patterns:
            regex_pattern = pattern.replace("*", ".*")
            if re.match(f"^{regex_pattern}$", event.source):
                return True

        return False


class PriorityFilter(EventFilter):
    """Filter events by priority."""

    def __init__(self, min_priority: EventPriority):
        """Initialize priority filter.

        Args:
            min_priority: Minimum priority level
        """
        self.min_priority = min_priority

    async def should_process(self, event: Event) -> bool:
        """Check if event priority is high enough."""
        return event.priority.value >= self.min_priority.value


class CompositeFilter(EventFilter):
    """Combine multiple filters."""

    def __init__(self, filters: list[EventFilter], operator: str = "AND"):
        """Initialize composite filter.

        Args:
            filters: List of filters to combine
            operator: Combination operator (AND/OR)
        """
        self.filters = filters
        self.operator = operator.upper()

    async def should_process(self, event: Event) -> bool:
        """Evaluate all filters."""
        if not self.filters:
            return True

        results = []
        for filter_instance in self.filters:
            result = await filter_instance.should_process(event)
            results.append(result)

        if self.operator == "OR":
            return any(results)
        else:  # AND
            return all(results)


class EventTransformer(ABC):
    """Abstract event transformer."""

    @abstractmethod
    async def transform(self, event: Event) -> Event:
        """Transform event.

        Args:
            event: Event to transform

        Returns:
            Transformed event
        """
        pass


class DataTransformer(EventTransformer):
    """Transform event data using function."""

    def __init__(self, transform_func: Callable[[dict[str, Any]], dict[str, Any]]):
        """Initialize data transformer.

        Args:
            transform_func: Function to transform event data
        """
        self.transform_func = transform_func

    async def transform(self, event: Event) -> Event:
        """Transform event data."""
        transformed_data = self.transform_func(event.data)
        event.data = transformed_data
        return event


class MetadataTransformer(EventTransformer):
    """Transform event metadata."""

    def __init__(self, metadata_updates: dict[str, str]):
        """Initialize metadata transformer.

        Args:
            metadata_updates: Metadata fields to add/update
        """
        self.metadata_updates = metadata_updates

    async def transform(self, event: Event) -> Event:
        """Transform event metadata."""
        event.metadata.update(self.metadata_updates)
        return event


class EventHandler:
    """Event handler wrapper."""

    def __init__(
        self,
        name: str,
        handler_func: Callable,
        config: EventHandlerConfig,
        filters: list[EventFilter] | None = None,
        transformers: list[EventTransformer] | None = None,
    ):
        """Initialize event handler.

        Args:
            name: Handler name
            handler_func: Handler function
            config: Handler configuration
            filters: Event filters
            transformers: Event transformers
        """
        self.name = name
        self.handler_func = handler_func
        self.config = config
        self.filters = filters or []
        self.transformers = transformers or []

        # Create composite filter
        filter_list = []

        if config.event_types:
            filter_list.append(TypeFilter(config.event_types))

        if config.source_patterns:
            filter_list.append(SourceFilter(config.source_patterns))

        if config.priority_filter:
            filter_list.append(PriorityFilter(config.priority_filter))

        filter_list.extend(self.filters)

        self.composite_filter = CompositeFilter(filter_list, "AND")

        # Handler metrics
        self.total_events = 0
        self.processed_events = 0
        self.failed_events = 0
        self.filtered_events = 0
        self.last_processed: datetime | None = None
        self.processing_times: list[float] = []

    async def can_handle(self, event: Event) -> bool:
        """Check if handler can process event."""
        return await self.composite_filter.should_process(event)

    async def handle(self, event: Event) -> bool:
        """Handle event with retries and error handling.

        Args:
            event: Event to handle

        Returns:
            True if successfully handled
        """
        self.total_events += 1

        # Check if handler can process this event
        if not await self.can_handle(event):
            self.filtered_events += 1
            return True  # Successfully filtered out

        # Apply transformers
        transformed_event = event
        for transformer in self.transformers:
            transformed_event = await transformer.transform(transformed_event)

        # Process with retries
        for attempt in range(self.config.max_retries + 1):
            try:
                start_time = time.time()

                # Call handler function
                if self.config.async_processing and asyncio.iscoroutinefunction(
                    self.handler_func
                ):
                    if self.config.timeout_seconds:
                        await asyncio.wait_for(
                            self.handler_func(transformed_event),
                            timeout=self.config.timeout_seconds,
                        )
                    else:
                        await self.handler_func(transformed_event)
                elif asyncio.iscoroutinefunction(self.handler_func):
                    await self.handler_func(transformed_event)
                else:
                    # Sync function
                    if self.config.async_processing:
                        loop = asyncio.get_event_loop()
                        if self.config.timeout_seconds:
                            await asyncio.wait_for(
                                loop.run_in_executor(
                                    None, self.handler_func, transformed_event
                                ),
                                timeout=self.config.timeout_seconds,
                            )
                        else:
                            await loop.run_in_executor(
                                None, self.handler_func, transformed_event
                            )
                    else:
                        self.handler_func(transformed_event)

                # Success
                processing_time = time.time() - start_time
                self.processing_times.append(processing_time)
                if len(self.processing_times) > 1000:  # Keep last 1000 times
                    self.processing_times.pop(0)

                self.processed_events += 1
                self.last_processed = datetime.utcnow()

                logger.debug(
                    f"Handler '{self.name}' processed event {event.id} in {processing_time:.3f}s"
                )
                return True

            except Exception as e:
                logger.error(
                    f"Handler '{self.name}' failed to process event {event.id}: {e}"
                )

                # If this was the last attempt, record failure
                if attempt == self.config.max_retries:
                    self.failed_events += 1
                    return False

                # Wait before retry
                if self.config.retry_delay_seconds > 0:
                    await asyncio.sleep(self.config.retry_delay_seconds)

        return False

    def get_metrics(self) -> dict[str, Any]:
        """Get handler metrics."""
        avg_processing_time = (
            sum(self.processing_times) / len(self.processing_times)
            if self.processing_times
            else 0.0
        )

        success_rate = (
            self.processed_events / self.total_events if self.total_events > 0 else 0.0
        )

        return {
            "name": self.name,
            "total_events": self.total_events,
            "processed_events": self.processed_events,
            "failed_events": self.failed_events,
            "filtered_events": self.filtered_events,
            "success_rate": success_rate,
            "average_processing_time_seconds": avg_processing_time,
            "last_processed": (
                self.last_processed.isoformat() if self.last_processed else None
            ),
            "config": {
                "event_types": self.config.event_types,
                "async_processing": self.config.async_processing,
                "max_retries": self.config.max_retries,
                "timeout_seconds": self.config.timeout_seconds,
                "delivery_mode": self.config.delivery_mode.value,
            },
        }


class EventDispatcher:
    """Main event dispatcher."""

    def __init__(self, name: str = "default"):
        """Initialize event dispatcher.

        Args:
            name: Dispatcher name
        """
        self.name = name
        self.handlers: list[EventHandler] = []
        self.middleware: list[Callable] = []
        self.event_queue: asyncio.Queue = asyncio.Queue()
        self.dead_letter_queue: asyncio.Queue = asyncio.Queue()
        self.running = False
        self.worker_tasks: list[asyncio.Task] = []
        self.num_workers = 4

        # Dispatcher metrics
        self.total_events_dispatched = 0
        self.total_events_processed = 0
        self.total_events_failed = 0
        self.start_time: datetime | None = None

    def add_handler(
        self,
        name: str,
        handler_func: Callable,
        config: EventHandlerConfig | None = None,
        filters: list[EventFilter] | None = None,
        transformers: list[EventTransformer] | None = None,
    ) -> EventHandler:
        """Add event handler.

        Args:
            name: Handler name
            handler_func: Handler function
            config: Handler configuration
            filters: Event filters
            transformers: Event transformers

        Returns:
            Event handler instance
        """
        handler_config = config or EventHandlerConfig()
        handler = EventHandler(
            name, handler_func, handler_config, filters, transformers
        )
        self.handlers.append(handler)

        logger.info(f"Added event handler '{name}' to dispatcher '{self.name}'")
        return handler

    def remove_handler(self, name: str) -> bool:
        """Remove event handler.

        Args:
            name: Handler name

        Returns:
            True if handler was removed
        """
        for i, handler in enumerate(self.handlers):
            if handler.name == name:
                del self.handlers[i]
                logger.info(
                    f"Removed event handler '{name}' from dispatcher '{self.name}'"
                )
                return True

        return False

    def add_middleware(self, middleware_func: Callable):
        """Add middleware function.

        Args:
            middleware_func: Middleware function
        """
        self.middleware.append(middleware_func)

    async def dispatch(self, event: Event) -> bool:
        """Dispatch event to handlers.

        Args:
            event: Event to dispatch

        Returns:
            True if successfully queued
        """
        # Check if event is expired
        if event.is_expired():
            logger.debug(f"Event {event.id} expired, not dispatching")
            return False

        # Apply middleware
        processed_event = event
        for middleware_func in self.middleware:
            if asyncio.iscoroutinefunction(middleware_func):
                processed_event = await middleware_func(processed_event)
            else:
                processed_event = middleware_func(processed_event)

            if processed_event is None:
                logger.debug(f"Event {event.id} filtered out by middleware")
                return False

        # Queue event for processing
        await self.event_queue.put(processed_event)
        self.total_events_dispatched += 1

        logger.debug(f"Event {event.id} queued for dispatch")
        return True

    async def start(self):
        """Start event dispatcher."""
        if self.running:
            return

        self.running = True
        self.start_time = datetime.utcnow()

        # Start worker tasks
        for i in range(self.num_workers):
            task = asyncio.create_task(self._worker_loop(f"worker-{i}"))
            self.worker_tasks.append(task)

        logger.info(
            f"Event dispatcher '{self.name}' started with {self.num_workers} workers"
        )

    async def stop(self):
        """Stop event dispatcher."""
        if not self.running:
            return

        self.running = False

        # Cancel worker tasks
        for task in self.worker_tasks:
            task.cancel()

        # Wait for tasks to complete
        if self.worker_tasks:
            await asyncio.gather(*self.worker_tasks, return_exceptions=True)

        self.worker_tasks.clear()

        logger.info(f"Event dispatcher '{self.name}' stopped")

    async def _worker_loop(self, worker_name: str):
        """Worker loop for processing events."""
        logger.debug(f"Worker {worker_name} started")

        try:
            while self.running:
                try:
                    # Get event from queue with timeout
                    event = await asyncio.wait_for(self.event_queue.get(), timeout=1.0)

                    await self._process_event(event)
                    self.event_queue.task_done()

                except asyncio.TimeoutError:
                    continue  # Check if still running
                except Exception as e:
                    logger.error(f"Worker {worker_name} error: {e}")

        except asyncio.CancelledError:
            logger.debug(f"Worker {worker_name} cancelled")
        except Exception as e:
            logger.error(f"Worker {worker_name} unexpected error: {e}")

        logger.debug(f"Worker {worker_name} stopped")

    async def _process_event(self, event: Event):
        """Process event with all handlers."""
        logger.debug(f"Processing event {event.id} of type {event.type}")

        # Find handlers that can process this event
        applicable_handlers = []
        for handler in self.handlers:
            if await handler.can_handle(event):
                applicable_handlers.append(handler)

        if not applicable_handlers:
            logger.debug(f"No handlers found for event {event.id}")
            return

        # Process event with each handler
        success_count = 0
        for handler in applicable_handlers:
            try:
                success = await handler.handle(event)
                if success:
                    success_count += 1
            except Exception as e:
                logger.error(f"Handler '{handler.name}' failed with error: {e}")

        # Update metrics
        if success_count > 0:
            self.total_events_processed += 1
        else:
            self.total_events_failed += 1

            # Send to dead letter queue if configured
            if any(h.config.dead_letter_queue for h in applicable_handlers):
                await self.dead_letter_queue.put(event)
                logger.debug(f"Event {event.id} sent to dead letter queue")

    def get_metrics(self) -> dict[str, Any]:
        """Get dispatcher metrics."""
        uptime_seconds = (
            (datetime.utcnow() - self.start_time).total_seconds()
            if self.start_time
            else 0
        )

        handler_metrics = [handler.get_metrics() for handler in self.handlers]

        return {
            "name": self.name,
            "running": self.running,
            "uptime_seconds": uptime_seconds,
            "num_workers": self.num_workers,
            "num_handlers": len(self.handlers),
            "total_events_dispatched": self.total_events_dispatched,
            "total_events_processed": self.total_events_processed,
            "total_events_failed": self.total_events_failed,
            "queue_size": self.event_queue.qsize(),
            "dead_letter_queue_size": self.dead_letter_queue.qsize(),
            "handler_metrics": handler_metrics,
        }


def event_handler(
    event_types: list[str] | None = None,
    source_patterns: list[str] | None = None,
    priority_filter: EventPriority | None = None,
    **config_kwargs,
):
    """Decorator for registering event handlers.

    Args:
        event_types: Event types to handle
        source_patterns: Source patterns to match
        priority_filter: Minimum priority level
        **config_kwargs: Additional configuration

    Returns:
        Decorated function
    """

    def decorator(func):
        config = EventHandlerConfig(
            event_types=event_types or [],
            source_patterns=source_patterns or [],
            priority_filter=priority_filter,
            **config_kwargs,
        )

        # Store configuration on function for later registration
        func._event_handler_config = config
        func._event_handler_name = func.__name__

        return func

    return decorator


# Export components
__all__ = [
    "EventDispatcher",
    "Event",
    "EventHandler",
    "EventHandlerConfig",
    "EventFilter",
    "EventTransformer",
    "EventPriority",
    "DeliveryMode",
    "TypeFilter",
    "SourceFilter",
    "PriorityFilter",
    "CompositeFilter",
    "DataTransformer",
    "MetadataTransformer",
    "event_handler",
]
