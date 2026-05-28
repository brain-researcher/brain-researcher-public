"""
Real-time status update system with WebSocket and SSE support.

Provides multiple transport mechanisms for delivering execution status updates
to clients in real-time.
"""

import asyncio
import json
import logging
from dataclasses import asdict, dataclass
from typing import Any, Dict, List, Optional, Set
from uuid import uuid4

from fastapi import WebSocket, WebSocketDisconnect
from fastapi.responses import StreamingResponse

logger = logging.getLogger(__name__)


@dataclass
class StatusUpdate:
    """Represents a status update message."""
    
    execution_id: str
    event: str
    timestamp: float
    data: Dict[str, Any]
    update_id: str = ""
    
    def __post_init__(self):
        """Generate update ID if not provided."""
        if not self.update_id:
            self.update_id = str(uuid4())
            
    def to_json(self) -> str:
        """Convert to JSON string."""
        return json.dumps(asdict(self), default=str)
        
    def to_sse(self) -> str:
        """Convert to Server-Sent Events format."""
        return f"id: {self.update_id}\nevent: {self.event}\ndata: {json.dumps(self.data, default=str)}\n\n"


class ConnectionManager:
    """Manages WebSocket and SSE connections for status updates."""
    
    def __init__(self):
        """Initialize connection manager."""
        # WebSocket connections by execution_id
        self.websocket_connections: Dict[str, Set[WebSocket]] = {}
        
        # SSE connections by execution_id
        self.sse_queues: Dict[str, List[asyncio.Queue]] = {}
        
        # Update history for replay
        self.update_history: Dict[str, List[StatusUpdate]] = {}
        self.history_limit = 100
        
        # Active execution trackers
        self.active_executions: Set[str] = set()
        
    async def connect_websocket(
        self,
        websocket: WebSocket,
        execution_id: str
    ):
        """
        Connect a WebSocket client.
        
        Args:
            websocket: WebSocket connection
            execution_id: Execution to subscribe to
        """
        await websocket.accept()
        
        # Add to connections
        if execution_id not in self.websocket_connections:
            self.websocket_connections[execution_id] = set()
        self.websocket_connections[execution_id].add(websocket)
        
        # Mark execution as active
        self.active_executions.add(execution_id)
        
        # Send connection confirmation
        await self._send_websocket(websocket, {
            "event": "connected",
            "execution_id": execution_id,
            "message": "WebSocket connected successfully"
        })
        
        # Send update history if available
        if execution_id in self.update_history:
            for update in self.update_history[execution_id]:
                await self._send_websocket(websocket, update.data)
                
        logger.info(f"WebSocket connected for execution {execution_id}")
        
    async def disconnect_websocket(
        self,
        websocket: WebSocket,
        execution_id: str
    ):
        """
        Disconnect a WebSocket client.
        
        Args:
            websocket: WebSocket connection
            execution_id: Execution ID
        """
        if execution_id in self.websocket_connections:
            self.websocket_connections[execution_id].discard(websocket)
            
            # Clean up if no more connections
            if not self.websocket_connections[execution_id]:
                del self.websocket_connections[execution_id]
                
        logger.info(f"WebSocket disconnected for execution {execution_id}")
        
    async def create_sse_stream(
        self,
        execution_id: str
    ) -> asyncio.Queue:
        """
        Create an SSE stream for an execution.
        
        Args:
            execution_id: Execution to subscribe to
            
        Returns:
            Queue for SSE updates
        """
        queue = asyncio.Queue()
        
        # Add to SSE queues
        if execution_id not in self.sse_queues:
            self.sse_queues[execution_id] = []
        self.sse_queues[execution_id].append(queue)
        
        # Mark execution as active
        self.active_executions.add(execution_id)
        
        # Send connection event
        await queue.put(StatusUpdate(
            execution_id=execution_id,
            event="connected",
            timestamp=asyncio.get_event_loop().time(),
            data={"message": "SSE stream connected"}
        ))
        
        # Send update history if available
        if execution_id in self.update_history:
            for update in self.update_history[execution_id]:
                await queue.put(update)
                
        logger.info(f"SSE stream created for execution {execution_id}")
        return queue
        
    async def close_sse_stream(
        self,
        execution_id: str,
        queue: asyncio.Queue
    ):
        """
        Close an SSE stream.
        
        Args:
            execution_id: Execution ID
            queue: SSE queue to close
        """
        if execution_id in self.sse_queues:
            if queue in self.sse_queues[execution_id]:
                self.sse_queues[execution_id].remove(queue)
                
            # Clean up if no more queues
            if not self.sse_queues[execution_id]:
                del self.sse_queues[execution_id]
                
        logger.info(f"SSE stream closed for execution {execution_id}")
        
    async def broadcast_update(
        self,
        execution_id: str,
        event: str,
        data: Dict[str, Any],
        timestamp: Optional[float] = None
    ):
        """
        Broadcast update to all connected clients.
        
        Args:
            execution_id: Execution ID
            event: Event name
            data: Event data
            timestamp: Optional timestamp
        """
        update = StatusUpdate(
            execution_id=execution_id,
            event=event,
            timestamp=timestamp or asyncio.get_event_loop().time(),
            data=data
        )
        
        # Store in history
        if execution_id not in self.update_history:
            self.update_history[execution_id] = []
        self.update_history[execution_id].append(update)
        
        # Trim history if needed
        if len(self.update_history[execution_id]) > self.history_limit:
            self.update_history[execution_id] = \
                self.update_history[execution_id][-self.history_limit:]
                
        # Broadcast to WebSocket connections
        if execution_id in self.websocket_connections:
            disconnected = set()
            for websocket in self.websocket_connections[execution_id]:
                try:
                    await self._send_websocket(websocket, {
                        "event": event,
                        "data": data,
                        "timestamp": update.timestamp,
                        "update_id": update.update_id
                    })
                except WebSocketDisconnect:
                    disconnected.add(websocket)
                except Exception as e:
                    logger.error(f"Failed to send WebSocket update: {e}")
                    disconnected.add(websocket)
                    
            # Clean up disconnected
            for ws in disconnected:
                await self.disconnect_websocket(ws, execution_id)
                
        # Broadcast to SSE queues
        if execution_id in self.sse_queues:
            for queue in self.sse_queues[execution_id]:
                try:
                    await queue.put(update)
                except Exception as e:
                    logger.error(f"Failed to send SSE update: {e}")
                    
    async def _send_websocket(
        self,
        websocket: WebSocket,
        data: Dict[str, Any]
    ):
        """Send data through WebSocket."""
        await websocket.send_json(data)
        
    def get_active_executions(self) -> List[str]:
        """Get list of active execution IDs."""
        return list(self.active_executions)
        
    def get_connection_stats(self) -> Dict[str, Any]:
        """Get connection statistics."""
        return {
            "active_executions": len(self.active_executions),
            "websocket_connections": sum(
                len(conns) for conns in self.websocket_connections.values()
            ),
            "sse_streams": sum(
                len(queues) for queues in self.sse_queues.values()
            ),
            "executions_with_history": len(self.update_history)
        }
        
    def cleanup_execution(self, execution_id: str):
        """
        Clean up resources for an execution.
        
        Args:
            execution_id: Execution to clean up
        """
        # Remove from active
        self.active_executions.discard(execution_id)
        
        # Clear history after delay (keep for replay)
        # In production, this would be scheduled
        if execution_id in self.update_history:
            # Keep history for 1 hour after completion
            pass


