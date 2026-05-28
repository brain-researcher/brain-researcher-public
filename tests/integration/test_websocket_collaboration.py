"""
Integration tests for WebSocket-based real-time collaboration.

Tests WebSocket connections, real-time message broadcasting,
operation synchronization, and multi-user scenarios.
"""

import pytest
import asyncio
import json
import websockets
import uuid
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional
from unittest.mock import AsyncMock, patch, MagicMock
from contextlib import asynccontextmanager

# Test WebSocket server setup
from fastapi import FastAPI
from fastapi.websockets import WebSocket, WebSocketDisconnect
import uvicorn
from threading import Thread
import time


class MockWebSocketManager:
    """Mock WebSocket connection manager for testing."""
    
    def __init__(self):
        self.connections: Dict[str, List[WebSocket]] = {}
        self.user_info: Dict[str, Dict] = {}
        self.document_users: Dict[str, set] = {}
        self.message_history: List[Dict] = []
    
    async def connect(self, websocket: WebSocket, document_id: str, user_id: str, user_name: str):
        """Connect user to document session."""
        await websocket.accept()
        
        if document_id not in self.connections:
            self.connections[document_id] = []
        
        self.connections[document_id].append(websocket)
        self.user_info[user_id] = {
            'id': user_id,
            'name': user_name,
            'websocket': websocket,
            'document_id': document_id,
            'status': 'online',
            'connected_at': datetime.now()
        }
        
        if document_id not in self.document_users:
            self.document_users[document_id] = set()
        self.document_users[document_id].add(user_id)
    
    def disconnect(self, websocket: WebSocket, document_id: str, user_id: str):
        """Disconnect user from document session."""
        if document_id in self.connections:
            try:
                self.connections[document_id].remove(websocket)
            except ValueError:
                pass
        
        if user_id in self.user_info:
            del self.user_info[user_id]
        
        if document_id in self.document_users:
            self.document_users[document_id].discard(user_id)
    
    async def broadcast_to_document(self, document_id: str, message: dict, exclude_user: Optional[str] = None):
        """Broadcast message to all users in document."""
        self.message_history.append({
            'document_id': document_id,
            'message': message,
            'exclude_user': exclude_user,
            'timestamp': datetime.now()
        })
        
        if document_id not in self.connections:
            return
        
        for websocket in self.connections[document_id]:
            try:
                user_id = self._get_user_id_by_websocket(websocket, document_id)
                if user_id != exclude_user:
                    await websocket.send_json(message)
            except Exception as e:
                print(f"Error broadcasting to websocket: {e}")
    
    def _get_user_id_by_websocket(self, websocket: WebSocket, document_id: str) -> Optional[str]:
        """Get user ID by WebSocket connection."""
        for user_id, info in self.user_info.items():
            if info['websocket'] == websocket and info['document_id'] == document_id:
                return user_id
        return None
    
    def get_document_users(self, document_id: str) -> List[Dict]:
        """Get all users connected to document."""
        users = []
        if document_id in self.document_users:
            for user_id in self.document_users[document_id]:
                if user_id in self.user_info:
                    info = self.user_info[user_id].copy()
                    info.pop('websocket', None)
                    users.append(info)
        return users


