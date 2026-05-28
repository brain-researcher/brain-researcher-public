"""WebSocket-based subscription system for real-time graph updates."""

import asyncio
import json
import logging
from datetime import datetime
from typing import Dict, List, Set, Any, Optional, Callable
from enum import Enum
import uuid
from fastapi import WebSocket, WebSocketDisconnect, APIRouter
from pydantic import BaseModel, Field
import redis.asyncio as redis

logger = logging.getLogger(__name__)

router = APIRouter()


class EventType(str, Enum):
    """Types of graph events."""
    NODE_CREATED = "node_created"
    NODE_UPDATED = "node_updated"
    NODE_DELETED = "node_deleted"
    EDGE_CREATED = "edge_created"
    EDGE_UPDATED = "edge_updated"
    EDGE_DELETED = "edge_deleted"
    QUERY_RESULT = "query_result"
    SUBSCRIPTION_CONFIRMED = "subscription_confirmed"
    ERROR = "error"


class SubscriptionFilter(BaseModel):
    """Filter criteria for subscriptions."""
    event_types: Optional[List[EventType]] = Field(default=None)
    node_types: Optional[List[str]] = Field(default=None)
    edge_types: Optional[List[str]] = Field(default=None)
    node_ids: Optional[List[str]] = Field(default=None)
    properties: Optional[Dict[str, Any]] = Field(default=None)


class GraphEvent(BaseModel):
    """Graph change event."""
    event_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    event_type: EventType
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    data: Dict[str, Any]
    metadata: Optional[Dict[str, Any]] = None


class Subscription:
    """Represents a client subscription."""
    
    def __init__(self,
                subscription_id: str,
                client_id: str,
                filter: SubscriptionFilter,
                callback: Optional[Callable] = None):
        """Initialize subscription.
        
        Args:
            subscription_id: Unique subscription ID
            client_id: Client identifier
            filter: Subscription filter
            callback: Optional callback function
        """
        self.subscription_id = subscription_id
        self.client_id = client_id
        self.filter = filter
        self.callback = callback
        self.created_at = datetime.utcnow()
        self.event_count = 0
    
    def matches_event(self, event: GraphEvent) -> bool:
        """Check if event matches subscription filter.
        
        Args:
            event: Graph event
            
        Returns:
            True if event matches filter
        """
        # Check event type
        if self.filter.event_types:
            if event.event_type not in self.filter.event_types:
                return False
        
        # Check node type
        if self.filter.node_types:
            node_type = event.data.get('node_type') or event.data.get('type')
            if node_type not in self.filter.node_types:
                return False
        
        # Check edge type
        if self.filter.edge_types:
            edge_type = event.data.get('edge_type') or event.data.get('type')
            if edge_type not in self.filter.edge_types:
                return False
        
        # Check node IDs
        if self.filter.node_ids:
            node_id = event.data.get('node_id') or event.data.get('id')
            if node_id not in self.filter.node_ids:
                return False
        
        # Check properties
        if self.filter.properties:
            event_props = event.data.get('properties', {})
            for key, value in self.filter.properties.items():
                if event_props.get(key) != value:
                    return False
        
        return True


