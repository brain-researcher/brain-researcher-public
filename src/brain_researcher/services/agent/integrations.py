"""Agent Service Integrations Master Module.

This module provides a unified interface for setting up and managing
all agent service integrations with the new infrastructure components.
"""

import logging
import asyncio
from typing import Dict, Any, Optional
from dataclasses import dataclass, field
from datetime import datetime

# Import all integration components
try:
    from brain_researcher.services.agent.subscription_integration import (
        AgentSubscriptionManager, setup_agent_subscriptions
    )
    from brain_researcher.services.agent.streaming_integration import (
        AgentStreamingManager, setup_agent_streaming
    )
    from brain_researcher.services.agent.deduplication_integration import (
        AgentDataDeduplication, setup_agent_deduplication
    )
    from brain_researcher.services.agent.plugin_integration import (
        AgentPluginManager, setup_agent_plugins
    )
    from brain_researcher.services.agent.notification_system import (
        AgentNotificationSystem, setup_agent_notifications
    )
    from brain_researcher.services.agent.error_integration import (
        IntegrationErrorManager, setup_integration_logging
    )
    INTEGRATIONS_AVAILABLE = True
except ImportError as e:
    logging.warning(f"Some agent integrations not available: {e}")
    INTEGRATIONS_AVAILABLE = False

logger = logging.getLogger(__name__)


@dataclass
class IntegrationConfig:
    """Configuration for agent integrations."""

    # Global settings
    enable_subscriptions: bool = True
    enable_streaming: bool = True
    enable_deduplication: bool = True
    enable_plugins: bool = True
    enable_notifications: bool = True
    enable_error_handling: bool = True

    # Service configurations
    kafka_config: Optional[Dict[str, Any]] = None
    redis_config: Optional[Dict[str, Any]] = None
    neo4j_config: Optional[Dict[str, Any]] = None

    # Integration-specific settings
    plugin_directory: str = "./plugins"
    auto_discover_plugins: bool = True
    enable_tool_deduplication: bool = True
    enable_tool_streaming: bool = True
    notification_channels: list = field(default_factory=lambda: ["in_chat", "websocket"])

    # Performance settings
    max_concurrent_operations: int = 100
    rate_limit_enabled: bool = True
    cache_ttl: int = 3600  # 1 hour


