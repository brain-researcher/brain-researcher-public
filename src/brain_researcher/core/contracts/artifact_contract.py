"""Artifact contract specifications and profile selection.

Pure, dependency-light contract definitions for run-bundle artifacts. These live
in ``core/contracts`` so that both ``core/artifact_validator`` (which layers
``Violation``-based validation on top) and review-contract synthesis in
``core/contracts/native_review_contract`` can depend on the specs without
creating a ``core/contracts -> core/artifact_validator`` import cycle.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

MissingArtifactPolicy = Literal["fail", "degraded", "still_evaluable"]
ArtifactFormat = Literal["json_object", "jsonl_objects"]


@dataclass(frozen=True)
class ArtifactContractSpec:
    filename: str
    component: str
    code_suffix: str
    required: bool
    missing_policy: MissingArtifactPolicy
    artifact_format: ArtifactFormat
    minimum_contract: str
    description: str


CORE_RUN_ARTIFACT_COMPONENTS: dict[str, str] = {
    "trace_jsonl": "trace.jsonl",
    "provenance_json": "provenance.json",
    "trajectory_json": "trajectory.json",
    "observation_json": "observation.json",
    "analysis_bundle_json": "analysis_bundle.json",
}

_CORE_RUN_BUNDLE_CONTRACT: tuple[ArtifactContractSpec, ...] = (
    ArtifactContractSpec(
        filename="trace.jsonl",
        component="trace_jsonl",
        code_suffix="TRACE",
        required=True,
        missing_policy="degraded",
        artifact_format="jsonl_objects",
        minimum_contract="Non-empty JSONL file with one JSON object per event line.",
        description=(
            "Append-only event stream used for replay, analytics, and debugging. "
            "Missing trace keeps the run reviewable only with degraded traceability."
        ),
    ),
    ArtifactContractSpec(
        filename="provenance.json",
        component="provenance_json",
        code_suffix="PROVENANCE",
        required=True,
        missing_policy="degraded",
        artifact_format="json_object",
        minimum_contract="Non-empty JSON object with run/tool lineage metadata.",
        description=(
            "Execution lineage and environment evidence. Missing provenance keeps "
            "the run reviewable only with degraded auditability."
        ),
    ),
    ArtifactContractSpec(
        filename="trajectory.json",
        component="trajectory_json",
        code_suffix="TRAJECTORY",
        required=True,
        missing_policy="degraded",
        artifact_format="json_object",
        minimum_contract="Non-empty JSON object, preferably ATIF-v1.4.",
        description=(
            "Agent trajectory for replay and loop analysis. Missing trajectory "
            "keeps the run reviewable only with degraded replayability."
        ),
    ),
    ArtifactContractSpec(
        filename="observation.json",
        component="observation_json",
        code_suffix="OBSERVATION",
        required=True,
        missing_policy="fail",
        artifact_format="json_object",
        minimum_contract="Non-empty observation-v1 JSON object.",
        description=(
            "Canonical per-run observation carrier for UI, review, export, and "
            "diagnostics. Missing observation makes the run bundle non-evaluable."
        ),
    ),
    ArtifactContractSpec(
        filename="analysis_bundle.json",
        component="analysis_bundle_json",
        code_suffix="ANALYSIS_BUNDLE",
        required=True,
        missing_policy="fail",
        artifact_format="json_object",
        minimum_contract="Non-empty analysis-bundle-v1 JSON object.",
        description=(
            "Top-level bundle index and review context. Missing analysis bundle "
            "makes the run bundle non-evaluable."
        ),
    ),
)

_EXTERNAL_REVIEW_BUNDLE_CONTRACT: tuple[ArtifactContractSpec, ...] = tuple(
    ArtifactContractSpec(
        filename=spec.filename,
        component=spec.component,
        code_suffix=spec.code_suffix,
        required=spec.filename in {"observation.json", "analysis_bundle.json"},
        missing_policy=(
            spec.missing_policy
            if spec.filename in {"observation.json", "analysis_bundle.json"}
            else "still_evaluable"
        ),
        artifact_format=spec.artifact_format,
        minimum_contract=spec.minimum_contract,
        description=spec.description,
    )
    for spec in _CORE_RUN_BUNDLE_CONTRACT
)


_ARTIFACT_CONTRACTS: dict[str, tuple[ArtifactContractSpec, ...]] = {
    "default": _CORE_RUN_BUNDLE_CONTRACT,
    "run_bundle": _CORE_RUN_BUNDLE_CONTRACT,
    "plan_execution": _CORE_RUN_BUNDLE_CONTRACT,
    "external_review_bundle": _EXTERNAL_REVIEW_BUNDLE_CONTRACT,
}


def _normalize_profile(job_profile: str) -> str:
    return job_profile if job_profile in _ARTIFACT_CONTRACTS else "default"


def artifact_contract_for_profile(job_profile: str) -> tuple[ArtifactContractSpec, ...]:
    """Return the artifact contract specs for a validator profile."""

    return _ARTIFACT_CONTRACTS[_normalize_profile(job_profile)]


def required_artifacts_for_profile(job_profile: str) -> tuple[str, ...]:
    """Return the required artifact filenames for a validator profile."""

    return tuple(
        spec.filename
        for spec in artifact_contract_for_profile(job_profile)
        if spec.required
    )


def optional_artifacts_for_profile(job_profile: str) -> tuple[str, ...]:
    """Return the optional artifact filenames for a validator profile."""

    return tuple(
        spec.filename
        for spec in artifact_contract_for_profile(job_profile)
        if not spec.required
    )


def infer_artifact_profile(
    *, job_kind: str | None, payload: dict[str, Any] | None
) -> str:
    """Infer which artifact contract profile should apply."""

    kind = (job_kind or "").strip().lower()
    if kind in {"plan", "dataset_analysis", "workflow", "pipeline"}:
        return "plan_execution"

    if isinstance(payload, dict):
        plan = payload.get("plan")
        if isinstance(plan, dict):
            steps = plan.get("steps")
            if isinstance(steps, list) and any(
                isinstance(step, dict) for step in steps
            ):
                return "plan_execution"

    return "default"
