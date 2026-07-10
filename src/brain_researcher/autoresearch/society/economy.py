"""In-memory epistemic economy skeleton (HTML sections 08-10).

**v0 scope.** This module is an *in-memory mechanism skeleton* that realizes the
three governance layers the implementation-status ledger marks as Spec-only
(``docs/specs/br_society_implementation_status.md`` section 9, "market / Editor
Board / penalties / dynamic-weight memory are NOT implemented"):

* section 08 — Epistemic Compute Market ("下注，而非请求"): a tri-stake market over a
  scarce credit budget, where staking spends credit and every stake carries a
  prediction + a settlement target.
* section 09 — Scientific Review Settlement ("惩罚坏的认识论行为"): settle stakes by
  whether each prediction matched the final claim-card status, paying winners and
  clawing back losers under three penalty tiers, with a 3-member Editor Board that
  only acts on tie-break / appeal and aggregates by calibration x confidence
  (never by reputation).
* section 10 — KG Retention / Dynamic Memory ("动态权重的记忆"): a dynamic-weight
  memory where a claim enters via rule-based OR editorial acceptance (the latter
  flagged + lower initial weight), weight promotes/demotes on replication or
  contradiction, and the immutable origin tag is NEVER erased.

It is deliberately NOT a production settlement service: no DB, no network, no
distributed ledger, no real compute accounting. It is pure-python, deterministic,
in-memory, with optional JSON snapshot persistence. It *consumes* a
``ClaimCardV1`` status (it does not modify the conductor or card behavior); the
conductor may add a thin optional hook that hands its final card here.

Nothing here imports the service tier, so it is safe inside ``autoresearch``.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from enum import Enum
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .cards import ClaimCardV1, ClaimStatusV1, _utc_now, fingerprint

# ---------------------------------------------------------------------------
# section 08 — tri-stake market
# ---------------------------------------------------------------------------


class StakeRole(str, Enum):
    """Which side of a proposal a stake is taking (HTML Fig 07)."""

    author = "author_stake"  # proposer bets on their own proposal
    support = "support_stake"  # others bet "it will hold"
    challenge = "challenge_stake"  # bets "it will fail" — buys scrutiny, NOT veto


class StakePrediction(str, Enum):
    """The predicted *direction* of the eventual claim-card settlement.

    A stake predicts whether the claim will end up holding within scope or not.
    Settlement (section 09) compares this against the realized ``ClaimStatusV1``.
    """

    will_hold = "will_hold"  # predicts supported_within_scope / qualified
    will_fail = "will_fail"  # predicts rejected / weakened / conflicting


# Which final claim-card statuses count as the claim "holding". `unresolved` is
# deliberately neither (a void / push) — it does not vindicate either side.
_HOLDS: frozenset[ClaimStatusV1] = frozenset(
    {ClaimStatusV1.supported_within_scope, ClaimStatusV1.qualified}
)
_FAILS: frozenset[ClaimStatusV1] = frozenset(
    {ClaimStatusV1.rejected, ClaimStatusV1.weakened, ClaimStatusV1.conflicting}
)


# Explicit strength ladder for *evidential* decision tie-breaking, strongest
# first. It is defined independently of ``ClaimStatusV1`` *declaration* order so
# that a weight tie always resolves toward the STRONGER (more decisive)
# evidential status. Two members are deliberately EXCLUDED:
#   * ``ill_typed`` — a structural-only verdict produced solely by
#     ``neuroclaim_compile``; the evidence/decision layer must NEVER emit it.
#   * ``unresolved`` — a non-evidential void/push; it is the safe fallback when
#     a tie has no defined evidential candidate, but is never *preferred* over
#     one in a tie-break.
# A status not in this map ranks below every listed one (treated as weakest), so
# a tie among undefined/degenerate statuses falls back to ``unresolved`` rather
# than ever selecting ``ill_typed``.
_DECISION_LADDER: tuple[ClaimStatusV1, ...] = (
    ClaimStatusV1.supported_within_scope,
    ClaimStatusV1.qualified,
    ClaimStatusV1.weakened,
    ClaimStatusV1.conflicting,
    ClaimStatusV1.rejected,
)
# Higher score == stronger / more preferred on a weight tie.
_DECISION_LADDER_RANK: dict[ClaimStatusV1, int] = {
    status: len(_DECISION_LADDER) - i for i, status in enumerate(_DECISION_LADDER)
}


def _decision_tiebreak_rank(status: ClaimStatusV1) -> int:
    """Tie-break score for a decision status: higher == stronger evidential status.

    Statuses absent from :data:`_DECISION_LADDER` (``unresolved``, ``ill_typed``)
    score ``0`` so a defined evidential status always wins a weight tie against
    them, and a tie among only-undefined statuses never *prefers* ``ill_typed``.
    """
    return _DECISION_LADDER_RANK.get(status, 0)


def _resolve_decision_tie(
    tally: dict[ClaimStatusV1, float],
) -> ClaimStatusV1:
    """Pick the winning status from a weight ``tally`` (decision/jury layer).

    Highest total weight wins; weight ties resolve toward the STRONGER evidential
    status per :data:`_DECISION_LADDER`. If the weight-tied front-runners are all
    non-evidential (``unresolved``/``ill_typed`` — rank 0), the result is forced
    to ``unresolved`` so ``ill_typed`` can NEVER be emitted by the evidence layer.
    """
    winner = max(
        tally.items(), key=lambda kv: (kv[1], _decision_tiebreak_rank(kv[0]))
    )[0]
    if _decision_tiebreak_rank(winner) == 0:
        return ClaimStatusV1.unresolved
    return winner


class PenaltyTier(str, Enum):
    """Settlement penalty tiers (HTML section 09, "惩罚坏的认识论行为").

    Penalty escalates by the *quality of the epistemic behavior*, not merely by
    being wrong: a reasonable-but-wrong bet is cheap; manipulation is expensive.
    """

    reasonable_but_wrong = "reasonable_but_wrong"  # small
    sloppy = "sloppy"  # medium — under-evidenced / careless
    evidence_violating = "evidence_violating"  # large — manipulation / evidence breach


# Fraction of a losing stake that is clawed back, by tier. A winning stake is
# always returned in full plus its share of the loser pool (see `settle`).
PENALTY_FRACTION: dict[PenaltyTier, float] = {
    PenaltyTier.reasonable_but_wrong: 0.25,
    PenaltyTier.sloppy: 0.50,
    PenaltyTier.evidence_violating: 1.00,
}


class Stake(BaseModel):
    """A single bet against a proposal (HTML section 08).

    Every stake MUST carry a ``prediction`` and a ``settlement_target`` — the
    artifact / claim whose final status will settle the bet ("stake 须附
    settlement target"). A stake without a settlement target is rejected at
    construction. Staking spends scarce credit (the editor is the one exception:
    the Editor "bets authority, not credit", so editor stakes are not minted
    here — see :class:`EditorBoard`).
    """

    model_config = ConfigDict(frozen=True)

    schema_version: Literal["stake-v1"] = "stake-v1"
    stake_id: str
    proposal_id: str
    agent_id: str
    role: StakeRole
    prediction: StakePrediction
    settlement_target: str  # claim_id / artifact id this bet settles against
    amount: float = Field(gt=0.0)
    # Declared/observed epistemic quality of THIS bet — drives the penalty tier on
    # a loss. Defaults to the most lenient tier.
    quality: PenaltyTier = PenaltyTier.reasonable_but_wrong
    rationale: str | None = None
    placed_at: str = Field(default_factory=_utc_now)

    @model_validator(mode="after")
    def _require_settlement_target(self) -> "Stake":
        if not str(self.settlement_target).strip():
            raise ValueError(
                "stake must carry a non-empty settlement_target "
                "(HTML section 08: 'stake 须附 settlement target')"
            )
        return self


class InsufficientCreditError(RuntimeError):
    """Raised when an agent tries to stake more credit than it holds."""


class SettlementOutcome(BaseModel):
    """Per-stake result of settling a proposal (HTML section 09)."""

    stake_id: str
    agent_id: str
    role: StakeRole
    won: bool
    amount_staked: float
    payout: float  # total credit returned to the agent for this stake
    net: float  # payout - amount_staked (>=0 win, <0 loss)
    penalty_tier: PenaltyTier | None = None  # only set on a loss


class SettlementReport(BaseModel):
    """Aggregate result of settling all stakes on one proposal."""

    proposal_id: str
    settlement_target: str
    final_status: ClaimStatusV1
    claim_held: bool | None  # None == void (unresolved): neither side vindicated
    contested: bool
    outcomes: list[SettlementOutcome] = Field(default_factory=list)
    total_clawed_back: float = 0.0
    total_redistributed: float = 0.0
    # Clawed-back credit that could not be redistributed because there were no
    # winners. Burning (rather than silently dropping) keeps the conservation
    # invariant auditable: clawed_back == redistributed + burned, and
    # sum(credit after) + total_burned == sum(credit before).
    total_burned: float = 0.0
    settled_at: str = Field(default_factory=_utc_now)


class EpistemicMarket(BaseModel):
    """Scarce-credit tri-stake market over proposals (HTML section 08).

    Holds a per-agent credit ledger and the open stakes on each proposal.
    ``place_stake`` debits credit immediately (staking is spending, not
    requesting); ``settle`` pays winners and claws back losers under the
    penalty tiers, returning the freed credit to agents.
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)

    credit: dict[str, float] = Field(default_factory=dict)
    stakes: dict[str, list[Stake]] = Field(default_factory=dict)  # proposal_id -> stakes
    # Contested-lane detection thresholds (HTML section 08). Conventions, not tuned.
    contested_min_support: float = 1.0
    contested_min_challenge: float = 1.0
    # If |support - challenge| exceeds this fraction of the larger side, the sides
    # are treated as "cancelling" and the proposal is NOT contested.
    contested_cancel_ratio: float = 0.5

    def grant(self, agent_id: str, amount: float) -> float:
        """Add credit to an agent (e.g. initial endowment). Returns new balance."""
        self.credit[agent_id] = self.credit.get(agent_id, 0.0) + float(amount)
        return self.credit[agent_id]

    def balance(self, agent_id: str) -> float:
        return self.credit.get(agent_id, 0.0)

    def place_stake(self, stake: Stake) -> Stake:
        """Place a stake, debiting the agent's credit.

        Raises :class:`InsufficientCreditError` if the agent cannot cover it. The
        ``Stake`` model already rejects a missing settlement target at construction.
        """
        bal = self.credit.get(stake.agent_id, 0.0)
        if stake.amount > bal:
            raise InsufficientCreditError(
                f"agent {stake.agent_id!r} has {bal} credit, "
                f"cannot stake {stake.amount}"
            )
        self.credit[stake.agent_id] = bal - stake.amount
        self.stakes.setdefault(stake.proposal_id, []).append(stake)
        return stake

    # --- contested lane (HTML section 08) --------------------------------------

    def support_pressure(self, proposal_id: str) -> float:
        return sum(
            s.amount
            for s in self.stakes.get(proposal_id, [])
            if s.role in (StakeRole.author, StakeRole.support)
        )

    def challenge_pressure(self, proposal_id: str) -> float:
        return sum(
            s.amount
            for s in self.stakes.get(proposal_id, [])
            if s.role is StakeRole.challenge
        )

    def is_contested(self, proposal_id: str) -> bool:
        """High support AND high challenge that do NOT cancel (HTML section 08).

        Challenge alone never makes a proposal contested or rejected — it must be
        met by comparable support. "Controversy buys scrutiny, not veto power."
        """
        support = self.support_pressure(proposal_id)
        challenge = self.challenge_pressure(proposal_id)
        if support < self.contested_min_support:
            return False
        if challenge < self.contested_min_challenge:
            return False
        larger = max(support, challenge)
        if larger <= 0:
            return False
        # If one side dominates the other beyond the cancel ratio, the dispute is
        # one-sided, not genuinely contested.
        return abs(support - challenge) <= self.contested_cancel_ratio * larger

    def contested_review_requirement(self, proposal_id: str) -> "ContestedReview":
        """Raised evidence bar + flag for a contested proposal (HTML section 08).

        A contested proposal is routed to a lane requiring stronger provenance and
        meta-falsification. This is represented as a flag plus a raised evidence
        bar; it NEVER rejects the claim (challenge buys scrutiny, not veto).
        """
        contested = self.is_contested(proposal_id)
        return ContestedReview(
            proposal_id=proposal_id,
            contested=contested,
            support_pressure=self.support_pressure(proposal_id),
            challenge_pressure=self.challenge_pressure(proposal_id),
            require_stronger_provenance=contested,
            require_meta_falsification=contested,
            # raised bar is a multiplier on the evidence requirement, never a veto
            evidence_bar_multiplier=2.0 if contested else 1.0,
        )

    # --- settlement (HTML section 09) ------------------------------------------

    def settle(
        self,
        proposal_id: str,
        claim_card: ClaimCardV1,
    ) -> SettlementReport:
        """Settle every stake on a proposal against a final claim card.

        Winners (prediction matched the realized status) get their stake back plus
        a share of the clawed-back pool, proportional to the size of their winning
        stake. Losers forfeit a tier-dependent fraction of their stake; the
        un-forfeited remainder is returned to them. An ``unresolved`` status is a
        void (push): every stake is returned in full, nothing changes hands.

        Credit conservation (audited, never silently violated): when a claim
        resolves but *every* stake is on the losing side, there are no winners to
        receive the clawed-back pool. Rather than silently destroying it, the
        un-redistributable remainder is recorded in ``SettlementReport.total_burned``.
        Thus for ANY settlement the invariant holds::

            sum(credit after) + total_burned
                == sum(credit before, including escrowed stake amounts)

        and ``total_clawed_back == total_redistributed + total_burned``.
        """
        stakes = list(self.stakes.get(proposal_id, []))
        status = claim_card.status
        contested = self.is_contested(proposal_id)

        if status in _HOLDS:
            held: bool | None = True
        elif status in _FAILS:
            held = False
        else:  # unresolved / ill_typed -> void push
            held = None

        outcomes: list[SettlementOutcome] = []

        if held is None:
            # Void: return every stake in full, no winners/losers.
            for st in stakes:
                self.credit[st.agent_id] = self.credit.get(st.agent_id, 0.0) + st.amount
                outcomes.append(
                    SettlementOutcome(
                        stake_id=st.stake_id,
                        agent_id=st.agent_id,
                        role=st.role,
                        won=False,
                        amount_staked=st.amount,
                        payout=st.amount,
                        net=0.0,
                        penalty_tier=None,
                    )
                )
            report = SettlementReport(
                proposal_id=proposal_id,
                settlement_target=claim_card.claim_id,
                final_status=status,
                claim_held=None,
                contested=contested,
                outcomes=outcomes,
                total_clawed_back=0.0,
                total_redistributed=0.0,
            )
            self.stakes.pop(proposal_id, None)
            return report

        # A stake "wins" iff its prediction matched the realized direction.
        def _won(st: Stake) -> bool:
            if held:
                return st.prediction is StakePrediction.will_hold
            return st.prediction is StakePrediction.will_fail

        winners = [st for st in stakes if _won(st)]
        losers = [st for st in stakes if not _won(st)]

        # Claw back tier-dependent fractions from losers; return the remainder.
        clawed_back = 0.0
        loser_outcomes: list[SettlementOutcome] = []
        for st in losers:
            frac = PENALTY_FRACTION[st.quality]
            penalty = st.amount * frac
            returned = st.amount - penalty
            clawed_back += penalty
            self.credit[st.agent_id] = self.credit.get(st.agent_id, 0.0) + returned
            loser_outcomes.append(
                SettlementOutcome(
                    stake_id=st.stake_id,
                    agent_id=st.agent_id,
                    role=st.role,
                    won=False,
                    amount_staked=st.amount,
                    payout=returned,
                    net=returned - st.amount,
                    penalty_tier=st.quality,
                )
            )

        # Redistribute the clawed-back pool to winners, proportional to stake size.
        total_winning_stake = sum(st.amount for st in winners)
        redistributed = 0.0
        winner_outcomes: list[SettlementOutcome] = []
        for st in winners:
            share = (
                clawed_back * (st.amount / total_winning_stake)
                if total_winning_stake > 0
                else 0.0
            )
            payout = st.amount + share
            redistributed += share
            self.credit[st.agent_id] = self.credit.get(st.agent_id, 0.0) + payout
            winner_outcomes.append(
                SettlementOutcome(
                    stake_id=st.stake_id,
                    agent_id=st.agent_id,
                    role=st.role,
                    won=True,
                    amount_staked=st.amount,
                    payout=payout,
                    net=payout - st.amount,
                    penalty_tier=None,
                )
            )

        # Whatever was clawed back but not redistributed (no winners, or float
        # residue) is burned — accounted for explicitly so credit is conserved.
        burned = clawed_back - redistributed

        outcomes = winner_outcomes + loser_outcomes
        report = SettlementReport(
            proposal_id=proposal_id,
            settlement_target=claim_card.claim_id,
            final_status=status,
            claim_held=held,
            contested=contested,
            outcomes=outcomes,
            total_clawed_back=clawed_back,
            total_redistributed=redistributed,
            total_burned=burned,
        )
        self.stakes.pop(proposal_id, None)
        return report


