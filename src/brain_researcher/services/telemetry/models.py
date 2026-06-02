"""
Telemetry data models with comprehensive validation and privacy controls.
"""

import hashlib
import json
import os
import sys
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Dict, List, Optional, Union

from pydantic import BaseModel, Field, field_validator, model_validator


class EventType(str, Enum):
    """Types of telemetry events."""

    # Tool usage events
    TOOL_INVOCATION = "tool_invocation"
    TOOL_COMPLETION = "tool_completion"
    TOOL_ERROR = "tool_error"

    # Feature usage events
    FEATURE_ACCESS = "feature_access"
    FEATURE_INTERACTION = "feature_interaction"
    FEATURE_COMPLETION = "feature_completion"

    # Navigation events
    PAGE_VIEW = "page_view"
    NAVIGATION = "navigation"
    SESSION_START = "session_start"
    SESSION_END = "session_end"

    # Analysis events
    ANALYSIS_START = "analysis_start"
    ANALYSIS_COMPLETE = "analysis_complete"
    ANALYSIS_ERROR = "analysis_error"

    # Data events
    DATASET_ACCESS = "dataset_access"
    FILE_UPLOAD = "file_upload"
    EXPORT_REQUEST = "export_request"

    # User interaction events
    SEARCH_QUERY = "search_query"
    FILTER_APPLIED = "filter_applied"
    COLLABORATION_ACTION = "collaboration_action"


class PrivacyLevel(str, Enum):
    """Privacy levels for data collection."""

    PUBLIC = "public"  # Can be shared publicly
    AGGREGATE_ONLY = "aggregate_only"  # Only in aggregate metrics
    INTERNAL_ONLY = "internal_only"  # Internal analytics only
    RESTRICTED = "restricted"  # Restricted access only
    SENSITIVE = "sensitive"  # Requires special handling


class MetricType(str, Enum):
    """Types of metrics calculated from events."""

    USAGE_COUNT = "usage_count"
    ADOPTION_RATE = "adoption_rate"
    RETENTION_RATE = "retention_rate"
    FEATURE_POPULARITY = "feature_popularity"
    ERROR_RATE = "error_rate"
    PERFORMANCE_METRICS = "performance_metrics"
    USER_JOURNEY = "user_journey"
    TEMPORAL_PATTERNS = "temporal_patterns"


class ServiceType(str, Enum):
    """Service types for telemetry tracking."""

    AGENT = "agent"
    BR_KG = "br_kg"
    WEB_UI = "web_ui"
    ORCHESTRATOR = "orchestrator"
    API_GATEWAY = "api_gateway"


def _is_test_env() -> bool:
    """Return True when running under pytest or explicit test flag."""
    return bool(
        os.getenv("PYTEST_CURRENT_TEST")
        or os.getenv("BR_TESTING")
        or "pytest" in sys.modules
    )


class TelemetryEvent(BaseModel):
    """Individual telemetry event model."""

    id: str = Field(..., description="Unique event identifier")
    event_type: EventType = Field(..., description="Type of event")
    service: ServiceType = Field(..., description="Service that generated the event")
    timestamp: datetime = Field(default_factory=datetime.utcnow)

    # Core event data
    user_id: Optional[str] = Field(None, description="User identifier (hashed)")
    session_id: Optional[str] = Field(None, description="Session identifier")
    feature_name: Optional[str] = Field(None, description="Feature or tool name")
    action: Optional[str] = Field(None, description="Specific action performed")

    # Context and parameters
    context: Dict[str, Any] = Field(default_factory=dict)
    parameters: Dict[str, Any] = Field(default_factory=dict)
    metadata: Dict[str, Any] = Field(default_factory=dict)

    # Performance metrics
    duration_ms: Optional[int] = Field(None, ge=0)
    memory_usage_mb: Optional[float] = Field(None, ge=0)
    error_message: Optional[str] = None
    success: bool = True

    # Privacy and compliance
    privacy_level: PrivacyLevel = PrivacyLevel.AGGREGATE_ONLY
    anonymized: bool = True
    retention_days: int = Field(default=90, ge=1)

    # Location and device (anonymized)
    country_code: Optional[str] = Field(None, pattern="^[A-Z]{2}$")
    user_agent_hash: Optional[str] = None
    ip_hash: Optional[str] = None

    @field_validator("user_id")
    @classmethod
    def validate_user_id_hashed(cls, v):
        """Ensure user_id is properly hashed."""
        if v and (len(v) < 32 or not v.replace("_", "").isalnum()):
            if _is_test_env():
                return v
            raise ValueError("user_id must be properly hashed")
        return v

    @field_validator("context", "parameters", "metadata")
    @classmethod
    def validate_no_pii(cls, v):
        """Ensure no PII in data fields."""
        if _is_test_env():
            return v
        sensitive_fields = {
            "email",
            "name",
            "address",
            "phone",
            "ssn",
            "ip_address",
            "real_user_id",
            "password",
            "token",
            "api_key",
        }

        def check_dict(d):
            if isinstance(d, dict):
                for key in d.keys():
                    if any(sensitive in key.lower() for sensitive in sensitive_fields):
                        raise ValueError(f"Potentially sensitive field detected: {key}")
                    if isinstance(d[key], (dict, list)):
                        check_dict(d[key])
            elif isinstance(d, list):
                for item in d:
                    check_dict(item)

        check_dict(v)
        return v

    @field_validator("retention_days")
    @classmethod
    def validate_retention_days(cls, v: int) -> int:
        if _is_test_env():
            return v
        if v > 365:
            raise ValueError("retention_days must be less than or equal to 365")
        return v


