"""
Enhanced WebSocket Endpoints for Real-time Collaboration.

Integrates all collaboration features including operational transformation,
conflict resolution, brain annotation collaboration, and state synchronization.
"""

import logging
import uuid
from datetime import datetime
from typing import Any

from fastapi import (
    APIRouter,
    HTTPException,
    Query,
    WebSocket,
    WebSocketDisconnect,
)
from pydantic import BaseModel, ValidationError

from ..websocket_manager import (
    Connection,
    MessageType,
    WebSocketMessage,
    websocket_pool,
)
from .brain_annotation_manager import (
    AnnotationType,
    BrainAnnotationManager,
    BrainCoordinate,
    CoordinateSystem,
)
from .collaboration_manager import (
    CollaborationManager,
    UserRole,
)
from .conflict_resolver import ConflictResolutionStrategy
from .operational_transform import Operation, OperationType
from .state_synchronizer import StateSynchronizer

logger = logging.getLogger(__name__)

# Initialize router
router = APIRouter(prefix="/ws/collaboration", tags=["collaboration-websockets"])

# Initialize collaboration components
collaboration_manager = CollaborationManager()
brain_annotation_manager = BrainAnnotationManager()
state_synchronizer = StateSynchronizer()


# ============================================================================
# WebSocket Message Models
# ============================================================================


class CollaborationMessageType(str):
    """Extended message types for collaboration."""

    # Session management
    JOIN_SESSION = "join_session"
    LEAVE_SESSION = "leave_session"
    SESSION_STATE = "session_state"

    # Operations
    OPERATION = "operation"
    OPERATION_ACK = "operation_ack"
    OPERATION_REJECTED = "operation_rejected"

    # Conflicts
    CONFLICT_DETECTED = "conflict_detected"
    CONFLICT_RESOLVED = "conflict_resolved"

    # Presence
    USER_JOINED = "user_joined"
    USER_LEFT = "user_left"
    CURSOR_UPDATE = "cursor_update"
    SELECTION_UPDATE = "selection_update"
    PRESENCE_UPDATE = "presence_update"

    # Brain annotations
    ANNOTATION_CREATED = "annotation_created"
    ANNOTATION_UPDATED = "annotation_updated"
    ANNOTATION_DELETED = "annotation_deleted"
    ANNOTATION_REVIEW = "annotation_review"

    # State synchronization
    SYNC_STATE = "sync_state"
    STATE_UPDATE = "state_update"
    CHECKPOINT_CREATED = "checkpoint_created"


class JoinSessionRequest(BaseModel):
    """Request to join a collaboration session."""

    document_id: str
    document_type: str = "text"
    user_role: UserRole = UserRole.EDITOR
    initial_state: dict[str, Any] | None = None
    conflict_resolution_strategy: ConflictResolutionStrategy = (
        ConflictResolutionStrategy.LAST_WRITE_WINS
    )


class OperationMessage(BaseModel):
    """Operation message for collaborative editing."""

    operation_id: str
    operation_type: OperationType
    position: int
    content: Any | None = None
    length: int | None = None
    attributes: dict[str, Any] | None = None
    client_version: int = 0


class PresenceUpdate(BaseModel):
    """User presence update message."""

    cursor_position: dict[str, Any] | None = None
    selection: dict[str, Any] | None = None
    status: str | None = None


class AnnotationRequest(BaseModel):
    """Brain annotation request."""

    annotation_type: AnnotationType
    title: str
    description: str
    coordinate: dict[str, Any] | None = None
    region: dict[str, Any] | None = None
    properties: dict[str, Any] | None = None


# ============================================================================
# Global State
# ============================================================================

# Active collaboration sessions
active_sessions: dict[str, str] = {}  # connection_id -> session_id
session_connections: dict[str, set[str]] = {}  # session_id -> connection_ids

# User information mapping
connection_users: dict[str, dict[str, Any]] = {}  # connection_id -> user_info


# ============================================================================
# WebSocket Connection Handlers
# ============================================================================