class TestWebSocketServer:
    """Test WebSocket server for integration tests."""
    __test__ = False

    def __init__(self):
        self.app = FastAPI()
        self.manager = MockWebSocketManager()
        self.setup_routes()
        self.server_task = None
    
    def setup_routes(self):
        """Setup WebSocket routes."""
        
        @self.app.websocket("/ws/collaboration/{document_id}")
        async def websocket_endpoint(websocket: WebSocket, document_id: str):
            # Generate test user ID
            user_id = f"user_{uuid.uuid4().hex[:8]}"
            user_name = f"User {user_id[-4:]}"
            
            await self.manager.connect(websocket, document_id, user_id, user_name)
            
            try:
                # Send initial user list
                await websocket.send_json({
                    'type': 'users',
                    'users': self.manager.get_document_users(document_id)
                })
                
                # Notify others of new user
                await self.manager.broadcast_to_document(
                    document_id,
                    {
                        'type': 'user_joined',
                        'userId': user_id,
                        'userName': user_name,
                        'timestamp': datetime.now().isoformat()
                    },
                    exclude_user=user_id
                )
                
                while True:
                    data = await websocket.receive_json()
                    await self._handle_message(websocket, document_id, user_id, user_name, data)
                    
            except WebSocketDisconnect:
                self.manager.disconnect(websocket, document_id, user_id)
                
                # Notify others of user leaving
                await self.manager.broadcast_to_document(
                    document_id,
                    {
                        'type': 'user_left',
                        'userId': user_id,
                        'userName': user_name,
                        'timestamp': datetime.now().isoformat()
                    }
                )
    
    async def _handle_message(self, websocket: WebSocket, document_id: str, user_id: str, user_name: str, data: dict):
        """Handle incoming WebSocket messages."""
        message_type = data.get('type')
        
        if message_type == 'ping':
            await websocket.send_json({'type': 'pong'})
        
        elif message_type == 'cursor':
            await self.manager.broadcast_to_document(
                document_id,
                {
                    'type': 'cursor',
                    'userId': user_id,
                    'userName': user_name,
                    'x': data.get('x', 0),
                    'y': data.get('y', 0),
                    'timestamp': data.get('timestamp', datetime.now().isoformat())
                },
                exclude_user=user_id
            )
        
        elif message_type == 'operation':
            await self.manager.broadcast_to_document(
                document_id,
                {
                    'type': 'operation',
                    'userId': user_id,
                    'userName': user_name,
                    'operation': data.get('operation', {}),
                    'timestamp': datetime.now().isoformat()
                },
                exclude_user=user_id
            )
        
        elif message_type == 'selection':
            await self.manager.broadcast_to_document(
                document_id,
                {
                    'type': 'selection',
                    'userId': user_id,
                    'userName': user_name,
                    'selection': data.get('selection', {}),
                    'timestamp': datetime.now().isoformat()
                },
                exclude_user=user_id
            )
        
        elif message_type == 'comment':
            await self.manager.broadcast_to_document(
                document_id,
                {
                    'type': 'comment',
                    'userId': user_id,
                    'userName': user_name,
                    'comment': data.get('comment', {}),
                    'timestamp': datetime.now().isoformat()
                },
                exclude_user=user_id
            )
        
        elif message_type == 'typing_start':
            await self.manager.broadcast_to_document(
                document_id,
                {
                    'type': 'typing_start',
                    'userId': user_id,
                    'userName': user_name,
                    'timestamp': datetime.now().isoformat()
                },
                exclude_user=user_id
            )
        
        elif message_type == 'typing_stop':
            await self.manager.broadcast_to_document(
                document_id,
                {
                    'type': 'typing_stop',
                    'userId': user_id,
                    'userName': user_name,
                    'timestamp': datetime.now().isoformat()
                },
                exclude_user=user_id
            )