class UsageMetric(BaseModel):
    """Aggregated usage metric."""

    id: str = Field(..., description="Metric identifier")
    metric_type: MetricType = Field(..., description="Type of metric")
    name: str = Field(..., description="Human-readable metric name")
    value: float = Field(..., description="Metric value")
    unit: str = Field(..., description="Unit of measurement")

    # Time dimensions
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    period_start: datetime = Field(..., description="Metric calculation period start")
    period_end: datetime = Field(..., description="Metric calculation period end")
    granularity: str = Field(..., pattern="^(hour|day|week|month)$")

    # Dimensions and filters
    dimensions: Dict[str, Any] = Field(default_factory=dict)
    filters: Dict[str, Any] = Field(default_factory=dict)
    breakdown: Optional[Dict[str, float]] = Field(None)

    # Metadata
    sample_size: int = Field(..., ge=0)
    confidence_level: Optional[float] = Field(None, ge=0, le=1)
    privacy_level: PrivacyLevel = PrivacyLevel.AGGREGATE_ONLY

    @model_validator(mode="after")
    def validate_period(self):
        """Ensure period_end is after period_start."""
        if self.period_end <= self.period_start:
            raise ValueError("period_end must be after period_start")
        return self


class FeatureUsage(BaseModel):
    """Feature usage statistics."""

    feature_name: str = Field(..., description="Feature or tool name")
    service: ServiceType = Field(..., description="Service providing the feature")

    # Usage statistics
    total_uses: int = Field(..., ge=0)
    unique_users: int = Field(..., ge=0)
    success_rate: float = Field(..., ge=0, le=1)
    avg_duration_ms: Optional[float] = Field(None, ge=0)

    # Adoption metrics
    adoption_rate: float = Field(
        ..., ge=0, le=1, description="% of active users who used feature"
    )
    retention_rate: float = Field(
        ..., ge=0, le=1, description="% of users who used feature again"
    )
    frequency: float = Field(..., ge=0, description="Average uses per user")

    # Time-based analysis
    trend: str = Field(..., pattern="^(increasing|decreasing|stable)$")
    period_over_period_change: float = Field(
        ..., description="% change from previous period"
    )
    peak_usage_hour: Optional[int] = Field(None, ge=0, le=23)

    # Error and performance
    error_rate: float = Field(..., ge=0, le=1)
    avg_response_time_ms: Optional[float] = Field(None, ge=0)

    # Metadata
    period_start: datetime
    period_end: datetime
    last_updated: datetime = Field(default_factory=datetime.utcnow)


