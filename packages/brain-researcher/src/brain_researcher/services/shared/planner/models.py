"""Shared planning contract models used by Agent and Orchestrator."""

from __future__ import annotations

import secrets
import os
import logging
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional

from pydantic import (
    BaseModel,
    Field,
    field_validator,
    GetCoreSchemaHandler,
    model_validator,
)
from pydantic_core import core_schema
from brain_researcher.core.contracts import Violation

from .por_tokens import (
    get_por_token_secret,
    is_signed_por_token,
    issue_por_token_from_env,
    por_token_enforced,
)

logger = logging.getLogger(__name__)

Domain = Literal[
    "neuroimaging",
    "neurokg",
    "literature",
    "llm_service",
    "code_assistant",
    "neurogenetics",
    "clinical",
]
Modality = Literal[
    "fmri",
    "eeg",
    "meg",
    "ieeg",
    "dmri",
    "smri",
    "pet",
    "genetics",
    "multimodal",
    "optical",
    "clinical",
    "general",  # for non-neuro text/coding tasks
    "literature",
    "data_catalog",
    "rag",
    "search",
]
RuntimeKind = Literal["container", "python", "api", "neurodesk"]


def normalize_modality(value: str) -> str:
    """Normalize modality strings to canonical lowercase values with basic aliases."""
    if value is None:
        raise ValueError("Modality cannot be None")
    v = str(value).strip().lower()
    aliases = {
        "bold": "fmri",
        "structural": "smri",
        "anatomical": "smri",
        "diffusion": "dmri",
    }
    return aliases.get(v, v)


class ResourceType:
    """Resource type validation with optional YAML extensibility."""

    _ALIASES: Dict[str, str] = {
        "file_path": "file_paths",
        "file_paths": "file_paths",
        "coords": "coordinates",
        "coord_table": "coordinate_table",
        "study_id": "study_ids",
        "metric_json": "metrics_json",
        "metrics": "metrics_json",
        "report": "report_json",
        "sim_params": "simulation_parameters",
        "sim_results": "simulation_results",
        "nf_signal": "neurofeedback_signal",
    }
    _HARDCODED = frozenset(
        [
            "volume_3d",
            "volume_4d",
            "scalar",
            "matrix",
            "surface_mesh",
            "parcellation_labels",
            "mask_path",
            "timeseries",
            "connectivity_matrix",
            "spd_matrix",
            "stat_map",
            "raw_eeg",
            "clean_eeg",
            "epochs",
            "power_spectra",
            "montage",
            "events_tsv",
            "features_table",
            "contacts_mni",
            "bids_root",
            "subject_label",
            "bvals",
            "bvecs",
            "coord_table",
            "kg_nodes",
            "kg_edges",
            "report_html",
            "text_prompt",
            "text_completion",
            "text_context",
            "demo_payload",
            "llm_usage",
            "code_context",
            "code_diff",
            "genetics_data",
            "fused_representation",
            "pet_metrics",
            "optical_timeseries",
            "optical_metrics",
            "clinical_data",
            "risk_scores",
            "causal_graph",
            "nwb_file",
            "nwb_summary",
            "model_artifact",
            # text / catalog tooling
            "pubmed_query",
            "doi_list",
            "coordinate_table",
            "effect_sizes",
            "dataset_list",
            "resource_list",
            "dataset_ref",
            "dataset_resources",
            "bids_path",
            "search_query",
            "search_results",
            "file_chunks",
            "coordinates",
            "study_ids",
            "file_paths",
            "site_labels",
            "harmonized_data",
            "report_json",
            "simulation_parameters",
            "simulation_results",
            "roi_mask",
            "metrics_json",
            "neurofeedback_signal",
        ]
    )
    _ALLOWED = set(_HARDCODED)
    _YAML_LOADED = False

    @classmethod
    def normalize(cls, value: str) -> str:
        """Best-effort canonicalization using alias map; returns lowercase canonical."""
        if value is None:
            raise ValueError("Resource type cannot be None")
        v = str(value).strip()
        if not v:
            raise ValueError("Resource type cannot be empty")
        key = v.lower()
        if key in cls._ALIASES:
            return cls._ALIASES[key]
        return key

    @classmethod
    def validate(cls, value: str) -> str:
        canon = cls.normalize(value)
        if canon not in cls._ALLOWED:
            raise ValueError(f"Unknown resource type: {value}")
        return canon

    @classmethod
    def get_allowed(cls) -> set[str]:
        return set(cls._ALLOWED)

    @classmethod
    def load_from_yaml(cls, path: Optional[Path] = None) -> None:
        if path is None:
            from brain_researcher.config.paths import get_config_root
            path = get_config_root() / "tool_resources.yaml"
        try:
            exists = path.exists()
        except OSError as exc:
            # Some environments disallow probing certain directories (e.g., sandboxed /tmp).
            # Treat as "missing" and keep the hardcoded defaults.
            logger.warning(
                "Resource YAML not found at %s (%s), using hardcoded types",
                path,
                exc,
            )
            return
        if not exists:
            logger.warning("Resource YAML not found at %s, using hardcoded types", path)
            return
        try:
            import yaml  # optional dependency

            data = yaml.safe_load(path.read_text()) or {}
            yaml_types = {
                entry.get("name")
                for entry in data.get("resources", [])
                if entry.get("name")
            }
            cls._ALLOWED = set(cls._HARDCODED) | set(yaml_types)
            cls._YAML_LOADED = True
            logger.info("Loaded %d resource types from YAML", len(yaml_types))
        except Exception as exc:  # pragma: no cover
            logger.exception(
                "Failed to load resource YAML, using hardcoded types: %s", exc
            )
            cls._ALLOWED = set(cls._HARDCODED)
            cls._YAML_LOADED = False

    # Pydantic v2 compatibility: treat ResourceType as a validated string
    @classmethod
    def __get_pydantic_core_schema__(
        cls, _source_type: Any, _handler: GetCoreSchemaHandler
    ) -> core_schema.CoreSchema:
        return core_schema.no_info_plain_validator_function(cls.validate)


