"""
Enhanced data models and DTOs for the Orchestrator service.

This module provides comprehensive Pydantic models with validation,
error codes, and contract definitions for frontend integration.
"""

import hashlib
import json
from datetime import datetime
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from brain_researcher.core.contracts.run_card import RunCardV1
from brain_researcher.core.contracts.violation import Violation
from brain_researcher.services.shared.retry_timeout import (
    RetryConfig as SharedRetryConfig,
)
from brain_researcher.services.shared.retry_timeout import (
    TimeoutConfig as SharedTimeoutConfig,
)

# ============================================================================
# Enums and Constants
# ============================================================================

CATALOG_DATASET_ID_PATTERN = r"^[a-zA-Z0-9_:-]+$"

class JobStatus(str, Enum):
    """Job execution status."""

    PENDING = "pending"
    QUEUED = "queued"
    CLAIMED = "claimed"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    CANCELLING = "cancelling"
    SKIPPED = "skipped"
    PAUSED = "paused"
    RETRYING = "retrying"
    TIMEOUT = "timeout"

class StepStatus(str, Enum):
    """Individual step execution status."""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"

class ErrorCode(str, Enum):
    """Standardized error codes for frontend handling."""
    # Service errors
    SERVICE_UNAVAILABLE = "SERVICE_UNAVAILABLE"
    SERVICE_TIMEOUT = "SERVICE_TIMEOUT"
    SERVICE_ERROR = "SERVICE_ERROR"

    # Request errors
    INVALID_REQUEST = "INVALID_REQUEST"
    VALIDATION_ERROR = "VALIDATION_ERROR"
    MISSING_PARAMETER = "MISSING_PARAMETER"
    INVALID_PARAMETER = "INVALID_PARAMETER"

    # Resource errors
    NOT_FOUND = "NOT_FOUND"
    RESOURCE_LOCKED = "RESOURCE_LOCKED"
    QUOTA_EXCEEDED = "QUOTA_EXCEEDED"

    # Processing errors
    PROCESSING_ERROR = "PROCESSING_ERROR"
    TIMEOUT = "TIMEOUT"
    CANCELLED = "CANCELLED"

    # Auth errors
    UNAUTHORIZED = "UNAUTHORIZED"
    FORBIDDEN = "FORBIDDEN"

    # Rate limiting
    RATE_LIMITED = "RATE_LIMITED"

    # Internal errors
    INTERNAL_ERROR = "INTERNAL_ERROR"
    UNKNOWN_ERROR = "UNKNOWN_ERROR"

class ArtifactType(str, Enum):
    """Types of artifacts that can be generated."""
    IMAGE = "image"
    TABLE = "table"
    FILE = "file"
    BRAIN_MAP = "brain_map"
    GRAPH = "graph"
    REPORT = "report"
    VIDEO = "video"
    MESH = "mesh"
    CHAT_RESPONSE = "chat_response"
    TOOL_RESULT = "tool_result"

class PipelineType(str, Enum):
    """Available analysis pipelines."""
    GLM = "glm"
    CONNECTIVITY = "connectivity"
    DECODING = "decoding"
    PREPROCESSING = "preprocessing"
    CUSTOM = "custom"
    DEMO = "demo"
    PIPELINE_BUILDER = "pipeline_builder"
    CHAT = "chat"
    COPILOT = "copilot"

class DatasetSource(str, Enum):
    """Dataset sources."""
    OPENNEURO = "OpenNeuro"
    BUILTIN = "BuiltIn"
    CUSTOM = "Custom"
    NEUROVAULT = "NeuroVault"
    HCP = "HCP"
    UKBIOBANK = "UKBiobank"

class Modality(str, Enum):
    """Neuroimaging modalities."""
    FMRI = "fMRI"
    SMRI = "sMRI"
    DTI = "DTI"
    MEG = "MEG"
    EEG = "EEG"
    PET = "PET"

# ============================================================================
# Error Response Models
# ============================================================================

class ErrorDetail(BaseModel):
    """Detailed error information."""
    field: str | None = None
    message: str
    code: str | None = None

class ErrorResponse(BaseModel):
    """Standardized error response."""
    error: dict[str, Any] = Field(default_factory=dict)

    model_config = {
        "json_schema_extra": {
            "example": {
                "error": {
                    "code": "VALIDATION_ERROR",
                    "message": "Invalid parameter value",
                    "details": {
                        "field": "smoothing",
                        "constraint": "Must be between 0 and 12"
                    },
                    "timestamp": "2024-01-01T00:00:00Z"
                }
            }
        }
    }

    @classmethod
    def create(cls, code: ErrorCode, message: str, details: dict | None = None):
        """Factory method to create error response."""
        return cls(
            error={
                "code": code.value,
                "message": message,
                "details": details or {},
                "timestamp": datetime.utcnow().isoformat() + "Z"
            }
        )

# ============================================================================
# File Models (needed before RunRequest)
# ============================================================================

class FileAttachment(BaseModel):
    """File attachment model for chat messages."""
    id: str = Field(..., description="Unique file identifier")
    name: str = Field(..., description="Original filename")
    type: str = Field(..., description="MIME type")
    size: int = Field(..., ge=0, description="File size in bytes")
    url: str = Field(..., description="URL to access the file")
    upload_progress: float | None = Field(None, ge=0, le=100, description="Upload progress percentage")
    # New optional fields for storage metadata and provenance (backward compatible)
    storage: Literal["local", "s3", "remote"] | None = Field(
        None, description="Storage backend type"
    )
    path: str | None = Field(
        None, description="Local filesystem path (if storage is local)"
    )
    checksum: str | None = Field(
        None, description="SHA256 checksum of file contents"
    )
    uploaded_by: str | None = Field(
        None, description="User or system that uploaded the file"
    )
    expires_at: datetime | None = Field(
        None, description="Expiration timestamp for temporary files"
    )

    @field_validator('name')
    @classmethod
    def validate_filename(cls, v):
        """Validate filename safety."""
        import os
        import re

        # Get just the filename (no path)
        filename = os.path.basename(v)

        # Check for valid characters (allowing dots for extensions)
        if not re.match(r'^[a-zA-Z0-9._-]+$', filename):
            raise ValueError('Filename contains invalid characters. Only alphanumeric characters, dots, underscores, and hyphens are allowed.')

        # Prevent dangerous filenames
        if filename.startswith('.') or filename in ['', '.', '..']:
            raise ValueError('Invalid filename')

        # Limit filename length
        if len(filename) > 255:
            raise ValueError('Filename too long (max 255 characters)')

        return filename

