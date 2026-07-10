"""VB-1: required-falsifier-verdict battery — the kernel → institution ordering gate.

A claim with a registry-derived falsifier battery may not be finalized / frozen / dispatched to
external compute unless every REQUIRED axis has produced a verdict. The distinction that *is* the
institution:

    missing verdict  ⇒  REFUSE the claim   (NEEDS_DIAGNOSIS — it was never adjudicated)
    present verdict   ⇒  let it stand        (a NEGATIVE verdict only downgrades, via the
                                              existing ceiling logic — never handled here)

Scope of this slice: the resolver operates over the conductor's ``FalsifierOutcome`` list, so the
required axes are the deterministic conductor gates. The motion/site group-confound check lives in
the *review* subsystem (it does not emit a conductor ``FalsifierOutcome``); enforcing it as a
required axis is a follow-up at the review enforcement point, not this conductor gate.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING

from pydantic import BaseModel, Field

from .cards import (
    NON_EVALUABLE_PROBE_PROVENANCES,
    ClaimSpecV1,
    FalsifierAxisSpec,
    FalsifierBatterySpec,
)

if TYPE_CHECKING:  # avoid a runtime import cycle (falsifiers imports cards, not battery)
    from .falsifiers import FalsifierOutcome


# --------------------------------------------------------------------------- #
# Registry — claim class -> required battery. Start with ONE real profile (the
# already-validated predictive kernel); discovery batteries are TODO stubs.
# --------------------------------------------------------------------------- #
def _axis(gate: str, rank: int) -> FalsifierAxisSpec:
    return FalsifierAxisSpec(axis_id=gate, gate_name=gate, required=True, cost_rank=rank,
                             fail_closed_policy="missing_verdict_blocks")


_PREDICTIVE_AXES = (
    "confound", "permutation_null", "correction_fragile",
    "selection_leakage", "effect_size_floor", "fold_dispersion",
)

INDIVIDUAL_DIFFERENCE_FMRI_PREDICTION = FalsifierBatterySpec(
    battery_id="individual_difference_fMRI_prediction.v1",
    claim_signature="individual_difference_fMRI_prediction",
    required_axes=[_axis(g, i) for i, g in enumerate(_PREDICTIVE_AXES)],
    cost_order=list(_PREDICTIVE_AXES),
    version="v1",
)

#: claim_signature -> required battery. (TODO: discovery batteries —
#: audio_language_encoding_contrast, task_fMRI_discovery_materialization — once their gates exist.)
REQUIRED_BATTERIES: dict[str, FalsifierBatterySpec] = {
    INDIVIDUAL_DIFFERENCE_FMRI_PREDICTION.claim_signature: INDIVIDUAL_DIFFERENCE_FMRI_PREDICTION,
}


def resolve_battery_for_claim(claim: ClaimSpecV1) -> FalsifierBatterySpec | None:
    """Map a claim to its required battery by signature; None if the class has no battery.

    Signature source (first hit): ``claim.extra['claim_class']`` / ``['claim_signature']``, then
    ``claim.scope_boundary.workflow_family``. A claim with no recognised signature is unbatteried
    (the conductor then never refuses on coverage — back-compatible).
    """
    extra = getattr(claim, "extra", None) or {}
    sig = extra.get("claim_class") or extra.get("claim_signature")
    if not sig:
        sig = getattr(getattr(claim, "scope_boundary", None), "workflow_family", None)
    return REQUIRED_BATTERIES.get(str(sig)) if sig else None


def derive_default_battery(
    strategies: tuple[str, ...] | list[str],
    claim: ClaimSpecV1,
    *,
    hard_axes: frozenset[str] | set[str],
) -> FalsifierBatterySpec | None:
    """The default required battery for a CONFIRMATORY claim, de-dormanting the institution without
    a claim-class registry entry: the HARD self-falsifier axes WITHIN the committed strategy set.

    This is the safe, run-mode-adaptive default. Because the required axes are
    ``strategies ∩ hard_axes`` they are a SUBSET of what the conductor will actually run — so the
    battery can never refuse for an un-runnable reason (no brick); it can only refuse when a
    *configured* hard axis produced no verdict, which is the correct fail-closed outcome ("your hard
    self-falsifiers must adjudicate before you finalize"). Adapts to the run mode for free: an LLM
    arm contributes {leakage, null, inference}; a gates-only arm contributes {permutation_null}.

    Returns ``None`` for a non-confirmatory claim (an exploratory claim is not held to this floor) or
    when the committed strategies contain no hard axis (nothing to require). The battery is
    hash-locked into the commitment by the caller, so it is committed before any result is observed.
    """
    if not getattr(claim, "confirmatory", False):
        return None
    required = [s for s in dict.fromkeys(strategies) if s in hard_axes]
    if not required:
        return None
    return FalsifierBatterySpec(
        battery_id="committed_hard_axes.v1",
        claim_signature="__committed_hard_axes__",
        required_axes=[
            FalsifierAxisSpec(axis_id=s, gate_name=s, cost_rank=i)
            for i, s in enumerate(required)
        ],
        cost_order=list(required),
    )


def battery_unrunnable_axes(
    battery: FalsifierBatterySpec, strategies: tuple[str, ...] | list[str]
) -> list[str]:
    """Required axes that are NOT in the committed strategy set — they cannot produce a verdict, so
    the battery is unsatisfiable as configured and every claim would be refused. Returned so a
    caller can surface the misconfiguration (e.g. a registry profile requiring deterministic gates
    that this arm never runs) instead of silently refusing everything."""
    configured = set(strategies)
    return [a.gate_name for a in battery.required_axes if a.required and a.gate_name not in configured]


# --------------------------------------------------------------------------- #
# Verdict resolution over the conductor's FalsifierOutcome list
# --------------------------------------------------------------------------- #
class AxisVerdictStatus(BaseModel):
    axis_id: str
    gate_name: str
    present: bool
    verdict: str | None = None
    blocking_reason: str | None = None


class BatteryVerdictStatus(BaseModel):
    battery_id: str
    complete: bool
    missing_axes: list[str] = Field(default_factory=list)
    blocking_axes: list[AxisVerdictStatus] = Field(default_factory=list)
    observed_axes: list[AxisVerdictStatus] = Field(default_factory=list)


def resolve_battery_status(
    battery: FalsifierBatterySpec, outcomes: list[FalsifierOutcome]
) -> BatteryVerdictStatus:
    """Is every REQUIRED axis present with a usable verdict?

    A required axis is SATISFIED iff a non-degenerate ``FalsifierOutcome`` exists for its
    ``gate_name``. No outcome (the gate never ran) or an infra-degenerate outcome ⇒ MISSING
    verdict ⇒ blocking. A present non-degenerate outcome — whether it refuted or survived — is a
    real verdict; its *content* downgrades the claim elsewhere, it never blocks here.
    """
    by: dict[str, FalsifierOutcome] = {}
    for o in outcomes:
        prev = by.get(o.strategy)
        # Prefer a non-degenerate outcome if duplicates exist for a strategy; among two
        # non-degenerate duplicates the FIRST wins. Either way the gate decision (a verdict
        # EXISTS for this axis) is order-independent — only the recorded verdict label could
        # differ, never present-vs-missing — so coverage is deterministic w.r.t. ordering.
        if prev is None or (getattr(prev, "degenerate", False) and not getattr(o, "degenerate", False)):
            by[o.strategy] = o

    missing: list[str] = []
    blocking: list[AxisVerdictStatus] = []
    observed: list[AxisVerdictStatus] = []
    for axis in battery.required_axes:
        if not axis.required:
            continue
        o = by.get(axis.gate_name)
        if o is None:
            missing.append(axis.gate_name)
            blocking.append(AxisVerdictStatus(axis_id=axis.axis_id, gate_name=axis.gate_name,
                                              present=False, blocking_reason="missing_verdict:axis_not_run"))
            continue
        if getattr(o, "degenerate", False):
            missing.append(axis.gate_name)
            blocking.append(AxisVerdictStatus(axis_id=axis.axis_id, gate_name=axis.gate_name,
                                              present=True, verdict="degenerate",
                                              blocking_reason="missing_verdict:infra_degenerate"))
            continue
        if getattr(o, "provenance", None) in NON_EVALUABLE_PROBE_PROVENANCES:
            missing.append(axis.gate_name)
            blocking.append(AxisVerdictStatus(
                axis_id=axis.axis_id,
                gate_name=axis.gate_name,
                present=True,
                verdict="non_evaluable",
                blocking_reason=f"missing_verdict:{o.provenance}",
            ))
            continue
        observed.append(AxisVerdictStatus(axis_id=axis.axis_id, gate_name=axis.gate_name,
                                          present=True, verdict=("refuted" if o.refuted else "survived")))
    return BatteryVerdictStatus(battery_id=battery.battery_id, complete=(not missing),
                                missing_axes=missing, blocking_axes=blocking, observed_axes=observed)


class ExternalComputeBlocked(RuntimeError):
    """Raised when external-compute dispatch is requested for a claim whose required falsifier
    battery is incomplete. Reason string: EXTERNAL_COMPUTE_BLOCKED_MISSING_FALSIFIER.

    ``note`` carries extra context for the persisted-artifact path (e.g. the claim was refused
    at finalization, or no society adjudication was found at all)."""

    reason = "EXTERNAL_COMPUTE_BLOCKED_MISSING_FALSIFIER"

    def __init__(self, status: BatteryVerdictStatus, note: str | None = None):
        self.status = status
        self.note = note
        msg = f"{self.reason}: missing required verdict(s) {status.missing_axes}"
        if note:
            msg += f" ({note})"
        super().__init__(msg)


def assert_required_battery_complete(
    battery: FalsifierBatterySpec, outcomes: list[FalsifierOutcome]
) -> BatteryVerdictStatus:
    """Raising precondition an external-compute / freeze dispatcher MUST call before dispatch:
    raise ``ExternalComputeBlocked`` if any required axis lacks a verdict, else return the
    (complete) status. It shares ``resolve_battery_status`` with the conductor's in-line finalize
    gate, so a dispatcher that calls this enforces the SAME invariant the conductor enforces.

    Scope note (VB-1): the conductor already refuses *finalization* in-process (``conduct()`` ->
    ``blocked``). No external-dispatch site is wired to this guard in this slice — the operational
    preflight (TRIBE / slurm) is a later PR. Until then a dispatcher's only obligations are to run
    through ``conduct()`` and honor ``ConductOutcome.blocked``, or to call this directly."""
    status = resolve_battery_status(battery, outcomes)
    if not status.complete:
        raise ExternalComputeBlocked(status)
    return status


# --------------------------------------------------------------------------- #
# VB-2 — survival-gated score (the numeric analog of the VB-1 refusal gate)
# --------------------------------------------------------------------------- #
class SurvivalGatedScore(BaseModel):
    """The score of record, gated by required-falsifier SURVIVAL.

    VB-1 gates *finalization* on required-verdict PRESENCE (missing ⇒ refuse). VB-2 gates the
    numeric *score* on required-verdict CONTENT: the magnitude is passed through only if the
    result survived its required battery; if any required axis REFUTED it, the score is WITHHELD
    (``gated_score=None``). This is distinct from the status ceiling (which already caps the
    *status* for any refutation): VB-2 stops a magnitude-optimizing loop from banking a number
    that a required self-falsifier killed. A claim class with no required battery has no survival
    contract on its score, so the raw score passes through unchanged (back-compatible).
    """

    raw_score: float | None
    gated_score: float | None
    survived: bool
    reason: str
    # Required axes that REFUTED the result (the reason the score was withheld). Strictly
    # refutations — NOT axes that merely failed to run; those go in ``missing_axes`` so a
    # downstream consumer never mistakes "never adjudicated" for "actively refuted".
    refuting_axes: list[str] = Field(default_factory=list)
    # Required axes with no usable verdict (absent or infra-degenerate) when the battery was
    # incomplete. Disjoint from ``refuting_axes``.
    missing_axes: list[str] = Field(default_factory=list)


def compute_survival_gated_score(
    raw_score: float | None,
    battery: FalsifierBatterySpec | None,
    outcomes: list[FalsifierOutcome],
) -> SurvivalGatedScore:
    """Gate a magnitude score by required-falsifier survival.

    * ``raw_score is None`` → no usable score → withheld (``no_score``).
    * no required battery → no survival contract → raw passes through (``no_required_battery``).
    * required battery incomplete (a required axis produced no verdict) → cannot certify
      survival → withheld (``incomplete_required_battery``). VB-1 normally blocks this upstream,
      but the gate is defensive so it never certifies a number it cannot stand behind.
    * any required axis REFUTED → withheld, axes listed (``refuted_by_required_axis``).
    * all required axes survived → raw passes through (``survived_required_battery``).
    """
    if raw_score is None:
        return SurvivalGatedScore(raw_score=None, gated_score=None, survived=False, reason="no_score")
    if battery is None:
        return SurvivalGatedScore(
            raw_score=raw_score, gated_score=raw_score, survived=True, reason="no_required_battery"
        )
    status = resolve_battery_status(battery, outcomes)
    if not status.complete:
        return SurvivalGatedScore(
            raw_score=raw_score, gated_score=None, survived=False,
            reason="incomplete_required_battery", missing_axes=list(status.missing_axes),
        )
    refuting = [a.gate_name for a in status.observed_axes if a.verdict == "refuted"]
    if refuting:
        return SurvivalGatedScore(
            raw_score=raw_score, gated_score=None, survived=False,
            reason="refuted_by_required_axis", refuting_axes=refuting,
        )
    return SurvivalGatedScore(
        raw_score=raw_score, gated_score=raw_score, survived=True, reason="survived_required_battery"
    )


# --------------------------------------------------------------------------- #
# VB-3 (M1 operational floor) — persisted-artifact external-dispatch preflight
# --------------------------------------------------------------------------- #
# A cross-process dispatcher (slurm / HPC / external compute) does NOT hold the live
# (battery, outcomes) — it only knows a claim's society state dir. The conductor persists the
# adjudication there: ``commitment_card.json`` (hash-locked battery), and either ``claim_card.json``
# (with ``pipeline_summary['survival_gate']['missing_axes']``) or ``refusal.json`` (a VB-1 refusal).
# Raw ``FalsifierOutcome`` objects are NOT serialized, so we cannot recompute the verdict from disk
# — but the conductor already recorded the COMPLETENESS result, so this guard enforces the SAME
# EXTERNAL_COMPUTE_BLOCKED_MISSING_FALSIFIER invariant as the in-memory
# ``assert_required_battery_complete``, read off the persisted cards. Fail-closed: a state dir with
# no adjudication at all is blocked (you may not book external compute for a claim the institution
# never adjudicated).
_SOCIETY_SUBDIR = "society"


def _block(missing: list[str], note: str) -> ExternalComputeBlocked:
    status = BatteryVerdictStatus(
        battery_id="persisted", complete=False, missing_axes=list(missing),
        blocking_axes=[], observed_axes=[],
    )
    return ExternalComputeBlocked(status, note=note)


def assert_external_compute_allowed_from_state_dir(state_dir: str | Path) -> BatteryVerdictStatus:
    """Persisted-artifact analog of :func:`assert_required_battery_complete`, for an external
    dispatcher (slurm / HPC) that has only a claim's society ``state_dir``.

    Reads ``{state_dir}/society/{refusal.json|claim_card.json}`` and raises
    :class:`ExternalComputeBlocked` if the claim was refused at finalization (VB-1), if its
    required battery is incomplete, or if no adjudication exists at all (fail-closed). Returns a
    ``complete`` :class:`BatteryVerdictStatus` when dispatch is allowed. Mirrors VB-1 exactly: the
    gate is on required-verdict COMPLETENESS, not survival — a battery-complete-but-refuted claim
    (status weakened/rejected) is adjudicated, so external dispatch is allowed; only a *missing*
    required verdict (or an outright refusal) blocks.
    """
    society = Path(state_dir).expanduser() / _SOCIETY_SUBDIR
    refusal = society / "refusal.json"
    claim_card = society / "claim_card.json"

    def _load(path: Path) -> dict:
        # Malformed/unreadable adjudication is fail-CLOSED (a clean refusal, not a crash): we
        # cannot verify completeness, so we refuse rather than silently allow.
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise _block([], f"unreadable {path.name}: {exc}") from exc

    if refusal.exists():
        data = _load(refusal)
        missing = list(
            data.get("falsification_budget_spent", {}).get("missing_required_axes", [])
        )
        raise _block(missing, "claim was REFUSED at finalization (VB-1 needs_diagnosis)")

    if claim_card.exists():
        data = _load(claim_card)
        gate = data.get("pipeline_summary", {}).get("survival_gate")
        # Fail-CLOSED on a card that lacks a well-formed completeness record (a pre-VB-2 card or a
        # non-conductor card). We MUST NOT treat "no missing_axes recorded" as "battery complete":
        # absence of the record is absence of evidence, so we refuse rather than allow.
        if not isinstance(gate, dict) or "missing_axes" not in gate:
            raise _block(
                [],
                "claim_card.json has no well-formed pipeline_summary.survival_gate.missing_axes "
                "record (pre-VB-2 or non-conductor card) — cannot verify battery completeness",
            )
        missing = list(gate.get("missing_axes") or [])
        if missing:
            raise _block(missing, "required falsifier battery incomplete")
        return BatteryVerdictStatus(
            battery_id="persisted", complete=True, missing_axes=[],
            blocking_axes=[], observed_axes=[],
        )

    # Neither a claim card nor a refusal: the claim was never adjudicated by the society. The
    # operational floor refuses to book external compute for an un-adjudicated claim (fail-closed).
    raise _block([], f"no society adjudication found under {society}")
