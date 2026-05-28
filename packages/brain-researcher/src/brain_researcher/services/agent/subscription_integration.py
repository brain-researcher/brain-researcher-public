"""Agent Subscription System Integration.

This module integrates the subscription system (KG-021) with the agent service
to provide real-time notifications and updates to agent conversations.
"""

import logging
import asyncio
import json
from typing import Dict, List, Any, Optional, Set, Callable
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum

from brain_researcher.services.neurokg.subscriptions.subscription_system import (
    SubscriptionSystem,
    Event,
    EventType,
    SubscriptionFilter
)

logger = logging.getLogger(__name__)


class AgentNotificationType(Enum):
    """Types of agent notifications."""
    
    ANALYSIS_COMPLETED = "analysis_completed"
    DATA_UPDATED = "data_updated"
    CURATION_STATUS_CHANGED = "curation_status_changed"
    GRAPH_CHANGED = "graph_changed"
    ERROR_OCCURRED = "error_occurred"


@dataclass
class AgentNotification:
    """Represents a notification to an agent conversation."""
    
    notification_id: str
    notification_type: AgentNotificationType
    thread_id: str
    title: str
    message: str
    data: Dict[str, Any]
    priority: int = 0  # 0=low, 1=medium, 2=high
    timestamp: datetime = field(default_factory=datetime.now)
    
    