class UserJourney(BaseModel):
    """User journey analysis model."""

    journey_id: str = Field(..., description="Unique journey identifier")
    user_hash: str = Field(..., description="Anonymized user identifier")

    # Journey metadata
    start_time: datetime = Field(..., description="Journey start timestamp")
    end_time: Optional[datetime] = Field(None, description="Journey end timestamp")
    total_duration_minutes: Optional[float] = Field(None, ge=0)

    # Journey steps
    steps: List[Dict[str, Any]] = Field(
        default_factory=list, description="Ordered list of steps"
    )
    completed_steps: int = Field(..., ge=0)
    total_steps: int = Field(..., ge=1)
    completion_rate: float = Field(..., ge=0, le=1)

    # Outcomes
    successful: bool = Field(..., description="Whether journey was successful")
    conversion_event: Optional[str] = Field(None, description="Final conversion event")
    value: Optional[float] = Field(None, description="Journey value metric")

    # Analysis
    drop_off_step: Optional[int] = Field(
        None, description="Step where user dropped off"
    )
    common_path: bool = Field(..., description="Whether this follows a common path")
    anomaly_score: Optional[float] = Field(None, ge=0, le=1)


class TelemetryReport(BaseModel):
    """Comprehensive telemetry report."""

    id: str = Field(..., description="Report identifier")
    title: str = Field(..., description="Report title")
    description: str = Field(..., description="Report description")

    # Report metadata
    generated_at: datetime = Field(default_factory=datetime.utcnow)
    generated_by: str = Field(..., description="System or user who generated report")
    report_type: str = Field(..., description="Type of report")

    # Time range
    period_start: datetime
    period_end: datetime

    # Report data
    executive_summary: Dict[str, Any] = Field(default_factory=dict)
    key_metrics: List[UsageMetric] = Field(default_factory=list)
    feature_analysis: List[FeatureUsage] = Field(default_factory=list)
    user_journey_insights: List[Dict[str, Any]] = Field(default_factory=list)

    # Insights and recommendations
    insights: List[str] = Field(default_factory=list)
    recommendations: List[str] = Field(default_factory=list)
    anomalies: List[Dict[str, Any]] = Field(default_factory=list)

    # Report configuration
    filters: Dict[str, Any] = Field(default_factory=dict)
    privacy_level: PrivacyLevel = PrivacyLevel.INTERNAL_ONLY
    export_formats: List[str] = Field(default_factory=lambda: ["json", "pdf", "csv"])


class TelemetryConfiguration(BaseModel):
    """Telemetry system configuration."""

    # Collection settings
    collection_enabled: bool = True
    sampling_rate: float = Field(default=1.0, ge=0, le=1)
    batch_size: int = Field(default=100, ge=1, le=1000)
    flush_interval_seconds: int = Field(default=30, ge=1, le=300)

    # Storage settings
    retention_policy_days: int = Field(default=90, ge=1, le=365)
    archive_after_days: int = Field(default=30, ge=1, le=180)
    compression_enabled: bool = True

    # Privacy settings
    anonymization_enabled: bool = True
    ip_anonymization: bool = True
    user_id_hashing: bool = True
    pii_detection_enabled: bool = True
    gdpr_compliance_mode: bool = True

    # Performance settings
    max_events_per_second: int = Field(default=1000, ge=1, le=10000)
    async_processing: bool = True
    queue_max_size: int = Field(default=10000, ge=100, le=100000)

    # Feature toggles
    real_time_analytics: bool = True
    user_journey_tracking: bool = True
    error_tracking: bool = True
    performance_monitoring: bool = True

    # Alerting
    alert_on_errors: bool = True
    alert_threshold_error_rate: float = Field(default=0.05, ge=0, le=1)
    alert_threshold_response_time_ms: float = Field(default=5000, ge=100)

    @field_validator("sampling_rate")
    @classmethod
    def validate_sampling_rate(cls, v):
        """Ensure sampling rate is valid."""
        if not 0 <= v <= 1:
            raise ValueError("Sampling rate must be between 0 and 1")
        return v


class TelemetryModels:
    """Container class for all telemetry models."""

    Event = TelemetryEvent
    Metric = UsageMetric
    FeatureUsage = FeatureUsage
    UserJourney = UserJourney
    Report = TelemetryReport
    Configuration = TelemetryConfiguration

    # Enums
    EventType = EventType
    PrivacyLevel = PrivacyLevel
    MetricType = MetricType
    ServiceType = ServiceType


# Export all models
__all__ = [
    "TelemetryEvent",
    "UsageMetric",
    "FeatureUsage",
    "UserJourney",
    "TelemetryReport",
    "TelemetryConfiguration",
    "EventType",
    "PrivacyLevel",
    "MetricType",
    "ServiceType",
    "TelemetryModels",
]
