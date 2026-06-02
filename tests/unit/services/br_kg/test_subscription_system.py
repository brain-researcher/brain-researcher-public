"""Comprehensive unit tests for KG-021 Subscription System.

This test suite covers:
- WebSocket connection management
- Subscription lifecycle and filtering
- Event publishing and matching
- Redis pub/sub integration
- Backpressure handling
- Statistics and metrics collection
- Error scenarios and edge cases
"""

import asyncio
import json
import os
import sys
import uuid
from collections import defaultdict
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Add project root to path
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../.."))
sys.path.insert(0, project_root)

from brain_researcher.services.br_kg.subscriptions.subscription_system import (
    Connection,
    Event,
    EventType,
    Subscription,
    SubscriptionFilter,
    SubscriptionSystem,
)


class MockWebSocket:
    """Mock WebSocket for testing."""

    def __init__(self, should_fail=False):
        self.should_fail = should_fail
        self.messages_sent = []
        self.closed = False

    async def send(self, message):
        """Mock send method."""
        if self.should_fail:
            raise Exception("WebSocket send failed")
        self.messages_sent.append(message)

    async def close(self):
        """Mock close method."""
        self.closed = True


class MockRedis:
    """Mock Redis client for testing."""

    def __init__(self):
        self.published_messages = []
        self.subscribers = []

    async def publish(self, channel, message):
        """Mock publish method."""
        self.published_messages.append({"channel": channel, "message": message})

    def pubsub(self):
        """Mock pubsub method."""
        return MockPubSub()


class MockPubSub:
    """Mock Redis pubsub for testing."""

    def __init__(self):
        self.subscriptions = []
        self.messages = []

    async def subscribe(self, pattern):
        """Mock subscribe method."""
        self.subscriptions.append(pattern)

    async def get_message(self, ignore_subscribe_messages=True, timeout=1.0):
        """Mock get_message method."""
        if self.messages:
            return self.messages.pop(0)
        return None


@pytest.fixture
def mock_websocket():
    """Create a mock WebSocket."""
    return MockWebSocket()


@pytest.fixture
def mock_failing_websocket():
    """Create a mock WebSocket that fails."""
    return MockWebSocket(should_fail=True)


@pytest.fixture
def mock_redis():
    """Create a mock Redis client."""
    return MockRedis()


@pytest.fixture
def subscription_system(mock_redis):
    """Create a subscription system instance."""
    return SubscriptionSystem(redis_client=mock_redis, max_connections=5)


@pytest.fixture
async def started_system(subscription_system):
    """Create and start a subscription system."""
    await subscription_system.start()
    yield subscription_system
    await subscription_system.stop()


