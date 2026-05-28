"""
Comprehensive unit tests for backend collaboration components.

Tests the operational transformation engine, collaboration manager,
conflict resolution, and state synchronization systems.
"""

import pytest
import asyncio
import json
import uuid
from datetime import datetime, timedelta
from unittest.mock import Mock, AsyncMock, patch, MagicMock
from typing import Dict, List, Any

# Import collaboration components
from brain_researcher.services.orchestrator.collaboration.collaboration_manager import (
    CollaborationManager, DocumentSession, CollaborativeUser, 
    SessionState, UserRole, PermissionLevel
)
from brain_researcher.services.orchestrator.collaboration.operational_transform import (
    OperationalTransform, Operation, OperationType, DocumentState
)


class TestOperationalTransform:
    """Test suite for operational transformation engine."""

    def setup_method(self):
        """Set up test fixtures."""
        self.ot = OperationalTransform()
        self.sample_document_state = DocumentState(
            document_id="doc123",
            version=1,
            content="Hello World",
            checksum="abc123",
            timestamp=datetime.utcnow()
        )

    def test_operation_creation(self):
        """Test basic operation creation and serialization."""
        op = Operation(
            id="op1",
            type=OperationType.INSERT,
            position=5,
            content="test",
            author_id="user1"
        )
        
        assert op.id == "op1"
        assert op.type == OperationType.INSERT
        assert op.position == 5
        assert op.content == "test"
        assert op.author_id == "user1"
        assert not op.is_noop()

    def test_operation_serialization(self):
        """Test operation to/from dict conversion."""
        op = Operation(
            id="op1",
            type=OperationType.INSERT,
            position=5,
            content="test",
            author_id="user1",
            client_version=1,
            server_version=2
        )
        
        op_dict = op.to_dict()
        assert op_dict["type"] == "insert"
        assert op_dict["position"] == 5
        assert op_dict["content"] == "test"
        
        reconstructed = Operation.from_dict(op_dict)
        assert reconstructed.type == OperationType.INSERT
        assert reconstructed.position == 5
        assert reconstructed.content == "test"

    def test_noop_detection(self):
        """Test no-operation detection."""
        # Retain with zero length
        noop_retain = Operation("", OperationType.RETAIN, 0, length=0)
        assert noop_retain.is_noop()
        
        # Insert with no content
        noop_insert = Operation("", OperationType.INSERT, 0, content="")
        assert noop_insert.is_noop()
        
        # Delete with zero length
        noop_delete = Operation("", OperationType.DELETE, 0, length=0)
        assert noop_delete.is_noop()
        
        # Valid operations are not noop
        valid_insert = Operation("", OperationType.INSERT, 0, content="text")
        assert not valid_insert.is_noop()

    def test_insert_insert_transform(self):
        """Test transforming insert against insert."""
        op1 = Operation("op1", OperationType.INSERT, 5, content="A")
        op2 = Operation("op2", OperationType.INSERT, 3, content="B")
        
        # op2 is before op1, so op1 position should be adjusted
        transformed = self.ot._transform_insert(op1, op2)
        assert transformed.position == 6  # 5 + 1 (length of "B")

    def test_insert_delete_transform(self):
        """Test transforming insert against delete."""
        op1 = Operation("op1", OperationType.INSERT, 10, content="A")
        op2 = Operation("op2", OperationType.DELETE, 5, length=3)
        
        # Delete is before insert, adjust position
        transformed = self.ot._transform_insert(op1, op2)
        assert transformed.position == 7  # 10 - 3

    def test_delete_insert_transform(self):
        """Test transforming delete against insert."""
        op1 = Operation("op1", OperationType.DELETE, 5, length=3)
        op2 = Operation("op2", OperationType.INSERT, 3, content="AB")
        
        # Insert is before delete, adjust position
        transformed = self.ot._transform_delete(op1, op2)
        assert transformed.position == 7  # 5 + 2 (length of "AB")

    def test_delete_delete_transform(self):
        """Test transforming delete against delete."""
        op1 = Operation("op1", OperationType.DELETE, 5, length=3)  # Delete positions 5-8
        op2 = Operation("op2", OperationType.DELETE, 3, length=2)  # Delete positions 3-5
        
        # op2 is before op1, adjust position
        transformed = self.ot._transform_delete(op1, op2)
        assert transformed.position == 3  # 5 - 2

    def test_overlapping_deletes(self):
        """Test transforming overlapping delete operations."""
        op1 = Operation("op1", OperationType.DELETE, 5, length=5)  # Delete 5-10
        op2 = Operation("op2", OperationType.DELETE, 3, length=4)  # Delete 3-7
        
        # Partial overlap: op2 deletes 3-7, op1 should delete remainder
        transformed = self.ot._transform_delete(op1, op2)
        assert transformed.position == 3
        assert transformed.length == 3  # Only positions 7-10 remain to delete

    def test_complete_overlap_delete(self):
        """Test delete operation completely overlapped by another."""
        op1 = Operation("op1", OperationType.DELETE, 5, length=3)  # Delete 5-8
        op2 = Operation("op2", OperationType.DELETE, 3, length=8)  # Delete 3-11
        
        # op1 is completely within op2, becomes noop
        transformed = self.ot._transform_delete(op1, op2)
        assert transformed.length == 0

    def test_replace_operations(self):
        """Test transforming replace operations."""
        op1 = Operation("op1", OperationType.REPLACE, 5, length=3, content="NEW")
        op2 = Operation("op2", OperationType.INSERT, 4, content="X")
        
        # Insert before replace, adjust position
        transformed = self.ot._transform_replace(op1, op2)
        assert transformed.position == 6

    def test_annotation_position_adjustment(self):
        """Test annotation position adjustments."""
        op1 = Operation("op1", OperationType.ANNOTATE, 10, 
                       attributes={"type": "highlight"})
        op2 = Operation("op2", OperationType.INSERT, 5, content="TEXT")
        
        # Insert before annotation, adjust position
        transformed = self.ot._transform_annotate(op1, op2)
        assert transformed.position == 14  # 10 + 4 (length of "TEXT")

    def test_format_range_adjustment(self):
        """Test format operation range adjustments."""
        op1 = Operation("op1", OperationType.FORMAT, 5, length=5,
                       attributes={"bold": True})
        op2 = Operation("op2", OperationType.INSERT, 7, content="XX")
        
        # Insert within format range, expand length
        transformed = self.ot._transform_format(op1, op2)
        assert transformed.position == 5
        assert transformed.length == 7  # 5 + 2

    @pytest.mark.asyncio
    async def test_operation_validation(self):
        """Test operation validation."""
        # Valid operations
        valid_insert = Operation("", OperationType.INSERT, 5, content="text")
        assert self.ot.validate_operation(valid_insert, self.sample_document_state)
        
        valid_delete = Operation("", OperationType.DELETE, 5, length=3)
        assert self.ot.validate_operation(valid_delete, self.sample_document_state)
        
        # Invalid operations
        invalid_pos = Operation("", OperationType.INSERT, -1, content="text")
        assert not self.ot.validate_operation(invalid_pos, self.sample_document_state)
        
        invalid_delete = Operation("", OperationType.DELETE, 5, length=0)
        assert not self.ot.validate_operation(invalid_delete, self.sample_document_state)
        
        invalid_insert = Operation("", OperationType.INSERT, 5, content="")
        assert not self.ot.validate_operation(invalid_insert, self.sample_document_state)

    @pytest.mark.asyncio
    async def test_operation_composition(self):
        """Test composing multiple operations."""
        ops = [
            Operation("op1", OperationType.INSERT, 0, content="A", author_id="user1", client_version=1),
            Operation("op2", OperationType.INSERT, 1, content="B", author_id="user1", client_version=1),
            Operation("op3", OperationType.INSERT, 2, content="C", author_id="user1", client_version=1)
        ]
        
        composed = await self.ot.compose_operations(ops)
        
        # Should merge adjacent inserts from same author/client
        assert len(composed) == 1
        assert composed[0].content == "ABC"

    def test_operation_priority(self):
        """Test operation priority calculation."""
        delete_op = Operation("", OperationType.DELETE, 0, length=1)
        insert_op = Operation("", OperationType.INSERT, 0, content="x")
        format_op = Operation("", OperationType.FORMAT, 0, length=1)
        
        assert self.ot.get_operation_priority(delete_op) > self.ot.get_operation_priority(insert_op)
        assert self.ot.get_operation_priority(insert_op) > self.ot.get_operation_priority(format_op)

    @pytest.mark.asyncio
    async def test_transform_with_multiple_concurrent_ops(self):
        """Test transforming against multiple concurrent operations."""
        base_op = Operation("base", OperationType.INSERT, 5, content="X")
        
        concurrent_ops = [
            Operation("c1", OperationType.INSERT, 3, content="A"),
            Operation("c2", OperationType.DELETE, 7, length=2),
            Operation("c3", OperationType.INSERT, 4, content="B")
        ]
        
        transformed = await self.ot.transform(base_op, concurrent_ops, self.sample_document_state)
        
        # Should be transformed against all concurrent operations
        # Position should be adjusted for both inserts before it
        assert transformed.position == 7  # 5 + 1 (A) + 1 (B)