class ContestedReview(BaseModel):
    """The raised evidence bar a contested proposal must clear (HTML section 08).

    A flag plus a multiplier — never a rejection. Challenge buys scrutiny, not
    veto power, so this object can only *raise the bar*, not fail the claim.
    """

    model_config = ConfigDict(frozen=True)

    proposal_id: str
    contested: bool
    support_pressure: float
    challenge_pressure: float
    require_stronger_provenance: bool
    require_meta_falsification: bool
    evidence_bar_multiplier: float = 1.0


# ---------------------------------------------------------------------------
# section 08 — public controversy reserve (v0)
# ---------------------------------------------------------------------------


class ReserveAllocation(BaseModel):
    """A single grant from the public controversy reserve (HTML section 08).

    Records that the reserve funded extra scrutiny for a contested proposal via an
    INDEPENDENT lineage ("public reserve must use independent lineage"). This buys
    scrutiny only — it carries no settlement prediction and can never reject a
    claim ("Controversy buys scrutiny, not veto power").
    """

    model_config = ConfigDict(frozen=True)

    proposal_id: str
    amount: float = Field(gt=0.0)
    contestedness: float  # the normalized contestedness that sized this grant
    # The independent verification lineage the reserve funded. Required: the public
    # reserve must NOT reuse a lineage already staked on the proposal.
    independent_lineage_id: str
    rationale: str | None = None
    allocated_at: str = Field(default_factory=_utc_now)


