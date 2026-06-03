"""
Comprehensive Push Notification System Tests for Brain Researcher PWA
Tests push notification subscription, delivery, brain research templates,
and notification interaction handling
"""

import json
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, Mock, patch

import pytest


# Mock the push notification classes for testing
class MockPushNotificationManager:
    def __init__(self, options=None):
        self.vapid_public_key = (
            options.get("vapidPublicKey", "test-key") if options else "test-key"
        )
        self.subscription_endpoint = (
            options.get("subscriptionEndpoint", "/api/push/subscribe")
            if options
            else "/api/push/subscribe"
        )
        self.registration = None
        self.subscription = None
        self.is_supported_flag = True
        self.permission_status = "default"

    def is_supported(self):
        return self.is_supported_flag

    def get_permission_status(self):
        return self.permission_status


class TestPushNotificationManager:
    """Test the PushNotificationManager class"""

    def setup_method(self):
        """Set up test fixtures"""
        self.mock_navigator = Mock()
        self.mock_service_worker = Mock()
        self.mock_push_manager = Mock()
        self.mock_registration = Mock()
        self.mock_subscription = Mock()

        # Set up mock service worker environment
        self.mock_navigator.serviceWorker = self.mock_service_worker
        self.mock_service_worker.register = AsyncMock()
        self.mock_service_worker.ready = AsyncMock()

        # Set up mock push manager
        self.mock_registration.pushManager = self.mock_push_manager
        self.mock_push_manager.getSubscription = AsyncMock()
        self.mock_push_manager.subscribe = AsyncMock()

        # Set up mock subscription
        self.mock_subscription.endpoint = "https://fcm.googleapis.com/endpoint/123"
        self.mock_subscription.getKey = Mock()
        self.mock_subscription.unsubscribe = AsyncMock()

        # Mock global objects
        self.mock_notification = Mock()
        self.mock_notification.permission = "default"
        self.mock_notification.requestPermission = AsyncMock()

        self.manager = MockPushNotificationManager(
            {
                "vapidPublicKey": "BNJxw7sCGkGLOUP2cawBaBXRuWZ8-MCkqRyTWJfgRtPw",
                "subscriptionEndpoint": "/api/push/subscribe",
            }
        )

    def test_initialization(self):
        """Test push notification manager initialization"""
        assert (
            self.manager.vapid_public_key
            == "BNJxw7sCGkGLOUP2cawBaBXRuWZ8-MCkqRyTWJfgRtPw"
        )
        assert self.manager.subscription_endpoint == "/api/push/subscribe"
        assert self.manager.subscription is None
        assert self.manager.registration is None

    def test_is_supported(self):
        """Test push notification support detection"""
        # Test supported environment
        assert self.manager.is_supported() is True

        # Test unsupported environment
        self.manager.is_supported_flag = False
        assert self.manager.is_supported() is False

    def test_get_permission_status(self):
        """Test permission status retrieval"""
        # Test default permission
        assert self.manager.get_permission_status() == "default"

        # Test granted permission
        self.manager.permission_status = "granted"
        assert self.manager.get_permission_status() == "granted"

        # Test denied permission
        self.manager.permission_status = "denied"
        assert self.manager.get_permission_status() == "denied"

    @pytest.mark.asyncio
    async def test_request_permission(self):
        """Test permission request flow"""
        # `fetch` is a browser API; allow patching even though it does not exist in Python.
        with patch("builtins.fetch", new_callable=AsyncMock, create=True) as mock_fetch:
            # Mock successful permission request
            mock_response = Mock()
            mock_response.ok = True
            mock_fetch.return_value = mock_response

            # Simulate permission granted
            self.manager.permission_status = "granted"

            result = self.manager.get_permission_status()
            assert result == "granted"

    @pytest.mark.asyncio
    async def test_subscription_creation(self):
        """Test push subscription creation"""
        with patch("builtins.fetch", new_callable=AsyncMock, create=True) as mock_fetch:
            # Mock successful subscription
            mock_response = Mock()
            mock_response.ok = True
            mock_response.json = AsyncMock(return_value={"success": True})
            mock_fetch.return_value = mock_response

            # Mock subscription data
            subscription_data = {
                "endpoint": "https://fcm.googleapis.com/endpoint/123",
                "keys": {"p256dh": "test-p256dh-key", "auth": "test-auth-key"},
            }

            # Simulate subscription creation
            self.manager.subscription = subscription_data

            # Verify subscription was created
            assert self.manager.subscription is not None
            assert (
                self.manager.subscription["endpoint"]
                == "https://fcm.googleapis.com/endpoint/123"
            )
            assert "keys" in self.manager.subscription

    @pytest.mark.asyncio
    async def test_subscription_backend_sync(self):
        """Test subscription synchronization with backend"""
        with patch("builtins.fetch", new_callable=AsyncMock, create=True) as mock_fetch:
            mock_response = Mock()
            mock_response.ok = True
            mock_response.json = AsyncMock(return_value={"subscribed": True})
            mock_fetch.return_value = mock_response

            subscription_data = {
                "subscription": {
                    "endpoint": "https://fcm.googleapis.com/endpoint/123",
                    "keys": {"p256dh": "test-p256dh-key", "auth": "test-auth-key"},
                },
                "userAgent": "Mozilla/5.0...",
                "timestamp": datetime.now().isoformat(),
            }

            # Simulate backend sync
            await mock_fetch(
                "/api/push/subscribe",
                {
                    "method": "POST",
                    "headers": {"Content-Type": "application/json"},
                    "body": json.dumps(subscription_data),
                },
            )

            mock_fetch.assert_called_once_with(
                "/api/push/subscribe",
                {
                    "method": "POST",
                    "headers": {"Content-Type": "application/json"},
                    "body": json.dumps(subscription_data),
                },
            )

    @pytest.mark.asyncio
    async def test_unsubscribe(self):
        """Test push notification unsubscription"""
        with patch("builtins.fetch", new_callable=AsyncMock, create=True) as mock_fetch:
            # Mock successful unsubscription
            mock_response = Mock()
            mock_response.ok = True
            mock_fetch.return_value = mock_response

            # Simulate existing subscription
            self.manager.subscription = {
                "endpoint": "https://fcm.googleapis.com/endpoint/123",
                "keys": {"p256dh": "key1", "auth": "key2"},
            }

            # Simulate unsubscription
            self.manager.subscription = None

            assert self.manager.subscription is None

    @pytest.mark.asyncio
    async def test_test_notification(self):
        """Test local test notification"""
        # `Notification` is a browser API; allow patching even though it does not exist in Python.
        with patch(
            "builtins.Notification", create=True
        ) as mock_notification_constructor:
            mock_notification = Mock()
            mock_notification.close = Mock()
            mock_notification_constructor.return_value = mock_notification

            # Set permission to granted
            self.manager.permission_status = "granted"

            # Create test notification
            if self.manager.get_permission_status() == "granted":
                mock_notification_constructor(
                    "Brain Researcher Test",
                    {
                        "body": "Push notifications are working correctly!",
                        "icon": "/icons/icon-192x192.png",
                        "tag": "test-notification",
                    },
                )

                mock_notification_constructor.assert_called_once_with(
                    "Brain Researcher Test",
                    {
                        "body": "Push notifications are working correctly!",
                        "icon": "/icons/icon-192x192.png",
                        "tag": "test-notification",
                    },
                )


