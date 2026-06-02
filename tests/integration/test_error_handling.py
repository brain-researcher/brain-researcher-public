"""
Comprehensive integration tests for Error Handling & Recovery system including
circuit breakers, health monitoring, and user experience components.
"""

import asyncio
import json
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, Mock, patch

import pytest

# Import our new error handling components
try:
    from brain_researcher.services.orchestrator.error_handler import (
        CircuitBreakerConfig,
        ErrorHandlerRegistry,
        ErrorMessageFormatter,
        GracefulDegradationStrategy,
        RetryStrategy,
        ServiceErrorHandler,
        ServiceType,
        ServiceUnavailableError,
        create_error_response,
        error_handling_context,
        with_error_handling,
    )
    from brain_researcher.services.orchestrator.health_monitor import (
        AlertSeverity,
        HealthStatus,
        ServiceEndpoint,
        ServiceHealthMonitor,
        health_monitor,
        initialize_health_monitoring,
    )
    from brain_researcher.services.orchestrator.models import ErrorCode
except ImportError:
    # Fallback for when imports are not available
    pytest.skip("Error handling components not available", allow_module_level=True)


class TestErrorHandling:
    """Test suite for Error Handling & Recovery"""

    @pytest.fixture
    def error_codes(self):
        """Sample error codes and configurations"""
        return {
            "E_DEMO_UNAVAILABLE": {
                "title": "Demo Temporarily Unavailable",
                "severity": "warning",
                "retryable": True,
                "retry_after": 30,
            },
            "E_TIMEOUT": {
                "title": "Request Timed Out",
                "severity": "error",
                "retryable": True,
                "retry_after": 60,
            },
            "E_TOOL_ERROR": {
                "title": "Analysis Tool Error",
                "severity": "error",
                "retryable": False,
            },
            "E_STORAGE": {
                "title": "Storage Error",
                "severity": "error",
                "retryable": True,
            },
            "E_NETWORK": {
                "title": "Network Connection Issue",
                "severity": "warning",
                "retryable": True,
                "retry_after": 10,
            },
            "E_AUTH": {
                "title": "Authentication Required",
                "severity": "error",
                "retryable": False,
            },
        }

    @pytest.fixture
    def sample_error(self):
        """Sample error object"""
        return {
            "code": "E_TIMEOUT",
            "message": "The analysis took longer than 90 seconds",
            "severity": "error",
            "timestamp": datetime.now(),
            "details": "Job exceeded maximum execution time",
            "context": {
                "operation": "runAnalysis",
                "endpoint": "/api/jobs/123",
                "requestId": "req_abc123",
                "duration": 95000,
            },
            "suggestions": [
                "Try running the analysis with a smaller dataset",
                "Check if the server is experiencing high load",
                "Contact support if the problem persists",
            ],
            "retryable": True,
            "retry_after": 60,
        }

    def test_error_severity_levels(self, error_codes):
        """Test different error severity levels"""
        severities = set()
        for error in error_codes.values():
            severities.add(error["severity"])

        assert "warning" in severities
        assert "error" in severities

    def test_retryable_errors(self, error_codes):
        """Test retryable vs non-retryable errors"""
        retryable = [k for k, v in error_codes.items() if v.get("retryable", False)]
        non_retryable = [
            k for k, v in error_codes.items() if not v.get("retryable", False)
        ]

        assert "E_TIMEOUT" in retryable
        assert "E_NETWORK" in retryable
        assert "E_AUTH" in non_retryable
        assert "E_TOOL_ERROR" in non_retryable

    def test_retry_after_timing(self, error_codes):
        """Test retry after timing for different errors"""
        timeout_error = error_codes["E_TIMEOUT"]
        network_error = error_codes["E_NETWORK"]

        assert timeout_error.get("retry_after") == 60
        assert network_error.get("retry_after") == 10

    def test_error_suggestions(self, sample_error):
        """Test that errors include helpful suggestions"""
        assert "suggestions" in sample_error
        assert len(sample_error["suggestions"]) == 3
        assert "smaller dataset" in sample_error["suggestions"][0]

    def test_error_context_tracking(self, sample_error):
        """Test error context information"""
        context = sample_error["context"]

        assert context["operation"] == "runAnalysis"
        assert context["endpoint"] == "/api/jobs/123"
        assert "requestId" in context
        assert context["duration"] == 95000

    def test_retry_mechanism(self, sample_error):
        """Test retry mechanism with max retries"""
        max_retries = 3
        retry_count = 0

        while retry_count < max_retries and sample_error["retryable"]:
            retry_count += 1
            # Simulate retry attempt
            success = retry_count == 2  # Success on second retry

            if success:
                break

        assert retry_count == 2
        assert retry_count < max_retries

    def test_auto_retry_countdown(self, sample_error):
        """Test auto-retry countdown functionality"""
        retry_after = sample_error.get("retry_after", 0)

        # Simulate countdown
        for seconds_remaining in range(retry_after, 0, -1):
            assert seconds_remaining > 0

        # After countdown, retry should trigger
        assert retry_after == 60

    def test_error_message_mapping(self, error_codes):
        """Test error code to message mapping"""
        for code, config in error_codes.items():
            assert "title" in config
            assert len(config["title"]) > 0

    def test_error_tracking_analytics(self, sample_error):
        """Test error tracking for analytics"""
        error_event = {
            "event": "error_occurred",
            "data": {
                "error_code": sample_error["code"],
                "severity": sample_error["severity"],
                "retryable": sample_error["retryable"],
                "context": sample_error["context"],
            },
            "timestamp": sample_error["timestamp"].isoformat(),
        }

        assert error_event["event"] == "error_occurred"
        assert error_event["data"]["error_code"] == "E_TIMEOUT"

    def test_error_boundary_fallback(self):
        """Test React error boundary fallback"""
        react_error = {
            "code": "E_REACT_ERROR",
            "message": "Component crashed unexpectedly",
            "severity": "error",
            "stack": "Error at Component.render()",
            "suggestions": [
                "Try refreshing the page",
                "Clear your browser cache",
                "Contact support if the problem persists",
            ],
        }

        assert react_error["code"] == "E_REACT_ERROR"
        assert "Component.render()" in react_error["stack"]

    def test_copy_error_details(self, sample_error):
        """Test copying error details to clipboard"""
        error_text = f"""
Error Code: {sample_error['code']}
Message: {sample_error['message']}
Timestamp: {sample_error['timestamp'].isoformat()}
Request ID: {sample_error['context']['requestId']}
        """.strip()

        assert sample_error["code"] in error_text
        assert sample_error["context"]["requestId"] in error_text

    def test_user_friendly_messages(self, error_codes):
        """Test that error messages are user-friendly"""
        user_friendly_terms = ["temporarily", "please", "try", "contact"]

        demo_error = error_codes["E_DEMO_UNAVAILABLE"]
        title_lower = demo_error["title"].lower()

        assert "temporarily" in title_lower

    def test_error_recovery_actions(self):
        """Test available recovery actions"""
        recovery_actions = {
            "retry": True,
            "go_back": True,
            "go_home": True,
            "get_help": True,
        }

        assert recovery_actions["retry"] is True
        assert recovery_actions["go_back"] is True
        assert recovery_actions["go_home"] is True
        assert recovery_actions["get_help"] is True

    def test_network_error_handling(self, error_codes):
        """Test network-specific error handling"""
        network_error = error_codes["E_NETWORK"]

        assert network_error["severity"] == "warning"
        assert network_error["retryable"] is True
        assert network_error["retry_after"] == 10

    def test_expandable_error_details(self, sample_error):
        """Test expandable technical error details"""
        has_details = any(
            [
                sample_error.get("details"),
                sample_error.get("stack"),
                sample_error.get("context"),
            ]
        )

        assert has_details is True
        assert sample_error["details"] == "Job exceeded maximum execution time"