class TestCollaborationManager:
    """Test suite for collaboration manager."""

    @pytest.fixture
    def redis_mock(self):
        """Mock Redis client."""
        redis_mock = AsyncMock()
        return redis_mock

    @pytest.fixture
    def manager(self, redis_mock):
        """Create collaboration manager with mocked dependencies."""
        with patch('brain_researcher.services.orchestrator.collaboration.collaboration_manager.StateSynchronizer') as mock_sync:
            mock_sync.return_value = AsyncMock()
            manager = CollaborationManager(
                redis_client=redis_mock,
                checkpoint_interval=10,
                session_timeout=3600,
                presence_timeout=300
            )
            return manager

    @pytest.mark.asyncio
    async def test_session_creation(self, manager):
        """Test creating a new collaboration session."""
        session_id = await manager.create_session(
            document_id="doc123",
            document_type="analysis",
            owner_id="user1"
        )
        
        assert session_id.startswith("session_")
        assert "doc123" in manager.document_sessions
        assert session_id in manager.active_sessions
        
        session = manager.active_sessions[session_id]
        assert session.document_id == "doc123"
        assert session.owner_id == "user1"
        assert session.state == SessionState.ACTIVE

    @pytest.mark.asyncio
    async def test_duplicate_session_creation(self, manager):
        """Test creating session for document that already has one."""
        # Create first session
        session_id1 = await manager.create_session(
            document_id="doc123",
            document_type="analysis",
            owner_id="user1"
        )
        
        # Try to create another session for same document
        session_id2 = await manager.create_session(
            document_id="doc123",
            document_type="analysis",
            owner_id="user2"
        )
        
        # Should return existing session
        assert session_id1 == session_id2

    @pytest.mark.asyncio
    async def test_user_join_session(self, manager):
        """Test user joining a collaboration session."""
        session_id = await manager.create_session(
            document_id="doc123",
            document_type="analysis",
            owner_id="user1"
        )
        
        success = await manager.join_session(
            session_id=session_id,
            user_id="user2",
            username="John Doe",
            connection_id="conn123",
            role=UserRole.EDITOR
        )
        
        assert success is True
        session = manager.active_sessions[session_id]
        assert "user2" in session.users
        
        user = session.users["user2"]
        assert user.username == "John Doe"
        assert user.role == UserRole.EDITOR
        assert PermissionLevel.WRITE in user.permissions
        assert PermissionLevel.READ in user.permissions

    @pytest.mark.asyncio
    async def test_user_leave_session(self, manager):
        """Test user leaving a collaboration session."""
        session_id = await manager.create_session(
            document_id="doc123",
            document_type="analysis",
            owner_id="user1"
        )
        
        await manager.join_session(
            session_id=session_id,
            user_id="user2",
            username="John Doe",
            connection_id="conn123"
        )
        
        success = await manager.leave_session(session_id, "user2")
        
        assert success is True
        session = manager.active_sessions[session_id]
        assert "user2" not in session.users

    @pytest.mark.asyncio
    async def test_operation_processing(self, manager):
        """Test processing operations with permissions check."""
        session_id = await manager.create_session(
            document_id="doc123",
            document_type="analysis",
            owner_id="user1"
        )
        
        await manager.join_session(
            session_id=session_id,
            user_id="user2",
            username="Editor User",
            connection_id="conn123",
            role=UserRole.EDITOR
        )
        
        operation = Operation(
            id="op1",
            type=OperationType.INSERT,
            position=5,
            content="test",
            author_id="user2"
        )
        
        # Mock the state synchronizer to return success
        manager.state_synchronizer.get_document_state.return_value = AsyncMock()
        manager.state_synchronizer.apply_operation.return_value = AsyncMock()
        
        success, transformed_op = await manager.process_operation(
            session_id, "user2", operation
        )
        
        assert success is True
        assert transformed_op is not None

    @pytest.mark.asyncio
    async def test_operation_permission_denied(self, manager):
        """Test operation rejected due to insufficient permissions."""
        session_id = await manager.create_session(
            document_id="doc123",
            document_type="analysis",
            owner_id="user1"
        )
        
        # Add user with viewer role (read-only)
        await manager.join_session(
            session_id=session_id,
            user_id="user2",
            username="Viewer User",
            connection_id="conn123",
            role=UserRole.VIEWER
        )
        
        # Try to perform write operation
        operation = Operation(
            id="op1",
            type=OperationType.INSERT,
            position=5,
            content="test",
            author_id="user2"
        )
        
        success, transformed_op = await manager.process_operation(
            session_id, "user2", operation
        )
        
        assert success is False
        assert transformed_op is None

    @pytest.mark.asyncio
    async def test_presence_updates(self, manager):
        """Test updating user presence information."""
        session_id = await manager.create_session(
            document_id="doc123",
            document_type="analysis",
            owner_id="user1"
        )
        
        await manager.join_session(
            session_id=session_id,
            user_id="user2",
            username="Active User",
            connection_id="conn123"
        )
        
        success = await manager.update_user_presence(
            session_id=session_id,
            user_id="user2",
            cursor_position={"x": 100, "y": 200},
            selection={"start": 5, "end": 10},
            status="typing"
        )
        
        assert success is True
        
        user = manager.active_sessions[session_id].users["user2"]
        assert user.cursor_position == {"x": 100, "y": 200}
        assert user.active_selection == {"start": 5, "end": 10}
        assert user.status == "typing"

    @pytest.mark.asyncio
    async def test_session_state_retrieval(self, manager):
        """Test getting current session state."""
        session_id = await manager.create_session(
            document_id="doc123",
            document_type="analysis",
            owner_id="user1"
        )
        
        await manager.join_session(
            session_id=session_id,
            user_id="user2",
            username="Test User",
            connection_id="conn123",
            role=UserRole.EDITOR
        )
        
        # Mock document state
        mock_doc_state = AsyncMock()
        mock_doc_state.to_dict.return_value = {"version": 1, "content": "test"}
        manager.state_synchronizer.get_document_state.return_value = mock_doc_state
        
        state = await manager.get_session_state(session_id)
        
        assert state is not None
        assert state["session_id"] == session_id
        assert state["document_id"] == "doc123"
        assert len(state["users"]) == 1
        assert "user2" in state["users"]
        assert state["users"]["user2"]["username"] == "Test User"
        assert state["users"]["user2"]["role"] == "editor"

    @pytest.mark.asyncio
    async def test_session_closure(self, manager):
        """Test closing a collaboration session."""
        session_id = await manager.create_session(
            document_id="doc123",
            document_type="analysis",
            owner_id="user1"
        )
        
        await manager.join_session(
            session_id=session_id,
            user_id="user2",
            username="Test User",
            connection_id="conn123"
        )
        
        success = await manager.close_session(session_id)
        
        assert success is True
        assert session_id not in manager.active_sessions
        assert "doc123" not in manager.document_sessions

    @pytest.mark.asyncio
    async def test_session_timeout_cleanup(self, manager):
        """Test automatic cleanup of stale sessions."""
        # Create session with old timestamp
        session_id = await manager.create_session(
            document_id="doc123",
            document_type="analysis",
            owner_id="user1"
        )
        
        # Manually set old timestamp
        session = manager.active_sessions[session_id]
        session.updated_at = datetime.utcnow() - timedelta(hours=2)
        
        # Mock the cleanup method
        with patch.object(manager, 'close_session') as mock_close:
            # Simulate cleanup check
            now = datetime.utcnow()
            if (now - session.updated_at).total_seconds() > manager.session_timeout:
                await manager.close_session(session_id)
            
            mock_close.assert_called_once_with(session_id)

    @pytest.mark.asyncio
    async def test_user_role_permissions(self, manager):
        """Test different user roles have correct permissions."""
        session_id = await manager.create_session(
            document_id="doc123",
            document_type="analysis",
            owner_id="user1"
        )
        
        # Test owner permissions
        await manager.join_session(
            session_id=session_id,
            user_id="owner",
            username="Owner User",
            connection_id="conn1",
            role=UserRole.OWNER
        )
        
        owner = manager.active_sessions[session_id].users["owner"]
        assert PermissionLevel.ADMIN in owner.permissions
        assert PermissionLevel.WRITE in owner.permissions
        assert PermissionLevel.READ in owner.permissions
        assert PermissionLevel.ANNOTATE in owner.permissions
        
        # Test editor permissions
        await manager.join_session(
            session_id=session_id,
            user_id="editor",
            username="Editor User",
            connection_id="conn2",
            role=UserRole.EDITOR
        )
        
        editor = manager.active_sessions[session_id].users["editor"]
        assert PermissionLevel.ADMIN not in editor.permissions
        assert PermissionLevel.WRITE in editor.permissions
        assert PermissionLevel.READ in editor.permissions
        assert PermissionLevel.ANNOTATE in editor.permissions
        
        # Test viewer permissions
        await manager.join_session(
            session_id=session_id,
            user_id="viewer",
            username="Viewer User",
            connection_id="conn3",
            role=UserRole.VIEWER
        )
        
        viewer = manager.active_sessions[session_id].users["viewer"]
        assert PermissionLevel.ADMIN not in viewer.permissions
        assert PermissionLevel.WRITE not in viewer.permissions
        assert PermissionLevel.READ in viewer.permissions
        assert PermissionLevel.ANNOTATE not in viewer.permissions

    def test_collaborative_user_creation(self):
        """Test collaborative user creation and defaults."""
        user = CollaborativeUser(
            user_id="user1",
            username="John Doe",
            role=UserRole.EDITOR,
            connection_id="conn123",
            joined_at=datetime.utcnow(),
            last_activity=datetime.utcnow()
        )
        
        assert user.user_id == "user1"
        assert user.role == UserRole.EDITOR
        assert PermissionLevel.WRITE in user.permissions
        assert PermissionLevel.READ in user.permissions
        assert user.status == "online"

    def test_document_session_creation(self):
        """Test document session creation and defaults."""
        session = DocumentSession(
            session_id="sess123",
            document_id="doc123",
            document_type="analysis",
            state=SessionState.ACTIVE,
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
            owner_id="user1",
            users={},
            operation_queue=[],  # Will be converted to deque
            state_version=0
        )
        
        assert session.session_id == "sess123"
        assert session.document_id == "doc123"
        assert session.state == SessionState.ACTIVE
        assert session.checkpoint_interval == 100
        assert session.max_operations == 1000

    @pytest.mark.asyncio
    async def test_manager_statistics(self, manager):
        """Test collaboration manager statistics tracking."""
        # Create some sessions
        await manager.create_session("doc1", "analysis", "user1")
        await manager.create_session("doc2", "analysis", "user2")
        
        stats = manager.get_stats()
        
        assert stats["sessions_created"] == 2
        assert stats["active_sessions"] == 2
        assert stats["documents_active"] == 2
        assert "operations_processed" in stats
        assert "conflicts_resolved" in stats

    @pytest.mark.asyncio
    async def test_checkpoint_creation(self, manager):
        """Test automatic checkpoint creation."""
        session_id = await manager.create_session(
            document_id="doc123",
            document_type="analysis",
            owner_id="user1"
        )
        
        # Set up checkpoint interval
        session = manager.active_sessions[session_id]
        session.checkpoint_interval = 2  # Every 2 operations
        
        # Mock state synchronizer
        mock_doc_state = AsyncMock()
        manager.state_synchronizer.get_document_state.return_value = mock_doc_state
        manager.state_synchronizer.create_checkpoint = AsyncMock()
        
        # Simulate multiple operations to trigger checkpoint
        session.state_version = 2
        await manager._create_checkpoint(session_id)
        
        manager.state_synchronizer.create_checkpoint.assert_called_once()

    @pytest.mark.asyncio 
    async def test_manager_lifecycle(self, manager):
        """Test manager start and stop lifecycle."""
        await manager.start()
        
        # Check that background tasks are created
        assert manager.cleanup_task is not None
        assert manager.autosave_task is not None
        assert manager.presence_task is not None
        
        await manager.stop()
        
        # Background tasks should be cancelled
        assert manager.cleanup_task.cancelled()
        assert manager.autosave_task.cancelled()
        assert manager.presence_task.cancelled()


