"""
Unit tests for Sentry Integration (TELEMETRY-002)
Tests error tracking, PII filtering, and context enrichment
"""

import os
from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest

from brain_researcher.services.telemetry.models import ServiceType
from brain_researcher.services.telemetry.sentry_integration import (
    ContextEnricher,
    PIIFilter,
    SentryConfig,
    SentryContext,
    SentryIntegration,
    capture_exception_with_context,
    capture_message_with_context,
    create_sentry_config_from_env,
    get_sentry,
    initialize_sentry,
    track_errors,
)


@pytest.fixture
def sentry_config():
    """Create test Sentry configuration."""
    return SentryConfig(
        dsn="https://test@sentry.io/123456",
        environment="test",
        release="1.0.0",
        sample_rate=1.0,
        traces_sample_rate=0.1,
        enable_pii_filtering=True,
        enable_tracing=True,
        debug=False,
    )


@pytest.fixture
def mock_sentry_sdk():
    """Mock Sentry SDK functions."""
    with patch(
        "brain_researcher.services.telemetry.sentry_integration.sentry_sdk"
    ) as mock:
        mock.init = MagicMock()
        mock.capture_exception = MagicMock(return_value="mock_event_id")
        mock.capture_message = MagicMock(return_value="mock_message_id")
        mock.add_breadcrumb = MagicMock()
        mock.start_transaction = MagicMock()
        yield mock


@pytest.fixture
def sentry_integration(sentry_config, mock_sentry_sdk):
    """Create SentryIntegration instance."""
    with patch(
        "brain_researcher.services.telemetry.sentry_integration.SENTRY_AVAILABLE", True
    ):
        integration = SentryIntegration(sentry_config)
        integration.is_initialized = True
        return integration


class TestPIIFilter:
    """Test PII filtering functionality."""

    def test_filter_email(self):
        """Test email filtering."""
        pii_filter = PIIFilter()
        text = "Contact me at john.doe@example.com for details"
        filtered = pii_filter.filter_string(text)
        assert "john.doe@example.com" not in filtered
        assert "[EMAIL_FILTERED]" in filtered

    def test_filter_phone(self):
        """Test phone number filtering."""
        pii_filter = PIIFilter()
        text = "Call me at 555-123-4567 or (555) 987-6543"
        filtered = pii_filter.filter_string(text)
        assert "555-123-4567" not in filtered
        assert "(555) 987-6543" not in filtered
        assert "[PHONE_FILTERED]" in filtered

    def test_filter_credit_card(self):
        """Test credit card filtering."""
        pii_filter = PIIFilter()
        text = "Card number: 1234 5678 9012 3456"
        filtered = pii_filter.filter_string(text)
        assert "1234 5678 9012 3456" not in filtered
        assert "[CARD_FILTERED]" in filtered

    def test_filter_api_key(self):
        """Test API key filtering."""
        pii_filter = PIIFilter()
        api_key = "sk_test_" + "4eC39HqLyjWDarjtT1zdp7dc"
        text = f"API Key: {api_key}"
        filtered = pii_filter.filter_string(text)
        assert api_key not in filtered
        assert "[API_KEY_FILTERED]" in filtered

    def test_filter_jwt_token(self):
        """Test JWT token filtering."""
        pii_filter = PIIFilter()
        jwt_token = ".".join(
            [
                "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9",
                "eyJzdWIiOiIxMjM0NTY3ODkwIn0",
                "TJVA95OrM7E2cBab30RMHrHDcEfxjoYZgeFONFh7HgQ",
            ]
        )
        text = f"Token: {jwt_token}"
        filtered = pii_filter.filter_string(text)
        assert "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9" not in filtered
        assert "[JWT_FILTERED]" in filtered

    def test_filter_dict_sensitive_fields(self):
        """Test filtering sensitive fields in dictionaries."""
        pii_filter = PIIFilter()
        data = {
            "username": "john_doe",
            "password": "secret123",
            "api_key": "sk_test_123",
            "email": "john@example.com",
            "safe_field": "public_data",
        }

        filtered = pii_filter.filter_dict(data)
        assert filtered["password"] == "[FILTERED]"
        assert filtered["api_key"] == "[FILTERED]"
        assert filtered["email"] == "[FILTERED]"
        assert filtered["safe_field"] == "public_data"

    def test_filter_nested_dict(self):
        """Test filtering nested dictionaries."""
        pii_filter = PIIFilter()
        data = {
            "user": {
                "name": "John Doe",
                "credentials": {"password": "secret", "token": "bearer_123"},
            },
            "metadata": {"timestamp": "2025-01-01"},
        }

        filtered = pii_filter.filter_dict(data)
        assert filtered["user"]["credentials"]["password"] == "[FILTERED]"
        assert filtered["user"]["credentials"]["token"] == "[FILTERED]"
        assert filtered["metadata"]["timestamp"] == "2025-01-01"

    def test_filter_list(self):
        """Test filtering lists."""
        pii_filter = PIIFilter()
        data = [
            "safe_string",
            "email@example.com",
            {"password": "secret"},
            ["nested", "555-1234"],
        ]

        filtered = pii_filter.filter_list(data)
        assert filtered[0] == "safe_string"
        assert "[EMAIL_FILTERED]" in filtered[1]
        assert filtered[2]["password"] == "[FILTERED]"
        assert "[PHONE_FILTERED]" in filtered[3][1]


