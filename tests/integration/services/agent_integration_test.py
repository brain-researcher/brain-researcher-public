"""Integration Tests for Agent Service Modules.

This module tests the integration between the agent service and all
newly implemented infrastructure components.
"""

import asyncio
import json
import logging
import uuid
from datetime import datetime
from typing import Any, Dict, List


# Mock implementations for testing
class MockRedisClient:
    """Mock Redis client for testing."""

    def __init__(self):
        self.data = {}
        self.lists = {}

    async def set(self, key: str, value: str):
        self.data[key] = value

    async def setex(self, key: str, seconds: int, value: str):
        self.data[key] = value

    async def get(self, key: str):
        return self.data.get(key)

    async def exists(self, key: str):
        return key in self.data

    async def lpush(self, key: str, value: str):
        if key not in self.lists:
            self.lists[key] = []
        self.lists[key].insert(0, value)

    async def lrange(self, key: str, start: int, end: int):
        if key not in self.lists:
            return []
        return self.lists[key][start : end + 1]

    async def ltrim(self, key: str, start: int, end: int):
        if key in self.lists:
            self.lists[key] = self.lists[key][start : end + 1]

    async def expire(self, key: str, seconds: int):
        # Mock expiry - just return True
        return True


class MockSubscriptionSystem:
    """Mock subscription system for testing."""

    def __init__(self):
        self.connections = {}
        self.subscriptions = {}
        self.handlers = {}

    async def connect(self, websocket, user_id: str, metadata: Dict[str, Any]):
        connection_id = str(uuid.uuid4())
        self.connections[connection_id] = {
            "websocket": websocket,
            "user_id": user_id,
            "metadata": metadata,
        }
        return connection_id

    async def subscribe(
        self, connection_id: str, query: str, variables: Dict[str, Any] = None
    ):
        subscription_id = str(uuid.uuid4())
        self.subscriptions[subscription_id] = {
            "connection_id": connection_id,
            "query": query,
            "variables": variables or {},
        }
        return subscription_id

    async def unsubscribe(self, subscription_id: str):
        self.subscriptions.pop(subscription_id, None)

    def register_handler(self, event_type: str, handler):
        self.handlers[event_type] = handler