# Optionally load YAML at import-time
if os.environ.get("BR_RESOURCE_YAML_ENABLED", "true").lower() == "true":
    ResourceType.load_from_yaml()


class ArtifactSpec(BaseModel):
    """Artifact produced or consumed within a plan."""

    name: str
    rtype: str
    description: Optional[str] = None

    @field_validator("rtype")
    @classmethod
    def _validate_rtype(cls, v: str) -> str:
        return ResourceType.validate(v)


class StepSpec(BaseModel):
    """Single step in a plan DAG."""

    id: str
    tool: str
    consumes: Dict[str, str] = Field(default_factory=dict)
    produces: Dict[str, str] = Field(default_factory=dict)
    params: Dict[str, Any] = Field(default_factory=dict)
    metadata: Dict[str, Any] = Field(default_factory=dict)
    runtime_kind: RuntimeKind = Field(
        default="container",
        description="Execution backend: container (default), python, or api",
    )

    @field_validator("consumes", "produces", mode="before")
    @classmethod
    def _validate_resources(cls, v: Dict[str, str]) -> Dict[str, str]:
        validated = {}
        for key, val in (v or {}).items():
            validated[key] = ResourceType.validate(val)
        return validated


class ConstraintSpec(BaseModel):
    """Planner constraints enforced by the orchestrator."""

    tool_allowlist: Optional[List[str]] = None
    max_steps: Optional[int] = None
    max_cost_units: Optional[float] = None
    warnings: List[str] = Field(default_factory=list)


class PlanDAG(BaseModel):
    """Structured DAG representation shared between services."""

    steps: List[StepSpec]
    artifacts: List[ArtifactSpec] = Field(default_factory=list)


