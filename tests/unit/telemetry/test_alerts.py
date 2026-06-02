"""
Unit tests for Alert Management System (TELEMETRY-001)
Tests alert thresholds, notifications, and dashboard configurations
"""

import asyncio
import json
from datetime import datetime, timedelta
from typing import Any, Dict
from unittest.mock import AsyncMock, MagicMock, Mock, patch

import pytest

from brain_researcher.services.telemetry.alerts import (
    Alert,
    AlertManager,
    AlertRule,
    AlertSeverity,
    AlertStatus,
    AlertThreshold,
    MetricsCollector,
    NotificationChannel,
    NotificationManager,
)
from brain_researcher.services.telemetry.models import ServiceType


@pytest.fixture
def mock_redis():
    """Create mock Redis client."""
    redis_mock = MagicMock()
    redis_mock.hmset = MagicMock()
    redis_mock.expire = MagicMock()
    redis_mock.zadd = MagicMock()
    redis_mock.zrangebyscore = MagicMock(return_value=[])
    redis_mock.hgetall = MagicMock(return_value={})
    redis_mock.get = MagicMock(return_value=None)
    return redis_mock


@pytest.fixture
def mock_telemetry_collector():
    """Create mock telemetry collector."""
    collector_mock = MagicMock()
    collector_mock.get_stats = MagicMock(
        return_value={
            "events_collected": 1000,
            "avg_processing_time_ms": 25,
            "buffer_size": 500,
        }
    )
    return collector_mock


@pytest.fixture
def notification_config():
    """Create notification configuration."""
    return {
        "smtp": {
            "enabled": True,
            "host": "smtp.test.com",
            "port": 587,
            "use_tls": True,
            "from_address": "alerts@test.com",
            "to_addresses": ["admin@test.com"],
            "username": "test_user",
            "password": "test_pass",
        },
        "slack": {
            "enabled": True,
            "webhook_url": "https://hooks.slack.com/test",
            "channel": "#alerts",
        },
        "webhook": {
            "enabled": True,
            "url": "https://webhook.test.com/alerts",
            "headers": {"Authorization": "Bearer test"},
        },
    }


@pytest.fixture
async def alert_manager(mock_redis, mock_telemetry_collector, notification_config):
    """Create AlertManager instance."""
    manager = AlertManager(
        redis_client=mock_redis,
        telemetry_collector=mock_telemetry_collector,
        notification_config=notification_config,
    )
    yield manager
    if manager._running:
        await manager.stop()


class TestAlertThreshold:
    """Test AlertThreshold evaluation logic."""

    def test_threshold_greater_than(self):
        """Test greater than operator."""
        threshold = AlertThreshold(
            metric_name="response_time", operator=">", value=2000.0
        )
        assert threshold.evaluate(2500.0) == True
        assert threshold.evaluate(1500.0) == False
        assert threshold.evaluate(2000.0) == False

    def test_threshold_less_than(self):
        """Test less than operator."""
        threshold = AlertThreshold(metric_name="success_rate", operator="<", value=95.0)
        assert threshold.evaluate(90.0) == True
        assert threshold.evaluate(98.0) == False

    def test_threshold_with_duration(self):
        """Test threshold with duration requirement."""
        threshold = AlertThreshold(
            metric_name="error_rate", operator=">=", value=5.0, duration_seconds=300
        )
        assert threshold.evaluate(6.0, duration_met=True) == True
        assert threshold.evaluate(6.0, duration_met=False) == False


