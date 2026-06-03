"""Unit tests for WebSocket subscription system."""

from datetime import datetime
from unittest.mock import AsyncMock, Mock

import pytest
from fastapi import WebSocket

from brain_researcher.services.br_kg.subscriptions.websocket import (
    ConnectionManager,
    EventType,
    GraphEvent,
    Subscription,
    SubscriptionFilter,
)


class TestSubscriptionFilter:
    """Test suite for SubscriptionFilter."""

    def test_filter_creation(self):
        """Test creating subscription filters."""
        filter = SubscriptionFilter(
            event_types=[EventType.NODE_CREATED, EventType.NODE_UPDATED],
            node_types=["Concept", "Study"],
            properties={"active": True},
        )

        assert len(filter.event_types) == 2
        assert EventType.NODE_CREATED in filter.event_types
        assert "Concept" in filter.node_types
        assert filter.properties["active"] is True

    def test_empty_filter(self):
        """Test empty filter (matches all)."""
        filter = SubscriptionFilter()

        assert filter.event_types is None
        assert filter.node_types is None
        assert filter.edge_types is None
        assert filter.node_ids is None
        assert filter.properties is None


class TestGraphEvent:
    """Test suite for GraphEvent."""

    def test_event_creation(self):
        """Test creating graph events."""
        event = GraphEvent(
            event_type=EventType.NODE_CREATED,
            data={"node_id": "node1", "type": "Concept"},
        )

        assert event.event_type == EventType.NODE_CREATED
        assert event.data["node_id"] == "node1"
        assert event.event_id is not None
        assert isinstance(event.timestamp, datetime)

    def test_event_with_metadata(self):
        """Test event with metadata."""
        metadata = {"user": "test_user", "source": "api"}
        event = GraphEvent(
            event_type=EventType.EDGE_CREATED,
            data={"source": "A", "target": "B"},
            metadata=metadata,
        )

        assert event.metadata == metadata


class TestSubscription:
    """Test suite for Subscription."""

    def test_subscription_creation(self):
        """Test creating subscriptions."""
        filter = SubscriptionFilter(event_types=[EventType.NODE_CREATED])
        sub = Subscription(subscription_id="sub1", client_id="client1", filter=filter)

        assert sub.subscription_id == "sub1"
        assert sub.client_id == "client1"
        assert sub.filter == filter
        assert sub.event_count == 0
        assert isinstance(sub.created_at, datetime)

    def test_matches_event_by_type(self):
        """Test event matching by type."""
        filter = SubscriptionFilter(event_types=[EventType.NODE_CREATED])
        sub = Subscription("sub1", "client1", filter)

        # Matching event
        event1 = GraphEvent(event_type=EventType.NODE_CREATED, data={"node_id": "A"})
        assert sub.matches_event(event1) is True

        # Non-matching event
        event2 = GraphEvent(event_type=EventType.NODE_DELETED, data={"node_id": "A"})
        assert sub.matches_event(event2) is False

    def test_matches_event_by_node_type(self):
        """Test event matching by node type."""
        filter = SubscriptionFilter(node_types=["Concept", "Study"])
        sub = Subscription("sub1", "client1", filter)

        # Matching event
        event1 = GraphEvent(
            event_type=EventType.NODE_CREATED,
            data={"node_id": "A", "node_type": "Concept"},
        )
        assert sub.matches_event(event1) is True

        # Non-matching event
        event2 = GraphEvent(
            event_type=EventType.NODE_CREATED,
            data={"node_id": "B", "type": "Experiment"},
        )
        assert sub.matches_event(event2) is False

    def test_matches_event_by_properties(self):
        """Test event matching by properties."""
        filter = SubscriptionFilter(properties={"status": "active", "priority": "high"})
        sub = Subscription("sub1", "client1", filter)

        # Matching event
        event1 = GraphEvent(
            event_type=EventType.NODE_UPDATED,
            data={
                "node_id": "A",
                "properties": {
                    "status": "active",
                    "priority": "high",
                    "other": "value",
                },
            },
        )
        assert sub.matches_event(event1) is True

        # Non-matching event (missing property)
        event2 = GraphEvent(
            event_type=EventType.NODE_UPDATED,
            data={
                "node_id": "B",
                "properties": {"status": "active"},  # Missing 'priority'
            },
        )
        assert sub.matches_event(event2) is False

    def test_matches_event_complex_filter(self):
        """Test complex filter matching."""
        filter = SubscriptionFilter(
            event_types=[EventType.NODE_CREATED, EventType.NODE_UPDATED],
            node_types=["Concept"],
            properties={"active": True},
        )
        sub = Subscription("sub1", "client1", filter)

        # Matching event (all conditions met)
        event1 = GraphEvent(
            event_type=EventType.NODE_CREATED,
            data={"node_id": "A", "type": "Concept", "properties": {"active": True}},
        )
        assert sub.matches_event(event1) is True

        # Non-matching (wrong node type)
        event2 = GraphEvent(
            event_type=EventType.NODE_CREATED,
            data={"node_id": "B", "type": "Study", "properties": {"active": True}},
        )
        assert sub.matches_event(event2) is False