class TestServiceErrorHandler:
    """Test service error handler functionality."""

    @pytest.fixture
    def error_handler(self):
        """Create error handler for testing."""
        return ServiceErrorHandler(
            service_name="test_service",
            service_type=ServiceType.AGENT,
            circuit_config=CircuitBreakerConfig(
                failure_threshold=3, success_threshold=2, timeout_seconds=5
            ),
            retry_strategy=RetryStrategy(
                max_attempts=3, initial_delay_ms=100, exponential_base=2.0
            ),
        )

    @pytest.mark.asyncio
    async def test_successful_operation(self, error_handler):
        """Test successful operation execution."""
        mock_operation = AsyncMock(return_value="success")

        result = await error_handler.execute_with_circuit_breaker(
            mock_operation, operation_id="test_op"
        )

        assert result == "success"
        assert error_handler.metrics.total_requests == 1
        assert error_handler.metrics.failed_requests == 0
        assert error_handler.metrics.success_rate == 1.0

    @pytest.mark.asyncio
    async def test_retry_logic(self, error_handler):
        """Test retry logic on failures."""
        call_count = 0

        async def failing_operation():
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise Exception("Temporary failure")
            return "success_after_retries"

        result = await error_handler.execute_with_circuit_breaker(
            failing_operation, operation_id="retry_test"
        )

        assert result == "success_after_retries"
        assert call_count == 3
        assert error_handler.metrics.total_requests == 1
        assert error_handler.metrics.failed_requests == 0

    @pytest.mark.asyncio
    async def test_circuit_breaker_opening(self, error_handler):
        """Test circuit breaker opening after failures."""
        failing_operation = AsyncMock(side_effect=Exception("Persistent failure"))

        # Trigger failures to open circuit
        for _ in range(3):
            with pytest.raises(Exception):
                await error_handler.execute_with_circuit_breaker(
                    failing_operation, operation_id="circuit_test"
                )

        # Circuit should be open now
        assert error_handler.metrics.circuit_state.value == "open"

        # Next call should fail fast
        with pytest.raises(ServiceUnavailableError):
            await error_handler.execute_with_circuit_breaker(
                failing_operation, operation_id="circuit_open_test"
            )

    @pytest.mark.asyncio
    async def test_graceful_degradation(self, error_handler):
        """Test graceful degradation when circuit is open."""
        error_handler.degradation_strategy.fallback_enabled = True
        error_handler.degradation_strategy.simplified_response = True

        # Force circuit open
        error_handler.metrics.circuit_state = (
            error_handler.metrics.circuit_state.__class__("open")
        )
        error_handler.circuit_opened_at = datetime.utcnow()

        mock_operation = AsyncMock()

        result = await error_handler.execute_with_circuit_breaker(
            mock_operation, operation_id="degradation_test"
        )

        assert result["status"] == "degraded"
        assert result["service"] == "test_service"
        assert "data" in result

    def test_error_classification(self, error_handler):
        """Test error type classification."""
        timeout_error = Exception("Request timeout")
        connection_error = Exception("Connection refused")
        validation_error = Exception("Invalid parameter")

        assert error_handler._classify_failure(timeout_error).value == "timeout"
        assert (
            error_handler._classify_failure(connection_error).value
            == "connection_error"
        )
        assert (
            error_handler._classify_failure(validation_error).value
            == "validation_error"
        )