class TestContextEnricher:
    """Test context enrichment functionality."""

    def test_enrich_event_with_service_context(self):
        """Test enriching event with service context."""
        from brain_researcher.services.telemetry.sentry_integration import (
            current_service_context,
        )

        current_service_context.set(ServiceType.ORCHESTRATOR)

        event = {}
        hint = {}

        enriched = ContextEnricher.enrich_event(event, hint)

        assert enriched["tags"]["service"] == ServiceType.ORCHESTRATOR
        assert enriched["contexts"]["service"]["name"] == ServiceType.ORCHESTRATOR
        assert "brain_researcher" in enriched["contexts"]

    def test_enrich_event_with_user_context(self):
        """Test enriching event with user context."""
        from brain_researcher.services.telemetry.sentry_integration import (
            current_user_context,
        )

        current_user_context.set(
            {"user_hash": "hashed_user_123", "session_hash": "hashed_session_456"}
        )

        event = {}
        hint = {}

        enriched = ContextEnricher.enrich_event(event, hint)

        assert enriched["user"]["id"] == "hashed_user_123"
        assert enriched["user"]["session_id"] == "hashed_session_456"

    def test_enrich_event_with_request_context(self):
        """Test enriching event with request context."""
        mock_request = MagicMock()
        mock_request.url = "https://api.example.com/test"
        mock_request.method = "POST"

        event = {}
        hint = {"request": mock_request}

        enriched = ContextEnricher.enrich_event(event, hint)

        assert enriched["request"]["url"] == "https://api.example.com/test"
        assert enriched["request"]["method"] == "POST"

    def test_enrich_event_adds_timestamp(self):
        """Test that enrichment adds timestamp."""
        event = {}
        hint = {}

        enriched = ContextEnricher.enrich_event(event, hint)

        assert "timestamp" in enriched
        # Verify it's a valid ISO format timestamp
        datetime.fromisoformat(enriched["timestamp"])