class ReserveError(RuntimeError):
    """Raised on an invalid reserve allocation (over-allocation / missing lineage)."""


class PublicControversyReserve(BaseModel):
    """A finite, shared credit pool that funds extra scrutiny (HTML section 08).

    This is SEPARATE from the per-agent credit in :class:`EpistemicMarket`: a
    bounded common pool that "资助高价值争议的额外审视" — funds extra independent
    verification for high-value contested proposals. The reserve:

    * allocates proportional to a proposal's *contestedness* (derived from the
      market's ``is_contested`` / support / challenge pressures);
    * depletes as it spends and REFUSES to over-allocate beyond ``balance``;
    * records the INDEPENDENT lineage each grant funded (HTML: public reserve must
      use independent lineage);
    * NEVER vetoes — it buys scrutiny only and holds no settlement prediction.

    Numeric knobs (``max_fraction_per_grant``) are uncalibrated v0 conventions.
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)

    balance: float = Field(default=0.0, ge=0.0)
    # Cap any single grant at this fraction of the CURRENT balance, so one
    # controversy cannot drain the whole pool. Uncalibrated v0 convention.
    max_fraction_per_grant: float = 0.5
    allocations: list[ReserveAllocation] = Field(default_factory=list)

    def fund(self, amount: float) -> float:
        """Top up the shared reserve. Returns the new balance."""
        if amount < 0:
            raise ReserveError("cannot fund the reserve with a negative amount")
        self.balance += float(amount)
        return self.balance

    @staticmethod
    def contestedness(support: float, challenge: float) -> float:
        """Normalized contestedness in ``[0, 1]`` (v0 convention).

        0 when either side is absent or one side fully dominates; ->1 as support and
        challenge approach parity at high volume. Defined as the ratio of the
        smaller side to the larger side: ``min/max``. This is purely a *sizing*
        signal for scrutiny; it is never used to reject a claim.
        """
        larger = max(support, challenge)
        if larger <= 0:
            return 0.0
        smaller = min(support, challenge)
        if smaller <= 0:
            return 0.0
        return smaller / larger

    def allocate(
        self,
        market: "EpistemicMarket",
        proposal_id: str,
        *,
        independent_lineage_id: str,
        rationale: str | None = None,
    ) -> ReserveAllocation:
        """Allocate reserve to a contested proposal, proportional to contestedness.

        The grant is ``contestedness * max_fraction_per_grant * balance`` — larger
        for more genuinely contested (parity, high-volume) proposals, capped so a
        single grant cannot drain the pool. The reserve depletes by the granted
        amount and REFUSES (raises :class:`ReserveError`) if it cannot cover a
        positive grant.

        ``independent_lineage_id`` MUST be a lineage NOT already staked on the
        proposal (the public reserve funds *independent* verification). A non-
        contested proposal yields no grant (raises): the reserve only funds genuine
        controversy. This method buys scrutiny; it never touches per-agent credit
        and never rejects the claim.
        """
        lineage = str(independent_lineage_id).strip()
        if not lineage:
            raise ReserveError(
                "reserve allocation requires a non-empty independent_lineage_id "
                "(HTML section 08: public reserve must use independent lineage)"
            )
        # Independence guard: the funded lineage must not be one already staked on
        # the proposal (otherwise it is not independent verification).
        staked_agents = {s.agent_id for s in market.stakes.get(proposal_id, [])}
        if lineage in staked_agents:
            raise ReserveError(
                f"lineage {lineage!r} already staked on proposal {proposal_id!r}; "
                "public reserve must fund an INDEPENDENT lineage"
            )
        if not market.is_contested(proposal_id):
            raise ReserveError(
                f"proposal {proposal_id!r} is not contested; the public reserve only "
                "funds genuine controversy (scrutiny, not veto)"
            )

        support = market.support_pressure(proposal_id)
        challenge = market.challenge_pressure(proposal_id)
        score = self.contestedness(support, challenge)
        grant = score * self.max_fraction_per_grant * self.balance
        if grant <= 0:
            raise ReserveError(
                f"computed reserve grant for {proposal_id!r} is non-positive "
                f"(contestedness={score}, balance={self.balance})"
            )
        if grant > self.balance:
            # Defensive: with max_fraction_per_grant <= 1 and score <= 1 this cannot
            # exceed the balance, but never over-allocate regardless.
            raise ReserveError(
                f"reserve cannot cover grant {grant} from balance {self.balance}"
            )

        self.balance -= grant
        alloc = ReserveAllocation(
            proposal_id=proposal_id,
            amount=grant,
            contestedness=score,
            independent_lineage_id=lineage,
            rationale=rationale,
        )
        self.allocations.append(alloc)
        return alloc


# ---------------------------------------------------------------------------
# section 08 — claim-level 70% PI prior + 30% market allocation (v0)
# ---------------------------------------------------------------------------


# Claim-level split (HTML section 08, "70% PI prior + 30% market"). The PI chooses
# the map; the market chooses where to dig first. Uncalibrated v0 convention.
PI_PRIOR_WEIGHT = 0.7
MARKET_WEIGHT = 0.3


class ClaimAllocationInput(BaseModel):
    """One claim's PI prior + market score, fed to :func:`claim_level_allocation`."""

    model_config = ConfigDict(frozen=True)

    claim_id: str
    pi_prior: float = Field(ge=0.0)  # the human PI's prior weight on this claim
    market_score: float = Field(ge=0.0)  # the agent market's score on this claim