async def handle_collaboration_connection(connection: Connection):
    """Handle new collaboration connection."""
    logger.info(f"New collaboration connection: {connection.connection_id}")

    # Send welcome message with collaboration capabilities
    welcome_message = WebSocketMessage(
        type=MessageType.DATA,
        data={
            "message_type": "collaboration_welcome",
            "connection_id": connection.connection_id,
            "capabilities": [
                "operational_transform",
                "conflict_resolution",
                "brain_annotations",
                "state_synchronization",
                "real_time_presence",
            ],
            "timestamp": datetime.utcnow().isoformat(),
        },
    )
    await connection.send_message(welcome_message)


async def handle_collaboration_disconnection(connection: Connection):
    """Handle collaboration connection closure."""
    logger.info(f"Collaboration connection closed: {connection.connection_id}")

    # Clean up session if user was in one
    if connection.connection_id in active_sessions:
        session_id = active_sessions[connection.connection_id]
        await _leave_collaboration_session(connection.connection_id, session_id)

    # Clean up user info
    if connection.connection_id in connection_users:
        del connection_users[connection.connection_id]


async def handle_collaboration_message(
    connection: Connection, message: WebSocketMessage
):
    """Handle collaboration-specific WebSocket messages."""
    try:
        if not message.data:
            return

        message_type = message.data.get("message_type")

        # Route message to appropriate handler
        handlers = {
            CollaborationMessageType.JOIN_SESSION: _handle_join_session,
            CollaborationMessageType.LEAVE_SESSION: _handle_leave_session,
            CollaborationMessageType.OPERATION: _handle_operation,
            CollaborationMessageType.CURSOR_UPDATE: _handle_cursor_update,
            CollaborationMessageType.SELECTION_UPDATE: _handle_selection_update,
            CollaborationMessageType.PRESENCE_UPDATE: _handle_presence_update,
            CollaborationMessageType.ANNOTATION_CREATED: _handle_annotation_created,
            CollaborationMessageType.ANNOTATION_UPDATED: _handle_annotation_updated,
            CollaborationMessageType.ANNOTATION_DELETED: _handle_annotation_deleted,
            CollaborationMessageType.SYNC_STATE: _handle_sync_state,
        }

        handler = handlers.get(message_type)
        if handler:
            await handler(connection, message.data)
        else:
            logger.warning(f"Unknown collaboration message type: {message_type}")

    except Exception as e:
        logger.error(f"Error handling collaboration message: {str(e)}")

        error_response = WebSocketMessage(
            type=MessageType.ERROR,
            data={
                "error": f"Failed to process collaboration message: {str(e)}",
                "original_message_id": message.message_id,
            },
        )
        await connection.send_message(error_response)


# Register handlers with WebSocket pool
websocket_pool.add_connection_handler(handle_collaboration_connection)
websocket_pool.add_disconnection_handler(handle_collaboration_disconnection)
websocket_pool.add_message_handler("data", handle_collaboration_message)


# ============================================================================
# Message Handlers
# ============================================================================


async def _handle_join_session(connection: Connection, data: dict[str, Any]):
    """Handle join session request."""
    try:
        request = JoinSessionRequest(**data)

        # Get user info from connection metadata or data
        user_id = (
            data.get("user_id") or connection.user_id or f"user_{uuid.uuid4().hex[:8]}"
        )
        username = data.get("username", f"User_{user_id[:8]}")

        # Store user info
        connection_users[connection.connection_id] = {
            "user_id": user_id,
            "username": username,
            "role": request.user_role.value,
        }

        # Create or join collaboration session
        session_id = await collaboration_manager.create_session(
            document_id=request.document_id,
            document_type=request.document_type,
            owner_id=user_id,
            initial_state=request.initial_state,
            conflict_strategy=request.conflict_resolution_strategy,
        )

        # Join the session
        success = await collaboration_manager.join_session(
            session_id=session_id,
            user_id=user_id,
            username=username,
            connection_id=connection.connection_id,
            role=request.user_role,
        )

        if success:
            # Track session connection
            active_sessions[connection.connection_id] = session_id
            if session_id not in session_connections:
                session_connections[session_id] = set()
            session_connections[session_id].add(connection.connection_id)

            # Subscribe to session channel
            await websocket_pool.subscribe(
                connection.connection_id, f"collaboration:{session_id}"
            )

            # Initialize state synchronizer client
            document_state = await state_synchronizer.connect_client(
                client_id=connection.connection_id,
                user_id=user_id,
                document_id=request.document_id,
            )

            # Send success response with session state
            session_state = await collaboration_manager.get_session_state(session_id)

            response = WebSocketMessage(
                type=MessageType.DATA,
                data={
                    "message_type": CollaborationMessageType.SESSION_STATE,
                    "session_id": session_id,
                    "session_state": session_state,
                    "document_state": (
                        document_state.to_dict() if document_state else None
                    ),
                    "status": "joined",
                },
            )
            await connection.send_message(response)

            # Notify other session participants
            await _broadcast_to_session(
                session_id,
                CollaborationMessageType.USER_JOINED,
                {
                    "user_id": user_id,
                    "username": username,
                    "role": request.user_role.value,
                    "timestamp": datetime.utcnow().isoformat(),
                },
                exclude_connection=connection.connection_id,
            )

        else:
            # Send failure response
            error_response = WebSocketMessage(
                type=MessageType.ERROR,
                data={"error": "Failed to join collaboration session"},
            )
            await connection.send_message(error_response)

    except ValidationError as e:
        error_response = WebSocketMessage(
            type=MessageType.ERROR,
            data={"error": f"Invalid join session request: {str(e)}"},
        )
        await connection.send_message(error_response)

    except Exception as e:
        logger.error(f"Error joining session: {str(e)}")
        error_response = WebSocketMessage(
            type=MessageType.ERROR, data={"error": f"Failed to join session: {str(e)}"}
        )
        await connection.send_message(error_response)


