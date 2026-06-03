"""Agent Notification System.

This module provides a comprehensive notification system for agent interactions,
integrating with all the new infrastructure components.
"""

import json
import logging
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Any

from brain_researcher.services.agent.error_integration import (
    IntegrationErrorManager,
)
from brain_researcher.services.agent.subscription_integration import (
    AgentNotification,
    AgentNotificationType,
    AgentSubscriptionManager,
)

logger = logging.getLogger(__name__)


class NotificationChannel(Enum):
    """Notification delivery channels."""

    IN_CHAT = "in_chat"  # Show in conversation
    POPUP = "popup"  # Browser popup/modal
    EMAIL = "email"  # Email notification
    WEBSOCKET = "websocket"  # Real-time WebSocket
    PUSH = "push"  # Push notification
    LOG = "log"  # Log file only


class NotificationPriority(Enum):
    """Notification priority levels."""

    LOW = 0
    MEDIUM = 1
    HIGH = 2
    CRITICAL = 3


@dataclass
class NotificationTemplate:
    """Template for generating notifications."""

    template_id: str
    name: str
    title_template: str
    message_template: str
    default_channels: list[NotificationChannel]
    default_priority: NotificationPriority
    variables: list[str] = field(default_factory=list)
    conditions: dict[str, Any] = field(default_factory=dict)


@dataclass
class NotificationPreference:
    """User notification preferences."""

    user_id: str
    enabled_channels: set[NotificationChannel]
    priority_threshold: NotificationPriority
    quiet_hours: dict[str, str] | None = None  # {"start": "22:00", "end": "08:00"}
    thread_specific: dict[str, dict[str, Any]] = field(default_factory=dict)


