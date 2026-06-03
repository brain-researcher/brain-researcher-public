"""
Comprehensive tests for WebSocket and real-time functionality in telemetry system.
"""

import asyncio
import json
import logging
import socket
import time
from datetime import datetime
from typing import Any

import pytest
import websockets
from websockets.exceptions import ConnectionClosed

from brain_researcher.services.telemetry.aggregator import UsageMetricsAggregator
from brain_researcher.services.telemetry.collector import TelemetryCollector
from brain_researcher.services.telemetry.models import (
    EventType,
    ServiceType,
    TelemetryConfiguration,
)


def _sockets_available() -> bool:
    try:
        sock = socket.socket()
        sock.close()
        return True
    except PermissionError:
        return False


pytestmark = pytest.mark.skipif(
    not _sockets_available(),
    reason="Socket operations are not permitted in this environment.",
)


# Mock WebSocket server for testing
class MockWebSocketServer:
    """Mock WebSocket server for testing real-time functionality."""

    def __init__(self, host="localhost", port=8765):
        self.host = host
        self.port = port
        self.clients = set()
        self.server = None
        self.running = False
        self.message_history = []
        self.connection_count = 0

    async def register_client(self, websocket, path):
        """Register a new WebSocket client."""
        self.clients.add(websocket)
        self.connection_count += 1
        logging.info(f"Client connected. Total clients: {len(self.clients)}")

        try:
            # Send welcome message
            await websocket.send(
                json.dumps(
                    {
                        "type": "connection_established",
                        "client_id": f"client_{len(self.clients)}",
                        "timestamp": datetime.utcnow().isoformat(),
                    }
                )
            )

            # Keep connection alive
            async for message in websocket:
                try:
                    data = json.loads(message)
                    await self.handle_message(websocket, data)
                except json.JSONDecodeError:
                    await websocket.send(
                        json.dumps({"type": "error", "message": "Invalid JSON"})
                    )

        except ConnectionClosed:
            logging.info("Client disconnected")
        finally:
            self.clients.remove(websocket)

    async def handle_message(self, websocket, data):
        """Handle incoming WebSocket messages."""
        self.message_history.append(data)

        if data.get("type") == "subscribe":
            # Handle subscription requests
            await websocket.send(
                json.dumps(
                    {
                        "type": "subscription_confirmed",
                        "topics": data.get("topics", []),
                        "timestamp": datetime.utcnow().isoformat(),
                    }
                )
            )
        elif data.get("type") == "ping":
            # Handle ping messages
            await websocket.send(
                json.dumps({"type": "pong", "timestamp": datetime.utcnow().isoformat()})
            )

    async def broadcast_message(self, message_data):
        """Broadcast message to all connected clients."""
        if not self.clients:
            return

        message = json.dumps(message_data)
        disconnected_clients = set()

        for client in self.clients:
            try:
                await client.send(message)
            except ConnectionClosed:
                disconnected_clients.add(client)

        # Clean up disconnected clients
        self.clients -= disconnected_clients

    async def start_server(self):
        """Start the WebSocket server."""
        self.server = await websockets.serve(
            self.register_client,
            self.host,
            self.port,
            ping_interval=20,
            ping_timeout=10,
        )
        self.running = True
        logging.info(f"WebSocket server started on ws://{self.host}:{self.port}")

    async def stop_server(self):
        """Stop the WebSocket server."""
        if self.server:
            self.server.close()
            await self.server.wait_closed()
            self.running = False
            logging.info("WebSocket server stopped")


# Mock WebSocket client for testing
class MockWebSocketClient:
    """Mock WebSocket client for testing."""

    def __init__(self, uri):
        self.uri = uri
        self.websocket = None
        self.connected = False
        self.messages_received = []
        self.connection_lost_callback = None

    async def connect(self):
        """Connect to WebSocket server."""
        try:
            self.websocket = await websockets.connect(self.uri)
            self.connected = True
            return True
        except Exception as e:
            logging.error(f"Failed to connect to WebSocket: {e}")
            return False

    async def disconnect(self):
        """Disconnect from WebSocket server."""
        if self.websocket:
            await self.websocket.close()
            self.connected = False

    async def send_message(self, data):
        """Send message to WebSocket server."""
        if self.websocket and self.connected:
            await self.websocket.send(json.dumps(data))

    async def listen_for_messages(self):
        """Listen for incoming WebSocket messages."""
        if not self.websocket:
            return

        try:
            async for message in self.websocket:
                data = json.loads(message)
                self.messages_received.append(data)

                if data.get("type") == "connection_lost":
                    if self.connection_lost_callback:
                        await self.connection_lost_callback()

        except ConnectionClosed:
            self.connected = False
            if self.connection_lost_callback:
                await self.connection_lost_callback()