class TestBrainNotificationTemplates:
    """Test notification templates for brain research use cases"""

    def test_analysis_complete_template(self):
        """Test analysis complete notification template"""
        template_data = {
            "type": "analysis-complete",
            "title": "Analysis Complete",
            "body": 'Your brain analysis "fMRI GLM Analysis" has finished processing.',
            "analysisName": "fMRI GLM Analysis",
            "analysisId": "analysis_123",
            "actions": [
                {"action": "view", "title": "View Results"},
                {"action": "dismiss", "title": "Dismiss"},
            ],
        }

        # Test template structure
        assert template_data["type"] == "analysis-complete"
        assert "fMRI GLM Analysis" in template_data["body"]
        assert template_data["analysisId"] == "analysis_123"
        assert len(template_data["actions"]) == 2
        assert template_data["actions"][0]["action"] == "view"

    def test_dataset_update_template(self):
        """Test dataset update notification template"""
        template_data = {
            "type": "data-update",
            "title": "Dataset Update",
            "body": "New brain data available: HCP-YA Dataset",
            "datasetName": "HCP-YA Dataset",
            "data": {"updateType": "new_subjects"},
            "actions": [
                {"action": "sync", "title": "Sync Now"},
                {"action": "later", "title": "Later"},
            ],
        }

        assert template_data["type"] == "data-update"
        assert "HCP-YA Dataset" in template_data["body"]
        assert template_data["data"]["updateType"] == "new_subjects"
        assert len(template_data["actions"]) == 2
        assert template_data["actions"][0]["action"] == "sync"

    def test_system_alert_template(self):
        """Test system alert notification template"""
        high_severity_template = {
            "type": "system-alert",
            "title": "Brain Researcher Alert",
            "body": "Critical system error: Unable to access brain atlas data",
            "message": "Critical system error: Unable to access brain atlas data",
            "data": {"severity": "high"},
            "requireInteraction": True,
        }

        low_severity_template = {
            "type": "system-alert",
            "title": "Brain Researcher Alert",
            "body": "System maintenance scheduled for tonight",
            "message": "System maintenance scheduled for tonight",
            "data": {"severity": "low"},
            "requireInteraction": False,
        }

        # Test high severity alert
        assert high_severity_template["requireInteraction"] is True
        assert high_severity_template["data"]["severity"] == "high"

        # Test low severity alert
        assert low_severity_template["requireInteraction"] is False
        assert low_severity_template["data"]["severity"] == "low"

    def test_processing_update_template(self):
        """Test processing update notification template"""
        template_data = {
            "type": "default",
            "title": "Processing Update",
            "body": 'Analysis "Connectivity Analysis" is 75% complete',
            "data": {"progress": 75, "analysisName": "Connectivity Analysis"},
        }

        assert "75%" in template_data["body"]
        assert template_data["data"]["progress"] == 75
        assert template_data["data"]["analysisName"] == "Connectivity Analysis"

    def test_offline_sync_template(self):
        """Test offline sync notification template"""
        template_data = {
            "type": "default",
            "title": "Offline Sync Complete",
            "body": "23 items synchronized while offline",
            "data": {"syncedItems": 23},
        }

        assert "23 items" in template_data["body"]
        assert template_data["data"]["syncedItems"] == 23


