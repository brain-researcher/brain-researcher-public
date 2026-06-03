"""
WebSocket endpoints for real-time communication including notifications,
job updates, and chat streaming.
"""

import asyncio
import json
import logging
import os
import uuid
from contextlib import suppress
from datetime import datetime
from typing import Dict, List, Optional, Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, HTTPException, Depends, Query
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from .websocket_manager import (
    websocket_pool, WebSocketMessage, MessageType, Connection
)
from .models import JobStatus, Job, Notification
from .dashboard_endpoints import build_dashboard_metrics_response
from .job_management_endpoints import _get_router_job
from .pipeline_graph import build_job_graph_snapshot

logger = logging.getLogger(__name__)

# Initialize router
router = APIRouter(prefix="/ws", tags=["websockets"])
DASHBOARD_WS_INTERVAL_SECONDS = float(os.getenv("DASHBOARD_WS_INTERVAL_SECONDS", "3"))


# ============================================================================
# WebSocket Models
# ============================================================================

class NotificationMessage(BaseModel):
    """Notification message structure."""
    id: str
    type: str
    title: str
    message: str
    priority: str = "normal"
    data: Optional[Dict[str, Any]] = None
    timestamp: datetime
    expires_at: Optional[datetime] = None


class JobUpdateMessage(BaseModel):
    """Job update message structure."""
    job_id: str
    status: JobStatus
    progress: float
    current_step: Optional[str] = None
    message: Optional[str] = None
    artifacts: List[Dict[str, Any]] = []
    timestamp: datetime


class ChatMessage(BaseModel):
    """Chat message structure."""
    thread_id: str
    message_id: str
    role: str  # "user" or "assistant"
    content: str
    timestamp: datetime
    is_streaming: bool = False
    is_complete: bool = True


# ============================================================================
# In-Memory Storage (Replace with Redis/Database in production)
# ============================================================================

# Active chat streams
active_chat_streams: Dict[str, asyncio.Queue] = {}

# Job subscribers
job_subscribers: Dict[str, List[str]] = {}  # job_id -> [connection_ids]

# Notification queues
notification_queues: Dict[str, asyncio.Queue] = {}  # user_id -> notification queue


# ============================================================================
# Connection Event Handlers
# ============================================================================

async def handle_new_connection(connection: Connection):
    """Handle new WebSocket connection."""
    logger.info(f"New WebSocket connection: {connection.connection_id}")

    # Send welcome message
    welcome_message = WebSocketMessage(
        type=MessageType.NOTIFICATION,
        data={
            "type": "welcome",
            "title": "Connected",
            "message": f"WebSocket connection established (ID: {connection.connection_id})",
            "timestamp": datetime.utcnow().isoformat()
        }
    )
    await connection.send_message(welcome_message)


async def handle_connection_closed(connection: Connection):
    """Handle WebSocket connection closure."""
    logger.info(f"WebSocket connection closed: {connection.connection_id}")

    # Clean up job subscriptions
    for job_id, subscribers in job_subscribers.items():
        if connection.connection_id in subscribers:
            subscribers.remove(connection.connection_id)

    # Clean up chat streams
    connection_chat_streams = [
        thread_id for thread_id, queue in active_chat_streams.items()
        if hasattr(queue, 'connection_id') and queue.connection_id == connection.connection_id
    ]
    for thread_id in connection_chat_streams:
        del active_chat_streams[thread_id]


async def handle_custom_message(connection: Connection, message: WebSocketMessage):
    """Handle custom WebSocket messages."""
    if message.type == MessageType.DATA:
        data = message.data or {}

        # Handle different data message types
        if data.get("action") == "subscribe_job":
            job_id = data.get("job_id")
            if job_id:
                if job_id not in job_subscribers:
                    job_subscribers[job_id] = []
                job_subscribers[job_id].append(connection.connection_id)

                # Send current job status
                # This would typically fetch from your job storage
                response = WebSocketMessage(
                    type=MessageType.DATA,
                    data={
                        "action": "job_subscribed",
                        "job_id": job_id,
                        "status": "subscribed"
                    }
                )
                await connection.send_message(response)

        elif data.get("action") == "unsubscribe_job":
            job_id = data.get("job_id")
            if job_id and job_id in job_subscribers:
                if connection.connection_id in job_subscribers[job_id]:
                    job_subscribers[job_id].remove(connection.connection_id)


