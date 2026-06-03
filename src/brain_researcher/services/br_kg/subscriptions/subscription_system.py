"""GraphQL Subscription System with WebSocket support - completes KG-021.

This module provides real-time updates via GraphQL subscriptions using WebSockets,
with event filtering, connection management, and scalable pub/sub.
"""

import asyncio
import json
import logging
import uuid
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)


# Custom Exception Classes
class SubscriptionSystemError(Exception):
    """Base exception for subscription system errors."""

    pass


class ConnectionError(SubscriptionSystemError):
    """Connection-related errors."""

    pass


class SubscriptionError(SubscriptionSystemError):
    """Subscription-related errors."""

    pass


class ValidationError(SubscriptionSystemError):
    """Validation errors."""

    pass


class MaxConnectionsError(SubscriptionSystemError):
    """Maximum connections exceeded error."""

    pass


class EventType(Enum):
    """Types of events that can be subscribed to."""

    NODE_CREATED = "node_created"
    NODE_UPDATED = "node_updated"
    NODE_DELETED = "node_deleted"
    EDGE_CREATED = "edge_created"
    EDGE_UPDATED = "edge_updated"
    EDGE_DELETED = "edge_deleted"
    GRAPH_CHANGED = "graph_changed"
    ANALYSIS_COMPLETED = "analysis_completed"
    CURATION_STATUS_CHANGED = "curation_status_changed"


@dataclass
class SubscriptionFilter:
    """Filter criteria for subscriptions."""

    event_types: list[EventType] | None = None
    entity_types: list[str] | None = None
    entity_ids: list[str] | None = None
    properties: dict[str, Any] | None = None
    user_id: str | None = None
    metadata_filters: dict[str, Any] = field(default_factory=dict)


@dataclass
class Subscription:
    """Represents an active subscription."""

    subscription_id: str
    connection_id: str
    query: str
    variables: dict[str, Any]
    filters: SubscriptionFilter
    created_at: datetime = field(default_factory=datetime.now)
    last_event_at: datetime | None = None
    event_count: int = 0


@dataclass
class Connection:
    """Represents a WebSocket connection."""

    connection_id: str
    websocket: Any  # WebSocket connection object
    user_id: str | None
    subscriptions: set[str] = field(default_factory=set)
    connected_at: datetime = field(default_factory=datetime.now)
    last_ping_at: datetime | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class Event:
    """Represents an event in the system."""

    event_id: str
    event_type: EventType
    entity_type: str
    entity_id: str
    data: dict[str, Any]
    user_id: str | None
    timestamp: datetime = field(default_factory=datetime.now)
    metadata: dict[str, Any] = field(default_factory=dict)


