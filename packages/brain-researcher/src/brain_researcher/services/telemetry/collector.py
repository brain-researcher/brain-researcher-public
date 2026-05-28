"""
TelemetryCollector - Real-time event collection with privacy controls.
"""

import asyncio
import hashlib
import json
import time
import uuid
from collections import defaultdict, deque
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any, Callable, Set
from dataclasses import dataclass, field
import threading
import logging

from .models import TelemetryEvent, EventType, ServiceType, PrivacyLevel, TelemetryConfiguration


logger = logging.getLogger(__name__)


@dataclass
class CollectorStats:
    """Statistics for the telemetry collector."""
    events_collected: int = 0
    events_processed: int = 0
    events_dropped: int = 0
    events_anonymized: int = 0
    last_flush_time: Optional[datetime] = None
    processing_errors: int = 0
    avg_processing_time_ms: float = 0.0


class EventBuffer:
    """Thread-safe circular buffer for events."""
    
    def __init__(self, max_size: int = 10000):
        self.max_size = max_size
        self._buffer = deque(maxlen=max_size)
        self._lock = threading.Lock()
        self._dropped_count = 0
    
    def append(self, event: TelemetryEvent) -> bool:
        """Add event to buffer. Returns True if added, False if dropped."""
        with self._lock:
            if len(self._buffer) >= self.max_size:
                self._dropped_count += 1
                return False
            self._buffer.append(event)
            return True
    
    def flush(self, count: Optional[int] = None) -> List[TelemetryEvent]:
        """Remove and return events from buffer."""
        with self._lock:
            if count is None:
                events = list(self._buffer)
                self._buffer.clear()
            else:
                events = []
                for _ in range(min(count, len(self._buffer))):
                    events.append(self._buffer.popleft())
            return events
    
    def size(self) -> int:
        """Get current buffer size."""
        with self._lock:
            return len(self._buffer)
    
    def dropped_count(self) -> int:
        """Get count of dropped events."""
        return self._dropped_count


