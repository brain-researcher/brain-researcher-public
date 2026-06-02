"""Alerting System for Brain Researcher Agent

Provides intelligent alerting with multiple channels, suppression,
and escalation policies.
"""

import asyncio
import hashlib
import json
import logging
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Set

logger = logging.getLogger(__name__)


class AlertSeverity(Enum):
    """Alert severity levels."""

    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


class AlertChannel(Enum):
    """Alert delivery channels."""

    LOG = "log"
    EMAIL = "email"
    SLACK = "slack"
    WEBHOOK = "webhook"
    PAGERDUTY = "pagerduty"


@dataclass
class Alert:
    """Individual alert."""

    alert_id: str
    title: str
    message: str
    severity: AlertSeverity
    source: str
    metadata: Dict[str, Any] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=datetime.now)
    fingerprint: Optional[str] = None

    def __post_init__(self):
        """Generate fingerprint if not provided."""
        if not self.fingerprint:
            # Create deterministic fingerprint for deduplication
            data = f"{self.title}:{self.source}:{self.severity.value}"
            self.fingerprint = hashlib.md5(data.encode()).hexdigest()


@dataclass
class AlertRule:
    """Alert rule configuration."""

    name: str
    condition: str  # Expression to evaluate
    severity: AlertSeverity
    channels: List[AlertChannel]
    cooldown_seconds: int = 300  # Prevent alert spam
    escalation_after: Optional[int] = None  # Seconds before escalation
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class AlertState:
    """Track alert state for suppression."""

    alert: Alert
    count: int = 1
    first_seen: datetime = field(default_factory=datetime.now)
    last_seen: datetime = field(default_factory=datetime.now)
    suppressed: bool = False
    acknowledged: bool = False
    resolved: bool = False