# ============================================================================
# Request Models with Enhanced Validation
# ============================================================================

class RunRequest(BaseModel):
    """Enhanced request model for job execution."""
    prompt: str = Field(..., min_length=1, max_length=5000)
    pipeline: PipelineType | None = PipelineType.CUSTOM
    dataset_id: str | None = Field(None, pattern=CATALOG_DATASET_ID_PATTERN)
    requested_job_id: str | None = Field(
        default=None,
        pattern="^[a-zA-Z0-9_-]+$",
        description="Internal deterministic job/analysis identifier for trusted demo seeding flows.",
    )
    project_id: str | None = Field(
        default=None,
        description="Optional project/workspace identifier used for analysis grouping.",
    )
    parameters: dict[str, Any] | None = Field(default_factory=dict)
    query_understanding: dict[str, Any] | None = Field(
        default=None,
        description="Optional query understanding payload (datasets/KG/derivatives).",
    )
    copilot: bool = False
    demo_mode: bool = False
    cache_key: str | None = None
    thread_id: str | None = None
    checkpoint_id: str | None = Field(
        default=None,
        description="Canonical checkpoint identifier used to resume an interrupted run.",
    )
    scenario_id: str | None = Field(
        default=None,
        description="Chat scenario identifier that defines system prompts/tool hints."
    )
    timeout_seconds: int = Field(default=300, ge=10, le=3600)
    priority: int = Field(default=5, ge=1, le=10)
    attachments: list[FileAttachment] | None = Field(default_factory=list)
    intent: str | None = Field(
        None,
        description="Natural language intent for automatic tool selection (e.g., 'skull strip')",
    )
    canonical_op: dict[str, Any] | None = Field(
        None,
        description="Canonical operation specification for LPM (e.g., {'name': 'smooth', 'params': {...}})",
    )

    @model_validator(mode="before")
    @classmethod
    def normalize_checkpoint_aliases(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        normalized = dict(data)
        requested_job_id = (
            normalized.get("requested_job_id")
            or normalized.get("requestedJobId")
            or normalized.get("analysis_id")
            or normalized.get("analysisId")
            or normalized.get("job_id")
            or normalized.get("jobId")
            or normalized.get("run_id")
            or normalized.get("runId")
        )
        checkpoint_id = (
            normalized.get("checkpoint_id")
            or normalized.get("checkpointId")
            or normalized.get("resume_checkpoint_id")
            or normalized.get("resumeCheckpointId")
        )
        normalized.pop("requestedJobId", None)
        normalized.pop("analysis_id", None)
        normalized.pop("analysisId", None)
        normalized.pop("job_id", None)
        normalized.pop("jobId", None)
        normalized.pop("run_id", None)
        normalized.pop("runId", None)
        normalized.pop("checkpointId", None)
        normalized.pop("resume_checkpoint_id", None)
        normalized.pop("resumeCheckpointId", None)
        if requested_job_id:
            normalized["requested_job_id"] = str(requested_job_id)
        if checkpoint_id:
            normalized["checkpoint_id"] = str(checkpoint_id)
        return normalized

    @field_validator('parameters')
    @classmethod
    def validate_parameters(cls, v, info):
        """Validate parameters based on pipeline type."""
        pipeline = info.data.get('pipeline')
        if pipeline == PipelineType.GLM and v:
            # Validate GLM-specific parameters
            if 'smoothing' in v:
                if not (0 <= v['smoothing'] <= 12):
                    raise ValueError('Smoothing must be between 0 and 12')
            if 'threshold' in v:
                if not (0 < v['threshold'] < 1):
                    raise ValueError('Threshold must be between 0 and 1')
        return v

    @field_validator('attachments')
    @classmethod
    def validate_attachments(cls, v):
        """Validate attachment format and size."""
        if not v:
            return v
        total_size = sum(attachment.size for attachment in v)
        if total_size > 150_000_000:  # 150MB total limit
            raise ValueError('Total attachment size cannot exceed 150MB')
        return v

    @model_validator(mode='after')
    def validate_demo_mode(self):
        """Ensure demo mode has required fields."""
        if self.demo_mode and not self.cache_key:
            self.cache_key = hashlib.md5(
                json.dumps({
                    'prompt': self.prompt,
                    'pipeline': self.pipeline
                }, sort_keys=True).encode()
            ).hexdigest()
        return self


class PipelineNodeConfig(BaseModel):
    """Node definition supplied by the visual pipeline builder."""

    id: str = Field(..., min_length=1, max_length=64, pattern=r"^[a-zA-Z0-9_-]+$")
    label: str = Field(..., min_length=1, max_length=120)
    tool: str | None = Field(None, min_length=1, max_length=120)
    node_type: str | None = Field(default=None, alias="type")
    category: str | None = Field(default=None, max_length=64)
    parameters: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)
    config: dict[str, Any] = Field(default_factory=dict)
    position: dict[str, Any] | None = None

    model_config = {
        "populate_by_name": True
    }


class PipelineEdgeConfig(BaseModel):
    """Edge definition supplied by the visual pipeline builder."""

    id: str | None = Field(default=None, pattern=r"^[a-zA-Z0-9_-]+$")
    source: str = Field(..., min_length=1, max_length=64, pattern=r"^[a-zA-Z0-9_-]+$")
    target: str = Field(..., min_length=1, max_length=64, pattern=r"^[a-zA-Z0-9_-]+$")
    label: str | None = Field(default=None, max_length=120)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode='after')
    def validate_direction(self):
        if self.source == self.target:
            raise ValueError('Edge cannot connect a node to itself')
        return self


class PipelineExecutionStep(BaseModel):
    """Step description returned to the UI for immediate feedback."""

    node_id: str
    order: int = Field(ge=0)
    name: str
    tool: str
    status: StepStatus
    estimated_duration_ms: int = Field(ge=0)
    summary: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class PipelineResourceSnapshot(BaseModel):
    """Initial resource snapshot for the pipeline nodes."""

    label: str
    status: StepStatus
    progress: float = Field(ge=0.0, le=100.0)
    node_type: str | None = None
    resources: dict[str, Any] = Field(default_factory=dict)


