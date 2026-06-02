"""
TelemetryAPI - RESTful endpoints for telemetry data access and management.
"""

import asyncio
import inspect
import json
import logging
import os
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Union

from fastapi import BackgroundTasks, Depends, FastAPI, HTTPException, Query, Request
from pydantic import BaseModel, Field, field_validator

from .aggregator import AggregationConfig, AggregationWindow, UsageMetricsAggregator
from .collector import TelemetryCollector
from .models import (
    EventType,
    FeatureUsage,
    MetricType,
    PrivacyLevel,
    ServiceType,
    TelemetryConfiguration,
    TelemetryEvent,
    TelemetryReport,
    UsageMetric,
    UserJourney,
    _is_test_env,
)
from .privacy import PrivacyController
from .storage import TelemetryEventStore

try:
    from brain_researcher.services.shared.auth_middleware import (
        UserInfo,
        get_current_user,
    )
except (
    Exception
):  # pragma: no cover - fallback when shared auth middleware is unavailable
    get_current_user = None
    UserInfo = None  # type: ignore


logger = logging.getLogger(__name__)
ALLOW_ANON_TELEMETRY = os.getenv("TELEMETRY_ALLOW_ANONYMOUS", "false").lower() == "true"
SERVICE_TOKEN = os.getenv("TELEMETRY_SERVICE_TOKEN")


def _patch_httpx_async_client() -> None:
    """Provide httpx.AsyncClient(app=...) compatibility in tests."""
    if not _is_test_env():
        return
    try:
        import httpx
    except Exception:  # pragma: no cover - httpx should be available in tests
        return

    if getattr(httpx.AsyncClient.__init__, "_br_patched", False):
        return

    original_init = httpx.AsyncClient.__init__

    def _init(self, *args, app=None, base_url=None, **kwargs):  # type: ignore[no-redef]
        if app is not None:
            kwargs.setdefault("transport", httpx.ASGITransport(app=app))
        if base_url is not None:
            kwargs["base_url"] = base_url
        return original_init(self, *args, **kwargs)

    _init._br_patched = True  # type: ignore[attr-defined]
    httpx.AsyncClient.__init__ = _init  # type: ignore[assignment]


_patch_httpx_async_client()


# Request/Response Models
class EventCollectionRequest(BaseModel):
    """Request to collect a telemetry event."""

    event_type: EventType
    service: ServiceType
    feature_name: Optional[str] = None
    action: Optional[str] = None
    user_id: Optional[str] = None
    session_id: Optional[str] = None
    context: Optional[Dict[str, Any]] = Field(default_factory=dict)
    parameters: Optional[Dict[str, Any]] = Field(default_factory=dict)
    metadata: Optional[Dict[str, Any]] = Field(default_factory=dict)
    duration_ms: Optional[int] = Field(None, ge=0)
    success: bool = True
    error_message: Optional[str] = None
    privacy_level: PrivacyLevel = PrivacyLevel.AGGREGATE_ONLY


class EventCollectionResponse(BaseModel):
    """Response from event collection."""

    event_id: Optional[str]
    collected: bool
    message: str
    timestamp: datetime = Field(default_factory=datetime.utcnow)


class MetricsQueryRequest(BaseModel):
    """Request for metrics aggregation."""

    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    granularity: str = Field(default="hour", pattern="^(hour|day|week|month)$")
    services: Optional[List[ServiceType]] = None
    features: Optional[List[str]] = None
    metric_types: Optional[List[MetricType]] = None

    @field_validator("start_time", "end_time")
    @classmethod
    def validate_time_range(cls, v, info):
        """Validate time range."""
        if v and v > datetime.utcnow():
            raise ValueError("Time cannot be in the future")
        return v


class MetricsResponse(BaseModel):
    """Response containing usage metrics."""

    metrics: List[UsageMetric]
    query: MetricsQueryRequest
    generated_at: datetime = Field(default_factory=datetime.utcnow)
    total_metrics: int
    cache_hit: bool = False


class FeatureAnalysisRequest(BaseModel):
    """Request for feature usage analysis."""

    feature_name: Optional[str] = None
    service: Optional[ServiceType] = None
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    min_usage_count: int = Field(default=5, ge=1)


