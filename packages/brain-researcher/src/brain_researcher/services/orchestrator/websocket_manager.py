"""
WebSocket infrastructure with enhanced connection management, connection pooling,
and automatic reconnection logic.
"""

import asyncio
import json
import logging
import time
import uuid
from collections import defaultdict, deque
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any, Set, Callable, Union
from enum import Enum
import weakref

from fastapi import WebSocket, WebSocketDisconnect
from pydantic import BaseModel
import redis.asyncio as redis

logger = logging.getLogger(__name__)


class ConnectionState(str, Enum):
    """WebSocket connection states."""
    CONNECTING = "connecting"
    CONNECTED = "connected"
    DISCONNECTING = "disconnecting"
    DISCONNECTED = "disconnected"
    RECONNECTING = "reconnecting"
    ERROR = "error"


class MessageType(str, Enum):
    """WebSocket message types."""
    PING = "ping"
    PONG = "pong"
    HEARTBEAT = "heartbeat"
    SUBSCRIBE = "subscribe"
    UNSUBSCRIBE = "unsubscribe"
    DATA = "data"
    ERROR = "error"
    CONNECTION_INFO = "connection_info"
    NOTIFICATION = "notification"
    # Collaboration message types
    JOIN = "join"
    LEAVE = "leave"
    # Pipeline monitoring
    REQUEST_RESOURCE_UPDATE = "request_resource_update"


class WebSocketMessage(BaseModel):
    """WebSocket message structure."""
    type: MessageType
    channel: Optional[str] = None
    data: Optional[Any] = None
    timestamp: datetime = None
    message_id: Optional[str] = None
    correlation_id: Optional[str] = None
    
    def __init__(self, **data):
        if data.get('timestamp') is None:
            data['timestamp'] = datetime.utcnow()
        if data.get('message_id') is None:
            data['message_id'] = f"msg_{uuid.uuid4().hex[:12]}"
        super().__init__(**data)


class Connection:
    """WebSocket connection wrapper with metadata and state tracking."""
    
    def __init__(self, websocket: WebSocket, connection_id: str, user_id: Optional[str] = None):
        self.websocket = websocket
        self.connection_id = connection_id
        self.user_id = user_id
        self.state = ConnectionState.CONNECTING
        self.created_at = datetime.utcnow()
        self.last_ping = datetime.utcnow()
        self.last_activity = datetime.utcnow()
        self.subscriptions: Set[str] = set()
        self.metadata: Dict[str, Any] = {}
        self.message_count = 0
        self.bytes_sent = 0
        self.bytes_received = 0
        self.retry_count = 0
        self.max_retries = 3
        
        # Rate limiting
        self.message_history: deque = deque(maxlen=100)  # Track recent messages
        self.rate_limit_window = 60  # seconds
        self.max_messages_per_window = 100
    
    async def send_message(self, message: WebSocketMessage):
        """Send message to WebSocket with error handling."""
        try:
            if self.state != ConnectionState.CONNECTED:
                logger.warning(f"Attempted to send message to disconnected websocket {self.connection_id}")
                return False
            
            message_json = message.json()
            await self.websocket.send_text(message_json)
            
            self.last_activity = datetime.utcnow()
            self.message_count += 1
            self.bytes_sent += len(message_json.encode('utf-8'))
            
            logger.debug(f"Sent message to {self.connection_id}: {message.type}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to send message to {self.connection_id}: {str(e)}")
            self.state = ConnectionState.ERROR
            return False
    
    def is_rate_limited(self) -> bool:
        """Check if connection is rate limited."""
        cutoff_time = datetime.utcnow() - timedelta(seconds=self.rate_limit_window)
        recent_messages = [
            msg_time for msg_time in self.message_history
            if msg_time > cutoff_time
        ]
        
        return len(recent_messages) >= self.max_messages_per_window
    
    def record_message(self):
        """Record a message for rate limiting."""
        self.message_history.append(datetime.utcnow())
    
    def update_ping(self):
        """Update last ping time."""
        self.last_ping = datetime.utcnow()
    
    def is_stale(self, timeout_seconds: int = 300) -> bool:
        """Check if connection is stale (no activity for timeout period)."""
        return (datetime.utcnow() - self.last_activity).total_seconds() > timeout_seconds