class ConnectionManager:
    """Manages WebSocket connections and subscriptions."""
    
    def __init__(self):
        """Initialize connection manager."""
        self.active_connections: Dict[str, WebSocket] = {}
        self.subscriptions: Dict[str, Subscription] = {}
        self.client_subscriptions: Dict[str, Set[str]] = {}  # client_id -> subscription_ids
        self.redis_client: Optional[redis.Redis] = None
        self.pubsub: Optional[redis.client.PubSub] = None
        self.event_queue: asyncio.Queue = asyncio.Queue()
        self.background_tasks: List[asyncio.Task] = []
    
    async def initialize(self, redis_url: str = "redis://localhost:6379"):
        """Initialize Redis connection for pub/sub.
        
        Args:
            redis_url: Redis connection URL
        """
        try:
            self.redis_client = redis.from_url(redis_url)
            self.pubsub = self.redis_client.pubsub()
            await self.pubsub.subscribe("graph_events")
            
            # Start background tasks
            self.background_tasks.append(
                asyncio.create_task(self._process_redis_events())
            )
            self.background_tasks.append(
                asyncio.create_task(self._process_event_queue())
            )
            
            logger.info("Connection manager initialized with Redis")
        except Exception as e:
            logger.warning(f"Redis initialization failed: {e}. Running in-memory mode.")
    
    async def connect(self, websocket: WebSocket, client_id: str):
        """Accept WebSocket connection.
        
        Args:
            websocket: WebSocket connection
            client_id: Client identifier
        """
        await websocket.accept()
        self.active_connections[client_id] = websocket
        self.client_subscriptions[client_id] = set()
        
        # Send connection confirmation
        await self.send_to_client(client_id, {
            "type": "connection_established",
            "client_id": client_id,
            "timestamp": datetime.utcnow().isoformat()
        })
        
        logger.info(f"Client {client_id} connected")
    
    async def disconnect(self, client_id: str):
        """Handle client disconnection.
        
        Args:
            client_id: Client identifier
        """
        # Remove subscriptions
        if client_id in self.client_subscriptions:
            for sub_id in self.client_subscriptions[client_id]:
                if sub_id in self.subscriptions:
                    del self.subscriptions[sub_id]
            del self.client_subscriptions[client_id]
        
        # Remove connection
        if client_id in self.active_connections:
            del self.active_connections[client_id]
        
        logger.info(f"Client {client_id} disconnected")
    
    async def subscribe(self,
                       client_id: str,
                       filter: SubscriptionFilter) -> str:
        """Create subscription for client.
        
        Args:
            client_id: Client identifier
            filter: Subscription filter
            
        Returns:
            Subscription ID
        """
        subscription_id = str(uuid.uuid4())
        
        subscription = Subscription(
            subscription_id=subscription_id,
            client_id=client_id,
            filter=filter
        )
        
        self.subscriptions[subscription_id] = subscription
        
        if client_id not in self.client_subscriptions:
            self.client_subscriptions[client_id] = set()
        self.client_subscriptions[client_id].add(subscription_id)
        
        # Send confirmation
        await self.send_to_client(client_id, {
            "type": EventType.SUBSCRIPTION_CONFIRMED.value,
            "subscription_id": subscription_id,
            "filter": filter.dict()
        })
        
        logger.info(f"Created subscription {subscription_id} for client {client_id}")
        return subscription_id
    
    async def unsubscribe(self, client_id: str, subscription_id: str):
        """Remove subscription.
        
        Args:
            client_id: Client identifier
            subscription_id: Subscription to remove
        """
        if subscription_id in self.subscriptions:
            del self.subscriptions[subscription_id]
        
        if client_id in self.client_subscriptions:
            self.client_subscriptions[client_id].discard(subscription_id)
        
        logger.info(f"Removed subscription {subscription_id}")
    
    async def publish_event(self, event: GraphEvent):
        """Publish event to subscribers.
        
        Args:
            event: Graph event to publish
        """
        # Add to queue for processing
        await self.event_queue.put(event)
        
        # Also publish to Redis if available
        if self.redis_client:
            await self.redis_client.publish(
                "graph_events",
                event.json()
            )
    
    async def _process_event_queue(self):
        """Process events from queue."""
        while True:
            try:
                event = await self.event_queue.get()
                await self._distribute_event(event)
            except Exception as e:
                logger.error(f"Error processing event: {e}")
            await asyncio.sleep(0.01)
    
    async def _process_redis_events(self):
        """Process events from Redis pub/sub."""
        if not self.pubsub:
            return
        
        while True:
            try:
                message = await self.pubsub.get_message(ignore_subscribe_messages=True)
                if message:
                    event_data = json.loads(message['data'])
                    event = GraphEvent(**event_data)
                    await self._distribute_event(event)
            except Exception as e:
                logger.error(f"Error processing Redis event: {e}")
            await asyncio.sleep(0.01)
    
    async def _distribute_event(self, event: GraphEvent):
        """Distribute event to matching subscribers.
        
        Args:
            event: Event to distribute
        """
        for subscription in self.subscriptions.values():
            if subscription.matches_event(event):
                subscription.event_count += 1
                
                # Send to client
                await self.send_to_client(
                    subscription.client_id,
                    {
                        "subscription_id": subscription.subscription_id,
                        "event": event.dict()
                    }
                )
                
                # Call callback if exists
                if subscription.callback:
                    try:
                        await subscription.callback(event)
                    except Exception as e:
                        logger.error(f"Callback error: {e}")
    
    async def send_to_client(self, client_id: str, data: Dict[str, Any]):
        """Send data to specific client.
        
        Args:
            client_id: Client identifier
            data: Data to send
        """
        if client_id in self.active_connections:
            websocket = self.active_connections[client_id]
            try:
                await websocket.send_json(data)
            except Exception as e:
                logger.error(f"Error sending to client {client_id}: {e}")
                await self.disconnect(client_id)
    
    async def broadcast(self, data: Dict[str, Any]):
        """Broadcast to all connected clients.
        
        Args:
            data: Data to broadcast
        """
        disconnected = []
        
        for client_id, websocket in self.active_connections.items():
            try:
                await websocket.send_json(data)
            except Exception:
                disconnected.append(client_id)
        
        # Clean up disconnected clients
        for client_id in disconnected:
            await self.disconnect(client_id)
    
    def get_statistics(self) -> Dict[str, Any]:
        """Get connection and subscription statistics.
        
        Returns:
            Statistics dictionary
        """
        event_counts = {}
        for sub in self.subscriptions.values():
            if sub.client_id not in event_counts:
                event_counts[sub.client_id] = 0
            event_counts[sub.client_id] += sub.event_count
        
        return {
            "active_connections": len(self.active_connections),
            "total_subscriptions": len(self.subscriptions),
            "clients": list(self.active_connections.keys()),
            "event_counts": event_counts,
            "queue_size": self.event_queue.qsize()
        }
    
    async def cleanup(self):
        """Clean up resources."""
        # Cancel background tasks
        for task in self.background_tasks:
            task.cancel()
        
        # Close Redis connection
        if self.redis_client:
            await self.redis_client.close()
        
        # Disconnect all clients
        for client_id in list(self.active_connections.keys()):
            await self.disconnect(client_id)