class ClaimAllocation(BaseModel):
    """The normalized compute/attention share assigned to one claim (HTML section 08)."""

    model_config = ConfigDict(frozen=True)

    claim_id: str
    pi_prior: float
    market_score: float
    blended: float  # 0.7 * normalized PI prior + 0.3 * normalized market score
    allocation: float  # blended, renormalized to sum to 1 across all claims


def claim_level_allocation(
    claims: Sequence[ClaimAllocationInput],
    *,
    pi_weight: float = PI_PRIOR_WEIGHT,
    market_weight: float = MARKET_WEIGHT,
) -> list[ClaimAllocation]:
    """Blend PI priors and market scores into a normalized allocation (HTML section 08).

    For each claim the blended score is ``pi_weight * PI_prior_share +
    market_weight * market_score_share`` where each share is that claim's value
    divided by the total over all claims (so PI and market are each normalized
    BEFORE blending — they live on independent scales). The blended scores are then
    renormalized to sum to 1, giving a compute/attention allocation.

    Degenerate inputs are handled safely:

    * empty ``claims`` -> empty list;
    * an all-zero PI column (or market column) contributes a uniform share for that
      side rather than dividing by zero;
    * if EVERYTHING is zero, the final allocation is uniform.
    """
    items = list(claims)
    if not items:
        return []

    n = len(items)
    pi_total = sum(c.pi_prior for c in items)
    mkt_total = sum(c.market_score for c in items)

    def _share(value: float, total: float) -> float:
        # A degenerate (all-zero) column falls back to a uniform share so we never
        # divide by zero and never silently drop a whole signal.
        if total <= 0:
            return 1.0 / n
        return value / total

    blended_raw: list[float] = []
    for c in items:
        pi_share = _share(c.pi_prior, pi_total)
        mkt_share = _share(c.market_score, mkt_total)
        blended_raw.append(pi_weight * pi_share + market_weight * mkt_share)

    blend_total = sum(blended_raw)
    out: list[ClaimAllocation] = []
    for c, b in zip(items, blended_raw):
        allocation = b / blend_total if blend_total > 0 else 1.0 / n
        out.append(
            ClaimAllocation(
                claim_id=c.claim_id,
                pi_prior=c.pi_prior,
                market_score=c.market_score,
                blended=b,
                allocation=allocation,
            )
        )
    return out


