"""Gate rule contract for QC/validation gates."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class GateRule(BaseModel):
    """Declarative rule used by the gate engine."""

    schema_version: Literal["gate-rule-v1"] = "gate-rule-v1"

    rule_id: str = Field(..., description="Unique rule identifier, e.g., QC_MISSING_T1W")
    description: str = Field(..., description="Human-readable summary")

    applies_to: Literal["run", "step", "artifact", "plan"] = Field(
        default="step", description="Scope where this rule applies"
    )
    stage: Literal["preflight", "postcheck", "plan_review", "artifact_review"] = Field(
        default="postcheck", description="Execution phase where the rule runs"
    )

    metric: str = Field(
        ...,
        description=(
            "Dot-notation path inside evaluation context (e.g., "
            "'qc.motion.mean_fd', 'fmriprep.inputs.t1w_present')."
        ),
    )
    comparator: Literal["lt", "lte", "gt", "gte", "eq", "ne", "contains", "missing"] = (
        "lt"
    )
    threshold: Any = Field(
        default=None,
        description="Comparison target. Ignored for 'missing' comparator.",
    )

    severity: Literal["warn", "error", "critical"] = "error"
    action: Literal["block", "warn"] = "block"

    message: str = Field(..., description="Message shown to users")
    suggested_fix: str | None = Field(default=None, description="How to remediate")
    tags: list[str] = Field(default_factory=list)
    reason_tags: list[str] = Field(
        default_factory=list,
        description=(
            "Reason taxonomy for review findings, e.g. leakage|circularity|confound|"
            "null_mismatch|claim_inflation."
        ),
    )
    novelty: str | None = Field(
        default=None,
        description=(
            "Optional novelty carve-out label for cases that are methodologically "
            "sound but conflict with field priors."
        ),
    )


__all__ = ["GateRule"]
