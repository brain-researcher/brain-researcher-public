"""
Brain Researcher Telemetry System

This package provides comprehensive telemetry capabilities including:
- TELEMETRY-001: Performance metrics with alerts and dashboards
- TELEMETRY-002: Error tracking with Sentry integration
- TELEMETRY-003: Usage metrics and analytics

Main components:
- collector: Event collection and processing
- alerts: Alert system with notifications
- sentry_integration: Error tracking and monitoring
- integrations: Service-specific telemetry hooks
- models: Data models and schemas
"""

import logging
import os
from typing import Any, Dict, Optional

import redis

from .alerts import AlertManager
from .collector import TelemetryCollector
from .integrations import (
    AgentTelemetry,
    BRKGTelemetry,
    TelemetryIntegration,
    UITelemetry,
    create_agent_telemetry,
    create_br_kg_telemetry,
    create_ui_telemetry,
)
from .models import EventType, PrivacyLevel, ServiceType, TelemetryConfiguration
from .notifications import NotificationManager, create_notification_config_from_env
from .sentry_integration import (
    SentryConfig,
    SentryIntegration,
    create_sentry_config_from_env,
    initialize_sentry,
)

# Legacy imports for backward compatibility
try:
    from .aggregator import MetricType, UsageMetricsAggregator
    from .privacy import PrivacyController

    LEGACY_MODULES_AVAILABLE = True
except ImportError:
    LEGACY_MODULES_AVAILABLE = False

logger = logging.getLogger(__name__)

# Global instances
_telemetry_collector: TelemetryCollector | None = None
_alert_manager: AlertManager | None = None
_notification_manager: NotificationManager | None = None
_sentry_integration: SentryIntegration | None = None


class TelemetrySystem:
    """Main telemetry system orchestrator."""

    def __init__(
        self,
        config: TelemetryConfiguration | None = None,
        redis_client: redis.Redis | None = None,
        sentry_config: SentryConfig | None = None,
    ):

        # Configuration
        self.config = config or TelemetryConfiguration()

        # Redis client
        if redis_client is None:
            try:
                redis_client = redis.from_url(
                    os.environ.get("REDIS_URL", "redis://localhost:6379/0"),
                    decode_responses=False,
                )
                redis_client.ping()
            except:
                try:
                    import fakeredis

                    redis_client = fakeredis.FakeRedis(decode_responses=False)
                    logger.warning("Using fake Redis for telemetry")
                except ImportError:
                    logger.error("Redis not available and fakeredis not installed")
                    raise

        self.redis_client = redis_client

        # Initialize core components
        self.collector = TelemetryCollector(self.config, redis_client)

        # Initialize Sentry
        if sentry_config is None:
            sentry_config = create_sentry_config_from_env()
        self.sentry = initialize_sentry(sentry_config)

        # Initialize notifications
        notification_config = create_notification_config_from_env()
        self.notification_manager = NotificationManager(
            notification_config, redis_client
        )

        # Initialize alerts
        self.alert_manager = AlertManager(
            redis_client, self.collector, notification_config.__dict__
        )

        # Service integrations
        self.integrations: dict[ServiceType, TelemetryIntegration] = {}

        logger.info("TelemetrySystem initialized")

    async def start(self):
        """Start all telemetry components."""
        try:
            # Start collector
            await self.collector.start()
            logger.info("Telemetry collector started")

            # Start alert manager
            await self.alert_manager.start()
            logger.info("Alert manager started")

            logger.info("TelemetrySystem fully started")

        except Exception as e:
            logger.error(f"Error starting telemetry system: {e}")
            raise

    async def stop(self):
        """Stop all telemetry components."""
        try:
            # Stop alert manager
            if self.alert_manager:
                await self.alert_manager.stop()
                logger.info("Alert manager stopped")

            # Stop collector
            if self.collector:
                await self.collector.stop()
                logger.info("Telemetry collector stopped")

            logger.info("TelemetrySystem stopped")

        except Exception as e:
            logger.error(f"Error stopping telemetry system: {e}")

    def get_service_integration(self, service: ServiceType) -> TelemetryIntegration:
        """Get or create service-specific telemetry integration."""
        if service not in self.integrations:
            if service == ServiceType.AGENT:
                self.integrations[service] = AgentTelemetry(self.collector, self.config)
            elif service == ServiceType.BR_KG:
                self.integrations[service] = BRKGTelemetry(self.collector, self.config)
            elif service == ServiceType.WEB_UI:
                self.integrations[service] = UITelemetry(self.collector, self.config)
            else:
                self.integrations[service] = TelemetryIntegration(
                    service, self.collector, self.config
                )

        return self.integrations[service]

    def get_stats(self) -> dict[str, Any]:
        """Get comprehensive telemetry system statistics."""
        stats = {
            "collector": self.collector.get_stats() if self.collector else {},
            "alerts": (
                self.alert_manager.get_alert_stats() if self.alert_manager else {}
            ),
            "notifications": (
                self.notification_manager.get_notification_stats()
                if self.notification_manager
                else {}
            ),
            "sentry": self.sentry.get_stats() if self.sentry else {},
            "integrations": {
                str(service): (
                    integration.collector.get_stats()
                    if hasattr(integration, "collector")
                    else {}
                )
                for service, integration in self.integrations.items()
            },
        }
        return stats