class TestConnectionManager:
    """Test suite for ConnectionManager."""

    @pytest.fixture
    def manager(self):
        """Create connection manager instance."""
        return ConnectionManager()

    @pytest.mark.asyncio
    async def test_connect(self, manager):
        """Test client connection."""
        websocket = AsyncMock(spec=WebSocket)
        client_id = "test_client"

        await manager.connect(websocket, client_id)

        assert client_id in manager.active_connections
        assert manager.active_connections[client_id] == websocket
        assert client_id in manager.client_subscriptions

        # Verify connection confirmation was sent
        websocket.accept.assert_called_once()
        websocket.send_json.assert_called_once()
        call_args = websocket.send_json.call_args[0][0]
        assert call_args["type"] == "connection_established"
        assert call_args["client_id"] == client_id

    @pytest.mark.asyncio
    async def test_disconnect(self, manager):
        """Test client disconnection."""
        websocket = AsyncMock(spec=WebSocket)
        client_id = "test_client"

        # Connect first
        await manager.connect(websocket, client_id)

        # Add a subscription
        filter = SubscriptionFilter()
        sub_id = await manager.subscribe(client_id, filter)

        # Disconnect
        await manager.disconnect(client_id)

        assert client_id not in manager.active_connections
        assert client_id not in manager.client_subscriptions
        assert sub_id not in manager.subscriptions

    @pytest.mark.asyncio
    async def test_subscribe(self, manager):
        """Test creating subscriptions."""
        websocket = AsyncMock(spec=WebSocket)
        client_id = "test_client"

        await manager.connect(websocket, client_id)

        filter = SubscriptionFilter(
            event_types=[EventType.NODE_CREATED], node_types=["Concept"]
        )

        sub_id = await manager.subscribe(client_id, filter)

        assert sub_id in manager.subscriptions
        assert sub_id in manager.client_subscriptions[client_id]

        subscription = manager.subscriptions[sub_id]
        assert subscription.client_id == client_id
        assert subscription.filter == filter

        # Verify confirmation was sent
        calls = websocket.send_json.call_args_list
        confirmation = calls[-1][0][0]  # Last call
        assert confirmation["type"] == EventType.SUBSCRIPTION_CONFIRMED.value
        assert confirmation["subscription_id"] == sub_id

    @pytest.mark.asyncio
    async def test_unsubscribe(self, manager):
        """Test removing subscriptions."""
        websocket = AsyncMock(spec=WebSocket)
        client_id = "test_client"

        await manager.connect(websocket, client_id)

        # Create subscription
        filter = SubscriptionFilter()
        sub_id = await manager.subscribe(client_id, filter)

        # Unsubscribe
        await manager.unsubscribe(client_id, sub_id)

        assert sub_id not in manager.subscriptions
        assert sub_id not in manager.client_subscriptions[client_id]

    @pytest.mark.asyncio
    async def test_publish_event(self, manager):
        """Test event publishing."""
        event = GraphEvent(
            event_type=EventType.NODE_CREATED, data={"node_id": "A", "type": "Concept"}
        )

        await manager.publish_event(event)

        # Event should be in queue
        assert manager.event_queue.qsize() > 0

    @pytest.mark.asyncio
    async def test_distribute_event(self, manager):
        """Test event distribution to subscribers."""
        # Create two clients with different filters
        ws1 = AsyncMock(spec=WebSocket)
        ws2 = AsyncMock(spec=WebSocket)

        await manager.connect(ws1, "client1")
        await manager.connect(ws2, "client2")

        # Client 1 subscribes to Concept nodes
        filter1 = SubscriptionFilter(node_types=["Concept"])
        sub1 = await manager.subscribe("client1", filter1)

        # Client 2 subscribes to Study nodes
        filter2 = SubscriptionFilter(node_types=["Study"])
        await manager.subscribe("client2", filter2)

        # Reset mock call counts
        ws1.send_json.reset_mock()
        ws2.send_json.reset_mock()

        # Distribute Concept node event
        event = GraphEvent(
            event_type=EventType.NODE_CREATED, data={"node_id": "A", "type": "Concept"}
        )

        await manager._distribute_event(event)

        # Only client1 should receive the event
        ws1.send_json.assert_called_once()
        ws2.send_json.assert_not_called()

        # Verify event content
        call_args = ws1.send_json.call_args[0][0]
        assert call_args["subscription_id"] == sub1
        assert call_args["event"]["data"]["node_id"] == "A"

    @pytest.mark.asyncio
    async def test_send_to_client(self, manager):
        """Test sending data to specific client."""
        websocket = AsyncMock(spec=WebSocket)
        client_id = "test_client"

        await manager.connect(websocket, client_id)
        websocket.send_json.reset_mock()

        data = {"message": "test", "value": 123}
        await manager.send_to_client(client_id, data)

        websocket.send_json.assert_called_once_with(data)

    @pytest.mark.asyncio
    async def test_broadcast(self, manager):
        """Test broadcasting to all clients."""
        ws1 = AsyncMock(spec=WebSocket)
        ws2 = AsyncMock(spec=WebSocket)
        ws3 = AsyncMock(spec=WebSocket)

        await manager.connect(ws1, "client1")
        await manager.connect(ws2, "client2")
        await manager.connect(ws3, "client3")

        # Reset mocks
        ws1.send_json.reset_mock()
        ws2.send_json.reset_mock()
        ws3.send_json.reset_mock()

        data = {"broadcast": "message"}
        await manager.broadcast(data)

        # All clients should receive the message
        ws1.send_json.assert_called_once_with(data)
        ws2.send_json.assert_called_once_with(data)
        ws3.send_json.assert_called_once_with(data)

    @pytest.mark.asyncio
    async def test_broadcast_with_disconnected_client(self, manager):
        """Test broadcast handles disconnected clients."""
        ws1 = AsyncMock(spec=WebSocket)
        ws2 = AsyncMock(spec=WebSocket)

        # ws2 will raise exception (disconnected)
        ws2.send_json.side_effect = Exception("Connection closed")

        await manager.connect(ws1, "client1")
        await manager.connect(ws2, "client2")

        data = {"broadcast": "message"}
        await manager.broadcast(data)

        # client2 should be disconnected
        assert "client1" in manager.active_connections
        assert "client2" not in manager.active_connections

    def test_get_statistics(self, manager):
        """Test statistics generation."""
        # Create mock setup
        manager.active_connections = {"client1": Mock(), "client2": Mock()}

        sub1 = Subscription("sub1", "client1", SubscriptionFilter())
        sub1.event_count = 10
        sub2 = Subscription("sub2", "client1", SubscriptionFilter())
        sub2.event_count = 5
        sub3 = Subscription("sub3", "client2", SubscriptionFilter())
        sub3.event_count = 8

        manager.subscriptions = {"sub1": sub1, "sub2": sub2, "sub3": sub3}

        stats = manager.get_statistics()

        assert stats["active_connections"] == 2
        assert stats["total_subscriptions"] == 3
        assert "client1" in stats["clients"]
        assert "client2" in stats["clients"]
        assert stats["event_counts"]["client1"] == 15  # 10 + 5
        assert stats["event_counts"]["client2"] == 8

    @pytest.mark.asyncio
    async def test_cleanup(self, manager):
        """Test cleanup operations."""
        # Setup connections and tasks
        ws1 = AsyncMock(spec=WebSocket)
        await manager.connect(ws1, "client1")

        # Create mock tasks
        task1 = AsyncMock()
        task2 = AsyncMock()
        manager.background_tasks = [task1, task2]

        # Mock Redis client
        manager.redis_client = AsyncMock()

        await manager.cleanup()

        # Tasks should be cancelled
        task1.cancel.assert_called_once()
        task2.cancel.assert_called_once()

        # Redis should be closed
        manager.redis_client.close.assert_called_once()

        # Clients should be disconnected
        assert len(manager.active_connections) == 0


class TestWebSocketIntegration:
    """Integration tests for WebSocket functionality."""

    @pytest.mark.asyncio
    async def test_subscription_workflow(self):
        """Test complete subscription workflow."""
        manager = ConnectionManager()

        # Simulate client connection
        ws = AsyncMock(spec=WebSocket)
        await manager.connect(ws, "test_client")

        # Create subscription
        filter = SubscriptionFilter(
            event_types=[EventType.NODE_CREATED], node_types=["Concept"]
        )
        await manager.subscribe("test_client", filter)

        # Reset mock
        ws.send_json.reset_mock()

        # Publish matching event
        event1 = GraphEvent(
            event_type=EventType.NODE_CREATED, data={"node_id": "A", "type": "Concept"}
        )
        await manager._distribute_event(event1)

        # Client should receive event
        ws.send_json.assert_called_once()

        # Publish non-matching event
        ws.send_json.reset_mock()
        event2 = GraphEvent(
            event_type=EventType.NODE_DELETED, data={"node_id": "A", "type": "Concept"}
        )
        await manager._distribute_event(event2)

        # Client should not receive event
        ws.send_json.assert_not_called()

        # Cleanup
        await manager.disconnect("test_client")
