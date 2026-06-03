"""
Alert Management System for Performance Metrics (TELEMETRY-001)

This module implements threshold-based alerting for performance degradation,
integrating with the existing telemetry infrastructure.
"""

import asyncio
import json
import logging
import math
import smtplib
import time
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from enum import Enum
from typing import Dict, List, Optional, Any, Callable, Union
import requests
import redis

from .models import TelemetryEvent, ServiceType, EventType
from .collector import TelemetryCollector


logger = logging.getLogger(__name__)


class AlertSeverity(str, Enum):
    """Alert severity levels."""
    CRITICAL = "critical"
    WARNING = "warning"
    INFO = "info"


class AlertStatus(str, Enum):
    """Alert status states."""
    ACTIVE = "active"
    RESOLVED = "resolved"
    SUPPRESSED = "suppressed"


class NotificationChannel(str, Enum):
    """Notification delivery channels."""
    EMAIL = "email"
    SLACK = "slack"
    WEBHOOK = "webhook"
    DISCORD = "discord"


@dataclass
class AlertThreshold:
    """Alert threshold configuration."""
    metric_name: str
    operator: str  # >, <, >=, <=, ==
    value: float
    duration_seconds: int = 300  # 5 minutes
    severity: AlertSeverity = AlertSeverity.WARNING
    description: str = ""

    def evaluate(self, current_value: float, duration_met: bool = True) -> bool:
        """Evaluate if threshold is breached."""
        if not duration_met:
            return False

        if self.operator == ">":
            if current_value > self.value:
                return True
            # Treat a zero threshold as inclusive to avoid missing baseline metrics.
            return self.value == 0 and math.isclose(current_value, 0.0)
        elif self.operator == "<":
            return current_value < self.value
        elif self.operator == ">=":
            return current_value >= self.value
        elif self.operator == "<=":
            return current_value <= self.value
        elif self.operator == "==":
            return current_value == self.value
        return False


@dataclass
class AlertRule:
    """Complete alert rule definition."""
    name: str
    threshold: AlertThreshold
    service: ServiceType
    enabled: bool = True
    cooldown_seconds: int = 3600  # 1 hour
    notification_channels: List[NotificationChannel] = None
    tags: Dict[str, str] = None

    def __post_init__(self):
        if self.notification_channels is None:
            self.notification_channels = [NotificationChannel.EMAIL]
        if self.tags is None:
            self.tags = {}


@dataclass
class Alert:
    """Active alert instance."""
    id: str
    rule_name: str
    service: ServiceType
    severity: AlertSeverity
    status: AlertStatus
    current_value: float
    threshold_value: float
    message: str
    triggered_at: datetime
    resolved_at: Optional[datetime] = None
    last_notification: Optional[datetime] = None
    notification_count: int = 0
    tags: Dict[str, str] = None

    def __post_init__(self):
        if self.tags is None:
            self.tags = {}