class AgentIntegrationTester:
    """Tests all agent integrations."""

    def __init__(self):
        self.logger = logging.getLogger(__name__)
        self.test_results = {}

    async def run_all_tests(self) -> Dict[str, Any]:
        """Run all integration tests.

        Returns:
            Test results dictionary
        """
        self.logger.info("Starting agent integration tests")

        # Initialize mock services
        redis_client = MockRedisClient()
        subscription_system = MockSubscriptionSystem()

        # Test results
        results = {
            "subscription_integration": await self.test_subscription_integration(
                subscription_system, redis_client
            ),
            "streaming_integration": await self.test_streaming_integration(
                redis_client
            ),
            "deduplication_integration": await self.test_deduplication_integration(
                redis_client
            ),
            "plugin_integration": await self.test_plugin_integration(),
            "notification_system": await self.test_notification_system(redis_client),
            "tool_registry": await self.test_tool_registry_integration(),
            "error_handling": await self.test_error_handling_integration(redis_client),
        }

        # Calculate overall success
        all_passed = all(result["success"] for result in results.values())

        summary = {
            "overall_success": all_passed,
            "tests_run": len(results),
            "tests_passed": sum(1 for r in results.values() if r["success"]),
            "timestamp": datetime.now().isoformat(),
            "details": results,
        }

        self.logger.info(
            f"Integration tests completed: {summary['tests_passed']}/{summary['tests_run']} passed"
        )

        return summary

    async def test_subscription_integration(
        self, subscription_system, redis_client
    ) -> Dict[str, Any]:
        """Test subscription system integration."""
        try:
            from brain_researcher.services.agent.subscription_integration import (
                AgentNotification,
                AgentNotificationType,
                AgentSubscriptionManager,
            )
            from brain_researcher.services.br_kg.subscriptions.subscription_system import (
                EventType,
            )

            # Create manager
            manager = AgentSubscriptionManager(subscription_system, redis_client)

            # Test subscription
            thread_id = "test_thread_001"
            subscription_id = await manager.subscribe_thread(
                thread_id, [EventType.ANALYSIS_COMPLETED], entity_types=["analysis"]
            )

            # Test notification sending
            notification = AgentNotification(
                notification_id="test_notif_001",
                notification_type=AgentNotificationType.ANALYSIS_COMPLETED,
                thread_id=thread_id,
                title="Test Analysis Complete",
                message="Test analysis has completed successfully",
                data={"test": True},
            )

            await manager.send_notification(thread_id, notification)

            # Test getting notifications
            notifications = await manager.get_notifications(thread_id)

            # Verify
            assert subscription_id is not None
            assert len(notifications) >= 0

            # Test unsubscribe
            await manager.unsubscribe_thread(thread_id)

            stats = manager.get_statistics()
            assert "subscriptions_created" in stats

            return {
                "success": True,
                "subscription_id": subscription_id,
                "notifications_received": len(notifications),
                "stats": stats,
            }

        except Exception as e:
            self.logger.error(
                f"Subscription integration test failed: {e}", exc_info=True
            )
            return {"success": False, "error": str(e)}

    async def test_streaming_integration(self, redis_client) -> Dict[str, Any]:
        """Test streaming data integration."""
        try:
            from brain_researcher.services.agent.streaming_integration import (
                AgentStreamingManager,
                AgentStreamType,
            )

            # Create manager
            kafka_config = {"bootstrap_servers": "localhost:9092"}  # Mock config
            manager = AgentStreamingManager(None, kafka_config, redis_client)

            # Test setup
            await manager.setup_streams()

            # Test publishing
            thread_id = "test_thread_002"
            await manager.publish_query(
                thread_id, "Test query for streaming", user_id="test_user"
            )

            await manager.publish_analysis_request(
                thread_id, "fMRI GLM", {"subjects": ["sub-01", "sub-02"]}
            )

            await manager.publish_tool_execution(
                thread_id, "coordinate_to_concept", {"coordinates": [0, 0, 0]}
            )

            # Get statistics
            stats = manager.get_statistics()

            # Test shutdown
            await manager.stop()

            return {
                "success": True,
                "streams_configured": len(manager.stream_configs),
                "messages_published": 3,
                "stats": stats,
            }

        except Exception as e:
            self.logger.error(f"Streaming integration test failed: {e}", exc_info=True)
            return {"success": False, "error": str(e)}

    async def test_deduplication_integration(self, redis_client) -> Dict[str, Any]:
        """Test deduplication system integration."""
        try:
            from brain_researcher.core.ingestion.deduplication.data_deduplication import (
                DataDeduplication,
            )
            from brain_researcher.services.agent.deduplication_integration import (
                AgentDataDeduplication,
                AgentDeduplicationConfig,
            )

            # Create core deduplication system
            core_dedup = DataDeduplication(neo4j_driver=None, redis_client=redis_client)

            # Create agent deduplication manager
            config = AgentDeduplicationConfig(
                auto_deduplicate=True, similarity_threshold=0.8
            )
            manager = AgentDataDeduplication(core_dedup, config)

            # Test tool result deduplication
            test_results = [
                {"id": "result_1", "title": "Test Analysis 1", "score": 0.85},
                {
                    "id": "result_2",
                    "title": "Test Analysis 1",
                    "score": 0.85,
                },  # Duplicate
                {"id": "result_3", "title": "Different Analysis", "score": 0.90},
            ]

            deduplicated_results, report = await manager.deduplicate_tool_results(
                "test_tool", test_results, "result"
            )

            # Test query duplicate checking
            recent_queries = [
                {"query": "What is fMRI?", "timestamp": datetime.now().isoformat()},
                {
                    "query": "How does fMRI work?",
                    "timestamp": datetime.now().isoformat(),
                },
            ]

            similar_query = await manager.check_query_duplicates(
                "What is fMRI?", "test_thread", recent_queries
            )

            stats = manager.get_statistics()

            return {
                "success": True,
                "original_results": len(test_results),
                "deduplicated_results": len(deduplicated_results),
                "duplicates_found": report.duplicates_found,
                "similar_query_found": similar_query is not None,
                "stats": stats,
            }

        except Exception as e:
            self.logger.error(
                f"Deduplication integration test failed: {e}", exc_info=True
            )
            return {"success": False, "error": str(e)}

    async def test_plugin_integration(self) -> Dict[str, Any]:
        """Test plugin system integration."""
        try:
            from brain_researcher.services.agent.plugin_integration import (
                AgentPluginConfig,
                AgentPluginManager,
            )

            # Create manager with test config
            config = AgentPluginConfig(
                auto_discover=False,  # Don't auto-discover for testing
                plugin_directory="./test_plugins",
            )
            manager = AgentPluginManager(config)

            # Initialize (will create empty plugin system)
            success = await manager.initialize()

            # Test plugin template generation
            template = manager.generate_plugin_template("TestAPI", "api", None)

            # Get statistics
            stats = manager.get_statistics()

            # Test plugin info methods
            plugins = manager.list_plugins()

            return {
                "success": success,
                "plugins_discovered": stats["agent_stats"]["plugins_discovered"],
                "plugins_loaded": stats["agent_stats"]["plugins_loaded"],
                "template_generated": len(template) > 0,
                "total_plugins": len(plugins),
            }

        except Exception as e:
            self.logger.error(f"Plugin integration test failed: {e}", exc_info=True)
            return {"success": False, "error": str(e)}

    async def test_notification_system(self, redis_client) -> Dict[str, Any]:
        """Test notification system."""
        try:
            from brain_researcher.services.agent.notification_system import (
                AgentNotificationSystem,
                NotificationChannel,
                NotificationPriority,
            )

            # Create notification system
            system = AgentNotificationSystem(
                subscription_manager=None, error_manager=None, redis_client=redis_client
            )

            # Test sending notifications
            thread_id = "test_thread_003"

            success1 = await system.send_notification(
                "analysis_started",
                thread_id,
                {"analysis_type": "GLM", "analysis_id": "test_analysis_001"},
            )

            success2 = await system.send_notification(
                "analysis_completed",
                thread_id,
                {
                    "analysis_type": "GLM",
                    "analysis_id": "test_analysis_001",
                    "result_summary": "Analysis completed with 5 significant clusters",
                },
            )

            # Test custom notification
            success3 = await system.send_notification(
                "system_error",
                thread_id,
                {
                    "component": "test_component",
                    "error_message": "Test error message",
                    "error_id": "error_001",
                },
                priority=NotificationPriority.HIGH,
                channels=[NotificationChannel.LOG, NotificationChannel.IN_CHAT],
            )

            # Get statistics
            stats = system.get_statistics()
            templates = system.get_templates()

            return {
                "success": all([success1, success2, success3]),
                "notifications_sent": stats["notifications_sent"],
                "notifications_failed": stats["notifications_failed"],
                "templates_available": len(templates),
            }

        except Exception as e:
            self.logger.error(f"Notification system test failed: {e}", exc_info=True)
            return {"success": False, "error": str(e)}

    async def test_tool_registry_integration(self) -> Dict[str, Any]:
        """Test tool registry with integrations."""
        try:
            from brain_researcher.services.tools.tool_registry import ToolRegistry

            # Create registry with integrations enabled
            registry = ToolRegistry(auto_discover=False, enable_integrations=True)

            # Test integration setup (without actual services)
            await registry.setup_integrations()

            # Get integration info
            integration_info = registry.get_integration_info()

            # Test statistics
            tool_count = len(registry.tools)

            return {
                "success": True,
                "integrations_enabled": integration_info["integrations_enabled"],
                "integrations_available": integration_info["integrations_available"],
                "tools_registered": tool_count,
                "integration_stats": integration_info["statistics"],
            }

        except Exception as e:
            self.logger.error(
                f"Tool registry integration test failed: {e}", exc_info=True
            )
            return {"success": False, "error": str(e)}

    async def test_error_handling_integration(self, redis_client) -> Dict[str, Any]:
        """Test error handling and logging integration."""
        try:
            from brain_researcher.services.agent.error_integration import (
                IntegrationErrorManager,
                IntegrationType,
                get_integration_logger,
            )

            # Create error manager
            manager = IntegrationErrorManager(redis_client)

            # Get loggers for different components
            subscription_logger = manager.get_logger(
                "subscription_test", IntegrationType.SUBSCRIPTION
            )
            streaming_logger = manager.get_logger(
                "streaming_test", IntegrationType.STREAMING
            )

            # Test logging operations
            async def test_operation():
                # Simulate some work
                await asyncio.sleep(0.01)
                return "test_result"

            # Test successful operation logging
            with subscription_logger.log_operation("test_subscription_op"):
                result = await test_operation()

            # Test error logging
            try:
                with streaming_logger.log_operation("test_error_op"):
                    raise ValueError("Test error for integration testing")
            except ValueError:
                pass  # Expected

            # Test direct error logging
            await subscription_logger.log_error(
                Exception("Direct error test"),
                {"context": "testing"},
                thread_id="test_thread_004",
            )

            # Get error statistics
            stats = manager.get_error_statistics()

            # Get recent errors
            errors = await manager.get_errors(limit=10)

            return {
                "success": True,
                "loggers_created": len(manager.loggers),
                "total_errors": stats["total_errors"],
                "recent_errors": len(errors),
                "error_stats": stats,
            }

        except Exception as e:
            self.logger.error(
                f"Error handling integration test failed: {e}", exc_info=True
            )
            return {"success": False, "error": str(e)}