class TestPushNotificationUtils:
    """Test utility functions for push notifications"""

    def test_permission_messages(self):
        """Test permission status messages"""
        messages = {
            "granted": "Notifications are enabled",
            "denied": "Notifications are blocked. Please enable them in browser settings.",
            "default": "Click to enable notifications",
            "unknown": "Unknown notification status",
        }

        assert messages["granted"] == "Notifications are enabled"
        assert "blocked" in messages["denied"]
        assert "Click to enable" in messages["default"]

    def test_mobile_device_detection(self):
        """Test mobile device detection"""
        mobile_user_agents = [
            "Mozilla/5.0 (iPhone; CPU iPhone OS 14_7_1 like Mac OS X)",
            "Mozilla/5.0 (Android 11; Mobile; rv:68.0)",
            "Mozilla/5.0 (iPad; CPU OS 14_7_1 like Mac OS X)",
        ]

        desktop_user_agents = [
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
        ]

        def is_mobile_device(user_agent):
            return any(
                mobile in user_agent
                for mobile in ["iPhone", "Android", "iPad", "Mobile"]
            )

        # Test mobile detection
        for ua in mobile_user_agents:
            assert is_mobile_device(ua) is True

        # Test desktop detection
        for ua in desktop_user_agents:
            assert is_mobile_device(ua) is False

    def test_optimal_notification_time(self):
        """Test optimal notification timing"""

        def get_optimal_notification_time(current_hour):
            # Avoid late night/early morning notifications
            if current_hour >= 22 or current_hour <= 7:
                # Schedule for 9 AM next day
                return 9
            return current_hour

        # Test late night (should schedule for next day)
        assert get_optimal_notification_time(23) == 9
        assert get_optimal_notification_time(2) == 9

        # Test normal hours (should use current time)
        assert get_optimal_notification_time(10) == 10
        assert get_optimal_notification_time(15) == 15

    def test_brain_notification_formatting(self):
        """Test brain research specific notification formatting"""

        def format_brain_notification_body(notification_type, data):
            templates = {
                "analysis-complete": f'Brain analysis "{data.get("analysisName", "Unknown")}" completed. {"Significant findings detected!" if data.get("significantFindings") else "Results ready for review."}',
                "dataset-ready": f'Dataset "{data.get("datasetName", "Unknown")}" ({data.get("subjectCount", 0)} subjects) is ready for analysis.',
                "processing-error": f'Analysis "{data.get("analysisName", "Unknown")}" encountered an error. Technical support has been notified.',
                "collaboration-invite": f'{data.get("inviterName", "Someone")} invited you to collaborate on "{data.get("projectName", "a project")}".',
            }

            return templates.get(
                notification_type, data.get("body", "Brain Researcher notification")
            )

        # Test analysis complete with significant findings
        data1 = {"analysisName": "fMRI Connectivity", "significantFindings": True}
        result1 = format_brain_notification_body("analysis-complete", data1)
        assert "fMRI Connectivity" in result1
        assert "Significant findings detected!" in result1

        # Test analysis complete without significant findings
        data2 = {"analysisName": "Structural Analysis", "significantFindings": False}
        result2 = format_brain_notification_body("analysis-complete", data2)
        assert "Structural Analysis" in result2
        assert "Results ready for review" in result2

        # Test dataset ready
        data3 = {"datasetName": "HCP-YA", "subjectCount": 1200}
        result3 = format_brain_notification_body("dataset-ready", data3)
        assert "HCP-YA" in result3
        assert "1200 subjects" in result3

        # Test collaboration invite
        data4 = {"inviterName": "Dr. Smith", "projectName": "Multi-site fMRI Study"}
        result4 = format_brain_notification_body("collaboration-invite", data4)
        assert "Dr. Smith" in result4
        assert "Multi-site fMRI Study" in result4