class AlertManager:
    """Manages alerts with intelligent routing and suppression."""

    def __init__(self, suppression_window: int = 300, max_alerts_per_window: int = 5):
        """Initialize alert manager.

        Args:
            suppression_window: Seconds to track alerts for suppression
            max_alerts_per_window: Max alerts before suppression
        """
        self.suppression_window = suppression_window
        self.max_alerts_per_window = max_alerts_per_window

        # Alert tracking
        self.active_alerts: Dict[str, AlertState] = {}
        self.alert_history: List[Alert] = []
        self.alert_rules: List[AlertRule] = []

        # Channel handlers
        self.channel_handlers: Dict[AlertChannel, List[Callable]] = defaultdict(list)

        # Suppression tracking
        self.suppression_counts: Dict[str, List[datetime]] = defaultdict(list)

        # Register default handlers
        self._register_default_handlers()

    def _register_default_handlers(self):
        """Register default channel handlers."""
        self.register_handler(AlertChannel.LOG, self._handle_log_alert)
        # Additional handlers would be registered here

    def register_handler(self, channel: AlertChannel, handler: Callable):
        """Register an alert handler for a channel.

        Args:
            channel: Alert channel
            handler: Handler function
        """
        self.channel_handlers[channel].append(handler)
        logger.info(f"Registered handler for {channel.value}")

    def add_rule(self, rule: AlertRule):
        """Add an alert rule.

        Args:
            rule: Alert rule configuration
        """
        self.alert_rules.append(rule)
        logger.info(f"Added alert rule: {rule.name}")

    async def send_alert(self, alert: Alert):
        """Send an alert through configured channels.

        Args:
            alert: Alert to send
        """
        # Check suppression
        if self._should_suppress(alert):
            logger.debug(f"Alert suppressed: {alert.fingerprint}")
            self._update_suppression(alert)
            return

        # Update alert state
        self._update_alert_state(alert)

        # Route to channels based on severity
        channels = self._get_channels_for_severity(alert.severity)

        # Send through each channel
        for channel in channels:
            await self._send_to_channel(alert, channel)

        # Add to history
        self.alert_history.append(alert)

        # Check for escalation
        await self._check_escalation(alert)

    def _should_suppress(self, alert: Alert) -> bool:
        """Check if alert should be suppressed.

        Args:
            alert: Alert to check

        Returns:
            True if should suppress
        """
        fingerprint = alert.fingerprint
        now = datetime.now()

        # Clean old suppression entries
        cutoff = now - timedelta(seconds=self.suppression_window)
        self.suppression_counts[fingerprint] = [
            ts for ts in self.suppression_counts[fingerprint] if ts > cutoff
        ]

        # Check if over limit
        count = len(self.suppression_counts[fingerprint])
        return count >= self.max_alerts_per_window

    def _update_suppression(self, alert: Alert):
        """Update suppression tracking.

        Args:
            alert: Alert that was suppressed
        """
        fingerprint = alert.fingerprint

        if fingerprint in self.active_alerts:
            state = self.active_alerts[fingerprint]
            state.count += 1
            state.last_seen = datetime.now()
            state.suppressed = True

    def _update_alert_state(self, alert: Alert):
        """Update alert state tracking.

        Args:
            alert: Alert to track
        """
        fingerprint = alert.fingerprint
        now = datetime.now()

        if fingerprint in self.active_alerts:
            # Update existing alert
            state = self.active_alerts[fingerprint]
            state.count += 1
            state.last_seen = now
        else:
            # New alert
            self.active_alerts[fingerprint] = AlertState(alert=alert)

        # Track for suppression
        self.suppression_counts[fingerprint].append(now)

    def _get_channels_for_severity(self, severity: AlertSeverity) -> List[AlertChannel]:
        """Get appropriate channels for severity.

        Args:
            severity: Alert severity

        Returns:
            List of channels
        """
        channels = [AlertChannel.LOG]

        if severity == AlertSeverity.WARNING:
            channels.append(AlertChannel.SLACK)
        elif severity == AlertSeverity.ERROR:
            channels.extend([AlertChannel.SLACK, AlertChannel.EMAIL])
        elif severity == AlertSeverity.CRITICAL:
            channels.extend(
                [AlertChannel.SLACK, AlertChannel.EMAIL, AlertChannel.PAGERDUTY]
            )

        return channels

    async def _send_to_channel(self, alert: Alert, channel: AlertChannel):
        """Send alert to specific channel.

        Args:
            alert: Alert to send
            channel: Target channel
        """
        handlers = self.channel_handlers.get(channel, [])

        for handler in handlers:
            try:
                if asyncio.iscoroutinefunction(handler):
                    await handler(alert)
                else:
                    handler(alert)
            except Exception as e:
                logger.error(f"Handler error for {channel.value}: {e}")

    async def _check_escalation(self, alert: Alert):
        """Check if alert needs escalation.

        Args:
            alert: Alert to check
        """
        fingerprint = alert.fingerprint

        if fingerprint not in self.active_alerts:
            return

        state = self.active_alerts[fingerprint]

        # Check if alert has been active too long
        duration = (datetime.now() - state.first_seen).total_seconds()

        if duration > 3600 and not state.acknowledged:  # 1 hour
            # Escalate to critical
            escalated = Alert(
                alert_id=f"{alert.alert_id}_escalated",
                title=f"[ESCALATED] {alert.title}",
                message=f"Alert active for {duration/3600:.1f} hours: {alert.message}",
                severity=AlertSeverity.CRITICAL,
                source=alert.source,
                metadata={**alert.metadata, "escalated": True},
            )
            await self.send_alert(escalated)

    def add_alert_handler(self, handler: Callable):
        """Add an alert handler.

        Args:
            handler: Alert handler function
        """
        # Add to appropriate channels
        self.channel_handlers[AlertChannel.LOG].append(handler)
        logger.info(
            f"Added alert handler: {handler.__name__ if hasattr(handler, '__name__') else 'handler'}"
        )

    async def _handle_log_alert(self, alert: Alert):
        """Default log handler.

        Args:
            alert: Alert to log
        """
        level = {
            AlertSeverity.INFO: logging.INFO,
            AlertSeverity.WARNING: logging.WARNING,
            AlertSeverity.ERROR: logging.ERROR,
            AlertSeverity.CRITICAL: logging.CRITICAL,
        }.get(alert.severity, logging.INFO)

        logger.log(
            level, f"[{alert.severity.value.upper()}] {alert.title}: {alert.message}"
        )

    def acknowledge_alert(self, fingerprint: str):
        """Acknowledge an alert.

        Args:
            fingerprint: Alert fingerprint
        """
        if fingerprint in self.active_alerts:
            self.active_alerts[fingerprint].acknowledged = True
            logger.info(f"Alert acknowledged: {fingerprint}")

    def resolve_alert(self, fingerprint: str):
        """Resolve an alert.

        Args:
            fingerprint: Alert fingerprint
        """
        if fingerprint in self.active_alerts:
            self.active_alerts[fingerprint].resolved = True
            logger.info(f"Alert resolved: {fingerprint}")

    def get_active_alerts(self) -> List[AlertState]:
        """Get list of active alerts.

        Returns:
            List of active alert states
        """
        return [state for state in self.active_alerts.values() if not state.resolved]

    def get_alert_summary(self) -> Dict[str, Any]:
        """Get alert summary statistics.

        Returns:
            Summary statistics
        """
        active = self.get_active_alerts()

        severity_counts = defaultdict(int)
        for state in active:
            severity_counts[state.alert.severity.value] += 1

        return {
            "total_active": len(active),
            "by_severity": dict(severity_counts),
            "suppressed": sum(1 for s in self.active_alerts.values() if s.suppressed),
            "acknowledged": sum(
                1 for s in self.active_alerts.values() if s.acknowledged
            ),
            "total_sent": len(self.alert_history),
        }


