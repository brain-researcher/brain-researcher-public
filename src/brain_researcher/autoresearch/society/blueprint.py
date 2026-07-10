"""Neuroimage Blueprint — the benchmark oracle for the Society conductor.

Implements the three-layer visibility design from
``docs/BR_Society_v0.1_Spec_and_Blueprint.html`` (section 11) with the
epistemological correction from section 12:

* **Full record** (``BlueprintClaimV1``) — PI / curator visible: everything.
* **Agent-facing** (``AgentFacingClaimV1``) — the runtime terrain the conductor
  sees. STRUCTURALLY excludes the verdict / oracle tier / rationale, so the
  benchmark cannot leak into the agents.
* **Hidden oracle** (``HiddenOracleV1``) — evaluator only: the expected verdict,
  acceptable alternatives, the oracle's epistemic tier, and severe-error
  conditions.

The section-12 correction is encoded as ``oracle_tier`` — the epistemic status of
the oracle ENTRY, which is a **per-claim curatorial judgment, NOT a fixed function
of the claim's ``evidence_status_type``**. The evaluator down-weights weaker tiers
rather than pretending all four claim types are ground truth.

The shipped ``configs/society/scz_fc_blueprint_v0.1.yaml`` realizes this judgment as
follows (and ``test_seed_blueprint_per_claim_tier_relationship`` pins it so the
docs cannot drift from the data):

* ``trap`` (Type C, 5 claims) -> ``ground_truth``. Methodological theorems
  (reverse inference, double dipping, uncorrected mass-univariate, motion/site
  confounds): definite, the gold line.
* ``fragile`` (Type B, 5 claims) -> ``reproducible``. Multiverse-sensitive
  behavior anchored on a runnable fork (e.g. GSR on/off).
* ``robust`` (Type A, 2 claims) -> ``reproducible`` (NOT ``consensus``). This is the
  documented exception: under the section-12 correction a "robust positive control"
  is only admitted when it is a VERIFIABLE methodological-robustness property of the
  measurement process (re-derivable in any cohort), not a popular substantive
  finding. Such claims are therefore reproducible-tier; each robust claim's
  ``gold_rationale`` states why it is ``reproducible`` and not ``consensus``. A
  merely "widely believed" robust finding would be ``consensus``-tier, but none ship.
* ``open`` (Type D, 3 claims) -> ``consensus``. The underlying group-level pattern
  the open question hangs on is a consensus-level belief (weakly scored), while the
  open question itself (specificity / trait-marker / disease-vs-medication) is
  genuinely ``unresolved``.

The naive reading "robust == consensus, fragile == reproducible" is WRONG for this
blueprint: tier is curated per claim from the strength of the evidence object, not
mapped mechanically from the control type.
"""

from __future__ import annotations

import json
from enum import Enum
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field

from .cards import ClaimSpecV1, ClaimStatusV1, ScopeBoundaryV1


class EvidenceStatusTypeV1(str, Enum):
    """The four benchmark control types (spec section 11, Fig 11)."""

    robust = "robust"        # Type A — robust positive control (methodological robustness)
    fragile = "fragile"      # Type B — fragile / multiverse-sensitive
    trap = "trap"            # Type C — refuted / artifact / methodological-theorem trap
    open = "open"            # Type D — truly open question


class OracleTierV1(str, Enum):
    """Epistemic status of the oracle entry itself (spec section 12, fix 4).

    This is a PER-CLAIM curatorial judgment about the strength of the evidence
    object, NOT a fixed function of ``evidence_status_type``. See the module
    docstring for the shipped type->tier realization and its documented exceptions
    (notably: robust positive controls ship as ``reproducible``, not ``consensus``,
    because they are verifiable methodological-robustness properties; the ``open``
    claims ship as ``consensus`` because the group-level pattern they hang on is a
    consensus belief).
    """

    ground_truth = "ground_truth"   # methodological theorem — definite, re-derivable logically
    reproducible = "reproducible"   # runnable & verifiable multiverse / robustness fact
    consensus = "consensus"         # widely-believed only — weakly interpreted


