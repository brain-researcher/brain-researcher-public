"""Typed cards for the Brain Researcher Society thin conductor layer.

These are fresh, self-contained Pydantic v2 contracts (NOT subclasses of the
existing ``ClaimV1`` / ``CommitmentRecordV1``) because the society layer needs a
different epistemic vocabulary than those carry:

* a 5-state editorial status (``ClaimStatusV1``) — see spec section 4,
* a structured ``ScopeBoundaryV1`` (population / modality / datasets / workflow),
* a *commit-before-observe* lock: a content hash computed and frozen on the
  ``CommitmentCardV1`` before any result exists (spec section 5).

See ``docs/BR_Society_v0.1_Spec_and_Blueprint.html``. Nothing here imports the
service tier, so this module is safe to live inside the ``autoresearch`` package.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


def _utc_now() -> str:
    """ISO-8601 UTC timestamp, matching ``autoresearch.state_contract._utc_now``."""
    return datetime.now(timezone.utc).isoformat()


def fingerprint(payload: Any) -> str:
    """SHA-256 over canonical JSON.

    Mirrors ``autoresearch.supervisor._fingerprint`` byte-for-byte
    (``sort_keys=True``, compact separators, ``default=str``) so society and
    supervisor fingerprints are directly comparable.
    """
    rendered = json.dumps(payload, sort_keys=True, default=str, separators=(",", ":"))
    return hashlib.sha256(rendered.encode("utf-8")).hexdigest()


NON_EVALUABLE_PROBE_PROVENANCES: frozenset[str] = frozenset(
    {
        "commission_abstained_inputs_present",
        "commission_unavailable_inputs_present",
    }
)


class ClaimStatusV1(str, Enum):
    """The unified editorial / epistemic status ladder.

    Five *evidential* states (spec section 4) express the community's current
    editorial status, NOT ground-truth (``supported_within_scope != true`` and
    ``rejected != false``). Two further states were added for ``neuroclaim_compile``:

    * ``conflicting`` — genuine support AND contradiction both present; an
      *evidential* verdict distinct from ``weakened`` (supported-but-undermined)
      and ``unresolved`` (insufficient evidence).
    * ``ill_typed`` — a *structural* verdict: the claim/plan is type-incoherent
      (e.g. an EEG dataset fed to an fMRI GLM), so no evidential verdict is even
      attempted. ``ill_typed`` MUST only be emitted by a deterministic typecheck
      (``verdict_basis == "structural"``), never by the evidence layer — the two
      honesty levels are never blurred.

    The society conductor (``synthesize_claim_card``) only ever emits the original
    five; the two new members are produced solely by ``neuroclaim_compile``.
    """

    supported_within_scope = "supported_within_scope"
    qualified = "qualified"
    weakened = "weakened"
    rejected = "rejected"
    unresolved = "unresolved"
    conflicting = "conflicting"
    ill_typed = "ill_typed"
    # A REFUSAL, not an evidential verdict: a required falsifier axis produced no verdict, so
    # the claim cannot be finalized / frozen / dispatched. Distinct from ``unresolved`` (an
    # evidential "insufficient evidence" on a claim that WAS adjudicated). Emitted only by the
    # conductor's required-verdict ordering gate (VB-1), never by the evidence layer.
    needs_diagnosis = "needs_diagnosis"


# Map a ``kg_verify_hypothesis`` verdict onto the unified *evidential* ladder.
# This is the single bridge between the KG verifier's vocabulary and the society
# ladder; it never returns ``ill_typed`` (a structural-only verdict).
_KG_VERDICT_TO_STATUS: dict[str, ClaimStatusV1] = {
    "supported": ClaimStatusV1.supported_within_scope,
    "conflicting": ClaimStatusV1.conflicting,
    "mixed": ClaimStatusV1.weakened,
    "uncertain": ClaimStatusV1.unresolved,
    "insufficient_evidence": ClaimStatusV1.unresolved,
}


def classify_kg_verdict(verdict: str) -> ClaimStatusV1:
    """Bridge a ``kg_verify_hypothesis`` verdict onto the unified evidential ladder.

    Unknown verdicts map to ``unresolved`` (never fabricate support). Never returns
    ``ill_typed``, which is reserved for the deterministic structural typecheck.
    """
    return _KG_VERDICT_TO_STATUS.get(
        str(verdict).strip().lower(), ClaimStatusV1.unresolved
    )


class ScopeBoundaryV1(BaseModel):
    """Dimensional scope a claim is asserted within (spec section 4)."""

    population: str | None = None
    modality: str | None = None
    datasets: list[str] = Field(default_factory=list)
    workflow_family: str | None = None


class ClaimSpecV1(BaseModel):
    """A human/PI-authored claim to verify in one episode (agent-facing input)."""

    schema_version: Literal["claim-spec-v1"] = "claim-spec-v1"
    claim_id: str
    claim_text: str
    # Optional link to the upstream HypothesisSpecV1 (society.hypotheses) this claim is derived
    # from; its reasoning_mode_ceiling bounds the claim's strength via compose_ceilings.
    hypothesis_id: str | None = None
    scope_boundary: ScopeBoundaryV1 = Field(default_factory=ScopeBoundaryV1)
    allowed_alternatives: list[str] = Field(default_factory=list)
    same_null_constraint: str | None = None
    success_criteria: str | None = None
    failure_criteria: str | None = None
    confirmatory: bool = True
    extra: dict[str, Any] = Field(default_factory=dict)


class FalsifierAxisSpec(BaseModel):
    """One required falsifier axis in a pre-registered battery (VB-1).

    ``fail_closed_policy`` separates the two honesty modes the institution turns on:
    ``missing_verdict_blocks`` — the axis MUST produce a verdict before finalization (a missing
    or infra-degenerate outcome refuses the claim); ``missing_data_blocks`` — same, and a
    data-abstain also refuses; ``missing_data_abstains`` — a data-abstain is tolerated (the axis
    still must have RUN). A present *negative* verdict never blocks here — it downgrades the
    claim via the existing ceiling logic. Missing ⇒ refuse; bad ⇒ grade down.
    """

    model_config = ConfigDict(frozen=True)
    axis_id: str
    gate_name: str
    required: bool = True
    threshold: dict[str, Any] = Field(default_factory=dict)
    data_requirements: dict[str, Any] = Field(default_factory=dict)
    fail_closed_policy: Literal[
        "missing_verdict_blocks", "missing_data_blocks", "missing_data_abstains"
    ] = "missing_verdict_blocks"
    cost_rank: int = 0


class FalsifierBatterySpec(BaseModel):
    """The required falsifier battery for a claim class, pre-registered and hash-locked (VB-1)."""

    model_config = ConfigDict(frozen=True)
    battery_id: str
    claim_signature: str
    required_axes: list[FalsifierAxisSpec] = Field(default_factory=list)
    cost_order: list[str] = Field(default_factory=list)
    version: str = "v1"


class EvidenceEngineRefV1(BaseModel):
    """Versioned evidence engine identity sealed with a commitment.

    ``adapter`` names the Brain Researcher integration surface separately from
    the upstream engine package.  All fields are part of the commitment hash
    whenever this optional reference is present.  It remains optional so
    historical ``commitment-card-v1`` records created before this field was
    introduced continue to verify byte-for-byte.
    """

    model_config = ConfigDict(frozen=True)
    name: str
    version: str
    adapter: str | None = None


class CommitmentCardV1(BaseModel):
    """Rules locked BEFORE the pipeline produces any result (spec section 5).

    Frozen after construction. The ``commitment_hash`` covers the lockable
    content (everything except the hash, the lock timestamp, and ``extra``),
    including the frozen falsifier ``rubric_refs``, optional ``evidence_engine``,
    AND the typed ``falsifier_battery`` — so any post-hoc change to the claim,
    scope, success criteria, attack rubric content hashes, engine identity, or
    the required-axis battery (axes / thresholds / cost order / data
    requirements / fail-closed policy) is detectable. A battery or engine
    identity placed in ``extra`` would NOT be hash-covered; it must use the
    typed field.
    """

    model_config = ConfigDict(frozen=True)

    schema_version: Literal["commitment-card-v1"] = "commitment-card-v1"
    commitment_id: str
    claim_id: str
    claim_text: str
    scope_boundary: ScopeBoundaryV1
    allowed_alternatives: list[str] = Field(default_factory=list)
    same_null_constraint: str | None = None
    success_criteria: str | None = None
    failure_criteria: str | None = None
    confirmatory: bool = True
    attack_strategies: list[str] = Field(default_factory=list)
    # strategy -> {"path": <frozen rubric file>, "hash": <sha256 of its text>}
    rubric_refs: dict[str, dict[str, str]] = Field(default_factory=dict)
    evidence_engine: EvidenceEngineRefV1 | None = None
    # The pre-registered required-verdict battery (typed, hash-covered). None = no required
    # battery for this claim class (the conductor then never refuses on coverage).
    falsifier_battery: FalsifierBatterySpec | None = None
    commitment_hash: str
    locked_at: str
    extra: dict[str, Any] = Field(default_factory=dict)

    def lockable_content(self) -> dict[str, Any]:
        """Return the stable content covered by ``commitment_hash``.

        ``locked_at`` records when sealing happened, not what was sealed, so it
        is deliberately excluded. ``extra`` is also explicitly non-contractual.
        Fields absent from a deserialized historical payload are omitted from
        its legacy hash shape. New cards created by ``lock_commitment`` set the
        typed fields explicitly, including ``None`` when no battery/engine is
        committed, so their presence is itself covered by the digest.
        """
        content = self.model_dump(exclude={"commitment_hash", "locked_at", "extra"})
        for later_v1_field in ("falsifier_battery", "evidence_engine"):
            if later_v1_field not in self.model_fields_set:
                content.pop(later_v1_field, None)
        return content

    def verify_hash(self) -> bool:
        """True iff the recorded hash still matches the lockable content."""
        return fingerprint(self.lockable_content()) == self.commitment_hash


class ClaimCardV1(BaseModel):
    """The final, bounded epistemic status of a claim for one episode (section 4)."""

    schema_version: Literal["claim-card-v1"] = "claim-card-v1"
    claim_id: str
    claim_text: str
    status: ClaimStatusV1
    scope_boundary: ScopeBoundaryV1
    commitment_card_ref: str
    commitment_hash: str
    evidence_bundle_refs: list[str] = Field(default_factory=list)
    survived_checks: list[str] = Field(default_factory=list)
    failed_checks: list[str] = Field(default_factory=list)
    # How hard the falsifiers actually tried — cheap survival is recorded, not hidden.
    falsification_budget_spent: dict[str, Any] = Field(default_factory=dict)
    # VB-2 survival-gated score of record: the pipeline magnitude IFF the result survived its
    # required falsifier battery, else None (withheld — a required axis refuted it, or the
    # battery was incomplete). None also when there was no score. The raw score stays in
    # ``pipeline_summary['last_score']``; details in ``pipeline_summary['survival_gate']``.
    survival_gated_score: float | None = None
    next_required_evidence: list[str] = Field(default_factory=list)
    pipeline_summary: dict[str, Any] = Field(default_factory=dict)
    # Per result-probe axis: how its verdict was obtained — "commissioned" (society
    # computed it from raw arrays), "supplied_inconsistent", "warrant", or "supplied".
    # Lets an auditor tell which gates fired on computed vs hand-fed evidence.
    probe_provenance: dict[str, str] = Field(default_factory=dict)
    # Per commissioned axis: plausibility verdict of the raw arrays it was computed from
    # ("clean"/"suspicious") — tamper-EVIDENCE on the inputs, not tamper-proof.
    probe_integrity: dict[str, str] = Field(default_factory=dict)
    status_not_ground_truth: bool = True
    generated_at: str = Field(default_factory=_utc_now)
    extra: dict[str, Any] = Field(default_factory=dict)


def lock_commitment(
    claim: ClaimSpecV1,
    attack_strategies: list[str],
    rubric_refs: dict[str, dict[str, str]],
    falsifier_battery: FalsifierBatterySpec | None = None,
    evidence_engine: EvidenceEngineRefV1 | None = None,
) -> CommitmentCardV1:
    """Build and freeze a ``CommitmentCardV1`` from a claim spec.

    The hash is computed over the lockable content of a draft card (the placeholder
    hash/timestamp are excluded from the hash), then a frozen copy carrying the real
    hash and lock time is returned. Calling ``verify_hash()`` on the result is True.
    The ``falsifier_battery`` (when given) is a typed, hash-covered field — so the required
    axes / thresholds / cost order cannot be quietly swapped after the result is seen.
    ``evidence_engine`` is also hash-covered when supplied. ``locked_at`` is a
    sealing audit timestamp and intentionally does not affect the digest.
    """
    draft = CommitmentCardV1(
        commitment_id=f"commit:{claim.claim_id}",
        claim_id=claim.claim_id,
        claim_text=claim.claim_text,
        scope_boundary=claim.scope_boundary,
        allowed_alternatives=list(claim.allowed_alternatives),
        same_null_constraint=claim.same_null_constraint,
        success_criteria=claim.success_criteria,
        failure_criteria=claim.failure_criteria,
        confirmatory=claim.confirmatory,
        attack_strategies=list(attack_strategies),
        rubric_refs=rubric_refs,
        evidence_engine=evidence_engine,
        falsifier_battery=falsifier_battery,
        commitment_hash="__pending__",
        locked_at="__pending__",
    )
    digest = fingerprint(draft.lockable_content())
    return draft.model_copy(update={"commitment_hash": digest, "locked_at": _utc_now()})
