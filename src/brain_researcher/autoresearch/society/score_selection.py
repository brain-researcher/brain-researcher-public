"""VB-2 consumer: select the best claim by its SURVIVAL-GATED score, not its raw magnitude.

VB-2 (``compute_survival_gated_score``) withholds a claim's numeric score of record when a required
falsifier refuted it. But a gate that produces a number only has teeth if a consumer RESPECTS it.
This is that consumer: cross-claim selection / ranking that ranks by the survival-gated score, so a
result a required self-falsifier refuted (or one whose battery was incomplete, i.e. a VB-1 refusal)
is INELIGIBLE to win — no matter how large its raw magnitude. A magnitude-optimizing loop wired
through this selector cannot climb a hill it did not earn.

The selector duck-types its inputs (it reads ``claim_card``/``survival_gated_score``/``blocked`` off
each ConductOutcome) so this module imports nothing from the conductor — no import cycle. It also
reports what a NAIVE bare-magnitude selector would have picked, so the divergence ("bare magnitude
would crown a refuted result; the institution does not") is explicit and auditable.
"""

from __future__ import annotations

import math
from typing import Any

from pydantic import BaseModel, Field


class GatedSelectionEntry(BaseModel):
    """One claim's standing in a survival-gated selection."""

    claim_id: str
    survival_gated_score: float | None
    raw_score: float | None
    eligible: bool
    reason: str


class SurvivalGatedSelection(BaseModel):
    """The outcome of selecting the best claim by survival-gated score.

    ``winner_claim_id`` is the highest survival-gated score among ELIGIBLE claims (survived their
    required battery with a real score); ``None`` if nothing is eligible. ``ranked`` is the eligible
    set descending by gated score; ``ineligible`` is everything withheld or refused.
    ``diverged_from_bare_magnitude`` is True when a naive max-raw-score selector would have crowned a
    DIFFERENT claim — i.e. the institution refused to bank a magnitude a required self-falsifier
    killed.
    """

    winner_claim_id: str | None
    winner_score: float | None
    ranked: list[GatedSelectionEntry] = Field(default_factory=list)
    ineligible: list[GatedSelectionEntry] = Field(default_factory=list)
    bare_magnitude_winner_claim_id: str | None = None
    bare_magnitude_winner_raw_score: float | None = None
    diverged_from_bare_magnitude: bool = False


def _claim_id(outcome: Any) -> str | None:
    """The claim id, or None when the outcome carries no resolvable claim_card/claim_id."""
    card = getattr(outcome, "claim_card", None)
    cid = getattr(card, "claim_id", None) if card is not None else None
    return str(cid) if cid is not None else None


def _finite_or_none(value: Any) -> float | None:
    """Coerce to a finite float, or None — so a NaN/inf never wins or distorts a ranking."""
    if value is None:
        return None
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


def _raw_score(outcome: Any) -> float | None:
    """The raw magnitude a bare agent would bank — read from the card's pipeline_summary, falling
    back to the stop artifact. Never the gated score. Non-finite (NaN/inf) -> None."""
    card = getattr(outcome, "claim_card", None)
    summary = getattr(card, "pipeline_summary", None) if card is not None else None
    if isinstance(summary, dict):
        raw = _finite_or_none(summary.get("last_score"))
        if raw is not None:
            return raw
    stop = getattr(outcome, "stop", None)
    return _finite_or_none(getattr(stop, "last_score", None) if stop is not None else None)


def select_best_by_survival_gated_score(outcomes: list[Any]) -> SurvivalGatedSelection:
    """Rank claims by survival-gated score; a withheld or refused claim cannot win.

    Eligibility (a claim may be selected as "best"):
      * NOT ``blocked`` (a VB-1 refusal is never selectable), AND
      * ``survival_gated_score is not None`` (a VB-2 withhold is never selectable).
    The winner is the max survival-gated score among eligible claims. Ties resolve to the first
    such claim in input order (stable). The bare-magnitude winner (max raw score over ALL claims
    that produced a score, ignoring gating) is reported alongside so the divergence is visible.
    """
    entries: list[GatedSelectionEntry] = []
    for o in outcomes:
        cid = _claim_id(o)
        raw = _raw_score(o)
        gated = _finite_or_none(getattr(o, "survival_gated_score", None))
        if cid is None:
            # A malformed outcome (no claim_card/claim_id) is not a selectable result.
            entries.append(GatedSelectionEntry(
                claim_id="<unknown>", survival_gated_score=None, raw_score=raw,
                eligible=False, reason="malformed: no claim_card/claim_id",
            ))
        elif getattr(o, "blocked", False):
            entries.append(GatedSelectionEntry(
                claim_id=cid, survival_gated_score=None, raw_score=raw,
                eligible=False, reason="refused: required falsifier verdict missing (VB-1)",
            ))
        elif gated is None:
            # None OR non-finite (NaN/inf) gated score -> withheld, never selectable.
            entries.append(GatedSelectionEntry(
                claim_id=cid, survival_gated_score=None, raw_score=raw,
                eligible=False, reason="score withheld: required axis refuted or no score (VB-2)",
            ))
        else:
            entries.append(GatedSelectionEntry(
                claim_id=cid, survival_gated_score=gated, raw_score=raw,
                eligible=True, reason="survived required battery",
            ))

    eligible = [e for e in entries if e.eligible]
    # max by gated score; stable on ties (max returns the first max under a strict key).
    ranked = sorted(eligible, key=lambda e: e.survival_gated_score, reverse=True)
    winner = ranked[0] if ranked else None

    scored = [e for e in entries if e.raw_score is not None]
    bare = max(scored, key=lambda e: e.raw_score, default=None)

    winner_id = winner.claim_id if winner is not None else None
    bare_id = bare.claim_id if bare is not None else None
    return SurvivalGatedSelection(
        winner_claim_id=winner_id,
        winner_score=winner.survival_gated_score if winner is not None else None,
        ranked=ranked,
        ineligible=[e for e in entries if not e.eligible],
        bare_magnitude_winner_claim_id=bare_id,
        bare_magnitude_winner_raw_score=bare.raw_score if bare is not None else None,
        # Divergence is meaningful only when a bare-magnitude winner exists AND it is not the gated
        # winner — i.e. naive magnitude would have crowned a claim the institution did not select.
        diverged_from_bare_magnitude=(bare_id is not None and bare_id != winner_id),
    )


__all__ = [
    "GatedSelectionEntry",
    "SurvivalGatedSelection",
    "select_best_by_survival_gated_score",
]