# Default scoring weight per tier so consensus-level claims do not dominate
# (spec section 12: "score Type A weakly").
TIER_WEIGHT: dict[OracleTierV1, float] = {
    OracleTierV1.ground_truth: 1.0,
    OracleTierV1.reproducible: 0.6,
    OracleTierV1.consensus: 0.3,
}


class DisagreementClassV1(str, Enum):
    """How a system/blueprint disagreement is adjudicated (spec section 12 table)."""

    system_error = "system_error"          # system missed evidence / misread lit / wrong workflow or query
    blueprint_error = "blueprint_error"     # system found stronger evidence; the blueprint entry is stale/wrong
    genuine_ambiguity = "genuine_ambiguity" # both sides have evidence; cannot adjudicate


class DisagreementVerdictV1(BaseModel):
    """The adjudication of one system-vs-blueprint disagreement.

    Encodes the spec section-12 "Blueprint Disagreement Protocol" table:

    | case               | meaning                                   | recommended action |
    |--------------------|-------------------------------------------|--------------------|
    | system_error       | system missed/misread evidence            | system penalty · credit update · failure memory |
    | blueprint_error    | system found stronger evidence; entry wrong | amendment proposal · PI review · version bump · system earns discovery credit |
    | genuine_ambiguity  | both have evidence, undecidable           | claim stays unresolved · blueprint gets ambiguity note · revisit later |

    The blueprint is a **versioned expert oracle, not an infallible gold standard**:
    a ``blueprint_error`` verdict can AMEND the blueprint and the system earns
    discovery credit; a ``genuine_ambiguity`` verdict leaves the claim
    ``unresolved`` and records an ambiguity note.

    CONFLICT-ISOLATION REQUIREMENT (spec section 12, jury-recusal principle): the
    human/judge who decides ``blueprint_error`` vs ``system_error`` MUST be
    interest-isolated from whoever annotated the blueprint entry. This cannot be
    enforced in code; this docstring + the ``conflict_isolation_required`` flag
    record the requirement so the calling review process can honor it.
    """

    schema_version: Literal["disagreement-verdict-v1"] = "disagreement-verdict-v1"
    claim_id: str
    classification: DisagreementClassV1
    expected_verdict: ClaimStatusV1
    system_verdict: ClaimStatusV1
    recommended_action: str
    amends_blueprint: bool = False
    awards_discovery_credit: bool = False
    new_blueprint_verdict: ClaimStatusV1 | None = None
    leaves_unresolved: bool = False
    ambiguity_note: str | None = None
    rationale: str = ""
    # Whether a conflict-isolated human adjudicator is required for this case
    # (always True for blueprint_error per the jury-recusal principle).
    conflict_isolation_required: bool = False