# Real-time telemetry service for testing
class RealTimeTelemetryService:
    """Service that handles real-time telemetry updates via WebSocket."""

    def __init__(
        self, collector: TelemetryCollector, aggregator: UsageMetricsAggregator
    ):
        self.collector = collector
        self.aggregator = aggregator
        self.websocket_server = None
        self.update_interval = 5  # seconds
        self.running = False
        self._update_task = None

    async def start_realtime_service(self, host="localhost", port=8765):
        """Start the real-time WebSocket service."""
        self.websocket_server = MockWebSocketServer(host, port)
        await self.websocket_server.start_server()

        # Start periodic updates
        self._update_task = asyncio.create_task(self._periodic_updates())
        self.running = True

    async def stop_realtime_service(self):
        """Stop the real-time WebSocket service."""
        self.running = False

        if self._update_task:
            self._update_task.cancel()
            try:
                await self._update_task
            except asyncio.CancelledError:
                pass

        if self.websocket_server:
            await self.websocket_server.stop_server()

    async def _periodic_updates(self):
        """Send periodic updates to connected clients."""
        while self.running:
            try:
                # Get real-time metrics
                metrics = await self.aggregator.get_real_time_metrics()

                # Get collector stats
                collector_stats = self.collector.get_stats()

                # Prepare update message
                update_data = {
                    "type": "metrics_update",
                    "timestamp": datetime.utcnow().isoformat(),
                    "metrics": metrics,
                    "collector_stats": collector_stats,
                    "client_count": (
                        len(self.websocket_server.clients)
                        if self.websocket_server
                        else 0
                    ),
                }

                # Broadcast to all clients
                if self.websocket_server:
                    await self.websocket_server.broadcast_message(update_data)

                await asyncio.sleep(self.update_interval)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logging.error(f"Error in periodic updates: {e}")
                await asyncio.sleep(1)  # Brief pause before retrying


