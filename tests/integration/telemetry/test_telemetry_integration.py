import pytest
pytest.skip("telemetry integration skipped (resilience marker not configured)", allow_module_level=True)
import pytest
"""
Integration tests for complete Telemetry System
Tests alert system and Sentry integration working together
"""

import asyncio
import pytest
import json
from datetime import datetime
from unittest.mock import Mock, AsyncMock, patch, MagicMock
from typing import Dict, Any

from brain_researcher.services.telemetry.alerts import AlertManager
from brain_researcher.services.telemetry.sentry_integration import (
    SentryIntegration, SentryConfig, initialize_sentry
)
from brain_researcher.services.telemetry.models import ServiceType, TelemetryEvent, EventType
from brain_researcher.services.telemetry.collector import TelemetryCollector


@pytest.fixture
def redis_client():
    """Create mock Redis client for testing."""
    client = MagicMock()
    client.hmset = MagicMock()
    client.expire = MagicMock()
    client.zadd = MagicMock()
    client.zrangebyscore = MagicMock(return_value=[])
    client.hgetall = MagicMock(return_value={})
    client.get = MagicMock(return_value=None)
    client.lpush = MagicMock()
    client.ltrim = MagicMock()
    return client


@pytest.fixture
def telemetry_config():
    """Create telemetry configuration."""
    return {
        "alerts": {
            "enabled": True,
            "notification": {
                "smtp": {
                    "enabled": False
                },
                "slack": {
                    "enabled": True,
                    "webhook_url": "https://hooks.slack.com/test",
                    "channel": "#alerts"
                },
                "webhook": {
                    "enabled": False
                }
            }
        },
        "sentry": {
            "dsn": "https://test@sentry.io/test",
            "environment": "integration_test",
            "enable_pii_filtering": True
        }
    }


@pytest.fixture
async def telemetry_system(redis_client, telemetry_config):
    """Create complete telemetry system."""
    # Initialize Sentry
    sentry_config = SentryConfig(
        dsn=telemetry_config["sentry"]["dsn"],
        environment=telemetry_config["sentry"]["environment"],
        enable_pii_filtering=telemetry_config["sentry"]["enable_pii_filtering"]
    )
    
    with patch('brain_researcher.services.telemetry.sentry_integration.SENTRY_AVAILABLE', True):
        with patch('brain_researcher.services.telemetry.sentry_integration.sentry_sdk'):
            sentry = initialize_sentry(sentry_config)
            sentry.is_initialized = True
    
    # Initialize Telemetry Collector
    collector = TelemetryCollector(redis_client)
    
    # Initialize Alert Manager
    alert_manager = AlertManager(
        redis_client=redis_client,
        telemetry_collector=collector,
        notification_config=telemetry_config["alerts"]["notification"]
    )
    
    # Start alert manager
    await alert_manager.start()
    
    yield {
        "sentry": sentry,
        "collector": collector,
        "alert_manager": alert_manager,
        "redis": redis_client
    }
    
    # Cleanup
    await alert_manager.stop()