class TestNotificationManager:
    """Test notification sending functionality."""

    @pytest.mark.asyncio
    async def test_send_email_notification(self, notification_config):
        """Test email notification."""
        manager = NotificationManager(notification_config)

        alert = Alert(
            id="test_alert_1",
            rule_name="high_response_time",
            service=ServiceType.ORCHESTRATOR,
            severity=AlertSeverity.WARNING,
            status=AlertStatus.ACTIVE,
            current_value=3000.0,
            threshold_value=2000.0,
            message="Response time is too high",
            triggered_at=datetime.utcnow(),
        )

        with patch("smtplib.SMTP") as mock_smtp:
            smtp_instance = mock_smtp.return_value
            result = await manager.send_notification(alert, NotificationChannel.EMAIL)
            assert result == True
            mock_smtp.assert_called_with("smtp.test.com", 587)
            smtp_instance.starttls.assert_called_once()

    @pytest.mark.asyncio
    async def test_send_slack_notification(self, notification_config):
        """Test Slack notification."""
        manager = NotificationManager(notification_config)

        alert = Alert(
            id="test_alert_2",
            rule_name="critical_error_rate",
            service=ServiceType.AGENT,
            severity=AlertSeverity.CRITICAL,
            status=AlertStatus.ACTIVE,
            current_value=15.0,
            threshold_value=5.0,
            message="Error rate critically high",
            triggered_at=datetime.utcnow(),
        )

        with patch("requests.post") as mock_post:
            mock_post.return_value.status_code = 200
            result = await manager.send_notification(alert, NotificationChannel.SLACK)
            assert result == True
            mock_post.assert_called_once()

            # Check payload structure
            call_args = mock_post.call_args
            payload = call_args.kwargs["json"]
            assert payload["channel"] == "#alerts"
            assert "Critical" in payload["attachments"][0]["title"]

    @pytest.mark.asyncio
    async def test_send_webhook_notification(self, notification_config):
        """Test webhook notification."""
        manager = NotificationManager(notification_config)

        alert = Alert(
            id="test_alert_3",
            rule_name="high_memory",
            service=ServiceType.BR_KG,
            severity=AlertSeverity.WARNING,
            status=AlertStatus.ACTIVE,
            current_value=85.0,
            threshold_value=80.0,
            message="Memory usage high",
            triggered_at=datetime.utcnow(),
        )

        with patch("requests.post") as mock_post:
            mock_post.return_value.status_code = 200
            result = await manager.send_notification(alert, NotificationChannel.WEBHOOK)
            assert result == True

            call_args = mock_post.call_args
            assert call_args.kwargs["json"]["is_resolution"] == False
            assert "Authorization" in call_args.kwargs["headers"]


class TestMetricsCollector:
    """Test metrics collection and aggregation."""

    @pytest.mark.asyncio
    async def test_get_service_metrics(self, mock_redis, mock_telemetry_collector):
        """Test service metrics collection."""
        collector = MetricsCollector(mock_redis, mock_telemetry_collector)

        # Mock Redis responses
        mock_redis.zrangebyscore.return_value = [b"req_1", b"req_2"]
        mock_redis.get.side_effect = [
            json.dumps(
                {
                    "service": ServiceType.ORCHESTRATOR,
                    "duration_ms": 1500,
                    "status_code": 200,
                }
            ),
            json.dumps(
                {
                    "service": ServiceType.ORCHESTRATOR,
                    "duration_ms": 2500,
                    "status_code": 500,
                    "error": True,
                }
            ),
        ]

        metrics = await collector.get_service_metrics(ServiceType.ORCHESTRATOR, 5)

        assert "response_time_ms" in metrics
        assert "error_rate" in metrics
        assert "memory_usage_percent" in metrics
        assert "cpu_usage_percent" in metrics
        assert metrics["response_time_ms"] == 2000.0  # Average of 1500 and 2500
        assert metrics["error_rate"] == 50.0  # 1 error out of 2 requests

    @pytest.mark.asyncio
    async def test_calculate_error_rate(self, mock_redis, mock_telemetry_collector):
        """Test error rate calculation."""
        collector = MetricsCollector(mock_redis, mock_telemetry_collector)

        mock_redis.zrangebyscore.return_value = [b"req_1", b"req_2", b"req_3"]
        mock_redis.get.side_effect = [
            json.dumps({"service": ServiceType.API_GATEWAY, "status_code": 200}),
            json.dumps({"service": ServiceType.API_GATEWAY, "status_code": 404}),
            json.dumps({"service": ServiceType.API_GATEWAY, "status_code": 500}),
        ]

        error_rate = await collector._calculate_error_rate(ServiceType.API_GATEWAY, 5)
        assert pytest.approx(error_rate, 0.1) == 66.67  # 2 errors out of 3 requests


