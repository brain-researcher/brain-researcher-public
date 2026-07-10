"""Typed hypothesis + reasoning mode (V-HRL P1, ported to society — SERVICE-FREE).

A *hypothesis* is the structured, causal-mechanistic object UPSTREAM of a claim. Its structural
completeness bounds how strong a claim derived from it may be — the reasoning-mode idea:

* missing cause/effect -> not a testable hypothesis (``cannot_compile``);
* cause+effect, no mechanism -> ``associational`` (no causal language) / ``exploratory``;
* +mechanism, no ruled-out alternatives -> ``mechanistic_nondiscriminative``;
* +alternatives, no discriminating critical test -> ``mechanistic``;
* all of the above -> ``causal``.

``reasoning_mode_ceiling`` expresses this as a composable :class:`CeilingResult`
(``ClaimStatusV1``), to be ``compose_ceilings``-d with the multiverse + claim-structure axes.
Following V-HRL's strength/kind split: only the genuinely weak modes (``cannot_compile`` /
``exploratory``) cap *strength*; the richer-but-incomplete modes restrict the claim *kind*
(no causal language), recorded in the display — the strength cap comes from the evidence axis.

This module imports only ``.cards`` / ``.multiverse`` (pure), so society stays service-free.
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field

from .cards import ClaimStatusV1
from .multiverse import CeilingResult


class ReasoningMode(str, Enum):
    cannot_compile = "cannot_compile"
    exploratory = "exploratory"
    associational = "associational"
    mechanistic_nondiscriminative = "mechanistic_nondiscriminative"
    mechanistic = "mechanistic"
    causal = "causal"
    confirmatory = "confirmatory"  # causal + an explicit pre-registration commitment


class CriticalTestV1(BaseModel):
    """A discriminating test: manipulation + measurement + comparison."""

    schema_version: Literal["critical-test-v1"] = "critical-test-v1"
    manipulation: str | None = None
    measurement: list[str] = Field(default_factory=list)
    comparison: str | None = None

    def is_discriminating(self) -> bool:
        return bool(self.manipulation and self.measurement and self.comparison)


class HypothesisSpecV1(BaseModel):
    """A typed, causal-mechanistic hypothesis (the object a claim is derived from)."""

    schema_version: Literal["hypothesis-spec-v1"] = "hypothesis-spec-v1"
    hypothesis_id: str
    statement: str
    cause: str | None = None
    effect: str | None = None
    mechanism: str | None = None
    context: list[str] = Field(default_factory=list)
    predictions: list[str] = Field(default_factory=list)
    alternative_explanations: list[str] = Field(default_factory=list)
    critical_test: CriticalTestV1 | None = None
    extra: dict[str, Any] = Field(default_factory=dict)


def derive_reasoning_mode(hyp: HypothesisSpecV1) -> ReasoningMode:
    """Map which fields are present to the allowed reasoning mode (graceful degradation).

    ``confirmatory`` is not derivable from structure alone (it needs an explicit
    pre-registration commitment recorded elsewhere), so derivation tops out at ``causal``.
    """
    if not ((hyp.cause or "").strip() and (hyp.effect or "").strip()):
        return ReasoningMode.cannot_compile
    if not (hyp.mechanism or "").strip():
        return (
            ReasoningMode.associational if hyp.predictions else ReasoningMode.exploratory
        )
    if not hyp.alternative_explanations:
        return ReasoningMode.mechanistic_nondiscriminative
    if not (hyp.critical_test and hyp.critical_test.is_discriminating()):
        return ReasoningMode.mechanistic
    return ReasoningMode.causal


# Only genuinely weak modes cap STRENGTH; the rest restrict claim KIND (display note only).
_MODE_STATUS: dict[ReasoningMode, ClaimStatusV1] = {
    ReasoningMode.cannot_compile: ClaimStatusV1.weakened,
    ReasoningMode.exploratory: ClaimStatusV1.qualified,
    ReasoningMode.associational: ClaimStatusV1.supported_within_scope,
    ReasoningMode.mechanistic_nondiscriminative: ClaimStatusV1.supported_within_scope,
    ReasoningMode.mechanistic: ClaimStatusV1.supported_within_scope,
    ReasoningMode.causal: ClaimStatusV1.supported_within_scope,
    ReasoningMode.confirmatory: ClaimStatusV1.supported_within_scope,
}
_MODE_KIND_NOTE: dict[ReasoningMode, str] = {
    ReasoningMode.cannot_compile: "not a testable hypothesis (missing cause/effect)",
    ReasoningMode.exploratory: "exploratory: no prediction specified",
    ReasoningMode.associational: "association only — no causal/mechanistic claim",
    ReasoningMode.mechanistic_nondiscriminative: "mechanism without ruled-out alternatives",
    ReasoningMode.mechanistic: "alternatives named but no discriminating critical test",
    ReasoningMode.causal: "",
    ReasoningMode.confirmatory: "",
}


def reasoning_mode_ceiling(hyp: HypothesisSpecV1) -> CeilingResult:
    """Ceiling a hypothesis's STRUCTURE permits (reasoning-mode), composable with the others."""
    mode = derive_reasoning_mode(hyp)
    note = _MODE_KIND_NOTE[mode]
    return CeilingResult(
        status=_MODE_STATUS[mode],
        display=f"reasoning_mode={mode.value}" + (f" ({note})" if note else ""),
        rationale=note or f"reasoning_mode={mode.value}: no structural strength cap.",
        inputs={"reasoning_mode": mode.value},
    )


__all__ = [
    "CriticalTestV1",
    "HypothesisSpecV1",
    "ReasoningMode",
    "derive_reasoning_mode",
    "reasoning_mode_ceiling",
]