class FeatureAnalysisResponse(BaseModel):
    """Response containing feature usage analysis."""

    features: List[FeatureUsage]
    query: FeatureAnalysisRequest
    generated_at: datetime = Field(default_factory=datetime.utcnow)
    total_features: int


class JourneyAnalysisRequest(BaseModel):
    """Request for user journey analysis."""

    user_hash: Optional[str] = None
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    min_steps: int = Field(default=2, ge=2, le=100)
    max_journeys: int = Field(default=100, ge=1, le=1000)


class JourneyAnalysisResponse(BaseModel):
    """Response containing user journey analysis."""

    journeys: List[UserJourney]
    query: JourneyAnalysisRequest
    generated_at: datetime = Field(default_factory=datetime.utcnow)
    total_journeys: int
    common_paths: int
    avg_journey_length: float


class RealtimeMetricsResponse(BaseModel):
    """Response for real-time metrics."""

    timestamp: datetime = Field(default_factory=datetime.utcnow)
    window_minutes: int
    total_events: int
    events_per_minute: float
    services: Dict[str, Dict[str, Union[int, float]]]
    features: Dict[str, int]
    errors: Dict[str, Any]
    health_score: float


class PrivacyComplianceResponse(BaseModel):
    """Response for privacy compliance check."""

    is_compliant: bool
    violations: List[str]
    privacy_summary: Dict[str, Any]
    audit_log_entries: int
    recommendations: List[str]


class SystemHealthResponse(BaseModel):
    """Response for telemetry system health."""

    status: str
    collector_stats: Dict[str, Any]
    aggregator_stats: Dict[str, Any]
    privacy_stats: Dict[str, Any]
    last_updated: datetime = Field(default_factory=datetime.utcnow)


class TelemetryService:
    """Main telemetry service coordinating all components."""

    def __init__(self, config: Optional[TelemetryConfiguration] = None):
        self.config = config or TelemetryConfiguration()

        # Initialize components
        self.collector = TelemetryCollector(self.config)
        self.aggregator = UsageMetricsAggregator(AggregationConfig())
        self.privacy_controller = PrivacyController(self.config)
        self.event_store = TelemetryEventStore(
            retention_days=self.config.retention_policy_days
        )

        # Load any persisted events to warm caches
        try:
            historical_events = self.event_store.load_recent_events(
                max_age_days=self.config.retention_policy_days
            )
            if historical_events:
                self.aggregator.seed_events(historical_events)
                logger.info(
                    "Loaded %s persisted telemetry events", len(historical_events)
                )
        except Exception as exc:  # pragma: no cover - best effort warm start
            logger.warning("Failed to load persisted telemetry events: %s", exc)

        # Connect collector to aggregator + storage
        if _is_test_env():
            self.collector.add_processing_handler(self._handle_event_batch_sync)
        else:
            self.collector.add_processing_handler(self._handle_event_batch)

        # Service state
        self._running = False
        self._loop: Optional[asyncio.AbstractEventLoop] = None

        logger.info("TelemetryService initialized")

    async def start(self):
        """Start the telemetry service."""
        if self._running:
            return
        self._loop = asyncio.get_running_loop()
        await self.collector.start()
        self._running = True
        logger.info("TelemetryService started")

    async def stop(self):
        """Stop the telemetry service."""
        if not self._running:
            return

        await self.collector.stop()
        self._running = False
        self._loop = None
        logger.info("TelemetryService stopped")

    async def _handle_event_batch(self, events: List[TelemetryEvent]) -> None:
        """Persist collected events before handing them to the aggregator."""
        await self.event_store.append_events(events)
        await self.aggregator.add_events(events)

    def _handle_event_batch_sync(self, events: List[TelemetryEvent]) -> None:
        """Synchronous handler for test harnesses."""
        self.event_store.append_events_sync(events)
        self.aggregator.add_events_sync(events)


# Global service instance
telemetry_service: Optional[TelemetryService] = None


def get_telemetry_service() -> TelemetryService:
    """Dependency to get the telemetry service."""
    global telemetry_service
    if telemetry_service is None:
        telemetry_service = TelemetryService()
    return telemetry_service


def _allow_service_token(request: Request) -> bool:
    if not SERVICE_TOKEN:
        return False
    supplied = request.headers.get("X-API-Key") or request.headers.get("x-api-key")
    return supplied == SERVICE_TOKEN