class NotificationManager:
    """Handles alert notifications across different channels."""

    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.smtp_config = config.get("smtp", {})
        self.slack_config = config.get("slack", {})
        self.webhook_config = config.get("webhook", {})

    async def send_notification(self,
                              alert: Alert,
                              channel: NotificationChannel,
                              is_resolution: bool = False) -> bool:
        """Send notification for an alert."""
        try:
            if channel == NotificationChannel.EMAIL:
                return await self._send_email(alert, is_resolution)
            elif channel == NotificationChannel.SLACK:
                return await self._send_slack(alert, is_resolution)
            elif channel == NotificationChannel.WEBHOOK:
                return await self._send_webhook(alert, is_resolution)
            else:
                logger.warning(f"Unsupported notification channel: {channel}")
                return False
        except Exception as e:
            logger.error(f"Failed to send {channel} notification for alert {alert.id}: {e}")
            return False

    async def _send_email(self, alert: Alert, is_resolution: bool) -> bool:
        """Send email notification."""
        if not self.smtp_config.get("enabled", False):
            return False

        try:
            msg = MIMEMultipart()
            msg['From'] = self.smtp_config['from_address']
            msg['To'] = ", ".join(self.smtp_config['to_addresses'])

            status = "RESOLVED" if is_resolution else "TRIGGERED"
            msg['Subject'] = f"[Brain Researcher] Alert {status}: {alert.rule_name}"

            # Create email body
            body = self._create_email_body(alert, is_resolution)
            msg.attach(MIMEText(body, 'html'))

            # Send email
            server = smtplib.SMTP(self.smtp_config['host'], self.smtp_config['port'])
            if self.smtp_config.get('use_tls', True):
                server.starttls()
            if self.smtp_config.get('username'):
                server.login(self.smtp_config['username'], self.smtp_config['password'])

            server.sendmail(msg['From'], self.smtp_config['to_addresses'], msg.as_string())
            server.quit()

            logger.info(f"Email notification sent for alert {alert.id}")
            return True

        except Exception as e:
            logger.error(f"Failed to send email for alert {alert.id}: {e}")
            return False

    async def _send_slack(self, alert: Alert, is_resolution: bool) -> bool:
        """Send Slack notification."""
        if not self.slack_config.get("enabled", False):
            return False

        try:
            status = "resolved" if is_resolution else "triggered"
            color = "good" if is_resolution else ("danger" if alert.severity == AlertSeverity.CRITICAL else "warning")
            severity_label = (
                alert.severity.value.title()
                if hasattr(alert.severity, "value")
                else str(alert.severity).title()
            )

            payload = {
                "channel": self.slack_config['channel'],
                "username": "Brain Researcher Alerts",
                "attachments": [{
                    "color": color,
                    "title": f"{severity_label} Alert {status.title()}: {alert.rule_name}",
                    "text": alert.message,
                    "fields": [
                        {"title": "Service", "value": alert.service, "short": True},
                        {"title": "Severity", "value": alert.severity, "short": True},
                        {"title": "Current Value", "value": str(alert.current_value), "short": True},
                        {"title": "Threshold", "value": str(alert.threshold_value), "short": True},
                        {"title": "Time", "value": alert.triggered_at.strftime("%Y-%m-%d %H:%M:%S UTC"), "short": True}
                    ]
                }]
            }

            response = requests.post(
                self.slack_config['webhook_url'],
                json=payload,
                timeout=10
            )
            response.raise_for_status()

            logger.info(f"Slack notification sent for alert {alert.id}")
            return True

        except Exception as e:
            logger.error(f"Failed to send Slack notification for alert {alert.id}: {e}")
            return False

    async def _send_webhook(self, alert: Alert, is_resolution: bool) -> bool:
        """Send webhook notification."""
        if not self.webhook_config.get("enabled", False):
            return False

        try:
            payload = {
                "alert": asdict(alert),
                "is_resolution": is_resolution,
                "timestamp": datetime.utcnow().isoformat()
            }

            response = requests.post(
                self.webhook_config['url'],
                json=payload,
                headers=self.webhook_config.get('headers', {}),
                timeout=10
            )
            response.raise_for_status()

            logger.info(f"Webhook notification sent for alert {alert.id}")
            return True

        except Exception as e:
            logger.error(f"Failed to send webhook notification for alert {alert.id}: {e}")
            return False

    def _create_email_body(self, alert: Alert, is_resolution: bool) -> str:
        """Create HTML email body."""
        status = "RESOLVED" if is_resolution else "TRIGGERED"
        status_color = "#28a745" if is_resolution else ("#dc3545" if alert.severity == AlertSeverity.CRITICAL else "#ffc107")

        return f"""
        <html>
        <body style="font-family: Arial, sans-serif;">
            <div style="max-width: 600px; margin: 0 auto;">
                <h2 style="color: {status_color};">Alert {status}: {alert.rule_name}</h2>

                <div style="background-color: #f8f9fa; padding: 15px; border-radius: 5px; margin: 15px 0;">
                    <p><strong>Message:</strong> {alert.message}</p>
                    <p><strong>Service:</strong> {alert.service}</p>
                    <p><strong>Severity:</strong> {alert.severity}</p>
                    <p><strong>Current Value:</strong> {alert.current_value}</p>
                    <p><strong>Threshold:</strong> {alert.threshold_value}</p>
                    <p><strong>Triggered At:</strong> {alert.triggered_at.strftime("%Y-%m-%d %H:%M:%S UTC")}</p>
                    {f'<p><strong>Resolved At:</strong> {alert.resolved_at.strftime("%Y-%m-%d %H:%M:%S UTC")}</p>' if is_resolution else ''}
                </div>

                <p style="font-size: 12px; color: #6c757d;">
                    This is an automated alert from Brain Researcher telemetry system.
                </p>
            </div>
        </body>
        </html>
        """