class AgentNotificationSystem:
    """Comprehensive notification system for agent interactions."""

    def __init__(
        self,
        subscription_manager: AgentSubscriptionManager | None = None,
        error_manager: IntegrationErrorManager | None = None,
        redis_client=None,
    ):
        """Initialize notification system.

        Args:
            subscription_manager: Subscription manager for real-time updates
            error_manager: Error manager for error notifications
            redis_client: Optional Redis client for persistence
        """
        self.subscription_manager = subscription_manager
        self.error_manager = error_manager
        self.redis = redis_client

        # Notification templates
        self.templates: dict[str, NotificationTemplate] = {}
        self._register_default_templates()

        # User preferences
        self.preferences: dict[str, NotificationPreference] = {}

        # Delivery handlers
        self.delivery_handlers: dict[NotificationChannel, Callable] = {}
        self._register_default_handlers()

        # Statistics
        self.stats = {
            "notifications_sent": 0,
            "notifications_failed": 0,
            "by_channel": {channel.value: 0 for channel in NotificationChannel},
            "by_priority": {priority.value: 0 for priority in NotificationPriority},
            "by_template": {},
        }

        # Rate limiting
        self.rate_limits: dict[str, dict[str, Any]] = {}
        self.rate_limit_window = 300  # 5 minutes
        self.rate_limit_max = 10  # Max notifications per window

    def _register_default_templates(self):
        """Register default notification templates."""
        templates = [
            NotificationTemplate(
                template_id="analysis_started",
                name="Analysis Started",
                title_template="Analysis Started: {analysis_type}",
                message_template="Your {analysis_type} analysis has started and is being processed.",
                default_channels=[
                    NotificationChannel.IN_CHAT,
                    NotificationChannel.WEBSOCKET,
                ],
                default_priority=NotificationPriority.MEDIUM,
                variables=["analysis_type", "analysis_id"],
            ),
            NotificationTemplate(
                template_id="analysis_completed",
                name="Analysis Completed",
                title_template="Analysis Completed: {analysis_type}",
                message_template="Your {analysis_type} analysis has completed successfully. {result_summary}",
                default_channels=[
                    NotificationChannel.IN_CHAT,
                    NotificationChannel.POPUP,
                    NotificationChannel.WEBSOCKET,
                ],
                default_priority=NotificationPriority.HIGH,
                variables=["analysis_type", "analysis_id", "result_summary"],
            ),
            NotificationTemplate(
                template_id="analysis_failed",
                name="Analysis Failed",
                title_template="Analysis Failed: {analysis_type}",
                message_template="Your {analysis_type} analysis failed: {error_message}. Please check the logs for details.",
                default_channels=[
                    NotificationChannel.IN_CHAT,
                    NotificationChannel.POPUP,
                    NotificationChannel.EMAIL,
                ],
                default_priority=NotificationPriority.HIGH,
                variables=["analysis_type", "analysis_id", "error_message"],
            ),
            NotificationTemplate(
                template_id="data_updated",
                name="Data Updated",
                title_template="Knowledge Graph Updated",
                message_template="New data has been added to the knowledge graph: {update_summary}",
                default_channels=[
                    NotificationChannel.IN_CHAT,
                    NotificationChannel.WEBSOCKET,
                ],
                default_priority=NotificationPriority.LOW,
                variables=["update_summary", "entity_count"],
            ),
            NotificationTemplate(
                template_id="system_error",
                name="System Error",
                title_template="System Error Occurred",
                message_template="A system error occurred in {component}: {error_message}",
                default_channels=[
                    NotificationChannel.POPUP,
                    NotificationChannel.EMAIL,
                    NotificationChannel.LOG,
                ],
                default_priority=NotificationPriority.CRITICAL,
                variables=["component", "error_message", "error_id"],
            ),
            NotificationTemplate(
                template_id="tool_execution",
                name="Tool Execution",
                title_template="Tool Executed: {tool_name}",
                message_template="Tool {tool_name} completed execution. {result_summary}",
                default_channels=[
                    NotificationChannel.IN_CHAT,
                    NotificationChannel.WEBSOCKET,
                ],
                default_priority=NotificationPriority.MEDIUM,
                variables=["tool_name", "result_summary", "execution_time"],
            ),
            NotificationTemplate(
                template_id="plugin_loaded",
                name="Plugin Loaded",
                title_template="Plugin Loaded: {plugin_name}",
                message_template="Data source plugin {plugin_name} has been loaded and is available for use.",
                default_channels=[NotificationChannel.IN_CHAT],
                default_priority=NotificationPriority.LOW,
                variables=["plugin_name", "plugin_type"],
            ),
            NotificationTemplate(
                template_id="duplicate_found",
                name="Duplicates Found",
                title_template="Duplicate Data Found",
                message_template="Found {duplicate_count} potential duplicates in {data_type} data. Review suggested.",
                default_channels=[
                    NotificationChannel.IN_CHAT,
                    NotificationChannel.WEBSOCKET,
                ],
                default_priority=NotificationPriority.MEDIUM,
                variables=["duplicate_count", "data_type", "similarity_score"],
            ),
        ]

        for template in templates:
            self.templates[template.template_id] = template

        logger.info(f"Registered {len(templates)} default notification templates")

    def _register_default_handlers(self):
        """Register default delivery handlers."""
        self.delivery_handlers = {
            NotificationChannel.IN_CHAT: self._deliver_in_chat,
            NotificationChannel.WEBSOCKET: self._deliver_websocket,
            NotificationChannel.LOG: self._deliver_log,
            NotificationChannel.POPUP: self._deliver_popup,
            NotificationChannel.EMAIL: self._deliver_email,
            NotificationChannel.PUSH: self._deliver_push,
        }

    async def send_notification(
        self,
        template_id: str,
        thread_id: str,
        variables: dict[str, Any],
        user_id: str | None = None,
        channels: list[NotificationChannel] | None = None,
        priority: NotificationPriority | None = None,
    ) -> bool:
        """Send a notification using a template.

        Args:
            template_id: Template ID
            thread_id: Target thread ID
            variables: Template variables
            user_id: Optional user ID
            channels: Optional custom channels
            priority: Optional custom priority

        Returns:
            Success status
        """
        try:
            # Get template
            template = self.templates.get(template_id)
            if not template:
                logger.error(f"Template {template_id} not found")
                return False

            # Check rate limiting
            if not self._check_rate_limit(user_id or thread_id, template_id):
                logger.warning(f"Rate limit exceeded for {template_id}")
                return False

            # Get user preferences
            preferences = self._get_user_preferences(user_id)

            # Determine channels and priority
            final_channels = channels or template.default_channels
            final_priority = priority or template.default_priority

            # Filter channels by preferences
            if preferences:
                final_channels = [
                    ch
                    for ch in final_channels
                    if ch in preferences.enabled_channels
                    and final_priority.value >= preferences.priority_threshold.value
                ]

            # Check quiet hours
            if preferences and self._in_quiet_hours(preferences):
                # Only allow critical notifications during quiet hours
                if final_priority != NotificationPriority.CRITICAL:
                    logger.info(
                        f"Skipping notification during quiet hours: {template_id}"
                    )
                    return True

            # Generate notification content
            title = self._render_template(template.title_template, variables)
            message = self._render_template(template.message_template, variables)

            # Create notification
            notification = AgentNotification(
                notification_id=str(uuid.uuid4()),
                notification_type=self._map_template_to_type(template_id),
                thread_id=thread_id,
                title=title,
                message=message,
                data={
                    "template_id": template_id,
                    "variables": variables,
                    "channels": [ch.value for ch in final_channels],
                    "priority": final_priority.value,
                },
                priority=final_priority.value,
            )

            # Deliver through each channel
            success = True
            for channel in final_channels:
                try:
                    await self._deliver_notification(notification, channel)
                    self.stats["by_channel"][channel.value] += 1
                except Exception as e:
                    logger.error(
                        f"Failed to deliver notification via {channel.value}: {e}"
                    )
                    success = False

            # Update statistics
            if success:
                self.stats["notifications_sent"] += 1
            else:
                self.stats["notifications_failed"] += 1

            self.stats["by_priority"][final_priority.value] += 1
            self.stats["by_template"][template_id] = (
                self.stats["by_template"].get(template_id, 0) + 1
            )

            # Update rate limit
            self._update_rate_limit(user_id or thread_id, template_id)

            logger.debug(f"Sent notification {template_id} to thread {thread_id}")
            return success

        except Exception as e:
            logger.error(
                f"Error sending notification {template_id}: {e}", exc_info=True
            )
            self.stats["notifications_failed"] += 1
            return False

    def _render_template(self, template: str, variables: dict[str, Any]) -> str:
        """Render a template with variables."""
        try:
            return template.format(**variables)
        except KeyError as e:
            logger.warning(f"Missing template variable: {e}")
            return template
        except Exception as e:
            logger.error(f"Error rendering template: {e}")
            return template

    def _map_template_to_type(self, template_id: str) -> AgentNotificationType:
        """Map template ID to notification type."""
        mapping = {
            "analysis_started": AgentNotificationType.ANALYSIS_COMPLETED,
            "analysis_completed": AgentNotificationType.ANALYSIS_COMPLETED,
            "analysis_failed": AgentNotificationType.ERROR_OCCURRED,
            "data_updated": AgentNotificationType.DATA_UPDATED,
            "system_error": AgentNotificationType.ERROR_OCCURRED,
            "tool_execution": AgentNotificationType.ANALYSIS_COMPLETED,
            "plugin_loaded": AgentNotificationType.DATA_UPDATED,
            "duplicate_found": AgentNotificationType.DATA_UPDATED,
        }

        return mapping.get(template_id, AgentNotificationType.DATA_UPDATED)

    async def _deliver_notification(
        self, notification: AgentNotification, channel: NotificationChannel
    ):
        """Deliver notification through a specific channel."""
        handler = self.delivery_handlers.get(channel)
        if handler:
            await handler(notification)
        else:
            logger.warning(f"No handler for channel {channel.value}")

    async def _deliver_in_chat(self, notification: AgentNotification):
        """Deliver notification in chat conversation."""
        if self.subscription_manager:
            await self.subscription_manager.send_notification(
                notification.thread_id, notification
            )
        else:
            logger.debug(f"Would show in chat: {notification.title}")

    async def _deliver_websocket(self, notification: AgentNotification):
        """Deliver notification via WebSocket."""
        # Integration with subscription system WebSocket
        if self.subscription_manager:
            # The subscription manager handles WebSocket delivery
            await self.subscription_manager.send_notification(
                notification.thread_id, notification
            )
        else:
            logger.debug(f"Would send via WebSocket: {notification.title}")

    async def _deliver_log(self, notification: AgentNotification):
        """Deliver notification to log file."""
        logger.info(
            f"NOTIFICATION [{notification.priority}] {notification.title}: {notification.message}"
        )

    async def _deliver_popup(self, notification: AgentNotification):
        """Deliver popup notification."""
        # This would integrate with frontend to show popup
        logger.debug(f"Would show popup: {notification.title}")

    async def _deliver_email(self, notification: AgentNotification):
        """Deliver email notification."""
        # This would integrate with email service
        logger.debug(f"Would send email: {notification.title}")

    async def _deliver_push(self, notification: AgentNotification):
        """Deliver push notification."""
        # This would integrate with push notification service
        logger.debug(f"Would send push notification: {notification.title}")

    def _get_user_preferences(
        self, user_id: str | None
    ) -> NotificationPreference | None:
        """Get user notification preferences."""
        if user_id:
            return self.preferences.get(user_id)
        return None

    def _in_quiet_hours(self, preferences: NotificationPreference) -> bool:
        """Check if current time is in user's quiet hours."""
        if not preferences.quiet_hours:
            return False

        try:

            now = datetime.now().time()
            start = datetime.strptime(preferences.quiet_hours["start"], "%H:%M").time()
            end = datetime.strptime(preferences.quiet_hours["end"], "%H:%M").time()

            if start <= end:
                return start <= now <= end
            else:  # Overnight quiet hours
                return now >= start or now <= end
        except Exception:
            return False

    def _check_rate_limit(self, identifier: str, template_id: str) -> bool:
        """Check if notification is within rate limit."""
        key = f"{identifier}:{template_id}"

        if key not in self.rate_limits:
            return True

        limit_data = self.rate_limits[key]
        window_start = limit_data["window_start"]
        count = limit_data["count"]

        # Check if we're in a new window
        if datetime.now() - window_start > timedelta(seconds=self.rate_limit_window):
            return True

        return count < self.rate_limit_max

    def _update_rate_limit(self, identifier: str, template_id: str):
        """Update rate limit counter."""
        key = f"{identifier}:{template_id}"
        now = datetime.now()

        if key not in self.rate_limits:
            self.rate_limits[key] = {"window_start": now, "count": 1}
        else:
            limit_data = self.rate_limits[key]

            # Check if we're in a new window
            if now - limit_data["window_start"] > timedelta(
                seconds=self.rate_limit_window
            ):
                limit_data["window_start"] = now
                limit_data["count"] = 1
            else:
                limit_data["count"] += 1

    async def set_user_preferences(
        self, user_id: str, preferences: NotificationPreference
    ):
        """Set user notification preferences."""
        self.preferences[user_id] = preferences

        # Store in Redis if available
        if self.redis:
            try:
                key = f"agent:notification_prefs:{user_id}"
                prefs_data = {
                    "user_id": preferences.user_id,
                    "enabled_channels": [
                        ch.value for ch in preferences.enabled_channels
                    ],
                    "priority_threshold": preferences.priority_threshold.value,
                    "quiet_hours": preferences.quiet_hours,
                    "thread_specific": preferences.thread_specific,
                }

                await self.redis.setex(
                    key, 86400 * 30, json.dumps(prefs_data)
                )  # 30 day TTL

            except Exception as e:
                logger.error(f"Failed to store user preferences: {e}")

        logger.info(f"Updated notification preferences for user {user_id}")

    def register_template(self, template: NotificationTemplate):
        """Register a custom notification template."""
        self.templates[template.template_id] = template
        logger.info(f"Registered custom notification template: {template.template_id}")

    def register_delivery_handler(
        self, channel: NotificationChannel, handler: Callable
    ):
        """Register a custom delivery handler."""
        self.delivery_handlers[channel] = handler
        logger.info(f"Registered custom delivery handler for {channel.value}")

    def get_statistics(self) -> dict[str, Any]:
        """Get notification statistics."""
        return self.stats.copy()

    def get_templates(self) -> list[dict[str, Any]]:
        """Get all notification templates."""
        return [
            {
                "template_id": template.template_id,
                "name": template.name,
                "title_template": template.title_template,
                "message_template": template.message_template,
                "default_channels": [ch.value for ch in template.default_channels],
                "default_priority": template.default_priority.value,
                "variables": template.variables,
            }
            for template in self.templates.values()
        ]