if get_current_user:

    async def verify_auth(
        request: Request, current_user: Any = Depends(get_current_user)
    ) -> Any:
        """Use shared auth middleware, with service-token bypass for internal calls."""
        if _allow_service_token(request):
            return {"service": "internal"}
        return current_user

else:

    async def verify_auth(request: Request):
        """Fallback dependency when shared auth middleware is unavailable."""
        if _allow_service_token(request):
            return {"service": "internal"}
        if ALLOW_ANON_TELEMETRY:
            logger.warning(
                "Telemetry auth middleware unavailable - allowing anonymous access"
            )
            return None
        raise HTTPException(
            status_code=503,
            detail=(
                "Authentication middleware unavailable for telemetry service. "
                "Set TELEMETRY_ALLOW_ANONYMOUS=true or configure TELEMETRY_SERVICE_TOKEN for internal access."
            ),
        )


def _build_dependency_kwargs(func: Any, http_request: Request) -> Dict[str, Any]:
    """Provide only supported kwargs when resolving dependencies manually."""
    try:
        params = inspect.signature(func).parameters
    except (TypeError, ValueError):  # pragma: no cover - defensive
        return {}
    kwargs: Dict[str, Any] = {}
    if "request" in params:
        kwargs["request"] = http_request
    return kwargs


async def _resolve_dependency(http_request: Request, dependency: Any) -> Any:
    """Resolve dependency overrides without using the threadpool."""
    override = http_request.app.dependency_overrides.get(dependency)
    target = override or dependency
    kwargs = _build_dependency_kwargs(target, http_request)
    result = target(**kwargs)
    if inspect.isawaitable(result):
        return await result
    return result


async def _await_in_service_loop(service: TelemetryService, coro: Any) -> Any:
    """Run coroutines on the service loop when called from another thread."""
    loop = getattr(service, "_loop", None)
    current_loop = asyncio.get_running_loop()
    if loop and loop is not current_loop and not loop.is_closed() and loop.is_running():
        future = asyncio.run_coroutine_threadsafe(coro, loop)
        return await asyncio.wrap_future(future)
    return await coro


# FastAPI app
app = FastAPI(
    title="Brain Researcher Telemetry API",
    description="TELEMETRY-003 Usage Metrics Tracking System",
    version="1.0.0",
    docs_url="/telemetry/docs",
    redoc_url="/telemetry/redoc",
)


@app.on_event("startup")
async def startup_event():
    """Initialize telemetry service on startup."""
    service = get_telemetry_service()
    await service.start()


@app.on_event("shutdown")
async def shutdown_event():
    """Clean shutdown of telemetry service."""
    service = get_telemetry_service()
    await service.stop()


# Event Collection Endpoints


@app.post("/telemetry/events/collect", response_model=EventCollectionResponse)
async def collect_event(
    request: EventCollectionRequest,
    background_tasks: BackgroundTasks,
    http_request: Request,
) -> EventCollectionResponse:
    """Collect a single telemetry event."""
    service = await _resolve_dependency(http_request, get_telemetry_service)
    await _resolve_dependency(http_request, verify_auth)
    try:
        event_id = service.collector.collect(
            event_type=request.event_type,
            service=request.service,
            feature_name=request.feature_name,
            action=request.action,
            user_id=request.user_id,
            session_id=request.session_id,
            context=request.context,
            parameters=request.parameters,
            metadata=request.metadata,
            duration_ms=request.duration_ms,
            success=request.success,
            error_message=request.error_message,
            privacy_level=request.privacy_level,
        )

        if event_id:
            return EventCollectionResponse(
                event_id=event_id,
                collected=True,
                message="Event collected successfully",
            )
        else:
            return EventCollectionResponse(
                event_id=None,
                collected=False,
                message="Event not collected (sampling, rate limiting, or disabled)",
            )

    except Exception as e:
        logger.error(f"Error collecting event: {e}", exc_info=True)
        raise HTTPException(
            status_code=500, detail=f"Failed to collect event: {str(e)}"
        )


