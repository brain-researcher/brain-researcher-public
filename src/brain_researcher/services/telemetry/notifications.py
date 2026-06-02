"""
Notification System for Alert Management

This module provides advanced notification capabilities for the alert system,
including rate limiting, notification templates, and delivery tracking.
"""

import asyncio
import json
import logging
import smtplib
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from enum import Enum
from typing import Any, Dict, List, Optional, Union

import redis
import requests
from jinja2 import DictLoader, Environment, Template
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from .alerts import Alert, AlertSeverity, NotificationChannel

logger = logging.getLogger(__name__)


@dataclass
class NotificationTemplate:
    """Notification template configuration."""

    name: str
    channel: NotificationChannel
    subject_template: str
    body_template: str
    variables: Dict[str, Any] = None

    def __post_init__(self):
        if self.variables is None:
            self.variables = {}


@dataclass
class NotificationResult:
    """Result of notification delivery attempt."""

    notification_id: str
    channel: NotificationChannel
    success: bool
    delivered_at: Optional[datetime] = None
    error_message: Optional[str] = None
    retry_count: int = 0
    next_retry: Optional[datetime] = None


@dataclass
class NotificationConfig:
    """Notification system configuration."""

    # Rate limiting
    max_notifications_per_hour: int = 100
    max_notifications_per_alert_per_hour: int = 5

    # Retry configuration
    max_retries: int = 3
    retry_delay_seconds: int = 300  # 5 minutes
    exponential_backoff: bool = True

    # Notification grouping
    enable_grouping: bool = True
    grouping_window_minutes: int = 15
    max_group_size: int = 10

    # Channel configurations
    email: Dict[str, Any] = None
    slack: Dict[str, Any] = None
    webhook: Dict[str, Any] = None
    discord: Dict[str, Any] = None

    def __post_init__(self):
        if self.email is None:
            self.email = {
                "enabled": False,
                "smtp_host": "localhost",
                "smtp_port": 587,
                "use_tls": True,
                "from_address": "alerts@brain-researcher.ai",
                "to_addresses": [],
                "username": "",
                "password": "",
            }
        if self.slack is None:
            self.slack = {
                "enabled": False,
                "webhook_url": "",
                "channel": "#alerts",
                "username": "Brain Researcher Alerts",
                "icon_emoji": ":warning:",
            }
        if self.webhook is None:
            self.webhook = {"enabled": False, "url": "", "headers": {}, "timeout": 30}
        if self.discord is None:
            self.discord = {
                "enabled": False,
                "webhook_url": "",
                "username": "Brain Researcher",
            }