class TestAlertManager:
    """Test AlertManager functionality."""

    def test_load_default_rules(self, alert_manager):
        """Test default alert rules are loaded."""
        assert len(alert_manager.alert_rules) > 0

        # Check for specific rule types
        rule_names = list(alert_manager.alert_rules.keys())
        assert any("high_response_time" in name for name in rule_names)
        assert any("high_error_rate" in name for name in rule_names)
        assert any("high_memory_usage" in name for name in rule_names)
        assert any("high_cpu_usage" in name for name in rule_names)

    @pytest.mark.asyncio
    async def test_start_stop(self, alert_manager):
        """Test starting and stopping alert manager."""
        await alert_manager.start()
        assert alert_manager._running == True
        assert alert_manager._monitoring_task is not None

        await alert_manager.stop()
        assert alert_manager._running == False

    @pytest.mark.asyncio
    async def test_evaluate_rule_threshold_breached(self, alert_manager):
        """Test rule evaluation when threshold is breached."""
        rule = AlertRule(
            name="test_high_response",
            threshold=AlertThreshold(
                metric_name="response_time_ms",
                operator=">",
                value=1000.0,
                severity=AlertSeverity.WARNING,
            ),
            service=ServiceType.ORCHESTRATOR,
        )

        metrics = {"response_time_ms": 2000.0}

        with patch.object(alert_manager, "_trigger_alert") as mock_trigger:
            await alert_manager._evaluate_rule(rule, metrics)
            mock_trigger.assert_called_once()

            # Check alert was created
            assert rule.name in alert_manager.active_alerts
            alert = alert_manager.active_alerts[rule.name]
            assert alert.current_value == 2000.0
            assert alert.status == AlertStatus.ACTIVE

    @pytest.mark.asyncio
    async def test_evaluate_rule_threshold_resolved(self, alert_manager):
        """Test rule evaluation when threshold is resolved."""
        rule_name = "test_error_rate"

        # Create an active alert
        existing_alert = Alert(
            id="existing_alert",
            rule_name=rule_name,
            service=ServiceType.AGENT,
            severity=AlertSeverity.WARNING,
            status=AlertStatus.ACTIVE,
            current_value=10.0,
            threshold_value=5.0,
            message="Error rate high",
            triggered_at=datetime.utcnow(),
        )
        alert_manager.active_alerts[rule_name] = existing_alert

        rule = AlertRule(
            name=rule_name,
            threshold=AlertThreshold(metric_name="error_rate", operator=">", value=5.0),
            service=ServiceType.AGENT,
        )

        metrics = {"error_rate": 3.0}  # Below threshold

        with patch.object(alert_manager, "_resolve_alert") as mock_resolve:
            await alert_manager._evaluate_rule(rule, metrics)
            mock_resolve.assert_called_once()
            assert existing_alert.status == AlertStatus.RESOLVED

    def test_should_re_alert(self, alert_manager):
        """Test re-alerting logic."""
        rule = AlertRule(
            name="test_rule",
            threshold=AlertThreshold("metric", ">", 10.0),
            service=ServiceType.ORCHESTRATOR,
        )

        # Alert with no previous notification
        alert1 = Alert(
            id="alert1",
            rule_name="test",
            service=ServiceType.ORCHESTRATOR,
            severity=AlertSeverity.WARNING,
            status=AlertStatus.ACTIVE,
            current_value=15.0,
            threshold_value=10.0,
            message="Test",
            triggered_at=datetime.utcnow(),
        )
        assert alert_manager._should_re_alert(alert1, rule) == True

        # Critical alert after 1 hour
        alert2 = Alert(
            id="alert2",
            rule_name="test",
            service=ServiceType.ORCHESTRATOR,
            severity=AlertSeverity.CRITICAL,
            status=AlertStatus.ACTIVE,
            current_value=15.0,
            threshold_value=10.0,
            message="Test",
            triggered_at=datetime.utcnow(),
            last_notification=datetime.utcnow() - timedelta(hours=1, minutes=1),
        )
        assert alert_manager._should_re_alert(alert2, rule) == True

        # Warning alert after 3 hours (not 4)
        alert3 = Alert(
            id="alert3",
            rule_name="test",
            service=ServiceType.ORCHESTRATOR,
            severity=AlertSeverity.WARNING,
            status=AlertStatus.ACTIVE,
            current_value=15.0,
            threshold_value=10.0,
            message="Test",
            triggered_at=datetime.utcnow(),
            last_notification=datetime.utcnow() - timedelta(hours=3),
        )
        assert alert_manager._should_re_alert(alert3, rule) == False

    def test_add_remove_rule(self, alert_manager):
        """Test adding and removing alert rules."""
        new_rule = AlertRule(
            name="custom_rule",
            threshold=AlertThreshold("custom_metric", ">", 100.0),
            service=ServiceType.WEB_UI,
        )

        alert_manager.add_rule(new_rule)
        assert "custom_rule" in alert_manager.alert_rules

        alert_manager.remove_rule("custom_rule")
        assert "custom_rule" not in alert_manager.alert_rules

    def test_enable_disable_rule(self, alert_manager):
        """Test enabling and disabling rules."""
        rule_name = list(alert_manager.alert_rules.keys())[0]

        alert_manager.disable_rule(rule_name)
        assert alert_manager.alert_rules[rule_name].enabled == False

        alert_manager.enable_rule(rule_name)
        assert alert_manager.alert_rules[rule_name].enabled == True

    def test_get_alert_stats(self, alert_manager):
        """Test getting alert statistics."""
        stats = alert_manager.get_alert_stats()

        assert "total_rules" in stats
        assert "enabled_rules" in stats
        assert "active_alerts" in stats
        assert "alerts_last_24h" in stats
        assert "rules_by_severity" in stats

        assert stats["total_rules"] == len(alert_manager.alert_rules)
        assert isinstance(stats["rules_by_severity"], dict)

    @pytest.mark.asyncio
    async def test_store_alert(self, alert_manager, mock_redis):
        """Test storing alert in Redis."""
        alert = Alert(
            id="test_store",
            rule_name="test",
            service=ServiceType.ORCHESTRATOR,
            severity=AlertSeverity.WARNING,
            status=AlertStatus.ACTIVE,
            current_value=15.0,
            threshold_value=10.0,
            message="Test alert",
            triggered_at=datetime.utcnow(),
        )

        await alert_manager._store_alert(alert)

        mock_redis.hmset.assert_called_once()
        mock_redis.expire.assert_called_once()
        mock_redis.zadd.assert_called_once()

    def test_parse_stored_alert(self, alert_manager):
        """Test parsing stored alert from Redis."""
        alert_data = {
            b"id": b"stored_alert",
            b"rule_name": b"test_rule",
            b"service": b"orchestrator",
            b"severity": b"warning",
            b"status": b"active",
            b"current_value": b"25.5",
            b"threshold_value": b"20.0",
            b"message": b"Test message",
            b"triggered_at": datetime.utcnow().isoformat().encode(),
            b"resolved_at": b"None",
            b"notification_count": b"2",
            b"tags": b"{}",
        }

        parsed = alert_manager._parse_stored_alert(alert_data)
        assert parsed is not None
        assert parsed.id == "stored_alert"
        assert parsed.current_value == 25.5
        assert parsed.notification_count == 2