async def _handle_leave_session(connection: Connection, data: dict[str, Any]):
    """Handle leave session request."""
    if connection.connection_id not in active_sessions:
        return

    session_id = active_sessions[connection.connection_id]
    await _leave_collaboration_session(connection.connection_id, session_id)


async def _handle_operation(connection: Connection, data: dict[str, Any]):
    """Handle collaborative operation."""
    try:
        if connection.connection_id not in active_sessions:
            return

        session_id = active_sessions[connection.connection_id]
        user_info = connection_users.get(connection.connection_id, {})
        user_id = user_info.get("user_id", "unknown")

        # Parse operation
        operation_data = data.get("operation", {})
        operation = Operation(
            id=operation_data.get("operation_id", ""),
            type=OperationType(operation_data["operation_type"]),
            position=operation_data["position"],
            content=operation_data.get("content"),
            length=operation_data.get("length"),
            attributes=operation_data.get("attributes"),
            author_id=user_id,
            client_version=operation_data.get("client_version", 0),
            timestamp=datetime.utcnow(),
        )

        # Process operation through collaboration manager
        success, transformed_op = await collaboration_manager.process_operation(
            session_id, user_id, operation
        )

        if success and transformed_op:
            # Send acknowledgment
            ack_response = WebSocketMessage(
                type=MessageType.DATA,
                data={
                    "message_type": CollaborationMessageType.OPERATION_ACK,
                    "operation_id": operation.id,
                    "transformed_operation": transformed_op.to_dict(),
                    "status": "applied",
                },
            )
            await connection.send_message(ack_response)

            # Broadcast operation to other session participants
            await _broadcast_to_session(
                session_id,
                CollaborationMessageType.OPERATION,
                {
                    "operation": transformed_op.to_dict(),
                    "author_id": user_id,
                    "author_name": user_info.get("username", "Unknown"),
                    "timestamp": datetime.utcnow().isoformat(),
                },
                exclude_connection=connection.connection_id,
            )
        else:
            # Send rejection
            reject_response = WebSocketMessage(
                type=MessageType.DATA,
                data={
                    "message_type": CollaborationMessageType.OPERATION_REJECTED,
                    "operation_id": operation.id,
                    "reason": "Operation could not be applied",
                },
            )
            await connection.send_message(reject_response)

    except Exception as e:
        logger.error(f"Error handling operation: {str(e)}")
        error_response = WebSocketMessage(
            type=MessageType.ERROR,
            data={"error": f"Failed to process operation: {str(e)}"},
        )
        await connection.send_message(error_response)


async def _handle_cursor_update(connection: Connection, data: dict[str, Any]):
    """Handle cursor position update."""
    if connection.connection_id not in active_sessions:
        return

    session_id = active_sessions[connection.connection_id]
    user_info = connection_users.get(connection.connection_id, {})

    # Update presence in collaboration manager
    await collaboration_manager.update_user_presence(
        session_id=session_id,
        user_id=user_info.get("user_id", "unknown"),
        cursor_position=data.get("cursor_position"),
    )