class PipelineExecutionRequest(BaseModel):
    """Request body for executing a visual pipeline."""

    name: str | None = Field(default=None, max_length=120)
    description: str | None = Field(default=None, max_length=500)
    pipeline_id: str | None = Field(default=None, max_length=64, pattern=r"^[a-zA-Z0-9_-]+$")
    nodes: list[PipelineNodeConfig]
    edges: list[PipelineEdgeConfig] = Field(default_factory=list)
    dataset_id: str | None = Field(default=None, pattern=CATALOG_DATASET_ID_PATTERN)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode='after')
    def validate_nodes_and_edges(self):
        if not self.nodes:
            raise ValueError('Pipeline must contain at least one node')

        node_ids: set[str] = {node.id for node in self.nodes}
        missing = [edge for edge in self.edges if edge.source not in node_ids or edge.target not in node_ids]
        if missing:
            raise ValueError('Edges reference undefined nodes')

        return self


class PipelineExecutionResponse(BaseModel):
    """Response payload for a pipeline execution request."""

    job_id: str
    pipeline_id: str
    status: JobStatus
    estimated_duration_seconds: int
    steps: list[PipelineExecutionStep]
    resource_snapshot: dict[str, PipelineResourceSnapshot]
    stream_url: str

class ThreadRequest(BaseModel):
    """Request to create a conversation thread."""
    title: str = Field(..., min_length=1, max_length=200)
    context: dict[str, Any] | None = Field(default_factory=dict)
    metadata: dict[str, Any] | None = Field(default_factory=dict)
    scenario_id: str | None = Field(
        default=None,
        description="Optional chat scenario identifier for specialized prompts."
    )

class FileUploadRequest(BaseModel):
    """File upload request with validation."""
    filename: str
    content_type: str
    size: int = Field(ge=0, le=100_000_000)  # 100MB limit

    @field_validator('content_type')
    @classmethod
    def validate_content_type(cls, v):
        """Validate allowed file types."""
        allowed_types = {
            'application/gzip',  # .nii.gz files
            'application/octet-stream',  # .nii files
            'text/csv',  # .csv files
            'application/json',  # .json files
            'application/pdf',  # .pdf files
            'text/plain',  # .txt files
        }
        if v not in allowed_types:
            raise ValueError(f'File type {v} not allowed. Allowed types: {allowed_types}')
        return v

    @field_validator('size')
    @classmethod
    def validate_size_by_type(cls, v, info):
        """Validate size limits by file type."""
        content_type = info.data.get('content_type', '')

        if content_type in ['application/gzip', 'application/octet-stream']:
            # NIFTI files: 100MB limit
            if v > 100_000_000:
                raise ValueError('NIFTI files must be under 100MB')
        else:
            # Other files: 10MB limit
            if v > 10_000_000:
                raise ValueError('Non-NIFTI files must be under 10MB')
        return v

class FileUploadResponse(BaseModel):
    """File upload response with file info."""
    file_id: str
    filename: str
    size: int
    content_type: str
    url: str
    upload_complete: bool = True
    storage: str | None = None  # "local", "s3", "remote"
    path: str | None = None     # Local filesystem path (for internal use)
    checksum: str | None = None # SHA256 checksum (format: "sha256:hexdigest")

class MessageRequest(BaseModel):
    """Request to add a message to a thread."""
    content: str = Field(..., min_length=1, max_length=10000)
    attachments: list[FileAttachment] | None = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    scenario_id: str | None = Field(
        default=None,
        description="Optional chat scenario identifier for this turn."
    )

    @field_validator('attachments')
    @classmethod
    def validate_attachments(cls, v):
        """Validate attachment format and size."""
        total_size = sum(attachment.size for attachment in v)
        if total_size > 150_000_000:  # 150MB total limit
            raise ValueError('Total attachment size cannot exceed 150MB')
        return v

class DatasetSearchRequest(BaseModel):
    """Advanced dataset search request."""
    query: dict[str, Any]
    options: dict[str, Any] | None = Field(default_factory=dict)

    model_config = {
        "json_schema_extra": {
            "example": {
                "query": {
                    "text": "motor cortex activation",
                    "filters": {
                        "n_subjects": {"min": 15, "max": 50},
                        "modality": ["fMRI"],
                        "has_task": "motor"
                    }
                },
                "options": {
                    "include_similar": True,
                    "similarity_threshold": 0.7
                }
            }
        }
    }

# ============================================================================
# Response Models with Provenance
# ============================================================================

class TimingInfo(BaseModel):
    """Timing information for steps and jobs."""
    start_time: datetime
    end_time: datetime | None = None
    duration_ms: int | None = None

    @model_validator(mode='after')
    def calculate_duration(self):
        """Calculate duration if both times are present."""
        if self.start_time and self.end_time:
            self.duration_ms = int((self.end_time - self.start_time).total_seconds() * 1000)
        return self

class ProvenanceInfo(BaseModel):
    """Provenance tracking for reproducibility."""
    tool_version: str | None = None
    parameters_hash: str | None = None
    generated_by: str | None = None
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    environment: dict[str, str] | None = None

    @field_validator('parameters_hash')
    @classmethod
    def validate_hash(cls, v):
        """Ensure hash is valid format."""
        if v and not (len(v) == 32 or len(v) == 64):
            raise ValueError('Hash must be MD5 (32) or SHA256 (64) characters')
        return v

class JobStep(BaseModel):
    """Enhanced job step with provenance."""
    id: str = Field(..., pattern="^step_[a-zA-Z0-9_]+$")
    name: str
    tool: str
    args: dict[str, Any] = Field(default_factory=dict)
    status: StepStatus = StepStatus.PENDING
    preview: str | None = None
    timing: TimingInfo | None = None
    error: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    provenance: ProvenanceInfo | None = None
    retry_count: int = 0
    max_retries: int = 3
    violations: list[Violation] = Field(
        default_factory=list,
        description="Structured violations raised during preflight/execute/postcheck",
    )

class JobArtifact(BaseModel):
    """Enhanced artifact with metadata and provenance."""
    id: str = Field(..., pattern="^artifact_[a-zA-Z0-9_]+$")
    type: ArtifactType
    name: str
    url: str
    meta: dict[str, Any] | None = Field(default_factory=dict)
    size_bytes: int | None = None
    checksum: str | None = None
    provenance: ProvenanceInfo | None = None
    annotations: list[dict[str, Any]] = Field(default_factory=list)

    @field_validator('url')
    @classmethod
    def validate_url(cls, v):
        """Ensure URL is properly formatted."""
        if not v.startswith(('/api/', 'http://', 'https://')):
            raise ValueError('URL must be relative API path or absolute HTTP(S) URL')
        return v


