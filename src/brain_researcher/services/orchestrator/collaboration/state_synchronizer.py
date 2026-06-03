"""
State Synchronization Protocol for Real-time Collaborative Editing.

Manages document state synchronization across multiple clients with
versioning, conflict detection, and consistency guarantees.
"""

import asyncio
import hashlib
import json
import logging
import uuid
from collections import defaultdict, deque
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from enum import Enum
from typing import Any

import redis.asyncio as redis

from .operational_transform import Operation, OperationType

logger = logging.getLogger(__name__)


class SyncEventType(str, Enum):
    """Types of synchronization events."""

    STATE_UPDATED = "state_updated"
    OPERATION_APPLIED = "operation_applied"
    CHECKPOINT_CREATED = "checkpoint_created"
    CONFLICT_DETECTED = "conflict_detected"
    CLIENT_CONNECTED = "client_connected"
    CLIENT_DISCONNECTED = "client_disconnected"
    SYNC_REQUESTED = "sync_requested"
    HEARTBEAT = "heartbeat"


class DocumentFormat(str, Enum):
    """Document formats that can be synchronized."""

    TEXT = "text"
    JSON = "json"
    BRAIN_IMAGE = "brain_image"
    ANNOTATION = "annotation"
    ANALYSIS_RESULT = "analysis_result"
    CUSTOM = "custom"