async def _handle_selection_update(connection: Connection, data: dict[str, Any]):
    """Handle text/content selection update."""
    if connection.connection_id not in active_sessions:
        return

    session_id = active_sessions[connection.connection_id]
    user_info = connection_users.get(connection.connection_id, {})

    # Update presence in collaboration manager
    await collaboration_manager.update_user_presence(
        session_id=session_id,
        user_id=user_info.get("user_id", "unknown"),
        selection=data.get("selection"),
    )


async def _handle_presence_update(connection: Connection, data: dict[str, Any]):
    """Handle general presence update."""
    if connection.connection_id not in active_sessions:
        return

    session_id = active_sessions[connection.connection_id]
    user_info = connection_users.get(connection.connection_id, {})

    # Update presence in collaboration manager
    await collaboration_manager.update_user_presence(
        session_id=session_id,
        user_id=user_info.get("user_id", "unknown"),
        cursor_position=data.get("cursor_position"),
        selection=data.get("selection"),
        status=data.get("status"),
    )


async def _handle_annotation_created(connection: Connection, data: dict[str, Any]):
    """Handle brain annotation creation."""
    try:
        if connection.connection_id not in active_sessions:
            return

        session_id = active_sessions[connection.connection_id]
        user_info = connection_users.get(connection.connection_id, {})

        # Get session document ID
        session_state = await collaboration_manager.get_session_state(session_id)
        if not session_state:
            return

        document_id = session_state["document_id"]

        # Parse annotation data
        annotation_data = data.get("annotation", {})

        # Parse coordinate if provided
        coordinate = None
        if annotation_data.get("coordinate"):
            coord_data = annotation_data["coordinate"]
            coordinate = BrainCoordinate(
                x=coord_data["x"],
                y=coord_data["y"],
                z=coord_data["z"],
                coordinate_system=CoordinateSystem(
                    coord_data.get("coordinate_system", "mni")
                ),
            )

        # Create annotation
        annotation = await brain_annotation_manager.create_annotation(
            document_id=document_id,
            annotation_type=AnnotationType(annotation_data["annotation_type"]),
            title=annotation_data["title"],
            description=annotation_data["description"],
            author_id=user_info.get("user_id", "unknown"),
            author_name=user_info.get("username", "Unknown"),
            coordinate=coordinate,
            **annotation_data.get("properties", {}),
        )

        # Send acknowledgment
        ack_response = WebSocketMessage(
            type=MessageType.DATA,
            data={
                "message_type": CollaborationMessageType.ANNOTATION_CREATED,
                "annotation": annotation.to_dict(),
                "status": "created",
            },
        )
        await connection.send_message(ack_response)

        # Broadcast to session participants
        await _broadcast_to_session(
            session_id,
            CollaborationMessageType.ANNOTATION_CREATED,
            {
                "annotation": annotation.to_dict(),
                "timestamp": datetime.utcnow().isoformat(),
            },
            exclude_connection=connection.connection_id,
        )

    except Exception as e:
        logger.error(f"Error creating annotation: {str(e)}")
        error_response = WebSocketMessage(
            type=MessageType.ERROR,
            data={"error": f"Failed to create annotation: {str(e)}"},
        )
        await connection.send_message(error_response)