class CacheMetadata(BaseModel):
    """Metadata for deterministic cache hits."""
    cache_key: str | None = None
    cache_hit: bool = False
    cached_run_id: str | None = None
    cache_timestamp: int | None = None

class ExecutionStepInfo(BaseModel):
    """Execution step information for Run Card."""
    id: str
    name: str
    tool: str
    args: dict[str, Any]
    status: StepStatus
    start_time: datetime
    end_time: datetime | None = None
    duration_ms: int | None = None
    logs: list[str] = Field(default_factory=list)


class JobLogEntry(BaseModel):
    """Structured log entry for long-running job execution."""

    message: str = Field(..., min_length=1)
    stream: Literal["stdout", "stderr", "info", "error", "debug"] = "stdout"
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    step_id: str | None = Field(
        default=None, pattern="^step_[a-zA-Z0-9_]+$"
    )
    sequence: int | None = Field(default=None, ge=0)


class EnvironmentInfo(BaseModel):
    """Environment information for reproducibility."""
    platform: str
    python_version: str
    os_version: str
    memory_gb: float
    cpu_cores: int
    gpu_info: str | None = None
    container_image: str | None = None
    environment_variables: dict[str, str] = Field(default_factory=dict)

class ResourceUsage(BaseModel):
    """Resource usage during execution."""
    peak_memory_mb: float
    cpu_time_seconds: float
    gpu_time_seconds: float | None = None
    disk_io_mb: float | None = None
    network_io_mb: float | None = None

class DatasetInfo(BaseModel):
    """Dataset information for Run Card."""
    id: str
    name: str
    source: str
    version: str | None = None
    n_subjects: int | None = None
    n_sessions: int | None = None
    tasks: list[str] = Field(default_factory=list)
    checksum: str | None = None
    bids_version: str | None = None

class ToolInfo(BaseModel):
    """Tool information with version and citation."""
    name: str
    version: str
    citation: str | None = None
    doi: str | None = None
    url: str | None = None
    checksum: str | None = None

class ArtifactInfo(BaseModel):
    """Artifact information for Run Card."""
    id: str
    name: str
    type: ArtifactType
    path: str
    size_bytes: int
    checksum: str
    description: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

class CitationInfo(BaseModel):
    """Enhanced citation information."""
    id: str
    type: str  # 'dataset', 'tool', 'method', 'reference'
    title: str
    authors: list[str]
    year: int | None = None
    journal: str | None = None
    doi: str | None = None
    url: str | None = None
    bibtex: str | None = None

# Canonical RunCard contract (P0/M0): orchestrator should not define its own.
RunCard = RunCardV1

class ProvenanceGraph(BaseModel):
    """Provenance graph for tracking data lineage."""
    nodes: list[dict[str, Any]]
    edges: list[dict[str, Any]]

    @field_validator('edges')
    @classmethod
    def validate_edges(cls, v, info):
        """Ensure edges reference valid nodes."""
        if 'nodes' in info.data:
            node_ids = {node['id'] for node in info.data['nodes']}
            for edge in v:
                if edge['source'] not in node_ids or edge['target'] not in node_ids:
                    raise ValueError('Edge references non-existent node')
        return v

class JobProgress(BaseModel):
    """Detailed job progress information."""
    percentage: float = Field(ge=0, le=100)
    current_step: int = Field(ge=0)
    total_steps: int = Field(ge=1)
    estimated_remaining_seconds: int | None = None
    processing_rate: float | None = None  # items/second
    last_update: datetime = Field(default_factory=datetime.utcnow)

class Job(BaseModel):
    """Enhanced job model with comprehensive tracking."""
    id: str = Field(..., pattern="^[a-zA-Z0-9_-]+$")
    status: JobStatus = JobStatus.PENDING
    prompt: str
    steps: list[JobStep] = Field(default_factory=list)
    artifacts: list[JobArtifact] = Field(default_factory=list)
    timing: TimingInfo
    progress: JobProgress | None = None
    error: ErrorResponse | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    plan_of_record: dict[str, Any] | None = None
    plan_events: list[dict[str, Any]] = Field(default_factory=list)
    por_token: str | None = None
    provenance_graph: ProvenanceGraph | None = None
    run_card: RunCard | None = None
    queue_position: int | None = None
    estimated_duration_seconds: int | None = None
    resource_usage: dict[str, Any] | None = None
    user_id: str | None = None  # For user-specific jobs
    session_id: str | None = None
    project_id: str | None = None
    attachments: list[FileAttachment] = Field(default_factory=list)  # File attachments for chat
    logs: list[JobLogEntry] = Field(default_factory=list)
    cache_metadata: CacheMetadata | None = None
    # Execution control metadata populated by the orchestrator backend
    worker_id: str | None = None
    lease_expires_at: datetime | None = None
    last_heartbeat: datetime | None = None
    attempt: int = 0
    max_attempts: int = 3
    gpu_count_required: int = 0
    gpu_type: str | None = None
    assigned_gpu_slots: list[int] = Field(default_factory=list)
    run_id: str | None = None
    run_dir: str | None = None
    provenance_path: str | None = None
    run_card_path: str | None = None  # Path to persisted RunCard JSON
    cancellation_requested: bool = False
    cancellation_reason: str | None = None

class JobResponse(BaseModel):
    """Response after creating a job."""
    job_id: str
    estimated_duration: int
    queue_position: int
    status_url: str
    stream_url: str
    # P0/M1: analysis is a first-class alias for the job (analysis_id == job_id).
    analysis_id: str | None = None
    analysis_url: str | None = None
    analysis_stream_url: str | None = None
    cached: bool | None = Field(default=False)
    cache_key: str | None = None

    model_config = {
        "json_schema_extra": {
            "example": {
                "job_id": "job_abc123",
                "estimated_duration": 90,
                "queue_position": 0,
                "status_url": "/jobs/job_abc123",
                "stream_url": "/jobs/job_abc123/stream",
                "analysis_id": "job_abc123",
                "analysis_url": "/api/analyses/job_abc123",
                "analysis_stream_url": "/api/analyses/job_abc123/stream",
            }
        }
    }

# ============================================================================
# Dataset Models
# ============================================================================