class TestWebSocketServer:
    """Test the WebSocket server functionality."""

    @pytest.fixture
    async def websocket_server(self):
        """Create and start a WebSocket server for testing."""
        server = MockWebSocketServer("localhost", 8765)
        await server.start_server()
        yield server
        await server.stop_server()

    @pytest.mark.asyncio
    async def test_websocket_server_startup_shutdown(self):
        """Test WebSocket server can start and stop."""
        server = MockWebSocketServer("localhost", 8766)

        # Server should not be running initially
        assert not server.running

        # Start server
        await server.start_server()
        assert server.running
        assert server.server is not None

        # Stop server
        await server.stop_server()
        assert not server.running

    @pytest.mark.asyncio
    async def test_websocket_client_connection(self, websocket_server):
        """Test WebSocket client can connect to server."""
        client = MockWebSocketClient("ws://localhost:8765")

        # Connect to server
        connected = await client.connect()
        assert connected
        assert client.connected

        # Should receive welcome message
        await asyncio.sleep(0.1)  # Allow time for message
        assert len(client.messages_received) > 0

        welcome_msg = client.messages_received[0]
        assert welcome_msg["type"] == "connection_established"
        assert "client_id" in welcome_msg

        # Disconnect
        await client.disconnect()
        assert not client.connected

    @pytest.mark.asyncio
    async def test_websocket_message_exchange(self, websocket_server):
        """Test bidirectional message exchange."""
        client = MockWebSocketClient("ws://localhost:8765")
        await client.connect()

        # Clear welcome message
        client.messages_received.clear()

        # Send ping message
        await client.send_message({"type": "ping", "data": "test"})

        # Start listening for messages
        listen_task = asyncio.create_task(client.listen_for_messages())

        # Wait for response
        await asyncio.sleep(0.1)
        listen_task.cancel()

        # Should receive pong response
        assert len(client.messages_received) > 0
        pong_msg = client.messages_received[0]
        assert pong_msg["type"] == "pong"

        await client.disconnect()

    @pytest.mark.asyncio
    async def test_websocket_subscription(self, websocket_server):
        """Test WebSocket subscription mechanism."""
        client = MockWebSocketClient("ws://localhost:8765")
        await client.connect()

        # Clear welcome message
        client.messages_received.clear()

        # Subscribe to topics
        await client.send_message(
            {"type": "subscribe", "topics": ["metrics", "events", "alerts"]}
        )

        # Start listening
        listen_task = asyncio.create_task(client.listen_for_messages())
        await asyncio.sleep(0.1)
        listen_task.cancel()

        # Should receive subscription confirmation
        assert len(client.messages_received) > 0
        sub_msg = client.messages_received[0]
        assert sub_msg["type"] == "subscription_confirmed"
        assert sub_msg["topics"] == ["metrics", "events", "alerts"]

        await client.disconnect()

    @pytest.mark.asyncio
    async def test_websocket_broadcast(self, websocket_server):
        """Test broadcasting messages to multiple clients."""
        # Connect multiple clients
        clients = []
        for _i in range(3):
            client = MockWebSocketClient("ws://localhost:8765")
            await client.connect()
            clients.append(client)

        # Clear welcome messages
        for client in clients:
            client.messages_received.clear()

        # Broadcast a message
        broadcast_data = {
            "type": "broadcast_test",
            "message": "Hello all clients",
            "timestamp": datetime.utcnow().isoformat(),
        }

        await websocket_server.broadcast_message(broadcast_data)

        # Start listening on all clients
        listen_tasks = [
            asyncio.create_task(client.listen_for_messages()) for client in clients
        ]

        await asyncio.sleep(0.1)

        # Cancel listening tasks
        for task in listen_tasks:
            task.cancel()

        # All clients should have received the broadcast
        for client in clients:
            assert len(client.messages_received) > 0
            received_msg = client.messages_received[0]
            assert received_msg["type"] == "broadcast_test"
            assert received_msg["message"] == "Hello all clients"

        # Disconnect all clients
        for client in clients:
            await client.disconnect()