class AgentSubscriptionManager:
    """Manages subscriptions for agent conversations."""
    
    def __init__(self, subscription_system: SubscriptionSystem, redis_client=None):
        """Initialize agent subscription manager.
        
        Args:
            subscription_system: Core subscription system
            redis_client: Optional Redis client for persistence
        """
        self.subscription_system = subscription_system
        self.redis = redis_client
        
        # Active agent subscriptions by thread_id
        self.agent_subscriptions: Dict[str, Set[str]] = {}
        
        # Notification handlers by thread_id
        self.notification_handlers: Dict[str, Callable] = {}
        
        # Notification queue for each thread
        self.notification_queues: Dict[str, asyncio.Queue] = {}
        
        # Statistics
        self.stats = {
            "subscriptions_created": 0,
            "notifications_sent": 0,
            "notifications_failed": 0,
            "active_threads": 0
        }
        
        # Register default event handlers
        self._register_event_handlers()
        
    async def subscribe_thread(
        self,
        thread_id: str,
        event_types: List[EventType],
        entity_types: Optional[List[str]] = None,
        filters: Optional[Dict[str, Any]] = None,
        notification_handler: Optional[Callable] = None
    ) -> str:
        """Subscribe an agent thread to events.
        
        Args:
            thread_id: Agent conversation thread ID
            event_types: Types of events to subscribe to
            entity_types: Entity types to filter on
            filters: Additional filters
            notification_handler: Custom notification handler
            
        Returns:
            Subscription ID
        """
        # Create subscription filter
        subscription_filter = SubscriptionFilter(
            event_types=event_types,
            entity_types=entity_types,
            metadata_filters=filters or {}
        )
        
        # Create subscription query (simplified GraphQL)
        query_parts = []
        for event_type in event_types:
            if event_type == EventType.ANALYSIS_COMPLETED:
                query_parts.append("analysisCompleted")
            elif event_type == EventType.NODE_CREATED:
                query_parts.append("nodeCreated")
            elif event_type == EventType.NODE_UPDATED:
                query_parts.append("nodeUpdated")
            elif event_type == EventType.GRAPH_CHANGED:
                query_parts.append("graphChanged")
                
        query = f"subscription {{ {', '.join(query_parts)} }}"
        
        # Mock connection for this agent thread
        mock_websocket = MockWebSocket(thread_id)
        
        # Connect and subscribe
        connection_id = await self.subscription_system.connect(
            mock_websocket,
            user_id=f"agent_{thread_id}",
            metadata={"thread_id": thread_id, "type": "agent"}
        )
        
        subscription_id = await self.subscription_system.subscribe(
            connection_id,
            query,
            variables={
                "entityTypes": entity_types,
                **filters
            } if entity_types or filters else None
        )
        
        # Track subscription
        if thread_id not in self.agent_subscriptions:
            self.agent_subscriptions[thread_id] = set()
        self.agent_subscriptions[thread_id].add(subscription_id)
        
        # Set up notification handler
        if notification_handler:
            self.notification_handlers[thread_id] = notification_handler
            
        # Initialize notification queue
        if thread_id not in self.notification_queues:
            self.notification_queues[thread_id] = asyncio.Queue()
            
        self.stats["subscriptions_created"] += 1
        self.stats["active_threads"] = len(self.agent_subscriptions)
        
        logger.info(f"Subscribed agent thread {thread_id} to {len(event_types)} event types")
        
        return subscription_id
        
    async def unsubscribe_thread(self, thread_id: str):
        """Unsubscribe an agent thread from all events.
        
        Args:
            thread_id: Agent conversation thread ID
        """
        if thread_id not in self.agent_subscriptions:
            return
            
        # Unsubscribe all subscriptions for this thread
        for subscription_id in self.agent_subscriptions[thread_id]:
            await self.subscription_system.unsubscribe(subscription_id)
            
        # Clean up
        del self.agent_subscriptions[thread_id]
        self.notification_handlers.pop(thread_id, None)
        self.notification_queues.pop(thread_id, None)
        
        self.stats["active_threads"] = len(self.agent_subscriptions)
        
        logger.info(f"Unsubscribed agent thread {thread_id} from all events")
        
    async def send_notification(
        self,
        thread_id: str,
        notification: AgentNotification
    ):
        """Send notification to an agent thread.
        
        Args:
            thread_id: Target thread ID
            notification: Notification to send
        """
        try:
            # Add to thread's notification queue
            if thread_id in self.notification_queues:
                await self.notification_queues[thread_id].put(notification)
                
            # Call custom handler if available
            if thread_id in self.notification_handlers:
                handler = self.notification_handlers[thread_id]
                await handler(notification)
                
            # Store in Redis for persistence
            if self.redis:
                key = f"agent:notifications:{thread_id}"
                notification_data = {
                    "notification_id": notification.notification_id,
                    "type": notification.notification_type.value,
                    "title": notification.title,
                    "message": notification.message,
                    "data": notification.data,
                    "priority": notification.priority,
                    "timestamp": notification.timestamp.isoformat()
                }
                
                await self.redis.lpush(key, json.dumps(notification_data))
                await self.redis.expire(key, 86400)  # 24 hour TTL
                
            self.stats["notifications_sent"] += 1
            
            logger.debug(f"Sent notification to thread {thread_id}: {notification.title}")
            
        except Exception as e:
            logger.error(f"Failed to send notification to thread {thread_id}: {e}", exc_info=True)
            self.stats["notifications_failed"] += 1
            
    async def get_notifications(
        self,
        thread_id: str,
        limit: int = 10
    ) -> List[AgentNotification]:
        """Get recent notifications for a thread.
        
        Args:
            thread_id: Thread ID
            limit: Maximum notifications to return
            
        Returns:
            List of recent notifications
        """
        notifications = []
        
        # Get from Redis if available
        if self.redis:
            key = f"agent:notifications:{thread_id}"
            raw_notifications = await self.redis.lrange(key, 0, limit - 1)
            
            for raw in raw_notifications:
                try:
                    data = json.loads(raw)
                    notification = AgentNotification(
                        notification_id=data["notification_id"],
                        notification_type=AgentNotificationType(data["type"]),
                        thread_id=thread_id,
                        title=data["title"],
                        message=data["message"],
                        data=data["data"],
                        priority=data["priority"],
                        timestamp=datetime.fromisoformat(data["timestamp"])
                    )
                    notifications.append(notification)
                except Exception as e:
                    logger.error(f"Error parsing notification: {e}")
                    
        return notifications
        
    def _register_event_handlers(self):
        """Register handlers for subscription system events."""
        # Register handler for analysis completion events
        self.subscription_system.register_handler(
            "analysisCompleted",
            self._handle_analysis_completed
        )
        
        # Register handler for node events
        self.subscription_system.register_handler(
            "nodeCreated",
            self._handle_node_event
        )
        
        self.subscription_system.register_handler(
            "nodeUpdated",
            self._handle_node_event
        )
        
    async def _handle_analysis_completed(self, subscription):
        """Handle analysis completed events."""
        # This would be called when an analysis completes
        # For now, create a mock notification
        for thread_id in self.agent_subscriptions:
            notification = AgentNotification(
                notification_id=f"analysis_{datetime.now().timestamp()}",
                notification_type=AgentNotificationType.ANALYSIS_COMPLETED,
                thread_id=thread_id,
                title="Analysis Completed",
                message="Your requested analysis has been completed.",
                data={"analysis_id": "mock_analysis"},
                priority=1
            )
            
            await self.send_notification(thread_id, notification)
            
    async def _handle_node_event(self, subscription):
        """Handle node creation/update events."""
        # This would be called when nodes are created/updated
        for thread_id in self.agent_subscriptions:
            notification = AgentNotification(
                notification_id=f"node_{datetime.now().timestamp()}",
                notification_type=AgentNotificationType.DATA_UPDATED,
                thread_id=thread_id,
                title="Knowledge Graph Updated",
                message="New data has been added to the knowledge graph.",
                data={"event_type": "node_created"},
                priority=0
            )
            
            await self.send_notification(thread_id, notification)
            
    async def notify_analysis_started(
        self,
        thread_id: str,
        analysis_id: str,
        analysis_type: str
    ):
        """Notify that an analysis has started.
        
        Args:
            thread_id: Thread ID
            analysis_id: Analysis identifier
            analysis_type: Type of analysis
        """
        notification = AgentNotification(
            notification_id=f"start_{analysis_id}",
            notification_type=AgentNotificationType.ANALYSIS_COMPLETED,
            thread_id=thread_id,
            title=f"Analysis Started: {analysis_type}",
            message=f"Your {analysis_type} analysis has started and is being processed.",
            data={
                "analysis_id": analysis_id,
                "analysis_type": analysis_type,
                "status": "started"
            },
            priority=1
        )
        
        await self.send_notification(thread_id, notification)
        
    async def notify_analysis_completed(
        self,
        thread_id: str,
        analysis_id: str,
        analysis_type: str,
        results: Dict[str, Any]
    ):
        """Notify that an analysis has completed.
        
        Args:
            thread_id: Thread ID
            analysis_id: Analysis identifier
            analysis_type: Type of analysis
            results: Analysis results
        """
        notification = AgentNotification(
            notification_id=f"complete_{analysis_id}",
            notification_type=AgentNotificationType.ANALYSIS_COMPLETED,
            thread_id=thread_id,
            title=f"Analysis Completed: {analysis_type}",
            message=f"Your {analysis_type} analysis has completed successfully.",
            data={
                "analysis_id": analysis_id,
                "analysis_type": analysis_type,
                "status": "completed",
                "results": results
            },
            priority=2
        )
        
        await self.send_notification(thread_id, notification)
        
    async def notify_error(
        self,
        thread_id: str,
        error_id: str,
        error_message: str,
        error_context: Dict[str, Any]
    ):
        """Notify about an error.
        
        Args:
            thread_id: Thread ID
            error_id: Error identifier
            error_message: Error message
            error_context: Error context
        """
        notification = AgentNotification(
            notification_id=f"error_{error_id}",
            notification_type=AgentNotificationType.ERROR_OCCURRED,
            thread_id=thread_id,
            title="Error Occurred",
            message=error_message,
            data={"error_context": error_context},
            priority=2
        )
        
        await self.send_notification(thread_id, notification)
        
    def get_statistics(self) -> Dict[str, Any]:
        """Get subscription manager statistics."""
        return {
            "subscriptions_created": self.stats["subscriptions_created"],
            "notifications_sent": self.stats["notifications_sent"],
            "notifications_failed": self.stats["notifications_failed"],
            "active_threads": self.stats["active_threads"],
            "total_subscriptions": sum(
                len(subs) for subs in self.agent_subscriptions.values()
            )
        }