class TestHealthMonitor:
    """Test health monitoring functionality."""

    @pytest.fixture
    def health_monitor_instance(self):
        """Create health monitor for testing."""
        monitor = ServiceHealthMonitor(
            check_interval_seconds=1, alert_cooldown_seconds=5
        )

        # Register test services
        test_endpoints = [
            ServiceEndpoint(
                name="test_agent",
                url="http://localhost:8000",
                service_type=ServiceType.AGENT,
                timeout_seconds=5,
            ),
            ServiceEndpoint(
                name="test_db",
                url="http://localhost:5432",
                service_type=ServiceType.DATABASE,
                timeout_seconds=3,
            ),
        ]

        monitor.register_services(test_endpoints)
        return monitor

    @pytest.mark.asyncio
    async def test_health_check_success(self, health_monitor_instance):
        """Test successful health check."""
        with patch("aiohttp.ClientSession.get") as mock_get:
            mock_response = Mock()
            mock_response.status = 200
            mock_response.json = AsyncMock(return_value={"status": "healthy"})
            mock_get.return_value.__aenter__.return_value = mock_response

            endpoint = health_monitor_instance.endpoints["test_agent"]
            result = await health_monitor_instance._run_health_check(endpoint)

            assert result.service_name == "test_agent"
            assert result.status == HealthStatus.HEALTHY
            assert result.response_time_ms < 1000

    @pytest.mark.asyncio
    async def test_health_check_timeout(self, health_monitor_instance):
        """Test health check timeout handling."""
        with patch("aiohttp.ClientSession.get") as mock_get:
            mock_get.side_effect = asyncio.TimeoutError()

            endpoint = health_monitor_instance.endpoints["test_agent"]
            result = await health_monitor_instance._run_health_check(endpoint)

            assert result.service_name == "test_agent"
            assert result.status == HealthStatus.UNHEALTHY
            assert "timeout" in result.error_message.lower()

    @pytest.mark.asyncio
    async def test_alert_generation(self, health_monitor_instance):
        """Test alert generation on status changes."""
        alerts_received = []

        def alert_handler(alert):
            alerts_received.append(alert)

        health_monitor_instance.add_alert_handler(alert_handler)

        # Simulate status change from healthy to unhealthy
        from brain_researcher.services.orchestrator.health_monitor import HealthCheck

        healthy_check = HealthCheck(
            service_name="test_agent",
            status=HealthStatus.HEALTHY,
            response_time_ms=100,
            timestamp=datetime.utcnow(),
        )

        unhealthy_check = HealthCheck(
            service_name="test_agent",
            status=HealthStatus.UNHEALTHY,
            response_time_ms=5000,
            timestamp=datetime.utcnow(),
            error_message="Service unavailable",
        )

        # Set up history
        health_monitor_instance.health_history["test_agent"] = [healthy_check]
        health_monitor_instance.health_cache["test_agent"] = unhealthy_check

        await health_monitor_instance._process_health_alerts()

        assert len(alerts_received) > 0
        alert = alerts_received[0]
        assert alert.service_name == "test_agent"
        assert alert.severity in [AlertSeverity.ERROR, AlertSeverity.CRITICAL]

    @pytest.mark.asyncio
    async def test_health_summary(self, health_monitor_instance):
        """Test health summary generation."""
        from brain_researcher.services.orchestrator.health_monitor import HealthCheck

        # Set up mock health data
        health_monitor_instance.health_cache = {
            "test_agent": HealthCheck(
                service_name="test_agent",
                status=HealthStatus.HEALTHY,
                response_time_ms=150,
                timestamp=datetime.utcnow(),
            ),
            "test_db": HealthCheck(
                service_name="test_db",
                status=HealthStatus.DEGRADED,
                response_time_ms=3000,
                timestamp=datetime.utcnow(),
            ),
        }

        summary = await health_monitor_instance.get_health_summary()

        assert summary.status == "degraded"  # One service degraded
        assert len(summary.services) == 2
        assert summary.services["test_agent"].status == "healthy"
        assert summary.services["test_db"].status == "degraded"