# ---------------------------------------------------------------------------
# section 09 — Editor Board tie-break
# ---------------------------------------------------------------------------


class EditorVote(BaseModel):
    """A single board member's structured, recorded vote (HTML section 09).

    The editor "bets authority, not credit": the vote carries a ``confidence`` and
    a separately-tracked ``calibration`` (historical accuracy), and aggregation
    weights by ``calibration x confidence`` — explicitly NOT by reputation /
    seniority, to avoid a Matthew effect.
    """

    model_config = ConfigDict(frozen=True)

    member_id: str
    seat: str  # e.g. "stats_methodology" / "neuroimaging_validity" / "scientific_significance"
    vote: ClaimStatusV1
    confidence: float = Field(ge=0.0, le=1.0)
    calibration: float = Field(ge=0.0, le=1.0)  # historical accuracy, NOT reputation
    rationale: str | None = None

    @property
    def weight(self) -> float:
        """Aggregation weight = calibration x confidence (reputation ignored)."""
        return self.calibration * self.confidence


class BoardDecision(BaseModel):
    """A recorded Editor Board decision (HTML section 09).

    Structured, auditable, and calibration-weighted. The majority verdict is the
    decision, but minority opinions are RETAINED (never deleted). There is no
    single permanent chief; the board only acts on tie-break / appeal.
    """

    model_config = ConfigDict(frozen=True)

    proposal_id: str
    decision: ClaimStatusV1
    votes: list[EditorVote]
    weights: dict[str, float]  # member_id -> calibration x confidence
    minority_opinions: list[EditorVote]
    triggered_by: Literal["tie_break", "appeal"]
    decided_at: str = Field(default_factory=_utc_now)
    decision_hash: str = ""

    def with_hash(self) -> "BoardDecision":
        payload = self.model_dump(exclude={"decision_hash", "decided_at"})
        return self.model_copy(update={"decision_hash": fingerprint(payload)})


class EditorBoard(BaseModel):
    """A 3-member board that only acts on tie-break / appeal (HTML section 09).

    No single permanent chief: aggregation is by ``calibration x confidence`` over
    the seated members, never by reputation. Minority opinions are retained on
    every decision. The board "bets authority, not credit", so deciding does not
    touch the :class:`EpistemicMarket` credit ledger.
    """

    model_config = ConfigDict(frozen=True)

    seats: tuple[str, str, str] = (
        "stats_methodology",
        "neuroimaging_validity",
        "scientific_significance",
    )

    def should_convene(
        self,
        *,
        jury_margin: float,
        appeal: bool = False,
        tie_break_margin: float = 0.1,
    ) -> bool:
        """Board convenes only on a close jury margin (tie) or an explicit appeal.

        ``jury_margin`` is the normalized winning margin from the upstream jury in
        ``[0, 1]``; a margin at or below ``tie_break_margin`` is a tie.

        NOTE (v0): the ``appeal`` path is intentionally NOT wired into the conductor
        — the only live trigger is the jury-tie tie-break (the conductor always passes
        ``triggered_by="tie_break"``). The ``appeal`` parameter is kept as a forward
        surface but is dead from the conductor's perspective in v0.
        """
        return appeal or jury_margin <= tie_break_margin

    def decide(
        self,
        proposal_id: str,
        votes: Sequence[EditorVote],
        *,
        triggered_by: Literal["tie_break", "appeal"] = "tie_break",
    ) -> BoardDecision:
        """Aggregate votes by calibration x confidence; retain minority opinions.

        Ties in aggregate weight are broken deterministically toward the
        *stronger* evidential status per :data:`_DECISION_LADDER` (strongest
        first), independent of ``ClaimStatusV1`` declaration order. The structural
        ``ill_typed`` verdict (and the non-evidential ``unresolved`` void) are
        never *preferred* as a tie-break winner; if the weight-tied front-runners
        are only such degenerate statuses the decision falls back to
        ``unresolved`` — ``ill_typed`` is NEVER emitted by this decision layer
        (it is structural-only, produced solely by ``neuroclaim_compile``).
        """
        if not votes:
            raise ValueError("EditorBoard.decide requires at least one vote")

        weights: dict[str, float] = {v.member_id: v.weight for v in votes}

        # Sum calibration x confidence weight per candidate status.
        tally: dict[ClaimStatusV1, float] = {}
        for v in votes:
            tally[v.vote] = tally.get(v.vote, 0.0) + v.weight

        # Deterministic winner: max total weight, ties broken toward the stronger
        # evidential status; never resolves to ill_typed.
        decision = _resolve_decision_tie(tally)

        minority = [v for v in votes if v.vote != decision]

        return BoardDecision(
            proposal_id=proposal_id,
            decision=decision,
            votes=list(votes),
            weights=weights,
            minority_opinions=minority,
            triggered_by=triggered_by,
        ).with_hash()