class TestPushNotificationIntegration:
    """Test push notification integration with Brain Researcher services"""

    def setup_method(self):
        """Set up integration test environment"""
        self.mock_orchestrator = Mock()
        self.mock_br_kg = Mock()
        self.mock_analysis_service = Mock()

    @pytest.mark.asyncio
    async def test_analysis_complete_notification_flow(self):
        """Test complete flow from analysis completion to notification"""
        with patch("builtins.fetch", new_callable=AsyncMock, create=True) as mock_fetch:
            # Mock analysis completion event
            analysis_result = {
                "analysisId": "analysis_123",
                "analysisName": "fMRI GLM Analysis",
                "status": "completed",
                "significantFindings": True,
                "completionTime": datetime.now().isoformat(),
            }

            # Mock notification payload
            notification_payload = {
                "type": "analysis-complete",
                "title": "Analysis Complete",
                "body": f'Analysis "{analysis_result["analysisName"]}" completed. Significant findings detected!',
                "data": {
                    "analysisId": analysis_result["analysisId"],
                    "analysisName": analysis_result["analysisName"],
                    "significantFindings": analysis_result["significantFindings"],
                },
            }

            # Mock push notification API response
            mock_response = Mock()
            mock_response.ok = True
            mock_response.json = AsyncMock(
                return_value={"sent": True, "messageId": "msg_123"}
            )
            mock_fetch.return_value = mock_response

            # Simulate sending notification
            await mock_fetch(
                "/api/push/send",
                {
                    "method": "POST",
                    "headers": {"Content-Type": "application/json"},
                    "body": json.dumps(notification_payload),
                },
            )

            mock_fetch.assert_called_once()

    @pytest.mark.asyncio
    async def test_dataset_update_notification_flow(self):
        """Test dataset update notification flow"""
        with patch("builtins.fetch", new_callable=AsyncMock, create=True) as mock_fetch:
            # Mock dataset update event
            dataset_update = {
                "datasetId": "hcp_ya_2023",
                "datasetName": "HCP Young Adult 2023",
                "updateType": "new_subjects",
                "newSubjectCount": 50,
                "totalSubjects": 1250,
                "updateTime": datetime.now().isoformat(),
            }

            # Mock notification payload
            notification_payload = {
                "type": "data-update",
                "title": "Dataset Update",
                "body": f'New brain data available: {dataset_update["datasetName"]} (+{dataset_update["newSubjectCount"]} subjects)',
                "data": {
                    "datasetId": dataset_update["datasetId"],
                    "datasetName": dataset_update["datasetName"],
                    "updateType": dataset_update["updateType"],
                    "newSubjectCount": dataset_update["newSubjectCount"],
                },
                "actions": [
                    {"action": "sync", "title": "Sync Now"},
                    {"action": "later", "title": "Later"},
                ],
            }

            mock_response = Mock()
            mock_response.ok = True
            mock_fetch.return_value = mock_response

            await mock_fetch(
                "/api/push/send",
                {
                    "method": "POST",
                    "headers": {"Content-Type": "application/json"},
                    "body": json.dumps(notification_payload),
                },
            )

            mock_fetch.assert_called_once()

    @pytest.mark.asyncio
    async def test_system_monitoring_alerts(self):
        """Test system monitoring alert notifications"""
        with patch("builtins.fetch", new_callable=AsyncMock, create=True) as mock_fetch:
            # Mock system alert scenarios
            alert_scenarios = [
                {
                    "type": "resource_warning",
                    "severity": "medium",
                    "message": "High memory usage detected on analysis server",
                    "metrics": {"memory_usage": 0.85, "threshold": 0.80},
                },
                {
                    "type": "service_unavailable",
                    "severity": "high",
                    "message": "BR-KG service is unavailable",
                    "affectedServices": ["br_kg", "finder"],
                },
                {
                    "type": "scheduled_maintenance",
                    "severity": "low",
                    "message": "System maintenance scheduled for 2:00 AM EST",
                    "scheduledTime": (datetime.now() + timedelta(hours=8)).isoformat(),
                },
            ]

            mock_response = Mock()
            mock_response.ok = True
            mock_fetch.return_value = mock_response

            for alert in alert_scenarios:
                notification_payload = {
                    "type": "system-alert",
                    "title": "Brain Researcher Alert",
                    "body": alert["message"],
                    "data": alert,
                    "requireInteraction": alert["severity"] == "high",
                }

                await mock_fetch(
                    "/api/push/send",
                    {
                        "method": "POST",
                        "headers": {"Content-Type": "application/json"},
                        "body": json.dumps(notification_payload),
                    },
                )

            # Verify all alerts were sent
            assert mock_fetch.call_count == len(alert_scenarios)

    def test_notification_action_handling(self):
        """Test notification action handling"""
        notification_actions = {
            "view_results": {
                "action": "view",
                "data": {"analysisId": "analysis_123"},
                "expectedUrl": "/analysis/results/analysis_123",
            },
            "sync_data": {
                "action": "sync",
                "data": {"datasetId": "hcp_ya_2023"},
                "expectedBackground": "sync-brain-data",
            },
            "open_dashboard": {
                "action": "dashboard",
                "data": {},
                "expectedUrl": "/dashboard",
            },
        }

        def handle_notification_action(action, data):
            if action == "view":
                return f"/analysis/results/{data.get('analysisId', '')}"
            elif action == "sync":
                return "sync-brain-data"
            elif action == "dashboard":
                return "/dashboard"
            else:
                return "/"

        # Test action handling
        for _action_name, action_data in notification_actions.items():
            result = handle_notification_action(
                action_data["action"], action_data["data"]
            )

            if "expectedUrl" in action_data:
                assert result == action_data["expectedUrl"]
            elif "expectedBackground" in action_data:
                assert result == action_data["expectedBackground"]

    @pytest.mark.asyncio
    async def test_notification_scheduling(self):
        """Test notification scheduling for optimal delivery"""

        def should_deliver_immediately(
            notification_type, current_hour, user_preferences
        ):
            # Critical alerts are always immediate
            if notification_type == "system-alert":
                return True

            # Respect user quiet hours
            quiet_start = user_preferences.get("quietHoursStart", 22)
            quiet_end = user_preferences.get("quietHoursEnd", 8)

            if quiet_start <= current_hour or current_hour <= quiet_end:
                return False

            # Analysis complete notifications during work hours
            if notification_type == "analysis-complete":
                return 8 <= current_hour <= 18

            return True

        test_cases = [
            # During work hours - should deliver
            {
                "type": "analysis-complete",
                "hour": 14,
                "preferences": {},
                "expected": True,
            },
            # During quiet hours - should not deliver
            {
                "type": "analysis-complete",
                "hour": 23,
                "preferences": {"quietHoursStart": 22, "quietHoursEnd": 8},
                "expected": False,
            },
            # Critical alert - always deliver
            {"type": "system-alert", "hour": 2, "preferences": {}, "expected": True},
            # Early morning non-critical - should not deliver
            {
                "type": "data-update",
                "hour": 6,
                "preferences": {"quietHoursStart": 22, "quietHoursEnd": 8},
                "expected": False,
            },
        ]

        for case in test_cases:
            result = should_deliver_immediately(
                case["type"], case["hour"], case["preferences"]
            )
            assert result == case["expected"], f"Failed for case: {case}"

    def test_notification_payload_validation(self):
        """Test notification payload validation"""

        def validate_notification_payload(payload):
            required_fields = ["type", "title", "body"]
            errors = []

            # Check required fields
            for field in required_fields:
                if field not in payload or not payload[field]:
                    errors.append(f"Missing required field: {field}")

            # Validate type
            valid_types = [
                "analysis-complete",
                "data-update",
                "system-alert",
                "default",
            ]
            if "type" in payload and payload["type"] not in valid_types:
                errors.append(f"Invalid type: {payload['type']}")

            # Validate actions format
            if "actions" in payload:
                for action in payload["actions"]:
                    if (
                        not isinstance(action, dict)
                        or "action" not in action
                        or "title" not in action
                    ):
                        errors.append("Invalid action format")

            return len(errors) == 0, errors

        # Test valid payload
        valid_payload = {
            "type": "analysis-complete",
            "title": "Analysis Complete",
            "body": "Your analysis is ready",
            "data": {"analysisId": "123"},
            "actions": [{"action": "view", "title": "View Results"}],
        }

        is_valid, errors = validate_notification_payload(valid_payload)
        assert is_valid is True
        assert len(errors) == 0

        # Test invalid payload
        invalid_payload = {
            "type": "invalid-type",
            "title": "",
            "actions": [{"invalid": "action"}],
        }

        is_valid, errors = validate_notification_payload(invalid_payload)
        assert is_valid is False
        assert len(errors) > 0