class StatusUpdateService:
    """Service for managing status updates across the application."""
    
    def __init__(self):
        """Initialize status update service."""
        self.connection_manager = ConnectionManager()
        self.execution_trackers: Dict[str, Any] = {}  # ExecutionTracker instances
        
    async def register_execution(
        self,
        execution_id: str,
        tracker: Any  # ExecutionTracker
    ):
        """
        Register an execution tracker.
        
        Args:
            execution_id: Execution ID
            tracker: ExecutionTracker instance
        """
        self.execution_trackers[execution_id] = tracker
        
        # Set up update callback
        async def update_callback(update: Dict[str, Any]):
            await self.connection_manager.broadcast_update(
                execution_id=execution_id,
                event=update.get("event", "update"),
                data=update.get("data", {}),
                timestamp=update.get("timestamp")
            )
            
        # For AsyncExecutionTracker
        if hasattr(tracker, 'add_listener'):
            await tracker.add_listener(update_callback)
        else:
            tracker.update_callback = update_callback
            
    async def unregister_execution(self, execution_id: str):
        """
        Unregister an execution tracker.
        
        Args:
            execution_id: Execution ID
        """
        if execution_id in self.execution_trackers:
            del self.execution_trackers[execution_id]
            
        # Schedule cleanup
        self.connection_manager.cleanup_execution(execution_id)
        
    def get_execution_tracker(self, execution_id: str) -> Optional[Any]:
        """
        Get execution tracker by ID.
        
        Args:
            execution_id: Execution ID
            
        Returns:
            ExecutionTracker instance or None
        """
        return self.execution_trackers.get(execution_id)
        
    async def handle_websocket(
        self,
        websocket: WebSocket,
        execution_id: str
    ):
        """
        Handle WebSocket connection for status updates.
        
        Args:
            websocket: WebSocket connection
            execution_id: Execution to subscribe to
        """
        await self.connection_manager.connect_websocket(websocket, execution_id)
        
        try:
            # Keep connection alive and handle messages
            while True:
                # Wait for messages (ping/pong or commands)
                data = await websocket.receive_json()
                
                # Handle commands
                if data.get("command") == "get_status":
                    tracker = self.get_execution_tracker(execution_id)
                    if tracker:
                        await websocket.send_json({
                            "event": "status",
                            "data": tracker.get_status()
                        })
                elif data.get("command") == "ping":
                    await websocket.send_json({"event": "pong"})
                    
        except WebSocketDisconnect:
            await self.connection_manager.disconnect_websocket(websocket, execution_id)
        except Exception as e:
            logger.error(f"WebSocket error: {e}")
            await self.connection_manager.disconnect_websocket(websocket, execution_id)
            
    async def create_sse_endpoint(self, execution_id: str):
        """
        Create SSE endpoint for status updates.
        
        Args:
            execution_id: Execution to subscribe to
            
        Returns:
            StreamingResponse for SSE
        """
        queue = await self.connection_manager.create_sse_stream(execution_id)
        
        async def event_generator():
            """Generate SSE events."""
            try:
                while True:
                    # Get update from queue
                    update = await queue.get()
                    
                    # Send as SSE
                    yield update.to_sse()
                    
                    # Check if execution completed
                    if update.event in ["execution_completed", "execution_failed", "execution_cancelled"]:
                        break
                        
            except asyncio.CancelledError:
                pass
            finally:
                await self.connection_manager.close_sse_stream(execution_id, queue)
                
        return StreamingResponse(
            event_generator(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",  # Disable Nginx buffering
            }
        )


# Global service instance
status_service = StatusUpdateService()


# FastAPI route examples
async def websocket_endpoint(websocket: WebSocket, execution_id: str):
    """
    WebSocket endpoint for status updates.
    
    Example usage in FastAPI:
    ```python
    @app.websocket("/ws/execution/{execution_id}")
    async def websocket_route(websocket: WebSocket, execution_id: str):
        await status_service.handle_websocket(websocket, execution_id)
    ```
    """
    await status_service.handle_websocket(websocket, execution_id)
    

async def sse_endpoint(execution_id: str):
    """
    SSE endpoint for status updates.
    
    Example usage in FastAPI:
    ```python
    @app.get("/sse/execution/{execution_id}")
    async def sse_route(execution_id: str):
        return await status_service.create_sse_endpoint(execution_id)
    ```
    """
    return await status_service.create_sse_endpoint(execution_id)