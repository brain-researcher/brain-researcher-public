"""Scientific episode contract (v1).

This module captures a research episode as a stable, serializable contract that
tracks options, evidence gating, commitments, and claim evolution.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

from .claim import ClaimV1
from .epistemic import ClaimVerdictV1


class EpisodeOptionV1(BaseModel):
    """A single research option considered during an episode."""

    option_id: str = Field(description="Stable id for the option within the episode")
    label: str = Field(description="Short human-readable option label")
    rationale: str | None = Field(
        default=None, description="Why this option is being considered"
    )
    expected_impact: str | None = Field(
        default=None, description="Expected scientific or operational impact"
    )
    risks: list[str] = Field(
        default_factory=list, description="Known risks or failure modes"
    )
    prerequisites: list[str] = Field(
        default_factory=list, description="Requirements that should hold first"
    )
    confidence: float | None = Field(
        default=None, description="Optional confidence score in [0, 1]"
    )
    extra: dict[str, Any] = Field(default_factory=dict)


class OptionSetV1(BaseModel):
    """Candidate options for an episode plus the selected option, if any."""

    schema_version: Literal["option-set-v1"] = "option-set-v1"

    options: list[EpisodeOptionV1] = Field(default_factory=list)
    selected_option_id: str | None = Field(
        default=None, description="option_id of the selected option"
    )
    selection_rationale: str | None = Field(
        default=None, description="Why the selected option was chosen"
    )
    extra: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _validate_selected_option(self) -> OptionSetV1:
        if self.selected_option_id is None:
            return self
        option_ids = {option.option_id for option in self.options}
        if self.selected_option_id not in option_ids:
            raise ValueError(
                "selected_option_id must match one of the option_ids in options"
            )
        return self


class EvidenceGateVerdictV1(BaseModel):
    """Verdict produced by the evidence gate for an episode."""

    schema_version: Literal["evidence-gate-verdict-v1"] = "evidence-gate-verdict-v1"

    decision: Literal["go", "collect_more", "stop"] = "collect_more"
    summary: str | None = Field(default=None, description="Short verdict summary")
    required_evidence_ids: list[str] = Field(default_factory=list)
    supporting_evidence_ids: list[str] = Field(default_factory=list)
    missing_evidence_ids: list[str] = Field(default_factory=list)
    blockers: list[str] = Field(default_factory=list)
    confidence: float | None = Field(
        default=None, description="Optional confidence score in [0, 1]"
    )
    extra: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _validate_confidence(self) -> EvidenceGateVerdictV1:
        if self.confidence is None:
            return self
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("confidence must be in [0, 1]")
        return self


class CommitmentRecordV1(BaseModel):
    """A commitment made during the episode."""

    schema_version: Literal["commitment-record-v1"] = "commitment-record-v1"

    commitment_id: str = Field(
        description="Stable id for the commitment within the episode"
    )
    option_id: str | None = Field(
        default=None, description="Option that motivated the commitment"
    )
    claim_id: str | None = Field(
        default=None, description="Claim that this commitment supports"
    )
    commitment_text: str = Field(description="Human-readable commitment statement")
    approval_level: str | None = Field(
        default=None, description="Approval level attached to this commitment"
    )
    approved_by: str | None = Field(
        default=None, description="Human or subsystem that approved the commitment"
    )
    allowed_tools: list[str] = Field(
        default_factory=list, description="Tools allowed under this commitment"
    )
    run_mode_hint: str | None = Field(
        default=None, description="Execution mode implied by this commitment"
    )
    budget_envelope: dict[str, Any] = Field(
        default_factory=dict, description="Optional budget or cost envelope"
    )
    stop_conditions: list[str] = Field(
        default_factory=list, description="Explicit stop conditions for this commitment"
    )
    committed_at: str | None = Field(
        default=None, description="UTC ISO-8601 timestamp when the commitment was made"
    )
    fulfilled: bool = False
    fulfilled_at: str | None = Field(
        default=None, description="UTC ISO-8601 timestamp when the commitment was met"
    )
    owner: str | None = Field(default=None, description="Who owns the commitment")
    extra: dict[str, Any] = Field(default_factory=dict)


class ClaimReportV1(BaseModel):
    """Episode-level claim report."""

    schema_version: Literal["claim-report-v1"] = "claim-report-v1"

    report_id: str | None = Field(default=None, description="Stable id for the report")
    episode_id: str | None = Field(
        default=None, description="Episode this report belongs to"
    )
    claims: list[ClaimV1] = Field(default_factory=list)
    evidence_ids: list[str] = Field(
        default_factory=list, description="Evidence ids referenced by the report"
    )
    summary: str | None = Field(default=None, description="Narrative summary")
    overall_verdict: ClaimVerdictV1 | None = Field(
        default=None, description="Aggregate verdict for the report"
    )
    caveats: list[str] = Field(default_factory=list)
    unresolved_questions: list[str] = Field(default_factory=list)
    scientific_review_overall_decision: str | None = Field(
        default=None,
        description="Overall scientific review decision associated with this report",
    )
    extra: dict[str, Any] = Field(default_factory=dict)


class ClaimUpdateV1(BaseModel):
    """Incremental update to a claim."""

    schema_version: Literal["claim-update-v1"] = "claim-update-v1"

    claim_id: str = Field(description="Claim being updated")
    canonical_claim_id: str | None = Field(
        default=None, description="Canonical claim identifier if available"
    )
    action: Literal["support", "weaken", "refute", "supersede"] = "support"
    claim_text: str | None = Field(default=None, description="Updated claim text")
    verdict: ClaimVerdictV1 | None = Field(
        default=None, description="Updated claim verdict"
    )
    confidence: float | None = Field(
        default=None, description="Optional confidence score in [0, 1]"
    )
    evidence_ids: list[str] = Field(
        default_factory=list, description="Evidence ids supporting the update"
    )
    supersedes_claim_id: str | None = Field(
        default=None, description="Claim id superseded by this update, if any"
    )
    rationale: str | None = Field(
        default=None, description="Why this update action was chosen"
    )
    note: str | None = Field(default=None, description="Notes about the update")
    updated_at: str | None = Field(
        default=None, description="UTC ISO-8601 timestamp when the update was made"
    )
    extra: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _validate_confidence(self) -> ClaimUpdateV1:
        if self.confidence is None:
            return self
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("confidence must be in [0, 1]")
        return self


class ResearchEpisodeV1(BaseModel):
    """Top-level scientific episode contract."""

    schema_version: Literal["research-episode-v1"] = "research-episode-v1"

    episode_id: str = Field(description="Stable episode id")
    run_id: str | None = Field(default=None, description="Owning run id")
    session_id: str | None = Field(default=None, description="Owning session id")
    title: str | None = Field(default=None, description="Episode title")
    research_question: str | None = Field(
        default=None, description="Question this episode is trying to answer"
    )
    objective: str | None = Field(
        default=None, description="Primary research objective for the episode"
    )
    estimand: str | None = Field(
        default=None, description="What exactly is being estimated or decided"
    )
    success_criteria: list[str] = Field(
        default_factory=list, description="Episode-level success criteria"
    )
    stop_conditions: list[str] = Field(
        default_factory=list, description="Conditions under which the episode stops"
    )
    status: Literal["draft", "active", "completed", "archived"] = "draft"
    created_at: str | None = Field(
        default=None, description="UTC ISO-8601 timestamp when the episode started"
    )
    updated_at: str | None = Field(
        default=None, description="UTC ISO-8601 timestamp when the episode changed"
    )

    option_set: OptionSetV1 | None = Field(
        default=None, description="Candidate option set for the episode"
    )
    evidence_gate: EvidenceGateVerdictV1 | None = Field(
        default=None, description="Evidence gate verdict for the episode"
    )
    commitments: list[CommitmentRecordV1] = Field(default_factory=list)
    claim_report: ClaimReportV1 | None = Field(
        default=None, description="Episode-level claim report"
    )
    claim_updates: list[ClaimUpdateV1] = Field(default_factory=list)
    context: dict[str, Any] = Field(
        default_factory=dict, description="Free-form episode context"
    )
    extra: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _validate_option_linkage(self) -> ResearchEpisodeV1:
        if (
            self.option_set is not None
            and self.option_set.selected_option_id is not None
        ):
            option_ids = {option.option_id for option in self.option_set.options}
            if self.option_set.selected_option_id not in option_ids:
                raise ValueError(
                    "option_set.selected_option_id must refer to one of the option ids"
                )

        if self.claim_report is not None and self.claim_report.episode_id is None:
            self.claim_report.episode_id = self.episode_id

        return self


__all__ = [
    "ClaimReportV1",
    "ClaimUpdateV1",
    "CommitmentRecordV1",
    "EpisodeOptionV1",
    "EvidenceGateVerdictV1",
    "OptionSetV1",
    "ResearchEpisodeV1",
]