def classify_disagreement(
    oracle: HiddenOracleV1,
    system_verdict: ClaimStatusV1,
    *,
    system_found_stronger_evidence: bool = False,
    both_sides_have_evidence: bool = False,
    theorem_refuted: bool = False,
    evidence_note: str | None = None,
) -> DisagreementVerdictV1 | None:
    """Adjudicate a system-vs-blueprint disagreement (spec section 12 protocol).

    Returns ``None`` when there is no disagreement (the system verdict matches the
    oracle's expected verdict or one of its acceptable alternatives) — agreement is
    not a protocol case.

    Otherwise classifies the disagreement into one of three cases and returns the
    recommended action. The caller supplies two adjudication signals that code alone
    cannot decide (they require literature/evidence review by a conflict-isolated
    human or an evidence backend):

    * ``system_found_stronger_evidence`` — the system surfaced evidence strong enough
      to show the blueprint entry is stale/wrong → ``blueprint_error`` (amends the
      blueprint, system earns discovery credit).
    * ``both_sides_have_evidence`` — both the system and the blueprint have defensible
      evidence and the disagreement cannot be adjudicated → ``genuine_ambiguity``
      (claim stays ``unresolved``, blueprint gets an ambiguity note).

    GOLD-LINE PROTECTION (spec section 12 fix 3, "the gold line"): a ground_truth
    entry — i.e. ``oracle.oracle_tier is ground_truth`` or a ``methodological_theorem``
    is set — is a logical/methodological theorem (e.g. double-dipping, reverse
    inference), NOT a stale empirical opinion. No amount of empirical "stronger
    evidence" overturns a theorem, so ``system_found_stronger_evidence`` alone CANNOT
    flip such an entry to ``blueprint_error`` / amend the blueprint. A gold-line
    disagreement instead routes to ``system_error`` (the system mis-applied the
    theorem) unless ``both_sides_have_evidence`` makes it ``genuine_ambiguity``.

    The ONLY way to classify a gold-line entry as ``blueprint_error`` is the explicit,
    separate ``theorem_refuted`` signal — asserting that the methodological theorem
    itself was shown to be incorrect (a far stronger claim than "found stronger
    empirical evidence"). For non-gold-line entries, ``theorem_refuted`` is irrelevant
    and ``system_found_stronger_evidence`` behaves as before.

    With no signal set, the default is ``system_error`` (the system is presumed to
    have missed/misread evidence) — the conservative default that does NOT let the
    system silently amend the oracle. ``blueprint_error`` takes precedence over
    ``genuine_ambiguity`` when both apply, because a decisive refutation/stronger
    evidence resolves the ambiguity.

    The human who decides ``blueprint_error`` vs ``system_error`` MUST be
    conflict-isolated from the blueprint annotator (see ``DisagreementVerdictV1``);
    that isolation cannot be enforced here, so ``conflict_isolation_required`` flags
    it on the returned verdict.
    """
    expected = oracle.expected_system_verdict
    acceptable = set(oracle.acceptable_alt_verdicts)
    if system_verdict == expected or system_verdict in acceptable:
        return None  # agreement is not a disagreement case

    base = dict(
        claim_id=oracle.claim_id,
        expected_verdict=expected,
        system_verdict=system_verdict,
    )

    # Gold line (spec section 12 fix 3): a ground_truth tier or a stated
    # methodological theorem is a logical truth no empirical "stronger evidence"
    # overturns. Refuse to amend it on the ordinary stronger-evidence signal; only
    # an explicit theorem_refuted signal may classify it as a blueprint_error.
    is_gold_line = (
        oracle.oracle_tier is OracleTierV1.ground_truth
        or bool(oracle.methodological_theorem)
    )
    can_amend = theorem_refuted if is_gold_line else system_found_stronger_evidence

    if can_amend:
        if is_gold_line:
            recommended_action = (
                "theorem-refutation proposal -> conflict-isolated PI review -> "
                "blueprint version bump; system earns discovery credit"
            )
            rationale = (
                "System asserted an explicit refutation of the entry's methodological "
                "theorem itself (theorem_refuted), not merely stronger empirical "
                "evidence. Overturning a gold-line theorem is a far stronger claim and "
                "requires conflict-isolated PI review before any amendment."
            )
        else:
            recommended_action = (
                "amendment proposal -> conflict-isolated PI review -> blueprint "
                "version bump; system earns discovery credit"
            )
            rationale = (
                "System surfaced evidence strong enough to show the blueprint entry "
                "is stale or wrong. The blueprint is a versioned expert oracle, not an "
                "infallible gold standard, so this is a candidate discovery, not a "
                "system failure."
            )
        return DisagreementVerdictV1(
            classification=DisagreementClassV1.blueprint_error,
            recommended_action=recommended_action,
            amends_blueprint=True,
            awards_discovery_credit=True,
            new_blueprint_verdict=system_verdict,
            conflict_isolation_required=True,
            rationale=rationale,
            **base,
        )

    if both_sides_have_evidence:
        note = evidence_note or (
            "System and blueprint both have defensible evidence for conflicting "
            "verdicts; disagreement is currently undecidable."
        )
        return DisagreementVerdictV1(
            classification=DisagreementClassV1.genuine_ambiguity,
            recommended_action=(
                "leave claim unresolved; add ambiguity note to blueprint entry; "
                "revisit after a decisive test"
            ),
            leaves_unresolved=True,
            ambiguity_note=note,
            rationale=(
                "Neither side can be adjudicated from current evidence, so the claim "
                "must not be scored as a system error nor used to amend the blueprint."
            ),
            **base,
        )

    if is_gold_line and system_found_stronger_evidence:
        rationale = (
            "Gold-line entry: the system claims stronger empirical evidence, but a "
            "ground_truth tier / methodological theorem is a logical truth that "
            "empirical evidence cannot overturn. The amendment is refused and the "
            "disagreement is scored as a system_error (the system mis-applied the "
            "theorem). Only an explicit theorem_refuted signal could amend it."
        )
    else:
        rationale = (
            "Default case: the system is presumed to have missed evidence, misread the "
            "literature, or run the wrong workflow/query. Without decisive stronger "
            "evidence the system cannot amend the oracle."
        )
    return DisagreementVerdictV1(
        classification=DisagreementClassV1.system_error,
        recommended_action="system penalty -> credit update -> failure memory entry",
        rationale=rationale,
        **base,
    )