class DatasetMetadata(BaseModel):
    """Comprehensive dataset metadata."""
    authors: list[str] = Field(default_factory=list)
    publication_year: int | None = None
    doi: str | None = None
    license: str | None = None
    acknowledgements: str | None = None
    references: list[str] = Field(default_factory=list)
    keywords: list[str] = Field(default_factory=list)

class DatasetStatistics(BaseModel):
    """Statistical summary of dataset."""
    mean_age: float | None = None
    age_range: list[float] | None = None
    sex_distribution: dict[str, int] | None = None
    handedness: dict[str, int] | None = None

class Dataset(BaseModel):
    """Enhanced dataset model."""
    id: str = Field(..., pattern="^[a-zA-Z0-9_-]+$")
    name: str
    description: str
    source: DatasetSource
    url: str | None = None
    modality: list[Modality]
    n_subjects: int = Field(ge=1)
    n_sessions: int = Field(ge=1)
    tasks: list[str] = Field(default_factory=list)
    size_gb: float = Field(ge=0)
    has_derivatives: bool = False
    bids_version: str | None = None
    metadata: DatasetMetadata | None = None
    statistics: DatasetStatistics | None = None
    preview_images: list[str] = Field(default_factory=list)
    last_updated: datetime
    quality_score: float | None = Field(None, ge=0, le=1)

class DatasetSearchResponse(BaseModel):
    """Response for dataset search with facets."""
    datasets: list[Dataset]
    pagination: dict[str, Any]
    facets: dict[str, list[dict[str, Any]]]
    search_metadata: dict[str, Any] | None = None

# ============================================================================
# Thread and Message Models (UI-003)
# ============================================================================

class Thread(BaseModel):
    """Conversation thread model."""
    thread_id: str = Field(..., pattern="^thread_[a-zA-Z0-9]+$")
    title: str
    created_at: datetime
    updated_at: datetime
    message_count: int = 0
    context: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)
    scenario_id: str | None = None

class Message(BaseModel):
    """Chat message model."""
    id: str = Field(..., pattern="^msg_[a-zA-Z0-9]+$")
    thread_id: str
    role: str = Field(..., pattern="^(user|assistant|system)$")
    content: str
    timestamp: datetime
    job_id: str | None = None
    artifacts: list[str] = Field(default_factory=list)
    attachments: list[FileAttachment] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)

class MessageHistory(BaseModel):
    """Message history response."""
    messages: list[Message]
    has_more: bool
    cursor: str | None = None
    total_count: int

# ============================================================================
# Service Health Models
# ============================================================================

class ServiceHealth(BaseModel):
    """Individual service health status."""
    name: str
    status: str = Field(..., pattern="^(healthy|degraded|unhealthy|unavailable)$")
    latency_ms: int | None = None
    last_check: datetime = Field(default_factory=datetime.utcnow)
    error: str | None = None

class HealthResponse(BaseModel):
    """Overall system health response."""
    status: str = Field(..., pattern="^(healthy|degraded|unhealthy)$")
    services: dict[str, ServiceHealth]
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    uptime_seconds: int | None = None
    version: str = "0.1.0"

# ============================================================================
# Tool and Capability Models
# ============================================================================

class ToolParameter(BaseModel):
    """Tool parameter definition."""
    name: str
    type: str
    default: Any | None = None
    required: bool = False
    description: str | None = None
    constraints: dict[str, Any] | None = None

class Tool(BaseModel):
    """Analysis tool definition."""
    id: str
    name: str
    category: str
    description: str
    version: str
    parameters: list[ToolParameter]
    required_inputs: list[str]
    outputs: list[str]
    estimated_runtime: str
    citations: list[str] = Field(default_factory=list)
    examples: list[dict[str, Any]] = Field(default_factory=list)

class ToolsResponse(BaseModel):
    """Response for tools listing."""
    tools: list[Tool]
    categories: list[dict[str, Any]]
    total_count: int

# ============================================================================
# Retry and Timeout Configuration
# ============================================================================

class RetryConfig(SharedRetryConfig):
    """Retry configuration for service calls."""


class TimeoutConfig(SharedTimeoutConfig):
    """Timeout configuration for various operations."""

# ============================================================================
# Demo Mode Support (UI-002)
# ============================================================================

class DemoScenario(BaseModel):
    """Pre-configured demo scenario."""
    id: str
    name: str
    description: str
    prompt: str
    pipeline: PipelineType
    dataset_id: str
    parameters: dict[str, Any]
    cached_job_id: str
    execution_time_seconds: int
    artifacts: list[JobArtifact]

class DemoResponse(BaseModel):
    """Response for demo mode execution."""
    job_id: str
    is_cached: bool
    scenario: DemoScenario
    instant_artifacts: list[JobArtifact]

# ============================================================================
# Authentication Models (UI-011)
# ============================================================================

class UserRole(str, Enum):
    """User roles for authorization."""
    ADMIN = "admin"
    RESEARCHER = "researcher"
    VIEWER = "viewer"