class TestSubscriptionSystem:
    """Test cases for SubscriptionSystem class."""

    def test_initialization(self):
        """Test subscription system initialization."""
        system = SubscriptionSystem(max_connections=100)

        assert system.max_connections == 100
        assert len(system.connections) == 0
        assert len(system.subscriptions) == 0
        assert system.stats["total_connections"] == 0
        assert system.stats["total_subscriptions"] == 0

    def test_initialization_with_redis(self, mock_redis):
        """Test subscription system initialization with Redis."""
        system = SubscriptionSystem(redis_client=mock_redis)

        assert system.redis == mock_redis
        assert system.max_connections == 1000

    @pytest.mark.asyncio
    async def test_start_stop_system(self, subscription_system):
        """Test starting and stopping the subscription system."""
        await subscription_system.start()

        # Verify tasks are created
        assert len(subscription_system.tasks) > 0

        await subscription_system.stop()

        # Verify tasks are cancelled
        for task in subscription_system.tasks:
            assert task.cancelled()

    @pytest.mark.asyncio
    async def test_connect_websocket(self, subscription_system, mock_websocket):
        """Test WebSocket connection."""
        connection_id = await subscription_system.connect(
            mock_websocket, user_id="test_user", metadata={"client": "test"}
        )

        assert connection_id is not None
        assert connection_id in subscription_system.connections

        connection = subscription_system.connections[connection_id]
        assert connection.websocket == mock_websocket
        assert connection.user_id == "test_user"
        assert connection.metadata["client"] == "test"
        assert subscription_system.stats["total_connections"] == 1

        # Verify connection acknowledgment was sent
        assert len(mock_websocket.messages_sent) == 1
        ack_message = json.loads(mock_websocket.messages_sent[0])
        assert ack_message["type"] == "connection_ack"
        assert ack_message["connection_id"] == connection_id

    @pytest.mark.asyncio
    async def test_connect_max_connections_exceeded(self, subscription_system):
        """Test connection limit enforcement."""
        # Fill up to max connections
        for i in range(subscription_system.max_connections):
            await subscription_system.connect(MockWebSocket())

        # Try to add one more connection
        with pytest.raises(Exception, match="Maximum connections reached"):
            await subscription_system.connect(MockWebSocket())

    @pytest.mark.asyncio
    async def test_disconnect_websocket(self, subscription_system, mock_websocket):
        """Test WebSocket disconnection."""
        connection_id = await subscription_system.connect(mock_websocket)

        # Create a subscription
        await subscription_system.subscribe(
            connection_id, "subscription { nodeCreated }"
        )

        # Verify subscription exists
        assert len(subscription_system.subscriptions) == 1

        await subscription_system.disconnect(connection_id)

        # Verify connection and subscriptions are cleaned up
        assert connection_id not in subscription_system.connections
        assert len(subscription_system.subscriptions) == 0
        assert mock_websocket.closed

    @pytest.mark.asyncio
    async def test_disconnect_nonexistent_connection(self, subscription_system):
        """Test disconnecting a non-existent connection."""
        # Should not raise an error
        await subscription_system.disconnect("nonexistent_id")

    @pytest.mark.asyncio
    async def test_subscribe_basic(self, subscription_system, mock_websocket):
        """Test basic subscription creation."""
        connection_id = await subscription_system.connect(mock_websocket)

        query = 'subscription { nodeCreated(entityTypes: ["Study"]) { eventId entityType } }'
        subscription_id = await subscription_system.subscribe(
            connection_id, query, variables={"entityTypes": ["Study"]}
        )

        assert subscription_id is not None
        assert subscription_id in subscription_system.subscriptions

        subscription = subscription_system.subscriptions[subscription_id]
        assert subscription.connection_id == connection_id
        assert subscription.query == query
        assert subscription.variables["entityTypes"] == ["Study"]
        assert (
            subscription_id
            in subscription_system.connections[connection_id].subscriptions
        )
        assert subscription_system.stats["total_subscriptions"] == 1

        # Verify subscription confirmation was sent
        messages_sent = [json.loads(msg) for msg in mock_websocket.messages_sent]
        success_messages = [
            msg for msg in messages_sent if msg.get("type") == "subscription_success"
        ]
        assert len(success_messages) == 1
        assert success_messages[0]["id"] == subscription_id

    @pytest.mark.asyncio
    async def test_subscribe_nonexistent_connection(self, subscription_system):
        """Test subscribing with non-existent connection."""
        with pytest.raises(Exception, match="Connection not found"):
            await subscription_system.subscribe(
                "nonexistent_id", "subscription { nodeCreated }"
            )

    @pytest.mark.asyncio
    async def test_unsubscribe(self, subscription_system, mock_websocket):
        """Test subscription cancellation."""
        connection_id = await subscription_system.connect(mock_websocket)
        subscription_id = await subscription_system.subscribe(
            connection_id, "subscription { nodeCreated }"
        )

        await subscription_system.unsubscribe(subscription_id)

        assert subscription_id not in subscription_system.subscriptions
        assert (
            subscription_id
            not in subscription_system.connections[connection_id].subscriptions
        )

    @pytest.mark.asyncio
    async def test_unsubscribe_nonexistent(self, subscription_system):
        """Test unsubscribing a non-existent subscription."""
        # Should not raise an error
        await subscription_system.unsubscribe("nonexistent_id")

    @pytest.mark.asyncio
    async def test_publish_event(self, started_system, mock_redis):
        """Test event publishing."""
        event = Event(
            event_id=str(uuid.uuid4()),
            event_type=EventType.NODE_CREATED,
            entity_type="Study",
            entity_id="study_123",
            data={"title": "Test Study"},
            user_id="test_user",
        )

        await started_system.publish_event(event)

        # Verify event was added to queue and Redis
        assert started_system.stats["total_events"] == 1
        assert started_system.stats["events_by_type"][EventType.NODE_CREATED.value] == 1

        # Wait a bit for Redis publishing
        await asyncio.sleep(0.1)
        assert len(mock_redis.published_messages) == 1

    @pytest.mark.asyncio
    async def test_event_matching_exact(self, subscription_system):
        """Test event matching with exact filters."""
        # Create subscription with specific entity types
        filters = SubscriptionFilter(
            event_types=[EventType.NODE_CREATED],
            entity_types=["Study"],
            entity_ids=["study_123"],
        )

        subscription = Subscription(
            subscription_id="sub_1",
            connection_id="conn_1",
            query="subscription { nodeCreated }",
            variables={},
            filters=filters,
        )
        subscription_system.subscriptions["sub_1"] = subscription

        # Create matching event
        event = Event(
            event_id="event_1",
            event_type=EventType.NODE_CREATED,
            entity_type="Study",
            entity_id="study_123",
            data={},
            user_id=None,
        )

        matches = subscription_system._find_matching_subscriptions(event)
        assert "sub_1" in matches

        # Create non-matching event
        event2 = Event(
            event_id="event_2",
            event_type=EventType.NODE_UPDATED,
            entity_type="Study",
            entity_id="study_123",
            data={},
            user_id=None,
        )

        matches2 = subscription_system._find_matching_subscriptions(event2)
        assert "sub_1" not in matches2

    @pytest.mark.asyncio
    async def test_event_matching_properties(self, subscription_system):
        """Test event matching with property filters."""
        filters = SubscriptionFilter(
            event_types=[EventType.NODE_CREATED],
            properties={"status": "published", "score": {"$gte": 5}},
        )

        subscription = Subscription(
            subscription_id="sub_1",
            connection_id="conn_1",
            query="subscription { nodeCreated }",
            variables={},
            filters=filters,
        )
        subscription_system.subscriptions["sub_1"] = subscription

        # Create matching event
        event = Event(
            event_id="event_1",
            event_type=EventType.NODE_CREATED,
            entity_type="Study",
            entity_id="study_123",
            data={"status": "published", "score": 8},
            user_id=None,
        )

        matches = subscription_system._find_matching_subscriptions(event)
        assert "sub_1" in matches

        # Create non-matching event (score too low)
        event2 = Event(
            event_id="event_2",
            event_type=EventType.NODE_CREATED,
            entity_type="Study",
            entity_id="study_456",
            data={"status": "published", "score": 3},
            user_id=None,
        )

        matches2 = subscription_system._find_matching_subscriptions(event2)
        assert "sub_1" not in matches2

    def test_property_matching_simple(self, subscription_system):
        """Test simple property matching."""
        data = {"status": "active", "type": "study"}
        filters = {"status": "active"}

        result = subscription_system._match_properties(data, filters)
        assert result is True

        filters_no_match = {"status": "inactive"}
        result2 = subscription_system._match_properties(data, filters_no_match)
        assert result2 is False

    def test_property_matching_operators(self, subscription_system):
        """Test property matching with operators."""
        data = {"score": 10, "tags": ["a", "b", "c"]}

        # Test $gte operator
        filters_gte = {"score": {"$gte": 5}}
        result = subscription_system._match_properties(data, filters_gte)
        assert result is True

        # Test $lte operator
        filters_lte = {"score": {"$lte": 15}}
        result2 = subscription_system._match_properties(data, filters_lte)
        assert result2 is True

        # Test $in operator (not implemented in original code, but tested for completeness)
        filters_in = {"score": {"$in": [8, 10, 12]}}
        result3 = subscription_system._match_properties(data, filters_in)
        assert result3 is True

    def test_subscription_filter_parsing(self, subscription_system):
        """Test subscription filter parsing from GraphQL queries."""
        query = 'subscription { nodeCreated(entityTypes: ["Study"]) }'
        variables = {"entityTypes": ["Study"], "userId": "user_123"}

        filters = subscription_system._parse_subscription_filters(query, variables)

        assert EventType.NODE_CREATED in filters.event_types
        assert filters.entity_types == ["Study"]
        assert filters.user_id == "user_123"

    def test_handler_name_extraction(self, subscription_system):
        """Test extracting handler names from queries."""
        test_cases = [
            ("subscription { nodeCreated }", "nodeCreated"),
            ("subscription { nodeUpdated }", "nodeUpdated"),
            ("subscription { edgeCreated }", "edgeCreated"),
            ("subscription { analysisCompleted }", "analysisCompleted"),
            ("subscription { someOtherQuery }", "default"),
        ]

        for query, expected in test_cases:
            result = subscription_system._get_handler_name(query)
            assert result == expected

    def test_format_event_data(self, subscription_system):
        """Test event data formatting for subscriptions."""
        event = Event(
            event_id="event_1",
            event_type=EventType.NODE_CREATED,
            entity_type="Study",
            entity_id="study_123",
            data={"title": "Test Study"},
            user_id="user_123",
            metadata={"source": "import"},
        )

        subscription = Subscription(
            subscription_id="sub_1",
            connection_id="conn_1",
            query="subscription { nodeCreated { eventId metadata user_id } }",
            variables={},
            filters=SubscriptionFilter(),
        )

        formatted = subscription_system._format_event_data(event, subscription)

        assert formatted["event_id"] == "event_1"
        assert formatted["event_type"] == "node_created"
        assert formatted["entity_type"] == "Study"
        assert formatted["entity_id"] == "study_123"
        assert formatted["data"]["title"] == "Test Study"
        assert "metadata" in formatted
        assert "user_id" in formatted

    @pytest.mark.asyncio
    async def test_send_message_success(self, subscription_system, mock_websocket):
        """Test successful message sending."""
        connection_id = await subscription_system.connect(mock_websocket)

        test_message = {"type": "test", "data": "hello"}
        await subscription_system._send_message(connection_id, test_message)

        assert len(mock_websocket.messages_sent) == 2  # Connection ack + test message
        sent_message = json.loads(mock_websocket.messages_sent[-1])
        assert sent_message == test_message

    @pytest.mark.asyncio
    async def test_send_message_failure(
        self, subscription_system, mock_failing_websocket
    ):
        """Test message sending failure and disconnect handling."""
        connection_id = await subscription_system.connect(mock_failing_websocket)

        # Clear the initial connection ack from failing
        mock_failing_websocket.messages_sent.clear()

        test_message = {"type": "test", "data": "hello"}
        await subscription_system._send_message(connection_id, test_message)

        # Connection should be disconnected due to send failure
        assert connection_id not in subscription_system.connections

    @pytest.mark.asyncio
    async def test_subscription_data_delivery(self, started_system, mock_websocket):
        """Test end-to-end subscription data delivery."""
        # Connect and subscribe
        connection_id = await started_system.connect(mock_websocket)
        subscription_id = await started_system.subscribe(
            connection_id, "subscription { nodeCreated }"
        )

        # Publish matching event
        event = Event(
            event_id="event_1",
            event_type=EventType.NODE_CREATED,
            entity_type="Study",
            entity_id="study_123",
            data={"title": "Test Study"},
            user_id=None,
        )

        await started_system.publish_event(event)

        # Allow time for event processing
        await asyncio.sleep(0.2)

        # Check that data was sent
        messages = [json.loads(msg) for msg in mock_websocket.messages_sent]
        data_messages = [msg for msg in messages if msg.get("type") == "data"]

        assert len(data_messages) >= 1
        data_msg = data_messages[0]
        assert data_msg["id"] == subscription_id
        assert data_msg["payload"]["data"]["event_id"] == "event_1"

    def test_get_statistics(self, subscription_system, mock_websocket):
        """Test statistics collection."""
        # Add some test data
        subscription_system.stats["total_connections"] = 5
        subscription_system.stats["total_subscriptions"] = 10
        subscription_system.stats["total_events"] = 100
        subscription_system.stats["events_by_type"]["node_created"] = 50
        subscription_system.stats["events_by_type"]["edge_created"] = 30

        # Add active connections
        connection = Connection(
            connection_id="conn_1", websocket=mock_websocket, user_id="user_1"
        )
        subscription_system.connections["conn_1"] = connection

        stats = subscription_system.get_statistics()

        assert stats["total_connections"] == 5
        assert stats["total_subscriptions"] == 10
        assert stats["total_events"] == 100
        assert stats["events_by_type"]["node_created"] == 50
        assert stats["events_by_type"]["edge_created"] == 30
        assert stats["active_connections"] == 1
        assert stats["connections_by_user"]["user_1"] == 1

    def test_connections_by_user(self, subscription_system):
        """Test user connection counting."""
        # Add connections with different users
        connections = [
            Connection("conn_1", MagicMock(), "user_1"),
            Connection("conn_2", MagicMock(), "user_1"),
            Connection("conn_3", MagicMock(), "user_2"),
            Connection("conn_4", MagicMock(), None),  # Anonymous
        ]

        for conn in connections:
            subscription_system.connections[conn.connection_id] = conn

        user_counts = subscription_system._get_connections_by_user()

        assert user_counts["user_1"] == 2
        assert user_counts["user_2"] == 1
        assert user_counts["anonymous"] == 1

    def test_register_handler(self, subscription_system):
        """Test handler registration."""

        def test_handler(subscription):
            return "handled"

        subscription_system.register_handler("test", test_handler)
        assert "test" in subscription_system.subscription_handlers
        assert subscription_system.subscription_handlers["test"] == test_handler

    @pytest.mark.asyncio
    async def test_redis_publishing(self, subscription_system, mock_redis):
        """Test Redis event publishing."""
        event = Event(
            event_id="event_1",
            event_type=EventType.NODE_CREATED,
            entity_type="Study",
            entity_id="study_123",
            data={"title": "Test Study"},
            user_id="user_123",
        )

        await subscription_system._publish_to_redis(event)

        assert len(mock_redis.published_messages) == 1
        published = mock_redis.published_messages[0]
        assert published["channel"] == "graph_events:node_created"

        event_data = json.loads(published["message"])
        assert event_data["event_id"] == "event_1"
        assert event_data["entity_type"] == "Study"

    @pytest.mark.asyncio
    async def test_redis_publishing_without_redis(self, subscription_system):
        """Test Redis publishing when Redis is not available."""
        subscription_system.redis = None

        event = Event(
            event_id="event_1",
            event_type=EventType.NODE_CREATED,
            entity_type="Study",
            entity_id="study_123",
            data={},
            user_id=None,
        )

        # Should not raise an error
        await subscription_system._publish_to_redis(event)

    @pytest.mark.asyncio
    async def test_concurrent_connections(self, subscription_system):
        """Test handling multiple concurrent connections."""
        websockets = [MockWebSocket() for _ in range(3)]
        connection_ids = []

        # Connect all WebSockets concurrently
        tasks = [
            subscription_system.connect(ws, user_id=f"user_{i}")
            for i, ws in enumerate(websockets)
        ]
        connection_ids = await asyncio.gather(*tasks)

        assert len(connection_ids) == 3
        assert len(subscription_system.connections) == 3

        # Disconnect all
        disconnect_tasks = [
            subscription_system.disconnect(conn_id) for conn_id in connection_ids
        ]
        await asyncio.gather(*disconnect_tasks)

        assert len(subscription_system.connections) == 0

    @pytest.mark.asyncio
    async def test_subscription_cleanup_on_disconnect(
        self, subscription_system, mock_websocket
    ):
        """Test that subscriptions are cleaned up when connection is lost."""
        connection_id = await subscription_system.connect(mock_websocket)

        # Create multiple subscriptions
        sub_ids = []
        for i in range(3):
            sub_id = await subscription_system.subscribe(
                connection_id, f"subscription {{ nodeCreated_{i} }}"
            )
            sub_ids.append(sub_id)

        assert len(subscription_system.subscriptions) == 3

        # Disconnect
        await subscription_system.disconnect(connection_id)

        # All subscriptions should be cleaned up
        assert len(subscription_system.subscriptions) == 0
        for sub_id in sub_ids:
            assert sub_id not in subscription_system.subscriptions
