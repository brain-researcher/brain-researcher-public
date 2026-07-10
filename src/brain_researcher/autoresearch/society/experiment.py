"""Three-arm controlled experiment driver (spec section 13).

Runs every blueprint claim through three arms and scores each against the hidden
oracle, producing the headline comparison:

* ``single_agent``  — baseline 1: one agent reasons and emits a verdict.
* ``no_society``     — baseline 2 (the hardest opponent): the bare pipeline
  (``BoundedSupervisor``) with NO commitment and NO falsifier population. Its
  status is ``pipeline_base_status`` with no downgrade, so it cannot catch a trap.
* ``full_society``   — treatment: the ``SocietyConductor``.

The thesis (section 13): if ``full_society`` cannot beat ``no_society`` — especially
on the trap gold line (``severity_weighted_error`` and ``risk_detection``) — the
society layer is decoration.

Each arm is an injected ``ArmRunner`` callable, so the harness is deterministic and
testable; the real run just supplies router-backed runners. The arms share
``pipeline_base_status`` and the same per-claim ``SupervisorConfig`` factory, so the
only difference between arm (b) and arm (c) is the society layer.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, Field

from .blueprint import AgentFacingClaimV1, Blueprint, HiddenOracleV1
from .cards import ClaimCardV1, ClaimStatusV1, ScopeBoundaryV1
from .conductor import pipeline_base_status
from .editorial import run_editor_board_votes, run_jury_votes
from .evaluate import EpisodeScore, detected_risks, score_episode
from .falsifiers import DEFAULT_REGISTRY_PATH, DEFAULT_STRATEGIES

if TYPE_CHECKING:  # heavy / service-adjacent imports stay lazy
    from ..critic import CriticVerdict
    from ..state_contract import StopArtifact
    from ..supervisor import SupervisorConfig
    from .calibration_store import CalibrationStore
    from .conductor import (
        EditorRunner,
        JuryRunner,
        SocietyConductor,
        SocietySettlement,
    )
    from .economy import EpistemicMarket, PublicControversyReserve

SINGLE_AGENT = "single_agent"
NO_SOCIETY = "no_society"
FULL_SOCIETY = "full_society"
ARM_ORDER = (SINGLE_AGENT, NO_SOCIETY, FULL_SOCIETY)


class ArmResult(BaseModel):
    claim_id: str
    arm: str
    status: ClaimStatusV1
    detected_risks: list[str] = Field(default_factory=list)
    detail: dict[str, Any] = Field(default_factory=dict)


# An arm maps an agent-facing claim (the only layer arms ever see) to a result.
ArmRunner = Callable[[AgentFacingClaimV1], ArmResult]
ConfigForClaim = Callable[[AgentFacingClaimV1], "SupervisorConfig"]
PipelineRunner = Callable[["SupervisorConfig", Any], "StopArtifact"]
CriticRunner = Callable[..., "CriticVerdict"]


@dataclass
class EditorialEpisode:
    """The conductor + its settlement for ONE society-arm episode (a side-channel).

    The arm runner records this per claim so the experiment DRIVER (which alone may
    see the oracle) can grade the episode's editorial votes against the realized
    status AFTER scoring — :meth:`SocietyConductor.record_editorial_outcome`. The arm
    runner itself never sees the oracle, so this carries no ground-truth: it is just a
    handle on the institution that ran, so the no-self-grade invariant is preserved
    (the conductor never grades its own editorial verdict; only the evaluator, which
    legitimately knows the oracle, feeds the realized status).
    """

    conductor: "SocietyConductor"
    settlement: "SocietySettlement | None"


class SocietyArmRunner:
    """Callable arm runner that ALSO exposes each episode's editorial side-channel.

    Behaves exactly like a plain ``ArmRunner`` (``runner(claim) -> ArmResult``) so the
    driver treats every arm uniformly, but additionally records, per claim, the
    :class:`EditorialEpisode` (conductor + settlement) it produced. The driver detects
    this attribute after scoring and feeds the hidden oracle's realized verdict to each
    episode's calibration store — the ONLY place the oracle is allowed to touch the
    society layer.
    """

    def __init__(self, run: ArmRunner | None = None) -> None:
        self._run = run
        self.episodes: dict[str, EditorialEpisode] = {}

    def __call__(self, claim: AgentFacingClaimV1) -> ArmResult:
        if self._run is None:  # pragma: no cover - defensive: misconstructed runner
            raise RuntimeError("SocietyArmRunner has no run function bound")
        return self._run(claim)


def arm_result_to_card(result: ArmResult) -> ClaimCardV1:
    """Wrap an ArmResult as a minimal ClaimCardV1 so the existing evaluator scores it."""
    return ClaimCardV1(
        claim_id=result.claim_id,
        claim_text="",
        status=result.status,
        scope_boundary=ScopeBoundaryV1(),
        commitment_card_ref=f"arm:{result.arm}",
        commitment_hash="-",
        failed_checks=[f"{axis}: detected by {result.arm}" for axis in result.detected_risks],
    )


def checklist_findings_to_status(
    findings: list[dict[str, Any]],
) -> tuple[ClaimStatusV1, list[str]]:
    """Map BR review-checklist findings on a method record to a status + detected risks.

    Pure (no service imports) so it is unit-testable; the CLI builds the real findings
    via ReviewRuleEngine and passes them here as plain dicts {severity, action,
    reason_tags}. For a claim UNDER REVIEW: a block/error means the method is rejected;
    a warning weakens it; NO finding means the checklist let it pass (so a trap that
    produces no finding silently survives as supported — the failure the experiment
    measures).
    """
    if not findings:
        return ClaimStatusV1.supported_within_scope, []
    severities = {str(f.get("severity")) for f in findings}
    actions = {str(f.get("action")) for f in findings}
    risks = sorted({t for f in findings for t in (f.get("reason_tags") or [])})
    if severities & {"error", "critical"} or actions & {"block", "block_claim", "raise"}:
        return ClaimStatusV1.rejected, risks
    return ClaimStatusV1.weakened, risks


class ThreeArmReport(BaseModel):
    blueprint_id: str
    n_claims: int
    arms: dict[str, EpisodeScore] = Field(default_factory=dict)
    results: dict[str, list[ArmResult]] = Field(default_factory=dict)

    def to_table(self) -> str:
        """Render the headline comparison as a markdown table."""
        header = [
            "arm",
            "status_agreement",
            "severity(tier-wtd)",
            "risk_detection",
            "trap_agreement",
            "trap_severity",
        ]
        lines = ["| " + " | ".join(header) + " |", "|" + "|".join(["---"] * len(header)) + "|"]
        for arm in ARM_ORDER:
            score = self.arms.get(arm)
            if score is None:
                continue
            trap = score.per_type.get("trap")
            rd = "n/a" if score.risk_detection_mean is None else f"{score.risk_detection_mean:.2f}"
            trap_agree = f"{trap['status_agreement']:.2f}" if trap else "n/a"
            trap_sev = f"{trap['severity_mean']:.2f}" if trap else "n/a"
            lines.append(
                "| "
                + " | ".join(
                    [
                        arm,
                        f"{score.status_agreement:.2f}",
                        f"{score.tier_weighted_severity:.2f}",
                        rd,
                        trap_agree,
                        trap_sev,
                    ]
                )
                + " |"
            )
        return "\n".join(lines)


def feed_oracle_to_calibration(
    runner: ArmRunner,
    oracle: dict[str, HiddenOracleV1],
) -> int:
    """Feed the hidden oracle's realized verdict into the society arm's calibration.

    This is the LOAD-BEARING no-self-grade seam. It runs at the EVALUATOR / DRIVER
    level — which legitimately knows the oracle — NOT inside the arm runner. For each
    episode the society arm recorded, it calls
    :meth:`SocietyConductor.record_editorial_outcome` with the realized status =
    ``oracle.expected_system_verdict`` (and ``acceptable_alts =
    oracle.acceptable_alt_verdicts``), so every juror / editor that voted with the
    oracle gains earned calibration weight and every seat that voted against it loses
    weight. Returns the total number of editorial votes scored across all episodes.

    A non-society runner (no ``episodes`` attribute) is a no-op (returns 0): the oracle
    NEVER reaches arm (a) or arm (b), nor the conductor / arm runner. The conductor's
    editorial verdict is not ground truth — only the oracle is — so only this driver
    hook may supply the realized signal.
    """
    episodes = getattr(runner, "episodes", None)
    if not episodes:
        return 0
    scored = 0
    for claim_id, episode in episodes.items():
        entry = oracle.get(claim_id)
        if entry is None or episode.settlement is None:
            continue
        scored += episode.conductor.record_editorial_outcome(
            episode.settlement,
            realized_status=entry.expected_system_verdict,
            acceptable_alts=entry.acceptable_alt_verdicts,
        )
    return scored


def run_three_arm_experiment(
    blueprint: Blueprint, runners: dict[str, ArmRunner]
) -> ThreeArmReport:
    """Run each arm over every claim and score it against the hidden oracle.

    After scoring, the hidden oracle's realized verdict is fed to any society arm's
    calibration store via :func:`feed_oracle_to_calibration` — at the DRIVER level, the
    only place the oracle may touch the society layer (no self-grade).
    """
    oracle = blueprint.oracle()
    agent_claims = blueprint.agent_facing()
    report = ThreeArmReport(blueprint_id=blueprint.blueprint_id, n_claims=len(agent_claims))
    for arm, runner in runners.items():
        results = [runner(claim) for claim in agent_claims]
        report.results[arm] = results
        cards = {r.claim_id: arm_result_to_card(r) for r in results}
        report.arms[arm] = score_episode(cards, oracle)
        # Oracle -> calibration feed (evaluator level, AFTER scoring, never in the arm).
        feed_oracle_to_calibration(runner, oracle)
    return report


# --------------------------------------------------------------------------- #
# real arm-runner factories (router/pipeline injected; defaults wire the real ones)
# --------------------------------------------------------------------------- #
def make_no_society_runner(
    config_for: ConfigForClaim,
    *,
    router: Any = None,
    pipeline_runner: PipelineRunner | None = None,
) -> ArmRunner:
    """Arm (b): bare pipeline, no commitment, no falsifiers (cannot downgrade a trap)."""

    def _run(claim: AgentFacingClaimV1) -> ArmResult:
        config = config_for(claim)
        if pipeline_runner is not None:
            stop = pipeline_runner(config, router)
        else:
            from ..supervisor import BoundedSupervisor

            stop = BoundedSupervisor(config, router=router).run()
        return ArmResult(
            claim_id=claim.claim_id,
            arm=NO_SOCIETY,
            status=pipeline_base_status(stop),
            detected_risks=[],  # no falsifier population -> nothing is flagged
            detail={
                "final_status": stop.final_status,
                "stop_reason": stop.stop_reason,
                "last_score": stop.last_score,
            },
        )

    return _run


def make_society_runner(
    config_for: ConfigForClaim,
    *,
    router: Any,
    strategies: tuple[str, ...] = DEFAULT_STRATEGIES,
    registry_path: str | None = DEFAULT_REGISTRY_PATH,
    critic_model: str = "claude-sonnet-4-6",
    pipeline_runner: PipelineRunner | None = None,
    critic_runner: CriticRunner | None = None,
    enable_settlement: bool = True,
    market: "EpistemicMarket | None" = None,
    public_reserve: "PublicControversyReserve | None" = None,
    calibration_store: "CalibrationStore | None" = None,
    jury_runner: "JuryRunner | None" = None,
    editor_runner: "EditorRunner | None" = None,
    editorial_model: str = "claude-sonnet-4-6",
    reserve_lineage_id: str = "public_review",
    editorial_every_claim: bool = False,
) -> SocietyArmRunner:
    """Arm (c): the full SocietyConductor, now running the BUILT institution.

    Unlike arm (b), this arm EXERCISES the settlement + editorial jury/board + reserve
    + calibration the experiment is meant to evaluate: ``enable_settlement`` defaults
    to ``True`` and the conductor is wired with an injected ``market``, optional
    ``public_reserve``, ``calibration_store``, and ``jury_runner`` / ``editor_runner``.

    The jury / editor runners DEFAULT to the real LLM-backed
    :func:`run_jury_votes` / :func:`run_editor_board_votes`, but are INJECTABLE so the
    three-arm experiment runs fully deterministically in CI with stubbed votes (no
    network). When ``market`` is ``None`` (the default) the conductor builds and
    SELF-FUNDS a fresh internal per-episode market — the right reproducible default,
    since an injected market is shared across claims and never auto-funded (the caller
    owns its funding). Inject a pre-funded market only to carry balances across claims.

    ``editorial_every_claim`` (default ``False``) opts into the §13 Option-2 mode: the
    holistic editorial jury convenes on EVERY claim (not just contested ones) and its
    verdict drives the ceiling-capped status. The §13 run passes ``True``; left
    ``False`` the arm behaves exactly as before (contested-gated convening).

    The returned :class:`SocietyArmRunner` is a drop-in ``ArmRunner`` that ALSO records
    each episode's :class:`EditorialEpisode` (conductor + settlement) keyed by claim id.
    The DRIVER reads that side-channel after scoring to feed the oracle's realized
    verdict into the calibration store (the no-self-grade invariant: the arm runner
    never sees the oracle and never grades itself).
    """
    jury = jury_runner if jury_runner is not None else run_jury_votes
    editor = editor_runner if editor_runner is not None else run_editor_board_votes
    runner = SocietyArmRunner()

    def _run(claim: AgentFacingClaimV1) -> ArmResult:
        from .conductor import SocietyConductor

        kwargs: dict[str, Any] = dict(
            config=config_for(claim),
            claim=claim.to_claim_spec(),
            router=router,
            strategies=strategies,
            registry_path=registry_path,
            critic_model=critic_model,
            pipeline_runner=pipeline_runner,
            jury_runner=jury,
            editor_runner=editor,
            editorial_model=editorial_model,
            enable_settlement=enable_settlement,
            # market=None lets the conductor build + self-fund a fresh per-episode
            # market; an injected market is shared and never auto-funded (caller-owned).
            market=market,
            public_reserve=public_reserve,
            calibration_store=calibration_store,
            reserve_lineage_id=reserve_lineage_id,
            # Opt-in §13 Option-2 (default OFF): run the holistic editorial jury on
            # EVERY claim and let its verdict drive the (ceiling-capped) status.
            editorial_every_claim=editorial_every_claim,
        )
        if critic_runner is not None:
            kwargs["critic_runner"] = critic_runner
        conductor = SocietyConductor(**kwargs)
        outcome = conductor.conduct()
        card = outcome.claim_card
        settlement = outcome.settlement
        # The arm's reported status is the institution's FINAL editorial status when a
        # settlement ran: the editorial jury / board may push the synthesized ceiling
        # DOWN (J1/J5 down-only). ``memory_entry.entered_status`` is the immutable
        # editorially-final status (== synthesized when no panel lowered it), read via
        # the public settlement surface (no conductor internals touched). Without a
        # settlement (e.g. enable_settlement=False) the synthesized card status stands.
        synthesized_status = card.status
        if settlement is not None:
            status = settlement.memory_entry.entered_status
        else:
            status = synthesized_status
        # Side-channel: stash the conductor + settlement so the DRIVER can feed the
        # oracle's realized verdict AFTER scoring (never the arm runner — no self-grade).
        runner.episodes[claim.claim_id] = EditorialEpisode(
            conductor=conductor, settlement=settlement
        )
        return ArmResult(
            claim_id=claim.claim_id,
            arm=FULL_SOCIETY,
            status=status,
            detected_risks=detected_risks(card),
            detail={
                "survived": card.survived_checks,
                "failed": card.failed_checks,
                "falsification_budget_spent": card.falsification_budget_spent,
                "settlement_ran": settlement is not None,
                "contested": (settlement.contested if settlement is not None else False),
                "synthesized_status": synthesized_status.value,
                "editorial_status": status.value,
                "editorial_downgrade": status is not synthesized_status,
            },
        )

    runner._run = _run
    return runner


def make_single_agent_runner(
    status_fn: Callable[[AgentFacingClaimV1], tuple[ClaimStatusV1, list[str]]],
) -> ArmRunner:
    """Arm (a): a single agent emits a verdict.

    The faithful implementation plugs the existing single BR agent into
    ``status_fn`` (claim -> (status, detected_risks)); the harness stays agnostic.
    """

    def _run(claim: AgentFacingClaimV1) -> ArmResult:
        status, risks = status_fn(claim)
        return ArmResult(
            claim_id=claim.claim_id, arm=SINGLE_AGENT, status=status, detected_risks=list(risks)
        )

    return _run