class Plan(BaseModel):
    """Planner response returned by the Agent."""

    plan_id: str
    version: int = 1
    schema_version: str = Field(
        default="1.0", description="Plan schema version for backward compatibility"
    )
    domain: Domain
    modality: List[Modality]
    resolvable: bool = True
    dag: PlanDAG
    estimates: Dict[str, float] = Field(default_factory=dict)
    warnings: List[str] = Field(default_factory=list)
    constraints: Optional[ConstraintSpec] = None
    allowlist_mode: Optional[Literal["curated", "diagnostic"]] = None
    # Signed POR token (issued by orchestrator; verified by agent before execution).
    # Falls back to an unsigned random token when BR_POR_TOKEN_SECRET is not set
    # and enforcement is disabled (dev mode).
    por_token: str = Field(default_factory=lambda: secrets.token_urlsafe(16))

    # P0-1: Selection reasoning (optional, populated by catalog-driven planner)
    # These fields provide transparency into the tool selection process
    intent: Optional[List[str]] = None  # Extracted intent operators from query
    predicted_capabilities: Optional[List[str]] = None  # Online predicted capabilities
    predicted_intents: Optional[List[str]] = None  # Online predicted intent signals
    capability_prediction: Optional[Dict[str, Any]] = None  # Predictor debug payload
    cross_stage_context: Optional[Dict[str, Any]] = (
        None  # Structured R1/R2/R3 constraints
    )
    loop_signals: Optional[List[Dict[str, Any]]] = (
        None  # Typed loop signals (JSON form)
    )
    candidates: Optional[List[Dict[str, Any]]] = None  # Ranked candidate metadata
    chosen_tool: Optional[str] = None  # Chosen tool ID (matches first step in DAG)
    selection_reason: Optional[str] = None  # Human-readable explanation of choice
    selection_reasons: Optional[List[Dict[str, Any]]] = (
        None  # Detailed scored reasons (optional, debug)
    )
    mask_reasons: Optional[List[Violation]] = (
        None  # Constraint/masking reasons (violations)
    )
    timestamp: Optional[int] = None  # Unix timestamp of plan generation
    mode: Optional[Literal["legacy", "catalog"]] = (
        None  # Planner mode used to generate this plan
    )
    # Planner trace + confidence (optional, for UI/analytics)
    planner_state: Optional[Dict[str, Any]] = None
    planner_events: Optional[List[Dict[str, Any]]] = None
    run_summary: Optional[Dict[str, Any]] = None
    plan_conf: Optional[float] = None
    confidence_score: Optional[float] = None
    routing_diagnostics: Optional[Dict[str, Any]] = None

    @model_validator(mode="after")
    def _ensure_signed_por_token(self) -> "Plan":
        """Ensure por_token is signed when the secret is configured."""
        if is_signed_por_token(self.por_token):
            return self
        if not get_por_token_secret():
            # Keep legacy unsigned token in development unless enforcement is enabled.
            if por_token_enforced():
                self.por_token = issue_por_token_from_env(
                    plan_id=self.plan_id, version=self.version
                )
            return self
        try:
            self.por_token = issue_por_token_from_env(
                plan_id=self.plan_id, version=self.version
            )
        except RuntimeError:
            raise
        except Exception as exc:  # pragma: no cover - best effort
            logger.debug("POR token signing skipped: %s", exc)
        return self


class PlanRequest(BaseModel):
    """Plan request sent from orchestrator to agent."""

    pipeline: str
    domain: Domain
    modality: List[Modality]
    inputs: Dict[str, str] = Field(default_factory=dict)
    constraints: Optional[ConstraintSpec] = None
    mode: Optional[Literal["catalog"]] = Field(
        None,
        description="Planner mode for active runtime requests. Only 'catalog' is supported; omitted requests default to catalog.",
    )
    allowlist_mode: Optional[Literal["curated", "diagnostic"]] = Field(
        None,
        description=(
            "Allowlist surface for planner selection. 'curated' keeps the default "
            "chat-safe surface; 'diagnostic' widens to the full catalog for "
            "benchmark routing analysis."
        ),
    )
    query_understanding: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Optional query understanding payload (datasets/KG/derivatives) forwarded to planner.",
    )


class RunPlanRequest(BaseModel):
    """Request body for POST /agent/run_plan."""

    plan_id: str
    version: int
    por_token: str
    plan: Optional[Plan] = Field(
        default=None,
        description=(
            "Optional committed plan payload. This lets orchestration surfaces "
            "submit an already-issued plan-of-record without depending on the "
            "Agent process-local /agent/plan cache."
        ),
    )


class PlanChange(BaseModel):
    """Formal change request that the agent can raise mid-run."""

    plan_id: str
    from_version: int
    to_version: int
    added_steps: List[StepSpec] = Field(default_factory=list)
    removed_step_ids: List[str] = Field(default_factory=list)
    reason: Optional[str] = None


class PORToken(BaseModel):
    """Immutable token recorded by the orchestrator when a POR is committed."""

    plan_id: str
    version: int
    token: str


__all__ = [
    "ArtifactSpec",
    "ConstraintSpec",
    "Domain",
    "Modality",
    "Plan",
    "PlanChange",
    "PlanDAG",
    "PlanRequest",
    "PORToken",
    "ResourceType",
    "RuntimeKind",
    "RunPlanRequest",
    "StepSpec",
    "Violation",
]