class AgentFacingClaimV1(BaseModel):
    """Runtime terrain the conductor/agents see. Carries NO oracle information."""

    schema_version: Literal["agent-facing-claim-v1"] = "agent-facing-claim-v1"
    claim_id: str
    claim_text: str
    scope_boundary: ScopeBoundaryV1 = Field(default_factory=ScopeBoundaryV1)
    human_priority: float = 0.5
    expected_entities: list[str] = Field(default_factory=list)
    expected_risks: list[str] = Field(default_factory=list)
    candidate_datasets: list[str] = Field(default_factory=list)
    allowed_workflow_space: list[str] = Field(default_factory=list)
    # The stated methodology (prose + structured record). These are the METHOD the
    # system evaluates, so they ARE agent-facing (not oracle). review_context is the
    # structured CodeReviewBundle.review_context that the checklist arm (b) consumes.
    method_description: str | None = None
    review_context: dict[str, Any] = Field(default_factory=dict)

    def to_claim_spec(self) -> ClaimSpecV1:
        """Bridge to the conductor's input. The conductor only ever sees this layer."""
        return ClaimSpecV1(
            claim_id=self.claim_id,
            claim_text=self.claim_text,
            scope_boundary=self.scope_boundary,
            allowed_alternatives=list(self.allowed_workflow_space),
            confirmatory=True,
        )


class HiddenOracleV1(BaseModel):
    """Evaluator-only ground-truth entry for one claim."""

    schema_version: Literal["hidden-oracle-v1"] = "hidden-oracle-v1"
    claim_id: str
    evidence_status_type: EvidenceStatusTypeV1
    expected_system_verdict: ClaimStatusV1
    acceptable_alt_verdicts: list[ClaimStatusV1] = Field(default_factory=list)
    oracle_tier: OracleTierV1
    expected_risks: list[str] = Field(default_factory=list)
    gold_rationale: str = ""
    status_evidence_refs: list[str] = Field(default_factory=list)
    severe_error_conditions: list[str] = Field(default_factory=list)
    methodological_theorem: str | None = None


