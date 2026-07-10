"""Claim-ceiling composition + claim-structure ceiling (ported from V-HRL §1.2 / reasoning-mode).

Two calibration axes that sit *beside* the multiverse keystone, so a claim's base status is the
most conservative of several independent ceilings:

* :func:`compose_ceilings` — the most conservative (weakest) ``CeilingResult`` wins, and the axis
  that bound it is recorded. This is the V-HRL §1.2 ``min`` law in society's ``ClaimStatusV1``
  vocabulary. (Refutation is a SEPARATE axis — a falsifier / trap — not composed here.)
* :func:`claim_structure_ceiling` — how strong a claim's STRUCTURE alone permits, independent of
  any evidence (the reasoning-mode idea): an *exploratory*, *alternatives-free*, or
  *failure-criterion-free* :class:`ClaimSpecV1` cannot reach ``supported_within_scope``.

The structure→ceiling mapping is a CONVENTION (like the multiverse ``_MV_*`` thresholds),
pending review — which fields gate ``supported_within_scope`` is a policy choice.
"""

from __future__ import annotations

from collections.abc import Sequence

from .cards import ClaimSpecV1, ClaimStatusV1
from .multiverse import CeilingResult

# Ascending strength for the *ceiling* axes (weakest -> strongest). Statuses not listed
# (unresolved / conflicting / ill_typed) are treated as most-conservative in composition.
_CEILING_STRENGTH: dict[ClaimStatusV1, int] = {
    ClaimStatusV1.weakened: 0,
    ClaimStatusV1.qualified: 1,
    ClaimStatusV1.supported_within_scope: 2,
}


def _strength(status: ClaimStatusV1) -> int:
    return _CEILING_STRENGTH.get(status, -1)  # off-ladder -> most conservative


def compose_ceilings(results: Sequence[CeilingResult]) -> CeilingResult:
    """Compose independent ceilings: the most conservative (weakest) one wins (V-HRL §1.2).

    An empty set means *no constraint* -> ``supported_within_scope``. Ties resolve to the
    first-listed. The returned ``CeilingResult`` is the binding one, with the other axes'
    displays folded into its rationale for auditability.
    """
    active = [r for r in results if r is not None]
    if not active:
        return CeilingResult(
            status=ClaimStatusV1.supported_within_scope,
            display="unconstrained",
            rationale="no ceiling axes applied.",
        )
    binding = min(active, key=lambda r: _strength(r.status))
    others = [f"{r.display}={r.status.value}" for r in active if r is not binding]
    rationale = binding.rationale
    if others:
        rationale = f"{rationale} (composed; other axes: {', '.join(others)})"
    return binding.model_copy(update={"rationale": rationale})


def claim_structure_ceiling(claim: ClaimSpecV1) -> CeilingResult:
    """Strongest status a claim's STRUCTURE alone permits — the reasoning-mode analog.

    CONVENTION (pending review): to be eligible for ``supported_within_scope`` on structure, a
    claim must be confirmatory, name the competing explanations it rules out, and carry a
    pre-specified failure criterion. Missing any of these caps it at ``qualified`` — structure
    weakens, it never rejects (rejection needs a positive refutation).
    """
    missing: list[str] = []
    if not claim.confirmatory:
        missing.append("exploratory (not confirmatory)")
    if not claim.allowed_alternatives:
        missing.append("no allowed_alternatives (competitors not specified)")
    if not claim.failure_criteria:
        missing.append("no failure_criteria (no pre-specified falsification)")

    if not missing:
        return CeilingResult(
            status=ClaimStatusV1.supported_within_scope,
            display="structure-complete",
            rationale="confirmatory, with named alternatives and a failure criterion.",
        )
    return CeilingResult(
        status=ClaimStatusV1.qualified,
        display="structure-incomplete",
        rationale="structurally capped: " + "; ".join(missing) + ".",
        inputs={"missing": missing},
    )


__all__ = ["claim_structure_ceiling", "compose_ceilings"]
