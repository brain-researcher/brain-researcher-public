"""
Sentry Integration for Error Tracking (TELEMETRY-002)

This module implements comprehensive Sentry SDK integration with proper
error filtering, PII scrubbing, and context enrichment.
"""

import logging
import os
import re
import traceback
from datetime import datetime
from typing import Dict, List, Optional, Any, Union
from contextvars import ContextVar
from dataclasses import dataclass, asdict

try:
    import sentry_sdk
    from sentry_sdk.integrations.asyncio import AsyncioIntegration
    from sentry_sdk.integrations.logging import LoggingIntegration
    from sentry_sdk.integrations.redis import RedisIntegration
    from sentry_sdk.integrations.sqlalchemy import SqlalchemyIntegration
    from sentry_sdk.integrations.httpx import HttpxIntegration
    from sentry_sdk import configure_scope, capture_exception, capture_message, set_user, set_context
    SENTRY_AVAILABLE = True
except ImportError:
    SENTRY_AVAILABLE = False
    # Mock Sentry SDK for development
    class MockSentrySDK:
        def init(self, *args, **kwargs): pass
        def configure_scope(self, *args, **kwargs): return MockScope()
        def capture_exception(self, *args, **kwargs): pass
        def capture_message(self, *args, **kwargs): pass
        def set_user(self, *args, **kwargs): pass
        def set_context(self, *args, **kwargs): pass

    class MockScope:
        def set_tag(self, *args, **kwargs): pass
        def set_context(self, *args, **kwargs): pass
        def set_user(self, *args, **kwargs): pass

    sentry_sdk = MockSentrySDK()

from .models import ServiceType, TelemetryConfiguration


logger = logging.getLogger(__name__)

# Context variables for request tracking
current_user_context: ContextVar[Optional[Dict]] = ContextVar('current_user_context', default=None)
current_service_context: ContextVar[Optional[ServiceType]] = ContextVar('current_service_context', default=None)


@dataclass
class SentryConfig:
    """Sentry configuration settings."""
    dsn: Optional[str] = None
    environment: str = "development"
    release: Optional[str] = None
    sample_rate: float = 1.0
    traces_sample_rate: float = 0.1
    profiles_sample_rate: float = 0.1
    max_breadcrumbs: int = 100
    attach_stacktrace: bool = True
    send_default_pii: bool = False
    enable_tracing: bool = True
    debug: bool = False

    # Custom filtering settings
    enable_pii_filtering: bool = True
    filter_sensitive_data: bool = True
    ignore_logger_names: List[str] = None
    ignore_exceptions: List[str] = None

    def __post_init__(self):
        if self.ignore_logger_names is None:
            self.ignore_logger_names = [
                'urllib3.connectionpool',
                'httpx',
                'asyncio'
            ]
        if self.ignore_exceptions is None:
            self.ignore_exceptions = [
                'KeyboardInterrupt',
                'SystemExit',
                'CancelledError'
            ]