class NotificationTemplateManager:
    """Manages notification templates and rendering."""

    def __init__(self):
        self.templates = {}
        self.jinja_env = Environment(loader=DictLoader({}))
        self._load_default_templates()

    def _load_default_templates(self):
        """Load default notification templates."""

        # Email templates
        self.add_template(
            NotificationTemplate(
                name="alert_triggered_email",
                channel=NotificationChannel.EMAIL,
                subject_template="[Brain Researcher] Alert: {{ alert.rule_name }}",
                body_template="""
<!DOCTYPE html>
<html>
<head>
    <style>
        body { font-family: Arial, sans-serif; }
        .alert-box { background-color: {% if alert.severity == 'critical' %}#ffebee{% elif alert.severity == 'warning' %}#fff3e0{% else %}#e8f5e8{% endif %}; padding: 20px; border-radius: 5px; margin: 10px 0; }
        .severity { color: {% if alert.severity == 'critical' %}#d32f2f{% elif alert.severity == 'warning' %}#f57c00{% else %}#388e3c{% endif %}; font-weight: bold; }
        .details { background-color: #f5f5f5; padding: 15px; border-radius: 3px; margin: 10px 0; }
    </style>
</head>
<body>
    <div class="alert-box">
        <h2>🚨 Alert Triggered</h2>
        <p><strong>Alert Name:</strong> {{ alert.rule_name }}</p>
        <p><strong>Severity:</strong> <span class="severity">{{ alert.severity|upper }}</span></p>
        <p><strong>Service:</strong> {{ alert.service }}</p>
        <p><strong>Current Value:</strong> {{ alert.current_value }}</p>
        <p><strong>Threshold:</strong> {{ alert.threshold_value }}</p>
        <p><strong>Triggered At:</strong> {{ alert.triggered_at.strftime('%Y-%m-%d %H:%M:%S UTC') }}</p>

        <div class="details">
            <strong>Message:</strong><br>
            {{ alert.message }}
        </div>

        {% if alert.tags %}
        <p><strong>Tags:</strong>
        {% for key, value in alert.tags.items() %}
            {{ key }}={{ value }}{% if not loop.last %}, {% endif %}
        {% endfor %}
        </p>
        {% endif %}

        <p><small>This is an automated alert from Brain Researcher monitoring system.</small></p>
    </div>
</body>
</html>
            """,
            )
        )

        self.add_template(
            NotificationTemplate(
                name="alert_resolved_email",
                channel=NotificationChannel.EMAIL,
                subject_template="[Brain Researcher] RESOLVED: {{ alert.rule_name }}",
                body_template="""
<!DOCTYPE html>
<html>
<head>
    <style>
        body { font-family: Arial, sans-serif; }
        .resolved-box { background-color: #e8f5e8; padding: 20px; border-radius: 5px; margin: 10px 0; border-left: 5px solid #4caf50; }
        .details { background-color: #f5f5f5; padding: 15px; border-radius: 3px; margin: 10px 0; }
    </style>
</head>
<body>
    <div class="resolved-box">
        <h2>✅ Alert Resolved</h2>
        <p><strong>Alert Name:</strong> {{ alert.rule_name }}</p>
        <p><strong>Service:</strong> {{ alert.service }}</p>
        <p><strong>Resolved At:</strong> {{ alert.resolved_at.strftime('%Y-%m-%d %H:%M:%S UTC') }}</p>
        <p><strong>Duration:</strong> {{ ((alert.resolved_at - alert.triggered_at).total_seconds() / 60) | round(1) }} minutes</p>

        <div class="details">
            <strong>Original Message:</strong><br>
            {{ alert.message }}
        </div>

        <p><small>Alert automatically resolved by Brain Researcher monitoring system.</small></p>
    </div>
</body>
</html>
            """,
            )
        )

        # Slack templates
        self.add_template(
            NotificationTemplate(
                name="alert_triggered_slack",
                channel=NotificationChannel.SLACK,
                subject_template="",  # Slack doesn't use subjects
                body_template="""
{
    "channel": "{{ config.slack.channel }}",
    "username": "{{ config.slack.username }}",
    "icon_emoji": "{{ config.slack.icon_emoji }}",
    "attachments": [
        {
            "color": "{% if alert.severity == 'critical' %}danger{% elif alert.severity == 'warning' %}warning{% else %}good{% endif %}",
            "title": "🚨 Alert Triggered: {{ alert.rule_name }}",
            "text": "{{ alert.message }}",
            "fields": [
                {
                    "title": "Service",
                    "value": "{{ alert.service }}",
                    "short": true
                },
                {
                    "title": "Severity",
                    "value": "{{ alert.severity|upper }}",
                    "short": true
                },
                {
                    "title": "Current Value",
                    "value": "{{ alert.current_value }}",
                    "short": true
                },
                {
                    "title": "Threshold",
                    "value": "{{ alert.threshold_value }}",
                    "short": true
                }
            ],
            "footer": "Brain Researcher Monitoring",
            "ts": {{ alert.triggered_at.timestamp() | int }}
        }
    ]
}
            """,
            )
        )

        # Webhook templates
        self.add_template(
            NotificationTemplate(
                name="alert_triggered_webhook",
                channel=NotificationChannel.WEBHOOK,
                subject_template="",
                body_template="""
{
    "event_type": "alert_triggered",
    "alert_id": "{{ alert.id }}",
    "alert_name": "{{ alert.rule_name }}",
    "service": "{{ alert.service }}",
    "severity": "{{ alert.severity }}",
    "current_value": {{ alert.current_value }},
    "threshold_value": {{ alert.threshold_value }},
    "message": "{{ alert.message }}",
    "triggered_at": "{{ alert.triggered_at.isoformat() }}",
    "tags": {{ alert.tags | tojson }},
    "system": "brain-researcher",
    "version": "1.0"
}
            """,
            )
        )

    def add_template(self, template: NotificationTemplate):
        """Add a notification template."""
        key = f"{template.name}_{template.channel}"
        self.templates[key] = template

        # Add to Jinja environment
        self.jinja_env.loader.mapping[f"{key}_subject"] = template.subject_template
        self.jinja_env.loader.mapping[f"{key}_body"] = template.body_template

    def render_notification(
        self,
        template_name: str,
        channel: NotificationChannel,
        alert: Alert,
        config: NotificationConfig,
        **kwargs,
    ) -> tuple[str, str]:
        """Render notification subject and body."""
        key = f"{template_name}_{channel}"

        if key not in self.templates:
            raise ValueError(f"Template {key} not found")

        template_vars = {"alert": alert, "config": config, **kwargs}

        try:
            subject_template = self.jinja_env.get_template(f"{key}_subject")
            body_template = self.jinja_env.get_template(f"{key}_body")

            subject = subject_template.render(**template_vars)
            body = body_template.render(**template_vars)

            return subject.strip(), body.strip()

        except Exception as e:
            logger.error(f"Error rendering template {key}: {e}")
            raise