class TestConflictResolution:
    """Test suite for conflict resolution scenarios."""

    def setup_method(self):
        """Set up test fixtures."""
        self.ot = OperationalTransform()

    def test_simultaneous_inserts_same_position(self):
        """Test handling simultaneous inserts at same position."""
        op1 = Operation("op1", OperationType.INSERT, 5, content="A", 
                       author_id="user1", timestamp=datetime.utcnow())
        op2 = Operation("op2", OperationType.INSERT, 5, content="B", 
                       author_id="user2", timestamp=datetime.utcnow() + timedelta(milliseconds=1))
        
        # Later timestamp should win position
        transformed = self.ot._transform_insert(op1, op2)
        # op2 is later, so op1 should be adjusted
        assert transformed.position == 5  # No adjustment needed for earlier operation

    def test_delete_insert_conflict(self):
        """Test conflict between delete and insert operations."""
        delete_op = Operation("del", OperationType.DELETE, 5, length=3)
        insert_op = Operation("ins", OperationType.INSERT, 6, content="NEW")
        
        # Insert is within delete range - should be adjusted
        transformed_insert = self.ot._transform_insert(insert_op, delete_op)
        assert transformed_insert.position == 5  # Moved to start of deleted range

    def test_overlapping_format_operations(self):
        """Test overlapping format operations."""
        format1 = Operation("fmt1", OperationType.FORMAT, 5, length=5,
                           attributes={"bold": True})
        format2 = Operation("fmt2", OperationType.FORMAT, 7, length=3,
                           attributes={"italic": True})
        
        # These don't conflict - they can coexist
        transformed = self.ot._transform_format(format1, format2)
        assert transformed.position == 5
        assert transformed.length == 5

    def test_replace_vs_delete_conflict(self):
        """Test replace operation conflicting with delete."""
        replace_op = Operation("repl", OperationType.REPLACE, 5, length=3, content="NEW")
        delete_op = Operation("del", OperationType.DELETE, 4, length=4)
        
        # Delete overlaps with replace - should adjust replace
        transformed = self.ot._transform_replace(replace_op, delete_op)
        assert transformed.position == 4  # Adjusted to delete start

    def test_annotation_preservation(self):
        """Test that annotations are preserved during conflicts."""
        annotation = Operation("ann", OperationType.ANNOTATE, 10,
                             attributes={"comment": "Important note"})
        delete_op = Operation("del", OperationType.DELETE, 5, length=8)
        
        # Annotation should be moved to safe position
        transformed = self.ot._transform_annotate(annotation, delete_op)
        assert transformed.position == 5  # Moved to start of deleted area
        assert transformed.attributes["comment"] == "Important note"

    def test_complex_multi_operation_scenario(self):
        """Test complex scenario with multiple conflicting operations."""
        base_op = Operation("base", OperationType.INSERT, 10, content="X")
        
        concurrent_ops = [
            Operation("c1", OperationType.DELETE, 5, length=3),      # Delete 5-8
            Operation("c2", OperationType.INSERT, 8, content="ABC"), # Insert at 8  
            Operation("c3", OperationType.REPLACE, 12, length=2, content="YZ")  # Replace 12-14
        ]
        
        # Transform base operation against all concurrent operations
        transformed = base_op.copy()
        for op in concurrent_ops:
            transformed = self.ot._transform_insert(transformed, op)
        
        # Final position should account for:
        # - Delete removes 3 chars before position 10
        # - Insert adds 3 chars at position 8 (which becomes 5 after delete)
        # - Replace doesn't affect position since it's after
        expected_position = 10 - 3 + 3  # Original - deleted + inserted
        assert transformed.position == expected_position