@app.post("/telemetry/events/batch", response_model=Dict[str, Any])
async def collect_events_batch(
    events: List[EventCollectionRequest],
    background_tasks: BackgroundTasks,
    http_request: Request,
) -> Dict[str, Any]:
    """Collect multiple telemetry events in batch."""
    service = await _resolve_dependency(http_request, get_telemetry_service)
    await _resolve_dependency(http_request, verify_auth)
    if len(events) > 100:
        raise HTTPException(
            status_code=400, detail="Batch size cannot exceed 100 events"
        )

    results = {
        "total_events": len(events),
        "collected_count": 0,
        "failed_count": 0,
        "event_ids": [],
        "errors": [],
    }

    for i, event_request in enumerate(events):
        try:
            event_id = service.collector.collect(
                event_type=event_request.event_type,
                service=event_request.service,
                feature_name=event_request.feature_name,
                action=event_request.action,
                user_id=event_request.user_id,
                session_id=event_request.session_id,
                context=event_request.context,
                parameters=event_request.parameters,
                metadata=event_request.metadata,
                duration_ms=event_request.duration_ms,
                success=event_request.success,
                error_message=event_request.error_message,
                privacy_level=event_request.privacy_level,
            )

            if event_id:
                results["collected_count"] += 1
                results["event_ids"].append(event_id)

        except Exception as e:
            results["failed_count"] += 1
            results["errors"].append(f"Event {i}: {str(e)}")

    return results


# Metrics and Analytics Endpoints


@app.post("/telemetry/metrics", response_model=MetricsResponse)
async def get_usage_metrics(
    request: MetricsQueryRequest,
    http_request: Request,
) -> MetricsResponse:
    """Get aggregated usage metrics."""
    service = await _resolve_dependency(http_request, get_telemetry_service)
    await _resolve_dependency(http_request, verify_auth)
    try:
        # Set default time window if not specified
        if request.end_time is None:
            request.end_time = datetime.utcnow()
        if request.start_time is None:
            request.start_time = request.end_time - timedelta(hours=24)

        # Create aggregation window
        window = AggregationWindow(
            start=request.start_time,
            end=request.end_time,
            granularity=request.granularity,
        )

        # Get metrics
        metrics = await service.aggregator.calculate_usage_metrics(
            window=window, services=request.services, features=request.features
        )

        # Filter by metric types if specified
        if request.metric_types:
            metrics = [m for m in metrics if m.metric_type in request.metric_types]

        return MetricsResponse(
            metrics=metrics, query=request, total_metrics=len(metrics)
        )

    except Exception as e:
        logger.error(f"Error getting usage metrics: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to get metrics: {str(e)}")


@app.post("/telemetry/features/analyze", response_model=FeatureAnalysisResponse)
async def analyze_feature_usage(
    request: FeatureAnalysisRequest,
    http_request: Request,
) -> FeatureAnalysisResponse:
    """Analyze feature usage patterns."""
    service = await _resolve_dependency(http_request, get_telemetry_service)
    await _resolve_dependency(http_request, verify_auth)
    try:
        # Set default time window if not specified
        if request.end_time is None:
            request.end_time = datetime.utcnow()
        if request.start_time is None:
            request.start_time = request.end_time - timedelta(hours=24)

        # Create aggregation window
        window = AggregationWindow(
            start=request.start_time, end=request.end_time, granularity="day"
        )

        # Analyze features
        features = await service.aggregator.analyze_feature_usage(
            feature_name=request.feature_name, service=request.service, window=window
        )

        # Filter by minimum usage count
        features = [f for f in features if f.total_uses >= request.min_usage_count]

        # Calculate average journey length
        avg_length = (
            sum(f.total_uses for f in features) / len(features) if features else 0
        )

        return FeatureAnalysisResponse(
            features=features, query=request, total_features=len(features)
        )

    except Exception as e:
        logger.error(f"Error analyzing features: {e}", exc_info=True)
        raise HTTPException(
            status_code=500, detail=f"Failed to analyze features: {str(e)}"
        )