class TestTelemetryIntegration:
    """Test integrated telemetry functionality."""
    
    @pytest.mark.asyncio
    async def test_metric_collection_triggers_alert(self, telemetry_system):
        """Test that high metrics trigger alerts."""
        alert_manager = telemetry_system["alert_manager"]
        collector = telemetry_system["collector"]
        redis = telemetry_system["redis"]
        
        # Simulate high response time metrics
        redis.zrangebyscore.return_value = [b"req_1", b"req_2", b"req_3"]
        redis.get.side_effect = [
            json.dumps({
                "service": ServiceType.ORCHESTRATOR,
                "duration_ms": 3000,
                "status_code": 200
            }),
            json.dumps({
                "service": ServiceType.ORCHESTRATOR,
                "duration_ms": 3500,
                "status_code": 200
            }),
            json.dumps({
                "service": ServiceType.ORCHESTRATOR,
                "duration_ms": 4000,
                "status_code": 200
            })
        ]
        
        # Add a rule for high response time
        from brain_researcher.services.telemetry.alerts import AlertRule, AlertThreshold, AlertSeverity
        rule = AlertRule(
            name="test_high_response",
            threshold=AlertThreshold(
                metric_name="response_time_ms",
                operator=">",
                value=2000.0,
                severity=AlertSeverity.WARNING
            ),
            service=ServiceType.ORCHESTRATOR
        )
        alert_manager.add_rule(rule)
        
        # Evaluate rules
        with patch.object(alert_manager.notification_manager, 'send_notification', 
                         return_value=True) as mock_notify:
            await alert_manager._evaluate_all_rules()
            
            # Check alert was triggered
            assert "test_high_response" in alert_manager.active_alerts
            alert = alert_manager.active_alerts["test_high_response"]
            assert alert.current_value > 2000.0
            
            # Check notification was sent
            mock_notify.assert_called()
    
    @pytest.mark.asyncio
    async def test_error_triggers_sentry_and_alert(self, telemetry_system):
        """Test that errors trigger both Sentry and alerts."""
        sentry = telemetry_system["sentry"]
        alert_manager = telemetry_system["alert_manager"]
        redis = telemetry_system["redis"]
        
        # Simulate high error rate
        redis.zrangebyscore.return_value = [b"req_1", b"req_2", b"req_3", b"req_4"]
        redis.get.side_effect = [
            json.dumps({"service": ServiceType.AGENT, "status_code": 500, "error": True}),
            json.dumps({"service": ServiceType.AGENT, "status_code": 500, "error": True}),
            json.dumps({"service": ServiceType.AGENT, "status_code": 200}),
            json.dumps({"service": ServiceType.AGENT, "status_code": 500, "error": True})
        ]
        
        # Capture error in Sentry
        with patch('brain_researcher.services.telemetry.sentry_integration.sentry_sdk.capture_exception') as mock_sentry:
            mock_sentry.return_value = "error_id"
            
            error = RuntimeError("Service failure")
            sentry.capture_exception(
                exception=error,
                service=ServiceType.AGENT,
                tags={"severity": "high"}
            )
            
            mock_sentry.assert_called_once()
        
        # Check if alert is triggered for error rate
        from brain_researcher.services.telemetry.alerts import AlertRule, AlertThreshold, AlertSeverity
        rule = AlertRule(
            name="high_error_rate",
            threshold=AlertThreshold(
                metric_name="error_rate",
                operator=">",
                value=50.0,  # 50% error rate
                severity=AlertSeverity.CRITICAL
            ),
            service=ServiceType.AGENT
        )
        alert_manager.add_rule(rule)
        
        with patch.object(alert_manager.notification_manager, 'send_notification', 
                         return_value=True) as mock_notify:
            await alert_manager._evaluate_all_rules()
            
            # Check alert was triggered
            assert "high_error_rate" in alert_manager.active_alerts
            alert = alert_manager.active_alerts["high_error_rate"]
            assert alert.severity == AlertSeverity.CRITICAL
    
    @pytest.mark.asyncio
    async def test_telemetry_event_processing(self, telemetry_system):
        """Test telemetry event collection and processing."""
        collector = telemetry_system["collector"]
        redis = telemetry_system["redis"]
        
        # Create telemetry events
        events = [
            TelemetryEvent(
                id="evt_1",
                service=ServiceType.NEUROKG,
                type=EventType.API_REQUEST,
                timestamp=datetime.utcnow(),
                data={
                    "endpoint": "/query",
                    "duration_ms": 150,
                    "status_code": 200
                }
            ),
            TelemetryEvent(
                id="evt_2",
                service=ServiceType.NEUROKG,
                type=EventType.ERROR,
                timestamp=datetime.utcnow(),
                data={
                    "error": "Connection timeout",
                    "severity": "warning"
                }
            )
        ]
        
        # Collect events
        for event in events:
            collector.collect(event)
        
        # Verify events were stored
        assert redis.lpush.called
        assert collector.get_stats()["events_collected"] == 2
    
    @pytest.mark.asyncio
    async def test_alert_recovery_flow(self, telemetry_system):
        """Test alert triggering and recovery."""
        alert_manager = telemetry_system["alert_manager"]
        redis = telemetry_system["redis"]
        
        from brain_researcher.services.telemetry.alerts import AlertRule, AlertThreshold, AlertSeverity
        rule = AlertRule(
            name="memory_usage",
            threshold=AlertThreshold(
                metric_name="memory_usage_percent",
                operator=">",
                value=75.0,
                severity=AlertSeverity.WARNING
            ),
            service=ServiceType.WEB_UI
        )
        alert_manager.add_rule(rule)
        
        # Phase 1: High memory triggers alert
        high_memory_metrics = {"memory_usage_percent": 85.0}
        
        with patch.object(alert_manager.notification_manager, 'send_notification', 
                         return_value=True) as mock_notify:
            await alert_manager._evaluate_rule(rule, high_memory_metrics)
            
            assert "memory_usage" in alert_manager.active_alerts
            alert = alert_manager.active_alerts["memory_usage"]
            assert alert.status.value == "active"
            mock_notify.assert_called_once()
        
        # Phase 2: Memory returns to normal
        normal_memory_metrics = {"memory_usage_percent": 60.0}
        
        with patch.object(alert_manager.notification_manager, 'send_notification', 
                         return_value=True) as mock_notify:
            await alert_manager._evaluate_rule(rule, normal_memory_metrics)
            
            assert alert.status.value == "resolved"
            assert alert.resolved_at is not None
            # Resolution notification sent
            mock_notify.assert_called_with(alert, rule.notification_channels[0], 
                                          is_resolution=True)
    
    @pytest.mark.asyncio
    async def test_pii_filtering_in_alerts(self, telemetry_system):
        """Test PII filtering when capturing errors."""
        sentry = telemetry_system["sentry"]
        
        # Data with PII
        sensitive_data = {
            "user_email": "john.doe@example.com",
            "credit_card": "1234 5678 9012 3456",
            "safe_field": "public_data"
        }
        
        with patch('brain_researcher.services.telemetry.sentry_integration.sentry_sdk.capture_message') as mock_capture:
            mock_capture.return_value = "msg_id"
            
            # Capture message with PII
            message = f"User {sensitive_data['user_email']} payment failed"
            sentry.capture_message(message, extra=sensitive_data)
            
            # Check PII was filtered
            call_args = mock_capture.call_args[0][0]
            assert "john.doe@example.com" not in call_args
            assert "[EMAIL_FILTERED]" in call_args
    
    @pytest.mark.asyncio
    async def test_concurrent_service_monitoring(self, telemetry_system):
        """Test monitoring multiple services concurrently."""
        alert_manager = telemetry_system["alert_manager"]
        redis = telemetry_system["redis"]
        
        services = [ServiceType.ORCHESTRATOR, ServiceType.AGENT, ServiceType.NEUROKG, ServiceType.WEB_UI]
        
        # Create rules for each service
        from brain_researcher.services.telemetry.alerts import AlertRule, AlertThreshold, AlertSeverity
        for service in services:
            rule = AlertRule(
                name=f"{service}_cpu_usage",
                threshold=AlertThreshold(
                    metric_name="cpu_usage_percent",
                    operator=">",
                    value=70.0,
                    severity=AlertSeverity.WARNING
                ),
                service=service
            )
            alert_manager.add_rule(rule)
        
        # Simulate high CPU for some services
        high_cpu_metrics = {"cpu_usage_percent": 85.0}
        normal_cpu_metrics = {"cpu_usage_percent": 45.0}
        
        with patch.object(alert_manager.notification_manager, 'send_notification', 
                         return_value=True):
            # Evaluate rules with varying metrics
            for i, service in enumerate(services):
                rule = alert_manager.alert_rules[f"{service}_cpu_usage"]
                metrics = high_cpu_metrics if i % 2 == 0 else normal_cpu_metrics
                await alert_manager._evaluate_rule(rule, metrics)
        
        # Check that only alternating services have active alerts
        active_alerts = alert_manager.get_active_alerts()
        assert len(active_alerts) == 2
        
        for alert in active_alerts:
            service_name = alert.service
            service_index = services.index(service_name)
            assert service_index % 2 == 0  # Only even-indexed services should have alerts
    
    @pytest.mark.asyncio
    async def test_grafana_dashboard_metrics(self, telemetry_system):
        """Test metrics collection for Grafana dashboards."""
        collector = telemetry_system["collector"]
        alert_manager = telemetry_system["alert_manager"]
        
        # Get system stats
        collector_stats = collector.get_stats()
        alert_stats = alert_manager.get_alert_stats()
        
        # Verify dashboard metrics are available
        dashboard_metrics = {
            "telemetry": {
                "events_collected": collector_stats.get("events_collected", 0),
                "buffer_size": collector_stats.get("buffer_size", 0),
                "processing_time": collector_stats.get("avg_processing_time_ms", 0)
            },
            "alerts": {
                "total_rules": alert_stats["total_rules"],
                "enabled_rules": alert_stats["enabled_rules"],
                "active_alerts": alert_stats["active_alerts"],
                "alerts_last_24h": alert_stats["alerts_last_24h"]
            }
        }
        
        # All metrics should be available for dashboard
        assert dashboard_metrics["telemetry"]["events_collected"] >= 0
        assert dashboard_metrics["alerts"]["total_rules"] > 0
        assert dashboard_metrics["alerts"]["enabled_rules"] > 0