class WebSocketPool:
    """Connection pool for managing WebSocket connections with scaling."""
    
    def __init__(
        self,
        max_connections_per_pool: int = 1000,
        cleanup_interval_seconds: int = 60,
        heartbeat_interval_seconds: int = 30,
        connection_timeout_seconds: int = 300,
        enable_redis_pubsub: bool = False,
        redis_url: Optional[str] = None
    ):
        self.max_connections_per_pool = max_connections_per_pool
        self.cleanup_interval_seconds = cleanup_interval_seconds
        self.heartbeat_interval_seconds = heartbeat_interval_seconds
        self.connection_timeout_seconds = connection_timeout_seconds
        self.enable_redis_pubsub = enable_redis_pubsub
        self.redis_url = redis_url
        
        # Connection storage
        self.connections: Dict[str, Connection] = {}
        self.connections_by_user: Dict[str, Set[str]] = defaultdict(set)
        self.connections_by_channel: Dict[str, Set[str]] = defaultdict(set)
        
        # Background tasks
        self.cleanup_task: Optional[asyncio.Task] = None
        self.heartbeat_task: Optional[asyncio.Task] = None
        self.pubsub_task: Optional[asyncio.Task] = None
        
        # Redis client for scaling
        self.redis_client: Optional[redis.Redis] = None
        
        # Statistics
        self.stats = {
            "total_connections": 0,
            "active_connections": 0,
            "messages_sent": 0,
            "messages_received": 0,
            "connections_created": 0,
            "connections_dropped": 0,
            "rate_limited_requests": 0
        }
        
        # Event handlers
        self.connection_handlers: List[Callable] = []
        self.disconnection_handlers: List[Callable] = []
        self.message_handlers: Dict[str, List[Callable]] = defaultdict(list)
        
        logger.info("WebSocket pool initialized")
    
    async def start(self):
        """Start the WebSocket pool and background tasks."""
        # Initialize Redis if enabled
        if self.enable_redis_pubsub and self.redis_url:
            try:
                self.redis_client = redis.from_url(self.redis_url, decode_responses=True)
                await self.redis_client.ping()
                logger.info("Redis client connected for WebSocket scaling")
                
                # Start pub/sub task
                self.pubsub_task = asyncio.create_task(self._redis_pubsub_handler())
                
            except Exception as e:
                logger.error(f"Failed to connect to Redis: {str(e)}")
                self.enable_redis_pubsub = False
        
        # Start background tasks
        self.cleanup_task = asyncio.create_task(self._cleanup_loop())
        self.heartbeat_task = asyncio.create_task(self._heartbeat_loop())
        
        logger.info("WebSocket pool started")
    
    async def stop(self):
        """Stop the WebSocket pool and cleanup."""
        # Cancel background tasks
        for task in [self.cleanup_task, self.heartbeat_task, self.pubsub_task]:
            if task:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
        
        # Close all connections
        for connection in list(self.connections.values()):
            await self.disconnect(connection.connection_id)
        
        # Close Redis connection
        if self.redis_client:
            await self.redis_client.close()
        
        logger.info("WebSocket pool stopped")
    
    async def add_connection(
        self, 
        websocket: WebSocket, 
        user_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None
    ) -> str:
        """Add a new WebSocket connection to the pool."""
        
        # Check pool capacity
        if len(self.connections) >= self.max_connections_per_pool:
            logger.warning("WebSocket pool at capacity, rejecting connection")
            await websocket.close(code=1008, reason="Pool at capacity")
            self.stats["connections_dropped"] += 1
            raise Exception("Connection pool at maximum capacity")
        
        # Generate connection ID
        connection_id = f"ws_{uuid.uuid4().hex[:12]}"
        
        # Create connection wrapper
        connection = Connection(websocket, connection_id, user_id)
        if metadata:
            connection.metadata.update(metadata)
        
        # Accept the WebSocket connection
        await websocket.accept()
        connection.state = ConnectionState.CONNECTED
        
        # Store connection
        self.connections[connection_id] = connection
        if user_id:
            self.connections_by_user[user_id].add(connection_id)
        
        # Update statistics
        self.stats["connections_created"] += 1
        self.stats["active_connections"] = len(self.connections)
        
        # Send connection info
        connection_info = WebSocketMessage(
            type=MessageType.CONNECTION_INFO,
            data={
                "connection_id": connection_id,
                "user_id": user_id,
                "server_time": datetime.utcnow().isoformat(),
                "heartbeat_interval": self.heartbeat_interval_seconds,
                "protocol_version": 1,
                "heartbeat_interval_ms": self.heartbeat_interval_seconds * 1000,
                "max_message_bytes": 1024 * 1024,
                "supports_resume": False,
            }
        )
        await connection.send_message(connection_info)
        
        # Notify handlers
        for handler in self.connection_handlers:
            try:
                if asyncio.iscoroutinefunction(handler):
                    await handler(connection)
                else:
                    handler(connection)
            except Exception as e:
                logger.error(f"Connection handler error: {str(e)}")
        
        logger.info(f"WebSocket connection established: {connection_id} (user: {user_id})")
        return connection_id
    
    async def disconnect(self, connection_id: str, reason: str = "Normal closure"):
        """Disconnect and cleanup a WebSocket connection."""
        if connection_id not in self.connections:
            return
        
        connection = self.connections[connection_id]
        connection.state = ConnectionState.DISCONNECTING
        
        try:
            # Unsubscribe from all channels
            for channel in list(connection.subscriptions):
                await self.unsubscribe(connection_id, channel)
            
            # Close WebSocket
            if not connection.websocket.client_state.name == 'DISCONNECTED':
                await connection.websocket.close(code=1000, reason=reason)
            
        except Exception as e:
            logger.error(f"Error during disconnect: {str(e)}")
        
        finally:
            # Cleanup connection references
            if connection.user_id and connection_id in self.connections_by_user.get(connection.user_id, set()):
                self.connections_by_user[connection.user_id].discard(connection_id)
                if not self.connections_by_user[connection.user_id]:
                    del self.connections_by_user[connection.user_id]
            
            # Remove from connections
            del self.connections[connection_id]
            connection.state = ConnectionState.DISCONNECTED
            
            # Update statistics
            self.stats["active_connections"] = len(self.connections)
            self.stats["connections_dropped"] += 1
            
            # Notify handlers
            for handler in self.disconnection_handlers:
                try:
                    if asyncio.iscoroutinefunction(handler):
                        await handler(connection)
                    else:
                        handler(connection)
                except Exception as e:
                    logger.error(f"Disconnection handler error: {str(e)}")
            
            logger.info(f"WebSocket connection closed: {connection_id} (reason: {reason})")
    
    async def subscribe(self, connection_id: str, channel: str):
        """Subscribe connection to a channel."""
        if connection_id not in self.connections:
            return False
        
        connection = self.connections[connection_id]
        connection.subscriptions.add(channel)
        self.connections_by_channel[channel].add(connection_id)
        
        logger.debug(f"Connection {connection_id} subscribed to channel {channel}")
        return True
    
    async def unsubscribe(self, connection_id: str, channel: str):
        """Unsubscribe connection from a channel."""
        if connection_id not in self.connections:
            return False
        
        connection = self.connections[connection_id]
        connection.subscriptions.discard(channel)
        self.connections_by_channel[channel].discard(connection_id)
        
        # Clean up empty channel sets
        if not self.connections_by_channel[channel]:
            del self.connections_by_channel[channel]
        
        logger.debug(f"Connection {connection_id} unsubscribed from channel {channel}")
        return True
    
    async def broadcast_to_channel(
        self, 
        channel: str, 
        message: WebSocketMessage,
        exclude_connections: Optional[Set[str]] = None
    ):
        """Broadcast message to all connections subscribed to a channel."""
        if channel not in self.connections_by_channel:
            logger.debug(f"No subscribers for channel {channel}")
            return 0
        
        exclude_connections = exclude_connections or set()
        target_connections = self.connections_by_channel[channel] - exclude_connections
        
        if not target_connections:
            return 0
        
        # Send to all subscribers
        success_count = 0
        failed_connections = []
        
        for connection_id in target_connections:
            if connection_id in self.connections:
                connection = self.connections[connection_id]
                if await connection.send_message(message):
                    success_count += 1
                else:
                    failed_connections.append(connection_id)
        
        # Cleanup failed connections
        for connection_id in failed_connections:
            await self.disconnect(connection_id, "Send message failed")
        
        # Publish to Redis for scaling
        if self.enable_redis_pubsub and self.redis_client:
            try:
                redis_message = {
                    "channel": channel,
                    "message": message.model_dump(),
                    "sender_pool": "orchestrator",
                    "timestamp": datetime.utcnow().isoformat()
                }
                await self.redis_client.publish(f"ws_broadcast:{channel}", json.dumps(redis_message))
            except Exception as e:
                logger.error(f"Failed to publish to Redis: {str(e)}")
        
        self.stats["messages_sent"] += success_count
        logger.debug(f"Broadcast to channel {channel}: {success_count} successful, {len(failed_connections)} failed")
        
        return success_count
    
    async def send_to_user(
        self, 
        user_id: str, 
        message: WebSocketMessage
    ) -> int:
        """Send message to all connections for a specific user."""
        if user_id not in self.connections_by_user:
            logger.debug(f"No connections for user {user_id}")
            return 0
        
        success_count = 0
        failed_connections = []
        
        for connection_id in list(self.connections_by_user[user_id]):
            if connection_id in self.connections:
                connection = self.connections[connection_id]
                if await connection.send_message(message):
                    success_count += 1
                else:
                    failed_connections.append(connection_id)
        
        # Cleanup failed connections
        for connection_id in failed_connections:
            await self.disconnect(connection_id, "Send message failed")
        
        self.stats["messages_sent"] += success_count
        return success_count
    
    async def send_to_connection(
        self, 
        connection_id: str, 
        message: WebSocketMessage
    ) -> bool:
        """Send message to a specific connection."""
        if connection_id not in self.connections:
            return False
        
        connection = self.connections[connection_id]
        success = await connection.send_message(message)
        
        if success:
            self.stats["messages_sent"] += 1
        else:
            await self.disconnect(connection_id, "Send message failed")
        
        return success
    
    async def handle_message(self, connection_id: str, message_data: str):
        """Handle incoming WebSocket message."""
        if connection_id not in self.connections:
            return
        
        connection = self.connections[connection_id]
        connection.record_message()
        connection.last_activity = datetime.utcnow()
        
        # Check rate limiting
        if connection.is_rate_limited():
            self.stats["rate_limited_requests"] += 1
            error_message = WebSocketMessage(
                type=MessageType.ERROR,
                data={"error": "Rate limit exceeded", "retry_after": connection.rate_limit_window}
            )
            await connection.send_message(error_message)
            return
        
        try:
            # Parse message
            message_dict = json.loads(message_data)
            message = WebSocketMessage(**message_dict)
            
            # Handle built-in message types
            if message.type == MessageType.PING:
                pong_message = WebSocketMessage(
                    type=MessageType.PONG,
                    correlation_id=message.message_id
                )
                await connection.send_message(pong_message)
                connection.update_ping()
                return
            
            elif message.type == MessageType.SUBSCRIBE and message.channel:
                await self.subscribe(connection_id, message.channel)
                return
            
            elif message.type == MessageType.UNSUBSCRIBE and message.channel:
                await self.unsubscribe(connection_id, message.channel)
                return
            
            # Handle custom message types
            message_type = message.type.value if isinstance(message.type, Enum) else message.type
            if message_type in self.message_handlers:
                for handler in self.message_handlers[message_type]:
                    try:
                        if asyncio.iscoroutinefunction(handler):
                            await handler(connection, message)
                        else:
                            handler(connection, message)
                    except Exception as e:
                        logger.error(f"Message handler error: {str(e)}")
            
            self.stats["messages_received"] += 1
            
        except json.JSONDecodeError:
            error_message = WebSocketMessage(
                type=MessageType.ERROR,
                data={"error": "Invalid JSON format"}
            )
            await connection.send_message(error_message)
            
        except Exception as e:
            logger.error(f"Error handling message from {connection_id}: {str(e)}")
            error_message = WebSocketMessage(
                type=MessageType.ERROR,
                data={"error": f"Message processing failed: {str(e)}"}
            )
            await connection.send_message(error_message)
    
    async def _cleanup_loop(self):
        """Background task to cleanup stale connections."""
        while True:
            try:
                await asyncio.sleep(self.cleanup_interval_seconds)
                
                stale_connections = []
                for connection_id, connection in self.connections.items():
                    if connection.is_stale(self.connection_timeout_seconds):
                        stale_connections.append(connection_id)
                
                for connection_id in stale_connections:
                    await self.disconnect(connection_id, "Connection timeout")
                
                if stale_connections:
                    logger.info(f"Cleaned up {len(stale_connections)} stale connections")
                
            except Exception as e:
                logger.error(f"Cleanup loop error: {str(e)}")
    
    async def _heartbeat_loop(self):
        """Background task to send heartbeats."""
        while True:
            try:
                await asyncio.sleep(self.heartbeat_interval_seconds)
                
                heartbeat_message = WebSocketMessage(
                    type=MessageType.HEARTBEAT,
                    data={
                        "timestamp": datetime.utcnow().isoformat(),
                        "active_connections": len(self.connections)
                    }
                )
                
                # Send heartbeat to all connections
                failed_connections = []
                for connection_id, connection in list(self.connections.items()):
                    if not await connection.send_message(heartbeat_message):
                        failed_connections.append(connection_id)
                
                # Cleanup failed connections
                for connection_id in failed_connections:
                    await self.disconnect(connection_id, "Heartbeat failed")
                
            except Exception as e:
                logger.error(f"Heartbeat loop error: {str(e)}")
    
    async def _redis_pubsub_handler(self):
        """Handle Redis pub/sub messages for scaling."""
        if not self.redis_client:
            return
        
        pubsub = self.redis_client.pubsub()
        await pubsub.subscribe("ws_broadcast:*")
        
        try:
            while True:
                message = await pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
                if message:
                    try:
                        data = json.loads(message["data"])
                        channel = data["channel"]
                        ws_message = WebSocketMessage(**data["message"])
                        
                        # Only process messages not from this pool
                        if data.get("sender_pool") != "orchestrator":
                            await self.broadcast_to_channel(channel, ws_message)
                        
                    except Exception as e:
                        logger.error(f"Redis pubsub message error: {str(e)}")
                
        except asyncio.CancelledError:
            pass
        finally:
            await pubsub.close()
    
    def add_connection_handler(self, handler: Callable):
        """Add connection event handler."""
        self.connection_handlers.append(handler)
    
    def add_disconnection_handler(self, handler: Callable):
        """Add disconnection event handler."""
        self.disconnection_handlers.append(handler)
    
    def add_message_handler(self, message_type: str, handler: Callable):
        """Add message type handler."""
        self.message_handlers[message_type].append(handler)
    
    def get_connection(self, connection_id: str) -> Optional[Connection]:
        """Get connection by ID."""
        return self.connections.get(connection_id)
    
    def get_user_connections(self, user_id: str) -> List[Connection]:
        """Get all connections for a user."""
        connection_ids = self.connections_by_user.get(user_id, set())
        return [
            self.connections[conn_id] 
            for conn_id in connection_ids 
            if conn_id in self.connections
        ]
    
    def get_channel_subscribers(self, channel: str) -> List[Connection]:
        """Get all connections subscribed to a channel."""
        connection_ids = self.connections_by_channel.get(channel, set())
        return [
            self.connections[conn_id] 
            for conn_id in connection_ids 
            if conn_id in self.connections
        ]
    
    def get_stats(self) -> Dict[str, Any]:
        """Get connection pool statistics."""
        return {
            **self.stats,
            "pool_capacity": self.max_connections_per_pool,
            "pool_utilization": len(self.connections) / self.max_connections_per_pool * 100,
            "channels": list(self.connections_by_channel.keys()),
            "users_connected": list(self.connections_by_user.keys())
        }


# Global WebSocket pool instance
websocket_pool = WebSocketPool()