class MockWebSocket:
    """Mock WebSocket for agent subscriptions."""
    
    def __init__(self, thread_id: str):
        self.thread_id = thread_id
        self.closed = False
        
    async def send(self, message: str):
        """Mock send - logs message for debugging."""
        logger.debug(f"Mock WebSocket for {self.thread_id} would send: {message}")
        
    async def close(self):
        """Mock close."""
        self.closed = True
        logger.debug(f"Mock WebSocket for {self.thread_id} closed")


# Integration helper functions
async def setup_agent_subscriptions(
    agent_state_machine,
    subscription_system: SubscriptionSystem,
    redis_client=None
) -> AgentSubscriptionManager:
    """Set up agent subscription integration.
    
    Args:
        agent_state_machine: Core agent state machine
        subscription_system: Subscription system instance
        redis_client: Optional Redis client
        
    Returns:
        Agent subscription manager
    """
    manager = AgentSubscriptionManager(subscription_system, redis_client)
    
    # Add subscription manager to state machine
    agent_state_machine.subscription_manager = manager
    
    # Subscribe to common events
    common_events = [
        EventType.ANALYSIS_COMPLETED,
        EventType.CURATION_STATUS_CHANGED,
        EventType.GRAPH_CHANGED
    ]
    
    logger.info("Agent subscription integration setup completed")
    
    return manager


async def subscribe_agent_to_analysis_events(
    subscription_manager: AgentSubscriptionManager,
    thread_id: str
):
    """Subscribe an agent thread to analysis events.
    
    Args:
        subscription_manager: Subscription manager
        thread_id: Thread ID to subscribe
    """
    await subscription_manager.subscribe_thread(
        thread_id,
        [EventType.ANALYSIS_COMPLETED],
        entity_types=["analysis", "result"],
        filters={"status": "completed"}
    )
    
    logger.info(f"Subscribed thread {thread_id} to analysis events")