class PIIFilter:
    """Filters personally identifiable information from Sentry data."""

    def __init__(self):
        # Patterns for detecting PII
        self.pii_patterns = {
            'email': re.compile(r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b'),
            'ssn': re.compile(r'\b\d{3}-?\d{2}-?\d{4}\b'),
            'credit_card': re.compile(r'\b(?:\d{4}[-\s]?){3}\d{4}\b'),
            'phone': re.compile(
                r'(?<!\d)(?:\+?1[-.\s]?)?(?:\(?[0-9]{3}\)?[-.\s]?[0-9]{3}[-.\s]?[0-9]{4}|[0-9]{3}[-.\s]?[0-9]{4})(?!\d)'
            ),
            'ip_address': re.compile(r'\b(?:[0-9]{1,3}\.){3}[0-9]{1,3}\b'),
            'jwt_token': re.compile(r'\beyJ[A-Za-z0-9-_]+\.[A-Za-z0-9-_]+\.[A-Za-z0-9-_]*\b'),
            'api_key': re.compile(
                r'\b(?:sk_(?:test|live)_[A-Za-z0-9]{16,}|[A-Za-z0-9_]{32,})\b'
            ),
        }

        # Sensitive field names
        self.sensitive_fields = {
            'password', 'passwd', 'pwd', 'pass', 'secret', 'token', 'key', 'api_key',
            'access_token', 'refresh_token', 'auth_token', 'session_id', 'csrf_token',
            'email', 'phone', 'ssn', 'social_security', 'credit_card', 'card_number',
            'real_name', 'full_name', 'address', 'home_address', 'billing_address',
            'user_id', 'account_id', 'customer_id'
        }

    def filter_dict(self, data: Dict[str, Any], max_depth: int = 10) -> Dict[str, Any]:
        """Recursively filter PII from dictionary."""
        if max_depth <= 0 or not isinstance(data, dict):
            return data

        filtered = {}
        for key, value in data.items():
            key_lower = key.lower()

            # Check if field name suggests sensitive data
            if any(sensitive in key_lower for sensitive in self.sensitive_fields):
                filtered[key] = "[FILTERED]"
            elif isinstance(value, dict):
                filtered[key] = self.filter_dict(value, max_depth - 1)
            elif isinstance(value, list):
                filtered[key] = self.filter_list(value, max_depth - 1)
            elif isinstance(value, str):
                filtered[key] = self.filter_string(value)
            else:
                filtered[key] = value

        return filtered

    def filter_list(self, data: List[Any], max_depth: int = 10) -> List[Any]:
        """Filter PII from list items."""
        if max_depth <= 0:
            return data

        filtered = []
        for item in data:
            if isinstance(item, dict):
                filtered.append(self.filter_dict(item, max_depth - 1))
            elif isinstance(item, list):
                filtered.append(self.filter_list(item, max_depth - 1))
            elif isinstance(item, str):
                filtered.append(self.filter_string(item))
            else:
                filtered.append(item)

        return filtered

    def filter_string(self, text: str) -> str:
        """Filter PII patterns from strings."""
        if not isinstance(text, str) or len(text) > 10000:  # Skip very long strings
            return text

        filtered_text = text

        for pattern_name, pattern in self.pii_patterns.items():
            if pattern.search(filtered_text):
                if pattern_name == 'email':
                    filtered_text = pattern.sub('[EMAIL_FILTERED]', filtered_text)
                elif pattern_name == 'phone':
                    filtered_text = pattern.sub('[PHONE_FILTERED]', filtered_text)
                elif pattern_name == 'ssn':
                    filtered_text = pattern.sub('[SSN_FILTERED]', filtered_text)
                elif pattern_name == 'credit_card':
                    filtered_text = pattern.sub('[CARD_FILTERED]', filtered_text)
                elif pattern_name == 'ip_address':
                    filtered_text = pattern.sub('[IP_FILTERED]', filtered_text)
                elif pattern_name == 'api_key':
                    filtered_text = pattern.sub('[API_KEY_FILTERED]', filtered_text)
                elif pattern_name == 'jwt_token':
                    filtered_text = pattern.sub('[JWT_FILTERED]', filtered_text)

        return filtered_text


class ContextEnricher:
    """Enriches Sentry events with additional context."""

    @staticmethod
    def enrich_event(event: Dict[str, Any], hint: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Enrich Sentry event with additional context."""
        try:
            # Add service context
            service_context = current_service_context.get()
            if service_context:
                event.setdefault('tags', {})['service'] = service_context
                event.setdefault('contexts', {})['service'] = {
                    'name': service_context,
                    'type': 'service'
                }

            # Add user context (anonymized)
            user_context = current_user_context.get()
            if user_context:
                event.setdefault('user', {}).update({
                    'id': user_context.get('user_hash'),  # Already hashed
                    'session_id': user_context.get('session_hash')  # Already hashed
                })

            # Add Brain Researcher specific context
            event.setdefault('contexts', {})['brain_researcher'] = {
                'component': 'telemetry',
                'version': '1.0.0',
                'deployment': os.environ.get('DEPLOYMENT_ENV', 'development')
            }

            # Add request context if available
            if 'request' in hint:
                request = hint['request']
                if hasattr(request, 'url'):
                    event.setdefault('request', {})['url'] = str(request.url)
                if hasattr(request, 'method'):
                    event.setdefault('request', {})['method'] = request.method

            # Add timestamp
            event['timestamp'] = datetime.utcnow().isoformat()

            return event

        except Exception as e:
            logger.error(f"Error enriching Sentry event: {e}")
            return event


class SentryIntegration:
    """Main Sentry integration class."""

    def __init__(self, config: SentryConfig):
        self.config = config
        self.pii_filter = PIIFilter()
        self.is_initialized = False

        if not SENTRY_AVAILABLE:
            logger.warning("Sentry SDK not available, using mock implementation")

        self._initialize_sentry()

    def _initialize_sentry(self):
        """Initialize Sentry SDK with configuration."""
        if not self.config.dsn:
            logger.info("Sentry DSN not provided, skipping initialization")
            return

        try:
            # Prepare integrations
            try:
                asyncio_integration = AsyncioIntegration(auto_enabling=True)
            except TypeError:
                asyncio_integration = AsyncioIntegration()

            try:
                httpx_integration = HttpxIntegration(transaction_style="endpoint")
            except TypeError:
                httpx_integration = HttpxIntegration()

            integrations = [
                LoggingIntegration(
                    level=logging.INFO,
                    event_level=logging.ERROR
                ),
                asyncio_integration,
                RedisIntegration(),
                httpx_integration
            ]

            # Add SQLAlchemy integration if available
            try:
                integrations.append(SqlalchemyIntegration())
            except:
                pass

            # Initialize Sentry
            sentry_sdk.init(
                dsn=self.config.dsn,
                environment=self.config.environment,
                release=self.config.release,
                sample_rate=self.config.sample_rate,
                traces_sample_rate=self.config.traces_sample_rate,
                profiles_sample_rate=self.config.profiles_sample_rate,
                max_breadcrumbs=self.config.max_breadcrumbs,
                attach_stacktrace=self.config.attach_stacktrace,
                send_default_pii=self.config.send_default_pii,
                debug=self.config.debug,
                integrations=integrations,
                before_send=self._before_send_filter,
                before_send_transaction=self._before_send_transaction
            )

            self.is_initialized = True
            logger.info(f"Sentry initialized for environment: {self.config.environment}")

        except Exception as e:
            logger.error(f"Failed to initialize Sentry: {e}")

    def _before_send_filter(self, event: Dict[str, Any], hint: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Filter events before sending to Sentry."""
        try:
            # Skip if not initialized
            if not self.is_initialized:
                return None

            # Filter ignored exceptions
            if 'exc_info' in hint and hint['exc_info']:
                exc_type = hint['exc_info'][1].__class__.__name__
                if exc_type in self.config.ignore_exceptions:
                    return None

            # Filter ignored loggers
            if event.get('logger') in self.config.ignore_logger_names:
                return None

            # Apply PII filtering
            if self.config.enable_pii_filtering:
                event = self._filter_event_pii(event)

            # Enrich with context
            event = ContextEnricher.enrich_event(event, hint)

            # Limit event size
            if self._event_too_large(event):
                event = self._truncate_event(event)

            return event

        except Exception as e:
            logger.error(f"Error in before_send filter: {e}")
            return event

    def _before_send_transaction(self, event: Dict[str, Any], hint: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Filter transaction events before sending to Sentry."""
        try:
            # Skip if not initialized
            if not self.is_initialized:
                return None

            # Add service context to transactions
            service_context = current_service_context.get()
            if service_context:
                event.setdefault('contexts', {})['service'] = {
                    'name': service_context,
                    'type': 'service'
                }

            return event

        except Exception as e:
            logger.error(f"Error in before_send_transaction filter: {e}")
            return event

    def _filter_event_pii(self, event: Dict[str, Any]) -> Dict[str, Any]:
        """Filter PII from Sentry event."""
        try:
            # Filter exception contexts
            if 'exception' in event:
                for exc_value in event['exception'].get('values', []):
                    if 'stacktrace' in exc_value:
                        for frame in exc_value['stacktrace'].get('frames', []):
                            if 'vars' in frame:
                                frame['vars'] = self.pii_filter.filter_dict(frame['vars'])

            # Filter request data
            if 'request' in event:
                if 'data' in event['request']:
                    if isinstance(event['request']['data'], dict):
                        event['request']['data'] = self.pii_filter.filter_dict(event['request']['data'])
                    elif isinstance(event['request']['data'], str):
                        event['request']['data'] = self.pii_filter.filter_string(event['request']['data'])

                # Filter headers
                if 'headers' in event['request']:
                    filtered_headers = {}
                    for key, value in event['request']['headers'].items():
                        if key.lower() in ['authorization', 'cookie', 'x-api-key']:
                            filtered_headers[key] = '[FILTERED]'
                        else:
                            filtered_headers[key] = value
                    event['request']['headers'] = filtered_headers

            # Filter extra data
            if 'extra' in event:
                event['extra'] = self.pii_filter.filter_dict(event['extra'])

            # Filter contexts
            if 'contexts' in event:
                event['contexts'] = self.pii_filter.filter_dict(event['contexts'])

            return event

        except Exception as e:
            logger.error(f"Error filtering PII from event: {e}")
            return event

    def _event_too_large(self, event: Dict[str, Any]) -> bool:
        """Check if event is too large."""
        try:
            import json
            event_size = len(json.dumps(event, default=str))
            return event_size > 200000  # 200KB limit
        except:
            return False

    def _truncate_event(self, event: Dict[str, Any]) -> Dict[str, Any]:
        """Truncate large events."""
        try:
            # Remove or truncate large fields
            if 'exception' in event:
                for exc_value in event['exception'].get('values', []):
                    if 'stacktrace' in exc_value:
                        frames = exc_value['stacktrace'].get('frames', [])
                        if len(frames) > 50:
                            exc_value['stacktrace']['frames'] = frames[:25] + frames[-25:]

            # Truncate extra data
            if 'extra' in event:
                for key, value in event['extra'].items():
                    if isinstance(value, str) and len(value) > 10000:
                        event['extra'][key] = value[:10000] + "... [TRUNCATED]"

            return event
        except Exception as e:
            logger.error(f"Error truncating event: {e}")
            return event

    def set_user_context(self, user_id: Optional[str], session_id: Optional[str] = None, **kwargs):
        """Set user context for error tracking."""
        try:
            # Hash user ID for privacy
            if user_id:
                import hashlib
                user_hash = hashlib.sha256(f"br_user_{user_id}".encode()).hexdigest()[:16]
            else:
                user_hash = None

            # Hash session ID
            if session_id:
                session_hash = hashlib.sha256(f"br_session_{session_id}".encode()).hexdigest()[:16]
            else:
                session_hash = None

            # Set context variable
            current_user_context.set({
                'user_hash': user_hash,
                'session_hash': session_hash,
                **kwargs
            })

            # Set Sentry user context
            if SENTRY_AVAILABLE and self.is_initialized:
                with configure_scope() as scope:
                    scope.set_user({
                        'id': user_hash,
                        'session_id': session_hash
                    })

        except Exception as e:
            logger.error(f"Error setting user context: {e}")

    def set_service_context(self, service: ServiceType):
        """Set service context for error tracking."""
        try:
            current_service_context.set(service)

            if SENTRY_AVAILABLE and self.is_initialized:
                with configure_scope() as scope:
                    scope.set_tag('service', service)
                    scope.set_context('service', {
                        'name': service,
                        'type': 'brain_researcher_service'
                    })
        except Exception as e:
            logger.error(f"Error setting service context: {e}")

    def capture_exception(self,
                         exception: Exception = None,
                         level: str = "error",
                         tags: Optional[Dict[str, str]] = None,
                         extra: Optional[Dict[str, Any]] = None,
                         user: Optional[Dict[str, str]] = None,
                         fingerprint: Optional[List[str]] = None) -> Optional[str]:
        """Capture exception with context enrichment."""
        try:
            if not SENTRY_AVAILABLE or not self.is_initialized:
                return None

            with configure_scope() as scope:
                if tags:
                    for key, value in tags.items():
                        scope.set_tag(key, str(value))

                if extra:
                    filtered_extra = self.pii_filter.filter_dict(extra)
                    scope.set_context('extra_data', filtered_extra)

                if user:
                    scope.set_user(user)

                if fingerprint:
                    scope.set_fingerprint(fingerprint)

                scope.set_level(level)

                return sentry_sdk.capture_exception(exception)

        except Exception as e:
            logger.error(f"Error capturing exception in Sentry: {e}")
            return None

    def capture_message(self,
                       message: str,
                       level: str = "info",
                       tags: Optional[Dict[str, str]] = None,
                       extra: Optional[Dict[str, Any]] = None) -> Optional[str]:
        """Capture message with context."""
        try:
            if not SENTRY_AVAILABLE or not self.is_initialized:
                return None

            with configure_scope() as scope:
                if tags:
                    for key, value in tags.items():
                        scope.set_tag(key, str(value))

                if extra:
                    filtered_extra = self.pii_filter.filter_dict(extra)
                    scope.set_context('extra_data', filtered_extra)

                scope.set_level(level)

                # Filter message for PII
                filtered_message = self.pii_filter.filter_string(message)

                return sentry_sdk.capture_message(filtered_message)

        except Exception as e:
            logger.error(f"Error capturing message in Sentry: {e}")
            return None

    def add_breadcrumb(self,
                      message: str,
                      category: str = "custom",
                      level: str = "info",
                      data: Optional[Dict[str, Any]] = None):
        """Add breadcrumb for debugging."""
        try:
            if not SENTRY_AVAILABLE or not self.is_initialized:
                return

            filtered_data = self.pii_filter.filter_dict(data) if data else None
            filtered_message = self.pii_filter.filter_string(message)

            sentry_sdk.add_breadcrumb(
                message=filtered_message,
                category=category,
                level=level,
                data=filtered_data
            )

        except Exception as e:
            logger.error(f"Error adding breadcrumb: {e}")

    def start_transaction(self, name: str, op: str = "function") -> Any:
        """Start a performance transaction."""
        try:
            if SENTRY_AVAILABLE and self.is_initialized and self.config.enable_tracing:
                return sentry_sdk.start_transaction(name=name, op=op)
            return None
        except Exception as e:
            logger.error(f"Error starting transaction: {e}")
            return None

    def get_stats(self) -> Dict[str, Any]:
        """Get Sentry integration statistics."""
        return {
            'initialized': self.is_initialized,
            'dsn_configured': bool(self.config.dsn),
            'environment': self.config.environment,
            'sample_rate': self.config.sample_rate,
            'pii_filtering_enabled': self.config.enable_pii_filtering,
            'tracing_enabled': self.config.enable_tracing,
            'sentry_available': SENTRY_AVAILABLE
        }


# Global Sentry instance
_sentry_instance: Optional[SentryIntegration] = None


def initialize_sentry(config: SentryConfig) -> SentryIntegration:
    """Initialize global Sentry instance."""
    global _sentry_instance
    _sentry_instance = SentryIntegration(config)
    return _sentry_instance


def get_sentry() -> Optional[SentryIntegration]:
    """Get global Sentry instance."""
    return _sentry_instance


# Convenience functions
def capture_exception_with_context(exception: Exception = None,
                                  service: Optional[ServiceType] = None,
                                  user_id: Optional[str] = None,
                                  session_id: Optional[str] = None,
                                  tags: Optional[Dict[str, str]] = None,
                                  extra: Optional[Dict[str, Any]] = None) -> Optional[str]:
    """Capture exception with Brain Researcher context."""
    sentry = get_sentry()
    if not sentry:
        return None

    if service:
        sentry.set_service_context(service)

    if user_id or session_id:
        sentry.set_user_context(user_id, session_id)

    return sentry.capture_exception(exception, tags=tags, extra=extra)


def capture_message_with_context(message: str,
                                level: str = "info",
                                service: Optional[ServiceType] = None,
                                tags: Optional[Dict[str, str]] = None,
                                extra: Optional[Dict[str, Any]] = None) -> Optional[str]:
    """Capture message with Brain Researcher context."""
    sentry = get_sentry()
    if not sentry:
        return None

    if service:
        sentry.set_service_context(service)

    return sentry.capture_message(message, level=level, tags=tags, extra=extra)


# Decorator for automatic error tracking
def track_errors(service: ServiceType,
                capture_args: bool = False,
                capture_result: bool = False):
    """Decorator to automatically track function errors."""
    def decorator(func):
        def wrapper(*args, **kwargs):
            sentry = get_sentry()
            if sentry:
                sentry.set_service_context(service)

            try:
                result = func(*args, **kwargs)
                return result
            except Exception as e:
                extra_data = {}
                if capture_args:
                    extra_data['function_args'] = {
                        'args_count': len(args),
                        'kwargs_keys': list(kwargs.keys())
                    }

                if sentry:
                    sentry.capture_exception(
                        exception=e,
                        tags={'function': func.__name__},
                        extra=extra_data
                    )

                raise

        # Handle async functions
        import asyncio
        if asyncio.iscoroutinefunction(func):
            async def async_wrapper(*args, **kwargs):
                sentry = get_sentry()
                if sentry:
                    sentry.set_service_context(service)

                try:
                    result = await func(*args, **kwargs)
                    return result
                except Exception as e:
                    extra_data = {}
                    if capture_args:
                        extra_data['function_args'] = {
                            'args_count': len(args),
                            'kwargs_keys': list(kwargs.keys())
                        }

                    if sentry:
                        sentry.capture_exception(
                            exception=e,
                            tags={'function': func.__name__},
                            extra=extra_data
                        )

                    raise
            return async_wrapper
        else:
            return wrapper

    return decorator


# Context managers
class SentryContext:
    """Context manager for Sentry operations."""

    def __init__(self,
                 service: Optional[ServiceType] = None,
                 user_id: Optional[str] = None,
                 session_id: Optional[str] = None,
                 tags: Optional[Dict[str, str]] = None):
        self.service = service
        self.user_id = user_id
        self.session_id = session_id
        self.tags = tags or {}

    def __enter__(self):
        sentry = get_sentry()
        if sentry:
            if self.service:
                sentry.set_service_context(self.service)
            if self.user_id or self.session_id:
                sentry.set_user_context(self.user_id, self.session_id)
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if exc_type and exc_val:
            sentry = get_sentry()
            if sentry:
                sentry.capture_exception(
                    exception=exc_val,
                    tags=self.tags
                )


def create_sentry_config_from_env() -> SentryConfig:
    """Create Sentry configuration from environment variables."""
    return SentryConfig(
        dsn=os.environ.get('SENTRY_DSN'),
        environment=os.environ.get('ENVIRONMENT', 'development'),
        release=os.environ.get('RELEASE_VERSION'),
        sample_rate=float(os.environ.get('SENTRY_SAMPLE_RATE', '1.0')),
        traces_sample_rate=float(os.environ.get('SENTRY_TRACES_SAMPLE_RATE', '0.1')),
        debug=os.environ.get('SENTRY_DEBUG', 'false').lower() == 'true',
        enable_pii_filtering=os.environ.get('SENTRY_PII_FILTERING', 'true').lower() == 'true',
        enable_tracing=os.environ.get('SENTRY_TRACING', 'true').lower() == 'true'
    )