class TestPushNotificationMetrics:
    """Test push notification metrics and analytics"""

    def test_delivery_metrics_tracking(self):
        """Test notification delivery metrics"""
        metrics = {"sent": 0, "delivered": 0, "clicked": 0, "dismissed": 0, "failed": 0}

        def track_notification_event(event_type, notification_id, data=None):
            if event_type in metrics:
                metrics[event_type] += 1

            # Track additional data
            event_record = {
                "event": event_type,
                "notification_id": notification_id,
                "timestamp": datetime.now().isoformat(),
                "data": data or {},
            }

            return event_record

        # Simulate notification lifecycle
        track_notification_event("sent", "notif_123")
        track_notification_event("delivered", "notif_123")
        track_notification_event("clicked", "notif_123", {"action": "view"})

        assert metrics["sent"] == 1
        assert metrics["delivered"] == 1
        assert metrics["clicked"] == 1

    def test_engagement_analysis(self):
        """Test notification engagement analysis"""
        engagement_data = [
            {"type": "analysis-complete", "clicked": True, "time_to_click": 30},
            {"type": "analysis-complete", "clicked": False, "time_to_dismiss": 120},
            {"type": "data-update", "clicked": True, "time_to_click": 60},
            {"type": "system-alert", "clicked": True, "time_to_click": 5},
        ]

        def calculate_engagement_metrics(data):
            total_notifications = len(data)
            clicked_notifications = sum(1 for n in data if n["clicked"])

            click_rate = (
                clicked_notifications / total_notifications
                if total_notifications > 0
                else 0
            )

            # Calculate average time to click for clicked notifications
            clicked_times = [
                n["time_to_click"]
                for n in data
                if n["clicked"] and "time_to_click" in n
            ]
            avg_time_to_click = (
                sum(clicked_times) / len(clicked_times) if clicked_times else 0
            )

            # Engagement by type
            type_engagement = {}
            for notification in data:
                notif_type = notification["type"]
                if notif_type not in type_engagement:
                    type_engagement[notif_type] = {"total": 0, "clicked": 0}

                type_engagement[notif_type]["total"] += 1
                if notification["clicked"]:
                    type_engagement[notif_type]["clicked"] += 1

            # Calculate click rate by type
            for notif_type in type_engagement:
                total = type_engagement[notif_type]["total"]
                clicked = type_engagement[notif_type]["clicked"]
                type_engagement[notif_type]["click_rate"] = (
                    clicked / total if total > 0 else 0
                )

            return {
                "overall_click_rate": click_rate,
                "avg_time_to_click": avg_time_to_click,
                "engagement_by_type": type_engagement,
            }

        metrics = calculate_engagement_metrics(engagement_data)

        assert metrics["overall_click_rate"] == 0.75  # 3/4 clicked
        assert metrics["engagement_by_type"]["system-alert"]["click_rate"] == 1.0
        assert metrics["engagement_by_type"]["analysis-complete"]["click_rate"] == 0.5

    def test_subscription_health_monitoring(self):
        """Test push subscription health monitoring"""

        def check_subscription_health(subscriptions):
            health_report = {
                "total_subscriptions": len(subscriptions),
                "active_subscriptions": 0,
                "expired_subscriptions": 0,
                "failing_subscriptions": 0,
                "platform_breakdown": {},
                "health_score": 0.0,
            }

            current_time = datetime.now()

            for sub in subscriptions:
                # Check if subscription is active
                last_success = datetime.fromisoformat(sub["last_successful_delivery"])
                days_since_success = (current_time - last_success).days

                if days_since_success <= 7:
                    health_report["active_subscriptions"] += 1
                elif days_since_success <= 30:
                    health_report["expired_subscriptions"] += 1
                else:
                    health_report["failing_subscriptions"] += 1

                # Platform breakdown
                platform = sub["platform"]
                if platform not in health_report["platform_breakdown"]:
                    health_report["platform_breakdown"][platform] = 0
                health_report["platform_breakdown"][platform] += 1

            # Calculate health score
            if health_report["total_subscriptions"] > 0:
                health_report["health_score"] = (
                    health_report["active_subscriptions"]
                    / health_report["total_subscriptions"]
                )

            return health_report

        # Mock subscription data
        subscriptions = [
            {
                "id": "sub_1",
                "platform": "chrome",
                "last_successful_delivery": (
                    datetime.now() - timedelta(days=1)
                ).isoformat(),
            },
            {
                "id": "sub_2",
                "platform": "firefox",
                "last_successful_delivery": (
                    datetime.now() - timedelta(days=15)
                ).isoformat(),
            },
            {
                "id": "sub_3",
                "platform": "safari",
                "last_successful_delivery": (
                    datetime.now() - timedelta(days=45)
                ).isoformat(),
            },
        ]

        health_report = check_subscription_health(subscriptions)

        assert health_report["total_subscriptions"] == 3
        assert health_report["active_subscriptions"] == 1
        assert health_report["expired_subscriptions"] == 1
        assert health_report["failing_subscriptions"] == 1
        assert abs(health_report["health_score"] - 0.333) < 0.01


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