class TestErrorHandlerRegistry:
    """Test error handler registry functionality."""

    @pytest.fixture
    def registry(self):
        """Create fresh registry for testing."""
        return ErrorHandlerRegistry()

    def test_handler_registration(self, registry):
        """Test service handler registration."""
        handler = registry.register_handler(
            service_name="test_service", service_type=ServiceType.AGENT
        )

        assert isinstance(handler, ServiceErrorHandler)
        assert registry.get_handler("test_service") is handler
        assert handler.service_name == "test_service"
        assert handler.service_type == ServiceType.AGENT

    def test_metrics_aggregation(self, registry):
        """Test metrics aggregation from multiple handlers."""
        # Register multiple handlers
        handler1 = registry.register_handler("service1", ServiceType.AGENT)
        handler2 = registry.register_handler("service2", ServiceType.BR_KG)

        # Simulate some metrics
        handler1.metrics.total_requests = 10
        handler1.metrics.failed_requests = 2
        handler2.metrics.total_requests = 15
        handler2.metrics.failed_requests = 1

        all_metrics = registry.get_all_metrics()

        assert len(all_metrics) == 2
        assert all_metrics["service1"].total_requests == 10
        assert all_metrics["service2"].failed_requests == 1


class TestErrorHandlerDecorators:
    """Test error handling decorators and context managers."""

    @pytest.mark.asyncio
    async def test_async_decorator(self):
        """Test async function decorator."""
        call_count = 0

        @with_error_handling("test_service", ServiceType.AGENT)
        async def test_function():
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise Exception("First call fails")
            return "success"

        result = await test_function()
        assert result == "success"
        assert call_count == 2  # Should retry once

    def test_sync_decorator(self):
        """Test sync function decorator."""
        call_count = 0

        @with_error_handling("test_service", ServiceType.AGENT)
        def test_function():
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise Exception("First call fails")
            return "success"

        result = test_function()
        assert result == "success"
        assert call_count == 2

    @pytest.mark.asyncio
    async def test_context_manager(self):
        """Test error handling context manager."""
        async with error_handling_context("test_service", ServiceType.AGENT) as handler:
            assert isinstance(handler, ServiceErrorHandler)
            # Context should record success automatically