# ---------------------------------------------------------------------------
# section 09 — settlement jury (rule-checklist -> jury -> board funnel middle)
# ---------------------------------------------------------------------------


class JurorVote(BaseModel):
    """A single juror's structured vote on an ambiguous settlement (HTML section 09).

    Built the SAME honest way as :class:`EditorVote`: the juror carries a
    ``confidence`` and a separately-tracked ``calibration`` (historical accuracy),
    and aggregation weights by ``calibration x confidence`` — explicitly NOT by
    reputation. Votes are INPUTS to the panel; the panel never fabricates them.
    """

    model_config = ConfigDict(frozen=True)

    juror_id: str  # cross-checked against market stakes to exclude conflicts
    vote: ClaimStatusV1
    confidence: float = Field(ge=0.0, le=1.0)
    calibration: float = Field(ge=0.0, le=1.0)  # historical accuracy, NOT reputation
    rationale: str | None = None

    @property
    def weight(self) -> float:
        """Aggregation weight = calibration x confidence (reputation ignored)."""
        return self.calibration * self.confidence


class JuryVerdict(BaseModel):
    """A recorded settlement-jury verdict (HTML section 09 middle tier).

    Aggregates juror votes by ``calibration x confidence``, retains minority
    opinions, and emits a normalized ``margin`` in ``[0, 1]`` (winning weight share
    minus runner-up weight share) that feeds
    :meth:`EditorBoard.should_convene(jury_margin=...)`. Conflicted jurors are
    recorded in ``excluded_jurors`` so the exclusion is auditable.
    """

    model_config = ConfigDict(frozen=True)

    proposal_id: str
    verdict: ClaimStatusV1
    counted_votes: list[JurorVote]
    excluded_jurors: list[str]  # juror_ids dropped for conflict of interest
    weights: dict[str, float]  # counted juror_id -> calibration x confidence
    minority_opinions: list[JurorVote]
    margin: float  # normalized winning margin in [0, 1]; feeds the Editor Board
    decided_at: str = Field(default_factory=_utc_now)

    #: How a jury-driven editorial admission is tagged in the immutable memory
    #: origin (mirrors :attr:`BoardDecision.triggered_by`). A decisive jury that
    #: lowers a claim's status is recorded as a ``"jury"`` admission, distinct from
    #: a board ``"tie_break"`` / ``"appeal"``.
    triggered_by: Literal["jury"] = "jury"

    @property
    def decision_hash(self) -> str:
        """Stable hash over the recorded verdict (the deciding-panel marker).

        Used so a jury-driven editorial admission records THIS panel's hash in the
        immutable memory origin, exactly as :attr:`BoardDecision.decision_hash` does
        for a board-driven admission. Excludes ``decided_at`` so the hash is
        deterministic over the deliberation content.
        """
        payload = self.model_dump(exclude={"decided_at"})
        return fingerprint(payload)


class JuryPanel(BaseModel):
    """A mixed settlement jury that resolves ambiguous cases (HTML section 09).

    The honest middle tier of the rule-checklist -> jury -> board funnel. It:

    * takes juror votes as INPUTS (never fabricates a vote);
    * EXCLUDES jurors with a conflict of interest — any juror who staked on the
      proposal, cross-checked against the market's stakes;
    * aggregates by ``calibration x confidence`` (never by reputation);
    * RETAINS minority opinions;
    * emits a normalized winning ``margin`` so ``EditorBoard.should_convene`` can
      decide whether to escalate (close margin -> board tie-break).
    """

    model_config = ConfigDict(frozen=True)

    def conflicted_jurors(
        self, market: "EpistemicMarket", proposal_id: str
    ) -> set[str]:
        """Juror/agent ids that have a stake on the proposal (conflict of interest)."""
        return {s.agent_id for s in market.stakes.get(proposal_id, [])}

    def deliberate(
        self,
        market: "EpistemicMarket",
        proposal_id: str,
        votes: Sequence[JurorVote],
    ) -> JuryVerdict:
        """Aggregate non-conflicted juror votes; emit the verdict + escalation margin.

        Jurors who staked on the proposal are excluded (cross-checked against
        ``market.stakes``). The remaining votes are tallied by
        ``calibration x confidence``; the highest-weight status wins, ties broken
        deterministically toward the *stronger* evidential status per
        :data:`_DECISION_LADDER` (matching :meth:`EditorBoard.decide`). The
        structural ``ill_typed`` verdict is never selectable as a tie winner here;
        a tie among only degenerate/non-evidential statuses falls back to
        ``unresolved``. Minority opinions are retained. The ``margin`` is the
        normalized gap between the winner's and runner-up's weight shares, in
        ``[0, 1]``.
        """
        if not votes:
            raise ValueError("JuryPanel.deliberate requires at least one vote")

        conflicted = self.conflicted_jurors(market, proposal_id)
        counted = [v for v in votes if v.juror_id not in conflicted]
        excluded = [v.juror_id for v in votes if v.juror_id in conflicted]
        if not counted:
            raise ValueError(
                "JuryPanel.deliberate: every juror is conflicted (staked on the "
                f"proposal {proposal_id!r}); cannot seat an impartial jury"
            )

        weights: dict[str, float] = {v.juror_id: v.weight for v in counted}

        tally: dict[ClaimStatusV1, float] = {}
        for v in counted:
            tally[v.vote] = tally.get(v.vote, 0.0) + v.weight

        ranked = sorted(
            tally.items(),
            key=lambda kv: (kv[1], _decision_tiebreak_rank(kv[0])),
            reverse=True,
        )
        # Winner: max weight, ties broken toward the stronger evidential status;
        # never resolves to ill_typed (falls back to unresolved if degenerate).
        verdict = _resolve_decision_tie(tally)

        # Normalized winning margin in [0, 1]: winner share minus runner-up share of
        # the total counted weight. With a single voted-for status the margin is the
        # winner's share (runner-up share == 0). All-zero weight -> margin 0 (a tie),
        # which routes to the Editor Board.
        total_weight = sum(weights.values())
        if total_weight <= 0:
            margin = 0.0
        else:
            top_share = ranked[0][1] / total_weight
            runner_share = ranked[1][1] / total_weight if len(ranked) > 1 else 0.0
            margin = top_share - runner_share

        minority = [v for v in counted if v.vote != verdict]

        return JuryVerdict(
            proposal_id=proposal_id,
            verdict=verdict,
            counted_votes=list(counted),
            excluded_jurors=excluded,
            weights=weights,
            minority_opinions=minority,
            margin=margin,
        )


