"""
Enhanced Collaboration Manager with Operational Transformation for Real-time Collaboration.

Provides sophisticated collaborative editing capabilities with conflict resolution,
document sessions, and brain annotation synchronization.
"""

import asyncio
import json
import logging
import time
import uuid
from collections import defaultdict, deque
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any, Set, Callable, Union, Tuple
from enum import Enum
from dataclasses import dataclass, asdict
import weakref

from pydantic import BaseModel
import redis.asyncio as redis

from .operational_transform import OperationalTransform, Operation, OperationType
from .conflict_resolver import ConflictResolver, ConflictResolutionStrategy
from .state_synchronizer import StateSynchronizer, DocumentState, SyncEvent

logger = logging.getLogger(__name__)


class SessionState(str, Enum):
    """Document session states."""
    INITIALIZING = "initializing"
    ACTIVE = "active"
    SYNCING = "syncing"
    PAUSED = "paused"
    CLOSED = "closed"
    ERROR = "error"


class UserRole(str, Enum):
    """User roles in collaboration."""
    OWNER = "owner"
    EDITOR = "editor"
    VIEWER = "viewer"
    ANNOTATOR = "annotator"


class PermissionLevel(str, Enum):
    """Permission levels for document operations."""
    READ = "read"
    WRITE = "write"
    ADMIN = "admin"
    ANNOTATE = "annotate"


@dataclass
class CollaborativeUser:
    """User information for collaboration sessions."""
    user_id: str
    username: str
    role: UserRole
    connection_id: str
    joined_at: datetime
    last_activity: datetime
    cursor_position: Optional[Dict[str, Any]] = None
    active_selection: Optional[Dict[str, Any]] = None
    permissions: Set[PermissionLevel] = None
    avatar_url: Optional[str] = None
    status: str = "online"  # online, away, busy, offline

    def __post_init__(self):
        if self.permissions is None:
            # Set default permissions based on role
            if self.role == UserRole.OWNER:
                self.permissions = {PermissionLevel.READ, PermissionLevel.WRITE, PermissionLevel.ADMIN, PermissionLevel.ANNOTATE}
            elif self.role == UserRole.EDITOR:
                self.permissions = {PermissionLevel.READ, PermissionLevel.WRITE, PermissionLevel.ANNOTATE}
            elif self.role == UserRole.ANNOTATOR:
                self.permissions = {PermissionLevel.READ, PermissionLevel.ANNOTATE}
            else:  # VIEWER
                self.permissions = {PermissionLevel.READ}


@dataclass
class DocumentSession:
    """Document collaboration session."""
    session_id: str
    document_id: str
    document_type: str  # text, brain_image, analysis_result, etc.
    state: SessionState
    created_at: datetime
    updated_at: datetime
    owner_id: str
    users: Dict[str, CollaborativeUser]
    operation_queue: deque
    state_version: int
    checkpoint_interval: int = 100
    max_operations: int = 1000
    auto_save_interval: int = 30  # seconds
    conflict_resolution_strategy: ConflictResolutionStrategy = ConflictResolutionStrategy.LAST_WRITE_WINS

    def __post_init__(self):
        if not hasattr(self, 'operation_queue') or not self.operation_queue:
            self.operation_queue = deque(maxlen=self.max_operations)