class TestSentryIntegration:
    """Test SentryIntegration main functionality."""

    def test_initialization_with_dsn(self, sentry_config, mock_sentry_sdk):
        """Test Sentry initialization with DSN."""
        with patch(
            "brain_researcher.services.telemetry.sentry_integration.SENTRY_AVAILABLE",
            True,
        ):
            SentryIntegration(sentry_config)

            mock_sentry_sdk.init.assert_called_once()
            call_kwargs = mock_sentry_sdk.init.call_args.kwargs

            assert call_kwargs["dsn"] == sentry_config.dsn
            assert call_kwargs["environment"] == "test"
            assert call_kwargs["release"] == "1.0.0"
            assert call_kwargs["sample_rate"] == 1.0
            assert call_kwargs["traces_sample_rate"] == 0.1
            assert not call_kwargs["send_default_pii"]

    def test_initialization_without_dsn(self, mock_sentry_sdk):
        """Test Sentry initialization without DSN."""
        config = SentryConfig(dsn=None)

        with patch(
            "brain_researcher.services.telemetry.sentry_integration.SENTRY_AVAILABLE",
            True,
        ):
            integration = SentryIntegration(config)

            mock_sentry_sdk.init.assert_not_called()
            assert not integration.is_initialized

    def test_before_send_filter_ignored_exceptions(self, sentry_integration):
        """Test filtering of ignored exceptions."""
        event = {"logger": "test_logger"}
        hint = {"exc_info": (KeyboardInterrupt, KeyboardInterrupt(), None)}

        result = sentry_integration._before_send_filter(event, hint)
        assert result is None  # Event should be filtered

    def test_before_send_filter_ignored_loggers(self, sentry_integration):
        """Test filtering of ignored loggers."""
        event = {"logger": "urllib3.connectionpool"}
        hint = {}

        result = sentry_integration._before_send_filter(event, hint)
        assert result is None  # Event should be filtered

    def test_before_send_filter_applies_pii_filtering(self, sentry_integration):
        """Test PII filtering in before_send."""
        event = {
            "request": {"data": {"email": "user@example.com", "safe_data": "public"}},
            "extra": {"password": "secret123"},
        }
        hint = {}

        with patch.object(sentry_integration.pii_filter, "filter_dict") as mock_filter:
            mock_filter.side_effect = lambda x: {
                k: "[FILTERED]" if k == "password" else v for k, v in x.items()
            }

            sentry_integration._before_send_filter(event, hint)
            assert mock_filter.called

    def test_set_user_context(self, sentry_integration):
        """Test setting user context."""
        with patch(
            "brain_researcher.services.telemetry.sentry_integration.configure_scope"
        ) as mock_scope:
            scope_instance = MagicMock()
            mock_scope.return_value.__enter__.return_value = scope_instance

            sentry_integration.set_user_context("user123", "session456")

            # Verify context was set
            scope_instance.set_user.assert_called_once()
            call_args = scope_instance.set_user.call_args[0][0]
            assert "id" in call_args
            assert "session_id" in call_args

    def test_set_service_context(self, sentry_integration):
        """Test setting service context."""
        with patch(
            "brain_researcher.services.telemetry.sentry_integration.configure_scope"
        ) as mock_scope:
            scope_instance = MagicMock()
            mock_scope.return_value.__enter__.return_value = scope_instance

            sentry_integration.set_service_context(ServiceType.BR_KG)

            scope_instance.set_tag.assert_called_with("service", ServiceType.BR_KG)
            scope_instance.set_context.assert_called()

    def test_capture_exception(self, sentry_integration, mock_sentry_sdk):
        """Test capturing exceptions."""
        exception = ValueError("Test error")
        tags = {"component": "test"}
        extra = {"debug_info": "test_data"}

        with patch(
            "brain_researcher.services.telemetry.sentry_integration.configure_scope"
        ) as mock_scope:
            scope_instance = MagicMock()
            mock_scope.return_value.__enter__.return_value = scope_instance

            event_id = sentry_integration.capture_exception(
                exception=exception, tags=tags, extra=extra
            )

            assert event_id == "mock_event_id"
            scope_instance.set_tag.assert_called_with("component", "test")
            mock_sentry_sdk.capture_exception.assert_called_with(exception)

    def test_capture_message(self, sentry_integration, mock_sentry_sdk):
        """Test capturing messages."""
        message = "Test message with email@example.com"

        with patch(
            "brain_researcher.services.telemetry.sentry_integration.configure_scope"
        ) as mock_scope:
            scope_instance = MagicMock()
            mock_scope.return_value.__enter__.return_value = scope_instance

            message_id = sentry_integration.capture_message(message)

            assert message_id == "mock_message_id"
            # Check PII was filtered
            call_args = mock_sentry_sdk.capture_message.call_args[0][0]
            assert "email@example.com" not in call_args
            assert "[EMAIL_FILTERED]" in call_args

    def test_add_breadcrumb(self, sentry_integration, mock_sentry_sdk):
        """Test adding breadcrumbs."""
        sentry_integration.add_breadcrumb(
            message="User clicked button",
            category="ui",
            level="info",
            data={"button": "submit", "password": "secret"},
        )

        mock_sentry_sdk.add_breadcrumb.assert_called_once()
        call_kwargs = mock_sentry_sdk.add_breadcrumb.call_args.kwargs
        assert call_kwargs["category"] == "ui"
        assert call_kwargs["level"] == "info"
        # Check PII was filtered
        assert call_kwargs["data"]["password"] == "[FILTERED]"

    def test_start_transaction(self, sentry_integration, mock_sentry_sdk):
        """Test starting performance transaction."""
        sentry_integration.start_transaction("test_operation", "function")

        mock_sentry_sdk.start_transaction.assert_called_with(
            name="test_operation", op="function"
        )

    def test_get_stats(self, sentry_integration):
        """Test getting integration statistics."""
        stats = sentry_integration.get_stats()

        assert stats["initialized"]
        assert stats["dsn_configured"]
        assert stats["environment"] == "test"
        assert stats["sample_rate"] == 1.0
        assert stats["pii_filtering_enabled"]
        assert stats["tracing_enabled"]


