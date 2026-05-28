"""Claim contract (v1).

Claims are structured, review-style findings extracted from source evidence.
Each claim references one or more evidence items by id.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from .epistemic import (
    ClaimScopeV1,
    ClaimVerdictV1,
    EpistemicConfidenceTierV1,
    EvidenceProvenanceV1,
)


class ClaimV1(BaseModel):
    schema_version: Literal["claim-v1"] = "claim-v1"

    claim_id: str = Field(description="Stable id for the claim within a run")
    claim_text: str = Field(description="Human-readable claim text")
    verdict: ClaimVerdictV1 | None = Field(
        default=None,
        description="Optional epistemic verdict label for the claim.",
    )
    confidence: float | None = Field(
        default=None, description="Optional confidence score in [0, 1]"
    )
    epistemic_confidence_tier: EpistemicConfidenceTierV1 | None = Field(
        default=None,
        description="Human-facing confidence tier derived from evidence strength.",
    )
    evidence_provenance: EvidenceProvenanceV1 | None = Field(
        default=None,
        description="Whether the claim is backed by direct evidence, cross-study inference, or theory only.",
    )
    claim_scope: ClaimScopeV1 | None = Field(
        default=None,
        description="Whether the claim is asserted within one study or across studies.",
    )
    raw_data_available: bool | None = Field(
        default=None,
        description="Whether claim support includes access to original data rather than literature summaries alone.",
    )
    direct_statistical_test: bool | None = Field(
        default=None,
        description="Whether the cited evidence includes a direct statistical test of the claim.",
    )
    evidence_ids: list[str] = Field(
        default_factory=list, description="Evidence ids supporting this claim"
    )

    extra: dict[str, Any] = Field(default_factory=dict)


__all__ = ["ClaimV1"]