class NotificationDelivery:
    """Handles notification delivery with retry logic and rate limiting."""

    def __init__(self, config: NotificationConfig, redis_client: redis.Redis):
        self.config = config
        self.redis_client = redis_client
        self.session = self._create_http_session()

    def _create_http_session(self) -> requests.Session:
        """Create HTTP session with retry configuration."""
        session = requests.Session()

        retry_strategy = Retry(
            total=self.config.max_retries,
            status_forcelist=[429, 500, 502, 503, 504],
            method_whitelist=["HEAD", "GET", "POST"],
            backoff_factor=1 if self.config.exponential_backoff else 0,
        )

        adapter = HTTPAdapter(max_retries=retry_strategy)
        session.mount("http://", adapter)
        session.mount("https://", adapter)

        return session

    async def deliver_notification(
        self,
        notification_id: str,
        channel: NotificationChannel,
        subject: str,
        body: str,
        alert: Alert,
    ) -> NotificationResult:
        """Deliver notification through specified channel."""

        # Check rate limits
        if not self._check_rate_limits(alert, channel):
            return NotificationResult(
                notification_id=notification_id,
                channel=channel,
                success=False,
                error_message="Rate limit exceeded",
            )

        try:
            if channel == NotificationChannel.EMAIL:
                success = await self._send_email(subject, body, alert)
            elif channel == NotificationChannel.SLACK:
                success = await self._send_slack(body, alert)
            elif channel == NotificationChannel.WEBHOOK:
                success = await self._send_webhook(body, alert)
            elif channel == NotificationChannel.DISCORD:
                success = await self._send_discord(subject, body, alert)
            else:
                raise ValueError(f"Unsupported notification channel: {channel}")

            result = NotificationResult(
                notification_id=notification_id,
                channel=channel,
                success=success,
                delivered_at=datetime.utcnow() if success else None,
            )

            # Update rate limiting counters
            if success:
                self._update_rate_limit_counters(alert, channel)

            # Store delivery result
            await self._store_delivery_result(result)

            return result

        except Exception as e:
            logger.error(f"Error delivering notification {notification_id}: {e}")
            return NotificationResult(
                notification_id=notification_id,
                channel=channel,
                success=False,
                error_message=str(e),
            )

    async def _send_email(self, subject: str, body: str, alert: Alert) -> bool:
        """Send email notification."""
        if not self.config.email.get("enabled", False):
            return False

        try:
            msg = MIMEMultipart()
            msg["From"] = self.config.email["from_address"]
            msg["To"] = ", ".join(self.config.email["to_addresses"])
            msg["Subject"] = subject

            msg.attach(MIMEText(body, "html"))

            server = smtplib.SMTP(
                self.config.email["smtp_host"], self.config.email["smtp_port"]
            )

            if self.config.email.get("use_tls", True):
                server.starttls()

            if self.config.email.get("username"):
                server.login(
                    self.config.email["username"], self.config.email["password"]
                )

            server.sendmail(
                msg["From"], self.config.email["to_addresses"], msg.as_string()
            )
            server.quit()

            logger.info(f"Email notification sent for alert {alert.id}")
            return True

        except Exception as e:
            logger.error(f"Failed to send email notification: {e}")
            return False

    async def _send_slack(self, body: str, alert: Alert) -> bool:
        """Send Slack notification."""
        if not self.config.slack.get("enabled", False):
            return False

        try:
            # Parse JSON body
            payload = json.loads(body)

            response = self.session.post(
                self.config.slack["webhook_url"], json=payload, timeout=30
            )
            response.raise_for_status()

            logger.info(f"Slack notification sent for alert {alert.id}")
            return True

        except Exception as e:
            logger.error(f"Failed to send Slack notification: {e}")
            return False

    async def _send_webhook(self, body: str, alert: Alert) -> bool:
        """Send webhook notification."""
        if not self.config.webhook.get("enabled", False):
            return False

        try:
            # Parse JSON body
            payload = json.loads(body)

            headers = self.config.webhook.get("headers", {})
            headers.setdefault("Content-Type", "application/json")

            response = self.session.post(
                self.config.webhook["url"],
                json=payload,
                headers=headers,
                timeout=self.config.webhook.get("timeout", 30),
            )
            response.raise_for_status()

            logger.info(f"Webhook notification sent for alert {alert.id}")
            return True

        except Exception as e:
            logger.error(f"Failed to send webhook notification: {e}")
            return False

    async def _send_discord(self, subject: str, body: str, alert: Alert) -> bool:
        """Send Discord notification."""
        if not self.config.discord.get("enabled", False):
            return False

        try:
            # Create Discord embed format
            color_map = {
                AlertSeverity.CRITICAL: 0xFF0000,  # Red
                AlertSeverity.WARNING: 0xFFA500,  # Orange
                AlertSeverity.INFO: 0x00FF00,  # Green
            }

            payload = {
                "username": self.config.discord.get("username", "Brain Researcher"),
                "embeds": [
                    {
                        "title": f"🚨 {subject}",
                        "description": alert.message,
                        "color": color_map.get(AlertSeverity(alert.severity), 0x808080),
                        "fields": [
                            {"name": "Service", "value": alert.service, "inline": True},
                            {
                                "name": "Severity",
                                "value": alert.severity.upper(),
                                "inline": True,
                            },
                            {
                                "name": "Current Value",
                                "value": str(alert.current_value),
                                "inline": True,
                            },
                            {
                                "name": "Threshold",
                                "value": str(alert.threshold_value),
                                "inline": True,
                            },
                        ],
                        "timestamp": alert.triggered_at.isoformat(),
                        "footer": {"text": "Brain Researcher Monitoring"},
                    }
                ],
            }

            response = self.session.post(
                self.config.discord["webhook_url"], json=payload, timeout=30
            )
            response.raise_for_status()

            logger.info(f"Discord notification sent for alert {alert.id}")
            return True

        except Exception as e:
            logger.error(f"Failed to send Discord notification: {e}")
            return False

    def _check_rate_limits(self, alert: Alert, channel: NotificationChannel) -> bool:
        """Check if notification is within rate limits."""
        now = int(time.time())
        hour_ago = now - 3600

        # Check global rate limit
        global_key = f"notifications:global:{now // 3600}"
        global_count = self.redis_client.get(global_key) or 0
        if int(global_count) >= self.config.max_notifications_per_hour:
            logger.warning("Global notification rate limit exceeded")
            return False

        # Check per-alert rate limit
        alert_key = f"notifications:alert:{alert.rule_name}:{now // 3600}"
        alert_count = self.redis_client.get(alert_key) or 0
        if int(alert_count) >= self.config.max_notifications_per_alert_per_hour:
            logger.warning(f"Rate limit exceeded for alert {alert.rule_name}")
            return False

        return True

    def _update_rate_limit_counters(self, alert: Alert, channel: NotificationChannel):
        """Update rate limiting counters."""
        now = int(time.time())
        hour_key = now // 3600

        # Update global counter
        global_key = f"notifications:global:{hour_key}"
        self.redis_client.incr(global_key)
        self.redis_client.expire(global_key, 7200)  # 2 hours

        # Update per-alert counter
        alert_key = f"notifications:alert:{alert.rule_name}:{hour_key}"
        self.redis_client.incr(alert_key)
        self.redis_client.expire(alert_key, 7200)

        # Update channel counter
        channel_key = f"notifications:channel:{channel}:{hour_key}"
        self.redis_client.incr(channel_key)
        self.redis_client.expire(channel_key, 7200)

    async def _store_delivery_result(self, result: NotificationResult):
        """Store notification delivery result."""
        try:
            key = f"notification_result:{result.notification_id}"
            data = asdict(result)

            # Convert datetime to ISO string
            if data["delivered_at"]:
                data["delivered_at"] = result.delivered_at.isoformat()
            if data["next_retry"]:
                data["next_retry"] = result.next_retry.isoformat()

            self.redis_client.hmset(
                key,
                {
                    k: json.dumps(v) if isinstance(v, (dict, list)) else str(v)
                    for k, v in data.items()
                },
            )

            # Expire after 7 days
            self.redis_client.expire(key, 7 * 24 * 3600)

        except Exception as e:
            logger.error(f"Error storing delivery result: {e}")


