"""Unit tests for CDC processor streaming module.

This module tests the Change Data Capture functionality including:
- Event detection and processing
- Neo4j integration
- Async operation handling
- Error conditions and edge cases
"""

import asyncio
from datetime import datetime
from unittest.mock import AsyncMock, Mock, patch

import pytest

# Import the modules to test
try:
    from brain_researcher.services.br_kg.streaming.cdc_processor import (
        CDCError,
        CDCProcessor,
        ChangeType,
        GraphChangeEvent,
        integrate_cdc_with_subscriptions,
    )
except ImportError:
    # Fallback if absolute imports don't work
    import os
    import sys

    sys.path.append(os.path.join(os.path.dirname(__file__), "..", "..", "..", ".."))
    from brain_researcher.services.br_kg.streaming.cdc_processor import (
        CDCError,
        CDCProcessor,
        ChangeType,
        GraphChangeEvent,
        integrate_cdc_with_subscriptions,
    )


class TestGraphChangeEvent:
    """Test GraphChangeEvent data class."""

    def test_event_creation(self):
        """Test creating a GraphChangeEvent."""
        timestamp = datetime.now()
        event = GraphChangeEvent(
            event_id="test-123",
            change_type=ChangeType.NODE_CREATED,
            timestamp=timestamp,
            entity_id="node-456",
            entity_type="node",
            labels=["Person", "User"],
            new_properties={"name": "John", "age": 30},
        )

        assert event.event_id == "test-123"
        assert event.change_type == ChangeType.NODE_CREATED
        assert event.timestamp == timestamp
        assert event.entity_id == "node-456"
        assert event.entity_type == "node"
        assert event.labels == ["Person", "User"]
        assert event.new_properties == {"name": "John", "age": 30}
        assert event.old_properties == {}

    def test_to_dict_conversion(self):
        """Test converting event to dictionary."""
        timestamp = datetime.now()
        event = GraphChangeEvent(
            event_id="test-123",
            change_type=ChangeType.RELATIONSHIP_UPDATED,
            timestamp=timestamp,
            entity_id="rel-789",
            entity_type="relationship",
            old_properties={"weight": 0.5},
            new_properties={"weight": 0.8},
            property_changes={"weight": {"old": 0.5, "new": 0.8}},
            start_node_id="node-1",
            end_node_id="node-2",
            relationship_type="KNOWS",
        )

        event_dict = event.to_dict()

        assert event_dict["event_id"] == "test-123"
        assert event_dict["change_type"] == "relationship_updated"
        assert event_dict["timestamp"] == timestamp.isoformat()
        assert event_dict["entity_id"] == "rel-789"
        assert event_dict["entity_type"] == "relationship"
        assert event_dict["old_properties"] == {"weight": 0.5}
        assert event_dict["new_properties"] == {"weight": 0.8}
        assert event_dict["property_changes"] == {"weight": {"old": 0.5, "new": 0.8}}
        assert event_dict["start_node_id"] == "node-1"
        assert event_dict["end_node_id"] == "node-2"
        assert event_dict["relationship_type"] == "KNOWS"

    def test_from_dict_conversion(self):
        """Test creating event from dictionary."""
        timestamp = datetime.now()
        event_dict = {
            "event_id": "test-456",
            "change_type": "node_deleted",
            "timestamp": timestamp.isoformat(),
            "entity_id": "node-789",
            "entity_type": "node",
            "labels": ["Document"],
            "old_properties": {"title": "Test Doc"},
            "user_id": "user-123",
            "metadata": {"source": "test"},
        }

        event = GraphChangeEvent.from_dict(event_dict)

        assert event.event_id == "test-456"
        assert event.change_type == ChangeType.NODE_DELETED
        assert event.timestamp == timestamp
        assert event.entity_id == "node-789"
        assert event.entity_type == "node"
        assert event.labels == ["Document"]
        assert event.old_properties == {"title": "Test Doc"}
        assert event.user_id == "user-123"
        assert event.metadata == {"source": "test"}