class User(BaseModel):
    """User model for authentication with OAuth support."""
    id: str = Field(..., pattern="^user_[a-zA-Z0-9]+$")
    username: str = Field(..., min_length=3, max_length=50, pattern="^[a-zA-Z0-9_]+$")
    email: str = Field(..., pattern=r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$')
    full_name: str | None = Field(None, max_length=200)
    role: UserRole = UserRole.RESEARCHER
    is_active: bool = True
    created_at: datetime = Field(default_factory=datetime.utcnow)
    last_login: datetime | None = None
    avatar_url: str | None = None
    preferences: dict[str, Any] = Field(default_factory=dict)

    # OAuth fields
    auth_provider: str | None = Field(None, description="OAuth provider: google, microsoft, github, email, password")
    provider_account_id: str | None = Field(None, description="OAuth provider user ID")
    picture: str | None = Field(None, description="Profile picture from OAuth provider")

    # Organization info (from Microsoft)
    organization: str | None = Field(None, max_length=200)
    department: str | None = Field(None, max_length=200)
    job_title: str | None = Field(None, max_length=200)

    # GitHub info (for CI/CD)
    github_username: str | None = Field(None, max_length=100)
    github_token_scope: str | None = Field(None, description="OAuth scopes granted")

    # Password is optional for OAuth users
    hashed_password: str | None = Field(None, exclude=True)  # Never include in API responses

class LoginRequest(BaseModel):
    """Login request model."""
    username: str | None = Field(None, min_length=3, max_length=50)
    email: str | None = Field(
        None, pattern=r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$"
    )
    password: str = Field(..., min_length=6, max_length=128)
    remember_me: bool = False

    @model_validator(mode="after")
    def require_username_or_email(self):
        if not (self.username or self.email):
            raise ValueError("Either username or email is required")
        return self

class SignupRequest(BaseModel):
    """User registration request model."""
    username: str = Field(..., min_length=3, max_length=50, pattern="^[a-zA-Z0-9_]+$")
    email: str = Field(..., pattern=r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$')
    password: str = Field(..., min_length=6, max_length=128)
    full_name: str = Field(..., min_length=1, max_length=200)
    accept_terms: bool = True

    @field_validator('accept_terms')
    @classmethod
    def terms_must_be_accepted(cls, v):
        if not v:
            raise ValueError('Terms and conditions must be accepted')
        return v

class TokenResponse(BaseModel):
    """JWT token response model."""
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int  # seconds
    user: User

class PasswordResetRequest(BaseModel):
    """Password reset request model."""
    email: str = Field(..., pattern=r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$')

class PasswordResetConfirm(BaseModel):
    """Password reset confirmation model."""
    token: str = Field(..., min_length=32)
    new_password: str = Field(..., min_length=6, max_length=128)

class OAuthProvider(str, Enum):
    """Supported OAuth providers."""
    GOOGLE = "google"
    GITHUB = "github"
    ORCID = "orcid"

class OAuthRequest(BaseModel):
    """OAuth authentication request."""
    provider: OAuthProvider
    code: str
    state: str | None = None
    redirect_uri: str

# ============================================================================
# Notification Models (UI-026)
# ============================================================================

class NotificationType(str, Enum):
    """Types of notifications."""
    JOB_COMPLETE = "job_complete"
    JOB_FAILED = "job_failed"
    SYSTEM_ALERT = "system_alert"
    DATASET_AVAILABLE = "dataset_available"
    ANALYSIS_SHARED = "analysis_shared"
    MAINTENANCE = "maintenance"
    WELCOME = "welcome"

class NotificationPriority(str, Enum):
    """Notification priority levels."""
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    URGENT = "urgent"

class Notification(BaseModel):
    """Notification model."""
    id: str = Field(..., pattern="^notif_[a-zA-Z0-9]+$")
    user_id: str
    type: NotificationType
    priority: NotificationPriority = NotificationPriority.NORMAL
    title: str = Field(..., max_length=200)
    message: str = Field(..., max_length=1000)
    data: dict[str, Any] | None = Field(default_factory=dict)
    read: bool = False
    created_at: datetime = Field(default_factory=datetime.utcnow)
    read_at: datetime | None = None
    expires_at: datetime | None = None
    action_url: str | None = None
    action_text: str | None = None

class NotificationPreferences(BaseModel):
    """User notification preferences."""
    user_id: str
    email_notifications: bool = True
    push_notifications: bool = True
    job_completion: bool = True
    job_failure: bool = True
    system_alerts: bool = True
    dataset_updates: bool = False
    analysis_sharing: bool = True
    maintenance_notices: bool = True
    quiet_hours_start: str | None = Field(None, pattern=r'^([0-1]?[0-9]|2[0-3]):[0-5][0-9]$')
    quiet_hours_end: str | None = Field(None, pattern=r'^([0-1]?[0-9]|2[0-3]):[0-5][0-9]$')
    timezone: str = "UTC"

class NotificationMarkReadRequest(BaseModel):
    """Request to mark notifications as read."""
    notification_ids: list[str] = Field(..., min_length=1)

class NotificationListResponse(BaseModel):
    """Response for notification listing."""
    notifications: list[Notification]
    unread_count: int
    total_count: int
    has_more: bool
    cursor: str | None = None

# ============================================================================
# Enhanced Error Response (UI-013)
# ============================================================================

class ErrorContext(BaseModel):
    """Additional error context for debugging."""
    request_id: str | None = None
    user_id: str | None = None
    endpoint: str | None = None
    method: str | None = None
    user_agent: str | None = None
    ip_address: str | None = None

class ErrorResponse(BaseModel):
    """Enhanced standardized error response."""
    error: dict[str, Any] = Field(default_factory=dict)

    model_config = {
        "json_schema_extra": {
            "example": {
                "error": {
                    "code": "VALIDATION_ERROR",
                    "message": "Invalid parameter value",
                    "details": {
                        "field": "smoothing",
                        "constraint": "Must be between 0 and 12"
                    },
                    "context": {
                        "request_id": "req_abc123",
                        "endpoint": "/run"
                    },
                    "suggestions": [
                        "Check parameter ranges in documentation",
                        "Use demo mode for testing"
                    ],
                    "documentation_url": "https://docs.brain-researcher.ai/api/errors#validation",
                    "timestamp": "2024-01-01T00:00:00Z"
                }
            }
        }
    }

    @classmethod
    def create(
        cls,
        code: ErrorCode,
        message: str,
        details: dict | None = None,
        context: ErrorContext | None = None,
        suggestions: list[str] | None = None,
        include_stack_trace: bool = False,
        stack_trace: str | None = None
    ):
        """Enhanced factory method to create error response."""
        error_data = {
            "code": code.value,
            "message": message,
            "details": details or {},
            "timestamp": datetime.utcnow().isoformat() + "Z"
        }

        if context:
            error_data["context"] = context.model_dump()

        if suggestions:
            error_data["suggestions"] = suggestions

        if code in [ErrorCode.VALIDATION_ERROR, ErrorCode.INVALID_PARAMETER]:
            error_data["documentation_url"] = "https://docs.brain-researcher.ai/api/validation"
        elif code in [ErrorCode.SERVICE_UNAVAILABLE, ErrorCode.SERVICE_TIMEOUT]:
            error_data["documentation_url"] = "https://docs.brain-researcher.ai/api/services"

        # Include stack trace only in development mode
        if include_stack_trace and stack_trace:
            error_data["stack_trace"] = stack_trace

        return cls(error=error_data)

# ============================================================================
# Enhanced Job Progress (UI-014)
# ============================================================================

class LoadingState(str, Enum):
    """Loading state types."""
    IDLE = "idle"
    LOADING = "loading"
    SUCCESS = "success"
    ERROR = "error"
    CANCELLED = "cancelled"

# ============================================================================
# UI Configuration (UI-015)
# ============================================================================

class UIFeatureFlags(BaseModel):
    """Feature flags for UI components."""
    demo_mode: bool = True
    advanced_search: bool = True
    real_time_collaboration: bool = False
    experimental_features: bool = False
    debug_mode: bool = False

class UIConfiguration(BaseModel):
    """UI configuration response."""
    feature_flags: UIFeatureFlags
    pagination: dict[str, int] = Field(default_factory=lambda: {
        "default_page_size": 20,
        "max_page_size": 100,
        "mobile_page_size": 10
    })
    timeouts: dict[str, int] = Field(default_factory=lambda: {
        "api_timeout_ms": 30000,
        "upload_timeout_ms": 120000,
        "websocket_retry_ms": 5000
    })
    limits: dict[str, int] = Field(default_factory=lambda: {
        "max_prompt_length": 5000,
        "max_file_size_mb": 100,
        "max_concurrent_jobs": 5
    })
    theme: dict[str, Any] = Field(default_factory=lambda: {
        "default_theme": "light",
        "available_themes": ["light", "dark", "auto"]
    })

# ============================================================================
# UI Component Support Models
# ============================================================================

# UI-010: Navigation Header Models
class UserProfile(BaseModel):
    """User profile information for navigation header."""
    id: str
    username: str
    full_name: str | None = None
    avatar_url: str | None = None
    role: UserRole
    unread_notifications: int = 0
    last_activity: datetime | None = None

# UI-009: Search Autocomplete Models
class SearchSuggestion(BaseModel):
    """Search suggestion item."""
    text: str
    category: str  # "dataset", "analysis", "tool", "user"
    confidence: float = Field(ge=0, le=1)
    metadata: dict[str, Any] | None = Field(default_factory=dict)

class SearchSuggestionsResponse(BaseModel):
    """Search suggestions response."""
    suggestions: list[SearchSuggestion]
    query: str
    total_suggestions: int
    categories: list[str]

class TrendingSearchResponse(BaseModel):
    """Trending searches response."""
    trending: list[dict[str, Any]]
    period: str  # "hour", "day", "week"
    updated_at: datetime = Field(default_factory=datetime.utcnow)

class SearchHistoryResponse(BaseModel):
    """User search history response."""
    history: list[dict[str, Any]]
    total_count: int
    last_updated: datetime | None = None

# UI-008: Filter Sidebar Models
class FilterFacet(BaseModel):
    """Individual filter facet."""
    id: str
    name: str
    type: str  # "select", "range", "checkbox", "text"
    options: list[dict[str, Any]] = Field(default_factory=list)
    selected_values: list[str] = Field(default_factory=list)
    count: int | None = None
    enabled: bool = True

class FilterFacetsResponse(BaseModel):
    """Available filter facets response."""
    facets: list[FilterFacet]
    categories: list[str]
    total_items_count: int
    context: str | None = None  # "datasets", "analyses", "tools"

class FilterPreset(BaseModel):
    """Saved filter preset."""
    id: str
    name: str
    description: str | None = None
    filters: dict[str, Any]
    user_id: str
    is_public: bool = False
    created_at: datetime = Field(default_factory=datetime.utcnow)
    used_count: int = 0

class FilterPresetRequest(BaseModel):
    """Request to save filter preset."""
    name: str = Field(..., min_length=1, max_length=100)
    description: str | None = Field(None, max_length=500)
    filters: dict[str, Any]
    is_public: bool = False

# UI-002C: Trust Strip Models
class SystemMetrics(BaseModel):
    """System performance and trust metrics."""
    analyses_completed: int
    datasets_available: int
    active_users: int
    uptime_percentage: float = Field(ge=0, le=100)
    avg_response_time_ms: float
    success_rate_percentage: float = Field(ge=0, le=100)
    last_updated: datetime = Field(default_factory=datetime.utcnow)

class SystemUptime(BaseModel):
    """System uptime information."""
    current_uptime_seconds: int
    uptime_percentage_24h: float
    uptime_percentage_7d: float
    uptime_percentage_30d: float
    last_downtime: datetime | None = None
    downtime_duration_seconds: int | None = None
    maintenance_scheduled: datetime | None = None

class Partner(BaseModel):
    """Institutional partner information."""
    id: str
    name: str
    logo_url: str | None = None
    website_url: str | None = None
    description: str | None = None
    partnership_type: str  # "academic", "industry", "government", "nonprofit"
    active: bool = True
    featured: bool = False

# UI-002D: Demo Result Display Models
class DemoResultSummary(BaseModel):
    """Demo result summary information."""
    demo_id: str
    title: str
    description: str
    completion_time: datetime
    processing_time_seconds: float
    success: bool
    artifacts_count: int
    key_findings: list[str] = Field(default_factory=list)

class DemoArtifact(BaseModel):
    """Demo output artifact."""
    id: str
    name: str
    type: ArtifactType
    description: str | None = None
    file_path: str
    file_size_bytes: int | None = None
    preview_url: str | None = None
    download_url: str
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=datetime.utcnow)

class DemoShareLink(BaseModel):
    """Demo share link information."""
    share_id: str
    demo_id: str
    share_url: str
    expires_at: datetime | None = None
    view_count: int = 0
    created_at: datetime = Field(default_factory=datetime.utcnow)
    is_public: bool = True

class DemoShareRequest(BaseModel):
    """Request to create demo share link."""
    demo_id: str
    expires_in_hours: int | None = Field(None, ge=1, le=8760)  # Max 1 year
    is_public: bool = True
    include_artifacts: bool = True

class DemoCitation(BaseModel):
    """Citation information for demo."""
    id: str
    title: str
    authors: list[str]
    journal: str | None = None
    year: int | None = None
    doi: str | None = None
    url: str | None = None
    citation_type: str  # "dataset", "tool", "method", "reference"
    relevance_score: float | None = Field(None, ge=0, le=1)

class DemoCitationsResponse(BaseModel):
    """Demo citations response."""
    demo_id: str
    citations: list[DemoCitation]
    total_count: int
    categories: dict[str, int]  # Count by citation_type
    formatted_bibliography: str | None = None

# ============================================================================
# Dashboard Layout Models (UI-035)
# ============================================================================

class WidgetPositionModel(BaseModel):
    """Widget position and size configuration."""
    x: int = Field(ge=0)
    y: int = Field(ge=0)
    w: int = Field(ge=1, le=12)
    h: int = Field(ge=1, le=20)
    minW: int | None = Field(None, ge=1, le=12)
    minH: int | None = Field(None, ge=1, le=20)
    maxW: int | None = Field(None, ge=1, le=12)
    maxH: int | None = Field(None, ge=1, le=20)

class WidgetConfigModel(BaseModel):
    """Widget configuration options."""
    showHeader: bool = True
    refreshInterval: int = Field(default=30000, ge=1000, le=300000)
    autoRefresh: bool = True
    theme: str = "default"
    borderStyle: str = "default"
    showShadow: bool = True
    customCss: str | None = None
    customDataSource: str | None = None
    notes: str | None = None

    # Widget-specific configs
    showCompleted: bool | None = None
    maxJobs: int | None = Field(None, ge=5, le=50)
    maxResults: int | None = Field(None, ge=5, le=50)
    showThumbnails: bool | None = None
    groupByType: bool | None = None
    showGPU: bool | None = None
    showStorage: bool | None = None
    warningThreshold: int | None = Field(None, ge=50, le=95)
    chartType: str | None = None
    colorScheme: str | None = None
    showGrid: bool | None = None
    maxActivities: int | None = Field(None, ge=5, le=50)
    showAvatars: bool | None = None
    groupByUser: bool | None = None

class WidgetModel(BaseModel):
    """Dashboard widget model."""
    id: str = Field(..., pattern="^widget_[a-zA-Z0-9_]+$")
    type: str = Field(..., pattern="^[a-z_]+$")
    title: str = Field(..., min_length=1, max_length=200)
    position: WidgetPositionModel
    config: WidgetConfigModel = Field(default_factory=WidgetConfigModel)
    visible: bool = True
    locked: bool = False
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

class BreakpointLayoutModel(BaseModel):
    """Breakpoint-specific layout configuration."""
    lg: list[dict[str, Any]] = Field(default_factory=list)
    md: list[dict[str, Any]] = Field(default_factory=list)
    sm: list[dict[str, Any]] = Field(default_factory=list)
    xs: list[dict[str, Any]] = Field(default_factory=list)

class DashboardLayoutModel(BaseModel):
    """Complete dashboard layout configuration."""
    id: str = Field(..., pattern="^[a-zA-Z0-9_-]+$")
    name: str = Field(..., min_length=1, max_length=200)
    description: str | None = Field(None, max_length=500)
    widgets: list[WidgetModel] = Field(default_factory=list, max_length=20)
    breakpoints: BreakpointLayoutModel = Field(default_factory=BreakpointLayoutModel)
    isDefault: bool = False
    user_id: str | None = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    @field_validator('widgets')
    @classmethod
    def validate_widget_positions(cls, v):
        """Validate widget positions don't overlap."""
        positions = []
        for widget in v:
            if not widget.visible:
                continue
            pos = widget.position
            # Simple overlap detection for large grid
            for existing_pos in positions:
                if not (pos.x >= existing_pos['x'] + existing_pos['w'] or
                       existing_pos['x'] >= pos.x + pos.w or
                       pos.y >= existing_pos['y'] + existing_pos['h'] or
                       existing_pos['y'] >= pos.y + pos.h):
                    raise ValueError(f'Widget {widget.id} overlaps with another widget')
            positions.append({'x': pos.x, 'y': pos.y, 'w': pos.w, 'h': pos.h})
        return v

class DashboardLayoutRequest(BaseModel):
    """Request to create or update dashboard layout."""
    name: str = Field(..., min_length=1, max_length=200)
    description: str | None = Field(None, max_length=500)
    widgets: list[WidgetModel] = Field(default_factory=list, max_length=20)
    breakpoints: BreakpointLayoutModel = Field(default_factory=BreakpointLayoutModel)
    isDefault: bool = False

class DashboardLayoutListResponse(BaseModel):
    """Response for listing dashboard layouts."""
    layouts: list[DashboardLayoutModel]
    total_count: int
    user_layouts_count: int
    default_layout_id: str | None = None

class DashboardExportData(BaseModel):
    """Dashboard layout export data."""
    version: str = "1.0"
    exported_at: datetime = Field(default_factory=datetime.utcnow)
    layout: DashboardLayoutModel
    metadata: dict[str, Any] = Field(default_factory=dict)

# ============================================================================
# Export all models
# ============================================================================

__all__ = [
    # Enums
    'JobStatus', 'StepStatus', 'ErrorCode', 'ArtifactType', 'PipelineType',
    'DatasetSource', 'Modality', 'UserRole', 'NotificationType', 'NotificationPriority',
    'OAuthProvider', 'LoadingState',

    # Error handling
    'ErrorDetail', 'ErrorResponse', 'ErrorContext',

    # Request models
    'RunRequest', 'ThreadRequest', 'MessageRequest', 'DatasetSearchRequest',
    'FileAttachment', 'FileUploadRequest', 'FileUploadResponse',

    # Core models
    'TimingInfo', 'ProvenanceInfo', 'JobStep', 'JobArtifact', 'RunCard',
    'ProvenanceGraph', 'Job', 'JobResponse', 'JobProgress',

    # Dataset models
    'DatasetMetadata', 'DatasetStatistics', 'Dataset', 'DatasetSearchResponse',

    # Thread/Message models
    'Thread', 'Message', 'MessageHistory',

    # Health models
    'ServiceHealth', 'HealthResponse',

    # Tool models
    'ToolParameter', 'Tool', 'ToolsResponse',

    # Configuration
    'RetryConfig', 'TimeoutConfig', 'UIFeatureFlags', 'UIConfiguration',

    # Demo mode
    'DemoScenario', 'DemoResponse',

    # Authentication models
    'User', 'LoginRequest', 'SignupRequest', 'TokenResponse', 'PasswordResetRequest',
    'PasswordResetConfirm', 'OAuthRequest',

    # Notification models
    'Notification', 'NotificationPreferences', 'NotificationMarkReadRequest',
    'NotificationListResponse',

    # UI Component Support Models
    'UserProfile', 'SearchSuggestion', 'SearchSuggestionsResponse', 'TrendingSearchResponse',
    'SearchHistoryResponse', 'FilterFacet', 'FilterFacetsResponse', 'FilterPreset',
    'FilterPresetRequest', 'SystemMetrics', 'SystemUptime', 'Partner',
    'DemoResultSummary', 'DemoArtifact', 'DemoShareLink', 'DemoShareRequest',
    'DemoCitation', 'DemoCitationsResponse'
]