class TestRealTimeTelemetryService:
    """Test the real-time telemetry service."""

    @pytest.fixture
    def telemetry_config(self):
        """Create telemetry configuration for testing."""
        return TelemetryConfiguration(
            collection_enabled=True,
            sampling_rate=1.0,
            batch_size=10,
            flush_interval_seconds=1,
        )

    @pytest.fixture
    def collector(self, telemetry_config):
        """Create telemetry collector."""
        return TelemetryCollector(telemetry_config)

    @pytest.fixture
    def aggregator(self):
        """Create usage metrics aggregator."""
        return UsageMetricsAggregator()

    @pytest.fixture
    async def realtime_service(self, collector, aggregator):
        """Create and start real-time telemetry service."""
        service = RealTimeTelemetryService(collector, aggregator)
        await service.start_realtime_service("localhost", 8767)
        yield service
        await service.stop_realtime_service()

    @pytest.mark.asyncio
    async def test_realtime_service_startup(self, collector, aggregator):
        """Test real-time service can start and stop."""
        service = RealTimeTelemetryService(collector, aggregator)

        # Should not be running initially
        assert not service.running

        # Start service
        await service.start_realtime_service("localhost", 8768)
        assert service.running
        assert service.websocket_server is not None
        assert service.websocket_server.running

        # Stop service
        await service.stop_realtime_service()
        assert not service.running

    @pytest.mark.asyncio
    async def test_realtime_metrics_broadcasting(self, realtime_service):
        """Test that real-time metrics are broadcast to clients."""
        # Connect a client
        client = MockWebSocketClient("ws://localhost:8767")
        await client.connect()

        # Clear welcome message
        client.messages_received.clear()

        # Start listening for messages
        listen_task = asyncio.create_task(client.listen_for_messages())

        # Wait for at least one update cycle
        await asyncio.sleep(6)  # Update interval is 5 seconds

        listen_task.cancel()

        # Should have received metrics updates
        metrics_updates = [
            msg
            for msg in client.messages_received
            if msg.get("type") == "metrics_update"
        ]

        assert len(metrics_updates) > 0

        # Check update structure
        update = metrics_updates[0]
        assert "timestamp" in update
        assert "metrics" in update
        assert "collector_stats" in update
        assert "client_count" in update

        await client.disconnect()

    @pytest.mark.asyncio
    async def test_realtime_event_integration(self, realtime_service, collector):
        """Test integration between event collection and real-time updates."""
        # Connect a client
        client = MockWebSocketClient("ws://localhost:8767")
        await client.connect()

        # Start collector
        await collector.start()

        # Clear initial messages
        client.messages_received.clear()

        # Collect some events
        for i in range(5):
            collector.collect(
                event_type=EventType.TOOL_INVOCATION,
                service=ServiceType.AGENT,
                feature_name=f"test_tool_{i}",
                duration_ms=100 + i * 50,
            )

        # Start listening for updates
        listen_task = asyncio.create_task(client.listen_for_messages())

        # Wait for updates
        await asyncio.sleep(6)

        listen_task.cancel()

        # Should have received updates reflecting the new events
        metrics_updates = [
            msg
            for msg in client.messages_received
            if msg.get("type") == "metrics_update"
        ]

        assert len(metrics_updates) > 0

        # Check that collector stats reflect the collected events
        update = metrics_updates[-1]  # Most recent update
        collector_stats = update["collector_stats"]
        assert collector_stats["events_collected"] >= 5

        await collector.stop()
        await client.disconnect()

    @pytest.mark.asyncio
    async def test_client_connection_tracking(self, realtime_service):
        """Test that client connections are properly tracked."""
        # Connect multiple clients
        clients = []
        for _i in range(3):
            client = MockWebSocketClient("ws://localhost:8767")
            await client.connect()
            clients.append(client)

        # Wait for connection registration
        await asyncio.sleep(0.2)

        # Check that server tracks the connections
        assert len(realtime_service.websocket_server.clients) == 3

        # Listen for updates on one client to verify client count
        client = clients[0]
        client.messages_received.clear()

        listen_task = asyncio.create_task(client.listen_for_messages())
        await asyncio.sleep(6)  # Wait for at least one update
        listen_task.cancel()

        # Check client count in updates
        metrics_updates = [
            msg
            for msg in client.messages_received
            if msg.get("type") == "metrics_update"
        ]

        if metrics_updates:
            update = metrics_updates[-1]
            assert update["client_count"] == 3

        # Disconnect clients
        for client in clients:
            await client.disconnect()

        # Wait for disconnection processing
        await asyncio.sleep(0.2)

        # Server should have no clients
        assert len(realtime_service.websocket_server.clients) == 0


class TestWebSocketErrorHandling:
    """Test WebSocket error handling and resilience."""

    @pytest.mark.asyncio
    async def test_connection_failure_handling(self):
        """Test handling of connection failures."""
        # Try to connect to non-existent server
        client = MockWebSocketClient("ws://localhost:9999")

        connected = await client.connect()
        assert not connected
        assert not client.connected

    @pytest.mark.asyncio
    async def test_invalid_message_handling(self, websocket_server):
        """Test handling of invalid WebSocket messages."""
        client = MockWebSocketClient("ws://localhost:8765")
        await client.connect()

        # Clear welcome message
        client.messages_received.clear()

        # Send invalid JSON
        if client.websocket:
            await client.websocket.send("invalid json {")

        # Start listening for responses
        listen_task = asyncio.create_task(client.listen_for_messages())
        await asyncio.sleep(0.1)
        listen_task.cancel()

        # Should receive error response
        error_messages = [
            msg for msg in client.messages_received if msg.get("type") == "error"
        ]

        assert len(error_messages) > 0
        assert "Invalid JSON" in error_messages[0]["message"]

        await client.disconnect()

    @pytest.mark.asyncio
    async def test_client_disconnection_cleanup(self, websocket_server):
        """Test that disconnected clients are properly cleaned up."""
        # Connect a client
        client = MockWebSocketClient("ws://localhost:8765")
        await client.connect()

        # Verify connection
        assert len(websocket_server.clients) == 1

        # Simulate abrupt disconnection
        if client.websocket:
            await client.websocket.close()

        # Try to broadcast a message (should trigger cleanup)
        await websocket_server.broadcast_message(
            {"type": "test_message", "data": "test"}
        )

        # Wait for cleanup
        await asyncio.sleep(0.1)

        # Client should be removed from server's client list
        assert len(websocket_server.clients) == 0

    @pytest.mark.asyncio
    async def test_server_restart_resilience(self):
        """Test client resilience to server restarts."""
        # Start server
        server = MockWebSocketServer("localhost", 8769)
        await server.start_server()

        # Connect client
        client = MockWebSocketClient("ws://localhost:8769")
        await client.connect()
        assert client.connected

        # Stop server
        await server.stop_server()

        # Client should detect disconnection
        # In a real implementation, client would attempt to reconnect

        # Restart server
        server2 = MockWebSocketServer("localhost", 8769)
        await server2.start_server()

        # Client could reconnect (would need reconnection logic)
        client2 = MockWebSocketClient("ws://localhost:8769")
        reconnected = await client2.connect()
        assert reconnected

        await client2.disconnect()
        await server2.stop_server()


