"""Analysis bundle contract (v1).

An AnalysisBundle is the single "find everything for this run" document meant
for export/benchmark/replay. It is intentionally a superset that can embed
other run-level documents (observation, manifests, trajectory) while also
providing a stable file manifest with hashes.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

from .evaluation import EvaluationV1
from .execution_manifest import ExecutionManifestV1
from .ids import IdsV1
from .loop_signals import (
    CrossStageContextV1,
    LoopSignalRecordV1,
    coerce_cross_stage_context,
    parse_loop_signals,
)
from .observation import RMLogMetadataV1
from .policy_ref import PolicyRefV1, build_policy_ref_v1
from .version_ref import VersionRefV1, get_cached_version_ref_v1


class BundleFileEntry(BaseModel):
    """A single file entry in the bundle manifest."""

    role: str = Field(description="Semantic role, e.g. observation|trace|trajectory")
    path: str = Field(description="Path relative to run_dir when possible")
    size: int | None = Field(default=None, description="File size in bytes")

    checksum: str | None = Field(
        default=None, description="Checksum in the form sha256:<hex>"
    )
    checksum_status: str = Field(
        default="skipped", description="ok|missing|skipped|error"
    )
    checksum_reason: str | None = Field(default=None)

    mime: str | None = Field(default=None, description="Best-effort MIME type")


class AnalysisBundleFiles(BaseModel):
    """Well-known file references relative to `run_dir` when possible."""

    observation_json: str = Field(default="observation.json")
    inputs_manifest_json: str | None = None
    analysis_json: str | None = None
    artifact_manifest_json: str | None = None
    trace_jsonl: str | None = None
    trajectory_json: str | None = None
    provenance_json: str | None = None
    execution_manifest_json: str | None = None
    analysis_script_py: str | None = None
    run_script_sh: str | None = None
    requirements_txt: str | None = None
    environment_yml: str | None = None
    docker_compose_yml: str | None = None
    user_environment_yml: str | None = None
    user_docker_compose_yml: str | None = None
    user_env_example: str | None = None
    user_docs_index_md: str | None = None
    user_mcp_md: str | None = None
    user_operations_md: str | None = None
    user_quickstart_md: str | None = None
    user_installation_md: str | None = None
    reward_breakdown_json: str | None = None
    research_episode_json: str | None = None
    option_set_json: str | None = None
    evidence_gate_json: str | None = None
    commitment_json: str | None = None
    claim_report_json: str | None = None
    claim_update_json: str | None = None
    correction_summary_json: str | None = None
    threshold_summary_json: str | None = None
    thresholded_map: str | None = None
    design_matrix: str | None = None
    contrast_table: str | None = None
    cluster_table: str | None = None
    peak_table: str | None = None
    stdout_txt: str | None = None
    stderr_txt: str | None = None
    rm_pairwise_redacted_json: str | None = None
    rm_pairwise_raw_json: str | None = None
    rm_process_redacted_json: str | None = None
    rm_process_raw_json: str | None = None


class AnalysisBundleV1(BaseModel):
    """Single-document bundle for a run (v1)."""

    schema_version: Literal["analysis-bundle-v1"] = "analysis-bundle-v1"

    # M0 primitives (first-class; stable envelope)
    ids: IdsV1 = Field(default_factory=IdsV1)
    policy: PolicyRefV1 = Field(default_factory=build_policy_ref_v1)
    versions: VersionRefV1 = Field(default_factory=get_cached_version_ref_v1)

    job_id: str | None = None
    run_id: str | None = None
    state: str | None = None

    created_at: int | None = None
    started_at: int | None = None
    finished_at: int | None = None

    run_dir: str | None = None
    generated_at: str = Field(description="UTC ISO8601 timestamp")
    evidence_index: list[str] = Field(default_factory=list)
    qc_summary_ref: str | None = None
    source_manifests: list[str] = Field(default_factory=list)

    files: AnalysisBundleFiles = Field(default_factory=AnalysisBundleFiles)
    file_manifest: list[BundleFileEntry] = Field(default_factory=list)

    # Embedded docs (best-effort; omitted if missing/unparseable).
    observation: dict[str, Any] | None = None
    inputs_manifest: dict[str, Any] | None = None
    analysis_manifest: dict[str, Any] | None = None
    artifact_manifest: dict[str, Any] | None = None
    execution_manifest: ExecutionManifestV1 | dict[str, Any] | None = None
    reward_breakdown: dict[str, Any] | None = None
    trajectory: dict[str, Any] | None = None

    # Convenience copies for benchmark consumers.
    artifacts: list[dict[str, Any]] = Field(default_factory=list)
    run_card: dict[str, Any] | None = None
    review_context: dict[str, Any] = Field(
        default_factory=dict,
        description=(
            "Structured scientific validity context: split manifests, null models, "
            "confounds, preprocessing provenance, and other review-only inputs."
        ),
    )
    provenance: dict[str, Any] | None = None
    cross_stage_context: CrossStageContextV1 | dict[str, Any] | None = None
    loop_signals: list[LoopSignalRecordV1] = Field(default_factory=list)

    # Benchmark/evaluation payloads (optional; namespaced to avoid polluting product fields).
    evaluation: EvaluationV1 | dict[str, Any] | None = None

    # Execution/policy metadata (best-effort).
    policy_snapshot: dict[str, Any] | None = None

    # Optional redact+raw-vault RM logs.
    rm_pairwise: RMLogMetadataV1 | dict[str, Any] | None = None
    rm_process: RMLogMetadataV1 | dict[str, Any] | None = None

    @model_validator(mode="after")
    def _backfill_ids(self) -> AnalysisBundleV1:
        if self.ids.job_id is None and self.job_id:
            self.ids.job_id = self.job_id
        if self.ids.run_id is None and self.run_id:
            self.ids.run_id = self.run_id
        if self.ids.analysis_id is None and self.ids.job_id:
            self.ids.analysis_id = self.ids.job_id
        return self

    @model_validator(mode="after")
    def _normalize_loop_contracts(self) -> AnalysisBundleV1:
        if self.cross_stage_context is None and isinstance(self.run_card, dict):
            self.cross_stage_context = self.run_card.get("cross_stage_context")
        if (not self.loop_signals) and isinstance(self.run_card, dict):
            self.loop_signals = self.run_card.get("loop_signals") or []

        context = coerce_cross_stage_context(self.cross_stage_context)
        self.cross_stage_context = context.model_dump() if context else None
        self.loop_signals = parse_loop_signals(self.loop_signals)
        return self

    @model_validator(mode="after")
    def _normalize_review_context(self) -> AnalysisBundleV1:
        if not self.review_context and isinstance(self.run_card, dict):
            review_context = self.run_card.get("review_context")
            if isinstance(review_context, dict):
                self.review_context = dict(review_context)
        return self


__all__ = ["AnalysisBundleV1", "AnalysisBundleFiles", "BundleFileEntry"]