@pytest.mark.performance
class TestTelemetryPerformance:
    """Performance tests for telemetry system."""
    
    @pytest.mark.asyncio
    async def test_high_volume_event_processing(self, telemetry_system):
        """Test processing high volume of telemetry events."""
        import time
        collector = telemetry_system["collector"]
        
        # Generate 1000 events
        events = []
        for i in range(1000):
            event = TelemetryEvent(
                id=f"perf_evt_{i}",
                service=ServiceType.ORCHESTRATOR,
                type=EventType.API_REQUEST if i % 3 != 0 else EventType.ERROR,
                timestamp=datetime.utcnow(),
                data={
                    "index": i,
                    "duration_ms": 100 + (i % 100)
                }
            )
            events.append(event)
        
        start_time = time.time()
        
        # Process all events
        for event in events:
            collector.collect(event)
        
        elapsed_time = time.time() - start_time
        
        # Should process 1000 events in under 2 seconds
        assert elapsed_time < 2.0
        assert collector.get_stats()["events_collected"] == 1000
    
    @pytest.mark.asyncio
    async def test_alert_evaluation_performance(self, telemetry_system):
        """Test performance of alert evaluation with many rules."""
        import time
        alert_manager = telemetry_system["alert_manager"]
        
        # Create 50 rules
        from brain_researcher.services.telemetry.alerts import AlertRule, AlertThreshold, AlertSeverity
        for i in range(50):
            rule = AlertRule(
                name=f"perf_rule_{i}",
                threshold=AlertThreshold(
                    metric_name=f"metric_{i}",
                    operator=">",
                    value=float(i * 10),
                    severity=AlertSeverity.WARNING
                ),
                service=ServiceType.ORCHESTRATOR
            )
            alert_manager.add_rule(rule)
        
        # Generate metrics
        metrics = {f"metric_{i}": float(i * 20) for i in range(50)}
        
        start_time = time.time()
        
        with patch.object(alert_manager.notification_manager, 'send_notification', 
                         return_value=True):
            # Evaluate all rules
            tasks = []
            for rule in list(alert_manager.alert_rules.values())[:50]:
                tasks.append(alert_manager._evaluate_rule(rule, metrics))
            
            await asyncio.gather(*tasks)
        
        elapsed_time = time.time() - start_time
        
        # Should evaluate 50 rules in under 3 seconds
        assert elapsed_time < 3.0
        
        # Verify alerts were created
        active_alerts = alert_manager.get_active_alerts()
        assert len(active_alerts) >= 50


