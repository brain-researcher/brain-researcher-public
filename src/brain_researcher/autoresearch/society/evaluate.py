"""Score a conductor ClaimCard against the hidden oracle (spec section 13).

Metrics (correction-speed metrics like false_claim_residence_time need a time
series and are out of scope for a single episode; these are the per-episode
status/severity/risk metrics):

* ``status_agreement`` — share of claims whose final status equals the expected
  verdict OR an acceptable alternative.
* ``severity_weighted_error`` — asymmetric cost (overclaiming is worse than
  underclaiming; asserting a definite verdict on an *open* question, or
  *supported* on a *trap*, is maximal).
* ``risk_detection`` — share of the oracle's expected risk axes that the
  falsifiers actually flagged.

Per section 12, every claim score carries its oracle ``tier_weight`` and the
aggregate is also broken down by claim type, so the methodological-theorem traps
(the gold line) can be read separately from consensus-tier "robust" claims.

Two tier aggregates are reported because they answer different questions:

* ``tier_weighted_severity`` — the weight-NORMALIZED mean (divides by
  ``sum(tier_weight)``). This re-balances the RELATIVE contribution of claims
  when their errors differ, but it is a NO-OP when every per-claim error is
  equal: two equally-wrong claims of different tiers contribute identically to a
  normalized mean. It is kept for backward compatibility and for reading "the
  average severity per unit of oracle weight".
* ``abs_tier_weighted_severity`` — the ABSOLUTE tier-weighted aggregate
  (``sum(severity * tier_weight) / n``, an unweighted reference). This is the
  metric that implements the section-12 semantics: a consensus-tier error costs
  ABSOLUTELY less than an equal-magnitude ground_truth error, so the gold-line
  (ground_truth / trap) errors dominate the aggregate and the system is not
  heavily penalized for doubting a shaky "consensus" claim. Because tier weights
  are <= 1.0, this aggregate is always <= ``severity_error_mean``.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from .blueprint import TIER_WEIGHT, EvidenceStatusTypeV1, HiddenOracleV1, OracleTierV1
from .cards import ClaimCardV1, ClaimStatusV1

# Ordinal "claim strength" for the four determinate statuses (unresolved is special).
# The non-evidential statuses are placed on the ladder so oracle scoring never
# KeyErrors if such a card is scored: ``conflicting`` ~ weakened-strength (not clean
# support); ``ill_typed`` is a structural reject (weakest); ``needs_diagnosis`` is a
# VB-1 refusal (asserts nothing positive, so strength 0 — never an overclaim), though
# ``status_severity`` treats it like a conservative non-verdict (a punt), not a wrong
# answer. The conductor emits ``needs_diagnosis`` on a required-falsifier refusal.
_STRENGTH: dict[ClaimStatusV1, int] = {
    ClaimStatusV1.supported_within_scope: 3,
    ClaimStatusV1.qualified: 2,
    ClaimStatusV1.weakened: 1,
    ClaimStatusV1.rejected: 0,
    ClaimStatusV1.conflicting: 1,
    ClaimStatusV1.ill_typed: 0,
    ClaimStatusV1.needs_diagnosis: 0,
}


def status_severity(
    expected: ClaimStatusV1,
    actual: ClaimStatusV1,
    acceptable: list[ClaimStatusV1],
) -> float:
    """Asymmetric error cost in [0, 1]; 0 == exact or acceptable-alternative match."""
    if actual == expected or actual in acceptable:
        return 0.0
    supported = ClaimStatusV1.supported_within_scope
    # Both ``unresolved`` (punt) and ``needs_diagnosis`` (VB-1 refusal-to-certify) are
    # NON-VERDICTS: honest "no determinate answer", never an overclaim. They are scored as
    # one class so a refusal reads the same as a punt (it must NOT collapse onto the
    # strength-0 ``rejected`` / ``ill_typed`` and look like a confident negative verdict).
    non_verdict = {ClaimStatusV1.unresolved, ClaimStatusV1.needs_diagnosis}
    # Expected a genuinely open / un-adjudicable question: another non-verdict is fine;
    # a confident verdict is the error (supported — claiming a definite answer — is worst).
    if expected in non_verdict:
        if actual in non_verdict:
            return 0.0
        return 1.0 if actual == supported else 0.6
    # A non-verdict on a claim that HAD a determinate answer: a conservative miss,
    # cheaper than a confidently wrong one.
    if actual in non_verdict:
        return 0.5
    dist = abs(_STRENGTH[expected] - _STRENGTH[actual]) / 3.0
    overclaim = _STRENGTH[actual] > _STRENGTH[expected]
    return min(1.0, dist * (1.5 if overclaim else 1.0))


def detected_risks(card: ClaimCardV1) -> list[str]:
    """Falsifier axes that actually fired, parsed from the claim card's failed_checks."""
    axes: list[str] = []
    for entry in card.failed_checks:
        axis = entry.split(":", 1)[0].strip()
        if axis and axis not in axes:
            axes.append(axis)
    return axes