@app.post("/telemetry/journeys/analyze", response_model=JourneyAnalysisResponse)
async def analyze_user_journeys(
    request: JourneyAnalysisRequest,
    http_request: Request,
) -> JourneyAnalysisResponse:
    """Analyze user journey patterns."""
    service = await _resolve_dependency(http_request, get_telemetry_service)
    await _resolve_dependency(http_request, verify_auth)
    try:
        # Set default time window if not specified
        if request.end_time is None:
            request.end_time = datetime.utcnow()
        if request.start_time is None:
            request.start_time = request.end_time - timedelta(hours=24)

        # Create aggregation window
        window = AggregationWindow(
            start=request.start_time, end=request.end_time, granularity="hour"
        )

        # Extract journeys
        journeys = await service.aggregator.extract_user_journeys(
            user_hash=request.user_hash, window=window, min_steps=request.min_steps
        )

        # Limit results
        if len(journeys) > request.max_journeys:
            journeys = journeys[: request.max_journeys]

        # Calculate statistics
        common_paths = sum(1 for j in journeys if j.common_path)
        avg_length = (
            sum(j.total_steps for j in journeys) / len(journeys) if journeys else 0
        )

        return JourneyAnalysisResponse(
            journeys=journeys,
            query=request,
            total_journeys=len(journeys),
            common_paths=common_paths,
            avg_journey_length=avg_length,
        )

    except Exception as e:
        logger.error(f"Error analyzing journeys: {e}", exc_info=True)
        raise HTTPException(
            status_code=500, detail=f"Failed to analyze journeys: {str(e)}"
        )


@app.get("/telemetry/realtime", response_model=RealtimeMetricsResponse)
async def get_realtime_metrics(
    http_request: Request,
) -> RealtimeMetricsResponse:
    """Get real-time telemetry metrics."""
    service = await _resolve_dependency(http_request, get_telemetry_service)
    await _resolve_dependency(http_request, verify_auth)
    try:
        metrics = await service.aggregator.get_real_time_metrics()

        # Calculate health score based on error rates and activity
        total_events = metrics.get("total_events", 0)
        errors = metrics.get("errors", {})
        error_count = errors.get("total_errors", 0) if isinstance(errors, dict) else 0

        health_score = 1.0
        if total_events > 0:
            error_rate = error_count / total_events
            health_score = max(0.0, 1.0 - (error_rate * 2))  # Penalize errors

        return RealtimeMetricsResponse(
            window_minutes=metrics["window_minutes"],
            total_events=total_events,
            events_per_minute=metrics["events_per_minute"],
            services=metrics["services"],
            features=metrics["features"],
            errors=metrics["errors"],
            health_score=health_score,
        )

    except Exception as e:
        logger.error(f"Error getting real-time metrics: {e}", exc_info=True)
        raise HTTPException(
            status_code=500, detail=f"Failed to get real-time metrics: {str(e)}"
        )


# Privacy and Compliance Endpoints


@app.get("/telemetry/privacy/compliance", response_model=PrivacyComplianceResponse)
async def check_privacy_compliance(
    days: int = Query(default=7, ge=1, le=30, description="Days of data to check"),
    http_request: Request = None,
) -> PrivacyComplianceResponse:
    """Check privacy compliance status."""
    if http_request is None:  # pragma: no cover - FastAPI will supply
        raise HTTPException(status_code=500, detail="Request context unavailable")
    service = await _resolve_dependency(http_request, get_telemetry_service)
    await _resolve_dependency(http_request, verify_auth)
    try:
        # Get recent events for compliance check
        end_time = datetime.utcnow()
        start_time = end_time - timedelta(days=days)

        # Filter events (simplified - would access actual event store)
        events = [
            e
            for e in service.aggregator._events
            if start_time <= e.timestamp <= end_time
        ]

        # Check compliance for each event
        all_violations = []
        for event in events[:100]:  # Limit to first 100 for performance
            is_compliant, violations = (
                service.privacy_controller.validate_data_compliance(event)
            )
            if not is_compliant:
                all_violations.extend(violations)

        # Get privacy summary
        privacy_summary = service.privacy_controller.get_privacy_summary(events)

        # Generate recommendations
        recommendations = []
        if len(all_violations) > 0:
            recommendations.append("Review and improve data anonymization processes")
        if privacy_summary.get("anonymization_rate", 0) < 95:
            recommendations.append("Increase anonymization rate to >95%")

        return PrivacyComplianceResponse(
            is_compliant=len(all_violations) == 0,
            violations=list(set(all_violations)),
            privacy_summary=privacy_summary,
            audit_log_entries=len(service.privacy_controller._audit_logs),
            recommendations=recommendations,
        )

    except Exception as e:
        logger.error(f"Error checking privacy compliance: {e}", exc_info=True)
        raise HTTPException(
            status_code=500, detail=f"Failed to check compliance: {str(e)}"
        )