class TestWebSocketPerformance:
    """Test WebSocket performance and scalability."""

    @pytest.mark.performance
    @pytest.mark.asyncio
    async def test_multiple_client_connections(self, websocket_server):
        """Test server performance with multiple concurrent clients."""
        num_clients = 50
        clients = []

        start_time = time.time()

        # Connect many clients concurrently
        connection_tasks = []
        for _i in range(num_clients):
            client = MockWebSocketClient("ws://localhost:8765")
            clients.append(client)
            connection_tasks.append(client.connect())

        # Wait for all connections
        results = await asyncio.gather(*connection_tasks)

        connection_time = time.time() - start_time

        # All clients should connect successfully
        assert all(results)
        assert len(websocket_server.clients) == num_clients

        # Connection time should be reasonable
        assert (
            connection_time < 5.0
        ), f"Connection time too slow: {connection_time:.2f}s"

        # Test broadcasting to all clients
        broadcast_start = time.time()

        await websocket_server.broadcast_message(
            {
                "type": "performance_test",
                "data": "test_broadcast",
                "timestamp": datetime.utcnow().isoformat(),
            }
        )

        broadcast_time = time.time() - broadcast_start

        # Broadcast should be fast even with many clients
        assert broadcast_time < 1.0, f"Broadcast too slow: {broadcast_time:.2f}s"

        # Disconnect all clients
        disconnect_tasks = [client.disconnect() for client in clients]
        await asyncio.gather(*disconnect_tasks)

    @pytest.mark.performance
    @pytest.mark.asyncio
    async def test_high_frequency_messaging(self, websocket_server):
        """Test server performance with high-frequency messages."""
        client = MockWebSocketClient("ws://localhost:8765")
        await client.connect()

        # Send many messages rapidly
        num_messages = 1000
        start_time = time.time()

        send_tasks = []
        for i in range(num_messages):
            task = client.send_message(
                {
                    "type": "ping",
                    "sequence": i,
                    "timestamp": datetime.utcnow().isoformat(),
                }
            )
            send_tasks.append(task)

        await asyncio.gather(*send_tasks)

        send_time = time.time() - start_time

        # Should handle high-frequency messages efficiently
        messages_per_second = num_messages / send_time
        assert (
            messages_per_second > 100
        ), f"Message throughput too low: {messages_per_second:.1f} msg/s"

        # Server should have received all messages
        await asyncio.sleep(0.5)  # Allow processing time
        assert len(websocket_server.message_history) >= num_messages

        await client.disconnect()

    @pytest.mark.performance
    @pytest.mark.asyncio
    async def test_memory_usage_stability(self):
        """Test that WebSocket server doesn't have memory leaks."""
        server = MockWebSocketServer("localhost", 8770)
        await server.start_server()

        # Simulate multiple connection/disconnection cycles
        for cycle in range(10):
            clients = []

            # Connect clients
            for _i in range(20):
                client = MockWebSocketClient("ws://localhost:8770")
                await client.connect()
                clients.append(client)

            # Send some messages
            for client in clients:
                await client.send_message(
                    {"type": "test", "cycle": cycle, "data": "x" * 100}  # Some data
                )

            # Disconnect all clients
            for client in clients:
                await client.disconnect()

            # Wait for cleanup
            await asyncio.sleep(0.1)

            # Server should clean up properly
            assert len(server.clients) == 0

        # Message history should be manageable size
        # (In production, you'd implement history cleanup)
        assert len(server.message_history) < 10000

        await server.stop_server()