# ---------------------------------------------------------------------------
# section 10 — dynamic-weight memory
# ---------------------------------------------------------------------------


class AcceptanceMode(str, Enum):
    """How a claim entered memory (HTML section 10).

    ``editorial`` acceptance MUST be flagged and start at a lower weight than
    ``rule_based`` acceptance.
    """

    rule_based = "rule_based_acceptance"
    editorial = "editorial_acceptance"


# Lower initial weight for editorial acceptance (HTML section 10). Conventions.
INITIAL_WEIGHT: dict[AcceptanceMode, float] = {
    AcceptanceMode.rule_based: 1.0,
    AcceptanceMode.editorial: 0.5,
}

WEIGHT_FLOOR = 0.0
WEIGHT_CEILING = 5.0


class WeightEvent(str, Enum):
    """A promotion or demotion trigger (HTML section 10, Fig 09)."""

    replication = "replication"  # +: independent replication
    stronger_falsification_survived = "stronger_falsification_survived"  # +
    rule_based_adjudication = "rule_based_adjudication"  # +
    failed_replication = "failed_replication"  # -: replication failed
    contradicted_by_stronger = "contradicted_by_stronger"  # -: higher-weight conflict
    calibration_penalty = "calibration_penalty"  # -


# Signed weight deltas per event. Conventions, not calibrated.
WEIGHT_DELTA: dict[WeightEvent, float] = {
    WeightEvent.replication: 0.5,
    WeightEvent.stronger_falsification_survived: 0.5,
    WeightEvent.rule_based_adjudication: 0.25,
    WeightEvent.failed_replication: -0.5,
    WeightEvent.contradicted_by_stronger: -0.75,
    WeightEvent.calibration_penalty: -0.25,
}


class WeightUpdate(BaseModel):
    """An append-only weight change record (HTML section 10)."""

    model_config = ConfigDict(frozen=True)

    event: WeightEvent
    delta: float
    weight_before: float
    weight_after: float
    note: str | None = None
    at: str = Field(default_factory=_utc_now)


class MemoryEntry(BaseModel):
    """A claim held in dynamic-weight memory (HTML section 10).

    The ``origin`` block is IMMUTABLE — acceptance mode, the entering claim status,
    and the initial weight are frozen at creation and never erased, even as the
    live ``weight`` promotes or demotes. ``editorial_flag`` marks an
    editorially-accepted claim for the lifetime of the entry.
    """

    model_config = ConfigDict(frozen=True)

    claim_id: str
    acceptance_mode: AcceptanceMode
    editorial_flag: bool
    entered_status: ClaimStatusV1
    # IMMUTABLE origin/provenance tag — never erased (HTML section 10).
    origin: dict[str, Any]
    initial_weight: float
    weight: float
    history: tuple[WeightUpdate, ...] = ()

    def apply_event(
        self, event: WeightEvent, *, note: str | None = None
    ) -> "MemoryEntry":
        """Return a new entry with the weight moved by the event's delta.

        Promotion/demotion clamps to ``[WEIGHT_FLOOR, WEIGHT_CEILING]``. The origin
        tag and the immutable fields are carried over verbatim; only ``weight`` and
        ``history`` change.
        """
        delta = WEIGHT_DELTA[event]
        before = self.weight
        after = max(WEIGHT_FLOOR, min(WEIGHT_CEILING, before + delta))
        update = WeightUpdate(
            event=event,
            delta=delta,
            weight_before=before,
            weight_after=after,
            note=note,
        )
        return self.model_copy(
            update={"weight": after, "history": self.history + (update,)}
        )


