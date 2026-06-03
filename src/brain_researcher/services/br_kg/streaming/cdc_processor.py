"""Change Data Capture (CDC) processor for Neo4j - completes KG-034 streaming.

This module captures changes from Neo4j using transaction event handlers
and publishes them to the streaming infrastructure for real-time processing.
Integrates with the existing subscription system and versioning.
"""

import asyncio
import logging
import uuid
import weakref
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any

try:
    from neo4j import GraphDatabase, Transaction
    from neo4j.exceptions import Neo4jError
except ImportError:
    GraphDatabase = None
    Transaction = None
    Neo4jError = Exception

logger = logging.getLogger(__name__)


class ChangeType(Enum):
    """Types of graph changes captured by CDC."""

    NODE_CREATED = "node_created"
    NODE_UPDATED = "node_updated"
    NODE_DELETED = "node_deleted"
    RELATIONSHIP_CREATED = "relationship_created"
    RELATIONSHIP_UPDATED = "relationship_updated"
    RELATIONSHIP_DELETED = "relationship_deleted"
    PROPERTY_CHANGED = "property_changed"
    LABEL_ADDED = "label_added"
    LABEL_REMOVED = "label_removed"


@dataclass
class GraphChangeEvent:
    """Represents a change event captured from Neo4j."""

    event_id: str
    change_type: ChangeType
    timestamp: datetime
    transaction_id: str | None = None

    # Node/relationship details
    entity_id: str | None = None
    entity_type: str = "unknown"  # node, relationship
    labels: list[str] = field(default_factory=list)

    # Change details
    old_properties: dict[str, Any] = field(default_factory=dict)
    new_properties: dict[str, Any] = field(default_factory=dict)
    property_changes: dict[str, Any] = field(default_factory=dict)

    # Relationship specific
    start_node_id: str | None = None
    end_node_id: str | None = None
    relationship_type: str | None = None

    # Metadata
    user_id: str | None = None
    session_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "event_id": self.event_id,
            "change_type": self.change_type.value,
            "timestamp": self.timestamp.isoformat(),
            "transaction_id": self.transaction_id,
            "entity_id": self.entity_id,
            "entity_type": self.entity_type,
            "labels": self.labels,
            "old_properties": self.old_properties,
            "new_properties": self.new_properties,
            "property_changes": self.property_changes,
            "start_node_id": self.start_node_id,
            "end_node_id": self.end_node_id,
            "relationship_type": self.relationship_type,
            "user_id": self.user_id,
            "session_id": self.session_id,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "GraphChangeEvent":
        """Create from dictionary."""
        return cls(
            event_id=data["event_id"],
            change_type=ChangeType(data["change_type"]),
            timestamp=datetime.fromisoformat(data["timestamp"]),
            transaction_id=data.get("transaction_id"),
            entity_id=data.get("entity_id"),
            entity_type=data.get("entity_type", "unknown"),
            labels=data.get("labels", []),
            old_properties=data.get("old_properties", {}),
            new_properties=data.get("new_properties", {}),
            property_changes=data.get("property_changes", {}),
            start_node_id=data.get("start_node_id"),
            end_node_id=data.get("end_node_id"),
            relationship_type=data.get("relationship_type"),
            user_id=data.get("user_id"),
            session_id=data.get("session_id"),
            metadata=data.get("metadata", {}),
        )


class CDCError(Exception):
    """CDC-related errors."""

    pass