class TestWebSocketIntegration:
    """Integration tests for WebSocket with telemetry system."""

    @pytest.mark.integration
    @pytest.mark.asyncio
    async def test_end_to_end_realtime_telemetry(self):
        """Test complete end-to-end real-time telemetry flow."""
        # Setup telemetry components
        config = TelemetryConfiguration(
            collection_enabled=True,
            sampling_rate=1.0,
            batch_size=5,
            flush_interval_seconds=1,
        )
        collector = TelemetryCollector(config)
        aggregator = UsageMetricsAggregator()

        # Connect collector to aggregator
        collector.add_processing_handler(aggregator.add_events)

        # Start real-time service
        realtime_service = RealTimeTelemetryService(collector, aggregator)
        await realtime_service.start_realtime_service("localhost", 8771)

        # Start collector
        await collector.start()

        try:
            # Connect WebSocket client
            client = MockWebSocketClient("ws://localhost:8771")
            await client.connect()

            # Start listening for updates
            client.messages_received.clear()
            listen_task = asyncio.create_task(client.listen_for_messages())

            # Collect various types of events
            events_to_collect = [
                {
                    "event_type": EventType.TOOL_INVOCATION,
                    "service": ServiceType.AGENT,
                    "feature_name": "fmri_analysis",
                    "duration_ms": 2000,
                    "success": True,
                },
                {
                    "event_type": EventType.PAGE_VIEW,
                    "service": ServiceType.WEB_UI,
                    "feature_name": "dashboard",
                    "success": True,
                },
                {
                    "event_type": EventType.FEATURE_ACCESS,
                    "service": ServiceType.BR_KG,
                    "feature_name": "knowledge_search",
                    "duration_ms": 800,
                    "success": False,
                    "error_message": "Search timeout",
                },
            ]

            # Collect events
            for event_data in events_to_collect:
                collector.collect(**event_data)

            # Wait for processing and real-time updates
            await asyncio.sleep(7)  # Allow for flush and update cycles

            listen_task.cancel()

            # Verify real-time updates were received
            metrics_updates = [
                msg
                for msg in client.messages_received
                if msg.get("type") == "metrics_update"
            ]

            assert len(metrics_updates) > 0

            # Check latest update contains our events
            latest_update = metrics_updates[-1]
            collector_stats = latest_update["collector_stats"]

            assert collector_stats["events_collected"] >= 3
            assert "metrics" in latest_update

            # Verify aggregator processed the events
            aggregator_stats = aggregator.get_aggregator_stats()
            assert aggregator_stats["total_events"] >= 3

            await client.disconnect()

        finally:
            # Cleanup
            await collector.stop()
            await realtime_service.stop_realtime_service()

    @pytest.mark.integration
    @pytest.mark.asyncio
    async def test_websocket_failover_and_recovery(self):
        """Test WebSocket failover and recovery scenarios."""
        config = TelemetryConfiguration(collection_enabled=True)
        collector = TelemetryCollector(config)
        aggregator = UsageMetricsAggregator()

        # Start service on primary port
        service1 = RealTimeTelemetryService(collector, aggregator)
        await service1.start_realtime_service("localhost", 8772)

        try:
            # Connect client
            client = MockWebSocketClient("ws://localhost:8772")
            await client.connect()
            assert client.connected

            # Collect initial events
            collector.collect(
                event_type=EventType.TOOL_INVOCATION,
                service=ServiceType.AGENT,
                feature_name="test_tool",
            )

            # Stop primary service (simulate failure)
            await service1.stop_realtime_service()

            # Client should detect disconnection
            await asyncio.sleep(0.2)

            # Start backup service on different port
            service2 = RealTimeTelemetryService(collector, aggregator)
            await service2.start_realtime_service("localhost", 8773)

            # Client would need to reconnect to backup (manual reconnection for test)
            client2 = MockWebSocketClient("ws://localhost:8773")
            await client2.connect()
            assert client2.connected

            # Continue collecting events
            collector.collect(
                event_type=EventType.FEATURE_ACCESS,
                service=ServiceType.WEB_UI,
                feature_name="recovery_test",
            )

            # Verify backup service is working
            client2.messages_received.clear()
            listen_task = asyncio.create_task(client2.listen_for_messages())
            await asyncio.sleep(6)
            listen_task.cancel()

            updates = [
                msg
                for msg in client2.messages_received
                if msg.get("type") == "metrics_update"
            ]
            assert len(updates) > 0

            await client2.disconnect()
            await service2.stop_realtime_service()

        finally:
            if service1.running:
                await service1.stop_realtime_service()