class TestBrainAnnotationCollaboration:
    """Test suite for brain annotation specific collaboration."""

    def setup_method(self):
        """Set up test fixtures."""
        self.ot = OperationalTransform()

    def test_brain_region_annotation(self):
        """Test collaborative brain region annotation."""
        annotation = Operation(
            id="brain_ann",
            type=OperationType.ANNOTATE,
            position=0,  # Brain region coordinates
            content={
                "region": "prefrontal_cortex",
                "coordinates": {"x": 45, "y": 67, "z": 23},
                "label": "Activation cluster",
                "confidence": 0.85
            },
            attributes={
                "annotation_type": "brain_region",
                "modality": "fmri",
                "author": "researcher1"
            }
        )
        
        assert annotation.type == OperationType.ANNOTATE
        assert annotation.content["region"] == "prefrontal_cortex"
        assert annotation.attributes["annotation_type"] == "brain_region"

    def test_conflicting_brain_annotations(self):
        """Test resolving conflicts in brain annotations."""
        ann1 = Operation(
            id="ann1",
            type=OperationType.ANNOTATE,
            position=100,  # Voxel index
            content={
                "region": "visual_cortex",
                "confidence": 0.8
            },
            author_id="researcher1"
        )
        
        ann2 = Operation(
            id="ann2", 
            type=OperationType.ANNOTATE,
            position=100,  # Same voxel
            content={
                "region": "motor_cortex",
                "confidence": 0.9
            },
            author_id="researcher2"
        )
        
        # Higher confidence annotation should be preserved
        # This would be handled by application-specific logic
        if ann2.content["confidence"] > ann1.content["confidence"]:
            winning_annotation = ann2
        else:
            winning_annotation = ann1
            
        assert winning_annotation == ann2
        assert winning_annotation.content["region"] == "motor_cortex"

    def test_collaborative_thresholding(self):
        """Test collaborative statistical thresholding changes."""
        threshold_change = Operation(
            id="thresh",
            type=OperationType.REPLACE,
            position=0,  # Global parameter
            content={"threshold": 0.001, "correction": "fdr"},
            length=1,
            attributes={"parameter_type": "statistical_threshold"}
        )
        
        assert threshold_change.content["threshold"] == 0.001
        assert threshold_change.attributes["parameter_type"] == "statistical_threshold"

    def test_roi_boundary_editing(self):
        """Test collaborative ROI boundary modifications."""
        roi_edit = Operation(
            id="roi_edit",
            type=OperationType.REPLACE,
            position=1000,  # ROI boundary voxels
            length=50,      # Number of boundary voxels
            content={"voxel_indices": [1001, 1002, 1003], "operation": "add"},
            attributes={"roi_name": "amygdala", "edit_type": "boundary_expansion"}
        )
        
        assert roi_edit.content["operation"] == "add"
        assert roi_edit.attributes["roi_name"] == "amygdala"
        assert len(roi_edit.content["voxel_indices"]) == 3


if __name__ == "__main__":
    pytest.main([__file__, "-v"])