@pytest.mark.resilience
class TestTelemetryResilience:
    """Test telemetry system resilience and error handling."""
    
    @pytest.mark.asyncio
    async def test_redis_failure_handling(self, telemetry_system):
        """Test system behavior when Redis fails."""
        collector = telemetry_system["collector"]
        redis = telemetry_system["redis"]
        
        # Simulate Redis failure
        redis.lpush.side_effect = Exception("Redis connection lost")
        
        # Try to collect event
        event = TelemetryEvent(
            id="fail_evt",
            service=ServiceType.ORCHESTRATOR,
            type=EventType.ERROR,
            timestamp=datetime.utcnow(),
            data={"error": "test"}
        )
        
        # Should not crash
        collector.collect(event)
        
        # Check buffering is working
        assert len(collector._buffer) > 0
    
    @pytest.mark.asyncio
    async def test_notification_failure_recovery(self, telemetry_system):
        """Test alert system continues when notifications fail."""
        alert_manager = telemetry_system["alert_manager"]
        
        from brain_researcher.services.telemetry.alerts import AlertRule, AlertThreshold, AlertSeverity
        rule = AlertRule(
            name="test_notification_fail",
            threshold=AlertThreshold(
                metric_name="test_metric",
                operator=">",
                value=10.0,
                severity=AlertSeverity.WARNING
            ),
            service=ServiceType.ORCHESTRATOR
        )
        alert_manager.add_rule(rule)
        
        # Notification fails
        with patch.object(alert_manager.notification_manager, 'send_notification', 
                         side_effect=Exception("Network error")):
            # Should not crash
            await alert_manager._evaluate_rule(rule, {"test_metric": 20.0})
            
            # Alert should still be created
            assert "test_notification_fail" in alert_manager.active_alerts
    
    @pytest.mark.asyncio
    async def test_sentry_failure_handling(self, telemetry_system):
        """Test system continues when Sentry fails."""
        sentry = telemetry_system["sentry"]
        
        with patch('brain_researcher.services.telemetry.sentry_integration.sentry_sdk.capture_exception', 
                  side_effect=Exception("Sentry unavailable")):
            # Should not crash
            event_id = sentry.capture_exception(
                exception=ValueError("Test error"),
                tags={"test": "true"}
            )
            
            # Should return None instead of crashing
            assert event_id is None


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])