class DynamicMemory(BaseModel):
    """In-memory dynamic-weight claim store (HTML section 10).

    ``accept`` admits a claim under one of the two write modes; editorial
    acceptance is flagged and starts lower. ``promote`` / ``demote`` move the live
    weight via :class:`WeightEvent`. The immutable origin tag is preserved across
    all updates — origin is never erased.
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)

    entries: dict[str, MemoryEntry] = Field(default_factory=dict)

    def accept(
        self,
        claim_card: ClaimCardV1,
        *,
        mode: AcceptanceMode,
        editor_decision: "BoardDecision | JuryVerdict | None" = None,
    ) -> MemoryEntry:
        """Admit a claim card into memory under the given write mode.

        Editorial acceptance is flagged and starts at a lower initial weight. The
        immutable origin records the mode, entering status, commitment hash, and
        (if editorial) the deciding-panel hash.

        ``editor_decision`` is the deciding editorial panel: a
        :class:`BoardDecision` (board tie-break) OR a :class:`JuryVerdict` (a
        DECISIVE jury that lowered the status without escalating to the board). Both
        expose ``decision_hash`` + ``triggered_by``; the immutable origin records the
        deciding panel's hash and its trigger marker (``"tie_break"`` / ``"appeal"``
        for a board, ``"jury"`` for a decisive jury) so the editorial provenance is
        never erased.
        """
        editorial = mode is AcceptanceMode.editorial
        weight = INITIAL_WEIGHT[mode]
        origin = {
            "acceptance_mode": mode.value,
            "entered_status": claim_card.status.value,
            "commitment_hash": claim_card.commitment_hash,
            "entered_at": _utc_now(),
        }
        if editor_decision is not None:
            origin["editor_decision_hash"] = editor_decision.decision_hash
            origin["editor_triggered_by"] = editor_decision.triggered_by
        entry = MemoryEntry(
            claim_id=claim_card.claim_id,
            acceptance_mode=mode,
            editorial_flag=editorial,
            entered_status=claim_card.status,
            origin=origin,
            initial_weight=weight,
            weight=weight,
        )
        self.entries[claim_card.claim_id] = entry
        return entry

    def apply_event(
        self, claim_id: str, event: WeightEvent, *, note: str | None = None
    ) -> MemoryEntry:
        entry = self.entries[claim_id]
        updated = entry.apply_event(event, note=note)
        self.entries[claim_id] = updated
        return updated

    def promote(
        self,
        claim_id: str,
        event: WeightEvent = WeightEvent.replication,
        *,
        note: str | None = None,
    ) -> MemoryEntry:
        if WEIGHT_DELTA[event] < 0:
            raise ValueError(f"{event} is a demotion event, not a promotion")
        return self.apply_event(claim_id, event, note=note)

    def demote(
        self,
        claim_id: str,
        event: WeightEvent = WeightEvent.failed_replication,
        *,
        note: str | None = None,
    ) -> MemoryEntry:
        if WEIGHT_DELTA[event] > 0:
            raise ValueError(f"{event} is a promotion event, not a demotion")
        return self.apply_event(claim_id, event, note=note)


# ---------------------------------------------------------------------------
# optional JSON snapshot persistence
# ---------------------------------------------------------------------------


class EconomySnapshot(BaseModel):
    """A serializable point-in-time snapshot of the whole economy (v0 persistence)."""

    schema_version: Literal["economy-snapshot-v1"] = "economy-snapshot-v1"
    market: EpistemicMarket
    memory: DynamicMemory
    taken_at: str = Field(default_factory=_utc_now)


def save_snapshot(
    path: str | Path,
    market: EpistemicMarket,
    memory: DynamicMemory,
) -> Path:
    """Write a JSON snapshot of the in-memory economy. Optional, best-effort."""
    snap = EconomySnapshot(market=market, memory=memory)
    p = Path(path)
    p.write_text(json.dumps(snap.model_dump(mode="json"), indent=2), encoding="utf-8")
    return p


def load_snapshot(path: str | Path) -> EconomySnapshot:
    """Load a JSON snapshot written by :func:`save_snapshot`."""
    p = Path(path)
    return EconomySnapshot.model_validate_json(p.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# append-only economy ledger (durable alternative to the flat JSON snapshot)
# ---------------------------------------------------------------------------


class EconomyEventType(str, Enum):
    """The kinds of ordered events the economy ledger records (v0)."""

    stake_placed = "stake_placed"
    settlement = "settlement"
    weight_event = "weight_event"


#: Default economy-ledger location, under the repo runs/ dir. Injectable everywhere.
#: Mirrors ``proof_ledger.DEFAULT_LEDGER_PATH``.
DEFAULT_ECONOMY_LEDGER_PATH = Path("runs") / "ledger" / "economy_ledger.jsonl"


class EconomyLedgerEntry(BaseModel):
    """One append-only economy-ledger line (v0).

    A typed envelope around a stake placement, a settlement report, or a
    dynamic-memory weight event. ``seq`` is the append-order index (0-based) and
    ``payload`` is the serialized record.
    """

    model_config = ConfigDict(frozen=True)

    schema_version: Literal["economy-ledger-entry-v1"] = "economy-ledger-entry-v1"
    seq: int
    event_type: EconomyEventType
    payload: dict[str, Any]
    recorded_at: str = Field(default_factory=_utc_now)


class EconomyLedger:
    """An append-only JSONL log of economy events (HTML sections 08-10).

    The durable, ordered alternative to the flat :class:`EconomySnapshot`. Follows
    the same shape as :class:`society.proof_ledger.ProofLedger`: append-only, one
    JSON object per line, path-injectable (default
    :data:`DEFAULT_ECONOMY_LEDGER_PATH`), and read back in append order. It records
    stake placements, settlement reports, and dynamic-memory weight events as
    ordered lines.

    A hash chain is intentionally NOT required here (it is a nice-to-have that
    ``proof_ledger`` provides for tamper-evidence); this ledger's contract is
    append-only ordering + round-trip, not tamper-proofing.
    """

    def __init__(self, path: str | Path | None = None) -> None:
        self.path = Path(path) if path is not None else DEFAULT_ECONOMY_LEDGER_PATH

    # -- reads -------------------------------------------------------------- #

    def _read_records(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        records: list[dict[str, Any]] = []
        with self.path.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                records.append(json.loads(line))
        return records

    def __len__(self) -> int:
        return len(self._read_records())

    def read_all(self) -> list[EconomyLedgerEntry]:
        """Return every stored entry, in append (``seq``) order."""
        return [EconomyLedgerEntry.model_validate(r) for r in self._read_records()]

    # -- writes ------------------------------------------------------------- #

    def _append_entry(
        self, event_type: EconomyEventType, payload: dict[str, Any]
    ) -> EconomyLedgerEntry:
        seq = len(self._read_records())
        entry = EconomyLedgerEntry(
            seq=seq, event_type=event_type, payload=payload
        )
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(
                json.dumps(entry.model_dump(mode="json"), sort_keys=True) + "\n"
            )
        return entry

    def append_stake(self, stake: Stake) -> EconomyLedgerEntry:
        """Append a stake-placement event."""
        return self._append_entry(
            EconomyEventType.stake_placed, stake.model_dump(mode="json")
        )

    def append_settlement(self, report: SettlementReport) -> EconomyLedgerEntry:
        """Append a settlement-report event."""
        return self._append_entry(
            EconomyEventType.settlement, report.model_dump(mode="json")
        )

    def append_weight_event(
        self, claim_id: str, update: WeightUpdate
    ) -> EconomyLedgerEntry:
        """Append a dynamic-memory weight-change event for a claim."""
        payload = {"claim_id": claim_id, **update.model_dump(mode="json")}
        return self._append_entry(EconomyEventType.weight_event, payload)