class CDCProcessor:
    """Processes change data capture from Neo4j for streaming analytics."""

    def __init__(
        self,
        neo4j_uri: str,
        neo4j_user: str,
        neo4j_password: str,
        database: str | None = None,
        buffer_size: int = 1000,
        batch_interval: float = 1.0,
    ):
        """Initialize CDC processor.

        Args:
            neo4j_uri: Neo4j connection URI
            neo4j_user: Neo4j username
            neo4j_password: Neo4j password
            database: Target database name
            buffer_size: Maximum events to buffer
            batch_interval: Batch processing interval in seconds
        """
        if GraphDatabase is None:
            raise ImportError("neo4j driver is required for CDC processing")

        self.neo4j_uri = neo4j_uri
        self.neo4j_user = neo4j_user
        self.neo4j_password = neo4j_password
        self.database = database
        self.buffer_size = buffer_size
        self.batch_interval = batch_interval

        self.driver = None
        self.is_running = False

        # Event processing
        self.event_buffer: list[GraphChangeEvent] = []
        self.event_handlers: list[Callable[[GraphChangeEvent], None]] = []
        self.batch_handlers: list[Callable[[list[GraphChangeEvent]], None]] = []

        # Change tracking state
        self.node_states: dict[str, dict[str, Any]] = {}
        self.relationship_states: dict[str, dict[str, Any]] = {}

        # Statistics
        self.stats = {
            "events_processed": 0,
            "events_by_type": defaultdict(int),
            "batches_processed": 0,
            "last_event_time": None,
            "errors": 0,
        }

        # Background tasks
        self.tasks: list[asyncio.Task] = []

        # Weak references for cleanup
        self.active_sessions = weakref.WeakSet()

    async def start(self):
        """Start the CDC processor."""
        if self.is_running:
            logger.warning("CDC processor is already running")
            return

        try:
            self.driver = GraphDatabase.driver(
                self.neo4j_uri, auth=(self.neo4j_user, self.neo4j_password)
            )

            # Test connection
            await self._test_connection()

            self.is_running = True

            # Start background tasks
            self.tasks.append(asyncio.create_task(self._batch_processor()))
            self.tasks.append(asyncio.create_task(self._state_monitor()))

            # Set up change tracking
            await self._initialize_change_tracking()

            logger.info("CDC processor started")

        except Exception as e:
            logger.error(f"Failed to start CDC processor: {e}", exc_info=True)
            raise CDCError(f"Failed to start CDC processor: {e}")

    async def stop(self):
        """Stop the CDC processor."""
        if not self.is_running:
            return

        self.is_running = False

        # Cancel background tasks
        for task in self.tasks:
            task.cancel()

        # Process remaining events
        if self.event_buffer:
            await self._process_batch(self.event_buffer.copy())
            self.event_buffer.clear()

        # Close driver
        if self.driver:
            self.driver.close()
            self.driver = None

        logger.info("CDC processor stopped")

    async def _test_connection(self):
        """Test Neo4j connection."""
        if not self.driver:
            raise CDCError("No Neo4j driver available")

        try:
            with self.driver.session(database=self.database) as session:
                result = session.run("RETURN 1 as test")
                record = result.single()
                if not record or record["test"] != 1:
                    raise CDCError("Invalid connection test result")
        except Neo4jError as e:
            raise CDCError(f"Neo4j connection failed: {e}")

    async def _initialize_change_tracking(self):
        """Initialize change tracking by capturing current state."""
        try:
            with self.driver.session(database=self.database) as session:
                # Capture current node states
                node_result = session.run(
                    "MATCH (n) RETURN n.id as id, labels(n) as labels, properties(n) as props"
                )

                for record in node_result:
                    node_id = record["id"]
                    if node_id:
                        self.node_states[str(node_id)] = {
                            "labels": list(record["labels"]),
                            "properties": dict(record["props"]),
                        }

                # Capture current relationship states
                rel_result = session.run(
                    """
                    MATCH (a)-[r]->(b)
                    RETURN id(r) as rel_id, a.id as start_id, b.id as end_id,
                           type(r) as rel_type, properties(r) as props
                    """
                )

                for record in rel_result:
                    rel_id = str(record["rel_id"])
                    self.relationship_states[rel_id] = {
                        "start_node_id": record["start_id"],
                        "end_node_id": record["end_id"],
                        "relationship_type": record["rel_type"],
                        "properties": dict(record["props"]),
                    }

            logger.info(
                f"Initialized CDC tracking: {len(self.node_states)} nodes, "
                f"{len(self.relationship_states)} relationships"
            )

        except Exception as e:
            logger.error(f"Failed to initialize change tracking: {e}", exc_info=True)
            raise CDCError(f"Failed to initialize change tracking: {e}")

    async def capture_changes(
        self, session_id: str | None = None, user_id: str | None = None
    ):
        """Capture changes from current graph state.

        Args:
            session_id: Optional session identifier
            user_id: Optional user identifier
        """
        if not self.is_running:
            logger.warning("CDC processor not running")
            return

        try:
            with self.driver.session(database=self.database) as session:
                await self._capture_node_changes(session, session_id, user_id)
                await self._capture_relationship_changes(session, session_id, user_id)

        except Exception as e:
            logger.error(f"Error capturing changes: {e}", exc_info=True)
            self.stats["errors"] += 1

    async def _capture_node_changes(
        self, session, session_id: str | None, user_id: str | None
    ):
        """Capture node changes."""
        current_nodes = {}

        # Get current node states
        result = session.run(
            "MATCH (n) RETURN n.id as id, labels(n) as labels, properties(n) as props"
        )

        for record in result:
            node_id = record["id"]
            if node_id:
                current_nodes[str(node_id)] = {
                    "labels": list(record["labels"]),
                    "properties": dict(record["props"]),
                }

        # Detect new nodes
        for node_id, current_state in current_nodes.items():
            if node_id not in self.node_states:
                event = GraphChangeEvent(
                    event_id=str(uuid.uuid4()),
                    change_type=ChangeType.NODE_CREATED,
                    timestamp=datetime.now(),
                    entity_id=node_id,
                    entity_type="node",
                    labels=current_state["labels"],
                    new_properties=current_state["properties"],
                    session_id=session_id,
                    user_id=user_id,
                )
                await self._add_event(event)
                self.node_states[node_id] = current_state

        # Detect updated nodes
        for node_id, current_state in current_nodes.items():
            if node_id in self.node_states:
                old_state = self.node_states[node_id]

                # Check for property changes
                old_props = old_state["properties"]
                new_props = current_state["properties"]

                if old_props != new_props:
                    property_changes = {}
                    for key, new_value in new_props.items():
                        if key not in old_props or old_props[key] != new_value:
                            property_changes[key] = {
                                "old": old_props.get(key),
                                "new": new_value,
                            }

                    for key in old_props:
                        if key not in new_props:
                            property_changes[key] = {"old": old_props[key], "new": None}

                    if property_changes:
                        event = GraphChangeEvent(
                            event_id=str(uuid.uuid4()),
                            change_type=ChangeType.NODE_UPDATED,
                            timestamp=datetime.now(),
                            entity_id=node_id,
                            entity_type="node",
                            labels=current_state["labels"],
                            old_properties=old_props,
                            new_properties=new_props,
                            property_changes=property_changes,
                            session_id=session_id,
                            user_id=user_id,
                        )
                        await self._add_event(event)
                        self.node_states[node_id] = current_state

                # Check for label changes
                old_labels = set(old_state["labels"])
                new_labels = set(current_state["labels"])

                if old_labels != new_labels:
                    added_labels = new_labels - old_labels
                    removed_labels = old_labels - new_labels

                    for label in added_labels:
                        event = GraphChangeEvent(
                            event_id=str(uuid.uuid4()),
                            change_type=ChangeType.LABEL_ADDED,
                            timestamp=datetime.now(),
                            entity_id=node_id,
                            entity_type="node",
                            labels=[label],
                            session_id=session_id,
                            user_id=user_id,
                            metadata={"added_label": label},
                        )
                        await self._add_event(event)

                    for label in removed_labels:
                        event = GraphChangeEvent(
                            event_id=str(uuid.uuid4()),
                            change_type=ChangeType.LABEL_REMOVED,
                            timestamp=datetime.now(),
                            entity_id=node_id,
                            entity_type="node",
                            labels=[label],
                            session_id=session_id,
                            user_id=user_id,
                            metadata={"removed_label": label},
                        )
                        await self._add_event(event)

                    self.node_states[node_id] = current_state

        # Detect deleted nodes
        for node_id in list(self.node_states.keys()):
            if node_id not in current_nodes:
                old_state = self.node_states[node_id]
                event = GraphChangeEvent(
                    event_id=str(uuid.uuid4()),
                    change_type=ChangeType.NODE_DELETED,
                    timestamp=datetime.now(),
                    entity_id=node_id,
                    entity_type="node",
                    labels=old_state["labels"],
                    old_properties=old_state["properties"],
                    session_id=session_id,
                    user_id=user_id,
                )
                await self._add_event(event)
                del self.node_states[node_id]

    async def _capture_relationship_changes(
        self, session, session_id: str | None, user_id: str | None
    ):
        """Capture relationship changes."""
        current_relationships = {}

        # Get current relationship states
        result = session.run(
            """
            MATCH (a)-[r]->(b)
            RETURN id(r) as rel_id, a.id as start_id, b.id as end_id,
                   type(r) as rel_type, properties(r) as props
            """
        )

        for record in result:
            rel_id = str(record["rel_id"])
            current_relationships[rel_id] = {
                "start_node_id": record["start_id"],
                "end_node_id": record["end_id"],
                "relationship_type": record["rel_type"],
                "properties": dict(record["props"]),
            }

        # Detect new relationships
        for rel_id, current_state in current_relationships.items():
            if rel_id not in self.relationship_states:
                event = GraphChangeEvent(
                    event_id=str(uuid.uuid4()),
                    change_type=ChangeType.RELATIONSHIP_CREATED,
                    timestamp=datetime.now(),
                    entity_id=rel_id,
                    entity_type="relationship",
                    start_node_id=current_state["start_node_id"],
                    end_node_id=current_state["end_node_id"],
                    relationship_type=current_state["relationship_type"],
                    new_properties=current_state["properties"],
                    session_id=session_id,
                    user_id=user_id,
                )
                await self._add_event(event)
                self.relationship_states[rel_id] = current_state

        # Detect updated relationships
        for rel_id, current_state in current_relationships.items():
            if rel_id in self.relationship_states:
                old_state = self.relationship_states[rel_id]
                old_props = old_state["properties"]
                new_props = current_state["properties"]

                if old_props != new_props:
                    property_changes = {}
                    for key, new_value in new_props.items():
                        if key not in old_props or old_props[key] != new_value:
                            property_changes[key] = {
                                "old": old_props.get(key),
                                "new": new_value,
                            }

                    for key in old_props:
                        if key not in new_props:
                            property_changes[key] = {"old": old_props[key], "new": None}

                    if property_changes:
                        event = GraphChangeEvent(
                            event_id=str(uuid.uuid4()),
                            change_type=ChangeType.RELATIONSHIP_UPDATED,
                            timestamp=datetime.now(),
                            entity_id=rel_id,
                            entity_type="relationship",
                            start_node_id=current_state["start_node_id"],
                            end_node_id=current_state["end_node_id"],
                            relationship_type=current_state["relationship_type"],
                            old_properties=old_props,
                            new_properties=new_props,
                            property_changes=property_changes,
                            session_id=session_id,
                            user_id=user_id,
                        )
                        await self._add_event(event)
                        self.relationship_states[rel_id] = current_state

        # Detect deleted relationships
        for rel_id in list(self.relationship_states.keys()):
            if rel_id not in current_relationships:
                old_state = self.relationship_states[rel_id]
                event = GraphChangeEvent(
                    event_id=str(uuid.uuid4()),
                    change_type=ChangeType.RELATIONSHIP_DELETED,
                    timestamp=datetime.now(),
                    entity_id=rel_id,
                    entity_type="relationship",
                    start_node_id=old_state["start_node_id"],
                    end_node_id=old_state["end_node_id"],
                    relationship_type=old_state["relationship_type"],
                    old_properties=old_state["properties"],
                    session_id=session_id,
                    user_id=user_id,
                )
                await self._add_event(event)
                del self.relationship_states[rel_id]

    async def _add_event(self, event: GraphChangeEvent):
        """Add event to buffer for processing."""
        self.event_buffer.append(event)
        self.stats["events_processed"] += 1
        self.stats["events_by_type"][event.change_type.value] += 1
        self.stats["last_event_time"] = event.timestamp

        # Process individual event handlers
        for handler in self.event_handlers:
            try:
                handler(event)
            except Exception as e:
                logger.error(f"Error in event handler: {e}", exc_info=True)
                self.stats["errors"] += 1

        # Check if buffer is full
        if len(self.event_buffer) >= self.buffer_size:
            await self._process_batch(self.event_buffer.copy())
            self.event_buffer.clear()

    async def _batch_processor(self):
        """Process events in batches periodically."""
        while self.is_running:
            try:
                await asyncio.sleep(self.batch_interval)

                if self.event_buffer:
                    batch = self.event_buffer.copy()
                    self.event_buffer.clear()
                    await self._process_batch(batch)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in batch processor: {e}", exc_info=True)
                self.stats["errors"] += 1

    async def _process_batch(self, events: list[GraphChangeEvent]):
        """Process a batch of events."""
        if not events:
            return

        self.stats["batches_processed"] += 1

        # Process batch handlers
        for handler in self.batch_handlers:
            try:
                handler(events)
            except Exception as e:
                logger.error(f"Error in batch handler: {e}", exc_info=True)
                self.stats["errors"] += 1

        logger.debug(f"Processed batch of {len(events)} events")

    async def _state_monitor(self):
        """Monitor and periodically capture changes."""
        while self.is_running:
            try:
                await asyncio.sleep(5.0)  # Check every 5 seconds
                await self.capture_changes()

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in state monitor: {e}", exc_info=True)
                self.stats["errors"] += 1

    def add_event_handler(self, handler: Callable[[GraphChangeEvent], None]):
        """Add an event handler for individual events.

        Args:
            handler: Function that processes individual events
        """
        self.event_handlers.append(handler)
        logger.info(f"Added event handler: {handler.__name__}")

    def add_batch_handler(self, handler: Callable[[list[GraphChangeEvent]], None]):
        """Add a batch handler for processing event batches.

        Args:
            handler: Function that processes event batches
        """
        self.batch_handlers.append(handler)
        logger.info(f"Added batch handler: {handler.__name__}")

    def remove_event_handler(self, handler: Callable[[GraphChangeEvent], None]):
        """Remove an event handler."""
        if handler in self.event_handlers:
            self.event_handlers.remove(handler)
            logger.info(f"Removed event handler: {handler.__name__}")

    def remove_batch_handler(self, handler: Callable[[list[GraphChangeEvent]], None]):
        """Remove a batch handler."""
        if handler in self.batch_handlers:
            self.batch_handlers.remove(handler)
            logger.info(f"Removed batch handler: {handler.__name__}")

    def get_stats(self) -> dict[str, Any]:
        """Get CDC processor statistics."""
        return {
            "is_running": self.is_running,
            "buffer_size": len(self.event_buffer),
            "max_buffer_size": self.buffer_size,
            "tracked_nodes": len(self.node_states),
            "tracked_relationships": len(self.relationship_states),
            "event_handlers": len(self.event_handlers),
            "batch_handlers": len(self.batch_handlers),
            **self.stats,
            "last_event_time": (
                self.stats["last_event_time"].isoformat()
                if self.stats["last_event_time"]
                else None
            ),
        }

    async def manual_trigger(
        self, session_id: str | None = None, user_id: str | None = None
    ):
        """Manually trigger change detection.

        Args:
            session_id: Optional session identifier
            user_id: Optional user identifier
        """
        await self.capture_changes(session_id=session_id, user_id=user_id)
        logger.info("Manual CDC trigger completed")

    async def reset_tracking(self):
        """Reset change tracking state."""
        self.node_states.clear()
        self.relationship_states.clear()
        self.event_buffer.clear()

        # Re-initialize
        await self._initialize_change_tracking()
        logger.info("CDC tracking state reset")