# Register event handlers
websocket_pool.add_connection_handler(handle_new_connection)
websocket_pool.add_disconnection_handler(handle_connection_closed)
websocket_pool.add_message_handler("data", handle_custom_message)


# ============================================================================
# WebSocket Endpoints
# ============================================================================


async def _send_dashboard_snapshot(connection_id: str) -> bool:
    """Push the latest dashboard snapshot to a single connection."""
    try:
        metrics = await build_dashboard_metrics_response()
        payload = {
            "type": "snapshot",
            "data": metrics.model_dump(mode="json"),
        }
    except Exception as exc:
        logger.error("Failed to build dashboard metrics snapshot: %s", exc)
        error_message = WebSocketMessage(
            type=MessageType.ERROR,
            channel="dashboard",
            data={"error": "dashboard_snapshot_failed", "detail": str(exc)},
        )
        await websocket_pool.send_to_connection(connection_id, error_message)
        return False

    message = WebSocketMessage(
        type=MessageType.DATA,
        channel="dashboard",
        data=payload,
    )
    return await websocket_pool.send_to_connection(connection_id, message)


async def _dashboard_metrics_loop(connection_id: str, interval_seconds: float = DASHBOARD_WS_INTERVAL_SECONDS):
    """Periodically refresh dashboard data for a connected client."""
    try:
        while True:
            await asyncio.sleep(interval_seconds)
            success = await _send_dashboard_snapshot(connection_id)
            if not success:
                break
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        logger.error("Dashboard metrics loop error: %s", exc)


async def _send_ws_json(connection: Connection, payload: Dict[str, Any]) -> bool:
    """Send a raw JSON message (v1 protocol) to a connection."""
    try:
        await connection.websocket.send_text(json.dumps(payload))
        return True
    except Exception as exc:
        logger.error("Failed to send WS payload: %s", exc)
        return False