class ClaimScore(BaseModel):
    claim_id: str
    evidence_status_type: EvidenceStatusTypeV1
    oracle_tier: OracleTierV1
    tier_weight: float
    expected_verdict: ClaimStatusV1
    actual_status: ClaimStatusV1
    status_exact: bool
    status_match: bool
    severity_weighted_error: float
    expected_risks: list[str] = Field(default_factory=list)
    detected_risks: list[str] = Field(default_factory=list)
    risk_detection: float | None = None


class EpisodeScore(BaseModel):
    n_claims: int
    status_agreement: float
    status_exact_rate: float
    severity_error_mean: float
    tier_weighted_severity: float
    abs_tier_weighted_severity: float
    risk_detection_mean: float | None
    per_type: dict[str, dict[str, float]] = Field(default_factory=dict)
    claim_scores: list[ClaimScore] = Field(default_factory=list)


def score_claim(card: ClaimCardV1, oracle: HiddenOracleV1) -> ClaimScore:
    expected = oracle.expected_system_verdict
    actual = card.status
    acceptable = list(oracle.acceptable_alt_verdicts)
    exact = actual == expected
    match = exact or actual in acceptable

    det = detected_risks(card)
    if oracle.expected_risks:
        hit = len(set(oracle.expected_risks) & set(det))
        risk_detection: float | None = hit / len(set(oracle.expected_risks))
    else:
        risk_detection = None

    return ClaimScore(
        claim_id=oracle.claim_id,
        evidence_status_type=oracle.evidence_status_type,
        oracle_tier=oracle.oracle_tier,
        tier_weight=TIER_WEIGHT[oracle.oracle_tier],
        expected_verdict=expected,
        actual_status=actual,
        status_exact=exact,
        status_match=match,
        severity_weighted_error=status_severity(expected, actual, acceptable),
        expected_risks=list(oracle.expected_risks),
        detected_risks=det,
        risk_detection=risk_detection,
    )


def score_episode(
    cards: dict[str, ClaimCardV1],
    oracle: dict[str, HiddenOracleV1],
) -> EpisodeScore:
    """Score every claim that has both a card and an oracle entry."""
    scores = [score_claim(cards[cid], oracle[cid]) for cid in oracle if cid in cards]
    n = len(scores)
    if n == 0:
        return EpisodeScore(
            n_claims=0,
            status_agreement=0.0,
            status_exact_rate=0.0,
            severity_error_mean=0.0,
            tier_weighted_severity=0.0,
            abs_tier_weighted_severity=0.0,
            risk_detection_mean=None,
        )

    status_agreement = sum(1 for s in scores if s.status_match) / n
    status_exact_rate = sum(1 for s in scores if s.status_exact) / n
    severity_error_mean = sum(s.severity_weighted_error for s in scores) / n

    abs_tier_weighted_sum = sum(s.severity_weighted_error * s.tier_weight for s in scores)
    weight_sum = sum(s.tier_weight for s in scores)
    # Weight-NORMALIZED mean (relative contribution; a no-op when errors are equal).
    tier_weighted_severity = abs_tier_weighted_sum / weight_sum if weight_sum else 0.0
    # ABSOLUTE tier-weighted aggregate (fixed reference n): a consensus-tier error
    # costs absolutely less than an equal-magnitude ground_truth error (spec section 12).
    abs_tier_weighted_severity = abs_tier_weighted_sum / n

    risk_scores = [s.risk_detection for s in scores if s.risk_detection is not None]
    risk_detection_mean = (sum(risk_scores) / len(risk_scores)) if risk_scores else None

    per_type: dict[str, dict[str, float]] = {}
    for status_type in EvidenceStatusTypeV1:
        subset = [s for s in scores if s.evidence_status_type == status_type]
        if not subset:
            continue
        per_type[status_type.value] = {
            "n": float(len(subset)),
            "status_agreement": sum(1 for s in subset if s.status_match) / len(subset),
            "severity_mean": sum(s.severity_weighted_error for s in subset) / len(subset),
        }

    return EpisodeScore(
        n_claims=n,
        status_agreement=status_agreement,
        status_exact_rate=status_exact_rate,
        severity_error_mean=severity_error_mean,
        tier_weighted_severity=tier_weighted_severity,
        abs_tier_weighted_severity=abs_tier_weighted_severity,
        risk_detection_mean=risk_detection_mean,
        per_type=per_type,
        claim_scores=scores,
    )
