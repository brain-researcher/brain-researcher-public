"""Canonical observation spec (v1).

This contract is intended to unify run-level "what happened" data for:
- UI Evidence Rail
- Export/audit bundles
- Training/trace extraction

The initial version is a pragmatic wrapper that can embed legacy payloads
(runcard/provenance) while providing stable top-level identifiers and file refs.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

from .ids import IdsV1
from .policy_ref import PolicyRefV1, build_policy_ref_v1
from .run_card import RunCardV1
from .version_ref import VersionRefV1, get_cached_version_ref_v1


class RMLogMetadataV1(BaseModel):
    """Optional metadata for redact+raw-vault RM logs."""

    schema_version: Literal["rm-log-metadata-v1"] = "rm-log-metadata-v1"
    policy: str = Field(default="redact+raw-vault")
    redacted_json: str | None = Field(default=None)
    raw_json: str | None = Field(default=None)
    redacted_checksum: str | None = Field(default=None)
    raw_checksum: str | None = Field(default=None)
    redacted_checksum_status: str | None = Field(default=None)
    raw_checksum_status: str | None = Field(default=None)
    redacted_checksum_reason: str | None = Field(default=None)
    raw_checksum_reason: str | None = Field(default=None)
    generated_at: str | None = Field(default=None)
    metadata: dict[str, Any] | None = None


class ObservationFiles(BaseModel):
    """File references relative to `run_dir` when possible."""

    observation_json: str = Field(default="observation.json")
    analysis_json: str | None = None
    provenance_json: str | None = None
    trace_jsonl: str | None = None
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
    rm_pairwise_redacted_json: str | None = None
    rm_pairwise_raw_json: str | None = None
    rm_process_redacted_json: str | None = None
    rm_process_raw_json: str | None = None


class ObservationSpecV1(BaseModel):
    """Canonical observation document (v1)."""

    schema_version: Literal["observation-v1"] = "observation-v1"

    # M0 primitives (first-class; stable envelope)
    ids: IdsV1 = Field(default_factory=IdsV1)
    policy: PolicyRefV1 = Field(default_factory=build_policy_ref_v1)
    versions: VersionRefV1 = Field(default_factory=get_cached_version_ref_v1)

    job_id: str
    run_id: str | None = None
    round_id: str | None = None
    state: str

    created_at: int | None = None
    started_at: int | None = None
    finished_at: int | None = None

    run_dir: str | None = None
    files: ObservationFiles = Field(default_factory=ObservationFiles)
    inputs_manifest_ref: str | None = None
    failure_summary: str | None = None

    # Embedded legacy payloads (best-effort, may be absent on partial runs).
    run_card: RunCardV1 | dict[str, Any] | None = None
    provenance: dict[str, Any] | None = None

    # Convenience views used by UI (best-effort).
    artifacts: list[dict[str, Any]] = Field(default_factory=list)
    steps: list[dict[str, Any]] = Field(default_factory=list)
    violations: list[dict[str, Any]] | None = None

    # Run-level diagnostic summary (best-effort).
    diagnostics_summary: dict[str, Any] | None = None

    # Optional redact+raw-vault RM logs.
    rm_pairwise: RMLogMetadataV1 | dict[str, Any] | None = None
    rm_process: RMLogMetadataV1 | dict[str, Any] | None = None

    @model_validator(mode="after")
    def _backfill_ids(self) -> ObservationSpecV1:
        if self.ids.job_id is None:
            self.ids.job_id = self.job_id
        if self.ids.run_id is None and self.run_id:
            self.ids.run_id = self.run_id
        if self.ids.analysis_id is None:
            self.ids.analysis_id = self.job_id
        return self


__all__ = ["RMLogMetadataV1", "ObservationSpecV1", "ObservationFiles"]