class TestAlertIntegration:
    """Integration tests for alert system."""

    @pytest.mark.asyncio
    async def test_full_alert_lifecycle(self, alert_manager):
        """Test complete alert lifecycle: trigger -> re-alert -> resolve."""
        rule = AlertRule(
            name="lifecycle_test",
            threshold=AlertThreshold(
                metric_name="test_metric",
                operator=">",
                value=50.0,
                duration_seconds=0,
                severity=AlertSeverity.WARNING,
            ),
            service=ServiceType.ORCHESTRATOR,
            cooldown_seconds=1,
        )
        alert_manager.add_rule(rule)

        # Phase 1: Trigger alert
        high_metrics = {"test_metric": 75.0}
        with patch.object(
            alert_manager.notification_manager, "send_notification", return_value=True
        ) as mock_notify:
            await alert_manager._evaluate_rule(rule, high_metrics)

            assert "lifecycle_test" in alert_manager.active_alerts
            alert = alert_manager.active_alerts["lifecycle_test"]
            assert alert.status == AlertStatus.ACTIVE
            assert alert.current_value == 75.0
            mock_notify.assert_called()

        # Phase 2: Re-alert check (should not re-alert immediately)
        alert.last_notification = datetime.utcnow()
        with patch.object(
            alert_manager.notification_manager, "send_notification"
        ) as mock_notify:
            await alert_manager._evaluate_rule(rule, high_metrics)
            mock_notify.assert_not_called()

        # Phase 3: Resolve alert
        low_metrics = {"test_metric": 25.0}
        with patch.object(
            alert_manager.notification_manager, "send_notification", return_value=True
        ) as mock_notify:
            await alert_manager._evaluate_rule(rule, low_metrics)

            assert alert.status == AlertStatus.RESOLVED
            assert alert.resolved_at is not None
            mock_notify.assert_called_with(
                alert, rule.notification_channels[0], is_resolution=True
            )

        # Wait for cleanup
        await asyncio.sleep(1.5)
        assert "lifecycle_test" not in alert_manager.active_alerts

    @pytest.mark.asyncio
    async def test_concurrent_alerts(self, alert_manager):
        """Test handling multiple concurrent alerts."""
        services = [ServiceType.ORCHESTRATOR, ServiceType.AGENT, ServiceType.BR_KG]

        # Create rules for different services
        for service in services:
            rule = AlertRule(
                name=f"{service}_concurrent_test",
                threshold=AlertThreshold("concurrent_metric", ">", 10.0),
                service=service,
            )
            alert_manager.add_rule(rule)

        # Trigger alerts concurrently
        metrics = {"concurrent_metric": 20.0}

        with patch.object(
            alert_manager.notification_manager, "send_notification", return_value=True
        ):
            tasks = [
                alert_manager._evaluate_rule(
                    alert_manager.alert_rules[f"{service}_concurrent_test"], metrics
                )
                for service in services
            ]
            await asyncio.gather(*tasks)

        # Verify all alerts were created
        for service in services:
            assert f"{service}_concurrent_test" in alert_manager.active_alerts
            alert = alert_manager.active_alerts[f"{service}_concurrent_test"]
            assert alert.service == service
            assert alert.status == AlertStatus.ACTIVE


@pytest.mark.performance
class TestAlertPerformance:
    """Performance tests for alert system."""

    @pytest.mark.asyncio
    async def test_high_volume_metrics(self, alert_manager):
        """Test handling high volume of metrics."""
        import time

        # Create 100 rules
        for i in range(100):
            rule = AlertRule(
                name=f"perf_test_{i}",
                threshold=AlertThreshold(f"metric_{i}", ">", float(i)),
                service=ServiceType.ORCHESTRATOR,
            )
            alert_manager.add_rule(rule)

        # Generate metrics
        metrics = {f"metric_{i}": float(i * 2) for i in range(100)}

        start_time = time.time()

        with patch.object(
            alert_manager.notification_manager, "send_notification", return_value=True
        ):
            # Evaluate all rules
            tasks = [
                alert_manager._evaluate_rule(rule, metrics)
                for rule in alert_manager.alert_rules.values()
            ]
            await asyncio.gather(*tasks)

        elapsed_time = time.time() - start_time

        # Should process 100 rules in under 5 seconds
        assert elapsed_time < 5.0

        # Verify alerts were created
        active_alerts = alert_manager.get_active_alerts()
        assert len(active_alerts) >= 100


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