class SubscriptionSystem:
    """Manages GraphQL subscriptions and WebSocket connections."""

    def __init__(self, redis_client=None, max_connections: int = 1000):
        """Initialize subscription system.

        Args:
            redis_client: Optional Redis client for pub/sub
            max_connections: Maximum concurrent connections
        """
        self.redis = redis_client
        self.max_connections = max_connections

        # In-memory storage (should be distributed in production)
        self.connections: dict[str, Connection] = {}
        self.subscriptions: dict[str, Subscription] = {}
        self.subscription_handlers: dict[str, Callable] = {}

        # Event queue with bounded size to prevent memory issues
        self.event_queue = asyncio.Queue(maxsize=10000)

        # Best-effort tracking for connections that failed I/O (ids only).
        self.expired_connections: set[str] = set()

        # Connection cleanup settings
        self.cleanup_interval = 300  # 5 minutes
        self.connection_timeout = 3600  # 1 hour

        # Statistics
        self.stats = {
            "total_connections": 0,
            "total_subscriptions": 0,
            "total_events": 0,
            "events_by_type": defaultdict(int),
        }

        # Start background tasks
        self.tasks = []

        # Input validation settings
        self.max_query_length = 10000
        self.max_variables_size = 1000

    async def start(self):
        """Start the subscription system."""
        self.tasks.append(asyncio.create_task(self._event_processor()))
        self.tasks.append(asyncio.create_task(self._ping_connections()))
        self.tasks.append(asyncio.create_task(self._cleanup_expired_connections()))

        if self.redis:
            self.tasks.append(asyncio.create_task(self._redis_subscriber()))

        logger.info("Subscription system started")

    async def stop(self):
        """Stop the subscription system."""
        # Cancel all tasks
        for task in self.tasks:
            task.cancel()
        if self.tasks:
            # Ensure background tasks observe cancellation before returning.
            await asyncio.gather(*self.tasks, return_exceptions=True)

        # Close all connections
        for connection in list(self.connections.values()):
            await self.disconnect(connection.connection_id)

        logger.info("Subscription system stopped")

    async def connect(
        self,
        websocket: Any,
        user_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> str:
        """Handle new WebSocket connection.

        Args:
            websocket: WebSocket connection object
            user_id: Optional user ID
            metadata: Connection metadata

        Returns:
            Connection ID
        """
        # Input validation
        if user_id is not None and not isinstance(user_id, str):
            raise ValidationError("user_id must be a string")

        if metadata is not None and not isinstance(metadata, dict):
            raise ValidationError("metadata must be a dictionary")

        if len(self.connections) >= self.max_connections:
            raise MaxConnectionsError(
                f"Maximum connections reached ({self.max_connections})"
            )

        connection_id = str(uuid.uuid4())

        connection = Connection(
            connection_id=connection_id,
            websocket=websocket,
            user_id=user_id,
            metadata=metadata or {},
        )

        self.connections[connection_id] = connection
        self.stats["total_connections"] += 1

        # Send connection acknowledgment
        await self._send_message(
            connection_id, {"type": "connection_ack", "connection_id": connection_id}
        )

        logger.info(f"Client connected: {connection_id}")
        return connection_id

    async def disconnect(self, connection_id: str):
        """Handle WebSocket disconnection.

        Args:
            connection_id: Connection ID
        """
        if connection_id not in self.connections:
            return

        connection = self.connections[connection_id]

        # Unsubscribe all subscriptions
        for subscription_id in list(connection.subscriptions):
            await self.unsubscribe(subscription_id)

        # Close WebSocket
        try:
            await connection.websocket.close()
        except:
            pass

        del self.connections[connection_id]

        logger.info(f"Client disconnected: {connection_id}")

    async def subscribe(
        self,
        connection_id: str,
        query: str,
        variables: dict[str, Any] | None = None,
        operation_name: str | None = None,
    ) -> str:
        """Create a new subscription.

        Args:
            connection_id: Connection ID
            query: GraphQL subscription query
            variables: Query variables
            operation_name: Operation name

        Returns:
            Subscription ID
        """
        # Input validation
        if not isinstance(query, str):
            raise ValidationError("query must be a string")

        if len(query) > self.max_query_length:
            raise ValidationError(
                f"query exceeds maximum length ({self.max_query_length})"
            )

        if variables is not None:
            if not isinstance(variables, dict):
                raise ValidationError("variables must be a dictionary")
            if len(str(variables)) > self.max_variables_size:
                raise ValidationError(
                    f"variables exceed maximum size ({self.max_variables_size})"
                )

        if connection_id not in self.connections:
            raise ConnectionError(f"Connection not found: {connection_id}")

        connection = self.connections[connection_id]
        subscription_id = str(uuid.uuid4())

        # Parse subscription to extract filters
        filters = self._parse_subscription_filters(query, variables)

        subscription = Subscription(
            subscription_id=subscription_id,
            connection_id=connection_id,
            query=query,
            variables=variables or {},
            filters=filters,
        )

        self.subscriptions[subscription_id] = subscription
        connection.subscriptions.add(subscription_id)
        self.stats["total_subscriptions"] += 1

        # Send subscription confirmation
        await self._send_message(
            connection_id, {"type": "subscription_success", "id": subscription_id}
        )

        # Execute subscription handler if defined
        handler_name = self._get_handler_name(query)
        if handler_name in self.subscription_handlers:
            handler = self.subscription_handlers[handler_name]
            asyncio.create_task(handler(subscription))

        logger.info(f"Subscription created: {subscription_id}")
        return subscription_id

    async def unsubscribe(self, subscription_id: str):
        """Cancel a subscription.

        Args:
            subscription_id: Subscription ID
        """
        if subscription_id not in self.subscriptions:
            return

        subscription = self.subscriptions[subscription_id]
        connection_id = subscription.connection_id

        if connection_id in self.connections:
            self.connections[connection_id].subscriptions.discard(subscription_id)

        del self.subscriptions[subscription_id]

        logger.info(f"Subscription cancelled: {subscription_id}")

    async def publish_event(self, event: Event):
        """Publish an event to subscribers.

        Args:
            event: Event to publish
        """
        # Add to queue for processing (with timeout to prevent blocking)
        try:
            await asyncio.wait_for(self.event_queue.put(event), timeout=1.0)
        except asyncio.TimeoutError:
            logger.warning("Event queue is full, dropping event")
            return

        # Publish to Redis if available
        if self.redis:
            await self._publish_to_redis(event)

        self.stats["total_events"] += 1
        self.stats["events_by_type"][event.event_type.value] += 1

    async def _event_processor(self):
        """Process events and send to subscribers."""
        while True:
            try:
                event = await self.event_queue.get()

                # Find matching subscriptions
                matching_subscriptions = self._find_matching_subscriptions(event)

                # Send to each subscriber
                for subscription_id in matching_subscriptions:
                    if subscription_id in self.subscriptions:
                        subscription = self.subscriptions[subscription_id]

                        # Format event data
                        data = self._format_event_data(event, subscription)

                        # Send to connection
                        await self._send_subscription_data(
                            subscription.connection_id, subscription_id, data
                        )

                        # Update subscription stats
                        subscription.last_event_at = datetime.now()
                        subscription.event_count += 1

            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.error(f"Error processing event: {e}", exc_info=True)

    def _find_matching_subscriptions(self, event: Event) -> list[str]:
        """Find subscriptions that match an event.

        Args:
            event: Event to match

        Returns:
            List of matching subscription IDs
        """
        matching = []

        for subscription_id, subscription in self.subscriptions.items():
            filters = subscription.filters

            # Check event type filter
            if filters.event_types:
                if event.event_type not in filters.event_types:
                    continue

            # Check entity type filter
            if filters.entity_types:
                if event.entity_type not in filters.entity_types:
                    continue

            # Check entity ID filter
            if filters.entity_ids:
                if event.entity_id not in filters.entity_ids:
                    continue

            # Check user filter
            if filters.user_id:
                if event.user_id != filters.user_id:
                    continue

            # Check property filters
            if filters.properties:
                if not self._match_properties(event.data, filters.properties):
                    continue

            # Check metadata filters
            if filters.metadata_filters:
                if not self._match_properties(event.metadata, filters.metadata_filters):
                    continue

            matching.append(subscription_id)

        return matching

    def _match_properties(self, data: dict[str, Any], filters: dict[str, Any]) -> bool:
        """Check if data matches property filters.

        Args:
            data: Data to check
            filters: Filter criteria

        Returns:
            True if matches
        """
        for key, value in filters.items():
            if key not in data:
                return False

            if isinstance(value, dict) and "$in" in value:
                if data[key] not in value["$in"]:
                    return False
            elif isinstance(value, dict) and "$gte" in value:
                if data[key] < value["$gte"]:
                    return False
            elif isinstance(value, dict) and "$lte" in value:
                if data[key] > value["$lte"]:
                    return False
            elif data[key] != value:
                return False

        return True

    def _format_event_data(
        self, event: Event, subscription: Subscription
    ) -> dict[str, Any]:
        """Format event data for subscription.

        Args:
            event: Event to format
            subscription: Target subscription

        Returns:
            Formatted data
        """
        # Basic event data
        data = {
            "event_id": event.event_id,
            "event_type": event.event_type.value,
            "entity_type": event.entity_type,
            "entity_id": event.entity_id,
            "timestamp": event.timestamp.isoformat(),
            "data": event.data,
        }

        # Add metadata if requested in query
        if "metadata" in subscription.query:
            data["metadata"] = event.metadata

        # Add user if requested
        if "user_id" in subscription.query:
            data["user_id"] = event.user_id

        return data

    async def _send_subscription_data(
        self, connection_id: str, subscription_id: str, data: dict[str, Any]
    ):
        """Send subscription data to connection.

        Args:
            connection_id: Connection ID
            subscription_id: Subscription ID
            data: Data to send
        """
        await self._send_message(
            connection_id,
            {"type": "data", "id": subscription_id, "payload": {"data": data}},
        )

    async def _send_message(self, connection_id: str, message: dict[str, Any]):
        """Send message to connection.

        Args:
            connection_id: Connection ID
            message: Message to send
        """
        if connection_id not in self.connections:
            return

        connection = self.connections[connection_id]

        try:
            await connection.websocket.send(json.dumps(message))
        except Exception as e:
            logger.error(
                f"Error sending message to {connection_id}: {e}", exc_info=True
            )
            # Mark connection as expired for cleanup
            if connection_id in self.connections:
                self.expired_connections.add(connection_id)
            await self.disconnect(connection_id)

    async def _ping_connections(self):
        """Ping connections periodically."""
        while True:
            try:
                await asyncio.sleep(30)  # Ping every 30 seconds

                for connection_id in list(self.connections.keys()):
                    await self._send_message(connection_id, {"type": "ping"})

                    connection = self.connections.get(connection_id)
                    if connection:
                        connection.last_ping_at = datetime.now()

            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.error(f"Error pinging connections: {e}", exc_info=True)

    def _parse_subscription_filters(
        self, query: str, variables: dict[str, Any] | None
    ) -> SubscriptionFilter:
        """Parse subscription query to extract filters.

        Args:
            query: GraphQL query
            variables: Query variables

        Returns:
            SubscriptionFilter object
        """
        filters = SubscriptionFilter()

        # Simple parsing - in production would use proper GraphQL parser
        if "nodeCreated" in query or "nodeUpdated" in query or "nodeDeleted" in query:
            if "nodeCreated" in query:
                filters.event_types = [EventType.NODE_CREATED]
            elif "nodeUpdated" in query:
                filters.event_types = [EventType.NODE_UPDATED]
            elif "nodeDeleted" in query:
                filters.event_types = [EventType.NODE_DELETED]

        if "edgeCreated" in query or "edgeUpdated" in query or "edgeDeleted" in query:
            if "edgeCreated" in query:
                filters.event_types = [EventType.EDGE_CREATED]
            elif "edgeUpdated" in query:
                filters.event_types = [EventType.EDGE_UPDATED]
            elif "edgeDeleted" in query:
                filters.event_types = [EventType.EDGE_DELETED]

        # Extract filters from variables
        if variables:
            if "entityTypes" in variables:
                filters.entity_types = variables["entityTypes"]
            if "entityIds" in variables:
                filters.entity_ids = variables["entityIds"]
            if "userId" in variables:
                filters.user_id = variables["userId"]
            if "properties" in variables:
                filters.properties = variables["properties"]

        return filters

    def _get_handler_name(self, query: str) -> str:
        """Extract handler name from query.

        Args:
            query: GraphQL query

        Returns:
            Handler name
        """
        # Simple extraction - would parse properly in production
        if "nodeCreated" in query:
            return "nodeCreated"
        elif "nodeUpdated" in query:
            return "nodeUpdated"
        elif "edgeCreated" in query:
            return "edgeCreated"
        elif "analysisCompleted" in query:
            return "analysisCompleted"
        else:
            return "default"

    async def _publish_to_redis(self, event: Event):
        """Publish event to Redis pub/sub.

        Args:
            event: Event to publish
        """
        if not self.redis:
            return

        channel = f"graph_events:{event.event_type.value}"

        event_data = {
            "event_id": event.event_id,
            "event_type": event.event_type.value,
            "entity_type": event.entity_type,
            "entity_id": event.entity_id,
            "data": event.data,
            "user_id": event.user_id,
            "timestamp": event.timestamp.isoformat(),
            "metadata": event.metadata,
        }

        try:
            await self.redis.publish(channel, json.dumps(event_data))
        except Exception as e:
            logger.error(f"Error publishing to Redis: {e}", exc_info=True)

    async def _redis_subscriber(self):
        """Subscribe to Redis events."""
        if not self.redis:
            return

        try:
            pubsub = self.redis.pubsub()
            await pubsub.subscribe("graph_events:*")

            while True:
                try:
                    message = await pubsub.get_message(
                        ignore_subscribe_messages=True, timeout=1.0
                    )

                    if not message:
                        # Avoid a busy loop in dev/tests (mock pubsub returns immediately).
                        await asyncio.sleep(0.05)
                        continue

                    if message:
                        # Parse event from Redis
                        event_data = json.loads(message["data"])

                        event = Event(
                            event_id=event_data["event_id"],
                            event_type=EventType(event_data["event_type"]),
                            entity_type=event_data["entity_type"],
                            entity_id=event_data["entity_id"],
                            data=event_data["data"],
                            user_id=event_data.get("user_id"),
                            timestamp=datetime.fromisoformat(event_data["timestamp"]),
                            metadata=event_data.get("metadata", {}),
                        )

                        # Process event
                        await self.event_queue.put(event)

                except asyncio.CancelledError:
                    raise
                except Exception as e:
                    logger.error(f"Error processing Redis message: {e}", exc_info=True)

        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.error(f"Redis subscriber error: {e}", exc_info=True)

    def register_handler(self, name: str, handler: Callable):
        """Register a subscription handler.

        Args:
            name: Handler name
            handler: Handler function
        """
        self.subscription_handlers[name] = handler

    def get_statistics(self) -> dict[str, Any]:
        """Get subscription system statistics.

        Returns:
            Statistics dictionary
        """
        active_connections = len(self.connections)
        active_subscriptions = len(self.subscriptions)

        # Calculate average subscriptions per connection
        avg_subscriptions = (
            active_subscriptions / active_connections if active_connections > 0 else 0
        )

        return {
            "active_connections": active_connections,
            "active_subscriptions": active_subscriptions,
            "avg_subscriptions_per_connection": avg_subscriptions,
            "total_connections": self.stats["total_connections"],
            "total_subscriptions": self.stats["total_subscriptions"],
            "total_events": self.stats["total_events"],
            "events_by_type": dict(self.stats["events_by_type"]),
            "max_connections": self.max_connections,
            "connections_by_user": self._get_connections_by_user(),
        }

    def _get_connections_by_user(self) -> dict[str, int]:
        """Get connection count by user.

        Returns:
            User connection counts
        """
        user_counts = defaultdict(int)

        for connection in self.connections.values():
            if connection.user_id:
                user_counts[connection.user_id] += 1
            else:
                user_counts["anonymous"] += 1

        return dict(user_counts)

    async def _cleanup_expired_connections(self):
        """Clean up expired connections periodically."""
        while True:
            try:
                await asyncio.sleep(self.cleanup_interval)

                current_time = datetime.now()
                expired_connection_ids = []

                # Find expired connections
                for connection_id, connection in self.connections.items():
                    # Check if connection hasn't been pinged recently
                    if (
                        connection.last_ping_at
                        and current_time - connection.last_ping_at
                        > timedelta(seconds=self.connection_timeout)
                    ):
                        expired_connection_ids.append(connection_id)
                    # Check if connection is too old
                    elif current_time - connection.connected_at > timedelta(
                        seconds=self.connection_timeout * 2
                    ):
                        expired_connection_ids.append(connection_id)

                # Clean up expired connections
                for connection_id in expired_connection_ids:
                    logger.info(f"Cleaning up expired connection: {connection_id}")
                    await self.disconnect(connection_id)

                if expired_connection_ids:
                    logger.info(
                        f"Cleaned up {len(expired_connection_ids)} expired connections"
                    )

            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.error(
                    f"Error cleaning up expired connections: {e}", exc_info=True
                )
                await asyncio.sleep(self.cleanup_interval)


# GraphQL Schema Extensions
SUBSCRIPTION_SCHEMA = """
type Subscription {
    # Node subscriptions
    nodeCreated(entityTypes: [String], properties: JSON): NodeEvent!
    nodeUpdated(entityIds: [String], entityTypes: [String]): NodeEvent!
    nodeDeleted(entityTypes: [String]): NodeEvent!

    # Edge subscriptions
    edgeCreated(entityTypes: [String], relationshipTypes: [String]): EdgeEvent!
    edgeUpdated(edgeIds: [String]): EdgeEvent!
    edgeDeleted(relationshipTypes: [String]): EdgeEvent!

    # Analysis subscriptions
    analysisCompleted(analysisTypes: [String], userId: String): AnalysisEvent!

    # Curation subscriptions
    curationStatusChanged(entityTypes: [String], statuses: [String]): CurationEvent!

    # Graph change subscription
    graphChanged(filters: GraphChangeFilter): GraphChangeEvent!
}

type NodeEvent {
    eventId: String!
    eventType: String!
    entityType: String!
    entityId: String!
    timestamp: String!
    data: JSON!
    metadata: JSON
    userId: String
}

type EdgeEvent {
    eventId: String!
    eventType: String!
    sourceId: String!
    targetId: String!
    relationshipType: String!
    timestamp: String!
    data: JSON!
    metadata: JSON
    userId: String
}

type AnalysisEvent {
    eventId: String!
    analysisId: String!
    analysisType: String!
    status: String!
    results: JSON
    timestamp: String!
    userId: String
}

type CurationEvent {
    eventId: String!
    itemId: String!
    entityType: String!
    status: String!
    reviewer: String
    timestamp: String!
}

type GraphChangeEvent {
    eventId: String!
    changeType: String!
    affectedNodes: [String!]!
    affectedEdges: [String!]!
    summary: String!
    timestamp: String!
}

input GraphChangeFilter {
    entityTypes: [String]
    changeTypes: [String]
    minImpact: Int
}
"""