def initialize_telemetry_system(
    config: TelemetryConfiguration | None = None,
    redis_client: redis.Redis | None = None,
    sentry_config: SentryConfig | None = None,
) -> TelemetrySystem:
    """Initialize the global telemetry system."""
    global _telemetry_collector, _alert_manager, _notification_manager, _sentry_integration

    system = TelemetrySystem(config, redis_client, sentry_config)

    # Set global references
    _telemetry_collector = system.collector
    _alert_manager = system.alert_manager
    _notification_manager = system.notification_manager
    _sentry_integration = system.sentry

    return system


def get_telemetry_collector() -> TelemetryCollector | None:
    """Get global telemetry collector instance."""
    return _telemetry_collector


def get_alert_manager() -> AlertManager | None:
    """Get global alert manager instance."""
    return _alert_manager


def get_notification_manager() -> NotificationManager | None:
    """Get global notification manager instance."""
    return _notification_manager


def get_sentry_integration() -> SentryIntegration | None:
    """Get global Sentry integration instance."""
    return _sentry_integration


# Convenience functions for service integration
def create_service_telemetry(
    service: ServiceType, config: TelemetryConfiguration | None = None
) -> TelemetryIntegration:
    """Create service-specific telemetry integration."""
    if service == ServiceType.AGENT:
        return create_agent_telemetry(config)
    elif service == ServiceType.BR_KG:
        return create_br_kg_telemetry(config)
    elif service == ServiceType.WEB_UI:
        return create_ui_telemetry(config)
    else:
        return TelemetryIntegration(service, _telemetry_collector, config)


__version__ = "2.0.0"
__all__ = [
    # Main system
    "TelemetrySystem",
    "initialize_telemetry_system",
    # Global accessors
    "get_telemetry_collector",
    "get_alert_manager",
    "get_notification_manager",
    "get_sentry_integration",
    # Service integrations
    "create_service_telemetry",
    "TelemetryIntegration",
    "AgentTelemetry",
    "BRKGTelemetry",
    "UITelemetry",
    # Core components
    "TelemetryCollector",
    "AlertManager",
    "NotificationManager",
    "SentryIntegration",
    # Configuration
    "TelemetryConfiguration",
    "SentryConfig",
    "create_sentry_config_from_env",
    "create_notification_config_from_env",
    # Models and enums
    "ServiceType",
    "EventType",
    "PrivacyLevel",
    # Legacy compatibility
    "TelemetryEvent",
]

# Add legacy exports if available
if LEGACY_MODULES_AVAILABLE:
    __all__.extend(["UsageMetricsAggregator", "MetricType", "PrivacyController"])