# Global connection manager
manager = ConnectionManager()


@router.websocket("/ws/{client_id}")
async def websocket_endpoint(websocket: WebSocket, client_id: str):
    """WebSocket endpoint for subscriptions.
    
    Args:
        websocket: WebSocket connection
        client_id: Client identifier
    """
    await manager.connect(websocket, client_id)
    
    try:
        while True:
            # Receive message from client
            data = await websocket.receive_json()
            
            if data.get("action") == "subscribe":
                filter_data = data.get("filter", {})
                filter = SubscriptionFilter(**filter_data)
                await manager.subscribe(client_id, filter)
            
            elif data.get("action") == "unsubscribe":
                subscription_id = data.get("subscription_id")
                if subscription_id:
                    await manager.unsubscribe(client_id, subscription_id)
            
            elif data.get("action") == "ping":
                await manager.send_to_client(client_id, {"type": "pong"})
    
    except WebSocketDisconnect:
        await manager.disconnect(client_id)
    except Exception as e:
        logger.error(f"WebSocket error for client {client_id}: {e}")
        await manager.disconnect(client_id)


@router.get("/subscriptions/stats")
async def get_subscription_stats():
    """Get subscription statistics."""
    return manager.get_statistics()


@router.on_event("startup")
async def startup_event():
    """Initialize manager on startup."""
    await manager.initialize()


@router.on_event("shutdown")
async def shutdown_event():
    """Cleanup on shutdown."""
    await manager.cleanup()