class AgentIntegrationManager:
    """Master manager for all agent integrations."""

    def __init__(self, config: Optional[IntegrationConfig] = None):
        """Initialize integration manager.

        Args:
            config: Optional integration configuration
        """
        self.config = config or IntegrationConfig()

        # Integration managers
        self.subscription_manager: Optional[AgentSubscriptionManager] = None
        self.streaming_manager: Optional[AgentStreamingManager] = None
        self.deduplication_manager: Optional[AgentDataDeduplication] = None
        self.plugin_manager: Optional[AgentPluginManager] = None
        self.notification_system: Optional[AgentNotificationSystem] = None
        self.error_manager: Optional[IntegrationErrorManager] = None

        # External service clients
        self.redis_client = None
        self.neo4j_driver = None
        self.subscription_system = None

        # Status tracking
        self.initialization_status = {
            "subscriptions": False,
            "streaming": False,
            "deduplication": False,
            "plugins": False,
            "notifications": False,
            "error_handling": False
        }

        # Statistics
        self.stats = {
            "initialized_at": None,
            "integrations_enabled": 0,
            "integrations_failed": 0,
            "total_operations": 0
        }

    async def initialize_all(self,
                           subscription_system=None,
                           redis_client=None,
                           neo4j_driver=None,
                           agent_state_machine=None) -> bool:
        """Initialize all enabled integrations.

        Args:
            subscription_system: Optional subscription system
            redis_client: Optional Redis client
            neo4j_driver: Optional Neo4j driver
            agent_state_machine: Optional agent state machine

        Returns:
            Success status
        """
        logger.info("Initializing agent integrations...")

        if not INTEGRATIONS_AVAILABLE:
            logger.error("Integration modules not available")
            return False

        self.redis_client = redis_client
        self.neo4j_driver = neo4j_driver
        self.subscription_system = subscription_system

        success_count = 0
        total_count = 0

        try:
            # Initialize error handling first (needed by others)
            if self.config.enable_error_handling:
                total_count += 1
                if await self._initialize_error_handling():
                    success_count += 1

            # Initialize subscription system
            if self.config.enable_subscriptions and subscription_system:
                total_count += 1
                if await self._initialize_subscriptions(subscription_system, redis_client):
                    success_count += 1

            # Initialize streaming
            if self.config.enable_streaming:
                total_count += 1
                if await self._initialize_streaming(redis_client, agent_state_machine):
                    success_count += 1

            # Initialize deduplication
            if self.config.enable_deduplication:
                total_count += 1
                if await self._initialize_deduplication(neo4j_driver, redis_client, agent_state_machine):
                    success_count += 1

            # Initialize plugins
            if self.config.enable_plugins:
                total_count += 1
                if await self._initialize_plugins(agent_state_machine):
                    success_count += 1

            # Initialize notifications
            if self.config.enable_notifications:
                total_count += 1
                if await self._initialize_notifications(redis_client):
                    success_count += 1

            # Setup cross-integrations
            await self._setup_cross_integrations()

            # Update statistics
            self.stats["initialized_at"] = datetime.now().isoformat()
            self.stats["integrations_enabled"] = success_count
            self.stats["integrations_failed"] = total_count - success_count

            success = success_count > 0
            logger.info(f"Integration initialization completed: {success_count}/{total_count} successful")

            return success

        except Exception as e:
            logger.error(f"Error initializing integrations: {e}", exc_info=True)
            self.stats["integrations_failed"] = total_count
            return False

    async def _initialize_error_handling(self) -> bool:
        """Initialize error handling integration."""
        try:
            self.error_manager = setup_integration_logging(
                self.redis_client,
                None  # Will be set later when notification system is available
            )

            self.initialization_status["error_handling"] = True
            logger.info("Error handling integration initialized")
            return True

        except Exception as e:
            logger.error(f"Failed to initialize error handling: {e}")
            return False

    async def _initialize_subscriptions(self, subscription_system, redis_client) -> bool:
        """Initialize subscription integration."""
        try:
            self.subscription_manager = await setup_agent_subscriptions(
                None,  # agent_state_machine will be set later
                subscription_system,
                redis_client
            )

            self.initialization_status["subscriptions"] = True
            logger.info("Subscription integration initialized")
            return True

        except Exception as e:
            logger.error(f"Failed to initialize subscriptions: {e}")
            return False

    async def _initialize_streaming(self, redis_client, agent_state_machine) -> bool:
        """Initialize streaming integration."""
        try:
            self.streaming_manager = await setup_agent_streaming(
                agent_state_machine,
                self.config.kafka_config,
                redis_client
            )

            self.initialization_status["streaming"] = True
            logger.info("Streaming integration initialized")
            return True

        except Exception as e:
            logger.error(f"Failed to initialize streaming: {e}")
            return False

    async def _initialize_deduplication(self, neo4j_driver, redis_client, agent_state_machine) -> bool:
        """Initialize deduplication integration."""
        try:
            self.deduplication_manager = await setup_agent_deduplication(
                agent_state_machine,
                neo4j_driver,
                redis_client
            )

            self.initialization_status["deduplication"] = True
            logger.info("Deduplication integration initialized")
            return True

        except Exception as e:
            logger.error(f"Failed to initialize deduplication: {e}")
            return False

    async def _initialize_plugins(self, agent_state_machine) -> bool:
        """Initialize plugin integration."""
        try:
            from brain_researcher.services.agent.plugin_integration import AgentPluginConfig

            plugin_config = AgentPluginConfig(
                auto_discover=self.config.auto_discover_plugins,
                plugin_directory=self.config.plugin_directory
            )

            self.plugin_manager = await setup_agent_plugins(
                agent_state_machine,
                plugin_config
            )

            self.initialization_status["plugins"] = True
            logger.info("Plugin integration initialized")
            return True

        except Exception as e:
            logger.error(f"Failed to initialize plugins: {e}")
            return False

    async def _initialize_notifications(self, redis_client) -> bool:
        """Initialize notification system."""
        try:
            self.notification_system = await setup_agent_notifications(
                self.subscription_manager,
                self.error_manager,
                redis_client
            )

            # Update error manager with notification system
            if self.error_manager:
                self.error_manager.notification_manager = self.notification_system

            self.initialization_status["notifications"] = True
            logger.info("Notification system initialized")
            return True

        except Exception as e:
            logger.error(f"Failed to initialize notifications: {e}")
            return False

    async def _setup_cross_integrations(self):
        """Set up integrations between components."""
        try:
            # Connect error manager to notification system
            if self.error_manager and self.notification_system:
                # Set notification manager in all component loggers
                for logger_instance in self.error_manager.loggers.values():
                    logger_instance.notification_manager = self.notification_system

            logger.debug("Cross-integrations setup completed")

        except Exception as e:
            logger.error(f"Error setting up cross-integrations: {e}")

    async def enable_tool_integrations(self, tool_registry):
        """Enable integrations for tools in the registry.

        Args:
            tool_registry: Tool registry to enhance
        """
        try:
            # Enable tool deduplication
            if self.deduplication_manager and self.config.enable_tool_deduplication:
                tool_registry.enable_tool_deduplication()
                logger.info("Tool deduplication enabled")

            # Enable tool streaming
            if self.streaming_manager and self.config.enable_tool_streaming:
                tool_registry.enable_tool_streaming()
                logger.info("Tool streaming enabled")

            # Register plugin tools
            if self.plugin_manager:
                from brain_researcher.services.agent.plugin_integration import register_plugins_with_tools
                count = await register_plugins_with_tools(
                    type('MockAgent', (), {'plugin_tool_registry':
                        type('MockRegistry', (), {'register_all_plugins':
                            lambda tr: len(self.plugin_manager.plugin_tools)})()})(),
                    tool_registry
                )
                logger.info(f"Registered {count} plugin tools")

        except Exception as e:
            logger.error(f"Error enabling tool integrations: {e}")

    async def subscribe_thread_to_events(self, thread_id: str):
        """Subscribe a thread to relevant events.

        Args:
            thread_id: Thread ID to subscribe
        """
        if self.subscription_manager:
            try:
                # Subscribe to analysis events
                from brain_researcher.services.agent.subscription_integration import subscribe_agent_to_analysis_events
                await subscribe_agent_to_analysis_events(self.subscription_manager, thread_id)

                logger.info(f"Subscribed thread {thread_id} to events")

            except Exception as e:
                logger.error(f"Error subscribing thread {thread_id}: {e}")

    async def notify_analysis_started(self, thread_id: str, analysis_type: str, analysis_id: str):
        """Send analysis started notification.

        Args:
            thread_id: Thread ID
            analysis_type: Type of analysis
            analysis_id: Analysis ID
        """
        if self.notification_system:
            try:
                from brain_researcher.services.agent.notification_system import notify_analysis_started
                await notify_analysis_started(
                    self.notification_system, thread_id, analysis_type, analysis_id
                )
            except Exception as e:
                logger.error(f"Error sending analysis started notification: {e}")

    async def notify_analysis_completed(self, thread_id: str, analysis_type: str,
                                      analysis_id: str, result_summary: str):
        """Send analysis completed notification.

        Args:
            thread_id: Thread ID
            analysis_type: Type of analysis
            analysis_id: Analysis ID
            result_summary: Summary of results
        """
        if self.notification_system:
            try:
                from brain_researcher.services.agent.notification_system import notify_analysis_completed
                await notify_analysis_completed(
                    self.notification_system, thread_id, analysis_type, analysis_id, result_summary
                )
            except Exception as e:
                logger.error(f"Error sending analysis completed notification: {e}")

    def get_comprehensive_status(self) -> Dict[str, Any]:
        """Get comprehensive status of all integrations.

        Returns:
            Status dictionary
        """
        status = {
            "initialization_status": self.initialization_status.copy(),
            "integrations_available": INTEGRATIONS_AVAILABLE,
            "statistics": self.stats.copy(),
            "configuration": {
                "subscriptions_enabled": self.config.enable_subscriptions,
                "streaming_enabled": self.config.enable_streaming,
                "deduplication_enabled": self.config.enable_deduplication,
                "plugins_enabled": self.config.enable_plugins,
                "notifications_enabled": self.config.enable_notifications,
                "error_handling_enabled": self.config.enable_error_handling
            },
            "component_stats": {}
        }

        # Add component-specific statistics
        if self.subscription_manager:
            status["component_stats"]["subscriptions"] = self.subscription_manager.get_statistics()

        if self.streaming_manager:
            status["component_stats"]["streaming"] = self.streaming_manager.get_statistics()

        if self.deduplication_manager:
            status["component_stats"]["deduplication"] = self.deduplication_manager.get_statistics()

        if self.plugin_manager:
            status["component_stats"]["plugins"] = self.plugin_manager.get_statistics()

        if self.notification_system:
            status["component_stats"]["notifications"] = self.notification_system.get_statistics()

        if self.error_manager:
            status["component_stats"]["error_handling"] = self.error_manager.get_error_statistics()

        return status

    async def shutdown_all(self):
        """Shutdown all integrations gracefully."""
        logger.info("Shutting down agent integrations...")

        # Shutdown in reverse order
        if self.streaming_manager:
            try:
                await self.streaming_manager.stop()
                logger.info("Streaming manager shutdown")
            except Exception as e:
                logger.error(f"Error shutting down streaming: {e}")

        # Other managers don't require explicit shutdown
        logger.info("All integrations shutdown completed")