class NotificationManager:
    """Main notification management system."""

    def __init__(self, config: NotificationConfig, redis_client: redis.Redis):
        self.config = config
        self.redis_client = redis_client
        self.template_manager = NotificationTemplateManager()
        self.delivery = NotificationDelivery(config, redis_client)

        logger.info("NotificationManager initialized")

    async def send_alert_notification(
        self,
        alert: Alert,
        channels: List[NotificationChannel],
        is_resolution: bool = False,
    ) -> List[NotificationResult]:
        """Send alert notification through multiple channels."""

        template_suffix = "resolved" if is_resolution else "triggered"
        results = []

        for channel in channels:
            try:
                notification_id = f"notif_{int(time.time())}_{alert.id}_{channel}"
                template_name = f"alert_{template_suffix}_{channel}"

                # Render notification content
                subject, body = self.template_manager.render_notification(
                    template_name, channel, alert, self.config
                )

                # Deliver notification
                result = await self.delivery.deliver_notification(
                    notification_id, channel, subject, body, alert
                )

                results.append(result)

                if result.success:
                    logger.info(
                        f"Successfully sent {channel} notification for alert {alert.id}"
                    )
                else:
                    logger.error(
                        f"Failed to send {channel} notification: {result.error_message}"
                    )

            except Exception as e:
                logger.error(
                    f"Error sending {channel} notification for alert {alert.id}: {e}"
                )
                results.append(
                    NotificationResult(
                        notification_id=f"error_{int(time.time())}_{alert.id}_{channel}",
                        channel=channel,
                        success=False,
                        error_message=str(e),
                    )
                )

        return results

    async def send_grouped_notification(
        self, alerts: List[Alert], channels: List[NotificationChannel]
    ) -> List[NotificationResult]:
        """Send grouped notification for multiple alerts."""

        if not alerts:
            return []

        # Create summary alert for grouping
        summary_alert = Alert(
            id=f"group_{int(time.time())}",
            rule_name=f"Multiple Alerts ({len(alerts)} alerts)",
            service=(
                alerts[0].service
                if len(set(a.service for a in alerts)) == 1
                else "mixed"
            ),
            severity=max(AlertSeverity(a.severity) for a in alerts),
            status=alerts[0].status,
            current_value=0,
            threshold_value=0,
            message=f"Group of {len(alerts)} alerts triggered",
            triggered_at=min(a.triggered_at for a in alerts),
            tags={"grouped": True, "alert_count": len(alerts)},
        )

        # Send using grouped template (would need to create these)
        return await self.send_alert_notification(summary_alert, channels)

    def get_notification_stats(self, hours_back: int = 24) -> Dict[str, Any]:
        """Get notification system statistics."""
        now = int(time.time())
        hours_keys = [now // 3600 - h for h in range(hours_back)]

        total_notifications = 0
        channel_stats = {}

        for hour_key in hours_keys:
            # Global notifications
            global_key = f"notifications:global:{hour_key}"
            count = self.redis_client.get(global_key) or 0
            total_notifications += int(count)

            # Channel stats
            for channel in NotificationChannel:
                channel_key = f"notifications:channel:{channel}:{hour_key}"
                count = self.redis_client.get(channel_key) or 0
                channel_stats.setdefault(channel, 0)
                channel_stats[channel] += int(count)

        return {
            "total_notifications_sent": total_notifications,
            "notifications_by_channel": channel_stats,
            "rate_limit_config": {
                "max_per_hour": self.config.max_notifications_per_hour,
                "max_per_alert_per_hour": self.config.max_notifications_per_alert_per_hour,
            },
            "enabled_channels": [
                channel
                for channel in NotificationChannel
                if self.config.__dict__.get(channel, {}).get("enabled", False)
            ],
        }


def create_notification_config_from_env() -> NotificationConfig:
    """Create notification configuration from environment variables."""
    import os

    return NotificationConfig(
        max_notifications_per_hour=int(
            os.environ.get("NOTIFICATION_MAX_PER_HOUR", "100")
        ),
        max_notifications_per_alert_per_hour=int(
            os.environ.get("NOTIFICATION_MAX_PER_ALERT_PER_HOUR", "5")
        ),
        enable_grouping=os.environ.get("NOTIFICATION_GROUPING", "true").lower()
        == "true",
        email={
            "enabled": os.environ.get("EMAIL_NOTIFICATIONS_ENABLED", "false").lower()
            == "true",
            "smtp_host": os.environ.get("SMTP_HOST", "localhost"),
            "smtp_port": int(os.environ.get("SMTP_PORT", "587")),
            "use_tls": os.environ.get("SMTP_USE_TLS", "true").lower() == "true",
            "from_address": os.environ.get(
                "SMTP_FROM_ADDRESS", "alerts@brain-researcher.ai"
            ),
            "to_addresses": os.environ.get("ALERT_EMAIL_RECIPIENTS", "").split(","),
            "username": os.environ.get("SMTP_USERNAME", ""),
            "password": os.environ.get("SMTP_PASSWORD", ""),
        },
        slack={
            "enabled": os.environ.get("SLACK_NOTIFICATIONS_ENABLED", "false").lower()
            == "true",
            "webhook_url": os.environ.get("SLACK_WEBHOOK_URL", ""),
            "channel": os.environ.get("SLACK_CHANNEL", "#alerts"),
            "username": os.environ.get("SLACK_USERNAME", "Brain Researcher Alerts"),
        },
        webhook={
            "enabled": os.environ.get("WEBHOOK_NOTIFICATIONS_ENABLED", "false").lower()
            == "true",
            "url": os.environ.get("WEBHOOK_URL", ""),
            "headers": json.loads(os.environ.get("WEBHOOK_HEADERS", "{}")),
            "timeout": int(os.environ.get("WEBHOOK_TIMEOUT", "30")),
        },
        discord={
            "enabled": os.environ.get("DISCORD_NOTIFICATIONS_ENABLED", "false").lower()
            == "true",
            "webhook_url": os.environ.get("DISCORD_WEBHOOK_URL", ""),
            "username": os.environ.get("DISCORD_USERNAME", "Brain Researcher"),
        },
    )