def _extract_v1_subscribe(message: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    if message.get("type") != "subscribe":
        return None
    if "streams" in message:
        return message
    data = message.get("data")
    if isinstance(data, dict) and "streams" in data:
        return data
    return None


@router.websocket("/dashboard")
async def websocket_dashboard_updates(
    websocket: WebSocket,
    user_id: Optional[str] = Query(None),
):
    """WebSocket endpoint for live dashboard updates."""
    connection_id: Optional[str] = None
    update_task: Optional[asyncio.Task] = None

    try:
        connection_id = await websocket_pool.add_connection(
            websocket,
            user_id=user_id,
            metadata={"endpoint": "dashboard"},
        )
        await websocket_pool.subscribe(connection_id, "dashboard:updates")

        await _send_dashboard_snapshot(connection_id)
        update_task = asyncio.create_task(_dashboard_metrics_loop(connection_id))

        while True:
            data = await websocket.receive_text()
            try:
                message_dict = json.loads(data)
            except json.JSONDecodeError:
                await websocket_pool.handle_message(connection_id, data)
                continue

            v1_payload = _extract_v1_subscribe(message_dict)
            if v1_payload:
                request_id = v1_payload.get("request_id") or message_dict.get("request_id")
                stream_id = "dashboard"
                applied_limits = (v1_payload.get("streams") or [{}])[0].get("limits") or {}
                await _send_ws_json(
                    websocket_pool.connections[connection_id],
                    {
                        "type": "subscribe_ack",
                        "request_id": request_id,
                        "stream_id": stream_id,
                        "applied_subscriptions": [
                            {"stream": "dashboard", "channels": ["snapshot"]}
                        ],
                        "applied_limits": applied_limits,
                        "checkpoint_id": 0,
                        "resume_status": "unsupported",
                        "snapshot_sent": False,
                    },
                )
                await _send_dashboard_snapshot(connection_id)
                continue

            await websocket_pool.handle_message(connection_id, data)

    except WebSocketDisconnect:
        logger.info("Dashboard WebSocket disconnected: %s", connection_id)

    except Exception as exc:
        logger.error("Failed to establish dashboard WebSocket: %s", exc)
        if connection_id:
            await websocket_pool.send_to_connection(
                connection_id,
                WebSocketMessage(
                    type=MessageType.ERROR,
                    channel="dashboard",
                    data={"error": "dashboard_connection_failed", "detail": str(exc)},
                ),
            )

    finally:
        if update_task:
            update_task.cancel()
            with suppress(asyncio.CancelledError):
                await update_task
        if connection_id:
            await websocket_pool.disconnect(connection_id, "Dashboard WebSocket closed")


@router.websocket("/notifications")
async def websocket_notifications(
    websocket: WebSocket,
    user_id: Optional[str] = Query(None),
    token: Optional[str] = Query(None)
):
    """
    WebSocket endpoint for real-time notifications with connection management
    and automatic reconnection logic.
    """
    connection_id: Optional[str] = None
    try:
        # Add connection to pool
        connection_id = await websocket_pool.add_connection(
            websocket,
            user_id=user_id,
            metadata={"endpoint": "notifications", "token": token}
        )

        # Subscribe to notifications channel
        if user_id:
            await websocket_pool.subscribe(connection_id, f"notifications:{user_id}")

        # Subscribe to system-wide notifications
        await websocket_pool.subscribe(connection_id, "notifications:system")

        # Handle incoming messages
        try:
            while True:
                data = await websocket.receive_text()
                try:
                    message_dict = json.loads(data)
                except json.JSONDecodeError:
                    await websocket_pool.handle_message(connection_id, data)
                    continue

                v1_payload = _extract_v1_subscribe(message_dict)
                if v1_payload:
                    request_id = v1_payload.get("request_id") or message_dict.get("request_id")
                    stream_id = f"notifications:{user_id or 'anonymous'}"
                    applied_limits = (v1_payload.get("streams") or [{}])[0].get("limits") or {}
                    await _send_ws_json(
                        websocket_pool.connections[connection_id],
                        {
                            "type": "subscribe_ack",
                            "request_id": request_id,
                            "stream_id": stream_id,
                            "applied_subscriptions": [
                                {"stream": "notifications", "user_id": user_id}
                            ],
                            "applied_limits": applied_limits,
                            "checkpoint_id": 0,
                            "resume_status": "unsupported",
                            "snapshot_sent": False,
                        },
                    )
                    continue

                await websocket_pool.handle_message(connection_id, data)

        except WebSocketDisconnect:
            logger.info(f"Notifications WebSocket disconnected: {connection_id}")

        except Exception as e:
            logger.error(f"Error in notifications WebSocket: {str(e)}")

    except Exception as e:
        logger.error(f"Failed to establish notifications WebSocket: {str(e)}")
        await websocket.close(code=1011, reason=f"Setup failed: {str(e)}")

    finally:
        if connection_id:
            await websocket_pool.disconnect(connection_id, "Notifications WebSocket closed")


@router.websocket("/jobs/{job_id}")
async def websocket_job_updates(
    websocket: WebSocket,
    job_id: str,
    user_id: Optional[str] = Query(None)
):
    """
    WebSocket endpoint for real-time job updates with detailed progress tracking.
    """
    connection_id: Optional[str] = None
    try:
        # Validate job exists (you would check your job storage here)
        # For now, we'll accept any job_id

        # Add connection to pool
        connection_id = await websocket_pool.add_connection(
            websocket,
            user_id=user_id,
            metadata={"endpoint": "job_updates", "job_id": job_id}
        )

        # Subscribe to job-specific channel (legacy compatibility)
        await websocket_pool.subscribe(connection_id, f"jobs:{job_id}")

        # Send initial job status (legacy)
        initial_message = WebSocketMessage(
            type=MessageType.DATA,
            channel=f"jobs:{job_id}",
            data={
                "type": "job_status",
                "job_id": job_id,
                "status": "connected",
                "message": "Connected to job updates",
                "timestamp": datetime.utcnow().isoformat()
            }
        )
        await websocket_pool.send_to_connection(connection_id, initial_message)

        # Handle incoming messages
        try:
            while True:
                data = await websocket.receive_text()
                try:
                    message_dict = json.loads(data)
                except json.JSONDecodeError:
                    await websocket_pool.handle_message(connection_id, data)
                    continue

                v1_payload = _extract_v1_subscribe(message_dict)
                if v1_payload:
                    streams = v1_payload.get("streams") or []
                    request_id = v1_payload.get("request_id") or message_dict.get("request_id")
                    stream = next(
                        (s for s in streams if s.get("stream") == "job"),
                        None,
                    )
                    target_job_id = (stream or {}).get("job_id") or job_id
                    if target_job_id != job_id:
                        await _send_ws_json(
                            websocket_pool.connections[connection_id],
                            {
                                "type": "error",
                                "error_code": "FORBIDDEN",
                                "detail": "Job mismatch",
                                "retryable": False,
                            },
                        )
                        continue

                    stream_id = f"job:{job_id}"
                    applied_limits = (stream or {}).get("limits") or {}
                    applied_channels = (stream or {}).get("channels") or []
                    await websocket_pool.subscribe(connection_id, f"jobs:{job_id}")

                    await _send_ws_json(
                        websocket_pool.connections[connection_id],
                        {
                            "type": "subscribe_ack",
                            "request_id": request_id,
                            "stream_id": stream_id,
                            "applied_subscriptions": [
                                {
                                    "stream": "job",
                                    "job_id": job_id,
                                    "channels": applied_channels,
                                }
                            ],
                            "applied_limits": applied_limits,
                            "checkpoint_id": 0,
                            "resume_status": "unsupported",
                            "snapshot_sent": False,
                        },
                    )

                    job = _get_router_job(job_id)
                    snapshot = build_job_graph_snapshot(job, job_id=job_id)
                    await _send_ws_json(
                        websocket_pool.connections[connection_id],
                        {
                            "type": "pipeline_snapshot",
                            "stream_id": stream_id,
                            "checkpoint_id": snapshot.get("checkpoint_id", 0),
                            "payload": snapshot,
                        },
                    )
                    continue

                # Legacy subscribe (e.g. data.channel)
                if message_dict.get("type") == "subscribe":
                    data_payload = message_dict.get("data") or {}
                    legacy_channel = data_payload.get("channel")
                    if legacy_channel:
                        await websocket_pool.subscribe(connection_id, legacy_channel)
                        await _send_ws_json(
                            websocket_pool.connections[connection_id],
                            {
                                "type": "deprecation_notice",
                                "deprecated_protocol": "legacy_channel",
                                "sunset_at": None,
                                "replacement": "subscribe_v1",
                            },
                        )
                        continue

                await websocket_pool.handle_message(connection_id, data)

        except WebSocketDisconnect:
            logger.info(f"Job updates WebSocket disconnected: {connection_id}")

        except Exception as e:
            logger.error(f"Error in job updates WebSocket: {str(e)}")

    except Exception as e:
        logger.error(f"Failed to establish job updates WebSocket: {str(e)}")
        await websocket.close(code=1011, reason=f"Setup failed: {str(e)}")
    finally:
        if connection_id:
            await websocket_pool.disconnect(connection_id, "Job updates WebSocket closed")


@router.websocket("/chat/{thread_id}")
async def websocket_chat_stream(
    websocket: WebSocket,
    thread_id: str,
    user_id: Optional[str] = Query(None)
):
    """
    WebSocket endpoint for streaming chat responses with real-time updates.
    """
    connection_id: Optional[str] = None
    try:
        # Add connection to pool
        connection_id = await websocket_pool.add_connection(
            websocket,
            user_id=user_id,
            metadata={"endpoint": "chat_stream", "thread_id": thread_id}
        )

        # Subscribe to thread-specific channel
        await websocket_pool.subscribe(connection_id, f"chat:{thread_id}")

        # Initialize chat stream queue
        if thread_id not in active_chat_streams:
            active_chat_streams[thread_id] = asyncio.Queue()
            # Add connection reference for cleanup
            active_chat_streams[thread_id].connection_id = connection_id

        # Send connection confirmation
        confirmation_message = WebSocketMessage(
            type=MessageType.DATA,
            channel=f"chat:{thread_id}",
            data={
                "type": "chat_connected",
                "thread_id": thread_id,
                "status": "ready",
                "timestamp": datetime.utcnow().isoformat()
            }
        )
        await websocket_pool.send_to_connection(connection_id, confirmation_message)

        # Handle incoming messages
        try:
            while True:
                data = await websocket.receive_text()

                try:
                    message_data = json.loads(data)

                    # Handle chat-specific messages
                    if message_data.get("type") == "user_message":
                        # Process user message and start streaming response
                        await handle_user_chat_message(thread_id, message_data, connection_id)

                    else:
                        # Handle other message types through pool
                        await websocket_pool.handle_message(connection_id, data)

                except json.JSONDecodeError:
                    error_message = WebSocketMessage(
                        type=MessageType.ERROR,
                        data={"error": "Invalid JSON format"}
                    )
                    await websocket_pool.send_to_connection(connection_id, error_message)

        except WebSocketDisconnect:
            logger.info(f"Chat stream WebSocket disconnected: {connection_id}")

        except Exception as e:
            logger.error(f"Error in chat stream WebSocket: {str(e)}")

    except Exception as e:
        logger.error(f"Failed to establish chat stream WebSocket: {str(e)}")
        await websocket.close(code=1011, reason=f"Setup failed: {str(e)}")

    finally:
        # Clean up chat stream
        if thread_id in active_chat_streams:
            del active_chat_streams[thread_id]
        if connection_id:
            await websocket_pool.disconnect(connection_id, "Chat stream WebSocket closed")


# ============================================================================
# Message Broadcasting Functions
# ============================================================================

async def broadcast_notification(
    user_id: Optional[str] = None,
    notification: NotificationMessage = None,
    system_wide: bool = False
):
    """Broadcast notification to WebSocket clients."""
    if not notification:
        return

    message = WebSocketMessage(
        type=MessageType.NOTIFICATION,
        data=notification.model_dump()
    )

    if system_wide:
        # Broadcast to all connected clients
        await websocket_pool.broadcast_to_channel("notifications:system", message)

    elif user_id:
        # Send to specific user
        await websocket_pool.broadcast_to_channel(f"notifications:{user_id}", message)


async def broadcast_job_update(
    job_id: str,
    update: JobUpdateMessage
):
    """Broadcast job update to subscribed WebSocket clients."""
    message = WebSocketMessage(
        type=MessageType.DATA,
        channel=f"jobs:{job_id}",
        data=update.model_dump()
    )

    await websocket_pool.broadcast_to_channel(f"jobs:{job_id}", message)


async def stream_chat_message(
    thread_id: str,
    message: ChatMessage
):
    """Stream chat message to WebSocket clients."""
    ws_message = WebSocketMessage(
        type=MessageType.DATA,
        channel=f"chat:{thread_id}",
        data=message.model_dump()
    )

    await websocket_pool.broadcast_to_channel(f"chat:{thread_id}", ws_message)


# ============================================================================
# Chat Message Handling
# ============================================================================

async def handle_user_chat_message(
    thread_id: str,
    message_data: Dict[str, Any],
    connection_id: str
):
    """Handle user chat message and start streaming response."""
    try:
        user_message = message_data.get("content", "")
        message_id = f"msg_{uuid.uuid4().hex[:12]}"

        # Echo the user message
        user_chat_msg = ChatMessage(
            thread_id=thread_id,
            message_id=message_id,
            role="user",
            content=user_message,
            timestamp=datetime.utcnow(),
            is_streaming=False,
            is_complete=True
        )
        await stream_chat_message(thread_id, user_chat_msg)

        # Start streaming assistant response
        asyncio.create_task(simulate_streaming_response(thread_id, user_message))

    except Exception as e:
        logger.error(f"Error handling user chat message: {str(e)}")
        error_message = WebSocketMessage(
            type=MessageType.ERROR,
            data={"error": f"Failed to process message: {str(e)}"}
        )
        await websocket_pool.send_to_connection(connection_id, error_message)


async def simulate_streaming_response(thread_id: str, user_message: str):
    """Simulate streaming chat response (replace with actual LLM integration)."""
    try:
        response_id = f"resp_{uuid.uuid4().hex[:12]}"

        # Simulate processing delay
        await asyncio.sleep(1)

        # Simulate streaming response
        mock_response = f"I understand you're asking about: '{user_message}'. Let me process this request and provide a detailed analysis..."

        words = mock_response.split()
        accumulated_content = ""

        for i, word in enumerate(words):
            accumulated_content += word + " "

            is_complete = i == len(words) - 1

            chat_message = ChatMessage(
                thread_id=thread_id,
                message_id=response_id,
                role="assistant",
                content=accumulated_content.strip(),
                timestamp=datetime.utcnow(),
                is_streaming=not is_complete,
                is_complete=is_complete
            )

            await stream_chat_message(thread_id, chat_message)

            # Simulate typing delay
            if not is_complete:
                await asyncio.sleep(0.1)

    except Exception as e:
        logger.error(f"Error in streaming response: {str(e)}")
        error_chat_msg = ChatMessage(
            thread_id=thread_id,
            message_id=f"error_{uuid.uuid4().hex[:8]}",
            role="assistant",
            content=f"Sorry, I encountered an error: {str(e)}",
            timestamp=datetime.utcnow(),
            is_streaming=False,
            is_complete=True
        )
        await stream_chat_message(thread_id, error_chat_msg)


# ============================================================================
# HTTP Endpoints for WebSocket Management
# ============================================================================

@router.get("/status")
async def get_websocket_status():
    """Get WebSocket pool status and statistics."""
    stats = websocket_pool.get_stats()

    return {
        "status": "active",
        "pool_stats": stats,
        "active_job_subscriptions": len(job_subscribers),
        "active_chat_streams": len(active_chat_streams),
        "channels": {
            "notifications": len([c for c in websocket_pool.connections_by_channel.keys() if c.startswith("notifications:")]),
            "jobs": len([c for c in websocket_pool.connections_by_channel.keys() if c.startswith("jobs:")]),
            "chat": len([c for c in websocket_pool.connections_by_channel.keys() if c.startswith("chat:")])
        }
    }


@router.post("/broadcast/notification")
async def broadcast_notification_endpoint(
    title: str,
    message: str,
    user_id: Optional[str] = None,
    system_wide: bool = False,
    priority: str = "normal",
    data: Optional[Dict[str, Any]] = None
):
    """HTTP endpoint to broadcast notifications via WebSocket."""
    notification = NotificationMessage(
        id=f"notif_{uuid.uuid4().hex[:12]}",
        type="notification",
        title=title,
        message=message,
        priority=priority,
        data=data,
        timestamp=datetime.utcnow()
    )

    await broadcast_notification(user_id, notification, system_wide)

    return {"status": "broadcasted", "notification_id": notification.id}


@router.post("/broadcast/job/{job_id}")
async def broadcast_job_update_endpoint(
    job_id: str,
    status: JobStatus,
    progress: float,
    current_step: Optional[str] = None,
    message: Optional[str] = None,
    artifacts: Optional[List[Dict[str, Any]]] = None
):
    """HTTP endpoint to broadcast job updates via WebSocket."""
    job_update = JobUpdateMessage(
        job_id=job_id,
        status=status,
        progress=progress,
        current_step=current_step,
        message=message,
        artifacts=artifacts or [],
        timestamp=datetime.utcnow()
    )

    await broadcast_job_update(job_id, job_update)

    return {"status": "broadcasted", "job_id": job_id}


@router.get("/connections")
async def list_connections(user_id: Optional[str] = None):
    """List active WebSocket connections."""
    if user_id:
        connections = websocket_pool.get_user_connections(user_id)
        return {
            "user_id": user_id,
            "connections": [
                {
                    "connection_id": conn.connection_id,
                    "created_at": conn.created_at.isoformat(),
                    "last_activity": conn.last_activity.isoformat(),
                    "subscriptions": list(conn.subscriptions),
                    "message_count": conn.message_count,
                    "state": conn.state.value
                }
                for conn in connections
            ]
        }
    else:
        stats = websocket_pool.get_stats()
        return {
            "total_connections": stats["active_connections"],
            "connections_by_user": {
                user: len(conn_ids)
                for user, conn_ids in websocket_pool.connections_by_user.items()
            },
            "connections_by_channel": {
                channel: len(conn_ids)
                for channel, conn_ids in websocket_pool.connections_by_channel.items()
            }
        }


@router.delete("/connections/{connection_id}")
async def disconnect_connection(connection_id: str, reason: str = "Manual disconnect"):
    """Manually disconnect a WebSocket connection."""
    connection = websocket_pool.get_connection(connection_id)
    if not connection:
        raise HTTPException(status_code=404, detail="Connection not found")

    await websocket_pool.disconnect(connection_id, reason)

    return {"status": "disconnected", "connection_id": connection_id}


@router.get("/test")
async def websocket_test_page():
    """Test page for WebSocket connections."""
    html_content = """
    <!DOCTYPE html>
    <html>
    <head>
        <title>WebSocket Test</title>
    </head>
    <body>
        <h1>WebSocket Test Page</h1>
        <div id="messages"></div>
        <input type="text" id="messageInput" placeholder="Type a message...">
        <button onclick="sendMessage()">Send</button>

        <script>
            const wsProtocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
            const ws = new WebSocket(`${wsProtocol}//${window.location.host}/ws/notifications`);
            const messages = document.getElementById('messages');

            ws.onmessage = function(event) {
                const message = JSON.parse(event.data);
                const div = document.createElement('div');
                div.textContent = JSON.stringify(message, null, 2);
                messages.appendChild(div);
            };

            ws.onopen = function() {
                console.log('WebSocket connected');
            };

            ws.onclose = function() {
                console.log('WebSocket disconnected');
            };

            function sendMessage() {
                const input = document.getElementById('messageInput');
                const message = {
                    type: 'data',
                    data: { content: input.value },
                    timestamp: new Date().toISOString()
                };
                ws.send(JSON.stringify(message));
                input.value = '';
            }

            document.getElementById('messageInput').addEventListener('keypress', function(e) {
                if (e.key === 'Enter') {
                    sendMessage();
                }
            });
        </script>
    </body>
    </html>
    """
    return HTMLResponse(content=html_content)


# ============================================================================
# Initialization
# ============================================================================

async def initialize_websocket_infrastructure():
    """Initialize WebSocket infrastructure."""
    await websocket_pool.start()
    logger.info("WebSocket infrastructure initialized")


async def shutdown_websocket_infrastructure():
    """Shutdown WebSocket infrastructure."""
    await websocket_pool.stop()
    logger.info("WebSocket infrastructure shutdown")