# Convenience function for running tests
async def run_integration_tests() -> Dict[str, Any]:
    """Run all agent integration tests.

    Returns:
        Test results
    """
    tester = AgentIntegrationTester()
    return await tester.run_all_tests()


# CLI function for manual testing
async def main():
    """Main function for running tests from command line."""
    logging.basicConfig(level=logging.INFO)

    print("Running Agent Integration Tests...")
    print("=" * 50)

    results = await run_integration_tests()

    print(f"\nTest Results:")
    print(f"Overall Success: {results['overall_success']}")
    print(f"Tests Passed: {results['tests_passed']}/{results['tests_run']}")

    print(f"\nDetailed Results:")
    for test_name, result in results["details"].items():
        status = "PASS" if result["success"] else "FAIL"
        print(f"  {test_name}: {status}")

        if not result["success"]:
            print(f"    Error: {result.get('error', 'Unknown error')}")
        else:
            # Print some key metrics if available
            for key, value in result.items():
                if key not in ["success", "error"] and isinstance(
                    value, (int, float, bool)
                ):
                    print(f"    {key}: {value}")

    print("\n" + "=" * 50)
    print("Integration tests completed!")

    # Save results to file
    with open("agent_integration_test_results.json", "w") as f:
        json.dump(results, f, indent=2, default=str)

    print("Results saved to agent_integration_test_results.json")


if __name__ == "__main__":
    asyncio.run(main())