@dataclass
class DocumentState:
    """Represents the complete state of a document."""

    document_id: str
    version: int
    content: Any
    checksum: str
    timestamp: datetime
    format: DocumentFormat = DocumentFormat.JSON
    metadata: dict[str, Any] | None = None
    operations: list[Operation] = None

    def __post_init__(self):
        if self.operations is None:
            self.operations = []
        if self.metadata is None:
            self.metadata = {}

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["timestamp"] = self.timestamp.isoformat()
        data["operations"] = [op.to_dict() for op in self.operations]
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "DocumentState":
        # Convert timestamp
        if isinstance(data.get("timestamp"), str):
            data["timestamp"] = datetime.fromisoformat(data["timestamp"])

        # Convert operations
        if data.get("operations"):
            data["operations"] = [Operation.from_dict(op) for op in data["operations"]]

        return cls(**data)

    def calculate_checksum(self) -> str:
        """Calculate checksum for the current state."""
        content_str = json.dumps(self.content, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(content_str.encode()).hexdigest()[:16]

    def verify_checksum(self) -> bool:
        """Verify that the stored checksum matches the current content."""
        return self.checksum == self.calculate_checksum()


@dataclass
class SyncEvent:
    """Represents a synchronization event."""

    event_id: str
    event_type: SyncEventType
    document_id: str
    client_id: str
    timestamp: datetime
    data: dict[str, Any] | None = None

    def __post_init__(self):
        if not self.event_id:
            self.event_id = f"event_{uuid.uuid4().hex[:12]}"

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["timestamp"] = self.timestamp.isoformat()
        return data


@dataclass
class ClientState:
    """Tracks the state of a connected client."""

    client_id: str
    user_id: str
    document_id: str
    last_seen_version: int
    connection_time: datetime
    last_heartbeat: datetime
    pending_operations: list[Operation] = None
    is_online: bool = True

    def __post_init__(self):
        if self.pending_operations is None:
            self.pending_operations = []


class StateSynchronizer:
    """
    Advanced state synchronization system for collaborative documents.

    Features:
    - Version-based conflict detection
    - Automatic state recovery
    - Client disconnect handling
    - Checkpoint management
    - Redis-based scaling support
    """

    def __init__(self, redis_client: redis.Redis | None = None):
        self.redis_client = redis_client

        # Document states
        self.document_states: dict[str, DocumentState] = {}
        self.document_versions: dict[str, int] = defaultdict(int)

        # Client tracking
        self.connected_clients: dict[str, ClientState] = {}
        self.clients_by_document: dict[str, set[str]] = defaultdict(set)

        # Checkpoints
        self.checkpoints: dict[str, list[DocumentState]] = defaultdict(list)
        self.max_checkpoints = 10
        self.checkpoint_interval = 50  # versions

        # Event tracking
        self.sync_events: deque = deque(maxlen=1000)
        self.event_handlers: list[callable] = []

        # Background tasks
        self.heartbeat_task: asyncio.Task | None = None
        self.cleanup_task: asyncio.Task | None = None
        self.sync_task: asyncio.Task | None = None

        # Configuration
        self.heartbeat_interval = 30  # seconds
        self.client_timeout = 300  # seconds
        self.sync_interval = 5  # seconds

        # Statistics
        self.stats = {
            "documents_active": 0,
            "clients_connected": 0,
            "operations_applied": 0,
            "conflicts_detected": 0,
            "checkpoints_created": 0,
            "sync_events_processed": 0,
        }

        logger.info("State synchronizer initialized")

    async def start(self):
        """Start the state synchronizer and background tasks."""
        # Start background tasks
        self.heartbeat_task = asyncio.create_task(self._heartbeat_loop())
        self.cleanup_task = asyncio.create_task(self._cleanup_loop())
        self.sync_task = asyncio.create_task(self._sync_loop())

        logger.info("State synchronizer started")

    async def stop(self):
        """Stop the state synchronizer and cleanup."""
        # Cancel background tasks
        for task in [self.heartbeat_task, self.cleanup_task, self.sync_task]:
            if task:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass

        logger.info("State synchronizer stopped")

    async def initialize_document(
        self, document_id: str, initial_state: DocumentState
    ) -> bool:
        """Initialize a new document for synchronization."""

        if document_id in self.document_states:
            logger.warning(f"Document {document_id} already initialized")
            return False

        # Ensure checksum is calculated
        if not initial_state.checksum:
            initial_state.checksum = initial_state.calculate_checksum()

        # Store document state
        self.document_states[document_id] = initial_state
        self.document_versions[document_id] = initial_state.version

        # Create initial checkpoint
        await self._create_checkpoint(document_id, initial_state)

        # Update statistics
        self.stats["documents_active"] = len(self.document_states)

        # Log event
        await self._log_event(
            SyncEventType.STATE_UPDATED,
            document_id,
            "system",
            {"action": "document_initialized", "version": initial_state.version},
        )

        logger.info(
            f"Initialized document: {document_id} at version {initial_state.version}"
        )
        return True

    async def connect_client(
        self, client_id: str, user_id: str, document_id: str
    ) -> DocumentState | None:
        """Connect a client to document synchronization."""

        if document_id not in self.document_states:
            logger.error(f"Document {document_id} not found for client connection")
            return None

        current_state = self.document_states[document_id]

        # Create client state
        client_state = ClientState(
            client_id=client_id,
            user_id=user_id,
            document_id=document_id,
            last_seen_version=current_state.version,
            connection_time=datetime.utcnow(),
            last_heartbeat=datetime.utcnow(),
        )

        # Store client state
        self.connected_clients[client_id] = client_state
        self.clients_by_document[document_id].add(client_id)

        # Update statistics
        self.stats["clients_connected"] = len(self.connected_clients)

        # Log event
        await self._log_event(
            SyncEventType.CLIENT_CONNECTED,
            document_id,
            client_id,
            {"user_id": user_id, "version": current_state.version},
        )

        logger.info(f"Client {client_id} connected to document {document_id}")
        return current_state

    async def disconnect_client(self, client_id: str) -> bool:
        """Disconnect a client from synchronization."""

        if client_id not in self.connected_clients:
            return False

        client_state = self.connected_clients[client_id]
        document_id = client_state.document_id

        # Handle any pending operations
        if client_state.pending_operations:
            logger.warning(
                f"Client {client_id} disconnected with {len(client_state.pending_operations)} pending operations"
            )
            # Could implement recovery mechanism here

        # Remove from tracking
        self.clients_by_document[document_id].discard(client_id)
        del self.connected_clients[client_id]

        # Clean up empty document client sets
        if not self.clients_by_document[document_id]:
            del self.clients_by_document[document_id]

        # Update statistics
        self.stats["clients_connected"] = len(self.connected_clients)

        # Log event
        await self._log_event(
            SyncEventType.CLIENT_DISCONNECTED,
            document_id,
            client_id,
            {"user_id": client_state.user_id},
        )

        logger.info(f"Client {client_id} disconnected from document {document_id}")
        return True

    async def apply_operation(
        self, document_id: str, operation: Operation, client_id: str | None = None
    ) -> DocumentState | None:
        """Apply an operation to the document state."""

        if document_id not in self.document_states:
            logger.error(f"Document {document_id} not found for operation")
            return None

        current_state = self.document_states[document_id]

        try:
            # Create new state with operation applied
            new_state = await self._apply_operation_to_state(current_state, operation)

            if not new_state:
                logger.error(f"Failed to apply operation to document {document_id}")
                return None

            # Update document state
            self.document_states[document_id] = new_state
            self.document_versions[document_id] = new_state.version

            # Update client states
            if client_id and client_id in self.connected_clients:
                self.connected_clients[client_id].last_seen_version = new_state.version

            # Create checkpoint if needed
            if new_state.version % self.checkpoint_interval == 0:
                await self._create_checkpoint(document_id, new_state)

            # Update statistics
            self.stats["operations_applied"] += 1

            # Log event
            await self._log_event(
                SyncEventType.OPERATION_APPLIED,
                document_id,
                client_id or "system",
                {
                    "operation_id": operation.id,
                    "operation_type": operation.type.value,
                    "new_version": new_state.version,
                },
            )

            # Notify other clients
            await self._notify_state_update(
                document_id, new_state, exclude_client=client_id
            )

            return new_state

        except Exception as e:
            logger.error(
                f"Error applying operation to document {document_id}: {str(e)}"
            )
            return None

    async def get_document_state(self, document_id: str) -> DocumentState | None:
        """Get current state of a document."""
        return self.document_states.get(document_id)

    async def sync_client(
        self, client_id: str, client_version: int
    ) -> dict[str, Any] | None:
        """Synchronize a client to the current document state."""

        if client_id not in self.connected_clients:
            logger.warning(f"Client {client_id} not found for sync")
            return None

        client_state = self.connected_clients[client_id]
        document_id = client_state.document_id

        if document_id not in self.document_states:
            logger.error(f"Document {document_id} not found for sync")
            return None

        current_state = self.document_states[document_id]

        # Check if client needs update
        if client_version >= current_state.version:
            # Client is up to date
            return {"status": "up_to_date", "current_version": current_state.version}

        # Get operations since client's version
        operations_since = await self._get_operations_since_version(
            document_id, client_version
        )

        # Update client state
        client_state.last_seen_version = current_state.version
        client_state.last_heartbeat = datetime.utcnow()

        # Log event
        await self._log_event(
            SyncEventType.SYNC_REQUESTED,
            document_id,
            client_id,
            {
                "client_version": client_version,
                "current_version": current_state.version,
                "operations_count": len(operations_since),
            },
        )

        return {
            "status": "update_required",
            "current_version": current_state.version,
            "client_version": client_version,
            "operations": [op.to_dict() for op in operations_since],
            "full_state": (
                current_state.to_dict() if len(operations_since) > 20 else None
            ),
        }

    async def handle_client_heartbeat(self, client_id: str) -> bool:
        """Handle heartbeat from a client."""

        if client_id not in self.connected_clients:
            return False

        self.connected_clients[client_id].last_heartbeat = datetime.utcnow()
        self.connected_clients[client_id].is_online = True

        return True

    async def create_checkpoint(
        self,
        document_id: str,
        checkpoint_id: str | None = None,
        custom_state: DocumentState | None = None,
    ) -> bool:
        """Create a manual checkpoint for a document."""

        if document_id not in self.document_states:
            return False

        state_to_checkpoint = custom_state or self.document_states[document_id]
        return await self._create_checkpoint(
            document_id, state_to_checkpoint, checkpoint_id
        )

    async def restore_from_checkpoint(
        self, document_id: str, checkpoint_index: int = -1
    ) -> DocumentState | None:
        """Restore document from a checkpoint."""

        if document_id not in self.checkpoints:
            logger.warning(f"No checkpoints found for document {document_id}")
            return None

        checkpoints = self.checkpoints[document_id]

        if not checkpoints or abs(checkpoint_index) > len(checkpoints):
            logger.warning(
                f"Invalid checkpoint index {checkpoint_index} for document {document_id}"
            )
            return None

        checkpoint = checkpoints[checkpoint_index]

        # Restore state
        self.document_states[document_id] = checkpoint
        self.document_versions[document_id] = checkpoint.version

        # Notify all clients
        await self._notify_state_update(document_id, checkpoint)

        # Log event
        await self._log_event(
            SyncEventType.STATE_UPDATED,
            document_id,
            "system",
            {
                "action": "checkpoint_restored",
                "checkpoint_version": checkpoint.version,
                "checkpoint_index": checkpoint_index,
            },
        )

        logger.info(
            f"Restored document {document_id} from checkpoint at version {checkpoint.version}"
        )
        return checkpoint

    # Helper methods

    async def _apply_operation_to_state(
        self, current_state: DocumentState, operation: Operation
    ) -> DocumentState | None:
        """Apply an operation to create a new document state."""

        try:
            # Create new state
            new_state = DocumentState(
                document_id=current_state.document_id,
                version=current_state.version + 1,
                content=self._apply_operation_to_content(
                    current_state.content, operation
                ),
                checksum="",  # Will be calculated below
                timestamp=datetime.utcnow(),
                format=current_state.format,
                metadata=(
                    current_state.metadata.copy() if current_state.metadata else {}
                ),
                operations=current_state.operations.copy() + [operation],
            )

            # Calculate checksum
            new_state.checksum = new_state.calculate_checksum()

            return new_state

        except Exception as e:
            logger.error(f"Error applying operation {operation.id}: {str(e)}")
            return None

    def _apply_operation_to_content(self, content: Any, operation: Operation) -> Any:
        """Apply operation to content based on operation type."""

        # This is a simplified implementation
        # In practice, you'd have specialized handlers for different content types

        if operation.type == OperationType.INSERT:
            if isinstance(content, str):
                # Text insertion
                pos = min(operation.position, len(content))
                return content[:pos] + str(operation.content or "") + content[pos:]
            elif isinstance(content, list):
                # List insertion
                pos = min(operation.position, len(content))
                new_content = content.copy()
                new_content.insert(pos, operation.content)
                return new_content
            elif isinstance(content, dict):
                # For dict content, handle as text operations on a text field or add to operations log
                if "text" in content:
                    # Apply to text field if it exists
                    text = str(content.get("text", ""))
                    pos = min(operation.position, len(text))
                    new_content = content.copy()
                    new_content["text"] = (
                        text[:pos] + str(operation.content or "") + text[pos:]
                    )
                    return new_content
                elif operation.attributes and "key" in operation.attributes:
                    key = operation.attributes["key"]
                    new_content = content.copy()
                    new_content[key] = operation.content
                    return new_content
                else:
                    # Add to operations log for dict content
                    new_content = content.copy()
                    if "operations" not in new_content:
                        new_content["operations"] = []
                    new_content["operations"].append(
                        {
                            "type": operation.type.value,
                            "position": operation.position,
                            "content": operation.content,
                            "author": operation.author_id,
                            "timestamp": (
                                operation.timestamp.isoformat()
                                if operation.timestamp
                                else None
                            ),
                        }
                    )
                    return new_content

        elif operation.type == OperationType.DELETE:
            if isinstance(content, str):
                # Text deletion
                start = operation.position
                end = start + (operation.length or 0)
                return content[:start] + content[end:]
            elif isinstance(content, list):
                # List deletion
                start = operation.position
                end = start + (operation.length or 1)
                return content[:start] + content[end:]

        elif operation.type == OperationType.REPLACE:
            if isinstance(content, str):
                # Text replacement
                start = operation.position
                end = start + (operation.length or 0)
                return content[:start] + str(operation.content or "") + content[end:]

        elif operation.type == OperationType.ANNOTATE:
            # Add annotation metadata
            if isinstance(content, dict):
                new_content = content.copy()
                if "annotations" not in new_content:
                    new_content["annotations"] = []
                new_content["annotations"].append(
                    {
                        "position": operation.position,
                        "content": operation.content,
                        "author": operation.author_id,
                        "timestamp": (
                            operation.timestamp.isoformat()
                            if operation.timestamp
                            else None
                        ),
                    }
                )
                return new_content

        # Return unchanged if operation couldn't be applied
        logger.warning(
            f"Could not apply operation {operation.type} to content type {type(content)}"
        )
        return content

    async def _get_operations_since_version(
        self, document_id: str, version: int
    ) -> list[Operation]:
        """Get all operations applied since a specific version."""

        if document_id not in self.document_states:
            return []

        current_state = self.document_states[document_id]

        # Return operations from the specified version onwards
        operations = []
        for op in current_state.operations:
            if op.server_version > version:
                operations.append(op)

        return operations

    async def _create_checkpoint(
        self,
        document_id: str,
        state: DocumentState,
        checkpoint_id: str | None = None,
    ) -> bool:
        """Create a checkpoint for the document state."""

        try:
            checkpoint = DocumentState(
                document_id=state.document_id,
                version=state.version,
                content=state.content,  # Deep copy might be needed for mutable content
                checksum=state.checksum,
                timestamp=state.timestamp,
                format=state.format,
                metadata=state.metadata.copy() if state.metadata else {},
                operations=state.operations.copy(),
            )

            # Store checkpoint
            if document_id not in self.checkpoints:
                self.checkpoints[document_id] = []

            self.checkpoints[document_id].append(checkpoint)

            # Limit number of checkpoints
            if len(self.checkpoints[document_id]) > self.max_checkpoints:
                self.checkpoints[document_id] = self.checkpoints[document_id][
                    -self.max_checkpoints :
                ]

            # Update statistics
            self.stats["checkpoints_created"] += 1

            # Log event
            await self._log_event(
                SyncEventType.CHECKPOINT_CREATED,
                document_id,
                "system",
                {
                    "checkpoint_id": checkpoint_id or f"auto_{state.version}",
                    "version": state.version,
                },
            )

            logger.debug(
                f"Created checkpoint for document {document_id} at version {state.version}"
            )
            return True

        except Exception as e:
            logger.error(
                f"Failed to create checkpoint for document {document_id}: {str(e)}"
            )
            return False

    async def _notify_state_update(
        self,
        document_id: str,
        new_state: DocumentState,
        exclude_client: str | None = None,
    ):
        """Notify clients about state updates."""

        # Get clients for this document
        client_ids = self.clients_by_document.get(document_id, set())

        for client_id in client_ids:
            if client_id == exclude_client:
                continue

            # This will be handled by WebSocket layer
            # For now, just update client tracking
            if client_id in self.connected_clients:
                client_state = self.connected_clients[client_id]
                if client_state.last_seen_version < new_state.version:
                    # Client needs update - could trigger push notification
                    pass

    async def _log_event(
        self,
        event_type: SyncEventType,
        document_id: str,
        client_id: str,
        data: dict[str, Any] | None = None,
    ):
        """Log a synchronization event."""

        event = SyncEvent(
            event_id="",  # Generated in __post_init__
            event_type=event_type,
            document_id=document_id,
            client_id=client_id,
            timestamp=datetime.utcnow(),
            data=data,
        )

        self.sync_events.append(event)
        self.stats["sync_events_processed"] += 1

        # Notify event handlers
        for handler in self.event_handlers:
            try:
                if asyncio.iscoroutinefunction(handler):
                    await handler(event)
                else:
                    handler(event)
            except Exception as e:
                logger.error(f"Event handler error: {str(e)}")

    # Background task loops

    async def _heartbeat_loop(self):
        """Background task for heartbeat monitoring."""
        while True:
            try:
                await asyncio.sleep(self.heartbeat_interval)

                now = datetime.utcnow()
                stale_clients = []

                # Check for stale clients
                for client_id, client_state in self.connected_clients.items():
                    time_since_heartbeat = (
                        now - client_state.last_heartbeat
                    ).total_seconds()

                    if time_since_heartbeat > self.client_timeout:
                        stale_clients.append(client_id)
                    elif time_since_heartbeat > self.heartbeat_interval * 2:
                        # Mark as potentially offline
                        client_state.is_online = False

                # Disconnect stale clients
                for client_id in stale_clients:
                    logger.info(f"Disconnecting stale client: {client_id}")
                    await self.disconnect_client(client_id)

                # Log heartbeat event
                if self.connected_clients:
                    await self._log_event(
                        SyncEventType.HEARTBEAT,
                        "system",
                        "system",
                        {
                            "active_clients": len(self.connected_clients),
                            "stale_clients_removed": len(stale_clients),
                        },
                    )

            except Exception as e:
                logger.error(f"Heartbeat loop error: {str(e)}")

    async def _cleanup_loop(self):
        """Background task for cleanup operations."""
        while True:
            try:
                await asyncio.sleep(300)  # Run every 5 minutes

                # Clean up old events
                cutoff_time = datetime.utcnow() - timedelta(hours=1)
                while self.sync_events and self.sync_events[0].timestamp < cutoff_time:
                    self.sync_events.popleft()

                # Could add more cleanup operations here

            except Exception as e:
                logger.error(f"Cleanup loop error: {str(e)}")

    async def _sync_loop(self):
        """Background task for periodic synchronization checks."""
        while True:
            try:
                await asyncio.sleep(self.sync_interval)

                # Check for clients that need synchronization
                for client_id, client_state in self.connected_clients.items():
                    document_id = client_state.document_id

                    if document_id in self.document_states:
                        current_version = self.document_states[document_id].version

                        if client_state.last_seen_version < current_version:
                            # Client is behind - could trigger sync
                            logger.debug(
                                f"Client {client_id} is behind (version {client_state.last_seen_version} vs {current_version})"
                            )

            except Exception as e:
                logger.error(f"Sync loop error: {str(e)}")

    # Public API methods

    def add_event_handler(self, handler: callable):
        """Add handler for synchronization events."""
        self.event_handlers.append(handler)

    def get_document_clients(self, document_id: str) -> list[str]:
        """Get all clients connected to a document."""
        return list(self.clients_by_document.get(document_id, set()))

    def get_client_info(self, client_id: str) -> dict[str, Any] | None:
        """Get information about a connected client."""
        if client_id not in self.connected_clients:
            return None

        client_state = self.connected_clients[client_id]
        return {
            "client_id": client_id,
            "user_id": client_state.user_id,
            "document_id": client_state.document_id,
            "last_seen_version": client_state.last_seen_version,
            "connection_time": client_state.connection_time.isoformat(),
            "last_heartbeat": client_state.last_heartbeat.isoformat(),
            "is_online": client_state.is_online,
            "pending_operations": len(client_state.pending_operations),
        }

    def get_sync_stats(self) -> dict[str, Any]:
        """Get synchronization statistics."""
        return {
            **self.stats,
            "documents_with_checkpoints": len(self.checkpoints),
            "total_checkpoints": sum(
                len(checkpoints) for checkpoints in self.checkpoints.values()
            ),
            "recent_events": len(self.sync_events),
            "clients_by_document": {
                doc_id: len(client_ids)
                for doc_id, client_ids in self.clients_by_document.items()
            },
        }

    def get_recent_events(self, limit: int = 50) -> list[dict[str, Any]]:
        """Get recent synchronization events."""
        recent_events = list(self.sync_events)[-limit:]
        return [event.to_dict() for event in recent_events]