class TestWebSocketCollaboration:
    """Integration tests for WebSocket collaboration."""
    
    @pytest.fixture(scope="class")
    async def test_server(self):
        """Start test WebSocket server."""
        server = TestWebSocketServer()
        config = uvicorn.Config(server.app, host="127.0.0.1", port=8765, log_level="error")
        server_instance = uvicorn.Server(config)
        
        # Start server in background
        server_task = asyncio.create_task(server_instance.serve())
        
        # Wait for server to start
        await asyncio.sleep(0.5)
        
        yield server
        
        # Cleanup
        server_instance.should_exit = True
        server_task.cancel()
        try:
            await server_task
        except asyncio.CancelledError:
            pass

    @pytest.fixture
    async def websocket_client(self):
        """Create WebSocket client connection."""
        clients = []
        
        async def create_client(document_id: str):
            uri = f"ws://127.0.0.1:8765/ws/collaboration/{document_id}"
            websocket = await websockets.connect(uri)
            clients.append(websocket)
            return websocket
        
        yield create_client
        
        # Cleanup connections
        for client in clients:
            await client.close()

    @pytest.mark.asyncio
    async def test_websocket_connection(self, test_server, websocket_client):
        """Test basic WebSocket connection and handshake."""
        document_id = "test_doc_123"
        websocket = await websocket_client(document_id)
        
        # Should receive initial users message
        message = await websocket.recv()
        data = json.loads(message)
        
        assert data['type'] == 'users'
        assert 'users' in data
        assert len(data['users']) == 1  # The connected user

    @pytest.mark.asyncio
    async def test_multi_user_connection(self, test_server, websocket_client):
        """Test multiple users connecting to same document."""
        document_id = "multi_user_doc"
        
        # Connect first user
        ws1 = await websocket_client(document_id)
        initial_msg = await ws1.recv()
        initial_data = json.loads(initial_msg)
        assert initial_data['type'] == 'users'
        assert len(initial_data['users']) == 1
        
        # Connect second user
        ws2 = await websocket_client(document_id)
        
        # First user should receive user_joined notification
        join_msg = await ws1.recv()
        join_data = json.loads(join_msg)
        assert join_data['type'] == 'user_joined'
        assert 'userId' in join_data
        assert 'userName' in join_data
        
        # Second user should receive users list
        users_msg = await ws2.recv()
        users_data = json.loads(users_msg)
        assert users_data['type'] == 'users'
        assert len(users_data['users']) == 2

    @pytest.mark.asyncio
    async def test_user_disconnection(self, test_server, websocket_client):
        """Test user disconnection notification."""
        document_id = "disconnect_test"
        
        # Connect two users
        ws1 = await websocket_client(document_id)
        await ws1.recv()  # Initial users message
        
        ws2 = await websocket_client(document_id)
        await ws1.recv()  # User joined notification
        await ws2.recv()  # Initial users message for ws2
        
        # Disconnect second user
        await ws2.close()
        
        # First user should receive user_left notification
        leave_msg = await ws1.recv()
        leave_data = json.loads(leave_msg)
        assert leave_data['type'] == 'user_left'
        assert 'userId' in leave_data

    @pytest.mark.asyncio
    async def test_ping_pong(self, test_server, websocket_client):
        """Test ping-pong keepalive mechanism."""
        document_id = "ping_test"
        websocket = await websocket_client(document_id)
        await websocket.recv()  # Initial users message
        
        # Send ping
        await websocket.send(json.dumps({'type': 'ping'}))
        
        # Should receive pong
        response = await websocket.recv()
        data = json.loads(response)
        assert data['type'] == 'pong'

    @pytest.mark.asyncio
    async def test_cursor_tracking(self, test_server, websocket_client):
        """Test real-time cursor position tracking."""
        document_id = "cursor_test"
        
        # Connect two users
        ws1 = await websocket_client(document_id)
        await ws1.recv()  # Initial users
        
        ws2 = await websocket_client(document_id)
        await ws1.recv()  # User joined
        await ws2.recv()  # Initial users
        
        # User 1 sends cursor position
        cursor_data = {
            'type': 'cursor',
            'x': 100,
            'y': 200,
            'timestamp': datetime.now().isoformat()
        }
        await ws1.send(json.dumps(cursor_data))
        
        # User 2 should receive cursor update
        cursor_msg = await ws2.recv()
        cursor_response = json.loads(cursor_msg)
        
        assert cursor_response['type'] == 'cursor'
        assert cursor_response['x'] == 100
        assert cursor_response['y'] == 200
        assert 'userId' in cursor_response
        assert 'userName' in cursor_response

    @pytest.mark.asyncio
    async def test_operation_broadcasting(self, test_server, websocket_client):
        """Test broadcasting of collaborative operations."""
        document_id = "operation_test"
        
        # Connect two users
        ws1 = await websocket_client(document_id)
        await ws1.recv()
        
        ws2 = await websocket_client(document_id)
        await ws1.recv()
        await ws2.recv()
        
        # User 1 sends operation
        operation = {
            'type': 'operation',
            'operation': {
                'type': 'insert',
                'position': 5,
                'content': 'Hello',
                'id': 'op_123'
            }
        }
        await ws1.send(json.dumps(operation))
        
        # User 2 should receive operation
        op_msg = await ws2.recv()
        op_data = json.loads(op_msg)
        
        assert op_data['type'] == 'operation'
        assert op_data['operation']['type'] == 'insert'
        assert op_data['operation']['content'] == 'Hello'
        assert 'userId' in op_data

    @pytest.mark.asyncio
    async def test_selection_sharing(self, test_server, websocket_client):
        """Test sharing text selections between users."""
        document_id = "selection_test"
        
        ws1 = await websocket_client(document_id)
        await ws1.recv()
        
        ws2 = await websocket_client(document_id)
        await ws1.recv()
        await ws2.recv()
        
        # User 1 makes selection
        selection = {
            'type': 'selection',
            'selection': {
                'start': 10,
                'end': 20,
                'text': 'selected text'
            }
        }
        await ws1.send(json.dumps(selection))
        
        # User 2 should see selection
        sel_msg = await ws2.recv()
        sel_data = json.loads(sel_msg)
        
        assert sel_data['type'] == 'selection'
        assert sel_data['selection']['start'] == 10
        assert sel_data['selection']['end'] == 20

    @pytest.mark.asyncio
    async def test_comment_broadcasting(self, test_server, websocket_client):
        """Test real-time comment broadcasting."""
        document_id = "comment_test"
        
        ws1 = await websocket_client(document_id)
        await ws1.recv()
        
        ws2 = await websocket_client(document_id)
        await ws1.recv()
        await ws2.recv()
        
        # User 1 adds comment
        comment = {
            'type': 'comment',
            'comment': {
                'id': 'comment_123',
                'content': 'Great analysis!',
                'position': {'x': 100, 'y': 200}
            }
        }
        await ws1.send(json.dumps(comment))
        
        # User 2 should receive comment
        comment_msg = await ws2.recv()
        comment_data = json.loads(comment_msg)
        
        assert comment_data['type'] == 'comment'
        assert comment_data['comment']['content'] == 'Great analysis!'
        assert 'userId' in comment_data

    @pytest.mark.asyncio
    async def test_typing_indicators(self, test_server, websocket_client):
        """Test typing indicator functionality."""
        document_id = "typing_test"
        
        ws1 = await websocket_client(document_id)
        await ws1.recv()
        
        ws2 = await websocket_client(document_id)
        await ws1.recv()
        await ws2.recv()
        
        # User 1 starts typing
        await ws1.send(json.dumps({'type': 'typing_start'}))
        
        # User 2 should receive typing start
        typing_msg = await ws2.recv()
        typing_data = json.loads(typing_msg)
        assert typing_data['type'] == 'typing_start'
        
        # User 1 stops typing
        await ws1.send(json.dumps({'type': 'typing_stop'}))
        
        # User 2 should receive typing stop
        stop_msg = await ws2.recv()
        stop_data = json.loads(stop_msg)
        assert stop_data['type'] == 'typing_stop'

    @pytest.mark.asyncio
    async def test_message_ordering(self, test_server, websocket_client):
        """Test that messages are received in correct order."""
        document_id = "ordering_test"
        
        ws1 = await websocket_client(document_id)
        await ws1.recv()
        
        ws2 = await websocket_client(document_id)
        await ws1.recv()
        await ws2.recv()
        
        # Send multiple operations quickly
        operations = []
        for i in range(5):
            op = {
                'type': 'operation',
                'operation': {
                    'type': 'insert',
                    'position': i,
                    'content': f'op_{i}',
                    'id': f'op_{i}'
                }
            }
            operations.append(op)
            await ws1.send(json.dumps(op))
        
        # Receive all operations on ws2
        received_ops = []
        for _ in range(5):
            msg = await ws2.recv()
            data = json.loads(msg)
            received_ops.append(data)
        
        # Check order is maintained
        for i, op_data in enumerate(received_ops):
            assert op_data['operation']['content'] == f'op_{i}'

    @pytest.mark.asyncio
    async def test_concurrent_operations(self, test_server, websocket_client):
        """Test handling concurrent operations from multiple users."""
        document_id = "concurrent_test"
        
        # Connect three users
        ws1 = await websocket_client(document_id)
        await ws1.recv()
        
        ws2 = await websocket_client(document_id)
        await ws1.recv()
        await ws2.recv()
        
        ws3 = await websocket_client(document_id)
        await ws1.recv()
        await ws2.recv()
        await ws3.recv()
        
        # All users send operations simultaneously
        ops = [
            {'type': 'operation', 'operation': {'type': 'insert', 'position': 0, 'content': 'A'}},
            {'type': 'operation', 'operation': {'type': 'insert', 'position': 0, 'content': 'B'}},
            {'type': 'operation', 'operation': {'type': 'insert', 'position': 0, 'content': 'C'}}
        ]
        
        await asyncio.gather(
            ws1.send(json.dumps(ops[0])),
            ws2.send(json.dumps(ops[1])),
            ws3.send(json.dumps(ops[2]))
        )
        
        # Each user should receive the other two operations
        # ws1 should receive ops from ws2 and ws3
        msg1 = await ws1.recv()
        msg2 = await ws1.recv()
        
        assert json.loads(msg1)['type'] == 'operation'
        assert json.loads(msg2)['type'] == 'operation'

    @pytest.mark.asyncio
    async def test_connection_resilience(self, test_server, websocket_client):
        """Test handling of connection drops and errors."""
        document_id = "resilience_test"
        
        ws1 = await websocket_client(document_id)
        await ws1.recv()
        
        ws2 = await websocket_client(document_id)
        await ws1.recv()
        await ws2.recv()
        
        # Simulate network error by closing connection abruptly
        await ws2.close()
        
        # ws1 should receive disconnection notification
        disconnect_msg = await ws1.recv()
        disconnect_data = json.loads(disconnect_msg)
        assert disconnect_data['type'] == 'user_left'

    @pytest.mark.asyncio
    async def test_brain_annotation_operations(self, test_server, websocket_client):
        """Test brain-specific annotation operations."""
        document_id = "brain_annotation_test"
        
        ws1 = await websocket_client(document_id)
        await ws1.recv()
        
        ws2 = await websocket_client(document_id)
        await ws1.recv()
        await ws2.recv()
        
        # Send brain region annotation
        brain_annotation = {
            'type': 'operation',
            'operation': {
                'type': 'annotate',
                'position': 0,
                'content': {
                    'region': 'prefrontal_cortex',
                    'coordinates': {'x': 45, 'y': 67, 'z': 23},
                    'confidence': 0.85,
                    'modality': 'fmri'
                },
                'attributes': {
                    'annotation_type': 'brain_region',
                    'study_id': 'study_123'
                }
            }
        }
        
        await ws1.send(json.dumps(brain_annotation))
        
        # ws2 should receive brain annotation
        annotation_msg = await ws2.recv()
        annotation_data = json.loads(annotation_msg)
        
        assert annotation_data['type'] == 'operation'
        assert annotation_data['operation']['type'] == 'annotate'
        assert annotation_data['operation']['content']['region'] == 'prefrontal_cortex'
        assert annotation_data['operation']['attributes']['annotation_type'] == 'brain_region'

    @pytest.mark.asyncio
    async def test_statistical_threshold_collaboration(self, test_server, websocket_client):
        """Test collaborative statistical threshold adjustments."""
        document_id = "threshold_test"
        
        ws1 = await websocket_client(document_id)
        await ws1.recv()
        
        ws2 = await websocket_client(document_id)
        await ws1.recv()
        await ws2.recv()
        
        # Send threshold change operation
        threshold_op = {
            'type': 'operation',
            'operation': {
                'type': 'replace',
                'position': 0,
                'content': {
                    'threshold': 0.001,
                    'correction': 'fdr',
                    'cluster_threshold': 10
                },
                'attributes': {
                    'parameter_type': 'statistical_threshold',
                    'analysis_id': 'analysis_456'
                }
            }
        }
        
        await ws1.send(json.dumps(threshold_op))
        
        # ws2 should receive threshold change
        threshold_msg = await ws2.recv()
        threshold_data = json.loads(threshold_msg)
        
        assert threshold_data['operation']['content']['threshold'] == 0.001
        assert threshold_data['operation']['content']['correction'] == 'fdr'

    @pytest.mark.asyncio
    async def test_load_balancing_multiple_documents(self, test_server, websocket_client):
        """Test handling multiple documents simultaneously."""
        # Connect users to different documents
        doc1_ws1 = await websocket_client("doc1")
        doc1_ws2 = await websocket_client("doc1")
        doc2_ws1 = await websocket_client("doc2")
        doc2_ws2 = await websocket_client("doc2")
        
        # Clear initial messages
        for ws in [doc1_ws1, doc1_ws2, doc2_ws1, doc2_ws2]:
            try:
                await ws.recv()  # users message or join notification
                if ws in [doc1_ws2, doc2_ws2]:
                    await ws.recv()  # additional users message for second connections
            except:
                pass
        
        # Send operations to both documents
        doc1_op = {'type': 'operation', 'operation': {'type': 'insert', 'content': 'doc1_data'}}
        doc2_op = {'type': 'operation', 'operation': {'type': 'insert', 'content': 'doc2_data'}}
        
        await doc1_ws1.send(json.dumps(doc1_op))
        await doc2_ws1.send(json.dumps(doc2_op))
        
        # Check operations are received by correct document users only
        doc1_msg = await doc1_ws2.recv()
        doc2_msg = await doc2_ws2.recv()
        
        doc1_data = json.loads(doc1_msg)
        doc2_data = json.loads(doc2_msg)
        
        assert doc1_data['operation']['content'] == 'doc1_data'
        assert doc2_data['operation']['content'] == 'doc2_data'

    @pytest.mark.asyncio
    async def test_message_rate_limiting(self, test_server, websocket_client):
        """Test handling of high-frequency messages."""
        document_id = "rate_limit_test"
        
        ws1 = await websocket_client(document_id)
        await ws1.recv()
        
        ws2 = await websocket_client(document_id)
        await ws1.recv()
        await ws2.recv()
        
        # Send many cursor updates rapidly
        start_time = time.time()
        messages_sent = 0
        
        for i in range(50):
            cursor_msg = {
                'type': 'cursor',
                'x': i,
                'y': i,
                'timestamp': datetime.now().isoformat()
            }
            await ws1.send(json.dumps(cursor_msg))
            messages_sent += 1
        
        # Receive messages (some may be throttled)
        messages_received = 0
        try:
            while messages_received < messages_sent:
                await asyncio.wait_for(ws2.recv(), timeout=1.0)
                messages_received += 1
        except asyncio.TimeoutError:
            pass
        
        # Should have received at least some messages
        assert messages_received > 0