class TestGlobalFunctions:
    """Test global helper functions."""

    def test_initialize_sentry(self, sentry_config):
        """Test global Sentry initialization."""
        with patch(
            "brain_researcher.services.telemetry.sentry_integration.SentryIntegration"
        ) as mock_class:
            initialize_sentry(sentry_config)

            mock_class.assert_called_with(sentry_config)
            assert get_sentry() is not None

    def test_capture_exception_with_context(self, sentry_config):
        """Test capturing exception with full context."""
        initialize_sentry(sentry_config)

        with patch.object(get_sentry(), "set_service_context") as mock_set_service:
            with patch.object(get_sentry(), "set_user_context") as mock_set_user:
                with patch.object(get_sentry(), "capture_exception") as mock_capture:
                    mock_capture.return_value = "test_event_id"

                    event_id = capture_exception_with_context(
                        exception=ValueError("test"),
                        service=ServiceType.AGENT,
                        user_id="user123",
                        session_id="session456",
                    )

                    mock_set_service.assert_called_with(ServiceType.AGENT)
                    mock_set_user.assert_called_with("user123", "session456")
                    mock_capture.assert_called_once()
                    assert event_id == "test_event_id"

    def test_capture_message_with_context(self, sentry_config):
        """Test capturing message with full context."""
        initialize_sentry(sentry_config)

        with patch.object(get_sentry(), "set_service_context") as mock_set_service:
            with patch.object(get_sentry(), "capture_message") as mock_capture:
                mock_capture.return_value = "test_message_id"

                message_id = capture_message_with_context(
                    message="Test message", service=ServiceType.WEB_UI, level="warning"
                )

                mock_set_service.assert_called_with(ServiceType.WEB_UI)
                mock_capture.assert_called_once()
                assert message_id == "test_message_id"


class TestDecorator:
    """Test error tracking decorator."""

    def test_track_errors_decorator_sync_function(self, sentry_config):
        """Test track_errors decorator on synchronous function."""
        initialize_sentry(sentry_config)

        @track_errors(service=ServiceType.ORCHESTRATOR)
        def test_function(x, y):
            if x == 0:
                raise ValueError("Division by zero")
            return y / x

        with patch.object(get_sentry(), "capture_exception") as mock_capture:
            # Normal execution
            result = test_function(2, 4)
            assert result == 2.0
            mock_capture.assert_not_called()

            # Error execution
            with pytest.raises(ValueError):
                test_function(0, 4)

            mock_capture.assert_called_once()
            call_args = mock_capture.call_args
            assert isinstance(call_args.kwargs["exception"], ValueError)
            assert call_args.kwargs["tags"]["function"] == "test_function"

    @pytest.mark.asyncio
    async def test_track_errors_decorator_async_function(self, sentry_config):
        """Test track_errors decorator on asynchronous function."""
        initialize_sentry(sentry_config)

        @track_errors(service=ServiceType.API_GATEWAY, capture_args=True)
        async def async_test_function(x, y):
            if x == 0:
                raise ValueError("Async division by zero")
            return y / x

        with patch.object(get_sentry(), "capture_exception") as mock_capture:
            # Normal execution
            result = await async_test_function(2, 4)
            assert result == 2.0
            mock_capture.assert_not_called()

            # Error execution
            with pytest.raises(ValueError):
                await async_test_function(0, 4)

            mock_capture.assert_called_once()
            call_args = mock_capture.call_args
            assert isinstance(call_args.kwargs["exception"], ValueError)
            assert "function_args" in call_args.kwargs["extra"]