class BlueprintClaimV1(BaseModel):
    """Full curator-visible record for one claim (superset of the other two layers)."""

    schema_version: Literal["blueprint-claim-v1"] = "blueprint-claim-v1"
    claim_id: str
    evidence_status_type: EvidenceStatusTypeV1
    natural_claim: str
    scope_boundary: ScopeBoundaryV1 = Field(default_factory=ScopeBoundaryV1)
    human_priority: float = 0.5
    expected_entities: list[str] = Field(default_factory=list)
    expected_risks: list[str] = Field(default_factory=list)
    candidate_datasets: list[str] = Field(default_factory=list)
    allowed_workflow_space: list[str] = Field(default_factory=list)
    method_description: str | None = None
    review_context: dict[str, Any] = Field(default_factory=dict)
    # ---- oracle fields (never exposed to agents) ----
    expected_system_verdict: ClaimStatusV1
    acceptable_alt_verdicts: list[ClaimStatusV1] = Field(default_factory=list)
    oracle_tier: OracleTierV1
    gold_rationale: str = ""
    status_evidence_refs: list[str] = Field(default_factory=list)
    severe_error_conditions: list[str] = Field(default_factory=list)
    methodological_theorem: str | None = None
    needs_pi_curation: bool = True
    extra: dict[str, Any] = Field(default_factory=dict)

    def to_agent_facing(self) -> AgentFacingClaimV1:
        return AgentFacingClaimV1(
            claim_id=self.claim_id,
            claim_text=self.natural_claim,
            scope_boundary=self.scope_boundary,
            human_priority=self.human_priority,
            expected_entities=list(self.expected_entities),
            expected_risks=list(self.expected_risks),
            candidate_datasets=list(self.candidate_datasets),
            allowed_workflow_space=list(self.allowed_workflow_space),
            method_description=self.method_description,
            review_context=dict(self.review_context),
        )

    def to_oracle(self) -> HiddenOracleV1:
        return HiddenOracleV1(
            claim_id=self.claim_id,
            evidence_status_type=self.evidence_status_type,
            expected_system_verdict=self.expected_system_verdict,
            acceptable_alt_verdicts=list(self.acceptable_alt_verdicts),
            oracle_tier=self.oracle_tier,
            expected_risks=list(self.expected_risks),
            gold_rationale=self.gold_rationale,
            status_evidence_refs=list(self.status_evidence_refs),
            severe_error_conditions=list(self.severe_error_conditions),
            methodological_theorem=self.methodological_theorem,
        )


class Blueprint(BaseModel):
    """A versioned set of blueprint claims (a "versioned expert oracle")."""

    schema_version: Literal["blueprint-v1"] = "blueprint-v1"
    blueprint_id: str = "scz_fc_blueprint_v0.1"
    domain: str = "schizophrenia / functional connectivity"
    version: str = "0.1"
    claims: list[BlueprintClaimV1] = Field(default_factory=list)

    def agent_facing(self) -> list[AgentFacingClaimV1]:
        """The anti-leak runtime view: oracle fields are structurally absent."""
        return [c.to_agent_facing() for c in self.claims]

    def oracle(self) -> dict[str, HiddenOracleV1]:
        return {c.claim_id: c.to_oracle() for c in self.claims}

    def by_type(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for c in self.claims:
            counts[c.evidence_status_type.value] = counts.get(c.evidence_status_type.value, 0) + 1
        return counts

    @classmethod
    def from_records(cls, records: list[dict[str, Any]], **meta: Any) -> "Blueprint":
        return cls(claims=[BlueprintClaimV1.model_validate(r) for r in records], **meta)


def load_blueprint(path: str | Path) -> Blueprint:
    """Load a blueprint from a YAML or JSON file (object form or bare claim list)."""
    target = Path(path).expanduser()
    text = target.read_text(encoding="utf-8")
    if target.suffix.lower() in (".yaml", ".yml"):
        import yaml

        raw = yaml.safe_load(text)
    else:
        raw = json.loads(text)
    if isinstance(raw, list):
        return Blueprint.from_records(raw)
    return Blueprint.model_validate(raw)