# Integration helper functions
async def setup_agent_notifications(
    subscription_manager: AgentSubscriptionManager | None = None,
    error_manager: IntegrationErrorManager | None = None,
    redis_client=None,
) -> AgentNotificationSystem:
    """Set up agent notification system.

    Args:
        subscription_manager: Subscription manager
        error_manager: Error manager
        redis_client: Optional Redis client

    Returns:
        Agent notification system
    """
    notification_system = AgentNotificationSystem(
        subscription_manager, error_manager, redis_client
    )

    logger.info("Agent notification system setup completed")
    return notification_system


# Convenience functions for common notifications
async def notify_analysis_started(
    notification_system: AgentNotificationSystem,
    thread_id: str,
    analysis_type: str,
    analysis_id: str,
):
    """Send analysis started notification."""
    await notification_system.send_notification(
        "analysis_started",
        thread_id,
        {"analysis_type": analysis_type, "analysis_id": analysis_id},
    )


async def notify_analysis_completed(
    notification_system: AgentNotificationSystem,
    thread_id: str,
    analysis_type: str,
    analysis_id: str,
    result_summary: str,
):
    """Send analysis completed notification."""
    await notification_system.send_notification(
        "analysis_completed",
        thread_id,
        {
            "analysis_type": analysis_type,
            "analysis_id": analysis_id,
            "result_summary": result_summary,
        },
    )


async def notify_system_error(
    notification_system: AgentNotificationSystem,
    thread_id: str,
    component: str,
    error_message: str,
    error_id: str,
):
    """Send system error notification."""
    await notification_system.send_notification(
        "system_error",
        thread_id,
        {"component": component, "error_message": error_message, "error_id": error_id},
    )