async def _handle_annotation_updated(connection: Connection, data: dict[str, Any]):
    """Handle brain annotation update."""
    try:
        user_info = connection_users.get(connection.connection_id, {})

        annotation_id = data.get("annotation_id")
        updates = data.get("updates", {})

        if not annotation_id:
            return

        # Update annotation
        updated_annotation = await brain_annotation_manager.update_annotation(
            annotation_id=annotation_id,
            user_id=user_info.get("user_id", "unknown"),
            updates=updates,
        )

        if updated_annotation:
            # Send acknowledgment
            ack_response = WebSocketMessage(
                type=MessageType.DATA,
                data={
                    "message_type": CollaborationMessageType.ANNOTATION_UPDATED,
                    "annotation": updated_annotation.to_dict(),
                    "status": "updated",
                },
            )
            await connection.send_message(ack_response)

            # Broadcast to session participants if in session
            if connection.connection_id in active_sessions:
                session_id = active_sessions[connection.connection_id]
                await _broadcast_to_session(
                    session_id,
                    CollaborationMessageType.ANNOTATION_UPDATED,
                    {
                        "annotation": updated_annotation.to_dict(),
                        "updates": updates,
                        "timestamp": datetime.utcnow().isoformat(),
                    },
                    exclude_connection=connection.connection_id,
                )

    except Exception as e:
        logger.error(f"Error updating annotation: {str(e)}")
        error_response = WebSocketMessage(
            type=MessageType.ERROR,
            data={"error": f"Failed to update annotation: {str(e)}"},
        )
        await connection.send_message(error_response)


async def _handle_annotation_deleted(connection: Connection, data: dict[str, Any]):
    """Handle brain annotation deletion."""
    try:
        user_info = connection_users.get(connection.connection_id, {})

        annotation_id = data.get("annotation_id")
        if not annotation_id:
            return

        # Delete annotation
        success = await brain_annotation_manager.delete_annotation(
            annotation_id=annotation_id, user_id=user_info.get("user_id", "unknown")
        )

        if success:
            # Send acknowledgment
            ack_response = WebSocketMessage(
                type=MessageType.DATA,
                data={
                    "message_type": CollaborationMessageType.ANNOTATION_DELETED,
                    "annotation_id": annotation_id,
                    "status": "deleted",
                },
            )
            await connection.send_message(ack_response)

            # Broadcast to session participants if in session
            if connection.connection_id in active_sessions:
                session_id = active_sessions[connection.connection_id]
                await _broadcast_to_session(
                    session_id,
                    CollaborationMessageType.ANNOTATION_DELETED,
                    {
                        "annotation_id": annotation_id,
                        "timestamp": datetime.utcnow().isoformat(),
                    },
                    exclude_connection=connection.connection_id,
                )

    except Exception as e:
        logger.error(f"Error deleting annotation: {str(e)}")
        error_response = WebSocketMessage(
            type=MessageType.ERROR,
            data={"error": f"Failed to delete annotation: {str(e)}"},
        )
        await connection.send_message(error_response)


async def _handle_sync_state(connection: Connection, data: dict[str, Any]):
    """Handle state synchronization request."""
    try:
        client_version = data.get("client_version", 0)

        # Synchronize client state
        sync_result = await state_synchronizer.sync_client(
            client_id=connection.connection_id, client_version=client_version
        )

        if sync_result:
            response = WebSocketMessage(
                type=MessageType.DATA,
                data={
                    "message_type": CollaborationMessageType.STATE_UPDATE,
                    "sync_result": sync_result,
                    "timestamp": datetime.utcnow().isoformat(),
                },
            )
            await connection.send_message(response)

    except Exception as e:
        logger.error(f"Error syncing state: {str(e)}")
        error_response = WebSocketMessage(
            type=MessageType.ERROR, data={"error": f"Failed to sync state: {str(e)}"}
        )
        await connection.send_message(error_response)


# ============================================================================
# Helper Functions
# ============================================================================


async def _leave_collaboration_session(connection_id: str, session_id: str):
    """Leave a collaboration session and cleanup."""
    if connection_id not in connection_users:
        return

    user_info = connection_users[connection_id]
    user_id = user_info.get("user_id")

    # Leave session in collaboration manager
    await collaboration_manager.leave_session(session_id, user_id)

    # Disconnect from state synchronizer
    await state_synchronizer.disconnect_client(connection_id)

    # Unsubscribe from session channel
    await websocket_pool.unsubscribe(connection_id, f"collaboration:{session_id}")

    # Clean up tracking
    if connection_id in active_sessions:
        del active_sessions[connection_id]

    if session_id in session_connections:
        session_connections[session_id].discard(connection_id)
        if not session_connections[session_id]:
            del session_connections[session_id]

    # Notify other session participants
    await _broadcast_to_session(
        session_id,
        CollaborationMessageType.USER_LEFT,
        {
            "user_id": user_id,
            "username": user_info.get("username", "Unknown"),
            "timestamp": datetime.utcnow().isoformat(),
        },
    )