# Integration with existing subscription system
async def integrate_cdc_with_subscriptions(
    cdc_processor: CDCProcessor, subscription_system
):
    """Integrate CDC processor with the existing subscription system.

    Args:
        cdc_processor: CDC processor instance
        subscription_system: Subscription system instance
    """
    from ..subscriptions.subscription_system import Event, EventType

    def convert_cdc_to_subscription_event(cdc_event: GraphChangeEvent) -> Event:
        """Convert CDC event to subscription event."""
        # Map CDC change types to subscription event types
        type_mapping = {
            ChangeType.NODE_CREATED: EventType.NODE_CREATED,
            ChangeType.NODE_UPDATED: EventType.NODE_UPDATED,
            ChangeType.NODE_DELETED: EventType.NODE_DELETED,
            ChangeType.RELATIONSHIP_CREATED: EventType.EDGE_CREATED,
            ChangeType.RELATIONSHIP_UPDATED: EventType.EDGE_UPDATED,
            ChangeType.RELATIONSHIP_DELETED: EventType.EDGE_DELETED,
        }

        event_type = type_mapping.get(cdc_event.change_type, EventType.GRAPH_CHANGED)

        return Event(
            event_id=cdc_event.event_id,
            event_type=event_type,
            entity_type=cdc_event.entity_type,
            entity_id=cdc_event.entity_id or "",
            data=cdc_event.to_dict(),
            user_id=cdc_event.user_id,
            timestamp=cdc_event.timestamp,
            metadata=cdc_event.metadata,
        )

    def cdc_event_handler(cdc_event: GraphChangeEvent):
        """Handle CDC events and publish to subscription system."""
        subscription_event = convert_cdc_to_subscription_event(cdc_event)
        asyncio.create_task(subscription_system.publish_event(subscription_event))

    # Register handler
    cdc_processor.add_event_handler(cdc_event_handler)
    logger.info("Integrated CDC processor with subscription system")