class MetricsCollector:
    """Collects and aggregates metrics for alert evaluation."""

    def __init__(self, redis_client: redis.Redis, telemetry_collector: TelemetryCollector):
        self.redis_client = redis_client
        self.telemetry_collector = telemetry_collector

    async def get_service_metrics(self, service: ServiceType, time_window_minutes: int = 5) -> Dict[str, float]:
        """Get current metrics for a service."""
        try:
            # Get metrics from telemetry collector
            stats = self.telemetry_collector.get_stats()

            # Load request metrics once to avoid repeated Redis fetches
            request_metrics = await self._get_request_metrics(service, time_window_minutes)

            # Get edge/front-door request metrics if available.
            edge_metrics = await self._get_edge_metrics(service, time_window_minutes)

            # Calculate response time metrics
            response_time = await self._calculate_avg_response_time(
                service, time_window_minutes, request_metrics=request_metrics
            )

            # Calculate error rate
            error_rate = await self._calculate_error_rate(
                service, time_window_minutes, request_metrics=request_metrics
            )

            # Get system metrics
            memory_usage = await self._get_memory_usage(service)
            cpu_usage = await self._get_cpu_usage(service)

            return {
                "response_time_ms": response_time,
                "error_rate": error_rate,
                "memory_usage_percent": memory_usage,
                "cpu_usage_percent": cpu_usage,
                "events_per_minute": stats.get("events_collected", 0) / time_window_minutes,
                "processing_time_ms": stats.get("avg_processing_time_ms", 0),
                "buffer_utilization": stats.get("buffer_size", 0) / 10000 * 100  # Assuming max 10k buffer
            }

        except Exception as e:
            logger.error(f"Failed to collect metrics for {service}: {e}")
            return {}

    async def _get_edge_metrics(self, service: ServiceType, time_window_minutes: int) -> Dict[str, float]:
        """Get metrics from any edge/front-door compatibility layer."""
        try:
            # This would integrate with edge/front-door metrics when present.
            # For now, return mock data structure
            return {
                "request_count": 0,
                "avg_response_time": 0,
                "error_count": 0
            }
        except Exception as e:
            logger.error(f"Failed to get edge metrics: {e}")
            return {}

    async def _get_request_metrics(
        self, service: ServiceType, time_window_minutes: int
    ) -> List[Dict[str, Any]]:
        """Fetch request metrics for a service from Redis."""
        try:
            cutoff_time = int(time.time()) - (time_window_minutes * 60)
            metrics_keys = self.redis_client.zrangebyscore(
                "metrics:requests", cutoff_time, int(time.time())
            )

            if not metrics_keys:
                return []

            metrics_list: List[Dict[str, Any]] = []
            for key in metrics_keys:
                if isinstance(key, bytes):
                    key = key.decode()

                metrics_data = self.redis_client.get(f"metrics:request:{key}")
                if metrics_data:
                    try:
                        metrics = json.loads(metrics_data)
                        if metrics.get("service") == service:
                            metrics_list.append(metrics)
                    except json.JSONDecodeError:
                        continue

            return metrics_list
        except Exception as e:
            logger.error(f"Failed to fetch request metrics for {service}: {e}")
            return []

    async def _calculate_avg_response_time(
        self,
        service: ServiceType,
        time_window_minutes: int,
        *,
        request_metrics: Optional[List[Dict[str, Any]]] = None,
    ) -> float:
        """Calculate average response time."""
        try:
            metrics_list = request_metrics
            if metrics_list is None:
                metrics_list = await self._get_request_metrics(service, time_window_minutes)
            if not metrics_list:
                return 0.0

            total_duration = 0
            count = 0
            for metrics in metrics_list:
                total_duration += metrics.get("duration_ms", 0)
                count += 1

            return total_duration / count if count > 0 else 0.0

        except Exception as e:
            logger.error(f"Failed to calculate response time for {service}: {e}")
            return 0.0

    async def _calculate_error_rate(
        self,
        service: ServiceType,
        time_window_minutes: int,
        *,
        request_metrics: Optional[List[Dict[str, Any]]] = None,
    ) -> float:
        """Calculate error rate percentage."""
        try:
            metrics_list = request_metrics
            if metrics_list is None:
                metrics_list = await self._get_request_metrics(service, time_window_minutes)
            if not metrics_list:
                return 0.0

            total_requests = len(metrics_list)
            error_requests = 0
            for metrics in metrics_list:
                status_code = metrics.get("status_code", 200)
                try:
                    status_code = int(status_code)
                except (TypeError, ValueError):
                    status_code = 200
                if status_code >= 400 or metrics.get("error"):
                    error_requests += 1

            return (error_requests / total_requests * 100) if total_requests > 0 else 0.0

        except Exception as e:
            logger.error(f"Failed to calculate error rate for {service}: {e}")
            return 0.0

    async def _get_memory_usage(self, service: ServiceType) -> float:
        """Get memory usage percentage."""
        try:
            # This would integrate with system monitoring
            # For now, return a simulated value based on service load
            service_metrics = await self._get_service_load_metrics(service)
            return service_metrics.get("memory_percent", 0.0)
        except Exception as e:
            logger.error(f"Failed to get memory usage for {service}: {e}")
            return 0.0

    async def _get_cpu_usage(self, service: ServiceType) -> float:
        """Get CPU usage percentage."""
        try:
            # This would integrate with system monitoring
            # For now, return a simulated value based on service load
            service_metrics = await self._get_service_load_metrics(service)
            return service_metrics.get("cpu_percent", 0.0)
        except Exception as e:
            logger.error(f"Failed to get CPU usage for {service}: {e}")
            return 0.0

    async def _get_service_load_metrics(self, service: ServiceType) -> Dict[str, float]:
        """Get service load metrics (mock implementation)."""
        # This would integrate with actual system monitoring
        # For demonstration, return reasonable default values
        return {
            "memory_percent": 45.0,
            "cpu_percent": 35.0,
            "disk_usage_percent": 20.0
        }


