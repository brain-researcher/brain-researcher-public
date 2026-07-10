"""The Brain Researcher Society thin conductor (spec sections 3-5, 13).

A single orchestration seam that wraps the existing ``BoundedSupervisor`` as a
black-box "pipeline arm" and adds the only genuinely new institutional pieces:

    commitment  ->  pipeline (black box)  ->  falsifier fan-out  ->  claim card

All four are recorded to a SEPARATE append-only ledger (``society_commits.jsonl``)
so the supervisor's own resume logic (which trusts the last line of
``stage_commits.jsonl``) is never corrupted.

Design choices that make this layer thin, testable, and ablatable:

* The commitment card (with its content hash and the frozen falsifier rubrics) is
  written to the ledger BEFORE the pipeline runs — "commit before observe" is
  enforced by append-only write ordering plus a post-run hash re-verification,
  not by self-discipline.
* The pipeline runner and critic runner are injected callables (defaulting to the
  real ``BoundedSupervisor`` and ``run_independent_critic``), so tests stub them
  and the spec section-13 ablation (arm b = no society) is a one-line bypass.
* Nothing here imports the service tier; the LLM router is injected from the CLI.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import TYPE_CHECKING, Any

from ..critic import CriticVerdict, run_independent_critic
from ..state_contract import StageCommit, StopArtifact, append_jsonl_artifact
from .battery import (
    FalsifierBatterySpec,
    battery_unrunnable_axes,
    compute_survival_gated_score,
    derive_default_battery,
    resolve_battery_for_claim,
    resolve_battery_status,
)
from .calibration import claim_structure_ceiling, compose_ceilings
from .calibration_store import CalibrationStore
from .cards import (
    NON_EVALUABLE_PROBE_PROVENANCES,
    ClaimCardV1,
    ClaimSpecV1,
    ClaimStatusV1,
    CommitmentCardV1,
    fingerprint,
    lock_commitment,
)
from .earned_check_registry import EarnedCheckRegistry, annotate_survived_axes
from .economy import (
    AcceptanceMode,
    BoardDecision,
    ContestedReview,
    DynamicMemory,
    EditorBoard,
    EditorVote,
    EpistemicMarket,
    JurorVote,
    JuryPanel,
    JuryVerdict,
    MemoryEntry,
    PenaltyTier,
    PublicControversyReserve,
    ReserveAllocation,
    ReserveError,
    SettlementReport,
    Stake,
    StakePrediction,
    StakeRole,
)
from .editorial import run_editor_board_votes, run_jury_votes
from .falsifiers import (
    COMMISSIONED_ONLY_PAYLOAD_KEYS,
    COMMISSIONED_ONLY_STRATEGY_KEYS,
    COMPLETENESS_ONLY_GATES,
    DEFAULT_REGISTRY_PATH,
    DEFAULT_STRATEGIES,
    DETERMINISTIC_GATES,
    HARD_STRATEGIES,
    RESULT_PROBE_STRATEGIES,
    FalsifierOutcome,
    build_deterministic_outcome,
    build_falsifier_rubric,
    build_probe_warrant_rubric,
    evaluate_llm_falsifier_axis,
    load_rule_registry,
)
from .hypotheses import HypothesisSpecV1, reasoning_mode_ceiling
from .multiverse import CeilingResult, MultiverseProfile, resolve_multiverse_ceiling
from .neuroprogram import NeuroProgramReportV1, program_ceiling_axis
from .probe_commissioner import ProbeCommissionerProtocol, has_probe_inputs
from .proof_ledger import NeuroProofCertificateV1, ProofLedger, build_certificate

if TYPE_CHECKING:  # avoid importing the supervisor module at conductor import time
    from ..supervisor import SupervisorConfig

logger = logging.getLogger(__name__)

SOCIETY_LEDGER_NAME = "society_commits.jsonl"

PipelineRunner = Callable[["SupervisorConfig", Any], StopArtifact]
CriticRunner = Callable[..., CriticVerdict]
# LLM-backed jury / editor-board runners (society.editorial). Injectable; tests stub
# them and default to the real `run_*` functions.
JuryRunner = Callable[..., list[JurorVote]]
EditorRunner = Callable[..., list[EditorVote]]

# Status ladder, ascending strength. Falsifiers may only push DOWN this ladder.
_LADDER: tuple[ClaimStatusV1, ...] = (
    ClaimStatusV1.rejected,
    ClaimStatusV1.weakened,
    ClaimStatusV1.qualified,
    ClaimStatusV1.supported_within_scope,
)


def _rank(status: ClaimStatusV1) -> int:
    return _LADDER.index(status)


# Evidential strength order, STRONGEST -> WEAKEST, used by the editorial clamp.
# Distinct from ``_LADDER`` (which omits the ``conflicting`` evidential state and is
# ordered weakest-first for the falsifier-downgrade min()): this includes
# ``conflicting`` between ``weakened`` and ``rejected`` per the decided down-only
# rule. ``unresolved`` / ``ill_typed`` are deliberately OFF this ladder — they are
# uninformative for a clamp (a vote of either may never move the status).
_EDITORIAL_STRENGTH: tuple[ClaimStatusV1, ...] = (
    ClaimStatusV1.supported_within_scope,
    ClaimStatusV1.qualified,
    ClaimStatusV1.weakened,
    ClaimStatusV1.conflicting,
    ClaimStatusV1.rejected,
)


# Primary (every-claim mode) strength order, STRONGEST -> WEAKEST. Identical to
# ``_EDITORIAL_STRENGTH`` EXCEPT it APPENDS ``unresolved`` as the weakest admissible
# rung. Rationale: in the opt-in "editorial-every-claim" §13 mode the holistic jury
# runs on EVERY claim and its verdict DRIVES the status (ceiling-capped), so a
# decisive editorial ``unresolved`` is a real, applicable downgrade ("this is an open
# question") rather than the uninformative push it is treated as in the default
# down-only clamp. ``ill_typed`` is STILL off this ladder — it is a structural-only
# verdict that must never be emitted by this evidential layer.
# Support level for the EVERY-CLAIM primary clamp: how SUPPORTED a status is
# (5 = strongest support, 1 = minimal). The ceiling caps how supported the editorial
# verdict may be; a verdict that is NOT more-supported than the ceiling is applied.
# `rejected` and `unresolved` are BOTH minimal-support (a determinate negative vs an
# open question — neither is "more supported" than the other), so a `rejected` verdict
# is NOT capped away by an `unresolved` ceiling (reviewer F3 — previously `unresolved`
# was mis-ordered as strictly weakest, blocking rejection of an unresolved-ceiling
# claim). `ill_typed` is off-scale (structural-only; never emitted by this layer).
_SUPPORT_RANK: dict[ClaimStatusV1, int] = {
    ClaimStatusV1.supported_within_scope: 5,
    ClaimStatusV1.qualified: 4,
    ClaimStatusV1.weakened: 3,
    ClaimStatusV1.conflicting: 2,
    ClaimStatusV1.rejected: 1,
    ClaimStatusV1.unresolved: 1,
}


def _editorial_clamp(
    synthesized: ClaimStatusV1, verdict: ClaimStatusV1
) -> tuple[ClaimStatusV1, bool]:
    """Down-only, ceiling-bound editorial clamp (J1 + J5).

    The synthesized claim-card status is a CEILING: a decisive jury or the editor
    board may only push the status DOWN the evidential strength ladder
    (``supported_within_scope > qualified > weakened > conflicting > rejected``),
    never raise it above the synthesized ceiling.

    Returns ``(status, changed)``:

    * ``verdict`` uninformative (``unresolved`` / ``ill_typed``, i.e. off the
      strength ladder) -> no change, ``(synthesized, False)``.
    * ``verdict`` strictly WEAKER than ``synthesized`` -> lower to ``verdict``,
      ``(verdict, True)``.
    * otherwise (``verdict`` not weaker, or off-ladder) -> no change,
      ``(synthesized, False)``.
    """
    if synthesized not in _EDITORIAL_STRENGTH or verdict not in _EDITORIAL_STRENGTH:
        # Either endpoint off the ladder (e.g. unresolved/ill_typed verdict, or an
        # unresolved synthesized base) is uninformative -> never move the status.
        return synthesized, False
    if _EDITORIAL_STRENGTH.index(verdict) > _EDITORIAL_STRENGTH.index(synthesized):
        # Strictly weaker (later in the strongest-first order) -> lower the ceiling.
        return verdict, True
    return synthesized, False


def _editorial_clamp_primary(
    synthesized: ClaimStatusV1, verdict: ClaimStatusV1
) -> tuple[ClaimStatusV1, bool]:
    """Ceiling-capped editorial clamp for the opt-in EVERY-CLAIM mode.

    Sibling to :func:`_editorial_clamp` used ONLY when
    ``editorial_every_claim=True``. Here the holistic jury (and, on a tie, the board)
    runs on EVERY claim and its aggregated verdict DRIVES the admitted status, subject
    to one ceiling: the verdict may never be STRONGER than the synthesized/multiverse
    ceiling (cap DOWN to the ceiling if so). This differs from the default down-only
    clamp in two ways:

    * the admitted status BECOMES the verdict (when at/below the ceiling), so a
      decisive editorial ``unresolved`` / ``weakened`` / ``qualified`` / ``conflicting``
      / ``rejected`` IS applied — a naive-``supported`` base can be moved to
      ``unresolved`` for an open question. (The default clamp treats ``unresolved`` as
      uninformative and only ever moves the status DOWN, never to ``unresolved``.)
    * ``unresolved`` is a VALID minimal-support verdict (:data:`_SUPPORT_RANK`), at the
      SAME support level as ``rejected`` — so a ``rejected`` verdict is applied (not
      capped) even when the ceiling is ``unresolved``.

    ``ill_typed`` is STILL never emitted (structural-only, off the ladder -> no
    change). A verdict equal to the synthesized status -> no change.

    Returns ``(status, changed)``:

    * ``verdict`` off the ladder (``ill_typed``) or synthesized off the ladder ->
      no change, ``(synthesized, False)``.
    * ``verdict`` MORE-SUPPORTED than ``synthesized`` -> cap to the ceiling,
      ``(synthesized, False)`` (no change, editorial cannot over-claim).
    * ``verdict`` equal to ``synthesized`` -> no change, ``(synthesized, False)``.
    * otherwise (``verdict`` equal-or-lower support AND a different status, i.e. a valid
      downgrade incl. ``unresolved``, and incl. ``rejected`` under an ``unresolved``
      ceiling) -> apply the verdict, ``(verdict, True)``.
    """
    if synthesized not in _SUPPORT_RANK or verdict not in _SUPPORT_RANK:
        # ill_typed (or any off-scale status) is uninformative -> never move.
        return synthesized, False
    if _SUPPORT_RANK[verdict] > _SUPPORT_RANK[synthesized]:
        # Verdict is MORE supported than the ceiling: cap to the ceiling (no over-claim).
        return synthesized, False
    if verdict == synthesized:
        return synthesized, False
    # Verdict is equal-or-lower support and DIFFERENT -> apply it (a real downgrade, or a
    # lateral move within the minimal-support tier, e.g. rejected under unresolved).
    return verdict, True


def _editorial_evidence(claim_card: ClaimCardV1) -> dict[str, Any]:
    """Claim-centered evidence for the holistic editorial jury/board (anti-anchoring).

    Deliberately EXCLUDES the raw pipeline ``results`` bundle (a naive stub that always
    "completes" with a passing score -> reads as "it worked") and the survived/all-clear
    signal. Both anchor the holistic judge toward ``supported`` — confirmed empirically:
    the same jury that votes a reverse-inference trap ``rejected`` 3/3 on the bare claim
    caves to ``supported`` when handed a falsifier "all-clear". So the jury judges the
    CLAIM on its merits, and falsifiers may only ADD genuine concerns (``failed_checks``),
    never present an all-clear the judge anchors on.
    """
    return {
        "claim_text": claim_card.claim_text,
        "scope": claim_card.scope_boundary.model_dump(mode="json"),
        # ONLY genuine refutations (added concerns); NOT survived/all-clear, NOT the
        # naive pipeline result.
        "raised_concerns": list(claim_card.failed_checks),
    }


def _default_pipeline_runner(config: SupervisorConfig, router: Any) -> StopArtifact:
    from ..supervisor import (
        BoundedSupervisor,  # lazy: same package, but keeps import light
    )

    return BoundedSupervisor(config, router=router).run()


# Conventional per-episode credit grants / stake sizes for the in-episode market.
# These are NOT calibrated — cross-episode credit budgets are the caller's
# responsibility (inject a pre-funded EpistemicMarket to carry balances across runs).
# The *_GRANT values are the funding floor the conductor's INTERNAL default market
# tops agents up to (idempotently, only when short); an injected market is never
# auto-funded so its balances are not inflated each episode.
_DEFAULT_AUTHOR_GRANT = 10.0
_DEFAULT_CHALLENGE_GRANT = 10.0
_DEFAULT_AUTHOR_STAKE = 2.0
_DEFAULT_CHALLENGE_STAKE = 1.0


@dataclass
class SocietySettlement:
    """The economy-layer settlement produced for one episode (opt-in).

    Bundles the market settlement, the dynamic-memory admission, the contested-lane
    review flag, and the NeuroProof audit certificate. ``None`` on a ``ConductOutcome``
    when ``enable_settlement`` was not requested.
    """

    report: SettlementReport
    memory_entry: MemoryEntry
    certificate: NeuroProofCertificateV1
    contested: bool
    review: ContestedReview
    settlement_path: Path
    memory_path: Path
    proof_ledger_path: Path
    # Editorial layer (HTML sections 08/09), populated ONLY when a contested claim
    # convened the settlement jury / editor board. Both ``None`` on an uncontested
    # claim (procedural restraint: no convening, no override).
    jury_verdict: JuryVerdict | None = None
    board_decision: BoardDecision | None = None
    # Public controversy reserve (HTML section 08, "资助高价值争议的额外审视"):
    # the grant the FINITE shared reserve made to fund this contested claim's extra
    # (editorial) scrutiny via an INDEPENDENT lineage. ``None`` when no reserve was
    # injected, the claim was uncontested (the reserve refuses non-contested by
    # design), or the reserve refused (depleted / non-independent) — in the last
    # case the scrutiny still ran UNFUNDED (see ``reserve_unfunded``). The reserve
    # NEVER changes the claim status, gates the convening, or vetoes — funding +
    # provenance only.
    reserve_allocation: ReserveAllocation | None = None
    # True iff the claim was contested, a reserve was injected, but the reserve
    # REFUSED the grant (``ReserveError``: depleted / non-independent). The contested
    # scrutiny ran UNFUNDED rather than being skipped (epistemics are not gated on
    # budget). ``False`` whenever an allocation succeeded or no reserve was consulted.
    reserve_unfunded: bool = False


@dataclass
class ConductOutcome:
    commitment: CommitmentCardV1
    claim_card: ClaimCardV1
    stop: StopArtifact
    outcomes: list[FalsifierOutcome]
    ledger_path: Path
    settlement: SocietySettlement | None = None
    # VB-1 — the required-verdict ordering gate. ``blocked`` means a required falsifier axis
    # produced NO verdict, so the claim was REFUSED (``claim_card.status == needs_diagnosis``,
    # written to ``refusal.json`` not ``claim_card.json``); no settlement runs, external
    # dispatch is barred. ``missing_axes`` lists the required gates that never adjudicated.
    blocked: bool = False
    block_reason: str | None = None
    missing_axes: list[str] = field(default_factory=list)
    # VB-2 — the survival-gated SCORE of record (the numeric analog of VB-1). This is the score
    # any consumer that selects, ranks, or reports a claim by magnitude MUST read — NOT the raw
    # supervisor ``best_score`` (which is a pre-falsifier, within-run optimization signal). It is
    # ``None`` when the result did not survive its required battery (or had no score). On a VB-1
    # refusal it is ``None`` and ``survived_required_battery`` is ``False``.
    # NOTE: no in-repo cross-claim selector consumes this yet — surfacing it here is the
    # contract; the consuming selector (e.g. survival-gated ``best_score`` across claims) is the
    # next M-ladder slice, deliberately out of this PR's scope.
    survival_gated_score: float | None = None
    survived_required_battery: bool = False
    survival_gate_reason: str | None = None


def pipeline_base_status(stop: StopArtifact) -> ClaimStatusV1:
    """Map a bare pipeline outcome to a status BEFORE any falsifier downgrade.

    Shared by the conductor (arm c) and the no-society experiment arm (b) so the
    ONLY difference between those two arms is the society layer itself.
    """
    if stop.final_status == "completed":
        return ClaimStatusV1.supported_within_scope
    if stop.last_score is not None and stop.stop_reason != "infra_recovery_failed":
        return ClaimStatusV1.qualified
    return ClaimStatusV1.unresolved


def synthesize_claim_card(
    claim: ClaimSpecV1,
    commitment: CommitmentCardV1,
    stop: StopArtifact,
    outcomes: list[FalsifierOutcome],
    *,
    hypothesis: HypothesisSpecV1 | None = None,
    multiverse_profiles: Sequence[MultiverseProfile] | None = None,
    multiverse_run_id: str | None = None,
    neuroprogram_report: NeuroProgramReportV1 | None = None,
    extra_ceilings: Sequence[CeilingResult] = (),
    require_result_probe: bool = False,
    require_commissioned_probe: bool = False,
    integrity_caps_certification: bool = False,
) -> ClaimCardV1:
    """v0.1 epistemic policy: start from the pipeline outcome, let falsifiers only lower
    confidence. This encodes an editorial status, NOT ground truth.

    When ``hypothesis`` and/or ``multiverse_profiles`` are supplied (the calibrated/empirical
    path), the V-HRL ceiling spine also bounds the base BEFORE the falsifier downgrade:
    ``base = min(pipeline outcome, reasoning_mode(hypothesis), claim_structure(claim),
    multiverse robustness [fail-closed binding])``. With neither supplied, the base is the bare
    pipeline outcome (unchanged behaviour). The composed result is recorded in
    ``extra['calibration']`` for audit. Falsifiers (a separate axis) only lower it further.
    """
    genuine = [o for o in outcomes if not o.degenerate]
    refuting = [o for o in genuine if o.refuted]
    judgment_fails = [o for o in refuting if not o.judgment_passed]
    completeness_only = [
        o for o in refuting if o.judgment_passed and not o.completeness_passed
    ]
    hard_fails = [o for o in judgment_fails if o.hard]

    # Base ceiling from the pipeline arm (shared with the no-society experiment arm).
    pipeline_base = pipeline_base_status(stop)
    calibration: dict[str, Any] = {}

    if pipeline_base is ClaimStatusV1.unresolved:
        # No usable result to support or refute; falsifier attacks are moot.
        status = ClaimStatusV1.unresolved
    else:
        base = pipeline_base
        # V-HRL calibration spine (opt-in): the most conservative structural/evidence ceiling
        # also bounds the base, before falsifiers lower it further.
        if (
            hypothesis is not None
            or multiverse_profiles is not None
            or neuroprogram_report is not None
            or extra_ceilings
        ):
            axes = [claim_structure_ceiling(claim)]
            if hypothesis is not None:
                axes.append(reasoning_mode_ceiling(hypothesis))
            binding_status: str | None = None
            if multiverse_profiles is not None:
                mv_result, binding_status = resolve_multiverse_ceiling(
                    claim_contrast=claim.extra.get("contrast"),
                    multiverse_run_id=multiverse_run_id,
                    profiles=multiverse_profiles,
                )
                axes.append(mv_result)
            if neuroprogram_report is not None:
                # The pre-registered program's verdict bounds the claim too (clamped to the
                # ladder so an off-ladder structural verdict caps, never crashes, the spine).
                axes.append(program_ceiling_axis(neuroprogram_report))
            if extra_ceilings:
                # Caller-supplied ceiling axes (e.g. the episode's resolve_committed_family
                # family-laundering cap) compose into the spine like any other axis.
                axes.extend(extra_ceilings)
            spine = compose_ceilings(axes)
            base = _LADDER[min(_rank(pipeline_base), _rank(spine.status))]
            calibration = {
                "base_before_falsifiers": base.value,
                "binding_axis": spine.display,
                "binding_rationale": spine.rationale,
                "multiverse_binding_status": binding_status,
                "axes": [
                    {"display": a.display, "status": a.status.value} for a in axes
                ],
            }
            if neuroprogram_report is not None:
                # Preserve the FULL (un-clamped) program verdict + pre-registration hash for
                # audit, even though only the clamped status entered the spine.
                calibration["neuroprogram"] = {
                    "program_id": neuroprogram_report.program_id,
                    "status": neuroprogram_report.status.value,
                    "design_status": neuroprogram_report.design_status,
                    "constraints_blocked": neuroprogram_report.constraints_blocked,
                    "commitment_hash": neuroprogram_report.commitment_hash,
                }

        ceiling = ClaimStatusV1.supported_within_scope
        if not genuine:
            # Cheap survival: nobody genuinely attacked -> cannot claim clean support.
            ceiling = ClaimStatusV1.qualified
        if completeness_only and not judgment_fails:
            ceiling = ClaimStatusV1.qualified
        if judgment_fails:
            ceiling = ClaimStatusV1.weakened
        if hard_fails or len(judgment_fails) >= 2:
            ceiling = ClaimStatusV1.rejected
        # L2: no-blind-certification gate (opt-in). A result is not certified
        # ``supported_within_scope`` unless at least one result-probing axis ran
        # (e.g. the ``confound`` strategy).  Method-only attestation stops at
        # ``qualified`` — the institution admits it has not checked result robustness.
        if require_result_probe and ceiling is ClaimStatusV1.supported_within_scope:
            probe_axes = [o for o in genuine if o.strategy in RESULT_PROBE_STRATEGIES]
            if require_commissioned_probe:
                # Provenance is load-bearing: only a society-computed (commissioned)
                # result-probe earns certification. A bare hand-fed pass cannot.
                certified = any(o.provenance == "commissioned" for o in probe_axes)
            else:
                certified = bool(probe_axes)
            if not certified:
                ceiling = ClaimStatusV1.qualified
        # Tamper-evidence cap (opt-in): if ANY genuine outcome was commissioned from raw
        # arrays the integrity scan flagged "suspicious", the claim cannot be certified
        # supported on those inputs — cap at qualified. Plausibility, not truth: this
        # raises the bar against lazy fabrication, it does not prove the data is real.
        if (
            integrity_caps_certification
            and ceiling is ClaimStatusV1.supported_within_scope
            and any(o.integrity == "suspicious" for o in genuine)
        ):
            ceiling = ClaimStatusV1.qualified
        # Non-evaluable result-probe cap (ALWAYS on, not opt-in): if a result-probe was opted
        # into (probe_inputs present) but could not be evaluated (malformed/length-mismatched
        # arrays, or no commissioner configured), the claim must NOT be certified
        # ``supported_within_scope``. The producer asked for a computed probe and we could not
        # compute it; an un-run probe is neither a survival nor a refutation, so it cannot earn
        # clean support (and a hand-fed scalar must not stand in for it). Caps at qualified.
        if ceiling is ClaimStatusV1.supported_within_scope and any(
            o.provenance in NON_EVALUABLE_PROBE_PROVENANCES for o in genuine
        ):
            ceiling = ClaimStatusV1.qualified
        status = _LADDER[min(_rank(base), _rank(ceiling))]

    def _prov_tag(o: FalsifierOutcome) -> str:
        return f" [{o.provenance}]" if o.provenance else ""

    # An opted-into result-probe that could not be evaluated is NOT a survival (it neither
    # survived nor failed). It is excluded here; its non-evaluable state is auditable via
    # probe_provenance[strategy] below.
    survived = [
        f"{o.strategy}: survived{_prov_tag(o)}"
        for o in genuine
        if not o.refuted and o.provenance not in NON_EVALUABLE_PROBE_PROVENANCES
    ]
    failed: list[str] = []
    for o in refuting:
        kind = "judgment" if not o.judgment_passed else "completeness"
        reason = o.reasons[0] if o.reasons else (o.summary or "no reason given")
        failed.append(f"{o.strategy}: {kind} failed{_prov_tag(o)} — {reason}")
    degenerate = [o.strategy for o in outcomes if o.degenerate]
    next_evidence = sorted({a for o in refuting for a in o.required_actions})
    # How each probe verdict was obtained: a set provenance (commissioned /
    # supplied_inconsistent / warrant) for any axis the society computed or warranted,
    # plus an explicit "supplied" for a result-probe axis that ran on a pre-filled scalar.
    probe_provenance: dict[str, str] = {}
    for o in genuine:
        if o.provenance is not None:
            probe_provenance[o.strategy] = o.provenance
        elif o.strategy in RESULT_PROBE_STRATEGIES:
            probe_provenance[o.strategy] = "supplied"
    commissioned_count = sum(1 for v in probe_provenance.values() if v == "commissioned")
    # Tamper-evidence: plausibility verdict of the raw arrays each commissioned probe was
    # computed from (clean/suspicious). Recorded for audit; only caps the status when the
    # conductor was run with integrity_caps_certification.
    probe_integrity = {o.strategy: o.integrity for o in genuine if o.integrity is not None}

    # VB-2: gate the numeric score of record by required-falsifier survival. The status ceiling
    # above already caps the STATUS for any refutation; this withholds the MAGNITUDE so a
    # magnitude-optimizing loop cannot bank a number a required self-falsifier killed. We read
    # the battery from ``commitment.falsifier_battery`` — the hash-locked authoritative copy, the
    # same object the conductor's VB-1 gate resolved over ``outcomes`` (no divergence possible).
    sgs = compute_survival_gated_score(stop.last_score, commitment.falsifier_battery, outcomes)

    return ClaimCardV1(
        claim_id=claim.claim_id,
        claim_text=claim.claim_text,
        status=status,
        scope_boundary=claim.scope_boundary,
        commitment_card_ref=commitment.commitment_id,
        commitment_hash=commitment.commitment_hash,
        evidence_bundle_refs=[p for p in [stop.last_scorer_payload_path] if p],
        survived_checks=survived,
        failed_checks=failed,
        falsification_budget_spent={
            "n_falsifiers": len(outcomes),
            "n_genuine": len(genuine),
            "n_refuting": len(refuting),
            "n_degenerate": len(degenerate),
            "hard_refutations": [o.strategy for o in hard_fails],
            "strategies": [o.strategy for o in outcomes],
            "degenerate_strategies": degenerate,
            "commissioned_probes": commissioned_count,
        },
        probe_provenance=probe_provenance,
        probe_integrity=probe_integrity,
        next_required_evidence=next_evidence,
        survival_gated_score=sgs.gated_score,
        pipeline_summary={
            "final_status": stop.final_status,
            "stop_reason": stop.stop_reason,
            "last_score": stop.last_score,
            "total_cycles": stop.total_cycles,
            "survival_gate": {
                "survived": sgs.survived,
                "reason": sgs.reason,
                "refuting_axes": sgs.refuting_axes,
                "missing_axes": sgs.missing_axes,
            },
        },
        status_not_ground_truth=True,
        extra={"calibration": calibration} if calibration else {},
    )


class SocietyConductor:
    """Wraps a ``BoundedSupervisor`` run with commitment + falsifier institutions."""

    def __init__(
        self,
        *,
        config: SupervisorConfig,
        claim: ClaimSpecV1,
        router: Any,
        strategies: tuple[str, ...] = DEFAULT_STRATEGIES,
        registry_path: str | None = DEFAULT_REGISTRY_PATH,
        critic_model: str = "claude-sonnet-4-6",
        critic_reps: int = 1,
        pipeline_runner: PipelineRunner | None = None,
        critic_runner: CriticRunner = run_independent_critic,
        jury_runner: JuryRunner = run_jury_votes,
        editor_runner: EditorRunner = run_editor_board_votes,
        editorial_model: str = "claude-sonnet-4-6",
        hypothesis: HypothesisSpecV1 | None = None,
        multiverse_profiles: Sequence[MultiverseProfile] | None = None,
        multiverse_run_id: str | None = None,
        neuroprogram_report: NeuroProgramReportV1 | None = None,
        enable_settlement: bool = False,
        market: EpistemicMarket | None = None,
        memory: DynamicMemory | None = None,
        proof_ledger: ProofLedger | None = None,
        calibration_store: CalibrationStore | None = None,
        earned_check_registry: EarnedCheckRegistry | None = None,
        public_reserve: PublicControversyReserve | None = None,
        reserve_lineage_id: str = "public_review",
        editorial_every_claim: bool = False,
        require_result_probe: bool = False,
        probe_commissioner: ProbeCommissionerProtocol | None = None,
        require_commissioned_probe: bool = False,
        integrity_caps_certification: bool = False,
        falsifier_battery: FalsifierBatterySpec | None = None,
        require_committed_hard_axes: bool = False,
    ) -> None:
        if not getattr(config, "state_root", None):
            raise ValueError(
                "SocietyConductor requires config.state_root to be set so the society "
                "ledger path is deterministic and isolated from the supervisor's."
            )
        self._config = config
        self._claim = claim
        self._router = router
        # De-duplicate strategies while preserving order: a repeated strategy
        # would otherwise collide on the per-falsifier ``stake_id`` and double-grant
        # the same agent (H9), and fan out the same falsifier rubric/run twice.
        self._strategies = tuple(dict.fromkeys(strategies))
        self._registry_path = registry_path
        self._critic_model = critic_model
        # Multi-rep majority voting for the nondeterministic LLM falsifier axes (default 1
        # == byte-identical). With reps>1 a hard refute (-> rejected) needs a majority of
        # genuine votes, so one spurious vote on wording cannot drive the status.
        self._critic_reps = max(1, int(critic_reps))
        self._pipeline_runner = pipeline_runner or _default_pipeline_runner
        self._critic_runner = critic_runner
        self._jury_runner = jury_runner
        self._editor_runner = editor_runner
        self._editorial_model = editorial_model
        self._hypothesis = hypothesis
        self._multiverse_profiles = multiverse_profiles
        self._multiverse_run_id = multiverse_run_id
        self._neuroprogram_report = neuroprogram_report
        self._enable_settlement = enable_settlement
        self._market = market
        self._memory = memory
        self._proof_ledger = proof_ledger
        # Per-seat earned calibration tracker (HTML section 09). When injected, each
        # juror/editor's calibration prior is its earned historical accuracy instead
        # of the static DEFAULT_CALIBRATION; default-off (None) is byte-identical.
        self._calibration_store = calibration_store
        # M4 per-AXIS earned-check registry. When injected, each non-blocked episode (a) annotates
        # every SURVIVED axis on the claim card with its HISTORICAL earned status (validated vs
        # gap) and (b) folds this episode's recorded outcomes into the persisted tally. Default-off
        # (None) is byte-identical: no annotation, no registry write. Annotate-only — never changes
        # status, ceilings, or the survived_checks list.
        self._earned_check_registry = earned_check_registry
        # Public controversy reserve (HTML section 08): a FINITE shared pool that funds
        # extra (editorial) scrutiny for CONTESTED claims via an INDEPENDENT lineage.
        # Default-off (None) is byte-identical: the reserve is never consulted. The
        # funding lineage is the INDEPENDENT verification lineage — it must NOT be one
        # of the market stakers (``pipeline`` / ``falsifier_*``) so the reserve's
        # independence cross-check passes. "Controversy buys scrutiny, not veto power."
        self._public_reserve = public_reserve
        self._reserve_lineage_id = reserve_lineage_id
        # Opt-in §13 Option-2 mode (DEFAULT OFF: production byte-for-byte unchanged).
        # When True the holistic editorial jury convenes on EVERY claim (not just
        # contested ones) and its verdict DRIVES the admitted status via the
        # ceiling-capped ``_editorial_clamp_primary`` instead of the default down-only
        # ``_editorial_clamp``. Motivation (validated by data): narrow single-axis
        # falsifiers under-refute (a reverse-inference trap got n_refuting=0, leaving
        # the claim stuck at naive 'supported'), while a holistic jury on the SAME
        # claim votes 'rejected' — so the editorial verdict, not a falsifier
        # refutation, should drive the status.
        self._editorial_every_claim = editorial_every_claim
        # L2: no-blind-certification gate. When True, ``supported_within_scope``
        # requires at least one RESULT_PROBE_STRATEGIES axis to have run. Method-only
        # attestation is capped at ``qualified``. Default False: backwards-compatible.
        self._require_result_probe = require_result_probe
        # Autonomous probe commissioning (default OFF: production byte-identical). When
        # set, a confound gate that would read a (possibly hand-fed) scalar instead has
        # the society RECOMPUTE retained_pct from raw out-of-sample arrays the pipeline
        # emitted. ``require_commissioned_probe`` makes provenance load-bearing: a
        # ``supported_within_scope`` may then be earned only by a genuinely commissioned
        # result-probe, never a bare hand-fed pass.
        self._probe_commissioner = probe_commissioner
        self._require_commissioned_probe = require_commissioned_probe
        # Tamper-evidence cap (opt-in, default OFF): when True a claim whose commissioned
        # probe inputs were flagged plausibility-"suspicious" cannot be certified supported.
        self._integrity_caps_certification = integrity_caps_certification
        # VB-1 required-falsifier battery. Precedence: explicit arg > claim-class registry profile >
        # (opt-in) the committed-hard-axes default. None => no required battery, never refuses on
        # coverage (fully back-compatible). When set, it is hash-locked into the commitment card and
        # a MISSING required verdict REFUSES finalization.
        battery = (
            falsifier_battery
            if falsifier_battery is not None
            else resolve_battery_for_claim(claim)
        )
        # De-dormant default (opt-in via require_committed_hard_axes; production turns it on). For a
        # confirmatory claim with no explicit/registry battery, require the HARD self-falsifier axes
        # within the COMMITTED strategy set — runnable by construction (required ⊆ strategies) so it
        # never bricks, run-mode-adaptive, and enforces "your hard self-falsifiers must adjudicate
        # before you finalize". Default off => byte-identical.
        if battery is None and require_committed_hard_axes:
            battery = derive_default_battery(self._strategies, claim, hard_axes=HARD_STRATEGIES)
        # Surface a misconfiguration: a required axis the conductor will NOT run (e.g. a registry
        # profile requiring deterministic gates this arm never enrolls) can never produce a verdict,
        # so every claim would be refused. Warn loudly rather than silently refuse everything.
        if battery is not None:
            _unrunnable = battery_unrunnable_axes(battery, self._strategies)
            if _unrunnable:
                logger.warning(
                    "society: required falsifier battery %s requires axes not in the committed "
                    "strategy set %s — they cannot produce a verdict, so every claim will be "
                    "REFUSED: %s",
                    battery.battery_id, list(self._strategies), _unrunnable,
                )
        self._falsifier_battery = battery
        self._state_dir = Path(config.state_root).expanduser().resolve()

    def conduct(self) -> ConductOutcome:
        society_dir = self._state_dir / "society"
        rubric_dir = society_dir / "falsifier_rubrics"
        rubric_dir.mkdir(parents=True, exist_ok=True)
        ledger = self._state_dir / SOCIETY_LEDGER_NAME

        # 1. Freeze the falsifier rubrics BEFORE any result exists (rules locked).
        registry = load_rule_registry(self._registry_path)
        rubric_refs: dict[str, dict[str, str]] = {}
        for strategy in self._strategies:
            text = build_falsifier_rubric(strategy, registry)
            path = rubric_dir / f"falsifier_{strategy}.md"
            path.write_text(text, encoding="utf-8")
            rubric_refs[strategy] = {"path": str(path), "hash": fingerprint(text)}

        # 2. Lock the commitment card and append it to the society ledger FIRST.
        #    The required-falsifier battery (VB-1) is hash-locked here too, so the axes the
        #    claim must answer are committed BEFORE any result — they cannot be swapped later.
        commitment = lock_commitment(
            self._claim,
            list(self._strategies),
            rubric_refs,
            falsifier_battery=self._falsifier_battery,
        )
        commitment_path = society_dir / "commitment_card.json"
        commitment_path.write_text(
            commitment.model_dump_json(indent=2), encoding="utf-8"
        )
        self._append_commit(
            ledger,
            stage="commitment",
            inp=self._claim.model_dump(),
            out=commitment.model_dump(),
            artifacts={"commitment_card": str(commitment_path)},
        )

        # 3. Run the pipeline arm as a black box (AFTER commitment is on the ledger).
        stop = self._pipeline_runner(self._config, self._router)

        # 4. Re-verify the commitment FROM DISK (not just the in-memory frozen
        #    object), so any out-of-process edit to commitment_card.json between the
        #    commit and synthesis is caught. This is what makes "commit before
        #    observe" enforced rather than cosmetic.
        reloaded = CommitmentCardV1.model_validate_json(
            commitment_path.read_text(encoding="utf-8")
        )
        if (
            not reloaded.verify_hash()
            or reloaded.commitment_hash != commitment.commitment_hash
        ):
            raise RuntimeError(
                "society: commitment hash mismatch — commitment_card.json changed after locking"
            )

        # 5. Fan out falsifiers using the FROZEN rubrics; record each to the ledger.
        #    L1/L3: strategies in DETERMINISTIC_GATES start with a numeric gate.
        #    When the gate signals probe_missing=True the conductor falls through to
        #    an LLM warrant check (L3) — asking whether a probe was warranted.
        results = self._load_results(stop)
        # Commissioned-only payload keys have NO legitimate producer — a society probe DEFINES
        # them (unlike standard inferential stats like family_block_p, which a real scorer may
        # compute and supply at L1). Strip any hand-fed top-level value so the corresponding
        # gate can ONLY ever read a commissioner-injected one; without a commissioner the gate
        # abstains rather than trusting a hand-fed verdict (closes a laundering vector in the
        # no-commissioner CLI path).
        _sp = results.get("scorer_payload")
        if isinstance(_sp, dict):
            for _k in COMMISSIONED_ONLY_PAYLOAD_KEYS:
                _sp.pop(_k, None)
        results_fp = fingerprint(results)
        outcomes: list[FalsifierOutcome] = []
        for strategy in self._strategies:
            ref = rubric_refs[strategy]
            if strategy in DETERMINISTIC_GATES:
                gate = DETERMINISTIC_GATES[strategy]
                refuted, probe_missing, reason = gate(results)
                # Autonomous probe commissioning: when a commissioner is configured and
                # raw probe inputs are locatable, the society COMPUTES the result-probe
                # from raw arrays instead of trusting (or merely missing) a pre-filled
                # scalar. Triggered on probe_missing OR inputs-present — and regardless of
                # the gate's first verdict, so a hand-fed value cannot launder a verdict in
                # EITHER direction (a hand-fed pass that should fail, or a hand-fed fail
                # that should pass). Falls through unchanged when not applicable.
                commissioned_provenance: str | None = None
                commissioned_integrity: str | None = None
                if self._probe_commissioner is not None and (
                    probe_missing or has_probe_inputs(results.get("scorer_payload"))
                ):
                    probes = self._probe_commissioner.commission(
                        strategy,
                        results,
                        scorer_payload_path=results.get("scorer_payload_path"),
                    )
                    if probes:
                        payload = results.setdefault("scorer_payload", {})
                        for pr in probes:
                            inject = pr.get("scorer_payload_inject")
                            if inject:
                                # Top-level p the gate reads first (permutation_null) —
                                # OVERWRITE any hand-fed value so the gate sees the computed
                                # one. setdefault would leave a hand-fed p winning.
                                for k, v in inject.items():
                                    payload[k] = v
                            else:
                                # Confound probe — append to robustness_probes (the gate
                                # iterates them); == the original .extend, byte-identical.
                                payload.setdefault("robustness_probes", []).append(pr)
                        # Re-run the gate on the injected computed probe(s) (re-binds the
                        # three locals; the recomputed value routes into the L1 else below).
                        refuted, probe_missing, reason = gate(results)
                        commissioned_provenance = probes[0].get("provenance", "commissioned")
                        commissioned_integrity = probes[0].get("integrity")
                        self._append_commit(
                            ledger,
                            stage=f"probe_commission_{strategy}",
                            inp={
                                "strategy": strategy,
                                "inputs_fingerprint": probes[0].get("inputs_fingerprint"),
                                "source": "raw_arrays",
                            },
                            out={
                                "probes": probes,
                                "refuted_after_recompute": refuted,
                                "provenance": commissioned_provenance,
                            },
                            artifacts={},
                        )
                    elif has_probe_inputs(results.get("scorer_payload")):
                        # probe_inputs present (producer opted into the raw-array channel)
                        # but commissioning produced NOTHING (malformed/abstained). Refuse to
                        # honor any hand-fed top-level scalar the gate read in step 1 — else a
                        # malformed-arrays + hand-fed-p payload would launder a verdict in
                        # either direction. When arrays are present the only trustworthy
                        # verdict is a commissioned one; with none, the gate abstains.
                        refuted, probe_missing, reason = (
                            False,
                            False,
                            f"{strategy}: probe_inputs present but commissioning abstained — "
                            "refusing to honor hand-fed scalar(s); gate abstains.",
                        )
                        commissioned_provenance = "commission_abstained_inputs_present"
                elif (
                    has_probe_inputs(results.get("scorer_payload"))
                    and (
                        probe_missing
                        or (
                            strategy in COMMISSIONED_ONLY_STRATEGY_KEYS
                            and not COMMISSIONED_ONLY_STRATEGY_KEYS[strategy].issubset(
                                set((results.get("scorer_payload") or {}).keys())
                            )
                        )
                    )
                ):
                    # Raw probe inputs are present, the deterministic gate has no usable
                    # scalar, and this conductor has no commissioner.
                    # Do not fall through to a warrant pass that would make the axis look like
                    # a clean survival: the producer opted into a society-computed probe, and
                    # without the computing component this axis is non-evaluable.
                    refuted, probe_missing, reason = (
                        False,
                        False,
                        f"{strategy}: probe_inputs present but no probe commissioner is configured — "
                        "gate cannot evaluate the raw-array channel.",
                    )
                    commissioned_provenance = "commission_unavailable_inputs_present"
                if probe_missing and not refuted:
                    # L3: probe absent — run LLM completeness warrant check.
                    # Judgment gate always passes (method is not wrong; probe was
                    # simply not run). Only the completeness gate decides whether the
                    # probe was warranted, producing needs_exploration → qualified.
                    warrant_text = build_probe_warrant_rubric(strategy)
                    warrant_path = rubric_dir / f"falsifier_{strategy}_warrant.md"
                    warrant_path.write_text(warrant_text, encoding="utf-8")
                    warrant_verdict = self._critic_runner(
                        line_id=f"falsifier_{strategy}_warrant:{self._claim.claim_id}",
                        results=results,
                        rubric_path=str(warrant_path),
                        router=self._router,
                        model=self._critic_model,
                    )
                    completeness_ok = bool(warrant_verdict.completeness.passed)
                    w_degenerate = warrant_verdict.summary.startswith(
                        "critic unavailable:"
                    )
                    outcome = FalsifierOutcome(
                        strategy=strategy,
                        refuted=(not completeness_ok) and not w_degenerate,
                        degenerate=w_degenerate,
                        judgment_passed=True,
                        completeness_passed=completeness_ok,
                        decision=(
                            "needs_exploration" if not completeness_ok else "proceed"
                        ),
                        summary=warrant_verdict.summary,
                        reasons=(),
                        required_actions=tuple(
                            warrant_verdict.completeness.required_actions
                        ),
                        rubric_ref=str(warrant_path),
                        hard=False,
                        provenance="warrant",
                    )
                    degenerate = w_degenerate
                    refuted = outcome.refuted
                else:
                    # L1 path: deterministic numeric result.
                    outcome = build_deterministic_outcome(
                        strategy=strategy,
                        refuted=refuted,
                        reason=reason,
                        rubric_ref=ref["path"],
                        hard=strategy in HARD_STRATEGIES,
                        completeness_only=strategy in COMPLETENESS_ONLY_GATES,
                    )
                    degenerate = False
                # Stamp commissioned provenance + raw-array integrity so the claim card can
                # distinguish a society-computed result-probe from a pre-supplied scalar and
                # surface a plausibility (tamper-evidence) verdict on its inputs.
                if commissioned_provenance is not None:
                    outcome = replace(
                        outcome,
                        provenance=commissioned_provenance,
                        integrity=commissioned_integrity,
                    )
            else:
                # LLM-critic path (single source of truth shared with the calibration
                # harness — see falsifiers.evaluate_llm_falsifier_axis).
                outcome = evaluate_llm_falsifier_axis(
                    strategy,
                    results,
                    rubric_path=ref["path"],
                    critic_runner=self._critic_runner,
                    router=self._router,
                    critic_model=self._critic_model,
                    claim_id=self._claim.claim_id,
                    hard=strategy in HARD_STRATEGIES,
                    reps=self._critic_reps,
                )
                refuted = outcome.refuted
                degenerate = outcome.degenerate
            outcomes.append(outcome)
            self._append_commit(
                ledger,
                stage=f"falsifier_{strategy}",
                inp={
                    "strategy": strategy,
                    "rubric_hash": ref["hash"],
                    "results_fingerprint": results_fp,
                },
                out={
                    "refuted": refuted,
                    "degenerate": degenerate,
                    "decision": outcome.decision,
                    "judgment_passed": outcome.judgment_passed,
                    "completeness_passed": outcome.completeness_passed,
                },
                artifacts={"rubric": ref["path"]},
            )

        # 5b. VB-1 — required-falsifier-verdict ordering gate. A required axis that produced
        #     NO verdict (never ran, or infra-degenerate) REFUSES finalization: the claim is
        #     NOT written as a final claim card and no settlement / external dispatch follows.
        #     This is the kernel->institution conversion: "missing required verdict => cannot
        #     finalize". A present *negative* verdict is the opposite case — a real adjudication
        #     that only DOWNGRADES the claim, handled by synthesize_claim_card's ceiling below.
        if self._falsifier_battery is not None:
            battery_status = resolve_battery_status(self._falsifier_battery, outcomes)
            if not battery_status.complete:
                return self._refuse_incomplete_battery(
                    society_dir, ledger, commitment, stop, outcomes,
                    results_fp, battery_status,
                )

        # 6. Synthesize and record the final claim card.
        claim_card = synthesize_claim_card(
            self._claim,
            commitment,
            stop,
            outcomes,
            hypothesis=self._hypothesis,
            multiverse_profiles=self._multiverse_profiles,
            multiverse_run_id=self._multiverse_run_id,
            neuroprogram_report=self._neuroprogram_report,
            require_result_probe=self._require_result_probe,
            require_commissioned_probe=self._require_commissioned_probe,
            integrity_caps_certification=self._integrity_caps_certification,
        )
        # M4: annotate each SURVIVED axis with its HISTORICAL earned status BEFORE writing the
        # card (so the persisted card carries the annotation), reading the registry as it stands
        # PRIOR to this episode — then fold this episode in below. Annotate-only: card.extra only.
        if self._earned_check_registry is not None:
            annotate_survived_axes(claim_card, self._earned_check_registry)

        claim_path = society_dir / "claim_card.json"
        claim_path.write_text(claim_card.model_dump_json(indent=2), encoding="utf-8")
        self._append_commit(
            ledger,
            stage="claim",
            inp={
                "commitment_hash": commitment.commitment_hash,
                "results_fingerprint": results_fp,
            },
            out=claim_card.model_dump(),
            artifacts={"claim_card": str(claim_path)},
        )

        # M4: now fold THIS episode's recorded outcomes (the persisted card) into the per-axis
        # earned-check tally and persist. Derived from the card's recorded falsifier outcomes,
        # never self-reported. Done after annotation so this episode never counts toward its own
        # historical tag.
        if self._earned_check_registry is not None:
            self._earned_check_registry.update_from_card(
                claim_card.model_dump(mode="json"),
                episode_id=commitment.commitment_hash,
            )
            if self._earned_check_registry.path is not None:
                self._earned_check_registry.save()

        # 7. (opt-in) economy settlement: market payout + dynamic-memory admission +
        #    NeuroProof audit certificate. Default-off so the section-13 arm-c comparison
        #    stays a clean "society layer minus economy" baseline.
        settlement: SocietySettlement | None = None
        if self._enable_settlement:
            settlement = self._settle_economy(
                society_dir,
                ledger,
                commitment,
                claim_card,
                outcomes,
                results_fp,
                results,
            )

        # VB-2: surface the survival-gated score of record (computed in synthesize_claim_card,
        # recorded on the card) as a first-class conductor output.
        survival_gate = claim_card.pipeline_summary.get("survival_gate", {})
        return ConductOutcome(
            commitment=commitment,
            claim_card=claim_card,
            stop=stop,
            outcomes=outcomes,
            ledger_path=ledger,
            settlement=settlement,
            survival_gated_score=claim_card.survival_gated_score,
            survived_required_battery=bool(survival_gate.get("survived", False)),
            survival_gate_reason=survival_gate.get("reason"),
        )

    def _refuse_incomplete_battery(
        self,
        society_dir: Path,
        ledger: Path,
        commitment: CommitmentCardV1,
        stop: StopArtifact,
        outcomes: list[FalsifierOutcome],
        results_fp: str,
        battery_status: Any,
    ) -> ConductOutcome:
        """VB-1 refusal: a required falsifier axis produced no verdict.

        Writes ``refusal.json`` (NOT ``claim_card.json``) with a ``needs_diagnosis`` card,
        appends a ``refusal`` ledger line, and returns a ``blocked`` ConductOutcome. No
        settlement runs and no final claim card is produced — the claim is un-finalizable
        until every required axis has adjudicated. ``needs_diagnosis`` is a refusal, not an
        evidential verdict: it says the claim was never properly adjudicated, not that the
        evidence was weak.
        """
        missing = list(battery_status.missing_axes)
        refusal_card = ClaimCardV1(
            claim_id=self._claim.claim_id,
            claim_text=self._claim.claim_text,
            status=ClaimStatusV1.needs_diagnosis,
            scope_boundary=self._claim.scope_boundary,
            commitment_card_ref=commitment.commitment_id,
            commitment_hash=commitment.commitment_hash,
            survived_checks=[a.gate_name for a in battery_status.observed_axes],
            failed_checks=[f"required falsifier verdict missing: {ax}" for ax in missing],
            next_required_evidence=[f"run required falsifier axis: {ax}" for ax in missing],
            falsification_budget_spent={
                "n_falsifiers": len(outcomes),
                "strategies": [o.strategy for o in outcomes],
                "required_battery": (
                    commitment.falsifier_battery.battery_id
                    if commitment.falsifier_battery
                    else None
                ),
                "missing_required_axes": missing,
            },
            pipeline_summary={
                "final_status": stop.final_status,
                "stop_reason": stop.stop_reason,
            },
            extra={
                "refusal": True,
                "refusal_reason": "REQUIRED_FALSIFIER_VERDICT_MISSING",
                "battery_id": battery_status.battery_id,
                "blocking_axes": [a.model_dump() for a in battery_status.blocking_axes],
            },
        )
        refusal_path = society_dir / "refusal.json"
        refusal_path.write_text(refusal_card.model_dump_json(indent=2), encoding="utf-8")
        block_reason = f"REQUIRED_FALSIFIER_VERDICT_MISSING: {missing}"
        self._append_commit(
            ledger,
            stage="refusal",
            inp={
                "commitment_hash": commitment.commitment_hash,
                "results_fingerprint": results_fp,
            },
            out={
                "status": refusal_card.status.value,
                "battery_id": battery_status.battery_id,
                "missing_required_axes": missing,
            },
            artifacts={"refusal": str(refusal_path)},
        )
        return ConductOutcome(
            commitment=commitment,
            claim_card=refusal_card,
            stop=stop,
            outcomes=outcomes,
            ledger_path=ledger,
            settlement=None,
            blocked=True,
            block_reason=block_reason,
            missing_axes=missing,
        )

    @staticmethod
    def _fund_for_stake(market: EpistemicMarket, agent_id: str, floor: float) -> None:
        """Idempotently top an agent up to a funding ``floor``.

        Used only for the conductor's internal default market. Unlike a flat
        ``grant`` every episode (which inflates balances additively), this only adds
        the shortfall when ``balance < floor``, guaranteeing the happy path never
        hits ``InsufficientCreditError`` while keeping balances driven by
        stakes/settlements rather than repeated grants.
        """
        shortfall = float(floor) - market.balance(agent_id)
        if shortfall > 0:
            market.grant(agent_id, shortfall)

    def _settle_economy(
        self,
        society_dir: Path,
        ledger: Path,
        commitment: CommitmentCardV1,
        claim_card: ClaimCardV1,
        outcomes: list[FalsifierOutcome],
        results_fp: str,
        results: dict[str, Any] | None = None,
    ) -> SocietySettlement:
        """Drive the economy layer for one settled claim (HTML sections 08-10).

        The conductor already holds the three roles a market needs: the pipeline arm
        is the *author* (bets the claim ``will_hold``), each falsifier is a *challenger*
        (bets it ``will_fail``), and the synthesized claim card is the settlement. We
        place those stakes, settle them, admit the claim into dynamic-weight memory, and
        emit a tamper-evident NeuroProof audit certificate over the frozen episode inputs.

        Honest scope: in-episode credit grants are conventions (inject a pre-funded
        ``EpistemicMarket`` to carry balances across episodes).

        Editorial convening (HTML sections 08/09): on a CONTESTED proposal the settlement
        jury is convened with real (injected) LLM voters; if its margin indicates a tie
        the Editor Board is convened to break it. The synthesized claim-card status is a
        CEILING: a DECISIVE jury and the Editor Board may only push it DOWN the evidential
        strength ladder (``supported_within_scope > qualified > weakened > conflicting >
        rejected``), NEVER raise it (J1/J5 down-only). When a panel lowers the status the
        claim admits to memory as ``editorial`` at a lower initial weight, with the
        DECIDING panel's hash/marker (the jury verdict's or the board decision's) in the
        immutable origin; otherwise it admits ``rule_based`` at the synthesized ceiling. A
        clear / uncontested claim does NOT convene at all (procedural restraint). When no
        usable runner/router is available — or an injected editorial runner raises — the
        editorial step degrades to no-override / ``rule_based`` admission, and the
        settlement + ledger lines are still written (J2).
        """
        proposal_id = self._claim.claim_id

        # --- market: author (pipeline) vs challengers (falsifiers) ---------------
        # When a market was injected the caller owns funding: do NOT auto-grant, or
        # the injected balances inflate by +grant every episode and prior clawback
        # discipline is nullified (H7). Only the conductor's own internal default
        # market self-funds, and even then idempotently (top-up to cover the stake,
        # never additive) so balances reflect stakes/settlements rather than grants.
        injected = self._market is not None
        market = self._market if injected else EpistemicMarket()
        if not injected:
            self._fund_for_stake(market, "pipeline", _DEFAULT_AUTHOR_GRANT)
        market.place_stake(
            Stake(
                stake_id=f"author:{proposal_id}",
                proposal_id=proposal_id,
                agent_id="pipeline",
                role=StakeRole.author,
                prediction=StakePrediction.will_hold,
                settlement_target=proposal_id,
                amount=_DEFAULT_AUTHOR_STAKE,
                quality=PenaltyTier.reasonable_but_wrong,
                rationale="pipeline arm bets its result holds within scope",
            )
        )
        # Only a falsifier that GENUINELY refuted the claim is a challenger that bets
        # it fails. Falsifiers the claim SURVIVED (or that degenerated, e.g. a dead
        # critic) placed no real challenge and do not stake. This keeps "contested" a
        # genuine support-vs-refutation dispute: a clean survival has zero challenge
        # pressure and is NOT contested, which gates the editorial jury (below) to real
        # disputes only — rather than convening on essentially every episode.
        for o in outcomes:
            if not (o.refuted and not o.degenerate):
                continue
            agent = f"falsifier_{o.strategy}"
            if not injected:
                self._fund_for_stake(market, agent, _DEFAULT_CHALLENGE_GRANT)
            market.place_stake(
                Stake(
                    stake_id=f"challenge:{o.strategy}:{proposal_id}",
                    proposal_id=proposal_id,
                    agent_id=agent,
                    role=StakeRole.challenge,
                    prediction=StakePrediction.will_fail,
                    settlement_target=proposal_id,
                    amount=_DEFAULT_CHALLENGE_STAKE,
                    quality=PenaltyTier.reasonable_but_wrong,
                    rationale=f"falsifier {o.strategy} refuted the claim and bets it fails",
                )
            )
        contested = market.is_contested(proposal_id)
        review = market.contested_review_requirement(proposal_id)

        # --- public controversy reserve (HTML section 08) ------------------------
        # When the claim is CONTESTED and a finite public reserve was injected, draw
        # from it to fund this claim's extra (editorial) scrutiny via the INDEPENDENT
        # ``reserve_lineage_id`` lineage (NOT one of the stakers, so the reserve's
        # independence cross-check passes). MUST run while the stakes are still on the
        # market: ``allocate`` reads ``is_contested`` / support / challenge pressures,
        # which ``settle`` clears below.
        #
        # INVARIANTS (load-bearing): the allocation NEVER changes the claim status,
        # NEVER gates/blocks the editorial convening or settlement, and is NEVER a
        # veto — funding + provenance only, and the pool is FINITE (depletes across
        # episodes when the same reserve is injected). An UNCONTESTED claim never
        # touches the reserve (the reserve refuses non-contested by design). If the
        # reserve REFUSES (depleted / non-independent -> ReserveError) the contested
        # scrutiny still runs UNFUNDED (epistemics are not gated on budget).
        reserve_allocation: ReserveAllocation | None = None
        reserve_unfunded = False
        reserve_balance_after: float | None = None
        if contested and self._public_reserve is not None:
            try:
                reserve_allocation = self._public_reserve.allocate(
                    market,
                    proposal_id,
                    independent_lineage_id=self._reserve_lineage_id,
                    rationale=(
                        "public controversy reserve funds independent scrutiny for a "
                        "contested claim (scrutiny, not veto)"
                    ),
                )
                # Snapshot the post-allocation balance HERE (not at ledger-write time)
                # so the audit value is the balance this episode produced and cannot
                # drift if the shared reserve is mutated by a later/concurrent caller.
                reserve_balance_after = self._public_reserve.balance
            except ReserveError as exc:
                # Depleted / non-independent / (defensively) non-contested: proceed
                # UNFUNDED. Do NOT crash and do NOT skip the contested scrutiny.
                logger.warning(
                    "society: public controversy reserve refused proposal %s; "
                    "contested scrutiny runs UNFUNDED: %s",
                    proposal_id,
                    exc,
                )
                reserve_unfunded = True

        report = market.settle(proposal_id, claim_card)

        # --- editorial convening (HTML sections 08/09) ---------------------------
        # On a CONTESTED proposal, convene the settlement jury (real injected LLM
        # voters); a close jury margin escalates to the Editor Board tie-break. A
        # genuine tie/contest may ADJUST the final status; a clear/uncontested claim
        # never convenes and never overrides the synthesized status.
        jury_verdict, board_decision, admit_card, editorial_decider = (
            self._convene_editorial(
                proposal_id=proposal_id,
                claim_card=claim_card,
                contested=contested,
                market=market,
                results=results or {},
            )
        )

        # --- dynamic-weight memory: admit the settled claim -----------------------
        # Default = rule-based (weight 1.0). The claim is admitted EDITORIALLY (lower
        # initial weight, deciding-panel hash in the immutable origin) ONLY when an
        # editorial panel actually LOWERED the status down the synthesized ceiling
        # (J1/J5): a decisive jury (``editorial_decider`` is the JuryVerdict) or the
        # board tie-break (``editorial_decider`` is the BoardDecision). A board that
        # convened but did NOT lower the status (uninformative / non-weaker verdict)
        # leaves ``editorial_decider`` None -> rule-based admission of the synthesized
        # card. No editorial panel may EVER raise the status (down-only ceiling).
        memory = self._memory if self._memory is not None else DynamicMemory()
        if editorial_decider is not None:
            memory_entry = memory.accept(
                admit_card,
                mode=AcceptanceMode.editorial,
                editor_decision=editorial_decider,
            )
        else:
            memory_entry = memory.accept(admit_card, mode=AcceptanceMode.rule_based)

        # --- NeuroProof audit certificate over the frozen episode inputs ----------
        # ``admit_card`` is the editorially-final card (== claim_card unless the
        # board adjusted the status on a genuine tie/contest).
        report_view = {
            "claim_id": admit_card.claim_id,
            "claim_text": admit_card.claim_text,
            "scope": admit_card.scope_boundary,
            "status": admit_card.status.value,
            "verdict_basis": "society_conductor",
            "backend": "falsifier_population",
            "formalized_claim": None,
            "reproducible_query": None,
        }
        certificate = build_certificate(
            report_view,
            corpus_version="",
            extra_inputs={
                "commitment_hash": commitment.commitment_hash,
                "results_fingerprint": results_fp,
                "n_falsifiers": len(outcomes),
            },
        )
        proof_ledger = (
            self._proof_ledger
            if self._proof_ledger is not None
            else ProofLedger(path=society_dir / "proof_ledger.jsonl")
        )
        proof_ledger.append(certificate)

        # --- artifacts + ledger commit -------------------------------------------
        settlement_path = society_dir / "settlement_report.json"
        settlement_path.write_text(report.model_dump_json(indent=2), encoding="utf-8")
        memory_path = society_dir / "dynamic_memory.json"
        memory_path.write_text(memory.model_dump_json(indent=2), encoding="utf-8")

        # Editorial artifacts + ledger append, written ONLY when the jury / board
        # actually convened (uncontested claims leave no editorial trace).
        settle_artifacts = {
            "settlement_report": str(settlement_path),
            "dynamic_memory": str(memory_path),
            "proof_ledger": str(proof_ledger.path),
        }
        if jury_verdict is not None:
            jury_path = society_dir / "jury_verdict.json"
            jury_path.write_text(
                jury_verdict.model_dump_json(indent=2), encoding="utf-8"
            )
            settle_artifacts["jury_verdict"] = str(jury_path)
        if board_decision is not None:
            board_path = society_dir / "board_decision.json"
            board_path.write_text(
                board_decision.model_dump_json(indent=2), encoding="utf-8"
            )
            settle_artifacts["board_decision"] = str(board_path)
        # Public controversy reserve artifact + ledger line, written ONLY when a grant
        # actually occurred (mirrors the editorial settlement/board records). An
        # uncontested claim, no injected reserve, or a refused (unfunded) grant leaves
        # no reserve artifact.
        if reserve_allocation is not None:
            reserve_path = society_dir / "reserve_allocation.json"
            reserve_path.write_text(
                reserve_allocation.model_dump_json(indent=2), encoding="utf-8"
            )
            settle_artifacts["reserve_allocation"] = str(reserve_path)
            self._append_commit(
                ledger,
                stage="reserve_allocation",
                inp={
                    "proposal_id": proposal_id,
                    "contested": contested,
                    "independent_lineage_id": reserve_allocation.independent_lineage_id,
                },
                out={
                    "amount": reserve_allocation.amount,
                    "contestedness": reserve_allocation.contestedness,
                    "reserve_balance_after": reserve_balance_after,
                },
                artifacts={"reserve_allocation": str(reserve_path)},
            )
        # Editorial ledger line: written whenever the editorial machinery CONVENED
        # (a jury seated), whether or not it escalated to the board. ``triggered_by``
        # records the deciding panel of the admitted status (the board's
        # ``tie_break``/``appeal`` when it lowered, the jury's ``"jury"`` when a
        # decisive jury lowered, else ``None`` — convened but the synthesized ceiling
        # stood). ``status_changed`` distinguishes a real downgrade from a convening
        # that left the ceiling intact (J1/J5 down-only).
        if jury_verdict is not None:
            self._append_commit(
                ledger,
                stage="editorial",
                inp={
                    "proposal_id": proposal_id,
                    "contested": contested,
                    "jury_margin": jury_verdict.margin,
                    "triggered_by": (
                        editorial_decider.triggered_by
                        if editorial_decider is not None
                        else None
                    ),
                },
                out={
                    "jury_verdict": jury_verdict.verdict.value,
                    "board_decision": (
                        board_decision.decision.value
                        if board_decision is not None
                        else None
                    ),
                    "decision_hash": (
                        editorial_decider.decision_hash
                        if editorial_decider is not None
                        else None
                    ),
                    "synthesized_status": claim_card.status.value,
                    "editorial_status": admit_card.status.value,
                    "status_changed": admit_card.status is not claim_card.status,
                },
                artifacts={
                    k: settle_artifacts[k]
                    for k in ("jury_verdict", "board_decision")
                    if k in settle_artifacts
                },
            )

        self._append_commit(
            ledger,
            stage="settlement",
            inp={
                "proposal_id": proposal_id,
                "results_fingerprint": results_fp,
                "contested": contested,
            },
            out={
                "final_status": report.final_status.value,
                "claim_held": report.claim_held,
                "total_clawed_back": report.total_clawed_back,
                "total_redistributed": report.total_redistributed,
                "memory_weight": memory_entry.weight,
                "acceptance_mode": memory_entry.acceptance_mode.value,
                "editorial_status": admit_card.status.value,
                "certificate_hash": certificate.content_hash,
            },
            artifacts=settle_artifacts,
        )

        return SocietySettlement(
            report=report,
            memory_entry=memory_entry,
            certificate=certificate,
            contested=contested,
            review=review,
            settlement_path=settlement_path,
            memory_path=memory_path,
            proof_ledger_path=proof_ledger.path,
            jury_verdict=jury_verdict,
            board_decision=board_decision,
            reserve_allocation=reserve_allocation,
            reserve_unfunded=reserve_unfunded,
        )

    def _convene_editorial(
        self,
        *,
        proposal_id: str,
        claim_card: ClaimCardV1,
        contested: bool,
        market: EpistemicMarket,
        results: dict[str, Any],
    ) -> tuple[
        JuryVerdict | None,
        BoardDecision | None,
        ClaimCardV1,
        BoardDecision | JuryVerdict | None,
    ]:
        """Convene the settlement jury (and, on a tie, the Editor Board) — sections 08/09.

        Returns ``(jury_verdict, board_decision, admit_card, editorial_decider)``.
        DEFAULT MODE: convening happens ONLY on a contested proposal with a usable
        router; an uncontested claim (or no router) returns
        ``(None, None, claim_card, None)`` unchanged — procedural restraint,
        deterministic. EVERY-CLAIM MODE (``editorial_every_claim=True``): the
        ``contested`` gate is skipped so the holistic jury convenes on EVERY claim
        (still requiring a usable router); falsifier findings remain supplementary
        evidence to the jury, not the gate.

        CLAMP SELECTION: default mode uses :func:`_editorial_clamp` (down-only,
        ``unresolved`` uninformative); every-claim mode uses
        :func:`_editorial_clamp_primary` (the verdict DRIVES the status, capped DOWN to
        the ceiling, ``unresolved`` an admissible downgrade). Both NEVER raise the
        status above the synthesized/multiverse ceiling and NEVER emit ``ill_typed``.

        DOWN-ONLY, CEILING-BOUND (J1 + J5): the synthesized status is a CEILING.
        Both a DECISIVE jury and the Editor Board may only push the status DOWN the
        evidential strength ladder (``supported_within_scope > qualified > weakened >
        conflicting > rejected``) via :func:`_editorial_clamp`; neither may EVER raise
        it above the synthesized ceiling. An uninformative verdict (``unresolved`` /
        ``ill_typed``) never moves the status. ``ill_typed`` is additionally
        unreachable from this layer (enforced by :meth:`EditorBoard.decide` /
        :meth:`JuryPanel.deliberate`).

        ``editorial_decider`` is the deciding panel whose hash/marker the caller must
        record in the immutable memory origin when the status was lowered: a
        :class:`BoardDecision` (board tie-break) or a :class:`JuryVerdict` (decisive
        jury). It is ``None`` when nothing lowered the status (rule-based admission at
        the synthesized ceiling).
        """
        # Gate. DEFAULT MODE (procedural restraint): no contest -> no convening, no
        # override. EVERY-CLAIM MODE (opt-in §13 Option-2): the ``contested`` gate is
        # SKIPPED so the holistic jury runs on every claim; a usable router/runners
        # is still REQUIRED (no router -> skip deterministically, matching the
        # falsifier-critic fallback discipline). In both modes a missing router skips.
        if self._router is None:
            return None, None, claim_card, None
        if not self._editorial_every_claim and not contested:
            return None, None, claim_card, None
        # In every-claim mode select the ceiling-capped primary clamp (verdict drives
        # status, capped to the ceiling, ``unresolved`` admissible); otherwise the
        # default down-only clamp (verdict may only lower, ``unresolved`` uninformative).
        clamp = (
            _editorial_clamp_primary
            if self._editorial_every_claim
            else _editorial_clamp
        )

        # 1. Settlement jury — real (injected) LLM voters. Pass the market so
        #    conflict-of-interest exclusion runs (jurors who staked are dropped).
        #    GUARDED (J2): the market is already settled-and-popped by this point;
        #    an injected runner that RAISES must not leave the settlement half-done
        #    with no ledger line. A failed runner degrades to no-editorial ->
        #    rule_based admission of the synthesized card (matching the deliberate
        #    / falsifier-critic fallback discipline), and the settlement + ledger
        #    lines are still written by the caller.
        # Anti-anchoring (confirmed crux): hand the holistic jury a CLAIM-CENTERED
        # bundle (claim + scope + only genuine raised concerns), NOT the naive pipeline
        # ``results`` ("completed, passing score") which imports the lenient falsifiers'
        # all-clear and drags the jury toward ``supported``.
        editorial_evidence = _editorial_evidence(claim_card)
        try:
            juror_votes = list(
                self._jury_runner(
                    claim_card=claim_card,
                    evidence=editorial_evidence,
                    router=self._router,
                    model=self._editorial_model,
                    calibration_store=self._calibration_store,
                )
            )
        except Exception as exc:  # noqa: BLE001 - any runner failure must degrade safely
            logger.warning("society: settlement jury runner failed: %s", exc)
            return None, None, claim_card, None
        if not juror_votes:
            # Degraded jury (e.g. n_jurors=0): nothing to deliberate; do not override.
            return None, None, claim_card, None
        try:
            jury_verdict = JuryPanel().deliberate(market, proposal_id, juror_votes)
        except ValueError as exc:
            # Every juror conflicted / no seatable jury — never crash the settlement.
            logger.warning("society: settlement jury could not seat: %s", exc)
            return None, None, claim_card, None

        # 2. Editor Board — convene ONLY on a tie margin (or explicit appeal).
        board = EditorBoard()
        if not board.should_convene(jury_margin=jury_verdict.margin):
            # Clear jury margin: the jury is DECISIVE and settles it without the
            # board (the board is the tie-break escalation, not a second-guesser).
            # The decisive jury may push the status DOWN the ceiling only (J1); in
            # every-claim mode its verdict DRIVES the status (ceiling-capped).
            status, changed = clamp(claim_card.status, jury_verdict.verdict)
            if changed:
                admit_card = claim_card.model_copy(update={"status": status})
                return jury_verdict, None, admit_card, jury_verdict
            # Verdict not weaker (or uninformative): synthesized ceiling stands.
            return jury_verdict, None, claim_card, None

        # GUARDED (J2): an injected editor runner that RAISES must not crash the
        # already-settled episode. Degrade to no board override (jury verdict still
        # recorded), so the settlement + ledger lines are still written.
        try:
            editor_votes = list(
                self._editor_runner(
                    claim_card=claim_card,
                    evidence=editorial_evidence,
                    router=self._router,
                    model=self._editorial_model,
                    seats=board.seats,
                    calibration_store=self._calibration_store,
                )
            )
        except Exception as exc:  # noqa: BLE001 - any runner failure must degrade safely
            logger.warning("society: editor board runner failed: %s", exc)
            return jury_verdict, None, claim_card, None
        if not editor_votes:
            logger.warning("society: editor board returned no votes; not overriding")
            return jury_verdict, None, claim_card, None
        board_decision = board.decide(
            proposal_id, editor_votes, triggered_by="tie_break"
        )

        # The board is the tie-break escalation and is ALSO clamped down-only against
        # the synthesized ceiling (J5): it may lower the status but never raise it
        # past the ceiling. The board decision is never ill_typed (H2 invariant in
        # EditorBoard.decide); an uninformative/non-weaker board verdict leaves the
        # synthesized status untouched (rule-based admission). In every-claim mode the
        # board decision DRIVES the status (ceiling-capped) via the primary clamp.
        status, changed = clamp(claim_card.status, board_decision.decision)
        if changed:
            admit_card = claim_card.model_copy(update={"status": status})
            return jury_verdict, board_decision, admit_card, board_decision
        return jury_verdict, board_decision, claim_card, None

    def record_editorial_outcome(
        self,
        settlement: SocietySettlement,
        realized_status: ClaimStatusV1,
        *,
        acceptable_alts: Sequence[ClaimStatusV1] = (),
        persist: bool = True,
    ) -> int:
        """Score this episode's editorial votes against a realized status (the SIGNAL).

        This is the OUTCOME hook the calibration store needs: once a realized /
        ground-truth status for the claim becomes known (a replication result, a
        curator adjudication, or the benchmark oracle's ``expected_system_verdict``),
        the caller drives this to grade every juror / editor vote that was cast on
        this settlement and update each seat's earned accuracy.

        A vote is correct iff its ``vote`` matches ``realized_status`` or is in
        ``acceptable_alts``. No signal is fabricated: the caller supplies the realized
        status. Returns the number of votes scored (0 if no editorial panel convened
        or no store is wired). When ``persist`` and the store has a path, the updated
        store is saved.

        NOTE — this is an explicit INTEGRATION POINT, not auto-wired into ``conduct``:
        the conductor produces an *editorial* status, which is NOT ground truth, so it
        must never grade itself. In production the realized signal is the
        DynamicMemory promote/demote (replication) path (``WeightEvent.replication`` /
        ``WeightEvent.failed_replication``); in the benchmark it is the HiddenOracle's
        ``expected_system_verdict``.
        """
        store = self._calibration_store
        if store is None or settlement is None:
            return 0
        votes: list[Any] = []
        if settlement.jury_verdict is not None:
            votes.extend(settlement.jury_verdict.counted_votes)
        if settlement.board_decision is not None:
            votes.extend(settlement.board_decision.votes)
        if not votes:
            return 0
        n = store.record_votes(votes, realized_status, acceptable_alts=acceptable_alts)
        if persist and store.path is not None:
            store.save()
        return n

    def _append_commit(
        self,
        ledger: Path,
        *,
        stage: str,
        inp: Any,
        out: Any,
        artifacts: dict[str, Any] | None = None,
    ) -> None:
        commit = StageCommit(
            line_id=self._config.line_id,
            session_id=self._config.session_id,
            cycle_count=0,
            stage=stage,
            input_fingerprint=fingerprint(inp),
            output_fingerprint=fingerprint(out),
            resume_token={"cycle": 0, "stage": stage},
            artifact_paths=artifacts or {},
        )
        append_jsonl_artifact(ledger, commit)

    def _load_results(self, stop: StopArtifact) -> dict[str, Any]:
        """Build the JSON-safe results dict the falsifiers judge.

        ``StopArtifact`` carries no results payload inline; the rich scorer payload
        lives in a side file (``stop.last_scorer_payload_path``) or in
        ``handoff.json``. Everything returned here must be JSON-serializable, or
        ``run_independent_critic`` will swallow the error and return its fallback.
        """
        results: dict[str, Any] = dict(stop.to_dict())
        payload_path = stop.last_scorer_payload_path
        if payload_path:
            path = Path(payload_path)
            if path.exists():
                try:
                    score_result = json.loads(path.read_text(encoding="utf-8"))
                    results["scorer_payload"] = score_result.get("payload", {})
                    results["final_score"] = score_result.get("score")
                    # Stash the resolved path so the probe commissioner can locate a
                    # co-located probe_inputs side-file (relative to the payload dir).
                    results["scorer_payload_path"] = str(path)
                except Exception as exc:  # pragma: no cover - defensive
                    logger.warning(
                        "society: could not read scorer payload %s: %s", path, exc
                    )
        else:
            handoff = self._state_dir / "handoff.json"
            if handoff.exists():
                try:
                    results["best_results"] = json.loads(
                        handoff.read_text(encoding="utf-8")
                    ).get("best_results")
                except Exception:  # pragma: no cover - defensive
                    pass
        return results