class TelemetryCollector:
    """
    Production-ready telemetry collector with privacy controls and performance optimization.
    """
    
    def __init__(self, config: Optional[TelemetryConfiguration] = None):
        self.config = config or TelemetryConfiguration()
        self.stats = CollectorStats()
        
        # Event storage and processing
        self._event_buffer = EventBuffer(max_size=self.config.queue_max_size)
        self._processing_handlers: List[Callable[[List[TelemetryEvent]], None]] = []
        
        # Privacy and anonymization
        self._pii_patterns: Set[str] = {
            'email', 'phone', 'ssn', 'address', 'name', 'ip_address',
            'user_name', 'full_name', 'real_name', 'password', 'token',
            'user_agent', 'api_key', 'real_user_id'
        }
        self._user_hash_cache: Dict[str, str] = {}
        
        # Performance tracking
        self._rate_limiter = defaultdict(lambda: deque(maxlen=100))
        self._processing_times: deque = deque(maxlen=1000)
        
        # Background processing
        self._flush_task: Optional[asyncio.Task] = None
        self._processing_locks: Dict[int, asyncio.Lock] = {}
        self._shutdown_event = asyncio.Event()
        
        # Session tracking
        self._active_sessions: Dict[str, datetime] = {}
        self._session_events: Dict[str, List[str]] = defaultdict(list)
        
        logger.info(f"TelemetryCollector initialized with config: {self.config}")
    
    async def start(self):
        """Start background processing tasks."""
        if not self.config.collection_enabled:
            logger.info("Telemetry collection disabled by configuration")
            return
        
        self._flush_task = asyncio.create_task(self._background_flush())
        logger.info("TelemetryCollector background processing started")
    
    async def stop(self):
        """Stop background processing and flush remaining events."""
        logger.info("Stopping TelemetryCollector...")
        self._shutdown_event.set()
        
        if self._flush_task:
            try:
                await asyncio.wait_for(self._flush_task, timeout=5.0)
            except asyncio.TimeoutError:
                logger.warning("Flush task timeout during shutdown")
                self._flush_task.cancel()
        
        # Final flush
        await self._flush_events(force=True)
        logger.info("TelemetryCollector stopped")
    
    def collect(self, 
                event_type: EventType, 
                service: ServiceType,
                feature_name: Optional[str] = None,
                action: Optional[str] = None,
                user_id: Optional[str] = None,
                session_id: Optional[str] = None,
                context: Optional[Dict[str, Any]] = None,
                parameters: Optional[Dict[str, Any]] = None,
                metadata: Optional[Dict[str, Any]] = None,
                duration_ms: Optional[int] = None,
                success: bool = True,
                error_message: Optional[str] = None,
                privacy_level: PrivacyLevel = PrivacyLevel.AGGREGATE_ONLY,
                **kwargs) -> Optional[str]:
        """
        Collect a telemetry event with automatic privacy controls.
        
        Returns event ID if collected successfully, None if dropped or disabled.
        """
        if not self.config.collection_enabled:
            return None
        
        # Apply sampling
        if not self._should_sample():
            return None
        
        # Rate limiting
        if not self._check_rate_limit(service):
            self.stats.events_dropped += 1
            return None
        
        start_time = time.time()
        
        try:
            # Generate event ID and session tracking
            event_id = f"evt_{uuid.uuid4().hex[:12]}"
            session_id = session_id or self._get_or_create_session(user_id)

            # Prepare data dictionaries for validation
            context = context or {}
            parameters = parameters or {}
            metadata = metadata or {}

            # Capture fields that will be anonymized before validation
            ip_address = metadata.get("ip_address") if isinstance(metadata, dict) else None
            user_agent = metadata.get("user_agent") if isinstance(metadata, dict) else None
            ip_hash = None
            user_agent_hash = None
            if self.config.anonymization_enabled:
                if ip_address and self.config.ip_anonymization:
                    ip_hash = hashlib.sha256(ip_address.encode()).hexdigest()[:16]
                if user_agent:
                    user_agent_hash = hashlib.sha256(user_agent.encode()).hexdigest()[:16]

            # Sanitize PII before model validation to avoid hard failures
            if self.config.pii_detection_enabled:
                if isinstance(context, dict):
                    context = self._sanitize_dict(context)
                if isinstance(parameters, dict):
                    parameters = self._sanitize_dict(parameters)
                if isinstance(metadata, dict):
                    metadata = self._sanitize_dict(metadata)

            # Ensure direct PII keys are removed before model validation
            if isinstance(metadata, dict):
                metadata.pop("ip_address", None)
                metadata.pop("user_agent", None)

            # Create base event
            event = TelemetryEvent(
                id=event_id,
                event_type=event_type,
                service=service,
                feature_name=feature_name,
                action=action,
                session_id=session_id,
                context=context,
                parameters=parameters,
                metadata=metadata,
                duration_ms=duration_ms,
                success=success,
                error_message=error_message,
                privacy_level=privacy_level,
                ip_hash=ip_hash,
                user_agent_hash=user_agent_hash,
                **kwargs
            )
            
            # Apply privacy controls
            if self.config.anonymization_enabled:
                event = self._anonymize_event(event, user_id)
            
            # Validate and sanitize
            event = self._validate_and_sanitize(event)
            
            # Buffer the event
            if self._event_buffer.append(event):
                self.stats.events_collected += 1
                self._track_session_event(session_id, event_id)
                
                # Update processing time stats
                processing_time = (time.time() - start_time) * 1000
                self._processing_times.append(processing_time)
                self.stats.avg_processing_time_ms = sum(self._processing_times) / len(self._processing_times)
                
                logger.debug(f"Collected event {event_id}: {event_type} from {service}")
                return event_id
            else:
                self.stats.events_dropped += 1
                logger.warning(f"Event buffer full, dropped event: {event_id}")
                return None
                
        except Exception as e:
            self.stats.processing_errors += 1
            logger.error(f"Error collecting event: {e}", exc_info=True)
            return None
    
    def collect_tool_usage(self, 
                          tool_name: str,
                          action: str,
                          service: ServiceType = ServiceType.AGENT,
                          user_id: Optional[str] = None,
                          parameters: Optional[Dict[str, Any]] = None,
                          duration_ms: Optional[int] = None,
                          success: bool = True,
                          error_message: Optional[str] = None) -> Optional[str]:
        """Convenience method for tool usage events."""
        return self.collect(
            event_type=EventType.TOOL_INVOCATION,
            service=service,
            feature_name=tool_name,
            action=action,
            user_id=user_id,
            parameters=parameters,
            duration_ms=duration_ms,
            success=success,
            error_message=error_message,
            privacy_level=PrivacyLevel.AGGREGATE_ONLY
        )
    
    def collect_feature_usage(self,
                            feature_name: str,
                            action: str,
                            service: ServiceType,
                            user_id: Optional[str] = None,
                            context: Optional[Dict[str, Any]] = None,
                            success: bool = True) -> Optional[str]:
        """Convenience method for feature usage events."""
        return self.collect(
            event_type=EventType.FEATURE_ACCESS,
            service=service,
            feature_name=feature_name,
            action=action,
            user_id=user_id,
            context=context,
            success=success,
            privacy_level=PrivacyLevel.AGGREGATE_ONLY
        )
    
    def collect_page_view(self,
                         page_path: str,
                         service: ServiceType = ServiceType.WEB_UI,
                         user_id: Optional[str] = None,
                         referrer: Optional[str] = None,
                         user_agent: Optional[str] = None) -> Optional[str]:
        """Convenience method for page view events."""
        context = {"page_path": page_path}
        if referrer:
            context["referrer_hash"] = hashlib.sha256(referrer.encode()).hexdigest()[:16]
        
        metadata = {}
        if user_agent:
            metadata["user_agent_hash"] = hashlib.sha256(user_agent.encode()).hexdigest()[:16]
        
        return self.collect(
            event_type=EventType.PAGE_VIEW,
            service=service,
            feature_name="page_view",
            action="view",
            user_id=user_id,
            context=context,
            metadata=metadata,
            privacy_level=PrivacyLevel.AGGREGATE_ONLY
        )
    
    def add_processing_handler(self, handler: Callable[[List[TelemetryEvent]], None]):
        """Add a handler function to process batches of events."""
        self._processing_handlers.append(handler)
        logger.info(f"Added processing handler: {handler.__name__}")
    
    def get_stats(self) -> Dict[str, Any]:
        """Get collector statistics."""
        return {
            "events_collected": self.stats.events_collected,
            "events_processed": self.stats.events_processed,
            "events_dropped": self.stats.events_dropped,
            "events_anonymized": self.stats.events_anonymized,
            "buffer_size": self._event_buffer.size(),
            "buffer_dropped": self._event_buffer.dropped_count(),
            "processing_errors": self.stats.processing_errors,
            "avg_processing_time_ms": self.stats.avg_processing_time_ms,
            "last_flush_time": self.stats.last_flush_time.isoformat() if self.stats.last_flush_time else None,
            "active_sessions": len(self._active_sessions),
            "config": {
                "collection_enabled": self.config.collection_enabled,
                "sampling_rate": self.config.sampling_rate,
                "batch_size": self.config.batch_size,
                "anonymization_enabled": self.config.anonymization_enabled
            }
        }
    
    async def _background_flush(self):
        """Background task to flush events periodically."""
        while not self._shutdown_event.is_set():
            try:
                await asyncio.sleep(self.config.flush_interval_seconds)
                await self._flush_events()
                self._cleanup_sessions()
            except Exception as e:
                logger.error(f"Error in background flush: {e}", exc_info=True)
    
    def _flush_events(self, force: bool = False):
        """Flush buffered events to processing handlers."""
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            asyncio.run(self._flush_events_async(force=force))
            return None
        return self._flush_events_async(force=force)

    async def _flush_events_async(self, force: bool = False):
        """Async flush implementation."""
        async with self._get_processing_lock():
            buffer_size = self._event_buffer.size()

            if buffer_size == 0:
                return

            if not force and buffer_size < self.config.batch_size:
                return

            events = self._event_buffer.flush(self.config.batch_size if not force else None)

            if events:
                for handler in self._processing_handlers:
                    try:
                        if asyncio.iscoroutinefunction(handler):
                            await handler(events)
                        else:
                            handler(events)
                    except Exception as e:
                        logger.error(f"Error in processing handler {handler.__name__}: {e}", exc_info=True)

                self.stats.events_processed += len(events)
                self.stats.last_flush_time = datetime.utcnow()
                logger.debug(f"Processed {len(events)} events")

    def _get_processing_lock(self) -> asyncio.Lock:
        """Return a loop-local processing lock to avoid cross-loop deadlocks."""
        loop = asyncio.get_running_loop()
        key = id(loop)
        lock = self._processing_locks.get(key)
        if lock is None:
            lock = asyncio.Lock()
            self._processing_locks[key] = lock
        return lock
    
    def _should_sample(self) -> bool:
        """Apply sampling rate to determine if event should be collected."""
        if self.config.sampling_rate >= 1.0:
            return True
        
        import random
        return random.random() < self.config.sampling_rate
    
    def _check_rate_limit(self, service: ServiceType) -> bool:
        """Check if we're within rate limits for this service."""
        now = time.time()
        service_rates = self._rate_limiter[service]
        
        # Remove old timestamps (older than 1 second)
        while service_rates and service_rates[0] < now - 1:
            service_rates.popleft()
        
        # Check if we're under the limit
        if len(service_rates) >= self.config.max_events_per_second:
            return False
        
        service_rates.append(now)
        return True
    
    def _anonymize_event(self, event: TelemetryEvent, original_user_id: Optional[str]) -> TelemetryEvent:
        """Apply privacy controls to anonymize event data."""
        # Hash user ID if provided
        if original_user_id:
            if original_user_id not in self._user_hash_cache:
                self._user_hash_cache[original_user_id] = self._hash_user_id(original_user_id)
            event.user_id = self._user_hash_cache[original_user_id]
            event.anonymized = True
            self.stats.events_anonymized += 1
        
        # Remove or hash IP information if present
        if 'ip_address' in event.metadata:
            if self.config.ip_anonymization:
                event.ip_hash = hashlib.sha256(event.metadata['ip_address'].encode()).hexdigest()[:16]
            del event.metadata['ip_address']
        
        # Hash user agent if present
        if 'user_agent' in event.metadata:
            event.user_agent_hash = hashlib.sha256(event.metadata['user_agent'].encode()).hexdigest()[:16]
            del event.metadata['user_agent']
        
        return event
    
    def _hash_user_id(self, user_id: str) -> str:
        """Create a consistent hash for user ID."""
        # Use a salt for additional security
        salt = "brain_researcher_telemetry_salt_2024"
        return hashlib.sha256((user_id + salt).encode()).hexdigest()[:32]
    
    def _validate_and_sanitize(self, event: TelemetryEvent) -> TelemetryEvent:
        """Validate event data and remove any PII."""
        if not self.config.pii_detection_enabled:
            return event
        
        # Check for PII in context, parameters, and metadata
        for field_name, field_data in [
            ("context", event.context),
            ("parameters", event.parameters), 
            ("metadata", event.metadata)
        ]:
            if isinstance(field_data, dict):
                sanitized = self._sanitize_dict(field_data)
                setattr(event, field_name, sanitized)
        
        return event
    
    def _sanitize_dict(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Remove or hash potential PII from dictionary."""
        sanitized = {}
        
        for key, value in data.items():
            key_lower = key.lower()

            # Preserve already-sanitized fields
            if key_lower.endswith("_hash") or key_lower.endswith("_masked"):
                sanitized[key] = value
                continue
            
            # Check if key looks like PII
            if any(pii_pattern in key_lower for pii_pattern in self._pii_patterns):
                if isinstance(value, str) and len(value) > 3:
                    # Hash the value instead of removing it
                    sanitized[f"{key}_hash"] = hashlib.sha256(value.encode()).hexdigest()[:16]
                continue
            
            # Recursively sanitize nested dictionaries
            if isinstance(value, dict):
                sanitized[key] = self._sanitize_dict(value)
            elif isinstance(value, list):
                sanitized[key] = [
                    self._sanitize_dict(item) if isinstance(item, dict) else item
                    for item in value
                ]
            else:
                sanitized[key] = value
        
        return sanitized
    
    def _get_or_create_session(self, user_id: Optional[str]) -> str:
        """Get or create a session ID for tracking user journeys."""
        if not user_id:
            return f"anon_{uuid.uuid4().hex[:8]}"
        
        # Clean up old sessions first
        now = datetime.utcnow()
        expired_sessions = [
            session_id for session_id, last_seen in self._active_sessions.items()
            if now - last_seen > timedelta(hours=1)
        ]
        for session_id in expired_sessions:
            del self._active_sessions[session_id]
            if session_id in self._session_events:
                del self._session_events[session_id]
        
        # Find existing session for user
        user_hash = self._hash_user_id(user_id) if user_id else None
        for session_id, last_seen in self._active_sessions.items():
            if session_id.startswith(f"user_{user_hash}"):
                self._active_sessions[session_id] = now
                return session_id
        
        # Create new session
        session_id = f"user_{user_hash}_{uuid.uuid4().hex[:8]}"
        self._active_sessions[session_id] = now
        return session_id
    
    def _track_session_event(self, session_id: str, event_id: str):
        """Track events within a session for journey analysis."""
        self._session_events[session_id].append(event_id)
        
        # Keep only recent events per session
        if len(self._session_events[session_id]) > 100:
            self._session_events[session_id] = self._session_events[session_id][-50:]
    
    def _cleanup_sessions(self):
        """Clean up expired sessions and associated data."""
        now = datetime.utcnow()
        expired_sessions = [
            session_id for session_id, last_seen in self._active_sessions.items()
            if now - last_seen > timedelta(hours=2)
        ]
        
        for session_id in expired_sessions:
            del self._active_sessions[session_id]
            if session_id in self._session_events:
                del self._session_events[session_id]
        
        if expired_sessions:
            logger.debug(f"Cleaned up {len(expired_sessions)} expired sessions")