# Utility functions for WebSocket testing
def create_mock_telemetry_events(count: int) -> list[dict[str, Any]]:
    """Create mock telemetry events for testing."""
    events = []
    event_types = [
        EventType.TOOL_INVOCATION,
        EventType.PAGE_VIEW,
        EventType.FEATURE_ACCESS,
    ]
    services = [ServiceType.AGENT, ServiceType.WEB_UI, ServiceType.BR_KG]

    for i in range(count):
        events.append(
            {
                "event_type": event_types[i % len(event_types)],
                "service": services[i % len(services)],
                "feature_name": f"test_feature_{i % 10}",
                "duration_ms": 100 + (i * 50) % 2000,
                "success": i % 10 != 9,  # 10% failure rate
                "error_message": "Test error" if i % 10 == 9 else None,
            }
        )

    return events


@pytest.mark.websocket
class TestWebSocketLoadTesting:
    """Load testing for WebSocket functionality."""

    @pytest.mark.load
    @pytest.mark.asyncio
    async def test_websocket_load_with_telemetry_events(self):
        """Test WebSocket under high telemetry event load."""
        config = TelemetryConfiguration(
            collection_enabled=True,
            sampling_rate=1.0,
            batch_size=50,
            flush_interval_seconds=2,
            max_events_per_second=10000,
        )
        collector = TelemetryCollector(config)
        aggregator = UsageMetricsAggregator()
        collector.add_processing_handler(aggregator.add_events)

        # Start services
        await collector.start()
        realtime_service = RealTimeTelemetryService(collector, aggregator)
        await realtime_service.start_realtime_service("localhost", 8774)

        try:
            # Connect multiple monitoring clients
            clients = []
            for _i in range(5):
                client = MockWebSocketClient("ws://localhost:8774")
                await client.connect()
                clients.append(client)

            # Generate high volume of telemetry events
            start_time = time.time()

            # Simulate concurrent event collection
            async def generate_events():
                events = create_mock_telemetry_events(1000)
                for event_data in events:
                    collector.collect(**event_data)
                    if len(events) % 100 == 0:
                        await asyncio.sleep(0.01)  # Brief pause to prevent overwhelming

            # Start event generation
            event_task = asyncio.create_task(generate_events())

            # Start monitoring on clients
            listen_tasks = [
                asyncio.create_task(client.listen_for_messages()) for client in clients
            ]

            # Run load test for duration
            await asyncio.sleep(10)  # 10 second load test

            # Stop tasks
            event_task.cancel()
            for task in listen_tasks:
                task.cancel()

            time.time() - start_time

            # Verify system handled the load
            collector_stats = collector.get_stats()
            aggregator.get_aggregator_stats()

            # Should have processed significant number of events
            assert collector_stats["events_collected"] > 500
            assert (
                collector_stats["processing_errors"]
                < collector_stats["events_collected"] * 0.1
            )  # <10% error rate

            # All clients should have received regular updates
            for client in clients:
                updates = [
                    msg
                    for msg in client.messages_received
                    if msg.get("type") == "metrics_update"
                ]
                assert len(updates) > 0  # Should have received at least one update

            # Cleanup
            for client in clients:
                await client.disconnect()

        finally:
            await collector.stop()
            await realtime_service.stop_realtime_service()
