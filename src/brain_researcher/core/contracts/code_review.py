"""Contracts for the domain-grounded code review layer."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

from brain_researcher.core.contracts.gate_rule import GateRule


class KGLookupSpec(BaseModel):
    """KG lookup specification for a review rule (activated in Phase 3)."""

    node_type: str
    property: str
    query_hint: str
    min_confidence: float = 0.5


def _coerce_review_context(source: Any) -> dict[str, Any]:
    """Return the first nested review_context found in a mapping-like source."""
    if not isinstance(source, dict):
        return {}

    review_context = source.get("review_context")
    if isinstance(review_context, dict):
        return dict(review_context)

    for key in ("review_contract", "analysis_bundle", "run_card"):
        nested = source.get(key)
        if isinstance(nested, dict):
            extracted = _coerce_review_context(nested)
            if extracted:
                return extracted
    return {}


class ReviewRule(GateRule):
    """Extends GateRule with review-layer fields."""

    review_mode: Literal["plan", "artifact", "both"] = "plan"
    check_fn: str | None = Field(
        default=None,
        description=(
            "Dotted importlib path to a check function, e.g. "
            "'brain_researcher.services.review.checks.tool_order.registration_before_atlas_analysis'. "
            "Function signature: (bundle: CodeReviewBundle) -> ReviewFinding | None."
        ),
    )
    tool_filter: list[str] = Field(
        default_factory=list,
        description="Restrict metric-based check to steps whose tool matches any entry.",
    )
    kg_lookup: KGLookupSpec | None = Field(
        default=None,
        description="KG enrichment spec (Phase 3; ignored in Phase 1).",
    )


class CodeReviewBundle(BaseModel):
    """The unit of review — built from a plan or run artifacts, contains no agent CoT."""

    plan_steps: list[dict[str, Any]] = Field(
        default_factory=list,
        description="[{tool, params, step_id}] extracted from PlanStep — no CoT.",
    )
    declared_modalities: list[str] = Field(default_factory=list)
    declared_spaces: list[str] = Field(default_factory=list)
    workflow_id: str | None = None
    run_id: str | None = None
    review_context: dict[str, Any] = Field(
        default_factory=dict,
        description=(
            "Structured validity inputs for scientific review, e.g. split manifests, "
            "null models, preprocessing provenance, and claim support summaries."
        ),
    )
    # Phase 2: artifact-time fields
    observed_artifacts: dict[str, Any] = Field(default_factory=dict)
    stats_metrics: dict[str, Any] = Field(
        default_factory=dict,
        description=(
            "Scalar metrics extracted from run output files: "
            "mean_fd, scrubbing_fraction, r_squared, cohens_d_max, flag_rate, etc."
        ),
    )
    scorecard_snapshot: dict[str, Any] = Field(
        default_factory=dict,
        description=(
            "Infrastructure signals from run.json: "
            "step_success_rate, steps_total, steps_failed, artifact_completeness_ratio."
        ),
    )
    # Phase 3: KG enrichment
    kg_context: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _normalize_review_context(self) -> CodeReviewBundle:
        if not self.review_context:
            for source in (
                self.observed_artifacts,
                self.scorecard_snapshot,
                self.kg_context,
            ):
                review_context = _coerce_review_context(source)
                if review_context:
                    self.review_context = review_context
                    break
        return self


class ReviewFinding(BaseModel):
    """A single rule violation found during review."""

    rule_id: str
    severity: Literal["warn", "error", "critical"]
    action: Literal["block", "warn"] = "warn"
    message: str
    suggested_fix: str | None = None
    step_id: str | None = None
    artifact_name: str | None = None
    kg_evidence: list[str] = Field(default_factory=list)
    reason_tags: list[str] = Field(
        default_factory=list,
        description="Reason taxonomy attached to the finding, if any.",
    )
    novelty: str | None = Field(
        default=None,
        description="Optional novelty carve-out label attached to the finding.",
    )


class CodeReviewVerdict(BaseModel):
    """Final verdict produced by the review layer."""

    decision: Literal["approve", "approve_with_warnings", "revise", "block"]
    risk_level: Literal["low", "medium", "high", "critical"]
    findings: list[ReviewFinding] = Field(default_factory=list)
    kg_rules_consulted: list[str] = Field(default_factory=list)
    checklist_generated: list[str] = Field(
        default_factory=list,
        description="Checklist items generated from the bundle spec before rule evaluation.",
    )
    reviewer_rationale: str = ""


__all__ = [
    "CodeReviewBundle",
    "CodeReviewVerdict",
    "KGLookupSpec",
    "ReviewFinding",
    "ReviewRule",
    "ReviewMode",
]


ReviewMode = Literal["plan", "artifact"]