class AlertManager:
    """Main alert management system."""

    def __init__(self,
                 redis_client: redis.Redis,
                 telemetry_collector: TelemetryCollector,
                 notification_config: Dict[str, Any] = None):
        self.redis_client = redis_client
        self.telemetry_collector = telemetry_collector
        self.metrics_collector = MetricsCollector(redis_client, telemetry_collector)
        self.notification_manager = NotificationManager(notification_config or {})

        # Alert storage
        self.alert_rules: Dict[str, AlertRule] = {}
        self.active_alerts: Dict[str, Alert] = {}

        # Background task management
        self._monitoring_task: Optional[asyncio.Task] = None
        self._running = False

        # Load default alert rules
        self._load_default_rules()

        logger.info("AlertManager initialized")

    def _load_default_rules(self):
        """Load default alert rules for Brain Researcher services."""
        default_rules = [
            AlertRule(
                name="high_response_time",
                threshold=AlertThreshold(
                    metric_name="response_time_ms",
                    operator=">",
                    value=2000.0,  # 2 seconds
                    duration_seconds=300,  # 5 minutes
                    severity=AlertSeverity.WARNING,
                    description="Service response time is too high"
                ),
                service=ServiceType.ORCHESTRATOR,
                notification_channels=[NotificationChannel.EMAIL, NotificationChannel.SLACK]
            ),
            AlertRule(
                name="critical_response_time",
                threshold=AlertThreshold(
                    metric_name="response_time_ms",
                    operator=">",
                    value=5000.0,  # 5 seconds
                    duration_seconds=300,
                    severity=AlertSeverity.CRITICAL,
                    description="Service response time is critically high"
                ),
                service=ServiceType.ORCHESTRATOR,
                notification_channels=[NotificationChannel.EMAIL, NotificationChannel.SLACK]
            ),
            AlertRule(
                name="high_error_rate",
                threshold=AlertThreshold(
                    metric_name="error_rate",
                    operator=">",
                    value=5.0,  # 5%
                    duration_seconds=300,
                    severity=AlertSeverity.WARNING,
                    description="Service error rate is too high"
                ),
                service=ServiceType.ORCHESTRATOR,
                notification_channels=[NotificationChannel.EMAIL, NotificationChannel.SLACK]
            ),
            AlertRule(
                name="critical_error_rate",
                threshold=AlertThreshold(
                    metric_name="error_rate",
                    operator=">",
                    value=15.0,  # 15%
                    duration_seconds=180,  # 3 minutes for critical
                    severity=AlertSeverity.CRITICAL,
                    description="Service error rate is critically high"
                ),
                service=ServiceType.ORCHESTRATOR,
                notification_channels=[NotificationChannel.EMAIL, NotificationChannel.SLACK]
            ),
            AlertRule(
                name="high_memory_usage",
                threshold=AlertThreshold(
                    metric_name="memory_usage_percent",
                    operator=">",
                    value=80.0,  # 80%
                    duration_seconds=600,  # 10 minutes
                    severity=AlertSeverity.WARNING,
                    description="Service memory usage is high"
                ),
                service=ServiceType.ORCHESTRATOR,
                notification_channels=[NotificationChannel.EMAIL]
            ),
            AlertRule(
                name="high_cpu_usage",
                threshold=AlertThreshold(
                    metric_name="cpu_usage_percent",
                    operator=">",
                    value=75.0,  # 75%
                    duration_seconds=600,
                    severity=AlertSeverity.WARNING,
                    description="Service CPU usage is high"
                ),
                service=ServiceType.ORCHESTRATOR,
                notification_channels=[NotificationChannel.EMAIL]
            )
        ]

        # Add rules for all services
        services = [ServiceType.AGENT, ServiceType.BR_KG, ServiceType.WEB_UI, ServiceType.API_GATEWAY]

        for rule in default_rules:
            for service in [ServiceType.ORCHESTRATOR] + services:
                rule_copy = AlertRule(
                    name=f"{service}_{rule.name}",
                    threshold=rule.threshold,
                    service=service,
                    enabled=rule.enabled,
                    cooldown_seconds=rule.cooldown_seconds,
                    notification_channels=rule.notification_channels,
                    tags={"service": service}
                )
                self.alert_rules[rule_copy.name] = rule_copy

        logger.info(f"Loaded {len(self.alert_rules)} default alert rules")

    async def start(self):
        """Start the alert monitoring system."""
        if self._running:
            logger.warning("AlertManager is already running")
            return

        self._running = True
        self._monitoring_task = asyncio.create_task(self._monitoring_loop())
        logger.info("AlertManager started")

    async def stop(self):
        """Stop the alert monitoring system."""
        self._running = False

        if self._monitoring_task:
            self._monitoring_task.cancel()
            try:
                await self._monitoring_task
            except asyncio.CancelledError:
                pass

        logger.info("AlertManager stopped")

    async def _monitoring_loop(self):
        """Main monitoring loop."""
        while self._running:
            try:
                await self._evaluate_all_rules()
                await asyncio.sleep(30)  # Check every 30 seconds
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in monitoring loop: {e}")
                await asyncio.sleep(60)  # Wait longer on error

    async def _evaluate_all_rules(self):
        """Evaluate all alert rules."""
        services = set(rule.service for rule in self.alert_rules.values())

        for service in services:
            try:
                metrics = await self.metrics_collector.get_service_metrics(service)

                service_rules = [rule for rule in self.alert_rules.values()
                               if rule.service == service and rule.enabled]

                for rule in service_rules:
                    await self._evaluate_rule(rule, metrics)

            except Exception as e:
                logger.error(f"Error evaluating rules for {service}: {e}")

    async def _evaluate_rule(self, rule: AlertRule, metrics: Dict[str, float]):
        """Evaluate a single alert rule."""
        try:
            metric_value = metrics.get(rule.threshold.metric_name, 0.0)

            # Check if threshold is breached
            threshold_breached = rule.threshold.evaluate(metric_value, duration_met=True)

            existing_alert = self.active_alerts.get(rule.name)

            if threshold_breached:
                if not existing_alert:
                    # Create new alert
                    alert = Alert(
                        id=f"alert_{int(time.time())}_{rule.name}",
                        rule_name=rule.name,
                        service=rule.service,
                        severity=rule.threshold.severity,
                        status=AlertStatus.ACTIVE,
                        current_value=metric_value,
                        threshold_value=rule.threshold.value,
                        message=f"{rule.threshold.description}. Current: {metric_value}, Threshold: {rule.threshold.value}",
                        triggered_at=datetime.utcnow(),
                        tags=rule.tags.copy()
                    )

                    self.active_alerts[rule.name] = alert
                    await self._trigger_alert(alert, rule)

                elif existing_alert.status == AlertStatus.ACTIVE:
                    # Update existing alert
                    existing_alert.current_value = metric_value

                    # Check if we should send another notification (re-alerting)
                    if self._should_re_alert(existing_alert, rule):
                        await self._trigger_alert(existing_alert, rule)

            else:
                # Threshold not breached
                if existing_alert and existing_alert.status == AlertStatus.ACTIVE:
                    # Resolve alert
                    existing_alert.status = AlertStatus.RESOLVED
                    existing_alert.resolved_at = datetime.utcnow()

                    await self._resolve_alert(existing_alert, rule)

                    # Remove from active alerts after cooldown
                    asyncio.create_task(self._cleanup_resolved_alert(rule.name, rule.cooldown_seconds))

        except Exception as e:
            logger.error(f"Error evaluating rule {rule.name}: {e}")

    def _should_re_alert(self, alert: Alert, rule: AlertRule) -> bool:
        """Check if we should send another notification."""
        if not alert.last_notification:
            return True

        # Re-alert every hour for critical, every 4 hours for warning
        re_alert_interval = 3600 if alert.severity == AlertSeverity.CRITICAL else 14400

        time_since_last = (datetime.utcnow() - alert.last_notification).total_seconds()
        return time_since_last >= re_alert_interval

    async def _trigger_alert(self, alert: Alert, rule: AlertRule):
        """Trigger alert notifications."""
        try:
            logger.warning(f"Alert triggered: {alert.rule_name} - {alert.message}")

            # Send notifications
            for channel in rule.notification_channels:
                success = await self.notification_manager.send_notification(alert, channel)
                if success:
                    alert.last_notification = datetime.utcnow()
                    alert.notification_count += 1

            # Store alert in Redis
            await self._store_alert(alert)

        except Exception as e:
            logger.error(f"Error triggering alert {alert.id}: {e}")

    async def _resolve_alert(self, alert: Alert, rule: AlertRule):
        """Resolve alert and send resolution notifications."""
        try:
            logger.info(f"Alert resolved: {alert.rule_name}")

            # Send resolution notifications
            for channel in rule.notification_channels:
                await self.notification_manager.send_notification(alert, channel, is_resolution=True)

            # Update stored alert
            await self._store_alert(alert)

        except Exception as e:
            logger.error(f"Error resolving alert {alert.id}: {e}")

    async def _cleanup_resolved_alert(self, rule_name: str, delay_seconds: int):
        """Clean up resolved alert after cooldown period."""
        await asyncio.sleep(delay_seconds)
        self.active_alerts.pop(rule_name, None)

    async def _store_alert(self, alert: Alert):
        """Store alert in Redis."""
        try:
            alert_key = f"alert:{alert.id}"
            alert_data = asdict(alert)

            # Convert datetime objects to ISO strings
            alert_data["triggered_at"] = alert.triggered_at.isoformat()
            if alert.resolved_at:
                alert_data["resolved_at"] = alert.resolved_at.isoformat()
            if alert.last_notification:
                alert_data["last_notification"] = alert.last_notification.isoformat()

            # Store alert data
            self.redis_client.hmset(alert_key, {
                k: json.dumps(v) if isinstance(v, (dict, list)) else str(v)
                for k, v in alert_data.items()
            })

            # Set expiration (30 days)
            self.redis_client.expire(alert_key, 30 * 24 * 3600)

            # Add to alerts timeline
            self.redis_client.zadd("alerts:timeline", {alert.id: int(alert.triggered_at.timestamp())})

        except Exception as e:
            logger.error(f"Error storing alert {alert.id}: {e}")

    def get_active_alerts(self) -> List[Alert]:
        """Get all currently active alerts."""
        return [alert for alert in self.active_alerts.values()
                if alert.status == AlertStatus.ACTIVE]

    def get_alert_history(self, hours_back: int = 24) -> List[Alert]:
        """Get alert history."""
        try:
            cutoff_time = int((datetime.utcnow() - timedelta(hours=hours_back)).timestamp())

            alert_ids = self.redis_client.zrangebyscore("alerts:timeline", cutoff_time, "+inf")
            alerts = []

            for alert_id in alert_ids:
                if isinstance(alert_id, bytes):
                    alert_id = alert_id.decode()

                alert_data = self.redis_client.hgetall(f"alert:{alert_id}")
                if alert_data:
                    # Parse alert data
                    parsed_alert = self._parse_stored_alert(alert_data)
                    if parsed_alert:
                        alerts.append(parsed_alert)

            return sorted(alerts, key=lambda x: x.triggered_at, reverse=True)

        except Exception as e:
            logger.error(f"Error getting alert history: {e}")
            return []

    def _parse_stored_alert(self, alert_data: Dict) -> Optional[Alert]:
        """Parse stored alert data."""
        try:
            # Convert byte strings to regular strings
            data = {k.decode() if isinstance(k, bytes) else k:
                   v.decode() if isinstance(v, bytes) else v
                   for k, v in alert_data.items()}

            return Alert(
                id=data['id'],
                rule_name=data['rule_name'],
                service=ServiceType(data['service']),
                severity=AlertSeverity(data['severity']),
                status=AlertStatus(data['status']),
                current_value=float(data['current_value']),
                threshold_value=float(data['threshold_value']),
                message=data['message'],
                triggered_at=datetime.fromisoformat(data['triggered_at']),
                resolved_at=datetime.fromisoformat(data['resolved_at']) if data.get('resolved_at') and data['resolved_at'] != 'None' else None,
                last_notification=datetime.fromisoformat(data['last_notification']) if data.get('last_notification') and data['last_notification'] != 'None' else None,
                notification_count=int(data.get('notification_count', 0)),
                tags=json.loads(data.get('tags', '{}'))
            )
        except Exception as e:
            logger.error(f"Error parsing stored alert: {e}")
            return None

    def add_rule(self, rule: AlertRule):
        """Add a new alert rule."""
        self.alert_rules[rule.name] = rule
        logger.info(f"Added alert rule: {rule.name}")

    def remove_rule(self, rule_name: str):
        """Remove an alert rule."""
        if rule_name in self.alert_rules:
            del self.alert_rules[rule_name]

            # Also remove any active alert for this rule
            if rule_name in self.active_alerts:
                del self.active_alerts[rule_name]

            logger.info(f"Removed alert rule: {rule_name}")

    def enable_rule(self, rule_name: str):
        """Enable an alert rule."""
        if rule_name in self.alert_rules:
            self.alert_rules[rule_name].enabled = True
            logger.info(f"Enabled alert rule: {rule_name}")

    def disable_rule(self, rule_name: str):
        """Disable an alert rule."""
        if rule_name in self.alert_rules:
            self.alert_rules[rule_name].enabled = False
            logger.info(f"Disabled alert rule: {rule_name}")

    def get_alert_stats(self) -> Dict[str, Any]:
        """Get alert system statistics."""
        return {
            "total_rules": len(self.alert_rules),
            "enabled_rules": len([r for r in self.alert_rules.values() if r.enabled]),
            "active_alerts": len(self.get_active_alerts()),
            "alerts_last_24h": len(self.get_alert_history(24)),
            "rules_by_severity": {
                severity: len([r for r in self.alert_rules.values()
                             if r.threshold.severity == severity])
                for severity in AlertSeverity
            }
        }