class TestCDCProcessor:
    """Test CDCProcessor class."""

    @pytest.fixture
    def mock_driver(self):
        """Create a mock Neo4j driver."""
        driver = Mock()
        driver.session.return_value.__enter__ = Mock()
        driver.session.return_value.__exit__ = Mock()
        driver.close = Mock()
        return driver

    @pytest.fixture
    def cdc_processor(self, mock_driver):
        """Create CDCProcessor instance with mocked dependencies."""
        with patch(
            "brain_researcher.services.br_kg.streaming.cdc_processor.GraphDatabase"
        ) as mock_graphdb:
            mock_graphdb.driver.return_value = mock_driver
            processor = CDCProcessor(
                neo4j_uri="neo4j://localhost:7687",
                neo4j_user="neo4j",
                neo4j_password="password",
                buffer_size=10,
                batch_interval=0.1,
            )
            return processor

    @pytest.mark.asyncio
    async def test_processor_initialization(self, cdc_processor):
        """Test CDC processor initialization."""
        assert cdc_processor.neo4j_uri == "neo4j://localhost:7687"
        assert cdc_processor.neo4j_user == "neo4j"
        assert cdc_processor.neo4j_password == "password"
        assert cdc_processor.buffer_size == 10
        assert cdc_processor.batch_interval == 0.1
        assert not cdc_processor.is_running
        assert len(cdc_processor.event_buffer) == 0
        assert len(cdc_processor.event_handlers) == 0
        assert len(cdc_processor.batch_handlers) == 0
        assert cdc_processor.stats["events_processed"] == 0

    @pytest.mark.asyncio
    async def test_start_stop_processor(self, cdc_processor, mock_driver):
        """Test starting and stopping the CDC processor."""
        # Mock session operations
        mock_session = Mock()
        mock_session.run.return_value = []
        mock_driver.session.return_value.__enter__.return_value = mock_session

        # Start processor
        await cdc_processor.start()

        assert cdc_processor.is_running
        assert cdc_processor.driver is not None
        assert len(cdc_processor.tasks) > 0

        # Stop processor
        await cdc_processor.stop()

        assert not cdc_processor.is_running
        assert cdc_processor.driver is None

    @pytest.mark.asyncio
    async def test_connection_failure(self):
        """Test handling of connection failures."""
        with patch(
            "brain_researcher.services.br_kg.streaming.cdc_processor.GraphDatabase"
        ) as mock_graphdb:
            # Mock driver that fails connection test
            mock_driver = Mock()
            mock_session = Mock()
            mock_session.run.side_effect = Exception("Connection failed")
            mock_driver.session.return_value.__enter__.return_value = mock_session
            mock_graphdb.driver.return_value = mock_driver

            processor = CDCProcessor(
                neo4j_uri="neo4j://localhost:7687",
                neo4j_user="neo4j",
                neo4j_password="password",
            )

            with pytest.raises(CDCError, match="Failed to start CDC processor"):
                await processor.start()

    @pytest.mark.asyncio
    async def test_event_handler_registration(self, cdc_processor):
        """Test event handler registration and removal."""

        def test_handler(event):
            pass

        def test_batch_handler(events):
            pass

        # Add handlers
        cdc_processor.add_event_handler(test_handler)
        cdc_processor.add_batch_handler(test_batch_handler)

        assert len(cdc_processor.event_handlers) == 1
        assert len(cdc_processor.batch_handlers) == 1
        assert test_handler in cdc_processor.event_handlers
        assert test_batch_handler in cdc_processor.batch_handlers

        # Remove handlers
        cdc_processor.remove_event_handler(test_handler)
        cdc_processor.remove_batch_handler(test_batch_handler)

        assert len(cdc_processor.event_handlers) == 0
        assert len(cdc_processor.batch_handlers) == 0

    @pytest.mark.asyncio
    async def test_event_buffering(self, cdc_processor):
        """Test event buffering and processing."""
        events_processed = []

        def test_handler(event):
            events_processed.append(event)

        cdc_processor.add_event_handler(test_handler)

        # Create test event
        event = GraphChangeEvent(
            event_id="test-event",
            change_type=ChangeType.NODE_CREATED,
            timestamp=datetime.now(),
            entity_id="node-123",
            entity_type="node",
        )

        # Add event to buffer
        await cdc_processor._add_event(event)

        assert len(cdc_processor.event_buffer) == 1
        assert len(events_processed) == 1
        assert events_processed[0].event_id == "test-event"
        assert cdc_processor.stats["events_processed"] == 1

    @pytest.mark.asyncio
    async def test_batch_processing(self, cdc_processor):
        """Test batch processing when buffer is full."""
        batches_processed = []

        def test_batch_handler(events):
            batches_processed.append(events)

        cdc_processor.add_batch_handler(test_batch_handler)

        # Fill buffer beyond capacity
        for i in range(cdc_processor.buffer_size + 1):
            event = GraphChangeEvent(
                event_id=f"event-{i}",
                change_type=ChangeType.NODE_CREATED,
                timestamp=datetime.now(),
                entity_id=f"node-{i}",
                entity_type="node",
            )
            await cdc_processor._add_event(event)

        # Should trigger batch processing
        assert len(batches_processed) >= 1
        assert len(batches_processed[0]) == cdc_processor.buffer_size
        assert cdc_processor.stats["batches_processed"] >= 1

    @pytest.mark.asyncio
    async def test_node_change_detection(self, cdc_processor, mock_driver):
        """Test node change detection."""
        # Mock current state query
        mock_session = Mock()

        # First call - empty initial state
        mock_session.run.side_effect = [
            [],  # Initial nodes query
            [],  # Initial relationships query
            [  # Current nodes query
                Mock(
                    values={
                        "id": "node-1",
                        "labels": ["Person"],
                        "props": {"name": "John", "age": 30},
                    }
                )
            ],
        ]

        mock_driver.session.return_value.__enter__.return_value = mock_session

        events_captured = []

        def capture_event(event):
            events_captured.append(event)

        cdc_processor.add_event_handler(capture_event)

        # Initialize and capture changes
        await cdc_processor._initialize_change_tracking()
        await cdc_processor._capture_node_changes(mock_session, "session-1", "user-1")

        # Should detect new node
        assert len(events_captured) == 1
        assert events_captured[0].change_type == ChangeType.NODE_CREATED
        assert events_captured[0].entity_id == "node-1"
        assert events_captured[0].labels == ["Person"]
        assert events_captured[0].new_properties == {"name": "John", "age": 30}

    @pytest.mark.asyncio
    async def test_property_change_detection(self, cdc_processor):
        """Test property change detection."""
        # Set up initial state
        cdc_processor.node_states["node-1"] = {
            "labels": ["Person"],
            "properties": {"name": "John", "age": 30},
        }

        # Mock updated state
        mock_session = Mock()
        mock_session.run.return_value = [
            Mock(
                values={
                    "id": "node-1",
                    "labels": ["Person"],
                    "props": {"name": "John", "age": 31},
                }
            )
        ]

        events_captured = []

        def capture_event(event):
            events_captured.append(event)

        cdc_processor.add_event_handler(capture_event)

        await cdc_processor._capture_node_changes(mock_session, "session-1", "user-1")

        # Should detect property change
        assert len(events_captured) == 1
        assert events_captured[0].change_type == ChangeType.NODE_UPDATED
        assert events_captured[0].property_changes["age"]["old"] == 30
        assert events_captured[0].property_changes["age"]["new"] == 31

    @pytest.mark.asyncio
    async def test_label_change_detection(self, cdc_processor):
        """Test label change detection."""
        # Set up initial state
        cdc_processor.node_states["node-1"] = {
            "labels": ["Person"],
            "properties": {"name": "John"},
        }

        # Mock updated state with new label
        mock_session = Mock()
        mock_session.run.return_value = [
            Mock(
                values={
                    "id": "node-1",
                    "labels": ["Person", "Employee"],
                    "props": {"name": "John"},
                }
            )
        ]

        events_captured = []

        def capture_event(event):
            events_captured.append(event)

        cdc_processor.add_event_handler(capture_event)

        await cdc_processor._capture_node_changes(mock_session, "session-1", "user-1")

        # Should detect label addition
        label_events = [
            e for e in events_captured if e.change_type == ChangeType.LABEL_ADDED
        ]
        assert len(label_events) == 1
        assert label_events[0].labels == ["Employee"]
        assert label_events[0].metadata["added_label"] == "Employee"

    @pytest.mark.asyncio
    async def test_node_deletion_detection(self, cdc_processor):
        """Test node deletion detection."""
        # Set up initial state
        cdc_processor.node_states["node-1"] = {
            "labels": ["Person"],
            "properties": {"name": "John"},
        }

        # Mock empty current state (node was deleted)
        mock_session = Mock()
        mock_session.run.return_value = []

        events_captured = []

        def capture_event(event):
            events_captured.append(event)

        cdc_processor.add_event_handler(capture_event)

        await cdc_processor._capture_node_changes(mock_session, "session-1", "user-1")

        # Should detect node deletion
        assert len(events_captured) == 1
        assert events_captured[0].change_type == ChangeType.NODE_DELETED
        assert events_captured[0].entity_id == "node-1"
        assert events_captured[0].old_properties == {"name": "John"}

    @pytest.mark.asyncio
    async def test_relationship_change_detection(self, cdc_processor, mock_driver):
        """Test relationship change detection."""
        # Mock session with new relationship
        mock_session = Mock()
        mock_session.run.return_value = [
            Mock(
                values={
                    "rel_id": "rel-1",
                    "start_id": "node-1",
                    "end_id": "node-2",
                    "rel_type": "KNOWS",
                    "props": {"since": "2023"},
                }
            )
        ]

        events_captured = []

        def capture_event(event):
            events_captured.append(event)

        cdc_processor.add_event_handler(capture_event)

        await cdc_processor._capture_relationship_changes(
            mock_session, "session-1", "user-1"
        )

        # Should detect new relationship
        assert len(events_captured) == 1
        assert events_captured[0].change_type == ChangeType.RELATIONSHIP_CREATED
        assert events_captured[0].entity_id == "rel-1"
        assert events_captured[0].start_node_id == "node-1"
        assert events_captured[0].end_node_id == "node-2"
        assert events_captured[0].relationship_type == "KNOWS"

    @pytest.mark.asyncio
    async def test_error_handling(self, cdc_processor):
        """Test error handling in event processing."""

        def failing_handler(event):
            raise Exception("Handler failed")

        cdc_processor.add_event_handler(failing_handler)

        # Create test event
        event = GraphChangeEvent(
            event_id="test-event",
            change_type=ChangeType.NODE_CREATED,
            timestamp=datetime.now(),
            entity_id="node-123",
            entity_type="node",
        )

        # Should not raise exception, but increment error count
        await cdc_processor._add_event(event)

        assert cdc_processor.stats["errors"] == 1

    @pytest.mark.asyncio
    async def test_manual_trigger(self, cdc_processor, mock_driver):
        """Test manual change detection trigger."""
        # Mock empty sessions
        mock_session = Mock()
        mock_session.run.return_value = []
        mock_driver.session.return_value.__enter__.return_value = mock_session

        cdc_processor.is_running = True

        # Should not raise exception
        await cdc_processor.manual_trigger("session-1", "user-1")

    @pytest.mark.asyncio
    async def test_reset_tracking(self, cdc_processor, mock_driver):
        """Test resetting tracking state."""
        # Set up some state
        cdc_processor.node_states["node-1"] = {"labels": [], "properties": {}}
        cdc_processor.relationship_states["rel-1"] = {"properties": {}}
        cdc_processor.event_buffer.append(Mock())

        # Mock empty sessions for re-initialization
        mock_session = Mock()
        mock_session.run.return_value = []
        mock_driver.session.return_value.__enter__.return_value = mock_session

        await cdc_processor.reset_tracking()

        assert len(cdc_processor.node_states) == 0
        assert len(cdc_processor.relationship_states) == 0
        assert len(cdc_processor.event_buffer) == 0

    def test_get_stats(self, cdc_processor):
        """Test getting CDC processor statistics."""
        # Add some test data
        cdc_processor.node_states["node-1"] = {}
        cdc_processor.relationship_states["rel-1"] = {}
        cdc_processor.event_buffer.append(Mock())
        cdc_processor.stats["events_processed"] = 5

        stats = cdc_processor.get_stats()

        assert not stats["is_running"]
        assert stats["buffer_size"] == 1
        assert stats["tracked_nodes"] == 1
        assert stats["tracked_relationships"] == 1
        assert stats["events_processed"] == 5

    @pytest.mark.asyncio
    async def test_import_error_handling(self):
        """Test handling when Neo4j driver is not available."""
        with patch(
            "brain_researcher.services.br_kg.streaming.cdc_processor.GraphDatabase",
            None,
        ):
            with pytest.raises(ImportError, match="neo4j driver is required"):
                CDCProcessor(
                    neo4j_uri="neo4j://localhost:7687",
                    neo4j_user="neo4j",
                    neo4j_password="password",
                )