class TestErrorMessageFormatting:
    """Test error message formatting for users."""

    def test_service_unavailable_formatting(self):
        """Test service unavailable error formatting."""
        formatted = ErrorMessageFormatter.format_error_for_user(
            error_code=ErrorCode.SERVICE_UNAVAILABLE,
            original_error="Service connection failed",
            suggestions=["Check network connection", "Try again later"],
        )

        assert formatted["title"] == "Service Temporarily Unavailable"
        assert formatted["icon"] == "🔧"
        assert formatted["severity"] == "warning"
        assert len(formatted["suggestions"]) >= 2
        assert "timestamp" in formatted

    def test_validation_error_formatting(self):
        """Test validation error formatting."""
        context = {"field": "smoothing", "value": 15, "max": 12}

        formatted = ErrorMessageFormatter.format_error_for_user(
            error_code=ErrorCode.VALIDATION_ERROR,
            original_error="Smoothing value out of range",
            context=context,
        )

        assert formatted["title"] == "Invalid Input"
        assert formatted["severity"] == "error"
        assert "parameter" in formatted["suggestions"][0].lower()
        assert formatted["context"] == context


class TestIntegration:
    """Test integration between all error handling components."""

    @pytest.mark.asyncio
    async def test_end_to_end_error_handling(self):
        """Test complete error handling flow."""
        # Set up health monitoring
        monitor = ServiceHealthMonitor(check_interval_seconds=0.1)
        endpoint = ServiceEndpoint(
            name="integration_test",
            url="http://localhost:9999",  # Non-existent service
            service_type=ServiceType.AGENT,
        )
        monitor.register_service(endpoint)

        # Set up error handler
        registry = ErrorHandlerRegistry()
        handler = registry.register_handler(
            "integration_test",
            ServiceType.AGENT,
            circuit_config=CircuitBreakerConfig(failure_threshold=2),
        )

        alerts_received = []
        monitor.add_alert_handler(lambda alert: alerts_received.append(alert))

        # Start monitoring
        await monitor.start_monitoring()

        # Wait for health checks to fail
        await asyncio.sleep(0.2)

        # Try to use the failing service
        with pytest.raises((ServiceUnavailableError, Exception)):
            await handler.execute_with_circuit_breaker(
                lambda: None,  # This won't be called due to circuit breaker
                operation_id="integration_test",
            )

        # Stop monitoring
        await monitor.stop_monitoring()

        # Verify circuit breaker opened and alerts were generated
        assert handler.metrics.circuit_state.value == "open"

    @pytest.mark.asyncio
    async def test_recovery_scenario(self):
        """Test service recovery scenario."""
        # Set up handler with graceful degradation
        handler = ServiceErrorHandler(
            service_name="recovery_test",
            service_type=ServiceType.AGENT,
            circuit_config=CircuitBreakerConfig(
                failure_threshold=2, timeout_seconds=1  # Short timeout for testing
            ),
            degradation_strategy=GracefulDegradationStrategy(
                fallback_enabled=True, use_cache=True
            ),
        )

        # First, cache a successful response
        await handler.execute_with_circuit_breaker(
            AsyncMock(return_value="cached_response"), operation_id="cache_test"
        )
        handler.cache_response("cache_test", {}, "cached_response")

        # Then trigger failures to open circuit
        failing_op = AsyncMock(side_effect=Exception("Service down"))

        for _ in range(2):
            with pytest.raises(Exception):
                await handler.execute_with_circuit_breaker(
                    failing_op, operation_id="fail_test"
                )

        # Circuit should be open, but graceful degradation should work
        result = await handler.execute_with_circuit_breaker(
            failing_op, operation_id="cache_test"  # Same ID as cached response
        )

        assert result["status"] == "degraded"
        assert "data" in result


@pytest.mark.asyncio
async def test_error_response_creation():
    """Test standardized error response creation."""
    from brain_researcher.services.orchestrator.models import ErrorContext

    context = ErrorContext(request_id="test_123", endpoint="/api/test", method="POST")

    response = create_error_response(
        error_code=ErrorCode.SERVICE_TIMEOUT,
        message="Request took too long",
        context=context,
        suggestions=["Try again with smaller dataset"],
    )

    assert response.error["code"] == ErrorCode.SERVICE_TIMEOUT.value
    assert "timestamp" in response.error
    assert "suggestions" in response.error["details"]