async def _broadcast_to_session(
    session_id: str,
    message_type: str,
    data: dict[str, Any],
    exclude_connection: str | None = None,
):
    """Broadcast message to all participants in a collaboration session."""

    if session_id not in session_connections:
        return

    message = WebSocketMessage(
        type=MessageType.DATA, data={"message_type": message_type, **data}
    )

    # Broadcast through WebSocket pool
    exclude_set = {exclude_connection} if exclude_connection else set()
    await websocket_pool.broadcast_to_channel(
        f"collaboration:{session_id}", message, exclude_connections=exclude_set
    )


# ============================================================================
# WebSocket Endpoints
# ============================================================================


@router.websocket("/session")
async def websocket_collaboration_session(
    websocket: WebSocket,
    user_id: str | None = Query(None),
    username: str | None = Query(None),
):
    """WebSocket endpoint for collaborative sessions."""
    try:
        # Add connection to pool
        connection_id = await websocket_pool.add_connection(
            websocket,
            user_id=user_id,
            metadata={"endpoint": "collaboration_session", "username": username},
        )

        # Handle incoming messages
        try:
            while True:
                data = await websocket.receive_text()
                await websocket_pool.handle_message(connection_id, data)

        except WebSocketDisconnect:
            logger.info(f"Collaboration WebSocket disconnected: {connection_id}")

        except Exception as e:
            logger.error(f"Error in collaboration WebSocket: {str(e)}")

    except Exception as e:
        logger.error(f"Failed to establish collaboration WebSocket: {str(e)}")
        await websocket.close(code=1011, reason=f"Setup failed: {str(e)}")


# ============================================================================
# HTTP Endpoints for Management
# ============================================================================


@router.get("/sessions")
async def list_collaboration_sessions():
    """List all active collaboration sessions."""
    sessions = collaboration_manager.get_session_ids()

    session_info = []
    for session_id in sessions:
        state = await collaboration_manager.get_session_state(session_id)
        if state:
            session_info.append(
                {
                    "session_id": session_id,
                    "document_id": state["document_id"],
                    "user_count": len(state["users"]),
                    "state": state["state"],
                    "created_at": state["created_at"],
                    "updated_at": state["updated_at"],
                }
            )

    return {"sessions": session_info}


@router.get("/sessions/{session_id}")
async def get_collaboration_session(session_id: str):
    """Get detailed information about a collaboration session."""
    state = await collaboration_manager.get_session_state(session_id)
    if not state:
        raise HTTPException(status_code=404, detail="Session not found")

    return {"session": state}


@router.delete("/sessions/{session_id}")
async def close_collaboration_session(session_id: str):
    """Close a collaboration session."""
    success = await collaboration_manager.close_session(session_id)
    if not success:
        raise HTTPException(status_code=404, detail="Session not found")

    return {"status": "closed", "session_id": session_id}


@router.get("/annotations/{document_id}")
async def get_document_annotations(document_id: str):
    """Get all annotations for a document."""
    annotations = await brain_annotation_manager.get_document_annotations(document_id)
    return {
        "document_id": document_id,
        "count": len(annotations),
        "annotations": [ann.to_dict() for ann in annotations],
    }


@router.get("/stats")
async def get_collaboration_stats():
    """Get collaboration system statistics."""
    collab_stats = collaboration_manager.get_stats()
    annotation_stats = brain_annotation_manager.get_annotation_stats()
    sync_stats = state_synchronizer.get_sync_stats()

    return {
        "collaboration": collab_stats,
        "annotations": annotation_stats,
        "synchronization": sync_stats,
        "active_websocket_connections": len(session_connections),
        "total_active_sessions": len(active_sessions),
    }


# ============================================================================
# Initialization
# ============================================================================


async def initialize_collaboration_infrastructure():
    """Initialize collaboration infrastructure."""
    await collaboration_manager.start()
    await state_synchronizer.start()

    logger.info("Collaboration infrastructure initialized")


async def shutdown_collaboration_infrastructure():
    """Shutdown collaboration infrastructure."""
    await collaboration_manager.stop()
    await state_synchronizer.stop()

    logger.info("Collaboration infrastructure shutdown")


# Initialize on module load
logger.info("Enhanced collaboration WebSocket endpoints loaded")