class TestSentryContext:
    """Test SentryContext context manager."""

    def test_context_manager_normal_execution(self, sentry_config):
        """Test context manager with normal execution."""
        initialize_sentry(sentry_config)

        with patch.object(get_sentry(), "set_service_context") as mock_set_service:
            with patch.object(get_sentry(), "capture_exception") as mock_capture:
                with SentryContext(service=ServiceType.BR_KG):
                    # Normal execution
                    pass

                mock_set_service.assert_called_with(ServiceType.BR_KG)
                mock_capture.assert_not_called()

    def test_context_manager_with_exception(self, sentry_config):
        """Test context manager with exception."""
        initialize_sentry(sentry_config)

        with patch.object(get_sentry(), "capture_exception") as mock_capture:
            with pytest.raises(ValueError):
                with SentryContext(service=ServiceType.AGENT, tags={"test": "true"}):
                    raise ValueError("Test error in context")

            mock_capture.assert_called_once()
            call_args = mock_capture.call_args
            assert call_args.kwargs["tags"] == {"test": "true"}


class TestConfigFromEnvironment:
    """Test creating configuration from environment variables."""

    def test_create_config_from_env(self):
        """Test creating Sentry config from environment."""
        env_vars = {
            "SENTRY_DSN": "https://test@sentry.io/999",
            "ENVIRONMENT": "production",
            "RELEASE_VERSION": "v2.0.0",
            "SENTRY_SAMPLE_RATE": "0.8",
            "SENTRY_TRACES_SAMPLE_RATE": "0.2",
            "SENTRY_DEBUG": "true",
            "SENTRY_PII_FILTERING": "false",
            "SENTRY_TRACING": "false",
        }

        with patch.dict(os.environ, env_vars, clear=True):
            config = create_sentry_config_from_env()

            assert config.dsn == "https://test@sentry.io/999"
            assert config.environment == "production"
            assert config.release == "v2.0.0"
            assert config.sample_rate == 0.8
            assert config.traces_sample_rate == 0.2
            assert config.debug
            assert not config.enable_pii_filtering
            assert not config.enable_tracing

    def test_create_config_from_env_defaults(self):
        """Test creating Sentry config with default values."""
        with patch.dict(os.environ, {}, clear=True):
            config = create_sentry_config_from_env()

            assert config.dsn is None
            assert config.environment == "development"
            assert config.release is None
            assert config.sample_rate == 1.0
            assert config.traces_sample_rate == 0.1
            assert not config.debug
            assert config.enable_pii_filtering
            assert config.enable_tracing


@pytest.mark.integration
class TestSentryIntegrationE2E:
    """End-to-end integration tests."""

    def test_full_error_tracking_flow(self, sentry_config):
        """Test complete error tracking flow."""
        # Initialize Sentry
        sentry = initialize_sentry(sentry_config)

        # Set service context
        sentry.set_service_context(ServiceType.ORCHESTRATOR)

        # Set user context
        sentry.set_user_context("user_123", "session_456")

        # Add breadcrumb
        sentry.add_breadcrumb(
            message="Starting operation", category="operation", level="info"
        )

        # Simulate error with PII
        error_data = {
            "operation": "data_processing",
            "email": "user@example.com",
            "api_key": "sk_live_1234567890abcdef",
            "safe_info": "public_data",
        }

        with patch(
            "brain_researcher.services.telemetry.sentry_integration.sentry_sdk.capture_exception"
        ) as mock_capture:
            mock_capture.return_value = "final_event_id"

            try:
                # Simulate error
                raise RuntimeError(f"Processing failed for {error_data}")
            except RuntimeError as e:
                event_id = sentry.capture_exception(
                    exception=e, tags={"module": "processing"}, extra=error_data
                )

            assert event_id == "final_event_id"
            mock_capture.assert_called_once()

        # Verify stats
        stats = sentry.get_stats()
        assert stats["initialized"]
        assert stats["pii_filtering_enabled"]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