class TestWebSocketErrorHandling:
    """Test WebSocket error handling and edge cases."""

    @pytest.mark.asyncio
    async def test_malformed_message_handling(self, test_server, websocket_client):
        """Test handling of malformed JSON messages."""
        document_id = "malformed_test"
        websocket = await websocket_client(document_id)
        await websocket.recv()  # Initial users message
        
        # Send malformed JSON
        await websocket.send("invalid json {")
        
        # Connection should remain open
        ping_msg = {'type': 'ping'}
        await websocket.send(json.dumps(ping_msg))
        
        response = await websocket.recv()
        data = json.loads(response)
        assert data['type'] == 'pong'

    @pytest.mark.asyncio
    async def test_unknown_message_type(self, test_server, websocket_client):
        """Test handling of unknown message types."""
        document_id = "unknown_type_test"
        websocket = await websocket_client(document_id)
        await websocket.recv()
        
        # Send unknown message type
        unknown_msg = {'type': 'unknown_operation', 'data': 'test'}
        await websocket.send(json.dumps(unknown_msg))
        
        # Connection should remain stable
        ping_msg = {'type': 'ping'}
        await websocket.send(json.dumps(ping_msg))
        
        response = await websocket.recv()
        data = json.loads(response)
        assert data['type'] == 'pong'

    @pytest.mark.asyncio
    async def test_large_message_handling(self, test_server, websocket_client):
        """Test handling of large messages."""
        document_id = "large_message_test"
        websocket = await websocket_client(document_id)
        await websocket.recv()
        
        # Send large operation
        large_content = "x" * 10000  # 10KB content
        large_op = {
            'type': 'operation',
            'operation': {
                'type': 'insert',
                'position': 0,
                'content': large_content
            }
        }
        
        await websocket.send(json.dumps(large_op))
        
        # Should handle without issues
        ping_msg = {'type': 'ping'}
        await websocket.send(json.dumps(ping_msg))
        
        response = await websocket.recv()
        data = json.loads(response)
        assert data['type'] == 'pong'


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