class TestCDCIntegration:
    """Test CDC integration with subscription system."""

    @pytest.mark.asyncio
    async def test_cdc_subscription_integration(self):
        """Test integration between CDC and subscription system."""
        # Mock subscription system
        mock_subscription_system = Mock()
        mock_subscription_system.publish_event = AsyncMock()

        # Mock CDC processor
        mock_cdc_processor = Mock()
        mock_cdc_processor.add_event_handler = Mock()

        # Test integration
        await integrate_cdc_with_subscriptions(
            mock_cdc_processor, mock_subscription_system
        )

        # Verify handler was registered
        mock_cdc_processor.add_event_handler.assert_called_once()

        # Get the registered handler
        handler = mock_cdc_processor.add_event_handler.call_args[0][0]

        # Create test CDC event
        cdc_event = GraphChangeEvent(
            event_id="test-123",
            change_type=ChangeType.NODE_CREATED,
            timestamp=datetime.now(),
            entity_id="node-456",
            entity_type="node",
            user_id="user-123",
            metadata={"source": "test"},
        )

        # Simulate event handling
        with patch("asyncio.create_task") as mock_create_task:
            handler(cdc_event)
            mock_create_task.assert_called_once()


@pytest.mark.asyncio
async def test_concurrent_event_processing():
    """Test concurrent event processing under load."""
    with patch(
        "brain_researcher.services.br_kg.streaming.cdc_processor.GraphDatabase"
    ) as mock_graphdb:
        mock_driver = Mock()
        mock_session = Mock()
        mock_session.run.return_value = []
        mock_driver.session.return_value.__enter__.return_value = mock_session
        mock_graphdb.driver.return_value = mock_driver

        processor = CDCProcessor(
            neo4j_uri="neo4j://localhost:7687",
            neo4j_user="neo4j",
            neo4j_password="password",
            buffer_size=100,
            batch_interval=0.01,
        )

        events_processed = []

        def capture_event(event):
            events_processed.append(event)

        processor.add_event_handler(capture_event)

        # Generate many events concurrently
        async def generate_events():
            tasks = []
            for i in range(50):
                event = GraphChangeEvent(
                    event_id=f"event-{i}",
                    change_type=ChangeType.NODE_CREATED,
                    timestamp=datetime.now(),
                    entity_id=f"node-{i}",
                    entity_type="node",
                )
                tasks.append(processor._add_event(event))

            await asyncio.gather(*tasks)

        await generate_events()

        # Should process all events without errors
        assert len(events_processed) == 50
        assert processor.stats["events_processed"] == 50
        assert processor.stats["errors"] == 0


@pytest.mark.asyncio
async def test_memory_cleanup():
    """Test memory cleanup and resource management."""
    with patch(
        "brain_researcher.services.br_kg.streaming.cdc_processor.GraphDatabase"
    ) as mock_graphdb:
        mock_driver = Mock()
        mock_session = Mock()
        mock_session.run.return_value = []
        mock_driver.session.return_value.__enter__.return_value = mock_session
        mock_graphdb.driver.return_value = mock_driver

        processor = CDCProcessor(
            neo4j_uri="neo4j://localhost:7687",
            neo4j_user="neo4j",
            neo4j_password="password",
        )

        # Start processor
        await processor.start()

        # Add some data
        for i in range(10):
            processor.node_states[f"node-{i}"] = {"labels": [], "properties": {}}
            processor.relationship_states[f"rel-{i}"] = {"properties": {}}

        # Stop processor - should clean up resources
        await processor.stop()

        assert not processor.is_running
        assert processor.driver is None

        # Should still maintain state for potential restart
        assert len(processor.node_states) == 10
        assert len(processor.relationship_states) == 10


if __name__ == "__main__":
    pytest.main([__file__])