class CollaborationManager:
    """
    Enhanced collaboration manager with operational transformation support.

    Provides real-time collaborative editing with:
    - Operational transformation for conflict resolution
    - Document session management
    - User presence and permissions
    - Brain annotation synchronization
    - State versioning and checkpointing
    """

    def __init__(
        self,
        redis_client: Optional[redis.Redis] = None,
        checkpoint_interval: int = 100,
        session_timeout: int = 3600,  # 1 hour
        presence_timeout: int = 300,  # 5 minutes
        auto_save_interval: int = 30,  # seconds
        max_concurrent_sessions: int = 100
    ):
        self.redis_client = redis_client
        self.checkpoint_interval = checkpoint_interval
        self.session_timeout = session_timeout
        self.presence_timeout = presence_timeout
        self.auto_save_interval = auto_save_interval
        self.max_concurrent_sessions = max_concurrent_sessions

        # Core components
        self.operational_transform = OperationalTransform()
        self.conflict_resolver = ConflictResolver()
        self.state_synchronizer = StateSynchronizer(redis_client)

        # Session management
        self.active_sessions: Dict[str, DocumentSession] = {}
        self.user_sessions: Dict[str, Set[str]] = defaultdict(set)  # user_id -> session_ids
        self.document_sessions: Dict[str, str] = {}  # document_id -> session_id

        # Event handlers
        self.session_handlers: List[Callable] = []
        self.operation_handlers: List[Callable] = []
        self.conflict_handlers: List[Callable] = []
        self.presence_handlers: List[Callable] = []

        # Background tasks
        self.cleanup_task: Optional[asyncio.Task] = None
        self.autosave_task: Optional[asyncio.Task] = None
        self.presence_task: Optional[asyncio.Task] = None

        # Statistics
        self.stats = {
            "sessions_created": 0,
            "operations_processed": 0,
            "conflicts_resolved": 0,
            "users_active": 0,
            "documents_active": 0
        }

        logger.info("Collaboration manager initialized")

    async def start(self):
        """Start the collaboration manager and background tasks."""
        # Start background tasks
        self.cleanup_task = asyncio.create_task(self._cleanup_loop())
        self.autosave_task = asyncio.create_task(self._autosave_loop())
        self.presence_task = asyncio.create_task(self._presence_loop())

        # Initialize state synchronizer
        await self.state_synchronizer.start()

        logger.info("Collaboration manager started")

    async def stop(self):
        """Stop the collaboration manager and cleanup."""
        # Cancel background tasks
        for task in [self.cleanup_task, self.autosave_task, self.presence_task]:
            if task:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass

        # Close all sessions
        for session_id in list(self.active_sessions.keys()):
            await self.close_session(session_id)

        # Stop state synchronizer
        await self.state_synchronizer.stop()

        logger.info("Collaboration manager stopped")

    async def create_session(
        self,
        document_id: str,
        document_type: str,
        owner_id: str,
        initial_state: Optional[Dict[str, Any]] = None,
        conflict_strategy: ConflictResolutionStrategy = ConflictResolutionStrategy.LAST_WRITE_WINS
    ) -> str:
        """Create a new collaboration session for a document."""

        # Check if session already exists for document
        if document_id in self.document_sessions:
            existing_session_id = self.document_sessions[document_id]
            if existing_session_id in self.active_sessions:
                logger.info(f"Returning existing session for document {document_id}")
                return existing_session_id

        # Check session limit
        if len(self.active_sessions) >= self.max_concurrent_sessions:
            raise Exception("Maximum concurrent sessions reached")

        # Create new session
        session_id = f"session_{uuid.uuid4().hex[:12]}"
        now = datetime.utcnow()

        session = DocumentSession(
            session_id=session_id,
            document_id=document_id,
            document_type=document_type,
            state=SessionState.INITIALIZING,
            created_at=now,
            updated_at=now,
            owner_id=owner_id,
            users={},
            operation_queue=deque(maxlen=1000),
            state_version=0,
            conflict_resolution_strategy=conflict_strategy
        )

        # Store session
        self.active_sessions[session_id] = session
        self.document_sessions[document_id] = session_id

        # Initialize state if provided
        if initial_state:
            document_state = DocumentState(
                document_id=document_id,
                version=0,
                content=initial_state,
                checksum=self._calculate_checksum(initial_state),
                timestamp=now
            )
            await self.state_synchronizer.initialize_document(document_id, document_state)

        # Update session state
        session.state = SessionState.ACTIVE
        session.updated_at = datetime.utcnow()

        # Update statistics
        self.stats["sessions_created"] += 1
        self.stats["documents_active"] = len(self.active_sessions)

        # Notify handlers
        for handler in self.session_handlers:
            try:
                if asyncio.iscoroutinefunction(handler):
                    await handler("session_created", session)
                else:
                    handler("session_created", session)
            except Exception as e:
                logger.error(f"Session handler error: {str(e)}")

        logger.info(f"Created collaboration session: {session_id} for document: {document_id}")
        return session_id

    async def join_session(
        self,
        session_id: str,
        user_id: str,
        username: str,
        connection_id: str,
        role: UserRole = UserRole.EDITOR,
        avatar_url: Optional[str] = None
    ) -> bool:
        """Add a user to a collaboration session."""
        if session_id not in self.active_sessions:
            logger.warning(f"Session {session_id} not found")
            return False

        session = self.active_sessions[session_id]
        now = datetime.utcnow()

        # Create user info
        user = CollaborativeUser(
            user_id=user_id,
            username=username,
            role=role,
            connection_id=connection_id,
            joined_at=now,
            last_activity=now,
            avatar_url=avatar_url
        )

        # Add user to session
        session.users[user_id] = user
        self.user_sessions[user_id].add(session_id)

        # Update session
        session.updated_at = now

        # Update statistics
        self.stats["users_active"] = len(set().union(*self.user_sessions.values()))

        # Notify other users
        await self._broadcast_user_event(session_id, "user_joined", user)

        # Send current state to new user
        await self._send_initial_state(session_id, user_id)

        logger.info(f"User {username} joined session {session_id}")
        return True

    async def leave_session(
        self,
        session_id: str,
        user_id: str
    ) -> bool:
        """Remove a user from a collaboration session."""
        if session_id not in self.active_sessions:
            return False

        session = self.active_sessions[session_id]

        if user_id not in session.users:
            return False

        user = session.users[user_id]

        # Remove user from session
        del session.users[user_id]
        self.user_sessions[user_id].discard(session_id)

        # Clean up empty user sessions
        if not self.user_sessions[user_id]:
            del self.user_sessions[user_id]

        # Update session
        session.updated_at = datetime.utcnow()

        # Update statistics
        self.stats["users_active"] = len(set().union(*self.user_sessions.values())) if self.user_sessions else 0

        # Notify other users
        await self._broadcast_user_event(session_id, "user_left", user)

        # Close session if no users remain and not owner present
        if not session.users or session.owner_id not in session.users:
            asyncio.create_task(self._schedule_session_cleanup(session_id, delay=60))  # 1 minute grace period

        logger.info(f"User {user.username} left session {session_id}")
        return True

    async def process_operation(
        self,
        session_id: str,
        user_id: str,
        operation: Operation
    ) -> Tuple[bool, Optional[Operation]]:
        """
        Process a collaborative operation with operational transformation.

        Returns:
            Tuple[bool, Optional[Operation]]: (success, transformed_operation)
        """
        if session_id not in self.active_sessions:
            return False, None

        session = self.active_sessions[session_id]

        # Validate user permissions
        if not await self._check_operation_permission(session, user_id, operation):
            logger.warning(f"User {user_id} lacks permission for operation in session {session_id}")
            return False, None

        # Update user activity
        if user_id in session.users:
            session.users[user_id].last_activity = datetime.utcnow()

        try:
            # Get current document state
            current_state = await self.state_synchronizer.get_document_state(session.document_id)
            if not current_state:
                logger.error(f"No state found for document {session.document_id}")
                return False, None

            # Apply operational transformation
            transformed_op = await self._transform_operation(
                session, operation, current_state
            )

            if not transformed_op:
                logger.warning(f"Operation transformation failed for session {session_id}")
                return False, None

            # Apply operation to document state
            new_state = await self.state_synchronizer.apply_operation(
                session.document_id, transformed_op
            )

            if not new_state:
                logger.error(f"Failed to apply operation to document {session.document_id}")
                return False, None

            # Add to operation queue
            session.operation_queue.append(transformed_op)
            session.state_version += 1
            session.updated_at = datetime.utcnow()

            # Create checkpoint if needed
            if session.state_version % self.checkpoint_interval == 0:
                await self._create_checkpoint(session_id)

            # Broadcast operation to other users
            await self._broadcast_operation(session_id, transformed_op, exclude_user=user_id)

            # Update statistics
            self.stats["operations_processed"] += 1

            # Notify handlers
            for handler in self.operation_handlers:
                try:
                    if asyncio.iscoroutinefunction(handler):
                        await handler(session_id, user_id, transformed_op)
                    else:
                        handler(session_id, user_id, transformed_op)
                except Exception as e:
                    logger.error(f"Operation handler error: {str(e)}")

            return True, transformed_op

        except Exception as e:
            logger.error(f"Error processing operation in session {session_id}: {str(e)}")
            return False, None

    async def update_user_presence(
        self,
        session_id: str,
        user_id: str,
        cursor_position: Optional[Dict[str, Any]] = None,
        selection: Optional[Dict[str, Any]] = None,
        status: Optional[str] = None
    ) -> bool:
        """Update user presence information."""
        if session_id not in self.active_sessions:
            return False

        session = self.active_sessions[session_id]
        if user_id not in session.users:
            return False

        user = session.users[user_id]
        user.last_activity = datetime.utcnow()

        # Update presence info
        if cursor_position is not None:
            user.cursor_position = cursor_position
        if selection is not None:
            user.active_selection = selection
        if status is not None:
            user.status = status

        # Broadcast presence update
        presence_data = {
            "user_id": user_id,
            "username": user.username,
            "cursor_position": user.cursor_position,
            "active_selection": user.active_selection,
            "status": user.status,
            "timestamp": datetime.utcnow().isoformat()
        }

        await self._broadcast_presence_update(session_id, presence_data, exclude_user=user_id)

        # Notify handlers
        for handler in self.presence_handlers:
            try:
                if asyncio.iscoroutinefunction(handler):
                    await handler(session_id, user_id, presence_data)
                else:
                    handler(session_id, user_id, presence_data)
            except Exception as e:
                logger.error(f"Presence handler error: {str(e)}")

        return True

    async def get_session_state(self, session_id: str) -> Optional[Dict[str, Any]]:
        """Get current session state and user information."""
        if session_id not in self.active_sessions:
            return None

        session = self.active_sessions[session_id]

        # Get current document state
        document_state = await self.state_synchronizer.get_document_state(session.document_id)

        return {
            "session_id": session_id,
            "document_id": session.document_id,
            "document_type": session.document_type,
            "state": session.state.value,
            "version": session.state_version,
            "created_at": session.created_at.isoformat(),
            "updated_at": session.updated_at.isoformat(),
            "owner_id": session.owner_id,
            "users": {
                uid: {
                    "user_id": user.user_id,
                    "username": user.username,
                    "role": user.role.value,
                    "joined_at": user.joined_at.isoformat(),
                    "last_activity": user.last_activity.isoformat(),
                    "cursor_position": user.cursor_position,
                    "active_selection": user.active_selection,
                    "status": user.status,
                    "avatar_url": user.avatar_url,
                    "permissions": [p.value for p in user.permissions]
                }
                for uid, user in session.users.items()
            },
            "document_state": document_state.to_dict() if document_state else None,
            "operation_count": len(session.operation_queue),
            "conflict_resolution_strategy": session.conflict_resolution_strategy.value
        }

    async def close_session(self, session_id: str) -> bool:
        """Close a collaboration session and cleanup resources."""
        if session_id not in self.active_sessions:
            return False

        session = self.active_sessions[session_id]

        # Update session state
        session.state = SessionState.CLOSED
        session.updated_at = datetime.utcnow()

        # Create final checkpoint
        await self._create_checkpoint(session_id)

        # Notify all users
        for user_id in list(session.users.keys()):
            await self._send_session_event(session_id, user_id, "session_closed")
            # Don't call leave_session to avoid recursion
            self.user_sessions[user_id].discard(session_id)

        # Cleanup references
        del self.active_sessions[session_id]
        if session.document_id in self.document_sessions:
            del self.document_sessions[session.document_id]

        # Clean up empty user sessions
        empty_users = [uid for uid, sessions in self.user_sessions.items() if not sessions]
        for uid in empty_users:
            del self.user_sessions[uid]

        # Update statistics
        self.stats["documents_active"] = len(self.active_sessions)
        self.stats["users_active"] = len(set().union(*self.user_sessions.values())) if self.user_sessions else 0

        # Notify handlers
        for handler in self.session_handlers:
            try:
                if asyncio.iscoroutinefunction(handler):
                    await handler("session_closed", session)
                else:
                    handler("session_closed", session)
            except Exception as e:
                logger.error(f"Session handler error: {str(e)}")

        logger.info(f"Closed collaboration session: {session_id}")
        return True

    # Helper Methods

    async def _transform_operation(
        self,
        session: DocumentSession,
        operation: Operation,
        current_state: DocumentState
    ) -> Optional[Operation]:
        """Transform operation using operational transformation algorithm."""
        try:
            # Get concurrent operations that might conflict
            concurrent_ops = list(session.operation_queue)

            if not concurrent_ops:
                # No concurrent operations, return as-is
                return operation

            # Apply operational transformation
            transformed_op = await self.operational_transform.transform(
                operation, concurrent_ops, current_state
            )

            return transformed_op

        except Exception as e:
            logger.error(f"Operation transformation failed: {str(e)}")
            return None

    async def _check_operation_permission(
        self,
        session: DocumentSession,
        user_id: str,
        operation: Operation
    ) -> bool:
        """Check if user has permission to perform operation."""
        if user_id not in session.users:
            return False

        user = session.users[user_id]

        # Map operation types to required permissions
        permission_map = {
            OperationType.INSERT: PermissionLevel.WRITE,
            OperationType.DELETE: PermissionLevel.WRITE,
            OperationType.RETAIN: PermissionLevel.WRITE,
            OperationType.ANNOTATE: PermissionLevel.ANNOTATE,
            OperationType.FORMAT: PermissionLevel.WRITE
        }

        required_permission = permission_map.get(operation.type, PermissionLevel.WRITE)
        return required_permission in user.permissions

    async def _broadcast_operation(
        self,
        session_id: str,
        operation: Operation,
        exclude_user: Optional[str] = None
    ):
        """Broadcast operation to all session users except sender."""
        # This will be implemented by the WebSocket layer
        # For now, we'll store it for the WebSocket endpoints to handle
        pass

    async def _broadcast_user_event(
        self,
        session_id: str,
        event_type: str,
        user: CollaborativeUser
    ):
        """Broadcast user events to session participants."""
        # This will be implemented by the WebSocket layer
        pass

    async def _broadcast_presence_update(
        self,
        session_id: str,
        presence_data: Dict[str, Any],
        exclude_user: Optional[str] = None
    ):
        """Broadcast presence updates to session participants."""
        # This will be implemented by the WebSocket layer
        pass

    async def _send_initial_state(self, session_id: str, user_id: str):
        """Send initial document state to a newly joined user."""
        # This will be implemented by the WebSocket layer
        pass

    async def _send_session_event(
        self,
        session_id: str,
        user_id: str,
        event_type: str,
        data: Optional[Dict[str, Any]] = None
    ):
        """Send session event to specific user."""
        # This will be implemented by the WebSocket layer
        pass

    async def _create_checkpoint(self, session_id: str):
        """Create a state checkpoint for the session."""
        if session_id not in self.active_sessions:
            return

        session = self.active_sessions[session_id]

        try:
            # Get current state
            document_state = await self.state_synchronizer.get_document_state(session.document_id)
            if not document_state:
                return

            # Create checkpoint
            checkpoint_id = f"checkpoint_{session_id}_{session.state_version}"
            await self.state_synchronizer.create_checkpoint(
                session.document_id, checkpoint_id, document_state
            )

            logger.debug(f"Created checkpoint {checkpoint_id} for session {session_id}")

        except Exception as e:
            logger.error(f"Failed to create checkpoint for session {session_id}: {str(e)}")

    async def _schedule_session_cleanup(self, session_id: str, delay: int = 60):
        """Schedule session cleanup after delay."""
        await asyncio.sleep(delay)

        # Check if session still has no users
        if session_id in self.active_sessions:
            session = self.active_sessions[session_id]
            if not session.users:
                await self.close_session(session_id)

    async def _cleanup_loop(self):
        """Background task to cleanup stale sessions and users."""
        while True:
            try:
                await asyncio.sleep(60)  # Run every minute

                now = datetime.utcnow()

                # Find stale sessions
                stale_sessions = []
                for session_id, session in self.active_sessions.items():
                    # Check session timeout
                    if (now - session.updated_at).total_seconds() > self.session_timeout:
                        stale_sessions.append(session_id)
                        continue

                    # Check for inactive users
                    inactive_users = []
                    for user_id, user in session.users.items():
                        if (now - user.last_activity).total_seconds() > self.presence_timeout:
                            inactive_users.append(user_id)

                    # Remove inactive users
                    for user_id in inactive_users:
                        await self.leave_session(session_id, user_id)

                # Close stale sessions
                for session_id in stale_sessions:
                    await self.close_session(session_id)

                if stale_sessions:
                    logger.info(f"Cleaned up {len(stale_sessions)} stale sessions")

            except Exception as e:
                logger.error(f"Cleanup loop error: {str(e)}")

    async def _autosave_loop(self):
        """Background task for auto-saving session states."""
        while True:
            try:
                await asyncio.sleep(self.auto_save_interval)

                # Save states for all active sessions
                for session_id, session in self.active_sessions.items():
                    if session.state == SessionState.ACTIVE:
                        await self._create_checkpoint(session_id)

            except Exception as e:
                logger.error(f"Autosave loop error: {str(e)}")

    async def _presence_loop(self):
        """Background task to monitor user presence."""
        while True:
            try:
                await asyncio.sleep(30)  # Check every 30 seconds

                now = datetime.utcnow()

                # Update user presence status based on activity
                for session in self.active_sessions.values():
                    for user in session.users.values():
                        time_since_activity = (now - user.last_activity).total_seconds()

                        # Update status based on activity
                        if time_since_activity > 300:  # 5 minutes
                            if user.status != "away":
                                user.status = "away"
                                await self._broadcast_presence_update(
                                    session.session_id,
                                    {
                                        "user_id": user.user_id,
                                        "username": user.username,
                                        "status": user.status,
                                        "timestamp": now.isoformat()
                                    }
                                )
                        elif time_since_activity < 60:  # 1 minute
                            if user.status != "online":
                                user.status = "online"
                                await self._broadcast_presence_update(
                                    session.session_id,
                                    {
                                        "user_id": user.user_id,
                                        "username": user.username,
                                        "status": user.status,
                                        "timestamp": now.isoformat()
                                    }
                                )

            except Exception as e:
                logger.error(f"Presence loop error: {str(e)}")

    def _calculate_checksum(self, data: Any) -> str:
        """Calculate checksum for data integrity verification."""
        import hashlib
        data_str = json.dumps(data, sort_keys=True, separators=(',', ':'))
        return hashlib.sha256(data_str.encode()).hexdigest()[:16]

    # Event Handler Registration

    def add_session_handler(self, handler: Callable):
        """Add session event handler."""
        self.session_handlers.append(handler)

    def add_operation_handler(self, handler: Callable):
        """Add operation event handler."""
        self.operation_handlers.append(handler)

    def add_conflict_handler(self, handler: Callable):
        """Add conflict resolution handler."""
        self.conflict_handlers.append(handler)

    def add_presence_handler(self, handler: Callable):
        """Add presence update handler."""
        self.presence_handlers.append(handler)

    # Statistics and Monitoring

    def get_stats(self) -> Dict[str, Any]:
        """Get collaboration manager statistics."""
        active_users = len(set().union(*self.user_sessions.values())) if self.user_sessions else 0

        return {
            **self.stats,
            "active_sessions": len(self.active_sessions),
            "active_users": active_users,
            "total_operations_queued": sum(len(s.operation_queue) for s in self.active_sessions.values()),
            "session_states": {
                state.value: sum(1 for s in self.active_sessions.values() if s.state == state)
                for state in SessionState
            }
        }

    def get_session_ids(self) -> List[str]:
        """Get list of active session IDs."""
        return list(self.active_sessions.keys())

    def get_user_sessions(self, user_id: str) -> List[str]:
        """Get sessions for a specific user."""
        return list(self.user_sessions.get(user_id, set()))