# Convenience functions
async def setup_full_agent_integration(
    subscription_system=None,
    redis_client=None,
    neo4j_driver=None,
    kafka_config=None,
    config: Optional[IntegrationConfig] = None
) -> AgentIntegrationManager:
    """Set up full agent integration with all components.

    Args:
        subscription_system: Subscription system instance
        redis_client: Redis client
        neo4j_driver: Neo4j driver
        kafka_config: Kafka configuration
        config: Optional integration configuration

    Returns:
        Initialized integration manager
    """
    if not config:
        config = IntegrationConfig(kafka_config=kafka_config)

    manager = AgentIntegrationManager(config)

    success = await manager.initialize_all(
        subscription_system=subscription_system,
        redis_client=redis_client,
        neo4j_driver=neo4j_driver
    )

    if success:
        logger.info("Full agent integration setup completed successfully")
    else:
        logger.warning("Agent integration setup completed with some failures")

    return manager


def create_integration_config(
    enable_all: bool = True,
    kafka_bootstrap_servers: str = "localhost:9092",
    plugin_directory: str = "./plugins"
) -> IntegrationConfig:
    """Create a standard integration configuration.

    Args:
        enable_all: Whether to enable all integrations
        kafka_bootstrap_servers: Kafka bootstrap servers
        plugin_directory: Plugin directory path

    Returns:
        Integration configuration
    """
    return IntegrationConfig(
        enable_subscriptions=enable_all,
        enable_streaming=enable_all,
        enable_deduplication=enable_all,
        enable_plugins=enable_all,
        enable_notifications=enable_all,
        enable_error_handling=enable_all,
        kafka_config={"bootstrap_servers": kafka_bootstrap_servers} if enable_all else None,
        plugin_directory=plugin_directory,
        auto_discover_plugins=enable_all,
        enable_tool_deduplication=enable_all,
        enable_tool_streaming=enable_all
    )