class CircuitBreaker:
    """Circuit breaker for preventing cascade failures."""

    def __init__(
        self, failure_threshold: int = 5, timeout: int = 60, recovery_timeout: int = 30
    ):
        """Initialize circuit breaker.

        Args:
            failure_threshold: Failures before opening
            timeout: Seconds to stay open
            recovery_timeout: Seconds before retry
        """
        self.failure_threshold = failure_threshold
        self.timeout = timeout
        self.recovery_timeout = recovery_timeout

        self.failure_count = 0
        self.last_failure_time = None
        self.state = "closed"  # closed, open, half-open

    def call(self, func: Callable, *args, **kwargs):
        """Call function with circuit breaker protection.

        Args:
            func: Function to call
            *args: Function arguments
            **kwargs: Function keyword arguments

        Returns:
            Function result

        Raises:
            CircuitOpenError: If circuit is open
        """
        if self.state == "open":
            if self._should_attempt_reset():
                self.state = "half-open"
            else:
                raise CircuitOpenError("Circuit breaker is open")

        try:
            result = func(*args, **kwargs)
            self._on_success()
            return result
        except Exception as e:
            self._on_failure()
            raise

    def _should_attempt_reset(self) -> bool:
        """Check if should attempt reset.

        Returns:
            True if should attempt
        """
        if not self.last_failure_time:
            return True

        elapsed = (datetime.now() - self.last_failure_time).total_seconds()
        return elapsed >= self.recovery_timeout

    def _on_success(self):
        """Handle successful call."""
        self.failure_count = 0
        self.state = "closed"

    def _on_failure(self):
        """Handle failed call."""
        self.failure_count += 1
        self.last_failure_time = datetime.now()

        if self.failure_count >= self.failure_threshold:
            self.state = "open"
            logger.warning(
                f"Circuit breaker opened after {self.failure_count} failures"
            )

    def reset(self):
        """Reset circuit breaker."""
        self.failure_count = 0
        self.last_failure_time = None
        self.state = "closed"


class CircuitOpenError(Exception):
    """Raised when circuit breaker is open."""

    pass