@app.get("/telemetry/privacy/audit", response_model=List[Dict[str, Any]])
async def get_privacy_audit_log(
    days: int = Query(
        default=7, ge=1, le=90, description="Days of audit logs to retrieve"
    ),
    http_request: Request = None,
) -> List[Dict[str, Any]]:
    """Get privacy audit logs for compliance reporting."""
    if http_request is None:  # pragma: no cover - FastAPI will supply
        raise HTTPException(status_code=500, detail="Request context unavailable")
    service = await _resolve_dependency(http_request, get_telemetry_service)
    await _resolve_dependency(http_request, verify_auth)
    try:
        start_time = datetime.utcnow() - timedelta(days=days)
        audit_logs = service.privacy_controller.export_audit_log(start_time=start_time)
        return audit_logs

    except Exception as e:
        logger.error(f"Error getting audit logs: {e}", exc_info=True)
        raise HTTPException(
            status_code=500, detail=f"Failed to get audit logs: {str(e)}"
        )


# System Management Endpoints


@app.get("/telemetry/health", response_model=SystemHealthResponse)
async def get_system_health(
    http_request: Request,
) -> SystemHealthResponse:
    """Get telemetry system health status."""
    service = await _resolve_dependency(http_request, get_telemetry_service)
    try:
        collector_stats = service.collector.get_stats()
        aggregator_stats = service.aggregator.get_aggregator_stats()

        # Create simplified privacy stats
        privacy_stats = {
            "audit_logs": len(service.privacy_controller._audit_logs),
            "gdpr_mode": service.privacy_controller._gdpr_enabled,
            "retention_policies": len(service.privacy_controller._retention_policies),
        }

        # Determine overall status
        status = "healthy"
        if collector_stats.get("processing_errors", 0) > 10:
            status = "degraded"
        if not service._running:
            status = "unhealthy"

        return SystemHealthResponse(
            status=status,
            collector_stats=collector_stats,
            aggregator_stats=aggregator_stats,
            privacy_stats=privacy_stats,
        )

    except Exception as e:
        logger.error(f"Error getting system health: {e}", exc_info=True)
        raise HTTPException(
            status_code=500, detail=f"Failed to get system health: {str(e)}"
        )


@app.post("/telemetry/admin/flush")
async def flush_events(
    http_request: Request,
) -> Dict[str, Any]:
    """Force flush of pending events (admin operation)."""
    service = await _resolve_dependency(http_request, get_telemetry_service)
    await _resolve_dependency(http_request, verify_auth)
    try:
        # Force flush collector
        await service.collector._flush_events(force=True)

        stats = service.collector.get_stats()
        return {
            "message": "Events flushed successfully",
            "events_processed": stats.get("events_processed", 0),
            "buffer_size": stats.get("buffer_size", 0),
        }

    except Exception as e:
        logger.error(f"Error flushing events: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to flush events: {str(e)}")


@app.post("/telemetry/admin/purge")
async def purge_expired_data(
    days: int = Query(
        default=90, ge=1, le=365, description="Purge data older than days"
    ),
    http_request: Request = None,
) -> Dict[str, Any]:
    """Purge expired telemetry data (admin operation)."""
    if http_request is None:  # pragma: no cover - FastAPI will supply
        raise HTTPException(status_code=500, detail="Request context unavailable")
    service = await _resolve_dependency(http_request, get_telemetry_service)
    await _resolve_dependency(http_request, verify_auth)
    try:
        # Get events for purge operation
        events = service.aggregator._events.copy()

        # Apply retention purge
        remaining_events, purged_count = service.privacy_controller.purge_expired_data(
            events
        )

        # Update aggregator events (in production, this would be database operation)
        service.aggregator._events = remaining_events

        return {
            "message": f"Purged {purged_count} expired events",
            "purged_count": purged_count,
            "remaining_events": len(remaining_events),
        }

    except Exception as e:
        logger.error(f"Error purging data: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to purge data: {str(e)}")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8003)
